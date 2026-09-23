"""Exercise the real Web library routes with only the write destination isolated."""

import io
import sys
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import fitz
import pytest
from flask import Flask
from server_package_utils import load_server_package

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
load_server_package("jarvis_library_test", ROOT / "jarvis-web/server")
from jarvis_library_test.routes.library import library_bp  # noqa: E402
from jarvis_library_test.services.pdf_upload import save_pdf_upload  # noqa: E402
from jarvis_library_test.services.text_upload import save_text_upload  # noqa: E402
from werkzeug.datastructures import FileStorage  # noqa: E402


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


def test_firefox_capture_saves_reviewed_dated_snapshot_and_new_page_version(client):
    first = "# Example\n\n- URL: https://example.test/article\n- Captured: 2026-09-23T10:00:00Z\n\n## Page\nOriginal facts.\n"
    data = {"markdown": first, "title": "Example", "url": "https://example.test/article",
            "captured_at": "2026-09-23T10:00:00Z"}
    saved = client.post("/api/library/capture?mode=local", json=data)
    assert saved.status_code == 200
    source = saved.json["source"]
    assert source["mode"] == "local"
    assert "2026-09-23T10:00:00Z" in source["origin"]
    assert client.get(f"/api/library/{source['source_id']}/download?mode=local").data == first.encode()
    assert client.post("/api/library/capture?mode=local", json=data).json["source"]["duplicate"] is True
    later = {**data, "captured_at": "2026-09-24T10:00:00Z",
             "markdown": first.replace("2026-09-23T10:00:00Z", "2026-09-24T10:00:00Z").replace("Original facts", "Updated facts")}
    next_source = client.post("/api/library/capture?mode=local", json=later).json["source"]
    assert next_source["source_id"] != source["source_id"]
    assert client.get(f"/api/library/{source['source_id']}/download?mode=local").data == first.encode()
    assert client.get("/api/library?mode=cloud").json["sources"] == []
    assert client.post("/api/library/capture?mode=local", json={**data, "markdown": ""}).status_code == 400
    assert client.post("/api/library/capture?mode=local", json={**data, "captured_at": "unknown"}).status_code == 400
    assert client.post("/api/library/capture?mode=local", json={**data, "url": "https://other.test"}).status_code == 400
    long_url = "https://example.test/article?" + "a" * 2100
    assert client.post("/api/library/capture?mode=local", json={**data,
        "url": long_url[:2000], "markdown": first.replace(data["url"], long_url)}).status_code == 200


