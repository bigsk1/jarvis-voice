#!/usr/bin/env python3
"""Record a quiet notification and optional channel delivery intent."""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.config_loader import get_active_config_mode, load_config  # noqa: E402
from lib.notifications import NotificationStore  # noqa: E402

ARGUMENTS = frozenset({"title", "message", "source", "channels", "dedupe_key", "max_age_seconds"})


def run(args: dict, *, root: Path | None = None, mode: str | None = None) -> dict:
    """Use the same local writer as API, workflow, and ordinary tool callers."""
    if not isinstance(args, dict) or set(args) - ARGUMENTS:
        raise ValueError("Expected a notification object with supported fields.")
    if "title" not in args or "message" not in args:
        raise ValueError("title and message are required.")
    data = NotificationStore(root or ROOT, mode or get_active_config_mode()).create(**args)
    prefix = (
        "Notification already recorded." if data.get("deduplicated") else "Notification recorded."
    )
    deliveries = data.get("deliveries", [])
    if any(item.get("state") == "pending" for item in deliveries):
        speech = prefix + " Channel delivery is queued."
    elif any(item.get("state") == "unavailable" for item in deliveries):
        speech = (
            prefix + " A requested delivery channel is unavailable; see Notifications settings."
        )
    else:
        speech = prefix
    return {"ok": True, "speech": speech, "data": data}


def main() -> int:
    try:
        if len(sys.argv) != 2:
            raise ValueError("Pass one JSON object containing title and message.")
        args = json.loads(sys.argv[1])
        load_config()
        result = run(args)
    except (ValueError, TypeError):
        result = {
            "ok": False,
            "error": "Invalid notification arguments. Provide a bounded title and message, supported channels, and an optional dedupe key.",
        }
    except (OSError, sqlite3.Error):
        result = {"ok": False, "error": "Notification storage is unavailable."}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
