"""Fail-open event publisher for the optional Jarvis Head display."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

MAX_DATAGRAM_BYTES = 4096
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def get_socket_path(
    override: str | os.PathLike[str] | None = None,
    *,
    uid: int | None = None,
    xdg_runtime_dir: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve the configured socket path without requiring the display stack."""

    if override is None:
        override = _config_value("JARVIS_HEAD_SOCKET", "")
    configured = str(override or "").strip()
    if configured:
        return Path(configured).expanduser()

    if xdg_runtime_dir is None:
        xdg_runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
    runtime_dir = str(xdg_runtime_dir or "").strip()
    if runtime_dir:
        return Path(runtime_dir).expanduser() / "jarvis" / "head.sock"

    resolved_uid = os.getuid() if uid is None else uid
    return Path("/tmp") / f"jarvis-head-{resolved_uid}" / "head.sock"


def emit(event_type: str, /, **payload: Any) -> bool:
    """Send one bounded nonblocking datagram, returning False on every failure."""

    try:
        enabled = _config_bool("JARVIS_HEAD_ENABLED", False)
    except Exception:
        return False
    if not enabled:
        return False

    try:
        encoded = json.dumps(
            {**payload, "type": event_type},
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if not encoded or len(encoded) > MAX_DATAGRAM_BYTES:
            raise ValueError(f"event exceeds {MAX_DATAGRAM_BYTES} bytes")

        destination = get_socket_path()
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sender:
            sender.setblocking(False)
            sent = sender.sendto(encoded, os.fspath(destination))
        return sent == len(encoded)
    except Exception as exc:
        _debug_failure(event_type, exc)
        return False


def _config_value(key: str, default: Any = None) -> Any:
    # Import lazily so disabled Jarvis callers never load the display stack.
    try:
        from config_loader import get_config_value
    except ModuleNotFoundError:
        from lib.config_loader import get_config_value

    return get_config_value(key, default)


def _config_bool(key: str, default: bool) -> bool:
    value = _config_value(key, str(default))
    return str(value or "").strip().lower() in _TRUE_VALUES


def _debug_failure(event_type: str, exc: Exception) -> None:
    try:
        debug_enabled = _config_bool("JARVIS_HEAD_DEBUG", False)
    except Exception:
        return
    if not debug_enabled:
        return
    event_label = str(event_type)[:48]
    detail = str(exc).replace("\n", " ")[:160]
    try:
        print(
            f"jarvis-head emit {event_label!r} failed: {type(exc).__name__}: {detail}",
            file=sys.stderr,
        )
    except OSError:
        pass
