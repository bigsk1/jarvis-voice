"""Foreground watch adapters use trusted identities and temporary databases."""

import json
import runpy
import sqlite3
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from lib import config_loader, paths
from lib.watch_state import Store, service
from lib.watch_state.normalization import SHARED_RADAR_KEYS
from skills import watch_state as tool

DEFINITION = {"id_field": "id", "compare_fields": ["price", "available"], "quiet_first": False}


@pytest.fixture
def invoke(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "load_config", lambda: None)
    monkeypatch.setattr(tool, "get_project_root", lambda: tmp_path)

    def call(arguments, *, writer="interactive", mode="cloud"):
        monkeypatch.setenv("JARVIS_INTERNAL_WATCH_WRITER", writer)
        monkeypatch.setattr(tool, "get_active_config_mode", lambda: mode)
        monkeypatch.setattr(sys, "argv", ["watch_state.py", json.dumps(arguments)])
        output = StringIO()
        with redirect_stdout(output):
            code = tool.main()
        result = json.loads(output.getvalue())
        assert isinstance(result["ok"], bool) and isinstance(result["speech"], str)
        return code, result

    return call


def test_tool_owner_is_trusted_workflow_and_caller_fields_cannot_override_it(invoke, tmp_path):
    key = "prices/laptop"
    code, registered = invoke(
        {"action": "register", "key": key, "definition": DEFINITION}, writer="workflow:prices"
    )
    assert code == 0 and registered["data"]["owner"] == "workflow:prices"
    for writer in ("interactive", "workflow:other", "api"):
        code, denied = invoke(
            {
                "action": "compare",
                "key": key,
                "records": [{"id": "001", "price": 0, "available": False}],
            },
            writer=writer,
        )
        assert code == 1 and denied["error"] == "watch_owner_required"
        assert "owner" in denied["speech"].lower() or "writer" in denied["speech"].lower()
    code, allowed = invoke(
        {
            "action": "compare",
            "key": key,
            "records": [{"id": "001", "price": 0, "available": False}],
        },
        writer="workflow:prices",
    )
    assert code == 0 and allowed["data"]["run_id"]
    assert allowed["data"]["action"] == "compare"
    assert allowed["data"]["mode"] == allowed["data"]["scope"] == "cloud"
    assert Store(tmp_path, "cloud").inspect(key)["revision"] == 0


@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "register", "key": "x", "definition": DEFINITION, "owner": "workflow:other"},
        {"action": "list", "writer": "api"},
        {"action": "list", "admin": True},
        {"action": "list", "actor": "admin"},
        {"action": "list", "db_path": "/private/state.db"},
        {"action": "list", "root": "/tmp"},
        {"action": "list", "mode": "shared"},
        {"action": "compare", "key": "x", "records": [], "dry_run": 1},
        {"action": "compare", "key": "x", "records": "not records"},
        {"action": "compare", "key": "x", "records": [{}] * 1001},
        {"action": "list", "limit": True},
        {"action": "list", "limit": 1001},
        {"action": "mute", "key": "x", "seconds": True},
        {
            "action": "claim",
            "key": "x",
            "event_id": "e",
            "channel": "email",
            "destination": "test@example.test",
            "lease_seconds": 3601,
        },
        {"action": "unknown"},
        [],
    ],
)
def test_tool_rejects_invalid_arguments_before_creating_storage(invoke, tmp_path, arguments):
    code, result = invoke(arguments)
    assert code == 1 and result["error"] == "invalid_watch_request"
    assert not (tmp_path / "data").exists()


def test_tool_rejects_oversize_or_nonfinite_input_without_storage(invoke, tmp_path):
    for value in ("x" * service.MAX_REQUEST_BYTES, float("inf")):
        code, result = invoke(
            {
                "action": "register",
                "key": "x",
                "definition": {"id_field": "id", "unexpected": value},
            }
        )
        assert code == 1 and result["ok"] is False
    assert not (tmp_path / "data").exists()


def test_dry_run_changes_neither_baseline_nor_database_bytes(invoke, tmp_path):
    assert invoke({"action": "register", "key": "price", "definition": DEFINITION})[0] == 0
    database = tmp_path / "data" / "watch_state.db"
    before = database.read_bytes()
    code, preview = invoke(
        {
            "action": "compare",
            "key": "price",
            "records": [{"id": "001", "price": 0, "available": False}],
            "dry_run": True,
        }
    )
    assert code == 0 and "preview" in preview["speech"].lower()
    assert database.read_bytes() == before
    assert Store(tmp_path, "cloud").inspect("price")["revision"] == 0


