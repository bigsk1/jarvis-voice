#!/usr/bin/env python3
"""Jarvis skill: public Trakt TV-show discovery and metadata."""

from __future__ import annotations

import json
import math
import os
import re
import sys
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from trakt_movies import (
    TraktAPIError,
    _bounded_text,
    _escape_search_query,
    _normalize_genres,
    _normalize_title,
    _provider_filter_params,
    _range_contains,
    _request_limit_for_filters,
    _safe_float,
    _safe_int,
    _valid_http_url,
)
from trakt_movies import (
    TraktClient as _BaseTraktClient,
)

MAX_REFERENCE_TITLES = 3
USER_AGENT = "JarvisVoice/TraktTVShows-1.0"

ACTION_PATHS = {
    "trending": "/shows/trending",
    "popular": "/shows/popular",
    "anticipated": "/shows/anticipated",
}

GENRE_HINTS: dict[str, tuple[str, ...]] = {
    "action": ("action", "adrenaline", "explosive", "fight", "martial arts"),
    "adventure": ("adventure", "quest", "journey", "epic"),
    "animation": ("animated", "animation", "anime"),
    "comedy": ("comedy", "comic", "funny", "laugh", "lighthearted", "sitcom"),
    "crime": ("crime", "criminal", "gangster", "heist", "mob", "procedural"),
    "documentary": ("documentary", "docuseries", "nonfiction", "true story"),
    "drama": ("drama", "dramatic", "emotional", "character driven"),
    "family": ("family", "family friendly", "kids", "children"),
    "fantasy": ("fantasy", "magical", "magic", "mythical"),
    "history": ("historical", "history", "period piece"),
    "horror": ("horror", "scary", "creepy", "frightening", "spooky"),
    "mystery": ("mystery", "detective", "whodunit", "puzzle"),
    "reality": ("reality", "competition show", "unscripted"),
    "romance": ("romance", "romantic", "love story"),
    "science-fiction": (
        "sci-fi",
        "sci fi",
        "science fiction",
        "space",
        "futuristic",
        "mind-bending",
        "mind bending",
    ),
    "thriller": ("thriller", "suspense", "suspenseful", "tense"),
    "war": ("war", "military", "battlefield"),
    "western": ("western", "cowboy", "frontier"),
}

SOURCE_WEIGHTS = {
    "related": 12.0,
    "streaming": 6.0,
    "trending": 5.0,
    "popular": 3.0,
}


class TraktClient(_BaseTraktClient):
    """Public Trakt client with a TV-specific user agent."""

    def __init__(self, client_id: str, request_func=None) -> None:
        super().__init__(client_id, request_func=request_func)
        self.headers["User-Agent"] = USER_AGENT


def _show_key(show: dict[str, Any]) -> str:
    ids = show.get("ids") if isinstance(show.get("ids"), dict) else {}
    for field in ("trakt", "slug", "imdb", "tmdb", "tvdb"):
        if ids.get(field) not in (None, ""):
            return f"{field}:{ids[field]}"
    return f"title:{_normalize_title(show.get('title'))}:{show.get('year') or ''}"