def test_promote_validated_web_text_attachment_without_client_bytes(client, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_OVERRIDE_STASH_DIR", str(tmp_path / "stash"))
    original = b"# Exact web attachment\n\nChecked content.\n"
    attachment, _ = save_text_upload(
        FileStorage(stream=io.BytesIO(original), filename="notes.md", content_type="text/markdown"),
        str(uuid.uuid4()),
    )
    url = "/api/library/from-attachment?mode=local"
    result = client.post(url, json={"attachment": {"kind": "text", "stash_ref": attachment["stash_ref"]}})
    assert result.status_code == 200, result.json
    source = result.json["source"]
    assert client.get(f"/api/library/{source['source_id']}/download?mode=local").data == original
    assert client.post(url, json={"attachment": {**attachment, "mode": "cloud"}}).status_code == 400
    assert client.post(url, json={"attachment": {"kind": "text", "stash_ref": "stash://bad"}}).status_code == 400


def test_promote_validated_pdf_attachment_keeps_exact_pdf(client, tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_OVERRIDE_STASH_DIR", str(tmp_path / "stash"))
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "A sourced PDF passage")
        original = pdf.tobytes()
    attachment, _ = save_pdf_upload(
        FileStorage(stream=io.BytesIO(original), filename="report.pdf", content_type="application/pdf"),
        str(uuid.uuid4()),
    )
    result = client.post("/api/library/from-attachment?mode=cloud", json={"attachment": attachment})
    assert result.status_code == 200, result.json
    source = result.json["source"]
    assert source["mode"] == "cloud"
    assert client.get(f"/api/library/{source['source_id']}/download?mode=cloud").data == original
    assert client.get("/api/library?mode=local").json["sources"] == []


def test_rename_route_updates_title_without_changing_source_id(client):
    saved = client.post(
        "/api/library?mode=local",
        data={"file": (io.BytesIO(b"A note about winter"), "note.txt")},
    ).json["source"]
    sid = saved["source_id"]
    response = client.patch(f"/api/library/{sid}?mode=local", json={"title": "Winter notes"})
    assert response.status_code == 200
    assert response.json["source"]["source_id"] == sid
    assert response.json["source"]["title"] == "Winter notes"
    assert client.get(f"/api/library/{sid}/download?mode=local").data == b"A note about winter"
    assert client.patch(f"/api/library/{sid}?mode=local", json={"title": " "}).status_code == 400


def test_queue_route_is_durable_and_does_not_run_embeddings(client, monkeypatch):
    import source_library

    def unexpected(*_args, **_kwargs):
        raise AssertionError("The queue endpoint must not embed in the request.")

    monkeypatch.setattr(source_library, "get_embeddings_batch", unexpected)
    sid = client.post(
        "/api/library?mode=local", data={"file": (io.BytesIO(b"A queued note"), "note.txt")}
    ).json["source"]["source_id"]
    queued = client.post(f"/api/library/{sid}/queue?mode=local")
    assert queued.status_code == 200 and queued.json["queued"] is True
    assert queued.json["source"]["index_job_status"] == "pending"


def test_inbox_routes_preview_then_queue(client, tmp_path):
    inbox = tmp_path / "library" / "inbox" / "local"
    inbox.mkdir(parents=True)
    (inbox / "note.txt").write_text("Local archive fact")
    preview = client.get("/api/library/inbox?mode=local")
    assert preview.status_code == 200 and preview.json["eligible_count"] == 1
    queued = client.post("/api/library/inbox/queue?mode=local")
    assert queued.status_code == 200 and queued.json["queued"] == 1
    assert client.get("/api/library/inbox?mode=cloud").json["eligible_count"] == 0


def test_visible_source_status_route(client):
    sid = client.post(
        "/api/library?mode=local", data={"file": (io.BytesIO(b"Visible source"), "note.txt")}
    ).json["source"]["source_id"]
    response = client.get(f"/api/library/status?mode=local&ids={sid}")
    assert response.status_code == 200
    assert response.json["sources"][0]["index_job_status"] == "pending"
    assert client.get("/api/library/status?mode=local&ids=bad").status_code == 400


@pytest.mark.skipif(sys.platform == "win32", reason="External worker uses POSIX advisory locks")
def test_worker_status_route_reports_live_external_lease_without_creating_db(client, monkeypatch, tmp_path):
    from source_library import SourceLibrary

    monkeypatch.setenv("JARVIS_LIBRARY_WORKER_EXTERNAL", "1")
    empty = client.get("/api/library/worker?mode=local")
    assert empty.status_code == 200 and empty.json["running"] is False
    assert empty.json["worker_mode"] == "external"
    assert empty.headers["Cache-Control"] == "no-store"
    library = SourceLibrary("local")
    with library.worker_lease():
        live = client.get("/api/library/worker?mode=local")
        assert live.status_code == 200 and live.json["running"] is True
    assert client.get("/api/library/worker?mode=local").json["running"] is False
    assert not (tmp_path / "library" / "local.db").exists()


def test_raw_and_rendered_text_routes_are_mode_scoped_and_no_store(client):
    sid = client.post(
        "/api/library?mode=local",
        data={"file": (io.BytesIO(b"# Notes\n\n<img src=https://bad.test/x>"), "notes.md")},
    ).json["source"]["source_id"]
    raw = client.get(f"/api/library/{sid}/text?mode=local")
    assert raw.json["text"].startswith("# Notes") and raw.headers["Cache-Control"] == "no-store"
    rendered = client.get(f"/api/library/{sid}/rendered?mode=local")
    assert "<h1>Notes</h1>" in rendered.json["html"]
    assert "<img" not in rendered.json["html"]
    assert client.get(f"/api/library/{sid}/text?mode=cloud").status_code == 400
    copy = client.post(f"/api/library/{sid}/copy?mode=local", json={"text": "# Revised notes"})
    assert copy.status_code == 200
    assert copy.json["source"]["source_id"] != sid
    assert client.get(f"/api/library/{sid}/download?mode=local").data.startswith(b"# Notes")
    assert client.post(f"/api/library/{sid}/copy?mode=local", json={"text": 42}).status_code == 400
    oversized = client.post(
        f"/api/library/{sid}/copy?mode=local", data=b"{}",
        environ_overrides={"CONTENT_LENGTH": str(25 * 1024 * 1024 + 4097)},
    )
    assert oversized.status_code == 413


def test_pdf_page_route_renders_only_authenticated_original(client):
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "A cited page")
        original = pdf.tobytes()
    sid = client.post(
        "/api/library?mode=local",
        data={"file": (io.BytesIO(original), "book.pdf")},
    ).json["source"]["source_id"]
    page = client.get(f"/api/library/{sid}/page/1?mode=local")
    assert page.status_code == 200 and page.data.startswith(b"\x89PNG\r\n\x1a\n")
    assert page.headers["Cache-Control"] == "no-store"
    assert client.get(f"/api/library/{sid}/page/2?mode=local").status_code == 400
    assert client.get(f"/api/library/{sid}/page/1?mode=cloud").status_code == 400


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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX no-follow directory handles")
def test_unsafe_store_returns_library_only_503(client, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "library").symlink_to(outside, target_is_directory=True)
    response = client.get("/api/library?mode=local")
    assert response.status_code == 503
    assert response.json["ok"] is False
    assert not (outside / "local.db").exists()


