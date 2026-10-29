# Optional Prompt Guard screening

Jarvis can screen selected external tool results with a separately hosted
[Prompt Guard service](https://github.com/bigsk1/prompt-guard). The shared client
is independent of the chat model. Cloud and local mode can both use the same
service, including a GPU service elsewhere on the LAN. Jarvis needs no local
inference packages, model weights, additional service, or database.

The check runs after a selected tool returns, before its result enters the next
model turn or workflow step:

- **Clean scan:** return the original tool result unchanged.
- **Confirmed detection:** withhold the returned content, end the tool turn or
  workflow, and return a neutral explanation with an incident ID. No automatic
  retry, loop alternative, or Completion Guard repair follows that detection.
- **Disabled, unavailable, timed-out, invalid, busy, or oversized scan:** continue
  with the original result. This is an unknown/unscanned result, never a clean
  verdict.

The tool has already run when screening happens. A rejection does not undo its
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
PROMPT_GUARD_TIMEOUT_SECONDS=2
PROMPT_GUARD_MAX_INPUT_BYTES=8192
# Optional; requires a scanner supporting the return_windows request field.
PROMPT_GUARD_RETURN_WINDOWS=false
PROMPT_GUARD_TOOLS=crawl_url,brave_llm_context,rss_feed,browser_use,browser_use_cloud
# Optional base directory; Jarvis appends cloud/ or local/.
# PROMPT_GUARD_INCIDENT_DIR=logs/prompt-guard/incidents
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

`PROMPT_GUARD_TOOLS` is a comma-separated list of exact tool names. An empty
value selects no tools. Review what a tool returns before adding it: selected
results are sent to another service. Email, calendar, memory, and arbitrary MCP
tools are not selected by default. No new tool schemas or Web settings are added.

The client makes one direct request, with ambient proxies, netrc credentials,
redirects, and retries disabled. It runs in the parent process and does not add
scanner credentials to restricted tool child environments. Existing legacy
tools that inherit the full mode environment can still inherit these settings;
this feature does not change their environment policy.

## Incident evidence and investigation

Incident evidence has dedicated, mode-separated subfolders:

```text
logs/prompt-guard/incidents/cloud/pg-<uuid>.json
logs/prompt-guard/incidents/local/pg-<uuid>.json
```

Each incident is a separate JSON file, published atomically without overwriting
an existing record. Incident directories have owner-only access (0700), and files
have owner-only read/write access (0600). The default log tree is gitignored and
excluded from Docker image builds. JSON quarantine files are not exposed by the
Web Log Explorer, enrolled in Stash, or injected into ordinary model context.

A report includes the incident ID, UTC timestamp, mode, tool name, score,
threshold, window coverage, validated service request/model identifiers,
execution summary, and exact scanned representation with SHA256. It also indexes
available request/result URLs, removing userinfo, sensitive query values, and
fragments. For multi-source results, these are **candidate source URLs**: a batch
classification does not establish which URL caused the detection.

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
and the notice says the evidence could not be saved. No incident cleanup job is
installed; retain or remove reviewed reports deliberately. A custom incident
base directory remains private configuration and should also stay out of Git
and public file serving.

## Initial coverage

The selected result's `data`, `speech`, and `error` fields are screened. Tool
arguments are not sent to the classifier; only candidate URL fields are examined
locally for incident provenance. The observer never opens local files or fetches
URLs and Stash artifacts.

The shared foreground executor covers ordinary chat/voice/CLI/API orchestration
and workflow component calls. The default list excludes the workflow wrapper so
its component results are not scanned twice. Required and optional workflow
steps both stop on a confirmed detection, including looped steps.

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
these shared boundaries remain outside this integration. Tools that fetch and
summarize internally need a separate hook before their own model call.

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

Oversized inputs are skipped whole, never silently truncated. The Jarvis byte
limit is separate from the service's token/window limits; service rejections are
unknown outcomes. Invalid or incomplete coverage never produces a clean verdict.
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
The runner respects the configured input limit. A mode using the default 8 KiB
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
