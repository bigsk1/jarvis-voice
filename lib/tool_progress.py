"""Small JSON-lines protocol for live progress from local tool subprocesses."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any, TextIO

TOOL_PROGRESS_PREFIX = "__JARVIS_TOOL_PROGRESS__:"
MAX_TOOL_PROGRESS_LINE_CHARS = 16_384


def emit_tool_progress(
    payload: Mapping[str, Any],
    *,
    stream: TextIO | None = None,
) -> None:
    """Write one machine-readable progress event without touching tool stdout."""
    target = stream or sys.stderr
    target.write(
        TOOL_PROGRESS_PREFIX
        + json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )
    target.flush()


def parse_tool_progress(line: str) -> dict[str, Any] | None:
    """Parse one protocol line, returning ``None`` for ordinary stderr."""
    if not isinstance(line, str) or not line.startswith(TOOL_PROGRESS_PREFIX):
        return None
    if len(line) > MAX_TOOL_PROGRESS_LINE_CHARS:
        return None

    try:
        payload = json.loads(line[len(TOOL_PROGRESS_PREFIX):].strip())
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None
