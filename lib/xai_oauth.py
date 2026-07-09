#!/usr/bin/env python3
"""Safe helpers for xAI Grok CLI OAuth authentication.

The official Grok CLI documents direct API access with the cached credentials
written by ``grok login``.  Jarvis uses that documented chat-proxy contract for
text/tool calls only; xAI media and TTS APIs still require ``XAI_API_KEY``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import shutil
import select
import stat
import struct
import subprocess
import termios
import time
from typing import Any


XAI_OAUTH_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
XAI_OAUTH_DEFAULT_MODEL = "grok-4.5"
XAI_OAUTH_REVIEWED_MODELS = ("grok-4.5", "grok-build")
_VALID_AUTH_MODES = {"auto", "api_key", "oauth"}
_VERSION_RE = re.compile(r"\bgrok\s+([0-9]+(?:\.[0-9]+){1,3})\b", re.IGNORECASE)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_MODEL_RE = re.compile(r"^\s*(?:\*|-)\s+([^\s(]+)")
_MODEL_CACHE: tuple[float, list[dict[str, str]]] | None = None
_MODEL_CACHE_TTL_SECONDS = 45
_USAGE_CACHE: tuple[float, dict[str, Any]] | None = None
_USAGE_CACHE_TTL_SECONDS = 60
_OSC_RE = re.compile(r"\x1b\][^\x07]*(?:\x07|\x1b\\)")
_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ESC_RE = re.compile(r"\x1b[=>]")


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
    models = list(XAI_OAUTH_REVIEWED_MODELS)
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
    if configured not in models and (
        configured != XAI_OAUTH_DEFAULT_MODEL or not models
    ):
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
            # Keep capabilities transport-scoped: the Grok CLI chat proxy is
            # treated as text-only until its image path is verified, even when
            # the same model ID is vision-capable through the xAI API key path.
            "capabilities": ["tools", "thinking"],
            "vision": False,
        })
    _MODEL_CACHE = (now, discovered)
    return [dict(item) for item in discovered]


def _strip_terminal_output(value: bytes | str) -> str:
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    text = _OSC_RE.sub("", text)
    text = _CSI_RE.sub("", text)
    text = _ESC_RE.sub("", text)
    text = text.replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text


def _format_oauth_reset(value: str) -> str:
    compact = re.sub(r"\s+", "", value)
    match = re.fullmatch(
        r"([A-Za-z]+)([0-9]{1,2}),([0-9]{1,2}:[0-9]{2})([A-Za-z]{2,4})",
        compact,
    )
    if not match:
        return value.strip()
    month, day, time_value, zone = match.groups()
    return f"{month} {day}, {time_value} {zone}"


def parse_xai_oauth_usage_output(output: bytes | str) -> dict[str, Any]:
    """Extract the high-level Grok CLI subscription usage fields."""

    text = _strip_terminal_output(output)
    compact = re.sub(r"\s+", "", text)

    weekly_match = re.search(
        r"Weeklylimit:([0-9]+(?:\.[0-9]+)?%)",
        compact,
        re.IGNORECASE,
    )
    reset_match = re.search(
        r"Nextreset:([A-Za-z]+[0-9]{1,2},[0-9]{1,2}:[0-9]{2}[A-Za-z]{2,4})",
        compact,
        re.IGNORECASE,
    )

    result: dict[str, Any] = {}
    if weekly_match:
        label = weekly_match.group(1)
        result["weekly_limit_label"] = label
        try:
            result["weekly_limit_percent"] = float(label.rstrip("%"))
        except ValueError:
            pass
    if reset_match:
        result["next_reset"] = _format_oauth_reset(reset_match.group(1))
    return result


def get_xai_oauth_usage(
    cli_path: str | None = None,
    *,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Return high-level Grok CLI OAuth quota from the interactive /usage command."""

    global _USAGE_CACHE
    now = time.monotonic()
    if use_cache and _USAGE_CACHE and now - _USAGE_CACHE[0] < _USAGE_CACHE_TTL_SECONDS:
        return dict(_USAGE_CACHE[1])

    command = [
        cli_path or get_grok_cli_path(),
        "--no-auto-update",
        "--no-alt-screen",
    ]
    env = os.environ.copy()
    env.pop("XAI_API_KEY", None)
    env.setdefault("TERM", "xterm-256color")

    master_fd: int | None = None
    process: subprocess.Popen[bytes] | None = None
    chunks: list[bytes] = []
    try:
        master_fd, slave_fd = pty.openpty()
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
        process = subprocess.Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            env=env,
        )
        os.close(slave_fd)

        start = time.monotonic()
        sent_usage = False
        sent_interrupt = False
        while time.monotonic() - start < 15:
            ready, _, _ = select.select([master_fd], [], [], 0.2)
            if ready:
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
                # Some terminal UIs ask for cursor position. Answer so startup
                # can proceed in this synthetic PTY.
                if b"\x1b[6n" in data:
                    os.write(master_fd, b"\x1b[1;1R")

            elapsed = time.monotonic() - start
            if not sent_usage and elapsed > 3:
                os.write(master_fd, b"/usage show\r")
                sent_usage = True
            if sent_usage:
                parsed = parse_xai_oauth_usage_output(b"".join(chunks))
                if parsed.get("weekly_limit_label") or parsed.get("next_reset"):
                    result = {
                        "available": True,
                        "source": "grok_cli_usage",
                        **parsed,
                    }
                    _USAGE_CACHE = (now, result)
                    return dict(result)
            if sent_usage and not sent_interrupt and elapsed > 10:
                os.write(master_fd, b"\x03")
                sent_interrupt = True
            if process.poll() is not None:
                break
    except (OSError, subprocess.SubprocessError) as exc:
        raise XaiOAuthError("Could not read Grok OAuth usage from the CLI") from exc
    finally:
        if master_fd is not None:
            try:
                os.close(master_fd)
            except OSError:
                pass
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()

    raise XaiOAuthError("Grok OAuth usage was not reported by the CLI")


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


def get_xai_oauth_status(
    *,
    check_models: bool = False,
    check_usage: bool = False,
) -> dict[str, Any]:
    """Return sanitized local OAuth readiness for settings/status surfaces."""

    result: dict[str, Any] = {
        "connection": "oauth",
        "signed_in": False,
        "status": "unavailable",
        "reason": None,
        "usage_available": False,
        "usage_note": "Grok CLI OAuth usage is subscription-scoped, not xAI API console usage",
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
        if check_usage:
            try:
                usage = get_xai_oauth_usage()
            except XaiOAuthError as exc:
                result.update(
                    usage_available=False,
                    usage_note=str(exc),
                )
            else:
                result.update(
                    usage_available=True,
                    oauth_usage=usage,
                    usage_note="High-level Grok CLI subscription quota",
                )
    except XaiOAuthError as exc:
        result.update(
            signed_in=False,
            status="unavailable",
            reason=str(exc),
        )
    return result
