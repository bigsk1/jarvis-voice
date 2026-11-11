#!/usr/bin/env python3
"""Jarvis Skill: Google search panels and local retained-result inspection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from config_loader import load_config
from serpapi_google import run_google_search


def main() -> int:
    load_config()
    try:
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object.")
        result = run_google_search(arguments)
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        message = str(exc)
        result = {"ok": False, "speech": message, "error": message}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
