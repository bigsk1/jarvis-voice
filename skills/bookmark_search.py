#!/usr/bin/env python3
"""
Bookmark Search Tool

Parses Firefox/Netscape bookmark export HTML and supports:
- Full-text search with keyword/phrase matching
- Tag filtering (Firefox TAGS + folder-derived labels)
- Folder and domain filters
- Bookmark stats, folder listing, and tag listing
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from paths import assert_not_restricted_read_path


MAX_RESULTS = 200
DEFAULT_LIMIT = 20
DEFAULT_BOOKMARK_FILE = "data/bookmarks.html"


def clean_text(value: str) -> str:
    """Collapse repeated whitespace and trim."""
    return " ".join(value.split()).strip()


def parse_epoch(value: str | None) -> int | None:
    """Parse unix epoch seconds, returning None if invalid."""
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def epoch_to_iso(value: int | None) -> str | None:
    """Convert unix epoch seconds to ISO-8601 UTC."""
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def parse_csv_list(value: Any) -> list[str]:
    """Parse comma-separated or list input into normalized lowercase strings."""
    if value is None:
        return []

    raw_items: list[str]
    if isinstance(value, list):
        raw_items = [str(item) for item in value]
    elif isinstance(value, str):
        raw_items = re.split(r"[,\n]", value)
    else:
        raw_items = [str(value)]

    seen: set[str] = set()
    cleaned: list[str] = []
    for item in raw_items:
        token = item.strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


def tokenize_words(value: str) -> list[str]:
    """Tokenize text into lowercase word-ish tokens."""
    return re.findall(r"[a-z0-9][a-z0-9._-]*", value.lower())


def parse_query(query: str) -> tuple[list[str], list[str]]:
    """Extract search terms and quoted phrases from a query string."""
    if not query:
        return [], []

    phrases: list[str] = []
    phrase_pattern = re.compile(r'"([^"]+)"|\'([^\']+)\'')
    for match in phrase_pattern.finditer(query):
        phrase = (match.group(1) or match.group(2) or "").strip().lower()
        if phrase:
            phrases.append(phrase)

    query_without_phrases = phrase_pattern.sub(" ", query)
    terms = tokenize_words(query_without_phrases)

    # Deduplicate while preserving order.
    seen_terms: set[str] = set()
    deduped_terms: list[str] = []
    for term in terms:
        if term in seen_terms:
            continue
        seen_terms.add(term)
        deduped_terms.append(term)

    seen_phrases: set[str] = set()
    deduped_phrases: list[str] = []
    for phrase in phrases:
        if phrase in seen_phrases:
            continue
        seen_phrases.add(phrase)
        deduped_phrases.append(phrase)

    return deduped_terms, deduped_phrases


def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse bool-ish values from JSON input."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    return default


def normalize_domain(hostname: str | None) -> str:
    """Normalize hostnames for matching and output."""
    if not hostname:
        return ""
    domain = hostname.strip().lower()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def domain_matches(candidate: str, requested: str) -> bool:
    """
    Match a candidate domain with a requested domain/filter.
    Allows exact match and subdomain match.
    """
    normalized_requested = normalize_domain(requested)
    if not normalized_requested:
        return False
    return candidate == normalized_requested or candidate.endswith(f".{normalized_requested}")


class FirefoxBookmarkParser(HTMLParser):
    """
    Streaming parser for Firefox/Netscape bookmark exports.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.folder_stack: list[str] = []
        self.dl_stack: list[bool] = []
        self.pending_folder: str | None = None

        self.current_h3_parts: list[str] | None = None
        self.current_anchor: dict[str, Any] | None = None
        self.current_anchor_parts: list[str] = []

        self.bookmarks: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lower_tag = tag.lower()

        if lower_tag == "h3":
            self.current_h3_parts = []
            return

        if lower_tag == "dl":
            if self.pending_folder:
                self.folder_stack.append(self.pending_folder)
                self.dl_stack.append(True)
                self.pending_folder = None
            else:
                self.dl_stack.append(False)
            return

        if lower_tag == "a":
            attrs_map: dict[str, str] = {}
            for key, value in attrs:
                if not key or value is None:
                    continue
                lower_key = key.lower()
                if lower_key in {"href", "add_date", "last_modified", "tags", "shortcuturl"}:
                    attrs_map[lower_key] = value

            self.current_anchor = {
                "url": attrs_map.get("href", "").strip(),
                "add_date": parse_epoch(attrs_map.get("add_date")),
                "last_modified": parse_epoch(attrs_map.get("last_modified")),
                "tags": parse_csv_list(attrs_map.get("tags")),
                "keyword": attrs_map.get("shortcuturl", "").strip() or None,
                "folders": list(self.folder_stack),
            }
            self.current_anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()

        if lower_tag == "h3":
            if self.current_h3_parts is not None:
                folder_name = clean_text("".join(self.current_h3_parts))
                if folder_name:
                    self.pending_folder = folder_name
            self.current_h3_parts = None
            return

        if lower_tag == "a":
            if self.current_anchor is not None:
                title = clean_text("".join(self.current_anchor_parts))
                self.bookmarks.append(build_bookmark_record(self.current_anchor, title, len(self.bookmarks) + 1))
            self.current_anchor = None
            self.current_anchor_parts = []
            return

        if lower_tag == "dl":
            if not self.dl_stack:
                return
            was_folder_scope = self.dl_stack.pop()
            if was_folder_scope and self.folder_stack:
                self.folder_stack.pop()

    def handle_data(self, data: str) -> None:
        if self.current_anchor is not None:
            self.current_anchor_parts.append(data)
            return

        if self.current_h3_parts is not None:
            self.current_h3_parts.append(data)


