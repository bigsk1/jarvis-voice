"""Trusted document bundles shared by Web socket intake and saved history."""

from __future__ import annotations

import math
import re
import uuid

from stash_helper import get_stash_dir, sanitize_filename
from vision_multimodal import max_vision_images

from .audio_upload import AudioUploadError, validate_audio_attachment
from .pdf_upload import PDFUploadError, validate_pdf_attachment
from .text_upload import MAX_TEXT_BYTES, TextUploadError, validate_text_attachment
from .video_upload import VideoUploadError, validate_video_attachment

_REFERENCE_RE = re.compile(r"stash://(space_web_(pdf|audio|video|text)_[0-9a-f]{32})/(f_[0-9a-f]{12})")


class AttachmentBundleError(ValueError):
    """A malformed, excessive, or unavailable collection of Web sources."""

    def __init__(self, message: str, *, error_code: str = "attachment_bundle_invalid",
                 status_code: int = 400, retryable: bool = False):
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.retryable = retryable

    def to_payload(self) -> dict:
        return {"ok": False, "error": str(self), "error_code": self.error_code,
                "retryable": self.retryable}


def _reference(raw: object):
    if not isinstance(raw, dict):
        return None
    reference = raw.get("stash_ref")
    match = _REFERENCE_RE.fullmatch(reference) if isinstance(reference, str) else None
    if match and raw.get("kind") == match.group(2):
        return match
    return None


def validate_attachments(raw: object, mode: str, image_count: int = 0) -> list[dict]:
    """Validate every source and enforce a shared image/document count and text budget."""
    if mode not in ("cloud", "local"):
        raise AttachmentBundleError('Mode must be "cloud" or "local".')
    if type(image_count) is not int or image_count < 0:
        raise AttachmentBundleError("Invalid image attachment count.")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise AttachmentBundleError("Attachments must be a list.")
    limit = max_vision_images(mode)
    if len(raw) + image_count > limit:
        raise AttachmentBundleError(f"Maximum {limit} total attachments allowed in {mode} mode.",
                                    error_code="attachment_count_invalid")
    result = []
    seen = set()
    text_bytes = 0
    validators = {"pdf": validate_pdf_attachment, "audio": validate_audio_attachment,
                  "text": validate_text_attachment, "video": validate_video_attachment}
    for item in raw:
        match = _reference(item)
        if match is None:
            raise AttachmentBundleError("Each attachment must reference a Jarvis Web PDF, audio, video, or text upload.")
        reference = item["stash_ref"]
        if reference in seen:
            raise AttachmentBundleError("The same source is attached more than once.",
                                        error_code="attachment_duplicate")
        # The older per-kind validators validate provenance; also reject filesystem
        # links before delegating so a reference cannot escape the configured Stash.
        root = get_stash_dir()
        space = root / match.group(1)
        if space.is_symlink() or (space / "meta.json").is_symlink():
            raise AttachmentBundleError("The stored attachment is unavailable.",
                                        error_code="attachment_unavailable", status_code=409)
        try:
            attachment = validators[match.group(2)](item)
        except (PDFUploadError, AudioUploadError, TextUploadError, VideoUploadError) as exc:
            raise AttachmentBundleError(str(exc), error_code=exc.error_code,
                                        status_code=exc.status_code, retryable=exc.retryable) from exc
        path = space / attachment["filename"]
        if path.is_symlink() or path.resolve().parent != space.resolve():
            raise AttachmentBundleError("The stored attachment is unavailable.",
                                        error_code="attachment_unavailable", status_code=409)
        if attachment["kind"] == "text":
            text_bytes += attachment["size_bytes"]
            if text_bytes > MAX_TEXT_BYTES:
                raise AttachmentBundleError("Attached text files must total at most 100KB.",
                                            error_code="attachment_text_too_large", status_code=413)
        seen.add(reference)
        result.append(attachment)
    return result


def stored_attachments(message_data: object) -> list[dict]:
    """Return bounded reference metadata from history, without trusting paths or content.

    Historical references remain useful even after retention removes the file.
    Reading source content still requires its upload validator, which reports expiry.
    """
    if not isinstance(message_data, dict):
        return []
    raw = message_data.get("attachments")
    if not isinstance(raw, list):
        return []
    result = []
    seen = set()
    for item in raw[:max_vision_images("cloud")]:
        match = _reference(item)
        if match is None or item["stash_ref"] in seen:
            continue
        name = item.get("filename")
        size = item.get("size_bytes")
        if not isinstance(name, str) or not name or len(name) > 200 or name != sanitize_filename(name):
            continue
        if type(size) is not int or size < 1:
            continue
        kind = match.group(2)
        if kind == "text" and size > MAX_TEXT_BYTES:
            continue
        attachment = {"kind": kind, "stash_ref": item["stash_ref"],
                      "space_id": match.group(1), "file_id": match.group(3),
                      "filename": name, "size_bytes": size,
                      "upload_id": str(uuid.UUID(match.group(1).rsplit("_", 1)[1]))}
        if kind == "pdf":
            attachment["mime_type"] = "application/pdf"
            pages = item.get("page_count")
            if type(pages) is int and pages > 0:
                attachment["page_count"] = pages
        elif kind == "text":
            attachment["mime_type"] = "text/markdown" if name.lower().endswith(".md") else "text/plain"
        else:
            mime = item.get("mime_type")
            if isinstance(mime, str) and re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", mime):
                attachment["mime_type"] = mime
            duration = item.get("duration_seconds")
            if type(duration) in (int, float) and math.isfinite(duration) and duration > 0:
                attachment["duration_seconds"] = duration
            if kind == "video" and isinstance(item.get("has_audio"), bool):
                attachment["has_audio"] = item["has_audio"]
        digest = item.get("sha256")
        if isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
            attachment["sha256"] = digest
        if item.get("mode") in ("cloud", "local"):
            attachment["mode"] = item["mode"]
        result.append(attachment)
        seen.add(item["stash_ref"])
    return result
