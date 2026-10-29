"""Prompt Guard classifications have bounded, scoped, private transport."""

import json
import logging
import sys
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import config_loader  # noqa: E402

from lib import prompt_guard as pg  # noqa: E402

TOKEN = "private-scanner-bearer-token"
TEXT = "private document content which must not appear in diagnostics"
CONFIG = {
    "PROMPT_GUARD_ENABLED": "true",
    "PROMPT_GUARD_URL": "http://scanner.test:8188",
    "PROMPT_GUARD_API_KEY": TOKEN,
}


def scan(text=TEXT, **kwargs):
    return pg.scan_text(text, source_type="tool_result", source_name="crawl_url", **kwargs)


def payload(**changes):
    return {
        "request_id": "provider-request-id",
        "status": "ok",
        "injection_score": 0.1,
        "threshold": 0.8,
        "flagged": False,
        "model": {"id": "Horizon-Labs/prompt-injection-guard-base", "revision": "pinned"},
        "coverage": {"complete": True, "truncated": False, "windows_scanned": 1, "windows_total": 1},
        "elapsed_ms": 25,
        **changes,
    }


class Response:
    def __init__(self, data=None, *, status=200, raw=None, content_type="application/json", blocks=None):
        self.status_code = status
        self.raw = json.dumps(payload() if data is None else data).encode() if raw is None else raw
        self.headers = {"Content-Type": content_type}
        self.blocks = blocks
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def iter_content(self, _size):
        yield from self.blocks if self.blocks is not None else [self.raw]


@pytest.fixture
def transport(monkeypatch):
    config, calls, responses, sessions = dict(CONFIG), [], [], []
    with pg._state_lock:
        pg._states.clear()
    monkeypatch.setattr(pg, "_capacity", threading.BoundedSemaphore(1))
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    monkeypatch.setattr(pg, "get_config_value", lambda key, default=None: config.get(key, default))

    class Session:
        def __init__(self):
            self.trust_env = True
            self.closed = False
            sessions.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.closed = True

        def post(self, url, **kwargs):
            assert self.trust_env is False
            assert kwargs["allow_redirects"] is False
            assert kwargs["stream"] is True
            assert kwargs["headers"]["Authorization"].startswith("Bearer ")
            assert sum(kwargs["timeout"]) <= float(config.get("PROMPT_GUARD_TIMEOUT_SECONDS", 2))
            calls.append((url, kwargs))
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            if callable(response):
                return response()
            return response

    monkeypatch.setattr(pg.requests, "Session", Session)
    return config, calls, responses, sessions


def test_default_disabled_does_not_validate_or_contact_service(transport, caplog):
    config, calls, _, _ = transport
    config.clear()
    caplog.set_level(logging.INFO, logger="prompt_guard")
    for _ in range(3):
        result = scan("")
        assert result.status == "disabled"
        assert result.flagged is None and result.injection_score is None
    assert not calls
    assert caplog.text.count("reason=disabled") == 1


@pytest.mark.parametrize("score,flagged", [(0.1, False), (0.8, True), (1.0, True)])
def test_scan_returns_observation_and_closes_transport(transport, caplog, score, flagged):
    config, calls, responses, sessions = transport
    caplog.set_level(logging.DEBUG, logger="prompt_guard")
    response = Response(payload(injection_score=score, flagged=flagged))
    responses.append(response)
    result = scan()
    assert result.status == "scanned" and result.flagged is flagged
    assert result.injection_score == score and result.threshold == 0.8
    assert result.coverage_complete and result.windows_scanned == 1
    assert result.input_bytes == len(TEXT.encode()) and result.elapsed_ms >= 0
    assert calls[0][0] == config["PROMPT_GUARD_URL"] + "/v1/scan"
    assert calls[0][1]["json"] == {
        "text": TEXT, "threshold": 0.8, "source": {"type": "tool_result", "name": "crawl_url"},
    }
    assert sessions[0].closed and response.closed
    assert "action=reported" in caplog.text
    assert TEXT not in caplog.text and TOKEN not in caplog.text
    with pytest.raises(FrozenInstanceError):
        result.status = "disabled"


