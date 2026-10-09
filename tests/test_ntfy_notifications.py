import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from filelock import FileLock

from lib import ntfy_notifications as ntfy


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


@pytest.fixture
def setup(tmp_path):
    (tmp_path / "data").mkdir()
    with closing(sqlite3.connect(tmp_path / "data/jarvis_memory.db")) as conn:
        conn.executescript("""
            CREATE TABLE alerts (id INTEGER PRIMARY KEY, title TEXT, description TEXT,
                severity TEXT, status TEXT, created_at TEXT);
            CREATE TABLE reminders (id INTEGER PRIMARY KEY, title TEXT, description TEXT,
                status TEXT, triggered_at TEXT);
        """)
    with closing(sqlite3.connect(tmp_path / "data/background_tasks.db")) as conn:
        conn.executescript("""
            CREATE TABLE jobs (id TEXT PRIMARY KEY, admission_json TEXT, mode TEXT,
                state TEXT, updated_at REAL, cancelled INTEGER DEFAULT 0,
                cancel_requested INTEGER DEFAULT 0, expired INTEGER DEFAULT 0, archived_at REAL);
        """)
    config = ntfy.validate_config({
        "enabled": True, "server_url": "https://ntfy.example.com",
        "publisher_token": "tk_" + "a" * 29,
    })
    now = [1800000000.0]
    sent = []
    worker = ntfy.NotificationWorker(
        tmp_path, "cloud", sender=lambda config, payload: sent.append(payload) or "receipt",
        clock=lambda: now[0],
    )
    return tmp_path, config, now, sent, worker


def sql(root, query, args=(), *, tasks=False):
    path = root / "data" / ("background_tasks.db" if tasks else "jarvis_memory.db")
    with closing(sqlite3.connect(path)) as conn, conn:
        return conn.execute(query, args).fetchall()


def alert(root, now, ident=1, severity="high", status="pending"):
    sql(root, "INSERT INTO alerts VALUES(?,?,?,?,?,?)",
        (ident, "Road closure", "Private location detail", severity, status, iso(now)))


def states(root):
    with closing(sqlite3.connect(root / "data/ntfy_notifications.db")) as conn:
        return conn.execute("SELECT state,attempts,payload FROM deliveries ORDER BY event_key").fetchall()


def test_baseline_filters_dedupes_and_keeps_producers_unchanged(setup):
    root, config, now, sent, worker = setup
    alert(root, now[0])
    worker.cycle(config)
    assert sent == []
    now[0] += 1
    alert(root, now[0], 2, "medium")
    alert(root, now[0], 3, "high")
    alert(root, now[0], 4, "critical")
    alert(root, now[0], 5, "critical", "auto_resolved")
    stats = worker.cycle(config)
    assert stats["delivered"] == 2
    assert [x["priority"] for x in sent] == [4, 5]
    assert all(x["message"] == "Road closure" for x in sent)
    assert all(row[2] is None for row in states(root))
    # Restart uses the same receipts; it never acknowledges or changes source speech/status.
    ntfy.NotificationWorker(root, "cloud", sender=worker.sender, clock=worker.clock).cycle(config)
    assert len(sent) == 2
    assert sql(root, "SELECT status FROM alerts WHERE id=3") == [("pending",)]


def test_retry_then_resolve_or_expire_suppresses_phone_message(setup):
    root, config, now, sent, worker = setup
    worker.cycle(config)
    now[0] += 1
    alert(root, now[0])
    alert(root, now[0], 2)

    def failed(*_):
        raise ntfy.DeliveryError("ntfy URLError")

    worker.sender = failed
    assert worker.cycle(config)["errors"] == ["ntfy URLError", "ntfy URLError"]
    assert all(row[:2] == ("pending", 1) for row in states(root))
    sql(root, "UPDATE alerts SET status='auto_resolved' WHERE id=1")
    now[0] += 31
    worker.sender = lambda config, payload: sent.append(payload) or "retry-receipt"
    assert worker.cycle(config)["delivered"] == 1
    assert [row[0] for row in states(root)] == ["suppressed", "delivered"]
    alert(root, now[0] - 1900, 3)
    worker.cycle(config)
    assert len(sent) == 1


