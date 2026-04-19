#!/usr/bin/env python3
"""
Jarvis Skill: Supa-Crawl-Chat Knowledge

Read-only access to a Supa-Crawl-Chat API instance. This is intentionally
separate from crawl_url: crawl_url fetches live pages, while this searches and
inspects the persistent Supabase/pgvector corpus maintained by Supa-Crawl-Chat.

Chunk lists: use action page_chunks, which calls GET /api/pages/{page_id}/chunks
(all chunk rows for that parent page).

See: https://github.com/bigsk1/supa-crawl-chat
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any
from urllib.parse import urljoin

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import get_config_value, load_config  # noqa: E402


DEFAULT_BASE_URL = "http://localhost:8001"
# Align with Supa-Crawl-Chat OpenAPI (/api/search limit max 100, /api/sites/.../pages max 1000).
MAX_SEARCH_LIMIT = 100
MAX_SITE_PAGES_LIMIT = 1000
MAX_LIST_SITES_RETURN = 100
MAX_CONTENT_CHARS = 20_000
# Search can request up to 50k per result server-side; cap for LLM payloads.
MAX_SEARCH_CONTENT_CHARS = 20_000
# API defaults for full-body truncation (aligned with Supa-Crawl-Chat).
DEFAULT_SEARCH_CONTENT_CHARS = 10_000
DEFAULT_PAGES_LIST_CONTENT_CHARS = 10_000
# Leading markdown preview when include_content=false (API preview_chars, 0–5000).
DEFAULT_PREVIEW_CHARS = 500
MAX_PREVIEW_CHARS = 5000


def supa_api_headers() -> dict[str, str]:
    """
    When Supa-Crawl-Chat has API auth enabled, set SUPA_API_KEY in env.
    Only one header is sent per request (Bearer or X-API-Key), matching the API.

    SUPA_API_KEY_STYLE (optional):
      - bearer (default): Authorization: Bearer <key>
      - x-api-key: X-API-Key: <key>
    """
    key = (get_config_value("SUPA_API_KEY", "") or "").strip()
    if not key:
        return {}
    style = (get_config_value("SUPA_API_KEY_STYLE", "bearer") or "bearer").strip().lower()
    normalized = style.replace("_", "-")
    if normalized in ("x-api-key", "xapikey"):
        return {"X-API-Key": key}
    return {"Authorization": f"Bearer {key}"}


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def parse_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def parse_float(value: Any, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def clean_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("SUPA_CRAWL_CHAT_URL must start with http:// or https://")
    return base_url


def trim_text(value: Any, max_chars: int) -> Any:
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + "...[truncated]"
    return value


def compact_metadata(meta: Any, max_chars: int = 800) -> Any:
    if not isinstance(meta, dict):
        return meta
    raw = json.dumps(meta, ensure_ascii=False)
    if len(raw) <= max_chars:
        return meta
    return trim_text(raw, max_chars)


def compact_result(
    result: dict[str, Any],
    *,
    max_snippet_chars: int = 1200,
    max_summary_chars: int = 1500,
    max_content_chars: int | None = None,
    max_preview_chars: int | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": result.get("id"),
        "site_id": result.get("site_id"),
        "site_name": result.get("site_name"),
        "url": result.get("url"),
        "title": result.get("title"),
        "snippet": trim_text(result.get("snippet"), max_snippet_chars),
        "similarity": result.get("similarity"),
        "context": result.get("context"),
        "is_chunk": result.get("is_chunk"),
        "chunk_index": result.get("chunk_index"),
        "parent_id": result.get("parent_id"),
        "parent_title": result.get("parent_title"),
        "content_length": result.get("content_length"),
        "content_truncated": result.get("content_truncated"),
        "summary": trim_text(result.get("summary"), max_summary_chars),
        "metadata": compact_metadata(result.get("metadata")),
    }
    preview = result.get("content_preview")
    if preview is not None:
        lim = max_preview_chars if max_preview_chars is not None else MAX_PREVIEW_CHARS
        if lim <= 0:
            out["content_preview"] = ""
        else:
            out["content_preview"] = trim_text(preview, lim)
    if max_content_chars is not None and result.get("content") is not None:
        out["content"] = trim_text(result.get("content"), max_content_chars)
    return out


def request_json(base_url: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
    headers = supa_api_headers()
    response = requests.get(
        urljoin(base_url + "/", path.lstrip("/")),
        params={k: v for k, v in (params or {}).items() if v is not None},
        headers=headers,
        timeout=20,
    )
    if response.status_code == 401:
        raise RuntimeError(
            "Supa-Crawl-Chat returned 401. Set SUPA_API_KEY to match the server. "
            "If it uses X-API-Key instead of Bearer, set SUPA_API_KEY_STYLE=x-api-key."
        )
    response.raise_for_status()
    return response.json()


def action_search(base_url: str, input_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    query = str(input_data.get("query", "")).strip()
    if not query:
        raise ValueError("query is required for search")

    limit = parse_int(input_data.get("limit"), 10, minimum=1, maximum=MAX_SEARCH_LIMIT)
    threshold = parse_float(input_data.get("threshold"), 0.3, minimum=0.0, maximum=1.0)
    text_only = parse_bool(input_data.get("text_only"), False)
    site_id = input_data.get("site_id")
    site_id = parse_int(site_id, 0, minimum=1) if site_id is not None else None
    site_name = input_data.get("site_name")
    site_name = str(site_name).strip() if site_name not in (None, "") else None
    after = input_data.get("after")
    after = str(after).strip() if after not in (None, "") else None
    include_content = parse_bool(input_data.get("include_search_content"), False)
    search_content_chars = parse_int(
        input_data.get("search_content_chars"),
        DEFAULT_SEARCH_CONTENT_CHARS,
        minimum=0,
        maximum=MAX_SEARCH_CONTENT_CHARS,
    )
    search_preview_chars = parse_int(
        input_data.get("search_preview_chars"),
        DEFAULT_PREVIEW_CHARS,
        minimum=0,
        maximum=MAX_PREVIEW_CHARS,
    )
    dedupe = parse_bool(input_data.get("dedupe"), True)

    params: dict[str, Any] = {
        "query": query,
        "threshold": threshold,
        "limit": limit,
        "text_only": text_only,
        "site_id": site_id,
        "site_name": site_name,
        "after": after,
        "include_content": include_content,
        "content_chars": search_content_chars,
        "preview_chars": search_preview_chars,
        "dedupe": dedupe,
    }

    payload = request_json(base_url, "/api/search", params)

    results = [
        compact_result(
            item,
            max_content_chars=search_content_chars if include_content else None,
            max_preview_chars=search_preview_chars if not include_content else MAX_PREVIEW_CHARS,
        )
        for item in payload.get("results", [])
    ]
    count = len(results)
    speech = f"Found {count} Supa-Crawl-Chat result{'s' if count != 1 else ''} for '{query}'."
    return speech, {
        "action": "search",
        "query": query,
        "count": count,
        "threshold": payload.get("threshold", threshold),
        "use_embedding": payload.get("use_embedding", not text_only),
        "dedupe": payload.get("dedupe", dedupe),
        "results": results,
    }


def action_list_sites(base_url: str, input_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    include_chunks = parse_bool(input_data.get("include_chunks"), False)
    limit = parse_int(input_data.get("limit"), 50, minimum=1, maximum=MAX_LIST_SITES_RETURN)
    payload = request_json(base_url, "/api/sites", {"include_chunks": include_chunks})
    all_sites = payload.get("sites", [])
    sites = all_sites[:limit]
    for site in sites:
        if isinstance(site, dict):
            site["description"] = trim_text(site.get("description"), 800)
    total = payload.get("count", len(all_sites))
    speech = f"Found {total} crawled site{'s' if total != 1 else ''} in Supa-Crawl-Chat."
    return speech, {
        "action": "list_sites",
        "count": total,
        "returned": len(sites),
        "sites": sites,
    }


def action_site_status(base_url: str, input_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    site_id = parse_int(input_data.get("site_id"), 0, minimum=1)
    if not site_id:
        raise ValueError("site_id is required for site_status")
    payload = request_json(base_url, f"/api/crawl/status/{site_id}")
    speech = (
        f"Site {site_id} has {payload.get('page_count', 0)} pages "
        f"and {payload.get('chunk_count', 0)} chunks."
    )
    return speech, {"action": "site_status", "site": payload}


def action_site_pages(base_url: str, input_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    site_id = parse_int(input_data.get("site_id"), 0, minimum=1)
    if not site_id:
        raise ValueError("site_id is required for site_pages")
    limit = parse_int(input_data.get("limit"), 20, minimum=1, maximum=MAX_SITE_PAGES_LIMIT)
    offset = parse_int(input_data.get("pages_offset"), 0, minimum=0, maximum=100_000)
    include_chunks = parse_bool(input_data.get("include_chunks"), False)
    include_content = parse_bool(input_data.get("include_pages_content"), False)
    list_content_chars = parse_int(
        input_data.get("pages_list_content_chars"),
        DEFAULT_PAGES_LIST_CONTENT_CHARS,
        minimum=0,
        maximum=20_000,
    )
    pages_preview_chars = parse_int(
        input_data.get("pages_preview_chars"),
        DEFAULT_PREVIEW_CHARS,
        minimum=0,
        maximum=MAX_PREVIEW_CHARS,
    )
    payload = request_json(base_url, f"/api/sites/{site_id}/pages", {
        "include_chunks": include_chunks,
        "limit": limit,
        "offset": offset,
        "include_content": include_content,
        "content_chars": list_content_chars,
        "preview_chars": pages_preview_chars,
    })
    pages = payload.get("pages", [])
    if not include_content:
        for p in pages:
            if isinstance(p, dict):
                p.pop("content", None)
    else:
        for p in pages:
            if isinstance(p, dict) and p.get("content") is not None:
                p["content"] = trim_text(p.get("content"), list_content_chars)
    speech = f"Found {len(pages)} page{'s' if len(pages) != 1 else ''} for site {site_id}."
    return speech, {
        "action": "site_pages",
        "site_id": site_id,
        "site_name": payload.get("site_name"),
        "count": payload.get("count", len(pages)),
        "offset": offset,
        "pages": pages,
    }


def action_site(base_url: str, input_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    site_id = parse_int(input_data.get("site_id"), 0, minimum=1)
    if not site_id:
        raise ValueError("site_id is required for site")
    payload = request_json(base_url, f"/api/sites/{site_id}")
    if isinstance(payload, dict):
        payload["description"] = trim_text(payload.get("description"), 1200)
    name = payload.get("name") if isinstance(payload, dict) else None
    speech = f"Retrieved site {site_id}: {name or 'unknown'}."
    return speech, {"action": "site", "site": payload}


def action_health(base_url: str, input_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    payload = request_json(base_url, "/api/health")
    sites = payload.get("site_count", 0)
    speech = f"Supa-Crawl-Chat is up with {sites} site{'s' if sites != 1 else ''} indexed."
    return speech, {"action": "health", "health": payload}


def action_crawl_activity(base_url: str, input_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    payload = request_json(base_url, "/api/crawl/activity")
    sites = payload.get("sites") if isinstance(payload, dict) else None
    n = len(sites) if isinstance(sites, list) else 0
    total = payload.get("count", n) if isinstance(payload, dict) else n
    speech = f"Crawl activity board: {total} site{'s' if total != 1 else ''}."
    return speech, {"action": "crawl_activity", "activity": payload}


def action_page(base_url: str, input_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    page_id = parse_int(input_data.get("page_id"), 0, minimum=1)
    if not page_id:
        raise ValueError("page_id is required for page")
    content_chars = parse_int(input_data.get("content_chars"), 8000, minimum=1000, maximum=MAX_CONTENT_CHARS)
    payload = request_json(base_url, f"/api/pages/{page_id}")
    if not payload:
        raise ValueError(f"Page {page_id} was not found")
    payload["content"] = trim_text(payload.get("content"), content_chars)
    speech = f"Retrieved page {page_id}: {payload.get('title') or payload.get('url') or 'untitled'}."
    return speech, {"action": "page", "page": payload}


def action_page_chunks(base_url: str, input_data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    page_id = parse_int(input_data.get("page_id"), 0, minimum=1)
    if not page_id:
        raise ValueError("page_id is required for page_chunks")
    content_chars = parse_int(input_data.get("content_chars"), 4000, minimum=1000, maximum=MAX_CONTENT_CHARS)
    payload = request_json(base_url, f"/api/pages/{page_id}/chunks")
    chunks = payload if isinstance(payload, list) else []
    for chunk in chunks:
        if isinstance(chunk, dict):
            chunk["content"] = trim_text(chunk.get("content"), content_chars)
    speech = f"Retrieved {len(chunks)} chunk{'s' if len(chunks) != 1 else ''} for page {page_id}."
    return speech, {"action": "page_chunks", "page_id": page_id, "chunks": chunks, "count": len(chunks)}


def main() -> int:
    load_config()

    try:
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return_error("Invalid JSON input")
        return 1

    try:
        base_url = clean_base_url(
            str(input_data.get("base_url") or get_config_value("SUPA_CRAWL_CHAT_URL", DEFAULT_BASE_URL))
        )
        action = str(input_data.get("action", "search")).strip().lower()

        actions = {
            "search": action_search,
            "list_sites": action_list_sites,
            "site": action_site,
            "site_status": action_site_status,
            "site_pages": action_site_pages,
            "page": action_page,
            "page_chunks": action_page_chunks,
            "health": action_health,
            "crawl_activity": action_crawl_activity,
        }
        if action not in actions:
            raise ValueError(f"Unsupported action '{action}'")

        speech, data = actions[action](base_url, input_data)
        data["base_url"] = base_url
        return_success(speech, data)
        return 0
    except requests.Timeout:
        return_error("Supa-Crawl-Chat request timed out")
        return 1
    except requests.RequestException as exc:
        return_error(f"Supa-Crawl-Chat request failed: {exc}")
        return 1
    except Exception as exc:
        return_error(str(exc))
        return 1


def return_success(speech: str, data: dict[str, Any] | None = None) -> None:
    result = {"ok": True, "speech": speech}
    if data is not None:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech: str, data: dict[str, Any] | None = None) -> None:
    result = {"ok": False, "speech": speech, "error": speech}
    if data is not None:
        result["data"] = data
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main())
