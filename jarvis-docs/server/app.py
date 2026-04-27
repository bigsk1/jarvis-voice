"""
Jarvis Docs - standalone markdown reader/editor for docs/.
"""
from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_from_directory
from flask_cors import CORS


DOCS_UI_ROOT = Path(__file__).parent.parent
JARVIS_ROOT = DOCS_UI_ROOT.parent
CLIENT_PATH = DOCS_UI_ROOT / 'client'
DOCS_PATH = JARVIS_ROOT / 'docs'
WEB_FONTS_PATH = JARVIS_ROOT / 'jarvis-web' / 'client' / 'fonts'
WEB_VENDOR_PATH = JARVIS_ROOT / 'jarvis-web' / 'client' / 'vendor'

sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from config_loader import load_config
from flask_error_logger import setup_error_logging
from webui_auth import get_token_from_request, is_auth_enabled, verify_token

from .routes.auth import auth_bp
from .routes.docs import docs_bp
from .services.docs_explorer import DocsExplorerError, get_docs_explorer


def _get_jarvis_version():
    try:
        from version import JARVIS_VERSION
        return JARVIS_VERSION
    except ImportError:
        try:
            return (JARVIS_ROOT / 'VERSION').read_text().strip()
        except Exception:
            return '0.0.0'


app = Flask(__name__, static_folder=str(CLIENT_PATH), static_url_path='')
app.config['docs_explorer'] = get_docs_explorer(DOCS_PATH)

CORS(app, resources={r"/*": {"origins": "*"}})

app.register_blueprint(auth_bp)
app.register_blueprint(docs_bp)

setup_error_logging(app, 'docs-ui')

PUBLIC_ROUTES = {'/login', '/api/auth/login', '/api/auth/status', '/api/auth/verify', '/api/status'}
PUBLIC_EXTENSIONS = {'.css', '.js', '.ico', '.png', '.jpg', '.jpeg', '.svg', '.woff', '.woff2'}


@app.before_request
def check_auth():
    if not is_auth_enabled():
        return None
    if request.path in PUBLIC_ROUTES:
        return None
    if any(request.path.endswith(ext) for ext in PUBLIC_EXTENSIONS):
        return None

    token = get_token_from_request(request)
    if verify_token(token):
        return None

    if request.path.startswith('/api/'):
        return {'ok': False, 'error': 'Authentication required'}, 401
    return redirect(f'/login?redirect={request.path}')


@app.route('/login')
def serve_login():
    return send_from_directory(CLIENT_PATH, 'login.html')


@app.route('/fonts/<path:path>')
def serve_fonts(path: str):
    return send_from_directory(WEB_FONTS_PATH, path)


@app.route('/vendor/<path:path>')
def serve_vendor(path: str):
    return send_from_directory(WEB_VENDOR_PATH, path)


@app.route('/docs-files/<path:path>')
def serve_docs_file(path: str):
    docs_explorer = app.config['docs_explorer']
    try:
        asset_path = docs_explorer.resolve_asset(path)
    except DocsExplorerError:
        return jsonify({'ok': False, 'error': 'Asset not found'}), 404
    return send_from_directory(asset_path.parent, asset_path.name)


@app.route('/')
def serve_index():
    return send_from_directory(CLIENT_PATH, 'index.html')


@app.route('/<path:path>')
def serve_static(path: str):
    return send_from_directory(CLIENT_PATH, path)


@app.route('/api/status', methods=['GET'])
def get_status():
    docs_explorer = app.config['docs_explorer']
    folder_count = len(docs_explorer.list_folders())
    doc_count = docs_explorer.list_documents(limit=1_000_000)['total']
    return jsonify({
        'ok': True,
        'status': 'running',
        'version': _get_jarvis_version(),
        'docs_root': str(DOCS_PATH),
        'folders': folder_count,
        'documents': doc_count,
        'edit_enabled': docs_explorer.edit_enabled,
    })


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    return send_from_directory(CLIENT_PATH, 'index.html')


@app.errorhandler(500)
def server_error(_error):
    return jsonify({'ok': False, 'error': 'Internal server error'}), 500


def run_server(host: str = '0.0.0.0', port: int = 5004, mode: str = 'cloud', debug: bool = False):
    load_config(mode)
    app.config['docs_explorer'] = get_docs_explorer(DOCS_PATH)
    docs_explorer = app.config['docs_explorer']
    auth_status = 'ENABLED' if is_auth_enabled() else 'DISABLED'
    edit_status = 'ON' if docs_explorer.edit_enabled else 'OFF'
    doc_count = docs_explorer.list_documents(limit=1_000_000)['total']

    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║                    JARVIS DOCS READER                        ║
╠═══════════════════════════════════════════════════════════════╣
║  Address:  http://{host}:{port:<42} ║
║  Docs:     {doc_count:<5}  |  Auth: {auth_status:<8} | Edit: {edit_status:<13} ║
║  Root:     docs/{'':<48} ║
╚═══════════════════════════════════════════════════════════════╝
""")

    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Jarvis Docs Reader')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5004, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()
    run_server(host=args.host, port=args.port, debug=args.debug)
