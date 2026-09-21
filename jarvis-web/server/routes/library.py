"""Authenticated source library endpoints using the normal Web request scope."""

import io
import json
import os
import sqlite3
from functools import wraps

from filelock import Timeout
from flask import Blueprint, current_app, jsonify, request, send_file
from source_library import MAX_SOURCE_BYTES, LibraryError, LibraryUnavailableError, SourceLibrary
from webui_auth import require_auth

from .api import _scoped_request_config

library_bp = Blueprint("library", __name__, url_prefix="/api/library")


@library_bp.before_request
def limit_edited_copy():
    # The shared mode-scope decorator parses JSON before calling the handler.
    if request.endpoint == "library.save_edited_copy":
        denied = require_auth(lambda: None)()
        if denied is not None:
            return denied
        if request.content_length is None or request.content_length > MAX_SOURCE_BYTES + 4096:
            return jsonify(ok=False, error="Edited text is too large or has no Content-Length."), 413


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
