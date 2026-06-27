"""
Jarvis Canvas - Health check routes
"""
from datetime import datetime, timezone
from flask import Blueprint, current_app, jsonify

from server.pages import load_pages

health_bp = Blueprint('health', __name__)


def _get_jarvis_version():
    """Read Jarvis version from central VERSION file."""
    try:
        from version import JARVIS_VERSION
        return JARVIS_VERSION
    except ImportError:
        try:
            from pathlib import Path
            return (Path(__file__).parent.parent.parent.parent / 'VERSION').read_text().strip()
        except Exception:
            return '0.0.0'


@health_bp.route('/api/health')
def health():
    """Health check endpoint."""
    startup_mode = current_app.config.get('JARVIS_STARTUP_MODE', 'cloud')
    return jsonify({
        "status": "healthy",
        "service": "jarvis-canvas",
        "startup_mode": startup_mode,
        "mode": startup_mode,
        "version": _get_jarvis_version(),
        "pages": len(load_pages()),
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + "Z"
    })