def test_reminders_observe_triggered_and_recurring_occurrences(setup):
    root, config, now, sent, worker = setup
    sql(root, "INSERT INTO reminders VALUES(1,'Take medicine','Detail','scheduled',NULL)")
    sql(root, "INSERT INTO reminders VALUES(2,'Old reminder','Detail','triggered',?)", (iso(now[0]-60),))
    worker.cycle(config)
    assert not sent
    now[0] += 30
    # Recurring scheduler stores triggered_at while keeping the next occurrence scheduled.
    sql(root, "UPDATE reminders SET triggered_at=? WHERE id=1", (iso(now[0]),))
    worker.cycle(config)
    assert len(sent) == 1 and sent[0]["title"] == "Reminder: Take medicine"
    worker.cycle(config)
    assert len(sent) == 1
    now[0] += 60
    sql(root, "UPDATE reminders SET triggered_at=? WHERE id=1", (iso(now[0]),))
    worker.cycle(config)
    assert len(sent) == 2
    assert sql(root, "SELECT status FROM reminders WHERE id=1") == [("scheduled",)]


def test_cancelled_reminder_and_changed_occurrence_do_not_retry(setup):
    root, config, now, sent, worker = setup
    worker.cycle(config)
    now[0] += 1
    sql(root, "INSERT INTO reminders VALUES(1,'Reminder',NULL,'triggered',?)", (iso(now[0]),))
    worker.sender = lambda *_: (_ for _ in ()).throw(ntfy.DeliveryError("ntfy HTTP 429"))
    worker.cycle(config)
    sql(root, "UPDATE reminders SET status='acknowledged' WHERE id=1")
    now[0] += 31
    worker.cycle(config)
    assert states(root)[0][0] == "suppressed" and not sent


def test_disable_reenable_has_fresh_baseline_and_no_backlog(setup):
    root, config, now, sent, worker = setup
    worker.cycle(config)
    config["alerts"]["enabled"] = False
    worker.cycle(config)
    alert(root, now[0])
    config["alerts"]["enabled"] = True
    worker.cycle(config)
    assert not sent
    now[0] += 1
    alert(root, now[0], 2)
    worker.cycle(config)
    assert len(sent) == 1
    config["enabled"] = False
    worker.cycle(config)
    alert(root, now[0], 3)
    config["enabled"] = True
    worker.cycle(config)
    assert len(sent) == 1


def test_background_tasks_opt_in_mode_scoped_and_no_results_forwarded(setup):
    root, config, now, sent, worker = setup
    sql(root, "INSERT INTO jobs(id,admission_json,mode,state,updated_at) VALUES(?,?,?,?,?)",
        ("old", '{"tool":"generate_image","arguments":{"prompt":"secret"}}',
         "cloud", "succeeded", now[0]), tasks=True)
    worker.cycle(config)
    config["background_tasks"]["enabled"] = True
    worker.cycle(config)
    assert not sent
    now[0] += 1
    for ident, mode in (("new", "cloud"), ("local", "local")):
        sql(root, "INSERT INTO jobs(id,admission_json,mode,state,updated_at) VALUES(?,?,?,?,?)",
            (ident, '{"tool":"generate_image","arguments":{"prompt":"secret"}}',
             mode, "succeeded", now[0]), tasks=True)
    worker.cycle(config)
    assert len(sent) == 1 and sent[0]["title"] == "generate_image: succeeded"
    assert "secret" not in json.dumps(sent)
    now[0] += 2
    sql(root, "UPDATE jobs SET updated_at=? WHERE id IN ('new','old')", (now[0],), tasks=True)
    worker.cycle(config)
    assert len(sent) == 1


def test_source_failure_isolated_and_pending_retries_wait_for_source(setup):
    root, config, now, sent, worker = setup
    worker.cycle(config)
    now[0] += 1
    alert(root, now[0])
    worker.sender = lambda *_: (_ for _ in ()).throw(ntfy.DeliveryError("ntfy HTTP 503"))
    worker.cycle(config)
    original = root / "data/jarvis_memory.db"
    original.rename(root / "data/temporarily-offline.db")
    config["background_tasks"]["enabled"] = True
    worker.cycle(config)
    now[0] += 31
    sql(root, "INSERT INTO jobs(id,admission_json,mode,state,updated_at) VALUES(?,?,?,?,?)",
        ("job", '{"tool":"generate_video"}', "cloud", "failed", now[0]), tasks=True)
    worker.sender = lambda config, payload: sent.append(payload) or "receipt"
    stats = worker.cycle(config)
    assert stats["errors"] and stats["delivered"] == 1
    assert not original.exists()  # Read-only connection cannot create a new source DB.
    (root / "data/temporarily-offline.db").rename(original)
    worker.cycle(config)
    assert len(sent) == 2


