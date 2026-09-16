"""Authenticated source library endpoints using the normal Web request scope."""

import io
import sqlite3
from functools import wraps

from flask import Blueprint, jsonify, request, send_file
from source_library import MAX_SOURCE_BYTES, LibraryError, SourceLibrary
from webui_auth import require_auth

from .api import _scoped_request_config

library_bp = Blueprint("library", __name__, url_prefix="/api/library")


def library_request(handler):
    @wraps(handler)
    @require_auth
    @_scoped_request_config
    def wrapped(*args, **kwargs):
        try:
            return handler(SourceLibrary(), *args, **kwargs)
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


@library_bp.post("/<source_id>/index")
@library_request
def index(library, source_id):
    return jsonify(ok=True, **library.index(source_id))


@library_bp.delete("/<source_id>")
@library_request
def remove(library, source_id):
    return jsonify(ok=True, **library.remove(source_id))
