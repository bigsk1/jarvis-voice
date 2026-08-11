#!/usr/bin/env python3
"""Jarvis skill: read-only authenticated Trakt account context."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import get_config_value, load_config
from http_client import http_request
from trakt_movies import (
    API_BASE_URL,
    _safe_int,
    normalize_movie,
)
from trakt_movies import (
    _infer_genres as infer_movie_genres,
)
from trakt_movies import (
    _infer_runtime_filter as infer_movie_runtime,
)
from trakt_oauth import DEFAULT_REDIRECT_URI, TraktOAuthError, get_fresh_credentials
from trakt_tv_shows import (
    _infer_genres as infer_show_genres,
)
from trakt_tv_shows import (
    _infer_runtime_filter as infer_show_runtime,
)
from trakt_tv_shows import (
    normalize_show,
)

USER_AGENT = "JarvisVoice/TraktAccount-1.0"
DEFAULT_TIMEOUT_SECONDS = 20
WATCHED_PAGE_LIMIT = 100
MAX_WATCHED_PAGES = 20
MAX_PUBLIC_CANDIDATES = 20
MEDIA_ID_FIELDS = ("trakt", "slug", "imdb", "tmdb", "tvdb")
LIST_ACTIONS = {
    "watchlist",
    "history",
    "ratings",
    "favorites",
    "personal_list_items",
    "smart_list_items",
}


class TraktAccountError(RuntimeError):
    """Structured account API error that never carries credentials."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after: int | None = None,
        endpoint: str | None = None,
        vip_required: bool = False,
        vip_enhanced_limit: bool = False,
        upgrade_url: str | None = None,
        vip_user: str | None = None,
        account_limit: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.endpoint = endpoint
        self.vip_required = vip_required
        self.vip_enhanced_limit = vip_enhanced_limit
        self.upgrade_url = upgrade_url
        self.vip_user = vip_user
        self.account_limit = account_limit


