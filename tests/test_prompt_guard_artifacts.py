"""Artifact screening happens at model consumption, never at storage ingress."""

import json
import logging
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest
from config_loader import config_scope, get_active_config_mode, get_config_value

from lib import prompt_guard_observer as observer
from lib.prompt_guard import PromptGuardResult
from orchestrator.executor import ToolExecutor


@pytest.fixture
def screening(monkeypatch):
    monkeypatch.setattr(observer, "notify_prompt_guard_block", lambda *_args, **_kwargs: None)
    calls = []
    observation = PromptGuardResult(
        "scanned", flagged=False, injection_score=.01, threshold=.8,
        coverage_complete=True, windows_scanned=1,
    )

    def scan(text, **source):
        calls.append({"text": text, **source, "mode": get_active_config_mode(),
                      "url": get_config_value("PROMPT_GUARD_URL")})
        return observation

    monkeypatch.setattr(observer, "scan_text", scan)
    with config_scope("cloud", overrides={
        "PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_TOOLS": "stash,source_library",
        "PROMPT_GUARD_URL": "http://synthetic-guard:8188", "PROMPT_GUARD_MAX_INPUT_BYTES": "8192",
    }):
        yield calls


@pytest.mark.parametrize("tool,action", [
    ("stash", "read"), ("stash", "READ"),
    ("source_library", "read"), ("source_library", "search"),
])
def test_selected_artifact_reads_scan_exact_returned_representation(screening, tool, action):
    result = {"ok": True, "speech": "Retrieved evidence.", "data": {
        "content": "External report.", "passages": [{"text": "A cited source passage."}],
        "ref": "stash://synthetic/file", "action": "save",
    }}
    original = deepcopy(result)
    args = {"action": action, "api_key": "PRIVATE_ARG_SECRET"}
    assert observer.review_tool_result(tool, result, args=args) is result
    assert result == original
    assert len(screening) == 1
    assert json.loads(screening[0]["text"]) == {"data": result["data"], "speech": result["speech"]}
    assert screening[0]["source_name"] == tool and screening[0]["source_type"] == "tool_result"
    assert "PRIVATE_ARG_SECRET" not in screening[0]["text"]


@pytest.mark.parametrize("tool,action", [
    ("stash", "save"), ("stash", "open_space"), ("stash", "list"),
    ("stash", "info"), ("stash", "update"), ("stash", "cleanup"),
    ("stash", "compose"), ("stash", "remember"),
    ("source_library", "save"), ("source_library", "list"),
    ("source_library", "index"), ("source_library", "rename"),
    ("source_library", "remove"), ("source_library", "READ"),
])
def test_artifact_writes_and_administration_never_scan_even_if_result_claims_read(screening, tool, action):
    result = {"ok": True, "data": {"action": "read", "content": "Stored report."}}
    assert observer.review_tool_result(tool, result, args={"action": action}) is result
    assert screening == []


def test_action_defaults_match_real_dispatchers_and_do_not_trust_result_metadata(screening):
    result = {"ok": True, "data": {"action": "read", "content": "A passage."}}
    assert observer.review_tool_result("stash", result) is result
    assert screening == []
    assert observer.review_tool_result("source_library", result) is result
    assert [call["source_name"] for call in screening] == ["source_library"]


@pytest.mark.parametrize("selection", ["", "crawl_url", "*", "stash_*"])
def test_artifact_reads_still_require_exact_tool_selection(screening, selection):
    with config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_TOOLS": selection}):
        for tool in ("stash", "source_library"):
            observer.review_tool_result(tool, {"data": {"content": "Evidence."}}, args={"action": "read"})
    assert screening == []


def test_no_stash_reference_or_url_is_resolved(screening):
    result = {"ok": True, "data": {"ref": "stash://unread/elsewhere",
              "url": "https://example.invalid/never-fetch", "path": "/not-opened/file.txt"}}
    assert observer.review_tool_result("stash", result, args={"action": "read"}) is result
    assert json.loads(screening[0]["text"])["data"] == result["data"]


def test_real_executor_screens_completed_artifact_once_without_replaying(screening, monkeypatch):
    executor = object.__new__(ToolExecutor)
    executor.mode = "cloud"
    executor.excluded_tools = set()
    executor.registry = SimpleNamespace()
    result = {"ok": True, "completion": "completed", "data": {"content": "PRIVATE_REPORT_BODY"}}
    executions = []

    def foreground(name, args, permission, *, log_callback=None):
        executions.append((name, args, permission))
        return result

    executor._execute_foreground = foreground
    monkeypatch.setattr(observer, "scan_text", lambda *_args, **_kwargs: PromptGuardResult(
        "scanned", flagged=True, injection_score=.99, threshold=.8,
    ))
    monkeypatch.setattr(observer, "save_incident", lambda **_kwargs: SimpleNamespace(
        incident_id="pg-" + "a" * 32, evidence_saved=True,
    ))
    blocked = executor.execute("stash", {"action": "read"})
    assert observer.is_prompt_guard_rejection(blocked)
    assert len(executions) == 1
    assert blocked["completion"] == "completed" and blocked["retry_safe"] is False
    assert blocked["data"]["operation"] == {"tool_executed": True, "original_ok": True}
    assert "PRIVATE_REPORT_BODY" not in json.dumps(blocked)


