# Router system prompts

This directory contains the versioned, stable instruction blocks used by
`orchestrator/router_v2.py`. Runtime context remains shared: current date/time,
response style, provider capabilities, location, model-specific overrides, and
the optional profile card are assembled around the selected version elsewhere.

Select a version with:

```bash
JARVIS_ROUTER_PROMPT_VERSION="v1"
```

Cloud and local modes may select different versions in `config/cloud.env` and
`config/local.env`. Jarvis Web can save a separate per-mode selection from
Settings > AI Config. The existing process override also works:

```bash
JARVIS_OVERRIDE_JARVIS_ROUTER_PROMPT_VERSION="v1"
```

Use a fresh process/session and a fresh conversation when comparing versions.
Provider continuation may retain the system instructions from an existing
conversation.

There is also continuation *inside one user request*. For OpenAI/xAI structural
continuation, the first model call receives the selected system prompt. Later
tool turns may send `system_prompt=None` together with the provider response ID,
so those turns inherit the system instructions established by the first call.
A prompt version therefore applies to the whole request and cannot be switched
mid-request. Treat a multi-tool request as one experimental sample, not as
independent per-tool prompt samples.

Successful assistant messages store `router_prompt_version` in their persisted
usage metadata. This makes the selected version visible in conversation JSON,
export/import data, and Markdown exports without duplicating the full routing
provenance payload. Every version is hash-validated when selected, and v1 is
also validated at startup. Prompt contents can change through reviewed
maintenance, so the version identifies the current checkout's pinned contents;
use the Git revision or contemporaneous prompt hash/size when distinguishing
older experiment runs.

## Comparing prompt versions

The CLI/env path is the controlled experiment surface. Set
`JARVIS_ROUTER_PROMPT_VERSION` (or its `JARVIS_OVERRIDE_*` form), restart the
process, and run the same question with the same provider, model, tools, Tool
RAG configuration, and runtime settings. Start a fresh provider session for
each sample. Model variance, temperature, runtime overlays, and retrieved tool
schemas can still add noise; record them or hold them fixed as appropriate.

For one-process CLI samples, use the override namespace because `load_config()`
hydrates ordinary values from the selected mode env file. `EXPORT=...` is not
shell export syntax and would set an unrelated variable named `EXPORT`.

```bash
QUERY='What is the current price of Solana?'

env JARVIS_OVERRIDE_JARVIS_ROUTER_PROMPT_VERSION=v1 \
    JARVIS_OVERRIDE_AUTO_CONTEXT_ENABLED=false \
    ./orchestrator/orchestrator_v2.py cloud "$QUERY" --json

env JARVIS_OVERRIDE_JARVIS_ROUTER_PROMPT_VERSION=v2 \
    JARVIS_OVERRIDE_AUTO_CONTEXT_ENABLED=false \
    ./orchestrator/orchestrator_v2.py cloud "$QUERY" --json

env JARVIS_OVERRIDE_JARVIS_ROUTER_PROMPT_VERSION=v3 \
    JARVIS_OVERRIDE_AUTO_CONTEXT_ENABLED=false \
    ./orchestrator/orchestrator_v2.py cloud "$QUERY" --json

env JARVIS_OVERRIDE_JARVIS_ROUTER_PROMPT_VERSION=v4 \
    JARVIS_OVERRIDE_AUTO_CONTEXT_ENABLED=false \
    ./orchestrator/orchestrator_v2.py cloud "$QUERY" --json
```

Each command appends real provider calls to the normal daily LLM log. Inspect
recent routing samples with:

```bash
tail -n 100 "logs/llm-calls-$(date +%F).jsonl" | jq -c '
  select(.prompt_type == "routing") |
  {timestamp,
   version: .routing_provenance.router_prompt.version,
   system_prompt_chars: .routing_provenance.router_prompt.chars,
   system_prompt_sent: .routing_provenance.router_prompt.sent,
   input_tokens, output_tokens, total_tokens,
   cached_input_tokens,
   tool: .response.tool_name}'
```

`system_prompt_chars` includes the selected version plus runtime context, provider
capability notes, model overrides, and profile data. Structural continuation
may correctly show `system_prompt_sent=false`; that call inherits the version
established by the first provider call in the request. Sum all routing calls in
a multi-tool request when comparing its total token cost.

