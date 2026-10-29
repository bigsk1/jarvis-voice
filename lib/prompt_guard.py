"""Optional classification client for a remote Prompt Guard scanner.

The client never authorizes an action or changes supplied content. Callers decide
how to handle a reported detection; disabled, skipped and failed scans remain
unknown rather than safe. Only credential-free diagnostics are logged; submitted
text is never retained here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

import requests

try:
    from config_loader import config_scope, get_active_config_mode, get_config_value
except ModuleNotFoundError as exc:
    if exc.name != "config_loader":
        raise
    from lib.config_loader import config_scope, get_active_config_mode, get_config_value

logger = logging.getLogger("prompt_guard")

DEFAULT_MAX_INPUT_BYTES = 8192
MAX_INPUT_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024
COOLDOWN_SECONDS = 30.0
MAX_BACKENDS = 64
_SOURCE_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
_REQUEST_ID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MODEL_REVISION = re.compile(r"[0-9a-fA-F]{40}\Z")
_capacity = threading.BoundedSemaphore(1)
_state_lock = threading.Lock()


@dataclass(frozen=True, slots=True)
class PromptGuardResult:
    """A scan observation, never a permission or a claim that content is safe."""

    status: Literal["scanned", "disabled", "skipped", "unknown"]
    reason_code: str | None = None
    flagged: bool | None = None
    injection_score: float | None = None
    threshold: float | None = None
    coverage_complete: bool | None = None
    windows_scanned: int | None = None
    input_bytes: int = 0
    elapsed_ms: float = 0.0
    service_request_id: str | None = None
    model_id: str | None = None
    model_revision: str | None = None


@dataclass(frozen=True, slots=True)
class _ScanResponse:
    score: float
    flagged: bool
    windows: int
    service_request_id: str | None
    model_id: str | None
    model_revision: str | None


@dataclass(frozen=True, slots=True)
class _Settings:
    url: str
    key: str = field(repr=False)
    threshold: float
    timeout: float
    max_input_bytes: int


@dataclass(slots=True)
class _BackendState:
    retry_after: float = 0.0
    unavailable: bool = False
    logged_at: dict[str, float] = field(default_factory=dict)


_states: OrderedDict[tuple[str, str, str], _BackendState] = OrderedDict()


def _log(level: int, message: str, *args: object) -> None:
    try:
        logger.log(level, message, *args)
    except Exception:
        # Diagnostics are best effort too: a broken handler cannot turn an
        # optional observation into a tool failure or a lost scan result.
        pass


def is_enabled() -> bool:
    """Read the selected mode's opt-in flag without changing process config."""
    return str(get_config_value("PROMPT_GUARD_ENABLED", "false") or "").strip().lower() in {
        "true", "1", "yes", "on",
    }


