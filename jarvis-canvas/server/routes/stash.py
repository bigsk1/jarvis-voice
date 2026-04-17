"""
Jarvis Canvas - Stash file serving routes
"""
import json
import mimetypes
from pathlib import Path

from flask import Blueprint, send_file, send_from_directory, abort

from config import STASH_DIR
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


@stash_bp.route('/api/stash/<space_id>/<file_id>')
def serve_stash_file(space_id, file_id):
    """
    Serve files from the stash system.
    
    Supports:
    - stash://space_id/file_id format (resolved via meta.json)
    - Direct filename if file_id is actually a filename
    """
    # Normalize space_id to handle date format variations
    space_id = normalize_space_id(space_id)
    
    space_dir = STASH_DIR / space_id
    
    if not space_dir.exists():
        abort(404, f"Stash space not found: {space_id}")
    
    # Try to resolve file_id via meta.json first
    meta_file = space_dir / "meta.json"
    target_file = None
    
    if meta_file.exists():
        try:
            with open(meta_file) as f:
                meta = json.load(f)
            
            # Check if file_id matches any file ID in meta
            for file_info in meta.get('files', []):
                if file_info.get('file_id') == file_id:
                    # Try stored_name first, then name as fallback
                    filename = file_info.get('stored_name') or file_info.get('name')
                    if filename:
                        target_file = space_dir / filename
                        break
        except Exception:
            pass
    
    # Fallback: treat file_id as direct filename
    if target_file is None or not target_file.exists():
        target_file = space_dir / file_id
    
    if not target_file.exists():
        abort(404, f"File not found in stash: {file_id}")
    
    # Determine MIME type
    mime_type = mimetypes.guess_type(str(target_file))[0] or 'application/octet-stream'
    
    return send_file(target_file, mimetype=mime_type)
