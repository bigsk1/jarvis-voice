"""
Jarvis Web UI - Main Application
Flask + SocketIO server for the web chat interface
"""
import logging
import sys
from pathlib import Path

from flask import Blueprint, Flask, jsonify, send_from_directory
from flask_cors import CORS

# Setup paths
WEB_ROOT = Path(__file__).parent.parent
JARVIS_ROOT = WEB_ROOT.parent
CLIENT_PATH = WEB_ROOT / 'client'

# Support both legacy top-level helpers and canonical lib.* packages before
# importing routes. Script launches do not inherit pytest's repo-root path.
sys.path.insert(0, str(JARVIS_ROOT))
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from .config import get_web_setting, load_jarvis_config, load_web_config  # noqa: E402
from .routes.api import api_bp  # noqa: E402
from .routes.auth import auth_bp  # noqa: E402
from .routes.background_tasks import background_bp  # noqa: E402
from .routes.task_integrations import integrations_bp  # noqa: E402
from .sockets.chat import ChatHandler  # noqa: E402

logger = logging.getLogger(__name__)
try:
    from .routes.library import library_bp  # noqa: E402
    library_routes_available = True
except Exception:
    logger.exception("Source Library routes failed to load; other Web features remain available")
    library_routes_available = False
    library_bp = Blueprint("library_unavailable", __name__, url_prefix="/api/library")

    @library_bp.route("", defaults={"path": ""}, methods=["GET", "POST", "PATCH", "DELETE"])
    @library_bp.route("/<path:path>", methods=["GET", "POST", "PATCH", "DELETE"])
    def unavailable_library(path):
        return jsonify(ok=False, error="The source library is unavailable. Check Web logs and retry."), 503

# Import auth utilities
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))
from flask_error_logger import setup_error_logging  # noqa: E402
try:
    from source_library_jobs import LibraryIndexWorker  # noqa: E402
except Exception:
    logger.exception("Source Library worker failed to load; Web will continue without indexing")
    LibraryIndexWorker = None
from ui_navigation import register_ui_navigation  # noqa: E402
from webui_auth import get_token_from_request, is_auth_enabled, verify_token  # noqa: E402

from .socket_auth import AuthenticatedSocketIO  # noqa: E402

# Global to track startup mode (set in run_server)
_startup_mode = 'cloud'

def get_startup_mode():
    """Get the mode the server was started with"""
    return _startup_mode

# Create Flask app
app = Flask(__name__,
            static_folder=str(CLIENT_PATH),
            static_url_path='')

# Configure CORS - allow all origins for local network
CORS(app, resources={r"/*": {"origins": "*"}})
register_ui_navigation(app)

# Configure SocketIO
socketio = AuthenticatedSocketIO(
    app,
    cors_allowed_origins="*",
    # Threading + simple-websocket avoids monkey-patching gRPC, subprocess,
    # and Python locks. Eventlet is deprecated and can emit greenlet
    # finalization errors while shutting down active SDK channels.
    async_mode='threading',
    # Grok/xAI SDK calls can block for a while on tool-heavy requests. Give the
    # browser more heartbeat headroom so a slow model turn does not look like a
    # dead socket immediately.
    ping_interval=25,
    ping_timeout=90,
    logger=False,
    engineio_logger=False
)