@pytest.mark.parametrize("setting,value", [
    ("PROMPT_GUARD_URL", ""),
    ("PROMPT_GUARD_URL", "http://user:password@scanner.test"),
    ("PROMPT_GUARD_URL", "http://scanner.test:bad"),
    ("PROMPT_GUARD_URL", "http://scanner.test:0"),
    ("PROMPT_GUARD_URL", "http://scanner.test:70000"),
    ("PROMPT_GUARD_URL", "http://scanner.test/v1/scan"),
    ("PROMPT_GUARD_URL", "http://scanner.test/?secret=private"),
    ("PROMPT_GUARD_URL", "http://scanner.test/#fragment"),
    ("PROMPT_GUARD_API_KEY", ""),
    ("PROMPT_GUARD_API_KEY", "key\r\ninjected: value"),
    ("PROMPT_GUARD_THRESHOLD", "nan"),
    ("PROMPT_GUARD_THRESHOLD", "1.1"),
    ("PROMPT_GUARD_TIMEOUT_SECONDS", "inf"),
    ("PROMPT_GUARD_TIMEOUT_SECONDS", "0"),
    ("PROMPT_GUARD_MAX_INPUT_BYTES", "invalid"),
    ("PROMPT_GUARD_MAX_INPUT_BYTES", "0"),
])
def test_invalid_configuration_is_unknown_without_network(transport, caplog, setting, value):
    config, calls, _, _ = transport
    config[setting] = value
    result = scan()
    assert result.status == "unknown" and result.reason_code == "invalid_configuration"
    assert result.flagged is None and result.injection_score is None
    assert not calls
    assert TOKEN not in caplog.text and "injected: value" not in caplog.text


@pytest.mark.parametrize("text,reason", [("", "empty_input"), (" \n\t", "empty_input"), ("\ud800", "invalid_text")])
def test_invalid_text_is_skipped(transport, text, reason):
    _, calls, _, _ = transport
    result = scan(text)
    assert result.status == "skipped" and result.reason_code == reason
    assert result.flagged is None and not calls


def test_utf8_byte_limit_skips_whole_input_without_truncation(transport):
    config, calls, responses, _ = transport
    config["PROMPT_GUARD_MAX_INPUT_BYTES"] = "4"
    assert scan("ééé").reason_code == "input_too_large"
    assert not calls
    responses.append(Response())
    result = scan("éé")
    assert result.status == "scanned" and result.input_bytes == 4
    assert calls[0][1]["json"]["text"] == "éé"


@pytest.mark.parametrize("response,reason", [
    (Response(status=301, raw=TOKEN.encode()), "http_301"),
    (Response(status=401, raw=TOKEN.encode()), "http_401"),
    (Response(status=503, raw=TOKEN.encode()), "http_503"),
    (Response(raw=b"<html>" + TOKEN.encode()), "invalid_response"),
    (Response(raw=b"{}", content_type="text/html"), "invalid_response"),
    (requests.exceptions.Timeout(TOKEN), "timeout"),
    (requests.exceptions.ConnectionError(TOKEN), "transport_error"),
    (RuntimeError(TOKEN), "unexpected_error"),
])
def test_failures_are_unknown_no_retries_no_error_leaks(transport, caplog, response, reason):
    _, calls, responses, sessions = transport
    responses.append(response)
    result = scan()
    assert result.status == "unknown" and result.reason_code == reason
    assert result.flagged is None and result.injection_score is None
    assert len(calls) == 1 and sessions[0].closed
    assert TOKEN not in caplog.text and TEXT not in caplog.text
    assert scan().reason_code == "cooldown"
    assert len(calls) == 1
    if isinstance(response, Response):
        assert response.closed


