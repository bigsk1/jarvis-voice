"""xAI Files API lifecycle and local catalog for generated-video shares."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from lib.config_loader import get_config_value

ALLOWED_TTL_DAYS = (1, 7, 30)
DEFAULT_TTL_DAYS = 7
# The xAI upload documentation currently states 48 MB while the public-URL
# page states 50 MiB. Use the smaller advertised boundary by default.
DEFAULT_MAX_VIDEO_BYTES = 48_000_000
_REGISTRY_LOCK = threading.RLock()
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class XaiVideoShareError(RuntimeError):
    """Safe, user-facing xAI video share failure."""


class XaiVideoShareDisabled(XaiVideoShareError):
    """Raised when public xAI video sharing is not explicitly available."""


class XaiVideoShareValidationError(XaiVideoShareError):
    """Raised when a local video is not eligible for public sharing."""


class XaiVideoShareConflict(XaiVideoShareError):
    """Raised when the reviewed local video changed before publishing."""


def _config_bool(name: str, default: bool = False) -> bool:
    fallback = "true" if default else "false"
    return str(get_config_value(name, fallback) or fallback).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _config_int(name: str, default: int) -> int:
    try:
        return int(get_config_value(name, default))
    except (TypeError, ValueError):
        return default


def get_xai_video_share_status() -> dict:
    """Return non-secret configuration details for API and Canvas clients."""
    enabled = _config_bool("CANVAS_XAI_VIDEO_SHARE", False)
    configured = bool(str(get_config_value("XAI_API_KEY", "") or "").strip())
    default_ttl = _config_int(
        "CANVAS_XAI_VIDEO_SHARE_DEFAULT_TTL_DAYS",
        DEFAULT_TTL_DAYS,
    )
    if default_ttl not in ALLOWED_TTL_DAYS:
        default_ttl = DEFAULT_TTL_DAYS
    max_video_bytes = max(
        1,
        _config_int("CANVAS_XAI_VIDEO_SHARE_MAX_BYTES", DEFAULT_MAX_VIDEO_BYTES),
    )

    reason = None
    if not enabled:
        reason = "Public xAI video sharing is disabled by configuration."
    elif not configured:
        reason = "XAI_API_KEY is not configured in the active Jarvis mode."

    return {
        "enabled": enabled,
        "configured": configured,
        "available": enabled and configured,
        "reason": reason,
        "default_ttl_days": default_ttl,
        "allowed_ttl_days": list(ALLOWED_TTL_DAYS),
        "max_video_bytes": max_video_bytes,
        "supported_extensions": [".mp4"],
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _protobuf_timestamp_iso(value, fallback: datetime) -> str:
    try:
        if hasattr(value, "ToDatetime"):
            return _iso(value.ToDatetime(tzinfo=timezone.utc))
    except (TypeError, ValueError, OverflowError):
        pass
    return _iso(fallback)


def _is_not_found(exc: Exception) -> bool:
    message = str(exc).lower()
    return "not found" in message or "statuscode.not_found" in message or "404" in message


def _is_valid_public_url(public_url: str) -> bool:
    try:
        parsed = urlparse(public_url)
    except ValueError:
        return False
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == "files-cdn.x.ai"


def _safe_remote_filename(filename: str) -> str:
    stem = _SAFE_FILENAME_RE.sub("-", Path(filename).stem).strip("-._") or "jarvis-video"
    return f"{stem[:100]}.mp4"


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class XaiVideoShareRegistry:
    """Atomic JSON share catalog stored beside generated-video data."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> list[dict]:
        with _REGISTRY_LOCK:
            if not self.path.exists():
                return []
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise XaiVideoShareError(
                    "The local xAI video share catalog could not be read."
                ) from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("shares"), list):
                raise XaiVideoShareError("The local xAI video share catalog has an invalid format.")
            return [dict(item) for item in payload["shares"] if isinstance(item, dict)]

    def write(self, records: list[dict]) -> None:
        with _REGISTRY_LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.path.with_name(
                f".{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
            )
            payload = {
                "schema_version": 1,
                "updated_at": _iso(_utc_now()),
                "shares": records,
            }
            try:
                temp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                os.replace(temp_path, self.path)
            except OSError as exc:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise XaiVideoShareError(
                    "The local xAI video share catalog could not be saved."
                ) from exc

    def add(self, record: dict) -> None:
        with _REGISTRY_LOCK:
            records = self.read()
            records.append(record)
            self.write(records)

    def update(self, share_id: str, changes: dict) -> dict:
        with _REGISTRY_LOCK:
            records = self.read()
            for record in records:
                if record.get("share_id") == share_id:
                    record.update(changes)
                    self.write(records)
                    return dict(record)
        raise XaiVideoShareError("The requested xAI video share was not found.")

    def get(self, share_id: str) -> dict | None:
        return next((item for item in self.read() if item.get("share_id") == share_id), None)

    def list_for_video(self, filename: str) -> list[dict]:
        with _REGISTRY_LOCK:
            all_records = self.read()
            now = _utc_now()
            changed = False
            for record in all_records:
                if record.get("status") != "active":
                    continue
                try:
                    expires_at = datetime.fromisoformat(
                        str(record.get("expires_at", "")).replace("Z", "+00:00")
                    )
                except (TypeError, ValueError):
                    continue
                if expires_at <= now:
                    record["status"] = "expired"
                    changed = True
            if changed:
                self.write(all_records)
            records = [item for item in all_records if item.get("filename") == filename]
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return records


