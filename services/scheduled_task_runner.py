#!/usr/bin/env python3
"""
Scheduled Task Runner
Polls for due scheduled tasks and executes them.
"""

import os
import sys
import time
import json
import hashlib
import multiprocessing
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'orchestrator'))

from config_loader import (
    config_scope,
    get_active_config_mode,
    get_config_value,
    get_int,
    load_config,
)
from service_logger import ServiceLogger
from api.managers.scheduled_task_manager import ScheduledTaskManager

PROJECT_ROOT = Path(__file__).parent.parent
NOTIFICATION_RATE_LIMIT_FILE = PROJECT_ROOT / "data" / ".scheduled_task_notification_rate_limit"


class ScheduledTaskTimeoutError(TimeoutError):
    """Raised when a scheduled execution exceeds its configured deadline."""


def _load_mode() -> str:
    load_config()
    return get_active_config_mode()


def _lock_owner_process_is_alive(owner: str, mode: str, current_owner: str) -> bool:
    """Return True unless a same-mode runner owner is demonstrably gone."""
    if owner == current_owner:
        return True
    parts = str(owner or "").split(":", 2)
    if len(parts) < 2 or parts[0] != mode:
        return True
    try:
        pid = int(parts[1])
    except (TypeError, ValueError):
        return True

    # A lock with our PID but a different/legacy session token predates this
    # runner instance (notably after a container PID namespace is recreated).
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _recover_abandoned_locks(
    manager: ScheduledTaskManager,
    mode: str,
    current_owner: str,
) -> list[int]:
    """Release locks left by runner processes that no longer exist."""
    recovered = []
    for task in manager.list_locked_tasks():
        owner = str(task.get("lock_owner") or "")
        if _lock_owner_process_is_alive(owner, mode, current_owner):
            continue
        reason = f"Recovered abandoned scheduled-task lock from runner {owner}"
        if manager.release_abandoned_lock(task["id"], owner, reason=reason):
            recovered.append(task["id"])
    return recovered


def _run_query_task(mode: str, query: str) -> dict:
    with config_scope(mode):
        from orchestrator_v2 import Orchestrator

        orch = Orchestrator(mode)
        return orch.process(query)


def _run_workflow_task(mode: str, workflow_id: str, query: str | None = None) -> dict:
    with config_scope(mode):
        from executor import ToolExecutor
        from workflow_loader import WorkflowLoader
        from pipeline_executor import PipelineExecutor
        from tool_schema import get_tool_registry
        from workflow_availability import (
            check_workflow_registry_availability,
            workflow_unavailable_message,
        )

        loader = WorkflowLoader(explicit_only=True)
        workflow = loader.get_workflow(workflow_id)
        if not workflow:
            normalized = workflow_id if workflow_id.startswith('/') else f"/{workflow_id}"
            for candidate in loader.workflows.values():
                explicit = candidate.get("triggers", {}).get("explicit", [])
                if workflow_id in explicit or normalized in explicit:
                    workflow = candidate
                    break
        if not workflow:
            raise ValueError(f"Workflow '{workflow_id}' not found")

        registry = get_tool_registry(mode=mode)
        availability = check_workflow_registry_availability(workflow, registry)
        if not availability["available"]:
            message = workflow_unavailable_message(workflow, availability)
            return {
                "ok": False,
                "speech": message,
                "error": message,
                "data": {
                    "workflow_id": workflow.get("id"),
                    "availability": availability,
                    "results": [],
                },
                "tools_used": [],
                "steps_completed": 0,
            }

        tool_executor = ToolExecutor(mode=mode, registry=registry)
        executor = PipelineExecutor(mode, tool_executor)

        trigger = workflow.get("triggers", {}).get("explicit", [f"/{workflow['id']}"])[0]
        transcript = f"{trigger} {query.strip()}" if query and query.strip() else trigger
        return executor.execute(workflow, transcript)


def _execute_scheduled_task(task: dict, payload: dict) -> dict:
    """Dispatch one scheduled task inside its isolated worker process."""
    if task['task_type'] == 'query':
        return _run_query_task(task['mode'], payload.get('query', ''))
    if task['task_type'] == 'workflow':
        return _run_workflow_task(task['mode'], task['task_target'], payload.get('query'))
    raise ValueError(f"Unsupported task_type: {task['task_type']}")