@pytest.mark.parametrize("changes", [
    {"status": "error"},
    {"injection_score": True},
    {"injection_score": -0.01},
    {"injection_score": 1.01},
    {"injection_score": float("nan")},
    {"injection_score": float("inf")},
    {"threshold": True},
    {"threshold": 0.5},
    {"flagged": "false"},
    {"flagged": True},
    {"coverage": {"complete": False, "truncated": False, "windows_scanned": 1, "windows_total": 1}},
    {"coverage": {"complete": True, "truncated": True, "windows_scanned": 1, "windows_total": 1}},
    {"coverage": {"complete": 1, "truncated": False, "windows_scanned": 1, "windows_total": 1}},
    {"coverage": {"complete": True, "truncated": False, "windows_scanned": 1, "windows_total": 2}},
    {"coverage": {"complete": True, "truncated": False, "windows_scanned": True, "windows_total": 1}},
    {"coverage": {"complete": True, "truncated": False, "windows_scanned": 0, "windows_total": 0}},
])
def test_response_validation_never_mislabels_unknown_content_clean(transport, changes):
    _, _, responses, _ = transport
    responses.append(Response(payload(**changes)))
    result = scan()
    assert result.status == "unknown" and result.reason_code == "invalid_response"
    assert result.flagged is None and result.injection_score is None
    assert result.coverage_complete is None


def test_bounded_stream_and_elapsed_observation(transport, monkeypatch):
    _, _, responses, _ = transport
    monkeypatch.setattr(pg, "MAX_RESPONSE_BYTES", 64)
    response = Response(blocks=[b"a" * 32, b"b" * 33])
    responses.append(response)
    assert scan().reason_code == "response_too_large"
    assert response.closed


def test_slow_stream_is_unknown_and_closed(transport, monkeypatch):
    _, _, responses, _ = transport
    now = [100.0]
    monkeypatch.setattr(pg.time, "monotonic", lambda: now[0])

    class SlowResponse(Response):
        def iter_content(self, _size):
            now[0] += 3
            yield self.raw

    response = SlowResponse()
    responses.append(response)
    result = scan()
    assert result.status == "unknown" and result.reason_code == "timeout"
    assert response.closed


def test_busy_observer_skips_without_waiting_or_network(transport):
    _, calls, _, _ = transport
    pg._capacity.acquire()
    try:
        result = scan()
    finally:
        pg._capacity.release()
    assert result.status == "skipped" and result.reason_code == "busy" and not calls


def test_cooldown_is_bounded_and_credentials_change_recovers(transport, caplog, monkeypatch):
    config, calls, responses, _ = transport
    caplog.set_level(logging.INFO, logger="prompt_guard")
    now = [100.0]
    monkeypatch.setattr(pg.time, "monotonic", lambda: now[0])
    responses.append(requests.exceptions.Timeout(TOKEN))
    assert scan().reason_code == "timeout"
    assert scan().reason_code == "cooldown"
    assert len(calls) == 1 and caplog.text.count("reason=timeout") == 1
    config["PROMPT_GUARD_API_KEY"] = "replacement-private-token"
    responses.append(Response())
    assert scan().status == "scanned"
    config["PROMPT_GUARD_API_KEY"] = TOKEN
    now[0] += 31
    responses.append(Response())
    assert scan().status == "scanned"
    assert "reason=recovered" in caplog.text
    assert TOKEN not in caplog.text
    assert "replacement-private-token" not in caplog.text


def test_backend_state_does_not_grow_without_bound(transport, monkeypatch):
    config, _, responses, _ = transport
    monkeypatch.setattr(pg, "MAX_BACKENDS", 3)
    for index in range(6):
        config["PROMPT_GUARD_API_KEY"] = f"private-key-{index}"
        responses.append(Response())
        assert scan().status == "scanned"
    assert len(pg._states) == 3


def test_configuration_helpers_are_current_and_safe(transport):
    config, _, _, _ = transport
    assert pg.is_enabled() and pg.get_max_input_bytes() == 8192
    config["PROMPT_GUARD_ENABLED"] = "false"
    config["PROMPT_GUARD_MAX_INPUT_BYTES"] = "not-integer"
    assert not pg.is_enabled() and pg.get_max_input_bytes() == 8192
    config["PROMPT_GUARD_MAX_INPUT_BYTES"] = str(pg.MAX_INPUT_BYTES + 1)
    assert pg.get_max_input_bytes() == 8192
    config["PROMPT_GUARD_MAX_INPUT_BYTES"] = "1234"
    assert pg.get_max_input_bytes() == 1234