The Web UI selector is operational control: for example, cloud Web may use v2
while local Web uses v1. It is convenient for live evaluation, but saved Web
overrides and ongoing provider sessions make it a less controlled benchmark
surface than a fixed CLI/env run.

## Version summary

| Version | UI label | Purpose | Status |
| --- | --- | --- | --- |
| `v1` | `v1 - Full context system prompt` | Full-context recovery and comparison prompt pinned to the current checkout | Pinned baseline |
| `v2` | `v2 - Compact full-context prompt` | Consolidated production prompt preserving v1 behavioral contracts | Experimental candidate |
| `v3` | `v3 - Caveman hybrid prompt` | Telegraphic v1/v2 hybrid with normal user-facing speech | Experimental |
| `v4` | `v4 - Caveman-light hybrid prompt` | Natural compact wording at nearly v3 size | Experimental |

## Measured size comparison

These measurements cover the static `BASE_SYSTEM_PROMPT` strings only. Rough
token estimates use characters divided by four; provider tokenizers differ. Runtime
date/time, provider capability notes, model-specific overrides, profile cards,
Tool RAG schemas, and conversation context are added separately at request
time.

| Version | Characters | Words | Rough Token Estimate | Character Delta |
| --- | ---: | ---: | ---: | --- |
| `v1` | `27,189` | `4,079` | `~6,798` | Baseline |
| `v2` | `13,664` | `1,950` | `~3,416` | `49.7%` fewer than v1 |
| `v3` | `10,325` | `1,364` | `~2,582` | `62.0%` fewer than v1; `24.4%` fewer than v2 |
| `v4` | `10,887` | `1,490` | `~2,722` | `60.0%` fewer than v1; `20.3%` fewer than v2; `5.4%` more than v3 |

The important live metric is full routing payload size. A compact prompt can
still be dominated by retrieved tool schemas, profile/context overlays, or
provider continuation behavior. Use `logs/llm-calls-YYYY-MM-DD.jsonl` and
`logs/tool-rag/tool-rag-YYYY-MM-DD.jsonl` when comparing real turns.

## v1: Full context system prompt

File: `v1.py`

`v1` is the full-context recovery prompt and comparison baseline in the current
checkout. It originated before prompt versioning but has received intentional
maintenance since then. Tool RAG, ghost tools, and tool schemas are independent
of this version.

Baseline measurements:

- Characters: `27,189`
- Physical lines: `283` (`232` nonblank)
- Space-separated words: `4,079`
- Rough token estimate: approximately `6,798` by characters divided by four; provider tokenizers differ
- Prompt SHA-256: `223f11725bdf1b159f542b90a711052436cd0bc44f26678265e936de373bea49`

Reminder creation uses one call per explicitly requested notification schedule.
Only that schedule belongs in `when`; appointment times stay in the title or
description. Preserve the stated local notification time without invented lead
time, and confirm the saved receipt without creating again to verify or correct it.

### v1 integrity and maintenance

The module carries its expected prompt SHA-256, and
`router_prompts/__init__.py` validates it whenever the router is imported. If
the prompt bytes change without matching the pinned checksum, Jarvis fails
closed instead of silently running a modified v1.

Comments and documentation outside `BASE_SYSTEM_PROMPT` do not affect the
prompt checksum. Keep v1 stable for comparisons and put prompt experiments in a
new version. Necessary security or compatibility maintenance may revise v1 in a
reviewed change that updates its checksum, size assertions, and documentation
together. The hash helper deliberately refuses `v1 --write` so this review
cannot be replaced by an automatic checksum rewrite.

Live tool schemas and implementation guards remain authoritative when a
v1 example names a parameter that a tool no longer accepts. Remove obsolete
or unsafe v1 guidance when necessary, and keep safety-critical validation at
the tool boundary.

Jarvis always validates v1 because it is the recovery baseline. Other versions
are validated when selected. A stale hash in an unused experimental version
therefore cannot prevent Jarvis from starting with v1, while selecting that
broken version still fails closed with its expected and actual hashes.

## v2: Compact full-context prompt

File: `v2.py`

