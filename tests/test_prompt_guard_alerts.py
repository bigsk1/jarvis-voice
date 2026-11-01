"""Confirmed content blocks publish only safe metadata through ordinary alerts."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import config_loader
import pytest
from config_loader import config_scope, get_active_config_mode, get_config_value
from filelock import FileLock

from api.managers import alert_manager
from lib import prompt_guard_alerts as alerts
from lib.prompt_guard import PromptGuardResult

SCHEMA = """
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY, title TEXT, description TEXT, severity TEXT,
    source TEXT, status TEXT, created_at TEXT, metadata TEXT,
    auto_resolve_url TEXT, auto_resolve_check_interval INTEGER,
    related_intel_file TEXT, spoken INTEGER DEFAULT 0, spoken_at TEXT
)
"""
DIGEST = "a" * 64
_REAL_SPEAK_ALERT = alert_manager.AlertManager._speak_alert


def observed(score=0.97, threshold=0.8):
    return PromptGuardResult(
        "scanned", flagged=True, injection_score=score, threshold=threshold,
        coverage_complete=True, windows_scanned=1,
    )


def withheld(**metadata):
    return {
        "ok": False, "error_code": "prompt_injection_detected", "terminal_failure": True,
        "retry_safe": False, "completion": "completed",
        "data": {"prompt_guard": {
            "content_withheld": True, "source_type": "tool_result", "tool": "crawl_url",
            "incident_id": "pg-" + "b" * 32, "policy_id": "default", **metadata,
        }},
    }


@pytest.fixture
def configured(tmp_path, monkeypatch):
    options = {
        "PROMPT_GUARD_ENABLED": "true", "PROMPT_GUARD_ALERTS_ENABLED": "true",
        "PROMPT_GUARD_ALERT_THRESHOLD": "0.95", "PROMPT_GUARD_ALERT_COOLDOWN_SECONDS": "3600",
    }
    monkeypatch.setattr(config_loader, "_load_mode_config", lambda _mode: options.copy())
    paths = {mode: tmp_path / f"{mode}.db" for mode in ("cloud", "local")}
    for path in paths.values():
        with sqlite3.connect(path) as connection:
            connection.execute(SCHEMA)
    handles = []

    def database(mode):
        handle = SimpleNamespace(db_path=str(paths[mode]), close=Mock())
        handles.append(handle)
        return handle

    monkeypatch.setattr(alert_manager, "get_memory_db", database)
    speech = Mock()
    monkeypatch.setattr(alert_manager.AlertManager, "_speak_alert", speech)

    def publish(*, mode="cloud", source="crawl_url", observation=None, result=None, digest=DIGEST, **overrides):
        with config_scope(mode, overrides=overrides):
            return alerts.notify_prompt_guard_block(
                source, observation if observation is not None else observed(),
                result if result is not None else withheld(), text_digest=digest,
            )

    def rows(mode="cloud"):
        with sqlite3.connect(paths[mode]) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute("SELECT * FROM alerts ORDER BY id")]

    return SimpleNamespace(publish=publish, rows=rows, paths=paths, options=options,
                           handles=handles, speech=speech)


def test_real_alert_manager_gets_only_safe_metadata_and_keeps_scope(configured):
    result = withheld(url="https://private.invalid/token?key=secret", text="ATTACK-TEXT", error="SECRET-ERROR")
    before = deepcopy(result)
    environment = dict(os.environ)
    receipt = configured.publish(mode="local", result=result)
    assert receipt == {"alert_id": 1, "duplicate_suppressed": False}
    assert not configured.rows("cloud")
    row = configured.rows("local")[0]
    assert row["source"] == "prompt_guard" and row["severity"] == "high" and row["status"] == "pending"
    metadata = json.loads(row["metadata"])
    assert metadata["mode"] == "local" and metadata["source_name"] == "crawl_url"
    assert metadata["incident_id"] == "pg-" + "b" * 32
    assert metadata["policy_id"] == "default"
    assert metadata["score"] == 0.97 and metadata["block_threshold"] == 0.8
    assert metadata["alert_threshold"] == 0.95
    rendered = json.dumps(row)
    assert not any(value in rendered for value in ("private.invalid", "ATTACK-TEXT", "SECRET-ERROR"))
    assert result == before and dict(os.environ) == environment
    configured.handles[0].close.assert_called_once()
    configured.speech.assert_called_once_with(
        1, row["title"], "high", description=row["description"], source="prompt_guard",
    )


@pytest.mark.parametrize("score,threshold,publishes", [(0.94, 0.8, False), (0.95, 0.8, True), (0.99, 1.0, False)])
def test_alert_floor_is_independent_of_block_threshold(configured, score, threshold, publishes):
    assert bool(configured.publish(observation=observed(score, threshold))) is publishes
    assert bool(configured.rows()) is publishes


@pytest.mark.parametrize("fields", [
    {"status": "unknown"}, {"status": "skipped"}, {"status": "disabled"}, {"flagged": False},
    {"coverage_complete": None}, {"coverage_complete": False}, {"windows_scanned": None},
    {"windows_scanned": 0}, {"windows_scanned": True}, {"injection_score": None},
    {"injection_score": float("nan")}, {"injection_score": True}, {"threshold": None},
])
def test_unattested_or_unflagged_scan_never_creates_alert(configured, fields):
    assert configured.publish(observation=replace(observed(), **fields)) is None
    assert not configured.handles and not configured.rows()


@pytest.mark.parametrize("changes", [
    {"ok": True}, {"terminal_failure": False}, {"retry_safe": True},
    {"error_code": "scan_unavailable"}, {"data": {}},
    {"data": {"prompt_guard": {"content_withheld": False}}},
])
def test_only_a_completed_withholding_decision_is_eligible(configured, changes):
    assert configured.publish(result={**withheld(), **changes}) is None
    assert not configured.handles


@pytest.mark.parametrize("overrides", [
    {"PROMPT_GUARD_ENABLED": "false"}, {"PROMPT_GUARD_ALERTS_ENABLED": "false"},
    {"PROMPT_GUARD_ALERT_THRESHOLD": "bad"}, {"PROMPT_GUARD_ALERT_THRESHOLD": "nan"},
    {"PROMPT_GUARD_ALERT_THRESHOLD": "1.1"}, {"PROMPT_GUARD_ALERT_THRESHOLD": "0.99"},
    {"PROMPT_GUARD_ALERT_COOLDOWN_SECONDS": "-1"}, {"PROMPT_GUARD_ALERT_COOLDOWN_SECONDS": "bad"},
])
def test_disabled_or_invalid_alert_policy_leaves_withholding_unchanged(configured, overrides):
    result = withheld()
    before = deepcopy(result)
    assert configured.publish(result=result, **overrides) is None
    assert result == before and not configured.handles


def test_alerts_are_opt_in_even_when_prompt_guard_is_enabled(configured):
    configured.options.pop("PROMPT_GUARD_ALERTS_ENABLED")
    assert configured.publish() is None
    assert not configured.handles


def test_pending_dedupe_and_recent_handled_alert_cooldown_survive_new_manager(configured):
    first = configured.publish()
    assert configured.publish() == {"alert_id": first["alert_id"], "duplicate_suppressed": True}
    configured.speech.assert_called_once()
    with sqlite3.connect(configured.paths["cloud"]) as connection:
        connection.execute("UPDATE alerts SET status='acknowledged' WHERE id=?", (first["alert_id"],))
    assert configured.publish() == {"alert_id": first["alert_id"], "duplicate_suppressed": True}
    assert len(configured.rows()) == 1
    configured.speech.assert_called_once()
    with sqlite3.connect(configured.paths["cloud"]) as connection:
        connection.execute("UPDATE alerts SET created_at=? WHERE id=?", (
            (datetime.now() - timedelta(hours=2)).isoformat(), first["alert_id"],
        ))
    assert configured.publish() == {"alert_id": 2, "duplicate_suppressed": False}
    assert len(configured.rows()) == 2
    assert configured.speech.call_count == 2


def test_normal_pending_dedupe_remains_when_cooldown_is_disabled(configured):
    assert configured.publish(PROMPT_GUARD_ALERT_COOLDOWN_SECONDS="0")["alert_id"] == 1
    assert configured.publish(PROMPT_GUARD_ALERT_COOLDOWN_SECONDS="0")["duplicate_suppressed"] is True
    assert len(configured.rows()) == 1


def test_source_mode_and_exact_text_digest_are_distinct(configured):
    configured.publish()
    configured.publish(mode="local")
    configured.publish(source="rss_feed")
    configured.publish(digest="c" * 64)
    assert len(configured.rows("cloud")) == 3 and len(configured.rows("local")) == 1


def test_attachment_alert_omits_untrusted_filename_and_policy_identifiers(configured):
    result = withheld(source_type="attachment", incident_id="file:///private/secret", policy_id="https://secret.invalid")
    assert configured.publish(source="web_text_attachment", result=result)
    metadata = json.loads(configured.rows()[0]["metadata"])
    assert metadata["source_type"] == "attachment" and metadata["source_name"] == "web_text_attachment"
    assert "incident_id" not in metadata and "policy_id" not in metadata


@pytest.mark.parametrize("field,value", [("source", "https://secret.invalid"), ("digest", "RAW SOURCE")])
def test_bad_source_and_content_digest_are_not_published(configured, field, value):
    assert configured.publish(**{field: value}) is None
    assert not configured.handles


def test_alert_delivery_failure_and_logging_failure_do_not_modify_rejection(configured, monkeypatch, caplog):
    def fail():
        raise RuntimeError("secret-provider-error")

    monkeypatch.setattr(alert_manager.AlertManager, "create_alert", lambda *args, **kwargs: fail())
    result = withheld()
    before = deepcopy(result)
    with caplog.at_level(logging.WARNING, logger="prompt_guard.alerts"):
        assert configured.publish(result=result) is None
    assert result == before
    assert "keep_withheld" in caplog.text and "secret-provider-error" not in caplog.text
    monkeypatch.setattr(alerts.logger, "warning", lambda *args: fail())
    assert configured.publish(result=result) is None
    assert result == before


def test_another_process_alert_lock_is_nonblocking_and_keeps_rejection(configured):
    configured.publish()
    lock_paths = list(configured.paths['cloud'].parent.glob('cloud.db.prompt-guard-alert.*.lock'))
    assert len(lock_paths) == 1
    result = withheld()
    before = deepcopy(result)
    with FileLock(lock_paths[0], timeout=0):
        assert configured.publish(result=result) is None
    assert result == before and len(configured.rows()) == 1
    configured.speech.assert_called_once()


@pytest.mark.parametrize('mode', ['cloud', 'local'])
@pytest.mark.parametrize('source,digest', [('crawl_url', 'c' * 64), ('rss_feed', DIGEST)])
def test_distinct_block_is_not_dropped_while_first_alert_is_speaking(configured, mode, source, digest):
    started = threading.Event()
    finish = threading.Event()

    def speak(alert_id, *_args, **_kwargs):
        if alert_id == 1:
            started.set()
            assert finish.wait(timeout=10)
        return True

    configured.speech.side_effect = speak
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(configured.publish, mode=mode)
        try:
            assert started.wait(timeout=5)
            # Only the matching block should contend with the ongoing alert.
            assert configured.publish(mode=mode) is None
            second = configured.publish(mode=mode, source=source, digest=digest)
            assert second == {'alert_id': 2, 'duplicate_suppressed': False}
            assert not first.done()
            assert len(configured.rows(mode)) == 2
        finally:
            finish.set()
        assert first.result(timeout=5) == {'alert_id': 1, 'duplicate_suppressed': False}

    assert configured.publish(mode=mode) == {'alert_id': 1, 'duplicate_suppressed': True}
    assert configured.speech.call_count == 2


def test_scope_is_created_without_loading_process_globals(configured, monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    before = dict(os.environ)
    assert alerts.notify_prompt_guard_block("crawl_url", observed(), withheld(), text_digest=DIGEST)
    assert dict(os.environ) == before


@pytest.mark.parametrize("mode,provider", [("cloud", "openai"), ("local", "kokoro")])
@pytest.mark.parametrize("delivered", [True, False])
def test_normal_alert_speech_completes_in_scope_before_return(
    configured, monkeypatch, mode, provider, delivered,
):
    monkeypatch.setattr(alert_manager.AlertManager, "_speak_alert", _REAL_SPEAK_ALERT)
    calls = []

    def speak(manager, message, *, priority, profile, blocking):
        row = configured.rows(mode)[0]
        assert row["spoken"] == 0 and row["spoken_at"] is None
        configured.handles[0].close.assert_not_called()
        calls.append((get_active_config_mode(), get_config_value("TTS_PROVIDER"), message, priority, blocking))
        return delivered

    monkeypatch.setattr(alert_manager.AlertManager, "_speak", speak)
    result = withheld()
    before = deepcopy(result)
    receipt = configured.publish(mode=mode, TTS_PROVIDER=provider, result=result)
    assert receipt == {"alert_id": 1, "duplicate_suppressed": False}
    assert calls == [(mode, provider, "Boss, Urgent alert: Prompt Guard blocked suspicious content", "high", True)]
    row = configured.rows(mode)[0]
    assert row["spoken"] == int(delivered)
    assert bool(row["spoken_at"]) is delivered
    assert result == before
    configured.handles[0].close.assert_called_once()


def test_unexpected_speech_failure_preserves_saved_alert_and_rejection(configured, caplog):
    configured.speech.side_effect = RuntimeError("SECRET-TTS-ERROR")
    result = withheld()
    before = deepcopy(result)
    with caplog.at_level(logging.WARNING, logger="prompt_guard.alerts"):
        assert configured.publish(result=result) is None
    assert result == before
    row = configured.rows()[0]
    assert row["status"] == "pending" and row["spoken"] == 0 and row["spoken_at"] is None
    assert "keep_withheld" in caplog.text and "SECRET-" not in caplog.text
    configured.handles[0].close.assert_called_once()
