#!/usr/bin/env python3
"""Start one ordinary Apify Actor through Jarvis's reviewed generic gateway."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.apify import ApifyError, run_actor  # noqa: E402
from lib.config_loader import load_config  # noqa: E402


def main():
    try:
        load_config()
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        if not isinstance(arguments, dict) or set(arguments) - {"actor", "input"}:
            raise ApifyError("Expected actor and input arguments")
        result = run_actor(arguments)
    except (ApifyError, ValueError, TypeError) as exc:
        uncertain = isinstance(exc, ApifyError) and exc.uncertain
        result = {"ok": False, "speech": str(exc), "error": str(exc),
                  "completion": "unknown" if uncertain else "rejected"}
    print(json.dumps(result, allow_nan=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
