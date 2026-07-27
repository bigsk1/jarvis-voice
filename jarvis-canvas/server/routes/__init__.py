"""
Jarvis Canvas - Routes package

All blueprints are registered here.
"""
from .health import health_bp
from .pages import pages_bp
from .gallery import gallery_bp
from .video_gallery import video_gallery_bp
from .audio_gallery import audio_gallery_bp
from .stash import stash_bp
from .views import views_bp

__all__ = [
    'health_bp',
    'pages_bp',
    'gallery_bp',
    'video_gallery_bp',
    'audio_gallery_bp',
    'stash_bp',
    'views_bp',
]