def test_explicit_mode_is_scoped_and_matching_overrides_are_preserved(transport, monkeypatch):
    _, calls, responses, _ = transport
    modes = {
        mode: {**CONFIG, "PROMPT_GUARD_URL": f"http://{mode}.test", "PROMPT_GUARD_API_KEY": f"{mode}-secret"}
        for mode in ("cloud", "local")
    }
    monkeypatch.setattr(config_loader, "_load_mode_config", lambda mode: dict(modes[mode]))
    monkeypatch.setattr(pg, "get_config_value", config_loader.get_config_value)
    responses.extend([Response(), Response()])
    with config_loader.config_scope("cloud", overrides={"PROMPT_GUARD_THRESHOLD": "0.8"}):
        assert scan(mode="cloud").status == "scanned"
        assert scan(mode="local").status == "scanned"
        assert pg.get_active_config_mode() == "cloud"
    assert calls[0][0] == "http://cloud.test/v1/scan"
    assert calls[1][0] == "http://local.test/v1/scan"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer cloud-secret"
    assert calls[1][1]["headers"]["Authorization"] == "Bearer local-secret"
    with config_loader.config_scope("cloud", overrides={"PROMPT_GUARD_ENABLED": "false"}):
        assert scan(mode="cloud").status == "disabled"
    assert len(calls) == 2


def test_source_labels_cannot_be_arbitrary_external_text(transport):
    _, calls, _, _ = transport
    result = pg.scan_text(TEXT, source_type="tool_result", source_name="https://private.test/page")
    assert result.status == "skipped" and result.reason_code == "invalid_source"
    assert not calls


