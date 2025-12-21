"""
Memory API Routes
CRUD operations for knowledge_base
"""
from flask import Blueprint, jsonify, request
from ..services.memory_service import MemoryService

memories_bp = Blueprint('memories', __name__, url_prefix='/api/memories')


def get_mode() -> str:
    """Get mode from query param or default to cloud"""
    return request.args.get('mode', 'cloud')


@memories_bp.route('', methods=['GET'])
def list_memories():
    """
    List memories with optional filtering
    
    Query params:
        - mode: cloud|local (default: cloud)
        - category: filter by category
        - limit: max results (default: 100)
        - offset: pagination offset (default: 0)
        - sort_by: column to sort by (default: updated_at)
        - sort_order: ASC|DESC (default: DESC)
    """
    mode = get_mode()
    service = MemoryService(mode)
    
    category = request.args.get('category')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    sort_by = request.args.get('sort_by', 'updated_at')
    sort_order = request.args.get('sort_order', 'DESC')
    
    memories = service.list_memories(
        category=category,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order
    )
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'count': len(memories),
        'memories': memories
    })


@memories_bp.route('/<int:memory_id>', methods=['GET'])
def get_memory(memory_id: int):
    """Get a single memory by ID"""
    mode = get_mode()
    service = MemoryService(mode)
    
    memory = service.get_memory(memory_id)
    
    if memory:
        return jsonify({
            'ok': True,
            'mode': mode,
            'memory': memory
        })
    else:
        return jsonify({
            'ok': False,
            'error': f'Memory not found: {memory_id}'
        }), 404


@memories_bp.route('/search', methods=['GET'])
def search_memories():
    """
    Search memories using FTS5 (full-text search)
    
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
    
    memories = service.search_memories(query, limit=limit)
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'query': query,
        'count': len(memories),
        'memories': memories
    })


@memories_bp.route('', methods=['POST'])
def create_memory():
    """
    Create a new memory
    
    Body (JSON):
        - category: string (required)
        - key: string (required)
        - value: string (required)
        - importance: int 1-10 (default: 5)
        - source: string (optional)
        - metadata: object (optional)
    
    Query params:
        - mode: cloud|local
    """
    mode = get_mode()
    service = MemoryService(mode)
    
    data = request.get_json() or {}
    
    # Validate required fields
    category = data.get('category', '').strip()
    key = data.get('key', '').strip()
    value = data.get('value', '').strip()
    
    if not category:
        return jsonify({'ok': False, 'error': 'category is required'}), 400
    if not key:
        return jsonify({'ok': False, 'error': 'key is required'}), 400
    if not value:
        return jsonify({'ok': False, 'error': 'value is required'}), 400
    
    importance = data.get('importance', 5)
    if not isinstance(importance, int) or importance < 1 or importance > 10:
        importance = 5
    
    memory_id = service.create_memory(
        category=category,
        key=key,
        value=value,
        importance=importance,
        source=data.get('source'),
        metadata=data.get('metadata')
    )
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'message': 'Memory created',
        'id': memory_id
    })


@memories_bp.route('/<int:memory_id>', methods=['PUT'])
def update_memory(memory_id: int):
    """
    Update an existing memory
    
    Body (JSON): any of
        - category: string
        - key: string
        - value: string
        - importance: int 1-10
        - metadata: object
    
    Query params:
        - mode: cloud|local
    """
    mode = get_mode()
    service = MemoryService(mode)
    
    data = request.get_json() or {}
    
    # Check memory exists
    existing = service.get_memory(memory_id)
    if not existing:
        return jsonify({
            'ok': False,
            'error': f'Memory not found: {memory_id}'
        }), 404
    
    # Extract update fields
    update_fields = {}
    if 'category' in data:
        update_fields['category'] = data['category']
    if 'key' in data:
        update_fields['key'] = data['key']
    if 'value' in data:
        update_fields['value'] = data['value']
    if 'importance' in data:
        importance = data['importance']
        if isinstance(importance, int) and 1 <= importance <= 10:
            update_fields['importance'] = importance
    if 'metadata' in data:
        update_fields['metadata'] = data['metadata']
    
    if not update_fields:
        return jsonify({
            'ok': False,
            'error': 'No update fields provided'
        }), 400
    
    success = service.update_memory(memory_id, **update_fields)
    
    return jsonify({
        'ok': success,
        'mode': mode,
        'message': 'Memory updated' if success else 'Update failed'
    })


@memories_bp.route('/<int:memory_id>', methods=['DELETE'])
def delete_memory(memory_id: int):
    """Delete a memory"""
    mode = get_mode()
    service = MemoryService(mode)
    
    # Check memory exists
    existing = service.get_memory(memory_id)
    if not existing:
        return jsonify({
            'ok': False,
            'error': f'Memory not found: {memory_id}'
        }), 404
    
    success = service.delete_memory(memory_id)
    
    return jsonify({
        'ok': success,
        'mode': mode,
        'message': 'Memory deleted' if success else 'Delete failed'
    })


@memories_bp.route('/<int:memory_id>/reembed', methods=['POST'])
def reembed_memory(memory_id: int):
    """
    Re-generate embedding for a memory after edits.
    Calls the bin/re-embed-memory script.
    
    Query params:
        - mode: cloud|local
    """
    import subprocess
    import sys
    from pathlib import Path
    
    mode = get_mode()
    service = MemoryService(mode)
    
    # Check memory exists
    existing = service.get_memory(memory_id)
    if not existing:
        return jsonify({
            'ok': False,
            'error': f'Memory not found: {memory_id}'
        }), 404
    
    try:
        # Get path to re-embed script
        jarvis_root = Path(__file__).parent.parent.parent.parent
        script_path = jarvis_root / 'bin' / 're-embed-memory'
        
        if not script_path.exists():
            return jsonify({
                'ok': False,
                'error': 'Re-embed script not found'
            }), 500
        
        # Run the script
        result = subprocess.run(
            [sys.executable, str(script_path), str(memory_id), mode],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            return jsonify({
                'ok': False,
                'error': result.stderr or result.stdout or 'Re-embed failed',
                'stdout': result.stdout,
                'stderr': result.stderr
            }), 500
        
        return jsonify({
            'ok': True,
            'mode': mode,
            'message': f'Memory {memory_id} re-embedded successfully',
            'id': memory_id,
            'output': result.stdout
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({
            'ok': False,
            'error': 'Re-embed timed out'
        }), 504
    except Exception as e:
        return jsonify({
            'ok': False,
            'error': str(e)
        }), 500


@memories_bp.route('/categories', methods=['GET'])
def get_categories():
    """Get list of categories with counts"""
    mode = get_mode()
    service = MemoryService(mode)
    
    categories = service.get_categories()
    
    return jsonify({
        'ok': True,
        'mode': mode,
        'categories': categories
    })

