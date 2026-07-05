#!/usr/bin/env python3
"""FastAPI regression coverage for Canvas append and shrink protection."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.models.canvas import CanvasAppend, CanvasUpdate
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
