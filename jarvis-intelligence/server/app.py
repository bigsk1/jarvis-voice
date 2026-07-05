"""
Jarvis Intelligence Dashboard - Main Application
Flask server for viewing/managing Jarvis intelligence layer
"""
import sys
from pathlib import Path
from flask import Flask, send_from_directory, jsonify, request, redirect
from flask_cors import CORS

# Setup paths
INTELLIGENCE_ROOT = Path(__file__).parent.parent
JARVIS_ROOT = INTELLIGENCE_ROOT.parent
CLIENT_PATH = INTELLIGENCE_ROOT / 'client'
FONTS_PATH = JARVIS_ROOT / 'jarvis-web' / 'client' / 'fonts'
ASSETS_PATH = JARVIS_ROOT / 'jarvis-web' / 'client' / 'assets'
DATA_PATH = JARVIS_ROOT / 'data'

# Add lib to path
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from webui_auth import is_auth_enabled, get_token_from_request, verify_token
from flask_error_logger import setup_error_logging
from config_loader import load_config

_startup_mode = 'cloud'


def _get_jarvis_version():
    """Read Jarvis version from central VERSION file."""
    try:
        from version import JARVIS_VERSION
        return JARVIS_VERSION
    except ImportError:
        try:
            return (JARVIS_ROOT / 'VERSION').read_text().strip()
        except Exception:
            return '0.0.0'


# Import routes after path setup. Support both package import and direct execution.
if __package__:
    from .routes.experiences import experiences_bp
    from .routes.insights import insights_bp
    from .routes.stats import stats_bp
    from .routes.maintenance import maintenance_bp
    from .routes.feedback import feedback_bp
    from .routes.auth import auth_bp
else:
    sys.path.insert(0, str(INTELLIGENCE_ROOT))
    from server.routes.experiences import experiences_bp
    from server.routes.insights import insights_bp
    from server.routes.stats import stats_bp
    from server.routes.maintenance import maintenance_bp
    from server.routes.feedback import feedback_bp
    from server.routes.auth import auth_bp

# Create Flask app
app = Flask(__name__,
            static_folder=str(CLIENT_PATH),
            static_url_path='')

# Configure CORS
CORS(app, resources={r"/*": {"origins": "*"}})

# Register blueprints
app.register_blueprint(experiences_bp)
app.register_blueprint(insights_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(maintenance_bp)
app.register_blueprint(feedback_bp)
app.register_blueprint(auth_bp)

# Error logging → logs/intelligence-ui/errors-YYYY-MM-DD.jsonl
setup_error_logging(app, 'intelligence-ui')

# Auth middleware
PUBLIC_ROUTES = {'/login', '/api/auth/login', '/api/auth/status', '/api/auth/verify', '/api/status'}
PUBLIC_EXTENSIONS = {'.css', '.js', '.ico', '.png', '.jpg', '.svg', '.woff', '.woff2'}

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


@app.route('/fonts/<path:path>')
def serve_fonts(path):
    """Serve shared fonts without relying on checkout symlink support."""
    return send_from_directory(FONTS_PATH, path)


@app.route('/assets/<path:path>')
def serve_brand_assets(path):
    """Serve shared branding assets without relying on checkout symlink support."""
    return send_from_directory(ASSETS_PATH, path)


@app.route('/<path:path>')
def serve_static(path):
    """Serve static files"""
    return send_from_directory(CLIENT_PATH, path)


# =============================================================================
# Status endpoint
# =============================================================================

@app.route('/api/status', methods=['GET'])
def get_status():
    """Health check and basic status info"""
    return jsonify({
        'ok': True,
        'status': 'running',
        'version': _get_jarvis_version(),
        'startup_mode': _startup_mode,
        'databases': {
            'cloud': str(DATA_PATH / 'jarvis_intelligence.db'),
            'local': str(DATA_PATH / 'jarvis_intelligence_local.db')
        }
    })


# =============================================================================
# Error handlers
# =============================================================================

@app.errorhandler(404)
def not_found(e):
    """Handle 404"""
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    return send_from_directory(CLIENT_PATH, 'index.html')


@app.errorhandler(500)
def server_error(e):
    """Handle 500 errors"""
    return jsonify({'ok': False, 'error': 'Internal server error'}), 500


# =============================================================================
# Main entry point
# =============================================================================

def run_server(host: str = '0.0.0.0', port: int = 5003, mode: str = 'cloud', debug: bool = False):
    """Run the web server"""
    global _startup_mode
    _startup_mode = mode
    load_config(mode)
    if __package__:
        from .services.intelligence_service import IntelligenceService
    else:
        from server.services.intelligence_service import IntelligenceService
    IntelligenceService(mode)
    auth_status = "ENABLED" if is_auth_enabled() else "DISABLED"
    
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║              📊 JARVIS INTELLIGENCE DASHBOARD                 ║
╠═══════════════════════════════════════════════════════════════╣
║  Address:  http://{host}:{port:<42} ║
║  Mode:     {mode.upper():<10} | Auth: {auth_status:<26} ║
║  Debug:    {str(debug):<52} ║
╚═══════════════════════════════════════════════════════════════╝
""")
    
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    import argparse
    import os
    from jarvis_mode import JarvisModeError, require_local_config, resolve_jarvis_mode
    
    parser = argparse.ArgumentParser(description='Jarvis Intelligence Dashboard')
    parser.add_argument('mode', nargs='?', default=None, choices=['cloud', 'local'],
                        help='Startup env mode: cloud (default) or local')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5003, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    try:
        mode = resolve_jarvis_mode(args.mode)
        require_local_config(mode, JARVIS_ROOT)
        os.environ['JARVIS_MODE'] = mode
    except JarvisModeError as exc:
        parser.error(str(exc))
    run_server(host=args.host, port=args.port, mode=mode, debug=args.debug)
