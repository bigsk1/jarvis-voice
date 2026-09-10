#!/usr/bin/env python3
"""Understand an existing video with sampled visual evidence and optional audio."""

from __future__ import annotations

import json
import re
import signal
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from config_loader import load_config
from paths import assert_not_restricted_read_path, resolve_local_file_tool_path
from provider_errors import sanitize_provider_error
from stash_helper import get_stash_dir, parse_stash_ref, safe_resolve_file
from video_analysis import VideoAnalysisError, analyze_video_file


def _resolve_source(source: object) -> tuple[Path, str | None]:
    if not isinstance(source, str) or not source.strip():
        raise VideoAnalysisError("source must be a Stash reference or an allowed local video path.")
    source = source.strip()
    if source.startswith("stash://"):
        if not re.fullmatch(r"stash://[A-Za-z0-9_-]+/[^/\\]+", source):
            raise VideoAnalysisError("Invalid Stash video reference.")
        space_id, _ = parse_stash_ref(source)
        root = get_stash_dir().resolve()
        space = root / space_id
        if space.is_symlink() or (space / "meta.json").is_symlink():
            raise VideoAnalysisError("The Stash video is unavailable.")
        resolved = safe_resolve_file(stash_ref=source)
        if not resolved.get("found"):
            raise VideoAnalysisError("The Stash video is unavailable; attach it again or provide an existing source.")
        path = assert_not_restricted_read_path(resolved["path"], label="Video source")
        if path.parent != space or Path(resolved["path"]).is_symlink():
            raise VideoAnalysisError("The Stash video is outside its source space.")
        return path, source
    if urlsplit(source).scheme and not Path(source).is_absolute():
        raise VideoAnalysisError("Remote URLs are not video inputs. Download the video to Stash first.")
    return resolve_local_file_tool_path(source, include_pictures=False), None


def execute(args: dict) -> dict:
    if not isinstance(args, dict):
        raise VideoAnalysisError("Tool input must be a JSON object.")
    unknown = set(args) - {"source", "question", "start_seconds", "end_seconds", "include_audio"}
    if unknown:
        raise VideoAnalysisError("Unsupported video analysis parameter.")
    path, source_ref = _resolve_source(args.get("source"))
    data = analyze_video_file(path, **{key: args[key] for key in (
        "question", "start_seconds", "end_seconds", "include_audio") if key in args})
    data["source_ref"] = source_ref or str(path)
    data["source_stash_ref"] = source_ref
    data["original_path"] = source_ref or str(path)
    ok = bool(data["analyzed_frame_timestamps"] or data["transcript"])
    evidence_missing = data["visual_status"] != "complete" or data["audio_status"] in {"partial", "unavailable"}
    speech = (f"Analyzed {len(data['analyzed_frame_timestamps'])} sampled video frames "
              f"from {data['start_seconds']:.1f} to {data['end_seconds']:.1f} seconds.")
    if evidence_missing:
        speech += " Some requested evidence was unavailable; review the source warnings."
        data["error_code"] = "video_analysis_partial"
    elif data["partial"]:
        speech += " This covers only the selected interval or bounded excerpts."
    result = {"ok": ok, "speech": speech, "data": data}
    if not ok:
        result["error"] = "Video analysis could not obtain all requested evidence."
    return result


def main() -> int:
    # The executor cancels the tool's process group. Unwind TemporaryDirectory
    # and subprocess.run on SIGTERM so extracted audio is removed promptly.
    def cancelled(_signum, _frame):
        raise SystemExit(143)

    signal.signal(signal.SIGTERM, cancelled)
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
        load_config()
        result = execute(args)
    except (ValueError, TypeError, OSError) as exc:
        message = sanitize_provider_error(str(exc), max_chars=400) or "Video analysis failed."
        result = {"ok": False, "speech": message, "error": message,
                  "data": {"error_code": "video_analysis_invalid"}}
    except Exception:
        result = {"ok": False, "speech": "Video analysis failed because of an unexpected provider or local error.",
                  "error": "Video analysis failed.", "data": {"error_code": "video_analysis_failed"}}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
