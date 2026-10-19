# Completion Guard

Completion Guard reviews a completed Jarvis Web answer and can run one repair
attempt when the answer is incomplete or unsupported. You can review answers
yourself with **Completed correctly? → Yes / No**, or enable automatic evaluation.
Unresolved repairs can produce a local Markdown ticket for troubleshooting.

The guard checks the full answer and available tool evidence, including claims
that files were created, actions were completed, or a search found no results.
It is an additional check, not a guarantee that every incorrect answer will be
detected. Evaluation and repair can add model calls, latency, and provider costs.

## Modes

Configure Completion Guard in **Jarvis Web → Settings → AI Config** for the
selected cloud or local mode.

| Mode | Behavior |
| --- | --- |
| Off | No completion prompt, evaluator, or repair. |
| Manual | Eligible answers show **Completed correctly?**. **Yes** accepts the answer; **No**, with an optional note, requests one repair attempt. |
| Auto | A background evaluator audits eligible answers. A sufficiently high repair score triggers one repair attempt. Wording-only findings are accepted without a repair. |

Manual cards have a countdown and expire after the configured lifetime. Sending
another message in the same conversation supersedes an unanswered card. Expiry
and supersession are neutral outcomes; neither means you rejected the answer.

During repair, the normal Web **Stop** control and conversation overlap
protection apply. Stopping remains cooperative and cannot undo actions a tool
already completed. See [Web task recovery](WEB_TASK_RECOVERY.md).

## Current configuration

The following example enables manual reviews. The mode templates in
`config/cloud.env.example` and `config/local.env.example` contain these settings:

```bash
JARVIS_COMPLETION_GUARD_ENABLED=true
JARVIS_COMPLETION_GUARD_MODE=manual
JARVIS_COMPLETION_GUARD_AUTO_THRESHOLD=0.89
JARVIS_COMPLETION_GUARD_TICKET_ON_FAIL=true
JARVIS_COMPLETION_GUARD_SHOW_UI_PROMPT=true
JARVIS_COMPLETION_GUARD_MANUAL_TTL_SECONDS=600
JARVIS_COMPLETION_GUARD_INCLUDE_QA=true
JARVIS_COMPLETION_GUARD_INCLUDE_TOOL_TASKS=true
COMPLETION_GUARD_EXCLUDED_TOOLS="phone_call,send_email,create_alert,printer,send_webhook,ssh_remote,generate_video,generate_image,generate_music,workflow"
```

Web supports per-mode overrides for enablement, mode, threshold, ticket creation,
prompt visibility, QA/tool eligibility, and evaluator provider/model. The
exclusion list and manual-card lifetime are environment settings. Restart Web
after changing its environment configuration.

The automatic threshold controls whether a scored finding starts a repair.
Higher values produce fewer repairs; lower values are more aggressive. It does
not reduce how often eligible answers are evaluated. An evaluator recommendation
of `tighten_only` settles without repair regardless of that score.

Template values and missing-setting fallbacks differ: without an explicit
setting, the code disables the guard and uses `0.70` as the threshold. Settings
shows the effective value for the selected mode. Prefer the shipped templates
and Web settings over copying a complete configuration from another installation.

Web overrides are stored in `jarvis-web/config/web_config.json`. A partial example
is:

```json
{
  "cloud": {
    "completion_guard_enabled": true,
    "completion_guard_mode": "manual",
    "completion_guard_auto_threshold": 0.89,
    "completion_guard_ticket_on_fail": true
  },
  "local": {
    "completion_guard_enabled": false
  }
}
```

There is no `MAX_REPAIRS` or `TICKET_DIR` environment setting. The repair limit
is one pass per response; Web owns ticket storage.

## Eligibility and safety boundaries

QA answers and tool tasks have separate inclusion settings. A turn containing
an excluded tool bypasses Completion Guard. The built-in exclusions are
`phone_call`, `send_email`, `create_alert`, `opencode`, and `workflow`; the
environment list adds exclusions and cannot remove that built-in set.

Recognized slash-command and autonomous workflow results also bypass manual
prompting and automatic evaluation. Replaying a deterministic workflow could
repeat its side effects. Background admission receipts likewise do not count as
completed tasks for review or repair; their jobs use the separate
[background-task lifecycle](BACKGROUND-TASKS.md).

These controls do not make every ordinary repair read-only. For eligible tasks,
a repair may call enabled tools to verify facts or correct an artifact, subject
to the normal tool permissions and Web approval controls. Chat-only turns and
attempted reminder creation have the stricter rules below.

### Chat-only turns

