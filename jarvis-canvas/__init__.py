"""
Jarvis Canvas - Visual Knowledge Viewer

A beautiful local web UI for Jarvis to display rich content.
Includes Canvas pages and Image Gallery.
"""
from .config import DEFAULT_PORT, DEFAULT_HOST
from .server import create_app

try:
    from version import JARVIS_VERSION
    __version__ = JARVIS_VERSION
except ImportError:
    __version__ = "0.0.0"

__all__ = ['create_app', 'DEFAULT_PORT', 'DEFAULT_HOST']
