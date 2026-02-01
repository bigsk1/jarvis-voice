"""
Jarvis Canvas - Health check routes
"""
from datetime import datetime, timezone
from flask import Blueprint, jsonify

from server.pages import load_pages

health_bp = Blueprint('health', __name__)


@health_bp.route('/api/health')
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "jarvis-canvas",
        "pages": len(load_pages()),
        "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') + "Z"
    })
