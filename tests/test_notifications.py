"""Explicit notification persistence, provider boundaries, and delivery receipts."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from types import SimpleNamespace

import pytest

from lib import notifications
from lib import ntfy_notifications as ntfy


@pytest.fixture
def setup(tmp_path, monkeypatch):
    now = [1800000000.0]
    monkeypatch.setattr(notifications, "time", SimpleNamespace(time=lambda: now[0]))
    config = ntfy.validate_config(
        {
            "enabled": True,
            "server_url": "https://ntfy.example.test",
            "publisher_token": "tk_" + "a" * 29,
            "alerts": {"enabled": False},
            "reminders": {"enabled": False},
            "background_tasks": {"enabled": False},
        }
    )
    folder = tmp_path / "config"
    folder.mkdir()
    path = folder / "ntfy.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    store = notifications.NotificationStore(tmp_path, "cloud")
    sent = []
    worker = ntfy.NotificationWorker(
        tmp_path,
        "cloud",
        sender=lambda config, payload: sent.append(payload) or "receipt",
        clock=lambda: now[0],
    )
    return store, worker, config, now, sent, path


def test_empty_history_does_not_create_database(tmp_path):
    result = notifications.NotificationStore(tmp_path, "cloud").list_history()
    assert result == {"items": [], "total": 0, "limit": 25, "offset": 0}
    assert not (tmp_path / "data").exists()


def test_default_channel_is_queued_without_network_then_receipted(setup):
    store, worker, _, now, sent, _ = setup
    item = store.create(
        "Maintenance complete",
        "Removed old scratch files",
        source="cleanup-all",
        dedupe_key="run-1",
    )
    assert item["state"] == "pending"
    assert item["deliveries"] == [{"channel": "ntfy", "state": "pending"}]
    assert sent == []
    config = ntfy.load_config(store.root / "config/ntfy.json")
    assert worker.cycle(config)["delivered"] == 1
    assert sent == [
        {
            "topic": "jarvis-notifications",
            "title": item["title"],
            "message": item["message"],
            "priority": 3,
        }
    ]
    delivered = store.list_history()["items"][0]
    assert delivered["state"] == "delivered"
    assert delivered["deliveries"][0]["sent_at"].endswith("+00:00")
    now[0] += 20
    assert worker.cycle(config)["delivered"] == 0
    assert len(sent) == 1
    assert (
        store.create("Changed", "Must not replay", source="cleanup-all", dedupe_key="run-1")["id"]
        == item["id"]
    )


def test_local_only_save_does_not_read_transport_configuration(setup, monkeypatch):
    store, _, _, _, _, _ = setup
    monkeypatch.setattr(
        notifications,
        "ntfy_readiness",
        lambda _: pytest.fail("local save must not read credentials"),
    )
    item = store.create("Saved", "Local history", channels=[])
    assert item["state"] == "saved" and item["deliveries"] == []
    assert store.list_history(state="saved")["total"] == 1
    assert store.list_history(channel="ntfy")["total"] == 0


@pytest.mark.parametrize(
    "setting,reason",
    [
        ("missing", "ntfy_unconfigured"),
        ("disabled", "ntfy_disabled"),
        ("invalid", "ntfy_invalid_configuration"),
        ("permissions", "ntfy_invalid_configuration"),
        ("category", "ntfy_notifications_disabled"),
    ],
)
def test_unavailable_transport_is_saved_and_never_replayed_after_enabling(setup, setting, reason):
    store, worker, config, _, sent, path = setup
    if setting == "missing":
        path.unlink()
    elif setting == "disabled":
        path.write_text(json.dumps({**config, "enabled": False}))
    elif setting == "category":
        path.write_text(
            json.dumps({**config, "notifications": {**config["notifications"], "enabled": False}})
        )
    elif setting == "permissions":
        path.chmod(0o644)
    else:
        path.write_text("private invalid token text")
    item = store.create("Completed", "See local history")
    assert item["state"] == "unavailable"
    assert item["deliveries"] == [{"channel": "ntfy", "state": "unavailable", "error": reason}]
    assert "private" not in json.dumps(item)
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    assert worker.cycle(config)["delivered"] == 0
    assert sent == []
    assert store.list_history()["total"] == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"title": ""},
        {"title": "x" * 201},
        {"message": "x" * 2001},
        {"message": "\0private"},
        {"source": "x" * 81},
        {"dedupe_key": "x" * 201},
        {"channels": ["email"]},
        {"channels": "ntfy"},
        {"channels": ["ntfy", "ntfy"]},
        {"channels": [{}]},
        {"max_age_seconds": True},
        {"max_age_seconds": 59},
        {"max_age_seconds": 86401},
    ],
)
def test_invalid_input_never_creates_a_database(tmp_path, kwargs):
    args = {"title": "Title", "message": "Body", **kwargs}
    store = notifications.NotificationStore(tmp_path, "cloud")
    with pytest.raises(ValueError):
        store.create(**args)
    assert not store.path.exists()


def test_dedupe_is_atomic_and_scoped_to_source_and_mode(setup):
    store, _, _, _, _, _ = setup

    def create(_):
        return store.create("Title", "Body", source="cleanup", channels=[], dedupe_key="same")

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(create, range(12)))
    assert len({row["id"] for row in rows}) == 1
    assert sum(not row["deduplicated"] for row in rows) == 1
    assert (
        store.create("Other", "Body", source="different", channels=[], dedupe_key="same")["id"]
        != rows[0]["id"]
    )
    local = notifications.NotificationStore(store.root, "local")
    assert (
        local.create("Other", "Body", source="cleanup", channels=[], dedupe_key="same")["id"]
        != rows[0]["id"]
    )
    assert store.list_history()["total"] == 2
    assert local.list_history()["total"] == 1


def test_content_expires_after_90_days_but_dedupe_and_receipt_do_not(setup):
    store, worker, config, now, sent, _ = setup
    item = store.create("Private title", "Private body", dedupe_key="forever")
    worker.cycle(config)
    now[0] += notifications.CONTENT_RETENTION_SECONDS + 1
    assert store.list_history()["items"] == []
    duplicate = store.create("Replacement", "Do not create again", dedupe_key="forever")
    assert duplicate["id"] == item["id"] and duplicate["deduplicated"]
    assert duplicate["title"] == duplicate["message"] == ""
    assert duplicate["content_expired"]
    assert duplicate["deliveries"][0]["state"] == "delivered"
    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("SELECT receipt FROM notification_channel_deliveries").fetchone() == (
            "receipt",
        )
    assert worker.cycle(config)["delivered"] == 0
    assert len(sent) == 1


def test_one_worker_delivers_explicit_records_from_both_modes(setup):
    store, worker, config, _, sent, _ = setup
    store.create("Cloud", "Cloud event")
    notifications.NotificationStore(store.root, "local").create("Local", "Local event")
    assert worker.cycle(config)["delivered"] == 2
    assert {item["title"] for item in sent} == {"Cloud", "Local"}
    assert [item["title"] for item in store.list_history()["items"]] == ["Cloud"]


def test_outage_retries_with_backoff_and_sanitized_failure(setup):
    store, worker, config, now, sent, _ = setup
    store.create("Finished", "Body")
    attempts = []

    def fail(*_):
        attempts.append(now[0])
        raise ntfy.DeliveryError("private response contains credential")

    worker.sender = fail
    config["max_attempts"] = 2
    assert worker.cycle(config)["errors"] == ["delivery_failed"]
    assert store.list_history()["items"][0]["state"] == "pending"
    now[0] += 29
    worker.cycle(config)
    assert len(attempts) == 1
    now[0] += 1
    worker.cycle(config)
    assert len(attempts) == 2
    item = store.list_history()["items"][0]
    assert item["state"] == "failed"
    assert item["deliveries"][0]["error"] == "delivery_failed"
    worker.sender = lambda config, payload: sent.append(payload) or "receipt"
    now[0] += 1000
    assert worker.cycle(config)["delivered"] == 0


def test_authentication_failure_is_final_and_never_retried(setup):
    store, worker, config, now, sent, _ = setup
    store.create("Title", "Body")
    worker.sender = lambda *_: (_ for _ in ()).throw(
        ntfy.DeliveryError("ntfy HTTP 401", retryable=False)
    )
    worker.cycle(config)
    now[0] += 60
    worker.sender = lambda config, payload: sent.append(payload) or "receipt"
    assert worker.cycle(config)["delivered"] == 0
    assert store.list_history()["items"][0]["state"] == "failed"


@pytest.mark.parametrize("disabled", ["global", "category", "expired"])
def test_pending_delivery_is_suppressed_permanently_when_disabled_or_old(setup, disabled):
    store, worker, config, now, sent, _ = setup
    store.create("Title", "Body", max_age_seconds=60)
    if disabled == "global":
        config["enabled"] = False
    elif disabled == "category":
        config["notifications"]["enabled"] = False
    else:
        now[0] += 60
    assert worker.cycle(config)["suppressed"] == 1
    assert store.list_history()["items"][0]["state"] == "suppressed"
    config["enabled"] = config["notifications"]["enabled"] = True
    assert worker.cycle(config)["delivered"] == 0
    assert sent == []


def test_configured_freshness_can_shorten_requested_age(setup):
    store, worker, config, now, _, path = setup
    config["notifications"]["max_age_seconds"] = 60
    path.write_text(json.dumps(config))
    store.create("Title", "Body", max_age_seconds=3600)
    now[0] += 60
    assert worker.cycle(config)["suppressed"] == 1


def test_history_unifies_legacy_receipts_without_payload_or_cross_mode_leaks(setup):
    store, worker, _, now, _, _ = setup
    with closing(worker._state()) as conn, conn:
        for index, category in enumerate(ntfy.CATEGORIES):
            key = json.dumps(["cloud", category, str(index), None])
            conn.execute(
                """INSERT INTO deliveries(event_key,category,mode,source_id,expires,payload,state,error,sent_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    key,
                    category,
                    "cloud",
                    str(index),
                    now[0] + index,
                    '{"secret":"do not expose"}',
                    "delivered",
                    "private token",
                    "2027-01-15T08:00:00+00:00",
                ),
            )
        conn.execute(
            """INSERT INTO deliveries(event_key,category,mode,source_id,expires,state)
            VALUES('local','alerts','local','hidden',?,'pending')""",
            (now[0],),
        )
        conn.execute(
            """INSERT INTO deliveries(event_key,category,mode,source_id,expires,state)
            VALUES('baseline','alerts','cloud','old',?,'baseline')""",
            (now[0],),
        )
    store.create("Explicit", "Message", source="cleanup", channels=[])
    history = store.list_history()
    assert history["total"] == 4
    assert {item["source_type"] for item in history["items"]} == {*ntfy.CATEGORIES, "notifications"}
    assert "secret" not in json.dumps(history) and "private token" not in json.dumps(history)
    assert "hidden" not in json.dumps(history)
    assert store.list_history(source_type="alerts")["total"] == 1
    assert store.list_history(source="cleanup")["total"] == 1
    assert store.list_history(channel="ntfy", state="delivered")["total"] == 3
    assert store.list_history(source_type="notifications", state="saved")["total"] == 1
    page = store.list_history(limit=2, offset=2)
    assert page["total"] == 4 and len(page["items"]) == 2
    with closing(sqlite3.connect(store.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM deliveries").fetchone() == (5,)
        assert conn.execute(
            "SELECT payload FROM deliveries WHERE event_key=?",
            (json.dumps(["cloud", "alerts", "0", None]),),
        ).fetchone() == ('{"secret":"do not expose"}',)


@pytest.mark.parametrize("state", ["pending", "failed", "suppressed", "delivered"])
@pytest.mark.parametrize("has_sent_at", [False, True])
def test_unknown_legacy_times_sort_after_dated_notices(setup, state, has_sent_at):
    store, _, _, now, _, _ = setup
    older = store.create("Older notice", "Body", channels=[])
    now[0] += 60
    latest = store.create("Latest notice", "Body", channels=[])
    with closing(sqlite3.connect(store.path)) as conn, conn:
        conn.execute(
            """CREATE TABLE deliveries (
                event_key TEXT PRIMARY KEY, category TEXT, mode TEXT, source_id TEXT,
                expires REAL, state TEXT, error TEXT"""
            + (", sent_at TEXT" if has_sent_at else "")
            + ")"
        )
        for category in ntfy.CATEGORIES:
            conn.execute(
                """INSERT INTO deliveries(event_key,category,mode,source_id,expires,state)
                VALUES(?,?,'cloud','old',?,?)""",
                (category, category, now[0] + 3600, state),
            )

    history = store.list_history()
    assert history["total"] == 5
    assert [item["id"] for item in history["items"][:2]] == [latest["id"], older["id"]]
    assert {item["source_type"] for item in history["items"][2:]} == set(ntfy.CATEGORIES)
    assert all(item["created_at"] is None for item in history["items"][2:])
    assert store.list_history(limit=1, offset=0)["items"][0]["id"] == latest["id"]
    assert store.list_history(limit=1, offset=1)["items"][0]["id"] == older["id"]


@pytest.mark.parametrize("state", ["pending", "failed", "suppressed", "delivered"])
@pytest.mark.parametrize("category", ntfy.CATEGORIES)
def test_legacy_history_uses_event_time_for_order_and_display(setup, state, category):
    store, worker, _, now, _, _ = setup
    older = store.create("Older notice", "Body", channels=[])
    now[0] += 60
    event_at = now[0]
    with closing(worker._state()) as conn, conn:
        conn.execute(
            """INSERT INTO deliveries
            (event_key,category,mode,source_id,expires,state,event_at,sent_at)
            VALUES('event',?,'cloud','source',?,?,?,?)""",
            (category, event_at + 3600, state, event_at,
             notifications._iso(event_at + 120) if state == "delivered" else None),
        )
    now[0] += 60
    latest = store.create("Latest notice", "Body", channels=[])

    history = store.list_history()
    assert history["total"] == 3
    first, event, last = history["items"]
    assert first["id"] == latest["id"] and last["id"] == older["id"]
    assert event["created_at"] == notifications._iso(event_at)
    assert event["state"] == state and event["source_type"] == category
    assert store.list_history(limit=1, offset=1)["items"] == [event]
    assert store.list_history(source_type=category, state=state)["items"] == [event]


def test_legacy_send_time_is_fallback_when_event_time_was_not_recorded(setup):
    store, worker, _, now, _, _ = setup
    older = store.create("Older notice", "Body", channels=[])
    now[0] += 60
    sent_at = notifications._iso(now[0])
    with closing(worker._state()) as conn, conn:
        conn.execute(
            """INSERT INTO deliveries
            (event_key,category,mode,source_id,expires,state,sent_at)
            VALUES('old','alerts','cloud','source',?,'delivered',?)""",
            (now[0] + 3600, sent_at),
        )
    now[0] += 60
    latest = store.create("Latest notice", "Body", channels=[])

    first, event, last = store.list_history()["items"]
    assert first["id"] == latest["id"] and last["id"] == older["id"]
    assert event["created_at"] is None
    assert event["deliveries"] == [{"channel": "ntfy", "state": "delivered", "sent_at": sent_at}]


def test_original_configuration_gets_notifications_defaults_without_replaying_legacy(setup):
    store, worker, config, _, _, _ = setup
    old_config = {key: value for key, value in config.items() if key != "notifications"}
    effective = ntfy.validate_config(old_config)
    assert effective["notifications"] == {
        "enabled": True,
        "topic": "jarvis-notifications",
        "max_age_seconds": 3600,
    }
    assert worker.cycle(effective)["delivered"] == 0
    store.create("Title", "Body")
    assert worker.cycle(effective)["delivered"] == 1


def test_publishing_does_not_hold_a_sqlite_write_lock(setup):
    store, worker, config, _, _, _ = setup
    store.create("Send", "Body")

    def publish(config, payload):
        assert (
            store.create("Concurrent writer", "Saved while publishing", channels=[])["state"]
            == "saved"
        )
        return "receipt"

    worker.sender = publish
    assert worker.cycle(config)["delivered"] == 1
    assert store.list_history()["total"] == 2


def test_expiry_rechecked_after_earlier_publish_consumes_time(setup):
    store, worker, config, now, sent, _ = setup
    store.create("First", "Body", max_age_seconds=60)
    now[0] += 1
    store.create("Second", "Body", max_age_seconds=60)

    def publish(config, payload):
        sent.append(payload)
        now[0] += 61
        return "receipt"

    worker.sender = publish
    stats = worker.cycle(config)
    assert stats["delivered"] == 1 and stats["suppressed"] == 1
    assert len(sent) == 1
    assert {item["state"] for item in store.list_history()["items"]} == {"delivered", "suppressed"}


def test_transport_credentials_and_destinations_never_enter_notification_rows(setup):
    store, _, config, _, _, _ = setup
    store.create("Title", "Body")
    with closing(sqlite3.connect(store.path)) as conn:
        contents = repr(conn.execute("SELECT * FROM notification_events").fetchall())
        contents += repr(conn.execute("SELECT * FROM notification_channel_deliveries").fetchall())
    assert config["publisher_token"] not in contents
    assert config["server_url"] not in contents
    assert config["notifications"]["topic"] not in contents


def test_producer_names_do_not_collide_with_source_type_filters(setup):
    store, worker, _, now, _, _ = setup
    explicit = store.create("Producer named alerts", "Body", source="alerts", channels=[])
    with closing(worker._state()) as conn, conn:
        conn.execute(
            """INSERT INTO deliveries(event_key,category,mode,source_id,expires,state)
            VALUES('alert','alerts','cloud','123',?,'delivered')""",
            (now[0],),
        )
    origin = store.list_history(source="alerts")
    assert origin["total"] == 2
    assert explicit["id"] in {item["id"] for item in origin["items"]}
    assert (
        store.list_history(source="alerts", source_type="notifications")["items"][0]["id"]
        == explicit["id"]
    )
    legacy = store.list_history(source_type="alerts")
    assert legacy["total"] == 1 and legacy["items"][0]["source_id"] == "123"
    assert store.list_history(source_type="notifications")["total"] == 1
    with pytest.raises(ValueError, match="source type"):
        store.list_history(source_type="unknown")
