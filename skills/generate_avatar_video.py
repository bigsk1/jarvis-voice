#!/usr/bin/env python3
"""Generate a short Avatar IV video through the optional HeyGen integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from config_loader import get_config_value, load_config  # noqa: E402

_FIELDS = {"script", "avatar_id", "image_source", "voice_id", "audio_source", "title", "aspect_ratio", "resolution"}


def validate_arguments(arguments: dict) -> dict:
    """Validate scalars and alternatives before resolving or uploading files."""
    if not isinstance(arguments, dict) or set(arguments) - _FIELDS:
        raise ValueError("Use only the documented avatar video arguments")
    args = {key: value for key, value in arguments.items() if value is not None}
    for field, value in args.items():
        if not isinstance(value, str) or (field != "title" and not value.strip()):
            raise ValueError(f"{field} must be a nonempty string")
    if bool(args.get("script")) == bool(args.get("audio_source")):
        raise ValueError("Provide exactly one of script or audio_source")
    if bool(args.get("avatar_id")) == bool(args.get("image_source")):
        raise ValueError("Provide exactly one of avatar_id or image_source")
    if args.get("script"):
        if len(args["script"]) > 1000 or len(args["script"].split()) > 75:
            raise ValueError("Avatar scripts are limited to 75 words and 1000 characters")
        if not args.get("voice_id"):
            raise ValueError("A script requires an exact voice_id from heygen list_voices")
    elif args.get("voice_id"):
        raise ValueError("Use voice_id with script only; audio_source supplies the voice")
    if len(args.get("title", "")) > 200:
        raise ValueError("title must contain at most 200 characters")
    if args.get("aspect_ratio", "16:9") not in {"16:9", "9:16", "1:1", "auto"}:
        raise ValueError("aspect_ratio must be 16:9, 9:16, 1:1, or auto")
    if args.get("resolution", "720p") not in {"720p", "1080p"}:
        raise ValueError("resolution must be 720p or 1080p")
    return args


def run(arguments: dict, *, submit_only: bool = False) -> dict:
    try:
        args = validate_arguments(arguments)
        load_config()
        if not str(get_config_value("HEYGEN_API_KEY", "") or "").strip():
            raise ValueError("Set HEYGEN_API_KEY in the selected mode to use HeyGen")
    except (TypeError, ValueError) as exc:
        return {"ok": False, "completion": "rejected", "error": str(exc), "speech": str(exc)}

    from heygen_client import HeyGenClient, heygen_error_result, save_result

    try:
        client = HeyGenClient()
        if submit_only:
            result = client.submit_avatar(**args)
            return {"ok": True, "speech": "HeyGen avatar video submitted. Check or collect this same video ID; do not submit again.",
                    "data": {**result, "provider": "heygen", "kind": "avatar", "submission_only": True}}
        result = client.generate_avatar(**args)
        return save_result(result, prompt=args.get("script") or args.get("title") or "Avatar video from supplied audio")
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
