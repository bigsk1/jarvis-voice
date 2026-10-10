"""Repeated Calendar deliveries must reuse reminders and cancel legacy copies."""

import importlib.util
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.managers.reminder_manager import ReminderManager


@pytest.fixture
def manager(tmp_path):
    path = tmp_path / "reminders.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE reminders (
                id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT,
                trigger_time TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT, triggered_at TEXT, acknowledged_at TEXT,
                spoken INTEGER DEFAULT 0, spoken_at TEXT, related_intel_file TEXT,
                callback_url TEXT, recurrence_rule TEXT, metadata TEXT
            )
        """)
    instance = ReminderManager.__new__(ReminderManager)
    instance.db = SimpleNamespace(db_path=str(path))
    return instance


def payload(event_id="sample-event", calendar_id="calendar.one@example.test", **extra):
    return {
        "title": "Sample appointment",
        "trigger_time": "2030-01-01T12:00:00Z",
        "description": "Sample details",
        "metadata": {"source": "google_calendar", "gcal_event_id": event_id,
                     "gcal_calendar_id": calendar_id, "synced_at": "first-delivery"},
        **extra,
    }


def count(manager):
    with sqlite3.connect(manager.db.db_path) as connection:
        return connection.execute("SELECT count(*) FROM reminders").fetchone()[0]


def test_calendar_replay_reuses_id_without_overwriting_current_state(manager):
    original = manager.create_reminder(**payload())
    changed = payload(title="Stale replay", trigger_time="2030-01-01T14:00:00Z")
    changed["metadata"]["synced_at"] = "retry-delivery"
    assert manager.create_reminder(**changed) == original
    assert count(manager) == 1
    assert manager.get_reminder(original)["title"] == "Sample appointment"
    assert manager.get_reminder(original)["trigger_time"] == "2030-01-01T12:00:00Z"


def test_create_replay_does_not_revive_canceled_calendar_import(manager):
    original = manager.create_reminder(**payload())
    assert manager.cancel_reminder(original)
    assert manager.create_reminder(**payload()) == original
    assert manager.get_reminder(original)["status"] == "canceled"
    assert count(manager) == 1


def test_calendar_identity_distinguishes_different_events_and_calendars(manager):
    ids = {
        manager.create_reminder(**payload()),
        manager.create_reminder(**payload(event_id="another-event")),
        manager.create_reminder(**payload(calendar_id="calendar.two@example.test")),
    }
    assert len(ids) == count(manager) == 3


def test_calendar_identity_without_calendar_id_is_still_idempotent(manager):
    body = payload()
    body["metadata"].pop("gcal_calendar_id")
    assert manager.create_reminder(**body) == manager.create_reminder(**body)
    assert count(manager) == 1


def test_exact_ordinary_reminder_reuses_active_record(manager):
    body = payload(metadata={"tag": "sample", "priority": 1})
    original = manager.create_reminder(**body)
    body["metadata"] = {"priority": 1, "tag": "sample"}
    assert manager.create_reminder(**body) == original
    assert count(manager) == 1


@pytest.mark.parametrize("different", [
    {"title": "Another appointment"},
    {"trigger_time": "2030-01-01T13:00:00Z"},
    {"description": "Other details"},
    {"callback_url": "https://example.test/callback"},
    {"recurrence_rule": "DAILY"},
    {"metadata": {"tag": "another"}},
])
def test_different_ordinary_reminders_are_not_merged(manager, different):
    original = manager.create_reminder(**payload(metadata=None))
    changed = payload(metadata=None)
    changed.update(different)
    assert manager.create_reminder(**changed) != original
    assert count(manager) == 2


@pytest.mark.parametrize("calendar", [True, False])
def test_simultaneous_duplicate_deliveries_insert_once(manager, calendar):
    barrier = threading.Barrier(4)
    body = payload() if calendar else payload(metadata=None)

    def deliver(_):
        barrier.wait()
        return manager.create_reminder(**body)

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(deliver, range(4)))
    assert len(set(ids)) == count(manager) == 1


def seed_legacy_copies(manager):
    original = manager.create_reminder(**payload())
    manager.cancel_reminder(original)
    with sqlite3.connect(manager.db.db_path) as connection:
        for _ in range(2):
            connection.execute("""
                INSERT INTO reminders (title, description, trigger_time, status, created_at, metadata)
                VALUES ('Sample appointment', 'Sample details', '2030-01-01T12:00:00Z',
                        'scheduled', '2030-01-01T10:00:00Z', ?)
            """, (json.dumps(payload()["metadata"]),))
    return original


def test_cancel_event_covers_all_legacy_copies_and_is_repeatable(manager):
    seed_legacy_copies(manager)
    other_calendar = manager.create_reminder(**payload(calendar_id="calendar.two@example.test"))
    other_event = manager.create_reminder(**payload(event_id="another-event"))
    assert manager.cancel_reminders_by_gcal_event_id("sample-event", "calendar.one@example.test") == 2
    assert manager.cancel_reminders_by_gcal_event_id("sample-event", "calendar.one@example.test") == 0
    assert manager.get_reminder(other_calendar)["status"] == "scheduled"
    assert manager.get_reminder(other_event)["status"] == "scheduled"


@pytest.fixture
def api_client(manager, monkeypatch):
    # Import this route module without constructing the real production manager.
    monkeypatch.setattr(ReminderManager, "__init__", lambda self, mode=None: setattr(self, "db", manager.db))
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("reminder_sync_test_routes", root / "api/routes/reminders.py")
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        yield client


def test_http_repeat_create_returns_same_id(api_client, manager):
    first = api_client.post("/api/reminders", json=payload())
    retry = api_client.post("/api/reminders", json=payload())
    assert first.status_code == retry.status_code == 200
    assert first.json()["reminder_id"] == retry.json()["reminder_id"]
    assert count(manager) == 1


def test_http_calendar_delete_cancels_remaining_copies_even_if_first_is_canceled(api_client, manager):
    seed_legacy_copies(manager)
    first = api_client.delete("/api/reminders/by-gcal/sample-event")
    retry = api_client.delete("/api/reminders/by-gcal/sample-event")
    assert first.status_code == retry.status_code == 200
    assert first.json()["ok"] and retry.json()["ok"]
    assert manager.list_reminders(status="scheduled") == []


def seed_mixed_calendar_copies(manager):
    original = manager.create_reminder(**payload())
    with sqlite3.connect(manager.db.db_path) as connection:
        for calendar in (None, 'primary'):
            metadata = payload()['metadata']
            if calendar is None:
                metadata.pop('gcal_calendar_id')
            else:
                metadata['gcal_calendar_id'] = calendar
            connection.execute("""
                INSERT INTO reminders (title, description, trigger_time, status, created_at, metadata)
                VALUES ('Sample appointment', 'Sample details', '2030-01-01T12:00:00Z',
                        'scheduled', '2030-01-01T10:00:00Z', ?)
            """, (json.dumps(metadata),))
    return original


@pytest.mark.parametrize('alias', [None, 'primary'])
def test_named_calendar_delivery_adopts_legacy_identity_without_inserting(manager, alias):
    legacy = payload()
    if alias is None:
        legacy['metadata'].pop('gcal_calendar_id')
    else:
        legacy['metadata']['gcal_calendar_id'] = alias
    original = manager.create_reminder(**legacy)
    assert manager.create_reminder(**payload()) == original
    assert count(manager) == 1
    assert json.loads(manager.get_reminder(original)['metadata'])['gcal_calendar_id'] == 'calendar.one@example.test'


def test_delete_handles_empty_primary_and_named_calendar_families(api_client, manager):
    seed_mixed_calendar_copies(manager)
    result = api_client.delete('/api/reminders/by-gcal/sample-event')
    assert result.status_code == 200
    assert manager.list_reminders(status='scheduled') == []
    assert {json.loads(row['metadata'])['gcal_calendar_id'] for row in manager.list_reminders()} == {'calendar.one@example.test'}


def test_update_changes_all_legacy_copies_and_schedules_only_one(api_client, manager):
    seed_mixed_calendar_copies(manager)
    body = payload(title='Updated appointment', trigger_time='2030-01-01T13:00:00Z')
    result = api_client.put('/api/reminders/by-gcal/sample-event', json=body)
    assert result.status_code == 200
    rows = manager.list_reminders()
    assert len(rows) == 3
    assert {row['trigger_time'] for row in rows} == {'2030-01-01T13:00:00Z'}
    assert {row['title'] for row in rows} == {'Updated appointment'}
    assert len([row for row in rows if row['status'] == 'scheduled']) == 1
    assert {json.loads(row['metadata'])['gcal_calendar_id'] for row in rows} == {'calendar.one@example.test'}
    assert manager.create_reminder(**body) == result.json()['reminder']['id']


def test_unscoped_multi_calendar_calls_fail_without_mutation(api_client, manager):
    first = manager.create_reminder(**payload())
    second = manager.create_reminder(**payload(calendar_id='calendar.two@example.test'))
    assert api_client.get('/api/reminders/by-gcal/sample-event').status_code == 409
    assert api_client.delete('/api/reminders/by-gcal/sample-event').status_code == 409
    assert manager.get_reminder(first)['status'] == manager.get_reminder(second)['status'] == 'scheduled'
    result = api_client.delete('/api/reminders/by-gcal/sample-event?calendar_id=calendar.one%40example.test')
    assert result.status_code == 200
    assert manager.get_reminder(first)['status'] == 'canceled'
    assert manager.get_reminder(second)['status'] == 'scheduled'


def test_update_selects_requested_calendar_even_if_other_calendar_row_is_older(api_client, manager):
    other = manager.create_reminder(**payload(calendar_id='calendar.two@example.test'))
    selected = manager.create_reminder(**payload())
    result = api_client.put('/api/reminders/by-gcal/sample-event', json=payload(title='Only selected calendar'))
    assert result.status_code == 200 and result.json()['reminder']['id'] == selected
    assert manager.get_reminder(other)['title'] == 'Sample appointment'


def test_metadata_only_calendar_update_does_not_replay_canceled_occurrence(api_client, manager):
    original = manager.create_reminder(**payload())
    manager.cancel_reminder(original)
    body = payload(description='Updated details', trigger_time='2030-01-01T12:00:00+00:00')
    result = api_client.put('/api/reminders/by-gcal/sample-event', json=body)
    assert result.status_code == 200
    assert manager.get_reminder(original)['status'] == 'canceled'


def test_calendar_update_preserves_unsupplied_local_fields_and_lifecycle(api_client, manager):
    original = manager.create_reminder(**payload(callback_url='https://example.test/callback',
                                                related_intel_file='sample.md', recurrence_rule='DAILY'))
    with sqlite3.connect(manager.db.db_path) as conn:
        conn.execute("UPDATE reminders SET status='acknowledged', spoken=1, spoken_at='sample', "
                     "triggered_at='sample', acknowledged_at='sample' WHERE id=?", (original,))
    result = api_client.put('/api/reminders/by-gcal/sample-event', json=payload(description='New details'))
    assert result.status_code == 200
    row = manager.get_reminder(original)
    assert row['callback_url'] == 'https://example.test/callback'
    assert row['related_intel_file'] == 'sample.md' and row['recurrence_rule'] == 'DAILY'
    assert row['status'] == 'acknowledged' and row['spoken'] == 1
    assert row['spoken_at'] == row['triggered_at'] == row['acknowledged_at'] == 'sample'
    result = api_client.put('/api/reminders/by-gcal/sample-event', json=payload(callback_url=None))
    assert result.status_code == 200 and manager.get_reminder(original)['callback_url'] is None


def test_ambiguous_legacy_copy_is_not_assigned_to_a_guessed_calendar(api_client, manager):
    manager.create_reminder(**payload())
    manager.create_reminder(**payload(calendar_id='calendar.two@example.test'))
    with sqlite3.connect(manager.db.db_path) as conn:
        metadata = payload()['metadata']
        metadata.pop('gcal_calendar_id')
        conn.execute("INSERT INTO reminders (title, trigger_time, status, metadata) VALUES (?, ?, 'scheduled', ?)",
                     ('Sample appointment', '2030-01-01T12:00:00Z', json.dumps(metadata)))
    before = manager.list_reminders()
    endpoint = '/api/reminders/by-gcal/sample-event?calendar_id=calendar.one%40example.test'
    assert api_client.delete(endpoint).status_code == 409
    assert api_client.put(endpoint, json=payload()).status_code == 409
    assert api_client.post('/api/reminders', json=payload()).status_code == 409
    assert manager.list_reminders() == before


def test_equivalent_ordinary_timestamps_deduplicate(manager):
    original = manager.create_reminder(**payload(metadata=None))
    assert manager.create_reminder(**payload(metadata=None, trigger_time='2030-01-01T04:00:00-08:00')) == original
    assert count(manager) == 1


def test_native_calendar_receipt_records_scope_for_later_import(manager, monkeypatch):
    from datetime import datetime, timezone

    from skills import create_reminder

    monkeypatch.setattr(create_reminder, 'sync_to_google_calendar', lambda **_kwargs: {
        'ok': True, 'gcal_event_id': 'sample-event', 'gcal_calendar_id': 'calendar.one@example.test',
    })
    result = create_reminder.create_single_reminder('Sample appointment', 'Sample details',
        datetime(2030, 1, 1, 12, tzinfo=timezone.utc), db_path=manager.db.db_path)
    metadata = json.loads(manager.get_reminder(result['reminder_id'])['metadata'])
    assert metadata['gcal_calendar_id'] == 'calendar.one@example.test'
    assert manager.create_reminder(**payload()) == result['reminder_id']
    assert count(manager) == 1


def test_memory_ui_duplicate_receipt_does_not_claim_new_creation(manager):
    from flask import Flask

    path = Path(__file__).resolve().parents[1] / 'jarvis-memory/server/routes/reminders.py'
    spec = importlib.util.spec_from_file_location('memory_duplicate_test_routes', path)
    routes = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(routes)
    routes.get_manager = lambda: manager
    app = Flask(__name__)
    app.register_blueprint(routes.reminders_bp)
    client = app.test_client()
    first = client.post('/api/reminders', json=payload(metadata=None))
    second = client.post('/api/reminders', json=payload(metadata=None))
    assert first.status_code == second.status_code == 200
    assert first.json['reminder_id'] == second.json['reminder_id']
    assert second.json['message'] == 'Reminder saved'
