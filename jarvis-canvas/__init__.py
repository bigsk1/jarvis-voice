"""
Jarvis Canvas - Visual Knowledge Viewer

A beautiful local web UI for Jarvis to display rich content.
Includes Canvas pages and Image Gallery.
"""
from .config import DEFAULT_PORT, DEFAULT_HOST
from .server import create_app

__version__ = "2.0.0"
__all__ = ['create_app', 'DEFAULT_PORT', 'DEFAULT_HOST']
