"""Observation preserves tool results and respects scope, privacy and limits."""

import json
import logging
from copy import deepcopy
from types import SimpleNamespace

import config_loader
import pytest
from config_loader import config_scope, get_active_config_mode, get_config_value

from lib import prompt_guard_observer as observer
from lib.prompt_guard import PromptGuardResult


@pytest.fixture
def configured(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    for mode in ("cloud", "local"):
        (directory / f"{mode}.env").write_text(
            "PROMPT_GUARD_ENABLED=true\n"
            f"PROMPT_GUARD_TOOLS={'crawl_url,brave_llm_context,rss_feed' if mode == 'cloud' else 'local_fetch'}\n"
            f"PROMPT_GUARD_URL=http://{mode}-guard:8188\n"
            "PROMPT_GUARD_MAX_INPUT_BYTES=8192\n"
        )
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    calls = []

    def record(text, **source):
        calls.append({
            "text": text, **source, "mode": get_active_config_mode(),
            "url": get_config_value("PROMPT_GUARD_URL"),
        })

    monkeypatch.setattr(observer, "scan_text", record)
    return calls


@pytest.mark.parametrize("tool", ["crawl_url", "brave_llm_context", "rss_feed"])
@pytest.mark.parametrize("ok", [True, False])
def test_selected_success_and_failure_submit_returned_content_without_mutation(configured, tool, ok):
    result = {
        "ok": ok, "data": {"content": "An external article.", "error": "Remote detail."},
        "speech": "Fetched article.", "arguments": {"api_key": "ARGUMENT_SECRET"},
        "completion": "completed", "error": "OUTER_ERROR_NOT_SELECTED",
    }
    before = deepcopy(result)
    with config_scope("cloud"):
        assert observer.review_tool_result(tool, result) is result
    assert result == before
    assert len(configured) == 1
    call = configured[0]
    assert json.loads(call["text"]) == {"data": result["data"], "speech": result["speech"], "error": result["error"]}
    assert call["source_type"] == "tool_result"
    assert call["source_name"] == tool
    assert "ARGUMENT_SECRET" not in call["text"]
    assert result["error"] in call["text"]


@pytest.mark.parametrize("tool", ["workflow", "send_email", "mcp_google_workspace_get_gmail_message", "mcp_fetch_fetch"])
def test_unselected_tools_are_silent(configured, caplog, tool):
    with config_scope("cloud"), caplog.at_level(logging.INFO):
        observer.review_tool_result(tool, {"data": "private"})
    assert configured == []
    assert caplog.records == []


def test_empty_tools_disables_hook_and_wildcards_do_not_select_mcp(configured):
    for value in ("", "*", "mcp_*"):
        with config_scope("cloud", overrides={"PROMPT_GUARD_TOOLS": value}):
            observer.review_tool_result("crawl_url", {"data": "article"})
            observer.review_tool_result("mcp_fetch_fetch", {"data": "article"})
    assert configured == []


def test_exact_configuration_can_select_reviewed_mcp_tool(configured):
    with config_scope("cloud", overrides={"PROMPT_GUARD_TOOLS": " mcp_fetch_fetch, crawl_url "}):
        observer.review_tool_result("mcp_fetch_fetch", {"data": "article"})
    assert configured[0]["source_name"] == "mcp_fetch_fetch"


def test_default_selection_applies_when_setting_absent(configured):
    path = config_loader.get_project_root() / "config/cloud.env"
    path.write_text("\n".join(line for line in path.read_text().splitlines()
                              if not line.startswith("PROMPT_GUARD_TOOLS=")))
    with config_scope("cloud"):
        for tool in observer.DEFAULT_TOOLS.split(","):
            observer.review_tool_result(tool, {"data": "article"})
    assert [call["source_name"] for call in configured] == observer.DEFAULT_TOOLS.split(",")


def test_disabled_skips_extraction_and_uses_shared_disabled_logging(configured, monkeypatch):
    def should_not_extract(*_args):
        raise AssertionError("Disabled observation must not inspect content")

    monkeypatch.setattr(observer, "_serialize_content", should_not_extract)
    with config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "false"}):
        observer.review_tool_result("crawl_url", {"data": "x" * 100000})
    assert configured[0]["text"] == ""


