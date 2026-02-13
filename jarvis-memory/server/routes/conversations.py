"""
Conversations API Routes
View conversation history from database
"""
from flask import Blueprint, jsonify, request
from ..services.memory_service import MemoryService

conversations_bp = Blueprint('conversations', __name__, url_prefix='/api/conversations')


def get_mode() -> str:
    """Get mode from query param or default to cloud"""
    return request.args.get('mode', 'cloud')


@conversations_bp.route('', methods=['GET'])
def list_conversations():
    """
    List conversations from database
    
    Query params:
        - mode: cloud|local (default: cloud)
        - limit: max results (default: 100)
        - offset: pagination offset (default: 0)
    """
    mode = get_mode()
    service = MemoryService(mode)
    
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    conversations = service.list_conversations(limit=limit, offset=offset)
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'count': len(conversations),
        'conversations': conversations
    })


@conversations_bp.route('/search', methods=['GET'])
def search_conversations():
    """
    Search conversations
    
    Query params:
        - q: search query (required)
        - mode: cloud|local
        - limit: max results (default: 50)
    """
    mode = get_mode()
    service = MemoryService(mode)
    
    query = request.args.get('q', '').strip()
    limit = request.args.get('limit', 50, type=int)
    
    if not query:
        return jsonify({
            'ok': False,
            'error': 'Search query required (q parameter)'
        }), 400
    
    conversations = service.search_conversations(query, limit=limit)
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'query': query,
        'count': len(conversations),
        'conversations': conversations
    })


@conversations_bp.route('/stats', methods=['GET'])
def conversation_stats():
    """Get conversation statistics"""
    mode = get_mode()
    service = MemoryService(mode)
    
    stats = service.get_conversation_stats()
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'stats': stats
    })