def test_attachment_ingestion_is_distinct_from_tool_selection_and_preserves_exact_text(screening):
    text = "Full attachment 😀\nParagraph two, no escaping or truncation."
    with config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_TOOLS": ""}):
        result = observer.review_untrusted_text("web_text", text)
    assert result == {"ok": True, "data": {"content": text}}
    assert screening[0]["text"] == text
    assert screening[0]["source_type"] == "attachment" and screening[0]["source_name"] == "web_text"


def test_disabled_attachment_screening_does_not_inspect_text(screening, monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("Disabled screening must not inspect attachment text")

    monkeypatch.setattr(observer, "_plain_content", unexpected)
    text = "x" * 100000
    with config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "false"}):
        assert observer.review_untrusted_text("web_text", text)["data"]["content"] == text
    assert screening[0]["text"] == ""


@pytest.mark.parametrize("observation", [
    PromptGuardResult("disabled", "disabled"),
    PromptGuardResult("unknown", "timeout"),
    PromptGuardResult("unknown", "invalid_configuration"),
    PromptGuardResult("skipped", "busy"),
    PromptGuardResult("skipped", "cooldown"),
    PromptGuardResult("scanned", flagged=False, injection_score=.1),
])
def test_incomplete_or_clean_attachment_scan_returns_original_text(screening, monkeypatch, observation):
    monkeypatch.setattr(observer, "scan_text", lambda *_args, **_kwargs: observation)
    text = "Attachment text stays byte-for-byte unchanged."
    assert observer.review_untrusted_text("web_text", text) == {"ok": True, "data": {"content": text}}


@pytest.mark.parametrize("text,reason", [
    ("界" * 3000, "input_too_large"), ("x" * 9000, "input_too_large"),
    ("\ud800", "invalid_content"), (" \n", "empty_content"),
])
def test_attachment_limit_skips_whole_text_without_scanning_prefix(screening, caplog, text, reason):
    with caplog.at_level(logging.INFO):
        result = observer.review_untrusted_text("web_text", text)
    assert result["data"]["content"] == text and screening == []
    assert reason in caplog.text
    assert "source=attachment" in caplog.text
    assert "界" not in caplog.text


def test_attachment_budget_is_exact_raw_utf8_not_serialized_json(screening):
    text = "界\n" * 20
    size = len(text.encode())
    with config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_MAX_INPUT_BYTES": str(size)}):
        observer.review_untrusted_text("web_text", text)
    assert screening[0]["text"] == text
    with config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_MAX_INPUT_BYTES": str(size - 1)}):
        observer.review_untrusted_text("web_text", text)
    assert len(screening) == 1


def test_confirmed_attachment_is_quarantined_without_claiming_a_tool_ran(screening, monkeypatch, caplog):
    observation = PromptGuardResult(
        "scanned", flagged=True, injection_score=.99, threshold=.8,
        coverage_complete=True, windows_scanned=1,
    )
    monkeypatch.setattr(observer, "scan_text", lambda *_args, **_kwargs: observation)
    saved = []

    def save(**kwargs):
        saved.append(kwargs)
        return SimpleNamespace(incident_id="pg-" + "b" * 32, evidence_saved=True)

    monkeypatch.setattr(observer, "save_incident", save)
    text = "PRIVATE_FLAGGED_ATTACHMENT_BODY"
    with caplog.at_level(logging.WARNING):
        blocked = observer.review_untrusted_text("web_text", text, args={"filename": "PRIVATE_FILENAME"})
    assert observer.is_prompt_guard_rejection(blocked) and observer.is_prompt_guard_stopped(blocked)
    assert blocked["completion"] == "rejected" and blocked["retry_safe"] is False
    assert blocked["data"]["operation"] == {"tool_executed": False, "original_ok": True}
    assert blocked["data"]["prompt_guard"]["source_type"] == "attachment"
    assert "attachment text was not sent to the model" in blocked["speech"]
    assert "tool already ran" not in blocked["speech"]
    assert "PRIVATE_" not in json.dumps(blocked) and "PRIVATE_" not in caplog.text
    assert saved[0]["text"] == text and saved[0]["source_type"] == "attachment"
    assert saved[0]["result"] == {"ok": True, "data": {"content": text}}


