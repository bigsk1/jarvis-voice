"""
Jarvis Canvas - Flask Application Factory
"""
import sys
from pathlib import Path
from flask import Flask, request, redirect, render_template, send_from_directory
from flask_cors import CORS

from config import GENERATED_IMAGES_DIR, GENERATED_VIDEOS_DIR
from server.pages import load_pages

# Add lib to path for auth
JARVIS_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from webui_auth import is_auth_enabled, get_token_from_request, verify_token
from flask_error_logger import setup_error_logging
from config_loader import get_config_value, load_config


def create_app(mode='cloud'):
    """Create and configure the Flask application."""
    
    # Get the path to the templates and static directories
    package_root = Path(__file__).parent.parent
    template_dir = package_root / 'client' / 'templates'
    static_dir = package_root / 'client' / 'static'
    fonts_dir = JARVIS_ROOT / 'jarvis-web' / 'client' / 'fonts'
    
    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
        static_url_path='/static'
    )
    
    CORS(app)
    app.config['JARVIS_STARTUP_MODE'] = mode
    
    # Load Jarvis config for auth
    load_config(mode)
    
    # Register blueprints
    from server.routes import health_bp, pages_bp, gallery_bp, video_gallery_bp, stash_bp, views_bp
    from server.routes.auth import auth_bp
    
    app.register_blueprint(health_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(gallery_bp)
    app.register_blueprint(video_gallery_bp)
    app.register_blueprint(stash_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(auth_bp)
    
    # Error logging → logs/canvas-ui/errors-YYYY-MM-DD.jsonl
    setup_error_logging(app, 'canvas-ui')
    
    # Auth middleware
    # Note: /api/pages/* routes are public for internal tool access (canvas skill)
    # Browser-facing routes (/, /gallery, /video-gallery) require auth
    PUBLIC_ROUTES = {'/login', '/api/auth/login', '/api/auth/status', '/api/auth/verify', '/api/health'}
    PUBLIC_API_PREFIXES = ('/api/pages', '/api/stash', '/api/gallery', '/api/video-gallery')  # Internal tool APIs
    PUBLIC_EXTENSIONS = {'.css', '.js', '.ico', '.png', '.jpg', '.svg', '.woff', '.woff2', '.mp4', '.webm'}
    
    @app.before_request
    def check_auth():
        if not is_auth_enabled():
            return None
        if request.path in PUBLIC_ROUTES:
            return None
        # Allow internal tool API calls (not browser)
        if request.path.startswith(PUBLIC_API_PREFIXES):
            return None
        if any(request.path.endswith(ext) for ext in PUBLIC_EXTENSIONS):
            return None
        if request.path.startswith('/static/'):
            return None
        
        token = get_token_from_request(request)
        if verify_token(token):
            return None
        
        # Only protect browser routes, not APIs
        if request.path.startswith('/api/'):
            return {'ok': False, 'error': 'Authentication required'}, 401
        return redirect(f'/login?redirect={request.path}')
    
    @app.route('/login')
    def login_page():
        return render_template('login.html')

    @app.route('/static/fonts/<path:path>')
    def shared_fonts(path):
        """Serve shared fonts without relying on checkout symlink support."""
        return send_from_directory(fonts_dir, path)
    
    return app


def run_server(host='0.0.0.0', port=8890, mode='cloud', debug=False):
    """Run the Flask server with startup banner."""
    
    app = create_app(mode)
    
    # Count content
    page_count = len(load_pages())
    image_count = len([f for f in GENERATED_IMAGES_DIR.iterdir() 
                      if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp')]) if GENERATED_IMAGES_DIR.exists() else 0
    video_count = len([f for f in GENERATED_VIDEOS_DIR.iterdir() 
                      if f.is_file() and f.suffix.lower() in ('.mp4', '.webm', '.mov')]) if GENERATED_VIDEOS_DIR.exists() else 0
    
    auth_status = "ENABLED" if is_auth_enabled() else "DISABLED"
    public_url = (get_config_value("CANVAS_PUBLIC_URL", f"http://localhost:{port}") or f"http://localhost:{port}").strip().rstrip("/")
    gallery_url = f"{public_url}/gallery"
    video_gallery_url = f"{public_url}/video-gallery"
    
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║                    🎨 Jarvis Canvas                            ║
║         Visual Knowledge Viewer + Media Galleries              ║
╠═══════════════════════════════════════════════════════════════╣
║  Canvas:        {public_url:<42} ║
║  Image Gallery: {gallery_url:<42} ║
║  Video Gallery: {video_gallery_url:<42} ║
╠═══════════════════════════════════════════════════════════════╣
║  Mode: {mode.upper():<7} | Auth: {auth_status:<8}                          ║
║  Pages: {page_count:<5}  |  Images: {image_count:<5}  |  Videos: {video_count:<5}          ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    app.run(host=host, port=port, debug=debug, threaded=True)
