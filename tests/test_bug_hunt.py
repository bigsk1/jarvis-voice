"""Safety and loop regression coverage for the isolated bug hunter."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from bug_hunt import (  # noqa: E402
    DEFAULT_MODEL,
    MAX_FINDING_JSON_CHARS,
    MAX_MODE_MEMORY_CHARS,
    MEMORY_RELATIVE_PATH,
    RESULTS_RELATIVE_PATH,
    BugHuntEngine,
    BugHuntRepoTool,
    IterationOutcome,
    RepositoryPolicy,
    format_progress_line,
    parse_deadline,
)


def _write(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_tracked_allowlist_is_fail_closed(tmp_path):
    tracked = {
        ".gitignore",
        "lib/good.py",
        "config/cloud.env",
        "config/cloud.env.example",
        "config/contacts.json",
        "data/private.txt",
        "data/workflows/deep_research.json",
        "docs/README.md",
        "docs/archive/old.md",
        "docs/personal/private.md",
        "jarvis-intel/user_profile.md",
    }
    for path in tracked:
        _write(tmp_path, path, "safe test content\n")

    policy = RepositoryPolicy(tmp_path, tracked_files=tracked)

    assert ".gitignore" in policy.readable_files
    assert "lib/good.py" in policy.readable_files
    assert "config/cloud.env.example" in policy.readable_files
    assert "data/workflows/deep_research.json" in policy.readable_files
    assert "docs/README.md" in policy.readable_files
    assert "config/cloud.env" not in policy.readable_files
    assert "config/contacts.json" not in policy.readable_files
    assert "data/private.txt" not in policy.readable_files
    assert "docs/archive/old.md" not in policy.readable_files
    assert "docs/personal/private.md" not in policy.readable_files
    assert "jarvis-intel/user_profile.md" not in policy.readable_files

    with pytest.raises(PermissionError):
        policy.resolve_read("config/cloud.env")
    with pytest.raises(ValueError):
        policy.resolve_read("../outside.txt")


def test_symlink_reads_are_rejected_even_when_tracked(tmp_path):
    outside = tmp_path.parent / "outside-bug-hunt.txt"
    outside.write_text("secret\n", encoding="utf-8")
    link = tmp_path / "lib" / "link.py"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)

    policy = RepositoryPolicy(tmp_path, tracked_files={"lib/link.py"})

    with pytest.raises(PermissionError, match="Symlink"):
        policy.resolve_read("lib/link.py")


def test_single_tool_lists_searches_and_reads_only_whitelisted_files(tmp_path):
    _write(tmp_path, "lib/example.py", "alpha\nNeedle here\nomega\n")
    _write(tmp_path, "tests/test_example.py", "Needle in test\n")
    _write(tmp_path, "untracked.txt", "Needle must stay hidden\n")
    policy = RepositoryPolicy(
        tmp_path,
        tracked_files={"lib/example.py", "tests/test_example.py"},
    )
    policy.ensure_state_files()
    tool = BugHuntRepoTool(policy)

    listing = tool.execute(
        {"action": "list_files", "path": "lib", "glob": "*.py"},
        allow_memory_write=False,
    )
    assert listing == {"ok": True, "files": ["lib/example.py"], "limit": 100}

    search = tool.execute(
        {"action": "search", "query": "needle", "case_sensitive": False},
        allow_memory_write=False,
    )
    assert {(item["path"], item["line"]) for item in search["matches"]} == {
        ("lib/example.py", 2),
        ("tests/test_example.py", 1),
    }

    read = tool.execute(
        {"action": "read_lines", "path": "lib/example.py", "start_line": 2, "end_line": 3},
        allow_memory_write=False,
    )
    assert read["content"] == "2: Needle here\n3: omega"
    denied = tool.execute(
        {"action": "read_lines", "path": "untracked.txt"},
        allow_memory_write=False,
    )
    assert denied["ok"] is False

    traversal = tool.execute(
        {"action": "list_files", "path": "../lib"},
        allow_memory_write=False,
    )
    assert traversal["ok"] is False


def test_only_memory_action_can_write_and_verifier_cannot_use_it(tmp_path):
    policy = RepositoryPolicy(tmp_path, tracked_files=set())
    policy.ensure_state_files()
    tool = BugHuntRepoTool(policy)

    denied = tool.execute(
        {"action": "update_memory", "content": "# denied"},
        allow_memory_write=False,
    )
    assert denied["ok"] is False

    written = tool.execute(
        {"action": "update_memory", "content": "# compact memory", "mode": "replace"},
        allow_memory_write=True,
    )
    assert written["ok"] is True
    assert (tmp_path / MEMORY_RELATIVE_PATH).read_text() == "# compact memory\n"

    unexpected = sorted(
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob("*")
        if path.is_file()
    )
    assert unexpected == sorted([MEMORY_RELATIVE_PATH, RESULTS_RELATIVE_PATH])


def test_finding_append_is_jsonl_and_deduplicated(tmp_path):
    policy = RepositoryPolicy(tmp_path, tracked_files=set())
    finding = {
        "title": "Current path loses state",
        "severity": "medium",
        "evidence": [{"path": "lib/example.py", "line_start": 1, "line_end": 2}],
    }

    finding_id = policy.append_finding(finding)
    duplicate_id = policy.append_finding(finding)

    assert finding_id and finding_id.startswith("bh_")
    assert duplicate_id is None
    rows = (tmp_path / RESULTS_RELATIVE_PATH).read_text().splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["title"] == finding["title"]


def test_finding_append_rejects_runaway_serialized_record(tmp_path):
    policy = RepositoryPolicy(tmp_path, tracked_files=set())

    with pytest.raises(ValueError, match="Finding exceeds"):
        policy.append_finding({
            "title": "oversized",
            "evidence": [],
            "runaway": "x" * (MAX_FINDING_JSON_CHARS + 1),
        })


def test_git_checkout_requirement_has_clear_error(tmp_path):
    with patch("bug_hunt.subprocess.run", side_effect=subprocess.CalledProcessError(128, "git")):
        with pytest.raises(RuntimeError, match="requires a Git checkout"):
            RepositoryPolicy(tmp_path)


class _FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        return response, None, {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }, None


class _TextToolProvider(_FakeProvider):
    """Simulate cloud models that emit tool arguments as plain JSON text."""


def _candidate_payload():
    return {
        "action": "candidate",
        "coverage": {
            "area": "example",
            "paths_reviewed": ["lib/example.py"],
            "next_area": "tests",
        },
        "memory_update": "# Bug Hunt Memory\n\nReviewed example path.",
        "candidate": {
            "title": "Example state is dropped",
            "severity": "medium",
            "confidence": 0.92,
            "symptom": "A caller receives stale state.",
            "trigger_path": "Call example() with a missing value.",
            "why_bug": "The fallback discards the current state.",
            "evidence": [{
                "path": "lib/example.py",
                "line_start": 1,
                "line_end": 2,
                "explanation": "The state is replaced before return.",
            }],
            "guards_checked": ["No caller restores it."],
            "reproduction_concept": "Call twice and compare state.",
            "suggested_regression_test": "Assert state survives the fallback.",
            "duplicate_check": "Not present in the historical ledger.",
        },
    }


def _verifier_payload(verdict="confirmed", confidence=0.91):
    return {
        "verdict": verdict,
        "confidence": confidence,
        "reason": "The current path is reachable and unguarded.",
        "evidence": [{
            "path": "lib/example.py",
            "line_start": 1,
            "line_end": 2,
            "explanation": "Independent check confirms the overwrite.",
        }],
        "missing_guard": "No state-preservation branch.",
        "duplicate_assessment": "Distinct from existing findings.",
    }


def test_engine_records_only_independently_confirmed_candidates(tmp_path):
    _write(tmp_path, "lib/example.py", "state = current\nstate = fallback\nreturn state\n")
    _write(tmp_path, "docs/personal/live-usage-bug-ledger.txt", "Known fixed bugs\n")
    provider = _FakeProvider([
        json.dumps(_candidate_payload()),
        json.dumps(_verifier_payload()),
    ])
    engine = BugHuntEngine(
        tmp_path,
        provider=provider,
        tracked_files={"lib/example.py"},
    )

    outcome = engine.run_iteration(1)

    assert outcome.action == "confirmed"
    assert outcome.finding_written is True
    assert outcome.severity == "medium"
    finding = json.loads((tmp_path / RESULTS_RELATIVE_PATH).read_text().strip())
    assert finding["title"] == "Example state is dropped"
    assert finding["verification"]["verdict"] == "confirmed"
    assert finding["model"] == DEFAULT_MODEL
    assert engine.total_usage["total_tokens"] == 30
    memory = (tmp_path / MEMORY_RELATIVE_PATH).read_text()
    assert "Status: confirmed" in memory
    assert outcome.finding_id in memory


def test_progress_line_shows_severity_only_for_confirmed_findings():
    confirmed = format_progress_line(
        42,
        IterationOutcome(
            action="confirmed",
            finding_written=True,
            severity="high",
            message="Scheduled task can remain locked",
        ),
        {"total_tokens": 1234},
        timestamp="12:34:56",
    )
    rejected = format_progress_line(
        43,
        IterationOutcome(action="rejected", message="Verifier rejected candidate"),
        {"total_tokens": 1300},
        timestamp="12:35:10",
    )

    assert confirmed == (
        "[12:34:56] iteration 42: confirmed [high] - "
        "Scheduled task can remain locked (tokens~1234)"
    )
    assert rejected == (
        "[12:35:10] iteration 43: rejected - "
        "Verifier rejected candidate (tokens~1300)"
    )


def test_engine_executes_plain_json_tool_action_from_cloud_model(tmp_path):
    _write(tmp_path, "lib/example.py", "needle\n")
    provider = _TextToolProvider([
        json.dumps({"action": "read_lines", "path": "lib/example.py"}),
        json.dumps({
            "action": "no_finding",
            "coverage": {
                "area": "example",
                "paths_reviewed": ["lib/example.py"],
                "next_area": "tests",
            },
            "memory_update": "# Bug Hunt Memory\n\nNo issue in example.",
            "candidate": None,
        }),
    ])
    engine = BugHuntEngine(
        tmp_path,
        provider=provider,
        tracked_files={"lib/example.py"},
    )

    outcome = engine.run_iteration(1)

    assert outcome.action == "no_finding"
    assert len(provider.calls) == 2
    first_system_prompt = provider.calls[0]["system_prompt"]
    assert "non-authoritative navigation aids" in first_system_prompt
    assert "trusted single-user application" in first_system_prompt
    assert "Reject semantic duplicates" in first_system_prompt
    second_messages = provider.calls[1]["messages"]
    assert "1: needle" in second_messages[-1]["content"]


def test_engine_forces_final_json_after_tool_budget_is_exhausted(tmp_path):
    _write(tmp_path, "lib/example.py", "needle\n")
    provider = _TextToolProvider([
        json.dumps({"action": "read_lines", "path": "lib/example.py"}),
        json.dumps({
            "action": "no_finding",
            "coverage": {
                "area": "example",
                "paths_reviewed": ["lib/example.py"],
                "next_area": "tests",
            },
            "memory_update": "# Bug Hunt Memory\n\nNo issue found.",
            "candidate": None,
        }),
    ])
    engine = BugHuntEngine(
        tmp_path,
        provider=provider,
        tracked_files={"lib/example.py"},
        max_tool_turns=1,
    )

    outcome = engine.run_iteration(1)

    assert outcome.action == "no_finding"
    assert provider.calls[1]["tools"] == []
    assert "tool budget is exhausted" in provider.calls[1]["messages"][-1]["content"]


def test_engine_does_not_record_rejected_candidate(tmp_path):
    _write(tmp_path, "lib/example.py", "state = current\nstate = fallback\n")
    provider = _FakeProvider([
        json.dumps(_candidate_payload()),
        json.dumps(_verifier_payload("rejected", 0.95)),
    ])
    engine = BugHuntEngine(
        tmp_path,
        provider=provider,
        tracked_files={"lib/example.py"},
    )

    outcome = engine.run_iteration(1)

    assert outcome.action == "rejected"
    assert outcome.finding_written is False
    assert (tmp_path / RESULTS_RELATIVE_PATH).read_text() == ""
    memory = (tmp_path / MEMORY_RELATIVE_PATH).read_text()
    assert "Status: rejected" in memory
    assert "Verifier verdict=rejected" in memory


def test_docs_only_rejects_candidate_without_documentation_evidence(tmp_path):
    _write(tmp_path, "lib/example.py", "state = current\nstate = fallback\n")
    provider = _FakeProvider([json.dumps(_candidate_payload())])
    engine = BugHuntEngine(
        tmp_path,
        provider=provider,
        tracked_files={"lib/example.py"},
        docs_only=True,
    )

    outcome = engine.run_iteration(1)

    assert outcome.action == "rejected"
    assert "does not cite active documentation" in outcome.message
    assert len(provider.calls) == 1
    assert (tmp_path / RESULTS_RELATIVE_PATH).read_text() == ""


def test_docs_only_records_verified_documentation_drift(tmp_path):
    _write(tmp_path, "docs/README.md", "Run ./bin/old-command\n")
    candidate = _candidate_payload()
    candidate["candidate"]["title"] = "Documented command no longer exists"
    candidate["candidate"]["evidence"] = [{
        "path": "docs/README.md",
        "line_start": 1,
        "line_end": 1,
        "explanation": "The active guide names the removed command.",
    }]
    verifier = _verifier_payload()
    verifier["evidence"] = [{
        "path": "docs/README.md",
        "line_start": 1,
        "line_end": 1,
        "explanation": "The stale command is present in active documentation.",
    }]
    provider = _FakeProvider([json.dumps(candidate), json.dumps(verifier)])
    engine = BugHuntEngine(
        tmp_path,
        provider=provider,
        tracked_files={"docs/README.md"},
        docs_only=True,
    )

    outcome = engine.run_iteration(1)

    assert outcome.action == "confirmed"
    finding = json.loads((tmp_path / RESULTS_RELATIVE_PATH).read_text())
    assert finding["hunt_mode"] == "docs_only"


def test_code_and_docs_modes_preserve_separate_memory_sections(tmp_path):
    _write(tmp_path, "lib/example.py", "value = 1\n")
    code_payload = {
        "action": "no_finding",
        "coverage": {"area": "code", "paths_reviewed": [], "next_area": "next"},
        "memory_update": "Reviewed code sentinel.",
        "candidate": None,
    }
    docs_payload = {
        "action": "no_finding",
        "coverage": {"area": "docs", "paths_reviewed": [], "next_area": "next"},
        "memory_update": "Reviewed docs sentinel.",
        "candidate": None,
    }
    BugHuntEngine(
        tmp_path,
        provider=_FakeProvider([json.dumps(code_payload)]),
        tracked_files={"lib/example.py"},
    ).run_iteration(1)
    BugHuntEngine(
        tmp_path,
        provider=_FakeProvider([json.dumps(docs_payload)]),
        tracked_files={"lib/example.py"},
        docs_only=True,
    ).run_iteration(1)

    memory = (tmp_path / MEMORY_RELATIVE_PATH).read_text()
    assert "Reviewed code sentinel." in memory
    assert "Reviewed docs sentinel." in memory
    assert memory.index("Reviewed code sentinel.") < memory.index("Reviewed docs sentinel.")


def test_recorded_findings_summary_is_mode_scoped_and_keeps_old_entries(tmp_path):
    policy = RepositoryPolicy(tmp_path, tracked_files=set())
    policy.ensure_state_files()
    records = [
        {
            "id": f"code-{index}",
            "hunt_mode": "code",
            "title": f"Code finding {index}",
            "severity": "medium",
            "evidence": [{"path": "lib/example.py"}],
        }
        for index in range(30)
    ]
    records.append({
        "id": "docs-1",
        "hunt_mode": "docs_only",
        "title": "Documentation finding",
        "severity": "low",
        "evidence": [{"path": "docs/README.md"}],
    })
    (tmp_path / RESULTS_RELATIVE_PATH).write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    code_summary = BugHuntEngine(
        tmp_path,
        provider=_FakeProvider([]),
        tracked_files=set(),
    )._recent_findings_summary()
    docs_summary = BugHuntEngine(
        tmp_path,
        provider=_FakeProvider([]),
        tracked_files=set(),
        docs_only=True,
    )._recent_findings_summary()

    assert "code-0 | Code finding 0" in code_summary
    assert "code-29 | Code finding 29" in code_summary
    assert "Documentation finding" not in code_summary
    assert "docs-1 | Documentation finding" in docs_summary
    assert "Code finding" not in docs_summary


def test_memory_drops_model_claimed_findings_and_preserves_tail_when_compacted(tmp_path):
    policy = RepositoryPolicy(tmp_path, tracked_files=set())
    policy.ensure_state_files()
    oversized = (
        "## Areas Reviewed\n" + "coverage line\n" * 1000
        + "\n## Confirmed Candidates (filed)\n- unsupported result claim\n"
        + "\n## Next Paths\n- preserve this tail sentinel\n"
    )
    policy.write_memory(
        f"# Bug Hunt Memory\n\n## Code Correctness Mode\n\n{oversized}\n\n"
        "## Documentation-Only Mode\n\nNo docs reviewed.\n"
    )

    BugHuntEngine(
        tmp_path,
        provider=_FakeProvider([]),
        tracked_files=set(),
    )

    memory = (tmp_path / MEMORY_RELATIVE_PATH).read_text(encoding="utf-8")
    code, _docs = BugHuntEngine._split_memory_sections(memory)
    assert "unsupported result claim" not in code
    assert "preserve this tail sentinel" in code
    assert "older memory compacted" in code
    assert len(code) <= MAX_MODE_MEMORY_CHARS


def test_recorded_finding_text_is_bounded(tmp_path):
    _write(tmp_path, "lib/example.py", "state = current\nstate = fallback\n")
    candidate = _candidate_payload()
    candidate["candidate"]["title"] = "t" * 1000
    candidate["candidate"]["symptom"] = "s" * 10_000
    candidate["candidate"]["why_bug"] = "w" * 10_000
    candidate["candidate"]["guards_checked"] = ["g" * 5000] * 40
    verifier = _verifier_payload()
    verifier["reason"] = "r" * 10_000
    provider = _FakeProvider([json.dumps(candidate), json.dumps(verifier)])
    engine = BugHuntEngine(
        tmp_path,
        provider=provider,
        tracked_files={"lib/example.py"},
    )

    outcome = engine.run_iteration(1)

    assert outcome.action == "confirmed"
    finding = json.loads((tmp_path / RESULTS_RELATIVE_PATH).read_text())
    assert len(finding["title"]) == 300
    assert len(finding["symptom"]) == 4000
    assert len(finding["why_bug"]) == 5000
    assert len(finding["guards_checked"]) == 20
    assert len(finding["guards_checked"][0]) == 1000
    assert len(finding["verification"]["reason"]) == 5000


def test_parse_deadline_rolls_past_local_time_to_tomorrow():
    now = datetime(2026, 7, 5, 20, 30)

    assert parse_deadline("21:00", now) == datetime(2026, 7, 5, 21, 0)
    assert parse_deadline("06:00", now) == datetime(2026, 7, 6, 6, 0)
    with pytest.raises(ValueError):
        parse_deadline("25:00", now)
