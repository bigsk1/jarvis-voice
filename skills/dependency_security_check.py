#!/usr/bin/env python3
"""Read-only dependency advisory check for Jarvis and scheduled workflows."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from dependency_security import run_audit  # noqa: E402


def execute(params: dict[str, Any]) -> dict[str, Any]:
    """Return an audit report; incomplete coverage remains explicit in data."""
    if set(params) - {"action"} or params.get("action", "check") != "check":
        return {
            "ok": False,
            "speech": "Only the read-only check action is supported.",
            "error": "unsupported_arguments",
        }
    data = run_audit(PROJECT_ROOT)
    status = data["status"]
    findings = len(data["findings"])
    speech = (
        f"Dependency security check: {status}. "
        f"Found {findings} affected package/version pair(s)."
    )
    if not data["complete"]:
        speech += " Some checks could not finish; review the coverage errors."
    # A completed diagnostic can report findings or incomplete source checks.
    # Keep the report available to the workflow's Canvas and alert steps.
    return {"ok": True, "speech": speech, "data": data}


def main() -> None:
    try:
        params = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        if not isinstance(params, dict):
            raise ValueError("Expected a JSON object")
        result = execute(params)
    except (ValueError, TypeError):
        result = {
            "ok": False,
            "speech": "The dependency security check needs a valid JSON object.",
            "error": "invalid_input",
        }
    except Exception:
        result = {
            "ok": False,
            "speech": "The dependency security check could not produce a report.",
            "error": "audit_failed",
        }
    print(json.dumps(result))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
