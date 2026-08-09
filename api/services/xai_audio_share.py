"""xAI Files lifecycle for public waveform MP4s made from retained audio."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from lib.audio_catalog import AUDIO_EXTENSIONS
from lib.config_loader import get_config_value

ALLOWED_TTL_DAYS = (1, 7, 30)
DEFAULT_TTL_DAYS = 7
DEFAULT_MAX_PUBLIC_BYTES = 48_000_000
AUDIO_BITRATE_KBPS = 128
MIN_VIDEO_BITRATE_KBPS = 350
MAX_VIDEO_BITRATE_KBPS = 1_800
PUBLIC_SIZE_SAFETY_RATIO = 0.86
_REGISTRY_LOCK = threading.RLock()
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class XaiAudioShareError(RuntimeError):
    """Safe, user-facing xAI audio-card share failure."""


class XaiAudioShareDisabled(XaiAudioShareError):
    """Raised when public xAI audio-card sharing is unavailable."""


class XaiAudioShareValidationError(XaiAudioShareError):
    """Raised when retained audio cannot be converted and shared."""


class XaiAudioShareConflict(XaiAudioShareError):
    """Raised when retained audio changes between preview and publish."""


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


def get_xai_audio_share_status() -> dict:
    """Return non-secret configuration details for API and Canvas clients."""
    enabled = _config_bool("CANVAS_XAI_AUDIO_SHARE", False)
    configured = bool(str(get_config_value("XAI_API_KEY", "") or "").strip())
    default_ttl = _config_int(
        "CANVAS_XAI_AUDIO_SHARE_DEFAULT_TTL_DAYS",
        DEFAULT_TTL_DAYS,
    )
    if default_ttl not in ALLOWED_TTL_DAYS:
        default_ttl = DEFAULT_TTL_DAYS
    max_public_bytes = max(
        1,
        _config_int(
            "CANVAS_XAI_AUDIO_SHARE_MAX_BYTES",
            DEFAULT_MAX_PUBLIC_BYTES,
        ),
    )

    reason = None
    if not enabled:
        reason = "Public xAI audio-card sharing is disabled by configuration."
    elif not configured:
        reason = "XAI_API_KEY is not configured in the active Jarvis mode."

    return {
        "enabled": enabled,
        "configured": configured,
        "available": enabled and configured,
        "reason": reason,
        "default_ttl_days": default_ttl,
        "allowed_ttl_days": list(ALLOWED_TTL_DAYS),
        "max_public_bytes": max_public_bytes,
        "supported_extensions": sorted(AUDIO_EXTENSIONS),
        "public_format": "video/mp4",
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
    return (
        "not found" in message
        or "statuscode.not_found" in message
        or "404" in message
    )


def _is_valid_public_url(public_url: str) -> bool:
    try:
        parsed = urlparse(public_url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "files-cdn.x.ai"
    )


def _safe_remote_filename(filename: str) -> str:
    stem = _SAFE_FILENAME_RE.sub("-", Path(filename).stem).strip("-._")
    return f"{(stem or 'jarvis-audio')[:91]}-waveform.mp4"


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class XaiAudioShareRegistry:
    """Atomic JSON lifecycle catalog stored beside generated audio."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def read(self) -> list[dict]:
        with _REGISTRY_LOCK:
            if not self.path.exists():
                return []
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise XaiAudioShareError(
                    "The local xAI audio share catalog could not be read."
                ) from exc
            if not isinstance(payload, dict) or not isinstance(
                payload.get("shares"),
                list,
            ):
                raise XaiAudioShareError(
                    "The local xAI audio share catalog has an invalid format."
                )
            return [
                dict(item)
                for item in payload["shares"]
                if isinstance(item, dict)
            ]

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
                temp_path.write_text(
                    json.dumps(payload, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.replace(temp_path, self.path)
            except OSError as exc:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
                raise XaiAudioShareError(
                    "The local xAI audio share catalog could not be saved."
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
        raise XaiAudioShareError("The requested xAI audio share was not found.")

    def get(self, share_id: str) -> dict | None:
        return next(
            (
                item
                for item in self.read()
                if item.get("share_id") == share_id
            ),
            None,
        )

    def list_for_audio(self, filename: str) -> list[dict]:
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
            records = [
                item
                for item in all_records
                if item.get("filename") == filename
            ]
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return records


class XaiAudioShareService:
    """Convert, publish, revoke, and catalog waveform MP4 audio cards."""

    def __init__(
        self,
        audio_dir: Path,
        *,
        client_factory=None,
        registry: XaiAudioShareRegistry | None = None,
        probe_func=None,
        convert_func=None,
    ):
        self.audio_dir = Path(audio_dir)
        self._client_factory = client_factory
        self._probe_func = probe_func or self._probe_audio
        self._convert_func = convert_func or self._convert_to_public_mp4
        self.registry = registry or XaiAudioShareRegistry(
            self.audio_dir / ".shares" / "xai_audio_registry.json"
        )

    def _client(self):
        status = get_xai_audio_share_status()
        if not status["available"]:
            raise XaiAudioShareDisabled(
                status["reason"] or "Public xAI audio sharing is unavailable."
            )
        if self._client_factory is not None:
            return self._client_factory()
        try:
            from xai_sdk import Client
        except ImportError as exc:
            raise XaiAudioShareError(
                "The installed xAI SDK does not support the Files API."
            ) from exc
        return Client(
            api_key=str(get_config_value("XAI_API_KEY", "") or "").strip(),
            timeout=180.0,
        )

    def _resolve_audio(self, filename: str) -> Path:
        if (
            not filename
            or filename != Path(filename).name
            or "/" in filename
            or "\\" in filename
            or ".." in filename
            or Path(filename).suffix.lower() not in AUDIO_EXTENSIONS
        ):
            raise XaiAudioShareValidationError(
                "Only retained Canvas audio files can be shared publicly."
            )
        path = self.audio_dir / filename
        if path.is_symlink():
            raise XaiAudioShareValidationError(
                "Symbolic-link audio cannot be shared publicly."
            )
        if not path.is_file():
            raise XaiAudioShareValidationError("Audio not found.")
        try:
            if path.resolve().parent != self.audio_dir.resolve():
                raise XaiAudioShareValidationError("Invalid audio path.")
        except OSError as exc:
            raise XaiAudioShareValidationError(
                "The audio path could not be resolved."
            ) from exc
        return path

    @staticmethod
    def _probe_audio(path: Path) -> dict:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=format_name,duration:stream=codec_type,codec_name",
                    "-of",
                    "json",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError as exc:
            raise XaiAudioShareValidationError(
                "ffprobe is required to validate audio before public sharing."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise XaiAudioShareValidationError(
                "Audio validation timed out."
            ) from exc
        if result.returncode != 0:
            raise XaiAudioShareValidationError(
                "The selected file is not readable audio."
            )
        try:
            payload = json.loads(result.stdout)
            format_info = payload.get("format") or {}
            streams = payload.get("streams") or []
            duration = float(format_info.get("duration") or 0)
            audio_stream = next(
                (
                    item
                    for item in streams
                    if item.get("codec_type") == "audio"
                ),
                None,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise XaiAudioShareValidationError(
                "The selected audio has invalid media metadata."
            ) from exc
        if not audio_stream or duration <= 0:
            raise XaiAudioShareValidationError(
                "The selected file does not contain a complete audio stream."
            )
        return {
            "duration": duration,
            "format": str(format_info.get("format_name") or "audio"),
            "codec": str(audio_stream.get("codec_name") or "audio"),
        }

    @staticmethod
    def _video_bitrate_kbps(duration: float) -> int:
        """Spend the available xAI byte budget on visual quality safely."""
        if duration <= 0:
            return MIN_VIDEO_BITRATE_KBPS
        max_bytes = get_xai_audio_share_status()["max_public_bytes"]
        total_budget_kbps = (
            max_bytes
            * 8
            * PUBLIC_SIZE_SAFETY_RATIO
            / (duration * 1_000)
        )
        video_budget_kbps = int(total_budget_kbps - AUDIO_BITRATE_KBPS)
        return max(
            MIN_VIDEO_BITRATE_KBPS,
            min(MAX_VIDEO_BITRATE_KBPS, video_budget_kbps),
        )

    @staticmethod
    def _convert_to_public_mp4(
        source: Path,
        target: Path,
        duration: float,
    ) -> dict:
        timeout = max(180, int(duration * 3 + 60))
        video_bitrate_kbps = XaiAudioShareService._video_bitrate_kbps(duration)
        filter_graph = (
            "gradients=s=854x480:r=24:c0=0x0d1117:c1=0x27183f:"
            "x0=0:y0=0:x1=854:y1=480:speed=0.00001[bg];"
            "[0:a:0]aformat=channel_layouts=mono,"
            "showwaves=s=854x480:mode=cline:rate=24:"
            "colors=#5eead4:scale=sqrt:draw=full,"
            "format=rgba,colorkey=0x000000:0.02:0.0[wave];"
            "[bg][wave]overlay=shortest=1:format=auto,"
            "vignette,format=yuv420p[v]"
        )
        try:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-filter_complex",
                    filter_graph,
                    "-map",
                    "[v]",
                    "-map",
                    "0:a:0",
                    "-map_metadata",
                    "-1",
                    "-map_chapters",
                    "-1",
                    "-sn",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "24",
                    "-maxrate",
                    f"{video_bitrate_kbps}k",
                    "-bufsize",
                    f"{video_bitrate_kbps * 2}k",
                    "-tune",
                    "animation",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    f"{AUDIO_BITRATE_KBPS}k",
                    "-movflags",
                    "+faststart",
                    "-shortest",
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise XaiAudioShareValidationError(
                "ffmpeg is required to create the public waveform MP4."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise XaiAudioShareValidationError(
                "Waveform MP4 conversion timed out."
            ) from exc
        if result.returncode != 0 or not target.is_file():
            raise XaiAudioShareValidationError(
                "The waveform MP4 could not be created from this audio file."
            )
        if target.stat().st_size <= 0:
            raise XaiAudioShareValidationError(
                "The waveform MP4 conversion produced an empty file."
            )
        return {
            "duration": duration,
            "format": "mp4",
            "video_bitrate_kbps": video_bitrate_kbps,
        }

    def inspect_audio(self, filename: str) -> dict:
        path = self._resolve_audio(filename)
        stat = path.stat()
        if stat.st_size <= 0:
            raise XaiAudioShareValidationError(
                "Empty audio files cannot be shared publicly."
            )
        media = self._probe_func(path)
        return {
            "filename": filename,
            "audio_bytes": stat.st_size,
            "audio_sha256": _sha256_path(path),
            "modified_at": _iso(
                datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            ),
            "duration": media.get("duration"),
            "format": media.get("format"),
            "codec": media.get("codec"),
            "public_format": "video/mp4",
            "warnings": [
                "The complete audio is embedded in an animated waveform MP4. Audio content is not scanned for secrets. Review the complete track before publishing."
            ],
        }

    def publish(
        self,
        *,
        filename: str,
        ttl_days: int,
        expected_audio_sha256: str,
        provider: str | None = None,
    ) -> dict:
        if ttl_days not in ALLOWED_TTL_DAYS:
            raise XaiAudioShareValidationError(
                "Expiration must be 1, 7, or 30 days."
            )
        inspection = self.inspect_audio(filename)
        if not re.fullmatch(r"[a-f0-9]{64}", expected_audio_sha256 or ""):
            raise XaiAudioShareConflict(
                "Preview this audio again before publishing."
            )
        if inspection["audio_sha256"] != expected_audio_sha256:
            raise XaiAudioShareConflict(
                "The local audio changed after preview. Review it again before publishing."
            )

        source = self._resolve_audio(filename)
        client = self._client()
        uploaded_file = None
        public_created = False
        try:
            with tempfile.TemporaryDirectory(
                prefix="jarvis-audio-share-"
            ) as temp_dir:
                public_mp4 = Path(temp_dir) / _safe_remote_filename(filename)
                self._convert_func(
                    source,
                    public_mp4,
                    float(inspection.get("duration") or 0),
                )
                if _sha256_path(source) != expected_audio_sha256:
                    raise XaiAudioShareConflict(
                        "The local audio changed during conversion. Review it again."
                    )
                public_bytes = public_mp4.stat().st_size
                max_bytes = get_xai_audio_share_status()["max_public_bytes"]
                if public_bytes > max_bytes:
                    raise XaiAudioShareValidationError(
                        "The waveform MP4 exceeds the configured xAI public-share "
                        f"limit of {max_bytes} bytes."
                    )
                payload = public_mp4.read_bytes()

            uploaded_file = client.files.upload(
                payload,
                filename=_safe_remote_filename(filename),
                expires_after=timedelta(days=ttl_days),
            )
            file_id = str(getattr(uploaded_file, "id", "") or "").strip()
            if not file_id:
                raise XaiAudioShareError(
                    "xAI uploaded the waveform MP4 without returning a file identifier."
                )

            public_result = client.files.create_public_url(file_id)
            public_created = True
            public_url = str(
                getattr(public_result, "public_url", "") or ""
            ).strip()
            if not _is_valid_public_url(public_url):
                raise XaiAudioShareError(
                    "xAI returned an unexpected public URL host."
                )

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
                "audio_sha256": expected_audio_sha256,
                "audio_bytes": inspection["audio_bytes"],
                "public_bytes": len(payload),
                "source_modified_at": inspection["modified_at"],
                "duration": inspection.get("duration"),
                "provider": provider,
                "public_format": "video/mp4",
            }
            self.registry.add(record)
            return record
        except XaiAudioShareError:
            self._cleanup_failed_publish(client, uploaded_file, public_created)
            raise
        except Exception as exc:
            self._cleanup_failed_publish(client, uploaded_file, public_created)
            raise XaiAudioShareError(
                "xAI could not publish this audio card. No public share was kept."
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

    def list_for_audio(self, filename: str) -> list[dict]:
        self._resolve_audio(filename)
        return self.registry.list_for_audio(filename)

    def active_for_audio(self, filename: str) -> list[dict]:
        return [
            record
            for record in self.registry.list_for_audio(filename)
            if record.get("status") in {"active", "revoked_cleanup_pending"}
        ]

    def revoke(self, share_id: str) -> dict:
        record = self.registry.get(share_id)
        if not record:
            raise XaiAudioShareError(
                "The requested xAI audio share was not found."
            )
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
                    raise XaiAudioShareError(
                        "xAI could not revoke the public audio URL."
                    ) from exc

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

    def revoke_all_for_audio(self, filename: str) -> list[dict]:
        return [
            self.revoke(record["share_id"])
            for record in self.active_for_audio(filename)
        ]
