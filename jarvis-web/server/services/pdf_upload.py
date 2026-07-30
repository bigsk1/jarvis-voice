"""Hardened PDF uploads from Jarvis Web into Stash."""

from __future__ import annotations

import hashlib
import json
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
from config_loader import get_int
from stash_helper import get_retention_policy, get_stash_dir, sanitize_filename


DEFAULT_MAX_PDF_BYTES = 50 * 1024 * 1024
_PDF_SPACE_RE = re.compile(r"^space_web_pdf_([0-9a-f]{32})$")
_PDF_FILE_RE = re.compile(r"^f_[0-9a-f]{12}$")
_ALLOWED_UPLOAD_MIME_TYPES = {
    "",
    "application/octet-stream",
    "application/pdf",
    "application/x-pdf",
}
_COMMIT_LOCK = threading.Lock()


class PDFUploadError(ValueError):
    """Typed, user-safe PDF upload or attachment validation failure."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "pdf_upload_invalid",
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
    """Small endpoint-local per-IP limiter for the Flask Web surface."""

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


def get_pdf_upload_max_bytes() -> int:
    """Return the configured hard upload cap."""
    configured_mb = get_int(
        "WEB_PDF_MAX_SIZE_MB",
        DEFAULT_MAX_PDF_BYTES // (1024 * 1024),
    )
    return max(1, configured_mb) * 1024 * 1024


def check_pdf_upload_rate(client_ip: str) -> tuple[bool, int]:
    """Apply the modest Web-only upload rate limit."""
    if os.environ.get("API_RATE_LIMIT_ENABLED", "true").lower() not in {
        "1",
        "true",
        "yes",
    }:
        return True, 0
    rpm = get_int("WEB_PDF_UPLOAD_RATE_LIMIT_PER_MINUTE", 6)
    return _UPLOAD_LIMITER.check(client_ip, rpm)


def reset_pdf_upload_rate_limit_for_tests() -> None:
    """Clear process-local limiter state for deterministic route tests."""
    _UPLOAD_LIMITER.reset()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _validated_upload_id(raw_upload_id: str) -> str:
    try:
        parsed = uuid.UUID(str(raw_upload_id or ""))
    except (ValueError, TypeError, AttributeError) as exc:
        raise PDFUploadError(
            "A valid upload ID is required.",
            error_code="pdf_upload_id_invalid",
        ) from exc
    return str(parsed)


def _validate_filename_and_mime(filename: str, mime_type: str) -> str:
    safe_name = sanitize_filename(filename)
    if not safe_name.lower().endswith(".pdf"):
        raise PDFUploadError(
            "Select a PDF file with a .pdf extension.",
            error_code="pdf_upload_extension_invalid",
        )

    normalized_mime = str(mime_type or "").split(";", 1)[0].strip().lower()
    if normalized_mime not in _ALLOWED_UPLOAD_MIME_TYPES:
        raise PDFUploadError(
            "The selected file is not identified as a PDF.",
            error_code="pdf_upload_mime_invalid",
        )
    return safe_name


def _stream_to_stage(
    stream: BinaryIO,
    output_path: Path,
    *,
    max_bytes: int,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    header = bytearray()

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
                    raise PDFUploadError(
                        f"PDF is too large (max {max_bytes // (1024 * 1024)}MB).",
                        error_code="pdf_upload_too_large",
                        status_code=413,
                    )
                if len(header) < 1024:
                    header.extend(chunk[: 1024 - len(header)])
                digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except PDFUploadError:
        raise
    except Exception as exc:
        raise PDFUploadError(
            "The PDF upload was interrupted. Please retry.",
            error_code="pdf_upload_interrupted",
            status_code=500,
            retryable=True,
        ) from exc

    if total == 0:
        raise PDFUploadError(
            "The selected PDF is empty.",
            error_code="pdf_upload_empty",
        )
    if b"%PDF-" not in bytes(header):
        raise PDFUploadError(
            "The selected file does not contain a valid PDF header.",
            error_code="pdf_upload_header_invalid",
        )
    return total, digest.hexdigest()


def _inspect_pdf(path: Path) -> int:
    try:
        import fitz
    except ImportError as exc:
        raise PDFUploadError(
            "PDF validation is unavailable on this server.",
            error_code="pdf_validation_unavailable",
            status_code=503,
            retryable=True,
        ) from exc

    try:
        with fitz.open(path) as document:
            if not document.is_pdf:
                raise PDFUploadError(
                    "The selected file is not a valid PDF.",
                    error_code="pdf_upload_invalid",
                )
            if document.needs_pass:
                raise PDFUploadError(
                    "Password-protected PDFs are not supported yet.",
                    error_code="pdf_upload_encrypted",
                    status_code=422,
                )
            page_count = int(document.page_count)
            if page_count < 1:
                raise PDFUploadError(
                    "The selected PDF has no readable pages.",
                    error_code="pdf_upload_no_pages",
                    status_code=422,
                )
            # Force the first page object to load so obviously corrupt cross-reference
            # tables fail before the Stash space becomes visible.
            document.load_page(0)
            return page_count
    except PDFUploadError:
        raise
    except Exception as exc:
        raise PDFUploadError(
            "The selected file is damaged or is not a readable PDF.",
            error_code="pdf_upload_invalid",
            status_code=422,
        ) from exc


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
        size_bytes = int(file_meta.get("size_bytes", -1))
        page_count = int(file_meta.get("page_count", 0))
        labels = set(meta.get("labels") or [])
        if (
            not _PDF_SPACE_RE.fullmatch(space_id)
            or space_path.name != space_id
            or not _PDF_FILE_RE.fullmatch(file_id)
            or meta.get("source") != "web_pdf_upload"
            or not {"web_upload", "pdf"}.issubset(labels)
            or file_meta.get("tool_origin") != "web_pdf_upload"
            or file_meta.get("mime_type") != "application/pdf"
            or display_name != stored_name
            or stored_name != sanitize_filename(stored_name)
            or not stored_name.lower().endswith(".pdf")
            or not re.fullmatch(r"[0-9a-f]{64}", file_hash)
            or size_bytes < 1
            or page_count < 1
        ):
            raise ValueError("invalid PDF upload provenance")
        upload_id = _validated_upload_id(meta.get("upload_id"))
        stored_path = space_path / stored_name
        if not stored_path.is_file():
            raise ValueError("missing stored PDF")
        if expected_hash and file_hash != expected_hash:
            raise PDFUploadError(
                "This upload ID was already used for a different PDF.",
                error_code="pdf_upload_id_conflict",
                status_code=409,
            )
        if stored_path.stat().st_size != size_bytes:
            raise ValueError("stored PDF size mismatch")
        attachment = {
            "kind": "pdf",
            "stash_ref": f"stash://{space_id}/{file_id}",
            "space_id": space_id,
            "file_id": file_id,
            "filename": display_name,
            "size_bytes": size_bytes,
            "mime_type": "application/pdf",
            "sha256": file_hash,
            "page_count": page_count,
            "upload_id": upload_id,
        }
    except PDFUploadError:
        raise
    except Exception as exc:
        raise PDFUploadError(
            "The stored PDF attachment is unavailable.",
            error_code="pdf_attachment_unavailable",
            status_code=409,
            retryable=True,
        ) from exc

    return attachment


def save_pdf_upload(
    file_storage,
    upload_id: str,
    *,
    max_bytes: int | None = None,
) -> tuple[dict, bool]:
    """Stream, validate, and atomically commit one PDF to a deterministic Stash space."""
    canonical_upload_id = _validated_upload_id(upload_id)
    safe_name = _validate_filename_and_mime(
        getattr(file_storage, "filename", ""),
        getattr(file_storage, "content_type", ""),
    )
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        raise PDFUploadError(
            "No PDF file was provided.",
            error_code="pdf_upload_missing",
        )

    max_bytes = int(max_bytes or get_pdf_upload_max_bytes())
    stash_root = get_stash_dir()
    stash_root.mkdir(parents=True, exist_ok=True)
    incoming_root = stash_root / ".incoming"
    incoming_root.mkdir(parents=True, exist_ok=True)

    space_id = f"space_web_pdf_{uuid.UUID(canonical_upload_id).hex}"
    final_path = stash_root / space_id
    stage_path = Path(tempfile.mkdtemp(prefix=f"{space_id}.", dir=incoming_root))
    committed = False

    try:
        staged_pdf = stage_path / safe_name
        size_bytes, file_hash = _stream_to_stage(
            stream,
            staged_pdf,
            max_bytes=max_bytes,
        )
        page_count = _inspect_pdf(staged_pdf)
        file_id = f"f_{file_hash[:12]}"
        now = _utc_now()
        labels = ["web_upload", "pdf"]
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
            "source": "web_pdf_upload",
            "files": [
                {
                    "file_id": file_id,
                    "name": safe_name,
                    "stored_name": safe_name,
                    "mime_type": "application/pdf",
                    "size_bytes": size_bytes,
                    "hash_sha256": file_hash,
                    "page_count": page_count,
                    "tags": ["user_upload", "pdf", "web_upload"],
                    "tool_origin": "web_pdf_upload",
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
                attachment = _attachment_from_committed_space(
                    final_path,
                    expected_hash=file_hash,
                )
                return attachment, True
            os.replace(stage_path, final_path)
            committed = True

        return _attachment_from_committed_space(final_path), False
    finally:
        if not committed and stage_path.exists():
            shutil.rmtree(stage_path, ignore_errors=True)


def validate_pdf_attachment(raw_attachment: object) -> dict:
    """Resolve a client-supplied reference back to server-owned PDF metadata."""
    if not isinstance(raw_attachment, dict):
        raise PDFUploadError(
            "Invalid PDF attachment metadata.",
            error_code="pdf_attachment_invalid",
        )
    if raw_attachment.get("kind") not in (None, "pdf"):
        raise PDFUploadError(
            "Unsupported attachment type.",
            error_code="pdf_attachment_invalid",
        )

    stash_ref = str(raw_attachment.get("stash_ref") or "")
    if not stash_ref.startswith("stash://"):
        raise PDFUploadError(
            "The PDF attachment reference is missing.",
            error_code="pdf_attachment_invalid",
        )
    parts = stash_ref[8:].split("/", 1)
    if len(parts) != 2:
        raise PDFUploadError(
            "The PDF attachment reference is invalid.",
            error_code="pdf_attachment_invalid",
        )
    space_id, file_id = parts
    if not _PDF_SPACE_RE.fullmatch(space_id) or not _PDF_FILE_RE.fullmatch(file_id):
        raise PDFUploadError(
            "The PDF attachment reference is not a Jarvis Web upload.",
            error_code="pdf_attachment_invalid",
        )

    attachment = _attachment_from_committed_space(get_stash_dir() / space_id)
    if attachment["file_id"] != file_id or attachment["stash_ref"] != stash_ref:
        raise PDFUploadError(
            "The PDF attachment reference does not match the stored file.",
            error_code="pdf_attachment_invalid",
        )

    return attachment


def validate_pdf_attachments(raw_attachments: object) -> list[dict]:
    """Validate the Web socket's bounded attachment collection."""
    if raw_attachments in (None, []):
        return []
    if not isinstance(raw_attachments, list) or len(raw_attachments) != 1:
        raise PDFUploadError(
            "Attach exactly one PDF at a time.",
            error_code="pdf_attachment_count_invalid",
        )
    return [validate_pdf_attachment(raw_attachments[0])]
