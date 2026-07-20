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

As of April 14, 2026, Completion Guard is implemented and in use in Jarvis Web, with a clearer distinction between:

- accepted answers
- wording-only tightening
- true repaired outcomes
- unresolved/ticketed failures

Implemented now:

- AI Config settings for enabling/disabling Completion Guard in the Web UI
- Manual mode with inline `Completed correctly? Yes / No` card
- Auto mode with a background evaluator that scores the raw final answer
- Configurable auto-repair threshold (`JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD`) with Web UI override support
- Auto mode uses a structured audit plus deterministic repair scoring instead of trusting a bare self-reported confidence value
- When the auto evaluator JSON returns **`recommended_action: "tighten_only"`** (minor hedging/wording only), the turn settles as **`auto_accepted`**—no repair run, and the persisted status is not labeled `tighten_only` (see `_completion_guard.evaluator_recommended_action`). The name **`tighten_only`** is reserved for **post-repair** settlement when a repair actually ran but did not change tools/evidence materially
- **Effective evidence** (`data['_effective_evidence']` on saved assistant messages): structured grounding for the auto-evaluator, including follow-ups that reuse prior tool results without a new skill call; see [Effective evidence (grounding bundle)](#effective-evidence-grounding-bundle)
- **Provider-native** (`server_side_tools`) usage counts as a fresh evidence epoch for that bundle (not only `tools_used`)
- **Repair classification**: a repair pass is classified as substantive `repaired` only when `operational_correction` is true (tool-path delta and/or evidence delta). **Similar-answer rule**: if the tool path did not change and the repaired answer is very similar to the original (see below), the outcome is forced to **`tighten_only`** even when JSON `data` churn would otherwise make `evidence_delta` look true
- No-tool rewrite repairs still default to `tighten_only` unless the repaired answer clearly cites a direct source or verified action
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
- Expired/superseded manual cards also update the linked experience with neutral Completion Guard metadata
- Successful repairs now fold the corrected answer, corrected tools, and corrected tool results back into the original experience record
- Internal repair runs no longer create separate first-class learning experiences
- In Jarvis Web, explicit feedback runs are gated behind Completion Guard settlement so feedback grades the settled result instead of a mid-repair snapshot
- Orchestrator-side random feedback sampling is disabled while Web Completion Guard is active, preventing pre-collected random feedback from racing manual/auto guard settlement
- Feedback prompts now receive Completion Guard metadata and the async web feedback path updates the linked experience record
- Rewrite-only tighten passes do not fold a corrected path back into the original experience as if they were a true operational fix
- The auto evaluator can use a different provider/model than the main chat model; by default it follows `JARVIS_COMPLETION_GUARD_EVAL_PROVIDER` then `FEEDBACK_PROVIDER`
- Jarvis Web AI Config now exposes per-mode Completion Guard eval provider/model overrides
- The **Completion Guard evaluator** and the **repair pass** are separate model paths:
  - the evaluator/judge uses `JARVIS_COMPLETION_GUARD_EVAL_PROVIDER` + `JARVIS_COMPLETION_GUARD_EVAL_MODEL`
  - the repair pass still runs through the normal orchestrator/runtime for that conversation, so it uses the active chat provider/model unless explicitly changed in the future
  - this means server logs may show the main provider/model for repair activity even when the guard evaluator itself is using a different judge model
- Ollama cloud judge models are now handled more defensively for auto eval:
  - cloud models use plain JSON mode instead of full schema mode
  - cloud JSON eval calls get a larger `num_predict` budget so internal reasoning does not consume the whole response budget
  - if a cloud model still returns empty `message.content`, the provider can fall back to `message.thinking` as a compatibility safety net
- Manual Completion Guard cards are intentionally current-turn UI:
  - unanswered manual prompts expire after `JARVIS_COMPLETION_GUARD_MANUAL_TTL_SECONDS` seconds (default: 600)
  - the Web UI shows a small countdown on active manual cards
  - when the user continues the same conversation before answering, older pending manual prompts settle as `superseded`
  - if a mobile/PWA reconnect leaves a stale card visible, submitting it now resolves as `expired` instead of surfacing a hard error

Not implemented yet:

- true same-in-flight orchestrator continuation
- persistence/re-hydration of still-active unanswered manual cards across refresh
- dashboard/reporting for Completion Guard outcomes

## Effective evidence (grounding bundle)

Jarvis’s normal chat turn sees **recent conversation history** plus compact **`tool_results`** extracted by `jarvis-web/server/services/followup_extractor.py`. Completion Guard’s auto-evaluator, by default, sees a **single turn record** (query, raw response, speech, tools, `data`). Without alignment, a no-tool follow-up that reuses Yelp or search results can look like “zero grounding” to the judge.

**Effective evidence** fixes that on the **saved message**:

- Stored at `data['_effective_evidence']` on each assistant message (version field `v: 1`).
- **Tool turns** (non-empty `tools_used` or provider-native tools in `server_side_tools`): rebuild from structured `data` using `extract_followup_data()` with a higher candidate cap for ranked lists than the default follow-up context (e.g. top-N follow-ups). Native tools are recorded under `supporting_tool_results.native_tools` (raw `server_side_tools` plus normalized names) because that key is excluded from generic extraction.
- **No-tool turns**: may **inherit** the nearest prior bundle from earlier assistant messages (bounded backscan) only when a **refinement heuristic** matches (e.g. “sorry”, “top 5”, “those results”). Short unrelated questions do **not** inherit, so stale Yelp/Amazon grounding is not copied onto a new task.
- **Follow-up extraction** accepts **list-shaped** tool payloads (list of dicts) by normalizing to `results[]` without a per-tool allowlist.

The auto-eval prompt includes:

- A dedicated **Effective evidence** JSON block (truncated).
- **Structured result data** (full `data`, truncated).
- Rules that **native provider tools** are real usage; **`supporting_tool_results`** may ground an answer even when `tools_used` is empty on a refinement turn.

Implementation reference: `ChatHandler._compute_effective_evidence` and `_evaluate_completion_guard_auto` in `jarvis-web/server/sockets/chat.py`, with extraction logic in `jarvis-web/server/services/followup_extractor.py`.

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
- if Completion Guard is active, explicit Web feedback (`📊` toggle or `--feedback`) is deferred until the response settles as:
  - `accepted`
  - `auto_accepted`
  - `tighten_only`
  - `repaired`
  - `unresolved`
  - `ticket_created`
  - `cancelled`
  - `expired`
  - `superseded`
- random feedback sampling (`FEEDBACK_RANDOM_ENABLED` / `FEEDBACK_RANDOM_CHANCE`) can pre-collect feedback in normal orchestrator runs, but Jarvis Web temporarily disables that random path while Completion Guard is enabled so guard settlement remains the single coordination point

This prevents feedback from grading a temporary first-pass answer that is about to be repaired.

When feedback finally runs, it receives Completion Guard context so it can:

- avoid penalizing the system just because Completion Guard exists
- treat `tighten_only` like a basically accepted answer with minor wording cleanup
- grade the repaired answer as the settled result when repair succeeds
- understand that `ticket_created` means the system recognized a failure but could not fully recover
- treat `expired` and `superseded` as neutral manual prompt settlement, not user dissatisfaction

## Outcome Meanings

### `accepted`

- Manual user confirmation that the original answer was good
- No repair required

### `auto_accepted`

- Auto evaluator reviewed the answer and **no repair pass was started** (e.g. `recommended_action: accept`, or `repair_score` below threshold, or judge JSON **`tighten_only`** which settles here without rewriting)
- No repair required
- If the judge JSON says **`recommended_action: "tighten_only"`** (wording/hedging only), the stored status is still **`auto_accepted`**; the full evaluation lives in **`_completion_guard.auto_evaluation`**, and **`_completion_guard.evaluator_recommended_action`** is **`tighten_only`** for analytics. The Web UI does not show a “Tightened only” card for this case (same as other `auto_accepted` turns)

### `tighten_only`

Use this label **only** when a **repair pass actually ran** and the outcome was rewording / no operational delta:

- Unlike **`repaired`**, **`tighten_only`** does not add a second assistant message for the repair content (`chat.py`: `if not tighten_only:` before `add_message` for the repair response)
- This should not be treated as a new operational lesson by itself

Settlement is **`tighten_only`** when the repair did **not** materially change tools or evidence (including the **similar-answer rule**):

- **`ChatHandler._completion_guard_tighten_instead_of_substantive_repair`**: if `tool_path_delta` is false and **answer similarity** is at or above **`_CG_TIGHTEN_ONLY_ANSWER_SIMILARITY_THRESHOLD` (0.88)**, `operational_correction` is cleared so the run is **not** labeled **`repaired`**. This avoids treating JSON `data` churn as substantive evidence when the prose and tool path are effectively the same.

The auto-evaluator **prompt** still asks the judge to prefer JSON **`tighten_only`** over **`repair_required`** for disclaimer/hedging-only gaps; that maps to **`auto_accepted`** at settlement, not to the **`tighten_only`** status above.

### `repaired`

- A repair pass found a materially better answer
- The repaired result used new evidence, a meaningfully different tool path, or a verified action/artifact update (see `_analyze_completion_guard_delta`: `operational_correction` = `tool_path_delta` or `evidence_delta`, subject to the similar-answer override above)
- This is the case reflections should learn from as a first-pass correction opportunity

### `unresolved`

- A repair pass ran but could not reliably finish the task

### `ticket_created`

- Unresolved after repair, so Jarvis logged a follow-up ticket

### `cancelled`

- Repair was started but stopped before settlement

### `expired`

- A manual prompt timed out, or a stale mobile/PWA card was submitted after the session context was gone
- The card becomes inactive and is persisted as neutral Completion Guard metadata
- This is not treated as user dissatisfaction, failure, or retry by itself

### `superseded`

- The user continued the conversation before answering the manual prompt
- The older card becomes inactive and is persisted as neutral Completion Guard metadata
- This is not treated as user dissatisfaction, failure, or retry by itself

```mermaid

Auto-eval JSON returned + parsed
│
├─ Settled as auto_accepted (e.g. judge hedging-only path, or repair_score < 0.89)
│    → NO repair, threshold / JSON text similarity not used for “second message”
│
└─ Else repair_score >= 0.89
     → Run ONE repair pass
          │
          └─ After repair, classify delta:
               - tool_path_delta / evidence_delta / answer_similarity
               → repaired vs tighten_only (second assistant message or not)
```

## Evaluator Provider Notes

Completion Guard auto evaluation can run on a different provider/model than the main response model.

The evaluator and synthesis helpers use **`record.get('mode', 'cloud')`** explicitly for provider selection, model overrides, and **location context** (`_get_completion_guard_location_context`), so the judge does not rely on an undefined `mode` variable.

Current precedence:

1. `JARVIS_COMPLETION_GUARD_EVAL_PROVIDER` / `JARVIS_COMPLETION_GUARD_EVAL_MODEL`
2. Web UI per-mode AI Config overrides
3. `FEEDBACK_PROVIDER`
4. the main chat provider/model

This lets Jarvis do things like:

- main chat on xAI
- Completion Guard eval on OpenAI or Ollama
- feedback grading on a separate provider

### Ollama Cloud Notes

Some Ollama cloud models expose internal reasoning in `message.thinking` and may spend a large portion of the output budget there before producing final content.

What Jarvis does now for Completion Guard eval:

- uses JSON mode for cloud Ollama judge calls
- increases the output budget so the model still has room to return final JSON
- keeps `message.thinking` fallback only as a defensive compatibility path, not as the primary design target

The main fix is the larger token budget. The `message.thinking` fallback is there for edge cases and debugging if a cloud model still returns empty `message.content`.

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

## Current Configuration

Environment variables:

```bash
JARVIS_COMPLETION_GUARD_ENABLED=false
JARVIS_COMPLETION_GUARD_MODE=manual
JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD=0.89
JARVIS_COMPLETION_GUARD_TICKET_ON_FAIL=true
JARVIS_COMPLETION_GUARD_SHOW_UI_PROMPT=true
JARVIS_COMPLETION_GUARD_MANUAL_TTL_SECONDS=600
JARVIS_COMPLETION_GUARD_INCLUDE_QA=true
JARVIS_COMPLETION_GUARD_INCLUDE_TOOL_TASKS=true
COMPLETION_GUARD_EXCLUDED_TOOLS=phone_call,send_email,create_reminder,create_alert
JARVIS_COMPLETION_GUARD_EVAL_PROVIDER=
JARVIS_COMPLETION_GUARD_EVAL_MODEL=
```

Jarvis Web supports per-mode overrides for these settings. Repair remains
bounded to one pass in code; there is no `MAX_REPAIRS` environment setting.
Ticket storage is owned by the Web conversation/debug flow rather than a
configurable `TICKET_DIR` variable.

### Web Config Schema

Current `web_config.json` shape:

```json
{
  "cloud": {
    "completion_guard_enabled": true,
    "completion_guard_mode": "manual",
    "completion_guard_auto_threshold": 0.7,
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

UI location:

- Jarvis Web
- Settings
- AI Config tab

Available controls:

- Enable Completion Guard
- Mode: Off / Manual / Auto
- Auto Threshold
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
  "expires_in_ms": 600000,
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
- [x] Effective evidence bundle + native-tool epoch + similar-answer tighten classification (see [Effective evidence](#effective-evidence-grounding-bundle))
- [x] Expire/supersede stale unanswered manual Completion Guard prompts
- [ ] Persist/re-hydrate still-active unanswered manual Completion Guard prompts across refresh
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
