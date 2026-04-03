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

## Current Status

As of April 2, 2026, Completion Guard is implemented and actively in use in Jarvis Web, with a clearer distinction between:

- accepted answers
- wording-only tightening
- true repaired outcomes
- unresolved/ticketed failures

Implemented now:

- AI Config settings for enabling/disabling Completion Guard in the Web UI
- Manual mode with inline `Completed correctly? Yes / No` card
- Auto mode with a background evaluator that scores the raw final answer
- Configurable auto-repair threshold (`JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD`) with Web UI override support
- Auto mode now uses a structured audit plus deterministic repair scoring instead of trusting a bare self-reported confidence value
- Auto mode now supports `tighten_only` for answers that are basically correct but only need wording/scope cleanup
- Visible repaired answers now require a real evidence delta or tool-path delta, not just a rewrite
- No-tool rewrite repairs now default to `tighten_only` unless the repaired answer clearly cites a direct source or verified action
- One bounded repair pass when the user clicks `No`
- Repair pass uses:
  - original query
  - raw LLM response
  - prior tool outputs
  - user completion note
- Repair-strategy classifier to bias tool selection during repair
- Synthesis fallback that can answer from existing tool results without another tool call
- Repair cancellation support in the Web UI stop flow
- Markdown ticket creation for unresolved failures
- Tool-aware exclusions for workflows and fire-and-forget/sensitive tools
- Completion Guard metadata included in conversation exports when available
- Accepted states are now persisted instead of being client-only
- Accepted/repaired/ticketed/cancelled outcomes are fed back into the recorded intelligence experience and reflection prompt
- Successful repairs now fold the corrected answer, corrected tools, and corrected tool results back into the original experience record
- Internal repair runs no longer create separate first-class learning experiences
- In Jarvis Web, manual/auto feedback is now gated behind Completion Guard settlement so feedback grades the settled result instead of a mid-repair snapshot
- Feedback prompts now receive Completion Guard metadata and the async web feedback path updates the linked experience record
- Rewrite-only tighten passes do not fold a corrected path back into the original experience as if they were a true operational fix
- The auto evaluator can use a different provider/model than the main chat model; by default it follows `JARVIS_COMPLETION_GUARD_EVAL_PROVIDER` then `FEEDBACK_PROVIDER`

Not implemented yet:

- true same-in-flight orchestrator continuation
- persistence of unanswered manual cards across refresh
- dashboard/reporting for Completion Guard outcomes

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

## Evaluate The Full Answer, Not Speech Text

Completion Guard should evaluate the full response before voice condensation.

Do not judge completion from:

- `speech`
- condensed casual-mode output
- multi-turn summary text

Instead prefer:

- `raw_llm_response`
- structured tool outputs in `data`
- tool result objects
- error context
- available follow-up refs like `stash_ref`, `canvas_page_id`, filenames, URLs, IDs

Why:

- speech output is intentionally shortened by `JARVIS_QA_WORD_LIMIT`
- multi-turn summaries are intentionally shortened by `JARVIS_MULTI_TURN_WORD_LIMIT`
- important caveats, evidence, and failure signals may exist only in the raw response
- the repair loop needs the detailed answer, not the spoken rewrite

The speech layer is for delivery. Completion Guard is about factual and operational correctness.

## Existing Systems To Reuse

Jarvis already has building blocks for this:

- feedback collection
- experience logging
- retry with error context
- Web UI settings overrides
- tool result persistence in conversations
- async feedback UI cards

This feature should reuse those systems instead of creating a totally separate stack.

## Current Learning Model

Completion Guard learning should happen on the original user task, not on the internal repair prompt.

That means the intelligence layer now treats a repaired turn like this:

- original user query
- original answer
- original tool path
- Completion Guard status and note
- repaired answer if one was found
- repaired tool path and repaired tool results

The repair attempt itself is operational, not a separate user interaction.

Why this matters:

