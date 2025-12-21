"""
Stats API Routes
"""
import sys
from pathlib import Path
from flask import Blueprint, jsonify, request

# Add parent paths
JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from ..services.intelligence_service import IntelligenceService

stats_bp = Blueprint('stats', __name__, url_prefix='/api/stats')


def get_service():
    """Get service instance with current mode"""
    mode = request.args.get('mode', 'cloud')
    return IntelligenceService(mode)


@stats_bp.route('', methods=['GET'])
def get_stats():
    """Get comprehensive intelligence statistics"""
    try:
        service = get_service()
        stats = service.get_stats()
        
        return jsonify({
            'ok': True,
            'stats': stats
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@stats_bp.route('/reflection-queue', methods=['GET'])
def get_reflection_queue():
    """Get pending reflections"""
    try:
        service = get_service()
        limit = request.args.get('limit', 50, type=int)
        queue = service.get_reflection_queue(limit)
        
        return jsonify({
            'ok': True,
            'count': len(queue),
            'queue': queue
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@stats_bp.route('/meta-knowledge', methods=['GET'])
def get_meta_knowledge():
    """Get meta-knowledge entries (blind spots, over-generalizations, etc.)"""
    try:
        service = get_service()
        limit = request.args.get('limit', 50, type=int)
        meta_type = request.args.get('type')
        
        entries = service.list_meta_knowledge(limit=limit, meta_type=meta_type)
        
        return jsonify({
            'ok': True,
            'count': len(entries),
            'entries': entries
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

