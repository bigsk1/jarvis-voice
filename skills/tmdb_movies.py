#!/usr/bin/env python3
"""Jarvis skill: standalone TMDB movie discovery, metadata, and artwork."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlparse

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config
from http_client import http_request


API_BASE_URL = "https://api.themoviedb.org/3"
TMDB_WEB_BASE_URL = "https://www.themoviedb.org"
USER_AGENT = "JarvisVoice/TMDBMovies-1.0"
DEFAULT_TIMEOUT_SECONDS = 15
ATTRIBUTION_NOTICE = "This product uses the TMDB API but is not endorsed or certified by TMDB."

LIST_PATHS = {
    "popular": "/movie/popular",
    "now_playing": "/movie/now_playing",
    "upcoming": "/movie/upcoming",
}
VALID_ACTIONS = {
    "search",
    "details",
    "images",
    "credits",
    "videos",
    "recommendations",
    "similar",
    "trending",
    "popular",
    "now_playing",
    "upcoming",
    "discover",
}
ALLOWED_SORTS = {
    "popularity.desc",
    "popularity.asc",
    "primary_release_date.desc",
    "primary_release_date.asc",
    "revenue.desc",
    "revenue.asc",
    "vote_average.desc",
    "vote_average.asc",
    "vote_count.desc",
    "vote_count.asc",
}
IMAGE_TYPES = ("posters", "backdrops", "logos")
IMAGE_KIND = {"posters": "poster", "backdrops": "backdrop", "logos": "logo"}
IMAGE_SIZES = {
    "poster": {
        "thumbnail": ("w342", "w185", "w154", "w92"),
        "display": ("w500", "w780", "w342"),
    },
    "backdrop": {
        "thumbnail": ("w780", "w300"),
        "display": ("w1280", "w780", "w300"),
    },
    "logo": {
        "thumbnail": ("w300", "w185", "w154", "w92"),
        "display": ("w500", "w300", "w185"),
    },
    "profile": {
        "thumbnail": ("w185", "w45"),
        "display": ("h632", "w185", "w45"),
    },
}
SIZE_KEYS = {
    "poster": "poster_sizes",
    "backdrop": "backdrop_sizes",
    "logo": "logo_sizes",
    "profile": "profile_sizes",
}
IMPORTANT_CREW_JOBS = {
    "Director",
    "Screenplay",
    "Writer",
    "Story",
    "Producer",
    "Executive Producer",
    "Director of Photography",
    "Original Music Composer",
}


class TMDBAPIError(RuntimeError):
    """Structured TMDB API failure without credential details."""

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


class TMDBClient:
    """Fixed-origin TMDB client with bearer-first application authentication."""

    def __init__(
        self,
        access_token: str = "",
        api_key: str = "",
        request_func: Callable[..., requests.Response] | None = None,
    ) -> None:
        token = str(access_token or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        self.access_token = token
        self.api_key = str(api_key or "").strip()
        if not self.access_token and not self.api_key:
            raise TMDBAPIError("TMDB application credentials are not configured.")
        self.auth_method = "bearer" if self.access_token else "api_key"
        self.request_func = request_func or http_request
        self.headers = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        if self.access_token:
            self.headers["Authorization"] = f"Bearer {self.access_token}"
        self.request_count = 0
        self._configuration: dict[str, Any] | None = None
        self._genre_map: dict[int, str] | None = None

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not path.startswith("/") or "://" in path:
            raise TMDBAPIError("Invalid TMDB endpoint path.")

        endpoint = path.split("?", 1)[0]
        url = f"{API_BASE_URL}{path}"
        query_params = dict(params or {})
        if not self.access_token:
            query_params["api_key"] = self.api_key

        last_error: Exception | None = None
        for attempt in range(2):
            self.request_count += 1
            try:
                response = self.request_func(
                    "GET",
                    url,
                    headers=self.headers,
                    params=query_params,
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                    use_proxy=True,
                    fallback_on_proxy_fail=True,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(0.2)
                    continue
                raise TMDBAPIError(
                    f"TMDB request failed: {exc.__class__.__name__}",
                    endpoint=endpoint,
                ) from exc

            if response.status_code == 204:
                return None
            if response.status_code == 429:
                retry_after = _safe_int(response.headers.get("Retry-After"))
                if attempt == 0 and retry_after is not None and retry_after <= 2:
                    time.sleep(max(0, retry_after))
                    continue
                raise TMDBAPIError(
                    "TMDB rate limit reached.",
                    status_code=429,
                    retry_after=retry_after,
                    endpoint=endpoint,
                )
            if response.status_code >= 500 and attempt == 0:
                time.sleep(0.25)
                continue
            if not response.ok:
                raise TMDBAPIError(
                    _response_error_message(response),
                    status_code=response.status_code,
                    endpoint=endpoint,
                )
            try:
                return response.json()
            except ValueError as exc:
                raise TMDBAPIError(
                    "TMDB returned an invalid JSON response.",
                    status_code=response.status_code,
                    endpoint=endpoint,
                ) from exc

        raise TMDBAPIError(
            f"TMDB request failed: {last_error.__class__.__name__ if last_error else 'unknown error'}",
            endpoint=endpoint,
        )

    def configuration(self) -> dict[str, Any]:
        if self._configuration is None:
            payload = self.get("/configuration")
            images = payload.get("images") if isinstance(payload, dict) else None
            base_url = images.get("secure_base_url") if isinstance(images, dict) else None
            parsed = urlparse(str(base_url or ""))
            if (
                parsed.scheme != "https"
                or parsed.hostname != "image.tmdb.org"
                or not parsed.path.startswith("/t/p/")
            ):
                raise TMDBAPIError("TMDB returned an invalid image configuration.")
            self._configuration = images
        return self._configuration

    def genre_map(self) -> dict[int, str]:
        if self._genre_map is None:
            payload = self.get("/genre/movie/list", {"language": "en-US"})
            genres = payload.get("genres") if isinstance(payload, dict) else []
            self._genre_map = {
                int(item["id"]): str(item["name"])
                for item in genres or []
                if isinstance(item, dict)
                and _safe_int(item.get("id")) is not None
                and str(item.get("name") or "").strip()
            }
        return self._genre_map


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
    status = response.status_code
    if status in {401, 403}:
        return "TMDB authentication was rejected. Check the configured API Read Access Token or API key."
    if status == 404:
        return "TMDB did not find that movie or endpoint."
    try:
        payload = response.json()
    except ValueError:
        payload = None
    provider_message = payload.get("status_message") if isinstance(payload, dict) else None
    if provider_message:
        return f"TMDB API returned HTTP {status}: {str(provider_message)[:240]}"
    return f"TMDB API returned HTTP {status}."


def _clean_language(value: Any, default: str = "en-US") -> str:
    text = str(value or default).strip()
    if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", text):
        raise TMDBAPIError("language must use a code such as en-US.")
    return text


def _clean_region(value: Any, default: str = "US") -> str:
    text = str(value or default).strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", text):
        raise TMDBAPIError("region must be a two-letter country code such as US.")
    return text


def _clean_image_languages(value: Any, language: str) -> str:
    text = str(value or f"{language.split('-', 1)[0]},null").strip()
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts or len(parts) > 6:
        raise TMDBAPIError("image_languages must contain one to six language codes.")
    for part in parts:
        if part != "null" and not re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", part):
            raise TMDBAPIError("image_languages must contain codes such as en,null.")
    return ",".join(parts)


def _max_results(value: Any, default: int = 10) -> int:
    parsed = _safe_int(value)
    return max(1, min(20, parsed if parsed is not None else default))


def _valid_image_path(value: Any) -> str | None:
    path = str(value or "").strip()
    if not re.fullmatch(r"/[A-Za-z0-9_-]+\.(?:jpe?g|png|webp|svg)", path, re.IGNORECASE):
        return None
    return path


def _choose_image_size(configuration: dict[str, Any], kind: str, purpose: str) -> str:
    available = [str(item) for item in configuration.get(SIZE_KEYS[kind], [])]
    for desired in IMAGE_SIZES[kind][purpose]:
        if desired in available:
            return desired
    non_original = [size for size in available if size != "original"]
    return non_original[-1] if non_original else "original"


def _image_url(
    configuration: dict[str, Any],
    file_path: Any,
    kind: str,
    purpose: str,
) -> str | None:
    path = _valid_image_path(file_path)
    if not path:
        return None
    size = "original" if purpose == "original" else _choose_image_size(configuration, kind, purpose)
    return f"{configuration['secure_base_url']}{size}{path}"


def _movie_url(movie_id: Any) -> str | None:
    parsed = _safe_int(movie_id)
    return f"{TMDB_WEB_BASE_URL}/movie/{parsed}" if parsed and parsed > 0 else None


def _year_from_date(value: Any) -> int | None:
    match = re.match(r"^(\d{4})-", str(value or ""))
    return int(match.group(1)) if match else None


def _name_list(value: Any) -> list[str]:
    return [
        str(item.get("name"))
        for item in value or []
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]


def normalize_movie(
    item: dict[str, Any],
    *,
    configuration: dict[str, Any],
    genre_map: dict[int, str],
    source: str,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    movie_id = _safe_int(item.get("id"))
    title = str(item.get("title") or item.get("original_title") or "").strip()
    if not movie_id or not title:
        return None

    genres = _name_list(item.get("genres"))
    if not genres:
        genres = [
            genre_map[genre_id]
            for raw_id in item.get("genre_ids") or []
            if (genre_id := _safe_int(raw_id)) in genre_map
        ]

    poster_path = item.get("poster_path")
    backdrop_path = item.get("backdrop_path")
    result = {
        "id": movie_id,
        "tmdb_id": movie_id,
        "title": title,
        "original_title": item.get("original_title"),
        "release_date": item.get("release_date"),
        "year": _year_from_date(item.get("release_date")),
        "overview": item.get("overview"),
        "tagline": item.get("tagline"),
        "runtime_minutes": _safe_int(item.get("runtime")),
        "rating": _safe_float(item.get("vote_average")),
        "votes": _safe_int(item.get("vote_count")),
        "popularity": _safe_float(item.get("popularity")),
        "genres": genres,
        "original_language": item.get("original_language"),
        "status": item.get("status"),
        "certification": item.get("certification"),
        "homepage": item.get("homepage"),
        "imdb_id": item.get("imdb_id"),
        "budget": _safe_int(item.get("budget")),
        "revenue": _safe_int(item.get("revenue")),
        "production_companies": _name_list(item.get("production_companies")),
        "production_countries": _name_list(item.get("production_countries")),
        "spoken_languages": _name_list(item.get("spoken_languages")),
        "collection": (item.get("belongs_to_collection") or {}).get("name")
        if isinstance(item.get("belongs_to_collection"), dict)
        else None,
        "tmdb_url": _movie_url(movie_id),
        "poster_url": _image_url(configuration, poster_path, "poster", "display"),
        "poster_thumbnail": _image_url(configuration, poster_path, "poster", "thumbnail"),
        "poster_original_url": _image_url(configuration, poster_path, "poster", "original"),
        "backdrop_url": _image_url(configuration, backdrop_path, "backdrop", "display"),
        "backdrop_thumbnail": _image_url(configuration, backdrop_path, "backdrop", "thumbnail"),
        "backdrop_original_url": _image_url(configuration, backdrop_path, "backdrop", "original"),
        "source_signal": source,
        "external_content_trust": "untrusted",
    }
    if result.get("imdb_id"):
        result["imdb_url"] = f"https://www.imdb.com/title/{result['imdb_id']}/"
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def normalize_images(
    payload: dict[str, Any],
    *,
    configuration: dict[str, Any],
    movie: dict[str, Any],
    image_type: str,
    max_results: int,
) -> list[dict[str, Any]]:
    requested = IMAGE_TYPES if image_type == "all" else (f"{image_type}s",)
    groups: dict[str, list[dict[str, Any]]] = {}
    for plural in requested:
        kind = IMAGE_KIND[plural]
        group: list[dict[str, Any]] = []
        rows = payload.get(plural) if isinstance(payload, dict) else []
        ranked = sorted(
            [item for item in rows or [] if isinstance(item, dict)],
            key=lambda item: (
                _safe_int(item.get("vote_count")) or 0,
                _safe_float(item.get("vote_average")) or 0.0,
            ),
            reverse=True,
        )
        for item in ranked[:max_results]:
            original = _image_url(configuration, item.get("file_path"), kind, "original")
            if not original:
                continue
            group.append(
                {
                    "image_type": kind,
                    "title": f"{movie.get('title', 'Movie')} {kind}",
                    "file_path": item.get("file_path"),
                    "width": _safe_int(item.get("width")),
                    "height": _safe_int(item.get("height")),
                    "aspect_ratio": _safe_float(item.get("aspect_ratio")),
                    "language": item.get("iso_639_1"),
                    "rating": _safe_float(item.get("vote_average")),
                    "votes": _safe_int(item.get("vote_count")),
                    "thumbnail": _image_url(configuration, item.get("file_path"), kind, "thumbnail"),
                    "image_url": _image_url(configuration, item.get("file_path"), kind, "display"),
                    "original_url": original,
                    "source_url": movie.get("tmdb_url"),
                    "source": "TMDB",
                    "untrusted_external_content": True,
                }
            )
        groups[kind] = group

    if image_type == "all":
        # A mixed-artwork request should stay useful in one call. Round-robin
        # the ranked groups so high-vote posters cannot crowd out backdrops and
        # logos from the returned gallery.
        entries = []
        group_index = 0
        while len(entries) < max_results:
            added = False
            for group in groups.values():
                if group_index < len(group):
                    entries.append(group[group_index])
                    added = True
                    if len(entries) >= max_results:
                        break
            if not added:
                break
            group_index += 1
    else:
        entries = list(groups.get(image_type, []))[:max_results]

    for position, item in enumerate(entries, 1):
        item["position"] = position
    return entries


def normalize_credits(
    payload: dict[str, Any], configuration: dict[str, Any], limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cast = []
    for item in (payload.get("cast") or [])[:limit]:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        cast.append(
            {
                "id": _safe_int(item.get("id")),
                "name": item.get("name"),
                "character": item.get("character"),
                "order": _safe_int(item.get("order")),
                "known_for_department": item.get("known_for_department"),
                "profile_thumbnail": _image_url(
                    configuration, item.get("profile_path"), "profile", "thumbnail"
                ),
                "profile_url": _image_url(
                    configuration, item.get("profile_path"), "profile", "display"
                ),
                "tmdb_url": f"{TMDB_WEB_BASE_URL}/person/{item.get('id')}"
                if _safe_int(item.get("id"))
                else None,
            }
        )
    crew = []
    for item in payload.get("crew") or []:
        if (
            not isinstance(item, dict)
            or not item.get("name")
            or item.get("job") not in IMPORTANT_CREW_JOBS
        ):
            continue
        crew.append(
            {
                "id": _safe_int(item.get("id")),
                "name": item.get("name"),
                "job": item.get("job"),
                "department": item.get("department"),
                "tmdb_url": f"{TMDB_WEB_BASE_URL}/person/{item.get('id')}"
                if _safe_int(item.get("id"))
                else None,
            }
        )
        if len(crew) >= limit:
            break
    return cast, crew


def normalize_videos(payload: dict[str, Any], movie_title: str, limit: int) -> list[dict[str, Any]]:
    videos = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        site = str(item.get("site") or "").lower()
        key = str(item.get("key") or "").strip()
        if site == "youtube" and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", key):
            url = f"https://www.youtube.com/watch?v={key}"
        elif site == "vimeo" and re.fullmatch(r"\d{4,20}", key):
            url = f"https://vimeo.com/{key}"
        else:
            continue
        videos.append(
            {
                "title": item.get("name") or f"{movie_title} video",
                "movie_title": movie_title,
                "url": url,
                "site": item.get("site"),
                "type": item.get("type"),
                "official": bool(item.get("official")),
                "published_at": item.get("published_at"),
                "language": item.get("iso_639_1"),
                "country": item.get("iso_3166_1"),
            }
        )
    videos.sort(
        key=lambda item: (
            item.get("official") is True,
            item.get("type") == "Trailer",
            item.get("published_at") or "",
        ),
        reverse=True,
    )
    return videos[:limit]


def _certification(payload: dict[str, Any], region: str) -> str | None:
    for group in payload.get("results") or []:
        if not isinstance(group, dict) or group.get("iso_3166_1") != region:
            continue
        releases = sorted(
            [item for item in group.get("release_dates") or [] if isinstance(item, dict)],
            key=lambda item: 0 if item.get("type") == 3 else 1,
        )
        for item in releases:
            value = str(item.get("certification") or "").strip()
            if value:
                return value
    return None


def _keyword_names(payload: dict[str, Any]) -> list[str]:
    rows = payload.get("keywords") or payload.get("results") or []
    return [
        str(item.get("name"))
        for item in rows[:20]
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]


def _resolve_movie_id(
    client: TMDBClient,
    movie_id: Any,
    query: str,
    *,
    language: str,
    region: str,
    year: int | None,
) -> tuple[int, dict[str, Any] | None]:
    parsed_id = _safe_int(movie_id)
    if parsed_id and parsed_id > 0:
        return parsed_id, None
    if not query:
        raise TMDBAPIError("movie_id or query is required for this action.")
    params: dict[str, Any] = {
        "query": query,
        "include_adult": False,
        "language": language,
        "region": region,
    }
    if year:
        params["primary_release_year"] = year
    payload = client.get("/search/movie", params)
    results = payload.get("results") if isinstance(payload, dict) else []
    if not results:
        raise TMDBAPIError(f"TMDB found no movie matching '{query[:120]}'.")
    resolved = results[0]
    resolved_id = _safe_int(resolved.get("id")) if isinstance(resolved, dict) else None
    if not resolved_id:
        raise TMDBAPIError("TMDB search returned a movie without a usable ID.")
    return resolved_id, resolved


def _base_payload(client: TMDBClient, action: str) -> dict[str, Any]:
    return {
        "action": action,
        "api_requests": client.request_count,
        "auth_method": client.auth_method,
        "oauth_used": False,
        "public_metadata_only": True,
        "attribution_notice": ATTRIBUTION_NOTICE,
        "attribution_url": TMDB_WEB_BASE_URL,
        "external_content_trust": "untrusted",
        "source": "TMDB API",
    }


def _list_payload(
    client: TMDBClient,
    action: str,
    provider_payload: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    query: str = "",
) -> dict[str, Any]:
    data = _base_payload(client, action)
    data.update(
        {
            "query": query or None,
            "results_count": len(results),
            "provider_results_count": _safe_int(provider_payload.get("total_results")),
            "page": _safe_int(provider_payload.get("page")),
            "total_pages": _safe_int(provider_payload.get("total_pages")),
            "results": results,
            "top_results": results[:5],
            "top_url": results[0].get("tmdb_url") if results else None,
        }
    )
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def execute_action(client: TMDBClient, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    if action not in VALID_ACTIONS:
        raise TMDBAPIError(f"Unsupported action '{action}'.")
    query = str(args.get("query") or "").strip()
    language = _clean_language(args.get("language"))
    region = _clean_region(args.get("region"))
    year = _safe_int(args.get("year"))
    page = max(1, min(500, _safe_int(args.get("page")) or 1))
    max_results = _max_results(args.get("max_results"))
    configuration = client.configuration()
    genre_map = client.genre_map()

    if action == "search":
        if not query:
            raise TMDBAPIError("query is required for search.")
        params: dict[str, Any] = {
            "query": query,
            "include_adult": bool(args.get("include_adult", False)),
            "language": language,
            "region": region,
            "page": page,
        }
        if year:
            params["primary_release_year"] = year
        payload = client.get("/search/movie", params)
        results = [
            movie
            for item in (payload.get("results") or [])[:max_results]
            if (movie := normalize_movie(item, configuration=configuration, genre_map=genre_map, source="search"))
        ]
        return _list_payload(client, action, payload, results, query=query)

    if action in LIST_PATHS or action == "trending":
        if action == "trending":
            time_window = str(args.get("time_window") or "day").lower()
            if time_window not in {"day", "week"}:
                raise TMDBAPIError("time_window must be day or week.")
            path = f"/trending/movie/{time_window}"
        else:
            path = LIST_PATHS[action]
        list_params: dict[str, Any] = {"language": language, "page": page}
        if action != "trending":
            list_params["region"] = region
        payload = client.get(path, list_params)
        results = [
            movie
            for item in (payload.get("results") or [])[:max_results]
            if (movie := normalize_movie(item, configuration=configuration, genre_map=genre_map, source=action))
        ]
        return _list_payload(client, action, payload, results)

    if action == "discover":
        params: dict[str, Any] = {
            "include_adult": bool(args.get("include_adult", False)),
            "include_video": False,
            "language": language,
            "region": region,
            "page": page,
            "sort_by": str(args.get("sort_by") or "popularity.desc"),
        }
        if params["sort_by"] not in ALLOWED_SORTS:
            raise TMDBAPIError("Unsupported TMDB discover sort_by value.")
        if year:
            params["primary_release_year"] = year
        requested_genres = [str(value).strip().lower() for value in args.get("genres") or [] if str(value).strip()]
        resolved_genres: list[str] = []
        if requested_genres:
            by_name = {name.lower(): genre_id for genre_id, name in genre_map.items()}
            unknown = [name for name in requested_genres if name not in by_name]
            if unknown:
                raise TMDBAPIError(f"Unknown TMDB movie genre: {unknown[0][:60]}")
            params["with_genres"] = ",".join(str(by_name[name]) for name in requested_genres)
            resolved_genres = [genre_map[by_name[name]] for name in requested_genres]
        for source_key, target_key in (
            ("runtime_min", "with_runtime.gte"),
            ("runtime_max", "with_runtime.lte"),
            ("min_votes", "vote_count.gte"),
        ):
            value = _safe_int(args.get(source_key))
            if value is not None:
                params[target_key] = max(0, value)
        min_rating = _safe_float(args.get("min_rating"))
        if min_rating is not None:
            params["vote_average.gte"] = max(0.0, min(10.0, min_rating))
        if args.get("release_date_from"):
            params["primary_release_date.gte"] = args["release_date_from"]
        if args.get("release_date_to"):
            params["primary_release_date.lte"] = args["release_date_to"]
        payload = client.get("/discover/movie", params)
        results = [
            movie
            for item in (payload.get("results") or [])[:max_results]
            if (movie := normalize_movie(item, configuration=configuration, genre_map=genre_map, source="discover"))
        ]
        data = _list_payload(client, action, payload, results, query=query)
        data["filters_used"] = {key: value for key, value in params.items() if key not in {"language", "page"}}
        data["selection_criteria"] = {
            key: value
            for key, value in {
                "genres": resolved_genres,
                "runtime_min_minutes": _safe_int(args.get("runtime_min")),
                "runtime_max_minutes": _safe_int(args.get("runtime_max")),
                "minimum_rating": min_rating,
                "minimum_votes": _safe_int(args.get("min_votes")),
                "year": year,
                "release_date_from": args.get("release_date_from"),
                "release_date_to": args.get("release_date_to"),
                "sort_by": params["sort_by"],
                "provider_filters_applied": True,
                "all_returned_results_match": True,
            }.items()
            if value not in (None, "", [], {})
        }
        return data

    movie_id, resolved_search = _resolve_movie_id(
        client,
        args.get("movie_id"),
        query,
        language=language,
        region=region,
        year=year,
    )
    append_map = {
        "details": "images,credits,videos,external_ids,release_dates,keywords,recommendations,similar",
        "images": "images",
        "credits": "credits",
        "videos": "videos",
        "recommendations": "recommendations",
        "similar": "similar",
    }
    image_languages = _clean_image_languages(args.get("image_languages"), language)
    bundle = client.get(
        f"/movie/{quote(str(movie_id), safe='')}",
        {
            "language": language,
            "append_to_response": append_map[action],
            "include_image_language": image_languages,
        },
    )
    if not isinstance(bundle, dict):
        raise TMDBAPIError("TMDB returned an invalid movie payload.")
    movie = normalize_movie(bundle, configuration=configuration, genre_map=genre_map, source=action)
    if not movie:
        raise TMDBAPIError("TMDB returned movie data without a usable identity.")
    if resolved_search:
        movie["resolved_from_query"] = query

    data = _base_payload(client, action)
    data.update({"query": query or None, "movie": movie, "top_url": movie.get("tmdb_url")})

    if action in {"details", "images"}:
        image_type = str(args.get("image_type") or "all").strip().lower()
        if image_type not in {"all", "poster", "backdrop", "logo"}:
            raise TMDBAPIError("image_type must be all, poster, backdrop, or logo.")
        images = normalize_images(
            bundle.get("images") or {},
            configuration=configuration,
            movie=movie,
            image_type=image_type,
            max_results=max_results,
        )
        data["images"] = images
        artwork_counts = {
            kind: sum(1 for item in images if item.get("image_type") == kind)
            for kind in ("poster", "backdrop", "logo")
        }
        data["artwork_counts"] = artwork_counts
        data["artwork_types_returned"] = [
            kind for kind, count in artwork_counts.items() if count
        ]
        if action == "images":
            data.update(
                {
                    "image_type": image_type,
                    "image_languages": image_languages,
                    "results_count": len(images),
                    "results": images,
                    "top_results": images[:5],
                }
            )

    if action in {"details", "credits"}:
        cast, crew = normalize_credits(
            bundle.get("credits") or {}, configuration, max_results
        )
        data["cast"] = cast
        data["crew"] = crew
        if action == "credits":
            data.update({"results_count": len(cast), "results": cast, "top_results": cast[:5]})

    if action in {"details", "videos"}:
        videos = normalize_videos(bundle.get("videos") or {}, movie["title"], max_results)
        data["videos"] = videos
        if action == "videos":
            data.update({"results_count": len(videos), "results": videos, "top_results": videos[:5]})

    for nested_action in ("recommendations", "similar"):
        if action not in {"details", nested_action}:
            continue
        nested = bundle.get(nested_action) or {}
        results = [
            normalized
            for item in (nested.get("results") or [])[:max_results]
            if (normalized := normalize_movie(
                item,
                configuration=configuration,
                genre_map=genre_map,
                source=nested_action,
            ))
        ]
        data[nested_action] = results
        if action == nested_action:
            data.update({"results_count": len(results), "results": results, "top_results": results[:5]})

    if action == "details":
        movie["certification"] = _certification(bundle.get("release_dates") or {}, region)
        data["external_ids"] = {
            key: value
            for key, value in (bundle.get("external_ids") or {}).items()
            if value not in (None, "")
        }
        data["keywords"] = _keyword_names(bundle.get("keywords") or {})
        data["details_included"] = [
            name
            for name, present in (
                ("movie_metadata", bool(movie)),
                (
                    "production_details",
                    any(
                        movie.get(key)
                        for key in (
                            "production_companies",
                            "production_countries",
                            "budget",
                            "revenue",
                        )
                    ),
                ),
                ("certification", bool(movie.get("certification"))),
                ("cast", bool(data.get("cast"))),
                ("director_and_crew", bool(data.get("crew"))),
                ("artwork", bool(data.get("images"))),
                ("videos", bool(data.get("videos"))),
                ("recommendations", bool(data.get("recommendations"))),
                ("similar_movies", bool(data.get("similar"))),
                ("external_ids", bool(data.get("external_ids"))),
                ("keywords", bool(data.get("keywords"))),
            )
            if present
        ]
        data["results_count"] = 1
        data["results"] = [movie]
        data["top_results"] = [movie]

    data["api_requests"] = client.request_count
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def build_speech(data: dict[str, Any]) -> str:
    action = str(data.get("action") or "movie")
    movie = data.get("movie") if isinstance(data.get("movie"), dict) else {}
    results = data.get("top_results") if isinstance(data.get("top_results"), list) else []
    top = results[0] if results and isinstance(results[0], dict) else {}
    title = movie.get("title") or top.get("title") or top.get("name")
    count = _safe_int(data.get("results_count")) or 0
    if action == "details" and title:
        return (
            f"Retrieved bundled TMDB details for {title}, including cast, crew, "
            "production metadata, certification, and artwork."
        )
    if action == "images" and title:
        artwork_counts = data.get("artwork_counts")
        if isinstance(artwork_counts, dict):
            breakdown = ", ".join(
                f"{artwork_counts[kind]} {kind}{'' if artwork_counts[kind] == 1 else 's'}"
                for kind in ("poster", "backdrop", "logo")
                if artwork_counts.get(kind)
            )
            if breakdown:
                return f"Found {count} TMDB artwork image(s) for {title}: {breakdown}."
        return f"Found {count} TMDB artwork image(s) for {title}."
    if action == "discover" and title:
        return (
            f"Found {count} TMDB movie(s) matching the provider-applied discover "
            f"filters. Top result: {title}."
        )
    if action == "credits" and title:
        return f"Retrieved {count} leading TMDB cast credit(s) for {title}."
    if title:
        return f"Found {count} TMDB {action.replace('_', ' ')} result(s). Top result: {title}."
    return f"Found {count} TMDB {action.replace('_', ' ')} result(s)."


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

        client = TMDBClient(
            access_token=os.getenv("TMDB_ACCESS_TOKEN", ""),
            api_key=os.getenv("TMDB_API_KEY", ""),
        )
        data = execute_action(client, input_data)
        _print_result({"ok": True, "speech": build_speech(data), "data": data})
        return 0
    except TMDBAPIError as exc:
        data = {
            key: value
            for key, value in {
                "status_code": exc.status_code,
                "retry_after": exc.retry_after,
                "endpoint": exc.endpoint,
                "source": "TMDB API",
            }.items()
            if value not in (None, "")
        }
        message = str(exc)
        _print_result({"ok": False, "speech": message, "error": message, "data": data})
        return 1
    except Exception as exc:
        message = f"TMDB movie tool error: {exc.__class__.__name__}"
        _print_result({"ok": False, "speech": message, "error": message})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
