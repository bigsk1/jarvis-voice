"""
Jarvis Web UI - Main Application
Flask + SocketIO server for the web chat interface
"""
import sys
from pathlib import Path
from flask import Flask, send_from_directory
from flask_socketio import SocketIO
from flask_cors import CORS

# Setup paths
WEB_ROOT = Path(__file__).parent.parent
JARVIS_ROOT = WEB_ROOT.parent
CLIENT_PATH = WEB_ROOT / 'client'

# Add lib to path
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from .config import load_web_config, get_web_setting, load_jarvis_config
from .routes.api import api_bp
from .sockets.chat import ChatHandler

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

# Configure SocketIO
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    logger=False,
    engineio_logger=False
)

# Register blueprints
app.register_blueprint(api_bp)

# Initialize chat handler
chat_handler = ChatHandler(socketio)


# =============================================================================
# Static file serving
# =============================================================================

@app.route('/')
def serve_index():
    """Serve the main HTML page"""
    return send_from_directory(CLIENT_PATH, 'index.html')


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
    
    return app, socketio


def run_server(host: str = None, port: int = None, mode: str = 'cloud', debug: bool = False):
    """Run the web server"""
    global _startup_mode
    _startup_mode = mode  # Store for session defaults
    
    load_web_config()
    
    host = host or get_web_setting('server.host', '0.0.0.0')
    port = port or get_web_setting('server.port', 5001)
    debug = debug or get_web_setting('server.debug', False)
    
    # Load Jarvis config for the specified mode
    load_jarvis_config(mode)
    
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║                     🤖 JARVIS WEB UI                          ║
╠═══════════════════════════════════════════════════════════════╣
║  Mode:     {mode.upper():<52} ║
║  Address:  http://{host}:{port:<42} ║
║  Debug:    {str(debug):<52} ║
╚═══════════════════════════════════════════════════════════════╝
""")
    
    socketio.run(app, host=host, port=port, debug=debug)


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

