"""Scheduled task API models"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ScheduledTaskType(str, Enum):
    QUERY = "query"
    WORKFLOW = "workflow"


class ScheduledTaskListStatus(str, Enum):
    ALL = "all"
    ENABLED = "enabled"
    DISABLED = "disabled"


class ScheduledTaskCreate(BaseModel):
    name: str = Field(..., description="Human-friendly task name")
    task_type: ScheduledTaskType = Field(..., description="Task type: query or workflow")
    query: str | None = Field(None, description="Natural language Jarvis query for query tasks")
    workflow_id: str | None = Field(None, description="Workflow ID for workflow tasks")
    when: str = Field(..., description="Natural schedule expression")
    timezone: str | None = Field(None, description="IANA timezone name")
    mode: Literal["cloud", "local"] | None = Field(
        None,
        description="Execution mode; defaults to the active scheduler mode",
    )
    enabled: bool = Field(True, description="Whether the task is enabled")
    allow_overlap: bool = Field(False, description="Allow overlapping runs")
    max_retries: int = Field(1, description="Maximum retry attempts")
    timeout_seconds: int = Field(300, description="Execution timeout in seconds")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")


class ScheduledTaskUpdate(BaseModel):
    name: str | None = None
    query: str | None = None
    workflow_id: str | None = None
    when: str | None = None
    timezone: str | None = None
    mode: Literal["cloud", "local"] | None = None
    enabled: bool | None = None
    allow_overlap: bool | None = None
    max_retries: int | None = None
    timeout_seconds: int | None = None
    metadata: dict[str, Any] | None = None


class ScheduledTask(BaseModel):
    id: int
    name: str
    enabled: bool
    task_type: ScheduledTaskType
    task_target: str | None = None
    task_payload: str | None = None
    schedule_type: str
    schedule_expr: str
    timezone: str
    mode: str
    allow_overlap: bool
    max_retries: int
    timeout_seconds: int
    last_run_at: str | None = None
    next_run_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    last_duration_ms: float | None = None
    last_result_summary: str | None = None
    lock_owner: str | None = None
    lock_acquired_at: str | None = None
    metadata: str | None = None
    created_at: str
    updated_at: str


class ScheduledTaskRun(BaseModel):
    id: int
    task_id: int
    started_at: str
    finished_at: str | None = None
    status: str
    mode: str | None = None
    provider: str | None = None
    model: str | None = None
    workflow_id: str | None = None
    tools_used: str | None = None
    speech: str | None = None
    raw_llm_response: str | None = None
    result_data: str | None = None
    error: str | None = None
    duration_ms: float | None = None
    completion_guard_applied: bool = False
    feedback_collected: bool = False
    metadata: str | None = None


class ScheduledTaskResponse(BaseModel):
    ok: bool
    task_id: int | None = None
    task: ScheduledTask | None = None
    tasks: list[ScheduledTask] | None = None
    runs: list[ScheduledTaskRun] | None = None
    message: str | None = None
