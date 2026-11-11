"""Real pre-model observer decisions use scoped JSON gates and safe receipts."""

import hashlib
import json
import logging
import sqlite3
import stat
import threading
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock

import config_loader
import paths as path_helpers
import pytest
import requests
from config_loader import config_scope, get_active_config_mode, get_config_value
from prompt_guard_test_config import write_guard_config
from test_prompt_guard import Response, payload
from test_prompt_guard_alerts import SCHEMA as ALERT_SCHEMA

from api.managers import alert_manager
from lib import prompt_guard as scanner
from lib import prompt_guard_observer as observer


@pytest.fixture
def model_input_guard(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    paths = {}
    for mode in ("cloud", "local"):
        paths[mode] = directory / f"{mode}.json"
        write_guard_config(paths[mode])
        (directory / f"{mode}.env").write_text(
            "PROMPT_GUARD_ENABLED=true\n"
            f"PROMPT_GUARD_POLICY_FILE={paths[mode]}\n"
            f"PROMPT_GUARD_URL=http://{mode}-input.test:8188\n"
            f"PROMPT_GUARD_API_KEY={mode}-private-scanner-key\n"
            "PROMPT_GUARD_THRESHOLD=0.8\n"
            "PROMPT_GUARD_MAX_INPUT_BYTES=8192\n"
            f"PROMPT_GUARD_INCIDENT_DIR={tmp_path / 'incidents'}\n"
            "PROMPT_GUARD_ALERTS_ENABLED=false\n"
        )
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    # This fixture models no operator tool assignments. Keep trusted manifest
    # discovery in the same temporary root as the empty tools selection.
    monkeypatch.setattr(path_helpers, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(scanner, "_states", OrderedDict())
    monkeypatch.setattr(scanner, "_capacity", threading.BoundedSemaphore(1))
    state = SimpleNamespace(calls=[], score=0.1, changes={}, failure=None)

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def post(self, url, **kwargs):
            assert self.trust_env is False
            assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
            body = kwargs["json"]
            state.calls.append({"url": url, "mode": get_active_config_mode(), **kwargs})
            if state.failure:
                raise state.failure
            return Response(payload(
                injection_score=state.score,
                threshold=body["threshold"],
                flagged=state.score >= body["threshold"],
                **state.changes,
            ))

    monkeypatch.setattr(scanner.requests, "Session", Session)
    return SimpleNamespace(root=tmp_path, paths=paths, state=state)


@pytest.mark.parametrize("mode", ["cloud", "local"])
@pytest.mark.parametrize("source", ["text_summarizer", "stash_summary"])
def test_default_enabled_model_input_scans_raw_text_independent_of_tool_selection(
    model_input_guard, mode, source
):
    text = "Complete source 😀\nPrices: $415,000; area: 1,700 sq ft."
    with config_scope(mode):
        assert not observer.is_tool_selected(source)
        result = observer.review_model_input(source, text)

    assert result == {"ok": True, "data": {"content": text}}
    call, = model_input_guard.state.calls
    assert call["mode"] == mode and call["url"] == f"http://{mode}-input.test:8188/v1/scan"
    assert call["json"] == {
        "text": text, "threshold": 0.8, "source": {"type": "model_input", "name": source},
    }
    assert not list(model_input_guard.root.glob("incidents/**/*.json"))


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_master_disabled_does_not_extract_source_or_contact_network(
    model_input_guard, monkeypatch, mode
):
    extraction = Mock(wraps=observer._plain_content)
    monkeypatch.setattr(observer, "_plain_content", extraction)
    text = "x" * 100000
    with config_scope(mode, {"PROMPT_GUARD_ENABLED": "false"}):
        assert observer.review_model_input("text_summarizer", text)["data"]["content"] == text
    extraction.assert_not_called()
    assert not model_input_guard.state.calls


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_summarizer_gate_disabled_does_not_disable_selected_output_scanning(
    model_input_guard, monkeypatch, mode
):
    write_guard_config(model_input_guard.paths[mode], tools=["text_summarizer"], summarizers_enabled=False)
    extraction = Mock(wraps=observer._plain_content)
    monkeypatch.setattr(observer, "_plain_content", extraction)
    with config_scope(mode):
        assert observer.review_model_input("text_summarizer", "x" * 100000)["ok"]
        returned = {"ok": True, "data": {"summary": "A completed summary."}}
        assert observer.review_tool_result("text_summarizer", returned) is returned
    extraction.assert_not_called()
    call, = model_input_guard.state.calls
    assert call["json"]["source"] == {"type": "tool_result", "name": "text_summarizer"}
    assert json.loads(call["json"]["text"]) == {"data": returned["data"]}


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_input_gate_hot_reloads_json_inside_existing_mode_scope(model_input_guard, mode):
    path = model_input_guard.paths[mode]
    with config_scope(mode):
        observer.review_model_input("text_summarizer", "First source.")
        write_guard_config(path, summarizers_enabled=False)
        observer.review_model_input("text_summarizer", "Second source.")
        write_guard_config(path)
        observer.review_model_input("text_summarizer", "Third source.")
    assert [call["json"]["text"] for call in model_input_guard.state.calls] == [
        "First source.", "Third source."
    ]


def test_matching_mode_retains_request_overrides_and_other_mode_uses_its_own_gate(model_input_guard):
    write_guard_config(model_input_guard.paths["local"], summarizers_enabled=False)
    with config_scope("cloud", {"PROMPT_GUARD_URL": "http://request-input.test:8188"}):
        observer.review_model_input("text_summarizer", "Scoped cloud source.", mode="cloud")
        observer.review_model_input("text_summarizer", "Unselected local input.", mode="local")
        assert get_active_config_mode() == "cloud"
        assert get_config_value("PROMPT_GUARD_URL") == "http://request-input.test:8188"
    call, = model_input_guard.state.calls
    assert call["mode"] == "cloud" and call["url"] == "http://request-input.test:8188/v1/scan"


def test_model_input_budget_counts_exact_utf8_without_json_overhead_or_prefix_scans(model_input_guard, caplog):
    text = "界\n😀" * 12
    size = len(text.encode("utf-8"))
    with config_scope("local", {"PROMPT_GUARD_MAX_INPUT_BYTES": str(size)}):
        assert observer.review_model_input("stash_summary", text)["data"]["content"] == text
    with config_scope("local", {"PROMPT_GUARD_MAX_INPUT_BYTES": str(size - 1)}), caplog.at_level(logging.INFO):
        assert observer.review_model_input("stash_summary", text)["data"]["content"] == text
    call, = model_input_guard.state.calls
    assert call["json"]["text"] == text
    assert "reason=input_too_large" in caplog.text and "source=model_input" in caplog.text
    assert text not in caplog.text


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_confirmed_model_input_saves_exact_quarantine_and_neutral_terminal_notice(
    model_input_guard, caplog, mode
):
    model_input_guard.state.score = 0.99
    text = "PRIVATE_SOURCE_BODY 😀"
    with config_scope(mode), caplog.at_level(logging.INFO):
        blocked = observer.review_model_input("text_summarizer", text, args={
            "stash_ref": "stash://private-space/private-file", "filename": "PRIVATE_FILENAME",
        })
    assert observer.is_prompt_guard_rejection(blocked) and observer.is_prompt_guard_stopped(blocked)
    assert blocked["completion"] == "rejected" and blocked["retry_safe"] is False
    assert blocked["data"]["operation"] == {"tool_executed": False, "original_ok": True}
    metadata = blocked["data"]["prompt_guard"]
    assert metadata["source_type"] == "model_input" and metadata["evidence_saved"] is True
    assert "blocked text was not sent to the summarizer model" in blocked["speech"]
    assert "No fallback summary or Memory write followed" in blocked["speech"]
    assert "tool already ran" not in blocked["speech"]
    assert "PRIVATE_" not in json.dumps(blocked) and "PRIVATE_" not in caplog.text
    assert "private-scanner-key" not in caplog.text
    evidence_path, = (model_input_guard.root / "incidents" / mode).glob("*.json")
    evidence = json.loads(evidence_path.read_text())
    assert stat.S_IMODE(evidence_path.stat().st_mode) == 0o600
    assert evidence["source_type"] == "model_input" and evidence["tool_name"] == "text_summarizer"
    assert evidence["evidence"] == {
        "representation": "scanned_untrusted_text", "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(), "utf8_bytes": len(text.encode()),
    }


@pytest.mark.parametrize("failure", ["timeout", "transport", "partial", "busy", "unconfigured"])
def test_unavailable_or_incomplete_input_scan_fails_open_without_false_clean_receipt(
    model_input_guard, failure, caplog
):
    options = {}
    if failure == "timeout":
        model_input_guard.state.failure = requests.exceptions.Timeout("PRIVATE_SCANNER_ERROR")
    elif failure == "transport":
        model_input_guard.state.failure = requests.exceptions.ConnectionError("PRIVATE_SCANNER_ERROR")
    elif failure == "partial":
        model_input_guard.state.changes = {"coverage": {
            "complete": False, "truncated": True, "windows_scanned": 1, "windows_total": 2,
        }}
    elif failure == "busy":
        assert scanner._capacity.acquire(blocking=False)
    else:
        options["PROMPT_GUARD_API_KEY"] = ""
    text = "Source content retained under the existing fail-open policy."
    try:
        with config_scope("cloud", options), caplog.at_level(logging.INFO):
            assert observer.review_model_input("text_summarizer", text) == {
                "ok": True, "data": {"content": text},
            }
    finally:
        if failure == "busy":
            scanner._capacity.release()
    assert not list(model_input_guard.root.glob("incidents/**/*.json"))
    assert "action=withhold" not in caplog.text and "PRIVATE_SCANNER_ERROR" not in caplog.text
    assert len(model_input_guard.state.calls) == (0 if failure in {"busy", "unconfigured"} else 1)


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_real_input_alert_publishes_safe_metadata_after_private_quarantine(
    model_input_guard, monkeypatch, mode
):
    database = model_input_guard.root / f"{mode}-alerts.db"
    with sqlite3.connect(database) as connection:
        connection.execute(ALERT_SCHEMA)
    monkeypatch.setattr(
        alert_manager, "get_memory_db", lambda _mode: SimpleNamespace(db_path=str(database), close=Mock()),
    )
    speech = Mock()
    monkeypatch.setattr(alert_manager.AlertManager, "_speak_alert", speech)
    model_input_guard.state.score = 0.99
    with config_scope(mode, {"PROMPT_GUARD_ALERTS_ENABLED": "true"}):
        blocked = observer.review_model_input("stash_summary", "PRIVATE_ALERT_SOURCE_BODY", args={
            "filename": "PRIVATE_FILENAME", "url": "https://private.example/?token=secret",
        })
    assert observer.is_prompt_guard_rejection(blocked)
    assert blocked["data"]["prompt_guard"]["alert"] == {"alert_id": 1, "duplicate_suppressed": False}
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = dict(connection.execute("SELECT * FROM alerts").fetchone())
    metadata = json.loads(row["metadata"])
    assert metadata["source_type"] == "model_input" and metadata["source_name"] == "stash_summary"
    assert metadata["mode"] == mode and metadata["score"] == 0.99
    assert metadata["incident_id"] == blocked["data"]["prompt_guard"]["incident_id"]
    assert list((model_input_guard.root / "incidents" / mode).glob("*.json"))
    assert "PRIVATE_" not in json.dumps(row) and "private.example" not in json.dumps(row)
    speech.assert_called_once()