def test_routes_require_auth_when_enabled(client, monkeypatch):
    import webui_auth

    monkeypatch.setattr(webui_auth, "is_auth_enabled", lambda: True)
    for method, path in [
        ("get", ""),
        ("post", ""),
        ("post", "/capture"),
        ("post", "/from-attachment"),
        ("get", "/a"),
        ("delete", "/a"),
        ("patch", "/a"),
        ("post", "/a/index"),
        ("post", "/a/queue"),
        ("get", "/inbox"),
        ("get", "/status"),
        ("post", "/inbox/queue"),
        ("get", "/a/download"),
        ("get", "/a/text"),
        ("post", "/a/copy"),
        ("get", "/a/rendered"),
        ("get", "/a/page/1"),
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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX no-follow index lock")
def test_unsafe_manual_index_lock_returns_503_without_truncating_target(client, tmp_path):
    sid = client.post(
        "/api/library?mode=local", data={"file": (io.BytesIO(b"A queued note"), "note.txt")}
    ).json["source"]["source_id"]
    victim = tmp_path / "private.txt"
    victim.write_text("KEEP-ME")
    (tmp_path / "library" / "local.db.index.lock").symlink_to(victim)
    response = client.post(f"/api/library/{sid}/index?mode=local")
    assert response.status_code == 503 and response.json["ok"] is False
    assert victim.read_text() == "KEEP-ME"


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


def test_web_stays_available_when_library_modules_cannot_import(tmp_path, monkeypatch):
    import importlib

    alias = "jarvis_library_degraded_test"
    load_server_package(alias, ROOT / "jarvis-web/server")
    config = importlib.import_module(f"{alias}.config")
    conversations = importlib.import_module(f"{alias}.services.conversation_store")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "web_config.json")
    monkeypatch.setattr(conversations, "CONVERSATIONS_DIR", tmp_path / "conversations")
    monkeypatch.setitem(sys.modules, f"{alias}.routes.library", None)
    monkeypatch.setitem(sys.modules, "source_library_jobs", None)

    app_module = importlib.import_module(f"{alias}.app")
    monkeypatch.setattr(app_module, "is_auth_enabled", lambda: True)
    assert app_module.app.test_client().get("/api/library").status_code == 401
    monkeypatch.setattr(app_module, "is_auth_enabled", lambda: False)
    web = app_module.app.test_client()
    assert web.get("/").status_code == 200
    unavailable = web.get("/api/library")
    assert unavailable.status_code == 503 and unavailable.json["ok"] is False
    assert app_module.app.extensions["jarvis_library_index_worker"] is None


