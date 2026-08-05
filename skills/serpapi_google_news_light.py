#!/usr/bin/env python3
"""Jarvis Skill: fast, structured Google News search through SerpApi."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from config_loader import load_config
from serpapi_client import (
    clamp_results_count,
    get_proxy_enabled,
    merge_extra_params,
    parse_bool,
    request_serpapi,
)


GOOGLE_NEWS_LIGHT_TIMEOUT = 90
DEFAULT_MAX_RESULTS = 10
DEFAULT_MAX_TOP_STORY_GROUPS = 5
DEFAULT_MAX_STORIES_PER_GROUP = 5
LOCALE_RE = re.compile(r"^[a-z]{2}$")
LANGUAGE_RESTRICT_RE = re.compile(r"^lang_[a-z]{2}(?:\|lang_[a-z]{2})*$")
DOMAIN_RE = re.compile(r"^[a-z0-9.-]+$")
RESERVED_KEYS = {
    "engine",
    "api_key",
    "output",
    "async",
    "zero_trace",
    "json_restrictor",
    "q",
    "location",
    "uule",
    "google_domain",
    "gl",
    "hl",
    "lr",
    "safe",
    "nfpr",
    "filter",
    "start",
    "device",
    "no_cache",
}


def return_success(speech: str, data: dict[str, Any]) -> None:
    print(json.dumps({"ok": True, "speech": speech, "data": data}))


def return_error(speech: str) -> None:
    print(json.dumps({"ok": False, "speech": speech, "error": speech}))


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _compact_text(value: Any, maximum: int = 1200) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        return None
    if len(text) <= maximum:
        return text
    return text[: maximum - 3].rstrip() + "..."


def _bounded_int(
    value: Any,
    label: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'{label}' must be an integer from {minimum} to {maximum}.") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"'{label}' must be from {minimum} to {maximum}.")
    return number


def normalize_safe(value: Any) -> str:
    safe = str(value or "active").strip().lower()
    if safe not in {"active", "off"}:
        raise ValueError("'safe' must be active or off.")
    return safe


def normalize_device(value: Any) -> str:
    device = str(value or "desktop").strip().lower()
    if device not in {"desktop", "tablet", "mobile"}:
        raise ValueError("'device' must be desktop, tablet, or mobile.")
    return device


def normalize_locale(value: Any, label: str) -> str | None:
    locale = str(value or "").strip().lower()
    if not locale:
        return None
    if not LOCALE_RE.fullmatch(locale):
        raise ValueError(f"'{label}' must be a two-letter code such as us or en.")
    return locale


def normalize_google_domain(value: Any) -> str:
    domain = str(value or "google.com").strip().lower()
    if len(domain) > 100 or not DOMAIN_RE.fullmatch(domain) or ".." in domain:
        raise ValueError("'google_domain' must be a Google domain such as google.com or google.co.uk.")
    return domain


def normalize_language_restrict(value: Any) -> str | None:
    language_restrict = str(value or "").strip().lower()
    if not language_restrict:
        return None
    if not LANGUAGE_RESTRICT_RE.fullmatch(language_restrict):
        raise ValueError("'language_restrict' must use values such as lang_en or lang_fr|lang_de.")
    return language_restrict


def parse_start(value: Any) -> int:
    return _bounded_int(value, "start", default=0, minimum=0, maximum=1000)


def extract_news_results(
    payload: dict[str, Any],
    *,
    max_results: int,
) -> tuple[list[dict[str, Any]], int]:
    raw_results = _dict_list(payload.get("news_results"))
    results: list[dict[str, Any]] = []
    for fallback_position, item in enumerate(raw_results, 1):
        title = _compact_text(item.get("title"), 500)
        url = str(item.get("link") or item.get("url") or "").strip()
        if not title and not url:
            continue
        results.append({
            key: value
            for key, value in {
                "position": item.get("position") or fallback_position,
                "title": title,
                "url": url or None,
                "source": _compact_text(item.get("source"), 200),
                "thumbnail": item.get("thumbnail"),
                "snippet": _compact_text(item.get("snippet")),
                "date": _compact_text(item.get("date"), 200),
            }.items()
            if value not in (None, "")
        })
        if len(results) >= max_results:
            break
    return results, len(raw_results)


def extract_top_stories(
    payload: dict[str, Any],
    *,
    max_groups: int,
    max_stories_per_group: int,
) -> tuple[list[dict[str, Any]], int, int]:
    raw_groups = _dict_list(payload.get("top_stories"))
    groups: list[dict[str, Any]] = []
    provider_article_count = sum(
        len(_dict_list(group.get("stories"))) for group in raw_groups
    )
    for group_position, group in enumerate(raw_groups, 1):
        raw_stories = _dict_list(group.get("stories"))
        stories: list[dict[str, Any]] = []
        for story_position, story in enumerate(raw_stories, 1):
            title = _compact_text(story.get("title"), 500)
            url = str(story.get("link") or story.get("url") or "").strip()
            if not title and not url:
                continue
            stories.append({
                key: value
                for key, value in {
                    "position": story_position,
                    "title": title,
                    "url": url or None,
                    "source": _compact_text(story.get("source"), 200),
                    "date": _compact_text(story.get("date"), 200),
                }.items()
                if value not in (None, "")
            })
            if len(stories) >= max_stories_per_group:
                break
        title = _compact_text(group.get("title"), 500)
        if not title and not stories:
            continue
        groups.append({
            "position": group_position,
            "title": title or f"Top stories group {group_position}",
            "stories_count": len(stories),
            "provider_stories_count": len(raw_stories),
            "stories": stories,
        })
        if len(groups) >= max_groups:
            break
    return groups, len(raw_groups), provider_article_count


def _search_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("search_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        key: metadata[key]
        for key in (
            "id",
            "status",
            "created_at",
            "processed_at",
            "total_time_taken",
            "cached",
            "google_news_light_url",
        )
        if metadata.get(key) not in (None, "")
    }


def _pagination_start(value: Any) -> int | None:
    if not value:
        return None
    try:
        raw_start = parse_qs(urlparse(str(value)).query).get("start", [None])[0]
        return int(raw_start) if raw_start is not None else None
    except (TypeError, ValueError):
        return None


def extract_pagination(payload: dict[str, Any], *, start: int) -> dict[str, Any]:
    pagination = payload.get("serpapi_pagination")
    pagination = pagination if isinstance(pagination, dict) else {}
    next_start = _pagination_start(pagination.get("next"))
    previous_start = _pagination_start(pagination.get("previous"))
    return {
        key: value
        for key, value in {
            "current": pagination.get("current"),
            "start": start,
            "has_more": next_start is not None,
            "next_start": next_start,
            "previous_start": previous_start,
        }.items()
        if value not in (None, "") or key == "has_more"
    }


def _google_news_light_request(params: dict[str, Any]) -> dict[str, Any]:
    # The shared client stays proxy-capable. proxy_policy=off keeps normal calls
    # direct while allowing a later manifest-only policy change.
    return request_serpapi(
        params,
        timeout=GOOGLE_NEWS_LIGHT_TIMEOUT,
        use_proxy=True,
        fallback_on_proxy_fail=True,
    )


def build_speech(
    query: str,
    results: list[dict[str, Any]],
    top_stories: list[dict[str, Any]],
) -> str:
    story_count = sum(len(group.get("stories") or []) for group in top_stories)
    if not results and not story_count:
        return f"Google News Light returned no news results for '{query}'."
    parts = [f"Found {len(results)} Google News result(s) for '{query}'"]
    if story_count:
        parts.append(f"plus {story_count} article(s) in grouped Top Stories")
    first_story = next(
        (
            story
            for group in top_stories
            for story in (group.get("stories") or [])
            if isinstance(story, dict)
        ),
        {},
    )
    top_title = results[0].get("title") if results else first_story.get("title")
    return f"{' '.join(parts)}. Top result: {top_title}."


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            return_error("Invalid JSON input")
            return 1

        query = " ".join(str(input_data.get("query") or "").split())
        if not query:
            raise ValueError("'query' is required.")
        if len(query) > 500:
            raise ValueError("'query' must be 500 characters or fewer.")

        location = _compact_text(input_data.get("location"), 200)
        uule = str(input_data.get("uule") or "").strip()
        if len(uule) > 500:
            raise ValueError("'uule' must be 500 characters or fewer.")
        if location and uule:
            raise ValueError("'location' and 'uule' cannot be used together.")

        google_domain = normalize_google_domain(input_data.get("google_domain"))
        country = normalize_locale(input_data.get("country"), "country")
        language = normalize_locale(input_data.get("language"), "language")
        language_restrict = normalize_language_restrict(input_data.get("language_restrict"))
        safe = normalize_safe(input_data.get("safe"))
        device = normalize_device(input_data.get("device"))
        start = parse_start(input_data.get("start"))
        exclude_autocorrected = parse_bool(input_data.get("exclude_autocorrected", False))
        filter_similar = parse_bool(input_data.get("filter_similar", True))
        no_cache = parse_bool(input_data.get("no_cache", False))
        include_raw = parse_bool(input_data.get("include_raw", False))
        max_results = clamp_results_count(
            input_data.get("max_results", DEFAULT_MAX_RESULTS),
            default=DEFAULT_MAX_RESULTS,
            maximum=20,
        )
        max_top_story_groups = _bounded_int(
            input_data.get("max_top_story_groups"),
            "max_top_story_groups",
            default=DEFAULT_MAX_TOP_STORY_GROUPS,
            minimum=1,
            maximum=10,
        )
        max_stories_per_group = _bounded_int(
            input_data.get("max_stories_per_group"),
            "max_stories_per_group",
            default=DEFAULT_MAX_STORIES_PER_GROUP,
            minimum=1,
            maximum=10,
        )
        extra_params = input_data.get("extra_params", {})
        if extra_params is None:
            extra_params = {}
        if not isinstance(extra_params, dict):
            raise ValueError("'extra_params' must be an object.")

        params: dict[str, Any] = {
            "engine": "google_news_light",
            "q": query,
            "google_domain": google_domain,
            "safe": safe,
            "nfpr": "1" if exclude_autocorrected else "0",
            "filter": "1" if filter_similar else "0",
            "start": start,
            "device": device,
            "no_cache": "true" if no_cache else "false",
        }
        for key, value in (
            ("location", location),
            ("uule", uule),
            ("gl", country),
            ("hl", language),
            ("lr", language_restrict),
        ):
            if value:
                params[key] = value
        merge_extra_params(params, extra_params, reserved_keys=RESERVED_KEYS)

        payload = _google_news_light_request(params)
        results, provider_results_count = extract_news_results(
            payload,
            max_results=max_results,
        )
        top_stories, provider_top_story_groups_count, provider_top_story_articles_count = (
            extract_top_stories(
                payload,
                max_groups=max_top_story_groups,
                max_stories_per_group=max_stories_per_group,
            )
        )
        top_story_articles_count = sum(
            len(group.get("stories") or []) for group in top_stories
        )
        metadata = _search_metadata(payload)
        search_information = payload.get("search_information")
        search_information = search_information if isinstance(search_information, dict) else {}
        pagination = extract_pagination(payload, start=start)
        first_story = next(
            (
                story
                for group in top_stories
                for story in (group.get("stories") or [])
                if isinstance(story, dict)
            ),
            None,
        )

        data: dict[str, Any] = {
            "engine": "google_news_light",
            "query": query,
            "query_displayed": search_information.get("query_displayed"),
            "news_results_state": search_information.get("news_results_state"),
            "location": location,
            "country": country,
            "language": language,
            "language_restrict": language_restrict,
            "google_domain": google_domain,
            "safe": safe,
            "exclude_autocorrected": exclude_autocorrected,
            "filter_similar": filter_similar,
            "device": device,
            "start": start,
            "max_results": max_results,
            "results_count": len(results),
            "provider_results_count": provider_results_count,
            "results": results,
            "top_results": results[:5],
            "top_stories_count": len(top_stories),
            "provider_top_story_groups_count": provider_top_story_groups_count,
            "top_story_articles_count": top_story_articles_count,
            "provider_top_story_articles_count": provider_top_story_articles_count,
            "top_stories": top_stories,
            "top_url": (
                results[0].get("url")
                if results
                else first_story.get("url") if first_story else None
            ),
            "pagination": pagination,
            "has_more": pagination.get("has_more", False),
            "next_start": pagination.get("next_start"),
            "search_id": metadata.get("id"),
            "search_metadata": metadata,
            "google_news_light_url": metadata.get("google_news_light_url"),
            "serpapi_searches_used": 1,
            "proxy_enabled": get_proxy_enabled(),
            "source": "SerpApi Google News Light",
        }
        data = {key: value for key, value in data.items() if value not in (None, "")}
        if include_raw:
            data["raw"] = payload

        return_success(build_speech(query, results, top_stories), data)
        return 0
    except ValueError as exc:
        return_error(str(exc))
        return 1
    except Exception as exc:
        message = str(exc)
        if "timeout" in message.lower() or "timed out" in message.lower():
            return_error("SerpApi Google News Light request timed out.")
            return 1
        return_error(f"SerpApi Google News Light error: {message}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
