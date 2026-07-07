"""
Reminder API routes for Jarvis Memory UI.
"""
from flask import Blueprint, jsonify, request
from pathlib import Path
import sys

JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT))

from api.managers.reminder_manager import ReminderManager


reminders_bp = Blueprint('reminders', __name__, url_prefix='/api/reminders')


def get_mode() -> str:
    return request.args.get('mode', 'cloud')


def get_manager() -> ReminderManager:
    return ReminderManager(mode=get_mode())


@reminders_bp.route('', methods=['GET'])
def list_reminders():
    manager = get_manager()
    status = request.args.get('status')
    limit = request.args.get('limit', 200, type=int)
    reminders = manager.list_reminders(status=status if status and status != 'all' else None, limit=limit)
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'count': len(reminders),
        'reminders': reminders
    })


@reminders_bp.route('/<int:reminder_id>', methods=['GET'])
def get_reminder(reminder_id: int):
    manager = get_manager()
    reminder = manager.get_reminder(reminder_id)
    if not reminder:
        return jsonify({'ok': False, 'error': f'Reminder not found: {reminder_id}'}), 404
    return jsonify({'ok': True, 'mode': get_mode(), 'reminder': reminder})


@reminders_bp.route('', methods=['POST'])
def create_reminder():
    manager = get_manager()
    data = request.get_json() or {}

    title = (data.get('title') or '').strip()
    trigger_time = (data.get('trigger_time') or '').strip()

    if not title:
        return jsonify({'ok': False, 'error': 'title is required'}), 400
    if not trigger_time:
        return jsonify({'ok': False, 'error': 'trigger_time is required'}), 400

    reminder_id = manager.create_reminder(
        title=title,
        description=(data.get('description') or '').strip() or None,
        trigger_time=trigger_time,
        related_intel_file=(data.get('related_intel_file') or '').strip() or None,
        callback_url=(data.get('callback_url') or '').strip() or None,
        recurrence_rule=(data.get('recurrence_rule') or '').strip() or None,
        metadata=data.get('metadata')
    )
    reminder = manager.get_reminder(reminder_id)
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'message': 'Reminder created',
        'reminder_id': reminder_id,
        'reminder': reminder
    })


@reminders_bp.route('/<int:reminder_id>', methods=['PUT'])
def update_reminder(reminder_id: int):
    manager = get_manager()
    data = request.get_json() or {}

    existing = manager.get_reminder(reminder_id)
    if not existing:
        return jsonify({'ok': False, 'error': f'Reminder not found: {reminder_id}'}), 404

    ok = manager.update_reminder(
        reminder_id=reminder_id,
        title=(data.get('title') or existing.get('title') or '').strip(),
        description=(data.get('description') or existing.get('description') or '').strip() or None,
        trigger_time=(data.get('trigger_time') or existing.get('trigger_time') or '').strip(),
        related_intel_file=(data.get('related_intel_file') or existing.get('related_intel_file') or '').strip() or None,
        callback_url=(data.get('callback_url') or existing.get('callback_url') or '').strip() or None,
        recurrence_rule=(data.get('recurrence_rule') or existing.get('recurrence_rule') or '').strip() or None,
        metadata=data.get('metadata') if 'metadata' in data else existing.get('metadata'),
        reactivate=True,
    )

    reminder = manager.get_reminder(reminder_id)
    return jsonify({
        'ok': ok,
        'mode': get_mode(),
        'message': 'Reminder updated' if ok else 'Update failed',
        'reminder': reminder
    })


@reminders_bp.route('/<int:reminder_id>', methods=['DELETE'])
def cancel_or_delete_reminder(reminder_id: int):
    manager = get_manager()
    permanent = request.args.get('permanent', 'false').lower() == 'true'
    ok = manager.delete_reminder(reminder_id) if permanent else manager.cancel_reminder(reminder_id)
    if not ok:
        return jsonify({'ok': False, 'error': f'Reminder not found: {reminder_id}'}), 404
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'message': 'Reminder deleted' if permanent else 'Reminder canceled'
    })


@reminders_bp.route('/<int:reminder_id>/acknowledge', methods=['POST'])
def acknowledge_reminder(reminder_id: int):
    manager = get_manager()
    ok = manager.acknowledge_reminder(reminder_id)
    if not ok:
        return jsonify({'ok': False, 'error': f'Reminder not found: {reminder_id}'}), 404
    reminder = manager.get_reminder(reminder_id)
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'message': 'Reminder acknowledged',
        'reminder': reminder
    })


@reminders_bp.route('/acknowledge-all', methods=['POST'])
def acknowledge_all_reminders():
    manager = get_manager()
    status = request.args.get('status')
    count = manager.acknowledge_all(status=status if status and status != 'all' else None)
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'message': f'Acknowledged {count} reminder(s)',
        'count': count
    })