def build_bookmark_record(raw: dict[str, Any], title: str, bookmark_id: int) -> dict[str, Any]:
    """Build normalized bookmark record for searching/filtering."""
    url = raw.get("url", "")
    parsed = urlparse(url)
    domain = normalize_domain(parsed.hostname)
    path = unquote(parsed.path or "")
    folders: list[str] = raw.get("folders", [])
    folder_path = " / ".join(folders) if folders else ""

    folder_labels = [clean_text(folder).lower() for folder in folders if clean_text(folder)]
    folder_token_set: set[str] = set()
    for label in folder_labels:
        for token in tokenize_words(label):
            if len(token) >= 2:
                folder_token_set.add(token)

    explicit_tags = [tag.lower() for tag in raw.get("tags", []) if tag]
    all_tag_labels = sorted(set(explicit_tags + folder_labels + list(folder_token_set)))

    final_title = title or url
    return {
        "id": bookmark_id,
        "title": final_title,
        "url": url,
        "domain": domain,
        "path": path,
        "folders": folders,
        "folder_path": folder_path,
        "tags": explicit_tags,
        "folder_labels": folder_labels,
        "all_tags": all_tag_labels,
        "keyword": raw.get("keyword"),
        "added_at": raw.get("add_date"),
        "added_at_iso": epoch_to_iso(raw.get("add_date")),
        "modified_at": raw.get("last_modified"),
        "modified_at_iso": epoch_to_iso(raw.get("last_modified")),
    }


def parse_bookmark_file(bookmark_file: Path) -> list[dict[str, Any]]:
    """Parse bookmarks HTML export file."""
    parser = FirefoxBookmarkParser()
    with bookmark_file.open("r", encoding="utf-8", errors="replace") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            parser.feed(chunk)
    parser.close()
    return parser.bookmarks


def match_query(
    bookmark: dict[str, Any], terms: list[str], phrases: list[str], query_mode: str
) -> tuple[bool, int]:
    """
    Match query terms/phrases and return (matched, score).

    Terms match as substrings in title, URL, folder path, tags, keyword, and
    domain. A term like \"youtube\" therefore matches the domain \"youtube.com\".
    With query_mode \"any\" and multiple terms, only one term needs to match,
    which can return unrelated YouTube links. Callers should default multi-word
    queries to query_mode \"all\" (every term must match) unless OR is intended.
    """
    if not terms and not phrases:
        return True, 0

    title = bookmark["title"].lower()
    url = bookmark["url"].lower()
    folder_path = bookmark["folder_path"].lower()
    domain = bookmark["domain"]
    keyword = (bookmark.get("keyword") or "").lower()
    tags = bookmark["all_tags"]

    matched_parts = 0
    required_parts = len(terms) + len(phrases)
    score = 0

    for phrase in phrases:
        phrase_score = 0
        if phrase in title:
            phrase_score += 12
        if phrase in folder_path:
            phrase_score += 9
        if phrase in url:
            phrase_score += 7
        if any(phrase in tag for tag in tags):
            phrase_score += 8
        if phrase in keyword:
            phrase_score += 4

        if phrase_score > 0:
            matched_parts += 1
            score += phrase_score

    for term in terms:
        term_score = 0
        if term in title:
            term_score += 5
        if term in folder_path:
            term_score += 4
        if term in domain:
            term_score += 4
        if term in url:
            term_score += 3
        if term in keyword:
            term_score += 2
        if any(term in tag for tag in tags):
            term_score += 4

        if term_score > 0:
            matched_parts += 1
            score += term_score

    if query_mode == "all":
        return matched_parts == required_parts, score
    return matched_parts > 0, score


