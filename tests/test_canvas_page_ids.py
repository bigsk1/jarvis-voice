"""Regression coverage for collision-resistant Canvas page creation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from api.models.canvas import CanvasCreate
from api.routes import canvas as canvas_routes
from lib import canvas_page_ids


def test_page_ids_remain_readable_and_unique_within_same_second(monkeypatch):
    values = iter([
        "111111111111aaaaaaaaaaaaaaaaaaaa",
        "222222222222bbbbbbbbbbbbbbbbbbbb",
    ])
    monkeypatch.setattr(
        canvas_page_ids,
        "uuid4",
        lambda: type("UUID", (), {"hex": next(values)})(),
    )
    now = datetime(2026, 7, 5, 12, 30, 45, tzinfo=timezone.utc)

    first = canvas_page_ids.generate_canvas_page_id(now)
    second = canvas_page_ids.generate_canvas_page_id(now)

    assert first == "page_20260705_123045_111111111111"
    assert second == "page_20260705_123045_222222222222"
    assert first != second


def test_fastapi_same_second_creates_preserve_both_pages(tmp_path, monkeypatch):
    class FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 5, 12, 30, 45, tzinfo=timezone.utc)

    monkeypatch.setattr(canvas_routes, "CANVAS_DIR", str(tmp_path))
    monkeypatch.setattr(canvas_routes, "datetime", FixedDateTime)

    first = asyncio.run(
        canvas_routes.create_page(CanvasCreate(title="First", content="first page"))
    )
    second = asyncio.run(
        canvas_routes.create_page(CanvasCreate(title="Second", content="second page"))
    )

    assert first.page.page_id != second.page.page_id
    assert (tmp_path / f"{first.page.page_id}.json").is_file()
    assert (tmp_path / f"{second.page.page_id}.json").is_file()
    assert len(list(tmp_path.glob("page_*.json"))) == 2


def test_canvas_server_create_and_force_new_import_use_shared_generator():
    source = (
        Path(__file__).resolve().parents[1]
        / "jarvis-canvas/server/routes/pages.py"
    ).read_text(encoding="utf-8")

    assert "from canvas_page_ids import generate_canvas_page_id" in source
    assert source.count("generate_canvas_page_id(now_utc)") == 2
    assert "page_id = f\"page_{now_utc.strftime('%Y%m%d_%H%M%S')}\"" not in source
