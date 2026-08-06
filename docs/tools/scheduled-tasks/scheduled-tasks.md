# Scheduled Tasks

> Purpose: Let Jarvis schedule future queries, workflows, and recurring jobs using its normal tool and orchestration stack, with first-class logs, visibility, and safe execution semantics.

## Current Status

The foundation is now implemented, not just planned.

Files added:

- `lib/time_utils.py`
- `lib/schedule_parser.py`
- `api/models/scheduled_task.py`
- `api/managers/scheduled_task_manager.py`
- `api/routes/scheduled_tasks.py`
- `services/scheduled_task_runner.py`
- `skills/schedule_task.py`
- `skills/schedule_task.tool.json`

Files updated:

- `skills/create_reminder.py`
- `skills/list_reminders.py`
- `services/reminder_scheduler.py`
- `bin/sync-memory-db.py`
- `api/server.py`
- `api/routes/__init__.py`

What works now:

- `schedule_task` tool with `create`, `list`, `update`, and `cancel`
- `schedule_task` also supports `run_now`, `list_runs`, and permanent `delete`
- durable `scheduled_tasks` and `scheduled_task_runs` tables
- API routes for scheduled-task CRUD and run history
- runner service scaffold that executes due `query` and `workflow` tasks
- each runner sees and executes only the schedules owned by its startup mode
- run history records the provider and provider-specific model resolved from
  the task's mode rather than the runner process environment
- scheduled tasks and run history remain independent across cloud/local memory DBs
- occurrences older than the configured grace window are marked missed; one-time
  tasks are disabled and recurring tasks advance directly to their next future slot
- Jarvis Memory UI tab for:
  - list / inspect
  - create / update
  - run now
  - cancel / delete
  - recent run history
- service wiring through:
  - `bin/jarvis-services`
  - `bin/start`
  - `bin/restart-services`
  - `services/self_healing_daemon.py`
- per-task post-run notifications:
  - email on success / failure using contact names from `config/contacts.json`
  - alert on failure
  - webhook on success / failure using named webhooks
  - per-occurrence notification cooldown to avoid spam if a restart hiccup reruns the same scheduled slot
  - notification delivery results are visible in scheduled-task run history (`email sent`, `alert created`, `webhook sent`, `cooldown suppressed`, etc.)
- shared natural-language schedule parsing for:
  - one-time future tasks
  - explicit dates like `April 4th at 4pm`
  - numeric dates like `4/4 at 4pm` and `04/04/2026 at 4pm`
  - `every N minutes/hours/days/weeks`
  - daily schedules
  - weekday / weekly schedules
  - monthly schedules

What is still next:

- richer scheduled-task evidence in intelligence/reflection
- production-hardening around retries and overlap policy
- optional chaining / dependency policies between tasks

## Important Revelation: Timezone Handling Had To Be Fixed First

The original design assumed we could reuse reminder scheduling logic directly.
That turned out to be only partly true.

While preparing Scheduled Tasks, we found the reminder path had grown through trial and error and mixed:

- naive local datetimes
- manual UTC offset math
- local display using `JARVIS_TIMEZONE`
- UTC-ish storage by convention

That was good enough to function, but not good enough to serve as the foundation for a general scheduler.

So before building Scheduled Tasks, Jarvis now has shared time helpers in `lib/time_utils.py`, and reminders were updated to:

- parse time in the configured app timezone
- convert to UTC using aware datetimes
- preserve local wall-clock recurrence better across DST changes
- parse due timestamps consistently in the scheduler

This is the most important difference from the original doc:

- Scheduled Tasks are not built on copied reminder math
- they are built on a cleaned-up shared timezone layer plus a dedicated `schedule_parser`

## Problem

Jarvis is strong at solving tasks now, but it does not yet have a native way to say:

- run `/status` every day at 10 AM
- check something again in 6 hours
- email a recurring report every morning
- run a workflow on a schedule and save the result to canvas or stash

Today, a plain cron job can do some of this, but it is not a great fit for the Jarvis architecture:

- cron has no first-class knowledge of Jarvis tools, workflows, or intelligence
- cron gives weak visibility into what happened unless each script builds its own logging
- cron does not naturally expose schedules in the Web UI
- cron is awkward for user-created schedules like "every Wednesday at 9"
- cron does not preserve rich task metadata like original query, output destinations, or last run state

The goal is not just "run a command later." The goal is:

