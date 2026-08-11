#!/usr/bin/env python3
"""Secure Trakt OAuth device-flow and rotating-token cache helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

try:
    from config_loader import get_project_root
    from http_client import http_request
except ImportError:  # pragma: no cover - package import
    from lib.config_loader import get_project_root
    from lib.http_client import http_request


AUTH_BASE_URL = "https://auth.trakt.tv"
DEFAULT_REDIRECT_URI = "urn:ietf:wg:oauth:2.0:oob"
DEFAULT_TIMEOUT_SECONDS = 20
REFRESH_SKEW_SECONDS = 300
TOKEN_CACHE_VERSION = 1


class TraktOAuthError(RuntimeError):
    """Sanitized authentication failure safe to return to a tool caller."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class TraktOAuthCredentials:
    access_token: str
    refresh_token: str
    expires_at: int
    token_type: str = "bearer"
    scope: str = "public"


def token_cache_path() -> Path:
    return get_project_root() / "data" / ".trakt_oauth.json"


def _client_fingerprint(client_id: str) -> str:
    return hashlib.sha256(client_id.encode("utf-8")).hexdigest()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _require_private_permissions(path: Path) -> None:
    if os.name == "nt" or not path.exists():
        return
    if path.stat().st_mode & 0o077:
        raise TraktOAuthError(
            f"Trakt OAuth cache permissions are too broad; run: chmod 600 {path}"
        )


def _read_cache_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TraktOAuthError("Trakt is not authorized. Run ./bin/trakt-auth first.")
    _require_private_permissions(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TraktOAuthError("The Trakt OAuth cache is unreadable; run ./bin/trakt-auth again.") from exc
    if not isinstance(payload, dict) or payload.get("version") != TOKEN_CACHE_VERSION:
        raise TraktOAuthError("The Trakt OAuth cache format is invalid; run ./bin/trakt-auth again.")
    return payload


def _credentials_from_payload(payload: dict[str, Any], client_id: str) -> TraktOAuthCredentials:
    if payload.get("client_id_sha256") != _client_fingerprint(client_id):
        raise TraktOAuthError(
            "The Trakt OAuth cache belongs to a different Client ID; run ./bin/trakt-auth again."
        )
    access_token = str(payload.get("access_token") or "").strip()
    refresh_token = str(payload.get("refresh_token") or "").strip()
    if not access_token or not refresh_token:
        raise TraktOAuthError("The Trakt OAuth cache is incomplete; run ./bin/trakt-auth again.")
    return TraktOAuthCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=_safe_int(payload.get("expires_at")),
        token_type=str(payload.get("token_type") or "bearer"),
        scope=str(payload.get("scope") or "public"),
    )


def save_token_response(
    token_data: dict[str, Any],
    *,
    client_id: str,
    redirect_uri: str,
    path: Path | None = None,
    now: int | None = None,
) -> TraktOAuthCredentials:
    """Validate and atomically persist one Trakt token response with mode 0600."""
    destination = path or token_cache_path()
    created_at = _safe_int(token_data.get("created_at"), now or int(time.time()))
    expires_in = _safe_int(token_data.get("expires_in"))
    access_token = str(token_data.get("access_token") or "").strip()
    refresh_token = str(token_data.get("refresh_token") or "").strip()
    if not access_token or not refresh_token or expires_in <= 0:
        raise TraktOAuthError("Trakt returned an incomplete OAuth token response.")
    payload = {
        "version": TOKEN_CACHE_VERSION,
        "client_id_sha256": _client_fingerprint(client_id),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": str(token_data.get("token_type") or "bearer"),
        "scope": str(token_data.get("scope") or "public"),
        "created_at": created_at,
        "expires_in": expires_in,
        "expires_at": created_at + expires_in,
        "redirect_uri": redirect_uri,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, destination)
        if os.name != "nt":
            destination.chmod(0o600)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return _credentials_from_payload(payload, client_id)


