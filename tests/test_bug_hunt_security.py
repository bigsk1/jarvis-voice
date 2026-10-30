"""Security-only hunting uses private state and verifies an actual trust boundary."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from bug_hunt import (  # noqa: E402
    DEFAULT_MODEL,
    DISMISSALS_RELATIVE_PATH,
    LEDGER_RELATIVE_PATH,
    MAX_FINDING_JSON_CHARS,
    MEMORY_RELATIVE_PATH,
    RESULTS_RELATIVE_PATH,
    SECURITY_MEMORY_RELATIVE_PATH,
    SECURITY_RESULTS_RELATIVE_PATH,
    BugHuntEngine,
)


def _write(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


class _FakeProvider:
    def __init__(self, responses):
        self.responses = [json.dumps(response) for response in responses]
        self.calls = []

    def chat_with_tools(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0), None, {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
        }, None


def _candidate():
    return {
        "action": "candidate",
        "coverage": {
            "area": "external input boundary",
            "paths_reviewed": ["lib/example.py"],
            "next_area": "callers",
        },
        "memory_update": "Reviewed the external input boundary sentinel.",
        "candidate": {
            "title": "Untrusted destination reaches an unchecked request",
            "severity": "high",
            "confidence": 0.94,
            "symptom": "External input crosses the intended request boundary.",
            "trigger_path": "An external document provides a destination.",
            "why_bug": "The checked entry point forwards the destination unchecked.",
            "evidence": [{
                "path": "lib/example.py",
                "line_start": 1,
                "line_end": 2,
                "explanation": "The source reaches the request without a guard.",
            }],
            "guards_checked": ["The caller does not validate the destination."],
            "reproduction_concept": "Supply a harmless test destination and inspect the request.",
            "suggested_regression_test": "Reject a test destination outside the allowed boundary.",
            "duplicate_check": "No matching current finding or fixed ledger entry.",
            "security": {
                "untrusted_input": "Destination supplied by external document content.",
                "entry_point": "lib/example.py:fetch",
                "trust_boundary": "External document content to an owner-side request.",
                "source_to_sink": ["document.destination", "fetch(destination)"],
                "impact": "An external actor controls an unintended request destination.",
                "preconditions": [],
                "why_outside_accepted_posture": (
                    "A malicious document can cross the boundary without an owner action."
                ),
            },
        },
    }


def _verification():
    return {
        "verdict": "confirmed",
        "confidence": 0.93,
        "reason": "The current source-to-sink path has no matching validation guard.",
        "evidence": [{
            "path": "lib/example.py",
            "line_start": 1,
            "line_end": 2,
            "explanation": "Independent review confirms the reachable unchecked request.",
        }],
        "missing_guard": "No destination validation is applied in the reachable path.",
        "duplicate_assessment": "No applicable duplicate or accepted current behavior.",
        "security_review": {
            "boundary_confirmed": True,
            "baseline_exceeded": True,
            "reason": "Untrusted external content exceeds the accepted single-owner posture.",
        },
    }


def _engine(tmp_path: Path, responses, **kwargs):
    _write(tmp_path, "lib/example.py", "def fetch(destination):\n    return request(destination)\n")
    provider = _FakeProvider(responses)
    engine = BugHuntEngine(
        tmp_path,
        provider=provider,
        tracked_files={"lib/example.py"},
        security_only=True,
        **kwargs,
    )
    return engine, provider


def _no_finding():
    return {
        "action": "no_finding",
        "coverage": {"area": "test", "paths_reviewed": [], "next_area": "next"},
        "memory_update": "Security coverage sentinel.",
        "candidate": None,
    }


def test_security_mode_selects_dedicated_files_before_initializing_state(tmp_path):
    originals = {
        MEMORY_RELATIVE_PATH: "# General memory\n\nDo not rewrite this legacy memory.\n",
        RESULTS_RELATIVE_PATH: '{"id":"old-code","title":"Ordinary finding"}\n',
        LEDGER_RELATIVE_PATH: "Fixed-bug history sentinel.\n",
        DISMISSALS_RELATIVE_PATH: "",
    }
    for relative, value in originals.items():
        _write(tmp_path, relative, value)

    engine, _provider = _engine(tmp_path, [_no_finding()])
    assert engine.hunt_mode == "security"
    assert engine.policy.memory_path == tmp_path / SECURITY_MEMORY_RELATIVE_PATH
    assert engine.policy.results_path == tmp_path / SECURITY_RESULTS_RELATIVE_PATH

    outcome = engine.run_iteration(1)

    assert outcome.action == "no_finding"
    assert "Security coverage sentinel." in engine.policy.memory_path.read_text()
    assert engine.policy.results_path.read_text() == ""
    for relative, original in originals.items():
        assert (tmp_path / relative).read_bytes() == original.encode()
    assert stat.S_IMODE(engine.policy.memory_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(engine.policy.results_path.stat().st_mode) == 0o600


def test_security_mode_does_not_create_general_state_files(tmp_path):
    engine, _provider = _engine(tmp_path, [])

    assert engine.policy.memory_path.exists()
    assert engine.policy.results_path.exists()
    for relative in (
        MEMORY_RELATIVE_PATH,
        RESULTS_RELATIVE_PATH,
        LEDGER_RELATIVE_PATH,
        DISMISSALS_RELATIVE_PATH,
    ):
        assert not (tmp_path / relative).exists()


def test_security_and_documentation_modes_are_mutually_exclusive_before_any_write(tmp_path):
    with pytest.raises(ValueError):
        BugHuntEngine(tmp_path, tracked_files=set(), docs_only=True, security_only=True)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("tracked_private", [
    SECURITY_MEMORY_RELATIVE_PATH, SECURITY_RESULTS_RELATIVE_PATH,
])
@pytest.mark.parametrize("already_exists", [False, True])
def test_security_mode_refuses_tracked_private_state_before_any_write(
    tmp_path, tracked_private, already_exists,
):
    if already_exists:
        _write(tmp_path, tracked_private, "Previously stored private state sentinel.\n")
    before = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*") if path.is_file()
    }

    with pytest.raises(ValueError, match="untracked"):
        BugHuntEngine(
            tmp_path,
            tracked_files={tracked_private},
            provider=_FakeProvider([]),
            security_only=True,
        )

    after = {
        str(path.relative_to(tmp_path)): path.read_bytes()
        for path in tmp_path.rglob("*") if path.is_file()
    }
    assert after == before


def test_read_memory_action_reads_selected_security_memory(tmp_path):
    _write(tmp_path, MEMORY_RELATIVE_PATH, "General memory must remain untouched.\n")
    _write(tmp_path, SECURITY_MEMORY_RELATIVE_PATH, "Security navigation sentinel.\n")
    engine, _provider = _engine(tmp_path, [])

    result = engine.tool.execute({"action": "read_memory"}, allow_memory_write=False)

    assert result["ok"] is True
    assert result["path"] == SECURITY_MEMORY_RELATIVE_PATH
    assert "Security navigation sentinel." in result["content"]
    assert "General memory must remain untouched." not in result["content"]


def test_confirmed_security_finding_retains_security_evidence_and_independent_review(tmp_path):
    candidate = _candidate()
    verification = _verification()
    engine, provider = _engine(tmp_path, [candidate, verification])

    outcome = engine.run_iteration(1)

    assert outcome.action == "confirmed"
    assert outcome.finding_written is True
    assert len(provider.calls) == 2
    finding = json.loads(engine.policy.results_path.read_text())
    assert finding["hunt_mode"] == "security"
    assert finding["security"] == candidate["candidate"]["security"]
    assert finding["verification"]["security_review"] == verification["security_review"]
    assert "security_review" not in finding
    assert finding["verification"]["verdict"] == "confirmed"
    assert finding["model"] == DEFAULT_MODEL == "glm-5.2:cloud"
    assert not (tmp_path / RESULTS_RELATIVE_PATH).exists()


@pytest.mark.parametrize("field", [
    "untrusted_input",
    "entry_point",
    "trust_boundary",
    "impact",
    "why_outside_accepted_posture",
])
@pytest.mark.parametrize("invalid", [None, "", "   ", {"not": "text"}])
def test_security_candidate_requires_explicit_nonempty_boundary_fields(tmp_path, field, invalid):
    candidate = _candidate()
    candidate["candidate"]["security"][field] = invalid
    engine, provider = _engine(tmp_path, [candidate])

    outcome = engine.run_iteration(1)

    assert outcome.action == "rejected"
    assert outcome.finding_written is False
    assert len(provider.calls) == 1
    assert engine.policy.results_path.read_text() == ""


@pytest.mark.parametrize("missing", ["security", "guards_checked"])
def test_security_candidate_without_security_context_or_checked_guards_is_rejected(tmp_path, missing):
    candidate = _candidate()
    candidate["candidate"].pop(missing)
    engine, provider = _engine(tmp_path, [candidate])

    outcome = engine.run_iteration(1)

    assert outcome.action == "rejected"
    assert len(provider.calls) == 1
    assert engine.policy.results_path.read_text() == ""


@pytest.mark.parametrize("guards", [None, [], "Caller validates input.", [" "]])
def test_security_candidate_requires_nonempty_checked_guards(tmp_path, guards):
    candidate = _candidate()
    candidate["candidate"]["guards_checked"] = guards
    engine, provider = _engine(tmp_path, [candidate])

    outcome = engine.run_iteration(1)

    assert outcome.action == "rejected"
    assert len(provider.calls) == 1
    assert engine.policy.results_path.read_text() == ""


@pytest.mark.parametrize("chain", [None, "source -> sink", [], ["source"], ["source", " "]])
def test_security_candidate_requires_a_source_to_sink_chain(tmp_path, chain):
    candidate = _candidate()
    candidate["candidate"]["security"]["source_to_sink"] = chain
    engine, provider = _engine(tmp_path, [candidate])

    outcome = engine.run_iteration(1)

    assert outcome.action == "rejected"
    assert len(provider.calls) == 1
    assert engine.policy.results_path.read_text() == ""


@pytest.mark.parametrize("review", [
    None,
    {},
    {"boundary_confirmed": False, "baseline_exceeded": True, "reason": "Boundary is absent."},
    {"boundary_confirmed": True, "baseline_exceeded": False, "reason": "Within accepted scope."},
    {"boundary_confirmed": "true", "baseline_exceeded": True, "reason": "Not a boolean."},
    {"boundary_confirmed": 1, "baseline_exceeded": True, "reason": "Not a boolean."},
    {"boundary_confirmed": True, "baseline_exceeded": True, "reason": " "},
])
def test_security_verifier_must_confirm_boundary_and_exceeded_accepted_posture(tmp_path, review):
    verification = _verification()
    verification["security_review"] = review
    engine, provider = _engine(tmp_path, [_candidate(), verification])

    outcome = engine.run_iteration(1)

    assert outcome.action == "rejected"
    assert outcome.finding_written is False
    assert len(provider.calls) == 2
    assert engine.policy.results_path.read_text() == ""


def test_security_still_requires_independent_current_line_evidence(tmp_path):
    verification = _verification()
    verification["evidence"][0]["line_end"] = 999
    engine, _provider = _engine(tmp_path, [_candidate(), verification])

    outcome = engine.run_iteration(1)

    assert outcome.action == "rejected"
    assert "evidence" in outcome.message.lower()
    assert engine.policy.results_path.read_text() == ""


@pytest.mark.parametrize("agent", ["investigator", "verifier"])
def test_security_finding_requires_current_source_evidence_from_both_agents(tmp_path, agent):
    _write(tmp_path, "lib/example.py", "def fetch(destination):\n    return request(destination)\n")
    _write(tmp_path, "README.md", "# Accepted security posture\nDocumentation is navigation only.\n")
    candidate = _candidate()
    verification = _verification()
    target = candidate["candidate"] if agent == "investigator" else verification
    target["evidence"] = [{
        "path": "README.md",
        "line_start": 1,
        "line_end": 2,
        "explanation": "A policy description cannot establish current executable behavior.",
    }]
    provider = _FakeProvider([candidate, verification])
    engine = BugHuntEngine(
        tmp_path,
        provider=provider,
        tracked_files={"lib/example.py", "README.md"},
        security_only=True,
    )

    outcome = engine.run_iteration(1)

    assert outcome.action == "rejected"
    assert "source" in outcome.message.lower()
    assert outcome.finding_written is False
    assert len(provider.calls) == (1 if agent == "investigator" else 2)
    assert engine.policy.results_path.read_text() == ""


def test_security_finding_bounds_boundary_text_chains_and_verifier_review(tmp_path):
    candidate = _candidate()
    for field in (
        "untrusted_input", "entry_point", "trust_boundary", "impact", "why_outside_accepted_posture",
    ):
        candidate["candidate"]["security"][field] = field + "x" * 5000
    candidate["candidate"]["security"]["source_to_sink"] = ["s" * 2000] * 12
    candidate["candidate"]["security"]["preconditions"] = ["p" * 2000] * 12
    candidate["candidate"]["security"]["unknown_model_field"] = "must not be persisted"
    verification = _verification()
    verification["security_review"]["reason"] = "r" * 5000
    verification["security_review"]["unknown_model_field"] = "must not be persisted"
    engine, _provider = _engine(tmp_path, [candidate, verification])

    assert engine.run_iteration(1).action == "confirmed"

    serialized = engine.policy.results_path.read_text()
    finding = json.loads(serialized)
    security = finding["security"]
    for field in (
        "untrusted_input", "entry_point", "trust_boundary", "impact", "why_outside_accepted_posture",
    ):
        assert len(security[field]) == 2000
    for field in ("source_to_sink", "preconditions"):
        assert len(security[field]) == 8
        assert all(len(step) == 1000 for step in security[field])
    assert len(finding["verification"]["security_review"]["reason"]) == 2000
    assert "unknown_model_field" not in serialized
    assert len(serialized.rstrip()) <= MAX_FINDING_JSON_CHARS


def test_both_security_agents_receive_accepted_posture_and_only_read_only_repo_tool(tmp_path):
    engine, provider = _engine(tmp_path, [_candidate(), _verification()])

    assert engine.run_iteration(1).action == "confirmed"

    for call in provider.calls:
        prompt = call["system_prompt"].lower()
        assert "self-hosted" in prompt
        assert any(term in prompt for term in ("single-owner", "single-user", "single owner"))
        assert "untrusted" in prompt
        assert "optional" in prompt
        assert "cve" in prompt or "dependency" in prompt
        assert "network" in prompt
        assert [tool["name"] for tool in call["tools"]] == ["bug_hunt_repo"]
        actions = call["tools"][0]["input_schema"]["properties"]["action"]["enum"]
        assert set(actions) == {"list_files", "search", "read_lines", "read_memory"}
    denied = engine.tool.execute(
        {"action": "update_memory", "content": "Model cannot replace state through a tool."},
        allow_memory_write=False,
    )
    assert denied["ok"] is False


def test_security_duplicate_context_includes_code_findings_but_excludes_docs_only(tmp_path):
    ordinary = [
        {"id": "code-current", "hunt_mode": "code", "title": "Code duplicate sentinel"},
        {"id": "code-legacy", "title": "Legacy code duplicate sentinel"},
        {"id": "docs-current", "hunt_mode": "docs_only", "title": "Docs-only sentinel"},
    ]
    _write(tmp_path, RESULTS_RELATIVE_PATH, "".join(json.dumps(row) + "\n" for row in ordinary))
    _write(tmp_path, SECURITY_RESULTS_RELATIVE_PATH, json.dumps({
        "id": "security-current", "hunt_mode": "security", "title": "Security duplicate sentinel",
    }) + "\n")
    engine, provider = _engine(tmp_path, [_candidate(), _verification()])
    original = (tmp_path / RESULTS_RELATIVE_PATH).read_bytes()

    assert engine.run_iteration(1).action == "confirmed"

    for call in provider.calls:
        task = call["messages"][0]["content"]
        assert "Security duplicate sentinel" in task
        assert "Code duplicate sentinel" in task
        assert "Legacy code duplicate sentinel" in task
        assert "Docs-only sentinel" not in task
    assert (tmp_path / RESULTS_RELATIVE_PATH).read_bytes() == original


def test_security_dismissals_include_code_security_all_but_exclude_documentation(tmp_path):
    dismissals = [{
        "id": f"dismiss-{mode}",
        "hunt_mode": mode,
        "disposition": "accepted_current_behavior",
        "title": f"Accepted {mode} sentinel",
        "root_cause": "An intentional trust boundary.",
        "reason": "Accepted within this scope.",
        "reopen_if": ["The boundary changes."],
    } for mode in ("code", "security", "all", "docs_only")]
    _write(tmp_path, DISMISSALS_RELATIVE_PATH, "".join(json.dumps(row) + "\n" for row in dismissals))
    engine, provider = _engine(tmp_path, [_candidate(), _verification()])
    original = engine.policy.dismissals_path.read_bytes()

    assert engine.run_iteration(1).action == "confirmed"

    for call in provider.calls:
        task = call["messages"][0]["content"]
        for mode in ("code", "security", "all"):
            assert f"Accepted {mode} sentinel" in task
        assert "Accepted docs_only sentinel" not in task
    assert engine.policy.dismissals_path.read_bytes() == original


def test_security_hunt_keeps_private_config_and_untracked_source_unreadable(tmp_path):
    private_files = {
        "config/ntfy.json", "config/oauth_tokens.json", "config/cloud.env",
        "docs/personal/unrelated-private.md",
    }
    untracked = {"lib/untracked.py", "skills/personal/private.py"}
    for relative in private_files | untracked:
        _write(tmp_path, relative, "Must stay private sentinel.\n")
    engine = BugHuntEngine(
        tmp_path,
        provider=_FakeProvider([]),
        tracked_files=private_files,
        security_only=True,
    )

    for relative in private_files | untracked:
        result = engine.tool.execute({"action": "read_lines", "path": relative}, allow_memory_write=False)
        assert result["ok"] is False
    listed = engine.tool.execute({"action": "list_files"}, allow_memory_write=False)
    assert SECURITY_MEMORY_RELATIVE_PATH in listed["files"]
    assert SECURITY_RESULTS_RELATIVE_PATH in listed["files"]


@pytest.mark.parametrize("model", [None, "deepseek-v4.1-flash:1017"])
def test_security_hunt_preserves_pinned_model_and_explicit_override(tmp_path, model):
    engine, _provider = _engine(tmp_path, [], model=model)
    selected = model or "glm-5.2:cloud"
    created = object()

    with (
        patch("config_loader.get_config_value", return_value="http://ollama.test"),
        patch("ollama_utils.get_effective_ollama_model", return_value=selected) as resolve_model,
        patch("llm_provider.create_provider", return_value=created) as create_provider,
    ):
        assert engine._create_provider() is created

    resolve_model.assert_called_once_with("cloud", model_override=selected)
    create_provider.assert_called_once_with("ollama", base_url="http://ollama.test", model=selected)


def test_general_hunt_cannot_read_security_state_even_if_tracked(tmp_path):
    for relative in (SECURITY_MEMORY_RELATIVE_PATH, SECURITY_RESULTS_RELATIVE_PATH):
        _write(tmp_path, relative, "Private security state sentinel.\n")
    engine = BugHuntEngine(
        tmp_path,
        provider=_FakeProvider([]),
        tracked_files={SECURITY_MEMORY_RELATIVE_PATH, SECURITY_RESULTS_RELATIVE_PATH},
    )

    for relative in (SECURITY_MEMORY_RELATIVE_PATH, SECURITY_RESULTS_RELATIVE_PATH):
        result = engine.tool.execute({"action": "read_lines", "path": relative}, allow_memory_write=False)
        assert result["ok"] is False


def test_security_cli_help_and_conflicting_flags_do_not_initialize_state(tmp_path):
    launcher = tmp_path / "bin/jarvis-bug-hunt"
    launcher.parent.mkdir()
    shutil.copy2(PROJECT_ROOT / "bin/jarvis-bug-hunt", launcher)
    (tmp_path / "lib").mkdir()
    shutil.copy2(PROJECT_ROOT / "lib/bug_hunt.py", tmp_path / "lib/bug_hunt.py")

    help_result = subprocess.run(
        [sys.executable, str(launcher), "--help"], capture_output=True, text=True, check=False,
    )
    conflict = subprocess.run(
        [sys.executable, str(launcher), "--security-only", "--docs-only"],
        capture_output=True, text=True, check=False,
    )

    assert help_result.returncode == 0
    assert "--security-only" in help_result.stdout
    assert conflict.returncode == 2
    assert "not allowed with argument" in conflict.stderr
    assert not (tmp_path / "docs").exists()


def test_security_cli_whitelist_uses_private_security_state_without_provider_calls(tmp_path):
    launcher = tmp_path / "bin/jarvis-bug-hunt"
    launcher.parent.mkdir()
    shutil.copy2(PROJECT_ROOT / "bin/jarvis-bug-hunt", launcher)
    (tmp_path / "lib").mkdir()
    shutil.copy2(PROJECT_ROOT / "lib/bug_hunt.py", tmp_path / "lib/bug_hunt.py")
    _write(tmp_path, "config/ntfy.json", '{"secret":"not-a-real-secret"}\n')
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "add", "bin/jarvis-bug-hunt", "lib/bug_hunt.py", "config/ntfy.json"],
        cwd=tmp_path, check=True, capture_output=True,
    )

    result = subprocess.run(
        [sys.executable, str(launcher), "--security-only", "--show-whitelist"],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    readable = set(result.stdout.splitlines())
    assert SECURITY_MEMORY_RELATIVE_PATH in readable
    assert SECURITY_RESULTS_RELATIVE_PATH in readable
    assert "lib/bug_hunt.py" in readable
    assert "config/ntfy.json" not in readable
    assert MEMORY_RELATIVE_PATH not in readable
    assert RESULTS_RELATIVE_PATH not in readable
    assert not (tmp_path / MEMORY_RELATIVE_PATH).exists()
    assert not (tmp_path / RESULTS_RELATIVE_PATH).exists()


def test_security_private_state_paths_are_gitignored(tmp_path):
    shutil.copy2(PROJECT_ROOT / ".gitignore", tmp_path / ".gitignore")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", SECURITY_MEMORY_RELATIVE_PATH, SECURITY_RESULTS_RELATIVE_PATH],
        cwd=tmp_path, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0
    assert set(result.stdout.splitlines()) == {
        SECURITY_MEMORY_RELATIVE_PATH, SECURITY_RESULTS_RELATIVE_PATH,
    }
