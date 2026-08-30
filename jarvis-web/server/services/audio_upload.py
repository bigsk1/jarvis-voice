"""Hardened Web audio uploads into server-owned Stash artifacts."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

JARVIS_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(JARVIS_ROOT / "lib"))

from audio_transcription import (  # noqa: E402
    SUPPORTED_AUDIO_EXTENSIONS,
    inspect_audio_file,
    load_audio_transcription_limits,
)
from config_loader import get_int  # noqa: E402
from stash_helper import (  # noqa: E402
    get_retention_policy,
    get_stash_dir,
    sanitize_filename,
)

_AUDIO_SPACE_RE = re.compile(r"^space_web_audio_([0-9a-f]{32})$")
_AUDIO_FILE_RE = re.compile(r"^f_[0-9a-f]{12}$")
_COMMIT_LOCK = threading.Lock()


class AudioUploadError(ValueError):
    """Typed, user-safe audio upload or attachment validation failure."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "audio_upload_invalid",
        status_code: int = 400,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.retryable = retryable

    def to_payload(self) -> dict:
        return {
            "ok": False,
            "error": str(self),
            "error_code": self.error_code,
            "retryable": self.retryable,
        }


class _SlidingUploadLimiter:
    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, client_ip: str, requests_per_minute: int) -> tuple[bool, int]:
        if requests_per_minute <= 0:
            return True, 0
        now = time.time()
        cutoff = now - 60
        with self._lock:
            timestamps = self._requests[str(client_ip or "unknown")]
            timestamps[:] = [stamp for stamp in timestamps if stamp > cutoff]
            if len(timestamps) >= requests_per_minute:
                retry_after = max(1, int(timestamps[0] + 60 - now) + 1)
                return False, retry_after
            timestamps.append(now)
        return True, 0

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()


_UPLOAD_LIMITER = _SlidingUploadLimiter()


def get_audio_upload_max_bytes() -> int:
    return load_audio_transcription_limits().max_file_bytes


def get_audio_upload_max_duration_seconds() -> int:
    return load_audio_transcription_limits().max_duration_seconds


def get_audio_upload_limits():
    """Return one immutable mode-scoped size/duration snapshot."""

    return load_audio_transcription_limits()


def check_audio_upload_rate(client_ip: str) -> tuple[bool, int]:
    if os.environ.get("API_RATE_LIMIT_ENABLED", "true").lower() not in {
        "1",
        "true",
        "yes",
    }:
        return True, 0
    return _UPLOAD_LIMITER.check(
        client_ip,
        get_int("WEB_AUDIO_UPLOAD_RATE_LIMIT_PER_MINUTE", 4),
    )


def reset_audio_upload_rate_limit_for_tests() -> None:
    _UPLOAD_LIMITER.reset()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _validated_upload_id(raw_upload_id: str) -> str:
    try:
        return str(uuid.UUID(str(raw_upload_id or "")))
    except (ValueError, TypeError, AttributeError) as exc:
        raise AudioUploadError(
            "A valid upload ID is required.",
            error_code="audio_upload_id_invalid",
        ) from exc


def _validate_filename_and_mime(filename: str, mime_type: str) -> tuple[str, str]:
    safe_name = sanitize_filename(filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_AUDIO_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_EXTENSIONS))
        raise AudioUploadError(
            f"Select a supported audio file ({supported}).",
            error_code="audio_upload_extension_invalid",
        )
    normalized_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime not in {"", "application/octet-stream"} and not (
        normalized_mime.startswith("audio/")
        or normalized_mime.startswith("video/")
    ):
        raise AudioUploadError(
            "The selected file is not identified as audio.",
            error_code="audio_upload_mime_invalid",
        )
    canonical_mime = normalized_mime or mimetypes.guess_type(safe_name)[0] or "audio/mpeg"
    return safe_name, canonical_mime