def _post_oauth(
    path: str,
    body: dict[str, Any],
    *,
    request_func: Callable[..., requests.Response] = http_request,
) -> requests.Response:
    if not path.startswith("/oauth/") or "://" in path:
        raise TraktOAuthError("Invalid Trakt OAuth endpoint.")
    try:
        return request_func(
            "POST",
            f"{AUTH_BASE_URL}{path}",
            json=body,
            headers={"Content-Type": "application/json", "User-Agent": "JarvisVoice/TraktOAuth-1.0"},
            timeout=DEFAULT_TIMEOUT_SECONDS,
            use_proxy=True,
            fallback_on_proxy_fail=True,
        )
    except requests.RequestException as exc:
        raise TraktOAuthError(f"Trakt authorization request failed: {exc.__class__.__name__}") from exc


def request_device_code(
    client_id: str,
    *,
    request_func: Callable[..., requests.Response] = http_request,
) -> dict[str, Any]:
    response = _post_oauth("/oauth/device/code", {"client_id": client_id}, request_func=request_func)
    if not response.ok:
        raise TraktOAuthError(
            f"Trakt device authorization returned HTTP {response.status_code}.",
            status_code=response.status_code,
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise TraktOAuthError("Trakt returned invalid device authorization JSON.") from exc
    required = ("device_code", "user_code", "verification_url", "expires_in", "interval")
    if not isinstance(payload, dict) or any(not payload.get(key) for key in required):
        raise TraktOAuthError("Trakt returned an incomplete device authorization response.")
    return payload


def poll_device_token(
    device_code: str,
    *,
    client_id: str,
    client_secret: str,
    interval: int,
    expires_in: int,
    request_func: Callable[..., requests.Response] = http_request,
    sleep_func: Callable[[float], None] = time.sleep,
    monotonic_func: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    deadline = monotonic_func() + max(1, expires_in)
    delay = max(1, interval)
    while monotonic_func() < deadline:
        response = _post_oauth(
            "/oauth/device/token",
            {"code": device_code, "client_id": client_id, "client_secret": client_secret},
            request_func=request_func,
        )
        if response.ok:
            try:
                payload = response.json()
            except ValueError as exc:
                raise TraktOAuthError("Trakt returned invalid OAuth token JSON.") from exc
            if not isinstance(payload, dict):
                raise TraktOAuthError("Trakt returned invalid OAuth token JSON.")
            return payload
        if response.status_code == 400:  # authorization pending
            sleep_func(delay)
            continue
        if response.status_code == 429:  # slow down
            delay += 1
            sleep_func(delay)
            continue
        messages = {
            404: "The Trakt device code is invalid.",
            409: "The Trakt device code was already used.",
            410: "The Trakt device code expired.",
            418: "Trakt authorization was denied.",
        }
        raise TraktOAuthError(
            messages.get(response.status_code, f"Trakt authorization returned HTTP {response.status_code}."),
            status_code=response.status_code,
        )
    raise TraktOAuthError("The Trakt device authorization window expired.")


def get_fresh_credentials(
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str = DEFAULT_REDIRECT_URI,
    path: Path | None = None,
    force_refresh: bool = False,
    request_func: Callable[..., requests.Response] = http_request,
    now_func: Callable[[], float] = time.time,
) -> TraktOAuthCredentials:
    """Load the cache and rotate Trakt's single-use refresh token under a lock."""
    from filelock import FileLock

    cache_path = path or token_cache_path()
    lock = FileLock(f"{cache_path}.lock", timeout=20)
    with lock:
        payload = _read_cache_payload(cache_path)
        credentials = _credentials_from_payload(payload, client_id)
        now = int(now_func())
        if not force_refresh and credentials.expires_at > now + REFRESH_SKEW_SECONDS:
            return credentials

        response = _post_oauth(
            "/oauth/token",
            {
                "refresh_token": credentials.refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "refresh_token",
            },
            request_func=request_func,
        )
        if not response.ok:
            if response.status_code == 400:
                raise TraktOAuthError(
                    "Trakt rejected the refresh token; run ./bin/trakt-auth again.",
                    status_code=400,
                )
            raise TraktOAuthError(
                f"Trakt token refresh returned HTTP {response.status_code}.",
                status_code=response.status_code,
            )
        try:
            token_data = response.json()
        except ValueError as exc:
            raise TraktOAuthError("Trakt returned invalid token refresh JSON.") from exc
        if not isinstance(token_data, dict):
            raise TraktOAuthError("Trakt returned invalid token refresh JSON.")
        return save_token_response(
            token_data,
            client_id=client_id,
            redirect_uri=redirect_uri,
            path=cache_path,
            now=now,
        )
