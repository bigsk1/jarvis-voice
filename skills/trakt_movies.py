#!/usr/bin/env python3
"""Jarvis skill: public Trakt movie discovery and metadata."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections.abc import Callable
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from http_client import http_request


API_BASE_URL = "https://api.trakt.tv"
USER_AGENT = "JarvisVoice/TraktMovies-1.0"
DEFAULT_TIMEOUT_SECONDS = 15
MAX_REFERENCE_TITLES = 3

ACTION_PATHS = {
    "trending": "/movies/trending",
    "popular": "/movies/popular",
    "anticipated": "/movies/anticipated",
    "boxoffice": "/movies/boxoffice",
}

GENRE_HINTS: dict[str, tuple[str, ...]] = {
    "action": ("action", "adrenaline", "explosive", "fight", "martial arts"),
    "adventure": ("adventure", "quest", "journey", "epic"),
    "animation": ("animated", "animation", "anime"),
    "comedy": ("comedy", "comic", "funny", "laugh", "lighthearted", "silly"),
    "crime": ("crime", "criminal", "gangster", "heist", "mob"),
    "documentary": ("documentary", "nonfiction", "real story", "true story"),
    "drama": ("drama", "dramatic", "emotional", "tearjerker"),
    "family": ("family", "family friendly", "kids", "children"),
    "fantasy": ("fantasy", "magical", "magic", "mythical"),
    "history": ("historical", "history", "period piece"),
    "horror": ("horror", "scary", "creepy", "frightening", "spooky"),
    "mystery": ("mystery", "detective", "whodunit", "puzzle"),
    "romance": ("romance", "romantic", "date night", "love story"),
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


class TraktAPIError(RuntimeError):
    """Structured Trakt API failure without credential details."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: int | None = None,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.endpoint = endpoint


class TraktClient:
    """Small fixed-origin client for public Trakt GET endpoints."""

    def __init__(
        self,
        client_id: str,
        request_func: Callable[..., requests.Response] | None = None,
    ) -> None:
        self.request_func = request_func or http_request
        self.headers = {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "trakt-api-version": "2",
            "trakt-api-key": client_id,
        }
        self.request_count = 0

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not path.startswith("/") or "://" in path:
            raise TraktAPIError("Invalid Trakt endpoint path.")

        endpoint = path.split("?", 1)[0]
        url = f"{API_BASE_URL}{path}"
        last_error: Exception | None = None
        for attempt in range(2):
            self.request_count += 1
            try:
                response = self.request_func(
                    "GET",
                    url,
                    headers=self.headers,
                    params=params or {},
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                    use_proxy=True,
                    fallback_on_proxy_fail=True,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.2)
                    continue
                raise TraktAPIError(
                    f"Trakt request failed: {exc.__class__.__name__}",
                    endpoint=endpoint,
                ) from exc

            if response.status_code == 204:
                return None
            if response.status_code == 429:
                retry_after = _safe_int(response.headers.get("Retry-After"))
                if attempt == 0 and retry_after is not None and retry_after <= 2:
                    time.sleep(max(0, retry_after))
                    continue
                raise TraktAPIError(
                    "Trakt rate limit reached.",
                    status_code=429,
                    retry_after=retry_after,
                    endpoint=endpoint,
                )
            if response.status_code >= 500 and attempt == 0:
                time.sleep(0.25)
                continue
            if not response.ok:
                message = _response_error_message(response)
                raise TraktAPIError(
                    message,
                    status_code=response.status_code,
                    endpoint=endpoint,
                )
            try:
                return response.json()
            except ValueError as exc:
                raise TraktAPIError(
                    "Trakt returned an invalid JSON response.",
                    status_code=response.status_code,
                    endpoint=endpoint,
                ) from exc

        raise TraktAPIError(
            f"Trakt request failed: {last_error.__class__.__name__ if last_error else 'unknown error'}",
            endpoint=endpoint,
        )


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _response_error_message(response: requests.Response) -> str:
    message = f"Trakt API returned HTTP {response.status_code}."
    try:
        payload = response.json()
    except ValueError:
        return message
    if isinstance(payload, dict):
        detail = payload.get("error_description") or payload.get("error") or payload.get("message")
        if detail:
            return f"{message} {str(detail)[:300]}"
    return message


def _valid_http_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if text.startswith("https://") or text.startswith("http://"):
        return text
    return None


def _normalize_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _escape_search_query(value: str) -> str:
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:/])', r"\\\1", value.strip())


