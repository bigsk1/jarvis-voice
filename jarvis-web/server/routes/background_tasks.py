"""Operator control on the Web origin. No FastAPI routes or cookie-only writes."""

import json
import logging
import os
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import uuid
from functools import wraps
from pathlib import Path

from filelock import FileLock, Timeout
from flask import Blueprint, current_app, jsonify, request

from lib.background_tasks import TaskError

from ..services.conversation_store import ConversationBusyError

background_bp = Blueprint("background_tasks", __name__)
logger = logging.getLogger(__name__)


def _browser_setup_paths(tasks):
    return (Path(str(tasks.store.path) + '.browser-use.setup.json'),
            str(tasks.store.path) + '.browser-use.setup.lock')


def _write_browser_setup_state(tasks, state, message=''):
    path, _ = _browser_setup_paths(tasks)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump({'state': state, 'message': message[:400], 'updated_at': time.time()}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _browser_setup_status(tasks):
    path, lock_path = _browser_setup_paths(tasks)
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ValueError('Invalid setup state permissions')
        value = json.loads(path.read_text())
        if value.get('state') not in {'running', 'ready', 'failed'}:
            raise ValueError('Invalid setup state')
    except FileNotFoundError:
        return {'state': 'idle', 'message': ''}
    except (OSError, ValueError, TypeError, AttributeError):
        return {'state': 'failed', 'message': 'Setup status is unavailable; retry setup.'}
    if value['state'] == 'running':
        try:
            with FileLock(lock_path, timeout=0):
                return {'state': 'failed', 'message': 'Setup was interrupted; retry it from Settings → Tools.'}
        except Timeout:
            pass
    return {'state': value['state'], 'message': str(value.get('message') or '')[:400]}


def _finish_browser_setup(tasks, lock):
    from browser_agent import BrowserPreflightError, install_runtime

    from lib.webhook_integrations.browser import activate

    try:
        install_runtime()
        activate(tasks.store,
                 os.environ.get('JARVIS_TASK_CALLBACK_BASE', 'http://127.0.0.1:8880'),
                 os.environ.get('JARVIS_BROWSER_USE_SUBMIT_URL', 'http://127.0.0.1:8790/submit'))
        ensure_task_worker(tasks)
        browser_command('start', tasks)
        _write_browser_setup_state(tasks, 'ready', 'Browser Use is configured and enabled.')
    except Exception as exc:
        logger.warning('Browser Use setup failed error_type=%s', type(exc).__name__)
        message = str(exc)[:400] if isinstance(exc, (TaskError, BrowserPreflightError)) else (
            'Browser Use setup failed; check the Web logs and retry.')
        _write_browser_setup_state(tasks, 'failed', message)
    finally:
        lock.release()


def allowed_origin():
    origin = request.headers.get("Origin")
    if not origin:
        return True  # Non-browser CLI still needs explicit bearer authentication.
    allowed = {
        request.host_url.rstrip("/"),
        *current_app.config.get("BACKGROUND_ALLOWED_ORIGINS", []),
    }
    # TLS can terminate at Tailscale/a reverse proxy while Flask sees HTTP.
    # Trust explicit deployment configuration, never arbitrary forwarded headers.
    allowed.update(
        value.strip().rstrip("/")
        for value in os.environ.get("JARVIS_WEB_BACKGROUND_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    )
    return origin.rstrip("/") in allowed


def operator_required(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        from webui_auth import is_auth_enabled, verify_token

        header = request.headers.get("Authorization", "")
        if (
            not is_auth_enabled()
            or not header.startswith("Bearer ")
            or not verify_token(header[7:])
        ):
            return jsonify({"error": "Configured Web operator authentication is required"}), 401
        if not allowed_origin():
            return jsonify({"error": "Web origin is not allowed"}), 403
        try:
            return method(*args, **kwargs)
        except (TaskError, ConversationBusyError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 409
        except (OSError, sqlite3.Error):
            return jsonify({"error": "Background task storage is unavailable"}), 503

    return wrapped


def service():
    return current_app.extensions["jarvis_background_tasks"]


def browser_details(tasks):
    from lib.webhook_integrations.browser import managed_status

    details = managed_status(tasks.store)
    details['setup'] = _browser_setup_status(tasks)
    healthy = {name for worker in tasks.store.healthy_workers() for name in worker['adapters']}
    details['worker_ready'] = 'http_callback_v1' in healthy
    settings = tasks.store.settings()
    details['selected'] = settings['background_enabled'] and 'browser_use' in settings['background_tools']
    try:
        managed = subprocess.run(['tmux', 'has-session', '-t', 'jarvis-browser-use'],
                                 capture_output=True, timeout=2).returncode == 0
    except (OSError, subprocess.SubprocessError):
        managed = False
    details['managed_by_tmux'] = managed
    details['operational'] = all(details[name] for name in (
        'configured', 'receiver_enabled', 'source_enabled', 'source_validated',
        'credential_ready', 'service_ready', 'worker_ready'))
    details['ready'] = details['operational'] and details['selected']
    return details


def browser_command(action, tasks):
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(root, 'bin', 'jarvis-browser-use'), action, '--tmux',
             '--db', str(tasks.store.path)], capture_output=True, text=True, timeout=75,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TaskError('Browser Use service command failed') from exc
    if result.returncode:
        raise TaskError((result.stdout or result.stderr or 'Browser Use service command failed').strip())


def task_worker_command(action, tasks):
    if action not in {'start', 'restart'}:
        raise TaskError('Unsupported background task worker action')
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(root, 'bin', 'jarvis-task-worker'), action, '--tmux',
             '--db', str(tasks.store.path)], capture_output=True, text=True, timeout=25,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TaskError('Background task worker could not start') from exc
    if result.returncode:
        raise TaskError((result.stdout or result.stderr or 'Background task worker could not start').strip())


def ensure_task_worker(tasks):
    """Start a current worker, or safely replace an idle pre-callback worker."""
    workers = tasks.store.healthy_workers()
    adapters = {name for worker in workers for name in worker['adapters']}
    action = 'start'
    if workers and 'http_callback_v1' not in adapters:
        counts = tasks.store.counts()
        if counts['running'] or counts['reserved']:
            raise TaskError('The existing task worker must be upgraded, but work is still active or needs attention. '
                            'Finish or reconcile it, then retry Browser Use setup.')
        action = 'restart'
    task_worker_command(action, tasks)


@background_bp.get("/api/background-tasks")
@operator_required
def status():
    tasks = service()
    mode = request.args.get("mode", "cloud")
    if mode not in {"cloud", "local"}:
        raise ValueError("Invalid mode")
    tasks.start()
    from lib.background_tasks.admission import BackgroundAdmissionService

    from ..config import get_web_setting

    supported = []
    if tasks.adapters:
        from config_loader import config_scope

        with config_scope(mode):
            supported = BackgroundAdmissionService(tasks.store, adapters=tasks.adapters).supported(
                tasks.get_registry(mode), get_web_setting("tools.blocked", [])
            )
    workers = tasks.store.healthy_workers()
    healthy_adapters = {name for worker in workers for name in worker["adapters"]}
    from lib.background_tasks.local_contract import REMOTE_ADAPTER
    tool_details = {name: {"remote_work": adapter == REMOTE_ADAPTER,
                          "worker_ready": adapter in healthy_adapters}
                    for name, adapter in tasks.adapters.items()}
    if 'browser_use' in tool_details:
        tool_details['browser_use']['browser_use'] = browser_details(tasks)
    return jsonify(
        {
            "settings": tasks.store.settings(),
            "coordinator_ready": tasks.ready(),
            "coordinator_unavailable_reason": tasks.unavailable_reason,
            "counts": tasks.store.counts(),
            "workers": workers,
            "tools": supported,
            "configured_tools": sorted(tasks.adapters),
            "tool_details": tool_details,
            "worker_ready": bool(supported)
            and any(tool_details[name]['worker_ready'] for name in supported),
        }
    )


@background_bp.post('/api/background-tasks/tools/browser_use/actions')
@operator_required
def browser_action():
    tasks = service()
    body = request.get_json(silent=True)
    action = body.get('action') if isinstance(body, dict) and set(body) == {'action'} else None
    if action == 'setup':
        _, lock_path = _browser_setup_paths(tasks)
        setup_lock = FileLock(lock_path, timeout=0, thread_local=False)
        try:
            setup_lock.acquire()
        except Timeout:
            # Join the existing attempt. A second click never starts another pull.
            return jsonify({'browser_use': browser_details(tasks)}), 202
        try:
            _write_browser_setup_state(tasks, 'running', 'Checking or downloading the pinned browser image…')
            worker = threading.Thread(target=_finish_browser_setup, args=(tasks, setup_lock),
                                      daemon=True, name='browser-use-setup')
            worker.start()
        except Exception:
            setup_lock.release()
            _write_browser_setup_state(tasks, 'failed', 'Browser Use setup could not start; retry it.')
            raise
        return jsonify({'browser_use': browser_details(tasks)}), 202
    elif action in {'start', 'restart', 'stop'}:
        browser_command(action, tasks)
    elif action == 'test':
        from lib.webhook_integrations.browser import read_config
        from lib.webhook_integrations.service import IntegrationService

        IntegrationService(tasks.store).test_source(read_config(tasks.store)['source_id'])
    else:
        raise ValueError('Expected setup, start, restart, stop, or test')
    # Newly provisioned adapters are discovered by the existing worker heartbeat.
    for _ in range(20 if action in {'setup', 'start', 'restart'} else 1):
        details = browser_details(tasks)
        if details['ready'] or action in {'stop', 'test'}:
            break
        time.sleep(.1)
    return jsonify({'browser_use': details})


@background_bp.patch("/api/background-tasks")
@operator_required
def settings():
    payload = request.get_json(silent=True)
    allowed = {'background_enabled', 'background_tools', 'max_running', 'max_outstanding', 'max_queued', 'max_per_adapter', 'result_retention_days'}
    if not isinstance(payload, dict) or not payload or set(payload) - allowed:
        raise ValueError("Expected background admission or capacity settings")
    tasks = service()
    enabled = payload.get("background_enabled")
    if enabled is not None and type(enabled) is not bool:
        raise ValueError("background_enabled must be boolean")
    selected = payload.get('background_tools')
    if selected is not None and (not isinstance(selected, list)
            or any(not isinstance(name, str) or name not in tasks.adapters for name in selected)):
        raise ValueError("Only reviewed background tools can be enabled")
    ready = tasks.start(create=True)
    if enabled and not ready:
        raise ValueError(tasks.unavailable_reason or "Background coordinator is unavailable")
    return jsonify({"settings": tasks.store.configure(**payload)})


@background_bp.get("/api/background-jobs")
@operator_required
def jobs():
    tasks = service()
    conversation_id = request.args.get("conversation_id")
    page = tasks.store.list_jobs(conversation_id=conversation_id, tool=request.args.get('tool'),
                                 state=request.args.get('state'), offset=int(request.args.get('offset', 0)),
                                 limit=int(request.args.get('limit', 25)))
    page['jobs'] = [tasks.card(job) for job in page['jobs']]
    page['counts'] = tasks.store.counts()
    return jsonify(page)


@background_bp.get('/api/background-jobs/<job_id>')
@operator_required
def detail(job_id):
    return jsonify({'job': service().store.job_detail(job_id)})


@background_bp.post('/api/background-jobs/<job_id>/actions')
@operator_required
def job_action(job_id):
    tasks = service()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError('Expected a job action')
    action, revision = payload.get('action'), payload.get('revision')
    job = tasks.store.get(job_id)
    if not job:
        raise ValueError('Job not found')
    # Serialize suppression with JSON projection, including its cross-store fence.
    with tasks.handler.runs.conversation_lock(job['conversation_id']):
        if action == 'cancel':
            from lib.background_tasks.local_contract import LOCAL_ADAPTERS
            from lib.webhook_integrations.contracts import ADAPTER as CALLBACK_ADAPTER

            adapters = set(LOCAL_ADAPTERS)
            if job['admission']['tool'] == 'browser_use' and job['adapter'] == CALLBACK_ADAPTER:
                adapters.add(CALLBACK_ADAPTER)
            tasks.store.request_cancel(job_id, revision, supported_adapters=adapters)
        elif action == 'reconcile':
            tasks.store.reconcile_job(job_id, revision, disposition=payload.get('disposition'),
                                     evidence=payload.get('evidence'), stopped=payload.get('stopped'))
        elif action in {'retry_delivery', 'suppress_delivery'}:
            tasks.store.control_delivery(job_id, revision, action)
        elif action == 'read':
            tasks.store.mark_read(job_id)
        else:
            raise ValueError('Unknown job action')
    updated = tasks.store.job_detail(job_id)
    if action != 'read':
        tasks.store.events.emit('operator_action', component='operator', job=updated, action=action)
    return jsonify({'job': updated})


@background_bp.post("/api/background-tasks/conversations/<conversation_id>/dispose")
@operator_required
def dispose(conversation_id):
    payload = request.get_json(silent=True) or {}
    if (
        payload.get("action") not in {"clear", "delete"}
        or type(payload.get("generation")) is not int
    ):
        raise ValueError("Expected clear/delete and the current generation")
    tasks = service()
    with tasks.handler.runs.conversation_lock(conversation_id):
        tasks.conversations.dispose_background(
            conversation_id, payload["action"], payload["generation"]
        )
    tasks.store.events.emit('conversation_disposed', component='operator',
                           conversation_id=conversation_id, action=payload['action'], generation=payload['generation'])
    return jsonify({"ok": True})


@background_bp.get('/api/background-tasks/retention')
@operator_required
def retention_preview():
    return jsonify({'eligible_in_next_batch': service().store.archive_results(dry_run=True), 'batch_limit':100})
