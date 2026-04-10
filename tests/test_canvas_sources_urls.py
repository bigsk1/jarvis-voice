#!/usr/bin/env python3
"""Regression tests for Sources section URL normalization."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from skills.canvas import _normalize_bare_urls_in_sources_sections  # noqa: E402


def test_sources_line_comma_separated_hosts_get_https():
    raw = (
        "**Sources:** regmovies.com/theatres/regal-evergreen-parkway-rpx-0850, "
        "showtimes.com/movie-theaters/regal-evergreen-parkway-stadium-13-7773/"
    )
    out = _normalize_bare_urls_in_sources_sections(raw)
    assert "https://regmovies.com/theatres/regal-evergreen-parkway-rpx-0850" in out
    assert "https://showtimes.com/movie-theaters/regal-evergreen-parkway-stadium-13-7773/" in out


def test_existing_https_unchanged():
    raw = "Sources:\n- https://example.com/path\n- http://other.test/\n"
    assert _normalize_bare_urls_in_sources_sections(raw) == raw


def test_bullet_list_under_sources():
    raw = "Sources:\n- regmovies.com/a\n- showtimes.com/b\n\nNext section."
    out = _normalize_bare_urls_in_sources_sections(raw)
    assert "- https://regmovies.com/a" in out
    assert "- https://showtimes.com/b" in out
    assert "Next section." in out


def test_body_text_outside_sources_not_modified():
    raw = "Visit regmovies.com for showtimes.\n\nSources:\n- ok.com/x\n"
    out = _normalize_bare_urls_in_sources_sections(raw)
    assert "Visit regmovies.com for showtimes." in out
    assert "- https://ok.com/x" in out
