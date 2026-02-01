"""
Jarvis Canvas - Flask Application Factory
"""
from pathlib import Path
from flask import Flask
from flask_cors import CORS

from config import STATIC_DIR, GENERATED_IMAGES_DIR, GENERATED_VIDEOS_DIR
from server.pages import load_pages


def create_app():
    """Create and configure the Flask application."""
    
    # Get the path to the templates and static directories
    package_root = Path(__file__).parent.parent
    template_dir = package_root / 'client' / 'templates'
    static_dir = package_root / 'client' / 'static'
    
    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(static_dir),
        static_url_path='/static'
    )
    
    CORS(app)
    
    # Register blueprints
    from server.routes import health_bp, pages_bp, gallery_bp, video_gallery_bp, stash_bp, views_bp
    
    app.register_blueprint(health_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(gallery_bp)
    app.register_blueprint(video_gallery_bp)
    app.register_blueprint(stash_bp)
    app.register_blueprint(views_bp)
    
    return app


def run_server(host='0.0.0.0', port=8890, debug=False):
    """Run the Flask server with startup banner."""
    
    # Count content
    page_count = len(load_pages())
    image_count = len([f for f in GENERATED_IMAGES_DIR.iterdir() 
                      if f.is_file() and f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp')]) if GENERATED_IMAGES_DIR.exists() else 0
    video_count = len([f for f in GENERATED_VIDEOS_DIR.iterdir() 
                      if f.is_file() and f.suffix.lower() in ('.mp4', '.webm', '.mov')]) if GENERATED_VIDEOS_DIR.exists() else 0
    
    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║                    🎨 Jarvis Canvas                            ║
║         Visual Knowledge Viewer + Media Galleries              ║
╠═══════════════════════════════════════════════════════════════╣
║  Canvas:        http://localhost:{port:<5}                      ║
║  Image Gallery: http://localhost:{port}/gallery                 ║
║  Video Gallery: http://localhost:{port}/video-gallery           ║
╠═══════════════════════════════════════════════════════════════╣
║  Pages: {page_count:<5}  |  Images: {image_count:<5}  |  Videos: {video_count:<5}          ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    app = create_app()
    app.run(host=host, port=port, debug=debug, threaded=True)
