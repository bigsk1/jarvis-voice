"""
Jarvis Canvas - Pages API routes
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from flask import Blueprint, jsonify, request, Response

from config import CANVAS_DIR
try:
    from stash_helper import get_stash_dir
except ImportError:
    from lib.stash_helper import get_stash_dir
from canvas_content import append_content, is_suspicious_content_shrink
from canvas_page_ids import generate_canvas_page_id
from server.pages import (
    delete_page_file,
    get_page_path,
    load_pages,
    save_page,
)
from server.utils import sync_stash_pins

pages_bp = Blueprint('pages', __name__)
SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"

@pages_bp.route('/api/pages/crypto-chart/<symbol>', methods=['GET'])
def proxy_crypto_chart(symbol):
    """
    Resolve crypto chart requests directly through the local skill so browser
    clients do not need to call the protected main API directly.
    """
    tool_path = SKILLS_DIR / "crypto_chart.py"
    if not tool_path.exists():
        return jsonify({"error": "crypto_chart tool not found"}), 404

    args = {
        "coin": symbol.lower(),
        "days": request.args.get('days', '7'),
        "vs_currency": request.args.get('vs_currency', 'usd').lower(),
    }
    for key in ('days', 'vs_currency', 'points_limit'):
        value = request.args.get(key)
        if value not in (None, ''):
            args[key] = int(value) if key == 'points_limit' else value

    try:
        result = subprocess.run(
            [sys.executable, str(tool_path), json.dumps(args)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(SKILLS_DIR.parent)
        )
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Chart request timed out"}), 504
    except Exception as exc:
        return jsonify({"error": "Chart request failed", "detail": str(exc)}), 502

    if result.returncode != 0:
        return jsonify({
            "error": "crypto_chart tool execution failed",
            "detail": (result.stderr or result.stdout or "").strip()[:500]
        }), 502

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return jsonify({
            "error": "Invalid chart response",
            "detail": result.stdout[:500]
        }), 502

    status_code = 200 if payload.get("ok") else 404
    return jsonify(payload), status_code


@pages_bp.route('/api/pages', methods=['GET'])
def list_pages():
    """List all pages."""
    return jsonify(load_pages())


@pages_bp.route('/api/pages/<page_id>', methods=['GET'])
def get_page(page_id):
    """Get a single page."""
    filepath = get_page_path(page_id)
    if not filepath.exists():
        return jsonify({"error": "Page not found"}), 404
    
    with open(filepath) as f:
        return jsonify(json.load(f))


@pages_bp.route('/api/pages', methods=['POST'])
def create_page():
    """Create a new page."""
    data = request.get_json()
    
    if not data.get('title'):
        return jsonify({"error": "Title is required"}), 400
    
    now_utc = datetime.now(timezone.utc)
    page_id = generate_canvas_page_id(now_utc)
    timestamp = now_utc.strftime('%Y-%m-%dT%H:%M:%S') + "Z"
    
    page = {
        "id": page_id,
        "title": data['title'],
        "content": data.get('content', ''),
        "content_type": data.get('content_type', 'markdown'),
        "tags": data.get('tags', []),
        "source_query": data.get('source_query'),
        "created": timestamp,
        "updated": timestamp,
        "pinned": data.get('pinned', False)
    }
    
    # Sync stash pins if page is created as pinned
    if page.get('pinned', False):
        sync_stash_pins(page.get('content', ''), pinned=True, stash_dir=get_stash_dir())
    
    save_page(page)
    return jsonify(page), 201


@pages_bp.route('/api/pages/<page_id>', methods=['PUT'])
def update_page(page_id):
    """Update an existing page."""
    filepath = get_page_path(page_id)
    if not filepath.exists():
        return jsonify({"error": "Page not found"}), 404
    
    with open(filepath) as f:
        page = json.load(f)
    
    data = request.get_json()
    # Update allowed fields
    if 'title' in data:
        page['title'] = data['title']
    if 'content' in data:
        old_content = page.get('content', '')
        new_content = data['content']
        allow_content_shrink = data.get('allow_content_shrink') is True
        if (
            not allow_content_shrink
            and is_suspicious_content_shrink(old_content, new_content)
        ):
            return jsonify({
                "error": "Content replacement blocked because it would remove most of the existing Canvas page",
                "error_code": "suspicious_content_shrink",
                "existing_content_length": len(old_content),
                "new_content_length": len(new_content or ''),
                "hint": (
                    "Use the append action to add a section, or set "
                    "allow_content_shrink=true for an intentional full replacement."
                ),
            }), 409
        page['content'] = data['content']
    if 'tags' in data:
        page['tags'] = data['tags']
    if 'pinned' in data:
        page['pinned'] = data['pinned']
    
    page['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + "Z"
    
    # Re-scan every pinned update so newly referenced stash spaces do not expire.
    if page.get('pinned', False):
        sync_stash_pins(page.get('content', ''), pinned=True, stash_dir=get_stash_dir())
    
    save_page(page)
    return jsonify(page)


@pages_bp.route('/api/pages/<page_id>/append', methods=['POST'])
def append_page(page_id):
    """Append Markdown to a page without sending its existing content through the LLM."""
    filepath = get_page_path(page_id)
    if not filepath.exists():
        return jsonify({"error": "Page not found"}), 404

    data = request.get_json() or {}
    additional_content = data.get('content')
    if not isinstance(additional_content, str) or not additional_content.strip():
        return jsonify({"error": "Content is required for append"}), 400

    with open(filepath) as f:
        page = json.load(f)

    page['content'] = append_content(page.get('content', ''), additional_content)
    page['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + "Z"

    if page.get('pinned', False):
        sync_stash_pins(page['content'], pinned=True, stash_dir=get_stash_dir())

    save_page(page)
    return jsonify(page)


@pages_bp.route('/api/pages/<page_id>', methods=['DELETE'])
def delete_page(page_id):
    """Delete a page."""
    if delete_page_file(page_id):
        return jsonify({"success": True})
    return jsonify({"error": "Page not found"}), 404


@pages_bp.route('/api/pages/<page_id>/download', methods=['GET'])
def download_page(page_id):
    """
    Download a page as JSON or Markdown.
    
    Query params:
        format: 'json' (default) or 'markdown'
    """
    filepath = get_page_path(page_id)
    if not filepath.exists():
        return jsonify({"error": "Page not found"}), 404
    
    with open(filepath) as f:
        page = json.load(f)
    
    export_format = request.args.get('format', 'json')
    
    if export_format == 'markdown':
        # Export as Markdown with frontmatter
        frontmatter = f"""---
