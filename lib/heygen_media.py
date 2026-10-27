"""Stash inputs, bounded downloads and durable HeyGen video artifacts."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from catalog_lock import catalog_lock
from config_loader import get_project_root
from http_client import http_request
from paths import assert_not_restricted_read_path
from PIL import Image
from remote_completion import RemoteCompletionError
from stash_helper import StashFile, open_space, safe_download, safe_resolve_file, validate_url
from video_catalog import load_video_catalog, upsert_video_catalog_entry


def _audio_duration(path: Path) -> float:
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as audio:
            return audio.getnframes() / audio.getframerate()
    executable = shutil.which("ffprobe")
    if not executable:
        raise ValueError("MP3 input validation requires the existing ffprobe command")
    result = subprocess.run(
        [executable, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=10, check=False,
        env={key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL") if key in os.environ},
    )
    if result.returncode:
        raise ValueError("Could not read the input audio duration")
    return float(json.loads(result.stdout)["format"]["duration"])


def media_input(source: str, kind: str, upload) -> dict:
    """Upload authorized local/Stash inputs; never publish a local URL."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("A Stash reference, local path, or public HTTPS media URL is required")
    if source.startswith(("https://", "http://")):
        parsed = urlsplit(source)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValueError("HeyGen media URLs must be public HTTPS URLs without credentials")
        validate_url(source)
        if kind == "image":
            return {"type": "url", "url": source}
        # Audio must be inspected before a paid avatar request, including URL input.
        content, mime, _ = safe_download(source, max_size=32 * 1024 * 1024)
        suffix = ".wav" if "wav" in mime else ".mp3"
        with tempfile.TemporaryDirectory(prefix="jarvis-heygen-audio-") as directory:
            path = Path(directory) / ("audio" + suffix)
            path.write_bytes(content)
            return _local_input(path, kind, upload)
    resolved = safe_resolve_file(**({"stash_ref": source} if source.startswith("stash://") else {"file_path": source}))
    if not resolved.get("found"):
        raise ValueError("The HeyGen input file could not be resolved")
    path = assert_not_restricted_read_path(resolved["path"], label="HeyGen media input")
    return _local_input(path, kind, upload)


def _local_input(path: Path, kind: str, upload) -> dict:
    if not path.is_file() or not 0 < path.stat().st_size <= 32 * 1024 * 1024:
        raise ValueError("HeyGen inputs must be nonempty files no larger than 32 MB")
    if kind == "image":
        with Image.open(path) as image:
            if image.format not in {"PNG", "JPEG"}:
                raise ValueError("HeyGen image inputs must be PNG or JPEG")
            mime = "image/png" if image.format == "PNG" else "image/jpeg"
            image.verify()
    elif kind == "audio":
        if path.suffix.lower() not in {".wav", ".mp3"}:
            raise ValueError("HeyGen audio inputs must be WAV or MP3")
        duration = _audio_duration(path)
        if not 0 < duration <= 30:
            raise ValueError("Presenter audio is limited to 30 seconds in this release")
        mime = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
    else:
        raise ValueError("Unsupported HeyGen input kind")
    return {"type": "asset_id", "asset_id": upload(path, mime)}


