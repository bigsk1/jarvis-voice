"""
Stats API Routes
"""
import sys
from pathlib import Path
from flask import Blueprint, jsonify, request

# Add parent paths
JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from reflection_review import ReflectionBusy  # noqa: E402

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


def _reflection_service():
    if request.args.get('mode', 'cloud') not in {'cloud', 'local'}:
        raise ValueError('mode must be cloud or local')
    return get_service()


@stats_bp.route('/reflection-queue', methods=['GET'])
def get_reflection_queue():
    """Search clean original requests; global next-batch preview ignores search/pagination."""
    try:
        service = _reflection_service()
        limit = int(request.args.get('limit', '50'))
        offset = int(request.args.get('offset', '0'))
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError('limit must be between 1 and 100; offset must be nonnegative')
        return jsonify({'ok': True, **service.get_reflection_queue_page(
            limit=limit, offset=offset, query=request.args.get('q', ''))})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@stats_bp.route('/reflection-queue/<int:reflection_id>', methods=['GET'])
def get_reflection_review(reflection_id):
    """Lazy review of redacted persisted evidence, including processed rows still present."""
    try:
        result = _reflection_service().get_reflection_review(reflection_id)
        if result is None:
            return jsonify({'ok': False, 'error': 'Reflection not found'}), 404
        return jsonify({'ok': True, **result})
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@stats_bp.route('/reflection-queue/<int:reflection_id>', methods=['DELETE'])
def delete_reflection(reflection_id):
    """Discard a pending queue item; retain its source experience and learned insights."""
    try:
        service = _reflection_service()
        success = service.delete_reflection(reflection_id)
        if success:
            return jsonify({'ok': True, 'message': f'Reflection {reflection_id} cancelled'})
        item = service.get_reflection_review(reflection_id)
        return jsonify({'ok': False, 'error': 'Reflection already processed' if item
                        else 'Reflection not found'}), 409 if item else 404
    except ReflectionBusy as e:
        return jsonify({'ok': False, 'error': str(e)}), 409
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@stats_bp.route('/reflection-queue', methods=['DELETE'])
def delete_all_reflections():
    """Discard all pending queue items for the selected mode only."""
    try:
        deleted_count = _reflection_service().delete_all_pending_reflections()
        return jsonify({'ok': True, 'deleted': deleted_count,
                        'message': f'Cancelled {deleted_count} pending reflections'})
    except ReflectionBusy as e:
        return jsonify({'ok': False, 'error': str(e)}), 409
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
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

