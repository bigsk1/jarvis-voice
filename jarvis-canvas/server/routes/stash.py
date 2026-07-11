"""
Jarvis Canvas - Stash file serving routes
"""
import json
import mimetypes
from pathlib import Path

from flask import Blueprint, send_file, send_from_directory, abort, jsonify

try:
    from stash_helper import get_stash_dir
except ImportError:
    from lib.stash_helper import get_stash_dir
from server.utils import normalize_space_id

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


def _resolve_stash_file(space_id, file_id):
    """Resolve a stash id to its file and public metadata."""
    normalized_space_id = normalize_space_id(space_id)
    space_dir = get_stash_dir() / normalized_space_id
    if not space_dir.exists():
        abort(404, f"Stash space not found: {normalized_space_id}")

    target_file = None
    file_info = None
    meta_file = space_dir / "meta.json"
    if meta_file.exists():
        try:
            with open(meta_file) as f:
                meta = json.load(f)

            for candidate in meta.get('files', []):
                if candidate.get('file_id') != file_id:
                    continue
                filename = candidate.get('stored_name') or candidate.get('name')
                if filename:
                    target_file = space_dir / filename
                    file_info = dict(candidate)
                break
        except Exception:
            pass

    if target_file is None or not target_file.exists():
        target_file = space_dir / file_id

    if not target_file.exists():
        abort(404, f"File not found in stash: {file_id}")

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
