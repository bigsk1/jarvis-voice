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
import subprocess
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'orchestrator'))

from config_loader import load_config, get_config_value, get_int
from service_logger import ServiceLogger
from api.managers.scheduled_task_manager import ScheduledTaskManager

PROJECT_ROOT = Path(__file__).parent.parent
NOTIFICATION_RATE_LIMIT_FILE = PROJECT_ROOT / "data" / ".scheduled_task_notification_rate_limit"


def _load_mode() -> str:
    load_config()
    provider = get_config_value('LLM_PROVIDER', 'anthropic')
    return 'local' if provider == 'ollama' else 'cloud'


def _run_query_task(mode: str, query: str) -> dict:
    if mode == 'local':
        os.environ['LLM_PROVIDER'] = 'ollama'

    from orchestrator_v2 import Orchestrator

    orch = Orchestrator(mode)
    return orch.process(query)


def _run_workflow_task(mode: str, workflow_id: str, query: str | None = None) -> dict:
    if mode == 'local':
        os.environ['LLM_PROVIDER'] = 'ollama'

    from executor import ToolExecutor
    from workflow_loader import WorkflowLoader
    from pipeline_executor import PipelineExecutor

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

    tool_executor = ToolExecutor(mode=mode)
    executor = PipelineExecutor(mode, tool_executor)

    transcript = query or workflow.get("triggers", {}).get("explicit", [f"/{workflow['id']}"])[0]
    return executor.execute(workflow, transcript)


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
            result = _run_skill_script("send_email.py", {
                "to": contact_name,
                "subject": subject,
                "body": body,
            })
            results.append({"channel": "email", "outcome": outcome, "result": result})
        else:
            results.append({"channel": "email", "outcome": outcome, "result": {"ok": False, "error": "cooldown_suppressed"}})

    if webhook_name and ((is_success and notifications.get("webhook_on_success")) or (is_failure and notifications.get("webhook_on_failure"))):
        ident = _notification_identifier(task["id"], "webhook", outcome, scheduled_for)
        if _notification_allowed(ident):
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
            results.append({"channel": "webhook", "outcome": outcome, "result": result})
        else:
            results.append({"channel": "webhook", "outcome": outcome, "result": {"ok": False, "error": "cooldown_suppressed"}})

    if is_failure and notifications.get("alert_on_failure"):
        ident = _notification_identifier(task["id"], "alert", outcome, scheduled_for)
        if _notification_allowed(ident):
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
            results.append({"channel": "alert", "outcome": outcome, "result": {"ok": True, "alert_id": alert_id}})
        else:
            results.append({"channel": "alert", "outcome": outcome, "result": {"ok": False, "error": "cooldown_suppressed"}})

    return results


def main():
    mode = _load_mode()
    manager = ScheduledTaskManager(mode=mode)
    logger = ServiceLogger('scheduled_task_runner')
    logger.log_startup(mode, {"check_interval": 60, "database": manager.db.db_path})

    project_root = Path(__file__).parent.parent
    owner = f"{mode}:{os.getpid()}"

    print("⏱️ Scheduled Task Runner Starting...")
    print(f"   Mode: {mode}")
    print(f"   Database: {manager.db.db_path}")
    print(f"   Check interval: 60 seconds")
    print()

    try:
        while True:
            due_tasks = manager.get_due_tasks(limit=20)
            logger.log_check(len(due_tasks), {"due_tasks": len(due_tasks)})

            for task in due_tasks:
                task_id = task['id']
                if not manager.acquire_lock(task_id, owner):
                    continue

                run_id = manager.create_run(task_id, metadata={"task_name": task['name']})
                started = time.time()
                status = 'success'
                error = None
                summary = None
                result = {}
                scheduled_for = task.get('next_run_at')

                try:
                    payload = json.loads(task.get('task_payload') or "{}")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Running task {task_id}: {task['name']}")

                    if task['task_type'] == 'query':
                        result = _run_query_task(task['mode'], payload.get('query', ''))
                    elif task['task_type'] == 'workflow':
                        result = _run_workflow_task(task['mode'], task['task_target'], payload.get('query'))
                    else:
                        raise ValueError(f"Unsupported task_type: {task['task_type']}")

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
                next_run = manager.calculate_followup_next_run(task, reference_utc=task.get('next_run_at'))
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
                    provider=os.environ.get('LLM_PROVIDER'),
                    model=os.environ.get('LLM_MODEL'),
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
