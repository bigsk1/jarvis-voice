"""Inspected Web video attachments backed by immutable Stash source media."""

from __future__ import annotations

import os
import re
from dataclasses import replace
from pathlib import Path

from audio_transcription import inspect_audio_file, load_audio_transcription_limits
from config_loader import get_int
from stash_helper import get_stash_dir, sanitize_filename
from video_analysis import (
    SUPPORTED_VIDEO_EXTENSIONS,
    NoVideoStreamError,
    inspect_video_file,
    load_video_analysis_limits,
)

from .audio_upload import (
    AudioUploadError,
    _attachment_from_committed_space,
    _save_media_upload,
    _SlidingUploadLimiter,
)


class VideoUploadError(AudioUploadError):
    """User-safe video upload or attachment validation error."""

    def __init__(self, message, *, error_code="video_upload_invalid", **kwargs):
        super().__init__(message, error_code=error_code, **kwargs)


_UPLOAD_LIMITER = _SlidingUploadLimiter()


def get_video_upload_limits():
    return load_video_analysis_limits()


def check_video_upload_rate(client_ip: str) -> tuple[bool, int]:
    if os.environ.get("API_RATE_LIMIT_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return True, 0
    return _UPLOAD_LIMITER.check(client_ip, get_int("WEB_VIDEO_UPLOAD_RATE_LIMIT_PER_MINUTE", 4))


def reset_video_upload_rate_limit_for_tests() -> None:
    _UPLOAD_LIMITER.reset()


def _validate_filename_and_mime(filename: str, mime_type: str) -> tuple[str, str]:
    name = sanitize_filename(filename)
    if Path(name).suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
        raise VideoUploadError(
            "Select a supported video file (MP4, WebM, MOV, MKV, AVI, M4V, or MPEG).",
            error_code="video_upload_extension_invalid",
        )
    mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if mime not in {"", "application/octet-stream", "application/mp4"} and not (
        mime.startswith("video/") or mime.startswith("audio/")
    ):
        raise VideoUploadError(
            "The selected file is not identified as video.", error_code="video_upload_mime_invalid"
        )
    return name, mime


def save_video_upload(
    file_storage, upload_id: str, *, max_bytes: int | None = None,
    max_duration_seconds: int | None = None,
) -> tuple[dict, bool]:
    """Inspect real streams; keep audio-only MP4/WebM on the audio contract."""
    limits = get_video_upload_limits()
    limits = replace(
        limits,
        max_file_bytes=limits.max_file_bytes if max_bytes is None else int(max_bytes),
        max_duration_seconds=(limits.max_duration_seconds if max_duration_seconds is None
                              else int(max_duration_seconds)),
    )

    def inspect_media(path, byte_limit, duration_limit):
        try:
            return "video", inspect_video_file(path, limits=limits)
        except NoVideoStreamError:
            # Only a valid audio stream can take this branch. Invalid video is
            # rejected by the video inspector rather than silently downgraded.
            audio_limits = load_audio_transcription_limits()
            return "audio", inspect_audio_file(
                path, max_file_bytes=min(byte_limit, audio_limits.max_file_bytes),
                max_duration_seconds=min(duration_limit, audio_limits.max_duration_seconds),
            )

    return _save_media_upload(
        file_storage, upload_id, kind="video", max_bytes=limits.max_file_bytes,
        max_duration_seconds=limits.max_duration_seconds, inspect_media=inspect_media,
        validate_filename=_validate_filename_and_mime, extensions=SUPPORTED_VIDEO_EXTENSIONS,
        error_type=VideoUploadError,
    )


def validate_video_attachment(raw_attachment: object) -> dict:
    if not isinstance(raw_attachment, dict) or raw_attachment.get("kind") != "video":
        raise VideoUploadError("Invalid video attachment metadata.", error_code="video_attachment_invalid")
    stash_ref = str(raw_attachment.get("stash_ref") or "")
    match = re.fullmatch(r"stash://(space_web_video_[0-9a-f]{32})/(f_[0-9a-f]{12})", stash_ref)
    if not match:
        raise VideoUploadError(
            "The video attachment reference is not a Jarvis Web upload.",
            error_code="video_attachment_invalid",
        )
    attachment = _attachment_from_committed_space(
        get_stash_dir() / match[1], kind="video", extensions=SUPPORTED_VIDEO_EXTENSIONS,
        error_type=VideoUploadError,
    )
    if attachment["stash_ref"] != stash_ref:
        raise VideoUploadError(
            "The video attachment reference does not match the stored file.",
            error_code="video_attachment_invalid",
        )
    return attachment