- schedule a future Jarvis task
- execute it with Jarvis's normal orchestration flow
- log what happened in a debuggable way
- make schedules inspectable and manageable

## Example Use Cases

### Daily workflow

`Run /status every day at 10 AM and put the new report on canvas.`

### Recurring report email

`Every weekday at 9 AM, get Bitcoin and Solana prices and email Boss.`

### Delayed re-check

`In 6 hours, check whether the service is healthy again and tell me if it is still down.`

### Background watch task

`Every 4 hours, run a deep search for updates about a vendor outage and save a summary to canvas.`

## Existing Jarvis Building Blocks

Jarvis already has several pieces that make this feasible:

### 1. Reminder scheduler pattern

There is already a daemon-style polling model in:

- `services/reminder_scheduler.py`
- `api/managers/reminder_manager.py`
- `skills/create_reminder.py`

That gives us:

- a durable scheduled table pattern
- daemon polling every minute
- recurring schedule support for reminders
- callback URL support
- an established "service + DB + tool" pattern

Most importantly, `skills/create_reminder.py` already contains the hard-won natural-language scheduling logic:

- one-time future scheduling
- recurring daily / weekly / monthly expressions
- multi-day patterns
- local-time parsing and UTC storage

That logic should be extracted into shared scheduling utilities instead of reimplemented from scratch.

### 2. Workflow execution

Jarvis already has deterministic multi-step workflows:

- `orchestrator/pipeline_executor.py`
- `orchestrator/workflow_loader.py`
- `data/workflows/*.json`

This is ideal for recurring operational jobs like:

- `/status`
- `/health`
- daily market reports
- research or ingest workflows

### 3. Orchestrator execution and learning

Normal Jarvis runs already know how to:

- route tool calls
- log tool usage
- record experiences
- feed reflections and insights

That means scheduled runs can become part of the same learning loop if we tag them correctly.

### 4. Existing service logging pattern

Jarvis already uses dedicated service logs for daemons and background workers.

That means a scheduler can have:

- `logs/services/scheduled_task_runner-*.jsonl`
- or `logs/scheduled-tasks/scheduled-tasks-YYYY-MM-DD.jsonl`

without inventing a new logging style.

## Naming

Possible names:

- `Scheduled Tasks`
- `Recurring Jobs`
- `Task Scheduler`
- `Heartbeat`

Recommended naming:

- user-facing concept: `Scheduled Tasks`
- internal service name: `scheduled_task_runner`

Why:

- "Scheduled Tasks" is clearer in the UI and tools
- "scheduled_task_runner" describes exactly what the background service does
- "heartbeat" sounds like a fixed poll/check mechanism, not a general future scheduling system

## Architectural Options

## Option 1: Plain cron wrapper

Use normal cron/systemd timers to execute:

- `./jarvis "query here"`
- `./orchestrator/orchestrator_v2.py ...`
- `./orchestrator/pipeline_executor.py --workflow ...`

### Pros

- fastest to prototype
- very little new code
- system-level reliability

### Cons

- poor UX for creating/editing schedules
- weak per-job metadata unless manually bolted on
- weak integration with Web UI
- no first-class task registry
- hard to inspect last run, next run, failures, or task payloads

### Verdict

Good for prototypes and personal scripts, not good as the native Jarvis feature.

## Option 2: Extend reminders into general scheduled jobs

Reuse the existing reminders table and scheduler daemon, and add a new kind of reminder that executes a Jarvis task instead of speaking TTS.

### Pros

- reuses the existing scheduler service
- durable storage already exists
- recurring logic already exists

### Cons

- reminders and scheduled jobs are conceptually different
- current reminder model is centered on notification delivery, not task execution
- recurrence support is limited and reminder-oriented
- reminder fields like `title`, `spoken`, and `acknowledged` do not map cleanly to recurring jobs
- overloading reminders will make the data model messy over time

### Verdict

Tempting for a shortcut, but not the clean long-term design.

## Option 3: Dedicated scheduled-task system

Create a separate scheduler service and table for executable Jarvis jobs.

### Pros

- clean semantics
- easier UI and API design
- supports one-time, recurring, query-based, and workflow-based tasks
- easier logging, retry policy, and output policy
- easier future features like pause/resume/history

### Cons

- more code than reusing reminders
- needs a new DB table and management layer

### Verdict

This is the recommended direction.

## Recommended Design

