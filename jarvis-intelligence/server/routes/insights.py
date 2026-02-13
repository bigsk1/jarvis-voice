"""
Insights API Routes
"""
import subprocess
import sys
from pathlib import Path
from flask import Blueprint, jsonify, request

# Add parent paths
JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

from ..services.intelligence_service import IntelligenceService

insights_bp = Blueprint('insights', __name__, url_prefix='/api/insights')


def get_service():
    """Get service instance with current mode"""
    mode = request.args.get('mode', 'cloud')
    return IntelligenceService(mode)


@insights_bp.route('', methods=['GET'])
def list_insights():
    """List all insights"""
    try:
        service = get_service()
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        constraint_type = request.args.get('constraint_type')
        min_confidence = request.args.get('min_confidence', type=float)
        
        insights = service.list_insights(
            limit=limit,
            offset=offset,
            constraint_type=constraint_type,
            min_confidence=min_confidence
        )
        
        return jsonify({
            'ok': True,
            'count': len(insights),
            'insights': insights
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@insights_bp.route('/<int:insight_id>', methods=['GET'])
def get_insight(insight_id):
    """Get a single insight"""
    try:
        service = get_service()
        insight = service.get_insight(insight_id)
        
        if not insight:
            return jsonify({'ok': False, 'error': 'Insight not found'}), 404
        
        return jsonify({
            'ok': True,
            'insight': insight
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@insights_bp.route('/search', methods=['GET'])
def search_insights():
    """Search insights"""
    try:
        service = get_service()
        query = request.args.get('q', '')
        limit = request.args.get('limit', 50, type=int)
        
        if not query:
            return jsonify({'ok': False, 'error': 'Query parameter q is required'}), 400
        
        insights = service.search_insights(query, limit)
        
        return jsonify({
            'ok': True,
            'count': len(insights),
            'query': query,
            'insights': insights
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@insights_bp.route('/<int:insight_id>', methods=['PUT'])
def update_insight(insight_id):
    """Update an insight"""
    try:
        service = get_service()
        data = request.get_json() or {}
        
        success = service.update_insight(
            insight_id,
            description=data.get('description'),
            applies_to_pattern=data.get('applies_to_pattern'),
            confidence=data.get('confidence'),
            constraint_type=data.get('constraint_type')
        )
        
        if success:
            return jsonify({'ok': True, 'message': 'Insight updated'})
        else:
            return jsonify({'ok': False, 'error': 'Insight not found or no changes'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@insights_bp.route('/<int:insight_id>', methods=['DELETE'])
def delete_insight(insight_id):
    """Delete an insight"""
    try:
        service = get_service()
        success = service.delete_insight(insight_id)
        
        if success:
            return jsonify({'ok': True, 'message': 'Insight deleted'})
        else:
            return jsonify({'ok': False, 'error': 'Insight not found'}), 404
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@insights_bp.route('/<int:insight_id>/reembed', methods=['POST'])
def reembed_insight(insight_id):
    """Re-embed an insight after editing"""
    try:
        mode = request.args.get('mode', 'cloud')
        
        # Run the re-embed script
        script_path = JARVIS_ROOT / 'bin' / 're-embed-insight'
        
        result = subprocess.run(
            [sys.executable, str(script_path), str(insight_id), mode],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            return jsonify({
                'ok': True,
                'message': f'Insight {insight_id} re-embedded successfully',
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


@insights_bp.route('/tool-performance', methods=['GET'])
def get_tool_performance():
    """Get tool performance metrics from insights"""
    try:
        service = get_service()
        performance = service.get_tool_performance()
        
        return jsonify({
            'ok': True,
            'count': len(performance),
            'tools': performance
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