def test_bad_record_does_not_drop_other_alerts_and_batch_cursor_advances(setup):
    root, config, now, sent, worker = setup
    worker.cycle(config)
    now[0] += 1
    for ident in range(1, 502):
        alert(root, now[0], ident, "medium")
    sql(root, "UPDATE alerts SET severity='high',created_at='unreadable' WHERE id=1")
    sql(root, "UPDATE alerts SET severity='high' WHERE id=501")
    assert worker.cycle(config)["errors"] == ["alerts invalid record"]
    assert not sent
    worker.cycle(config)
    assert len(sent) == 1


def test_private_config_and_state_and_disabled_fresh_clone(setup, tmp_path):
    root, config, now, sent, worker = setup
    config_path = root / "config.json"
    config_path.write_text(json.dumps(config))
    config_path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        ntfy.load_config(config_path)
    config_path.chmod(0o600)
    assert ntfy.load_config(config_path)["enabled"]
    worker.cycle(config)
    assert worker.state_path.stat().st_mode & 0o777 == 0o600
    fresh_root = root / "fresh"
    fresh = ntfy.NotificationWorker(fresh_root, "cloud")
    assert fresh.cycle(ntfy.load_config(fresh_root / "missing.json"))["errors"] == []
    assert not fresh.state_path.exists()


@pytest.mark.parametrize("origin", [
    "http://ntfy.example.com", "https://user:pass@ntfy.example.com",
    "https://ntfy.example.com/path", "https://ntfy.example.com?key=secret",
])
def test_rejects_unsafe_origins(origin):
    with pytest.raises(ValueError, match="HTTPS"):
        ntfy.validate_config({"enabled": True, "server_url": origin})


def test_receipt_validation_redirects_and_safe_errors(setup, monkeypatch):
    _, config, _, _, _ = setup
    payload = {"topic": "jarvis-test", "message": "test"}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, _):
            return json.dumps({"event": "message", "id": "abc", "topic": "wrong"}).encode()

    class Opener:
        def open(self, request, timeout):
            assert request.get_header("Authorization") == "Bearer " + config["publisher_token"]
            assert timeout == 10
            return Response()

    monkeypatch.setattr(ntfy.urllib.request, "build_opener", lambda *_: Opener())
    with pytest.raises(ntfy.DeliveryError, match="receipt"):
        ntfy.publish(config, payload)
    assert ntfy.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other") is None

    class FailingOpener:
        def open(self, *_args, **_kwargs):
            raise ntfy.urllib.error.HTTPError("https://secret", 401, config["publisher_token"], {}, None)

    monkeypatch.setattr(ntfy.urllib.request, "build_opener", lambda *_: FailingOpener())
    with pytest.raises(ntfy.DeliveryError) as caught:
        ntfy.publish(config, payload)
    assert str(caught.value) == "ntfy HTTP 401" and not caught.value.retryable


def test_worker_refuses_second_instance_before_reading_config(tmp_path, monkeypatch):
    from services import ntfy_notifications as service

    (tmp_path / "data").mkdir()
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(service.sys, "argv", ["worker", "--once"])
    with FileLock(tmp_path / "data/ntfy_notifications.db.lock"):
        assert service.main() == 1
    assert not (tmp_path / "data/ntfy_notifications.db").exists()


def test_failed_delivery_retries_are_bounded_and_privacy_change_applies(setup):
    root, config, now, sent, worker = setup
    config["include_descriptions"] = True
    config["max_attempts"] = 2
    worker.cycle(config)
    now[0] += 1
    alert(root, now[0])

    def unavailable(config, payload):
        sent.append(payload)
        raise ntfy.DeliveryError("ntfy HTTP 503")

    worker.sender = unavailable
    worker.cycle(config)
    assert sent[0]["message"] == "Private location detail"
    config["include_descriptions"] = False
    now[0] += 31
    worker.cycle(config)
    assert sent[1]["message"] == "Road closure"
    assert states(root) == [("failed", 2, None)]
    now[0] += 100
    worker.cycle(config)
    assert len(sent) == 2


def test_example_and_private_config_are_correctly_distributed():
    root = Path(__file__).resolve().parents[1]
    example = ntfy.validate_config(
        json.loads((root / "config/ntfy.json.example").read_text())
    )
    assert not example["enabled"] and not example["background_tasks"]["enabled"]
    for filename in (".gitignore", ".dockerignore"):
        assert "config/ntfy.json" in (root / filename).read_text().splitlines()
    for filename in ("bin/jarvis-services", "docker/services.sh"):
        assert "services/ntfy_notifications.py" in (root / filename).read_text()