@pytest.mark.parametrize("content", ["x" * 9000, "界" * 3000, ["x" * 1000] * 10])
def test_oversized_content_skips_whole_and_logs_no_text(configured, caplog, content):
    result = {"data": content, "speech": "PRIVATE_SPEECH_SENTINEL"}
    before = deepcopy(result)
    with config_scope("cloud"), caplog.at_level(logging.INFO):
        observer.review_tool_result("crawl_url", result)
    assert configured == []
    assert result == before
    assert "input_too_large" in caplog.text
    assert "PRIVATE_SPEECH_SENTINEL" not in caplog.text


def test_budget_counts_utf8_and_json_escaping_without_truncation(configured, caplog):
    result = {"data": "界\n" * 20}
    exact_size = len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
    with config_scope("cloud", overrides={"PROMPT_GUARD_MAX_INPUT_BYTES": str(exact_size)}):
        observer.review_tool_result("crawl_url", result)
    assert len(configured) == 1
    with config_scope("cloud", overrides={"PROMPT_GUARD_MAX_INPUT_BYTES": str(exact_size - 1)}), caplog.at_level(logging.INFO):
        observer.review_tool_result("crawl_url", result)
    assert len(configured) == 1
    assert "input_too_large" in caplog.text


def test_cyclic_content_skips_without_modifying_it(configured, caplog):
    data = {"title": "PRIVATE_CYCLE_SENTINEL"}
    data["self"] = data
    result = {"data": data}
    with config_scope("cloud"), caplog.at_level(logging.INFO):
        observer.review_tool_result("crawl_url", result)
    assert configured == []
    assert data["self"] is data
    assert "cyclic_content" in caplog.text
    assert "PRIVATE_CYCLE_SENTINEL" not in caplog.text


@pytest.mark.parametrize("content", [float("nan"), float("inf"), b"binary", {1: "bad key"}, "\ud800"])
def test_non_json_or_invalid_text_skips_safely(configured, caplog, content):
    with config_scope("cloud"), caplog.at_level(logging.INFO):
        observer.review_tool_result("crawl_url", {"data": content})
    assert configured == []
    assert "invalid_content" in caplog.text


def test_untrusted_object_is_never_stringified(configured, caplog):
    class NoString:
        def __str__(self):
            raise AssertionError("Object was stringified")

    with config_scope("cloud"), caplog.at_level(logging.INFO):
        observer.review_tool_result("crawl_url", {"data": NoString()})
    assert configured == []
    assert "invalid_content" in caplog.text


def test_structure_depth_limit_is_bounded(configured, caplog):
    data = "leaf"
    for _ in range(40):
        data = [data]
    with config_scope("cloud"), caplog.at_level(logging.INFO):
        observer.review_tool_result("crawl_url", {"data": data})
    assert configured == []
    assert "content_structure_limit" in caplog.text


def test_structure_node_limit_is_bounded(configured, caplog):
    with config_scope("cloud", overrides={"PROMPT_GUARD_MAX_INPUT_BYTES": "100000"}), caplog.at_level(logging.INFO):
        observer.review_tool_result("crawl_url", {"data": list(range(5000))})
    assert configured == []
    assert "content_structure_limit" in caplog.text


def test_shared_aliases_are_not_mistaken_for_cycles(configured):
    shared = {"title": "Article"}
    with config_scope("cloud"):
        observer.review_tool_result("crawl_url", {"data": [shared, shared]})
    assert json.loads(configured[0]["text"])["data"] == [shared, shared]


def test_no_stash_or_url_dereference(configured):
    data = {"ref": "stash://example/article.md", "url": "https://example.org/article"}
    with config_scope("cloud"):
        observer.review_tool_result("crawl_url", {"data": data})
    assert json.loads(configured[0]["text"])["data"] == data


def test_same_explicit_mode_preserves_request_overrides(configured):
    with config_scope("cloud", overrides={"PROMPT_GUARD_TOOLS": "custom_fetch", "PROMPT_GUARD_URL": "http://request-guard:8188"}):
        observer.review_tool_result("custom_fetch", {"data": "article"}, mode="cloud")
    assert configured[0]["url"] == "http://request-guard:8188"
    assert configured[0]["mode"] == "cloud"


