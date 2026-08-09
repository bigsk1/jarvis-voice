"""xAI Files API lifecycle and local catalog for public Canvas PDFs."""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from config import CANVAS_DIR
from config_loader import get_config_value

from .pdf_export import has_blocking_findings, validate_canvas_pdf


ALLOWED_TTL_DAYS = (1, 7, 30)
DEFAULT_TTL_DAYS = 7
DEFAULT_MAX_PDF_BYTES = 8 * 1024 * 1024
REGISTRY_PATH = CANVAS_DIR / ".shares" / "xai_pdf_registry.json"
_REGISTRY_LOCK = threading.RLock()
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


class XaiPdfShareError(RuntimeError):
    """Safe, user-facing xAI PDF share failure."""


class XaiPdfShareDisabled(XaiPdfShareError):
    """Raised when public xAI PDF sharing is not explicitly available."""


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


def get_xai_pdf_share_status() -> dict:
    """Return non-secret configuration details for the Canvas client."""
    enabled = _config_bool("CANVAS_XAI_PDF_SHARE", False)
    configured = bool(str(get_config_value("XAI_API_KEY", "") or "").strip())
    default_ttl = _config_int("CANVAS_XAI_PDF_SHARE_DEFAULT_TTL_DAYS", DEFAULT_TTL_DAYS)
    if default_ttl not in ALLOWED_TTL_DAYS:
        default_ttl = DEFAULT_TTL_DAYS
    max_pdf_bytes = max(
        1,
        _config_int("CANVAS_XAI_PDF_SHARE_MAX_BYTES", DEFAULT_MAX_PDF_BYTES),
    )

    reason = None
    if not enabled:
        reason = "Public xAI PDF sharing is disabled by configuration."
    elif not configured:
        reason = "XAI_API_KEY is not configured in the active Canvas mode."

    return {
        "enabled": enabled,
        "configured": configured,
        "available": enabled and configured,
        "reason": reason,
        "default_ttl_days": default_ttl,
        "allowed_ttl_days": list(ALLOWED_TTL_DAYS),
        "max_pdf_bytes": max_pdf_bytes,
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _protobuf_timestamp_iso(value, fallback: datetime) -> str:
    try:
        if hasattr(value, "ToDatetime"):
            result = value.ToDatetime(tzinfo=timezone.utc)
            return _iso(result)
    except (TypeError, ValueError, OverflowError):
        pass
    return _iso(fallback)


def _safe_pdf_filename(title: str, page_id: str) -> str:
    stem = _SAFE_FILENAME_RE.sub("-", str(title or "canvas-page").strip()).strip("-._")
    if not stem:
        stem = f"canvas-{page_id}"
    return f"{stem[:100]}.pdf"


def _is_valid_public_url(public_url: str) -> bool:
    try:
        parsed = urlparse(public_url)
    except ValueError:
        return False
    return parsed.scheme == "https" and (parsed.hostname or "").lower() == "files-cdn.x.ai"


def _is_not_found(exc: Exception) -> bool:
    message = str(exc).lower()
    return "not found" in message or "statuscode.not_found" in message or "404" in message


class XaiPdfShareRegistry:
    """Atomic JSON catalog stored outside the Canvas page glob."""

    def __init__(self, path: Path = REGISTRY_PATH):
        self.path = Path(path)

    def read(self) -> list[dict]:
        with _REGISTRY_LOCK:
            if not self.path.exists():
                return []
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise XaiPdfShareError("The local xAI PDF share catalog could not be read.") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("shares"), list):
                raise XaiPdfShareError("The local xAI PDF share catalog has an invalid format.")
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
                raise XaiPdfShareError("The local xAI PDF share catalog could not be saved.") from exc

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
        raise XaiPdfShareError("The requested xAI PDF share was not found in the local catalog.")

    def get(self, share_id: str) -> dict | None:
        return next((item for item in self.read() if item.get("share_id") == share_id), None)

    def list_for_page(self, page_id: str) -> list[dict]:
        with _REGISTRY_LOCK:
            now = _utc_now()
            records = [item for item in self.read() if item.get("page_id") == page_id]
            changed = False
            for record in records:
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
                all_records = self.read()
                by_id = {item.get("share_id"): item for item in records}
                for index, item in enumerate(all_records):
                    if item.get("share_id") in by_id:
                        all_records[index] = by_id[item.get("share_id")]
                self.write(all_records)
        records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return records