def test_tool_active_modes_are_isolated_without_a_mode_argument(invoke):
    for mode in ("cloud", "local"):
        code, registered = invoke(
            {"action": "register", "key": "same", "definition": DEFINITION},
            writer=f"workflow:{mode}",
            mode=mode,
        )
        assert code == 0 and registered["data"]["scope"] == mode
        assert registered["data"]["owner"] == f"workflow:{mode}"
    code, inspected = invoke({"action": "inspect", "key": "same"}, mode="local")
    assert code == 0 and inspected["data"]["owner"] == "workflow:local"


def test_custom_workflow_is_mode_scoped_readable_and_cannot_borrow_radar_identity(invoke):
    key, writer = "custom_watch", "workflow:custom_watch"
    assert invoke({"action": "register", "key": key, "definition": DEFINITION}, writer=writer)[0] == 0
    code, missing = invoke({"action": "inspect", "key": key}, writer=writer, mode="local")
    assert code == 1 and missing["error"] == "watch_not_found"

    code, inspected = invoke({"action": "inspect", "key": key}, writer="workflow:other")
    assert code == 0 and inspected["data"]["owner"] == writer
    code, denied = invoke({"action": "reset", "key": key}, writer="workflow:other")
    assert code == 1 and denied["error"] == "watch_owner_required"
    for radar in SHARED_RADAR_KEYS:
        for arguments in (
            {"action": "radar_history", "key": radar},
            {"action": "register", "key": radar, "definition": {"id_field": "tmdb_id"}},
        ):
            code, denied = invoke(arguments, writer=writer)
            assert code == 1 and denied["error"] == "watch_owner_required"


@pytest.mark.parametrize("key", sorted(SHARED_RADAR_KEYS))
def test_reviewed_radar_registration_uses_same_ledger_from_both_modes(invoke, key):
    writer = f"workflow:{key}"
    code, registered = invoke(
        {"action": "register", "key": key, "definition": {"id_field": "tmdb_id"}},
        writer=writer,
    )
    assert code == 0 and registered["data"]["scope"] == "shared"
    code, inspected = invoke({"action": "inspect", "key": key}, writer=writer, mode="local")
    assert code == 0 and inspected["data"]["scope"] == "shared"
    assert inspected["data"]["owner"] == writer


def test_tool_sanitizes_storage_failure_and_invalid_writer_context(invoke, monkeypatch):
    import lib.watch_state as core

    def broken_store(*args, **kwargs):
        raise sqlite3.OperationalError("PRIVATE_SENTINEL /private/database token=secret")

    monkeypatch.setattr(core, "Store", broken_store)
    code, result = invoke({"action": "list"})
    assert code == 1 and result["error"] == "storage_unavailable"
    assert "PRIVATE_SENTINEL" not in json.dumps(result)
    code, result = invoke({"action": "list"}, writer='{"writer":"api","admin":true}')
    assert code == 1 and result["error"] == "watch_owner_required"


def _legacy_manifest(stash, key, files):
    space = stash / f"space_{key}"
    space.mkdir(parents=True, exist_ok=True)
    (space / "meta.json").write_text(json.dumps({"files": files}))


def test_radar_migration_preserves_ever_emailed_ids_and_late_other_mode_writes(
    invoke, tmp_path, monkeypatch
):
    stash = tmp_path / "stash"
    key = "upcoming_movie_radar"
    monkeypatch.setattr(service, "get_stash_dir", lambda: stash)
    files = [
        {"name": "123", "kind": "json", "stored_name": "unrelated-storage-name.json"},
        {"name": "456", "mime_type": "application/json"},
        {"name": "123.json", "kind": "json"},
        {"name": "789", "kind": "text"},
        {"name": "../999", "kind": "json"},
    ]
    _legacy_manifest(stash, key, files)
    code, first = invoke({"action": "radar_history", "key": key}, writer=f"workflow:{key}")
    assert code == 0 and set(first["data"]["handled_ids"]) == {"123", "456"}
    assert first["data"]["scope"] == "shared" and first["data"]["mode"] == "cloud"
    files.append({"name": "999", "kind": "json"})
    _legacy_manifest(stash, key, files)
    code, repeated = invoke(
        {"action": "radar_history", "key": key}, writer=f"workflow:{key}", mode="local"
    )
    assert code == 0 and set(repeated["data"]["handled_ids"]) == {"123", "456", "999"}
    assert repeated["data"]["scope"] == "shared" and repeated["data"]["mode"] == "local"
    _legacy_manifest(stash, key, [])
    code, permanent = invoke({"action": "radar_history", "key": key}, writer=f"workflow:{key}")
    assert code == 0 and set(permanent["data"]["handled_ids"]) == {"123", "456", "999"}
    assert Store(tmp_path, "shared").inspect(key)["definition"]["stale_after_seconds"] == 0
    assert not Store(tmp_path, "shared").health(key)["items"][0]["stale"]