Build a first-class scheduled-task system with:

1. a new `scheduled_tasks` table
2. a daemon service: `services/scheduled_task_runner.py`
3. a single multi-action tool: `skills/schedule_task.py`
4. matching API/manager endpoints for create/list/update/cancel
4. dedicated logs
5. optional Web UI management later

## Mode and Database Model

Scheduled tasks follow the cloud/local database split, but unlike portable
memory, each schedule belongs to the mode that created it.

Recommended storage model:

- cloud mode → `data/jarvis_memory.db`
- local mode → `data/jarvis_memory_local.db`

Why:

- cloud and local modes can have different tool profiles, providers, credentials,
  MCP servers, and workflow availability
- a local runner must not execute a cloud schedule whose dependencies are unavailable
- independent integer IDs and run histories cannot safely be merged by the
  general memory sync

Important implication:

- `bin/sync-memory-db.py` does not copy `scheduled_tasks` or
  `scheduled_task_runs`
- creating, listing, updating, running, and deleting a task are scoped to the
  active scheduler mode
- switching modes pauses the schedules owned by the inactive mode; when its
  runner starts again, occurrences older than the grace window are skipped
  rather than replayed

## Recommended Implementation Shape

### Tool

One tool, not four:

- `skills/schedule_task.py`
- `skills/schedule_task.tool.json`

Actions:

- `create`
- `list`
- `update`
- `cancel`
- `run_now`
- `list_runs`
- `delete`

This matches existing Jarvis patterns like `manage_intel`, keeps the surface area small, and makes discovery easier for the model.

### Backend

- `api/managers/scheduled_task_manager.py`
- `api/models/scheduled_task.py`
- `api/routes/scheduled_tasks.py`
- `services/scheduled_task_runner.py`

### Shared parser utilities

Extract reusable scheduling logic from:

- `skills/create_reminder.py`

into something like:

- `lib/schedule_parser.py`

That shared module should handle:

- one-time future times
- daily recurring schedules
- weekly recurring schedules
- monthly recurring schedules
- interval schedules
- local timezone parsing and UTC normalization
- calculation of `next_run_at`

This avoids a second independent parser drifting over time.

## Core Data Model

Suggested table: `scheduled_tasks`

Suggested fields:

```json
{
  "id": 42,
  "name": "Daily status at 10",
  "enabled": true,
  "task_type": "workflow",
  "task_target": "daily_status",
  "task_payload": {
    "query": "/status"
  },
  "schedule_type": "cron",
  "schedule_expr": "0 10 * * *",
  "timezone": "America/Los_Angeles",
  "mode": "cloud",
  "run_policy": {
    "max_retries": 1,
    "allow_overlap": false,
    "timeout_seconds": 300
  },
  "output_policy": {
    "save_result": true,
    "notify_on_failure": true
  },
  "metadata": {
    "created_by": "jarvis_tool",
    "source": "scheduled_task"
  },
  "last_run_at": null,
  "next_run_at": "2026-03-31T10:00:00-07:00",
  "last_status": null,
  "last_error": null,
  "created_at": "2026-03-31T08:15:00-07:00",
  "updated_at": "2026-03-31T08:15:00-07:00"
}
```

## Proposed SQLite Schema

### `scheduled_tasks`

```sql
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    enabled BOOLEAN DEFAULT 1,

    task_type TEXT NOT NULL,           -- query | workflow
    task_target TEXT,                  -- workflow id for workflow tasks
    task_payload TEXT,                 -- JSON payload (query, args, output policy, etc.)

    schedule_type TEXT NOT NULL,       -- once | interval | daily | weekly | monthly | cron
    schedule_expr TEXT NOT NULL,       -- normalized expression or JSON string
    timezone TEXT DEFAULT 'America/Los_Angeles',

    mode TEXT DEFAULT 'cloud',         -- cloud | local
    allow_overlap BOOLEAN DEFAULT 0,
    max_retries INTEGER DEFAULT 1,
    timeout_seconds INTEGER DEFAULT 300,

    last_run_at TEXT,
    next_run_at TEXT,
    last_status TEXT,                  -- success | failure | running | skipped | cancelled
    last_error TEXT,
    last_duration_ms REAL,
    last_result_summary TEXT,

    lock_owner TEXT,
    lock_acquired_at TEXT,

    metadata TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run
ON scheduled_tasks(enabled, next_run_at);

CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_mode
ON scheduled_tasks(mode);
```

