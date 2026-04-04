#!/usr/bin/env python3
"""
Tool Name: create_alert
Create alerts in the proactive API system.

Input: {
  "title": "Alert title",
  "source": "source_system",
  "description": "Optional details",
  "severity": "low|medium|high|critical",
  "auto_resolve_url": "Optional URL to check for recovery",
  "auto_resolve_check_interval": 300,
  "metadata": {"key": "value"},
  "related_intel_file": "Optional intel path",
  "speak_immediately": true
}

Output: { "ok": bool, "speech": str, "data": dict }
"""

import sys
import os
import json

# Add project root and lib to path
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'lib'))

from api.managers.alert_manager import AlertManager


VALID_SEVERITIES = {"low", "medium", "high", "critical"}


def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)

        title = (args.get("title") or "").strip()
        source = (args.get("source") or "").strip()
        description = args.get("description")
        severity = (args.get("severity") or "medium").strip().lower()
        auto_resolve_url = args.get("auto_resolve_url")
        auto_resolve_check_interval = int(args.get("auto_resolve_check_interval", 300))
        metadata = args.get("metadata")
        related_intel_file = args.get("related_intel_file")
        speak_immediately = bool(args.get("speak_immediately", True))

        if not title:
            raise ValueError("title is required")
        if not source:
            raise ValueError("source is required")
        if severity not in VALID_SEVERITIES:
            raise ValueError(f"severity must be one of: {', '.join(sorted(VALID_SEVERITIES))}")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object when provided")

        manager = AlertManager()
        alert_id = manager.create_alert(
            title=title,
            source=source,
            description=description,
            severity=severity,
            auto_resolve_url=auto_resolve_url,
            auto_resolve_check_interval=auto_resolve_check_interval,
            metadata=metadata,
            related_intel_file=related_intel_file,
            speak_immediately=speak_immediately,
        )

        duplicate_suppressed = alert_id < 0
        actual_alert_id = abs(alert_id)
        alert = manager.get_alert(actual_alert_id)

        if duplicate_suppressed:
            speech = f"Alert already exists: {title}."
        else:
            speech = f"Alert created: {title}."

        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": {
                "alert_id": actual_alert_id,
                "alert": alert,
                "duplicate_suppressed": duplicate_suppressed,
                "severity": severity,
                "source": source,
                "speak_immediately": speak_immediately,
            }
        }))

    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to create alert: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