def test_different_mode_uses_its_config_and_restores_outer_scope(configured):
    with config_scope("cloud", overrides={"PROMPT_GUARD_URL": "http://request-guard:8188"}):
        observer.review_tool_result("local_fetch", {"data": "article"}, mode="local")
        assert get_active_config_mode() == "cloud"
        assert get_config_value("PROMPT_GUARD_URL") == "http://request-guard:8188"
    assert configured[0]["url"] == "http://local-guard:8188"
    assert configured[0]["mode"] == "local"


@pytest.mark.parametrize("mode,tool", [("cloud", "crawl_url"), ("local", "local_fetch")])
def test_explicit_background_scope_uses_job_config_and_restores_unrelated_request(configured, mode, tool):
    with config_scope(mode, overrides={
        "PROMPT_GUARD_ENABLED": "false", "PROMPT_GUARD_TOOLS": "unrelated_tool",
        "PROMPT_GUARD_URL": "http://unrelated-request:8188",
    }):
        original = {"ok": True, "data": "Background report."}
        assert observer.review_tool_result(tool, original, mode=mode, config_overrides={}) is original
        assert get_config_value("PROMPT_GUARD_URL") == "http://unrelated-request:8188"
        assert get_config_value("PROMPT_GUARD_ENABLED") == "false"
    assert len(configured) == 1
    assert configured[0]["mode"] == mode
    assert configured[0]["url"] == f"http://{mode}-guard:8188"
    assert json.loads(configured[0]["text"]) == {"data": original["data"]}


def test_background_deployment_overrides_apply_in_shared_adapter_scope(configured):
    with config_scope("local"):
        observer.review_tool_result(
            "crawl_url", {"data": "Report."}, mode="cloud",
            config_overrides={"PROMPT_GUARD_URL": "http://deployment-guard:8188"},
        )
        assert get_active_config_mode() == "local"
    assert configured[0]["mode"] == "cloud"
    assert configured[0]["url"] == "http://deployment-guard:8188"


def test_observer_bug_cannot_fail_tool_or_disclose_exception(configured, monkeypatch, caplog):
    def broken(*_args, **_kwargs):
        raise RuntimeError("EXCEPTION_SECRET")

    monkeypatch.setattr(observer, "scan_text", broken)
    result = {"ok": True, "completion": "completed", "data": {"ref": "stash://recording.mp3"}}
    before = deepcopy(result)
    with config_scope("cloud"), caplog.at_level(logging.INFO):
        assert observer.review_tool_result("crawl_url", result) is result
    assert result == before
    assert "observer_error" in caplog.text
    assert "EXCEPTION_SECRET" not in caplog.text


@pytest.mark.parametrize("observation", [
    PromptGuardResult("scanned", flagged=False, injection_score=0.01),
    PromptGuardResult("unknown", reason_code="timeout"),
    PromptGuardResult("skipped", reason_code="busy"),
])
def test_observation_outcome_never_changes_result_or_adds_logs(configured, monkeypatch, caplog, observation):
    monkeypatch.setattr(observer, "scan_text", lambda *_args, **_kwargs: observation)
    result = {"ok": True, "data": {"article": "Original content."}, "completion": "completed"}
    before = deepcopy(result)
    with config_scope("cloud"), caplog.at_level(logging.INFO):
        assert observer.review_tool_result("crawl_url", result) is result
    assert result == before
    assert caplog.records == []