### `scheduled_task_runs`

```sql
CREATE TABLE IF NOT EXISTS scheduled_task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,

    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,              -- success | failure | running | skipped | cancelled

    mode TEXT,
    provider TEXT,
    model TEXT,
    workflow_id TEXT,

    tools_used TEXT,                   -- JSON array
    speech TEXT,
    raw_llm_response TEXT,
    result_data TEXT,                  -- JSON result payload
    error TEXT,
    duration_ms REAL,

    completion_guard_applied BOOLEAN DEFAULT 0,
    feedback_collected BOOLEAN DEFAULT 0,

    metadata TEXT,

    FOREIGN KEY(task_id) REFERENCES scheduled_tasks(id)
);
```

Recommended indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_scheduled_task_runs_task
ON scheduled_task_runs(task_id, started_at DESC);
```

## Tool Schema Recommendation

Recommended tool name:

- `schedule_task`

Recommended shape:

```json
{
  "enabled": true,
  "name": "schedule_task",
  "description": "Create, list, update, or cancel scheduled Jarvis tasks. Use when the user wants Jarvis to run a future one-time or recurring query or workflow such as daily status reports, periodic checks, or scheduled emails.",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "enum": ["create", "list", "update", "cancel"],
        "description": "What to do with scheduled tasks."
      },
      "task_id": {
        "type": "integer",
        "description": "Required for update or cancel."
      },
      "name": {
        "type": "string",
        "description": "Human-friendly task name."
      },
      "task_type": {
        "type": "string",
        "enum": ["query", "workflow"],
        "description": "Task type for create or update."
      },
      "query": {
        "type": "string",
        "description": "Natural language Jarvis query to run later. Used when task_type=query."
      },
      "workflow_id": {
        "type": "string",
        "description": "Workflow ID to run. Used when task_type=workflow."
      },
      "when": {
        "type": "string",
        "description": "Natural time or recurrence expression like 'tomorrow at 10am', 'every day at 9am', 'every 6 hours', or 'next Wednesday at 2pm'."
      },
      "timezone": {
        "type": "string",
        "description": "IANA timezone name. Defaults to local timezone."
      },
      "mode": {
        "type": "string",
        "enum": ["cloud", "local"],
        "description": "Which Jarvis mode should execute the task."
      },
      "enabled": {
        "type": "boolean",
        "description": "Enable or disable the task."
      },
      "allow_overlap": {
        "type": "boolean",
        "description": "Whether the task may start a new run while the previous one is still running."
      },
      "max_retries": {
        "type": "integer",
        "description": "Maximum retry attempts for a failed run."
      },
      "limit": {
        "type": "integer",
        "description": "For list action: maximum number of tasks to return."
      },
      "status": {
        "type": "string",
        "enum": ["all", "enabled", "disabled"],
        "description": "For list action: filter by enabled state."
      }
    },
    "required": ["action"]
  }
}
```

## API Recommendation

Suggested endpoints:

- `POST /api/scheduled-tasks`
- `GET /api/scheduled-tasks`
- `GET /api/scheduled-tasks/{id}`
- `PATCH /api/scheduled-tasks/{id}`
- `DELETE /api/scheduled-tasks/{id}`
- `POST /api/scheduled-tasks/{id}/run`
- `GET /api/scheduled-tasks/{id}/runs`

### Local API auth note

If `JARVIS_API_AUTH=true`, localhost requests still bypass auth by design.

That means these examples should work from the Jarvis host without needing an `Authorization` header:

- `http://localhost:8880/api/scheduled-tasks`

### Curl examples

Task create/update requests accept only `"cloud"` or `"local"` for `mode`.
Typos are rejected with `422 Unprocessable Entity` rather than being stored for
the runner to fail later.

Create a recurring workflow task:

```bash
curl -s -X POST http://localhost:8880/api/scheduled-tasks \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Daily status at 10",
    "task_type": "workflow",
    "workflow_id": "daily_status",
    "when": "every day at 10am",
    "mode": "cloud",
    "timezone": "America/Los_Angeles"
  }' | jq
```

Create a recurring query task:

```bash
curl -s -X POST http://localhost:8880/api/scheduled-tasks \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Morning crypto email",
    "task_type": "query",
    "query": "get bitcoin and solana price and email boss",
    "when": "every weekday at 9am",
    "mode": "cloud",
    "timezone": "America/Los_Angeles"
  }' | jq
```

