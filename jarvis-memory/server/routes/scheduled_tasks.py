"""
Scheduled Tasks API Routes
Manage scheduled tasks and run history from Jarvis Memory UI.
"""
from flask import Blueprint, jsonify, request
from pathlib import Path
import sys

JARVIS_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(JARVIS_ROOT))

from api.managers.scheduled_task_manager import ScheduledTaskManager


scheduled_tasks_bp = Blueprint('scheduled_tasks', __name__, url_prefix='/api/scheduled-tasks')


def get_mode() -> str:
    """Get mode from query param or default to cloud."""
    return request.args.get('mode', 'cloud')


def get_manager() -> ScheduledTaskManager:
    return ScheduledTaskManager(mode=get_mode())


@scheduled_tasks_bp.route('', methods=['GET'])
def list_scheduled_tasks():
    manager = get_manager()
    status = request.args.get('status', 'all')
    limit = request.args.get('limit', 100, type=int)
    tasks = manager.list_tasks(status=status, limit=limit)
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'count': len(tasks),
        'tasks': tasks
    })


@scheduled_tasks_bp.route('/<int:task_id>', methods=['GET'])
def get_scheduled_task(task_id: int):
    manager = get_manager()
    task = manager.get_task(task_id)
    if not task:
        return jsonify({'ok': False, 'error': f'Scheduled task not found: {task_id}'}), 404
    return jsonify({'ok': True, 'mode': get_mode(), 'task': task})


@scheduled_tasks_bp.route('', methods=['POST'])
def create_scheduled_task():
    manager = get_manager()
    data = request.get_json() or {}

    name = (data.get('name') or '').strip()
    task_type = (data.get('task_type') or '').strip()
    when = (data.get('when') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'name is required'}), 400
    if task_type not in ('query', 'workflow'):
        return jsonify({'ok': False, 'error': 'task_type must be query or workflow'}), 400
    if not when:
        return jsonify({'ok': False, 'error': 'when is required'}), 400
    if task_type == 'query' and not (data.get('query') or '').strip():
        return jsonify({'ok': False, 'error': 'query is required for query tasks'}), 400
    if task_type == 'workflow' and not (data.get('workflow_id') or '').strip():
        return jsonify({'ok': False, 'error': 'workflow_id is required for workflow tasks'}), 400

    task_id = manager.create_task(
        name=name,
        task_type=task_type,
        query=(data.get('query') or '').strip() or None,
        workflow_id=(data.get('workflow_id') or '').strip() or None,
        when=when,
        timezone_name=(data.get('timezone') or '').strip() or None,
        mode=(data.get('execution_mode') or get_mode()),
        enabled=bool(data.get('enabled', True)),
        allow_overlap=bool(data.get('allow_overlap', False)),
        max_retries=int(data.get('max_retries', 1)),
        timeout_seconds=int(data.get('timeout_seconds', 300)),
        metadata=data.get('metadata'),
    )
    task = manager.get_task(task_id)
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'message': 'Scheduled task created',
        'task_id': task_id,
        'task': task
    })


@scheduled_tasks_bp.route('/<int:task_id>', methods=['PUT'])
def update_scheduled_task(task_id: int):
    manager = get_manager()
    data = request.get_json() or {}

    if not manager.get_task(task_id):
        return jsonify({'ok': False, 'error': f'Scheduled task not found: {task_id}'}), 404

    updates = {}
    if 'name' in data:
        updates['name'] = (data.get('name') or '').strip()
    if 'query' in data:
        updates['query'] = (data.get('query') or '').strip()
    if 'workflow_id' in data:
        updates['workflow_id'] = (data.get('workflow_id') or '').strip()
    if 'when' in data:
        updates['when'] = (data.get('when') or '').strip()
    if 'timezone' in data:
        updates['timezone'] = (data.get('timezone') or '').strip() or None
    if 'execution_mode' in data:
        updates['mode'] = data.get('execution_mode')
    if 'enabled' in data:
        updates['enabled'] = bool(data.get('enabled'))
    if 'allow_overlap' in data:
        updates['allow_overlap'] = bool(data.get('allow_overlap'))
    if 'max_retries' in data:
        updates['max_retries'] = int(data.get('max_retries', 1))
    if 'timeout_seconds' in data:
        updates['timeout_seconds'] = int(data.get('timeout_seconds', 300))
    if 'metadata' in data:
        updates['metadata'] = data.get('metadata')

    ok = manager.update_task(task_id, **updates)
    task = manager.get_task(task_id)
    return jsonify({
        'ok': ok,
        'mode': get_mode(),
        'message': 'Scheduled task updated' if ok else 'Update failed',
        'task': task
    })


@scheduled_tasks_bp.route('/<int:task_id>', methods=['DELETE'])
def delete_or_cancel_scheduled_task(task_id: int):
    manager = get_manager()
    permanent = request.args.get('permanent', 'false').lower() == 'true'
    ok = manager.delete_task(task_id) if permanent else manager.cancel_task(task_id)
    if not ok:
        return jsonify({'ok': False, 'error': f'Scheduled task not found: {task_id}'}), 404
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'message': 'Scheduled task deleted' if permanent else 'Scheduled task canceled'
    })


@scheduled_tasks_bp.route('/<int:task_id>/run', methods=['POST'])
def run_scheduled_task_now(task_id: int):
    manager = get_manager()
    ok = manager.run_now(task_id)
    if not ok:
        return jsonify({'ok': False, 'error': f'Scheduled task not found: {task_id}'}), 404
    task = manager.get_task(task_id)
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'message': 'Scheduled task queued to run now',
        'task': task
    })


@scheduled_tasks_bp.route('/<int:task_id>/runs', methods=['GET'])
def list_scheduled_task_runs(task_id: int):
    manager = get_manager()
    if not manager.get_task(task_id):
        return jsonify({'ok': False, 'error': f'Scheduled task not found: {task_id}'}), 404
    limit = request.args.get('limit', 20, type=int)
    runs = manager.list_runs(task_id, limit=limit)
    return jsonify({
        'ok': True,
        'mode': get_mode(),
        'count': len(runs),
        'runs': runs
    })