def _movie_key(movie: dict[str, Any]) -> str:
    ids = movie.get("ids") if isinstance(movie.get("ids"), dict) else {}
    for field in ("trakt", "slug", "imdb", "tmdb"):
        if ids.get(field) not in (None, ""):
            return f"{field}:{ids[field]}"
    return f"title:{_normalize_title(movie.get('title'))}:{movie.get('year') or ''}"


def normalize_movie(item: Any, *, source: str | None = None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    movie = item.get("movie") if isinstance(item.get("movie"), dict) else item
    if not isinstance(movie, dict) or not movie.get("title"):
        return None

    ids = movie.get("ids") if isinstance(movie.get("ids"), dict) else {}
    slug = ids.get("slug")
    imdb = ids.get("imdb")
    genres = movie.get("genres") if isinstance(movie.get("genres"), list) else []
    subgenres = movie.get("subgenres") if isinstance(movie.get("subgenres"), list) else []
    normalized: dict[str, Any] = {
        "title": str(movie.get("title")),
        "year": _safe_int(movie.get("year")),
        "ids": {
            key: ids.get(key)
            for key in ("trakt", "slug", "imdb", "tmdb")
            if ids.get(key) not in (None, "")
        },
        "trakt_url": f"https://trakt.tv/movies/{quote(str(slug), safe='')}" if slug else None,
        "imdb_url": f"https://www.imdb.com/title/{quote(str(imdb), safe='')}/" if imdb else None,
        "tagline": str(movie.get("tagline") or "")[:400] or None,
        "overview": str(movie.get("overview") or "")[:1800] or None,
        "released": movie.get("released"),
        "runtime_minutes": _safe_int(movie.get("runtime")),
        "country": movie.get("country"),
        "language": movie.get("language"),
        "status": movie.get("status"),
        "rating": _safe_float(movie.get("rating")),
        "votes": _safe_int(movie.get("votes")),
        "genres": [str(value) for value in genres[:8] if value],
        "subgenres": [str(value) for value in subgenres[:8] if value],
        "certification": movie.get("certification"),
        "trailer_url": _valid_http_url(movie.get("trailer")),
        "homepage": _valid_http_url(movie.get("homepage")),
        "source_signals": [source] if source else [],
        "external_content_trust": "untrusted",
    }
    for field in ("watchers", "list_count", "rank", "delta", "revenue", "score"):
        if item.get(field) not in (None, ""):
            normalized[field] = item[field]
    return {key: value for key, value in normalized.items() if value not in (None, "", [], {})}


def normalize_video(item: Any, movie_title: str | None = None) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    url = _valid_http_url(item.get("url"))
    if not url:
        return None
    return {
        key: value
        for key, value in {
            "movie_title": movie_title,
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


def _infer_genres(request: str) -> list[str]:
    lowered = request.lower()
    return [
        genre
        for genre, phrases in GENRE_HINTS.items()
        if any(phrase in lowered for phrase in phrases)
    ][:4]


def _infer_runtime_filter(request: str) -> str | None:
    lowered = request.lower()
    minute_match = re.search(
        r"(?:under|less than|max(?:imum)?(?: of)?)\s+(\d{2,3})\s*(?:minutes?|mins?)",
        lowered,
    )
    if minute_match:
        return f"1-{max(30, min(int(minute_match.group(1)), 300))}"
    hour_match = re.search(r"(?:under|less than|max(?:imum)?(?: of)?)\s+(\d(?:\.\d+)?)\s*hours?", lowered)
    if hour_match:
        minutes = int(float(hour_match.group(1)) * 60)
        return f"1-{max(30, min(minutes, 300))}"
    if any(term in lowered for term in ("short movie", "something short", "quick watch")):
        return "1-105"
    if "not too long" in lowered:
        return "1-120"
    return None


def _clean_reference_fragment(value: str) -> str:
    cleaned = re.split(
        r"\b(?:but|although|however|tonight|right now|in the mood|mood is|nothing too)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return cleaned.strip(" \t\r\n.;:-\"")


def extract_reference_candidates(request: str) -> list[str]:
    candidates: list[str] = []
    for quoted in re.findall(r'["“]([^"”]{1,120})["”]', request):
        cleaned = _clean_reference_fragment(quoted)
        if cleaned:
            candidates.append(cleaned)

    marker = re.search(
        r"\b(?:movies?\s+)?(?:i\s+)?"
        r"(?:like|liked|love|loved|favorites?(?:\s+movies?)?"
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
                candidates.extend(comma_parts)
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


def _normalize_genres(value: Any) -> list[str]:
    if isinstance(value, str):
        raw = value.split(",")
    elif isinstance(value, list):
        raw = value
    else:
        return []
    genres = []
    for item in raw:
        genre = re.sub(r"[^a-z0-9-]+", "-", str(item).strip().lower()).strip("-")
        if genre and genre not in genres:
            genres.append(genre)
    return genres[:6]


def _bounded_text(value: Any, maximum: int = 100) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:maximum]


def _filter_params(input_data: dict[str, Any], inferred_genres: list[str] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    genres = _normalize_genres(input_data.get("genres")) or list(inferred_genres or [])
    if genres:
        params["genres"] = ",".join(genres)
    for field in ("years", "runtimes", "ratings"):
        value = _bounded_text(input_data.get(field))
        if value:
            params[field] = value
    return params


def _provider_filter_params(filters: dict[str, Any]) -> dict[str, Any]:
    """Use the provider-side filter proven stable across current public lists."""
    return {"genres": filters["genres"]} if filters.get("genres") else {}


def _request_limit_for_filters(max_results: int, filters: dict[str, Any]) -> int:
    """Over-fetch a bounded pool when filters must be enforced locally."""
    if any(filters.get(field) for field in ("years", "runtimes", "ratings")):
        return min(20, max_results * 3)
    return max_results


def _range_contains(value: float | int | None, range_text: Any, *, scale: float = 1.0) -> bool:
    if value is None:
        return False
    text = str(range_text or "").strip()
    if not text:
        return True
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:-\s*(\d+(?:\.\d+)?))?\s*", text)
    if not match:
        return True
    lower = float(match.group(1)) / scale
    upper = float(match.group(2)) / scale if match.group(2) else lower
    return lower <= float(value) <= upper


def _movie_matches_filters(movie: dict[str, Any], filters: dict[str, Any]) -> bool:
    genres = {str(value).lower() for value in movie.get("genres") or []}
    requested_genres = {
        value.strip().lower()
        for value in str(filters.get("genres") or "").split(",")
        if value.strip()
    }
    if requested_genres and not genres.intersection(requested_genres):
        return False
    if filters.get("years") and not _range_contains(movie.get("year"), filters["years"]):
        return False
    if filters.get("runtimes") and not _range_contains(movie.get("runtime_minutes"), filters["runtimes"]):
        return False
    # Trakt's filter contract uses a 0..100 percentage while movie metadata is 0..10.
    if filters.get("ratings") and not _range_contains(movie.get("rating"), filters["ratings"], scale=10.0):
        return False
    return True


def _resolve_reference(client: TraktClient, title: str) -> dict[str, Any] | None:
    rows = client.get(
        "/search/movie",
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
        movie = normalize_movie(row, source="reference")
        if not movie:
            continue
        score = SequenceMatcher(None, target, _normalize_title(movie.get("title"))).ratio()
        if best is None or score > best[0]:
            best = (score, movie)
    if best is None or best[0] < 0.62:
        return None
    best[1]["reference_match_score"] = round(best[0], 3)
    return best[1]


def _merge_candidate(
    candidates: dict[str, dict[str, Any]],
    movie: dict[str, Any],
    source: str,
    *,
    related_to: str | None = None,
) -> None:
    key = _movie_key(movie)
    existing = candidates.get(key)
    if existing is None:
        existing = dict(movie)
        existing["source_signals"] = []
        existing["related_to"] = []
        candidates[key] = existing
    if source not in existing["source_signals"]:
        existing["source_signals"].append(source)
    if related_to and related_to not in existing["related_to"]:
        existing["related_to"].append(related_to)


def _candidate_score(movie: dict[str, Any], genre_hints: list[str]) -> float:
    score = 0.0
    for signal in movie.get("source_signals") or []:
        base_signal = "related" if str(signal).startswith("related:") else str(signal)
        score += SOURCE_WEIGHTS.get(base_signal, 0.0)
    movie_genres = {str(value).lower() for value in movie.get("genres") or []}
    score += len(movie_genres.intersection(genre_hints)) * 2.5
    rating = _safe_float(movie.get("rating"))
    votes = _safe_int(movie.get("votes")) or 0
    if rating is not None and votes >= 50:
        score += max(0.0, rating - 5.5) * 0.9
    if votes > 0:
        score += min(2.5, math.log10(votes + 1) * 0.5)
    if movie.get("trailer_url"):
        score += 0.5
    return round(score, 3)


def _select_videos(rows: Any, movie_title: str, limit: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    normalized = [normalize_video(row, movie_title=movie_title) for row in rows]
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

    genre_hints = _normalize_genres(input_data.get("genres")) or _infer_genres(request)
    filters = _filter_params(input_data, genre_hints)
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
        if any(_movie_key(existing) == _movie_key(reference) for existing in resolved_references):
            continue
        resolved_references.append(reference)
        slug = reference.get("ids", {}).get("slug") or reference.get("ids", {}).get("trakt")
        if not slug:
            continue
        try:
            rows = client.get(
                f"/movies/{quote(str(slug), safe='')}/related",
                {"limit": max(10, min(max_results * 2, 20)), "extended": "full"},
            )
            result_count = len(rows) if isinstance(rows, list) else 0
            sources_queried.append({
                "source": "related",
                "reference": reference.get("title"),
                "results_count": result_count,
            })
            for row in rows or []:
                movie = normalize_movie(row, source="related")
                if movie:
                    _merge_candidate(
                        candidates,
                        movie,
                        f"related:{reference.get('title')}",
                        related_to=str(reference.get("title")),
                    )
        except TraktAPIError as exc:
            warnings.append(f"Related movies for '{reference.get('title')}' were unavailable: {exc}")

    source_limit = max(8, min(max_results * 2, 20))
    discovery_sources = (
        ("trending", "/movies/trending", {}),
        ("streaming", f"/movies/streaming/{period}", {}),
        ("popular", "/movies/popular", {}),
    )
    for source, path, extra_params in discovery_sources:
        params = {
            "limit": source_limit,
            "extended": "full",
            **_provider_filter_params(filters),
            **extra_params,
        }
        try:
            rows = client.get(path, params)
        except TraktAPIError as exc:
            warnings.append(f"Trakt {source} candidates were unavailable: {exc}")
            continue
        result_count = len(rows) if isinstance(rows, list) else 0
        sources_queried.append({"source": source, "results_count": result_count})
        for row in rows or []:
            movie = normalize_movie(row, source=source)
            if movie:
                _merge_candidate(candidates, movie, source)

    reference_keys = {_movie_key(movie) for movie in resolved_references}
    ranked: list[dict[str, Any]] = []
    for key, movie in candidates.items():
        if key in reference_keys:
            continue
        if not _movie_matches_filters(movie, filters):
            continue
        movie["match_score"] = _candidate_score(movie, genre_hints)
        if "streaming" in (movie.get("source_signals") or []):
            movie["streaming_signal"] = (
                "Recently ranked in Trakt's streaming list; provider and current "
                "entitlement are not specified."
            )
        ranked.append(movie)
    ranked.sort(
        key=lambda movie: (
            movie.get("match_score") or 0,
            movie.get("rating") or 0,
            movie.get("votes") or 0,
        ),
        reverse=True,
    )
    ranked = ranked[:max_results]
    if not ranked:
        raise TraktAPIError("Trakt returned no usable movie candidates for this request.")

    trailers: list[dict[str, Any]] = []
    if include_videos:
        for movie in ranked[:video_limit]:
            slug = movie.get("ids", {}).get("slug") or movie.get("ids", {}).get("trakt")
            if not slug:
                continue
            try:
                rows = client.get(f"/movies/{quote(str(slug), safe='')}/videos")
            except TraktAPIError as exc:
                warnings.append(f"Videos for '{movie.get('title')}' were unavailable: {exc}")
                continue
            movie_videos = _select_videos(rows, str(movie.get("title")), limit=2)
            if movie_videos:
                movie["videos"] = movie_videos
                movie["trailer_url"] = movie_videos[0]["url"]
                trailers.extend(movie_videos)

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
        "external_content_trust": "untrusted",
        "source": "Trakt API",
    }


def _resolve_movie_for_action(
    client: TraktClient,
    movie_id: str | None,
    query: str | None,
) -> tuple[str, dict[str, Any] | None]:
    if movie_id:
        identifier = movie_id.strip()
        details = client.get(f"/movies/{quote(identifier, safe='')}", {"extended": "full"})
        movie = normalize_movie(details, source="details")
        return identifier, movie
    if query:
        movie = _resolve_reference(client, query)
        if movie:
            identifier = str(movie.get("ids", {}).get("slug") or movie.get("ids", {}).get("trakt") or "")
            return identifier, movie
    raise TraktAPIError("Provide movie_id or query for this action.")


def execute_action(client: TraktClient, input_data: dict[str, Any]) -> dict[str, Any]:
    action = str(input_data.get("action") or "recommend").strip().lower()
    max_results = max(1, min(_safe_int(input_data.get("max_results")) or 10, 20))
    query = str(input_data.get("query") or "").strip()
    movie_id = str(input_data.get("movie_id") or "").strip()

    if action == "recommend":
        return _recommend(client, input_data)

    if action == "search":
        if not query:
            raise TraktAPIError("Parameter 'query' is required for search.")
        filters = _filter_params(input_data)
        params = {
            "query": _escape_search_query(query),
            "fields": "title,original_title,translations,aliases,tagline,overview",
            "limit": _request_limit_for_filters(max_results, filters),
            "extended": "full",
            **_provider_filter_params(filters),
        }
        rows = client.get("/search/movie", params)
        results = [movie for row in (rows or []) if (movie := normalize_movie(row, source="search"))]
        results = [movie for movie in results if _movie_matches_filters(movie, filters)]
        results = results[:max_results]
        return _standard_list_payload(action, query, results, client)

    if action in ACTION_PATHS or action == "streaming":
        if action == "streaming":
            period = str(input_data.get("period") or "weekly").lower()
            if period not in {"daily", "weekly", "monthly"}:
                raise TraktAPIError("Streaming period must be daily, weekly, or monthly.")
            path = f"/movies/streaming/{period}"
        else:
            path = ACTION_PATHS[action]
        filters = _filter_params(input_data)
        params = {
            "limit": _request_limit_for_filters(max_results, filters),
            "extended": "full",
            **_provider_filter_params(filters),
        }
        rows = client.get(path, params)
        results = [movie for row in (rows or []) if (movie := normalize_movie(row, source=action))]
        results = [movie for movie in results if _movie_matches_filters(movie, filters)]
        results = results[:max_results]
        return _standard_list_payload(action, query, results, client)

    if action in {"details", "related", "videos"}:
        identifier, resolved_movie = _resolve_movie_for_action(client, movie_id or None, query or None)
        if action == "details":
            movie = resolved_movie or {}
            return {
                "action": action,
                "movie": movie,
                "results_count": 1 if movie else 0,
                "results": [movie] if movie else [],
                "top_results": [movie] if movie else [],
                "top_url": movie.get("trakt_url"),
                "api_requests": client.request_count,
                "oauth_used": False,
                "public_metadata_only": True,
                "external_content_trust": "untrusted",
                "source": "Trakt API",
            }
        if action == "related":
            filters = _filter_params(input_data)
            rows = client.get(
                f"/movies/{quote(identifier, safe='')}/related",
                {
                    "limit": _request_limit_for_filters(max_results, filters),
                    "extended": "full",
                    **_provider_filter_params(filters),
                },
            )
            results = [movie for row in (rows or []) if (movie := normalize_movie(row, source="related"))]
            results = [movie for movie in results if _movie_matches_filters(movie, filters)]
            results = results[:max_results]
            payload = _standard_list_payload(action, query or identifier, results, client)
            payload["resolved_movie"] = resolved_movie
            return payload
        rows = client.get(f"/movies/{quote(identifier, safe='')}/videos")
        title = resolved_movie.get("title") if resolved_movie else query or identifier
        videos = _select_videos(rows, str(title), max_results)
        return {
            "action": action,
            "movie": resolved_movie,
            "results_count": len(videos),
            "videos": videos,
            "results": videos,
            "top_results": videos[:5],
            "top_url": videos[0].get("url") if videos else None,
            "api_requests": client.request_count,
            "oauth_used": False,
            "public_metadata_only": True,
            "external_content_trust": "untrusted",
            "source": "Trakt API",
        }

    raise TraktAPIError(f"Unsupported action '{action}'.")


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
        "external_content_trust": "untrusted",
        "source": "Trakt API",
    }


def build_speech(data: dict[str, Any]) -> str:
    action = data.get("action") or "movie"
    count = _safe_int(data.get("results_count")) or 0
    results = data.get("top_results") if isinstance(data.get("top_results"), list) else []
    top = results[0] if results and isinstance(results[0], dict) else {}
    title = top.get("title") or top.get("movie_title")
    if action == "recommend":
        if title:
            return f"Found {count} Trakt movie-night candidate(s). Top source-ranked candidate: {title}."
        return "Trakt did not return a usable movie-night candidate."
    if action == "details" and title:
        return f"Retrieved Trakt details for {title}."
    if title:
        return f"Found {count} Trakt {action} result(s). Top result: {title}."
    return f"Found {count} Trakt {action} result(s)."


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
            _print_result(
                {
                    "ok": False,
                    "speech": "Input must be a JSON object.",
                    "error": "Input must be a JSON object.",
                }
            )
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
        message = f"Trakt movie tool error: {exc.__class__.__name__}"
        _print_result({"ok": False, "speech": message, "error": message})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