The sticky `#chat_only` mode keeps its no-tools policy throughout evaluation
and repair. Zero tool calls and the absence of live retrieval are intentional,
not failures. A repair can improve reasoning, completeness, or correctness from
the supplied context; it cannot search, inspect files, use hosted tools, or
update artifacts.

If a fact needs evidence unavailable in that context, the answer must state the
limitation. A material QA correction can count as `repaired` without a tool call.
See [Chat-only mode](JARVIS_WEB_UI.md#chat_only-sticky-no-tools-chat).

## What evaluation and repair use

Automatic evaluation focuses on `raw_llm_response`, structured result data, and
the effective evidence bundle. The shorter `speech` field is additional context;
speech condensation and word limits alone are not evidence of an incomplete
answer.

The evaluator returns a structured audit of missing requirements, unsupported
claims, contradictions, evidence gaps, and whether repair is worthwhile.
Deterministic scoring converts those findings into the repair score rather than
trusting a model's confidence number alone. An unparseable evaluator response
does not authorize a repair.

A repair is a **new bounded orchestrator pass in the same conversation**, using
the original response's mode, main chat provider, and model. It receives the
original query, raw answer, delivery text, prior tool names, bounded structured
data, and the user or evaluator note. Strategy hints direct it toward the missing
verification or correction; it can also synthesize an answer from returned data.
It does not resume the original in-flight orchestrator instance or preserve all
of that instance's transient state.

The guard distinguishes a substantive correction from a rewrite by comparing
tools, evidence, and answer content. A nearly identical answer with the same tool
path is classified as wording-only even if structured JSON changed. Ordinary
no-tool rewrites also settle as wording-only unless the result clearly cites a
direct source or verified action. Chat-only material corrections retain the
exception described above.

## Effective evidence (grounding bundle)

Follow-up questions can reuse earlier results without running another tool.
The saved assistant message carries `data._effective_evidence` (`v: 1`) so the
evaluator can recognize that grounding:

- Tool turns rebuild the bundle from structured results. Native provider tools
  in `server_side_tools` count as fresh evidence and are included under
  `supporting_tool_results.native_tools`.
- No-tool refinements such as “top five” can inherit a nearby earlier bundle
  through a bounded scan and refinement check. Unrelated short questions do not
  automatically inherit old results.
- List-shaped tool payloads are normalized into `results[]` without a per-tool
  allowlist. Ranked-list extraction can retain more candidates than the normal
  compact follow-up context.

The evaluator receives bounded excerpts of this bundle and structured result
data. It also receives configured location context. A Tool RAG schema shortlist
is a partial selection, so a tool absent from that shortlist is not necessarily
disabled.

Implementation references:
[Completion Guard policy](../jarvis-web/server/services/completion_guard.py),
[Web handler](../jarvis-web/server/sockets/chat.py), and
[follow-up extraction](../jarvis-web/server/services/followup_extractor.py).

## Built-in reminder review

`create_reminder` is eligible for manual prompting and automatic evaluation when
Completion Guard and tool-task reviews are enabled. An explicit environment
exclusion still takes precedence.

Reminder evaluation compares the requested **notification schedule** with saved
IDs, schedules, subjects, and current statuses:

- A noon reminder about a 2 p.m. appointment requests one noon notification.
  The guard must not invent lead time or treat the appointment time as another
  requested reminder.
- Equivalent local/UTC instants are compared as the same time. A representation
  difference alone is not a wrong schedule.
- An exact call blocked by the duplicate guard or a reused reminder ID is not
  another saved reminder. Explicitly requested separate notifications and
  bounded daily schedules may legitimately create several rows. Canceled rows
  do not count as extra active notifications.
- Google Calendar sync is optional. A missing or failed sync does not invalidate
  the local reminder or authorize another Calendar event.
- Wrong schedules, extra notifications, and misleading success claims are
  substantive failures. Clearer wording does not correct persisted state.

After any attempted reminder creation, **repair is read-only**. The executor
permits only `list_reminders`, including for mixed tasks containing a reminder
attempt or an attempt recorded only in the saved trace. It cannot create,
cancel, replace, or update a reminder or write through Calendar, workflows, or
other tools. Chat-only remains stricter and permits no tools at all. An empty
or default-ten-row listing cannot prove that a reminder is absent.

Router commentary in the saved trace is unverified audit context. It may help
identify a mismatch, but is not evidence that state changed. Receipt-based
reminder confirmations suppress that commentary; mixed-action replies may
contain it. It is excluded from ordinary follow-up extraction and repair
evidence-delta comparisons.

If incorrect or extra reminders remain scheduled, the review must remain
unresolved and explain the saved state and correction needed. **Correct the
reminder in a separate user request or in the Memory UI.** The guard never
silently retries the original creation.

Older installations may explicitly exclude `create_reminder` in
`COMPLETION_GUARD_EXCLUDED_TOOLS`. Remove only that entry to enable reminder
review, retain the other exclusions, and restart Web. Private mode files are not
automatically migrated.

## Outcome meanings

| Stored status | Meaning |
| --- | --- |
| `accepted` | You accepted the original answer; no repair ran. |
| `auto_accepted` | Automatic evaluation did not start a repair. This includes a wording-only `tighten_only` recommendation from the evaluator. |
| `tighten_only` | A repair ran but did not materially improve the tool path or evidence. Its rewrite is not appended as another assistant answer. |
| `repaired` | A repair produced a substantive correction through changed tools/evidence, a verified result, or a material Chat-only answer correction. |
| `unresolved` | The repair could not reliably finish the task. |
| `ticket_created` | An unresolved result was saved as a local troubleshooting ticket. |
| `cancelled` | Repair stopped before settlement. |
| `expired` | The manual card timed out or its retained review context was unavailable. |
| `superseded` | A new user turn replaced the unanswered manual review. |

An evaluator's `recommended_action: "tighten_only"` and a stored status of
`tighten_only` are different: the first avoids a repair; the second describes a
repair that already ran. The original recommendation remains in
`_completion_guard.evaluator_recommended_action` and the complete audit in
`_completion_guard.auto_evaluation`.

## Evaluator provider notes

The automatic evaluator can use a different model from the main answer and
repair pass:

```bash
JARVIS_COMPLETION_GUARD_EVAL_PROVIDER=openai
JARVIS_COMPLETION_GUARD_EVAL_MODEL=
```

The Web per-mode evaluator override takes precedence over these environment
settings. With no provider setting, the evaluator uses OpenAI in cloud mode and
Ollama in local mode. An explicit compatible model override wins; otherwise the
matching evaluator environment model or selected provider's mode-specific model
default is used. Changing providers does not carry an incompatible model across.
`FEEDBACK_PROVIDER` does not select the Completion Guard evaluator.

The evaluator is constructed with hosted tools disabled. Repair uses the original
answer's main chat provider/model, so seeing that model in repair logs is expected
even when the judge is different.

Ollama cloud evaluation uses JSON mode and a larger output budget to accommodate
models that spend tokens reasoning before returning JSON. If final content is
empty, the provider can recover a parseable JSON object from `message.thinking`;
it does not return the surrounding reasoning prose. These measures do not
guarantee that every model returns a usable audit.

## Completion Guard vs feedback system

Completion Guard decides whether to correct the current answer. Feedback grades
the settled result for learning and analysis. In Web, explicit feedback waits
for guard settlement so it does not grade an answer in the middle of repair.
Orchestrator random feedback sampling is disabled while Web Completion Guard is
active to avoid a second competing assessment path.

Guard outcomes update the original Intelligence experience. A substantive repair
can fold its corrected answer, tools, and results into that experience; the
internal repair prompt does not create a separate first-class learning
experience. Wording-only repairs do not become operational corrections.
Expired/superseded manual reviews are neutral metadata, not negative feedback.
Conversation exports retain Completion Guard metadata when available.

## Tickets and troubleshooting

Unresolved repairs write Markdown tickets under `logs/completion-guard/` when
ticket creation is enabled. Filenames include the timestamp, conversation ID,
and message prefix. Tickets can contain the query, note, raw/delivery text,
provider/model, tools, structured results, evaluator audit, and repair details.
Keep them private; the logs directory is gitignored. Review and redact a ticket
before sharing it publicly.

If no card or evaluation appears, check the selected mode's enablement and mode,
QA/tool inclusion settings, exclusions, and workflow/background eligibility.
If automatic review does not start a repair, inspect the audit and effective
threshold rather than assuming the evaluator did not run.

Review contexts are held in the current Web process, with up to 50 recent records.
Socket reconnect can restore a retained, unexpired review. A Web restart does not
reconstruct active review contexts; submitting a stale card settles it as expired.
Saved outcomes and tickets remain, but they cannot resume an expired repair.
There is no dedicated outcome dashboard or recurring-failure clustering.

## Contributor checks

From the repository root:

```bash
.venv/bin/python -m pytest tests/test_completion_guard_server_side_tools.py tests/test_chat_only_mode.py tests/test_intelligence_server_side_tools.py tests/test_web_task_recovery.py -q
```

These checks use isolated state and scripted model/provider behavior. They do
not establish the quality of a live judge or verify real provider cancellation.
Use [the full core suite](TESTING.md) for cross-component regression checks.