def _task_process_entry(send_conn, target, args):
    """Execute one picklable callable and return a serializable outcome."""
    if os.name == 'posix':
        os.setsid()
    try:
        send_conn.send(("result", target(*args)))
    except BaseException as exc:
        try:
            send_conn.send(("error", f"{type(exc).__name__}: {exc}"))
        except Exception:
            pass
    finally:
        send_conn.close()


def _stop_task_process(process) -> None:
    """Stop a timed-out task process and any subprocesses it started."""
    if not process.is_alive():
        process.join(timeout=1)
        return
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    else:
        process.terminate()
    process.join(timeout=2)
    if process.is_alive():
        if os.name == 'posix':
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.join(timeout=2)


def _run_with_timeout(target, args: tuple, timeout_seconds: int):
    """Run a callable in an isolated process and enforce a hard deadline."""
    timeout_seconds = max(1, int(timeout_seconds))
    context = multiprocessing.get_context('spawn')
    receive_conn, send_conn = context.Pipe(duplex=False)
    process = context.Process(
        target=_task_process_entry,
        args=(send_conn, target, args),
        name="jarvis-scheduled-task",
    )
    process.start()
    send_conn.close()
    deadline = time.monotonic() + timeout_seconds
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_task_process(process)
                raise ScheduledTaskTimeoutError(
                    f"Scheduled task timed out after {timeout_seconds} seconds"
                )
            if receive_conn.poll(min(0.1, remaining)):
                outcome, value = receive_conn.recv()
                process.join(timeout=1)
                if process.is_alive():
                    _stop_task_process(process)
                if outcome == "error":
                    raise RuntimeError(value)
                return value
            if not process.is_alive():
                process.join(timeout=1)
                raise RuntimeError(
                    f"Scheduled task worker exited without a result (exit {process.exitcode})"
                )
    finally:
        receive_conn.close()


def _execution_identity(mode: str) -> tuple[str | None, str | None]:
    """Resolve truthful provider/model metadata inside a task's config scope."""
    with config_scope(mode):
        provider = (get_config_value('LLM_PROVIDER', '') or '').strip().lower() or None
        if provider == 'ollama':
            from ollama_utils import resolve_ollama_model

            return provider, resolve_ollama_model(mode)

        model_keys = {
            'openai': 'OPENAI_MODEL',
            'anthropic': 'ANTHROPIC_MODEL',
            'xai': 'XAI_MODEL',
        }
        model_key = model_keys.get(provider)
        model = (get_config_value(model_key, '') or '').strip() if model_key else ''
        return provider, (model or None)


def _parse_json_field(value):
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except Exception:
        return {}


def _get_notification_settings(task: dict) -> dict:
    metadata = _parse_json_field(task.get("metadata"))
    notifications = metadata.get("notifications", {})
    if not isinstance(notifications, dict):
        return {}
    return notifications


def _notification_identifier(task_id: int, channel: str, outcome: str, scheduled_for: str | None) -> str:
    slot = scheduled_for or "manual"
    return f"{task_id}:{channel}:{outcome}:{slot}"


def _notification_allowed(identifier: str) -> bool:
    cooldown = get_int("SCHEDULED_TASK_NOTIFICATION_COOLDOWN_SECONDS", 900)
    digest = hashlib.md5(identifier.encode("utf-8")).hexdigest()[:12]
    now = time.time()

    try:
        if NOTIFICATION_RATE_LIMIT_FILE.exists():
            limits = json.loads(NOTIFICATION_RATE_LIMIT_FILE.read_text(encoding="utf-8"))
        else:
            limits = {}
    except Exception:
        limits = {}

    last_sent = float(limits.get(digest, 0) or 0)
    if cooldown > 0 and now - last_sent < cooldown:
        return False

    limits[digest] = now
    try:
        NOTIFICATION_RATE_LIMIT_FILE.write_text(json.dumps(limits), encoding="utf-8")
    except Exception:
        pass
    return True


