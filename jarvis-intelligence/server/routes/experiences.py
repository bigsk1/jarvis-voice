"""
Experiences API Routes
"""
import subprocess
import sys
from pathlib import Path
from flask import Blueprint, jsonify, request

# Add parent paths
JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from ..services.intelligence_service import IntelligenceService

experiences_bp = Blueprint('experiences', __name__, url_prefix='/api/experiences')


def get_service():
    """Get service instance with current mode"""
    mode = request.args.get('mode', 'cloud')
    return IntelligenceService(mode)


@experiences_bp.route('', methods=['GET'])
def list_experiences():
    """List all experiences"""
    try:
        service = get_service()
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        success_only = request.args.get('success_only')
        sort = request.args.get('sort', 'date')
        tool_count = request.args.get('tool_count')
        tool = request.args.get('tool')
        completion_guard_status = request.args.get('completion_guard_status')
        
        if success_only is not None:
            success_only = success_only.lower() == 'true'
        
        experiences, total = service.list_experiences(
            limit=limit,
            offset=offset,
            success_only=success_only,
            sort=sort,
            tool_count=tool_count,
            tool=tool,
            completion_guard_status=completion_guard_status
        )
        
        return jsonify({
            'ok': True,
            'count': len(experiences),
            'total': total,
            'limit': limit,
            'offset': offset,
            'has_more': offset + len(experiences) < total,
            'experiences': experiences
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@experiences_bp.route('/summary', methods=['GET'])
def get_experience_summary():
    """Get lightweight experience counts and facets."""
    try:
        service = get_service()
        return jsonify({
            'ok': True,
            'summary': service.get_experience_summary()
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@experiences_bp.route('/<int:experience_id>', methods=['GET'])
def get_experience(experience_id):
    """Get a single experience"""
    try:
        service = get_service()
        experience = service.get_experience(experience_id)
        
        if not experience:
            return jsonify({'ok': False, 'error': 'Experience not found'}), 404
        
        return jsonify({
            'ok': True,
            'experience': experience
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@experiences_bp.route('/search', methods=['GET'])
def search_experiences():
    """Search experiences"""
    try:
        service = get_service()
        query = request.args.get('q', '')
        limit = request.args.get('limit', 50, type=int)
        sort = request.args.get('sort', 'date')
        
        if not query:
            return jsonify({'ok': False, 'error': 'Query parameter q is required'}), 400
        
        experiences = service.search_experiences(query, limit, sort=sort)
        
        return jsonify({
            'ok': True,
            'count': len(experiences),
            'query': query,
            'experiences': experiences
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@experiences_bp.route('/<int:experience_id>', methods=['PUT'])
def update_experience(experience_id):
    """Update an experience"""
    try:
        service = get_service()
        data = request.get_json() or {}
        
        success = service.update_experience(
            experience_id,
            query=data.get('query'),
            context_summary=data.get('context_summary'),
            outcome_success=data.get('outcome_success')
        )
        
        if success:
            return jsonify({'ok': True, 'message': 'Experience updated'})
        else:
            return jsonify({'ok': False, 'error': 'Experience not found or no changes'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@experiences_bp.route('/<int:experience_id>', methods=['DELETE'])
def delete_experience(experience_id):
    """Delete an experience"""
    try:
        service = get_service()
        success = service.delete_experience(experience_id)
        
        if success:
            return jsonify({'ok': True, 'message': 'Experience deleted'})
        else:
            return jsonify({'ok': False, 'error': 'Experience not found'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@experiences_bp.route('/<int:experience_id>/reembed', methods=['POST'])
def reembed_experience(experience_id):
    """Re-embed an experience after editing"""
    try:
        mode = request.args.get('mode', 'cloud')
        
        # Run the re-embed script
        script_path = JARVIS_ROOT / 'bin' / 're-embed-experience'
        
        result = subprocess.run(
            [sys.executable, str(script_path), str(experience_id), mode],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            return jsonify({
                'ok': True,
                'message': f'Experience {experience_id} re-embedded successfully',
                'output': result.stdout
            })
        else:
            return jsonify({
                'ok': False,
                'error': result.stderr or result.stdout or 'Re-embed failed'
            }), 500
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': 'Re-embed timed out'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
