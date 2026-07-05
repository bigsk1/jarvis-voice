"""Stable, collision-resistant identifiers for Canvas pages."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


def generate_canvas_page_id(now: datetime | None = None) -> str:
    """Return a readable page ID with enough entropy for concurrent creates."""
    timestamp = now or datetime.now(timezone.utc)
    return f"page_{timestamp.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:12]}"
