"""
Jarvis Intelligence Dashboard - Main Application
Flask server for viewing/managing Jarvis intelligence layer
"""
import os
import sys
from pathlib import Path
from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS

# Setup paths
INTELLIGENCE_ROOT = Path(__file__).parent.parent
JARVIS_ROOT = INTELLIGENCE_ROOT.parent
CLIENT_PATH = INTELLIGENCE_ROOT / 'client'
DATA_PATH = JARVIS_ROOT / 'data'

# Add lib to path
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

# Import routes after path setup
from .routes.experiences import experiences_bp
from .routes.insights import insights_bp
from .routes.stats import stats_bp
from .routes.maintenance import maintenance_bp
from .routes.feedback import feedback_bp

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
# Status endpoint
# =============================================================================

@app.route('/api/status', methods=['GET'])
def get_status():
    """Health check and basic status info"""
    return jsonify({
        'ok': True,
        'status': 'running',
        'version': '1.0.0',
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

def run_server(host: str = '0.0.0.0', port: int = 5003, debug: bool = False):
    """Run the web server"""
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║              📊 JARVIS INTELLIGENCE DASHBOARD                 ║
╠═══════════════════════════════════════════════════════════════╣
║  Address:  http://{host}:{port:<42} ║
║  Debug:    {str(debug):<52} ║
╚═══════════════════════════════════════════════════════════════╝
""")
    
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Jarvis Intelligence Dashboard')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=5003, help='Port to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, debug=args.debug)

