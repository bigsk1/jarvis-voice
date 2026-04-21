#!/usr/bin/env python3
"""
Analyze a Firefox/Netscape bookmark HTML export (same format as bookmark_search).

Reports:
  - Total <a> bookmarks parsed (matches bookmark_search total_bookmarks)
  - Unique URLs and how many bookmark rows are duplicates (same URL repeated)
  - Optional: raw count of <a href= lines for sanity check vs parser

Usage:
  source ~/jarvis-venv/bin/activate
  ./bin/analyze-bookmarks-export.py
  ./bin/analyze-bookmarks-export.py /path/to/bookmarks.html

Cross-check with ripgrep (approximate — counts lines with href= on <a> tags):
  rg -c '<a[^>]+href=' data/bookmarks.html
  rg -c 'HREF=' data/bookmarks.html

---

Where truncation can affect bookmarks / chat (for debugging "truncated URL" reports):

  • Web UI — no global limit on assistant message body. chat.js renders full text;
    Utils.truncate() defaults to 100 chars but is only used for toasts (30 chars),
    tool catalog descriptions (500), etc., not the main answer bubble.

  • jarvis-web/server/sockets/chat.py — _truncate_for_prompt(..., max_chars=6000–8000)
    truncates JSON sent to the *model* in repair/synthesis prompts, not what the
    user sees in the bubble. Adds suffix "... [truncated]".

  • orchestrator/orchestrator_v2.py — fallback synthesis can return extracted_data[:400]
    only when the provider returns empty/error in a narrow path (not normal chat).

  • _truncate_followup_summary in chat.py — max 5000 chars for follow-up context
    summaries (text_summarizer etc.), not the primary assistant reply.

  • If the *assistant* text says URLs are "truncated in preview", that is usually the
    model paraphrasing, not this codebase cutting bookmark URLs.

"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze bookmark export duplicates and counts.")
    parser.add_argument(
        "bookmark_file",
        nargs="?",
        default=None,
        help="Path to bookmarks.html (default: <repo>/data/bookmarks.html)",
    )
    parser.add_argument(
        "--raw-href-count",
        action="store_true",
        help="Also print a regex count of <a ... href= occurrences in the file (sanity check).",
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parent.parent
    default_path = repo / "data" / "bookmarks.html"
    path = Path(args.bookmark_file).expanduser() if args.bookmark_file else default_path
    if not path.is_absolute():
        path = (repo / path).resolve()
    else:
        path = path.resolve()
    if not path.is_file():
        print(f"Not a file: {path}", file=sys.stderr)
        return 1

    sys.path.insert(0, str(repo / "skills"))
    from bookmark_search import parse_bookmark_file

    bookmarks = parse_bookmark_file(path)
    total = len(bookmarks)
    urls = [b.get("url") or "" for b in bookmarks]
    url_counts = Counter(urls)
    unique_urls = len(url_counts)
    # Rows beyond the first per URL are "duplicate rows"
    duplicate_rows = sum(c - 1 for c in url_counts.values() if c > 1)
    urls_with_dupes = sum(1 for c in url_counts.values() if c > 1)

    print(f"File: {path}")
    print(f"Total bookmark rows (parsed): {total}")
    print(f"Unique URLs:                  {unique_urls}")
    print(f"Duplicate rows (extra copies): {duplicate_rows}  ({urls_with_dupes} URLs appear more than once)")
    if total:
        print(f"Duplicate row share:          {duplicate_rows / total:.1%} of rows")
    print()

    if urls_with_dupes:
        print("URLs with the most duplicate rows (top 15):")
        ranked = [(u, c) for u, c in url_counts.most_common() if c > 1][:15]
        for i, (url, count) in enumerate(ranked, 1):
            short = url if len(url) <= 96 else url[:93] + "..."
            print(f"  {i:2}. x{count:3}  {short}")
        print()

    if args.raw_href_count:
        raw = path.read_text(encoding="utf-8", errors="replace")
        # Loose count of bookmark-style anchors (same file may use HREF or href)
        n_href = len(re.findall(r"<a\s+[^>]*href\s*=", raw, flags=re.IGNORECASE))
        print(f"Regex count of <a ... href= in file: {n_href}")
        print(f"  (should match parsed total if every <a> is a bookmark anchor)")
        if n_href != total:
            print(f"  Note: mismatch vs parser ({total}) can mean non-bookmark <a> tags in file.")

    print()
    print("bookmark_search `total_bookmarks` is len(parsed rows), not unique URLs.")
    print("Search `include_duplicates: false` dedupes by URL when building match lists.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
