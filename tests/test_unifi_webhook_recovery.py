"""Camera timeout recovery must acknowledge the same event without another create."""

import importlib.util
import json
import logging
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

RECEIVER = (
    Path(__file__).resolve().parents[1]
    / "services/unifi-protect-webhook/webhook_receiver.py"
)


@pytest.fixture
def runtime(monkeypatch):
    for key, value in {
        "JARVIS_ALERTS_URL": "http://example.test/api/alerts",
        "JARVIS_API_KEY": "test-key",
        "WEBHOOK_PORT": "5050",
        "ALERT_START_HOUR": "0",
        "ALERT_END_HOUR": "24",
        "COOLDOWN_SECONDS": "60",
        "CREATE_ALERT_TIMEOUT_SECONDS": "15",
        "ACK_ALERT_TIMEOUT_SECONDS": "5",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(logging, "basicConfig", lambda **kwargs: None)
    spec = importlib.util.spec_from_file_location("unifi_recovery_test_receiver", RECEIVER)
    assert spec is not None and spec.loader is not None
    receiver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(receiver)
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(receiver, "time", SimpleNamespace(
        time=lambda: 2_000_000_000.0 + clock.now,
        monotonic=lambda: clock.now,
        sleep=lambda seconds: setattr(clock, "now", clock.now + seconds),
    ))
    event = {
        "alarm": {
            "name": "Person: Test Camera",
            "triggers": [{"key": "person", "device": "TEST-CAMERA", "eventId": "event-123"}],
        },
        "timestamp": 2_000_000_000_000,
    }
    alert = receiver.process_unifi_event(event)["alert"]
    return receiver, clock, alert


@contextmanager
def response(body, status=200):
    yield SimpleNamespace(status=status, read=lambda: json.dumps(body).encode())


def test_camera_success_has_no_recovery_lookup_or_delay(runtime, monkeypatch):
    receiver, clock, alert = runtime
    calls = []

    def urlopen(request, timeout):
        calls.append(request.get_method())
        return response({"alert_id": 17})

    monkeypatch.setattr(receiver, "urlopen", urlopen)
    assert receiver.send_to_jarvis(alert, auto_ack=True) is True
    assert calls == ["POST", "PUT"]
    assert clock.now == 0


def test_late_create_is_found_after_initial_empty_lookup_without_resubmission(runtime, monkeypatch):
    receiver, clock, alert = runtime
    calls = []

    def urlopen(request, timeout):
        calls.append((request.get_method(), request.full_url, timeout))
        if request.get_method() == "POST":
            raise TimeoutError("create still running")
        if request.get_method() == "GET":
            rows = [dict(alert, id=17)] if clock.now >= 2 else []
            return response({"alerts": rows})
        return response({"ok": True})

    monkeypatch.setattr(receiver, "urlopen", urlopen)
    assert receiver.send_to_jarvis(alert, auto_ack=True) is True
    assert [call[0] for call in calls] == ["POST", "GET", "GET", "GET", "PUT"]
    assert calls[-1][1].endswith("/17/acknowledge")
    assert clock.now == 2


def test_known_alert_ack_timeout_retries_only_acknowledgement(runtime, monkeypatch):
    receiver, clock, alert = runtime
    calls = []

    def urlopen(request, timeout):
        calls.append((request.get_method(), request.full_url, timeout))
        if request.get_method() == "POST":
            return response({"alert_id": 17})
        if len(calls) < 4:
            raise TimeoutError("ack response lost")
        return response({"ok": True})

    monkeypatch.setattr(receiver, "urlopen", urlopen)
    assert receiver.send_to_jarvis(alert, auto_ack=True) is True
    assert [call[0] for call in calls] == ["POST", "PUT", "PUT", "PUT"]
    assert all(call[1].endswith("/17/acknowledge") for call in calls[1:])
    assert clock.now == 1


def test_ack_failure_is_reported_and_recovery_time_is_bounded(runtime, monkeypatch):
    receiver, clock, alert = runtime
    calls = []

    def urlopen(request, timeout):
        calls.append((request.get_method(), timeout))
        if request.get_method() == "POST":
            return response({"alert_id": 17})
        clock.now += timeout
        raise TimeoutError("ack unavailable")

    monkeypatch.setattr(receiver, "urlopen", urlopen)
    assert receiver.send_to_jarvis(alert, auto_ack=True) is False
    assert calls == [("POST", 15), ("PUT", 5), ("PUT", 5), ("PUT", 4)]
    assert clock.now == 15  # Initial ack allowance plus ten seconds of recovery.


def test_unavailable_api_does_not_extend_recovery_or_create_again(runtime, monkeypatch):
    receiver, clock, alert = runtime
    calls = []

    def urlopen(request, timeout):
        calls.append((request.get_method(), timeout))
        clock.now += timeout
        raise TimeoutError("API unavailable")

    monkeypatch.setattr(receiver, "urlopen", urlopen)
    assert receiver.send_to_jarvis(alert, auto_ack=True) is False
    assert calls == [("POST", 15), ("GET", 5), ("GET", 4)]
    assert clock.now == 25


@pytest.mark.parametrize("changed", [
    {"source": "other"},
    {"title": "Person: Different Camera"},
    {"severity": "medium"},
    {"event_id": "different-event"},
])
def test_recovery_does_not_match_another_alert(runtime, monkeypatch, changed):
    receiver, clock, alert = runtime
    candidate = deepcopy(alert)
    for key, value in changed.items():
        (candidate["metadata"] if key == "event_id" else candidate)[key] = value
    calls = []

    def urlopen(request, timeout):
        calls.append(request.get_method())
        if request.get_method() == "POST":
            raise TimeoutError("create still running")
        return response({"alerts": [dict(candidate, id=99)]})

    monkeypatch.setattr(receiver, "urlopen", urlopen)
    assert receiver.send_to_jarvis(alert, auto_ack=True) is False
    assert calls.count("POST") == 1
    assert "PUT" not in calls
    assert clock.now == 10


@pytest.mark.parametrize("timestamp,expected", [(2_000_000_000_000, 17), (123, None), (None, None)])
def test_event_without_id_requires_original_timestamp(runtime, monkeypatch, timestamp, expected):
    receiver, _, alert = runtime
    alert["metadata"]["event_id"] = ""
    candidate = deepcopy(alert)
    candidate["metadata"]["timestamp_ms"] = timestamp
    monkeypatch.setattr(receiver, "urlopen", lambda request, timeout: response({
        "alerts": [dict(candidate, id=17)],
    }))
    assert receiver._find_matching_pending_alert_id(alert) == expected


@pytest.mark.parametrize("fail", [False, True])
def test_sensor_delivery_never_acknowledges_or_recovers(runtime, monkeypatch, fail):
    receiver, clock, _ = runtime
    processed = receiver.process_unifi_event({
        "alarm": {
            "name": "Water Leak: Test Sensor",
            "triggers": [{"key": "sensor_water_leak", "device": "TEST-SENSOR", "eventId": "sensor-1"}],
        },
        "timestamp": 2_000_000_000_000,
    })
    assert processed["auto_ack"] is False
    calls = []

    def urlopen(request, timeout):
        calls.append(request.get_method())
        if fail:
            raise TimeoutError("create unavailable")
        return response({"alert_id": 18})

    monkeypatch.setattr(receiver, "urlopen", urlopen)
    assert receiver.send_to_jarvis(processed["alert"], auto_ack=False) is not fail
    assert calls == ["POST"]
    assert clock.now == 0
