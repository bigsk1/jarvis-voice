#!/usr/bin/env python3
"""
Tool Name: schedule_task
Create, list, update, or cancel scheduled Jarvis tasks.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from api.managers.scheduled_task_manager import ScheduledTaskManager


def _summarize_task(task: dict) -> str:
    payload = json.loads(task.get('task_payload') or '{}')
    summary = payload.get('schedule_summary') or task.get('schedule_type')
    if task.get('task_type') == 'workflow':
        target = task.get('task_target') or payload.get('workflow_id') or 'workflow'
    else:
        target = payload.get('query', '')[:80]
    return f"[{task['id']}] {task['name']} ({task['task_type']}) -> {target} | next: {task.get('next_run_at') or 'n/a'} | {summary}"


def main():
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
        action = (args.get('action') or '').strip().lower()
        if not action:
            raise ValueError("action is required")

        manager = ScheduledTaskManager(mode=args.get('mode'))

        if action == 'create':
            name = args.get('name')
            task_type = args.get('task_type')
            when = args.get('when')
            if not name or not task_type or not when:
                raise ValueError("create requires name, task_type, and when")

            task_id = manager.create_task(
                name=name,
                task_type=task_type,
                query=args.get('query'),
                workflow_id=args.get('workflow_id'),
                when=when,
                timezone_name=args.get('timezone'),
                mode=args.get('mode', 'cloud'),
                enabled=args.get('enabled', True),
                allow_overlap=args.get('allow_overlap', False),
                max_retries=args.get('max_retries', 1),
                timeout_seconds=args.get('timeout_seconds', 300),
                metadata=args.get('metadata'),
            )
            task = manager.get_task(task_id)
            speech = f"Scheduled task created: {task['name']}. Next run {task.get('next_run_at')}."
            print(json.dumps({"ok": True, "speech": speech, "data": {"task": task, "task_id": task_id}}))
            return

        if action == 'list':
            tasks = manager.list_tasks(status=args.get('status', 'all'), limit=args.get('limit', 20))
            if not tasks:
                speech = "No scheduled tasks found."
            elif len(tasks) == 1:
                speech = f"Found 1 scheduled task: {tasks[0]['name']}."
            else:
                speech = f"Found {len(tasks)} scheduled tasks. Next: {tasks[0]['name']}."
            print(json.dumps({
                "ok": True,
                "speech": speech,
                "data": {"tasks": tasks, "count": len(tasks), "summary_lines": [_summarize_task(t) for t in tasks]}
            }))
            return

        if action == 'update':
            task_id = args.get('task_id')
            if not task_id:
                raise ValueError("update requires task_id")
            updates = {k: v for k, v in args.items() if k in {
                'name', 'query', 'workflow_id', 'when', 'timezone', 'mode',
                'enabled', 'allow_overlap', 'max_retries', 'timeout_seconds', 'metadata'
            } and v is not None}
            ok = manager.update_task(int(task_id), **updates)
            if not ok:
                print(json.dumps({"ok": False, "speech": f"Scheduled task {task_id} not found.", "error": "not_found"}))
                sys.exit(1)
            task = manager.get_task(int(task_id))
            print(json.dumps({
                "ok": True,
                "speech": f"Scheduled task {task_id} updated.",
                "data": {"task": task, "task_id": int(task_id)}
            }))
            return

        if action == 'cancel':
            task_id = args.get('task_id')
            if not task_id:
                raise ValueError("cancel requires task_id")
            ok = manager.cancel_task(int(task_id))
            if not ok:
                print(json.dumps({"ok": False, "speech": f"Scheduled task {task_id} not found.", "error": "not_found"}))
                sys.exit(1)
            print(json.dumps({
                "ok": True,
                "speech": f"Scheduled task {task_id} canceled.",
                "data": {"task_id": int(task_id), "canceled": True}
            }))
            return

        if action == 'delete':
            task_id = args.get('task_id')
            if not task_id:
                raise ValueError("delete requires task_id")
            ok = manager.delete_task(int(task_id))
            if not ok:
                print(json.dumps({"ok": False, "speech": f"Scheduled task {task_id} not found.", "error": "not_found"}))
                sys.exit(1)
            print(json.dumps({
                "ok": True,
                "speech": f"Scheduled task {task_id} deleted.",
                "data": {"task_id": int(task_id), "deleted": True}
            }))
            return

        if action == 'run_now':
            task_id = args.get('task_id')
            if not task_id:
                raise ValueError("run_now requires task_id")
            ok = manager.run_now(int(task_id))
            if not ok:
                print(json.dumps({"ok": False, "speech": f"Scheduled task {task_id} not found.", "error": "not_found"}))
                sys.exit(1)
            task = manager.get_task(int(task_id))
            print(json.dumps({
                "ok": True,
                "speech": f"Scheduled task {task_id} queued to run now.",
                "data": {"task": task, "task_id": int(task_id), "queued": True}
            }))
            return

        if action == 'list_runs':
            task_id = args.get('task_id')
            if not task_id:
                raise ValueError("list_runs requires task_id")
            runs = manager.list_runs(int(task_id), limit=args.get('limit', 10))
            speech = f"Found {len(runs)} recent run(s) for scheduled task {task_id}."
            print(json.dumps({
                "ok": True,
                "speech": speech,
                "data": {"task_id": int(task_id), "runs": runs, "count": len(runs)}
            }))
            return

        raise ValueError("action must be one of: create, list, update, cancel, delete, run_now, list_runs")

    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to manage scheduled tasks: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