title: {page.get('title', 'Untitled')}
id: {page.get('id', '')}
created: {page.get('created', '')}
updated: {page.get('updated', '')}
tags: {json.dumps(page.get('tags', []))}
pinned: {page.get('pinned', False)}
---

"""
        content = frontmatter + page.get('content', '')
        filename = f"{page.get('title', 'page').replace('/', '_')}.md"
        
        return Response(
            content,
            mimetype='text/markdown',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )
    else:
        # Export as JSON
        filename = f"{page_id}.json"
        return Response(
            json.dumps(page, indent=2),
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )


@pages_bp.route('/api/pages/upload', methods=['POST'])
def upload_page():
    """
    Upload/import a page from JSON.
    
    Accepts JSON body with page data. If 'id' is provided and exists, 
    it will be treated as an update. Otherwise creates a new page.
    
    Set 'force_new': true to always create a new page even if ID matches.
    """
    data = request.get_json()
    
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
    
    if not data.get('title'):
        return jsonify({"error": "Title is required"}), 400
    
    force_new = data.pop('force_new', False)
    existing_id = data.get('id')
    
    # Check if page with this ID exists
    if existing_id and not force_new:
        existing_path = CANVAS_DIR / f"{existing_id}.json"
        if existing_path.exists():
            # Update existing page
            with open(existing_path) as f:
                existing = json.load(f)
            
            existing['title'] = data.get('title', existing.get('title'))
            existing['content'] = data.get('content', existing.get('content', ''))
            existing['tags'] = data.get('tags', existing.get('tags', []))
            existing['pinned'] = data.get('pinned', existing.get('pinned', False))
            existing['updated'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + "Z"

            if existing.get('pinned', False):
                sync_stash_pins(existing.get('content', ''), pinned=True, stash_dir=get_stash_dir())

            save_page(existing)
            return jsonify({"action": "updated", "page": existing})
    
    # Create new page
    now_utc = datetime.now(timezone.utc)
    page_id = generate_canvas_page_id(now_utc)
    
    page = {
        'id': page_id,
        'title': data.get('title'),
        'content': data.get('content', ''),
        'tags': data.get('tags', []),
        'pinned': data.get('pinned', False),
        'created': now_utc.strftime('%Y-%m-%dT%H:%M:%S') + "Z",
        'updated': now_utc.strftime('%Y-%m-%dT%H:%M:%S') + "Z",
        'source_query': data.get('source_query')
    }

    if page.get('pinned', False):
        sync_stash_pins(page.get('content', ''), pinned=True, stash_dir=get_stash_dir())

    save_page(page)
    return jsonify({"action": "created", "page": page}), 201
