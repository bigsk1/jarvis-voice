#!/usr/bin/env python3
"""Regression coverage for the jarvis-api memory categories response."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from api.routes import memory as memory_routes


class _CategoryCursor:
    def execute(self, _query: str):
        return self

    def fetchall(self):
        return [
            {"category": "project", "count": 3},
            {"category": "personal", "count": 2},
        ]


def test_list_categories_returns_names_and_counts():
    db = SimpleNamespace(
        conn=SimpleNamespace(cursor=lambda: _CategoryCursor()),
    )

    with patch.object(memory_routes, "get_db", return_value=db):
        response = asyncio.run(memory_routes.list_categories())

    assert response.model_dump() == {
        "ok": True,
        "message": "Found 2 categories",
        "categories": {"project": 3, "personal": 2},
        "count": 5,
    }
