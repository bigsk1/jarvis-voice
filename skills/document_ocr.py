#!/usr/bin/env python3
"""First-class Jarvis client for an optional OVIS FastAPI OCR service.

The service performs local OvisOCR2 inference for OCR. Its optional
``/v1/generate`` route may then pass the OCR text to the text-instruction
backend configured on the OVIS host (for example, a local Ollama model).
Jarvis only knows the configured OVIS service URL.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from config_loader import load_config
from paths import resolve_local_file_tool_path, validate_tool_output_filename
from stash_helper import StashFile, get_space, open_space, resolve_file_path, safe_resolve_file

TOOL_NAME = "document_ocr"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 900
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5
READY_TIMEOUT_SECONDS = 5
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_JSON_RESPONSE_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_RESPONSE_BYTES = 100 * 1024 * 1024
MAX_ERROR_RESPONSE_BYTES = 64 * 1024
INLINE_EXCERPT_CHARS = 6000
MAX_INLINE_STRUCTURED_CHARS = 12000
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}


class OvisToolError(RuntimeError):
    """A safe, user-facing OVIS client error."""

    def __init__(self, message: str, *, code: str = "ovis_error", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def get_ovis_base_url() -> str:
    """Return a normalized, administrator-configured OVIS service URL."""
    raw = str(os.environ.get("OVIS_OCR_URL", "")).strip()
    if not raw:
        raise OvisToolError(
            "The optional document OCR service is not configured.",
            code="ovis_not_configured",
        )

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OvisToolError(
            "OVIS_OCR_URL must be an http or https service URL.",
            code="ovis_invalid_url",
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OvisToolError(
            "OVIS_OCR_URL may not contain credentials, a query, or a fragment.",
            code="ovis_invalid_url",
        )
    if parsed.path not in {"", "/"}:
        raise OvisToolError(
            "OVIS_OCR_URL must point to the service root, without an API path.",
            code="ovis_invalid_url",
        )
    return raw.rstrip("/")


def _request_timeout() -> tuple[int, int]:
    connect = _bounded_int_env(
        "OVIS_OCR_CONNECT_TIMEOUT_SECONDS",
        DEFAULT_CONNECT_TIMEOUT_SECONDS,
        1,
        30,
    )
    read = _bounded_int_env(
        "OVIS_OCR_TIMEOUT_SECONDS",
        DEFAULT_REQUEST_TIMEOUT_SECONDS,
        10,
        1100,
    )
    return connect, read


def _safe_error_from_response(response: requests.Response) -> OvisToolError:
    code = "ovis_http_error"
    message = f"The document OCR service returned HTTP {response.status_code}."
    try:
        raw = _bounded_response_bytes(response, MAX_ERROR_RESPONSE_BYTES)
        payload = json.loads(raw.decode("utf-8"))
    except (OvisToolError, UnicodeDecodeError, json.JSONDecodeError):
        payload = None

    if isinstance(payload, dict):
        detail = payload.get("detail", payload)
        if isinstance(detail, dict):
            raw_code = detail.get("code")
            raw_message = detail.get("message")
            if isinstance(raw_code, str) and raw_code.strip():
                code = raw_code.strip()[:120]
            if isinstance(raw_message, str) and raw_message.strip():
                message = raw_message.strip()[:1000]
        elif isinstance(detail, str) and detail.strip():
            message = detail.strip()[:1000]

    retryable = response.status_code in {408, 425, 429, 502, 503, 504}
    return OvisToolError(message, code=code, retryable=retryable)


def _bounded_response_bytes(response: requests.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("Content-Length")
    if declared:
        try:
            if int(declared) > max_bytes:
                raise OvisToolError(
                    "The document OCR service response exceeded Jarvis's safety limit.",
                    code="ovis_response_too_large",
                )
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise OvisToolError(
                "The document OCR service response exceeded Jarvis's safety limit.",
                code="ovis_response_too_large",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _request_json(
    method: str,
    endpoint: str,
    *,
    timeout: tuple[int, int] | tuple[int, int | float] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{get_ovis_base_url()}{endpoint}"
    try:
        response = requests.request(
            method,
            url,
            files=files,
            data=data,
            timeout=timeout or _request_timeout(),
            stream=True,
        )
    except requests.Timeout as exc:
        raise OvisToolError(
            "The document OCR service timed out. The request was not retried.",
            code="ovis_timeout",
            retryable=True,
        ) from exc
    except requests.RequestException as exc:
        raise OvisToolError(
            "The document OCR service is unavailable.",
            code="ovis_unavailable",
            retryable=True,
        ) from exc

    with response:
        if not response.ok:
            raise _safe_error_from_response(response)
        raw = _bounded_response_bytes(response, MAX_JSON_RESPONSE_BYTES)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OvisToolError(
            "The document OCR service returned invalid JSON.",
            code="ovis_invalid_response",
        ) from exc
    if not isinstance(payload, dict):
        raise OvisToolError(
            "The document OCR service returned an unexpected response.",
            code="ovis_invalid_response",
        )
    return payload


def _request_archive(endpoint: str, *, files: dict[str, Any], data: dict[str, Any]) -> bytes:
    url = f"{get_ovis_base_url()}{endpoint}"
    try:
        response = requests.post(
            url,
            files=files,
            data=data,
            timeout=_request_timeout(),
            stream=True,
        )
    except requests.Timeout as exc:
        raise OvisToolError(
            "The document OCR archive request timed out. It was not retried.",
            code="ovis_timeout",
            retryable=True,
        ) from exc
    except requests.RequestException as exc:
        raise OvisToolError(
            "The document OCR service is unavailable.",
            code="ovis_unavailable",
            retryable=True,
        ) from exc

    with response:
        if not response.ok:
            raise _safe_error_from_response(response)
        return _bounded_response_bytes(response, MAX_ARCHIVE_RESPONSE_BYTES)


def _ready_preflight() -> dict[str, Any]:
    """Fail quickly before uploading a potentially large document."""
    try:
        ready = _request_json(
            "GET",
            "/health/ready",
            timeout=(READY_TIMEOUT_SECONDS, READY_TIMEOUT_SECONDS),
        )
    except OvisToolError as exc:
        if exc.code == "ovis_http_error":
            exc.code = "ovis_not_ready"
        raise
    status = str(ready.get("status", "")).strip().lower()
    if ready.get("ready") is False or status in {"loading", "not_ready", "unavailable", "error"}:
        raise OvisToolError(
            "The document OCR service is running but is not ready yet.",
            code="ovis_not_ready",
            retryable=True,
        )
    return ready


def _resolve_input_path(args: dict[str, Any]) -> Path:
    file_path = args.get("file_path")
    stash_ref = args.get("stash_ref")
    space_id = args.get("space_id")
    file_id = args.get("file_id")

    if file_path:
        path = resolve_local_file_tool_path(file_path, include_pictures=True)
    elif stash_ref:
        result = safe_resolve_file(stash_ref=str(stash_ref))
        if not result.get("found"):
            raise ValueError(result.get("error") or f"Stash file not found: {stash_ref}")
        path = Path(str(result["path"])).resolve()
    elif space_id and file_id:
        path = Path(resolve_file_path(space_id=str(space_id), file_id=str(file_id))).resolve()
    else:
        raise ValueError("Provide stash_ref, space_id with file_id, or file_path.")

    if not path.exists() or not path.is_file():
        raise ValueError(f"Input file not found: {path.name}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported OCR input type. Supported extensions: {allowed}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("The OCR input file is empty.")
    if size > MAX_UPLOAD_BYTES:
        raise ValueError("The OCR input exceeds Jarvis's 50 MB upload limit.")
    return path


def _page_form(args: dict[str, Any]) -> dict[str, str]:
    form: dict[str, str] = {}
    page_start = args.get("page_start")
    page_end = args.get("page_end")
    if page_start is not None:
        page_start = int(page_start)
        if page_start < 1:
            raise ValueError("page_start must be at least 1.")
        form["page_start"] = str(page_start)
    if page_end is not None:
        page_end = int(page_end)
        if page_end < 1:
            raise ValueError("page_end must be at least 1.")
        form["page_end"] = str(page_end)
    if page_start is not None and page_end is not None and page_end < page_start:
        raise ValueError("page_end must be greater than or equal to page_start.")
    return form


def _add_max_new_tokens(form: dict[str, str], args: dict[str, Any]) -> None:
    max_new_tokens = args.get("max_new_tokens")
    if max_new_tokens is None:
        return
    max_new_tokens = int(max_new_tokens)
    if not 1 <= max_new_tokens <= 16384:
        raise ValueError("max_new_tokens must be between 1 and 16384.")
    form["max_new_tokens"] = str(max_new_tokens)


def _upload_parts(path: Path) -> tuple[dict[str, Any], Any]:
    handle = path.open("rb")
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {"file": (path.name, handle, mime_type)}, handle


def _output_space(args: dict[str, Any]):
    output_space_id = args.get("output_space_id")
    if output_space_id:
        return get_space(str(output_space_id))
    space, _ = open_space(labels=["document_ocr", "ocr"])
    return space


def _output_base_name(args: dict[str, Any], source: Path) -> str:
    requested = str(args.get("output_name") or "").strip()
    if requested:
        validated = validate_tool_output_filename(requested, label="OCR output name")
        stem = Path(validated).stem
    else:
        stem = source.stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")[:120]
    return stem or "document"


def _save_text(space, content: str, name: str, tags: list[str]) -> str:
    result = StashFile(space).save_text(
        content=content,
        name=validate_tool_output_filename(name, label="OCR output name"),
        on_conflict="version",
        tags=tags,
        tool_origin=TOOL_NAME,
    )
    return result["ref"]


def _save_json(space, content: Any, name: str, tags: list[str]) -> str:
    result = StashFile(space).save_json(
        content=content,
        name=validate_tool_output_filename(name, label="OCR output name"),
        on_conflict="version",
        tags=tags,
        tool_origin=TOOL_NAME,
    )
    return result["ref"]


def _save_binary(space, content: bytes, name: str, mime_type: str, tags: list[str]) -> str:
    result = StashFile(space).save_binary(
        data=content,
        name=validate_tool_output_filename(name, label="OCR output name"),
        mime_type=mime_type,
        on_conflict="version",
        tags=tags,
        tool_origin=TOOL_NAME,
    )
    return result["ref"]


def _excerpt(value: Any, limit: int = INLINE_EXCERPT_CHARS) -> str | None:
    if value in (None, ""):
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 44)].rstrip() + "\n...[truncated; full result saved to Stash]"


def _common_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "request_id",
        "filename",
        "document_type",
        "model",
        "ocr_model",
        "generation_model",
        "scope",
        "response_format",
        "pages_processed",
        "total_pages",
        "elapsed_seconds",
        "ocr_elapsed_seconds",
        "generation_elapsed_seconds",
    )
    return {key: payload[key] for key in keys if payload.get(key) is not None}


def action_status(_args: dict[str, Any]) -> dict[str, Any]:
    health = _request_json(
        "GET",
        "/health/live",
        timeout=(READY_TIMEOUT_SECONDS, READY_TIMEOUT_SECONDS),
    )
    ready: dict[str, Any] | None = None
    capabilities: dict[str, Any] | None = None
    warnings: list[str] = []
    try:
        ready = _request_json(
            "GET",
            "/health/ready",
            timeout=(READY_TIMEOUT_SECONDS, READY_TIMEOUT_SECONDS),
        )
    except OvisToolError as exc:
        warnings.append(str(exc))
    try:
        capabilities = _request_json(
            "GET",
            "/v1/capabilities",
            timeout=(READY_TIMEOUT_SECONDS, READY_TIMEOUT_SECONDS),
        )
    except OvisToolError as exc:
        warnings.append(str(exc))

    ready_flag = bool(ready and ready.get("ready", ready.get("status") == "ready"))
    if health.get("status") == "ok" and ready is not None and "ready" not in ready:
        ready_flag = str(ready.get("status", "")).lower() not in {
            "loading",
            "not_ready",
            "unavailable",
            "error",
        }
    data: dict[str, Any] = {
        "action": "status",
        "ready": ready_flag,
        "health": health,
    }
    if ready is not None:
        data["readiness"] = ready
    if capabilities is not None:
        data["capabilities"] = capabilities
    if warnings:
        data["warnings"] = warnings
    return {
        "ok": True,
        "speech": "The document OCR service is ready." if ready_flag else "The document OCR service responded but is not ready.",
        "data": data,
    }


def action_ocr(args: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_input_path(args)
    _ready_preflight()
    form = _page_form(args)
    _add_max_new_tokens(form, args)
    form["keep_region_tags"] = str(bool(args.get("keep_region_tags", True))).lower()
    form["include_region_data"] = str(bool(args.get("include_region_data", False))).lower()
    files, handle = _upload_parts(source)
    try:
        payload = _request_json("POST", "/v1/ocr", files=files, data=form)
    finally:
        handle.close()

    markdown = str(payload.get("markdown") or "")
    data = {"action": "ocr", **_common_metadata(payload)}
    data["markdown_excerpt"] = _excerpt(markdown)
    pages = payload.get("pages")
    if isinstance(pages, list):
        data["pages"] = [
            {
                key: page[key]
                for key in ("page_number", "elapsed_seconds")
                if isinstance(page, dict) and page.get(key) is not None
            }
            for page in pages[:100]
            if isinstance(page, dict)
        ]

    if args.get("save_to_stash", True):
        space = _output_space(args)
        base = _output_base_name(args, source)
        data["markdown_stash_ref"] = _save_text(
            space,
            markdown,
            f"{base}_ocr.md",
            ["document_ocr", "ocr", "markdown"],
        )
        data["json_stash_ref"] = _save_json(
            space,
            payload,
            f"{base}_ocr.json",
            ["document_ocr", "ocr", "json"],
        )
        data["stash_ref"] = data["markdown_stash_ref"]
        data["space_id"] = space.space_id

    pages_processed = data.get("pages_processed", len(data.get("pages", [])))
    return {
        "ok": True,
        "speech": f"OCR completed for {pages_processed} page(s).",
        "data": data,
    }


def _validated_json_schema(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("json_schema must be valid JSON.") from exc
    elif isinstance(value, dict):
        parsed = value
    else:
        raise ValueError("json_schema must be a JSON object or JSON string.")
    if not isinstance(parsed, dict):
        raise ValueError("json_schema must describe a JSON object.")
    encoded = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > 20000:
        raise ValueError("json_schema exceeds the OVIS 20,000-character limit.")
    return encoded


def action_extract(args: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_input_path(args)
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required for action=extract.")
    if len(prompt) > 8000:
        raise ValueError("prompt exceeds the OVIS 8,000-character limit.")
    _ready_preflight()

    scope = str(args.get("scope") or "document").strip().lower()
    response_format = str(args.get("response_format") or "text").strip().lower()
    if scope not in {"document", "page"}:
        raise ValueError("scope must be document or page.")
    if response_format not in {"text", "markdown", "json"}:
        raise ValueError("response_format must be text, markdown, or json.")

    form = _page_form(args)
    form.update({"prompt": prompt, "scope": scope, "response_format": response_format})
    schema = _validated_json_schema(args.get("json_schema"))
    if schema is not None:
        if response_format != "json":
            raise ValueError("json_schema requires response_format=json.")
        form["json_schema"] = schema
    _add_max_new_tokens(form, args)

    files, handle = _upload_parts(source)
    try:
        payload = _request_json("POST", "/v1/generate", files=files, data=form)
    finally:
        handle.close()

    output = payload.get("output")
    parsed_json = payload.get("parsed_json")
    data = {"action": "extract", **_common_metadata(payload)}
    data["output_excerpt"] = _excerpt(output)
    if parsed_json is not None:
        encoded = json.dumps(parsed_json, ensure_ascii=False, default=str)
        if len(encoded) <= MAX_INLINE_STRUCTURED_CHARS:
            data["parsed_json"] = parsed_json
        else:
            data["parsed_json_excerpt"] = _excerpt(parsed_json)

    pages = payload.get("pages")
    if isinstance(pages, list):
        data["page_outputs"] = [
            {
                "page_number": page.get("page_number"),
                "output_excerpt": _excerpt(page.get("output"), 1200),
                "elapsed_seconds": page.get("elapsed_seconds"),
            }
            for page in pages[:100]
            if isinstance(page, dict)
        ]

    if args.get("save_to_stash", True):
        space = _output_space(args)
        base = _output_base_name(args, source)
        extension = {"text": "txt", "markdown": "md", "json": "json"}[response_format]
        primary_ref: str | None = None
        if response_format == "json" and parsed_json is not None:
            primary_ref = _save_json(
                space,
                parsed_json,
                f"{base}_extracted.{extension}",
                ["document_ocr", "extract", response_format],
            )
        elif output is not None:
            primary_ref = _save_text(
                space,
                str(output),
                f"{base}_extracted.{extension}",
                ["document_ocr", "extract", response_format],
            )
        if primary_ref:
            data["output_stash_ref"] = primary_ref
        data["response_json_stash_ref"] = _save_json(
            space,
            payload,
            f"{base}_extract_response.json",
            ["document_ocr", "extract", "response"],
        )
        data["stash_ref"] = primary_ref or data["response_json_stash_ref"]
        data["space_id"] = space.space_id

    return {
        "ok": True,
        "speech": "Document extraction completed.",
        "data": data,
    }


def action_archive(args: dict[str, Any]) -> dict[str, Any]:
    source = _resolve_input_path(args)
    _ready_preflight()
    form = _page_form(args)
    _add_max_new_tokens(form, args)
    files, handle = _upload_parts(source)
    try:
        archive = _request_archive("/v1/ocr/archive", files=files, data=form)
    finally:
        handle.close()

    space = _output_space(args)
    base = _output_base_name(args, source)
    archive_ref = _save_binary(
        space,
        archive,
        f"{base}_ocr.zip",
        "application/zip",
        ["document_ocr", "ocr", "archive"],
    )
    return {
        "ok": True,
        "speech": "OCR archive created and saved to Stash.",
        "data": {
            "action": "archive",
            "filename": source.name,
            "archive_stash_ref": archive_ref,
            "stash_ref": archive_ref,
            "space_id": space.space_id,
            "size_bytes": len(archive),
        },
    }


def execute(args: dict[str, Any]) -> dict[str, Any]:
    action = str(args.get("action") or "ocr").strip().lower()
    aliases = {"generate": "extract", "json": "extract", "health": "status"}
    action = aliases.get(action, action)
    handlers = {
        "status": action_status,
        "ocr": action_ocr,
        "extract": action_extract,
        "archive": action_archive,
    }
    handler = handlers.get(action)
    if handler is None:
        raise ValueError("action must be status, ocr, extract, or archive.")
    return handler(args)


def main() -> int:
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        if not isinstance(args, dict):
            raise ValueError("Tool input must be a JSON object.")
        load_config()
        result = execute(args)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except OvisToolError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "speech": str(exc),
                    "error": str(exc),
                    "data": {
                        "action": str(locals().get("args", {}).get("action", "ocr")),
                        "error_code": exc.code,
                        "retryable": exc.retryable,
                    },
                },
                ensure_ascii=False,
            )
        )
        return 1
    except (ValueError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "speech": f"Document OCR request failed: {exc}",
                    "error": str(exc),
                    "data": {"action": str(locals().get("args", {}).get("action", "ocr"))},
                },
                ensure_ascii=False,
            )
        )
        return 1
    except Exception:
        print(
            json.dumps(
                {
                    "ok": False,
                    "speech": "Document OCR failed because of an unexpected local error.",
                    "error": "Unexpected document OCR error",
                    "data": {"action": str(locals().get("args", {}).get("action", "ocr"))},
                },
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
