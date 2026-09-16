"""Exercise the real Web library routes with only the write destination isolated."""

import io
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from flask import Flask
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
load_server_package("jarvis_library_test", ROOT / "jarvis-web/server")
from jarvis_library_test.routes.library import library_bp  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    import webui_auth

    monkeypatch.setattr(webui_auth, "is_auth_enabled", lambda: False)
    monkeypatch.setenv("JARVIS_OVERRIDE_SOURCE_LIBRARY_DIR", str(tmp_path / "library"))
    app = Flask(__name__)
    app.register_blueprint(library_bp)
    return app.test_client()


def test_upload_search_read_download_delete_and_mode_isolation(client):
    source = ("Unrelated context.\n" * 200 + "Escape route: juniper trail.").encode()
    response = client.post(
        "/api/library?mode=local", data={"file": (io.BytesIO(source), "plan.txt")}
    )
    assert response.status_code == 200
    sid = response.json["source"]["source_id"]
    assert client.get("/api/library?mode=cloud").json["sources"] == []
    found = client.get("/api/library?mode=local&q=juniper&semantic=false").json
    passage = found["passages"][0]
    assert "juniper" in passage["text"] and passage["char_start"] > 2000
    read = client.get(f"/api/library/{sid}?mode=local&passage={passage['number']}").json
    assert read["passages"][0]["text"] == passage["text"]
    download = client.get(f"/api/library/{sid}/download?mode=local")
    assert download.data == source
    assert download.headers["Cache-Control"] == "no-store"
    assert "attachment" in download.headers["Content-Disposition"]
    assert client.delete(f"/api/library/{sid}?mode=local").json["removed"]
    assert client.get(f"/api/library/{sid}?mode=local").status_code == 400


def test_empty_browse_is_non_mutating_and_bad_requests_are_clear(client, tmp_path):
    assert client.get("/api/library?mode=local").json["total"] == 0
    assert not (tmp_path / "library").exists()
    for url in (
        "/api/library?mode=other",
        "/api/library?limit=x",
        "/api/library?offset=-1",
        "/api/library/not-an-id",
    ):
        response = client.get(url)
        assert response.status_code == 400 and response.json["error"]
    assert client.post("/api/library?mode=local").status_code == 400


def test_routes_require_auth_when_enabled(client, monkeypatch):
    import webui_auth

    monkeypatch.setattr(webui_auth, "is_auth_enabled", lambda: True)
    for method, path in [
        ("get", ""),
        ("post", ""),
        ("get", "/a"),
        ("delete", "/a"),
        ("post", "/a/index"),
        ("get", "/a/download"),
    ]:
        response = getattr(client, method)("/api/library" + path)
        assert response.status_code == 401


def test_index_failure_is_distinct_from_save_success(client, monkeypatch):
    import source_library

    def fail(*args, **kwargs):
        raise source_library.EmbeddingError("offline")

    monkeypatch.setattr(source_library, "get_embeddings_batch", fail)
    sid = client.post(
        "/api/library?mode=local", data={"file": (io.BytesIO(b"stored"), "note.txt")}
    ).json["source"]["source_id"]
    response = client.post(f"/api/library/{sid}/index?mode=local")
    assert response.status_code == 200
    assert (
        response.json["index_error"] and response.json["source"]["index_status"] == "keyword_only"
    )
    assert client.get(f"/api/library/{sid}/download?mode=local").data == b"stored"


@pytest.mark.parametrize("page", ["/library", "/library.html"])
def test_actual_app_preserves_source_citation_through_login(tmp_path, monkeypatch, page):
    import importlib

    alias = "jarvis_library_auth_test"
    load_server_package(alias, ROOT / "jarvis-web/server")
    config = importlib.import_module(f"{alias}.config")
    conversations = importlib.import_module(f"{alias}.services.conversation_store")
    target = tmp_path / "web_config.json"
    if config.CONFIG_PATH.exists():
        target.write_bytes(config.CONFIG_PATH.read_bytes())
    monkeypatch.setattr(config, "CONFIG_PATH", target)
    monkeypatch.setattr(conversations, "CONVERSATIONS_DIR", tmp_path / "conversations")
    app_module = importlib.import_module(f"{alias}.app")
    monkeypatch.setattr(app_module, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(app_module, "verify_token", lambda token: False)
    destination = f"{page}?mode=local&source={'a' * 64}&passage=7"
    response = app_module.app.test_client().get(destination)
    assert response.status_code == 302
    location = urlsplit(response.headers["Location"])
    assert location.path == "/login"
    assert parse_qs(location.query)["redirect"] == [destination]
