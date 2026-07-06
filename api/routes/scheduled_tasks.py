"""Scheduled task API endpoints"""

from fastapi import APIRouter, HTTPException, Query
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.managers.scheduled_task_manager import ScheduledTaskManager
from api.models.scheduled_task import (
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskListStatus,
    ScheduledTaskResponse,
    ScheduledTaskRun,
    ScheduledTaskUpdate,
)

router = APIRouter(prefix="/api/scheduled-tasks", tags=["scheduled-tasks"])

scheduled_task_manager = ScheduledTaskManager()


@router.post("", response_model=ScheduledTaskResponse)
@router.post("/", response_model=ScheduledTaskResponse, include_in_schema=False)
async def create_scheduled_task(task: ScheduledTaskCreate):
    try:
        task_id = scheduled_task_manager.create_task(
            name=task.name,
            task_type=task.task_type.value,
            query=task.query,
            workflow_id=task.workflow_id,
            when=task.when,
            timezone_name=task.timezone,
            mode=task.mode,
            enabled=task.enabled,
            allow_overlap=task.allow_overlap,
            max_retries=task.max_retries,
            timeout_seconds=task.timeout_seconds,
            metadata=task.metadata,
        )
        created = scheduled_task_manager.get_task(task_id)
        return ScheduledTaskResponse(
            ok=True,
            task_id=task_id,
            task=ScheduledTask(**created) if created else None,
            message=f"Scheduled task created (ID: {task_id})"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=ScheduledTaskResponse)
@router.get("/", response_model=ScheduledTaskResponse, include_in_schema=False)
async def list_scheduled_tasks(
    status: ScheduledTaskListStatus = Query(ScheduledTaskListStatus.ALL),
    limit: int = Query(100, description="Maximum number of tasks")
):
    try:
        tasks = scheduled_task_manager.list_tasks(status=status.value, limit=limit)
        return ScheduledTaskResponse(
            ok=True,
            tasks=[ScheduledTask(**row) for row in tasks],
            message=f"Found {len(tasks)} scheduled task(s)"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}", response_model=ScheduledTaskResponse)
async def get_scheduled_task(task_id: int):
    task = scheduled_task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Scheduled task {task_id} not found")
    return ScheduledTaskResponse(ok=True, task=ScheduledTask(**task))


@router.patch("/{task_id}", response_model=ScheduledTaskResponse)
async def update_scheduled_task(task_id: int, updates: ScheduledTaskUpdate):
    try:
        ok = scheduled_task_manager.update_task(task_id, **updates.model_dump(exclude_none=True))
        if not ok:
            raise HTTPException(status_code=404, detail=f"Scheduled task {task_id} not found")
        task = scheduled_task_manager.get_task(task_id)
        return ScheduledTaskResponse(
            ok=True,
            task=ScheduledTask(**task) if task else None,
            message=f"Scheduled task {task_id} updated"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{task_id}", response_model=ScheduledTaskResponse)
async def cancel_scheduled_task(task_id: int, permanent: bool = Query(False)):
    ok = scheduled_task_manager.delete_task(task_id) if permanent else scheduled_task_manager.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Scheduled task {task_id} not found")
    action = "deleted" if permanent else "canceled"
    return ScheduledTaskResponse(ok=True, message=f"Scheduled task {task_id} {action}")


@router.post("/{task_id}/run", response_model=ScheduledTaskResponse)
async def run_scheduled_task_now(task_id: int):
    ok = scheduled_task_manager.run_now(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Scheduled task {task_id} not found")
    task = scheduled_task_manager.get_task(task_id)
    one_shot = task and scheduled_task_manager.is_manual_run_once(task)
    message = (
        f"Scheduled task {task_id} queued for a one-time run (schedule stays disabled)"
        if one_shot
        else f"Scheduled task {task_id} queued to run now"
    )
    return ScheduledTaskResponse(
        ok=True,
        task=ScheduledTask(**task) if task else None,
        message=message
    )


@router.get("/{task_id}/runs", response_model=ScheduledTaskResponse)
async def list_scheduled_task_runs(task_id: int, limit: int = Query(20)):
    task = scheduled_task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Scheduled task {task_id} not found")
    runs = scheduled_task_manager.list_runs(task_id, limit=limit)
    return ScheduledTaskResponse(
        ok=True,
        task=ScheduledTask(**task),
        runs=[ScheduledTaskRun(**row) for row in runs],
        message=f"Found {len(runs)} run(s)"
    )