class XaiPdfShareService:
    """Upload, publish, revoke, and catalog Canvas PDF snapshots."""

    def __init__(self, *, client_factory=None, registry: XaiPdfShareRegistry | None = None):
        self._client_factory = client_factory
        self.registry = registry or XaiPdfShareRegistry()

    def _client(self):
        status = get_xai_pdf_share_status()
        if not status["available"]:
            raise XaiPdfShareDisabled(status["reason"] or "Public xAI PDF sharing is unavailable.")
        if self._client_factory is not None:
            return self._client_factory()
        try:
            from xai_sdk import Client
        except ImportError as exc:
            raise XaiPdfShareError("The installed xAI SDK does not support the Files API.") from exc
        return Client(api_key=str(get_config_value("XAI_API_KEY", "")).strip(), timeout=60.0)

    def publish(
        self,
        *,
        page_id: str,
        title: str,
        source_updated_at: str | None,
        pdf_payload: bytes,
        projection: dict,
        ttl_days: int,
        pdf_sha256: str,
    ) -> dict:
        if ttl_days not in ALLOWED_TTL_DAYS:
            raise XaiPdfShareError("Expiration must be 1, 7, or 30 days.")
        if has_blocking_findings(projection):
            raise XaiPdfShareError("Publishing was blocked by the PDF safety check.")

        status = get_xai_pdf_share_status()
        validate_canvas_pdf(pdf_payload, max_bytes=status["max_pdf_bytes"])
        client = self._client()
        filename = _safe_pdf_filename(title, page_id)
        uploaded_file = None
        public_created = False
        try:
            uploaded_file = client.files.upload(
                pdf_payload,
                filename=filename,
                expires_after=timedelta(days=ttl_days),
            )
            file_id = str(getattr(uploaded_file, "id", "") or "").strip()
            if not file_id:
                raise XaiPdfShareError("xAI uploaded the PDF without returning a file identifier.")

            public_result = client.files.create_public_url(file_id)
            public_created = True
            public_url = str(getattr(public_result, "public_url", "") or "").strip()
            if not _is_valid_public_url(public_url):
                raise XaiPdfShareError("xAI returned an unexpected public URL host.")

            now = _utc_now()
            expires_at = _protobuf_timestamp_iso(
                getattr(public_result, "expires_at", None),
                now + timedelta(days=ttl_days),
            )
            record = {
                "share_id": uuid.uuid4().hex,
                "page_id": page_id,
                "title": title,
                "filename": filename,
                "file_id": file_id,
                "public_url": public_url,
                "created_at": _iso(now),
                "expires_at": expires_at,
                "ttl_days": ttl_days,
                "status": "active",
                "source_updated_at": source_updated_at,
                "pdf_sha256": pdf_sha256,
                "pdf_bytes": len(pdf_payload),
            }
            self.registry.add(record)
            return record
        except XaiPdfShareError:
            self._cleanup_failed_publish(client, uploaded_file, public_created)
            raise
        except Exception as exc:
            self._cleanup_failed_publish(client, uploaded_file, public_created)
            raise XaiPdfShareError("xAI could not publish this PDF. No public share was kept.") from exc

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

    def revoke(self, share_id: str) -> dict:
        record = self.registry.get(share_id)
        if not record:
            raise XaiPdfShareError("The requested xAI PDF share was not found in the local catalog.")
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
                    raise XaiPdfShareError("xAI could not revoke the public URL.") from exc

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
                changes["cleanup_error"] = "The public URL was revoked, but xAI file deletion needs retrying."
        return self.registry.update(share_id, changes)

    def list_for_page(self, page_id: str) -> list[dict]:
        return self.registry.list_for_page(page_id)