def _stream_to_stage(
    stream: BinaryIO,
    output_path: Path,
    *,
    max_bytes: int,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    try:
        with output_path.open("xb") as output:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray)):
                    raise TypeError("Upload stream returned non-binary data")
                total += len(chunk)
                if total > max_bytes:
                    raise AudioUploadError(
                        f"Audio is too large (max {max_bytes // (1024 * 1024)}MB).",
                        error_code="audio_upload_too_large",
                        status_code=413,
                    )
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except AudioUploadError:
        raise
    except Exception as exc:
        raise AudioUploadError(
            "The audio upload was interrupted. Please retry.",
            error_code="audio_upload_interrupted",
            status_code=500,
            retryable=True,
        ) from exc
    if total < 1:
        raise AudioUploadError(
            "The selected audio file is empty.",
            error_code="audio_upload_empty",
        )
    return total, digest.hexdigest()


def _attachment_from_committed_space(
    space_path: Path,
    *,
    expected_hash: str | None = None,
) -> dict:
    try:
        meta = json.loads((space_path / "meta.json").read_text(encoding="utf-8"))
        files = meta.get("files")
        file_meta = files[0] if isinstance(files, list) and len(files) == 1 else None
        if not isinstance(file_meta, dict):
            raise ValueError("missing file metadata")
        space_id = str(meta.get("space_id") or "")
        file_id = str(file_meta.get("file_id") or "")
        display_name = str(file_meta.get("name") or "")
        stored_name = str(file_meta.get("stored_name") or "")
        file_hash = str(file_meta.get("hash_sha256") or "")
        mime_type = str(file_meta.get("mime_type") or "")
        size_bytes = int(file_meta.get("size_bytes", -1))
        duration_seconds = float(file_meta.get("duration_seconds", 0))
        labels = set(meta.get("labels") or [])
        if (
            not _AUDIO_SPACE_RE.fullmatch(space_id)
            or space_path.name != space_id
            or not _AUDIO_FILE_RE.fullmatch(file_id)
            or meta.get("source") != "web_audio_upload"
            or not {"web_upload", "audio"}.issubset(labels)
            or file_meta.get("tool_origin") != "web_audio_upload"
            or display_name != stored_name
            or stored_name != sanitize_filename(stored_name)
            or Path(stored_name).suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS
            or not re.fullmatch(r"[0-9a-f]{64}", file_hash)
            or size_bytes < 1
            or duration_seconds <= 0
        ):
            raise ValueError("invalid audio upload provenance")
        upload_id = _validated_upload_id(meta.get("upload_id"))
        stored_path = space_path / stored_name
        if not stored_path.is_file():
            raise ValueError("missing stored audio")
        if expected_hash and file_hash != expected_hash:
            raise AudioUploadError(
                "This upload ID was already used for a different audio file.",
                error_code="audio_upload_id_conflict",
                status_code=409,
            )
        if stored_path.stat().st_size != size_bytes:
            raise ValueError("stored audio size mismatch")
        return {
            "kind": "audio",
            "stash_ref": f"stash://{space_id}/{file_id}",
            "space_id": space_id,
            "file_id": file_id,
            "filename": display_name,
            "size_bytes": size_bytes,
            "mime_type": mime_type,
            "sha256": file_hash,
            "duration_seconds": round(duration_seconds, 3),
            "upload_id": upload_id,
        }
    except AudioUploadError:
        raise
    except Exception as exc:
        raise AudioUploadError(
            "The stored audio attachment is unavailable.",
            error_code="audio_attachment_unavailable",
            status_code=409,
            retryable=True,
        ) from exc


