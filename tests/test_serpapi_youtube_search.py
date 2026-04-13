#!/usr/bin/env python3
"""Regression tests for serpapi_youtube_search helpers."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from serpapi_youtube_search import build_speech, normalize_video_results, rank_video_results


class SerpApiYouTubeSearchTests(unittest.TestCase):
    def test_normalize_video_results_returns_video_first_fields(self):
        payload = {
            "video_results": [
                {
                    "video_id": "abc123def45",
                    "title": "Ferment Peppers Hot Sauce",
                    "link": "https://www.youtube.com/watch?v=abc123def45",
                    "serpapi_link": "https://serpapi.com/search.json?engine=youtube_video&v=abc123def45",
                    "thumbnail": {
                        "static": "https://i.ytimg.com/vi/abc123def45/hqdefault.jpg",
                    },
                    "published_date": "1 year ago",
                    "views": "150K views",
                    "extracted_views": 150000,
                    "length": "12:34",
                    "channel": {
                        "name": "Pepper Geek",
                        "link": "https://www.youtube.com/@peppergeek",
                        "verified": True,
                    },
                }
            ]
        }

        results = normalize_video_results(payload, limit=5)
        self.assertEqual(results[0]["video_id"], "abc123def45")
        self.assertEqual(results[0]["channel"], "Pepper Geek")
        self.assertEqual(results[0]["duration"], "12:34")
        self.assertEqual(results[0]["thumbnail"], "https://i.ytimg.com/vi/abc123def45/hqdefault.jpg")
        self.assertEqual(results[0]["extracted_views"], 150000)

    def test_rank_video_results_prefers_highest_views_for_popularity_queries(self):
        results = [
            {
                "video_id": "lowviews0001",
                "title": "Recent Pumpkin Tips",
                "views": "101K views",
                "extracted_views": 101000,
                "channel": "Epic Gardening",
                "published_date": "8 months ago",
            },
            {
                "video_id": "highviews002",
                "title": "5 Tips How to Grow Ton of Pumpkins at Home",
                "views": "765K views",
                "extracted_views": 765000,
                "channel": "Self Sufficient Me",
                "published_date": "4 years ago",
            },
        ]

        ranked, ranking_mode = rank_video_results("popular pumpkin growing videos", results)
        self.assertEqual(ranking_mode, "views_desc")
        self.assertEqual(ranked[0]["video_id"], "highviews002")

    def test_build_speech_mentions_top_by_views_when_ranked(self):
        speech = build_speech(
            "popular pumpkin growing videos",
            [
                {
                    "title": "5 Tips How to Grow Ton of Pumpkins at Home",
                    "channel": "Self Sufficient Me",
                    "published_date": "4 years ago",
                    "views": "765K views",
                }
            ],
            ranking_mode="views_desc",
        )
        self.assertIn("Top by views", speech)
        self.assertIn("765K views", speech)


if __name__ == "__main__":
    unittest.main()
