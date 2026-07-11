#!/usr/bin/env python3
"""Regression tests for memory_deduper report metadata."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "skills"))

import memory_deduper  # noqa: E402


def _summary(**overrides):
    summary = {
        "database_mode": "cloud",
        "database_label": "Cloud memory DB",
        "database_path": str(PROJECT_ROOT / "data" / "jarvis_memory.db"),
        "database_path_display": "data/jarvis_memory.db",
        "scanned_memories": 12,
        "categories_scanned": 3,
        "exact_duplicate_groups": 1,
        "probable_duplicate_groups": 2,
        "conflict_pairs": 0,
        "pair_checks": 42,
    }
    summary.update(overrides)
    return summary


def _empty_analysis():
    return {
        "exact_groups": [],
        "probable_groups": [],
        "conflicts": [],
    }


def test_markdown_report_identifies_cloud_database():
    report = memory_deduper.build_markdown_report(
        summary=_summary(),
        analysis=_empty_analysis(),
        max_output_groups=10,
    )

    assert report.startswith("# Memory Deduper Report - Cloud memory DB")
    assert "- Database: Cloud memory DB (`cloud`)" in report
    assert "- Database file: `data/jarvis_memory.db`" in report


def test_database_context_identifies_local_memory_db(monkeypatch):
    monkeypatch.setenv("JARVIS_MODE", "local")

    context = memory_deduper.database_context(
        str(PROJECT_ROOT / "data" / "jarvis_memory_local.db")
    )

    assert context["mode"] == "local"
    assert context["label"] == "Local memory DB"
    assert context["path_display"] == "data/jarvis_memory_local.db"
