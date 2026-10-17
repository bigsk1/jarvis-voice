#!/usr/bin/env python3
"""Read one existing Apify run, bounded dataset page or retained output record."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.apify import ApifyError, read_result  # noqa: E402
from lib.config_loader import load_config  # noqa: E402


def main():
    try:
        load_config()
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        if not isinstance(arguments, dict) or set(arguments) - {
            "run_id", "action", "dataset_id", "offset", "limit", "fields", "record_key"
        }:
            raise ApifyError("Invalid Apify result arguments")
        result = read_result(arguments)
    except (ApifyError, ValueError, TypeError) as exc:
        result = {"ok": False, "speech": str(exc), "error": str(exc)}
    print(json.dumps(result, allow_nan=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
