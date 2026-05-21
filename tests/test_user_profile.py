#!/usr/bin/env python3
"""Tests for user profile card extraction, cache, and synthesis injection."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from memory_db import MemoryDB
from user_profile import (
    PROFILE_CARD_CACHE_KEY,
    ROUTER_PROFILE_BOUNDARY,
    append_profile_card_for_router_direct_answer,
    append_user_profile_card_to_prompt,
    extract_profile_card,
    get_cached_profile_card,
    load_profile_card_from_disk,
    profile_source_hash,
)


SAMPLE_PROFILE = """# User Profile

## Profile Card

- **Role**: Operator
- **Execution**: Surgical diffs only

## Profile Reference

### Projects

- jarvis-voice
"""


class UserProfileTests(unittest.TestCase):
    def test_extract_profile_card_stops_at_next_heading(self) -> None:
        card = extract_profile_card(SAMPLE_PROFILE)
        self.assertIn("Operator", card)
        self.assertNotIn("jarvis-voice", card)

    def test_profile_source_hash_stable(self) -> None:
        self.assertEqual(profile_source_hash("abc"), profile_source_hash("abc"))
        self.assertNotEqual(profile_source_hash("abc"), profile_source_hash("abcd"))

    def test_load_profile_card_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "user_profile.md"
            path.write_text(SAMPLE_PROFILE, encoding="utf-8")
            card, digest, mtime = load_profile_card_from_disk(path)
            self.assertIn("Operator", card)
            self.assertTrue(digest)
            self.assertIsNotNone(mtime)

    def test_cached_profile_card_uses_user_model_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "memory.db"
            profile_path = Path(tmpdir) / "user_profile.md"
            profile_path.write_text(SAMPLE_PROFILE, encoding="utf-8")

            db = MemoryDB(str(db_path))
            try:
                with patch("user_profile.default_profile_path", return_value=profile_path), patch(
                    "user_profile._profile_card_enabled", return_value=True
                ):
                    card1 = get_cached_profile_card(force_refresh=True, db=db)
                    self.assertIn("Operator", card1)
                    cached = db.get_user_model_trait(PROFILE_CARD_CACHE_KEY)
                    self.assertIsNotNone(cached)
                    self.assertEqual(cached.get("value_type"), "text")

                    card2 = get_cached_profile_card(force_refresh=False, db=db)
                    self.assertEqual(card1, card2)
            finally:
                db.close()

    def test_append_user_profile_card_to_prompt(self) -> None:
        with patch("user_profile.get_cached_profile_card", return_value="- **Role**: Operator"):
            prompt = append_user_profile_card_to_prompt("Base synthesis prompt.")
            self.assertIn("USER PROFILE CARD", prompt)
            self.assertIn("Operator", prompt)

    def test_append_skips_when_disabled(self) -> None:
        with patch("user_profile._profile_card_enabled", return_value=False):
            self.assertEqual(
                append_user_profile_card_to_prompt("Base only."),
                "Base only.",
            )

    def test_append_router_direct_answer_includes_boundary(self) -> None:
        with patch("user_profile.get_cached_profile_card", return_value="- **Role**: Operator"):
            prompt = append_profile_card_for_router_direct_answer("Router base prompt.")
            self.assertIn(ROUTER_PROFILE_BOUNDARY, prompt)
            self.assertIn("Does not affect Tool RAG retrieval", prompt)
            self.assertIn("Operator", prompt)

    def test_append_router_skips_when_disabled(self) -> None:
        with patch("user_profile._profile_card_enabled", return_value=False):
            self.assertEqual(
                append_profile_card_for_router_direct_answer("Router only."),
                "Router only.",
            )


if __name__ == "__main__":
    unittest.main()