List tasks:

```bash
curl -s "http://localhost:8880/api/scheduled-tasks?status=all&limit=50" | jq
```

Get one task:

```bash
curl -s http://localhost:8880/api/scheduled-tasks/42 | jq
```

Update a task:

```bash
curl -s -X PATCH http://localhost:8880/api/scheduled-tasks/42 \
  -H "Content-Type: application/json" \
  -d '{
    "when": "every weekday at 8:30am",
    "enabled": true
  }' | jq
```

Cancel a task without deleting history:

```bash
curl -s -X DELETE http://localhost:8880/api/scheduled-tasks/42 | jq
```

Permanently delete a task and its run history:

```bash
curl -s -X DELETE "http://localhost:8880/api/scheduled-tasks/42?permanent=true" | jq
```

Queue a task to run now:

```bash
curl -s -X POST http://localhost:8880/api/scheduled-tasks/42/run | jq
```

List recent runs for a task:

```bash
curl -s "http://localhost:8880/api/scheduled-tasks/42/runs?limit=10" | jq
```

## Task Types

The scheduler should support at least these task types:

### 1. Query task

Run a normal Jarvis query through the orchestrator:

`get bitcoin and solana price and email boss`

### 2. Workflow task

Run a deterministic workflow directly:

- `daily_status`
- `server_health_check`
- `crypto_market_report`

### 3. Future task types

- direct tool invocation
- batch workflow
- maintenance/intelligence jobs
- webhook-only task

For MVP, query + workflow is enough.

## Scheduling Types

Recommended support:

### MVP

- one-time at a future datetime
- interval every N minutes/hours/days
- daily at a local time
- weekly on selected days at a local time

### Later

- full cron expressions
- monthly rules
- blackout windows
- jitter
- calendar-style exceptions

The user-facing tool should not require cron syntax for common schedules.

## Execution Flow

### Create

1. User asks Jarvis to schedule something
2. Jarvis calls a scheduler tool
3. The tool stores a durable scheduled task
4. The task gets a calculated `next_run_at`

### Run

1. On startup, `scheduled_task_runner` recovers locks owned by runner processes that no longer exist and marks their unfinished run records as failed
2. `scheduled_task_runner` wakes up on a fixed interval
3. It skips occurrences older than `SCHEDULED_TASK_MISSED_GRACE_SECONDS`
   (default `300`, or five minutes). This lets normal polling and short service
   restarts execute slightly late without replaying work after longer downtime.
4. It fetches due tasks where:
   - `enabled = true`
   - `next_run_at <= now`
   - not currently locked/running
5. It marks the task as running
6. It executes either in an isolated worker process, enforcing the task's `timeout_seconds` deadline:
   - orchestrator query mode, or
   - workflow executor mode
7. It stores run history, status, timing, and outputs
8. It calculates the next run or disables/completes the task

### Inspect

Users should later be able to:

- list all schedules
- see next run time
- inspect last result
- inspect last error
- pause/resume/cancel

## Execution Engine Choice

Do not make the runner shell out to CLI commands unless needed for debugging.

Recommended execution paths:

### Query tasks

- direct Python call into `Orchestrator`

### Workflow tasks

- direct Python call into `PipelineExecutor`

Why direct Python is better than shelling out:

- structured results instead of parsing CLI output
- easier cancellation and timeout handling
- lower process overhead
- cleaner logging and run-history capture

## Query tasks

Use the normal orchestrator so scheduled jobs keep access to:

- tool routing
- MCP/skills/tool stack
- intelligence insights
- normal logging

## Workflow tasks

Use `pipeline_executor` directly when the target is a deterministic workflow.

This is better for known operational routines like:

- status reports
- health checks
- research workflows

Scheduled workflow tasks do not discover or execute through the autonomous
`workflow` meta-tool. Consequently:

- disabling/profile-disabling/Web-blocking the `workflow` meta-tool does not disable an existing scheduled workflow;
- Web blocked tools are a Web-chat surface policy, not a scheduler policy;
- the runner still checks its own mode/profile registry and rejects the complete workflow if any required component is unavailable;
- a component explicitly marked `required: false` may be unavailable; the runner skips it without a tool call and records a degraded result, while conditional steps remain required unless explicitly optional;
- the scheduled task's own `timeout_seconds` deadline still wraps the complete run, even though `PipelineExecutor` itself has no global wall-clock timeout.

