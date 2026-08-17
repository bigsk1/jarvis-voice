#!/usr/bin/env python3
"""Preference slot, scope, and expiry regression tests."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from memory_db import MemoryDB  # noqa: E402

from skills import remember as remember_tool  # noqa: E402


def test_persistent_aliases_upsert_one_canonical_slot(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        first_id = db.remember(
            "preference",
            "preferred_name",
            "Call me Joe",
            generate_embedding=False,
        )
        second_id = db.remember(
            "preference",
            "address_me_as",
            "Call me Wayne",
            generate_embedding=False,
        )

        rows = db.conn.execute(
            "SELECT id, category, key, value, metadata FROM knowledge_base"
        ).fetchall()
        metadata = json.loads(rows[0]["metadata"])
        assert first_id == second_id
        assert len(rows) == 1
        assert rows[0]["category"] == "preference"
        assert rows[0]["key"] == "how_to_address_user"
        assert rows[0]["value"] == "Call me Wayne"
        assert metadata["preference_slot"] == "how_to_address_user"
        assert metadata["preference_scope"] == "persistent"
    finally:
        db.close()


def test_session_preference_only_overrides_its_own_session(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        persistent_id = db.remember(
            "preference",
            "response_style",
            "Use concise prose",
            generate_embedding=False,
        )
        session_one_id = db.remember(
            "preference",
            "response_style",
            "Talk like a pirate",
            generate_embedding=False,
            metadata={
                "preference_slot": "response_style",
                "preference_scope": "session",
                "preference_session_id": "conversation-one",
            },
        )
        session_one_updated_id = db.remember(
            "preference",
            "response_style",
            "Use Australian phrasing",
            generate_embedding=False,
            metadata={
                "preference_slot": "response_style",
                "preference_scope": "session",
                "preference_session_id": "conversation-one",
            },
        )
        session_two_id = db.remember(
            "preference",
            "response_style",
            "Use formal prose",
            generate_embedding=False,
            metadata={
                "preference_slot": "response_style",
                "preference_scope": "session",
                "preference_session_id": "conversation-two",
            },
        )

        first = db.get_addressing_preferences(limit=4, session_id="conversation-one")
        second = db.get_addressing_preferences(limit=4, session_id="conversation-two")
        no_session = db.get_addressing_preferences(limit=4)

        assert {persistent_id, session_one_id, session_two_id} == {
            row["id"]
            for row in db.conn.execute("SELECT id FROM knowledge_base")
        }
        assert session_one_updated_id == session_one_id
        assert first[0]["id"] == session_one_id
        assert first[0]["value"] == "Use Australian phrasing"
        assert first[0]["key"] == "response_style"
        assert first[0]["preference_scope"] == "session"
        assert second[0]["id"] == session_two_id
        assert no_session[0]["id"] == persistent_id
    finally:
        db.close()


def test_expired_temporary_preference_reveals_persistent_value(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    now = datetime.now(timezone.utc)
    try:
        persistent_id = db.remember(
            "preference",
            "response_tone",
            "Be direct",
            generate_embedding=False,
        )
        temporary_id = db.remember(
            "preference",
            "response_tone",
            "Be playful",
            generate_embedding=False,
            metadata={
                "preference_slot": "response_tone",
                "preference_scope": "temporary",
                "expires_at": (now + timedelta(minutes=30)).isoformat(),
            },
        )

        active = db.get_addressing_preferences(limit=4, now=now)
        after_expiry = db.get_addressing_preferences(
            limit=4,
            now=now + timedelta(hours=1),
        )

        assert active[0]["id"] == temporary_id
        assert active[0]["preference_scope"] == "temporary"
        assert after_expiry[0]["id"] == persistent_id
        assert after_expiry[0]["value"] == "Be direct"
    finally:
        db.close()


def test_newer_alias_wins_within_scope_regardless_of_importance(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        db.conn.execute(
            """
            INSERT INTO knowledge_base
                (category, key, value, importance, created_at, updated_at)
            VALUES
                ('preference', 'preferred_name', 'Call me Old Name', 10,
                 '2026-01-01 00:00:00', '2026-01-01 00:00:00'),
                ('preference', 'how_to_address_user', 'Call me New Name', 5,
                 '2026-01-02 00:00:00', '2026-01-02 00:00:00')
            """
        )
        db.conn.commit()

        active = db.get_addressing_preferences(limit=4)

        assert len(active) == 1
        assert active[0]["key"] == "how_to_address_user"
        assert active[0]["value"] == "Call me New Name"
    finally:
        db.close()


def test_ordinary_topic_preference_is_not_canonicalized_or_pinned(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        memory_id = db.remember(
            "preference",
            "favorite_restaurant",
            "The Green Dragon",
            generate_embedding=False,
        )
        row = db.conn.execute(
            "SELECT category, key FROM knowledge_base WHERE id = ?",
            (memory_id,),
        ).fetchone()

        assert row["category"] == "preference"
        assert row["key"] == "favorite_restaurant"
        assert db.get_addressing_preferences(limit=4) == []
    finally:
        db.close()


def test_source_owned_profile_fact_does_not_become_an_active_override(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        memory_id = db.remember(
            "preference",
            "response_style",
            "Profile baseline says to be concise",
            source="intel/user-profile.md",
            generate_embedding=False,
            dedupe_by_source=True,
        )
        row = db.conn.execute(
            "SELECT category, key FROM knowledge_base WHERE id = ?",
            (memory_id,),
        ).fetchone()

        assert row["category"] == "preference"
        assert row["key"] == "response_style"
        assert db.get_addressing_preferences(limit=4) == []
    finally:
        db.close()


def test_default_resolver_limit_allows_all_four_canonical_slots(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        for slot in (
            "how_to_address_user",
            "response_style",
            "preferred_language",
            "response_tone",
        ):
            db.remember(
                "preference",
                slot,
                f"Active value for {slot}",
                generate_embedding=False,
            )

        active = db.get_addressing_preferences()

        assert {row["preference_slot"] for row in active} == {
            "how_to_address_user",
            "response_style",
            "preferred_language",
            "response_tone",
        }
    finally:
        db.close()


def test_scoped_preferences_fail_closed_without_lifecycle_data(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        with pytest.raises(ValueError, match="active Jarvis session"):
            db.remember(
                "preference",
                "response_style",
                "Talk like a pirate",
                generate_embedding=False,
                metadata={"preference_scope": "session"},
            )
        with pytest.raises(ValueError, match="expires_at or ttl_minutes"):
            db.remember(
                "preference",
                "response_style",
                "Talk like a pirate",
                generate_embedding=False,
                metadata={"preference_scope": "temporary"},
            )
        with pytest.raises(ValueError, match="timezone offset"):
            db.remember(
                "preference",
                "response_style",
                "Talk like a pirate",
                generate_embedding=False,
                metadata={
                    "preference_scope": "temporary",
                    "expires_at": "2027-01-01T12:00:00",
                },
            )
    finally:
        db.close()


def test_temporary_ttl_is_normalized_to_an_expiry(tmp_path):
    db = MemoryDB(str(tmp_path / "memory.db"))
    try:
        memory_id = db.remember(
            "preference",
            "preferred_language",
            "Use Australian English",
            generate_embedding=False,
            metadata={
                "preference_scope": "temporary",
                "ttl_minutes": 45,
            },
        )
        row = db.conn.execute(
            "SELECT metadata FROM knowledge_base WHERE id = ?",
            (memory_id,),
        ).fetchone()
        metadata = json.loads(row["metadata"])

        assert metadata["preference_scope"] == "temporary"
        assert metadata["expires_at"]
        assert "ttl_minutes" not in metadata
        assert db.get_addressing_preferences(limit=4)[0]["id"] == memory_id
    finally:
        db.close()


def test_remember_tool_binds_session_preference_to_web_conversation(monkeypatch):
    class FakeDb:
        kwargs = None
        closed = False

        def remember(self, **kwargs):
            self.kwargs = kwargs
            return 123

        def close(self):
            self.closed = True

    db = FakeDb()
    monkeypatch.setattr(remember_tool, "load_config", lambda: None)
    monkeypatch.setattr(remember_tool, "get_memory_db", lambda: db)
    monkeypatch.setenv("JARVIS_WEB_CONVERSATION_ID", "web-chat-abc")
    monkeypatch.setenv("JARVIS_SESSION_ID", "process-session-def")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "remember.py",
            json.dumps(
                {
                    "category": "preference",
                    "key": "response_style",
                    "value": "Talk like a pirate",
                    "preference_slot": "response_style",
                    "preference_scope": "session",
                }
            ),
        ],
    )

    result = remember_tool.main()

    assert result["ok"] is True
    assert result["data"]["key"] == "response_style"
    assert result["data"]["storage_key"].startswith(
        "preference_override:response_style:session:"
    )
    assert result["data"]["preference_scope"] == "session"
    assert db.kwargs["category"] == "preference"
    assert db.kwargs["key"].startswith("preference_override:response_style:session:")
    assert db.kwargs["metadata"]["preference_session_id"] == "web-chat-abc"
    assert db.closed is True