@pytest.mark.parametrize("saving_failure", [True, False])
def test_attachment_evidence_or_logging_failure_never_unblocks(screening, monkeypatch, saving_failure):
    monkeypatch.setattr(observer, "scan_text", lambda *_args, **_kwargs: PromptGuardResult(
        "scanned", flagged=True, injection_score=.99, threshold=.8,
    ))

    def save(**_kwargs):
        if saving_failure:
            raise OSError("PRIVATE_DISK_ERROR")
        return SimpleNamespace(incident_id="pg-" + "c" * 32, evidence_saved=False)

    def broken_log(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_LOG_ERROR")

    monkeypatch.setattr(observer, "save_incident", save)
    monkeypatch.setattr(observer.logger, "warning", broken_log)
    blocked = observer.review_untrusted_text("web_text", "PRIVATE_FLAGGED_BODY")
    assert observer.is_prompt_guard_rejection(blocked)
    assert "PRIVATE_" not in json.dumps(blocked)
    assert "could not be saved" in blocked["speech"]


def test_attachment_observer_bug_fails_open_without_exception_details(screening, monkeypatch, caplog):
    def broken(*_args, **_kwargs):
        raise RuntimeError("PRIVATE_EXCEPTION")

    monkeypatch.setattr(observer, "scan_text", broken)
    with caplog.at_level(logging.INFO):
        result = observer.review_untrusted_text("web_text", "Original attachment.")
    assert result == {"ok": True, "data": {"content": "Original attachment."}}
    assert "observer_error" in caplog.text and "PRIVATE_EXCEPTION" not in caplog.text


@pytest.mark.parametrize("source_type", ["tool_result", "attachment"])
@pytest.mark.parametrize("notification_failure", [True, False])
def test_high_confidence_alert_is_attempted_once_after_quarantine_without_raw_text(
    screening, monkeypatch, source_type, notification_failure,
):
    from hashlib import sha256

    observation = PromptGuardResult(
        "scanned", flagged=True, injection_score=.99, threshold=.8,
        coverage_complete=True, windows_scanned=1,
    )
    monkeypatch.setattr(observer, "scan_text", lambda *_args, **_kwargs: observation)
    order = []
    notices = []

    def save(**_kwargs):
        order.append("quarantine")
        raise OSError("PRIVATE_DISK_ERROR")

    def notify(source_name, observed, withheld, *, text_digest):
        order.append("alert")
        assert observer.is_prompt_guard_rejection(withheld)
        assert withheld["data"]["prompt_guard"]["evidence_saved"] is False
        notices.append((source_name, observed, deepcopy(withheld), text_digest))
        if notification_failure:
            raise RuntimeError("PRIVATE_ALERT_ERROR")
        return {"alert_id": 123, "duplicate_suppressed": False}

    monkeypatch.setattr(observer, "save_incident", save)
    monkeypatch.setattr(observer, "notify_prompt_guard_block", notify)
    text = "PRIVATE_FLAGGED_ATTACHMENT_BODY"
    if source_type == "attachment":
        blocked = observer.review_untrusted_text("web_text", text)
        scanned_text = text
    else:
        original = {"ok": True, "data": {"content": text}}
        blocked = observer.review_tool_result("stash", original, args={"action": "read"})
        scanned_text = observer._serialize_content(original, 8192)
    assert observer.is_prompt_guard_rejection(blocked)
    assert order == ["quarantine", "alert"] and len(notices) == 1
    assert notices[0][3] == sha256(scanned_text.encode()).hexdigest()
    assert "PRIVATE_" not in json.dumps(blocked) and "PRIVATE_" not in json.dumps(notices[0][2])
    assert blocked["data"]["prompt_guard"].get("alert") == (
        None if notification_failure else {"alert_id": 123, "duplicate_suppressed": False}
    )


def test_attachment_source_name_is_not_a_filename_or_arbitrary_external_label(screening):
    for source in ("private filename.txt", "https://example.invalid/file", "<script>"):
        assert observer.review_untrusted_text(source, "Evidence.")["ok"] is True
    assert screening == []


def test_attachment_scope_preserves_overrides_and_restores_outer_request(screening):
    with config_scope("local", overrides={"PROMPT_GUARD_URL": "http://outer-guard:8188"}):
        observer.review_untrusted_text("web_text", "Evidence.", mode="cloud", config_overrides={
            "PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_URL": "http://job-guard:8188",
        })
        assert get_active_config_mode() == "local"
        assert get_config_value("PROMPT_GUARD_URL") == "http://outer-guard:8188"
    assert screening[0]["mode"] == "cloud" and screening[0]["url"] == "http://job-guard:8188"


@pytest.mark.parametrize("policy_id,expected", [("attachment_default", "attachment_default"),
                                               ("PRIVATE<script>", None)])
def test_only_validated_policy_ids_enter_neutral_receipts(screening, monkeypatch, policy_id, expected):
    observation = replace(PromptGuardResult("scanned", flagged=True, injection_score=.99, threshold=.8),
                          policy_id=policy_id)
    monkeypatch.setattr(observer, "scan_text", lambda *_args, **_kwargs: observation)
    monkeypatch.setattr(observer, "save_incident", lambda **_kwargs: SimpleNamespace(
        incident_id=None, evidence_saved=False,
    ))
    blocked = observer.review_untrusted_text("web_text", "Evidence.")
    assert blocked["data"]["prompt_guard"].get("policy_id") == expected
    assert "PRIVATE" not in json.dumps(blocked)