def normalize_show(item: Any, *, source: str | None = None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    show = item.get("show") if isinstance(item.get("show"), dict) else item
    if not isinstance(show, dict) or not show.get("title"):
        return None

    ids = show.get("ids") if isinstance(show.get("ids"), dict) else {}
    slug = ids.get("slug")
    imdb = ids.get("imdb")
    genres = show.get("genres") if isinstance(show.get("genres"), list) else []
    subgenres = show.get("subgenres") if isinstance(show.get("subgenres"), list) else []
    airs = show.get("airs") if isinstance(show.get("airs"), dict) else None
    normalized: dict[str, Any] = {
        "title": str(show.get("title")),
        "year": _safe_int(show.get("year")),
        "ids": {
            key: ids.get(key)
            for key in ("trakt", "slug", "imdb", "tmdb", "tvdb")
            if ids.get(key) not in (None, "")
        },
        "trakt_url": f"https://trakt.tv/shows/{quote(str(slug), safe='')}" if slug else None,
        "imdb_url": f"https://www.imdb.com/title/{quote(str(imdb), safe='')}/" if imdb else None,
        "overview": str(show.get("overview") or "")[:1800] or None,
        "first_aired": show.get("first_aired"),
        "episode_runtime_minutes": _safe_int(show.get("runtime")),
        "network": show.get("network"),
        "country": show.get("country"),
        "language": show.get("language"),
        "status": show.get("status"),
        "show_type": show.get("type"),
        "aired_episodes": _safe_int(show.get("aired_episodes")),
        "airs": airs,
        "rating": _safe_float(show.get("rating")),
        "votes": _safe_int(show.get("votes")),
        "genres": [str(value) for value in genres[:8] if value],
        "subgenres": [str(value) for value in subgenres[:8] if value],
        "certification": show.get("certification"),
        "trailer_url": _valid_http_url(show.get("trailer")),
        "homepage": _valid_http_url(show.get("homepage")),
        "source_signals": [source] if source else [],
        "external_content_trust": "untrusted",
    }
    for field in ("watchers", "list_count", "rank", "delta", "score"):
        if item.get(field) not in (None, ""):
            normalized[field] = item[field]
    return {key: value for key, value in normalized.items() if value not in (None, "", [], {})}


def normalize_video(item: Any, show_title: str | None = None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    url = _valid_http_url(item.get("url"))
    if not url:
        return None
    return {
        key: value
        for key, value in {
            "show_title": show_title,
            "title": item.get("title") or "Trailer",
            "url": url,
            "site": item.get("site"),
            "type": item.get("type"),
            "official": item.get("official"),
            "published_at": item.get("published_at"),
            "country": item.get("country"),
            "language": item.get("language"),
        }.items()
        if value not in (None, "")
    }


def _genre_phrase_is_negated(text: str, start: int) -> bool:
    prefix = text[max(0, start - 60):start]
    clause = re.split(r"[,.;:]", prefix)[-1]
    if re.search(r"\b(?:no|not|without|exclude|excluding)\b[^,.;:]{0,50}$", clause):
        return True
    return bool(re.search(r"\bnon[-\s]*$", clause))


def _normalized_genre_request(request: str) -> str:
    lowered = re.sub(r"[-_/]+", " ", request.lower())
    return re.sub(r"\s+", " ", lowered)


def _genre_matches(request: str, phrases: tuple[str, ...]) -> list[re.Match[str]]:
    return [
        match
        for phrase in phrases
        for match in re.finditer(
            rf"(?<![a-z0-9]){re.escape(re.sub(r'[-_/]+', ' ', phrase))}(?![a-z0-9])",
            request,
        )
    ]


def _infer_genres(request: str) -> list[str]:
    lowered = _normalized_genre_request(request)
    inferred: list[str] = []
    for genre, phrases in GENRE_HINTS.items():
        matches = _genre_matches(lowered, phrases)
        if matches and any(not _genre_phrase_is_negated(lowered, match.start()) for match in matches):
            inferred.append(genre)
    return inferred[:4]


def _infer_excluded_genres(request: str) -> list[str]:
    lowered = _normalized_genre_request(request)
    excluded: list[str] = []
    for genre, phrases in GENRE_HINTS.items():
        matches = _genre_matches(lowered, phrases)
        if matches and any(_genre_phrase_is_negated(lowered, match.start()) for match in matches):
            excluded.append(genre)
    return excluded[:6]


def _infer_runtime_filter(request: str) -> str | None:
    lowered = request.lower()
    minute_match = re.search(
        r"(?:episodes?\s+)?(?:under|less than|max(?:imum)?(?: of)?)\s+"
        r"(\d{2,3})\s*(?:minutes?|mins?)",
        lowered,
    )
    if minute_match:
        return f"1-{max(10, min(int(minute_match.group(1)), 240))}"
    if re.search(
        r"(?:episodes?\s+)?(?:under|less than|max(?:imum)?(?: of)?)\s+"
        r"(?:an?|one)\s+hours?",
        lowered,
    ):
        return "1-60"
    if any(term in lowered for term in ("short episodes", "quick episodes", "half hour show")):
        return "1-35"
    if "not too long" in lowered:
        return "1-60"
    return None


def _clean_reference_fragment(value: str) -> str:
    cleaned = re.split(
        r"\b(?:but|although|however|tonight|right now|in the mood|mood is|nothing too)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return cleaned.strip(" \t\r\n.;:-\"")


def _is_reference_constraint(value: str) -> bool:
    return bool(
        re.match(
            r"^(?:episodes?|episode\s+(?:length|runtime)|runtime|under|over|"
            r"less\s+than|preferably|completed|finished|ongoing|returning|"
            r"available|streaming|on\s+\w+)\b",
            value.strip(),
            flags=re.IGNORECASE,
        )
    )


def extract_reference_candidates(request: str) -> list[str]:
    candidates: list[str] = []
    for quoted in re.findall(r'["“]([^"”]{1,120})["”]', request):
        cleaned = _clean_reference_fragment(quoted)
        if cleaned:
            candidates.append(cleaned)

    marker = re.search(
        r"\b(?:(?:tv\s+)?(?:shows?|series)\s+)?(?:i\s+)?"
        r"(?:like|liked|love|loved|favorites?(?:\s+(?:shows?|series))?"
        r"(?:\s+are|\s+include)?|similar\s+to)\b\s*[:\-]?\s*(.+)",
        request,
        flags=re.IGNORECASE,
    )
    if marker:
        segment = re.split(r"[;\n]", marker.group(1), maxsplit=1)[0]
        segment = _clean_reference_fragment(segment)
        if segment:
            comma_parts = [_clean_reference_fragment(part) for part in segment.split(",")]
            comma_parts = [part for part in comma_parts if part]
            if len(comma_parts) > 1:
                for part in comma_parts:
                    if _is_reference_constraint(part):
                        break
                    candidates.append(part)
                    and_parts = [
                        _clean_reference_fragment(value)
                        for value in re.split(r"\s+(?:and|&)\s+", part)
                    ]
                    if len(and_parts) > 1:
                        candidates.extend(value for value in and_parts if value)
            else:
                candidates.append(segment)
                and_parts = [
                    _clean_reference_fragment(part)
                    for part in re.split(r"\s+(?:and|&)\s+", segment)
                ]
                if len(and_parts) > 1:
                    candidates.extend(part for part in and_parts if part)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_title(candidate)
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(candidate[:120])
    return deduped[:6]


def _filter_params(
    input_data: dict[str, Any],
    inferred_genres: list[str] | None = None,
    inferred_excluded_genres: list[str] | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    genres = _normalize_genres(input_data.get("genres")) or list(inferred_genres or [])
    excluded_genres = _normalize_genres(input_data.get("exclude_genres"))
    for genre in inferred_excluded_genres or []:
        if genre not in excluded_genres:
            excluded_genres.append(genre)
    genres = [genre for genre in genres if genre not in excluded_genres]
    if genres:
        params["genres"] = ",".join(genres)
    if excluded_genres:
        params["exclude_genres"] = ",".join(excluded_genres)
    for field in ("years", "runtimes", "ratings"):
        value = _bounded_text(input_data.get(field))
        if value:
            params[field] = value
    return params


def _show_matches_filters(show: dict[str, Any], filters: dict[str, Any]) -> bool:
    genres = {str(value).lower() for value in show.get("genres") or []}
    requested_genres = {
        value.strip().lower()
        for value in str(filters.get("genres") or "").split(",")
        if value.strip()
    }
    if requested_genres and not genres.intersection(requested_genres):
        return False
    excluded_genres = {
        value.strip().lower()
        for value in str(filters.get("exclude_genres") or "").split(",")
        if value.strip()
    }
    if excluded_genres and genres.intersection(excluded_genres):
        return False
    if filters.get("years") and not _range_contains(show.get("year"), filters["years"]):
        return False
    if filters.get("runtimes") and not _range_contains(
        show.get("episode_runtime_minutes"), filters["runtimes"]
    ):
        return False
    if filters.get("ratings") and not _range_contains(
        show.get("rating"), filters["ratings"], scale=10.0
    ):
        return False
    return True


def _resolve_reference(client: TraktClient, title: str) -> dict[str, Any] | None:
    rows = client.get(
        "/search/show",
        {
            "query": _escape_search_query(title),
            "fields": "title",
            "limit": 5,
            "extended": "full",
        },
    )
    if not isinstance(rows, list):
        return None
    target = _normalize_title(title)
    best: tuple[float, dict[str, Any]] | None = None
    for row in rows:
        show = normalize_show(row, source="reference")
        if not show:
            continue
        score = SequenceMatcher(None, target, _normalize_title(show.get("title"))).ratio()
        if best is None or score > best[0]:
            best = (score, show)
    if best is None or best[0] < 0.62:
        return None
    best[1]["reference_match_score"] = round(best[0], 3)
    return best[1]


def _merge_candidate(
    candidates: dict[str, dict[str, Any]],
    show: dict[str, Any],
    source: str,
    *,
    related_to: str | None = None,
) -> None:
    key = _show_key(show)
    existing = candidates.get(key)
    if existing is None:
        existing = dict(show)
        existing["source_signals"] = []
        existing["related_to"] = []
        candidates[key] = existing
    if source not in existing["source_signals"]:
        existing["source_signals"].append(source)
    if related_to and related_to not in existing["related_to"]:
        existing["related_to"].append(related_to)


def _candidate_score(show: dict[str, Any], genre_hints: list[str]) -> float:
    score = 0.0
    for signal in show.get("source_signals") or []:
        base_signal = "related" if str(signal).startswith("related:") else str(signal)
        score += SOURCE_WEIGHTS.get(base_signal, 0.0)
    show_genres = {str(value).lower() for value in show.get("genres") or []}
    score += len(show_genres.intersection(genre_hints)) * 2.5
    rating = _safe_float(show.get("rating"))
    votes = _safe_int(show.get("votes")) or 0
    if rating is not None and votes >= 50:
        score += max(0.0, rating - 5.5) * 0.9
    if votes > 0:
        score += min(2.5, math.log10(votes + 1) * 0.5)
    if show.get("trailer_url"):
        score += 0.5
    return round(score, 3)


def _select_videos(rows: Any, show_title: str, limit: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    normalized = [normalize_video(row, show_title=show_title) for row in rows]
    videos = [video for video in normalized if video]
    videos.sort(
        key=lambda video: (
            str(video.get("type", "")).lower() == "trailer",
            video.get("official") is True,
            str(video.get("site", "")).lower() == "youtube",
            video.get("published_at") or "",
        ),
        reverse=True,
    )
    return videos[:limit]


def _recommend(client: TraktClient, input_data: dict[str, Any]) -> dict[str, Any]:
    request = str(input_data.get("request") or input_data.get("query") or "").strip()
    max_results = max(3, min(_safe_int(input_data.get("max_results")) or 8, 15))
    include_videos = input_data.get("include_videos", True) is not False
    video_limit = max(1, min(_safe_int(input_data.get("video_limit")) or 3, 5))
    explicit_references = input_data.get("reference_titles")
    if isinstance(explicit_references, list):
        reference_candidates = [
            str(value).strip()[:120]
            for value in explicit_references
            if str(value).strip()
        ]
    else:
        reference_candidates = []
    if not reference_candidates:
        reference_candidates = extract_reference_candidates(request)

    inferred_excluded_genres = _infer_excluded_genres(request)
    genre_hints = _normalize_genres(input_data.get("genres")) or _infer_genres(request)
    filters = _filter_params(input_data, genre_hints, inferred_excluded_genres)
    excluded_genres = {
        value.strip()
        for value in str(filters.get("exclude_genres") or "").split(",")
        if value.strip()
    }
    genre_hints = [genre for genre in genre_hints if genre not in excluded_genres]
    if not filters.get("runtimes"):
        inferred_runtime = _infer_runtime_filter(request)
        if inferred_runtime:
            filters["runtimes"] = inferred_runtime

    candidates: dict[str, dict[str, Any]] = {}
    resolved_references: list[dict[str, Any]] = []
    warnings: list[str] = []
    sources_queried: list[dict[str, Any]] = []
    period = str(input_data.get("period") or "weekly").strip().lower()
    if period not in {"daily", "weekly", "monthly"}:
        raise TraktAPIError("Streaming period must be daily, weekly, or monthly.")

    for reference_title in reference_candidates:
        if len(resolved_references) >= MAX_REFERENCE_TITLES:
            break
        try:
            reference = _resolve_reference(client, reference_title)
        except TraktAPIError as exc:
            warnings.append(f"Could not resolve reference '{reference_title}': {exc}")
            continue
        if not reference:
            continue
        if any(_show_key(existing) == _show_key(reference) for existing in resolved_references):
            continue
        resolved_references.append(reference)
        slug = reference.get("ids", {}).get("slug") or reference.get("ids", {}).get("trakt")
        if not slug:
            continue
        try:
            rows = client.get(
                f"/shows/{quote(str(slug), safe='')}/related",
                {"limit": max(10, min(max_results * 2, 20)), "extended": "full"},
            )
            result_count = len(rows) if isinstance(rows, list) else 0
            sources_queried.append(
                {
                    "source": "related",
                    "reference": reference.get("title"),
                    "results_count": result_count,
                }
            )
            for row in rows or []:
                show = normalize_show(row, source="related")
                if show:
                    _merge_candidate(
                        candidates,
                        show,
                        f"related:{reference.get('title')}",
                        related_to=str(reference.get("title")),
                    )
        except TraktAPIError as exc:
            warnings.append(f"Related shows for '{reference.get('title')}' were unavailable: {exc}")

    source_limit = max(8, min(max_results * 2, 20))
    discovery_sources = (
        ("trending", "/shows/trending"),
        ("streaming", f"/shows/streaming/{period}"),
        ("popular", "/shows/popular"),
    )
    for source, path in discovery_sources:
        params = {
            "limit": source_limit,
            "extended": "full",
            **_provider_filter_params(filters),
        }
        try:
            rows = client.get(path, params)
        except TraktAPIError as exc:
            warnings.append(f"Trakt {source} candidates were unavailable: {exc}")
            continue
        result_count = len(rows) if isinstance(rows, list) else 0
        sources_queried.append({"source": source, "results_count": result_count})
        for row in rows or []:
            show = normalize_show(row, source=source)
            if show:
                _merge_candidate(candidates, show, source)

    reference_keys = {_show_key(show) for show in resolved_references}
    ranked: list[dict[str, Any]] = []
    for key, show in candidates.items():
        if key in reference_keys or not _show_matches_filters(show, filters):
            continue
        show["match_score"] = _candidate_score(show, genre_hints)
        if "streaming" in (show.get("source_signals") or []):
            show["streaming_signal"] = (
                "Recently ranked in Trakt's streaming list; provider and current "
                "entitlement are not specified."
            )
        ranked.append(show)
    ranked.sort(
        key=lambda show: (
            show.get("match_score") or 0,
            show.get("rating") or 0,
            show.get("votes") or 0,
        ),
        reverse=True,
    )
    ranked = ranked[:max_results]
    if not ranked:
        raise TraktAPIError("Trakt returned no usable TV-show candidates for this request.")

    trailers: list[dict[str, Any]] = []
    if include_videos:
        for show in ranked[:video_limit]:
            slug = show.get("ids", {}).get("slug") or show.get("ids", {}).get("trakt")
            if not slug:
                continue
            try:
                rows = client.get(f"/shows/{quote(str(slug), safe='')}/videos")
            except TraktAPIError as exc:
                warnings.append(f"Videos for '{show.get('title')}' were unavailable: {exc}")
                continue
            show_videos = _select_videos(rows, str(show.get("title")), limit=2)
            if show_videos:
                show["videos"] = show_videos
                show["trailer_url"] = show_videos[0]["url"]
                trailers.extend(show_videos)

    return {
        "action": "recommend",
        "request": request,
        "reference_titles_requested": reference_candidates[:MAX_REFERENCE_TITLES],
        "resolved_references": resolved_references,
        "genre_hints": genre_hints,
        "filters_used": filters,
        "results_count": len(ranked),
        "candidates": ranked,
        "results": ranked,
        "top_results": ranked[:5],
        "top_url": ranked[0].get("trakt_url"),
        "trailers": trailers[: max(3, video_limit * 2)],
        "sources_queried": sources_queried,
        "warnings": warnings,
        "api_requests": client.request_count,
        "oauth_used": False,
        "public_metadata_only": True,
        "streaming_provider_data": "not returned",
        "runtime_scope": "episode",
        "external_content_trust": "untrusted",
        "source": "Trakt API",
    }


def _resolve_show_for_action(
    client: TraktClient,
    show_id: str | None,
    query: str | None,
) -> tuple[str, dict[str, Any] | None]:
    if show_id:
        identifier = show_id.strip()
        details = client.get(f"/shows/{quote(identifier, safe='')}", {"extended": "full"})
        show = normalize_show(details, source="details")
        return identifier, show
    if query:
        show = _resolve_reference(client, query)
        if show:
            identifier = str(show.get("ids", {}).get("slug") or show.get("ids", {}).get("trakt") or "")
            return identifier, show
    raise TraktAPIError("Provide show_id or query for this action.")


def _standard_list_payload(
    action: str,
    query: str,
    results: list[dict[str, Any]],
    client: TraktClient,
) -> dict[str, Any]:
    return {
        "action": action,
        "query": query or None,
        "results_count": len(results),
        "results": results,
        "top_results": results[:5],
        "top_url": results[0].get("trakt_url") if results else None,
        "api_requests": client.request_count,
        "oauth_used": False,
        "public_metadata_only": True,
        "streaming_provider_data": "not returned",
        "runtime_scope": "episode",
        "external_content_trust": "untrusted",
        "source": "Trakt API",
    }


def execute_action(client: TraktClient, input_data: dict[str, Any]) -> dict[str, Any]:
    action = str(input_data.get("action") or "recommend").strip().lower()
    max_results = max(1, min(_safe_int(input_data.get("max_results")) or 10, 20))
    query = str(input_data.get("query") or "").strip()
    show_id = str(input_data.get("show_id") or "").strip()

    if action == "recommend":
        return _recommend(client, input_data)

    if action == "search":
        if not query:
            raise TraktAPIError("Parameter 'query' is required for search.")
        filters = _filter_params(input_data)
        params = {
            "query": _escape_search_query(query),
            "fields": "title,original_title,translations,aliases,overview",
            "limit": _request_limit_for_filters(max_results, filters),
            "extended": "full",
            **_provider_filter_params(filters),
        }
        rows = client.get("/search/show", params)
        results = [show for row in (rows or []) if (show := normalize_show(row, source="search"))]
        results = [show for show in results if _show_matches_filters(show, filters)][:max_results]
        return _standard_list_payload(action, query, results, client)

    if action in ACTION_PATHS or action == "streaming":
        if action == "streaming":
            period = str(input_data.get("period") or "weekly").lower()
            if period not in {"daily", "weekly", "monthly"}:
                raise TraktAPIError("Streaming period must be daily, weekly, or monthly.")
            path = f"/shows/streaming/{period}"
        else:
            path = ACTION_PATHS[action]
        filters = _filter_params(input_data)
        params = {
            "limit": _request_limit_for_filters(max_results, filters),
            "extended": "full",
            **_provider_filter_params(filters),
        }
        rows = client.get(path, params)
        results = [show for row in (rows or []) if (show := normalize_show(row, source=action))]
        results = [show for show in results if _show_matches_filters(show, filters)][:max_results]
        return _standard_list_payload(action, query, results, client)

    if action in {"details", "related", "videos"}:
        identifier, resolved_show = _resolve_show_for_action(client, show_id or None, query or None)
        if action == "details":
            show = resolved_show or {}
            return {
                **_standard_list_payload(action, query or identifier, [show] if show else [], client),
                "show": show,
            }
        if action == "related":
            filters = _filter_params(input_data)
            rows = client.get(
                f"/shows/{quote(identifier, safe='')}/related",
                {
                    "limit": _request_limit_for_filters(max_results, filters),
                    "extended": "full",
                    **_provider_filter_params(filters),
                },
            )
            results = [show for row in (rows or []) if (show := normalize_show(row, source="related"))]
            results = [show for show in results if _show_matches_filters(show, filters)][:max_results]
            payload = _standard_list_payload(action, query or identifier, results, client)
            payload["resolved_show"] = resolved_show
            return payload
        rows = client.get(f"/shows/{quote(identifier, safe='')}/videos")
        title = resolved_show.get("title") if resolved_show else query or identifier
        videos = _select_videos(rows, str(title), max_results)
        return {
            **_standard_list_payload(action, query or identifier, videos, client),
            "show": resolved_show,
            "videos": videos,
            "top_url": videos[0].get("url") if videos else None,
        }

    raise TraktAPIError(f"Unsupported action '{action}'.")


def build_speech(data: dict[str, Any]) -> str:
    action = data.get("action") or "TV show"
    count = _safe_int(data.get("results_count")) or 0
    results = data.get("top_results") if isinstance(data.get("top_results"), list) else []
    top = results[0] if results and isinstance(results[0], dict) else {}
    title = top.get("title") or top.get("show_title")
    if action == "recommend":
        if title:
            return f"Found {count} Trakt TV-show candidate(s). Top source-ranked candidate: {title}."
        return "Trakt did not return a usable TV-show candidate."
    if action == "details" and title:
        return f"Retrieved Trakt TV-show details for {title}."
    if title:
        return f"Found {count} Trakt TV {action} result(s). Top result: {title}."
    return f"Found {count} Trakt TV {action} result(s)."


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False))


def main() -> int:
    try:
        load_config()
        try:
            input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (json.JSONDecodeError, IndexError):
            _print_result({"ok": False, "speech": "Invalid JSON input.", "error": "Invalid JSON input."})
            return 1
        if not isinstance(input_data, dict):
            message = "Input must be a JSON object."
            _print_result({"ok": False, "speech": message, "error": message})
            return 1

        client_id = os.getenv("TRAKT_API_KEY", "").strip()
        if not client_id:
            message = "TRAKT_API_KEY is not configured for the active Jarvis mode."
            _print_result({"ok": False, "speech": message, "error": message})
            return 1

        client = TraktClient(client_id)
        data = execute_action(client, input_data)
        _print_result({"ok": True, "speech": build_speech(data), "data": data})
        return 0
    except TraktAPIError as exc:
        data = {
            key: value
            for key, value in {
                "status_code": exc.status_code,
                "retry_after": exc.retry_after,
                "endpoint": exc.endpoint,
                "source": "Trakt API",
            }.items()
            if value not in (None, "")
        }
        message = str(exc)
        _print_result({"ok": False, "speech": message, "error": message, "data": data})
        return 1
    except Exception as exc:
        message = f"Trakt TV-show tool error: {exc.__class__.__name__}"
        _print_result({"ok": False, "speech": message, "error": message})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
