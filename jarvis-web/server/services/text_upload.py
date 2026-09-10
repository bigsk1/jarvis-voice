"""Bounded UTF-8 notes stored as durable, server-owned Web attachments."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from config_loader import get_int
from stash_helper import get_retention_policy, get_stash_dir, sanitize_filename
from werkzeug.datastructures import FileStorage

from .pdf_upload import _SlidingUploadLimiter

MAX_TEXT_BYTES = 100 * 1024
_TEXT_REFERENCE_RE = re.compile(r"stash://(space_web_text_([0-9a-f]{32}))/(f_[0-9a-f]{12})")
_MIME_TYPES = {"", "application/octet-stream", "text/plain", "text/markdown", "text/x-markdown"}
_COMMIT_LOCK = threading.Lock()
_UPLOAD_LIMITER = _SlidingUploadLimiter()


class TextUploadError(ValueError):
    """A user-safe failure at the text upload or stored-reference boundary."""

    def __init__(self, message: str, *, error_code: str = "text_upload_invalid",
                 status_code: int = 400, retryable: bool = False):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.retryable = retryable

    def to_payload(self) -> dict:
        return {"ok": False, "error": str(self), "error_code": self.error_code,
                "retryable": self.retryable}


def check_text_upload_rate(client_ip: str) -> tuple[bool, int]:
    if os.environ.get("API_RATE_LIMIT_ENABLED", "true").lower() not in {"1", "true", "yes"}:
        return True, 0
    return _UPLOAD_LIMITER.check(client_ip, get_int("WEB_TEXT_UPLOAD_RATE_LIMIT_PER_MINUTE", 12))


def reset_text_upload_rate_limit_for_tests() -> None:
    _UPLOAD_LIMITER.reset()


def _upload_uuid(value: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(value or ""))
    except (ValueError, TypeError, AttributeError) as exc:
        raise TextUploadError("A valid upload ID is required.", error_code="text_upload_id_invalid") from exc


def _filename(value: object) -> str:
    if not isinstance(value, str):
        raise TextUploadError("Select a UTF-8 .txt or .md file.", error_code="text_upload_extension_invalid")
    name = sanitize_filename(value)
    if Path(name).suffix.lower() not in {".txt", ".md"}:
        raise TextUploadError("Select a UTF-8 .txt or .md file.", error_code="text_upload_extension_invalid")
    return name


def _decode_text(payload: bytes) -> str:
    if len(payload) > MAX_TEXT_BYTES:
        raise TextUploadError("Text is too large (max 100KB).", error_code="text_upload_too_large", status_code=413)
    if not payload:
        raise TextUploadError("The selected text file is empty.", error_code="text_upload_empty")
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TextUploadError("Save this text file as UTF-8 and try again.", error_code="text_upload_encoding_invalid") from exc
    if "\x00" in content:
        raise TextUploadError("The selected file contains binary data.", error_code="text_upload_encoding_invalid")
    return content


def _read_committed(space_path: Path, *, expected_hash: str | None = None) -> tuple[dict, str]:
    """Rebuild metadata and content from one intact committed upload only."""
    try:
        root = get_stash_dir().resolve()
        if space_path.is_symlink() or space_path.resolve().parent != root:
            raise ValueError("invalid upload directory")
        meta_path = space_path / "meta.json"
        if meta_path.is_symlink() or meta_path.stat().st_size > 32768:
            raise ValueError("invalid upload metadata")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        files = meta.get("files")
        if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
            raise ValueError("invalid file metadata")
        file_meta = files[0]
        upload_uuid = _upload_uuid(meta.get("upload_id"))
        space_id = f"space_web_text_{upload_uuid.hex}"
        name = file_meta.get("stored_name")
        digest = file_meta.get("hash_sha256")
        size = file_meta.get("size_bytes")
        expected_mime = "text/markdown" if Path(str(name)).suffix.lower() == ".md" else "text/plain"
        if (meta.get("space_id") != space_id or space_path.name != space_id
                or meta.get("source") != "web_text_upload"
                or not {"web_upload", "text"}.issubset(set(meta.get("labels") or []))
                or file_meta.get("tool_origin") != "web_text_upload"
                or not isinstance(name, str) or _filename(name) != name
                or file_meta.get("name") != name
                or file_meta.get("mime_type") != expected_mime
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or file_meta.get("file_id") != f"f_{digest[:12]}"
                or type(size) is not int or not 0 < size <= MAX_TEXT_BYTES):
            raise ValueError("invalid text upload provenance")
        path = space_path / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise ValueError("missing or changed text file")
        with path.open("rb") as stream:
            payload = stream.read(MAX_TEXT_BYTES + 1)
        if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("text upload integrity mismatch")
        content = _decode_text(payload)
        if expected_hash is not None and digest != expected_hash:
            raise TextUploadError("This upload ID was already used for different text.",
                                  error_code="text_upload_id_conflict", status_code=409)
        return {
            "kind": "text", "stash_ref": f"stash://{space_id}/{file_meta['file_id']}",
            "space_id": space_id, "file_id": file_meta["file_id"], "filename": name,
            "size_bytes": size, "mime_type": expected_mime, "sha256": digest,
            "upload_id": str(upload_uuid),
        }, content
    except TextUploadError as exc:
        if exc.error_code == "text_upload_id_conflict":
            raise
        raise TextUploadError("The stored text attachment is unavailable. Please attach it again.",
                              error_code="text_attachment_unavailable", status_code=409) from exc
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        raise TextUploadError("The stored text attachment is unavailable. Please attach it again.",
                              error_code="text_attachment_unavailable", status_code=409) from exc


def save_text_upload(file_storage, upload_id: str) -> tuple[dict, bool]:
    """Commit validated original bytes and metadata together; retries reuse the source."""
    upload_uuid = _upload_uuid(upload_id)
    name = _filename(getattr(file_storage, "filename", ""))
    mime = str(getattr(file_storage, "content_type", "") or "").split(";", 1)[0].strip().lower()
    if mime not in _MIME_TYPES:
        raise TextUploadError("The selected file is not identified as text.", error_code="text_upload_mime_invalid")
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        raise TextUploadError("No text file was provided.", error_code="text_upload_missing")
    try:
        chunks = bytearray()
        while len(chunks) <= MAX_TEXT_BYTES:
            chunk = stream.read(min(65536, MAX_TEXT_BYTES + 1 - len(chunks)))
            if not chunk:
                break
            if not isinstance(chunk, (bytes, bytearray)):
                raise TypeError("non-binary upload stream")
            chunks.extend(chunk)
    except Exception as exc:
        raise TextUploadError("The text upload was interrupted. Please retry.",
                              error_code="text_upload_interrupted", status_code=500, retryable=True) from exc
    payload = bytes(chunks)
    _decode_text(payload)
    digest = hashlib.sha256(payload).hexdigest()
    space_id = f"space_web_text_{upload_uuid.hex}"
    root = get_stash_dir()
    root.mkdir(parents=True, exist_ok=True)
    incoming = root / ".incoming"
    if incoming.is_symlink():
        raise TextUploadError("Text upload storage is unavailable.", error_code="text_upload_failed", status_code=500)
    incoming.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f"{space_id}.", dir=incoming))
    final = root / space_id
    committed = False
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        labels = ["web_upload", "text"]
        retention, ttl = get_retention_policy(labels, "session")
        meta = {
            "space_id": space_id, "created_at": now, "last_used_at": now,
            "labels": labels, "owner": "jarvis", "scope": "session", "ttl_days": ttl,
            "retention_policy": retention, "pinned": False, "upload_id": str(upload_uuid),
            "source": "web_text_upload", "files": [{
                "file_id": f"f_{digest[:12]}", "name": name, "stored_name": name,
                "mime_type": "text/markdown" if Path(name).suffix.lower() == ".md" else "text/plain",
                "size_bytes": len(payload), "hash_sha256": digest,
                "tags": ["user_upload", "text", "web_upload"],
                "tool_origin": "web_text_upload", "created_at": now,
            }],
        }
        with (stage / name).open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        with (stage / "meta.json").open("x", encoding="utf-8") as output:
            json.dump(meta, output, indent=2)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        with _COMMIT_LOCK:
            if final.exists() or final.is_symlink():
                return _read_committed(final, expected_hash=digest)[0], True
            try:
                os.rename(stage, final)
            except OSError:
                # Another worker may have committed the same retry identity.
                if final.exists():
                    return _read_committed(final, expected_hash=digest)[0], True
                raise
            committed = True
        return _read_committed(final)[0], False
    finally:
        if not committed:
            shutil.rmtree(stage, ignore_errors=True)


def _validated_reference(raw_attachment: object) -> tuple[dict, str]:
    if not isinstance(raw_attachment, dict) or raw_attachment.get("kind") not in (None, "text"):
        raise TextUploadError("Invalid text attachment metadata.", error_code="text_attachment_invalid")
    reference = raw_attachment.get("stash_ref")
    match = _TEXT_REFERENCE_RE.fullmatch(reference) if isinstance(reference, str) else None
    if not match:
        raise TextUploadError("The text attachment reference is not a Jarvis Web upload.", error_code="text_attachment_invalid")
    attachment, content = _read_committed(get_stash_dir() / match.group(1))
    if attachment["stash_ref"] != reference:
        raise TextUploadError("The text attachment reference does not match the stored file.", error_code="text_attachment_invalid")
    return attachment, content


def validate_text_attachment(raw_attachment: object) -> dict:
    return _validated_reference(raw_attachment)[0]


def read_text_attachment(attachment: object) -> str:
    """Read complete bounded text from validated storage, never client-supplied content."""
    return _validated_reference(attachment)[1]


def ingest_text_context(raw: object, upload_id: str | None = None) -> dict:
    """Persist the legacy socket name/content input through the same upload boundary."""
    if not isinstance(raw, dict) or not isinstance(raw.get("content"), str):
        raise TextUploadError("Invalid attached text.", error_code="text_attachment_invalid")
    try:
        payload = raw["content"].encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TextUploadError("The attached text is not valid UTF-8.", error_code="text_upload_encoding_invalid") from exc
    _decode_text(payload)
    name = _filename(raw.get("name", "file.txt"))
    file = FileStorage(stream=io.BytesIO(payload), filename=name, content_type="text/plain")
    return save_text_upload(file, upload_id or str(uuid.uuid4()))[0]
