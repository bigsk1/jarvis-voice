#!/usr/bin/env python3
"""Read HeyGen catalogs and observe or collect existing jobs without submission."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from config_loader import get_config_value, load_config  # noqa: E402

_ACTIONS = {"account", "list_avatars", "list_voices", "status", "collect"}


def validate_arguments(arguments: dict) -> dict:
    if not isinstance(arguments, dict) or set(arguments) - {"action", "video_id", "kind", "limit", "cursor"}:
        raise ValueError("Use only the documented HeyGen catalog/status arguments")
    args = {key: value for key, value in arguments.items() if value is not None}
    action = args.get("action")
    if not isinstance(action, str) or action not in _ACTIONS:
        raise ValueError("action must be account, list_avatars, list_voices, status, or collect")
    expected = {"action"}
    if action in {"status", "collect"}:
        expected |= {"video_id", "kind"}
        identifier = args.get("video_id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", identifier):
            raise ValueError("Supply the exact provider_video_id from an existing HeyGen receipt")
        if args.get("kind", "model") not in {"model", "avatar"}:
            raise ValueError("kind must be model or avatar, matching the original receipt")
    elif action in {"list_avatars", "list_voices"}:
        expected |= {"limit", "cursor"}
        if type(args.get("limit", 20)) is not int or not 1 <= args.get("limit", 20) <= 50:
            raise ValueError("limit must be an integer from 1 to 50")
        if "cursor" in args and (not isinstance(args["cursor"], str) or not args["cursor"].strip() or len(args["cursor"]) > 500):
            raise ValueError("cursor must be a nonempty provider pagination token, at most 500 characters")
    if set(args) - expected:
        raise ValueError("Arguments do not match the selected HeyGen action")
    return args


def run(arguments: dict) -> dict:
    try:
        args = validate_arguments(arguments)
        load_config()
        if not str(get_config_value("HEYGEN_API_KEY", "") or "").strip():
            raise ValueError("Set HEYGEN_API_KEY in the selected mode to use HeyGen")
    except (TypeError, ValueError) as exc:
        return {"ok": False, "completion": "rejected", "error": str(exc), "speech": str(exc)}

    from heygen_client import HeyGenClient, heygen_error_result

    try:
        client = HeyGenClient()
        action = args.pop("action")
        if action == "collect":
            result = client.collect(args["video_id"], kind=args.get("kind", "model"))
            result.setdefault("data", {}).update(action=action, kind=args.get("kind", "model"))
            return result
        if action == "account":
            data = client.account()
        elif action == "list_avatars":
            data = client.list_avatars(limit=args.get("limit", 20), cursor=args.get("cursor"))
        elif action == "list_voices":
            data = client.list_voices(limit=args.get("limit", 20), cursor=args.get("cursor"))
        else:
            data = client.status(args["video_id"], kind=args.get("kind", "model"))
        return {"ok": True, "speech": f"HeyGen {action.replace('_', ' ')} returned.",
                "data": {**data, "provider": "heygen", "action": action}}
    except Exception as exc:
        return heygen_error_result(exc)


def main() -> int:
    try:
        arguments = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
    except (ValueError, OSError):
        result = {"ok": False, "completion": "rejected", "error": "Invalid JSON input", "speech": "Invalid JSON input"}
    else:
        result = run(arguments)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