def test_concurrent_mode_scopes_do_not_share_url_or_authorization(transport, monkeypatch):
    _, calls, responses, _ = transport
    modes = {
        mode: {**CONFIG, "PROMPT_GUARD_URL": f"http://{mode}.test", "PROMPT_GUARD_API_KEY": f"{mode}-secret"}
        for mode in ("cloud", "local")
    }
    monkeypatch.setattr(config_loader, "_load_mode_config", lambda mode: dict(modes[mode]))
    monkeypatch.setattr(pg, "get_config_value", config_loader.get_config_value)
    monkeypatch.setattr(pg, "_capacity", threading.BoundedSemaphore(2))
    barrier = threading.Barrier(2)

    def delayed_response():
        barrier.wait(timeout=2)
        return Response()

    responses.extend([delayed_response, delayed_response])
    results = []

    def run(mode):
        with config_loader.config_scope(mode):
            results.append(scan(mode=mode))

    threads = [threading.Thread(target=run, args=(mode,)) for mode in ("cloud", "local")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
        assert not thread.is_alive()
    assert len(results) == 2 and all(result.status == "scanned" for result in results)
    by_url = {url: kwargs["headers"]["Authorization"] for url, kwargs in calls}
    assert by_url == {
        "http://cloud.test/v1/scan": "Bearer cloud-secret",
        "http://local.test/v1/scan": "Bearer local-secret",
    }


def test_unexpected_configuration_failure_is_fail_open(transport, monkeypatch, caplog):
    _, calls, _, _ = transport

    def broken_config(_key, _default=None):
        raise RuntimeError(TOKEN)

    monkeypatch.setattr(pg, "get_config_value", broken_config)
    result = scan()
    assert result.status == "unknown" and result.reason_code == "observer_error"
    assert not calls and TOKEN not in caplog.text


@pytest.mark.parametrize("configuration_broken", [False, True])
def test_broken_log_handler_never_interrupts_observation(transport, monkeypatch, configuration_broken):
    _, calls, responses, _ = transport

    class BrokenHandler(logging.Handler):
        def emit(self, _record):
            raise RuntimeError(TOKEN)

    def broken_config(_key, _default=None):
        raise RuntimeError(TOKEN)

    if configuration_broken:
        monkeypatch.setattr(pg, "get_config_value", broken_config)
    else:
        responses.append(Response(payload(injection_score=0.99, flagged=True)))
    handler = BrokenHandler()
    pg.logger.addHandler(handler)
    try:
        result = scan()
    finally:
        pg.logger.removeHandler(handler)
    if configuration_broken:
        assert result.status == "unknown" and result.reason_code == "observer_error"
        assert not calls
    else:
        assert result.status == "scanned" and result.flagged is True
        assert len(calls) == 1


def test_observer_uses_the_same_shared_client_module():
    from lib import prompt_guard_observer

    assert prompt_guard_observer.scan_text is pg.scan_text


def test_validated_forensic_metadata_is_retained_without_raw_fields(transport, caplog):
    _, _, responses, _ = transport
    caplog.set_level(logging.DEBUG, logger="prompt_guard")
    request_id = "f9385181-572d-41f4-a74a-d5558177fffa"
    model_id = "Horizon-Labs/prompt-injection-guard-base"
    revision = "f95005bbceac345aafec1620719857c6202eabd5"
    responses.append(Response(payload(
        request_id=request_id,
        model={"id": model_id, "revision": revision, "raw_debug": TOKEN},
        raw_debug=TEXT,
    )))
    result = scan()
    assert result.status == "scanned" and result.flagged is False
    assert result.service_request_id == request_id
    assert result.model_id == model_id and result.model_revision == revision
    assert TOKEN not in repr(result) and TEXT not in repr(result)
    assert TOKEN not in caplog.text and TEXT not in caplog.text


@pytest.mark.parametrize("metadata,expected", [
    ({"request_id": None, "model": None}, (None, None, None)),
    ({"request_id": "not-a-uuid", "model": {}}, (None, None, None)),
    ({"request_id": True, "model": True}, (None, None, None)),
    ({"request_id": "a" * 300, "model": {"id": "a" * 300, "revision": "a" * 300}},
     (None, None, None)),
    ({"request_id": "\n" + TOKEN, "model": {"id": "https://attacker.test/" + TOKEN,
                                            "revision": "<script>" + TOKEN}}, (None, None, None)),
    ({"model": {"id": "Horizon-Labs/prompt-injection-guard-base", "revision": "invalid"}},
     (None, "Horizon-Labs/prompt-injection-guard-base", None)),
])
def test_missing_or_invalid_metadata_does_not_invalidate_classification(transport, caplog, metadata, expected):
    _, _, responses, _ = transport
    responses.append(Response(payload(injection_score=0.99, flagged=True, **metadata)))
    result = scan()
    assert result.status == "scanned" and result.flagged is True
    assert (result.service_request_id, result.model_id, result.model_revision) == expected
    assert TOKEN not in caplog.text and TEXT not in caplog.text


def window_diagnostics(**changes):
    return {
        "version": 1, "aggregation": "max", "representation": "raw_text_v1",
        "winning_window_index": 0, "offset_unit": "unicode_code_points",
        "windows": [{"index": 0, "content_token_start": 0, "content_token_end": 4,
                     "char_start": 0, "char_end": len(TEXT), "injection_score": 0.99}],
        **changes,
    }


@pytest.mark.parametrize("setting,expected", [(None, False), ("false", False),
                                               ("invalid", False), ("true", True)])
def test_window_diagnostics_request_is_opt_in_without_extra_calls(transport, setting, expected):
    config, calls, responses, _ = transport
    if setting is not None:
        config["PROMPT_GUARD_RETURN_WINDOWS"] = setting
    responses.append(Response())  # Older responses omit the optional object.
    result = scan()
    assert result.status == "scanned" and result.diagnostics is None
    assert len(calls) == 1
    assert calls[0][1]["json"].get("return_windows", False) is expected
    if not expected:
        assert "return_windows" not in calls[0][1]["json"]


def test_valid_diagnostics_survive_transport_without_text_or_extra_fields(transport, caplog):
    config, calls, responses, _ = transport
    config["PROMPT_GUARD_RETURN_WINDOWS"] = "true"
    caplog.set_level(logging.DEBUG, logger="prompt_guard")
    diag = window_diagnostics(raw_debug=TOKEN)
    diag["windows"][0]["text"] = TEXT
    responses.append(Response(payload(injection_score=0.99, flagged=True, diagnostics=diag)))
    result = scan()
    assert calls[0][1]["json"]["return_windows"] is True
    assert result.status == "scanned" and result.flagged is True
    assert result.diagnostics is not None
    assert result.diagnostics.winning_window_index == 0
    assert result.diagnostics.windows[0].char_end == len(TEXT)
    assert TOKEN not in repr(result.diagnostics) and TEXT not in repr(result.diagnostics)
    assert "diagnostics=" not in repr(result)
    assert TEXT not in caplog.text and TOKEN not in caplog.text


@pytest.mark.parametrize("diagnostics", [None, {}, "untrusted", window_diagnostics(version=True),
                                          window_diagnostics(winning_window_index=20),
                                          window_diagnostics(offset_unit="utf16")])
def test_bad_diagnostics_do_not_turn_a_valid_detection_into_fail_open(transport, diagnostics):
    config, calls, responses, _ = transport
    config["PROMPT_GUARD_RETURN_WINDOWS"] = "true"
    responses.append(Response(payload(injection_score=0.99, flagged=True, diagnostics=diagnostics)))
    result = scan()
    assert result.status == "scanned" and result.flagged is True
    assert result.diagnostics is None and len(calls) == 1


def test_diagnostics_flag_follows_mode_and_request_scope(transport, monkeypatch):
    _, calls, responses, _ = transport
    modes = {
        "cloud": {**CONFIG, "PROMPT_GUARD_RETURN_WINDOWS": "true"},
        "local": {**CONFIG, "PROMPT_GUARD_RETURN_WINDOWS": "false"},
    }
    monkeypatch.setattr(config_loader, "_load_mode_config", lambda mode: dict(modes[mode]))
    monkeypatch.setattr(pg, "get_config_value", config_loader.get_config_value)
    responses.extend([Response(), Response(), Response()])
    with config_loader.config_scope("cloud"):
        assert scan().status == "scanned"
        assert scan(mode="local").status == "scanned"
    with config_loader.config_scope("cloud", overrides={"PROMPT_GUARD_RETURN_WINDOWS": "false"}):
        assert scan().status == "scanned"
    assert [kwargs["json"].get("return_windows") for _, kwargs in calls] == [True, None, None]


def test_old_service_rejection_does_not_trigger_an_automatic_rescan(transport):
    config, calls, responses, _ = transport
    config["PROMPT_GUARD_RETURN_WINDOWS"] = "true"
    responses.append(Response(status=422))
    result = scan()
    assert result.status == "unknown" and result.reason_code == "http_422"
    assert len(calls) == 1


@pytest.mark.parametrize("valid_diagnostics", [True, False])
def test_full_boundary_saves_only_private_diagnostics_and_keeps_detection(
    transport, tmp_path, valid_diagnostics,
):
    from lib import prompt_guard_observer as observer

    config, calls, responses, _ = transport
    config["PROMPT_GUARD_RETURN_WINDOWS"] = "true"
    original = {"ok": True, "speech": TEXT, "data": {"content": TEXT}, "completion": "completed"}
    text = observer._serialize_content(original, 8192)
    diag = window_diagnostics()
    diag["windows"][0]["char_end"] = len(text) if valid_diagnostics else len(text) + 1
    diag["raw_debug"] = TOKEN
    responses.append(Response(payload(injection_score=0.99, flagged=True, diagnostics=diag)))
    with config_loader.config_scope("cloud", overrides={"PROMPT_GUARD_INCIDENT_DIR": str(tmp_path)}):
        result = observer.review_tool_result("crawl_url", original)
    assert result["error_code"] == "prompt_injection_detected"
    assert result["retry_safe"] is False and result["completion"] == "completed"
    assert original["speech"] == TEXT and len(calls) == 1
    exposed = json.dumps(result)
    assert TEXT not in exposed and TOKEN not in exposed and "diagnostics" not in exposed
    report = json.loads(next((tmp_path / "cloud").glob("pg-*.json")).read_text())
    assert report["evidence"]["text"] == text
    assert ("diagnostics" in report["scan"]) is valid_diagnostics
    if valid_diagnostics:
        assert report["scan"]["diagnostics"]["windows"][0]["char_end"] == len(text)
    assert TOKEN not in json.dumps(report)