# Register blueprints
app.register_blueprint(api_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(library_bp)
app.register_blueprint(background_bp)
app.register_blueprint(integrations_bp)

# Error logging → logs/web-ui/errors-YYYY-MM-DD.jsonl
setup_error_logging(app, 'web-ui')

# Initialize chat handler
chat_handler = ChatHandler(socketio)
app.extensions['jarvis_chat_runs'] = chat_handler.runs
app.extensions['jarvis_background_tasks'] = chat_handler.background_tasks
try:
    library_index_worker = LibraryIndexWorker() if LibraryIndexWorker else None
except Exception:
    logger.exception("Source Library worker failed to initialize; Web will continue without indexing")
    library_index_worker = None
app.extensions['jarvis_library_index_worker'] = library_index_worker
app.extensions['jarvis_library_routes_available'] = library_routes_available


# =============================================================================
# Authentication middleware
# =============================================================================

# Routes that don't require authentication
PUBLIC_ROUTES = {
    '/login',
    '/login.html',
    '/api/auth/login',
    '/api/auth/status',
    '/api/auth/verify',
    '/api/status',        # Health check (used by ./bin/start --list)
}

# Static file extensions that don't need auth
PUBLIC_EXTENSIONS = {'.css', '.js', '.ico', '.png', '.jpg', '.svg', '.woff', '.woff2'}


@app.before_request
def check_auth():
    """Check authentication before each request"""
    from flask import redirect, request, url_for
    
    # Skip if auth not enabled
    if not is_auth_enabled():
        return None
    
    # Skip public routes
    if request.path in PUBLIC_ROUTES:
        return None
    
    # Skip static files
    if any(request.path.endswith(ext) for ext in PUBLIC_EXTENSIONS):
        return None
    
    # Check for valid token
    token = get_token_from_request(request)
    if verify_token(token):
        return None
    
    # Not authenticated
    if request.path.startswith('/api/'):
        # API request - return 401 JSON
        return {'ok': False, 'error': 'Authentication required'}, 401
    else:
        # Page request - redirect to login
        return redirect(url_for('serve_login', redirect=request.full_path.rstrip('?')))


# =============================================================================
# Static file serving
# =============================================================================

@app.route('/login')
def serve_login():
    """Serve the login page"""
    return send_from_directory(CLIENT_PATH, 'login.html')


@app.route('/')
def serve_index():
    """Serve the main HTML page"""
    return send_from_directory(CLIENT_PATH, 'index.html')


@app.route('/logs')
def serve_logs():
    """Serve the dedicated log viewer page"""
    return send_from_directory(CLIENT_PATH, 'logs.html')


@app.route('/library')
def serve_library():
    """Browse retained originals and source-attributed passages."""
    return send_from_directory(CLIENT_PATH, 'library.html')


@app.route('/stash/view/<space_id>/<file_id>')
def serve_stash_viewer(space_id, file_id):
    """Serve a rendered viewer for stash text/markdown artifacts."""
    return send_from_directory(CLIENT_PATH, 'stash-viewer.html')


@app.route('/<path:path>')
def serve_static(path):
    """Serve static files"""
    return send_from_directory(CLIENT_PATH, path)


# =============================================================================
# Error handlers
# =============================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404 - return index for SPA-like behavior, but not for API routes"""
    from flask import request
    # Don't return HTML for API routes - they should get proper 404
    if request.path.startswith('/api/'):
        return {'ok': False, 'error': 'Not found'}, 404
    return send_from_directory(CLIENT_PATH, 'index.html')


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors"""
    return {'ok': False, 'error': 'Internal server error'}, 500


# =============================================================================
# Main entry point
# =============================================================================

def create_app(mode: str = 'cloud'):
    """Create and configure the app"""
    # Load configs
    load_web_config()
    load_jarvis_config(mode)
    chat_handler.background_tasks.start()
    return app, socketio


def run_server(host: str = None, port: int = None, mode: str = 'cloud', debug: bool = False):
    """Run the web server"""
    from os import environ

    global _startup_mode
    _startup_mode = mode  # Store for session defaults
    
    load_web_config()
    
    host = host or get_web_setting('server.host', '0.0.0.0')
    port = port or get_web_setting('server.port', 5001)
    debug = debug or get_web_setting('server.debug', False)
    
    # Load Jarvis config for the specified mode
    load_jarvis_config(mode)

    # A second Web process sharing enabled task storage must not own a coordinator.
    chat_handler.background_tasks.start()
    library_worker = app.extensions.get('jarvis_library_index_worker')
    if library_worker is not None and environ.get('JARVIS_LIBRARY_WORKER_EXTERNAL') != '1':
        try:
            library_worker.start()
        except Exception:
            logger.exception("Source Library worker failed to start; Web will continue without indexing")
    
    # Read version
    try:
        _version = (JARVIS_ROOT / 'VERSION').read_text().strip()
    except Exception:
        _version = '0.0.0'
    
    auth_status = "ENABLED (password required)" if is_auth_enabled() else "DISABLED (open access)"
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║                  🤖 JARVIS WEB UI v{_version:<25} ║
╠═══════════════════════════════════════════════════════════════╣
║  Mode:     {mode.upper():<52} ║
║  Address:  http://{host}:{port:<42} ║
║  Auth:     {auth_status:<52} ║
║  Debug:    {str(debug):<52} ║
╚═══════════════════════════════════════════════════════════════╝
""")
    
    socketio.run(
        app,
        host=host,
        port=port,
        debug=debug,
        # Jarvis Web is intentionally a local/LAN application. Flask-SocketIO
        # requires this acknowledgement when its threading development server
        # is used outside debug mode.
        allow_unsafe_werkzeug=True,
    )


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Jarvis Web UI')
    parser.add_argument('mode', nargs='?', default='cloud', choices=['cloud', 'local'],
                        help='Run mode (cloud or local)')
    parser.add_argument('--host', default=None, help='Host to bind to')
    parser.add_argument('--port', type=int, default=None, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, mode=args.mode, debug=args.debug)