- reflections can compare what the first pass did versus what the repaired pass did differently
- insights can recommend a better first-pass tool choice next time
- the system avoids learning from internal meta-prompts as if they were real user requests

This is the intended progression:

1. first pass fails or is incomplete
2. Completion Guard repairs or escalates
3. original experience is updated with the corrected path
4. reflections learn from the delta between original and corrected behavior

That is how Completion Guard becomes a real self-improving loop instead of only a ticketing mechanism.

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

### Current Interaction With Feedback

In Jarvis Web, feedback should not race Completion Guard.

Current behavior:

- if Completion Guard is not active for the response, feedback can run immediately
- if Completion Guard is active, feedback is deferred until the response settles as:
  - `accepted`
  - `auto_accepted`
  - `tighten_only`
  - `repaired`
  - `unresolved`
  - `ticket_created`
  - `cancelled`

This prevents feedback from grading a temporary first-pass answer that is about to be repaired.

When feedback finally runs, it receives Completion Guard context so it can:

- avoid penalizing the system just because Completion Guard exists
- treat `tighten_only` like a basically accepted answer with minor wording cleanup
- grade the repaired answer as the settled result when repair succeeds
- understand that `ticket_created` means the system recognized a failure but could not fully recover

## Outcome Meanings

### `accepted`

- Manual user confirmation that the original answer was good
- No repair required

### `auto_accepted`

- Auto evaluator reviewed the answer and found no meaningful issue
- No repair required

### `tighten_only`

- The answer is basically correct
- Completion Guard saw minor scope, hedging, or wording cleanup opportunities
- No visible repaired answer should be surfaced just for that
- This should not be treated as a new operational lesson by itself

### `repaired`

- A repair pass found a materially better answer
- The repaired result used new evidence, a meaningfully different tool path, or a verified action/artifact update
- This is the case reflections should learn from as a first-pass correction opportunity

### `unresolved`

- A repair pass ran but could not reliably finish the task

### `ticket_created`

- Unresolved after repair, so Jarvis logged a follow-up ticket

### `cancelled`

- Repair was started but stopped before settlement

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

## Why Repair Can Work Without Starting Over

A fair concern is:

`If the same LLM sees the same info, won't it just give the same wrong answer again?`

Sometimes yes. That is why the repair pass must be materially different from the first pass.

Repair should change at least one of these:

- the objective
- the constraints
- the evidence requirements
- the tool-selection policy
- the failure context injected into the prompt

### First Pass Objective

Usually:

- answer the user
- choose tools if needed
- be concise enough for Jarvis output rules

### Repair Pass Objective

Instead:

- identify what was wrong or missing
- verify concrete claims before repeating them
- prefer evidence over fluency
- call one missing validation step if needed
- fix or retract unsupported claims

### What Makes The Repair Pass Different

The repair pass should receive:

- the original query
- the full raw answer
- the user's rejection note
- explicit evaluator findings
- prior tool outputs
- explicit instruction to avoid repeating unsupported claims

This creates a different task:

`Do not answer from scratch. Audit the prior answer, identify unsupported claims, verify if possible, then correct it.`

That is a very different prompt than the normal routing pass.

### Verification Rules For Repair

Repair should follow stricter rules than the main answer:

- If a claim is time-sensitive, verify it
- If a claim says something is unavailable, deprecated, removed, or shut down, verify it
- If a claim says an artifact was created, confirm the artifact exists
- If a claim updates external state, confirm the state change actually happened
- If a research answer sounds definitive, ensure evidence actually supports it

### Why Same Runtime Helps Repair

Because the repair loop can use:

- exact failed claim text
- exact tools already used
- exact data already gathered
- exact missing artifact or missing evidence

This often lets Jarvis repair by:

1. correcting the wording using existing facts
2. running one small validation step
3. updating the final answer or canvas output

instead of restarting the entire workflow.

## Example Failure: Sora API "Shutdown" Claim

Real-world style example from web conversation `ea584146`:

### User Request

The user asked about the Sora API.

### Bad First Result

