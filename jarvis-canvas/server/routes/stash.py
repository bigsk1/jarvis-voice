"""
Jarvis Canvas - Stash file serving routes
"""
import json
import mimetypes
from pathlib import Path

from flask import Blueprint, abort, jsonify, send_file, send_from_directory

try:
    from stash_helper import get_stash_dir
except ImportError:
    from lib.stash_helper import get_stash_dir
from ..utils import normalize_space_id

stash_bp = Blueprint('stash', __name__)

_JARVIS_CANVAS_ROOT = Path(__file__).resolve().parent.parent.parent
_CLIENT_STATIC = _JARVIS_CANVAS_ROOT / "client" / "static"


@stash_bp.route("/stash/view/<space_id>/<file_id>")
def stash_viewer_page(space_id, file_id):
    """Same-origin Markdown/text viewer for stash artifacts (matches Jarvis Web UI behavior).

    Flask injects ``space_id`` and ``file_id`` from the URL; the HTML reads the path from
    ``window.location`` instead, but the parameter names must match the route variables.
    """
    assert space_id and file_id
    return send_from_directory(_CLIENT_STATIC, "stash-viewer.html")


def _stash_component(value: object) -> str:
    """Keep URL selectors and stored filenames to a single path component."""
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or any(char in value for char in "/\\")
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        abort(404)
    return value


def _confined_stash_path(parent: Path, name: object) -> Path:
    """Resolve links before any read, keeping each path inside its own parent."""
    component = _stash_component(name)
    try:
        path = (parent / component).resolve()
    except (OSError, RuntimeError):
        abort(404)
    if path == parent or not path.is_relative_to(parent):
        abort(404)
    return path


def _resolve_stash_file(space_id, file_id):
    """Resolve an ID or legacy filename within its configured Stash space."""
    normalized_space_id = normalize_space_id(_stash_component(space_id))
    _stash_component(file_id)
    try:
        root = get_stash_dir().resolve()
    except (OSError, RuntimeError):
        abort(404)
    space_dir = _confined_stash_path(root, normalized_space_id)
    if not space_dir.is_dir():
        abort(404)

    target_file = None
    file_info = None
    meta_file = _confined_stash_path(space_dir, "meta.json")
    if meta_file.is_file():
        try:
            with open(meta_file) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
        entries = meta.get('files', []) if isinstance(meta, dict) else []
        for candidate in entries if isinstance(entries, list) else []:
            if not isinstance(candidate, dict) or candidate.get('file_id') != file_id:
                continue
            filename = candidate.get('stored_name') or candidate.get('name')
            if filename:
                # Security rejection must not be swallowed by metadata fallback.
                target_file = _confined_stash_path(space_dir, filename)
                file_info = dict(candidate)
            break

    if target_file is None or not target_file.is_file():
        target_file = _confined_stash_path(space_dir, file_id)

    if not target_file.is_file():
        abort(404)

    return normalized_space_id, target_file, file_info or {}


@stash_bp.route('/api/stash/<space_id>/<file_id>/metadata')
def get_stash_file_metadata(space_id, file_id):
    """Return the media fields Canvas needs without exposing a local path."""
    normalized_space_id, target_file, file_info = _resolve_stash_file(space_id, file_id)
    mime_type = (
        file_info.get('mime_type')
        or mimetypes.guess_type(str(target_file))[0]
        or 'application/octet-stream'
    )
    return jsonify({
        'space_id': normalized_space_id,
        'file_id': file_id,
        'name': file_info.get('name') or target_file.name,
        'mime_type': mime_type,
        'size_bytes': file_info.get('size_bytes') or target_file.stat().st_size,
        'source_url': file_info.get('source_url'),
        'tool_origin': file_info.get('tool_origin'),
        'tags': file_info.get('tags', []),
    })


@stash_bp.route('/api/stash/<space_id>/<file_id>')
def serve_stash_file(space_id, file_id):
    """
    Serve files from the stash system.
    
    Supports:
    - stash://space_id/file_id format (resolved via meta.json)
    - Direct filename if file_id is actually a filename
    """
    _, target_file, file_info = _resolve_stash_file(space_id, file_id)
    mime_type = (
        file_info.get('mime_type')
        or mimetypes.guess_type(str(target_file))[0]
        or 'application/octet-stream'
    )
    
    return send_file(target_file, mimetype=mime_type)
