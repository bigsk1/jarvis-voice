# Completion Guard

> Purpose: Add a bounded "did this actually get completed?" loop after Jarvis answers, with an optional same-runtime repair pass and an escalation ticket when the task still fails.

## Problem

Jarvis can produce answers that sound complete but are not actually complete.

Common failure modes:

- A tool failed silently or returned weak data
- The LLM skipped an obvious tool even though one existed
- The answer was incomplete for the query asked
- The answer claimed an action happened when it did not
- Search concluded "couldn't find it" too early
- Provider, proxy, or tool issues degraded output without a hard error
- The result was technically related, but not sufficient for the actual task

This is not only a prompting problem. It is a control-loop problem.

## Goal

Add a lightweight completion-check step that can:

1. Decide whether the task appears actually complete
2. Let the user confirm or reject the result
3. Run one bounded repair pass when needed
4. Create a debug ticket when repair still fails

The system should improve recovery without turning every request into a slow multi-pass workflow.

## Core Principle

The repair pass should stay in the same runtime whenever possible.

That means:

- Keep the same orchestrator execution context
- Keep the same transcript and turn history
- Keep the same accumulated tool outputs
- Keep the same tool/result references
- Keep the same error context and progress state

Avoid starting a fresh conversation unless there is no safe way to continue in-process.

Why this matters:

- A fresh run loses subtle context about what Jarvis already tried
- It may repeat the same bad path again
- It makes debugging harder because the recovery path is split across requests
- It weakens the model's ability to reason over prior failures and partial results

The repair loop should feel like "continue solving with better awareness", not "start over and hope this time is better."

## Recommended Name

`Completion Guard`

This is a better fit than "self-repair tool" because it is not just a tool call. It is an orchestration and UI control loop around task completion.

## High-Level Flow

### Manual Mode

1. User sends a request
2. Jarvis completes the normal answer/tool flow
3. Web UI shows a small inline card:
   - `Completed correctly?`
   - `Yes`
   - `No`
   - optional note field
4. If user clicks `Yes`, the task is accepted
5. If user clicks `No`, Jarvis runs one repair pass in the same runtime context
6. If repair succeeds, updated answer is shown
7. If repair still fails, create a ticket markdown file for follow-up

### Auto Mode

1. User sends a request
2. Jarvis completes the normal answer/tool flow
3. A completion evaluator scores whether the task looks complete
4. If score is above threshold, no action
5. If score is below threshold:
   - either ask user for confirmation, or
   - auto-run one repair pass if configured
6. If still unresolved, create a ticket

## Why Same Runtime Matters

The repair pass should see all of this without reconstructing it from scratch:

- original user query
- exact prior answer
- tools used
- structured tool outputs
- raw LLM response before speech condensation
- error context from retries
- provider/model/mode
- conversation context injected earlier in the task
- any follow-up refs like `stash_ref`, `canvas_page_id`, generated filenames, IDs, provider names

This is especially important when:

- a tool almost succeeded
- one step worked and one did not
- the user says "no, that's not what I meant"
- the answer omitted a key requirement even though the data already existed

## Existing Systems To Reuse

Jarvis already has building blocks for this:

- feedback collection
- experience logging
- retry with error context
- Web UI settings overrides
- tool result persistence in conversations
- async feedback UI cards

This feature should reuse those systems instead of creating a totally separate stack.

## Completion Guard vs Feedback System

These are related but not the same thing.

### Feedback System

- retrospective analysis
- grades quality
- useful for learning and analytics
- can happen asynchronously

### Completion Guard

- operational recovery
- decides whether to repair now
- changes the live result path
- needs tighter control and strict limits

Feedback asks:

`How good was this?`

Completion Guard asks:

`Is this actually done, and if not, should we repair it right now?`

## Signals For "Not Complete"

Do not rely only on LLM self-judgment.

Use multiple signals:

- User explicitly clicks `No`
- Tool returned empty/weak output
- Final answer claims success but no artifact/result exists
- Final answer says "done" but expected IDs, files, or links are missing
- Final answer says "couldn't find it" even though strong matching tools were available
- The answer ignores a direct constraint from the user
- Tool error occurred but the final answer hides or softens it
- Provider-side native tools were used but evidence in the answer is insufficient
- Search/research answer lacks expected sources or specifics
- Generated result does not satisfy requested format

LLM self-eval should be one signal among many, not the sole authority.

## Modes

### Off

No completion check, no repair.

### Manual

Show UI completion prompt after each answer or after selected answer types.

### Auto

Run evaluator automatically. If the answer looks weak, either:

- ask the user, or
- auto-run one repair pass

Recommended initial rollout:

- start with `manual`
- then add `auto` only after the repair logic is stable

## Proposed Config

Environment variables:

```bash
JARVIS_COMPLETION_GUARD_ENABLED=false
JARVIS_COMPLETION_GUARD_MODE=manual
JARVIS_COMPLETION_GUARD_MAX_REPAIRS=1
JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD=0.70
JARVIS_COMPLETION_GUARD_REQUIRE_USER_CONFIRM=true
JARVIS_COMPLETION_GUARD_TICKET_ON_FAIL=true
JARVIS_COMPLETION_GUARD_TICKET_DIR=logs/completion-guard
JARVIS_COMPLETION_GUARD_SHOW_UI_PROMPT=true
JARVIS_COMPLETION_GUARD_INCLUDE_QA=true
JARVIS_COMPLETION_GUARD_INCLUDE_TOOL_TASKS=true
JARVIS_COMPLETION_GUARD_EVAL_PROVIDER=
JARVIS_COMPLETION_GUARD_EVAL_MODEL=
```