@pytest.mark.parametrize("writer", ["interactive", "workflow:upcoming_tv_radar", "api"])
def test_radar_migration_requires_the_exact_matching_workflow(
    invoke, tmp_path, monkeypatch, writer
):
    def forbidden_stash():
        raise AssertionError("unauthorized migration must not inspect Stash")

    monkeypatch.setattr(service, "get_stash_dir", forbidden_stash)
    code, result = invoke({"action": "radar_history", "key": "upcoming_movie_radar"}, writer=writer)
    assert code == 1 and result["error"] == "watch_owner_required"
    assert not (tmp_path / "data").exists()


def test_radar_bad_legacy_history_fails_closed_before_registering(invoke, tmp_path, monkeypatch):
    stash = tmp_path / "stash"
    key = "upcoming_tv_radar"
    monkeypatch.setattr(service, "get_stash_dir", lambda: stash)
    path = stash / f"space_{key}"
    path.mkdir(parents=True)
    (path / "meta.json").write_text("{broken")
    code, result = invoke({"action": "radar_history", "key": key}, writer=f"workflow:{key}")
    assert code == 1 and "safely" in result["speech"]
    assert not (tmp_path / "data").exists()


def test_radar_legacy_manifest_cannot_escape_stash_through_a_symlink(invoke, tmp_path, monkeypatch):
    stash = tmp_path / "stash"
    stash.mkdir()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "meta.json").write_text(json.dumps({"files": [{"name": "123", "kind": "json"}]}))
    (stash / "space_upcoming_movie_radar").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(service, "get_stash_dir", lambda: stash)
    code, result = invoke(
        {"action": "radar_history", "key": "upcoming_movie_radar"},
        writer="workflow:upcoming_movie_radar",
    )
    assert code == 1 and "outside" in result["speech"]
    assert str(outside) not in result["speech"]
    assert not (tmp_path / "data").exists()


def test_radar_oversize_legacy_manifest_fails_without_partial_import(invoke, tmp_path, monkeypatch):
    stash = tmp_path / "stash"
    _legacy_manifest(
        stash, "upcoming_movie_radar", [{"name": str(i), "kind": "json"} for i in range(20)]
    )
    monkeypatch.setattr(service, "get_stash_dir", lambda: stash)
    monkeypatch.setattr(service, "MAX_LEGACY_BYTES", 128)
    code, result = invoke(
        {"action": "radar_history", "key": "upcoming_movie_radar"},
        writer="workflow:upcoming_movie_radar",
    )
    assert code == 1 and "size limit" in result["speech"]
    assert not (tmp_path / "data").exists()


def test_radar_discovery_limit_fails_closed_without_losing_ever_emailed_ids(
    invoke, tmp_path, monkeypatch
):
    stash = tmp_path / "stash"
    key = "upcoming_movie_radar"
    _legacy_manifest(stash, key, [{"name": str(i), "kind": "json"} for i in range(501)])
    monkeypatch.setattr(service, "get_stash_dir", lambda: stash)
    code, result = invoke({"action": "radar_history", "key": key}, writer=f"workflow:{key}")
    assert code == 1 and result["ok"] is False
    assert "500 excluded IDs" in result["speech"] and "history was preserved" in result["speech"]
    assert "No IDs were truncated or reset" in result["speech"]
    ledger = Store(tmp_path, "shared").handled(key, "email", limit=1000)
    assert set(ledger["ids"]) == {str(i) for i in range(501)}
    health = Store(tmp_path, "cloud").health()
    assert health["ok"] is False and health["error_count"] == 1
    assert health["items"][0]["last_error"]["code"] == "radar_discovery_limit_exceeded"

    # A later valid check clears this operational error without resetting sent IDs.
    monkeypatch.setattr(service, "MAX_RADAR_EXCLUSIONS", 1000)
    code, recovered = invoke({"action": "radar_history", "key": key}, writer=f"workflow:{key}")
    assert code == 0 and len(recovered["data"]["handled_ids"]) == 501
    health = Store(tmp_path, "local").health()
    assert health["ok"] is True and health["error_count"] == 0
    assert health["items"][0]["last_success_at"] is not None


