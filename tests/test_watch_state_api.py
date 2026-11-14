"""Watch API requires its own mode-scoped Bearer auth, including localhost."""

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import watch as routes
from lib import config_loader
from lib.watch_state import Authority, Store
from lib.watch_state.service import MAX_REQUEST_BYTES

DEFINITION = {
    "id_field": "id",
    "compare_fields": ["price"],
    "quiet_first": False,
    "channels": [{"channel": "email", "destination": "test@example.test"}],
}
TOKENS = {"cloud": "watch-cloud-test-key", "local": "watch-local-test-key"}


def auth(mode="cloud"):
    return {"Authorization": f"Bearer {TOKENS[mode]}"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    for mode, token in TOKENS.items():
        (config / f"{mode}.env").write_text(f"JARVIS_API_KEY={token}\n")
    monkeypatch.setattr(config_loader, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(routes, "get_project_root", lambda: tmp_path)
    monkeypatch.setenv("JARVIS_MODE", "cloud")
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app, client=("127.0.0.1", 12345)) as value:
        yield value


@pytest.mark.parametrize(
    "path,method,body",
    [
        ("/api/watch", "get", None),
        ("/api/watch/", "get", None),
        ("/api/watch/health", "get", None),
        ("/api/watch/example", "get", None),
        ("/api/watch/example", "put", {"definition": DEFINITION}),
        ("/api/watch/example", "delete", {}),
        ("/api/watch/example/compare", "post", {"records": []}),
        ("/api/watch/example/commit", "post", {}),
        ("/api/watch/example/claim", "post", {}),
        ("/api/watch/example/ack", "post", {}),
        ("/api/watch/example/pending", "post", {}),
        ("/api/watch/example/history", "post", {}),
        ("/api/watch/example/handled", "post", {}),
        ("/api/watch/example/reset", "post", {}),
        ("/api/watch/example/mute", "post", {}),
        ("/api/watch/example/cleanup", "post", {}),
        ("/api/watch/example/record_error", "post", {}),
        ("/api/watch/example/retry", "post", {}),
        ("/api/watch/example/record_delivery", "post", {}),
    ],
)
def test_all_watch_routes_require_auth_even_on_loopback(client, tmp_path, path, method, body):
    kwargs = {} if body is None else {"json": body}
    assert client.request(method, path, **kwargs).status_code == 401
    assert (
        client.request(
            method, path, headers={"Authorization": "Bearer wrong"}, **kwargs
        ).status_code
        == 401
    )
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("mode", ["cloud", "local"])
def test_mode_specific_tokens_fail_closed_and_do_not_borrow_another_mode(client, tmp_path, mode):
    other = "local" if mode == "cloud" else "cloud"
    path = f"/api/watch?mode={mode}"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth(other)).status_code == 401
    response = client.get(path, headers=auth(mode))
    assert response.status_code == 200, response.text
    assert response.json()["data"]["mode"] == mode
    (tmp_path / "config" / f"{mode}.env").write_text("JARVIS_API_KEY=\n")
    assert client.get(path, headers=auth(mode)).status_code == 503
    assert client.get(path).status_code == 503


def test_authentication_precedes_body_parsing_and_declared_size_check(client, tmp_path):
    for body in ("{not json", "x" * (MAX_REQUEST_BYTES + 1)):
        assert client.post("/api/watch/example/compare", content=body).status_code == 401
    assert (
        client.post("/api/watch/example/compare", content="{not json", headers=auth()).status_code
        == 422
    )
    assert (
        client.post(
            "/api/watch/example/compare", content="x" * (MAX_REQUEST_BYTES + 1), headers=auth()
        ).status_code
        == 413
    )
    assert not (tmp_path / "data").exists()


