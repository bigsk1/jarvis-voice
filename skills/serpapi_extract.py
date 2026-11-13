#!/usr/bin/env python3
"""Read public pages, discover feeds, or map/crawl a bounded site with SerpApi."""
from __future__ import annotations

import ipaddress
import json
import math
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from config_loader import load_config
from security_utils import redact_sensitive_text
from serpapi_client import request_serpapi
from stash_helper import SecurityError, validate_url

MAX_RESULT_BYTES = 56 * 1024
MAX_PROVIDER_BYTES = 5 * 1024 * 1024
MAX_LINKS = 20
MAX_FEEDS = 10
_PARAMETERS = {
    "url", "mode", "max_chars", "max_urls", "max_pages", "max_depth",
    "include_subdomains", "include_sitemap", "include_markdown", "include_tags",
    "exclude_tags", "device", "timeout", "no_cache",
}


def _text(value: object, maximum: int) -> str:
    return value[:maximum].strip() if isinstance(value, str) else ""


def _public_url(value: object) -> str:
    """Validate returned references without fetching or resolving every link."""
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return ""
    if any(character.isspace() or ord(character) < 32 for character in value) or "\\" in value:
        return ""
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if (parsed.scheme not in {"http", "https"} or not hostname
                or parsed.username is not None or parsed.password is not None
                or hostname in {"localhost", "localhost.localdomain"}
                or hostname.endswith((".local", ".localhost", ".internal"))):
            return ""
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            return ""
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            return ""
    except ValueError:
        return ""
    return value


def _integer(arguments: dict, name: str, default: int, low: int, high: int) -> int:
    value = arguments.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"'{name}' must be an integer from {low} to {high}.")
    return value


def _boolean(arguments: dict, name: str, default: bool) -> bool:
    value = arguments.get(name, default)
    if type(value) is not bool:
        raise ValueError(f"'{name}' must be true or false.")
    return value


