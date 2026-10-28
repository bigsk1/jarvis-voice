#!/usr/bin/env python3
"""Read public RSS/Atom feeds and support the scheduled digest workflow."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))

from config_loader import load_config  # noqa: E402
from rss_feeds import RSSFeedError  # noqa: E402
from rss_feeds.service import RSSFeedService  # noqa: E402

ACTIONS = frozenset({"list_profiles", "read", "resolve_selection", "acknowledge"})
PARAMETERS = frozenset({"url", "profile", "batch_id", "text", "page_id", "limit"})


def execute(params: dict[str, Any]) -> dict[str, Any]:
    """Wrap the feed service without exposing exceptions or accepting extra settings."""
    if not isinstance(params, dict):
        return {"ok": False, "speech": "RSS feed requests need a JSON object.", "error": "invalid_input"}
    arguments = dict(params)
    action = arguments.pop("action", "read")
    if not isinstance(action, str) or action not in ACTIONS:
        return {"ok": False, "speech": "That RSS feed action is not supported.", "error": "invalid_action"}

    # Generic workflow LLM filling returns these three identical text aliases.
    # Keep only text; conflicting aliases are never allowed to override it.
    for alias in ("content", "body"):
        if alias in arguments:
            if action != "resolve_selection" or arguments[alias] != arguments.get("text"):
                return {"ok": False, "speech": "RSS selection text is inconsistent.", "error": "invalid_input"}
            arguments.pop(alias)
    if set(arguments) - PARAMETERS:
        return {"ok": False, "speech": "The RSS request contains unsupported settings.", "error": "invalid_input"}

    try:
        load_config()
        data = RSSFeedService().execute(action=action, **arguments)
    except RSSFeedError as exc:
        return {"ok": False, "speech": str(exc), "error": str(exc)}
    except Exception:
        return {"ok": False, "speech": "The RSS feed request could not finish.", "error": "rss_feed_failed"}

    if action == "list_profiles":
        speech = "Listed the configured RSS digest profiles."
    elif action == "resolve_selection":
        speech = f"Validated {len(data.get('selected_items', []))} stories for the digest."
    elif action == "acknowledge":
        speech = "Recorded the stories published to Canvas."
        data = {**data, "publication_status": "Published the digest to Canvas."}
    elif data.get("profile"):
        speech = f"Found {data.get('candidate_count', 0)} fresh RSS candidates."
    else:
        speech = f"Read {len(data.get('items', []))} feed items."
    return {"ok": True, "speech": speech, "data": data}


def main() -> None:
    """Use the normal foreground tool JSON-in-argv protocol."""
    try:
        params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (ValueError, TypeError):
        result = {"ok": False, "speech": "RSS feed requests need valid JSON.", "error": "invalid_input"}
    else:
        result = execute(params)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
