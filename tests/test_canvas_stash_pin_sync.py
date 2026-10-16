"""Regression coverage for stash retention on pinned Canvas mutations."""

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import Mock

from flask import Flask

from lib.canvas_content import canvas_url_validation_error

ROOT = Path(__file__).resolve().parents[1]
PAGES_ROUTE = ROOT / "jarvis-canvas" / "server" / "routes" / "pages.py"


def _load_pages_route(tmp_path, monkeypatch):
    alias = "canvas_stash_pin_test_server"
    sync_pins = Mock()
    saved_pages = {}

    config = types.ModuleType(f"{alias}.config")
    config.CANVAS_DIR = tmp_path
    config.STASH_DIR = tmp_path / "stash"

    server_package = types.ModuleType(alias)
    server_package.__path__ = []
    routes_package = types.ModuleType(f"{alias}.routes")
    routes_package.__path__ = []
    server_pages = types.ModuleType(f"{alias}.pages")
    server_pages.get_page_path = lambda page_id: tmp_path / f"{page_id}.json"
    server_pages.load_pages = lambda: []
    server_pages.delete_page_file = lambda _page_id: False

    def save_page(page):
        saved_pages[page["id"]] = dict(page)
        (tmp_path / f"{page['id']}.json").write_text(json.dumps(page), encoding="utf-8")

    server_pages.save_page = save_page
    server_utils = types.ModuleType(f"{alias}.utils")
    server_utils.sync_stash_pins = sync_pins

    for name, module in {
        alias: server_package,
        f"{alias}.config": config,
        f"{alias}.routes": routes_package,
        f"{alias}.pages": server_pages,
        f"{alias}.utils": server_utils,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    route_name = f"{alias}.routes.pages"
    spec = importlib.util.spec_from_file_location(route_name, PAGES_ROUTE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, route_name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "append_content", lambda old, new: f"{old}\n\n{new}")
    monkeypatch.setattr(module, "canvas_url_validation_error", canvas_url_validation_error)
    monkeypatch.setattr(module, "is_suspicious_content_shrink", lambda _old, _new: False)
    monkeypatch.setattr(module, "generate_canvas_page_id", lambda _now: "page_new")
    monkeypatch.setattr(module, "get_stash_dir", lambda: tmp_path / "stash")

    app = Flask(__name__)
    app.register_blueprint(module.pages_bp)
    return app, sync_pins


def test_updating_already_pinned_page_syncs_new_stash_references(tmp_path, monkeypatch):
    app, sync_pins = _load_pages_route(tmp_path, monkeypatch)
    page = {
        "id": "page_existing",
        "title": "Pinned",
        "content": "old content",
        "pinned": True,
    }
    (tmp_path / "page_existing.json").write_text(json.dumps(page), encoding="utf-8")

    response = app.test_client().put(
        "/api/pages/page_existing",
        json={"content": "![new](stash://space_new/image.png)"},
    )

    assert response.status_code == 200
    sync_pins.assert_called_once_with(
        "![new](stash://space_new/image.png)",
        pinned=True,
        stash_dir=tmp_path / "stash",
    )


def test_upload_syncs_stash_references_for_new_and_existing_pinned_pages(tmp_path, monkeypatch):
    app, sync_pins = _load_pages_route(tmp_path, monkeypatch)
    client = app.test_client()

    created = client.post(
        "/api/pages/upload",
        json={
            "title": "Imported",
            "content": "stash://space_created/file.png",
            "pinned": True,
        },
    )
    assert created.status_code == 201

    updated = client.post(
        "/api/pages/upload",
        json={
            "id": "page_new",
            "title": "Imported again",
            "content": "stash://space_updated/file.png",
            "pinned": True,
        },
    )
    assert updated.status_code == 200

    assert [call.args[0] for call in sync_pins.call_args_list] == [
        "stash://space_created/file.png",
        "stash://space_updated/file.png",
    ]


def test_canvas_server_create_uses_shared_url_policy(tmp_path, monkeypatch):
    app, _sync_pins = _load_pages_route(tmp_path, monkeypatch)
    client = app.test_client()

    accepted = client.post(
        "/api/pages",
        json={
            "title": "Release Notes",
            "content": (
                "[Compare](https://github.com/yt-dlp/yt-dlp/compare/"
                "2026.07.04...2026.08.19)"
            ),
        },
    )
    rejected = client.post(
        "/api/pages",
        json={
            "title": "Incomplete",
            "content": "Source: https://example.com/...",
        },
    )

    assert accepted.status_code == 201
    assert rejected.status_code == 400
    assert rejected.get_json()["error_code"] == "truncated_content_url"
