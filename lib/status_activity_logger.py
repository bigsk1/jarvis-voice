"""Structured lifecycle logging for auxiliary status LLM and TTS work."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


_WRITE_LOCK = threading.Lock()


def log_status_event(event: str, *, mode: str, **fields: Any) -> None:
    """Append one status lifecycle event without affecting the request path."""
    if os.environ.get("STATUS_LOGGING_ENABLED", "true").strip().lower() != "true":
        return
    try:
        log_dir = Path(__file__).resolve().parent.parent / "logs" / "status-llm"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"status-updates-{datetime.now():%Y-%m-%d}.jsonl"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event,
            "mode": mode,
            **fields,
        }
        with _WRITE_LOCK, log_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        # Observability must never affect tool execution or status delivery.
        return
