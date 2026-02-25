#!/usr/bin/env python3
"""
YouTube Video Downloader - download a YouTube video and save it to stash.

Focus:
- Stable yt-dlp defaults with fallback strategies for YouTube blocking
- Stash-first output so WebUI can preview/download via /api/stash
- No generated_videos folder usage (separate from generate_video tool)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

# IMPORTANT: This tool lives in skills/auto-tools/, so go up 2 levels to reach lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
from config_loader import load_config, get_config_value
from stash_helper import open_space, StashFile
from memory_db import MemoryDB


VALID_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"}


def is_youtube_url(url: str) -> bool:
    """Basic YouTube URL validation."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and parsed.netloc.lower() in VALID_HOSTS
    except Exception:
        return False


def normalize_youtube_url(url: str) -> str:
    """
    Normalize youtu.be links to canonical youtube.com/watch?v=...
    Leaves other valid YouTube URLs untouched.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/")
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    return url


def sanitize_name(name: str, default: str = "youtube_video") -> str:
    """Create filesystem-safe display name."""
    clean = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", (name or "").strip())
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        clean = default
    return clean[:140]


def derive_format_selector(quality: str, audio_only: bool) -> str:
    """
    Build a yt-dlp format selector.
    Keeps formats practical and generally web-playable.
    """
    if audio_only:
        return "bestaudio/best"

    quality = (quality or "best").lower()
    if quality == "1080p":
        return "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    if quality == "720p":
        return "bestvideo[height<=720]+bestaudio/best[height<=720]"
    if quality == "480p":
        return "bestvideo[height<=480]+bestaudio/best[height<=480]"
    return "bestvideo+bestaudio/best"


def resolve_yt_dlp_command() -> list[str]:
    """Prefer yt-dlp binary, fallback to module invocation."""
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    return [sys.executable, "-m", "yt_dlp"]


def build_common_args(output_template: str, max_filesize_mb: int, proxy: str | None) -> list[str]:
    """Common yt-dlp args tuned for reliability."""
    args = [
        "--no-playlist",
        "--newline",
        "--no-progress",
        "--restrict-filenames",
        "--retries", "10",
        "--fragment-retries", "10",
        "--extractor-retries", "3",
        "--file-access-retries", "3",
        "--retry-sleep", "linear=2::8",
        "--concurrent-fragments", "1",
        "--sleep-requests", "1",
        "--sleep-interval", "1",
        "--max-sleep-interval", "5",
        "--socket-timeout", "30",
        "--force-ipv4",
        "--geo-bypass",
        "--output", output_template,
        "--write-info-json",
        "--no-warnings",
    ]
    if max_filesize_mb and max_filesize_mb > 0:
        args.extend(["--max-filesize", f"{max_filesize_mb}M"])
    if proxy:
        args.extend(["--proxy", proxy])
    return args


def cookie_args_from_config() -> list[str]:
    """
    Optional cookie configuration for bot-check-restricted videos.
    Supports either explicit cookie file or browser extraction.
    """
    cookie_file = get_config_value("YTDLP_COOKIES_FILE", "").strip()
    cookies_from_browser = get_config_value("YTDLP_COOKIES_FROM_BROWSER", "").strip()

    if cookie_file:
        if Path(cookie_file).is_file():
            return ["--cookies", cookie_file]
        return []

    if cookies_from_browser:
        # Example values: chrome, firefox, edge, safari
        return ["--cookies-from-browser", cookies_from_browser]

    return []


def fetch_video_metadata(url: str, proxy: str | None) -> dict:
    """Best-effort metadata fetch for title/duration before download."""
    cmd = resolve_yt_dlp_command()
    args = [
        "--dump-single-json",
        "--no-playlist",
        "--skip-download",
        "--no-warnings",
        "--force-ipv4",
        "--socket-timeout", "20",
    ]
    if proxy:
        args.extend(["--proxy", proxy])

    result = subprocess.run(
        cmd + args + [url],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {}

    try:
        return json.loads(result.stdout)
    except Exception:
        return {}


def run_download_with_fallbacks(
    url: str,
    output_template: str,
    format_selector: str,
    audio_only: bool,
    max_filesize_mb: int,
    proxy: str | None,
    can_merge: bool,
) -> tuple[bool, str, str, str]:
    """
    Run yt-dlp with fallback strategies.

    Returns:
        (success, attempt_name, stdout, stderr)
    """
    base_cmd = resolve_yt_dlp_command()
    common = build_common_args(output_template, max_filesize_mb, proxy)
    cookie_args = cookie_args_from_config()

    postproc = []
    if not audio_only and can_merge:
        # Use mp4 container when merge is needed; yt-dlp handles compatibility fallback.
        postproc = ["--merge-output-format", "mp4"]

    attempts = [
        ("default", []),
        ("youtube_android_client", ["--extractor-args", "youtube:player_client=android,web"]),
    ]
    if cookie_args:
        attempts.append(
            ("youtube_android_client_with_cookies", ["--extractor-args", "youtube:player_client=android,web"] + cookie_args)
        )

    last_stdout = ""
    last_stderr = ""

    for attempt_name, attempt_extra in attempts:
        cmd = (
            base_cmd
            + common
            + ["-f", format_selector]
            + postproc
            + attempt_extra
            + [url]
        )
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=900,  # Large videos can take a while
            )
        except subprocess.TimeoutExpired:
            last_stdout = ""
            last_stderr = "yt-dlp timed out after 900s"
            continue

        last_stdout = result.stdout or ""
        last_stderr = result.stderr or ""
        if result.returncode == 0:
            return True, attempt_name, last_stdout, last_stderr

    return False, "", last_stdout, last_stderr


def pick_downloaded_media_file(temp_dir: Path, audio_only: bool) -> Path | None:
    """Pick best candidate downloaded media file from temp directory."""
    candidates = []
    for path in temp_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix == ".part" or path.name.endswith(".info.json"):
            continue
        ext = path.suffix.lower()
        if audio_only:
            if ext in {".mp3", ".m4a", ".aac", ".opus", ".ogg", ".wav", ".flac", ".webm"}:
                candidates.append(path)
        else:
            if ext in VIDEO_EXTENSIONS:
                candidates.append(path)

    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def load_info_json(temp_dir: Path) -> dict:
    """Load first info json found."""
    info_files = sorted(temp_dir.glob("*.info.json"))
    if not info_files:
        return {}
    try:
        with open(info_files[0], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_media_to_stash(media_path: Path, tags: list[str]) -> tuple[dict, object]:
    """Save downloaded media file to stash."""
    space, _ = open_space(scope="session", labels=["youtube_downloads"])
    stash_file = StashFile(space)

    with open(media_path, "rb") as f:
        blob = f.read()

    result = stash_file.save_binary(
        data=blob,
        name=media_path.name,
        mime_type=None,  # infer from extension
        on_conflict="version",
        tags=tags,
        tool_origin="youtube_video",
    )
    return result, space


def remember_download(space, stash_ref: str, media_name: str, metadata: dict, source_url: str):
    """Store stash artifact reference in memory for follow-up queries."""
    try:
        db = MemoryDB()
        title = metadata.get("title") or media_name
        db.remember(
            key=f"youtube_video_{space.space_id}",
            value=f"YouTube download: {title}. STASH: {stash_ref}. FILE: {media_name}. URL: {source_url}",
            category="stash_artifact",
            importance=6,
            source="youtube_video",
            metadata={
                "stash_ref": stash_ref,
                "space_id": space.space_id,
                "filename": media_name,
                "youtube_url": source_url,
                "video_title": title,
                "duration_seconds": metadata.get("duration"),
                "channel": metadata.get("uploader") or metadata.get("channel"),
                "type": "video_download",
                "tags": ["youtube", "video", "download"],
            },
        )
    except Exception:
        pass


def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)

        load_config()

        url = str(args.get("url", "")).strip()
        quality = str(args.get("quality", "best")).strip().lower()
        format_selector = str(args.get("format", "")).strip()
        filename_override = str(args.get("filename", "")).strip()
        max_filesize_mb = int(args.get("max_filesize_mb", 250) or 250)
        audio_only = bool(args.get("audio_only", False))

        if not url:
            print(json.dumps({
                "ok": False,
                "error": "url is required",
                "speech": "Please provide a YouTube URL."
            }))
            sys.exit(1)

        if not is_youtube_url(url):
            print(json.dumps({
                "ok": False,
                "error": "invalid YouTube URL",
                "speech": "Please provide a valid youtube.com or youtu.be URL."
            }))
            sys.exit(1)

        url = normalize_youtube_url(url)
        proxy = get_config_value("LOCAL_PROXY", "").strip() or None

        if not format_selector:
            format_selector = derive_format_selector(quality, audio_only)
        can_merge = bool(shutil.which("ffmpeg"))
        if not audio_only and not can_merge and "+" in format_selector:
            # Without ffmpeg, force a progressive single stream to avoid merge failures.
            format_selector = "best[ext=mp4]/best"

        with tempfile.TemporaryDirectory(prefix="jarvis_ytdlp_") as td:
            temp_dir = Path(td)
            output_template = str(temp_dir / "media.%(ext)s")

            metadata = fetch_video_metadata(url, proxy)

            ok, attempt_used, stdout, stderr = run_download_with_fallbacks(
                url=url,
                output_template=output_template,
                format_selector=format_selector,
                audio_only=audio_only,
                max_filesize_mb=max_filesize_mb,
                proxy=proxy,
                can_merge=can_merge,
            )

            if not ok:
                error_tail = (stderr or stdout or "unknown error").strip()[-800:]
                print(json.dumps({
                    "ok": False,
                    "error": f"yt-dlp failed after fallback attempts: {error_tail}",
                    "speech": "Failed to download that YouTube video. It may require cookies, be region/age restricted, or unavailable."
                }))
                sys.exit(1)

            info_json = load_info_json(temp_dir)
            if info_json:
                metadata = info_json

            media_path = pick_downloaded_media_file(temp_dir, audio_only=audio_only)
            if not media_path or not media_path.exists():
                print(json.dumps({
                    "ok": False,
                    "error": "download completed but no media file found",
                    "speech": "The download finished but no media file was found."
                }))
                sys.exit(1)

            title = sanitize_name(metadata.get("title") or filename_override or "youtube_video")
            ext = media_path.suffix.lower()
            if filename_override:
                base = sanitize_name(filename_override)
                if Path(base).suffix:
                    desired_name = base
                else:
                    desired_name = f"{base}{ext}"
            else:
                desired_name = f"{title}{ext}"

            renamed = media_path.with_name(desired_name)
            media_path.rename(renamed)
            media_path = renamed

            tags = ["youtube", "download", "video" if not audio_only else "audio"]
            stash_result, space = save_media_to_stash(media_path, tags=tags)
            stash_ref = stash_result.get("ref")
            mime_type = stash_result.get("mime_type") or "application/octet-stream"
            file_size = stash_result.get("size_bytes", media_path.stat().st_size)

            if stash_ref and space:
                remember_download(space, stash_ref, media_path.name, metadata, url)

            duration_seconds = metadata.get("duration")
            uploader = metadata.get("uploader") or metadata.get("channel")

            speech = f"Downloaded YouTube {'audio' if audio_only else 'video'} and saved it to stash."
            if metadata.get("title"):
                speech = f"Downloaded {metadata.get('title')} and saved it to stash."

            print(json.dumps({
                "ok": True,
                "speech": speech,
                "data": {
                    "url": url,
                    "video_title": metadata.get("title") or title,
                    "duration_seconds": duration_seconds,
                    "channel": uploader,
                    "quality": quality,
                    "format": format_selector,
                    "attempt_used": attempt_used,
                    "filename": media_path.name,
                    "mime_type": mime_type,
                    "size_bytes": file_size,
                    "stash_ref": stash_ref,
                    "space_id": space.space_id if space else None,
                    "file_id": stash_result.get("file_id"),
                }
            }))

    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Error downloading YouTube video: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
