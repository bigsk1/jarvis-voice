#!/usr/bin/env python3
"""
Scheduled Task Runner
Polls for due scheduled tasks and executes them.
"""

import os
import sys
import time
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'lib'))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / 'orchestrator'))

from config_loader import load_config, get_config_value
from service_logger import ServiceLogger
from api.managers.scheduled_task_manager import ScheduledTaskManager


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

    from workflow_loader import WorkflowLoader
    from pipeline_executor import PipelineExecutor

    loader = WorkflowLoader(explicit_only=True)
    workflow = loader.get_workflow(workflow_id)
    if not workflow:
        raise ValueError(f"Workflow '{workflow_id}' not found")

    executor = PipelineExecutor(mode=mode)
    return executor.execute(workflow, query or workflow_id)


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
                    metadata={"task_name": task['name']}
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