Jarvis responded that Sora API was shut down, gave a date, and created a canvas page reflecting that conclusion.

### What Was Actually Wrong

- the answer overstated the situation
- it treated an announcement as if there were a confirmed hard cutoff
- it created a downstream artifact based on an unverified claim
- it did not run a direct validation step even though tools were available

### User Correction

The user proved the claim was wrong by successfully generating a Sora video, then had to ask again to get the canvas fixed.

### What Completion Guard Should Have Done

When the answer included a strong time-sensitive shutdown claim, Completion Guard should have flagged this as high risk:

- "service is shut down"
- "API no longer works"
- "cutoff already happened"

The repair pass should then have done one of the following:

1. Re-check the exact claim against the source wording
2. Use a validation step such as a lightweight API probe or authenticated check if available
3. Fall back to softer, evidence-supported wording:
   - "there was an announcement"
   - "I do not yet have proof of an enforced cutoff"
   - "service availability should be validated before stating it is shut down"

### Better Repair Result

Instead of repeating the incorrect claim, the repaired result should say something like:

- there was an announcement affecting Sora/API access
- the prior answer overstated that as a confirmed shutdown
- I do not have evidence of a hard cutoff from the steps taken so far
- if needed, I can verify live status with a direct check before updating the canvas

### Important Lesson