def _run_skill_script(script_name: str, payload: dict) -> dict:
    script_path = PROJECT_ROOT / "skills" / script_name
    proc = subprocess.run(
        [sys.executable, str(script_path), json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=60
    )

    stdout = (proc.stdout or "").strip()
    if stdout:
        try:
            return json.loads(stdout)
        except Exception:
            return {"ok": False, "error": f"Invalid JSON from {script_name}", "raw": stdout}

    return {
        "ok": False,
        "error": (proc.stderr or f"{script_name} returned no output").strip()
    }


def _build_notification_body(task: dict, *, status: str, summary: str | None, error: str | None,
                             scheduled_for: str | None, next_run: str | None) -> str:
    payload = _parse_json_field(task.get("task_payload"))
    lines = [
        f"Scheduled task: {task['name']}",
        f"Status: {status}",
        f"Task type: {task['task_type']}",
        f"Mode: {task['mode']}",
    ]
    if task['task_type'] == 'workflow':
        lines.append(f"Workflow: {task.get('task_target') or payload.get('workflow_id') or 'unknown'}")
    else:
        lines.append(f"Query: {payload.get('query', '')}")
    if scheduled_for:
        lines.append(f"Scheduled for: {scheduled_for}")
    if summary:
        lines.append(f"Summary: {summary}")
    if error:
        lines.append(f"Error: {error}")
    if next_run:
        lines.append(f"Next run: {next_run}")
    return "\n".join(lines)


def _maybe_send_notifications(task: dict, *, status: str, summary: str | None, error: str | None,
                              scheduled_for: str | None, next_run: str | None) -> list[dict]:
    notifications = _get_notification_settings(task)
    if not notifications:
        return []

    results: list[dict] = []
    is_success = status == "success"
    is_failure = status == "failure"
    if not (is_success or is_failure):
        return results

    outcome = "success" if is_success else "failure"
    body = _build_notification_body(
        task,
        status=status,
        summary=summary,
        error=error,
        scheduled_for=scheduled_for,
        next_run=next_run,
    )

    contact_name = (notifications.get("contact_name") or "").strip()
    webhook_name = (notifications.get("webhook_name") or "").strip()

    if contact_name and ((is_success and notifications.get("email_on_success")) or (is_failure and notifications.get("email_on_failure"))):
        ident = _notification_identifier(task["id"], "email", outcome, scheduled_for)
        if _notification_allowed(ident):
            subject = f"Jarvis scheduled task {outcome}: {task['name']}"
            try:
                result = _run_skill_script("send_email.py", {
                    "to": contact_name,
                    "subject": subject,
                    "body": body,
                })
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            results.append({"channel": "email", "outcome": outcome, "result": result})
        else:
            results.append({"channel": "email", "outcome": outcome, "result": {"ok": False, "error": "cooldown_suppressed"}})

    if webhook_name and ((is_success and notifications.get("webhook_on_success")) or (is_failure and notifications.get("webhook_on_failure"))):
        ident = _notification_identifier(task["id"], "webhook", outcome, scheduled_for)
        if _notification_allowed(ident):
            try:
                result = _run_skill_script("send_webhook.py", {
                    "webhook": webhook_name,
                    "data": {
                        "task_id": task["id"],
                        "task_name": task["name"],
                        "status": status,
                        "mode": task["mode"],
                        "task_type": task["task_type"],
                        "scheduled_for": scheduled_for,
                        "next_run_at": next_run,
                        "summary": summary,
                        "error": error,
                    }
                })
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            results.append({"channel": "webhook", "outcome": outcome, "result": result})
        else:
            results.append({"channel": "webhook", "outcome": outcome, "result": {"ok": False, "error": "cooldown_suppressed"}})

    if is_failure and notifications.get("alert_on_failure"):
        ident = _notification_identifier(task["id"], "alert", outcome, scheduled_for)
        if _notification_allowed(ident):
            try:
                from api.managers.alert_manager import AlertManager
                alert_manager = AlertManager(mode=task["mode"])
                description = body
                alert_id = alert_manager.create_alert(
                    title=f"Scheduled task failed: {task['name']}",
                    source="scheduled_task_runner",
                    description=description,
                    severity="medium",
                    metadata={
                        "task_id": task["id"],
                        "task_name": task["name"],
                        "scheduled_for": scheduled_for,
                        "mode": task["mode"],
                        "dedupe_key": f"scheduled_task_failure:{task['id']}:{scheduled_for or 'manual'}",
                    },
                    speak_immediately=False,
                )
                result = {"ok": True, "alert_id": alert_id}
            except Exception as exc:
                result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            results.append({"channel": "alert", "outcome": outcome, "result": result})
        else:
            results.append({"channel": "alert", "outcome": outcome, "result": {"ok": False, "error": "cooldown_suppressed"}})

    return results


def main():
    mode = _load_mode()
    manager = ScheduledTaskManager(mode=mode)
    logger = ServiceLogger('scheduled_task_runner')
    missed_grace_seconds = max(0, get_int("SCHEDULED_TASK_MISSED_GRACE_SECONDS", 300))
    logger.log_startup(mode, {
        "check_interval": 60,
        "database": manager.db.db_path,
        "missed_grace_seconds": missed_grace_seconds,
    })

    project_root = Path(__file__).parent.parent
    owner = f"{mode}:{os.getpid()}:{uuid4().hex[:12]}"
    recovered_locks = _recover_abandoned_locks(manager, mode, owner)
    if recovered_locks:
        logger.log_action("recover_abandoned_locks", {
            "task_ids": recovered_locks,
            "count": len(recovered_locks),
        })

    print("⏱️ Scheduled Task Runner Starting...")
    print(f"   Mode: {mode}")
    print(f"   Database: {manager.db.db_path}")
    print(f"   Check interval: 60 seconds")
    print(f"   Missed occurrence grace: {missed_grace_seconds} seconds")
    if recovered_locks:
        print(f"   Recovered abandoned task locks: {', '.join(map(str, recovered_locks))}")
    print()

    try:
        while True:
            skipped_tasks = manager.skip_missed_tasks(
                grace_seconds=missed_grace_seconds,
            )
            if skipped_tasks:
                logger.log_action("skip_missed_tasks", {
                    "count": len(skipped_tasks),
                    "tasks": skipped_tasks,
                })
            due_tasks = manager.get_due_tasks(limit=20)
            logger.log_check(len(due_tasks), {"due_tasks": len(due_tasks)})

            for task in due_tasks:
                task_id = task['id']
                manual_run_once = manager.is_manual_run_once(task)
                if not manager.acquire_lock(task_id, owner):
                    continue

                run_id = manager.create_run(task_id, metadata={"task_name": task['name']})
                started = time.time()
                status = 'success'
                error = None
                summary = None
                result = {}
                execution_provider = None
                execution_model = None
                scheduled_for = task.get('next_run_at')

                try:
                    payload = json.loads(task.get('task_payload') or "{}")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Running task {task_id}: {task['name']}")

                    timeout_seconds = max(1, int(task.get('timeout_seconds') or 300))
                    result = _run_with_timeout(
                        _execute_scheduled_task,
                        (task, payload),
                        timeout_seconds,
                    )

                    execution_provider, execution_model = _execution_identity(task['mode'])

                    status = 'success' if result.get('ok', True) else 'failure'
                    error = result.get('error')
                    summary = result.get('speech') or result.get('raw_llm_response') or task['name']
                except Exception as e:
                    status = 'failure'
                    error = str(e)
                    summary = f"Scheduled task failed: {e}"
                    result = {"ok": False, "error": error}
                    logger.log_error(f"Scheduled task {task_id} failed", {"task_id": task_id, "error": error})

                duration_ms = round((time.time() - started) * 1000, 2)
                next_run = manager.resolve_followup_next_run(
                    task,
                    reference_utc=task.get('next_run_at'),
                    manual_run_once=manual_run_once,
                )
                notification_results = _maybe_send_notifications(
                    task,
                    status=status,
                    summary=summary,
                    error=error,
                    scheduled_for=scheduled_for,
                    next_run=next_run
                )
                for item in notification_results:
                    if not item.get("result", {}).get("ok"):
                        logger.log_error("Scheduled task notification issue", {
                            "task_id": task_id,
                            "channel": item.get("channel"),
                            "outcome": item.get("outcome"),
                            "error": item.get("result", {}).get("error"),
                        })
                manager.finish_run(
                    run_id,
                    status=status,
                    mode=task['mode'],
                    provider=execution_provider,
                    model=execution_model,
                    workflow_id=task.get('task_target') if task['task_type'] == 'workflow' else None,
                    tools_used=result.get('tools_used', []),
                    speech=result.get('speech'),
                    raw_llm_response=result.get('raw_llm_response'),
                    result_data=result.get('data'),
                    error=error,
                    duration_ms=duration_ms,
                    completion_guard_applied=False,
                    feedback_collected=False,
                    metadata={"task_name": task['name'], "notifications": notification_results}
                )
                manager.release_lock_and_update(
                    task_id,
                    status=status,
                    error=error,
                    duration_ms=duration_ms,
                    summary=summary[:500] if summary else None,
                    next_run_at=next_run
                )
                logger.log_action("run_task", {
                    "task_id": task_id,
                    "name": task['name'],
                    "status": status,
                    "next_run_at": next_run
                }, success=(status == 'success'))

            time.sleep(60)

    except KeyboardInterrupt:
        logger.log_shutdown({"reason": "keyboard_interrupt"})


if __name__ == "__main__":
    main()