def save_audio_upload(
    file_storage,
    upload_id: str,
    *,
    max_bytes: int | None = None,
    max_duration_seconds: int | None = None,
) -> tuple[dict, bool]:
    """Stream, inspect, and atomically commit one audio upload to Stash."""

    canonical_upload_id = _validated_upload_id(upload_id)
    safe_name, mime_type = _validate_filename_and_mime(
        getattr(file_storage, "filename", ""),
        getattr(file_storage, "content_type", ""),
    )
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        raise AudioUploadError(
            "No audio file was provided.", error_code="audio_upload_missing"
        )

    if max_bytes is None or max_duration_seconds is None:
        limits = get_audio_upload_limits()
        max_bytes = limits.max_file_bytes if max_bytes is None else max_bytes
        max_duration_seconds = (
            limits.max_duration_seconds
            if max_duration_seconds is None
            else max_duration_seconds
        )
    max_bytes = int(max_bytes)
    max_duration_seconds = int(max_duration_seconds)
    stash_root = get_stash_dir()
    stash_root.mkdir(parents=True, exist_ok=True)
    incoming_root = stash_root / ".incoming"
    incoming_root.mkdir(parents=True, exist_ok=True)

    space_id = f"space_web_audio_{uuid.UUID(canonical_upload_id).hex}"
    final_path = stash_root / space_id
    stage_path = Path(tempfile.mkdtemp(prefix=f"{space_id}.", dir=incoming_root))
    committed = False
    try:
        staged_audio = stage_path / safe_name
        size_bytes, file_hash = _stream_to_stage(
            stream, staged_audio, max_bytes=max_bytes
        )
        try:
            info = inspect_audio_file(
                staged_audio,
                max_file_bytes=max_bytes,
                max_duration_seconds=max_duration_seconds,
            )
        except ValueError as exc:
            raise AudioUploadError(
                str(exc),
                error_code="audio_upload_invalid",
                status_code=422,
            ) from exc

        file_id = f"f_{file_hash[:12]}"
        now = _utc_now()
        labels = ["web_upload", "audio"]
        retention_policy, ttl_days = get_retention_policy(labels, "session")
        meta = {
            "space_id": space_id,
            "created_at": now,
            "last_used_at": now,
            "labels": labels,
            "owner": "jarvis",
            "scope": "session",
            "ttl_days": ttl_days,
            "retention_policy": retention_policy,
            "pinned": False,
            "upload_id": canonical_upload_id,
            "source": "web_audio_upload",
            "files": [
                {
                    "file_id": file_id,
                    "name": safe_name,
                    "stored_name": safe_name,
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                    "hash_sha256": file_hash,
                    "duration_seconds": round(info.duration_seconds, 3),
                    "format_name": info.format_name,
                    "tags": ["user_upload", "audio", "web_upload"],
                    "tool_origin": "web_audio_upload",
                    "created_at": now,
                }
            ],
        }
        meta_path = stage_path / "meta.json"
        with meta_path.open("x", encoding="utf-8") as meta_file:
            json.dump(meta, meta_file, indent=2)
            meta_file.write("\n")
            meta_file.flush()
            os.fsync(meta_file.fileno())

        with _COMMIT_LOCK:
            if final_path.exists():
                return (
                    _attachment_from_committed_space(
                        final_path, expected_hash=file_hash
                    ),
                    True,
                )
            os.replace(stage_path, final_path)
            committed = True
        return _attachment_from_committed_space(final_path), False
    finally:
        if not committed and stage_path.exists():
            shutil.rmtree(stage_path, ignore_errors=True)


def validate_audio_attachment(raw_attachment: object) -> dict:
    if not isinstance(raw_attachment, dict) or raw_attachment.get("kind") != "audio":
        raise AudioUploadError(
            "Invalid audio attachment metadata.",
            error_code="audio_attachment_invalid",
        )
    stash_ref = str(raw_attachment.get("stash_ref") or "")
    if not stash_ref.startswith("stash://"):
        raise AudioUploadError(
            "The audio attachment reference is missing.",
            error_code="audio_attachment_invalid",
        )
    parts = stash_ref[8:].split("/", 1)
    if len(parts) != 2:
        raise AudioUploadError(
            "The audio attachment reference is invalid.",
            error_code="audio_attachment_invalid",
        )
    space_id, file_id = parts
    if not _AUDIO_SPACE_RE.fullmatch(space_id) or not _AUDIO_FILE_RE.fullmatch(file_id):
        raise AudioUploadError(
            "The audio attachment reference is not a Jarvis Web upload.",
            error_code="audio_attachment_invalid",
        )
    attachment = _attachment_from_committed_space(get_stash_dir() / space_id)
    if attachment["file_id"] != file_id or attachment["stash_ref"] != stash_ref:
        raise AudioUploadError(
            "The audio attachment reference does not match the stored file.",
            error_code="audio_attachment_invalid",
        )
    return attachment


def validate_audio_attachments(raw_attachments: object) -> list[dict]:
    if raw_attachments in (None, []):
        return []
    if not isinstance(raw_attachments, list) or len(raw_attachments) != 1:
        raise AudioUploadError(
            "Attach exactly one audio file at a time.",
            error_code="audio_attachment_count_invalid",
        )
    return [validate_audio_attachment(raw_attachments[0])]