def test_streaming_size_cap_works_without_a_content_length(client, tmp_path):
    def body():
        yield b'{"records":[{"id":"x","value":"'
        yield b"x" * MAX_REQUEST_BYTES
        yield b'"}]}'

    response = client.post(
        "/api/watch/example/compare",
        content=body(),
        headers={**auth(), "Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "body",
    [
        {"definition": DEFINITION, "writer": "workflow:other"},
        {"definition": DEFINITION, "actor": "administrator"},
        {"definition": DEFINITION, "admin": True},
        {"definition": DEFINITION, "db_path": "/private/state.db"},
        {"definition": DEFINITION, "project_root": "/private"},
        {"definition": DEFINITION, "mode": "shared"},
        {"definition": DEFINITION, "key": "other"},
        {"records": [], "dry_run": "true"},
        {"records": [], "dry_run": 1},
        {"records": [], "complete": "false"},
        {"records": [{}] * 1001},
    ],
)
def test_api_forbids_untrusted_fields_and_loose_types_before_storage(client, tmp_path, body):
    action = "register" if "definition" in body else "compare"
    response = client.post(f"/api/watch/example/{action}", json=body, headers=auth())
    assert response.status_code == 422, response.text
    assert not (tmp_path / "data").exists()


def test_api_register_owner_is_admin_only_and_does_not_turn_other_fields_into_authority(
    client, tmp_path
):
    response = client.put(
        "/api/watch/price",
        json={"definition": DEFINITION, "owner": "workflow:prices"},
        headers=auth(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["owner"] == "workflow:prices"
    response = client.post(
        "/api/watch/price/compare", json={"records": [], "owner": "interactive"}, headers=auth()
    )
    assert response.status_code == 400
    assert Store(tmp_path, "cloud").inspect("price")["owner"] == "workflow:prices"
    response = client.post("/api/watch/price/compare", json={"records": []}, headers=auth())
    assert response.status_code == 200  # API administrator may operate an owned watch.


def test_api_compares_commits_claims_and_acks_without_delivering(client, tmp_path):
    base = "/api/watch/prices/laptop"
    assert client.put(base, json={"definition": DEFINITION}, headers=auth()).status_code == 200
    preview = client.post(
        base + "/compare", json={"records": [{"id": "001", "price": 0}]}, headers=auth()
    ).json()["data"]
    assert preview["status"] == "staged" and preview["scope"] == preview["mode"] == "cloud"
    assert client.get(base, headers=auth()).json()["data"]["revision"] == 0
    committed = client.post(base + "/commit", json={"run_id": preview["run_id"]}, headers=auth())
    assert committed.status_code == 200, committed.text
    assert committed.json()["data"]["events_count"] == 1
    pending = client.post(base + "/pending", json={}, headers=auth()).json()["data"]["items"]
    assert len(pending) == 1 and pending[0]["record_id"] == "001"
    identity = {
        "event_id": pending[0]["event_id"],
        "channel": "email",
        "destination": "test@example.test",
    }
    assert client.post(base + "/ack", json=identity, headers=auth()).status_code == 409
    claim = client.post(base + "/claim", json=identity, headers=auth()).json()["data"]
    token = claim["claim_token"]
    assert isinstance(token, str) and len(token) >= 16
    assert client.post(base + "/claim", json=identity, headers=auth()).status_code == 409
    delivered = client.post(
        base + "/ack",
        json={**identity, "claim_token": token, "receipt": {"status": "sent"}},
        headers=auth(),
    )
    assert delivered.status_code == 200, delivered.text
    assert client.post(base + "/pending", json={}, headers=auth()).json()["data"]["items"] == []
    history = client.post(base + "/history", json={}, headers=auth()).json()["data"]["items"]
    assert len(history) == 1 and history[0]["after"]["price"] == 0
    assert Store(tmp_path, "cloud").inspect("prices/laptop")["revision"] == 1
    repeated_claim = client.post(base + "/claim", json=identity, headers=auth())
    assert repeated_claim.status_code == 200
    assert repeated_claim.json()["data"]["claimed"] is False
    assert repeated_claim.json()["data"]["claim_token"] is None
    assert "Do not send" in repeated_claim.json()["speech"]


def test_abandoned_delivery_claims_exhaust_without_authorizing_another_send(client, monkeypatch):
    import lib.watch_state as core

    real_store = core.Store
    now = [1_000.0]
    monkeypatch.setattr(
        core, "Store", lambda root, mode: real_store(root, mode, clock=lambda: now[0])
    )
    path = "/api/watch/abandoned"
    assert client.put(path, json={"definition": DEFINITION}, headers=auth()).status_code == 200
    run = client.post(
        path + "/compare", json={"records": [{"id": "001", "price": 2}]}, headers=auth()
    ).json()["data"]
    committed = client.post(
        path + "/commit", json={"run_id": run["run_id"]}, headers=auth()
    ).json()["data"]
    identity = {
        "event_id": committed["event_ids"][0],
        "channel": "email",
        "destination": "test@example.test",
    }
    for _ in range(5):
        claim = client.post(path + "/claim", json={**identity, "lease_seconds": 60}, headers=auth())
        assert claim.status_code == 200 and claim.json()["data"]["claimed"] is True
        assert claim.json()["data"]["claim_token"]
        now[0] += 61
    exhausted = client.post(path + "/claim", json=identity, headers=auth())
    assert exhausted.status_code == 200
    assert exhausted.json()["data"]["claimed"] is False
    assert exhausted.json()["data"]["status"] == "parked"
    assert exhausted.json()["data"]["claim_token"] is None
    assert "Do not send" in exhausted.json()["speech"]
    assert client.post(path + "/handled", json={}, headers=auth()).json()["data"]["ids"] == []


def test_api_dry_run_and_error_recovery_keep_the_committed_baseline(client, tmp_path):
    path = "/api/watch/prices/example"
    assert client.put(path, json={"definition": DEFINITION}, headers=auth()).status_code == 200
    preview = client.post(
        path + "/compare",
        json={"records": [{"id": "001", "price": 0}], "dry_run": True},
        headers=auth(),
    )
    assert preview.status_code == 200 and preview.json()["data"]["dry_run"] is True
    assert Store(tmp_path, "cloud").inspect("prices/example")["revision"] == 0
    error = client.post(
        path + "/record_error", json={"error_code": "source_fetch_failed"}, headers=auth()
    )
    assert error.status_code == 200, error.text
    assert error.json()["data"]["last_error"]["code"] == "source_fetch_failed"
    assert error.json()["data"]["revision"] == 0
    assert (
        client.post(
            path + "/record_error", json={"error_code": "SECRET /private/exception"}, headers=auth()
        ).status_code
        == 422
    )
    cleanup = client.post(path + "/cleanup", json={"limit": 1}, headers=auth())
    assert cleanup.status_code == 200 and cleanup.json()["data"]["handled_preserved"] is True
    assert cleanup.json()["data"]["action"] == "cleanup"
    staged = client.post(
        path + "/compare", json={"records": [{"id": "001", "price": 0}]}, headers=auth()
    ).json()["data"]
    assert (
        client.post(path + "/commit", json={"run_id": staged["run_id"]}, headers=auth()).status_code
        == 200
    )
    healthy = client.get("/api/watch/health?key=prices/example", headers=auth()).json()["data"]
    assert healthy["error_count"] == 0 and healthy["items"][0]["last_error"] is None


def test_api_reset_retains_an_already_claimed_delivery_and_exact_ack_token(client):
    path = "/api/watch/reset-test"
    assert client.put(path, json={"definition": DEFINITION}, headers=auth()).status_code == 200
    run = client.post(
        path + "/compare", json={"records": [{"id": "001", "price": 4}]}, headers=auth()
    ).json()["data"]
    committed = client.post(
        path + "/commit", json={"run_id": run["run_id"]}, headers=auth()
    ).json()["data"]
    identity = {
        "event_id": committed["event_ids"][0],
        "channel": "email",
        "destination": "test@example.test",
    }
    claim = client.post(path + "/claim", json=identity, headers=auth()).json()["data"]
    reset = client.post(path + "/reset", json={}, headers=auth())
    assert reset.status_code == 200 and reset.json()["data"]["pending_count"] == 1
    assert reset.json()["data"]["initialized"] is False
    ack = client.post(
        path + "/ack", json={**identity, "claim_token": claim["claim_token"]}, headers=auth()
    )
    assert ack.status_code == 200, ack.text


def test_api_can_discard_one_staged_run_without_resetting_the_watch(client):
    path = "/api/watch/discard-test"
    assert client.put(path, json={"definition": DEFINITION}, headers=auth()).status_code == 200
    run = client.post(
        path + "/compare", json={"records": [{"id": "001", "price": 2}]}, headers=auth()
    ).json()["data"]
    discarded = client.post(path + "/discard", json={"run_id": run["run_id"]}, headers=auth())
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["data"]["status"] == "cancelled"
    assert client.get(path, headers=auth()).json()["data"]["revision"] == 0
    assert (
        client.post(path + "/commit", json={"run_id": run["run_id"]}, headers=auth()).status_code
        == 409
    )


def test_administrator_can_explicitly_retry_a_parked_delivery_with_same_event_identity(client):
    path = "/api/watch/parked"
    assert client.put(path, json={"definition": DEFINITION}, headers=auth()).status_code == 200
    run = client.post(
        path + "/compare", json={"records": [{"id": "001", "price": 2}]}, headers=auth()
    ).json()["data"]
    committed = client.post(
        path + "/commit", json={"run_id": run["run_id"]}, headers=auth()
    ).json()["data"]
    identity = {
        "event_id": committed["event_ids"][0],
        "channel": "email",
        "destination": "test@example.test",
    }
    for _ in range(5):
        claim = client.post(path + "/claim", json=identity, headers=auth())
        assert claim.status_code == 200, claim.text
        failed = client.post(
            path + "/ack",
            json={
                **identity,
                "claim_token": claim.json()["data"]["claim_token"],
                "success": False,
                "error": "delivery_unavailable",
            },
            headers=auth(),
        )
        assert failed.status_code == 200, failed.text
    assert failed.json()["data"]["status"] == "parked"
    assert client.post(path + "/claim", json=identity, headers=auth()).status_code == 409
    retried = client.post(path + "/retry", json=identity, headers=auth())
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["event_id"] == identity["event_id"]
    assert retried.json()["data"]["status"] == "pending" and retried.json()["data"]["attempts"] == 0
    pending = client.post(path + "/pending", json={}, headers=auth()).json()["data"]["items"]
    assert len(pending) == 1 and pending[0]["event_id"] == identity["event_id"]


@pytest.mark.parametrize("key", ["prices/laptop", "prices/history", "prices/pending", "health"])
def test_api_namespaced_and_reserved_suffix_keys_keep_their_exact_identity(client, key):
    path = f"/api/watch/{key}"
    assert client.put(path, json={"definition": DEFINITION}, headers=auth()).status_code == 200
    if key == "health":
        response = client.post(path + "/inspect", json={}, headers=auth())
    else:
        response = client.get(path, headers=auth())
    assert response.status_code == 200, response.text
    assert response.json()["data"]["key"] == key
    assert client.post(path + "/history", json={}, headers=auth()).status_code == 200


def test_api_modes_and_default_active_mode_do_not_mutate_each_other(client, monkeypatch):
    for mode in ("cloud", "local"):
        response = client.put(
            f"/api/watch/same?mode={mode}",
            json={"definition": DEFINITION, "owner": f"workflow:{mode}"},
            headers=auth(mode),
        )
        assert response.status_code == 200
        assert response.json()["data"]["owner"] == f"workflow:{mode}"
    monkeypatch.setenv("JARVIS_MODE", "local")
    default = client.get("/api/watch/same", headers=auth("local"))
    assert default.status_code == 200
    assert default.json()["data"]["mode"] == "local"
    assert default.json()["data"]["owner"] == "workflow:local"
    assert (
        client.get("/api/watch/same?mode=cloud", headers=auth()).json()["data"]["owner"]
        == "workflow:cloud"
    )


@pytest.mark.parametrize("mode", ["shared", "invalid", "LOCAL", ""])
def test_api_rejects_unknown_modes(client, mode):
    assert client.get(f"/api/watch?mode={mode}", headers=auth()).status_code == 422


def test_api_storage_errors_do_not_expose_paths_or_secrets(client, monkeypatch):
    import lib.watch_state as core

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("PRIVATE_SENTINEL /private/database secret=credential")

    monkeypatch.setattr(core, "Store", fail)
    response = client.get("/api/watch", headers=auth())
    assert response.status_code == 503
    assert "PRIVATE_SENTINEL" not in response.text and "/private" not in response.text


def test_public_http_never_exposes_internal_radar_migration(client, tmp_path):
    response = client.post("/api/watch/upcoming_movie_radar/radar_history", json={}, headers=auth())
    assert response.status_code == 422
    assert not (tmp_path / "data").exists()


def test_api_health_includes_reviewed_shared_radars_without_showing_other_mode(client, tmp_path):
    Store(tmp_path, "shared").register(
        "upcoming_movie_radar",
        {"id_field": "tmdb_id", "stale_after_seconds": 0},
        Authority("workflow:upcoming_movie_radar"),
    )
    Store(tmp_path, "local").register("local-only", {"id_field": "id"}, Authority("interactive"))
    response = client.get("/api/watch/health", headers=auth())
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["mode"] == data["scope"] == "cloud"
    assert [item["key"] for item in data["items"]] == ["upcoming_movie_radar"]
    assert data["items"][0]["scope"] == "shared"
    keyed = client.get("/api/watch/health?key=upcoming_movie_radar", headers=auth()).json()["data"]
    assert keyed["mode"] == "cloud" and keyed["scope"] == "shared"


@pytest.mark.parametrize("auth_enabled", ["true", "false"])
def test_mandatory_watch_auth_remains_active_under_real_api_middleware(
    client, tmp_path, monkeypatch, auth_enabled
):
    from api import server

    monkeypatch.setattr(
        server,
        "get_config_value",
        lambda key, default="": {
            "JARVIS_API_AUTH": auth_enabled,
            "JARVIS_API_KEY": TOKENS["cloud"],
        }.get(key, default),
    )
    app = FastAPI()
    app.include_router(routes.router)
    app.add_middleware(server.APIAuthMiddleware)
    with TestClient(app, client=("198.51.100.10", 23456)) as full:
        for mode in ("cloud", "local"):
            url = f"/api/watch?mode={mode}"
            assert full.get(url).status_code == 401
            assert full.get(url, headers={"Authorization": "Bearer wrong"}).status_code == 401
            assert full.get(url, headers=auth(mode)).status_code == 200
        (tmp_path / "config" / "local.env").write_text("JARVIS_API_KEY=\n")
        assert full.get("/api/watch?mode=local", headers=auth("local")).status_code == 503