def get_max_input_bytes() -> int:
    """Return the current extraction bound, defaulting safely for invalid config."""
    try:
        value = int(str(get_config_value("PROMPT_GUARD_MAX_INPUT_BYTES", DEFAULT_MAX_INPUT_BYTES)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_INPUT_BYTES
    return value if 1 <= value <= MAX_INPUT_BYTES else DEFAULT_MAX_INPUT_BYTES


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("invalid_number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("invalid_number")
    return number


def _settings() -> _Settings:
    url = str(get_config_value("PROMPT_GUARD_URL", "") or "").strip().rstrip("/")
    key = str(get_config_value("PROMPT_GUARD_API_KEY", "") or "").strip()
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path
            or any(character.isspace() for character in url)):
        raise ValueError("invalid_configuration")
    # Accessing .port also rejects malformed or out-of-range ports.
    if parsed.port is not None and parsed.port < 1:
        raise ValueError("invalid_configuration")
    if not key or any(character in key for character in "\r\n"):
        raise ValueError("invalid_configuration")
    threshold = float(str(get_config_value("PROMPT_GUARD_THRESHOLD", "0.8")))
    timeout = float(str(get_config_value("PROMPT_GUARD_TIMEOUT_SECONDS", "2.0")))
    maximum = int(str(get_config_value("PROMPT_GUARD_MAX_INPUT_BYTES", DEFAULT_MAX_INPUT_BYTES)))
    if (not math.isfinite(threshold) or not 0 <= threshold <= 1
            or not math.isfinite(timeout) or not 0.05 <= timeout <= 30
            or not 1 <= maximum <= MAX_INPUT_BYTES):
        raise ValueError("invalid_configuration")
    return _Settings(url, key, threshold, timeout, maximum)


def _state(key: tuple[str, str, str]) -> _BackendState:
    """Access bounded process-local state while holding _state_lock."""
    state = _states.setdefault(key, _BackendState())
    _states.move_to_end(key)
    while len(_states) > MAX_BACKENDS:
        _states.popitem(last=False)
    return state


def _log_once(key: tuple[str, str, str], reason: str, *, level: int, mode: str) -> None:
    now = time.monotonic()
    with _state_lock:
        state = _state(key)
        previous = state.logged_at.get(reason)
        if previous is not None and now - previous < COOLDOWN_SECONDS:
            return
        state.logged_at[reason] = now
    _log(level, "[PROMPT_GUARD] mode=%s reason=%s action=continue", mode, reason)


def _invalid_json_constant(_value: str) -> None:
    raise ValueError("invalid_json")


def _identifier(value: object, pattern: re.Pattern[str]) -> str | None:
    # Optional service metadata is diagnostic, not part of the verdict. Discard
    # malformed values without copying arbitrary service content into receipts.
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _parse_response(raw: bytes, threshold: float) -> _ScanResponse:
    data = json.loads(raw, parse_constant=_invalid_json_constant)
    if not isinstance(data, dict) or data.get("status") != "ok":
        raise ValueError("invalid_response")
    score = _number(data.get("injection_score"))
    observed_threshold = _number(data.get("threshold"))
    flagged = data.get("flagged")
    coverage = data.get("coverage")
    if (not 0 <= score <= 1 or not math.isclose(observed_threshold, threshold, abs_tol=1e-9)
            or type(flagged) is not bool or flagged != (score >= threshold)
            or not isinstance(coverage, dict) or coverage.get("complete") is not True
            or coverage.get("truncated") is not False):
        raise ValueError("invalid_response")
    scanned, total = coverage.get("windows_scanned"), coverage.get("windows_total")
    if type(scanned) is not int or type(total) is not int or scanned < 1 or scanned != total:
        raise ValueError("invalid_response")
    model = data.get("model")
    if not isinstance(model, dict):
        model = {}
    return _ScanResponse(
        score, flagged, scanned,
        _identifier(data.get("request_id"), _REQUEST_ID),
        _identifier(model.get("id"), _MODEL_ID),
        _identifier(model.get("revision"), _MODEL_REVISION),
    )


def _scan_text(text: str, *, source_type: str, source_name: str) -> PromptGuardResult:
    started = time.monotonic()
    mode = get_active_config_mode()
    input_bytes = 0

    def result(status, reason=None, **fields) -> PromptGuardResult:
        return PromptGuardResult(status, reason, input_bytes=input_bytes,
                                 elapsed_ms=(time.monotonic() - started) * 1000, **fields)

    if not is_enabled():
        _log_once((mode, "", ""), "disabled", level=logging.INFO, mode=mode)
        return result("disabled", "disabled")
    try:
        settings = _settings()
    except (TypeError, ValueError):
        _log_once((mode, "", ""), "invalid_configuration", level=logging.WARNING, mode=mode)
        return result("unknown", "invalid_configuration")
    key = (mode, settings.url, hashlib.sha256(settings.key.encode()).hexdigest())
    if (not isinstance(source_type, str) or not _SOURCE_NAME.fullmatch(source_type)
            or not isinstance(source_name, str) or not _SOURCE_NAME.fullmatch(source_name)):
        return result("skipped", "invalid_source", threshold=settings.threshold)
    if not isinstance(text, str) or not text.strip():
        return result("skipped", "empty_input", threshold=settings.threshold)
    try:
        input_bytes = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        return result("skipped", "invalid_text", threshold=settings.threshold)
    if input_bytes > settings.max_input_bytes:
        _log_once(key, "input_too_large", level=logging.INFO, mode=mode)
        return result("skipped", "input_too_large", threshold=settings.threshold)
    with _state_lock:
        cooling_down = time.monotonic() < _state(key).retry_after
    if cooling_down:
        return result("skipped", "cooldown", threshold=settings.threshold)
    if not _capacity.acquire(blocking=False):
        return result("skipped", "busy", threshold=settings.threshold)
    reason = "unexpected_error"
    try:
        # Socket timeouts limit connect/read inactivity. They are not a strict
        # wall-clock deadline; the bounded input and response also limit work.
        deadline = time.monotonic() + settings.timeout
        with requests.Session() as session:
            session.trust_env = False  # No ambient proxies or ~/.netrc auth.
            with session.post(
                settings.url + "/v1/scan",
                json={"text": text, "threshold": settings.threshold,
                      "source": {"type": source_type, "name": source_name}},
                headers={"Authorization": "Bearer " + settings.key, "Accept": "application/json"},
                timeout=(min(0.3, settings.timeout / 4), settings.timeout * 0.75),
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.status_code != 200:
                    reason = f"http_{int(response.status_code)}"
                    raise ValueError("http_status")
                reason = "invalid_response"
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                if content_type != "application/json":
                    raise ValueError("invalid_content_type")
                raw = bytearray()
                for block in response.iter_content(1024):
                    if time.monotonic() > deadline:
                        reason = "timeout"
                        raise ValueError("deadline_exceeded")
                    raw.extend(block)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        reason = "response_too_large"
                        raise ValueError("response_too_large")
                observation = _parse_response(bytes(raw), settings.threshold)
        with _state_lock:
            state = _state(key)
            recovered = state.unavailable
            state.unavailable = False
            state.retry_after = 0.0
        if recovered:
            _log(logging.INFO, "[PROMPT_GUARD] mode=%s reason=recovered action=continue", mode)
        _log(
            logging.WARNING if observation.flagged else logging.DEBUG,
            "[PROMPT_GUARD] mode=%s source_type=%s source=%s status=scanned flagged=%s "
            "score=%.6f threshold=%.6f bytes=%s windows=%s elapsed_ms=%.1f action=reported",
            mode, source_type, source_name, observation.flagged, observation.score, settings.threshold,
            input_bytes, observation.windows, (time.monotonic() - started) * 1000,
        )
        return result("scanned", flagged=observation.flagged, injection_score=observation.score,
                      threshold=settings.threshold, coverage_complete=True,
                      windows_scanned=observation.windows,
                      service_request_id=observation.service_request_id,
                      model_id=observation.model_id, model_revision=observation.model_revision)
    except requests.exceptions.Timeout:
        reason = "timeout"
    except requests.exceptions.RequestException:
        reason = "transport_error"
    except (ValueError, TypeError, UnicodeError):
        pass  # All error details are intentionally replaced with safe codes.
    except Exception:
        reason = "unexpected_error"
    finally:
        _capacity.release()
    with _state_lock:
        state = _state(key)
        state.unavailable = True
        state.retry_after = time.monotonic() + COOLDOWN_SECONDS
    _log_once(key, reason, level=logging.WARNING, mode=mode)
    return result("unknown", reason, threshold=settings.threshold)


def scan_text(
    text: str, *, source_type: str, source_name: str, mode: str | None = None,
) -> PromptGuardResult:
    """Classify text without changing it, preserving matching scoped overrides.

    ``source_type`` and ``source_name`` must be short caller-owned identifiers,
    never a query, document title, URL or other external content. A validated
    detection is reported to the caller, which owns the content-handling policy.
    """
    try:
        scope = config_scope(mode) if mode is not None and mode != get_active_config_mode() else nullcontext()
        with scope:
            return _scan_text(text, source_type=source_type, source_name=source_name)
    except Exception:
        # A configuration/observer bug must not convert a completed tool into a
        # failure. Do not print exception text, which may contain secrets.
        _log(logging.WARNING, "[PROMPT_GUARD] reason=observer_error action=continue")
        return PromptGuardResult("unknown", "observer_error")