`v2` is a standalone rewrite of v1. It preserves the operational contracts for
context freshness, tool discovery, duplicate prevention, multi-part workflows,
reminders/alerts, research-to-output sequencing, Canvas finalization, memory,
image stash follow-ups, autonomous deterministic workflow selection, OpenCode,
execution-host boundaries, and runtime response style. It removes repeated warnings and
tutorial-style good/bad examples, consolidating each rule and its exceptions
into one authoritative section.

Measurements:

- Characters: `13,664` (`49.7%` fewer than v1)
- Physical lines: `86` (`73` nonblank)
- Space-separated words: `1,950`
- Rough token estimate: approximately `3,416` by characters divided by four; provider tokenizers differ
- Prompt SHA-256: `5831a62121f4e20a36f4991074c399aab249cba995e09e6bf82626c82dcffd9b`

Tool RAG, schemas, runtime date/time, provider capability notes, response-style
overlays, model overrides, and profile cards remain unchanged. Treat live tests
as an A/B experiment against v1. v2 is an experimental baseline and may evolve
in place when its hash, exact-size tests, documentation, and validation samples
are updated together. v1 remains the pinned control for the current checkout.

## v3: Caveman hybrid prompt

File: `v3.py`

`v3` compresses v1/v2 into short, telegraphic instructions while explicitly
requiring normal fluent user-facing answers. It is not a Grug persona and must
not leak Caveman grammar into responses. Tool naming, availability, evidence,
exceptions, stop conditions, workflow boundaries, and deterministic
workflow-recipe routing remain explicit.

V3 also makes injected-runtime precedence unambiguous: configured
location/ZIP/timezone questions use the injected values directly, explicit
current-time questions still call `get_time`, and casual greetings may mention
the injected time without a tool call.

Measurements:

- Characters: `10,325` (`62.0%` fewer than v1; `24.4%` fewer than v2)
- Physical lines: `90` (`75` nonblank)
- Space-separated words: `1,364`
- Rough token estimate: approximately `2,582` by characters divided by four; provider tokenizers differ
- Prompt SHA-256: `1911835df1c42b4794c6f4b9ba0c3626dc2336996f817aa3c8c1127b3f642d59`

The main experimental risk is instruction adherence on weaker/local models:
telegraphic grammar removes explanatory redundancy that may help some models.
Compare simple routing, multi-tool completion, duplicate recovery,
research/crawl-to-Canvas, memory fallback, and failure handling against v1/v2.

## v4: Caveman-light hybrid prompt

File: `v4.py`

`v4` uses the same compact contract set as v3 with fuller sentences and less
telegraphic grammar. "Light" describes the lighter Caveman style, not a claim
that it is smaller than v3. It is intended to test whether a tiny size increase
improves adherence for providers/models that struggle with v3 shorthand.

Measurements:

- Characters: `10,887` (`60.0%` fewer than v1; `20.3%` fewer than v2; `5.4%` more than v3)
- Physical lines: `46` (`31` nonblank)
- Space-separated words: `1,490`
- Rough token estimate: approximately `2,722` by characters divided by four; provider tokenizers differ
- Prompt SHA-256: `23cf620c527ea9aa100cad3e2fd72d31614dd68e481d3e1b65aa4d729379cd68`

V4 intentionally preserves the supplied Unicode comparison arrows and symbols;
provider tokenization may therefore differ slightly from the character-based
estimate. Its key comparison is adherence versus v3, not maximum compression.

## Maintenance contracts and regression risks

V1 remains the fuller recovery reference; V2 is compact prose, V3 telegraphic,
and V4 natural compact wording. All four share these contracts:

- Named tools are optional examples. The active profile, request policy, live
  schemas, and eligible discovery results determine actual capabilities.
- Claims require tool evidence, including explicit automatic-save receipts.
  Distinguish earlier work, work performed now, pending admission, and failures.
  Assistant prose alone is not evidence of a save.
- Complete every requested outcome. Finalizing a research page ends unsolicited
  search/polishing, while distinct requested actions may continue. The runtime
  one-successful-write cap applies only to Canvas exports.
- Canvas append adds material. Supplying content to update replaces the complete
  content field; title/tags/pinned-only updates need not resend content.
- Recall missing user-specific information, with at most two attempts. Applicable
  injected knowledge and live-state exceptions avoid unnecessary recall.
- Reuse reminder lists only while still applicable; gaps, relevant mutations, and
  explicit rechecks require fresh data. Notification schedules stay separate from
  appointment times, and successful creation is not repeated for verification.
