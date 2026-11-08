"""Imports create independent Canvas pages through the real storage path."""

import importlib
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from flask import Flask

from tests.server_package_utils import load_canvas_server_package

ALIAS = "canvas_import_test_server"
load_canvas_server_package(ALIAS)
pages = importlib.import_module(f"{ALIAS}.pages")
routes = importlib.import_module(f"{ALIAS}.routes.pages")
NOW = datetime(2026, 11, 8, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def imports(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(pages, "CANVAS_DIR", tmp_path)
    monkeypatch.setattr(routes, "datetime", Clock)
    sync_pins = Mock()
    monkeypatch.setattr(routes, "sync_stash_pins", sync_pins)
    monkeypatch.setattr(routes, "get_stash_dir", lambda: tmp_path / "stash")
    app = Flask(__name__)
    app.register_blueprint(routes.pages_bp)
    return app.test_client(), tmp_path, sync_pins


@pytest.mark.parametrize("legacy_flag", [None, False, True])
def test_imported_existing_id_always_creates_a_new_page(imports, legacy_flag):
    client, directory, sync_pins = imports
    original = {
        "id": "page_existing",
        "title": "Keep this page",
        "content": "Original content. " * 600,
        "tags": ["original"],
        "pinned": True,
        "created": "2020-01-01T00:00:00Z",
        "updated": "2020-01-01T00:00:00Z",
    }
    pages.save_page(original)
    original_bytes = (directory / "page_existing.json").read_bytes()
    incoming = {
        "id": original["id"],
        "title": "Imported page",
        "content": "Short imported content",
        "tags": ["imported"],
        "source_query": "original research query",
        "created": "2010-01-01T00:00:00Z",
        "updated": "2010-01-01T00:00:00Z",
    }
    if legacy_flag is not None:
        incoming["force_new"] = legacy_flag

    response = client.post("/api/pages/upload", json=incoming)

    assert response.status_code == 201
    result = response.get_json()
    assert result["action"] == "created"
    saved = result["page"]
    assert saved["id"] != original["id"]
    assert saved["title"] == incoming["title"]
    assert saved["content"] == incoming["content"]
    assert saved["tags"] == incoming["tags"]
    assert saved["source_query"] == incoming["source_query"]
    assert saved["created"] == saved["updated"] == "2026-11-08T15:00:00Z"
    assert saved["pinned"] is False
    assert (directory / "page_existing.json").read_bytes() == original_bytes
    assert json.loads((directory / f"{saved['id']}.json").read_text()) == saved
    assert len(list(directory.glob("*.json"))) == 2
    sync_pins.assert_not_called()


def test_repeated_imports_get_independent_ids_and_pin_their_content(imports):
    client, directory, sync_pins = imports
    incoming = {
        "id": "../../ignored",
        "title": "Pinned import",
        "content": "![chart](stash://report/chart.png)",
        "pinned": True,
    }

    first = client.post("/api/pages/upload", json=incoming)
    second = client.post("/api/pages/upload", json=incoming)

    assert first.status_code == second.status_code == 201
    first_page = first.get_json()["page"]
    second_page = second.get_json()["page"]
    assert first_page["id"] != second_page["id"]
    assert first_page["pinned"] is second_page["pinned"] is True
    assert len(list(directory.glob("*.json"))) == 2
    assert sync_pins.call_count == 2
    for call in sync_pins.call_args_list:
        assert call.args == (incoming["content"],)
        assert call.kwargs == {"pinned": True, "stash_dir": directory / "stash"}


@pytest.mark.parametrize(
    "content",
    [
        "Source: https://example.com/...",
        "[Article](https://example.com/rese.../details)",
        "Example: `https://example.com/...`",
    ],
)
def test_import_uses_new_page_url_check_before_saving_or_pinning(imports, content):
    client, directory, sync_pins = imports

    response = client.post(
        "/api/pages/upload",
        json={"title": "Incomplete", "content": content, "pinned": True},
    )

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "truncated_content_url"
    assert list(directory.iterdir()) == []
    sync_pins.assert_not_called()


def test_import_allows_complete_urls_with_compare_ranges(imports):
    client, directory, _sync_pins = imports
    content = "[Compare](https://github.com/example/repo/compare/v1...v2)"

    response = client.post(
        "/api/pages/upload", json={"title": "Comparison", "content": content},
    )

    assert response.status_code == 201
    assert response.get_json()["page"]["content"] == content
    assert len(list(directory.glob("*.json"))) == 1
