#!/usr/bin/env python3
"""Safe helpers for xAI Grok CLI OAuth authentication.

The official Grok CLI documents direct API access with the cached credentials
written by ``grok login``.  Jarvis uses that documented chat-proxy contract for
text/tool calls only; xAI media and TTS APIs still require ``XAI_API_KEY``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
from typing import Any


XAI_OAUTH_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
XAI_OAUTH_DEFAULT_MODEL = "grok-build"
_VALID_AUTH_MODES = {"auto", "api_key", "oauth"}
_VERSION_RE = re.compile(r"\bgrok\s+([0-9]+(?:\.[0-9]+){1,3})\b", re.IGNORECASE)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_MODEL_RE = re.compile(r"^\s*(?:\*|-)\s+([^\s(]+)")
_MODEL_CACHE: tuple[float, list[dict[str, str]]] | None = None
_MODEL_CACHE_TTL_SECONDS = 45


class XaiOAuthError(RuntimeError):
    """Raised when Grok CLI OAuth cannot be used safely."""


@dataclass(frozen=True)
class XaiOAuthCredentials:
    """One cached Grok OAuth session.  Token values must never be logged."""

    token: str
    account_id: str
    expires_at: datetime | None
    auth_file: Path
    mtime_ns: int

    @property
    def expired(self) -> bool:
        return bool(self.expires_at and self.expires_at <= datetime.now(timezone.utc))


def _config_value(name: str, default: str = "") -> str:
    try:
        from config_loader import get_config_value

        value = get_config_value(name, default)
    except Exception:
        value = os.environ.get(name, default)
    return str(value or "").strip()


def get_xai_auth_mode(api_key: str | None = None, configured_mode: str | None = None) -> str:
    """Resolve ``auto`` to the concrete authentication path Jarvis will use."""

    raw_mode = (configured_mode or _config_value("XAI_AUTH_MODE", "auto")).strip().lower()
    if raw_mode not in _VALID_AUTH_MODES:
        raise XaiOAuthError(
            f"Invalid XAI_AUTH_MODE={raw_mode!r}; expected auto, api_key, or oauth"
        )
    key_present = bool(str(api_key if api_key is not None else _config_value("XAI_API_KEY", "")).strip())
    if raw_mode == "auto":
        return "api_key" if key_present else "oauth"
    return raw_mode


def xai_native_search_configured(api_key: str | None = None) -> bool:
    """Whether config/auth can support xAI SDK server-side tools.

    OAuth chat-proxy sessions support Jarvis function calls, but not the xAI
    SDK Agent Tools path used by ``XAI_SEARCH``.
    """

    if _config_value("XAI_SEARCH", "false").lower() != "true":
        return False
    try:
        return get_xai_auth_mode(api_key) == "api_key"
    except XaiOAuthError:
        return False


def get_xai_oauth_auth_file() -> Path:
    configured = _config_value("XAI_OAUTH_AUTH_FILE", "")
    return Path(configured).expanduser() if configured else Path.home() / ".grok" / "auth.json"


def _parse_expiry(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _credential_candidates(payload: Any):
    if not isinstance(payload, dict):
        return
    for account_id, value in payload.items():
        if isinstance(value, dict) and isinstance(value.get("key"), str):
            yield str(account_id), value


def load_xai_oauth_credentials(
    auth_file: Path | None = None,
    *,
    allow_expired: bool = False,
) -> XaiOAuthCredentials:
    """Load the Grok CLI session while rejecting insecure credential files."""

    path = (auth_file or get_xai_oauth_auth_file()).expanduser()
    try:
        file_stat = path.stat()
    except FileNotFoundError as exc:
        raise XaiOAuthError(f"Grok OAuth session not found; run `grok login` ({path})") from exc

    if not stat.S_ISREG(file_stat.st_mode):
        raise XaiOAuthError(f"Grok OAuth auth path is not a regular file: {path}")
    if file_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise XaiOAuthError(
            f"Grok OAuth auth file permissions are too broad; run `chmod 600 {path}`"
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise XaiOAuthError(f"Could not read Grok OAuth session from {path}") from exc

    candidates: list[XaiOAuthCredentials] = []
    for account_id, entry in _credential_candidates(payload):
        token = entry.get("key", "").strip()
        if not token:
            continue
        candidates.append(
            XaiOAuthCredentials(
                token=token,
                account_id=account_id,
                expires_at=_parse_expiry(entry.get("expires_at")),
                auth_file=path,
                mtime_ns=file_stat.st_mtime_ns,
            )
        )

    if not candidates:
        raise XaiOAuthError(f"No Grok OAuth session found in {path}; run `grok login`")

    # Prefer the session with the furthest known expiry.  Unknown expiry sorts
    # behind known valid sessions but remains usable for older CLI formats.
    credentials = max(
        candidates,
        key=lambda item: item.expires_at or datetime.min.replace(tzinfo=timezone.utc),
    )
    if credentials.expired and not allow_expired:
        raise XaiOAuthError("Grok OAuth session has expired; run `grok login` again")
    return credentials


def get_grok_cli_path() -> str:
    configured = _config_value("GROK_CLI_PATH", "")
    resolved = configured or shutil.which("grok")
    if not resolved:
        raise XaiOAuthError("Grok CLI not found; install it or set GROK_CLI_PATH")
    return resolved


def get_grok_cli_version(cli_path: str | None = None) -> str:
    """Return the version required by the official chat proxy headers."""

    command = [cli_path or get_grok_cli_path(), "--no-auto-update", "--version"]
    env = os.environ.copy()
    env.pop("XAI_API_KEY", None)
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise XaiOAuthError("Could not read the installed Grok CLI version") from exc
    match = _VERSION_RE.search(f"{result.stdout}\n{result.stderr}")
    if not match:
        raise XaiOAuthError("Could not parse the installed Grok CLI version")
    return match.group(1)


def build_xai_oauth_headers(model: str, cli_version: str) -> dict[str, str]:
    """Headers documented by the Grok CLI for OAuth chat-proxy access."""

    return {
        "X-XAI-Token-Auth": "xai-grok-cli",
        "x-grok-model-override": model,
        "x-grok-client-version": cli_version,
        "x-grok-client-identifier": "xai-grok-cli",
    }


def get_xai_oauth_allowed_models() -> tuple[str, ...]:
    """Return reviewed OAuth chat models plus explicit operator opt-ins."""

    configured = _config_value("XAI_OAUTH_ALLOWED_MODELS", "")
    models = [XAI_OAUTH_DEFAULT_MODEL]
    for value in configured.split(","):
        normalized = value.strip().lower()
        if normalized and normalized not in models:
            models.append(normalized)
    # Composer is a coding agent with its own filesystem tools, not a safe
    # drop-in Jarvis chat model, even when an operator accidentally lists it.
    return tuple(model for model in models if not model.startswith("grok-composer"))


def is_xai_oauth_model(model: str | None) -> bool:
    """Allow reviewed models and explicit non-Composer operator opt-ins."""

    return (model or "").strip().lower() in get_xai_oauth_allowed_models()


def get_xai_oauth_model(requested_model: str | None = None) -> str:
    configured = _config_value("XAI_OAUTH_MODEL", XAI_OAUTH_DEFAULT_MODEL)
    requested = (requested_model or "").strip()
    if is_xai_oauth_model(requested):
        return requested
    if is_xai_oauth_model(configured):
        return configured
    return XAI_OAUTH_DEFAULT_MODEL


def discover_xai_oauth_models(
    cli_path: str | None = None,
    *,
    use_cache: bool = True,
) -> list[dict[str, object]]:
    """Discover supported OAuth chat models from ``grok models`` output."""

    global _MODEL_CACHE
    now = time.monotonic()
    if use_cache and _MODEL_CACHE and now - _MODEL_CACHE[0] < _MODEL_CACHE_TTL_SECONDS:
        return [dict(item) for item in _MODEL_CACHE[1]]

    command = [cli_path or get_grok_cli_path(), "--no-auto-update", "models"]
    env = os.environ.copy()
    env.pop("XAI_API_KEY", None)
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise XaiOAuthError("Could not discover Grok OAuth models") from exc

    models: list[str] = []
    output = _ANSI_RE.sub("", f"{result.stdout}\n{result.stderr}")
    for line in output.splitlines():
        match = _MODEL_RE.match(line)
        if not match:
            continue
        model = match.group(1).strip()
        if is_xai_oauth_model(model) and model not in models:
            models.append(model)

    configured = get_xai_oauth_model()
    if configured not in models:
        models.insert(0, configured)
    try:
        from model_catalog import get_model_context_label
    except ImportError:
        get_model_context_label = None
    discovered = []
    for model in models:
        context = get_model_context_label("xai", model) if get_model_context_label else None
        discovered.append({
            "id": model,
            "name": model,
            "context": context or "OAuth subscription",
            "auth": "oauth",
            # The Grok CLI chat proxy currently accepts text only even though
            # the similarly named xAI API model accepts image input.
            "capabilities": ["tools", "thinking"],
            "vision": False,
        })
    _MODEL_CACHE = (now, discovered)
    return [dict(item) for item in discovered]


def refresh_xai_oauth_credentials(cli_path: str | None = None) -> XaiOAuthCredentials:
    """Ask the official CLI to refresh its session, then reload the cache.

    The refresh token stays inside the CLI-owned auth flow.  Jarvis never
    parses, transmits, or logs it.
    """

    command = [cli_path or get_grok_cli_path(), "--no-auto-update", "models"]
    env = os.environ.copy()
    env.pop("XAI_API_KEY", None)
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise XaiOAuthError("Grok OAuth refresh failed; run `grok login` again") from exc
    return load_xai_oauth_credentials()


def get_fresh_xai_oauth_credentials() -> XaiOAuthCredentials:
    """Load a valid session, delegating an expired-session refresh to Grok CLI."""

    credentials = load_xai_oauth_credentials(allow_expired=True)
    if credentials.expired:
        return refresh_xai_oauth_credentials()
    return credentials


def get_xai_oauth_status(*, check_models: bool = False) -> dict[str, Any]:
    """Return sanitized local OAuth readiness for settings/status surfaces."""

    result: dict[str, Any] = {
        "connection": "oauth",
        "signed_in": False,
        "status": "unavailable",
        "reason": None,
        "usage_available": False,
        "usage_note": "xAI does not expose subscription quota through this API",
    }
    try:
        credentials = get_fresh_xai_oauth_credentials()
        version = get_grok_cli_version()
        result.update(
            signed_in=True,
            status="available",
            expires_at=credentials.expires_at.isoformat() if credentials.expires_at else None,
            cli_version=version,
        )
        if check_models:
            result["models"] = discover_xai_oauth_models()
    except XaiOAuthError as exc:
        result.update(
            signed_in=False,
            status="unavailable",
            reason=str(exc),
        )
    return result
