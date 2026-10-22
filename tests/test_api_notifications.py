"""Notification REST validation, mode isolation, and real API auth middleware."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import notifications as routes
from lib.config_loader import config_scope


@pytest.fixture
def client(tmp_path, monkeypatch):
    from api import server

    monkeypatch.setattr(routes, "get_project_root", lambda: tmp_path)
    monkeypatch.setattr(
        server,
        "get_config_value",
        lambda key, default="": {
            "JARVIS_API_AUTH": "true",
            "JARVIS_API_KEY": "notification-test-key",
        }.get(key, default),
    )
    app = FastAPI()
    app.include_router(routes.router)
    app.add_middleware(server.APIAuthMiddleware)
    with TestClient(app, client=("198.51.100.42", 54321)) as value:
        yield value


AUTH = {"Authorization": "Bearer notification-test-key"}
PAYLOAD = {"title": "Cleanup complete", "message": "All stages succeeded.", "source": "cleanup_all"}


@pytest.mark.parametrize("path", ["/api/notifications", "/api/notifications/"])
@pytest.mark.parametrize("method", ["get", "post"])
def test_api_requires_configured_auth_for_every_route_alias(client, tmp_path, path, method):
    call = getattr(client, method)
    kwargs = {"json": PAYLOAD} if method == "post" else {}
    assert call(path, **kwargs).status_code == 401
    assert call(path, headers={"Authorization": "Bearer incorrect"}, **kwargs).status_code == 403
    assert not (tmp_path / "data").exists()
    assert call(path, headers=AUTH, **kwargs).status_code == 200


def test_api_create_dedupe_and_mode_filtered_history(client):
    payload = {**PAYLOAD, "mode": "local", "dedupe_key": "run-7", "channels": []}
    first = client.post("/api/notifications", json=payload, headers=AUTH).json()["data"]
    repeated = client.post("/api/notifications", json=payload, headers=AUTH).json()["data"]
    assert first["id"] == repeated["id"] and repeated["deduplicated"]
    assert first["state"] == "saved" and first["deliveries"] == []
    local = client.get("/api/notifications?mode=local&source=cleanup_all", headers=AUTH).json()
    assert local["total"] == 1 and local["items"][0]["id"] == first["id"]
    assert client.get("/api/notifications?mode=cloud", headers=AUTH).json()["total"] == 0
    assert (
        client.get("/api/notifications?mode=local&source_type=notifications", headers=AUTH).json()[
            "total"
        ]
        == 1
    )
    assert (
        client.get("/api/notifications?mode=local&source_type=alerts", headers=AUTH).json()["total"]
        == 0
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "invalid"},
        {"title": " "},
        {"message": "x" * 2001},
        {"source": "x" * 81},
        {"channels": ["discord"]},
        {"channels": ["ntfy", "ntfy"]},
        {"max_age_seconds": True},
        {"max_age_seconds": 1},
        {"publisher_token": "PRIVATE_SENTINEL"},
    ],
)
def test_api_rejects_invalid_creation_before_storage(client, tmp_path, changes):
    response = client.post("/api/notifications", json={**PAYLOAD, **changes}, headers=AUTH)
    assert response.status_code in {400, 422}, response.text
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize(
    "query",
    [
        "mode=invalid",
        "source_type=invalid",
        "limit=0",
        "limit=101",
        "offset=-1",
        "channel=unknown",
        "state=unknown",
    ],
)
def test_api_validates_history_filters(client, query):
    assert client.get("/api/notifications?" + query, headers=AUTH).status_code in {400, 422}


def test_api_omitted_mode_uses_current_scope_without_mutating_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, "get_project_root", lambda: tmp_path)
    from api.models.notification import NotificationCreate

    with config_scope("local"):
        result = routes.create_notification(NotificationCreate(**PAYLOAD))
    assert result["data"]["mode"] == "local"
    assert result["data"]["deliveries"][0]["state"] == "unavailable"


def test_real_app_registers_notification_routes():
    from api.server import app

    schema = app.openapi()
    assert {"get", "post"} <= set(schema["paths"]["/api/notifications"])
