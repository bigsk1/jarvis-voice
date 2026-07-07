"""Shared placeholder assets when generated, uploaded, or cached media is missing."""

from pathlib import Path

from flask import abort, send_file

_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = _ROOT / 'jarvis-web' / 'client' / 'assets'
IMAGE_UNAVAILABLE = ASSETS_DIR / 'image-unavailable.jpg'
VIDEO_UNAVAILABLE = ASSETS_DIR / 'video-unavailable.jpg'

WEB_IMAGE_PLACEHOLDER_URL = '/assets/image-unavailable.jpg'
WEB_VIDEO_PLACEHOLDER_URL = '/assets/video-unavailable.jpg'
CANVAS_IMAGE_PLACEHOLDER_URL = '/static/assets/image-unavailable.jpg'
CANVAS_VIDEO_PLACEHOLDER_URL = '/static/assets/video-unavailable.jpg'

_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.ico', '.tif', '.tiff'}
_VIDEO_EXTENSIONS = {'.mp4', '.webm', '.mov', '.avi', '.mkv', '.m4v'}

_CACHE_MAX_AGE = 31536000


def placeholder_path(kind: str = 'image') -> Path:
    return VIDEO_UNAVAILABLE if kind == 'video' else IMAGE_UNAVAILABLE


def is_image_extension(ext: str) -> bool:
    return ext.lower() in _IMAGE_EXTENSIONS


def is_video_extension(ext: str) -> bool:
    return ext.lower() in _VIDEO_EXTENSIONS


def send_placeholder(kind: str = 'image'):
    """Return a cached JPEG placeholder response."""
    path = placeholder_path(kind)
    if not path.is_file():
        abort(404)
    return send_file(
        path,
        mimetype='image/jpeg',
        max_age=_CACHE_MAX_AGE,
        conditional=True,
    )