def test_radar_delivery_requires_actual_sent_receipt_and_resolved_recipient(
    invoke, tmp_path, monkeypatch
):
    key = "upcoming_tv_radar"
    monkeypatch.setattr(service, "get_stash_dir", lambda: tmp_path / "stash")
    assert invoke({"action": "radar_history", "key": key}, writer=f"workflow:{key}")[0] == 0
    arguments = {
        "action": "record_delivery",
        "key": key,
        "record": {
            "tmdb_id": "123",
            "title": "Example",
            "tmdb_url": "https://www.themoviedb.org/tv/123",
        },
        "channel": "email",
        "destination": "test@example.test",
        "receipt": {"ok": True, "data": {"status": "sent", "to": "test@example.test"}},
    }
    for receipt in (
        {"ok": False, "data": {"status": "sent", "to": "test@example.test"}},
        {"ok": True, "data": {"status": "queued", "to": "test@example.test"}},
        {"ok": True, "data": {"status": "sent", "to": "other@example.test"}},
    ):
        assert invoke({**arguments, "receipt": receipt}, writer=f"workflow:{key}")[0] == 1
    assert invoke(arguments, writer=f"workflow:{key}")[0] == 0
    code, history = invoke(
        {"action": "radar_history", "key": key}, writer=f"workflow:{key}", mode="local"
    )
    assert code == 0 and history["data"]["handled_ids"] == ["123"]


def test_generic_delivery_cannot_mark_an_explicitly_failed_receipt_handled(invoke):
    assert (
        invoke({"action": "register", "key": "generic", "definition": {"id_field": "id"}})[0] == 0
    )
    args = {
        "action": "record_delivery",
        "key": "generic",
        "record": {"id": "001"},
        "channel": "email",
        "destination": "test@example.test",
        "receipt": {"ok": False},
    }
    code, failed = invoke(args)
    assert code == 1 and "successful standard receipt" in failed["speech"]
    assert invoke({"action": "handled", "key": "generic"})[1]["data"]["ids"] == []
    assert invoke({**args, "receipt": {"ok": True, "data": {"status": "sent"}}})[0] == 0
    assert invoke({"action": "handled", "key": "generic"})[1]["data"]["ids"] == ["001"]


def test_ordinary_tool_cannot_restart_a_parked_delivery_retry_loop(invoke, tmp_path):
    code, result = invoke(
        {
            "action": "retry",
            "key": "x",
            "event_id": "event",
            "channel": "email",
            "destination": "test@example.test",
        }
    )
    assert code == 1 and result["error"] == "watch_owner_required"
    assert not (tmp_path / "data").exists()


def test_real_script_entrypoint_uses_json_runner_and_trusted_interactive_default(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(config_loader, "load_config", lambda: None)
    monkeypatch.setattr(paths, "get_project_root", lambda: tmp_path)
    monkeypatch.setenv("JARVIS_MODE", "local")
    monkeypatch.delenv("JARVIS_INTERNAL_WATCH_WRITER", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "watch_state.py",
            json.dumps({"action": "register", "key": "runner", "definition": DEFINITION}),
        ],
    )
    output = StringIO()
    with redirect_stdout(output), pytest.raises(SystemExit) as exited:
        runpy.run_path(str(Path(tool.__file__)), run_name="__main__")
    assert exited.value.code == 0
    result = json.loads(output.getvalue())
    assert result["data"]["owner"] == "interactive" and result["data"]["mode"] == "local"
    assert Store(tmp_path, "local").inspect("runner")["owner"] == "interactive"


def test_manifest_is_credential_free_and_does_not_accept_authority_or_storage_fields():
    manifest = json.loads(Path(tool.__file__).with_suffix(".tool.json").read_text())
    assert manifest["child_environment"] == {
        "mode": "restricted",
        "from_availability": False,
        "allow": ["STASH_DIR"],
    }
    assert manifest["permissions"]["network"] is False
    schema = manifest["parameters"]
    assert schema["additionalProperties"] is False
    assert not (
        {"owner", "writer", "actor", "admin", "mode", "root", "db_path"}
        & schema["properties"].keys()
    )
    assert {"claim", "ack", "radar_history", "record_delivery"} <= set(
        schema["properties"]["action"]["enum"]
    )
    assert "retry" not in schema["properties"]["action"]["enum"]
