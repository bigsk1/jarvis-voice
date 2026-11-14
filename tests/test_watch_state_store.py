"""Real SQLite lifecycle contracts for staged watch state and durable deliveries."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from lib.watch_state import (
    Authority,
    AuthorityError,
    ConflictError,
    NotFoundError,
    Store,
    ValidationError,
    authority_from_environment,
    export_writer_context,
    watch_writer_scope,
)
from lib.watch_state.normalization import MAX_RECORDS
from lib.watch_state.store import MAX_DELIVERY_ATTEMPTS, STAGE_TTL_SECONDS

OWNER = Authority("workflow:price_watch")
ADMIN = Authority("api", admin=True)


@pytest.fixture
def clock():
    return [1000.0]


@pytest.fixture
def store(tmp_path, clock):
    return Store(tmp_path, "cloud", clock=lambda: clock[0])


def register(store, **overrides):
    return store.register("price", {"id_field": "id", **overrides}, OWNER)


def commit(store, records, **options):
    run = store.compare("price", records, OWNER, **options)
    return run, store.commit("price", run["run_id"], OWNER)


def counts(store):
    with sqlite3.connect(store.db_path) as conn:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("snapshots", "runs", "events", "deliveries", "handled_records")}


def test_staging_has_no_baseline_or_delivery_side_effect_until_atomic_commit(store):
    register(store, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
    staged = store.compare("price", [{"id": "001", "price": 0}], OWNER)
    assert staged["base_revision"] == 0 and staged["changes"][0]["record_id"] == "001"
    assert store.inspect("price")["snapshot_count"] == 0
    assert store.pending("price")["items"] == []
    committed = store.commit("price", staged["run_id"], OWNER)
    assert committed["revision"] == 1 and committed["pending_count"] == 1
    assert store.inspect("price")["snapshot"][0]["record"]["price"] == 0
    assert store.pending("price")["items"][0]["after"] == {"id": "001", "price": 0}
    assert store.commit("price", staged["run_id"], OWNER)["already_committed"] is True
    assert counts(store) == {"snapshots": 1, "runs": 1, "events": 1, "deliveries": 1, "handled_records": 0}


def test_quiet_first_preserves_baseline_then_reports_changed_zero_and_false(store):
    register(store, compare_fields=["price", "available"], ignore_fields=["checked_at"])
    first, receipt = commit(store, [{"id": "001", "price": 10, "available": True, "checked_at": "old"}])
    assert first["quiet_first"] is True and receipt["events_count"] == 0
    unchanged, _ = commit(store, [{"id": "001", "price": 10, "available": True, "checked_at": "new"}])
    assert unchanged["changes"] == []
    changed, _ = commit(store, [{"id": "001", "price": 0, "available": False}])
    assert changed["changes"][0]["kind"] == "changed"
    assert changed["changes"][0]["fields"] == ["available", "price"]
    assert changed["changes"][0]["after"]["available"] is False


def test_ignored_fields_still_update_snapshot_and_preserve_original_event_history(store):
    register(store, compare_fields=["severity"], ignore_fields=["name"], quiet_first=False)
    first_record = {"id": "001", "name": "First label", "severity": "medium"}
    _, first = commit(store, [first_record])
    renamed = {**first_record, "name": "Renamed label"}
    preview = store.compare("price", [renamed], OWNER)
    assert preview["changes"] == []
    assert store.inspect("price")["snapshot"][0]["record"] == first_record

    receipt = store.commit("price", preview["run_id"], OWNER)
    assert receipt["events_count"] == 0
    assert store.inspect("price")["snapshot"][0]["record"] == renamed
    history = store.history("price")["items"]
    assert len(history) == 1
    assert history[0]["event_id"] == first["event_ids"][0]
    assert history[0]["after"] == first_record


def test_missing_grace_counts_distinct_complete_commits_and_reappearance(store):
    register(store, complete=False, missing_grace=2)
    commit(store, [{"id": "001"}], complete=True)
    first = store.compare("price", [], OWNER, complete=True, request_id="missing-once")
    stale = store.compare("price", [], OWNER, complete=True)
    assert first["changes"] == stale["changes"] == []
    store.commit("price", first["run_id"], OWNER)
    assert store.compare("price", [], OWNER, complete=True, request_id="missing-once")["run_id"] == first["run_id"]
    with pytest.raises(ConflictError):
        store.commit("price", stale["run_id"], OWNER)
    partial, _ = commit(store, [])
    assert partial["changes"] == [] and store.inspect("price")["snapshot"][0]["missing_count"] == 1
    removed, _ = commit(store, [], complete=True)
    assert removed["changes"][0]["kind"] == "removed"
    assert store.inspect("price")["snapshot_count"] == 0
    reappeared, _ = commit(store, [{"id": "001", "price": 0}])
    assert reappeared["changes"][0]["kind"] == "reappeared"
    assert store.inspect("price")["snapshot"][0]["missing_count"] == 0


def test_new_store_and_registered_dry_runs_make_no_writes(tmp_path, store):
    absent = Store(tmp_path / "absent", "local")
    with pytest.raises(NotFoundError):
        absent.compare("price", [], OWNER, dry_run=True)
    assert not absent.db_path.exists()
    assert absent.list()["items"] == [] and absent.health()["ok"] is True
    assert not absent.db_path.parent.exists()
    register(store, quiet_first=False)
    before = (counts(store), store.inspect("price"))
    result = store.compare("price", [{"id": "0001"}], OWNER, dry_run=True)
    assert result["status"] == "dry_run" and result["changes"]
    assert (counts(store), store.inspect("price")) == before
    with pytest.raises(ValidationError):
        store.compare("price", [{"no_id": True}], OWNER, dry_run=True)
    assert (counts(store), store.inspect("price")) == before


def test_request_id_reuse_is_idempotent_and_different_observation_is_rejected(store):
    register(store, quiet_first=False)
    first = store.compare("price", [{"id": "001", "price": 1}], OWNER, request_id="request-one")
    repeated = store.compare("price", [{"price": 1, "id": "001"}], OWNER, request_id="request-one")
    assert repeated["run_id"] == first["run_id"] and counts(store)["runs"] == 1
    with pytest.raises(ConflictError):
        store.compare("price", [{"id": "001", "price": 2}], OWNER, request_id="request-one")


def test_modes_are_isolated_and_shared_radars_remain_visible_in_each_active_mode(tmp_path, clock):
    cloud, local, shared = [Store(tmp_path, mode, clock=lambda: clock[0]) for mode in ("cloud", "local", "shared")]
    register(cloud)
    register(local)
    commit(cloud, [{"id": "001", "price": 1}])
    commit(local, [{"id": "001", "price": 9}])
    key = "upcoming_movie_radar"
    shared.register(key, {"id_field": "tmdb_id", "stale_after_seconds": 0}, Authority(f"workflow:{key}"))
    assert cloud.inspect("price")["snapshot"][0]["record"]["price"] == 1
    assert local.inspect("price")["snapshot"][0]["record"]["price"] == 9
    for active in (cloud, local):
        assert {(row["scope"], row["key"]) for row in active.list()["items"]} == {(active.mode, "price"), ("shared", key)}
        assert active.health()["watches_count"] == 2
    with pytest.raises(AuthorityError):
        shared.register("arbitrary", {"id_field": "id"}, ADMIN)
    with pytest.raises(AuthorityError):
        shared.register("upcoming_tv_radar", {"id_field": "id"}, Authority("interactive"))
    with pytest.raises(AuthorityError):
        shared.import_handled(key, [{"tmdb_id": "1"}], OWNER, "email")


@pytest.mark.parametrize("operation", ["compare", "commit", "reset", "mute", "delete", "record_error", "import_handled"])
def test_other_writers_cannot_mutate_or_poison_health(store, operation):
    register(store)
    wrong = Authority("workflow:other")
    before = store.inspect("price")
    with pytest.raises(AuthorityError):
        if operation == "compare":
            store.compare("price", [], wrong)
        elif operation == "commit":
            store.commit("price", "missing-run", wrong)
        elif operation == "import_handled":
            store.import_handled("price", [{"id": "1"}], wrong, "ntfy")
        else:
            getattr(store, operation)("price", wrong)
    assert store.inspect("price") == before


def test_definitions_require_reset_and_version_bump_and_owner_transfer_is_admin_only(store):
    register(store, compare_fields=["price"])
    commit(store, [{"id": "001", "price": 1}])
    with pytest.raises(ConflictError):
        register(store, compare_fields=["stock"], schema_version=2)
    store.reset("price", OWNER)
    with pytest.raises(ConflictError):
        register(store, compare_fields=["stock"])
    changed = register(store, compare_fields=["stock"], schema_version=2)
    assert changed["definition"]["compare_fields"] == ["stock"]
    with pytest.raises(AuthorityError):
        store.register("price", changed["definition"], OWNER, owner="other")
    store.register("price", changed["definition"], ADMIN, owner="workflow:new_owner")
    with pytest.raises(AuthorityError):
        store.reset("price", OWNER)
    store.reset("price", Authority("workflow:new_owner"))


def test_explicit_normalizers_keep_leading_zero_identity_and_semantic_values(store):
    register(store, id_field="metadata._id", compare_fields=["price", "count", "title", "date"],
             normalizers={"price": {"type": "money", "currency": "USD"}, "count": "number", "title": "text", "date": "date"})
    commit(store, [{"metadata": {"_id": "0001"}, "price": "$1,234.50", "count": "1,000.00", "title": "  Example   PRODUCT ", "date": "2026-01-01T12:00:00-08:00"}])
    run, _ = commit(store, [{"metadata": {"_id": "0001"}, "price": {"amount": "1234.500", "currency": "USD"}, "count": 1000, "title": "example product", "date": "2026-01-01T20:00:00Z"}])
    assert run["changes"] == []
    assert store.inspect("price")["snapshot"][0]["record_id"] == "0001"
    assert store.inspect("price")["snapshot"][0]["record"]["price"] == {"amount": "1234.5", "currency": "USD"}


@pytest.mark.parametrize("definition", [
    {"id_field": "meta.id", "normalizers": {"meta": "text"}},
    {"id_field": "meta", "normalizers": {"meta.id": "text"}},
    {"id_field": "id", "normalizers": {"id": "number"}},
    {"id_field": "id", "compare_fields": ["meta.price"], "ignore_fields": ["meta"]},
    {"id_field": "id", "thresholds": {"price": 2}},
    {"id_field": "id", "normalizers": {"price": {"type": "money", "currency": "usd"}}},
])
def test_invalid_definitions_and_identity_normalization_are_rejected_before_creation(store, definition):
    with pytest.raises(ValidationError):
        store.register("invalid", definition, OWNER)
    assert not store.db_path.exists()


@pytest.mark.parametrize("records", [
    [{"id": "001"}, {"id": "001"}], [{"id": True}], [{"id": 1.5}], [{"id": None}],
    [{"id": "one", "price": float("nan")}], [{"id": "one", "price": float("inf")}],
    [{"id": str(index)} for index in range(MAX_RECORDS + 1)],
    [{"id": "one", "text": "x" * 2_000_001}],
])
def test_invalid_observations_fail_without_advancing_baseline(store, records):
    register(store)
    with pytest.raises(ValidationError):
        store.compare("price", records, OWNER)
    assert store.inspect("price")["revision"] == 0 and counts(store)["runs"] == 0
    assert store.health()["error_count"] == 1


def test_claim_fencing_and_channel_specific_success_receipts_are_durable(store, clock):
    register(store, quiet_first=False, channels=[{"channel": "email", "destination": "a@example.test"}, {"channel": "ntfy", "destination": "topic"}])
    run, _ = commit(store, [{"id": "001", "tmdb_url": "https://example.test/movie", "date": "2026-11-13"}])
    event = run["changes"][0]["event_id"]
    first = store.claim("price", event, "email", "a@example.test", OWNER, lease_seconds=1)
    with pytest.raises(ConflictError):
        store.claim("price", event, "email", "a@example.test", OWNER)
    assert {row["channel"] for row in store.pending("price")["items"]} == {"ntfy"}
    clock[0] += 2
    second = store.claim("price", event, "email", "a@example.test", OWNER)
    with pytest.raises(ConflictError):
        store.ack("price", event, "email", "a@example.test", OWNER, claim_token=first["claim_token"])
    receipt = {"ok": True, "message_id": "exact-message-id"}
    delivered = store.ack("price", event, "email", "a@example.test", OWNER, claim_token=second["claim_token"], receipt=receipt)
    assert delivered["status"] == "delivered" and delivered["receipt"] == receipt
    again = store.ack("price", event, "email", "a@example.test", OWNER, success=False, error="old failure")
    assert again["already_delivered"] is True and again["receipt"] == receipt
    handled = store.handled("price", "email")
    assert handled["ids"] == ["001"] and handled["items"][0]["record"]["tmdb_url"] == "https://example.test/movie"
    assert {row["channel"] for row in store.pending("price")["items"]} == {"ntfy"}


def test_failed_destinations_are_unhealthy_immediately_and_park_at_retry_cap(store):
    register(store, quiet_first=False, channels=[{"channel": "email", "destination": "a@example.test"}])
    run, _ = commit(store, [{"id": "001"}])
    event = run["changes"][0]["event_id"]
    assert store.health()["ok"] is True
    for attempt in range(MAX_DELIVERY_ATTEMPTS):
        claim = store.claim("price", event, "email", "a@example.test", OWNER)
        result = store.ack("price", event, "email", "a@example.test", OWNER, success=False,
                           error={"code": "temporarily_unavailable"}, claim_token=claim["claim_token"])
        assert result["attempts"] == attempt + 1
        assert store.health()["ok"] is False and store.health()["delivery_error_count"] == 1
        commit(store, [{"id": "001"}])
        assert store.health()["delivery_error_count"] == 1
    assert result["status"] == "parked"
    assert store.pending("price")["items"] == []
    assert store.pending("price", include_parked=True)["items"][0]["attempts"] == MAX_DELIVERY_ATTEMPTS
    with pytest.raises(ConflictError):
        store.claim("price", event, "email", "a@example.test", OWNER)


def test_successful_retry_clears_only_the_failed_channel_health(store):
    register(store, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
    run, _ = commit(store, [{"id": "001"}])
    event = run["changes"][0]["event_id"]
    claim = store.claim("price", event, "ntfy", "topic", OWNER)
    store.ack("price", event, "ntfy", "topic", OWNER, success=False, claim_token=claim["claim_token"])
    assert store.health()["error_count"] == 1
    claim = store.claim("price", event, "ntfy", "topic", OWNER)
    store.ack("price", event, "ntfy", "topic", OWNER, receipt={"id": "sent-once"}, claim_token=claim["claim_token"])
    assert store.health()["ok"] is True and store.health()["error_count"] == 0


def test_mute_holds_pending_without_losing_them_and_reset_preserves_claimed_delivery(store, clock):
    register(store, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
    run, _ = commit(store, [{"id": "001"}])
    event = run["changes"][0]["event_id"]
    store.mute("price", OWNER, seconds=10)
    assert store.pending("price")["items"] == []
    with pytest.raises(ConflictError):
        store.claim("price", event, "ntfy", "topic", OWNER)
    clock[0] += 11
    claim = store.claim("price", event, "ntfy", "topic", OWNER)
    store.reset("price", OWNER)
    store.ack("price", event, "ntfy", "topic", OWNER, receipt={"id": "sent"}, claim_token=claim["claim_token"])
    assert store.inspect("price")["snapshot_count"] == 0
    assert store.handled("price")["ids"] == ["001"]


def test_durable_handled_import_is_atomic_idempotent_and_survives_reset_cleanup_delete(store, clock):
    register(store, retention_days=1)
    imported = store.import_handled("price", [{"id": "001", "tmdb_url": "https://example.test/a"}, {"id": "002"}], OWNER, "email")
    assert imported["imported_count"] == 2 and store.history("price")["items"] == []
    repeated = store.import_handled("price", [{"id": "001", "tmdb_url": "replacement"}], OWNER, "email")
    assert repeated["imported_count"] == 0 and repeated["items"][0]["record"]["tmdb_url"] == "https://example.test/a"
    with pytest.raises(ValidationError):
        store.import_handled("price", [{"id": "003"}, {"missing": True}], OWNER, "email")
    assert store.handled("price")["ids"] == ["001", "002"]
    receipt = {"ok": True, "data": {"message_id": "long-lived-message-id"}}
    sent = store.record_delivery("price", {"id": "004", "date": "2026-11-13"}, "ntfy", "topic", OWNER, receipt=receipt)
    assert sent["already_handled"] is False
    assert store.record_delivery("price", {"id": "004"}, "ntfy", "topic", OWNER, receipt={"wrong": True})["receipt"] == receipt
    store.reset("price", OWNER)
    clock[0] += 30 * 86_400
    store.cleanup("price", OWNER)
    store.delete("price", OWNER)
    register(store)
    assert store.handled("price")["ids"] == ["001", "002", "004"]
    with pytest.raises(AuthorityError):
        store.delete("price", OWNER, delete_handled=True)
    store.delete("price", ADMIN, delete_handled=True)
    register(store)
    assert store.handled("price")["items"] == []


@pytest.mark.parametrize("legacy_deleted_row", [False, True])
def test_delete_and_reregister_clear_history_but_preserve_handled_and_replay_fences(store, clock, legacy_deleted_row):
    register(store, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
    _, receipt = commit(store, [{"id": "001"}, {"id": "002"}], request_id="original-observation")
    events = {row["record_id"]: row["event_id"] for row in store.history("price")["items"]}
    sent = store.claim("price", events["001"], "ntfy", "topic", OWNER)
    store.ack("price", events["001"], "ntfy", "topic", OWNER,
              claim_token=sent["claim_token"], receipt={"ok": True, "message_id": "preserved"})
    store.claim("price", events["002"], "ntfy", "topic", OWNER)
    staged = store.compare("price", [{"id": "003"}], OWNER, request_id="abandoned-observation")
    if legacy_deleted_row:
        # Earlier deletes retained events/run bodies; revive must clean existing rows too.
        with sqlite3.connect(store.db_path) as conn:
            conn.execute("UPDATE watches SET deleted_at=?,generation=generation+1,revision=revision+1 WHERE scope='cloud' AND key='price'", (clock[0],))
            conn.execute("UPDATE runs SET status='cancelled' WHERE scope='cloud' AND key='price' AND status='staged'")
    else:
        store.delete("price", OWNER)
        assert counts(store) == {"snapshots": 0, "runs": 2, "events": 0, "deliveries": 0, "handled_records": 1}
    with pytest.raises(NotFoundError):
        store.history("price")
    with pytest.raises(AuthorityError):
        store.register("price", {"id_field": "id"}, Authority("workflow:other"))

    clock[0] += 10
    fresh = register(store)
    assert fresh["initialized"] is False and fresh["last_success_at"] is None
    assert store.inspect("price")["snapshot_count"] == 0
    assert store.history("price")["items"] == store.pending("price")["items"] == []
    assert store.handled("price")["ids"] == ["001"]
    assert store.handled("price")["items"][0]["receipt"]["message_id"] == "preserved"
    with sqlite3.connect(store.db_path) as conn:
        runs = conn.execute("SELECT status,snapshot_json,changes_json,receipt_json FROM runs ORDER BY status").fetchall()
    assert [row[0] for row in runs] == ["cancelled", "committed"]
    assert all(row[1] is row[2] is None for row in runs)
    assert runs[1][3] is not None
    before_retry = (store.inspect("price"), counts(store))
    replay = store.commit("price", receipt["run_id"], OWNER)
    assert replay["already_committed"] is True and replay["event_ids"] == receipt["event_ids"]
    assert (store.inspect("price"), counts(store)) == before_retry
    with pytest.raises(ConflictError):
        store.commit("price", staged["run_id"], OWNER)
    for request_id in ("original-observation", "abandoned-observation"):
        with pytest.raises(ConflictError):
            store.compare("price", [{"id": "001"}, {"id": "002"}], OWNER, request_id=request_id)
    first, _ = commit(store, [{"id": "001"}])
    assert first["quiet_first"] is True and first["changes"] == []
    assert store.history("price")["items"] == []


def test_delete_history_is_scoped_and_reset_retains_existing_history_and_outbox(store):
    local = Store(store.project_root, "local", clock=store.clock)
    for active in (store, local):
        register(active, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
        commit(active, [{"id": "001"}])
    store.register("other", {"id_field": "id", "quiet_first": False}, OWNER)
    other_run = store.compare("other", [{"id": "other"}], OWNER)
    store.commit("other", other_run["run_id"], OWNER)
    history = store.history("price")
    pending = store.pending("price")
    store.reset("price", OWNER)
    assert store.history("price") == history and store.pending("price") == pending
    store.delete("price", OWNER)
    register(store)
    assert store.history("price")["items"] == []
    assert len(local.history("price")["items"]) == len(local.pending("price")["items"]) == 1
    assert len(store.history("other")["items"]) == 1


def test_staleness_is_opt_in_and_existing_explicit_cadence_is_preserved(store, clock):
    default = register(store)
    assert default["stale_after_seconds"] == 0
    store.register("scheduled", {"id_field": "id", "stale_after_seconds": 10}, OWNER)
    clock[0] += 365 * 86_400
    assert store.inspect("price")["stale"] is False
    scheduled = store.inspect("scheduled")
    assert scheduled["stale"] is True and scheduled["stale_after_seconds"] == 10
    assert store.health()["stale_count"] == 1


def test_trusted_ledger_check_success_clears_source_error_without_mutating_watch_work(store, clock):
    register(store, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
    run, _ = commit(store, [{"id": "001"}])
    event = run["changes"][0]["event_id"]
    claim = store.claim("price", event, "ntfy", "topic", OWNER)
    store.ack("price", event, "ntfy", "topic", OWNER, success=False, claim_token=claim["claim_token"])
    store.import_handled("price", [{"id": "legacy"}], OWNER, "email")
    staged = store.compare("price", [{"id": "002"}], OWNER)
    clock[0] += 5
    store.record_error("price", OWNER, "radar_discovery_limit_exceeded")
    before = store.inspect("price")
    work = (counts(store), store.history("price"), store.pending("price"), store.handled("price"))
    clock[0] += 5
    with pytest.raises(AuthorityError):
        store.record_check_success("price", Authority("workflow:other"))
    assert store.inspect("price") == before
    recovered = store.record_check_success("price", OWNER)
    assert recovered["last_run_at"] == recovered["last_success_at"] == clock[0]
    assert recovered["last_error"] is None and recovered["source_error_count"] == 0
    assert recovered["delivery_error_count"] == recovered["error_count"] == 1
    assert recovered["revision"] == before["revision"]
    assert store.inspect("price")["snapshot"] == before["snapshot"]
    assert (counts(store), store.history("price"), store.pending("price"), store.handled("price")) == work
    store.commit("price", staged["run_id"], OWNER)  # Success checks leave staged revisions usable.


def test_cleanup_expires_stages_and_history_but_keeps_commit_idempotency_and_undelivered_events(store, clock):
    register(store, quiet_first=False, retention_days=1)
    _, receipt = commit(store, [{"id": "001"}], request_id="durable-commit")
    staged = store.compare("price", [{"id": "002"}], OWNER)
    clock[0] += STAGE_TTL_SECONDS + 1
    result = store.cleanup("price", OWNER)
    assert result["expired_runs"] == 1 and result["events_deleted"] == 1
    assert store.history("price")["items"] == []
    repeated = store.commit("price", receipt["run_id"], OWNER)
    assert repeated["already_committed"] is True and repeated["event_ids"] == receipt["event_ids"]
    assert repeated["revision"] == receipt["revision"]
    with pytest.raises(ConflictError):
        store.commit("price", staged["run_id"], OWNER)


def test_cleanup_never_drops_pending_delivery_context(store, clock):
    register(store, quiet_first=False, retention_days=1, channels=[{"channel": "ntfy", "destination": "topic"}])
    run, _ = commit(store, [{"id": "001", "title": "Keep this pending event"}])
    clock[0] += 30 * 86_400
    commit(store, [{"id": "001", "title": "Keep this pending event"}])
    store.cleanup("price", OWNER)
    pending = store.pending("price")["items"]
    assert pending[0]["event_id"] == run["changes"][0]["event_id"]
    assert pending[0]["after"]["title"] == "Keep this pending event"


def test_safe_source_error_and_staleness_recover_only_after_a_successful_commit(store, clock):
    register(store, stale_after_seconds=10)
    _, previous = commit(store, [{"id": "001"}])
    clock[0] += 11
    assert store.health()["stale_count"] == 1
    store.record_error("price", OWNER)
    assert store.health()["error_count"] == 1 and store.inspect("price")["revision"] == previous["revision"]
    assert store.inspect("price")["last_success_at"] == previous["committed_at"]
    with pytest.raises(ValidationError):
        store.record_error("price", OWNER, "HTTP 401 secret=private")
    commit(store, [{"id": "001"}])
    assert store.health()["ok"] is True and store.health()["error_count"] == 0
    store.reset("price", OWNER)
    store.register("price", {"id_field": "id", "schema_version": 2, "stale_after_seconds": 0}, OWNER)
    clock[0] += 10_000_000
    assert store.health()["stale_count"] == 0


def test_real_sqlite_concurrent_revisions_commit_only_one_snapshot(store):
    register(store, quiet_first=False)
    first = store.compare("price", [{"id": "001", "price": 1}], OWNER)
    second = store.compare("price", [{"id": "001", "price": 2}], OWNER)

    def competing(run):
        other = Store(store.project_root, "cloud", clock=store.clock)
        try:
            return other.commit("price", run["run_id"], OWNER)
        except ConflictError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(competing, [first, second]))
    assert sum(result is not None for result in results) == 1
    assert store.inspect("price")["revision"] == 1
    assert counts(store)["events"] == counts(store)["snapshots"] == 1


def test_pagination_is_bounded_and_order_is_stable(store):
    register(store)
    store.import_handled("price", [{"id": f"{index:03d}"} for index in range(5)], OWNER, "email")
    assert store.handled("price", limit=2)["ids"] == ["000", "001"]
    assert store.handled("price", limit=2)["next_offset"] == 2
    assert store.handled("price", limit=2, offset=4)["next_offset"] is None
    for invalid in (0, 1001, True):
        with pytest.raises(ValidationError):
            store.handled("price", limit=invalid)


def test_writer_context_is_nested_trusted_and_invalid_workflows_do_not_borrow_authority(store):
    assert export_writer_context() == "interactive"
    with watch_writer_scope("price_watch"):
        assert export_writer_context() == "workflow:price_watch"
        with watch_writer_scope("other"):
            assert export_writer_context() == "workflow:other"
        assert export_writer_context() == "workflow:price_watch"
        with watch_writer_scope("invalid workflow!"):
            assert export_writer_context() == "workflow:unidentified"
            with pytest.raises(AuthorityError):
                store.register("forbidden", {"id_field": "id"}, Authority(export_writer_context()))
    assert export_writer_context() == "interactive"
    assert authority_from_environment({}).writer == "interactive"
    assert authority_from_environment({"JARVIS_INTERNAL_WATCH_WRITER": "workflow:price_watch"}) == OWNER
    with pytest.raises(AuthorityError):
        authority_from_environment({"JARVIS_INTERNAL_WATCH_WRITER": "workflow:price_watch\nadmin"})
    assert json.loads(json.dumps(OWNER.writer)) == "workflow:price_watch"


def test_abandoned_claims_count_against_the_retry_cap_and_park_without_another_send(store, clock):
    register(store, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
    run, _ = commit(store, [{"id": "001"}])
    event = run["changes"][0]["event_id"]
    previous_token = None
    for attempt in range(MAX_DELIVERY_ATTEMPTS):
        claim = store.claim("price", event, "ntfy", "topic", OWNER, lease_seconds=1)
        assert claim["claimed"] is True and claim["attempts"] == attempt + 1
        if attempt == 0:
            assert store.health()["ok"] is True  # An ordinary active first attempt is not a failure.
        previous_token = claim["claim_token"]
        clock[0] += 2
        assert store.health()["delivery_error_count"] == 1
    parked = store.claim("price", event, "ntfy", "topic", OWNER)
    assert parked["status"] == "parked" and parked["claimed"] is False and parked["claim_token"] is None
    assert parked["attempts"] == MAX_DELIVERY_ATTEMPTS
    assert store.pending("price")["items"] == []
    assert store.pending("price", include_parked=True)["items"][0]["status"] == "parked"
    with pytest.raises(ConflictError):
        store.ack("price", event, "ntfy", "topic", OWNER, claim_token=previous_token)


def test_admin_retry_recovers_a_parked_destination_without_new_events_or_handled_entries(store):
    register(store, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
    run, _ = commit(store, [{"id": "001"}])
    event = run["changes"][0]["event_id"]
    for _ in range(MAX_DELIVERY_ATTEMPTS):
        claim = store.claim("price", event, "ntfy", "topic", OWNER)
        store.ack("price", event, "ntfy", "topic", OWNER, success=False, claim_token=claim["claim_token"])
    with pytest.raises(AuthorityError):
        store.retry("price", event, "ntfy", "topic", OWNER)
    retry = store.retry("price", event, "ntfy", "topic", ADMIN)
    assert retry["event_id"] == event and retry["status"] == "pending" and retry["attempts"] == 0
    assert counts(store)["events"] == 1 and counts(store)["handled_records"] == 0
    claim = store.claim("price", event, "ntfy", "topic", OWNER)
    store.ack("price", event, "ntfy", "topic", OWNER, claim_token=claim["claim_token"], receipt={"ok": True})
    assert store.health()["ok"] is True and store.handled("price")["ids"] == ["001"]
    assert store.retry("price", event, "ntfy", "topic", ADMIN)["already_delivered"] is True


def test_discard_only_cancels_the_staged_run_and_success_frees_other_stale_stages(store):
    register(store, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
    commit(store, [{"id": "001", "price": 1}])
    before = store.inspect("price")
    first = store.compare("price", [{"id": "001", "price": 2}], OWNER)
    discarded = store.discard("price", first["run_id"], OWNER)
    assert discarded["already_discarded"] is False
    assert store.discard("price", first["run_id"], OWNER)["already_discarded"] is True
    assert store.inspect("price")["revision"] == before["revision"]
    assert len(store.pending("price")["items"]) == 1
    second = store.compare("price", [{"id": "001", "price": 3}], OWNER)
    stale = store.compare("price", [{"id": "001", "price": 4}], OWNER)
    store.commit("price", second["run_id"], OWNER)
    with pytest.raises(ConflictError):
        store.commit("price", stale["run_id"], OWNER)
    with sqlite3.connect(store.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs WHERE status='staged'").fetchone()[0] == 0
    with pytest.raises(ConflictError):
        store.discard("price", second["run_id"], OWNER)


def test_record_and_read_page_budgets_keep_all_persisted_changes_and_exact_pagination(store, clock):
    register(store, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
    with pytest.raises(ValidationError, match="16 KiB"):
        store.compare("price", [{"id": "oversize", "text": "x" * 16_384}], OWNER)
    for generation in range(3):
        clock[0] += 1
        records = [{"id": f"{index:03d}", "price": generation, "text": "x" * 15_000} for index in range(20)]
        run, receipt = commit(store, records)
        assert run["changes_count"] == 20 and run["changes_truncated"] is True
        assert len(json.dumps(run).encode()) < 270_000
        assert receipt["events_count"] == 20
    assert counts(store)["events"] == 60 and counts(store)["deliveries"] == 60
    for reader in (store.history, store.pending):
        observed = []
        offset = 0
        while True:
            page = reader("price", limit=1000, offset=offset)
            assert len(json.dumps(page).encode()) < 270_000
            observed.extend(row["event_id"] for row in page["items"])
            if page["next_offset"] is None:
                break
            assert page["next_offset"] == offset + len(page["items"])
            offset = page["next_offset"]
        assert len(observed) == len(set(observed)) == 60
    assert store.inspect("price")["snapshot_truncated"] is True
    assert len(json.dumps(store.inspect("price")).encode()) < 270_000


def test_normalized_small_scientific_numbers_and_ignored_nested_metadata_are_stable(store):
    register(store, normalizers={"number": "number"}, ignore_fields=["metadata.checked_at"])
    commit(store, [{"id": "001", "number": 0.00001, "metadata": {"checked_at": "old"}}])
    run, _ = commit(store, [{"id": "001", "number": "0.000010"}])
    assert run["changes"] == []


def test_an_explicit_failed_receipt_cannot_mark_delivery_success(store):
    register(store, quiet_first=False, channels=[{"channel": "ntfy", "destination": "topic"}])
    with pytest.raises(ValidationError):
        store.record_delivery("price", {"id": "001"}, "ntfy", "topic", OWNER, receipt={"ok": False})
    run, _ = commit(store, [{"id": "001"}])
    event = run["changes"][0]["event_id"]
    claim = store.claim("price", event, "ntfy", "topic", OWNER)
    with pytest.raises(ValidationError):
        store.ack("price", event, "ntfy", "topic", OWNER, claim_token=claim["claim_token"], receipt={"ok": False})
    assert store.handled("price")["items"] == []


def test_successful_writes_lazily_expire_history_without_losing_commit_or_handled_receipts(store, clock):
    register(store, quiet_first=False, retention_days=1)
    _, original = commit(store, [{"id": "001", "price": 1}])
    clock[0] += 2 * 86_400
    _, current = commit(store, [{"id": "001", "price": 2}])
    assert [event["run_id"] for event in store.history("price")["items"]] == [current["run_id"]]
    assert store.commit("price", original["run_id"], OWNER)["event_ids"] == original["event_ids"]
    clock[0] += 2 * 86_400
    store.record_delivery("price", {"id": "002"}, "email", "exact-recipient", OWNER,
                          receipt={"ok": True, "message_id": "permanent-delivery"})
    assert store.history("price")["items"] == []
    assert store.handled("price")["items"][0]["receipt"]["message_id"] == "permanent-delivery"
    assert store.commit("price", current["run_id"], OWNER)["already_committed"] is True
