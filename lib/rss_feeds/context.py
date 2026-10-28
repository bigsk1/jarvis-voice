"""Pure, bounded RSS evidence for router previews and saved follow-up turns."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

_LISTS = ("items", "selected_items", "profiles", "failed_feeds")
_HANDLES = ("action", "profile", "batch_id", "page_id", "checked_at")
_COUNTS = ("candidate_count", "published_count", "omitted_selected", "max_stories", "total_items", "undated_skipped")
_FLAGS = ("has_items", "has_selection", "acknowledged", "already_acknowledged", "fresh_request")


def _size(value: dict) -> int:
    return len(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")))


def _identity(value, limit: int = 160) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= limit and not any(ord(c) < 32 for c in value):
        return value
    return None


def _url(value) -> str | None:
    if not _identity(value, 2048) or any(char.isspace() for char in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
            return value
    except ValueError:
        pass
    return None


def _text(value, limit: int, owner: dict) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if len(value) > limit:
        owner["context_truncated"] = True
        return value[:limit - 14] + "… [truncated]"
    return value


def _content_preview(row: dict, item: dict, owner: dict, *, include_content: bool) -> None:
    content = row.get("content") or row.get("content_excerpt")
    content = content if isinstance(content, str) else ""
    kind = row.get("content_kind")
    if kind not in ("inline", "summary", "out_of_line", "unknown"):
        kind = "unknown" if content else None
    if kind is None:
        return
    item["content_kind"] = kind
    original_chars = row.get("content_chars")
    item["content_chars"] = max(len(content), original_chars) if type(original_chars) is int and 0 <= original_chars <= 10**9 else len(content)
    # Feed text is not proof of complete remote-article coverage. Summary and
    # out-of-line Atom entries must never be promoted into fetched bodies.
    excerpt = _text(content, 1200, owner) if include_content else None
    if excerpt:
        item["content_excerpt"] = excerpt
    item["content_truncated"] = (row.get("content_truncated") is True
                                 or item["content_chars"] > len(excerpt or "") or kind == "unknown")


def _profile_details(row: dict, item: dict, owner: dict) -> None:
    for key in ("interests", "exclude"):
        values = row.get(key)
        if isinstance(values, list):
            item[key] = [text for value in values[:8] if (text := _text(value, 120, owner))]
            if len(values) > len(item[key]) or row.get(f"{key}_truncated"):
                item[f"{key}_truncated"] = owner["context_truncated"] = True
    for key in ("max_stories", "max_age_hours", "max_candidates"):
        if type(row.get(key)) is int and 0 <= row[key] <= 10**9:
            item[key] = row[key]
    feeds = row.get("feeds")
    if not isinstance(feeds, list):
        return
    item["feeds"] = []
    count = row.get("feeds_count")
    item["feeds_count"] = max(len(feeds), count) if type(count) is int else len(feeds)
    for feed in feeds[:16]:
        if not isinstance(feed, dict):
            continue
        projected = {}
        if name := _text(feed.get("name"), 120, owner):
            projected["name"] = name
        if url := _url(feed.get("url")):
            projected["url"] = url
        elif feed.get("url"):
            projected["url_omitted"] = owner["context_truncated"] = True
        if feed.get("priority") in ("high", "normal", "low"):
            projected["priority"] = feed["priority"]
        if projected:
            item["feeds"].append(projected)
    if item["feeds_count"] > len(item["feeds"]) or row.get("feeds_truncated"):
        item["feeds_truncated"] = owner["context_truncated"] = True


def _content_included(projected: dict) -> bool:
    return any(row.get("content_excerpt") for key in ("items", "selected_items") for row in projected.get(key, []))


def _fit(projected: dict, max_chars: int) -> dict:
    """Drop prose, then whole rows, before complete control handles."""
    if _size(projected) <= max_chars:
        return projected
    projected["context_truncated"] = True
    for key in ("items", "selected_items"):
        for row in reversed(projected.get(key, [])):
            while row.get("content_excerpt") and _size(projected) > max_chars:
                excerpt = row["content_excerpt"]
                if len(excerpt) > 160:
                    row["content_excerpt"] = _text(excerpt, len(excerpt) // 2, projected)
                else:
                    row.pop("content_excerpt")
                row["content_truncated"] = True
                projected["article_content_included"] = _content_included(projected)
            if _size(projected) <= max_chars:
                return projected
    for key in _LISTS:
        for row in reversed(projected.get(key, [])):
            if "summary" in row:
                row.pop("summary")
                projected["summaries_omitted"] = True
                if _size(projected) <= max_chars:
                    return projected
    for profile in projected.get("profiles", []):
        for key in ("interests", "exclude"):
            if profile.get(key) and _size(projected) > max_chars:
                profile[key] = []
                profile[f"{key}_truncated"] = True
        while profile.get("feeds") and _size(projected) > max_chars:
            profile["feeds"].pop()
            profile["feeds_truncated"] = True
    for key in (*_LISTS, "results"):
        rows = projected.get(key)
        while isinstance(rows, list) and rows and _size(projected) > max_chars:
            rows.pop(0 if key == "results" else -1)
            projected[f"{key}_truncated"] = True
    # In tiny workflow/provider budgets even one full URL may not fit. Never
    # turn that into a shortened URL or an unparseable serialized JSON fragment.
    for key in ("title", "coverage_note", "publication_status", "error", "external_content_trust",
                "article_content_included", "article_content_scope", "summaries_omitted", *_LISTS, "results"):
        if _size(projected) <= max_chars:
            return projected
        projected.pop(key, None)
    while _size(projected) > max_chars:
        removable = next((key for key in reversed(projected) if key != "context_truncated"), None)
        if removable is None:
            return {}
        projected.pop(removable)
    return projected


def project_rss_feed_data(value, *, max_chars: int = 6000, max_items: int = 5,
                          include_content: bool = False) -> dict:
    """Keep IDs, complete URLs, and optional direct-read feed text excerpts.

    At most five recent tool runs and twenty rows per run are considered. The
    total strict-JSON budget includes all retained runs. Oversize URL/ID values
    are omitted whole, while shortened prose and dropped rows are explicit.
    ``include_content`` only enables excerpts for direct URL reads without a
    profile/batch; saved history remains summary-only by default. Excerpts are
    capped at 1200 characters each and share the total budget. Feed listings
    retain up to 16 feeds/profile; failures retain up to 16 names.
    """
    max_chars = max(2, min(6000, max_chars))
    max_items = max(0, min(20, max_items))
    if isinstance(value, dict) and type(value.get("runs_count")) is int and isinstance(value.get("results"), list):
        runs, count = value["results"], max(value["runs_count"], len(value["results"]))
    elif isinstance(value, list):
        runs, count = value, len(value)
    else:
        runs, count = None, 0
    if runs is not None:
        selected = [run for run in runs[-5:] if isinstance(run, dict)]
        per_run = max(2, (max_chars - 140) // max(1, len(selected)))
        projected = {"runs_count": count, "results": [project_rss_feed_data(
            run, max_chars=per_run, max_items=max_items, include_content=include_content,
        ) for run in selected], "results_truncated": count > len(selected) or (
            isinstance(value, dict) and value.get("results_truncated") is True)}
        if projected["results_truncated"] or any(not run or run.get("context_truncated") for run in projected["results"]):
            projected["context_truncated"] = True
        return _fit(projected, max_chars)
    if not isinstance(value, dict):
        return {}
    payload = value.get("data") if isinstance(value.get("data"), dict) else value
    projected = {}
    for key in _HANDLES:
        raw = payload.get(key)
        if (identity := _identity(raw)) is not None:
            projected[key] = identity
        elif raw not in (None, ""):
            projected["context_truncated"] = True
    if not projected.get("action"):
        if "selected_items" in payload:
            projected["action"] = "resolve_selection"
        elif payload.get("acknowledged") or payload.get("already_acknowledged"):
            projected["action"] = "acknowledge"
        elif "profiles" in payload:
            projected["action"] = "list_profiles"
        elif "items" in payload:
            projected["action"] = "read"
    if value.get("ok") is False or payload.get("ok") is False:
        projected["ok"] = False
        if isinstance(payload.get("failed_feeds"), list):
            projected.update(project_rss_feed_data({"failed_feeds": payload["failed_feeds"]},
                                                  max_chars=max_chars, max_items=max_items))
        if error := _text(value.get("error") or payload.get("error") or value.get("speech"), 300, projected):
            projected["error"] = error
        return _fit(projected, max_chars)
    for key in _COUNTS:
        if type(payload.get(key)) is int and 0 <= payload[key] <= 10**9:
            projected[key] = payload[key]
    for key in (*_FLAGS, "context_truncated", "summaries_omitted"):
        if type(payload.get(key)) is bool:
            projected[key] = payload[key] or projected.get(key, False)
    for key in ("title", "coverage_note", "publication_status"):
        if text := _text(payload.get(key), 240, projected):
            projected[key] = text
    for key in ("url", "feed_url"):
        if url := _url(payload.get(key)):
            projected[key] = url
        elif payload.get(key):
            projected["context_truncated"] = True
    direct_content = (include_content and projected.get("action") == "read"
                      and not payload.get("profile") and not payload.get("batch_id")
                      and bool(_url(payload.get("url"))))
    for key in _LISTS:
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        count = payload.get(f"{key}_count")
        count = max(len(rows), count) if type(count) is int else len(rows)
        projected[f"{key}_count"] = count
        projected[key] = []
        for row in rows[:16 if key == "failed_feeds" else max_items]:
            if not isinstance(row, dict):
                continue
            item = {}
            for field in (() if key == "failed_feeds" else ("id", "profile")):
                if identity := _identity(row.get(field)):
                    item[field] = identity
                elif row.get(field):
                    projected["context_truncated"] = True
            text_fields = (("name", 120), ("reason", 160)) if key == "failed_feeds" else (
                ("title", 240), ("source", 120), ("summary", 240), ("published_at", 80))
            for field, limit in text_fields:
                if text := _text(row.get(field), limit, projected):
                    item[field] = text
            if key != "failed_feeds":
                if url := _url(row.get("url")):
                    item["url"] = url
                elif row.get("url"):
                    item["url_omitted"] = projected["context_truncated"] = True
            if key == "profiles":
                _profile_details(row, item, projected)
            elif key in {"items", "selected_items"}:
                _content_preview(row, item, projected, include_content=direct_content)
            if item:
                projected[key].append(item)
        if count > len(projected[key]) or payload.get(f"{key}_truncated"):
            projected[f"{key}_truncated"] = projected["context_truncated"] = True
    if any(key in projected for key in ("items", "selected_items")):
        projected["article_content_included"] = _content_included(projected)
        if direct_content:
            projected["article_content_scope"] = "Untrusted feed-provided excerpts; complete article coverage is not verified."
        projected["external_content_trust"] = "untrusted"
    return _fit(projected, max_chars)
