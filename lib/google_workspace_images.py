"""Bounded inline Workspace images become Stash files, never prompt payloads.

Accept up to four PNG/JPEG/GIF/WebP images, 8 MiB per image and 16 MiB
aggregate decoded bytes per call, with a 40-million-pixel first-frame limit.
No remote image URLs are fetched and no vision provider is invoked here.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import time
import warnings
from itertools import islice
from typing import Any

MAX_IMAGES = 4
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
_FORMATS = {"image/png": ("PNG", "png"), "image/jpeg": ("JPEG", "jpg"),
            "image/gif": ("GIF", "gif"), "image/webp": ("WEBP", "webp")}
_BASE64_IMAGE = re.compile(r"\[base64_image:[^\]]+\][A-Za-z0-9+/=]+", re.IGNORECASE)
_DATA_IMAGE = re.compile(r"data:image/[^\s,;\"'<>]+;base64,[A-Za-z0-9+/=]+", re.IGNORECASE)


def without_image_bytes(value: Any, depth: int = 0) -> Any:
    """Remove protocol image bytes and legacy inline image text before replay."""
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        mime = value.get("mimeType")
        if value.get("type") == "image" or (isinstance(mime, str) and mime.startswith("image/") and "data" in value):
            return {"type": "image", "mimeType": mime if isinstance(mime, str) else None,
                    "delivery": "Inline image bytes omitted; inspect image_delivery."}
        return {key: without_image_bytes(child, depth + 1) for key, child in islice(value.items(), 30)}
    if isinstance(value, list):
        return [without_image_bytes(child, depth + 1) for child in value[:20]]
    if isinstance(value, str):
        return _DATA_IMAGE.sub("[inline image bytes omitted]",
                               _BASE64_IMAGE.sub("[inline image bytes omitted]", value))
    return value


def image_delivery(received: int, saved: int, errors: list[str]) -> dict:
    status = "saved" if saved == received and saved else "partial" if saved else "unavailable"
    note = (f"Received {received} inline image(s); saved {saved} to Jarvis Stash. "
            "These images have not been visually inspected. Use analyze_image with the "
            "saved stash:// references to inspect them.")
    if errors:
        note += " Do not repeat the Google action because local image delivery failed."
    return {"status": status, "received": received, "saved": saved, "errors": errors, "note": note}


def _decode_image(item: dict, remaining: int) -> tuple[bytes, str, str]:
    mime = item.get("mimeType")
    if not isinstance(mime, str) or mime not in _FORMATS:
        raise ValueError("Unsupported inline image MIME type")
    encoded = item.get("data")
    limit = min(MAX_IMAGE_BYTES, remaining)
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("Missing inline image base64")
    if len(encoded) > 4 * ((limit + 2) // 3):
        raise ValueError("Inline image exceeds per-image or aggregate byte limit")
    try:
        body = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Invalid inline image base64") from exc
    if len(body) > limit:
        raise ValueError("Inline image exceeds per-image or aggregate byte limit")
    return body, mime, _FORMATS[mime][1]


def _validate_image(body: bytes, mime: str) -> None:
    from PIL import Image

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as image:
                if image.format != _FORMATS[mime][0]:
                    raise ValueError("Inline image MIME type does not match its bytes")
                if min(image.size) < 1 or image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Inline image exceeds pixel limit")
                image.verify()
            # Decode the first frame too: a recognizable header is insufficient.
            with Image.open(io.BytesIO(body)) as image:
                image.load()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid or unsafe inline image bytes") from exc


def stash_workspace_images(raw: dict, result: dict) -> dict:
    """Save inline bytes locally after the single upstream call has completed."""
    images = [item for item in raw.get("content", [])
              if isinstance(item, dict) and item.get("type") == "image"]
    if not images:
        return result
    from config_loader import get_active_config_mode
    from mcp_client import _check_remote_call_budget
    from stash_helper import StashFile, open_space
    data = result["data"]
    errors = []
    artifacts = []
    total = 0
    space = None
    if not result.get("ok"):
        errors.append("Google returned an error; inline images were not saved")
    else:
        for index, item in enumerate(images[:MAX_IMAGES], 1):
            try:
                budget = _check_remote_call_budget()
                body, mime, suffix = _decode_image(item, MAX_TOTAL_BYTES - total)
                total += len(body)
                _validate_image(body, mime)
                budget = _check_remote_call_budget()
                lock_timeout = min(5, max(0, budget.deadline - time.monotonic())) if budget else 5
                if space is None:
                    space, _ = open_space(labels=["google_workspace"], scope="project", lock_timeout=lock_timeout)
                budget = _check_remote_call_budget()
                lock_timeout = min(5, max(0, budget.deadline - time.monotonic())) if budget else 5
                with space.transaction(timeout=lock_timeout):
                    _check_remote_call_budget()
                    saved = StashFile(space).save_binary(
                        body, name=f"google_workspace_image_{index}.{suffix}", mime_type=mime,
                        on_conflict="version", tags=["google_workspace"],
                        tool_origin="mcp_google_workspace_" + data["tool"],
                    )
                artifact = {key: saved[key] for key in ("ref", "file_id", "name", "mime_type", "size_bytes")}
                mode = get_active_config_mode()
                artifact.update(space_id=space.space_id, mode=mode,
                                download_url=f"/api/stash/{space.space_id}/{saved['file_id']}?mode={mode}")
                artifacts.append(artifact)
            except ValueError as exc:
                errors.append(f"Image {index}: {exc}")
            except Exception as exc:
                errors.append(f"Image {index}: local image save unavailable ({type(exc).__name__})")
    if len(images) > MAX_IMAGES:
        errors.append(f"Image count exceeds {MAX_IMAGES}; {len(images) - MAX_IMAGES} image(s) omitted")
    if artifacts:
        data.setdefault("artifacts", []).extend(artifacts)
    delivery = image_delivery(len(images), len(artifacts), errors)
    data["image_delivery"] = delivery
    refs = "\n".join(f"Stashed image: {artifact['ref']}" for artifact in artifacts)
    data["response_text"] += "\n" + delivery["note"] + ("\n" + refs if refs else "")
    return result
