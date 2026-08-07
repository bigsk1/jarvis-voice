#!/usr/bin/env python3
"""Jarvis skill: standalone TMDB TV discovery, metadata, and artwork."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config

from tmdb_movies import (
    ATTRIBUTION_NOTICE,
    TMDBAPIError,
    TMDBClient as _BaseTMDBClient,
    TMDB_WEB_BASE_URL,
    _clean_image_languages,
    _clean_language,
    _image_url,
    _max_results,
    _name_list,
    _safe_float,
    _safe_int,
    _year_from_date,
    normalize_images as _normalize_images,
)


USER_AGENT = "JarvisVoice/TMDBTVShows-1.0"

LIST_PATHS = {
    "popular": "/tv/popular",
    "airing_today": "/tv/airing_today",
    "on_the_air": "/tv/on_the_air",
    "top_rated": "/tv/top_rated",
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
    "airing_today",
    "on_the_air",
    "top_rated",
    "discover",
}
ALLOWED_SORTS = {
    "first_air_date.desc",
    "first_air_date.asc",
    "name.desc",
    "name.asc",
    "original_name.desc",
    "original_name.asc",
    "popularity.desc",
    "popularity.asc",
    "vote_average.desc",
    "vote_average.asc",
    "vote_count.desc",
    "vote_count.asc",
}
IMPORTANT_CREW_JOBS = {
    "Creator",
    "Director",
    "Executive Producer",
    "Producer",
    "Screenplay",
    "Series Director",
    "Series Producer",
    "Story",
    "Writer",
}


class TMDBClient(_BaseTMDBClient):
    """TMDB application client with TV genre discovery."""

    def __init__(self, access_token: str = "", api_key: str = "", request_func=None) -> None:
        super().__init__(access_token=access_token, api_key=api_key, request_func=request_func)
        self.headers["User-Agent"] = USER_AGENT

    def genre_map(self) -> dict[int, str]:
        if self._genre_map is None:
            payload = self.get("/genre/tv/list", {"language": "en-US"})
            genres = payload.get("genres") if isinstance(payload, dict) else []
            self._genre_map = {
                int(item["id"]): str(item["name"])
                for item in genres or []
                if isinstance(item, dict)
                and _safe_int(item.get("id")) is not None
                and str(item.get("name") or "").strip()
            }
        return self._genre_map


def _show_url(show_id: Any) -> str | None:
    parsed = _safe_int(show_id)
    return f"{TMDB_WEB_BASE_URL}/tv/{parsed}" if parsed and parsed > 0 else None


def _episode_summary(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    summary = {
        "id": _safe_int(item.get("id")),
        "name": item.get("name"),
        "air_date": item.get("air_date"),
        "season_number": _safe_int(item.get("season_number")),
        "episode_number": _safe_int(item.get("episode_number")),
        "runtime_minutes": _safe_int(item.get("runtime")),
        "overview": str(item.get("overview") or "")[:700] or None,
    }
    return {key: value for key, value in summary.items() if value not in (None, "", [], {})}


def normalize_show(
    item: dict[str, Any],
    *,
    configuration: dict[str, Any],
    genre_map: dict[int, str],
    source: str,
) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    show_id = _safe_int(item.get("id"))
    title = str(item.get("name") or item.get("original_name") or "").strip()
    if not show_id or not title:
        return None

    genres = _name_list(item.get("genres"))
    if not genres:
        genres = [
            genre_map[genre_id]
            for raw_id in item.get("genre_ids") or []
            if (genre_id := _safe_int(raw_id)) in genre_map
        ]

    runtimes = [
        runtime
        for value in item.get("episode_run_time") or []
        if (runtime := _safe_int(value)) is not None and runtime > 0
    ]
    episode_runtime = runtimes[0] if runtimes else _safe_int(item.get("runtime"))
    poster_path = item.get("poster_path")
    backdrop_path = item.get("backdrop_path")
    result = {
        "id": show_id,
        "tmdb_id": show_id,
        "title": title,
        "original_title": item.get("original_name"),
        "first_air_date": item.get("first_air_date"),
        "last_air_date": item.get("last_air_date"),
        "year": _year_from_date(item.get("first_air_date")),
        "overview": item.get("overview"),
        "tagline": item.get("tagline"),
        "episode_runtime_minutes": episode_runtime,
        "episode_runtimes": runtimes,
        "number_of_seasons": _safe_int(item.get("number_of_seasons")),
        "number_of_episodes": _safe_int(item.get("number_of_episodes")),
        "rating": _safe_float(item.get("vote_average")),
        "votes": _safe_int(item.get("vote_count")),
        "popularity": _safe_float(item.get("popularity")),
        "genres": genres,
        "original_language": item.get("original_language"),
        "origin_countries": [str(value) for value in item.get("origin_country") or [] if value],
        "status": item.get("status"),
        "show_type": item.get("type"),
        "in_production": item.get("in_production"),
        "homepage": item.get("homepage"),
        "created_by": _name_list(item.get("created_by")),
        "networks": _name_list(item.get("networks")),
        "production_companies": _name_list(item.get("production_companies")),
        "production_countries": _name_list(item.get("production_countries")),
        "spoken_languages": _name_list(item.get("spoken_languages")),
        "next_episode_to_air": _episode_summary(item.get("next_episode_to_air")),
        "last_episode_to_air": _episode_summary(item.get("last_episode_to_air")),
        "tmdb_url": _show_url(show_id),
        "poster_url": _image_url(configuration, poster_path, "poster", "display"),
        "poster_thumbnail": _image_url(configuration, poster_path, "poster", "thumbnail"),
        "poster_original_url": _image_url(configuration, poster_path, "poster", "original"),
        "backdrop_url": _image_url(configuration, backdrop_path, "backdrop", "display"),
        "backdrop_thumbnail": _image_url(configuration, backdrop_path, "backdrop", "thumbnail"),
        "backdrop_original_url": _image_url(configuration, backdrop_path, "backdrop", "original"),
        "source_signal": source,
        "runtime_scope": "episode",
        "external_content_trust": "untrusted",
    }
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def normalize_images(
    payload: dict[str, Any],
    *,
    configuration: dict[str, Any],
    show: dict[str, Any],
    image_type: str,
    max_results: int,
) -> list[dict[str, Any]]:
    return _normalize_images(
        payload,
        configuration=configuration,
        movie=show,
        image_type=image_type,
        max_results=max_results,
    )


def normalize_credits(
    payload: dict[str, Any], configuration: dict[str, Any], limit: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cast = []
    for item in payload.get("cast") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        roles = [role for role in item.get("roles") or [] if isinstance(role, dict)]
        characters = [str(role.get("character")) for role in roles if role.get("character")][:4]
        episode_count = _safe_int(item.get("total_episode_count"))
        if episode_count is None:
            episode_count = sum(_safe_int(role.get("episode_count")) or 0 for role in roles) or None
        cast.append(
            {
                key: value
                for key, value in {
                    "id": _safe_int(item.get("id")),
                    "name": item.get("name"),
                    "character": characters[0] if characters else None,
                    "characters": characters,
                    "episode_count": episode_count,
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
                }.items()
                if value not in (None, "", [], {})
            }
        )
        if len(cast) >= limit:
            break

    crew = []
    for item in payload.get("crew") or []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        jobs = [job for job in item.get("jobs") or [] if isinstance(job, dict)]
        job_names = [str(job.get("job")) for job in jobs if job.get("job")]
        important = [job for job in job_names if job in IMPORTANT_CREW_JOBS]
        if not important and item.get("department") not in {"Directing", "Production", "Writing"}:
            continue
        episode_count = _safe_int(item.get("total_episode_count"))
        if episode_count is None:
            episode_count = sum(_safe_int(job.get("episode_count")) or 0 for job in jobs) or None
        crew.append(
            {
                key: value
                for key, value in {
                    "id": _safe_int(item.get("id")),
                    "name": item.get("name"),
                    "job": (important or job_names or [None])[0],
                    "jobs": (important or job_names)[:4],
                    "department": item.get("department"),
                    "episode_count": episode_count,
                    "tmdb_url": f"{TMDB_WEB_BASE_URL}/person/{item.get('id')}"
                    if _safe_int(item.get("id"))
                    else None,
                }.items()
                if value not in (None, "", [], {})
            }
        )
        if len(crew) >= limit:
            break
    return cast, crew


def normalize_videos(payload: dict[str, Any], show_title: str, limit: int) -> list[dict[str, Any]]:
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
                "title": item.get("name") or f"{show_title} video",
                "show_title": show_title,
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


def _content_rating(payload: dict[str, Any], region: str) -> str | None:
    for item in payload.get("results") or []:
        if not isinstance(item, dict) or item.get("iso_3166_1") != region:
            continue
        rating = str(item.get("rating") or "").strip()
        if rating:
            return rating
    return None


def _keyword_names(payload: dict[str, Any]) -> list[str]:
    return [
        str(item.get("name"))
        for item in (payload.get("results") or [])[:20]
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]


def _normalize_seasons(
    rows: Any, configuration: dict[str, Any], show_url: str | None
) -> list[dict[str, Any]]:
    seasons = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        seasons.append(
            {
                key: value
                for key, value in {
                    "id": _safe_int(item.get("id")),
                    "name": item.get("name"),
                    "season_number": _safe_int(item.get("season_number")),
                    "air_date": item.get("air_date"),
                    "episode_count": _safe_int(item.get("episode_count")),
                    "overview": str(item.get("overview") or "")[:700] or None,
                    "poster_thumbnail": _image_url(
                        configuration, item.get("poster_path"), "poster", "thumbnail"
                    ),
                    "poster_url": _image_url(
                        configuration, item.get("poster_path"), "poster", "display"
                    ),
                    "source_url": show_url,
                }.items()
                if value not in (None, "", [], {})
            }
        )
    return seasons[:30]


def _resolve_show_id(
    client: TMDBClient,
    show_id: Any,
    query: str,
    *,
    language: str,
    year: int | None,
) -> tuple[int, dict[str, Any] | None]:
    parsed_id = _safe_int(show_id)
    if parsed_id and parsed_id > 0:
        return parsed_id, None
    if not query:
        raise TMDBAPIError("show_id or query is required for this action.")
    params: dict[str, Any] = {
        "query": query,
        "include_adult": False,
        "language": language,
    }
    if year:
        params["first_air_date_year"] = year
    payload = client.get("/search/tv", params)
    results = payload.get("results") if isinstance(payload, dict) else []
    if not results:
        raise TMDBAPIError(f"TMDB found no TV show matching '{query[:120]}'.")
    resolved = results[0]
    resolved_id = _safe_int(resolved.get("id")) if isinstance(resolved, dict) else None
    if not resolved_id:
        raise TMDBAPIError("TMDB search returned a TV show without a usable ID.")
    return resolved_id, resolved


def _base_payload(client: TMDBClient, action: str) -> dict[str, Any]:
    return {
        "action": action,
        "media_type": "tv_show",
        "runtime_scope": "episode",
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
    region = str(args.get("region") or "US").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", region):
        raise TMDBAPIError("region must be a two-letter country code such as US.")
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
            "page": page,
        }
        if year:
            params["first_air_date_year"] = year
        payload = client.get("/search/tv", params)
        results = [
            show
            for item in (payload.get("results") or [])[:max_results]
            if (show := normalize_show(item, configuration=configuration, genre_map=genre_map, source="search"))
        ]
        return _list_payload(client, action, payload, results, query=query)

    if action in LIST_PATHS or action == "trending":
        if action == "trending":
            time_window = str(args.get("time_window") or "day").lower()
            if time_window not in {"day", "week"}:
                raise TMDBAPIError("time_window must be day or week.")
            path = f"/trending/tv/{time_window}"
        else:
            path = LIST_PATHS[action]
        payload = client.get(path, {"language": language, "page": page})
        results = [
            show
            for item in (payload.get("results") or [])[:max_results]
            if (show := normalize_show(item, configuration=configuration, genre_map=genre_map, source=action))
        ]
        return _list_payload(client, action, payload, results)

    if action == "discover":
        params: dict[str, Any] = {
            "include_adult": bool(args.get("include_adult", False)),
            "include_null_first_air_dates": False,
            "language": language,
            "page": page,
            "sort_by": str(args.get("sort_by") or "popularity.desc"),
        }
        if params["sort_by"] not in ALLOWED_SORTS:
            raise TMDBAPIError("Unsupported TMDB TV discover sort_by value.")
        if year:
            params["first_air_date_year"] = year
        requested_genres = [
            str(value).strip().lower() for value in args.get("genres") or [] if str(value).strip()
        ]
        resolved_genres: list[str] = []
        if requested_genres:
            by_name = {name.lower(): genre_id for genre_id, name in genre_map.items()}
            unknown = [name for name in requested_genres if name not in by_name]
            if unknown:
                raise TMDBAPIError(f"Unknown TMDB TV genre: {unknown[0][:60]}")
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
        if args.get("first_air_date_from"):
            params["first_air_date.gte"] = args["first_air_date_from"]
        if args.get("first_air_date_to"):
            params["first_air_date.lte"] = args["first_air_date_to"]
        if args.get("origin_country"):
            params["with_origin_country"] = str(args["origin_country"]).upper()
        if args.get("original_language"):
            params["with_original_language"] = str(args["original_language"]).lower()
        payload = client.get("/discover/tv", params)
        results = [
            show
            for item in (payload.get("results") or [])[:max_results]
            if (show := normalize_show(item, configuration=configuration, genre_map=genre_map, source="discover"))
        ]
        data = _list_payload(client, action, payload, results, query=query)
        data["filters_used"] = {
            key: value for key, value in params.items() if key not in {"language", "page"}
        }
        data["selection_criteria"] = {
            key: value
            for key, value in {
                "genres": resolved_genres,
                "episode_runtime_min_minutes": _safe_int(args.get("runtime_min")),
                "episode_runtime_max_minutes": _safe_int(args.get("runtime_max")),
                "minimum_rating": min_rating,
                "minimum_votes": _safe_int(args.get("min_votes")),
                "first_air_year": year,
                "first_air_date_from": args.get("first_air_date_from"),
                "first_air_date_to": args.get("first_air_date_to"),
                "origin_country": args.get("origin_country"),
                "original_language": args.get("original_language"),
                "sort_by": params["sort_by"],
                "provider_filters_applied": True,
                "all_returned_results_match": True,
            }.items()
            if value not in (None, "", [], {})
        }
        return data

    show_id, resolved_search = _resolve_show_id(
        client,
        args.get("show_id"),
        query,
        language=language,
        year=year,
    )
    append_map = {
        "details": "images,aggregate_credits,videos,external_ids,content_ratings,keywords,recommendations,similar",
        "images": "images",
        "credits": "aggregate_credits",
        "videos": "videos",
        "recommendations": "recommendations",
        "similar": "similar",
    }
    image_languages = _clean_image_languages(args.get("image_languages"), language)
    bundle = client.get(
        f"/tv/{quote(str(show_id), safe='')}",
        {
            "language": language,
            "append_to_response": append_map[action],
            "include_image_language": image_languages,
        },
    )
    if not isinstance(bundle, dict):
        raise TMDBAPIError("TMDB returned an invalid TV-show payload.")
    show = normalize_show(bundle, configuration=configuration, genre_map=genre_map, source=action)
    if not show:
        raise TMDBAPIError("TMDB returned TV-show data without a usable identity.")
    if resolved_search:
        show["resolved_from_query"] = query

    data = _base_payload(client, action)
    data.update({"query": query or None, "show": show, "top_url": show.get("tmdb_url")})

    if action in {"details", "images"}:
        image_type = str(args.get("image_type") or "all").strip().lower()
        if image_type not in {"all", "poster", "backdrop", "logo"}:
            raise TMDBAPIError("image_type must be all, poster, backdrop, or logo.")
        images = normalize_images(
            bundle.get("images") or {},
            configuration=configuration,
            show=show,
            image_type=image_type,
            max_results=max_results,
        )
        data["images"] = images
        artwork_counts = {
            kind: sum(1 for item in images if item.get("image_type") == kind)
            for kind in ("poster", "backdrop", "logo")
        }
        data["artwork_counts"] = artwork_counts
        data["artwork_types_returned"] = [kind for kind, count in artwork_counts.items() if count]
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
            bundle.get("aggregate_credits") or {}, configuration, max_results
        )
        data["cast"] = cast
        data["crew"] = crew
        if action == "credits":
            data.update({"results_count": len(cast), "results": cast, "top_results": cast[:5]})

    if action in {"details", "videos"}:
        videos = normalize_videos(bundle.get("videos") or {}, show["title"], max_results)
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
            if (normalized := normalize_show(
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
        show["content_rating"] = _content_rating(bundle.get("content_ratings") or {}, region)
        data["external_ids"] = {
            key: value
            for key, value in (bundle.get("external_ids") or {}).items()
            if value not in (None, "")
        }
        imdb_id = data["external_ids"].get("imdb_id")
        if imdb_id:
            show["imdb_id"] = imdb_id
            show["imdb_url"] = f"https://www.imdb.com/title/{imdb_id}/"
        data["keywords"] = _keyword_names(bundle.get("keywords") or {})
        data["seasons"] = _normalize_seasons(
            bundle.get("seasons"), configuration, show.get("tmdb_url")
        )
        data["details_included"] = [
            name
            for name, present in (
                ("show_metadata", bool(show)),
                (
                    "production_details",
                    any(show.get(key) for key in ("created_by", "networks", "production_companies")),
                ),
                ("content_rating", bool(show.get("content_rating"))),
                ("seasons", bool(data.get("seasons"))),
                ("aggregate_cast", bool(data.get("cast"))),
                ("aggregate_crew", bool(data.get("crew"))),
                ("artwork", bool(data.get("images"))),
                ("videos", bool(data.get("videos"))),
                ("recommendations", bool(data.get("recommendations"))),
                ("similar_shows", bool(data.get("similar"))),
                ("external_ids", bool(data.get("external_ids"))),
                ("keywords", bool(data.get("keywords"))),
            )
            if present
        ]
        data["results_count"] = 1
        data["results"] = [show]
        data["top_results"] = [show]

    data["api_requests"] = client.request_count
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def build_speech(data: dict[str, Any]) -> str:
    action = str(data.get("action") or "TV show")
    show = data.get("show") if isinstance(data.get("show"), dict) else {}
    results = data.get("top_results") if isinstance(data.get("top_results"), list) else []
    top = results[0] if results and isinstance(results[0], dict) else {}
    title = show.get("title") or top.get("title") or top.get("name")
    count = _safe_int(data.get("results_count")) or 0
    if action == "details" and title:
        return (
            f"Retrieved bundled TMDB TV details for {title}, including aggregate cast and crew, "
            "production metadata, seasons, content rating, and artwork."
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
                return f"Found {count} TMDB TV artwork image(s) for {title}: {breakdown}."
        return f"Found {count} TMDB TV artwork image(s) for {title}."
    if action == "discover" and title:
        return (
            f"Found {count} TMDB TV show(s) matching the provider-applied discover filters. "
            f"Top result: {title}."
        )
    if action == "credits" and title:
        return f"Retrieved {count} leading aggregate TMDB cast credit(s) for {title}."
    if title:
        return f"Found {count} TMDB TV {action.replace('_', ' ')} result(s). Top result: {title}."
    return f"Found {count} TMDB TV {action.replace('_', ' ')} result(s)."


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
        message = f"TMDB TV-show tool error: {exc.__class__.__name__}"
        _print_result({"ok": False, "speech": message, "error": message})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
