"""Operator commands for the optional email channel and its normal schedule."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "lib"), str(ROOT / "orchestrator")]


def ensure_schedule(mode, every, manager):
    existing = [
        task
        for task in manager.list_tasks(limit=1000)
        if task.get("task_target") == "jarvis_email_inbox"
        and task.get("task_type") == "workflow"
        and task.get("last_status") != "cancelled"
        and task.get("mode", mode) == mode
    ]
    if existing:
        return {
            "ok": True,
            "data": {
                "task_id": existing[0]["id"],
                "existing": True,
                "enabled": bool(existing[0]["enabled"]),
            },
        }
    task_id = manager.create_task(
        name="Jarvis Email Inbox",
        task_type="workflow",
        workflow_id="jarvis_email_inbox",
        when=f"every {every} minutes",
        mode=mode,
        timeout_seconds=600,
        max_retries=0,
        allow_overlap=False,
    )
    return {"ok": True, "data": {"task_id": task_id, "existing": False, "enabled": True}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["cloud", "local"], default="cloud")
    parser.add_argument("action", choices=["status", "preview", "poll", "schedule"])
    parser.add_argument(
        "--every", type=int, default=30, help="Schedule interval in minutes; default 30"
    )
    args = parser.parse_args(argv)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from config_loader import config_scope
            from email_contacts import load_email_channel
            from executor import ToolExecutor
            from tool_schema import get_tool_registry

            from lib.email_inbox import execute_inbox

            with config_scope(args.mode):
                if args.action == "schedule":
                    if not 5 <= args.every <= 1440:
                        raise ValueError("Schedule interval must be between 5 and 1440 minutes")
                    if not load_email_channel(args.mode).get("enabled"):
                        raise ValueError("Enable jarvis_email for this mode in contacts.json first")
                    from api.managers.scheduled_task_manager import ScheduledTaskManager

                    result = ensure_schedule(args.mode, args.every, ScheduledTaskManager(args.mode))
                else:
                    executor = None
                    if args.action != "status":
                        registry = get_tool_registry(mode=args.mode)
                        executor = ToolExecutor(args.mode, registry=registry)
                    result = execute_inbox(args.mode, {"action": args.action}, executor)
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    except Exception as exc:
        message = (
            str(exc) if isinstance(exc, ValueError) else "Email command failed; check local setup"
        )
        print(json.dumps({"ok": False, "error": message}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