Why not route workflow commands back through free-form LLM every time:

- direct workflow execution is more predictable
- lower latency
- fewer chances of route drift

## Logging

This feature needs its own log stream.

Current location:

- `logs/services/scheduled_task_runner-YYYY-MM-DD.jsonl`
- `logs/services/scheduled_task_runner-YYYY-MM-DD.log`

Possible later split if desired:

- `logs/scheduled-tasks/scheduled-tasks-YYYY-MM-DD.jsonl`

Each run should log:

- task id
- task name
- task type
- schedule details
- started_at / finished_at
- mode / provider / model
- success / failure
- tools used
- workflow id if applicable
- output refs (canvas/stash/memory ids when available)
- error summary
- duration

Example:

```json
{
  "timestamp": "2026-03-31T10:00:04-07:00",
  "task_id": 42,
  "task_name": "Daily status at 10",
  "task_type": "workflow",
  "target": "daily_status",
  "mode": "cloud",
  "status": "success",
  "tools_used": ["get_time", "weather", "crypto_price", "canvas"],
  "duration_ms": 4215,
  "result_summary": "Daily status report created.",
  "refs": {
    "canvas": ["canvas://..."],
    "stash": []
  }
}
```

## Run History

In addition to logs, it likely makes sense to keep a small durable run-history table:

- `scheduled_task_runs`

This would make UI/API views much easier than parsing log files alone.

Suggested fields:

- `task_id`
- `started_at`
- `finished_at`
- `status`
- `speech`
- `raw_llm_response`
- `tools_used`
- `result_data`
- `error`

## How This Fits With Completion Guard

Completion Guard today is primarily a Jarvis Web interaction loop.

For scheduled tasks:

- the UI prompt path does not apply
- the Web-only completion card does not apply
- automatic repair should not be assumed in MVP

Recommended initial behavior:

- scheduled tasks run without Web Completion Guard
- failures are logged normally
- if needed later, add a headless scheduler-specific repair policy

Why:

- scheduled jobs need reliability first
- a hidden repair loop could make operational jobs less predictable
- headless repair should be introduced deliberately, not accidentally

## How This Fits With Feedback

Feedback is optional and should stay optional here too.

Recommended MVP:

- do not auto-run feedback for every scheduled task by default
- allow an advanced per-task option later like:
  - `collect_feedback: true`

Why:

- recurring jobs could create a lot of grading traffic
- feedback cost could grow quickly
- scheduled tasks should succeed operationally first

## How This Fits With Intelligence

This is where the feature gets interesting.

Scheduled tasks should still be able to contribute to learning, but they need proper metadata.

Recommended metadata on recorded experiences:

```json
{
  "source": "scheduled_task",
  "scheduled_task_id": 42,
  "scheduled_task_name": "Daily status at 10",
  "scheduled_task_type": "workflow"
}
```

That would allow reflections to learn from recurring jobs without confusing them with ad-hoc user chat.

This could help Jarvis improve future runs by learning:

- which tools work best for recurring checks
- whether a workflow should be preferred over open-ended routing
- which recurring tasks tend to fail and why

## Safety and Guardrails

This feature can become very powerful very quickly, so it needs guardrails.

### 1. Explicit scheduling only

Jarvis should only create scheduled jobs when the user clearly asked for one.

### 2. No overlapping runs by default

If a job is still running when the next slot arrives:

- default: skip or delay
- do not run multiple copies unless explicitly allowed

### 3. Clear output destinations

The scheduled task should know whether it is expected to:

- just run and log
- update canvas
- send email
- write stash output
- notify on failure

### 4. Failure visibility

Users should be able to inspect:

- last error
- retry count
- last success
- recent run history

### 5. Sensitive actions

For actions like:

- email
- phone calls
- webhooks

the schedule creation step itself is the approval boundary.

Once the user explicitly scheduled it, the daemon can execute it later without asking again.

## Proposed Tools / APIs

Recommended tool shape:

### `schedule_task`

Use a single multi-action tool, similar to `manage_intel`, instead of four separate tools.

Recommended actions:

- `create`
- `list`
- `update`
- `cancel`
- `run_now`
- `list_runs`
- `delete`

Why this is a good fit:

- keeps the surface area small
- easier for the LLM to discover and remember
- matches existing Jarvis patterns like `manage_intel`
- keeps related schedule operations in one schema and one handler

