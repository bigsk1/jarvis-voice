"""
Jarvis Canvas - Main view routes (templates)
"""
from pathlib import Path

from flask import Blueprint, render_template, send_from_directory

from config import STATIC_DIR

views_bp = Blueprint('views', __name__)

JARVIS_LOGO = Path(__file__).resolve().parents[3] / 'jarvis-web' / 'client' / 'assets' / 'jarvis-voice.png'


@views_bp.route('/')
def index():
    """Serve the main Canvas UI."""
    return render_template('canvas.html')


@views_bp.route('/page_<path:page_suffix>')
def page_link(page_suffix):
    """Serve the Canvas UI for direct page links like /page_YYYYMMDD_HHMMSS."""
    return render_template('canvas.html')


@views_bp.route('/favicon.ico')
def favicon():
    """Serve Jarvis logo as favicon."""
    return send_from_directory(JARVIS_LOGO.parent, JARVIS_LOGO.name, mimetype='image/png')


@views_bp.route('/docs/images/<path:filename>')
def docs_images(filename):
    """Serve images from docs/images for backwards compatibility."""
    return send_from_directory(STATIC_DIR, filename)
