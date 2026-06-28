"""
Alert API routes for Jarvis Memory UI.
"""
from flask import Blueprint, jsonify, request
from pathlib import Path
import sys

JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT))

from api.managers.alert_manager import AlertManager


alerts_bp = Blueprint('alerts', __name__, url_prefix='/api/alerts')


def get_mode() -> str:
    return request.args.get('mode', 'cloud')


def get_manager() -> AlertManager:
    return AlertManager(mode=get_mode())


@alerts_bp.route('', methods=['GET'])
def list_alerts():
    manager = get_manager()
    status = request.args.get('status')
    severity = request.args.get('severity')
    source = request.args.get('source')
    search = request.args.get('search', '').strip()
    limit = request.args.get('limit', 200, type=int)
    offset = request.args.get('offset', 0, type=int)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    alerts = manager.list_alerts(
        status=status if status and status != 'all' else None,
        severity=severity if severity and severity != 'all' else None,
        source=source if source and source != 'all' else None,
        limit=limit + 1,
        offset=offset,
        search=search or None
    )
    has_more = len(alerts) > limit
    alerts = alerts[:limit]
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'count': len(alerts),
        'alerts': alerts,
        'has_more': has_more,
        'next_offset': offset + len(alerts)
    })


@alerts_bp.route('/<int:alert_id>', methods=['GET'])
def get_alert(alert_id: int):
    manager = get_manager()
    alert = manager.get_alert(alert_id)
    if not alert:
        return jsonify({'ok': False, 'error': f'Alert not found: {alert_id}'}), 404
    return jsonify({'ok': True, 'mode': get_mode(), 'alert': alert})


@alerts_bp.route('/<int:alert_id>/acknowledge', methods=['POST'])
def acknowledge_alert(alert_id: int):
    manager = get_manager()
    ok = manager.acknowledge_alert(alert_id)
    if not ok:
        return jsonify({'ok': False, 'error': f'Alert not found: {alert_id}'}), 404
    alert = manager.get_alert(alert_id)
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'message': 'Alert acknowledged',
        'alert': alert
    })


@alerts_bp.route('/acknowledge-all', methods=['POST'])
def acknowledge_all_alerts():
    manager = get_manager()
    status = request.args.get('status')
    severity = request.args.get('severity')
    count = manager.acknowledge_all(
        status=status if status and status != 'all' else None,
        severity=severity if severity and severity != 'all' else None
    )
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'message': f'Acknowledged {count} alert(s)',
        'count': count
    })


@alerts_bp.route('/<int:alert_id>', methods=['DELETE'])
def cancel_alert(alert_id: int):
    manager = get_manager()
    ok = manager.cancel_alert(alert_id)
    if not ok:
        return jsonify({'ok': False, 'error': f'Alert not found: {alert_id}'}), 404
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'message': 'Alert canceled'
    })