class TraktAccountClient:
    """Fixed-origin authenticated GET client with one safe 401 refresh retry."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        request_func: Callable[..., requests.Response] = http_request,
        credential_func: Callable[..., Any] = get_fresh_credentials,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.request_func = request_func
        self.credential_func = credential_func
        self.request_count = 0

    def _credentials(self, *, force_refresh: bool = False):
        return self.credential_func(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            force_refresh=force_refresh,
        )

    def get(self, path: str, params: dict[str, Any] | None = None) -> tuple[Any, dict[str, int]]:
        if not path.startswith("/") or "://" in path:
            raise TraktAccountError("Invalid Trakt account endpoint path.")
        endpoint = path.split("?", 1)[0]
        force_refresh = False
        server_retry_used = False
        rate_retry_used = False
        for _attempt in range(4):
            try:
                credentials = self._credentials(force_refresh=force_refresh)
            except TraktOAuthError as exc:
                raise TraktAccountError(str(exc), status_code=exc.status_code) from exc
            force_refresh = False
            headers = {
                "Authorization": f"Bearer {credentials.access_token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "trakt-api-version": "2",
                "trakt-api-key": self.client_id,
            }
            self.request_count += 1
            try:
                response = self.request_func(
                    "GET",
                    f"{API_BASE_URL}{path}",
                    headers=headers,
                    params=params or {},
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                    use_proxy=True,
                    fallback_on_proxy_fail=True,
                )
            except requests.RequestException as exc:
                if not server_retry_used:
                    server_retry_used = True
                    time.sleep(0.2)
                    continue
                raise TraktAccountError(
                    f"Trakt account request failed: {exc.__class__.__name__}", endpoint=endpoint
                ) from exc
            if response.status_code == 401 and not force_refresh and _attempt == 0:
                force_refresh = True
                continue
            if response.status_code == 429:
                retry_after = _safe_int(response.headers.get("Retry-After"))
                if not rate_retry_used and retry_after is not None and retry_after <= 2:
                    rate_retry_used = True
                    time.sleep(max(0, retry_after))
                    continue
                raise self._http_error(response, endpoint, retry_after=retry_after)
            if response.status_code >= 500 and not server_retry_used:
                server_retry_used = True
                time.sleep(0.25)
                continue
            if not response.ok:
                raise self._http_error(response, endpoint)
            if response.status_code == 204:
                return None, {}
            try:
                payload = response.json()
            except ValueError as exc:
                raise TraktAccountError(
                    "Trakt returned invalid account JSON.",
                    status_code=response.status_code,
                    endpoint=endpoint,
                ) from exc
            pagination = {
                name: value
                for name, header in (
                    ("page", "X-Pagination-Page"),
                    ("page_count", "X-Pagination-Page-Count"),
                    ("item_count", "X-Pagination-Item-Count"),
                    ("limit", "X-Pagination-Limit"),
                )
                if (value := _safe_int(response.headers.get(header))) is not None
            }
            return payload, pagination
        raise TraktAccountError(
            "Trakt account request failed after bounded retries.", endpoint=endpoint
        )

    @staticmethod
    def _http_error(
        response: requests.Response,
        endpoint: str,
        *,
        retry_after: int | None = None,
    ) -> TraktAccountError:
        status = response.status_code
        vip_required = status == 426
        vip_enhanced = status == 420
        if vip_required:
            message = "This Trakt endpoint requires VIP access."
        elif vip_enhanced:
            message = "This Trakt request exceeded a VIP Enhanced account limit."
        elif status == 401:
            message = "Trakt authorization is no longer valid; run ./bin/trakt-auth again."
        elif status == 403:
            message = "The Trakt account does not permit this read operation."
        elif status == 404:
            message = "The requested Trakt account resource was not found."
        elif status == 429:
            message = "Trakt account rate limit reached."
        else:
            message = f"Trakt account API returned HTTP {status}."
        return TraktAccountError(
            message,
            status_code=status,
            retry_after=retry_after,
            endpoint=endpoint,
            vip_required=vip_required,
            vip_enhanced_limit=vip_enhanced,
            upgrade_url=_safe_header_url(response.headers.get("X-Upgrade-URL")),
            vip_user=_bounded_header(response.headers.get("X-VIP-User")),
            account_limit=_bounded_header(response.headers.get("X-Account-Limit")),
        )


def _safe_header_url(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:500] if text.startswith(("https://", "http://")) else None


def _bounded_header(value: Any) -> str | None:
    text = re.sub(r"[\r\n]+", " ", str(value or "")).strip()
    return text[:200] or None


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    parsed = _safe_int(value)
    return max(low, min(parsed if parsed is not None else default, high))


def _clean_genres(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        cleaned
        for item in value[:6]
        if (cleaned := re.sub(r"[^a-z0-9-]+", "-", str(item).strip().lower()).strip("-"))
    ]


def _normalize_title(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _identity_keys(item: Any) -> set[str]:
    """Return stable media identifiers without retaining watched-history rows."""
    if not isinstance(item, dict):
        return set()
    ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
    keys = {
        f"{field}:{str(value).strip().lower()}"
        for field in MEDIA_ID_FIELDS
        if (value := ids.get(field)) not in (None, "")
    }
    title = _normalize_title(item.get("title"))
    year = _safe_int(item.get("year"))
    if title and year is not None:
        keys.add(f"title-year:{title}:{year}")
    elif title and not keys:
        keys.add(f"title:{title}")
    return keys


def _normalize_workflow_candidate(row: Any, *, is_show: bool) -> dict[str, Any] | None:
    """Normalize an internal public-tool handoff and preserve ranking signals."""
    normalized = (
        normalize_show(row, source="public_candidate")
        if is_show
        else normalize_movie(row, source="public_candidate")
    )
    if not normalized:
        return None
    normalized["media_type"] = "show" if is_show else "movie"
    if isinstance(row, dict):
        for field in ("source_signals", "related_to"):
            values = row.get(field)
            if isinstance(values, list):
                normalized[field] = [str(value)[:160] for value in values[:8] if value]
        for field in ("match_score", "reference_match_score"):
            value = row.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                normalized[field] = value
        streaming_signal = str(row.get("streaming_signal") or "")[:500]
        if streaming_signal:
            normalized["streaming_signal"] = streaming_signal
    return normalized


def _normalize_recommendations(
    rows: Any, *, is_show: bool, max_results: int
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in rows or []:
        item = _normalize_workflow_candidate(row, is_show=is_show)
        if item:
            item["source_signals"] = ["account_recommendation"]
            results.append(item)
        if len(results) >= max_results:
            break
    return results


def _fetch_watched_identities(
    client: TraktAccountClient,
    *,
    is_show: bool,
) -> tuple[set[str], int, int]:
    """Read every bounded watched page and retain only identity keys and counts."""
    path = "/sync/watched/shows" if is_show else "/sync/watched/movies"
    watched_keys: set[str] = set()
    watched_items_checked = 0
    pages_checked = 0
    page_count = 1

    for page in range(1, MAX_WATCHED_PAGES + 1):
        rows, pagination = client.get(
            path,
            {"page": page, "limit": WATCHED_PAGE_LIMIT, "extended": "full"},
        )
        pages_checked += 1
        if page == 1:
            page_count = max(1, _safe_int(pagination.get("page_count")) or 1)
            if page_count > MAX_WATCHED_PAGES:
                raise TraktAccountError(
                    "Watched-history filtering exceeded the bounded page limit.",
                    endpoint=path,
                )
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            media = row.get("show" if is_show else "movie")
            normalized = (
                normalize_show(media, source="watched_filter")
                if is_show
                else normalize_movie(media, source="watched_filter")
            )
            if not normalized:
                continue
            watched_items_checked += 1
            watched_keys.update(_identity_keys(normalized))
        if page >= page_count:
            break

    return watched_keys, watched_items_checked, pages_checked


def _exclude_watched(
    candidates: list[dict[str, Any]],
    watched_keys: set[str],
) -> tuple[list[dict[str, Any]], int]:
    eligible = [item for item in candidates if not (_identity_keys(item) & watched_keys)]
    return eligible, len(candidates) - len(eligible)


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        keys = _identity_keys(candidate)
        if keys & seen:
            continue
        deduped.append(candidate)
        seen.update(keys)
    return deduped


def _media_item(row: Any, source: str) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    if isinstance(row.get("movie"), dict):
        normalized = normalize_movie(row, source=source)
        media_type = "movie"
    elif isinstance(row.get("show"), dict):
        normalized = normalize_show(row, source=source)
        media_type = "show"
    elif isinstance(row.get("episode"), dict):
        episode = row["episode"]
        show = (
            normalize_show(row.get("show"), source=source)
            if isinstance(row.get("show"), dict)
            else None
        )
        ids = episode.get("ids") if isinstance(episode.get("ids"), dict) else {}
        normalized = {
            "title": episode.get("title") or "Episode",
            "season": _safe_int(episode.get("season")),
            "number": _safe_int(episode.get("number")),
            "ids": {
                key: ids[key]
                for key in ("trakt", "tvdb", "imdb", "tmdb")
                if ids.get(key) not in (None, "")
            },
            "show": show,
            "source_signals": [source],
            "external_content_trust": "untrusted",
        }
        media_type = "episode"
    else:
        normalized = normalize_movie(row, source=source) or normalize_show(row, source=source)
        media_type = "movie" if normalized and "runtime_minutes" in normalized else "show"
    if not normalized:
        return None
    normalized["media_type"] = media_type
    metadata = {
        "rank": row.get("rank"),
        "listed_at": row.get("listed_at"),
        "watched_at": row.get("watched_at"),
        "rated_at": row.get("rated_at"),
        "user_rating": _safe_int(row.get("rating")),
        "history_id": row.get("id"),
        "progress": row.get("progress"),
        "notes": str(row.get("notes") or "")[:600] or None,
    }
    normalized.update(
        {key: value for key, value in metadata.items() if value not in (None, "", [], {})}
    )
    return normalized


def _normalize_list(row: Any, source: str) -> dict[str, Any] | None:
    if not isinstance(row, dict) or not row.get("name"):
        return None
    ids = row.get("ids") if isinstance(row.get("ids"), dict) else {}
    slug = ids.get("slug")
    return {
        key: value
        for key, value in {
            "name": str(row.get("name"))[:300],
            "description": str(row.get("description") or "")[:1200] or None,
            "privacy": row.get("privacy"),
            "share_link": _safe_header_url(row.get("share_link")),
            "trakt_url": f"https://trakt.tv/lists/{quote(str(slug), safe='')}" if slug else None,
            "ids": ids,
            "item_count": _safe_int(row.get("item_count")),
            "comment_count": _safe_int(row.get("comment_count")),
            "sort_by": row.get("sort_by"),
            "sort_how": row.get("sort_how"),
            "display_numbers": row.get("display_numbers"),
            "allow_comments": row.get("allow_comments"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "source_signals": [source],
            "external_content_trust": "untrusted",
        }.items()
        if value not in (None, "", [], {})
    }


def _common_payload(action: str, client: TraktAccountClient) -> dict[str, Any]:
    return {
        "action": action,
        "oauth_used": True,
        "account_data": True,
        "read_only": True,
        "api_requests": client.request_count,
        "external_content_trust": "untrusted",
        "source": "Trakt API account",
    }


def _list_payload(
    action: str,
    rows: Any,
    pagination: dict[str, int],
    client: TraktAccountClient,
    *,
    source: str,
    max_results: int,
) -> dict[str, Any]:
    results = [item for row in (rows or []) if (item := _media_item(row, source))][:max_results]
    payload = _common_payload(action, client)
    payload.update(
        {
            "results_count": len(results),
            "results": results,
            "candidates": results,
            "top_results": results[:5],
            "top_url": results[0].get("trakt_url") if results else None,
            "pagination": pagination,
        }
    )
    return payload


def execute_action(client: TraktAccountClient, args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    max_results = _clamp_int(args.get("max_results"), 20, 1, 50)
    page = _clamp_int(args.get("page"), 1, 1, 10000)
    limit_params = {"page": page, "limit": max_results, "extended": "full"}

    if action == "status":
        data, _pagination = client.get("/users/settings", {"extended": "full"})
        data = data if isinstance(data, dict) else {}
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        ids = user.get("ids") if isinstance(user.get("ids"), dict) else {}
        payload = _common_payload(action, client)
        payload.update(
            {
                "authorized": True,
                "user": {
                    key: value
                    for key, value in {
                        "username": user.get("username"),
                        "private": user.get("private"),
                        "vip": user.get("vip"),
                        "vip_ep": user.get("vip_ep"),
                        "joined_at": user.get("joined_at"),
                        "location": user.get("location"),
                        "about": str(user.get("about") or "")[:600] or None,
                        "ids": {key: ids[key] for key in ("slug", "uuid") if ids.get(key)},
                    }.items()
                    if value not in (None, "", [], {})
                },
                "permissions": data.get("permissions")
                if isinstance(data.get("permissions"), dict)
                else {},
                "account": data.get("account") if isinstance(data.get("account"), dict) else {},
                "limits": data.get("limits") if isinstance(data.get("limits"), dict) else {},
            }
        )
        return payload

    if action in {
        "movie_recommendations",
        "show_recommendations",
        "movie_night_context",
        "tv_night_context",
    }:
        is_show = action in {"show_recommendations", "tv_night_context"}
        is_night_context = action.endswith("_night_context")
        ignore_watched = bool(args.get("ignore_watched", True))
        request = str(args.get("request") or "")[:800]
        genres = _clean_genres(args.get("genres"))
        runtime = str(args.get("runtimes") or "").strip()[:30]
        if is_night_context:
            genres = genres or (
                infer_show_genres(request) if is_show else infer_movie_genres(request)
            )
            runtime = (
                runtime
                or (infer_show_runtime(request) if is_show else infer_movie_runtime(request))
                or ""
            )
        params: dict[str, Any] = {
            **limit_params,
            "ignore_watched": str(ignore_watched).lower(),
            "ignore_collected": str(bool(args.get("ignore_collected", False))).lower(),
            "ignore_watchlisted": str(bool(args.get("ignore_watchlisted", False))).lower(),
        }
        for key, value in {
            "genres": ",".join(genres),
            "years": str(args.get("years") or "")[:30],
            "runtimes": runtime,
            "ratings": str(args.get("ratings") or "")[:30],
        }.items():
            if value:
                params[key] = value
        rows, pagination = client.get(
            "/recommendations/shows/" if is_show else "/recommendations/movies/", params
        )
        account_candidates = _normalize_recommendations(
            rows,
            is_show=is_show,
            max_results=max_results,
        )
        public_candidates = [
            item
            for row in (
                args.get("public_candidates", [])[:MAX_PUBLIC_CANDIDATES]
                if isinstance(args.get("public_candidates"), list)
                else []
            )
            if (item := _normalize_workflow_candidate(row, is_show=is_show))
        ]
        watched_items_checked = 0
        watched_pages_checked = 0
        public_excluded = 0
        account_excluded = 0
        watched_filter_applied = is_night_context and ignore_watched
        if watched_filter_applied:
            watched_keys, watched_items_checked, watched_pages_checked = _fetch_watched_identities(
                client,
                is_show=is_show,
            )
            public_candidates, public_excluded = _exclude_watched(public_candidates, watched_keys)
            account_candidates, account_excluded = _exclude_watched(
                account_candidates, watched_keys
            )

        eligible_candidates = _dedupe_candidates(public_candidates + account_candidates)
        payload = _common_payload(action, client)
        payload.update(
            {
                "results_count": len(account_candidates),
                "results": account_candidates,
                "candidates": account_candidates,
                "top_results": account_candidates[:5],
                "top_url": account_candidates[0].get("trakt_url") if account_candidates else None,
                "pagination": pagination,
                "request": request or None,
                "genre_hints": genres,
                "filters_used": params,
            }
        )
        if is_night_context:
            first_candidate = eligible_candidates[0] if eligible_candidates else {}
            second_candidate = eligible_candidates[1] if len(eligible_candidates) > 1 else {}
            third_candidate = eligible_candidates[2] if len(eligible_candidates) > 2 else {}
            payload.update(
                {
                    "eligible_public_candidates": public_candidates,
                    "eligible_candidates": eligible_candidates,
                    "enrichment_title": first_candidate.get("title") or "not returned",
                    "enrichment_year": first_candidate.get("year") or "not returned",
                    "second_eligible_title": second_candidate.get("title") or "not returned",
                    "third_eligible_title": third_candidate.get("title") or "not returned",
                    "watched_filter_applied": watched_filter_applied,
                    "watched_items_checked": watched_items_checked,
                    "watched_pages_checked": watched_pages_checked,
                    "watched_public_excluded_count": public_excluded,
                    "watched_account_excluded_count": account_excluded,
                    "watched_excluded_count": public_excluded + account_excluded,
                }
            )
        if is_show:
            payload["runtime_scope"] = "typical episode runtime"
        return payload

    if action in LIST_ACTIONS:
        media_type = str(args.get("media_type") or "movies").strip().lower()
        allowed_types = {"movies", "shows", "seasons", "episodes", "media"}
        if media_type not in allowed_types:
            raise TraktAccountError(
                "media_type must be movies, shows, seasons, episodes, or media."
            )
        sort_by = str(args.get("sort_by") or "rank").strip().lower()
        sort_how = str(args.get("sort_how") or "asc").strip().lower()
        if sort_how not in {"asc", "desc"}:
            raise TraktAccountError("sort_how must be asc or desc.")
        if action == "watchlist":
            path = f"/users/me/watchlist/{media_type}/{quote(sort_by, safe='')}/{sort_how}"
        elif action == "history":
            path = f"/users/me/history/{media_type}"
        elif action == "ratings":
            path = f"/users/me/ratings/{media_type}"
        elif action == "favorites":
            if media_type not in {"movies", "shows"}:
                raise TraktAccountError("favorites supports media_type movies or shows.")
            path = f"/users/me/favorites/{media_type}/{quote(sort_by, safe='')}/{sort_how}"
        else:
            list_id = str(args.get("list_id") or "").strip()
            if not list_id:
                raise TraktAccountError(f"list_id is required for {action}.")
            prefix = "/users/me/lists" if action == "personal_list_items" else "/smart-lists"
            path = f"{prefix}/{quote(list_id, safe='')}/items/{media_type}/{quote(sort_by, safe='')}/{sort_how}"
        rows, pagination = client.get(path, limit_params)
        return _list_payload(
            action, rows, pagination, client, source=action, max_results=max_results
        )

    if action in {"personal_lists", "smart_lists"}:
        path = "/users/me/lists" if action == "personal_lists" else "/users/me/smart-lists"
        rows, pagination = client.get(path, limit_params)
        results = [item for row in (rows or []) if (item := _normalize_list(row, action))][
            :max_results
        ]
        payload = _common_payload(action, client)
        payload.update(
            {
                "results_count": len(results),
                "results": results,
                "top_results": results[:5],
                "top_url": results[0].get("share_link") or results[0].get("trakt_url")
                if results
                else None,
                "pagination": pagination,
            }
        )
        return payload

    if action == "up_next":
        params = {
            **limit_params,
            "include_stats": str(bool(args.get("include_stats", True))).lower(),
        }
        rows, pagination = client.get("/sync/progress/up_next", params)
        return _list_payload(
            action, rows, pagination, client, source=action, max_results=max_results
        )

    raise TraktAccountError(f"Unsupported action '{action}'.")


def build_speech(data: dict[str, Any]) -> str:
    action = str(data.get("action") or "account").replace("_", " ")
    if data.get("action") == "status":
        username = (
            (data.get("user") or {}).get("username") if isinstance(data.get("user"), dict) else None
        )
        return f"Trakt account authorization is active{f' for {username}' if username else ''}."
    count = _safe_int(data.get("results_count")) or 0
    return f"Retrieved {count} read-only Trakt account {action} result(s)."


def _print_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False))


def main() -> int:
    try:
        load_config()
        try:
            args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        except (ValueError, IndexError):
            raise TraktAccountError("Invalid JSON input.")
        if not isinstance(args, dict):
            raise TraktAccountError("Input must be a JSON object.")
        client_id = str(get_config_value("TRAKT_API_KEY", "") or "").strip()
        client_secret = str(get_config_value("TRAKT_CLIENT_SECRET", "") or "").strip()
        redirect_uri = str(
            get_config_value("TRAKT_REDIRECT_URI", DEFAULT_REDIRECT_URI) or DEFAULT_REDIRECT_URI
        ).strip()
        if not client_id or not client_secret:
            raise TraktAccountError(
                "TRAKT_API_KEY and TRAKT_CLIENT_SECRET are required in the active Jarvis mode."
            )
        data = execute_action(TraktAccountClient(client_id, client_secret, redirect_uri), args)
        _print_result({"ok": True, "speech": build_speech(data), "data": data})
        return 0
    except TraktAccountError as exc:
        data = {
            key: value
            for key, value in {
                "status_code": exc.status_code,
                "retry_after": exc.retry_after,
                "endpoint": exc.endpoint,
                "vip_required": exc.vip_required or None,
                "vip_enhanced_limit": exc.vip_enhanced_limit or None,
                "upgrade_url": exc.upgrade_url,
                "vip_user": exc.vip_user,
                "account_limit": exc.account_limit,
                "source": "Trakt API account",
            }.items()
            if value not in (None, "")
        }
        _print_result({"ok": False, "speech": str(exc), "error": str(exc), "data": data})
        return 1
    except Exception as exc:
        message = f"Trakt account tool error: {exc.__class__.__name__}"
        _print_result({"ok": False, "speech": message, "error": message})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
