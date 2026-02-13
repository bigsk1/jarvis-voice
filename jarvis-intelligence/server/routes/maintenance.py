"""
Maintenance API Routes - Trigger maintenance jobs
"""
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
    """Trigger reflection processing"""
    try:
        mode = request.args.get('mode', 'cloud')
        batch_size = request.args.get('batch_size', 5, type=int)
        
        # Load config for mode
        from config_loader import load_config
        load_config(mode)
        
        # Import intelligence after config loaded
        from intelligence import get_intelligence_layer
        import asyncio
        
        async def do_reflect():
            intel = get_intelligence_layer()
            if not intel:
                return 0
            return await intel.process_reflection_queue(batch_size=batch_size)
        
        processed = asyncio.run(do_reflect())
        
        return jsonify({
            'ok': True,
            'processed': processed,
            'message': f'Processed {processed} pending reflections'
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@maintenance_bp.route('/decay', methods=['POST'])
def run_decay_job():
    """Run confidence decay job"""
    try:
        mode = request.args.get('mode', 'cloud')
        
        from config_loader import load_config
        load_config(mode)
        
        from intelligence import get_intelligence_layer
        import asyncio
        
        async def do_decay():
            intel = get_intelligence_layer()
            if not intel:
                return {'error': 'Intelligence layer not available'}
            return await intel.run_decay_job()
        
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
        
        from config_loader import load_config
        load_config(mode)
        
        from intelligence import get_intelligence_layer
        import asyncio
        
        async def do_anomaly():
            intel = get_intelligence_layer()
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
        
        from config_loader import load_config
        load_config(mode)
        
        from intelligence import get_intelligence_layer
        import asyncio
        
        async def do_meta():
            intel = get_intelligence_layer()
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
        
        from config_loader import load_config
        load_config(mode)
        
        from intelligence import get_intelligence_layer
        import asyncio
        
        async def do_all():
            intel = get_intelligence_layer()
            if not intel:
                return {'error': 'Intelligence layer not available'}
            return await intel.run_all_maintenance()
        
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

