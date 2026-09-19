#!/usr/bin/env python3
"""Reject direct calls: only authorized Web callback jobs may run Browser Use."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.background_tasks.admission import background_only_result  # noqa: E402


def main():
    # Voice, CLI, schedulers and older executors can call skill scripts directly.
    # Do not import/start the agent or accept a caller-supplied background flag.
    print(json.dumps(background_only_result('browser_use'), ensure_ascii=False))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
