#!/usr/bin/env python3
"""Preflight strict offline mode; --exercise also runs a real local LLM probe."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from config_loader import config_scope  # noqa: E402
from source_library import LibraryError  # noqa: E402
from source_library_offline import exercise, preflight  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exercise", action="store_true", help="Import/render/search and ask a real local model with external sockets blocked")
    args = parser.parse_args()
    try:
        with config_scope("local"):
            result = exercise() if args.exercise else preflight()
        print(json.dumps(result, indent=2))
        if not result["ready"]:
            parser.exit(1)
    except (LibraryError, OSError, ValueError) as exc:
        parser.exit(1, f"Offline readiness: {exc}\n")


if __name__ == "__main__":
    main()
