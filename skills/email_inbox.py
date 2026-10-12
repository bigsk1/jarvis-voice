#!/usr/bin/env python3
"""Standalone operator entry point; normal execution is an in-process tool."""

import contextlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "lib"), str(ROOT / "orchestrator")]


def main():
    from config_loader import config_scope
    from executor import ToolExecutor
    from tool_schema import get_tool_registry

    from lib.email_inbox import execute_inbox

    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
    mode = os.environ.get("JARVIS_MODE") or os.environ.get("JARVIS_EXECUTION_MODE") or "cloud"
    with contextlib.redirect_stdout(sys.stderr), config_scope(mode):
        registry = get_tool_registry(mode=mode)
        executor = ToolExecutor(mode, registry=registry)
        result = execute_inbox(mode, args, executor)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