This example shows why Completion Guard must inspect the full raw answer and claims, not just the short spoken summary. The short voice-safe answer may hide exactly the details that need auditing.

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
COMPLETION_GUARD_EXCLUDED_TOOLS=phone_call,send_email,create_reminder,create_alert
JARVIS_COMPLETION_GUARD_EVAL_PROVIDER=
JARVIS_COMPLETION_GUARD_EVAL_MODEL=
```

Web UI should support per-mode override like other AI Config settings.

### Web Config Schema

Recommended `web_config.json` shape:

```json
{
  "cloud": {
    "completion_guard_enabled": true,
    "completion_guard_mode": "manual",
    "completion_guard_max_repairs": 1,
    "completion_guard_auto_threshold": 0.7,
    "completion_guard_require_user_confirm": true,
    "completion_guard_ticket_on_fail": true,
    "completion_guard_show_ui_prompt": true,
    "completion_guard_include_qa": true,
    "completion_guard_include_tool_tasks": true,
    "completion_guard_eval_provider": "",
    "completion_guard_eval_model": ""
  },
  "local": {
    "completion_guard_enabled": false,
    "completion_guard_mode": "manual"
  }
}
```

Recommended UI location:

- Jarvis Web
- Settings
- AI Config tab

Recommended controls:

- Enable Completion Guard
- Mode: Off / Manual / Auto
- Max Repairs
- Auto Threshold
- Require User Confirm
- Create Ticket On Failure
- Show UI Prompt
- Include QA Responses
- Include Tool Tasks
- Excluded Tools (optional env-driven list)
- Eval Provider override
- Eval Model override

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

### Suggested Card States

- `idle`
- `awaiting_user`
- `repairing`
- `repaired`
- `accepted`
- `cancelled`
- `ticket_created`
- `error`

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

The raw answer is more important than the `speech` field.

### Repair Prompt Goal

The repair model should answer:

1. What specifically was incomplete or incorrect?
2. Can this be repaired using existing context and tool outputs?
3. If more work is needed, which tool or step should happen next?
4. Produce a corrected final result, or produce a clear unresolved failure reason

### Suggested Repair Prompt Rules

- Do not answer from scratch
- Audit the prior answer first
- Identify unsupported or overstated claims
- Prefer correcting the smallest broken step
- Only call another tool if verification or a missing step is clearly required
- If you cannot verify a strong claim, soften or retract it
- If a prior artifact such as canvas content is now known to be wrong, propose the exact correction
- Never repeat a strong factual claim unless the available evidence supports it

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
- choosing whether to inspect `raw_llm_response` vs `speech`

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

## Socket Event Flow

Recommended websocket events:

- `completion_guard:prompt`
- `completion_guard:respond`
- `completion_guard:repair_start`
- `completion_guard:repair_complete`
- `completion_guard:ticket_created`
- `completion_guard:error`

### Event Payload Sketch

`completion_guard:prompt`

```json
{
  "message_id": "msg_123",
  "conversation_id": "ea584146",
  "mode": "manual",
  "expires_in_ms": 5000,
  "can_add_note": true
}
```

`completion_guard:respond`

```json
{
  "message_id": "msg_123",
  "conversation_id": "ea584146",
  "accepted": false,
  "note": "The shutdown claim looks wrong. Verify live API status first."
}
```

`completion_guard:repair_start`

```json
{
  "message_id": "msg_123",
  "repair_attempt": 1
}
```

`completion_guard:repair_complete`

```json
{
  "message_id": "msg_123",
  "repair_attempt": 1,
  "success": true,
  "summary": "Corrected unsupported shutdown claim and updated final answer."
}
```

`completion_guard:ticket_created`

```json
{
  "message_id": "msg_123",
  "ticket_path": "logs/completion-guard/2026-03-30-001-completion-guard.md"
}
```

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

### Task State Object

Recommended per-message state to preserve:

- message id
- conversation id
- original transcript
- enhanced transcript after auto-context
- `raw_llm_response`
- `speech`
- tools used
- accumulated tool data
- available tools
- retry count
- repair count
- provider/model/mode
- progress events emitted
- stash/canvas refs
- evaluator result
- user completion response

That state object is what allows same-runtime continuation instead of a synthetic restart.

## Implementation Checklist

### Phase 1: UX + Ticketing

- [x] Add env config keys
- [x] Add Web UI AI Config overrides
- [x] Add completion card component in chat UI
- [x] Add websocket events for prompt and response
- [x] Add markdown ticket writer
- [x] Log completion-guard outcomes

### Phase 2: Manual Repair

- [x] Accept user `Yes/No` and optional note
- [x] Run one bounded repair pass
- [x] Feed `raw_llm_response` into repair instead of condensed speech
- [x] Emit repair progress and final repaired result
- [x] Write ticket on unresolved repair
- [x] Add repair-strategy classifier
- [x] Add tool-family hints to repair prompt
- [x] Add synthesize-from-existing-tool-result fallback
- [x] Skip workflows and fire-and-forget/sensitive tools

### Phase 3: Remaining Work

- [x] Add real auto mode evaluator
- [x] Score risk of incomplete/incorrect result before finalizing
- [x] Trigger repair automatically above a threshold
- [x] Feed accepted/repaired/ticketed outcomes into intelligence analysis
- [ ] Persist unanswered manual Completion Guard prompts across refresh
- [ ] Add issue clustering and recurring-failure reporting

## Repair Evaluation Heuristics

Useful high-risk heuristics:

- strong time-sensitive claims: "shut down", "removed", "deprecated", "no longer works"
- claims of external side effects: "created", "updated", "sent", "saved"
- claims of absence: "couldn't find", "no results", "nothing available"
- answers with zero evidence on research-heavy questions
- mismatch between tool outputs and final answer
- canvas/stash artifact created from an unsupported conclusion

These heuristics should be enough for an MVP before building a sophisticated evaluator.

## Recommended Rollout

### Phase 1

- Design doc
- env flags
- UI setting
- manual completion prompt card
- ticket generation only

### Phase 2

- bounded manual repair pass
- one retry max
- user rejection note fed into repair prompt
- repair strategy hints and synthesis fallback

### Phase 3

- evaluator-based auto triggering
- auto-threshold override in AI Config
- intelligence/reflection outcome bridge
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

Best current next implementation:

1. Persist unanswered manual cards across refresh
2. Add clustering/reporting for recurring completion failures
3. Add a small Completion Guard dashboard or log view
4. Move from same-conversation replay toward true in-flight continuation

That would move Completion Guard from a useful manual recovery loop into a broader self-improving system.
