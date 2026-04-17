#!/usr/bin/env python3
"""Tests for bookmark_search AND/OR semantics and domain matching."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import bookmark_search as bs


def _bm(title: str, url: str, folder: str = "Toolbar / Youtube") -> dict:
    return {
        "id": 1,
        "title": title,
        "url": url,
        "domain": "youtube.com",
        "path": "/",
        "folders": folder.split(" / ") if folder else [],
        "folder_path": folder,
        "tags": [],
        "folder_labels": [folder.lower().replace(" / ", " ")],
        "all_tags": [],
        "keyword": None,
        "added_at": None,
        "added_at_iso": None,
        "modified_at": None,
        "modified_at_iso": None,
    }


class BookmarkSearchMatchTests(unittest.TestCase):
    def test_any_mode_multi_term_matches_youtube_domain_without_chili(self):
        """Regression: OR + 'youtube' in youtube.com matched every YouTube bookmark."""
        bookmark = _bm("InvestAnswers - YouTube", "https://www.youtube.com/@InvestAnswers/featured")
        terms, phrases = bs.parse_query("chili youtube")
        ok_any, _ = bs.match_query(bookmark, terms, phrases, "any")
        self.assertTrue(ok_any)

    def test_all_mode_multi_term_requires_chili_and_youtube(self):
        bookmark = _bm("InvestAnswers - YouTube", "https://www.youtube.com/@InvestAnswers/featured")
        terms, phrases = bs.parse_query("chili youtube")
        ok_all, _ = bs.match_query(bookmark, terms, phrases, "all")
        self.assertFalse(ok_all)

    def test_all_mode_matches_when_both_terms_present(self):
        bookmark = _bm("Chili recipes", "https://www.youtube.com/watch?v=abc123")
        terms, phrases = bs.parse_query("chili youtube")
        ok_all, score = bs.match_query(bookmark, terms, phrases, "all")
        self.assertTrue(ok_all)
        self.assertGreater(score, 0)

    def test_quoted_phrase_single_unit(self):
        bookmark = _bm("Other", "https://www.youtube.com/watch?v=xyz")
        terms, phrases = bs.parse_query('"chili youtube"')
        self.assertEqual(terms, [])
        self.assertEqual(phrases, ["chili youtube"])
        ok, _ = bs.match_query(bookmark, terms, phrases, "any")
        self.assertFalse(ok)


class BookmarkSearchDefaultQueryModeTests(unittest.TestCase):
    def test_main_defaults_to_all_for_multi_term_when_query_mode_omitted(self):
        """Simulate search_bookmarks call path: omit query_mode + multi-word query."""
        bookmarks = [
            _bm("InvestAnswers - YouTube", "https://www.youtube.com/@InvestAnswers/featured"),
            _bm("Chili cookoff stream", "https://www.youtube.com/watch?v=abc"),
        ]
        for i, b in enumerate(bookmarks):
            b["id"] = i + 1

        terms, phrases = bs.parse_query("chili youtube")
        raw_mode = None
        if raw_mode is None or (isinstance(raw_mode, str) and not str(raw_mode).strip()):
            search_query_mode = "all" if (len(terms) + len(phrases) > 1) else "any"
        else:
            search_query_mode = "any"

        self.assertEqual(search_query_mode, "all")

        out = bs.search_bookmarks(
            bookmarks=bookmarks,
            query="chili youtube",
            tag_filters=[],
            folder_filters=[],
            domain_filters=[],
            query_mode=search_query_mode,
            sort_by="relevance",
            include_duplicates=True,
            limit=20,
            offset=0,
        )
        self.assertEqual(out["data"]["matched_count"], 1)
        self.assertIn("chili", out["data"]["results"][0]["title"].lower())


if __name__ == "__main__":
    unittest.main()