- Preserve exact IDs, original upload identity, bounded research, explicit
  failure reporting, and OpenCode single-call/fallback-only status discipline.
- Use configured workspaces and the tool's actual execution host; do not assume
  an OS, display, shared paths, or that a local check reaches a remote project.

Shared runtime assembly owns voice/display formatting and limits. Email-recipient
and flight-routing policies are included when their tool families are enabled,
respecting request exclusions. They stay before volatile clock/location context.
News follow-ups defer to active provider/request search capability. Learned
strategies are scoped historical advice; numeric preferences influence retrieval,
not permissions or a calibrated probability of success.

The 2026-10-30 maintenance revises the pinned contents, not historical experiment
records. V1 loses repeated tutorials/examples while retaining representative
failure cases. V2 is slightly shorter; V3/V4 remain near their earlier sizes
because explicit availability, evidence, and host boundaries replace obsolete
procedures. Size alone does not establish adherence.

Deterministic checks cover pins, selected versions, assembled policies under
profile/request exclusions, native continuation inheritance, and formatter-to-
retrieval behavior. Fresh live samples are still needed to compare model
adherence. Use the same provider/model and settings for scenarios such as:

- Save the research to Canvas, then perform a separately authorized action.
- Describe an earlier confirmed save without creating another page.
- Report a tool's automatic save or a queued result with accurate timing/status.
- Handle a profile without memory, Canvas, or discovery tools.
- Complete ingestion plus another requested outcome.
- Recheck reminders after a conversation gap or a relevant state change.

Memory fallback, Canvas loop prevention, truthful completion, and runtime speech
formatting remain the highest-value regression checks when shortening further.

## Hash helper

The helper hashes the actual runtime `BASE_SYSTEM_PROMPT` string, not the Python
source file. It is shared across modes; cloud and local independently select
the resulting versions through their env or Web overrides.

```bash
# Inspect the current v1 pin without changing it.
bin/router-prompt-hash v1

# Inspect one version and print a ready-to-paste constant on mismatch.
bin/router-prompt-hash v2

# Intentionally update a non-v1 module after editing its prompt.
bin/router-prompt-hash v2 --write

# Verify every version registered in the shared catalog.
bin/router-prompt-hash --check-all
```

The helper refuses to rewrite v1 automatically. Its checksum is a
source-controlled integrity guard against accidental drift, not a secret or a
security signature. Intentional v1 maintenance requires a reviewed manual hash
update and corresponding test/documentation changes.

Experimental v2-v4 may be intentionally revised in place. Update their prompt,
checksum, measurements, behavioral tests, and experiment notes as one change.
Do not rewrite a checksum merely to hide unexplained prompt drift.

## Adding a new version

Each new version gets its own section in this README. Record its intent,
differences from v1, measurements, checksum, tested providers/models, and known
tradeoffs.

Implementation checklist:

1. Copy `v1.py` to a new module such as `v2.py`.
2. Rename/update its prompt and checksum constants.
3. Add its ID and descriptive UI label to `lib/router_prompt_catalog.py`.
4. Import and register it in `router_prompts/__init__.py`.
5. Add integrity, selection, prompt-size, and behavior regression tests.
6. Run `bin/router-prompt-hash VERSION --write`, then `--check-all`.
7. Compare it with v1 using fresh conversations and the same tools/config.
8. Do not change Tool RAG or schemas in the same experiment.

## Restoring v1

To discard an accidental local edit, restore the version tracked by the
current checkout. Back up any intentional local work first.

```bash
git diff -- orchestrator/router_prompts/v1.py
git restore --source=HEAD -- orchestrator/router_prompts/v1.py
.venv/bin/python bin/router-prompt-hash --check-all
```

For an older release, first inspect and select a reviewed tag or commit whose
prompt behavior is appropriate for that release. The original prompt-versioning
commit is not the current recovery baseline. The integrity check above confirms
the restored file matches its own pinned checksum.

## Cache behavior

The selected static prompt remains before changing runtime context. For a fixed
provider/model, any model-specific prepend is also stable. Date/time and other
per-turn context follow the stable prefix, preserving the cache-friendly
ordering used before prompt extraction. Changing versions intentionally changes
the prefix and should be expected to start a new provider cache lineage.
