#!/usr/bin/env python3
"""Standalone entry point for the workflow meta-tool."""

import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "orchestrator"))

from tool_schema import get_tool_registry
from workflow_tool_runtime import execute_workflow_tool


def main() -> int:
    try:
        payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
    except Exception:
        payload = {}

    mode = os.environ.get("JARVIS_MODE") or os.environ.get("JARVIS_EXECUTION_MODE") or "cloud"
    registry = get_tool_registry(mode=mode)
    result = execute_workflow_tool(
        registry=registry,
        args=payload,
        mode=mode,
        excluded_tools=payload.get("_excluded_tools") or [],
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
