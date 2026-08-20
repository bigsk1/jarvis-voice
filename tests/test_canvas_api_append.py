#!/usr/bin/env python3
"""FastAPI regression coverage for Canvas append and shrink protection."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.models.canvas import CanvasAppend, CanvasCreate, CanvasUpdate
from api.routes import canvas as canvas_routes


def _write_page(root: Path, content: str = "x" * 6902) -> Path:
    path = root / "page_test.json"
    path.write_text(
        json.dumps({
            "id": "page_test",
            "title": "Research",
            "content": content,
            "created": "2026-07-04T00:00:00Z",
            "updated": "2026-07-04T00:00:00Z",
            "tags": [],
            "pinned": False,
        }),
        encoding="utf-8",
    )
    return path


def test_fastapi_exposes_separate_canvas_append_route():
    route = next(
        route
        for route in canvas_routes.router.routes
        if route.path == "/api/canvas/{page_id}/append"
    )
    assert "POST" in route.methods


def test_fastapi_canvas_append_preserves_existing_page(tmp_path, monkeypatch):
    monkeypatch.setattr(canvas_routes, "CANVAS_DIR", str(tmp_path))
    _write_page(tmp_path, "# Existing")

    result = asyncio.run(
        canvas_routes.append_page("page_test", CanvasAppend(content="## Videos"))
    )

    assert result.page.content == "# Existing\n\n## Videos"


def test_fastapi_canvas_update_blocks_suspicious_shrink(tmp_path, monkeypatch):
    monkeypatch.setattr(canvas_routes, "CANVAS_DIR", str(tmp_path))
    _write_page(tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            canvas_routes.update_page("page_test", CanvasUpdate(content="short"))
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error_code"] == "suspicious_content_shrink"


def test_fastapi_canvas_create_allows_compare_range_url(tmp_path, monkeypatch):
    monkeypatch.setattr(canvas_routes, "CANVAS_DIR", str(tmp_path))

    result = asyncio.run(
        canvas_routes.create_page(CanvasCreate(
            title="Release Notes",
            content=(
                "[Compare](https://github.com/yt-dlp/yt-dlp/compare/"
                "2026.07.04...2026.08.19)"
            ),
        ))
    )

    assert result.ok is True
    assert result.page is not None
    assert result.page.title == "Release Notes"


def test_fastapi_canvas_create_rejects_truncated_url(tmp_path, monkeypatch):
    monkeypatch.setattr(canvas_routes, "CANVAS_DIR", str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            canvas_routes.create_page(CanvasCreate(
                title="Incomplete",
                content="Source: https://example.com/...",
            ))
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["error_code"] == "truncated_content_url"
    assert list(tmp_path.iterdir()) == []
