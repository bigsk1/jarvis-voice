#!/usr/bin/env python3
"""Regression tests for serpapi_youtube helpers."""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from serpapi_youtube import extract_video_id, normalize_video_data


class SerpApiYouTubeTests(unittest.TestCase):
    def test_extract_video_id_from_watch_url(self):
        self.assertEqual(
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_extract_video_id_from_short_url(self):
        self.assertEqual(
            extract_video_id("https://youtu.be/dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_normalize_video_data_keeps_transcript_link_and_related_videos(self):
        payload = {
            "title": "Example YouTube Video",
            "link": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "description": "A video description",
            "thumbnail": {
                "static": "https://img.youtube.com/example.jpg",
            },
            "channel": {
                "name": "Example Channel",
                "link": "https://www.youtube.com/@example",
                "thumbnail": "https://yt3.example.com/channel.jpg",
                "verified": True,
            },
            "views": "1.2M views",
            "extracted_views": 1200000,
            "length": "3:33",
            "published_date": "2 years ago",
            "transcript": {
                "serpapi_link": "https://serpapi.com/search.json?engine=youtube_video_transcript&video_id=dQw4w9WgXcQ&language_code=en"
            },
            "related_videos": [
                {
                    "video_id": "abc123def45",
                    "title": "Related One",
                    "link": "https://www.youtube.com/watch?v=abc123def45",
                    "thumbnail": "https://img.youtube.com/related.jpg",
                    "views": "50K views",
                    "length": "10:00",
                    "channel": {"name": "Another Channel"},
                }
            ],
        }

        data = normalize_video_data(payload, "dQw4w9WgXcQ")
        self.assertEqual(data["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(data["channel"], "Example Channel")
        self.assertEqual(data["transcript_api_url"], payload["transcript"]["serpapi_link"])
        self.assertEqual(data["related_videos"][0]["video_id"], "abc123def45")


if __name__ == "__main__":
    unittest.main()