Recommended input shape:

- `action`
- `task_id` for update/cancel/run_now
- `name`
- `task_type`: `query` or `workflow`
- `query` or `workflow_id`
- `when`
- `timezone`
- `mode`
- `enabled`
- `allow_overlap`
- `max_retries`

Implementation note:

The tool should call shared scheduling utilities that are extracted from `create_reminder.py`, rather than maintaining a second natural-language time parser.

## Completion Guard and Feedback

Completion Guard today is primarily a Jarvis Web interaction flow, so scheduled tasks should not use the current Web Completion Guard path.

Current behavior:

- Completion Guard: bypassed
- Feedback: disabled by default
- Intelligence recording: enabled, but tagged as scheduled-task-originated

Why:

- scheduled runs are headless
- the current Completion Guard UI prompt does not apply
- always-on feedback would create unnecessary grading traffic for recurring jobs

If needed later, a headless scheduled-task repair policy can be added separately.

## Service Supervision

Scheduled tasks are now wired into the same background-service pattern as other Jarvis daemons.

- `bin/jarvis-services` starts:
  - `follow_up_daemon`
  - `reminder_scheduler`
  - `scheduled_task_runner`
  - `self_healing_daemon`
- `bin/start` treats `jarvis-services` as the tmux-managed background-services session
- `services/self_healing_daemon.py` monitors `scheduled_task_runner` by PID file and restarts it if it crashes

This keeps the scheduler aligned with how Jarvis already supervises non-systemd background services.

## Intelligence Metadata Recommendation

Scheduled runs should still be learnable, but clearly tagged.

Suggested experience metadata:

```json
{
  "source": "scheduled_task",
  "scheduled_task_id": 42,
  "scheduled_task_name": "Daily status at 10",
  "scheduled_task_type": "workflow"
}
```

That lets reflections learn from recurring jobs without confusing them with ad-hoc chat requests.

## Why Not Just a Tool With Future Query Text

A tool that only stores:

- `run this query later`

is a good start, but not enough by itself.

You still need:

- durable scheduling state
- a runner daemon
- logging
- next-run calculation
- cancellation
- run history

So the real feature is:

- scheduler service + storage + tool/API

not just a single tool.

## Recommended MVP

Phase 1 should be practical and modest:

1. New DB table: `scheduled_tasks`
2. New DB table: `scheduled_task_runs`
3. New service: `services/scheduled_task_runner.py`
4. New tool: `schedule_task`
4. Support actions:
   - `create`
   - `list`
   - `update`
   - `cancel`
5. Support:
   - one-time
   - every N hours/days
   - daily at local time
   - weekly at local time
6. Reuse extracted reminder scheduling logic for time parsing
7. Add sync support in `bin/sync-memory-db.py`
8. Support task types:
   - query
   - workflow
9. Dedicated logs
10. Simple failure state + last run state

## Memory UI Management

The first management surface is now Jarvis Memory UI, not Jarvis Web chat.

Current placement:

- `Scheduled Tasks` tab in Jarvis Memory UI
- next to `Stats`

Current management actions in the tab:

- list tasks
- inspect full task details
- create / update
- run now
- cancel
- permanent delete
- view recent run history

Why this fits:

- it is already the place where durable data is inspected and managed
- scheduled tasks are DB-backed operational records, more like reminders/alerts than live chat
- the global mode selector manages each mode's independent scheduled tasks cleanly

## Recommended Phase 2

1. richer filtering and sorting in Memory UI
2. pause/resume instead of cancel-only behavior
3. richer run-history inspection with structured result views
4. better notification options
5. optional per-task output policy controls

## Recommended Phase 3

1. Headless repair policy for scheduled tasks
2. Optional feedback collection per task
3. Rich intelligence/reporting by schedule
4. Failure clustering across recurring jobs
5. Dependencies between jobs

## Recommendation

The best fit for Jarvis is:

- not plain cron
- not overloaded reminders
- a dedicated scheduled-task system that reuses Jarvis's existing orchestrator, workflow, reminder-daemon, and logging patterns

If built this way, it can feel native:

- schedule a future query or workflow
- run it with Jarvis's existing tools and intelligence
- save outputs where Jarvis already knows how to save them
- inspect results and failures like any other first-class feature

That is the direction most likely to feel powerful without turning into a pile of shell scripts.