Web UI should support per-mode override like other AI Config settings.

## UI Concept

Use a small inline card under the assistant response, not only a toast.

Suggested UI:

- `Completed correctly?`
- `Yes`
- `No`
- optional `Add note`

Behavior:

- Appears after the assistant response
- Can auto-collapse after a few seconds if untouched
- Can be reopened from the message area if needed
- If user clicks `No`, show:
  - `Repairing...`
  - then either a corrected response or a failure ticket notice

Optional note examples:

- "You said you created the file but it is not there"
- "This did not answer the second part of my question"
- "You had search tools but gave up too early"

## Repair Pass Design

### Constraints

- Max repairs per task: `1`
- Must stay in same orchestrator run if possible
- Must receive explicit failure context
- Must prefer missing/incorrect step correction over full re-execution
- Must not loop indefinitely

### Repair Prompt Inputs

- original user request
- prior final answer
- raw LLM answer
- tools used
- structured tool outputs
- accumulated conversation context for the current request
- retry/error context from failed tools
- evaluator reasons
- user-provided rejection note

### Repair Prompt Goal

The repair model should answer:

1. What specifically was incomplete or incorrect?
2. Can this be repaired using existing context and tool outputs?
3. If more work is needed, which tool or step should happen next?
4. Produce a corrected final result, or produce a clear unresolved failure reason

### Repair Strategy

Prefer this order:

1. Fix answer using existing data
2. Run one missing tool step if clearly needed
3. Re-summarize with corrected facts
4. Escalate to ticket if still unresolved

Avoid:

- restarting the whole task blindly
- re-running every tool
- pretending the second attempt succeeded without evidence

## Ticketing

If one repair pass still fails, write a markdown ticket.

Location:

`logs/completion-guard/`

Suggested filename:

`2026-03-30-001-completion-guard.md`

Suggested contents:

- timestamp
- conversation id
- message id
- mode / provider / model
- original user request
- previous final answer
- repair answer, if any
- user rejection note
- evaluator summary
- tools used
- important structured outputs or references
- error context
- likely failure category
- recommended debugging direction

This file should be gitignored.

## Failure Categories

Useful categories for clustering later:

- `tool_failure`
- `tool_output_weak`
- `missed_tool_selection`
- `claimed_action_not_done`
- `incomplete_answer`
- `bad_search_stop`
- `provider_or_proxy_issue`
- `format_mismatch`
- `artifact_missing`
- `unknown`

These categories would help later analysis in the intelligence layer.

## Suggested Architecture

### Orchestrator

Owns:

- completion guard state
- current repair count
- same-runtime repair loop
- final decision to repair or ticket

### Web Socket Server

Owns:

- emitting completion prompt events
- receiving yes/no/note actions
- resuming the same in-flight task when possible
- ticket notification event

### Web UI

Owns:

- inline completion card
- optional note entry
- repair progress state
- display of ticket created

### Intelligence / Logging

Owns:

- storing failure patterns
- connecting low-confidence repairs to experiences
- later clustering of recurring issues

## Same-Runtime Implementation Strategy

This part is the most important design choice.

Preferred model:

- Keep a task state object alive through answer completion
- Pause at the "completion checkpoint"
- Wait briefly for user response or evaluator result
- If accepted, finalize normally
- If rejected, continue the same task state with:
  - prior route outputs
  - tool results
  - accumulated data
  - failure note

This is much better than:

- creating a brand-new chat message
- reconstructing state from saved conversation history
- hoping the model infers what happened previously

If true same-runtime resume is too hard initially, a fallback can rebuild from saved conversation data, but that should be considered phase 1.5, not the ideal end state.

## Recommended Rollout

### Phase 1

- Design doc
- env flags
- UI setting
- manual completion prompt card
- ticket generation only

No auto repair yet.

### Phase 2

- same-runtime repair pass
- one retry max
- user rejection note fed into repair prompt

### Phase 3

- optional evaluator-based auto triggering
- issue clustering from tickets
- dashboard or log view for recurring completion failures

## Risks

- Too much automatic repair makes the UI feel slow
- The LLM may overestimate its own success
- Bad evaluator prompts can create false positives
- Too many tickets can create noise instead of insight
- Re-running tools blindly can waste tokens and time

These are reasons to keep:

- one repair max
- manual-first rollout
- strict ticketing
- same-runtime continuation where possible

## Non-Goals

This feature should not:

- silently re-run forever
- replace normal retries/error recovery
- turn every answer into a long evaluator workflow
- hide failures behind polished language

## MVP Recommendation

Best first real implementation:

1. Add `Completion Guard` config to env + Web UI
2. Show inline `Completed correctly? Yes / No` card
3. If `No`, run one same-context repair pass
4. If still unresolved, write ticket markdown
5. Log outcome for later intelligence analysis

That gives immediate user value and strong debugging leverage without overcomplicating the first version.