def matches_tag_filters(bookmark: dict[str, Any], tag_filters: list[str], mode: str) -> bool:
    """Match bookmark tag labels against requested tag filters."""
    if not tag_filters:
        return True

    labels = bookmark["all_tags"]
    if mode == "all":
        return all(any(filter_tag in label for label in labels) for filter_tag in tag_filters)
    return any(any(filter_tag in label for label in labels) for filter_tag in tag_filters)


def matches_folder_filters(bookmark: dict[str, Any], folder_filters: list[str], mode: str) -> bool:
    """Match bookmark folder path against requested folder filters."""
    if not folder_filters:
        return True

    folder_path = bookmark["folder_path"].lower()
    if mode == "all":
        return all(fragment in folder_path for fragment in folder_filters)
    return any(fragment in folder_path for fragment in folder_filters)


def matches_domain_filters(bookmark: dict[str, Any], domain_filters: list[str]) -> bool:
    """Match bookmark domain against requested domain filters."""
    if not domain_filters:
        return True

    candidate = bookmark["domain"]
    return any(domain_matches(candidate, requested) for requested in domain_filters)


def resolve_bookmark_path(project_root: Path, input_value: str | None) -> Path:
    """Resolve bookmark file path from arg or default."""
    raw_path = input_value.strip() if input_value else DEFAULT_BOOKMARK_FILE
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    resolved = assert_not_restricted_read_path(candidate, label="Bookmark file")
    if not resolved.exists():
        raise FileNotFoundError(f"Bookmark file not found: {resolved}")
    if not resolved.is_file():
        raise ValueError(f"Bookmark path is not a file: {resolved}")
    return resolved


