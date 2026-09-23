"""Authenticated source library endpoints using the normal Web request scope."""

import hashlib
import io
import json
import os
import sqlite3
from datetime import datetime
from functools import wraps
from urllib.parse import urlsplit

from filelock import Timeout
from flask import Blueprint, current_app, jsonify, request, send_file
from source_library import MAX_SOURCE_BYTES, LibraryError, LibraryUnavailableError, SourceLibrary
from stash_helper import get_stash_dir
from webui_auth import require_auth

from ..services.attachment_bundle import AttachmentBundleError, validate_attachments
from .api import _scoped_request_config

library_bp = Blueprint("library", __name__, url_prefix="/api/library")


@library_bp.before_request
def limit_source_write_bodies():
    # The shared mode-scope decorator parses JSON before calling the handler.
    if request.endpoint == "library.save_edited_copy":
        denied = require_auth(lambda: None)()
        if denied is not None:
            return denied
        if request.content_length is None or request.content_length > MAX_SOURCE_BYTES + 4096:
            return jsonify(ok=False, error="Edited text is too large or has no Content-Length."), 413
    if request.endpoint in {"library.save_capture", "library.save_attachment"}:
        denied = require_auth(lambda: None)()
        if denied is not None:
            return denied
        # JSON escaping can make a 100KB DOM snapshot larger on the wire.
        limit = 256 * 1024 if request.endpoint == "library.save_capture" else 4096
        if request.content_length is None or request.content_length > limit:
            return jsonify(ok=False, error="Save request is too large or has no Content-Length."), 413


def library_request(handler):
    @wraps(handler)
    @require_auth
    @_scoped_request_config
    def wrapped(*args, **kwargs):
        try:
            return handler(SourceLibrary(), *args, **kwargs)
        except LibraryUnavailableError:
            return jsonify(
                ok=False, error="The source library store is unavailable or unsafe. Check its directory and retry."
            ), 503
        except LibraryError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except AttachmentBundleError as exc:
            return jsonify(ok=False, error=str(exc)), exc.status_code
        except (sqlite3.OperationalError, OSError):
            return jsonify(
                ok=False, error="The source library is busy or unavailable. Please retry."
            ), 503

    return wrapped


def number(name, default):
    value = request.args.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise LibraryError(f"{name} must be an integer.") from exc


@library_bp.get("")
@library_request
def browse(library):
    if request.args.get("q") is not None:
        return jsonify(
            ok=True,
            **library.search(
                request.args["q"],
                source_id=request.args.get("source"),
                limit=number("limit", 6),
                semantic=request.args.get("semantic", "true") != "false",
            ),
        )
    return jsonify(ok=True, **library.list(offset=number("offset", 0), limit=number("limit", 30)))


@library_bp.post("")
@library_request
def save(library):
    upload = request.files.get("file")
    if upload is None:
        raise LibraryError("Choose a PDF or text source to save.")
    payload = upload.stream.read(MAX_SOURCE_BYTES + 1)
    source = library.save(
        payload, upload.filename, title=request.form.get("title"), origin="Web upload"
    )
    return jsonify(ok=True, source=source)


