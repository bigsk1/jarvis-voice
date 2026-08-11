#!/usr/bin/env python3
"""Regression tests for serpapi_youtube helpers."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

from serpapi_youtube import (
    build_transcript_markdown,
    extract_video_id,
    normalize_video_data,
    save_transcript_to_stash,
)


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

    def test_build_transcript_markdown_keeps_every_ordered_segment(self):
        markdown = build_transcript_markdown(
            {
                "title": "Example Video",
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            },
            {
                "transcript": [
                    {"start_time_text": "0:00", "snippet": "First segment."},
                    {"start_time_text": "0:07", "snippet": "Second segment."},
                ]
            },
        )

        self.assertLess(markdown.index("First segment."), markdown.index("Second segment."))
        self.assertIn("**[0:00]** First segment.", markdown)
        self.assertIn("Source: https://www.youtube.com/watch?v=dQw4w9WgXcQ", markdown)

    @patch("serpapi_youtube.StashFile")
    @patch("serpapi_youtube.open_space")
    def test_save_transcript_exposes_durable_followup_ref(self, open_space, stash_file):
        open_space.return_value = (SimpleNamespace(space_id="space_youtube"), True)
        saver = Mock()
        saver.save_text.return_value = {
            "file_id": "f_transcript",
            "ref": "stash://space_youtube/f_transcript",
        }
        stash_file.return_value = saver

        result = save_transcript_to_stash(
            {"video_id": "dQw4w9WgXcQ", "title": "Example Video"},
            {"transcript": [{"start_time_text": "0:00", "snippet": "Full text."}]},
        )

        self.assertTrue(result["transcript_saved"])
        self.assertEqual(result["md_stash_ref"], "stash://space_youtube/f_transcript")
        self.assertEqual(
            result["transcript_stash_ref"],
            "stash://space_youtube/f_transcript",
        )
        saved_markdown = saver.save_text.call_args.kwargs["content"]
        self.assertIn("Full text.", saved_markdown)


if __name__ == "__main__":
    unittest.main()
