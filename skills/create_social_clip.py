#!/usr/bin/env python3
"""
Social Clip Tool for Jarvis
Creates stock-footage B-roll social videos via MoneyPrinterTurbo (local Docker API).

Pipeline: AI script → stock clips (Pexels/Pixabay/Coverr) → TTS voiceover →
subtitles → background music → final MP4.

NOT the same as generate_video (xAI Grok / Sora / Gemini Veo AI animation).

Configure via MONEYPRINTER_* settings in cloud.env / local.env
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from config_loader import get_config_value, load_config

DEFAULT_VOICE = "en-CA-LiamNeural-Male"
DEFAULT_LANGUAGE = "en-US"

STATE_PROCESSING = 4
STATE_COMPLETE = 1
STATE_FAILED = -1

POLL_INTERVAL_SEC = 5
DEFAULT_MAX_WAIT_SEC = 1200
CREATE_429_RETRY_DELAYS = (15, 30, 60)


def get_max_wait_sec() -> int:
    raw = get_config_value("MONEYPRINTER_MAX_WAIT_SEC")
    try:
        return max(60, int(raw)) if raw else DEFAULT_MAX_WAIT_SEC
    except (TypeError, ValueError):
        return DEFAULT_MAX_WAIT_SEC


def get_api_base() -> str:
    base = (get_config_value("MONEYPRINTER_API_URL") or "").strip().rstrip("/")
    if not base:
        raise ValueError(
            "MONEYPRINTER_API_URL is not set — add it to config/cloud.env or config/local.env "
            '(e.g. MONEYPRINTER_API_URL="http://192.168.x.xx:8080")'
        )
    return base


def get_default_voice() -> str:
    return (get_config_value("MONEYPRINTER_VOICE") or DEFAULT_VOICE).strip()


def resolve_download_url(api_base: str, video_url: str) -> str:
    """MPT returns relative /tasks/... paths when endpoint is unset in config.toml."""
    if not video_url:
        return video_url
    if video_url.startswith("/"):
        return f"{api_base.rstrip('/')}{video_url}"
    return video_url


def _task_failed_message(task_id: str, data: dict) -> str:
    msg = data.get("message")
    if msg:
        return f"Task {task_id} failed: {msg}"
    return (
        f"Task {task_id} failed (MoneyPrinterTurbo state -1). "
        f"MPT rarely includes error text — check API logs or storage/tasks/{task_id}/ on the server."
    )


def create_task(api_base: str, payload: dict) -> str:
    url = f"{api_base}/api/v1/videos"
    last_error = "Task creation failed"

    for attempt in range(len(CREATE_429_RETRY_DELAYS) + 1):
        resp = requests.post(url, json=payload, timeout=60)

        if resp.status_code == 429:
            last_error = "MoneyPrinterTurbo queue full (429) — max concurrent/queued tasks reached"
            if attempt < len(CREATE_429_RETRY_DELAYS):
                delay = CREATE_429_RETRY_DELAYS[attempt]
                print(f"[SOCIAL_CLIP] {last_error}, retry in {delay}s...", file=sys.stderr)
                time.sleep(delay)
                continue
            raise RuntimeError(f"{last_error}. Try again later.")

        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            body = {}
            try:
                body = resp.json()
            except Exception:
                pass
            raise RuntimeError(body.get("message") or str(e)) from e

        body = resp.json()
        if body.get("status") != 200:
            raise RuntimeError(body.get("message") or last_error)
        task_id = (body.get("data") or {}).get("task_id")
        if not task_id:
            raise RuntimeError("No task_id in create response")
        return task_id

    raise RuntimeError(last_error)


def poll_task(api_base: str, task_id: str) -> dict:
    url = f"{api_base}/api/v1/tasks/{task_id}"
    max_wait = get_max_wait_sec()
    deadline = time.time() + max_wait
    last_progress = -1

    while time.time() < deadline:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        state = data.get("state")
        progress = data.get("progress", 0)

        if progress != last_progress:
            print(f"[SOCIAL_CLIP] task {task_id}: state={state} progress={progress}%", file=sys.stderr)
            last_progress = progress

        if state == STATE_COMPLETE:
            return data
        if state == STATE_FAILED:
            print(f"[SOCIAL_CLIP] task {task_id} failed at progress={progress}%", file=sys.stderr)
            raise RuntimeError(_task_failed_message(task_id, data))

        time.sleep(POLL_INTERVAL_SEC)

    raise TimeoutError(f"Task {task_id} did not complete within {max_wait}s")


def download_video(url: str, filename: str) -> Path:
    out_dir = Path("/tmp/jarvis_social_clips")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    resp = requests.get(url, timeout=300, stream=True)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return out_path


def save_to_stash(video_path: Path, subject: str, task_id: str, source_url: str) -> dict:
    video_bytes = video_path.read_bytes()
    try:
        from stash_helper import StashFile, open_space

        space, _ = open_space(scope="session", labels=["social_clips", "generated_videos"])
        stash_file = StashFile(space)
        result = stash_file.save_binary(
            data=video_bytes,
            name=video_path.name,
            mime_type="video/mp4",
            on_conflict="overwrite",
            tags=["social_clip", "broll", "moneyprinter", "video"],
            tool_origin="create_social_clip",
        )

        file_id = result.get("file_id")
        if file_id and source_url:
            for f in space.meta.get("files", []):
                if f.get("file_id") == file_id:
                    f["source_url"] = source_url
                    f["task_id"] = task_id
                    f["subject"] = subject[:200]
                    break
            space._save_meta()

        return {
            "saved": True,
            "stash_ref": result.get("ref"),
            "space_id": space.space_id,
            "path": str(video_path),
            "filename": video_path.name,
            "size_bytes": len(video_bytes),
            "stash": True,
            "source_url": source_url,
        }
    except Exception as e:
        return {
            "saved": True,
            "path": str(video_path),
            "filename": video_path.name,
            "size_bytes": video_path.stat().st_size,
            "stash": False,
            "note": f"File saved but stash indexing failed: {e}",
        }


def build_payload(args: dict) -> dict:
    payload = {
        "video_subject": args["subject"],
        "video_aspect": args.get("aspect_ratio", "9:16"),
        "video_source": args.get("video_source", "pexels"),
        "voice_name": args.get("voice") or get_default_voice(),
        "video_language": args.get("language") or DEFAULT_LANGUAGE,
        "subtitle_enabled": args.get("subtitles", True),
        "video_clip_duration": args.get("clip_duration", 5),
    }
    script = args.get("script")
    if script:
        payload["video_script"] = script
    if args.get("paragraph_number") is not None:
        payload["paragraph_number"] = args["paragraph_number"]
    if args.get("match_materials_to_script") is not None:
        payload["match_materials_to_script"] = bool(args["match_materials_to_script"])
    if args.get("bgm_type") is not None:
        payload["bgm_type"] = args["bgm_type"]
    if args.get("video_count") is not None:
        payload["video_count"] = args["video_count"]
    return payload


def main():
    try:
        load_config()

        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)

        subject = (args.get("subject") or "").strip()
        if not subject:
            raise ValueError("subject is required — the topic for the social clip")

        api_base = get_api_base()
        payload = build_payload(args)
        save = args.get("save", True)

        print(f"[SOCIAL_CLIP] Creating task at {api_base} for: {subject[:60]}", file=sys.stderr)
        task_id = create_task(api_base, payload)

        print(f"[SOCIAL_CLIP] Polling task {task_id}...", file=sys.stderr)
        result = poll_task(api_base, task_id)

        videos = result.get("videos") or []
        if not videos:
            raise RuntimeError("Task completed but no final video URL returned")

        video_url = resolve_download_url(api_base, videos[0])
        safe_subject = "".join(c if c.isalnum() or c in " -_" else "" for c in subject[:40])
        safe_subject = safe_subject.replace(" ", "_").lower() or "clip"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"social_{safe_subject}_{timestamp}.mp4"

        save_info = None
        if save:
            video_path = download_video(video_url, filename)
            save_info = save_to_stash(video_path, subject, task_id, video_url)

            try:
                from memory_db import MemoryDB

                db = MemoryDB()
                stash_ref = save_info.get("stash_ref", "")
                space_id = save_info.get("space_id", "")
                memory_key = f"stash_social_clip_{space_id}" if space_id else f"social_clip_{timestamp}"
                db.remember(
                    key=memory_key,
                    value=f"Social clip: {subject[:150]}. STASH: {stash_ref}. FILE: {save_info.get('filename')}",
                    category="stash_artifact",
                    importance=6,
                    source="create_social_clip",
                    metadata={
                        "stash_ref": stash_ref,
                        "space_id": space_id,
                        "filename": save_info.get("filename", ""),
                        "subject": subject[:200],
                        "task_id": task_id,
                        "tags": ["video", "social_clip", "broll"],
                        "type": "video",
                    },
                )
            except Exception:
                pass

        aspect = payload["video_aspect"]
        speech = f"Social clip ready: {subject[:50]}{'...' if len(subject) > 50 else ''}"

        response = {
            "ok": True,
            "speech": speech,
            "data": {
                "subject": subject,
                "task_id": task_id,
                "aspect_ratio": aspect,
                "video_url": video_url,
                "progress": result.get("progress", 100),
            },
        }

        if save_info:
            response["data"]["saved"] = save_info
            if save_info.get("stash_ref"):
                response["data"]["stash_ref"] = save_info["stash_ref"]
            if save_info.get("filename"):
                response["data"]["filename"] = save_info["filename"]
            if save_info.get("path"):
                response["data"]["file_path"] = save_info["path"]
            response["data"]["mime_type"] = "video/mp4"
            response["data"]["has_audio"] = True
            response["data"]["title"] = subject

        print(json.dumps(response))

    except Exception as e:
        print(json.dumps({"ok": False, "speech": f"Social clip failed: {e}", "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