def search_bookmarks(
    bookmarks: list[dict[str, Any]],
    query: str,
    tag_filters: list[str],
    folder_filters: list[str],
    domain_filters: list[str],
    query_mode: str,
    sort_by: str,
    include_duplicates: bool,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Search and filter bookmarks."""
    terms, phrases = parse_query(query)

    matches: list[dict[str, Any]] = []
    for bookmark in bookmarks:
        if not matches_domain_filters(bookmark, domain_filters):
            continue
        if not matches_tag_filters(bookmark, tag_filters, query_mode):
            continue
        if not matches_folder_filters(bookmark, folder_filters, query_mode):
            continue

        query_match, score = match_query(bookmark, terms, phrases, query_mode)
        if not query_match:
            continue

        record = dict(bookmark)
        record["score"] = score
        matches.append(record)

    if not include_duplicates:
        unique_by_url: dict[str, dict[str, Any]] = {}
        for item in matches:
            key = item.get("url", "")
            existing = unique_by_url.get(key)
            if existing is None:
                unique_by_url[key] = item
                continue
            existing_score = existing.get("score", 0)
            new_score = item.get("score", 0)
            if new_score > existing_score:
                unique_by_url[key] = item
            elif new_score == existing_score:
                existing_ts = existing.get("added_at") or 0
                new_ts = item.get("added_at") or 0
                if new_ts > existing_ts:
                    unique_by_url[key] = item
        matches = list(unique_by_url.values())

    if sort_by == "title":
        matches.sort(key=lambda item: (item["title"].lower(), item["domain"], -(item.get("added_at") or 0)))
    elif sort_by == "domain":
        matches.sort(key=lambda item: (item["domain"], item["title"].lower(), -(item.get("added_at") or 0)))
    elif sort_by == "recent":
        matches.sort(key=lambda item: (-(item.get("added_at") or 0), item["title"].lower()))
    else:
        # relevance (default)
        if terms or phrases:
            matches.sort(key=lambda item: (-(item.get("score") or 0), -(item.get("added_at") or 0), item["title"].lower()))
        else:
            matches.sort(key=lambda item: (-(item.get("added_at") or 0), item["title"].lower()))

    total_matches = len(matches)
    sliced = matches[offset : offset + limit]

    results = [
        {
            "id": item["id"],
            "title": item["title"],
            "url": item["url"],
            "domain": item["domain"],
            "folder_path": item["folder_path"],
            "tags": item["tags"],
            "keyword": item.get("keyword"),
            "added_at_iso": item.get("added_at_iso"),
            "modified_at_iso": item.get("modified_at_iso"),
            "score": item.get("score", 0),
        }
        for item in sliced
    ]

    if total_matches == 0:
        speech = "I found no matching bookmarks."
    else:
        query_part = f" for '{query}'" if query else ""
        speech = f"I found {total_matches} bookmark matches{query_part}, returning {len(results)}."

    # Compact multi-line block for workflow LLM speech (e.g. * bookmark_search)
    if not results:
        results_for_llm = "No bookmarks matched this query."
    else:
        lines: list[str] = []
        for i, r in enumerate(results[:15], start=1):
            title = r.get("title") or "(no title)"
            url = r.get("url") or ""
            domain = r.get("domain") or ""
            folder = (r.get("folder_path") or "").strip()
            tags = r.get("tags") or []
            tag_str = ", ".join(str(t) for t in tags[:10]) if tags else ""
            block = f"{i}. {title}\n   URL: {url}\n   Domain: {domain}"
            if folder:
                block += f"\n   Folder: {folder}"
            if tag_str:
                block += f"\n   Tags: {tag_str}"
            lines.append(block)
        extra = ""
        if total_matches > len(results):
            extra = f"\n\n(Showing {len(results)} of {total_matches} total matches.)"
        results_for_llm = "\n\n".join(lines) + extra

    return {
        "speech": speech,
        "data": {
            "query": query,
            "query_terms": terms,
            "query_phrases": phrases,
            "filters": {
                "tags": tag_filters,
                "folders": folder_filters,
                "domains": domain_filters,
                "query_mode": query_mode,
                "include_duplicates": include_duplicates,
            },
            "sort_by": sort_by,
            "offset": offset,
            "limit": limit,
            "total_bookmarks": len(bookmarks),
            "matched_count": total_matches,
            "returned_count": len(results),
            "results": results,
            "results_for_llm": results_for_llm,
        },
    }


def list_tags(bookmarks: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """List most common explicit and derived tags."""
    explicit_counter: Counter[str] = Counter()
    derived_counter: Counter[str] = Counter()
    combined_counter: Counter[str] = Counter()

    for bookmark in bookmarks:
        explicit = bookmark["tags"]
        derived = bookmark["folder_labels"]

        explicit_counter.update(explicit)
        derived_counter.update(derived)
        combined_counter.update(set(explicit + derived))

    explicit = [{"tag": key, "count": value} for key, value in explicit_counter.most_common(limit)]
    derived = [{"tag": key, "count": value} for key, value in derived_counter.most_common(limit)]
    combined = [{"tag": key, "count": value} for key, value in combined_counter.most_common(limit)]

    speech = (
        f"I found {len(explicit_counter)} explicit tags and "
        f"{len(derived_counter)} folder-derived tags."
    )

    return {
        "speech": speech,
        "data": {
            "total_bookmarks": len(bookmarks),
            "explicit_tag_count": len(explicit_counter),
            "derived_tag_count": len(derived_counter),
            "top_explicit_tags": explicit,
            "top_derived_tags": derived,
            "top_combined_tags": combined,
        },
    }


def list_folders(bookmarks: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """List folders by bookmark count."""
    counter: Counter[str] = Counter()
    for bookmark in bookmarks:
        path = bookmark["folder_path"] or "(root)"
        counter[path] += 1

    top_folders = [{"folder_path": key, "count": value} for key, value in counter.most_common(limit)]
    speech = f"I found {len(counter)} bookmark folders."
    return {
        "speech": speech,
        "data": {
            "total_bookmarks": len(bookmarks),
            "folder_count": len(counter),
            "top_folders": top_folders,
        },
    }


def stats(bookmarks: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    """Return aggregate bookmark stats."""
    domain_counter: Counter[str] = Counter()
    folder_counter: Counter[str] = Counter()
    explicit_tag_counter: Counter[str] = Counter()

    urls: set[str] = set()
    with_tags = 0
    with_keyword = 0

    for bookmark in bookmarks:
        domain_counter[bookmark["domain"] or "(none)"] += 1
        folder_counter[bookmark["folder_path"] or "(root)"] += 1
        explicit_tag_counter.update(bookmark["tags"])
        urls.add(bookmark["url"])
        if bookmark["tags"]:
            with_tags += 1
        if bookmark.get("keyword"):
            with_keyword += 1

    top_domains = [{"domain": key, "count": value} for key, value in domain_counter.most_common(limit)]
    top_folders = [{"folder_path": key, "count": value} for key, value in folder_counter.most_common(limit)]
    top_tags = [{"tag": key, "count": value} for key, value in explicit_tag_counter.most_common(limit)]

    speech = f"You have {len(bookmarks)} bookmarks across {len(domain_counter)} domains."
    return {
        "speech": speech,
        "data": {
            "total_bookmarks": len(bookmarks),
            "unique_urls": len(urls),
            "unique_domains": len(domain_counter),
            "unique_folders": len(folder_counter),
            "explicit_tag_count": len(explicit_tag_counter),
            "bookmarks_with_explicit_tags": with_tags,
            "bookmarks_with_keyword": with_keyword,
            "top_domains": top_domains,
            "top_folders": top_folders,
            "top_explicit_tags": top_tags,
        },
    }


def clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    """Coerce to int and clamp into range."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def main() -> None:
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)

        project_root = Path(__file__).parent.parent.resolve()
        bookmark_file = resolve_bookmark_path(project_root, args.get("file_path"))

        action = str(args.get("action", "search")).strip().lower()
        if action not in {"search", "list_tags", "list_folders", "stats"}:
            raise ValueError("Invalid action. Use: search, list_tags, list_folders, or stats")

        limit = clamp_int(args.get("limit"), DEFAULT_LIMIT, 1, MAX_RESULTS)
        offset = clamp_int(args.get("offset"), 0, 0, 1_000_000)

        sort_by = str(args.get("sort_by", "relevance")).strip().lower()
        if sort_by not in {"relevance", "recent", "title", "domain"}:
            sort_by = "relevance"

        include_duplicates = parse_bool(args.get("include_duplicates"), default=True)

        bookmarks = parse_bookmark_file(bookmark_file)

        if action == "list_tags":
            payload = list_tags(bookmarks, limit=limit)
        elif action == "list_folders":
            payload = list_folders(bookmarks, limit=limit)
        elif action == "stats":
            payload = stats(bookmarks, limit=limit)
        else:
            query = str(args.get("query", "")).strip()
            tag_filters = parse_csv_list(args.get("tags"))
            folder_filters = parse_csv_list(args.get("folders"))
            domain_filters = parse_csv_list(args.get("domains"))

            terms, phrases = parse_query(query)
            raw_mode = args.get("query_mode")
            if raw_mode is None or (isinstance(raw_mode, str) and not str(raw_mode).strip()):
                # Multi-term queries default to AND: "any" + OR matched every youtube.com
                # bookmark when one term was "youtube" (substring of youtube.com).
                search_query_mode = "all" if (len(terms) + len(phrases) > 1) else "any"
            else:
                search_query_mode = str(raw_mode).strip().lower()
                if search_query_mode not in {"any", "all"}:
                    search_query_mode = "all" if (len(terms) + len(phrases) > 1) else "any"

            payload = search_bookmarks(
                bookmarks=bookmarks,
                query=query,
                tag_filters=tag_filters,
                folder_filters=folder_filters,
                domain_filters=domain_filters,
                query_mode=search_query_mode,
                sort_by=sort_by,
                include_duplicates=include_duplicates,
                limit=limit,
                offset=offset,
            )

        result = {
            "ok": True,
            "speech": payload["speech"],
            "data": {
                "bookmark_file": str(bookmark_file),
                **payload["data"],
            },
        }
        print(json.dumps(result))

    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "speech": f"Bookmark tool failed: {error}",
                    "error": str(error),
                }
            )
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
