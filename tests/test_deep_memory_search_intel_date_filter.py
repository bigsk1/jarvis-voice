"""Regression coverage for deep_memory_search intel date filtering."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from skills.deep_memory_search import search_intel_folder  # noqa: E402
import skills.deep_memory_search as deep_memory_search  # noqa: E402


def test_search_intel_folder_applies_date_filter(tmp_path, monkeypatch):
    intel_dir = tmp_path / "jarvis-intel"
    intel_dir.mkdir()

    token = "bh999c44a3_intel_filter_token"
    old_file = intel_dir / "old-topic.md"
    new_file = intel_dir / "new-topic.md"
    old_file.write_text(f"{token} garden pests on tomatoes")
    new_file.write_text(f"{token} garden pests on peppers")

    old_mtime = time.time() - (30 * 86400)
    os.utime(old_file, (old_mtime, old_mtime))

    monkeypatch.setattr(deep_memory_search, "PROJECT_ROOT", tmp_path)

    week_filter = datetime.now() - timedelta(days=7)
    filtered = search_intel_folder(token, limit=10, date_filter=week_filter)
    filtered_files = {item["file"] for item in filtered}

    assert "old-topic.md" not in filtered_files
    assert "new-topic.md" in filtered_files

    unfiltered = search_intel_folder(token, limit=10)
    all_files = {item["file"] for item in unfiltered}
    assert {"old-topic.md", "new-topic.md"}.issubset(all_files)