def test_web_listener_starts_when_library_worker_start_fails(tmp_path):
    import ast
    from types import SimpleNamespace

    app_path = ROOT / "jarvis-web/server/app.py"
    module = ast.parse(app_path.read_text())
    boot = ast.Module(body=[node for node in module.body if isinstance(node, ast.FunctionDef)
                            and node.name == "run_server"], type_ignores=[])
    events = []

    class FailingWorker:
        def start(self):
            raise RuntimeError("isolated library worker failure")

    scope = {
        "app": SimpleNamespace(extensions={"jarvis_library_index_worker": FailingWorker()}),
        "chat_handler": SimpleNamespace(background_tasks=SimpleNamespace(start=lambda: None)),
        "load_web_config": lambda: None, "load_jarvis_config": lambda mode: None,
        "get_web_setting": lambda key, default: default, "is_auth_enabled": lambda: False,
        "JARVIS_ROOT": tmp_path,
        "logger": SimpleNamespace(exception=lambda message: events.append(message)),
        "socketio": SimpleNamespace(run=lambda *args, **kwargs: events.append("listener started")),
    }
    exec(compile(boot, str(app_path), "exec"), scope)
    scope["run_server"]()
    assert events == [
        "Source Library worker failed to start; Web will continue without indexing",
        "listener started",
    ]


def test_external_library_worker_does_not_start_in_web(tmp_path, monkeypatch):
    import ast
    from types import SimpleNamespace

    monkeypatch.setenv("JARVIS_LIBRARY_WORKER_EXTERNAL", "1")
    app_path = ROOT / "jarvis-web/server/app.py"
    module = ast.parse(app_path.read_text())
    boot = ast.Module(body=[node for node in module.body if isinstance(node, ast.FunctionDef)
                            and node.name == "run_server"], type_ignores=[])
    events = []
    scope = {
        "app": SimpleNamespace(extensions={"jarvis_library_index_worker":
                                           SimpleNamespace(start=lambda: events.append("worker started"))}),
        "chat_handler": SimpleNamespace(background_tasks=SimpleNamespace(start=lambda: None)),
        "load_web_config": lambda: None, "load_jarvis_config": lambda mode: None,
        "get_web_setting": lambda key, default: default, "is_auth_enabled": lambda: False,
        "JARVIS_ROOT": tmp_path,
        "socketio": SimpleNamespace(run=lambda *args, **kwargs: events.append("listener started")),
    }
    exec(compile(boot, str(app_path), "exec"), scope)
    scope["run_server"]()
    assert events == ["listener started"]


def test_compose_runs_library_worker_outside_web():
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    worker = services["jarvis-library-worker"]
    web = services["jarvis-web"]
    assert worker["command"] == ["library-worker"]
    assert worker["healthcheck"]["test"] == ["CMD", "python", "/app/bin/jarvis-library-worker", "status"]
    assert worker["restart"] == "unless-stopped"
    assert worker["user"] == web["user"]
    assert "./data:/app/data" in worker["volumes"]
    assert not worker.get("profiles") and not worker.get("ports")
    assert "jarvis-library-worker" not in web.get("depends_on", {})
    assert web["environment"]["JARVIS_LIBRARY_WORKER_EXTERNAL"] == "1"
    entrypoint = (ROOT / "docker/entrypoint.sh").read_text().split("  library-worker)")[1].split(";;")[0]
    assert "exec ./bin/jarvis-library-worker" in entrypoint
    assert "run_init" not in entrypoint