def _download_video(url: str) -> bytes:
    """Bound a public MP4 download without weakening Stash's generic MIME policy."""
    limit = 128 * 1024 * 1024
    for _ in range(5):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValueError("HeyGen download must use a public HTTPS URL without credentials")
        validate_url(url)
        response = http_request("GET", url, stream=True, timeout=(10, 120),
                                proxy_policy="off", allow_redirects=False)
        try:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("HeyGen download redirect has no destination")
                url = urljoin(url, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in {"video/mp4", "application/mp4", "application/octet-stream", "binary/octet-stream"}:
                raise ValueError("HeyGen download was not an MP4 response")
            if int(response.headers.get("Content-Length", "0")) > limit:
                raise ValueError("HeyGen video exceeds the 128 MB download limit")
            content = bytearray()
            for chunk in response.iter_content(65536):
                if len(content) + len(chunk) > limit:
                    raise ValueError("HeyGen video exceeds the 128 MB download limit")
                content.extend(chunk)
            return bytes(content)
        finally:
            response.close()
    raise ValueError("HeyGen download exceeded the redirect limit")


def save_result(result: dict, prompt: str = "") -> dict:
    """Serialize collection for one provider job, without blocking other videos."""
    video_id = str(result.get("provider_video_id") or result.get("video_id") or "")
    kind = result.get("kind", "model")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", video_id) or kind not in {"model", "avatar"}:
        raise ValueError("A valid completed HeyGen job is required")
    root = Path(get_project_root()) / "data" / "generated_videos"
    try:
        root.mkdir(parents=True, exist_ok=True)
        with catalog_lock(root / f".heygen_collect_{kind}_{video_id}"):
            return _save_result(result, prompt)
    except RemoteCompletionError:
        raise
    except Exception as exc:
        error = RemoteCompletionError("HeyGen finished, but collecting the video failed; check this job without regenerating", "completed")
        error.recovery = {"provider_video_id": video_id, "kind": kind}
        raise error from exc


def _save_result(result: dict, prompt: str) -> dict:
    """Save while holding the provider-job artifact lock."""
    video_id = str(result.get("provider_video_id") or result.get("video_id") or "")
    kind = result.get("kind", "model")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", video_id) or kind not in {"model", "avatar"}:
        raise ValueError("A valid completed HeyGen job is required")
    if result.get("status") != "completed" or not result.get("video_url"):
        raise ValueError("Only completed HeyGen videos can be collected")
    root = Path(get_project_root()) / "data" / "generated_videos"
    catalog_path = root / "video_catalog.json"
    filename = f"heygen_{kind}_{video_id}.mp4"
    path = root / filename
    try:
        root.mkdir(parents=True, exist_ok=True)
        metadata = load_video_catalog(catalog_path).get(filename, {})
        saved = metadata.get("saved")
        if path.is_file() and isinstance(saved, dict) and saved.get("stash_ref"):
            if safe_resolve_file(stash_ref=saved["stash_ref"]).get("found"):
                return _saved_envelope(result, saved)
        if not path.is_file():
            content = _download_video(result["video_url"])
            # Reject API error pages before enrolling an artifact as a playable MP4.
            if len(content) < 12 or content[4:8] != b"ftyp":
                raise ValueError("HeyGen did not return an MP4 file")
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=root, suffix=".part", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(content)
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        space, _ = open_space(labels=["heygen", "video", "generated_videos"], scope="project")
        stored = StashFile(space).save_binary(
            path.read_bytes(), name=filename, mime_type="video/mp4",
            tags=["video", "ai_generated", "heygen", result.get("model", "")],
            tool_origin="generate_avatar_video" if kind == "avatar" else "generate_video",
        )
        saved = {"saved": True, "path": str(path), "filename": filename,
                 "size_bytes": path.stat().st_size, "stash": True,
                 "stash_ref": stored["ref"], "space_id": space.space_id}
        with space.transaction():
            for entry in space.meta["files"]:
                if entry["file_id"] == stored["file_id"]:
                    entry.update({"provider": "HeyGen", "model": result.get("model"),
                                  "provider_video_id": video_id, "kind": kind})
            space._save_meta()
        upsert_video_catalog_entry(catalog_path, filename, {
            "provider": "HeyGen", "model": result.get("model"), "kind": kind,
            "provider_video_id": video_id, "aspect": result.get("aspect_ratio"),
            "tags": ["video", "ai_generated", "heygen"], "prompt": prompt[:2000],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tool_origin": "generate_avatar_video" if kind == "avatar" else "generate_video",
            "stash_ref": stored["ref"], "space_id": space.space_id, "saved": saved,
        })
        return _saved_envelope(result, saved)
    except Exception as exc:
        error = RemoteCompletionError("HeyGen finished, but saving the video failed; collect this job again without regenerating", "completed")
        error.recovery = {key: result[key] for key in ("provider_video_id", "kind", "receipt_stash_ref") if key in result}
        raise error from exc


def _saved_envelope(result: dict, saved: dict) -> dict:
    return {"ok": True, "speech": "HeyGen video saved to Stash and the video gallery", "data": {
        **result, "saved": saved, "stash_ref": saved["stash_ref"], "file_path": saved["path"],
        "filename": saved["filename"], "mime_type": "video/mp4",
    }}
