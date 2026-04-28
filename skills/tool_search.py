#!/usr/bin/env python3
"""
Jarvis Tool: tool_search

Direct invocation path for discovery. Normal orchestrator execution uses the
shared in-process registry to avoid spawning duplicate MCP discovery state, but
this script remains usable for standalone runs and testing.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from tool_schema import get_tool_registry
from tool_search_runtime import search_tools_runtime


def main() -> int:
    try:
        if len(sys.argv) > 1:
            payload = json.loads(sys.argv[1])
        else:
            payload = json.load(sys.stdin)
    except Exception:
        payload = {}

    mode = os.environ.get("JARVIS_MODE") or os.environ.get("JARVIS_EXECUTION_MODE") or "cloud"
    registry = get_tool_registry(mode=mode)
    result = search_tools_runtime(
        registry=registry,
        query=payload.get("query", ""),
        limit=payload.get("limit", 8),
        excluded_tools=payload.get("_excluded_tools") or [],
        tool_names=payload.get("tool_names"),
        include_schema=bool(payload.get("include_schema")),
    )
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
