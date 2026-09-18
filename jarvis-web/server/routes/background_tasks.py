"""Operator control on the Web origin. No FastAPI routes or cookie-only writes."""

import os
import sqlite3
from functools import wraps

from flask import Blueprint, current_app, jsonify, request

from lib.background_tasks import TaskError

from ..services.conversation_store import ConversationBusyError

background_bp = Blueprint("background_tasks", __name__)


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
            tasks.store.request_cancel(job_id, revision, supported_adapters=LOCAL_ADAPTERS)
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
