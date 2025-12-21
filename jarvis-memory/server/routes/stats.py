"""
Stats API Routes
Dashboard statistics for memory system
"""
from flask import Blueprint, jsonify, request
from ..services.memory_service import MemoryService

stats_bp = Blueprint('stats', __name__, url_prefix='/api/stats')


def get_mode() -> str:
    """Get mode from query param or default to cloud"""
    return request.args.get('mode', 'cloud')


@stats_bp.route('', methods=['GET'])
def get_stats():
    """
    Get comprehensive memory statistics
    
    Query params:
        - mode: cloud|local (default: cloud)
    """
    mode = get_mode()
    service = MemoryService(mode)
    
    memory_stats = service.get_stats()
    conversation_stats = service.get_conversation_stats()
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'memory': memory_stats,
        'conversations': conversation_stats
    })


@stats_bp.route('/memory', methods=['GET'])
def get_memory_stats():
    """Get memory-specific statistics"""
    mode = get_mode()
    service = MemoryService(mode)
    
    stats = service.get_stats()
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'stats': stats
    })

