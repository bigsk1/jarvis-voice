"""Screen executor results once before their operational log is persisted."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from config_loader import config_scope
from tool_logger import ToolLogger

import orchestrator.executor as executor_module
from lib import prompt_guard_observer as observer
from lib.prompt_guard import PromptGuardResult
from orchestrator.executor import ToolExecutor

PRIVATE = "UNTRUSTED_PRIVATE_INJECTION"
INCIDENT = "pg-" + "a" * 32
SOURCE_RESULT = {
    "ok": True, "completion": "completed", "speech": PRIVATE + " title",
    "error": PRIVATE + " error", "data": {"content": PRIVATE + " body", "filename": PRIVATE},
}


@pytest.fixture
def harness(tmp_path, monkeypatch):
    logger = ToolLogger(tmp_path / "tool-logs")
    monkeypatch.setattr(executor_module, "get_logger", lambda _mode: logger)
    monkeypatch.setattr(executor_module, "export_config_environment", lambda _mode: {})
    script = tmp_path / "example.py"
    script.write_text("# Process execution is mocked in these tests.\n")
    schema = SimpleNamespace(
        script_path=script, requires_confirmation=lambda: False, background_required=False,
        proxy_policy="inherit", child_environment_names=None,
    )
    calls = []

    class MCPClient:
        def call_tool(self, name, args):
            calls.append(("mcp", name, args))
            return dict(SOURCE_RESULT)

        def get_proxy_log_metadata(self):
            return {"policy": "prefer", "used": True, "slot": "primary"}

    registry = SimpleNamespace(
        get_tool=lambda _name: schema,
        is_mcp_tool=lambda name: name.startswith("mcp_"),
        get_mcp_info=lambda _name: ("fetch", "fetch"),
        mcp_clients={"fetch": MCPClient()},
    )
    executor = ToolExecutor(mode="cloud", registry=registry, load_runtime_config=False)
    executor.skills_dir = tmp_path
    executor.project_root = tmp_path

    monkeypatch.syspath_prepend(str(Path(executor_module.__file__).parent))
    import tool_process

    def run(*_args, **kwargs):
        calls.append(("local", kwargs["tool_name"]))
        return json.dumps(SOURCE_RESULT), "", False

    monkeypatch.setattr(tool_process, "run_local_process", run)
    scans = []

    def scan(text, **source):
        scans.append((text, source))
        return PromptGuardResult(
            "scanned", flagged=True, injection_score=.99, threshold=.8,
            coverage_complete=True, windows_scanned=1,
        )

    monkeypatch.setattr(observer, "scan_text", scan)
    monkeypatch.setattr(observer, "save_incident", lambda **_kwargs: SimpleNamespace(
        incident_id=INCIDENT, evidence_saved=True,
    ))
    return SimpleNamespace(
        executor=executor, logger=logger, calls=calls, scans=scans, scan=scan,
        tool_process=tool_process, monkeypatch=monkeypatch,
    )


def records(harness):
    path = harness.logger.log_file
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def scope(*names):
    return config_scope("cloud", overrides={
        "PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_TOOLS": ",".join(names),
    })


@pytest.mark.parametrize("tool", ["crawl_url", "mcp_fetch_fetch"])
@pytest.mark.parametrize("verdict", ["flagged", "clean", "unavailable"])
def test_real_helpers_persist_only_reviewed_result(harness, tool, verdict):
    if verdict != "flagged":
        observation = (
            PromptGuardResult("scanned", flagged=False, injection_score=.01, threshold=.8)
            if verdict == "clean" else PromptGuardResult("unknown", "timeout")
        )

        def scan(text, **source):
            harness.scans.append((text, source))
            return observation

        harness.monkeypatch.setattr(observer, "scan_text", scan)
    with scope(tool):
        returned = harness.executor.execute(tool, {"url": "https://example.test/"})
    entries = records(harness)
    assert len(harness.calls) == len(harness.scans) == len(entries) == 1
    entry = entries[0]
    assert entry["tool"] == tool and entry["duration_ms"] >= 0
    assert entry["arguments"] == {"url": "https://example.test/"}
    if verdict == "flagged":
        assert returned["error_code"] == "prompt_injection_detected"
        assert PRIVATE not in harness.logger.log_file.read_text()
        assert entry["result"]["speech"] == returned["speech"][:200]
        assert entry["result"]["error"] == "Returned content withheld by Prompt Guard."
    else:
        assert returned == SOURCE_RESULT
        assert entry["result"]["speech"] == SOURCE_RESULT["speech"]
        assert entry["result"]["error"] == SOURCE_RESULT["error"]
    if tool.startswith("mcp_"):
        assert entry["proxy"] == {"policy": "prefer", "used": True, "slot": "primary"}


def test_nothing_is_logged_until_scan_and_quarantine_complete(harness):
    def scan(text, **source):
        assert not records(harness)
        return harness.scan(text, **source)

    def quarantine(**_kwargs):
        assert not records(harness)
        return SimpleNamespace(incident_id=INCIDENT, evidence_saved=True)

    harness.monkeypatch.setattr(observer, "scan_text", scan)
    harness.monkeypatch.setattr(observer, "save_incident", quarantine)
    with scope("crawl_url"):
        returned = harness.executor.execute("crawl_url", {})
    assert returned["terminal_failure"] and len(records(harness)) == 1


def test_malformed_local_stdout_cannot_leak_raw_stderr_before_review(harness):
    def run(*_args, **_kwargs):
        harness.calls.append(("local", "crawl_url"))
        return "not json", PRIVATE, False

    harness.monkeypatch.setattr(harness.tool_process, "run_local_process", run)
    with scope("crawl_url"):
        returned = harness.executor.execute("crawl_url", {})
    assert returned["terminal_failure"]
    assert PRIVATE in harness.scans[0][0]
    assert PRIVATE not in harness.logger.log_file.read_text()
    assert len(harness.calls) == len(harness.scans) == len(records(harness)) == 1


@pytest.mark.parametrize("tool", ["crawl_url", "mcp_fetch_fetch"])
def test_direct_private_helper_keeps_immediate_logging_without_screening(harness, tool):
    with scope(tool):
        returned = harness.executor._execute_foreground(tool, {})
    assert returned == SOURCE_RESULT
    assert len(harness.calls) == len(records(harness)) == 1
    assert not harness.scans
    assert PRIVATE in harness.logger.log_file.read_text()


@pytest.mark.parametrize("flagged", [True, False])
def test_log_flush_failure_does_not_replace_or_replay_tool_outcome(harness, caplog, flagged):
    if not flagged:
        harness.monkeypatch.setattr(observer, "scan_text", lambda text, **source: (
            harness.scans.append((text, source)) or PromptGuardResult("unknown", "timeout")
        ))
    attempts = []

    def broken_logger(**entry):
        attempts.append(entry)
        raise OSError(PRIVATE + " storage failure")

    harness.monkeypatch.setattr(harness.logger, "log_tool_call", broken_logger)
    with scope("crawl_url"):
        returned = harness.executor.execute("crawl_url", {})
    assert len(harness.calls) == len(harness.scans) == len(attempts) == 1
    if flagged:
        assert returned["error_code"] == "prompt_injection_detected"
        assert attempts[0]["result"] is returned
    else:
        assert returned == SOURCE_RESULT
    assert PRIVATE not in caplog.text
    assert "preserving the tool result" in caplog.text


def test_nested_workflow_logs_remain_separate_per_invocation(harness):
    def workflow(**kwargs):
        child = kwargs["tool_executor"].execute("crawl_url", {"url": "https://child.test/"})
        return {"ok": False, "speech": "Workflow stopped.", "data": {"child": child}}

    harness.monkeypatch.setattr(executor_module, "execute_workflow_tool", workflow)
    with scope("crawl_url"):
        returned = harness.executor.execute("workflow", {"name": "research"})
    entries = records(harness)
    assert [entry["tool"] for entry in entries] == ["crawl_url", "workflow"]
    assert entries[0]["arguments"] == {"url": "https://child.test/"}
    assert entries[1]["arguments"] == {"name": "research"}
    assert entries[0]["result"]["speech"].startswith("Prompt Guard withheld")
    assert entries[1]["result"]["speech"] == returned["speech"] == "Workflow stopped."
    assert len(harness.calls) == len(harness.scans) == 1
    assert PRIVATE not in harness.logger.log_file.read_text()


def test_tool_search_helper_passes_its_log_to_same_review_boundary(harness):
    harness.monkeypatch.setattr(
        executor_module, "search_tools_runtime", lambda **_kwargs: dict(SOURCE_RESULT)
    )
    with scope("tool_search"):
        returned = harness.executor.execute("tool_search", {"query": "find"})
    assert returned["terminal_failure"]
    assert len(harness.scans) == len(records(harness)) == 1
    assert PRIVATE not in harness.logger.log_file.read_text()


def test_early_unlogged_return_still_passes_once_through_review(harness):
    harness.executor.registry.get_tool = lambda _name: None
    harness.monkeypatch.setattr(observer, "scan_text", lambda text, **source: (
        harness.scans.append((text, source)) or PromptGuardResult("unknown", "timeout")
    ))
    with scope("missing_tool"):
        returned = harness.executor.execute("missing_tool", {})
    assert returned["error"] == "Tool not found"
    assert len(harness.scans) == 1 and not harness.calls and not records(harness)


def test_concurrent_invocations_do_not_share_pending_logs(harness):
    def run(*_args, **kwargs):
        tool = kwargs["tool_name"]
        harness.calls.append(("local", tool))
        result = dict(SOURCE_RESULT) if tool == "crawl_url" else {"ok": True, "speech": "Clean feed."}
        return json.dumps(result), "", False

    def scan(text, **source):
        harness.scans.append((text, source))
        return PromptGuardResult(
            "scanned", flagged=PRIVATE in text, injection_score=.99 if PRIVATE in text else .01,
            threshold=.8, coverage_complete=True, windows_scanned=1,
        )

    harness.monkeypatch.setattr(harness.tool_process, "run_local_process", run)
    harness.monkeypatch.setattr(observer, "scan_text", scan)

    def execute(name):
        with scope("crawl_url", "rss_feed"):
            return harness.executor.execute(name, {"name": name})

    with ThreadPoolExecutor(max_workers=2) as pool:
        returned = list(pool.map(execute, ["crawl_url", "rss_feed"]))
    entries = {entry["tool"]: entry for entry in records(harness)}
    assert len(harness.calls) == len(harness.scans) == len(entries) == 2
    assert returned[0]["terminal_failure"] and returned[1]["speech"] == "Clean feed."
    assert entries["crawl_url"]["arguments"] == {"name": "crawl_url"}
    assert entries["crawl_url"]["result"]["speech"].startswith("Prompt Guard withheld")
    assert entries["rss_feed"]["arguments"] == {"name": "rss_feed"}
    assert entries["rss_feed"]["result"]["speech"] == "Clean feed."
    assert PRIVATE not in harness.logger.log_file.read_text()
