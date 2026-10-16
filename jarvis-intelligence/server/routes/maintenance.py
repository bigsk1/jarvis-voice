"""
Maintenance API Routes - Trigger maintenance jobs
"""
import asyncio
import subprocess
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request

# Add parent paths
JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT / 'lib'))

maintenance_bp = Blueprint('maintenance', __name__, url_prefix='/api/maintenance')


@maintenance_bp.route('/reflect', methods=['POST'])
def trigger_reflection():
    """Synchronously process a bounded global batch or explicit pending queue IDs."""
    from reflection_review import ReflectionBusy

    try:
        mode = request.args.get('mode', 'cloud')
        if mode not in {'cloud', 'local'}:
            raise ValueError('mode must be cloud or local')
        batch_size = int(request.args.get('batch_size', '5'))
        if not 1 <= batch_size <= 20:
            raise ValueError('batch_size must be between 1 and 20')
        body = request.get_json(silent=True) if request.is_json else {}
        if body is None or not isinstance(body, dict):
            raise ValueError('request body must be a JSON object')
        if 'reflection_id' in body and 'reflection_ids' in body:
            raise ValueError('use reflection_id or reflection_ids, not both')
        single = 'reflection_id' in body
        ids = [body['reflection_id']] if single else body.get('reflection_ids')
        if 'reflection_ids' in body or single:
            if (not isinstance(ids, list) or not 1 <= len(ids) <= 5
                    or any(isinstance(value, bool) or not isinstance(value, int) or value < 1
                           for value in ids)
                    or len(set(ids)) != len(ids)):
                raise ValueError('reflection_ids must contain 1 to 5 unique positive queue IDs')

        from config_loader import config_scope
        from intelligence import get_intelligence_layer

        async def do_reflect():
            with config_scope(mode):
                intel = get_intelligence_layer(mode)
                if not intel:
                    return None
                return await intel.process_reflection_queue_detailed(
                    batch_size=batch_size, reflection_ids=ids)

        result = asyncio.run(do_reflect())
        if result is None:
            return jsonify({'ok': False, 'error': 'Intelligence layer not available'}), 503
        if single and result['outcomes'][0]['status'] == 'skipped':
            reason = result['outcomes'][0].get('reason')
            if reason != 'missing_experience':
                status = 404 if reason == 'missing' else 409
                return jsonify({'ok': False, 'error': reason, **result}), status
        return jsonify({'ok': True, **result,
                        'message': f"Processed {result['processed']} pending reflections"})
    except ReflectionBusy as e:
        return jsonify({'ok': False, 'error': str(e)}), 409
    except ValueError as e:
        return jsonify({'ok': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@maintenance_bp.route('/decay', methods=['POST'])
def run_decay_job():
    """Run confidence decay job"""
    try:
        mode = request.args.get('mode', 'cloud')
        force = request.args.get('force', 'false').lower() in ('true', '1', 'yes', 'on')
        dry_run = request.args.get('dry_run', 'false').lower() in ('true', '1', 'yes', 'on')
        
        from config_loader import config_scope
        from intelligence import get_intelligence_layer
        
        async def do_decay():
            with config_scope(mode):
                intel = get_intelligence_layer(mode)
                if not intel:
                    return {'error': 'Intelligence layer not available'}
                return await intel.run_decay_job(force=force, dry_run=dry_run)
        
        result = asyncio.run(do_decay())
        
        return jsonify({
            'ok': True,
            'job': 'decay',
            **result
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@maintenance_bp.route('/anomaly', methods=['POST'])
def run_anomaly_detection():
    """Run anomaly detection"""
    try:
        mode = request.args.get('mode', 'cloud')
        
        from config_loader import config_scope
        from intelligence import get_intelligence_layer
        
        async def do_anomaly():
            with config_scope(mode):
                intel = get_intelligence_layer(mode)
                if not intel:
                    return {'error': 'Intelligence layer not available'}
                return await intel.run_anomaly_detection()
        
        result = asyncio.run(do_anomaly())
        
        return jsonify({
            'ok': True,
            'job': 'anomaly',
            **result
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@maintenance_bp.route('/meta-cognition', methods=['POST'])
def run_meta_cognition():
    """Run meta-cognition analysis"""
    try:
        mode = request.args.get('mode', 'cloud')
        
        from config_loader import config_scope
        from intelligence import get_intelligence_layer
        
        async def do_meta():
            with config_scope(mode):
                intel = get_intelligence_layer(mode)
                if not intel:
                    return {'error': 'Intelligence layer not available'}
                return await intel.run_meta_cognition()
        
        result = asyncio.run(do_meta())
        
        return jsonify({
            'ok': True,
            'job': 'meta_cognition',
            **result
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@maintenance_bp.route('/all', methods=['POST'])
def run_all_maintenance():
    """Run all maintenance jobs"""
    try:
        mode = request.args.get('mode', 'cloud')
        force = request.args.get('force', 'false').lower() in ('true', '1', 'yes', 'on')
        dry_run = request.args.get('dry_run', 'false').lower() in ('true', '1', 'yes', 'on')
        
        from config_loader import config_scope
        from intelligence import get_intelligence_layer
        
        async def do_all():
            with config_scope(mode):
                intel = get_intelligence_layer(mode)
                if not intel:
                    return {'error': 'Intelligence layer not available'}
                return await intel.run_all_maintenance(force=force, dry_run=dry_run)
        
        result = asyncio.run(do_all())
        
        return jsonify({
            'ok': True,
            'job': 'all',
            **result
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@maintenance_bp.route('/health', methods=['GET'])
def check_health():
    """Check intelligence layer health"""
    try:
        mode = request.args.get('mode', 'cloud')
        
        # Run the health check script
        script_path = JARVIS_ROOT / 'bin' / 'check-intelligence-health.py'
        
        result = subprocess.run(
            [sys.executable, str(script_path), mode, '--json'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            import json
            try:
                health_data = json.loads(result.stdout)
                return jsonify({
                    'ok': True,
                    'health': health_data
                })
            except json.JSONDecodeError:
                return jsonify({
                    'ok': True,
                    'output': result.stdout
                })
        else:
            return jsonify({
                'ok': False,
                'error': result.stderr or result.stdout
            }), 500
    except subprocess.TimeoutExpired:
        return jsonify({'ok': False, 'error': 'Health check timed out'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