def _page_information(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, limit in (("title", 500), ("description", 2000), ("language", 64)):
        if text := _text(value.get(key), limit):
            result[key] = text
    for key in ("final_url", "canonical", "favicon"):
        if url := _public_url(value.get(key)):
            result[key] = url
    return result


def _references(value: object, *, feeds: bool = False) -> tuple[list[dict], int]:
    if not isinstance(value, list):
        return [], 0
    maximum = MAX_FEEDS if feeds else MAX_LINKS
    rows = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        url = _public_url(item.get("source") if feeds else item.get("link"))
        if not url or url in seen:
            continue
        seen.add(url)
        if len(rows) >= maximum:
            continue
        row: dict[str, Any] = {"url": url, "title": _text(item.get("title"), 300)}
        if feeds:
            row["type"] = _text(item.get("type"), 100)
        elif type(item.get("internal")) is bool:
            row["internal"] = item["internal"]
        rows.append(row)
    return rows, len(seen)


def _page(value: dict, url: str, budget: list[int], include_markdown: bool) -> dict:
    information = _page_information(value.get("page_information"))
    final_url = information.get("final_url") or _public_url(value.get("url")) or url
    original = value.get("markdown") if include_markdown else ""
    original = original if isinstance(original, str) else ""
    content = original[:budget[0]]
    budget[0] -= len(content)
    feeds, feed_count = _references(value.get("feeds"), feeds=True)
    links, link_count = _references(value.get("inline_links"))
    result = {
        "url": final_url, "title": information.get("title", ""),
        "page_information": information, "content": content,
        "content_chars": len(original),
        "content_truncated": len(content) < len(original) or len(original) >= 50000,
        "content_omitted": not include_markdown,
        "feeds": feeds, "feeds_count": len(feeds), "provider_feeds_count": feed_count,
        "feeds_truncated": feed_count > len(feeds),
        "links": links, "links_count": len(links), "provider_links_count": link_count,
        "links_truncated": link_count > len(links),
    }
    error = redact_sensitive_text(_text(value.get("error"), 1000))[:500]
    if error:
        result["error"] = error
    return result


def _encoded_size(data: dict) -> int:
    return len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _bound_result(data: dict) -> None:
    """Bound the actual returned/scanned representation, keeping omissions explicit."""
    while (size := _encoded_size(data)) > MAX_RESULT_BYTES:
        pages = data.get("pages") or [data]
        removed = False
        # Preserve article text before optional link/feed collections. Entries
        # are removed whole and their provider counts remain unchanged.
        for field in ("links", "feeds"):
            for owner in pages:
                rows = owner.get(field)
                if isinstance(rows, list) and rows:
                    rows.pop()
                    owner[field + "_count"] = len(rows)
                    owner[field + "_truncated"] = True
                    removed = True
                    break
            if removed:
                break
        if removed:
            continue
        largest = max(pages, key=lambda page: len(page.get("content", "")))
        if largest.get("content"):
            encoded = largest["content"].encode("utf-8")
            keep = max(0, len(encoded) - (size - MAX_RESULT_BYTES) - 128)
            largest["content"] = encoded[:keep].decode("utf-8", errors="ignore")
            largest["content_truncated"] = True
            continue
        # Long untrusted metadata can also exceed the budget. Remove complete
        # collection entries rather than shortening URLs into different sources.
        for owner in [data]:
            for field in ("urls", "pages"):
                rows = owner.get(field)
                if isinstance(rows, list) and rows:
                    rows.pop()
                    owner[field + "_count"] = len(rows)
                    owner[field + "_truncated"] = True
                    removed = True
                    break
            if removed:
                break
        if not removed:
            raise ValueError("Extract metadata exceeded the returned-content limit.")
    if data.get("pages"):
        data["content_truncated"] = any(page.get("content_truncated") for page in data["pages"])


def extract(arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one bounded request, preserving source identity and extraction limits."""
    if not isinstance(arguments, dict) or set(arguments) - _PARAMETERS:
        raise ValueError("Extract requests require an object with supported settings only.")
    url = arguments.get("url")
    if not _public_url(url):
        raise ValueError("'url' must be a public HTTP(S) URL without credentials or ambiguous characters.")
    try:
        validate_url(url)
    except SecurityError as exc:
        raise ValueError("URL blocked by public-address validation.") from exc
    mode = arguments.get("mode", "scrape")
    if not isinstance(mode, str) or mode not in {"scrape", "map", "crawl"}:
        raise ValueError("'mode' must be scrape, map, or crawl.")
    device = arguments.get("device", "desktop")
    if not isinstance(device, str) or device not in {"desktop", "mobile", "tablet"}:
        raise ValueError("'device' must be desktop, mobile, or tablet.")
    maximum_chars = _integer(arguments, "max_chars", 12000, 1000, 20000)
    maximum_urls = _integer(arguments, "max_urls", 50, 1, 100)
    maximum_pages = _integer(arguments, "max_pages", 3, 1, 10)
    depth = _integer(arguments, "max_depth", 1, 0, 3)
    timeout_ms = _integer(arguments, "timeout", 30000, 1000, 120000)
    markdown = _boolean(arguments, "include_markdown", True)
    subdomains = _boolean(arguments, "include_subdomains", False)
    sitemap = _boolean(arguments, "include_sitemap", True)
    params: dict[str, Any] = {
        "engine": "extract", "url": url, "mode": mode, "device": device,
        "timeout": timeout_ms, "no_cache": _boolean(arguments, "no_cache", False),
    }
    if mode in {"map", "crawl"}:
        params["include_subdomains"] = subdomains
    if mode == "map":
        params["include_sitemap"] = sitemap
    else:
        params["include_markdown"] = markdown
    if mode == "crawl":
        params.update(max_pages=maximum_pages, max_depth=depth)
    for key in ("include_tags", "exclude_tags"):
        if key in arguments:
            value = arguments[key]
            if not isinstance(value, str) or not 1 <= len(value) <= 500:
                raise ValueError(f"'{key}' must be a CSS selector string of 1 to 500 characters.")
            params[key] = value
    # Match SerpApi's documented query tokens, independent of Requests' Python
    # boolean encoding. Keep the callable tool schema's values as JSON booleans.
    params = {key: str(value).lower() if type(value) is bool else value
              for key, value in params.items()}
    try:
        payload = request_serpapi(
            params, timeout=max(45, math.ceil(timeout_ms / 1000) + 15),
            use_proxy=False, fallback_on_proxy_fail=False,
            max_response_bytes=MAX_PROVIDER_BYTES,
        )
    except (RuntimeError, ValueError) as exc:
        # The shared client redacts provider credentials before raising.
        return {"ok": False, "speech": str(exc), "error": str(exc)}
    if not isinstance(payload, dict):
        raise ValueError("SerpApi Extract returned an invalid response.")
    provider_params = payload.get("search_parameters") or {}
    if isinstance(provider_params, dict) and provider_params.get("engine", "extract") != "extract":
        raise ValueError("SerpApi routed this URL to a different engine; use that engine's search tool.")
    metadata = payload.get("search_metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError("SerpApi Extract returned invalid search metadata.")
    if metadata.get("status", "Success") != "Success":
        raise ValueError("SerpApi Extract did not return a completed extraction.")
    data: dict[str, Any] = {
        "provider": "serpapi", "engine": "extract", "mode": mode,
        "requested_url": url, "url": url, "external_content_trust": "untrusted",
        "search_id": _text(metadata.get("id"), 100),
        "javascript_rendered": False,
    }
    credits = metadata.get("credits_consumed")
    if type(credits) in (int, float) and math.isfinite(credits) and credits >= 0:
        data["credits_consumed"] = credits
    budget = [maximum_chars]
    if mode == "scrape":
        data.update(_page(payload, url, budget, markdown))
        if not (data["content"] or data["page_information"] or data["feeds"]):
            raise ValueError("No page content, page information, or feeds were extracted.")
    elif mode == "map":
        rows = payload.get("urls")
        if not isinstance(rows, list):
            raise ValueError("SerpApi Extract did not return a URL map.")
        urls = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            target = _public_url(row.get("url"))
            if not target or target in seen:
                continue
            seen.add(target)
            if len(urls) < maximum_urls:
                urls.append({"url": target, "title": _text(row.get("title"), 500),
                             "source": _text(row.get("source"), 64)})
        data.update(urls=urls, urls_count=len(urls), provider_urls_count=len(seen),
                    urls_truncated=len(seen) > len(urls))
    else:
        rows = payload.get("pages")
        if not isinstance(rows, list) or not rows:
            raise ValueError("SerpApi Extract did not return crawled pages.")
        pages = []
        for row in rows[:maximum_pages]:
            if not isinstance(row, dict) or not (target := _public_url(row.get("url"))):
                continue
            page = _page(row, target, budget, markdown)
            page["depth"] = row.get("depth") if type(row.get("depth")) is int else 0
            pages.append(page)
        if not any(not page.get("error") and (page["content"] or page["page_information"] or page["feeds"]) for page in pages):
            raise ValueError("No crawled page returned usable content or page information.")
        data.update(pages=pages, pages_count=len(pages), provider_pages_count=len(rows),
                    pages_truncated=len(rows) > len(pages), max_pages=maximum_pages, max_depth=depth)
    _bound_result(data)
    if mode == "scrape":
        speech = "SerpApi extracted the page information and requested content."
    elif mode == "map":
        speech = f"SerpApi returned {data['urls_count']} site URLs."
    else:
        speech = f"SerpApi returned {data['pages_count']} crawled pages."
    if any(data.get(field) for field in (
        "content_truncated", "urls_truncated", "pages_truncated", "feeds_truncated", "links_truncated",
    )):
        speech += " Returned content or entries were truncated; use the reported limits when summarizing."
    return {"ok": True, "speech": speech, "data": data}


def main() -> int:
    load_config()
    try:
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        result = extract(arguments)
    except (ValueError, TypeError, OSError) as exc:
        result = {"ok": False, "speech": str(exc), "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