class XaiVideoShareService:
    """Inspect, upload, publish, revoke, and catalog retained MP4 files."""

    def __init__(
        self,
        videos_dir: Path,
        *,
        client_factory=None,
        registry: XaiVideoShareRegistry | None = None,
        probe_func=None,
    ):
        self.videos_dir = Path(videos_dir)
        self._client_factory = client_factory
        self._probe_func = probe_func or self._probe_mp4
        self.registry = registry or XaiVideoShareRegistry(
            self.videos_dir / ".shares" / "xai_video_registry.json"
        )

    def _client(self):
        status = get_xai_video_share_status()
        if not status["available"]:
            raise XaiVideoShareDisabled(
                status["reason"] or "Public xAI video sharing is unavailable."
            )
        if self._client_factory is not None:
            return self._client_factory()
        try:
            from xai_sdk import Client
        except ImportError as exc:
            raise XaiVideoShareError(
                "The installed xAI SDK does not support the Files API."
            ) from exc
        return Client(
            api_key=str(get_config_value("XAI_API_KEY", "") or "").strip(),
            timeout=180.0,
        )

    def _resolve_video(self, filename: str) -> Path:
        if (
            not filename
            or filename != Path(filename).name
            or "/" in filename
            or "\\" in filename
            or ".." in filename
            or Path(filename).suffix.lower() != ".mp4"
        ):
            raise XaiVideoShareValidationError("Only retained MP4 videos can be shared publicly.")
        path = self.videos_dir / filename
        if path.is_symlink():
            raise XaiVideoShareValidationError("Symbolic-link videos cannot be shared publicly.")
        if not path.is_file():
            raise XaiVideoShareValidationError("Video not found.")
        try:
            if path.resolve().parent != self.videos_dir.resolve():
                raise XaiVideoShareValidationError("Invalid video path.")
        except OSError as exc:
            raise XaiVideoShareValidationError("The video path could not be resolved.") from exc
        return path

    @staticmethod
    def _probe_mp4(path: Path) -> dict:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=format_name,duration:stream=codec_type",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError as exc:
            raise XaiVideoShareValidationError(
                "ffprobe is required to validate a video before public sharing."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise XaiVideoShareValidationError("Video validation timed out.") from exc
        if result.returncode != 0:
            raise XaiVideoShareValidationError("The selected file is not a readable MP4 video.")
        try:
            payload = json.loads(result.stdout)
            format_info = payload.get("format") or {}
            streams = payload.get("streams") or []
            format_name = str(format_info.get("format_name") or "").lower()
            duration = float(format_info.get("duration") or 0)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise XaiVideoShareValidationError(
                "The selected MP4 has invalid media metadata."
            ) from exc
        if "mp4" not in format_name or not any(
            item.get("codec_type") == "video" for item in streams
        ):
            raise XaiVideoShareValidationError("The selected file is not an MP4 video.")
        return {"duration": max(0.0, duration), "format": format_name}

    def inspect_video(self, filename: str) -> dict:
        path = self._resolve_video(filename)
        stat = path.stat()
        max_bytes = get_xai_video_share_status()["max_video_bytes"]
        if stat.st_size <= 0:
            raise XaiVideoShareValidationError("Empty videos cannot be shared publicly.")
        if stat.st_size > max_bytes:
            raise XaiVideoShareValidationError(
                f"This video exceeds the configured public-share limit of {max_bytes} bytes."
            )
        media = self._probe_func(path)
        return {
            "filename": filename,
            "video_bytes": stat.st_size,
            "video_sha256": _sha256_path(path),
            "modified_at": _iso(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)),
            "duration": media.get("duration"),
            "format": media.get("format", "mp4"),
            "warnings": [
                "Video frames, audio, captions, and metadata are not scanned for secrets. Review the complete video before publishing."
            ],
        }

    def publish(
        self,
        *,
        filename: str,
        ttl_days: int,
        expected_video_sha256: str,
        provider: str | None = None,
    ) -> dict:
        if ttl_days not in ALLOWED_TTL_DAYS:
            raise XaiVideoShareValidationError("Expiration must be 1, 7, or 30 days.")
        inspection = self.inspect_video(filename)
        if not re.fullmatch(r"[a-f0-9]{64}", expected_video_sha256 or ""):
            raise XaiVideoShareConflict("Preview this video again before publishing.")
        if inspection["video_sha256"] != expected_video_sha256:
            raise XaiVideoShareConflict(
                "The local video changed after preview. Review it again before publishing."
            )

        path = self._resolve_video(filename)
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected_video_sha256:
            raise XaiVideoShareConflict(
                "The local video changed while it was being prepared. Review it again."
            )

        client = self._client()
        uploaded_file = None
        public_created = False
        try:
            uploaded_file = client.files.upload(
                payload,
                filename=_safe_remote_filename(filename),
                expires_after=timedelta(days=ttl_days),
            )
            file_id = str(getattr(uploaded_file, "id", "") or "").strip()
            if not file_id:
                raise XaiVideoShareError(
                    "xAI uploaded the video without returning a file identifier."
                )

            public_result = client.files.create_public_url(file_id)
            public_created = True
            public_url = str(getattr(public_result, "public_url", "") or "").strip()
            if not _is_valid_public_url(public_url):
                raise XaiVideoShareError("xAI returned an unexpected public URL host.")

            now = _utc_now()
            expires_at = _protobuf_timestamp_iso(
                getattr(public_result, "expires_at", None),
                now + timedelta(days=ttl_days),
            )
            record = {
                "share_id": uuid.uuid4().hex,
                "filename": filename,
                "file_id": file_id,
                "public_url": public_url,
                "created_at": _iso(now),
                "expires_at": expires_at,
                "ttl_days": ttl_days,
                "status": "active",
                "video_sha256": expected_video_sha256,
                "video_bytes": len(payload),
                "source_modified_at": inspection["modified_at"],
                "duration": inspection.get("duration"),
                "provider": provider,
            }
            self.registry.add(record)
            return record
        except XaiVideoShareError:
            self._cleanup_failed_publish(client, uploaded_file, public_created)
            raise
        except Exception as exc:
            self._cleanup_failed_publish(client, uploaded_file, public_created)
            raise XaiVideoShareError(
                "xAI could not publish this video. No public share was kept."
            ) from exc

    @staticmethod
    def _cleanup_failed_publish(client, uploaded_file, public_created: bool) -> None:
        file_id = str(getattr(uploaded_file, "id", "") or "").strip()
        if not file_id:
            return
        if public_created:
            try:
                client.files.revoke_public_url(file_id)
            except Exception:
                pass
        try:
            client.files.delete(file_id)
        except Exception:
            pass

    def list_for_video(self, filename: str) -> list[dict]:
        return self.registry.list_for_video(filename)

    def active_for_video(self, filename: str) -> list[dict]:
        return [
            record
            for record in self.list_for_video(filename)
            if record.get("status") in {"active", "revoked_cleanup_pending"}
        ]

    def revoke(self, share_id: str) -> dict:
        record = self.registry.get(share_id)
        if not record:
            raise XaiVideoShareError("The requested xAI video share was not found.")
        status = record.get("status")
        if status not in {"active", "revoked_cleanup_pending"}:
            return record

        client = self._client()
        file_id = str(record.get("file_id") or "")
        if status == "active":
            try:
                client.files.revoke_public_url(file_id)
            except Exception as exc:
                if not _is_not_found(exc):
                    raise XaiVideoShareError("xAI could not revoke the public video URL.") from exc

        now = _iso(_utc_now())
        changes = {
            "status": "revoked",
            "revoked_at": record.get("revoked_at") or now,
        }
        try:
            client.files.delete(file_id)
            changes["deleted_at"] = now
            changes["cleanup_error"] = None
        except Exception as exc:
            if not _is_not_found(exc):
                changes["status"] = "revoked_cleanup_pending"
                changes["cleanup_error"] = (
                    "The public URL was revoked, but xAI file deletion needs retrying."
                )
        return self.registry.update(share_id, changes)

    def revoke_all_for_video(self, filename: str) -> list[dict]:
        return [self.revoke(record["share_id"]) for record in self.active_for_video(filename)]
