"""
API routes for browsing markdown docs.
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request, send_file

from ..services.docs_explorer import DocsExplorerError


docs_bp = Blueprint('docs', __name__, url_prefix='/api/docs')


def _explorer():
    return current_app.config['docs_explorer']


@docs_bp.route('/folders', methods=['GET'])
def list_folders():
    return jsonify({
        'ok': True,
        'folders': _explorer().list_folders(),
    })


@docs_bp.route('/documents', methods=['GET'])
def list_documents():
    folder = request.args.get('folder', '')
    search = request.args.get('search', '')
    sort = request.args.get('sort', 'recent')
    offset = max(request.args.get('offset', 0, type=int) or 0, 0)
    limit = min(max(request.args.get('limit', 40, type=int) or 40, 1), 200)

    try:
        payload = _explorer().list_documents(
            folder=folder,
            search=search,
            sort=sort,
            offset=offset,
            limit=limit,
        )
    except DocsExplorerError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

    return jsonify({'ok': True, **payload})


@docs_bp.route('/document', methods=['GET'])
def get_document():
    relative_path = request.args.get('path', '')
    try:
        payload = _explorer().read_document(relative_path)
    except DocsExplorerError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, **payload})


@docs_bp.route('/document', methods=['PUT'])
def update_document():
    relative_path = request.args.get('path', '')
    content = (request.get_json() or {}).get('content')
    if content is None:
        return jsonify({'ok': False, 'error': 'Content is required'}), 400

    try:
        payload = _explorer().save_document(relative_path, str(content))
    except DocsExplorerError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400
    return jsonify({'ok': True, **payload})


@docs_bp.route('/config', methods=['GET'])
def get_config():
    explorer = _explorer()
    return jsonify({
        'ok': True,
        'edit_enabled': explorer.edit_enabled,
    })


@docs_bp.route('/assistant/chat', methods=['POST'])
def docs_assistant_chat():
    """Dedicated docs LLM Q&A — uses LLM_PROVIDER from cloud/local env."""
    data = request.get_json() or {}
    messages = data.get('messages')
    mode_raw = data.get('mode', 'cloud')
    mode = 'local' if str(mode_raw).strip().lower() == 'local' else 'cloud'

    if not isinstance(messages, list) or len(messages) < 1:
        return jsonify({'ok': False, 'error': 'messages must be a non-empty array'}), 400

    try:
        from ..services.docs_assistant import run_docs_assistant

        payload = run_docs_assistant(messages, mode)
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500

    return jsonify(payload)


@docs_bp.route('/asset', methods=['GET'])
def get_asset():
    relative_path = request.args.get('path', '')
    download = request.args.get('download', '').strip().lower() in {'1', 'true', 'yes'}

    try:
        asset_path = _explorer().resolve_asset(relative_path)
    except DocsExplorerError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

    return send_file(asset_path, as_attachment=download)