def test_logging_failure_does_not_change_result(configured, monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("Broken logging handler")

    monkeypatch.setattr(observer.logger, "info", broken)
    with config_scope("cloud"):
        result = {"data": "x" * 9000}
        assert observer.review_tool_result("crawl_url", result) is result
    assert configured == []


@pytest.mark.parametrize("ok", [True, False])
@pytest.mark.parametrize("completion", ["completed", "unknown", None])
def test_confirmed_detection_withholds_content_and_returns_investigation_receipt(configured, monkeypatch, ok, completion):
    observation = PromptGuardResult("scanned", flagged=True, injection_score=.99, threshold=.8)
    monkeypatch.setattr(observer, "scan_text", lambda *_args, **_kwargs: observation)
    saved = []

    def save(**kwargs):
        saved.append(kwargs)
        return SimpleNamespace(incident_id="pg-" + "a" * 32, evidence_saved=True)

    monkeypatch.setattr(observer, "save_incident", save)
    result = {"ok": ok, "completion": completion, "speech": "PRIVATE_FLAGGED_SPEECH",
              "data": {"content": "PRIVATE_FLAGGED_BODY", "receipt": "private-provider-handle"}}
    original = deepcopy(result)
    args = {"url": "https://source.example/article", "api_key": "PRIVATE_ARG_KEY"}
    with config_scope("cloud"):
        blocked = observer.review_tool_result("crawl_url", result, args=args)
    assert observer.is_prompt_guard_rejection(blocked)
    assert blocked is not result and result == original
    assert blocked["retry_safe"] is False
    assert blocked["completion"] == (completion or "unknown")
    assert blocked["data"]["operation"] == {"tool_executed": True, "original_ok": ok}
    assert blocked["data"]["prompt_guard"]["evidence_saved"] is True
    assert "pg-" + "a" * 32 in blocked["speech"]
    assert "crawl_url" in blocked["speech"] and "not be retried" in blocked["speech"]
    encoded = json.dumps(blocked)
    for secret in ("PRIVATE_FLAGGED_SPEECH", "PRIVATE_FLAGGED_BODY", "private-provider-handle", "PRIVATE_ARG_KEY", "source.example"):
        assert secret not in encoded
    assert json.loads(saved[0]["text"]) == {"data": result["data"], "speech": result["speech"]}
    assert saved[0]["args"] is args and saved[0]["result"] is result


@pytest.mark.parametrize("save_raises", [True, False])
def test_incident_or_logging_failure_never_restores_flagged_content(configured, monkeypatch, save_raises):
    monkeypatch.setattr(observer, "scan_text", lambda *_args, **_kwargs:
                        PromptGuardResult("scanned", flagged=True, injection_score=.99, threshold=.8))

    def save(**_kwargs):
        if save_raises:
            raise OSError("PRIVATE_DISK_ERROR")
        return SimpleNamespace(incident_id="pg-" + "b" * 32, evidence_saved=False)

    def broken_log(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_LOG_ERROR")

    monkeypatch.setattr(observer, "save_incident", save)
    monkeypatch.setattr(observer.logger, "warning", broken_log)
    original = {"ok": True, "data": "PRIVATE_FLAGGED_BODY"}
    with config_scope("cloud"):
        blocked = observer.review_tool_result("rss_feed", original)
    assert observer.is_prompt_guard_rejection(blocked)
    assert blocked["data"]["prompt_guard"]["evidence_saved"] is False
    assert "could not be saved" in blocked["speech"]
    assert "PRIVATE_" not in json.dumps(blocked)


def test_notice_uses_only_validated_identifiers():
    result = {"data": {"prompt_guard": {"tool": "PRIVATE_SECRET<script>",
               "incident_id": "PRIVATE_SECRET<script>", "evidence_saved": True}},
              "speech": "PRIVATE_SECRET", "error": "PRIVATE_SECRET"}
    notice = observer.prompt_guard_notice(result)
    assert "PRIVATE_SECRET" not in notice
    assert "a tool" in notice


@pytest.mark.parametrize("result", [
    {"error_code": "prompt_injection_detected", "terminal_failure": True},
    {"prompt_guard_blocked": True},
    {"data": {"prompt_guard": {"content_withheld": True}}},
    {"data": {"crawl_url": {"prompt_guard": {"content_withheld": True}}}},
])
def test_projected_or_saved_stop_is_recognized_without_mutation(result):
    original = deepcopy(result)
    assert observer.is_prompt_guard_stopped(result)
    assert result == original


@pytest.mark.parametrize("result", [
    None, [], "prompt_injection_detected",
    {"ok": False, "error": "Remote timeout"},
    {"error_code": "prompt_injection_detected", "terminal_failure": False},
    {"prompt_guard_blocked": "true"},
    {"data": {"prompt_guard": {"content_withheld": "true"}}},
    {"data": {"prompt_guard": {"content_withheld": False}}},
    {"data": {"article": {"content": {"prompt_guard": {"content_withheld": True}}}}},
])
def test_stop_recognition_ignores_normal_errors_and_arbitrary_content(result):
    assert not observer.is_prompt_guard_stopped(result)


def test_projected_receipt_does_not_become_a_canonical_tool_rejection():
    # A tool's arbitrary data must not acquire terminal execution semantics.
    result = {"ok": True, "data": {"prompt_guard": {"content_withheld": True}}}
    assert not observer.is_prompt_guard_rejection(result)
