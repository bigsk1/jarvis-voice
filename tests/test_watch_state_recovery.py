"""Fault injection verifies that acceptance and its delivery outbox are atomic."""

import sqlite3

import pytest

from lib.watch_state import Authority, StorageError, Store


def test_failed_outbox_write_rolls_back_snapshot_and_can_retry_the_same_run(tmp_path):
    store = Store(tmp_path, "cloud")
    owner = Authority("workflow:prices")
    store.register("prices", {"id_field": "id", "channels": [
        {"channel": "email", "destination": "fixture@example.test"},
    ]}, owner)
    first = store.compare("prices", [{"id": "0001", "price": 10}], owner)
    store.commit("prices", first["run_id"], owner)
    staged = store.compare("prices", [{"id": "0001", "price": 0}], owner)
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON deliveries "
                           "BEGIN SELECT RAISE(ABORT, 'controlled delivery write failure'); END")
    with pytest.raises(StorageError):
        store.commit("prices", staged["run_id"], owner)
    persisted = store.inspect("prices")
    assert persisted["revision"] == 1
    assert persisted["snapshot"][0]["record"]["price"] == 10
    assert store.pending("prices")["items"] == []
    assert store.history("prices")["items"] == []
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("SELECT status FROM runs WHERE run_id=?", (staged["run_id"],)).fetchone()[0] == "staged"
        connection.execute("DROP TRIGGER fail_outbox")
    receipt = store.commit("prices", staged["run_id"], owner)
    assert receipt["revision"] == 2 and receipt["events_count"] == 1
    assert store.pending("prices")["items"][0]["after"]["price"] == 0
    assert store.commit("prices", staged["run_id"], owner)["already_committed"] is True
    assert len(store.history("prices")["items"]) == 1
