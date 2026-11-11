# Optional Prompt Guard screening

Jarvis can screen selected tool results and model-bound text attachments with a separately hosted
[Prompt Guard service](https://github.com/bigsk1/prompt-guard). The shared client
is independent of the chat model. Cloud and local mode can both use the same
service, including a GPU service elsewhere on the LAN. Jarvis needs no local
inference packages, model weights, additional service, or database.

The check runs after a selected tool returns, before its result enters the next
model turn or workflow step. Text attachments and enabled summarizer source
inputs are checked immediately before their content reaches a model:

- **Clean scan:** return the original tool result unchanged.
- **Confirmed detection:** withhold the returned content, end the tool turn or
  workflow or current attachment request, and return a neutral explanation with
  an incident ID. No automatic retry, loop alternative, or Completion Guard
  repair follows that detection. A historical attachment excerpt is omitted
  with a neutral notice instead of stopping every later message in that chat.
- **Disabled, unavailable, timed-out, invalid, busy, or oversized scan:** continue
  with the original result. This is an unknown/unscanned result, never a clean
  verdict.

For tool results, the tool has already run when screening happens. A rejection does not undo its
side effects or claim the operation never ran. Existing completion facts are
preserved. When incident saving succeeds, the private report retains the exact
screened representation and recovery handles contained in it. Existing
permissions, approvals, and SSRF protections continue to apply.

## Configuration

Add settings to the selected `config/cloud.env` or `config/local.env` and restart
the Jarvis processes that execute tools. Fresh installations leave this off.
The two modes have independent opt-in flags; local mode supports this feature.

```dotenv
PROMPT_GUARD_ENABLED=false
PROMPT_GUARD_URL=http://your-prompt-guard-host:8188
PROMPT_GUARD_API_KEY=
PROMPT_GUARD_THRESHOLD=0.8
# Optional custom JSON selection, named policies and workflow exceptions:
# PROMPT_GUARD_POLICY_FILE=config/prompt_guard_policy.json
PROMPT_GUARD_TIMEOUT_SECONDS=2
PROMPT_GUARD_MAX_INPUT_BYTES=65536
# Optional; requires a scanner supporting the return_windows request field.
PROMPT_GUARD_RETURN_WINDOWS=false
PROMPT_GUARD_ALERTS_ENABLED=false
PROMPT_GUARD_ALERT_THRESHOLD=0.95
PROMPT_GUARD_ALERT_COOLDOWN_SECONDS=3600
# Optional base directory; Jarvis appends cloud/ or local/.
# PROMPT_GUARD_INCIDENT_DIR=logs/prompt-guard/incidents
PROMPT_GUARD_INCIDENT_RETENTION_DAYS=90
```

Set `PROMPT_GUARD_ENABLED=true` when ready to send selected result text to the
service. Jarvis calls `/v1/scan` on the configured base URL with bearer auth.
Use a trusted private network for HTTP, or HTTPS where transport encryption is
needed. In Docker, the address must be reachable from the Jarvis container.

With a scanner supporting window diagnostics, set
`PROMPT_GUARD_RETURN_WINDOWS=true` in each desired mode. The same scan then returns
per-window scores and token/character intervals for private incident evidence.
Leave this false for older scanners: they may reject the unfamiliar request field
with HTTP 422. Jarvis does not retry without it or issue a separate capability
request. Omitted diagnostics remain compatible with aggregate-only responses.
Roll back diagnostic capture by setting it false; scoring, input representation,
thresholds, and withholding rules are unchanged.

Tool selection now lives in JSON, rather than a comma-separated ENV value.
Copy `config/prompt_guard_policy.json.example` to
`config/prompt_guard_policy.json` and set `PROMPT_GUARD_POLICY_FILE` to that
private file. Both modes can use the same file or separate
`prompt_guard_policy.cloud.json` and `prompt_guard_policy.local.json` files.
An unset path uses the shipped example. Its shape is:

```json
{
  "v": 2,
  "tools": [
    "crawl_url",
    "source_library"
  ],
  "summarizers": {"enabled": true},
  "policies": {
    "web_content": 0.8,
    "document_text": 0.8,
    "high_risk": 0.7
  },
  "rules": []
}
```

The shipped example selects additional existing public-content tools and SSH
output. Names are exact, including hyphens in MCP names such as
`mcp_apify_search-actors`; wildcards are rejected. The `tools` array opts in
tools that should use the global threshold. Named policy assignments also opt
in tools, without a list entry. An empty `tools` array therefore leaves only
assigned tools selected. Review a tool's returned content before selecting it: results
are sent to another service. Email, calendar, memory and arbitrary MCP tools
are not selected by default.

`summarizers.enabled` is independent of that selection. It defaults to `true`
and applies only when the master `PROMPT_GUARD_ENABLED` flag is on. Set it to
`false` to pause source screening inside `text_summarizer` and Stash's
`remember(summarize=true)` helper while retaining selected returned-result and
Web attachment screening. Turning it off does not stop summaries themselves.

Existing installations must move every selected name from
`PROMPT_GUARD_TOOLS` into `tools`, remove that ENV entry, and upgrade an existing
v1 policy to the v2 shape above while retaining its `rules`. The CSV setting
is no longer read. JSON edits are reloaded for each check; ENV changes still
require restarting affected processes. A missing or invalid file selects no
tool results, logs `invalid_policy`, retains the global threshold, and defaults
the summarizer gate to `true`. An invalid file is never treated as a clean scan.

### Per-tool named policies

An optional top-level tool-manifest field enables result screening and selects
a named threshold:

```json
"prompt_guard_policy": "web_content"
```

This is operator-owned metadata beside `proxy_policy`, not a model argument.
There is no need to repeat the tool name in `tools`. For an MCP server, add the
same field to its existing server entry in `config/mcp-servers.json` to cover
all its tools. Per-tool `tool_metadata` can choose a different policy:

```json
{
  "prompt_guard_policy": "web_content",
  "tool_metadata": {
    "inspect_sensitive_result": {"prompt_guard_policy": "high_risk"}
  }
}
```

The example shows fields to merge into an existing server entry, retaining its
transport settings. Valid per-tool assignments override the server default;
missing, null or invalid assignments inherit it. Server assignment applies to
all returned tool results on that server, so review its content before opting
in. Remote MCP metadata, tool arguments and returned payloads cannot choose a policy.
An omitted MCP `enabled` field defaults to `true` for both tool discovery and
policy lookup. Set it explicitly to `false` to disable the server.
Restart processes that execute tools after changing manifest or MCP assignments
so their registered schemas use the same bindings. Threshold edits in the
Prompt Guard policy JSON continue to reload on each check.
Google Search starts with `web_content`; Stash and `text_summarizer` use
`document_text`. Both named thresholds start at `0.8`. A tool without a named
policy is screened only when listed in `tools`, then uses the global threshold
unless an exact rule overrides it. The master enable flag still applies to all
screening. Removing a name from `tools` does not disable its policy assignment;
remove the assignment too when that tool should no longer be screened.

The order is: matching workflow/profile rule, matching source-only rule, named
tool policy, then the mode's global threshold. Several tools can share a name
and be tuned in one place. Unknown policy names use the global threshold and
log `unknown_policy`; they never disable screening. Named policies are not
the same thing as RSS profile selectors or Jarvis tool-availability profiles.

### Scoped thresholds

The ENV threshold is the fallback for that mode. Higher thresholds block fewer
results; lower thresholds are more sensitive. Add entries to the JSON `rules`
array to override exact source types/names. Relative file paths resolve against
the project root; absolute paths work too. For example, these two entries
relax only the AI Status RSS digest and its article crawls:

```json
[
  {
    "id": "ai_status_rss",
    "source_type": "tool_result",
    "source_name": "rss_feed",
    "workflow_id": "rss_digest",
    "profile": "ai_status",
    "threshold": 0.9
  }, {
    "id": "ai_status_crawl",
    "source_type": "tool_result",
    "source_name": "crawl_url",
    "workflow_id": "rss_digest",
    "profile": "ai_status",
    "threshold": 0.9
  }
]
```

`ai_status` is an RSS profile, not a workflow ID. Other RSS profiles and ordinary
crawls keep the ENV threshold. The selection model consumes the screened feed
result; there is no separate classifier call for its prompt. The shipped v2
example has no exception rules; add these only when wanted.
Removing `workflow_id` and `profile` makes a rule
apply to that tool everywhere. Source type/name are mandatory exact selectors;
there are no wildcard matches. More workflow/profile selectors win, then the
first declared rule wins a specificity tie. Duplicate selectors/IDs and invalid
fields invalidate the file. Source-only rules also apply to tools outside a
workflow. A rule can use either numeric `threshold` or a named `policy`, never
both. A malformed file falls back as described above rather than activating
only the valid subset of rules.

Workflow identity and a configured RSS profile are captured before execution
in a mode-bound scope. Tool results and model-filled arguments cannot choose
their own policy. The scope resets on completion, errors, and nested workflows.
The executor carries its validated workflow snapshot into tool child processes,
so internal summarizer checks retain applicable workflow exceptions. Arguments,
saved text and result fields cannot forge that snapshot. To exempt a summarizer
input specifically, match `source_type: "model_input"` and
`source_name: "text_summarizer"` or `"stash_summary"` in a rule. Existing
`tool_result` rules keep their original returned-result scope.
Policy IDs and effective thresholds appear in scan metadata,
receipts, and private incidents. The scanner service needs no change.

### High-score block alerts

Set `PROMPT_GUARD_ALERTS_ENABLED=true` to create an ordinary high-severity Jarvis
alert for an actual block scoring at least `PROMPT_GUARD_ALERT_THRESHOLD` (default
`0.95`). This floor is independent of the block threshold: a result must first
have been scanned and withheld. Clean, unavailable, or skipped scans never alert.

Alerts contain only the source identifier, mode, score, thresholds, policy ID,
and incident ID when available. Flagged text, URLs, filenames, and source errors
are excluded. Identical mode/source/content hashes use the existing pending-alert
dedupe and a configurable cooldown (default one hour) for recently handled alerts.
Private incident records remain separate for each block.
The alert lock uses that same mode/source/content identity. Simultaneous repeats
contend with each other; distinct blocks can create their alerts during an
existing alert's speech.

The alert uses the normal high-severity `create_alert` path: persist it, wait for
speech through the existing status-audio cache, then mark it spoken on success.
The original mode/configuration stays active throughout delivery. Failed speech
leaves the durable alert available for normal follow-up. Alert, locking, and
speech failures cannot restore withheld content or retry the tool. No separate
speech thread, alert service, or database is added.

The client makes one direct request, with ambient proxies, netrc credentials,
redirects, and retries disabled. It runs in the parent process and does not add
scanner credentials to restricted tool child environments. Existing legacy
tools that inherit the full mode environment can still inherit these settings;
this feature does not change their environment policy.

## Incident evidence and investigation

Incident evidence has dedicated, mode-separated subfolders:

```text
logs/prompt-guard/incidents/cloud/2026-11-09-pg-<uuid>.json
logs/prompt-guard/incidents/local/2026-11-09-pg-<uuid>.json
```

Each incident is a separate JSON file, published atomically without overwriting
an existing record. The filename starts with the record's UTC creation date for
chronological sorting; the internal `pg-<uuid>` ID used by receipts and alerts
is unchanged. Older `pg-<uuid>.json` reports remain valid. Incident directories
have owner-only access (0700), and files
have owner-only read/write access (0600). The default log tree is gitignored and
excluded from Docker image builds. JSON quarantine files are not exposed by the
Web Log Explorer, enrolled in Stash, or injected into ordinary model context.

A report includes the incident ID, UTC timestamp, mode, tool name, score,
threshold, window coverage, validated service request/model identifiers,
execution summary, and exact scanned representation with SHA256. It also indexes
available request/result URLs, removing userinfo, sensitive query values, and
fragments. For multi-source results, these are **candidate source URLs**: a batch
classification does not establish which URL caused the detection.
New incidents also identify their source type (`tool_result` or `attachment`)
and the selected threshold policy. Older incident files remain readable.

When available, `scan.diagnostics` contains the validated version, representation,
aggregation, winning window index, and each window's score and token interval.
Character intervals use **Unicode code points** in the exact saved `evidence.text`,
with an exclusive end. For example, Python's `text[char_start:char_end]` selects the
region. JavaScript UTF-16 string indexes require conversion before highlighting.
If the tokenizer cannot map characters, token intervals and a known reason are
retained without inventing character positions. These regions locate a high
score; they do not identify a causal phrase or prove the content is malicious.

The client checks finite scores, window counts/order, max-score consistency,
winner/tie behavior, and interval bounds. It retains at most 128 windows within
the existing 32 KiB response limit. Incidents revalidate metadata against their
exact saved text and copy only reviewed fields. Missing, unsupported, or malformed
optional diagnostics are discarded while a valid aggregate verdict remains in
effect. A malformed JSON body or an oversized response still follows the existing
unknown/unscanned policy. Per-window scores and positions stay in private evidence;
no window text or arbitrary service metadata is copied into ordinary logs or model context.
The scan response supplies model identity/revision, but no tokenizer artifact hash;
Jarvis does not infer one or make a second request to obtain it.

The exact quarantined text can contain malicious instructions or sensitive
values, including credentials embedded in the original content. Treat it as
untrusted investigation evidence. Prompt Guard diagnostic logs contain only
metadata and the incident ID. Foreground and supervised background tool-call
logs record the screened result, so a detection's original speech and error are
withheld there too.
Existing argument logging and any logs or artifacts produced inside the tool
are separate from this check. The assistant's neutral notice identifies the
tool and incident; investigate that report explicitly with Codex or another
trusted operator rather than automatically rerunning the source tool.

If saving evidence fails after a confirmed detection, the content stays withheld
and the notice says the evidence could not be saved. The existing weekly
`cleanup-all` job expires incident JSON after 90 days by default. Set
`PROMPT_GUARD_INCIDENT_RETENTION_DAYS` to a positive number of days in each mode's
ENV file to change this. Cleanup checks each configured mode independently,
including its `PROMPT_GUARD_INCIDENT_DIR`, even when screening is disabled or the
scanner is offline. It uses the file's modification time, so both dated and
legacy incident names expire consistently. It does not read evidence text,
follow symlinks, or clean benchmark and archive directories.

Preview incident cleanup independently, or supply a one-off retention override:

```bash
./bin/cleanup-retention prompt-guard --dry-run
./bin/cleanup-retention prompt-guard --days 60 --dry-run
```

Remove `--dry-run` to apply it. An invalid retention setting stops incident
cleanup before any incident is removed. Dry runs do not create directories or
change permissions. A custom incident base directory remains private
configuration and should also stay out of Git and public file serving.

## Initial coverage

The selected result's `data`, `speech`, and `error` fields are screened. Tool
arguments are not sent to the classifier; only candidate URL fields are examined
locally for incident provenance. The observer never opens local files or fetches
URLs and Stash artifacts.

The shared foreground executor covers ordinary chat/voice/CLI/API orchestration
and workflow component calls. The default list excludes the workflow wrapper so
its component results are not scanned twice. Required and optional workflow
steps both stop on a confirmed detection, including looped steps.

Selected `stash` calls screen `read` results; selected `source_library` calls
screen `read` and `search` results. These names are included in starter settings.
Custom JSON can opt them in through `tools` or a named policy assignment. Saving,
listing, indexing, downloading, renaming, and deleting artifacts are unaffected.
Stash's URL, MIME, and filesystem checks remain separate from prompt screening.
Storing an artifact is not a clean verdict, and screening never automatically
resolves references in other tool results.

The Google Search tool uses the same boundary. Add `serpapi_google_search` to
the JSON `tools` array or assign its named policy to screen returned search previews
and saved `read_result` excerpts. The shipped example includes this name.
The tool can save the complete provider JSON before the returned preview is
screened; the scan does not open that saved archive or certify its omitted
sections. Local tools and MCP tools both require their exact selected names.

Web chat screens the text evidence it inserts from current attachments,
historical attachment excerpts, and legacy text context before orchestration or
upload vision starts. It does not screen the user's task instructions as source
evidence. This separate insertion boundary follows `PROMPT_GUARD_ENABLED`;
The JSON `tools` array and named assignments select tool results only. When enabled, Web bounds inserted
text to `PROMPT_GUARD_MAX_INPUT_BYTES` without splitting UTF-8 characters, then
screens exactly that excerpt. Omitted text is labeled as an excerpt and the
complete file stays in Stash. History also retains its existing 4,000-character
budget shared among text sources. Neither excerpt is a scan of the whole file.
Unavailable scans keep the excerpt under the existing fail-open policy.
The source selector for these text insertions is type `attachment`, name
`web_text`. A current-attachment block saves and delivers the neutral receipt,
ends the turn, and disables Completion Guard repair. A historical block omits
only that source's text, preserving the human message and other sources. Its
neutral notice prohibits inferring or automatically retrieving the withheld
contents; the current request can continue. The original attachment remains in
storage; withheld text is not copied into model context or the response/repair
record. A confirmed block records only its Stash reference and file hash in the
existing conversation JSON. That same saved source stays omitted from automatic
history, including during a later scanner outage. Attach a new upload to request
a fresh review. Other historical excerpts are screened again when reused, including
after a policy or classifier change, without locking the conversation.

Selected background results use the same review function at worker completion
and authenticated callback completion. This covers both `browser_use_cloud`
(worker-observed) and local `browser_use` (callback-observed), in either Jarvis
mode. The default list includes both browser tools; adding another reviewed
background tool's exact name opts its returned text into screening too.

Worker results are screened before terminal-result storage and delivery.
Callback events are accepted into the durable inbox first. Final callback
results are screened outside SQLite transactions; concurrent drainers are
serialized, and source credentials, execution ownership, conversation generation,
and deadlines are checked again before applying the result. Duplicate callbacks
retain their original identity and cannot launch the tool again.

A confirmed detection replaces the returned content with the incident receipt.
A known completion releases the running slot with a failed result presentation;
the operation's completion facts are retained. An already uncertain remote
operation remains `needs_attention` and retains its slot. Late replies deliver
the neutral incident notice directly, including after reload or delivery retry.
Neither a detection nor a scanner outage resubmits the job.
Requested cancellation reports are screened too, because retained task results
can enter later context. Cancellation stays cancelled and its late reply stays
suppressed, regardless of the verdict; clean partial artifacts remain available.

Coverage applies to the returned representation. A tool may already have
shortened a page or stored content in Stash before screening. Original accepted
callback bodies remain in the private durable inbox for authentication and
deduplication; quarantine is not their only storage location. Progress updates,
browser agents' internal observations, provider-hosted search, and APIs bypassing
these shared boundaries remain outside this integration. Other tools that fetch
and summarize internally need a reviewed hook before their own model call.
Direct artifact HTTP downloads remain downloads, not
model consumption. PDFs, OCR/transcription/vision output, provider-hosted search,
and external agents' internal observations need their own reviewed text-ingestion
hooks or selected result tools. This integration does not classify raw binaries
or claim that local storage makes source text trusted.

### Summarizer model inputs

With the master guard on and `summarizers.enabled: true`, `text_summarizer`
screens each actual source chunk before its helper model reads it, then screens
merged partial summaries before the final model call. This covers explicit
summarization, automatic Stash summaries and automatic YouTube transcript
summaries. Stash's separate `remember(summarize=true)` helper screens its actual
8,000-character source slice before its model call. These hooks use the same
scanner, thresholds, incidents and unknown/fail-open behavior as other inputs.
They apply regardless of which provider/model each helper uses, and do not
depend on selecting the summarizer for returned-result screening. Count,
keyword, sentiment and extractive operations make no helper-model call.

The shipped input budget is 64 KiB (65,536 bytes), enough for the normal
12,000-character chunk even when every character takes four UTF-8 bytes. The
same budget covers Stash's 8,000-character source slice. Existing explicit
budgets remain in effect. A smaller configured budget or a larger custom chunk
can still skip a scan: oversized source text is passed through under the
existing fail-open policy, never shortened and reported as fully screened.

Jarvis sends the resolved classification threshold and optional window
diagnostics request. Window size, overlap, token limits, request-body limits,
queue capacity and inference deadline remain scanner settings. Jarvis's own
scan timeout remains independent; increasing a server limit does not extend
the client timeout. Inputs rejected by the scanner remain unknown/unscanned.

A confirmed input detection produces a terminal `model_input` receipt. No
fallback summary, truncated source or Memory write follows that detection.
Automatic-summary wrappers preserve the stop rather than silently dropping it.
The current chat turn or workflow ends with the neutral notice, without asking
the chat model to retrieve the source by another tool. Other requests continue.
Usage from any earlier completed summary chunks remains recorded. A file is not
certified as fully screened when only selected chunks or an excerpt were used.

Restart Web, the task worker, and any callback/API processes after updating so
completion, delivery, and callback handling load the same code. No browser image
rebuild, additional service, dependency, or task-schema migration is needed.

HTTP query and workflow responses preserve `error_code`, `terminal_failure`,
`retry_safe`, and `completion`. A confirmed detection reports
`error_code: "prompt_injection_detected"`, `terminal_failure: true`, and
`retry_safe: false`. API clients should respect those facts instead of retrying
the whole request. The HTTP response remains a successful delivery of a failed
application outcome; `completion` describes the operation that already ran.

## Input size, latency, and failures

The shared scanner skips oversized inputs whole, never silently truncating a
tool result or caller's text. Web attachment composition separately bounds and
labels the exact excerpt it will insert before calling that scanner. The Jarvis
byte limit is separate from the service's token/window limits; service rejections
are unknown outcomes. Invalid or incomplete coverage never produces a clean verdict.
For a GPU service benchmarked with larger inputs, `262144` allows a 256 KiB
returned representation. Keep the smaller default for an unmeasured or
CPU-constrained service.

Only one scan per Jarvis process can be in flight; a concurrent call skips rather
than waiting. An unavailable service enters a short cooldown, separately keyed
by mode and credentials, to avoid repeated failed requests.

The timeout bounds HTTP connect/read operations with additional elapsed-time
checks on a bounded response. It is not a strict wall-clock deadline for every
DNS/socket operation. A client timeout does not guarantee remote inference has
stopped; configure resource limits and inference deadlines on the service too.

The `prompt_guard` logger reports disabled/unconfigured and outage states with
repeat suppression. Classification logs use `action=reported`; withholding logs
use `action=withhold`. Successful clean scans are DEBUG-level information. Raw
text, credentials, response bodies, and exception messages are excluded.

A classifier score is an estimate. An unflagged result does not make external
content trusted or authorize tool execution, and a detection can be a false
positive. The incident record supports checking that distinction.

## Real-model evaluation

The deterministic tests verify transport, validation, withholding, private evidence,
and continuation behavior using controlled responses. Evaluate detection quality
separately against the configured real service:

```bash
# Offline corpus listing; sends nothing.
.venv/bin/python bin/benchmark-prompt-guard

# Sequential live scans of paired planted documents and benign look-alikes.
.venv/bin/python bin/benchmark-prompt-guard --run --mode cloud

# Also compare readable JSON as an isolated experiment.
.venv/bin/python bin/benchmark-prompt-guard --run --mode cloud \
  --representations tool_result raw_text readable_json_experiment
```

The curated seed corpus is `tests/fixtures/prompt_guard_eval.json`. It covers
planted status notes, role/authority spoofing, fake tool instructions, hidden HTML
and metadata, Base64/Unicode obfuscation, task-shaped support requests, answer
manipulation, preference poisoning, delayed triggers, and long documents.
Long-placement inputs include documents around 95 KiB; a case
named for a window boundary is an approximate placement, not an attested split at
a tokenizer boundary. Reported window positions come from actual scans.
The runner respects the configured input limit. A mode using the default 64 KiB
limit will skip the long cases; completing those requires a larger limit already
validated for that service, such as the measured GPU configuration described above.

`tool_result` uses the real shared serializer around a synthetic tool result;
`raw_text` scores its document body. The readable form preserves the same keys and
values but remains experimental. The runner never calls source tools, opens payload
URLs, executes payload commands, or exposes real credentials in fixture content.
It requests diagnostics without changing saved settings, model, or thresholds.

Each run saves private inputs, hashes, model/request identifiers, window diagnostics,
scores, latency, misses, false alarms, and unknown/skipped outcomes under
`logs/prompt-guard/benchmarks/<run>/`. Threshold comparisons reuse those same scores;
they do not issue more requests or choose a production threshold. Unscanned cases
are counted separately rather than treated as successful detections or clean
documents. Exit 2 means at least one scan did not complete; a completed evaluation
can still contain missed attacks and false positives in its report.

These fixtures are synthetic, labeled by intended behavior. They are a repeatable
challenge set, not held-out accuracy or proof that an agent would follow each
planted instruction. Keep reviewed production incidents separate, including their
exact representation; a good corpus result does not erase an observed false
positive. Compare both detection and benign rejection before changing policy.

## Reusing the client

```python
from lib.prompt_guard import scan_text

observation = scan_text(
    external_text,
    source_type="tool_result",
    source_name="my_reviewed_consumer",
)
# Apply the consumer's policy to this typed classification.
# Unknown/skipped/disabled results do not mean the content is safe.
```

Resolve configuration inside the active request mode. The client returns a
classification; the tool-result adapter owns withholding and incident handling.
Use `is_prompt_guard_rejection` from `lib.prompt_guard_observer` for canonical
tool outcomes, and `is_prompt_guard_stopped` for projected or persisted frontend
results. Keep receipt recognition in those shared helpers when adding another
continuation or repair path.