@library_bp.post("/capture")
@library_request
def save_capture(library):
    """Save exactly the Firefox DOM-text snapshot the user reviewed."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise LibraryError("Provide a captured page snapshot.")
    markdown = data.get("markdown")
    title = data.get("title")
    url = data.get("url")
    captured_at = data.get("captured_at")
    if not isinstance(markdown, str) or not markdown.strip():
        raise LibraryError("Capture readable page text before saving.")
    try:
        payload = markdown.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LibraryError("Captured page text must be valid UTF-8.") from exc
    if len(payload) > 100 * 1024:
        raise LibraryError("Captured page text is too large (max 100KB).")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise LibraryError("Captured page title must contain 1 to 200 characters.")
    if not isinstance(url, str) or len(url) > 2000 or any(ord(char) < 32 for char in url):
        raise LibraryError("Captured page URL is invalid.")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise LibraryError("Captured page URL is invalid.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise LibraryError("Captured page URL must be HTTP or HTTPS.")
    if not isinstance(captured_at, str) or len(captured_at) > 40:
        raise LibraryError("Captured page date is invalid.")
    try:
        captured_date = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LibraryError("Captured page date is invalid.") from exc
    if captured_date.tzinfo is None:
        raise LibraryError("Captured page date needs a timezone.")
    if f"- URL: {url}" not in markdown or f"- Captured: {captured_at}\n" not in markdown:
        raise LibraryError("The captured URL and date must match the reviewed page text.")
    origin = f"Firefox page capture at {captured_at}; client-reported URL: {url}"
    source = library.save(payload, "browser-page.md", title=title, origin=origin[:1000])
    return jsonify(ok=True, source=source)


@library_bp.post("/from-attachment")
@library_request
def save_attachment(library):
    """Promote a validated Web Stash PDF or text upload without client file bytes."""
    data = request.get_json(silent=True)
    item = data.get("attachment") if isinstance(data, dict) else None
    if not isinstance(item, dict) or item.get("kind") not in {"pdf", "text"}:
        raise LibraryError("Choose a PDF or text attachment to save.")
    if item.get("mode") not in (None, library.mode):
        raise LibraryError("Save the attachment in its original mode.")
    attachment = validate_attachments([item], library.mode)[0]
    if attachment["size_bytes"] > MAX_SOURCE_BYTES:
        raise LibraryError("Source is too large for the library (max 25MB).")
    path = get_stash_dir() / attachment["space_id"] / attachment["filename"]
    if path.is_symlink() or not path.is_file():
        raise LibraryError("The stored attachment is unavailable. Attach it again.")
    with path.open("rb") as stream:
        payload = stream.read(MAX_SOURCE_BYTES + 1)
    if (len(payload) != attachment["size_bytes"]
            or hashlib.sha256(payload).hexdigest() != attachment["sha256"]):
        raise LibraryError("The stored attachment changed. Attach it again.")
    source = library.save(payload, attachment["filename"], origin="Web chat attachment")
    return jsonify(ok=True, source=source)


@library_bp.get("/inbox")
@library_request
def inbox_status(library):
    return jsonify(ok=True, **library.inbox_status())


@library_bp.get("/status")
@library_request
def source_statuses(library):
    raw = request.args.get("ids", "")
    return jsonify(ok=True, **library.statuses(raw.split(",") if raw else []))


@library_bp.get("/worker")
@library_request
def worker_status(library):
    external = os.environ.get("JARVIS_LIBRARY_WORKER_EXTERNAL") == "1"
    if external:
        running = library.worker_running()
    else:
        worker = current_app.extensions.get("jarvis_library_index_worker")
        running = bool(worker and worker.thread and worker.thread.is_alive())
    response = jsonify(ok=True, running=running, worker_mode="external" if external else "in_process")
    response.headers["Cache-Control"] = "no-store"
    return response


@library_bp.post("/inbox/queue")
@library_request
def queue_inbox_import(library):
    return jsonify(ok=True, **library.queue_inbox_import())


@library_bp.get("/<source_id>")
@library_request
def read(library, source_id):
    return jsonify(
        ok=True, **library.read(source_id, passage=number("passage", 1), limit=number("limit", 3))
    )


@library_bp.get("/<source_id>/download")
@library_request
def download(library, source_id):
    payload, filename, mime = library.download(source_id)
    response = send_file(
        io.BytesIO(payload), mimetype=mime, as_attachment=True, download_name=filename
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@library_bp.get("/<source_id>/text")
@library_request
def original_text(library, source_id):
    text, filename = library.original_text(source_id)
    response = jsonify(ok=True, text=text, filename=filename)
    response.headers["Cache-Control"] = "no-store"
    return response


@library_bp.post("/<source_id>/copy")
@library_request
def save_edited_copy(library, source_id):
    body = request.get_data(cache=True)
    if len(body) > MAX_SOURCE_BYTES + 4096:
        raise LibraryError("Edited text is too large for one source.")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise LibraryError("Provide JSON with edited text.") from exc
    if not isinstance(payload, dict):
        raise LibraryError("Provide JSON with edited text.")
    return jsonify(ok=True, source=library.save_edited_copy(source_id, payload.get("text")))


@library_bp.get("/<source_id>/rendered")
@library_request
def rendered_markdown(library, source_id):
    response = jsonify(ok=True, html=library.rendered_markdown(source_id))
    response.headers["Cache-Control"] = "no-store"
    return response


@library_bp.get("/<source_id>/page/<int:page>")
@library_request
def rendered_pdf_page(library, source_id, page):
    response = send_file(io.BytesIO(library.rendered_pdf_page(source_id, page)), mimetype="image/png")
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@library_bp.post("/<source_id>/index")
@library_request
def index(library, source_id):
    # Preserve the existing one-batch API without racing the library worker.
    library.read(source_id, limit=1)
    try:
        with library.locked_index():
            return jsonify(ok=True, **library.index(source_id))
    except Timeout as exc:
        raise LibraryError("This library is already indexing. Try again shortly.") from exc


@library_bp.post("/<source_id>/queue")
@library_request
def queue_index(library, source_id):
    return jsonify(ok=True, **library.queue_index(source_id))


@library_bp.delete("/<source_id>")
@library_request
def remove(library, source_id):
    return jsonify(ok=True, **library.remove(source_id))


@library_bp.patch("/<source_id>")
@library_request
def rename(library, source_id):
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise LibraryError("Provide a JSON object with a title.")
    return jsonify(ok=True, source=library.rename(source_id, payload.get("title")))
