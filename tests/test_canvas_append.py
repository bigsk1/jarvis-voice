#!/usr/bin/env python3
"""Regression tests for safe Canvas append and replacement behavior."""

import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import skills.canvas as canvas_module  # noqa: E402
from lib.canvas_content import append_content, is_suspicious_content_shrink  # noqa: E402


def test_append_page_sends_only_new_content(monkeypatch):
    calls = []

    monkeypatch.setattr(canvas_module, "check_canvas_health", lambda: True)
    monkeypatch.setattr(canvas_module, "save_to_memory", lambda page: None)

    def fake_api(method, endpoint, data=None):
        calls.append((method, endpoint, data))
        return {
            "id": "page_existing",
            "title": "Research",
            "content": "# Existing\n\n## New section",
        }

    monkeypatch.setattr(canvas_module, "api_request", fake_api)

    result = canvas_module.append_page("page_existing", "## New section")

    assert result["ok"] is True
    assert calls == [
        ("POST", "/pages/page_existing/append", {"content": "## New section"})
    ]


def test_update_only_sends_shrink_override_when_explicit(monkeypatch):
    calls = []

    monkeypatch.setattr(canvas_module, "check_canvas_health", lambda: True)
    monkeypatch.setattr(canvas_module, "save_to_memory", lambda page: None)

    def fake_api(method, endpoint, data=None):
        calls.append(data)
        return {"id": "page_existing", "title": "Research", "content": data["content"]}

    monkeypatch.setattr(canvas_module, "api_request", fake_api)

    canvas_module.update_page("page_existing", content="# Replacement")
    canvas_module.update_page(
        "page_existing",
        content="# Intentional short replacement",
        allow_content_shrink=True,
    )

    assert "allow_content_shrink" not in calls[0]
    assert calls[1]["allow_content_shrink"] is True


def test_main_allows_pin_only_updates(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(canvas_module, "load_config", lambda: None)

    def fake_update_page(page_id, **kwargs):
        calls.append((page_id, kwargs))
        return {
            "ok": True,
            "data": {"page_id": page_id, "pinned": kwargs["pinned"]},
        }

    monkeypatch.setattr(canvas_module, "update_page", fake_update_page)

    for pinned in (True, False):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "canvas.py",
                json.dumps({
                    "action": "update",
                    "page_id": "page_existing",
                    "pinned": pinned,
                }),
            ],
        )

        canvas_module.main()
        output = json.loads(capsys.readouterr().out)

        assert output["ok"] is True
        assert output["data"]["pinned"] is pinned

    assert [call[1]["pinned"] for call in calls] == [True, False]


def test_main_allows_empty_tags_to_clear_page_tags(monkeypatch, capsys):
    calls = []

    monkeypatch.setattr(canvas_module, "load_config", lambda: None)

    def fake_update_page(page_id, **kwargs):
        calls.append((page_id, kwargs))
        return {
            "ok": True,
            "data": {"page_id": page_id, "tags": kwargs["tags"]},
        }

    monkeypatch.setattr(canvas_module, "update_page", fake_update_page)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "canvas.py",
            json.dumps({
                "action": "update",
                "page_id": "page_existing",
                "tags": [],
            }),
        ],
    )

    canvas_module.main()
    output = json.loads(capsys.readouterr().out)

    assert output["ok"] is True
    assert output["data"]["tags"] == []
    assert calls[0][0] == "page_existing"
    assert calls[0][1]["tags"] == []


def test_server_append_preserves_existing_content():
    assert append_content("# Existing\n", "\n## Added\n") == "# Existing\n\n## Added"


def test_server_shrink_guard_blocks_large_accidental_replacement():
    assert is_suspicious_content_shrink("x" * 6902, "y" * 794) is True
    assert is_suspicious_content_shrink("x" * 1000, "y" * 800) is False
    assert is_suspicious_content_shrink("x" * 6902, "y" * 7000) is False
    assert is_suspicious_content_shrink("short page", "shorter") is False
