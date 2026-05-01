#!/usr/bin/env python3
"""Regression tests for memory follow-up context extraction."""

import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "jarvis-web"))

fake_socketio = types.ModuleType("flask_socketio")
fake_socketio.emit = lambda *args, **kwargs: None
fake_socketio.join_room = lambda *args, **kwargs: None
fake_socketio.leave_room = lambda *args, **kwargs: None
sys.modules.setdefault("flask_socketio", fake_socketio)

fake_flask = types.ModuleType("flask")
fake_flask.request = object()
sys.modules.setdefault("flask", fake_flask)

from server.sockets.chat import ChatHandler


def _handler():
    return ChatHandler.__new__(ChatHandler)


def test_extract_followup_data_preserves_search_memory_candidates():
    handler = _handler()
    data = {
        "search_memory": {
            "memories": [
                {
                    "id": 387,
                    "key": "user_birthday",
                    "value": "January 1st",
                    "category": "personal",
                    "importance": 9,
                    "relevance": 0.91,
                },
                {
                    "id": 2491,
                    "key": "birthday",
                    "value": "January 1st",
                    "category": "personal",
                    "importance": 8,
                    "relevance": 0.88,
                },
            ],
            "count": 2,
            "by_category": {"personal": 2},
        }
    }

    result = handler._extract_followup_data(data)
    memory = result["search_memory"]

    assert memory["memory_count"] == 2
    assert memory["count"] == 2
    assert memory["by_category"] == {"personal": 2}
    assert memory["id"] == 387
    assert memory["key"] == "user_birthday"
    assert len(memory["candidates"]) == 2
    assert memory["candidates"][1]["id"] == 2491
    assert memory["candidates"][1]["key"] == "birthday"


def test_extract_followup_data_preserves_semantic_recall_candidates():
    handler = _handler()
    data = {
        "semantic_recall": {
            "memories": [
                {
                    "id": 111,
                    "key": "wife_birthday",
                    "value": "March 15th",
                    "category": "personal",
                    "similarity": 0.97,
                },
                {
                    "id": 222,
                    "key": "birthday_notes",
                    "value": "Do not use placeholders",
                    "category": "fact",
                    "similarity": 0.62,
                },
            ],
            "count": 2,
        }
    }

    result = handler._extract_followup_data(data)
    memory = result["semantic_recall"]

    assert memory["memory_count"] == 2
    assert memory["id"] == 111
    assert memory["key"] == "wife_birthday"
    assert memory["candidates"][0]["similarity"] == 0.97
    assert memory["candidates"][1]["id"] == 222


def test_extract_followup_data_preserves_forget_mutation_refs():
    handler = _handler()
    data = {
        "forget": {
            "deleted_ids": [387, 2491],
            "deleted_keys": ["user_birthday", "birthday"],
            "deleted": [
                {"id": 387, "key": "user_birthday"},
                {"id": 2491, "key": "birthday"},
            ],
        }
    }

    result = handler._extract_followup_data(data)
    forget = result["forget"]

    assert forget["deleted_ids"] == [387, 2491]
    assert forget["deleted_keys"] == ["user_birthday", "birthday"]
    assert forget["deleted"][0] == {"id": 387, "key": "user_birthday"}
    assert forget["deleted"][1] == {"id": 2491, "key": "birthday"}


def test_extract_followup_data_preserves_update_memory_refs():
    handler = _handler()
    data = {
        "update_memory": {
            "memory_id": 387,
            "old_value": "January 1st",
            "new_value": "March 15th",
        }
    }

    result = handler._extract_followup_data(data)
    updated = result["update_memory"]

    assert updated["memory_id"] == 387
    assert updated["old_value"] == "January 1st"
    assert updated["new_value"] == "March 15th"
