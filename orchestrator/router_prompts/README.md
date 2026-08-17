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
also validated at startup. Because experimental v2-v4 may evolve in place, the
version identifies the current checkout's pinned contents; use the Git revision
or contemporaneous prompt hash/size when distinguishing older experiment runs.

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

Both commands append real provider calls to the normal daily LLM log. Inspect
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

`system_prompt_chars` includes v1/v2 plus unchanged runtime context, provider
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
| `v1` | `v1 - Full context system prompt` | Exact established Jarvis router prompt accumulated through production use and provider/model testing | Immutable baseline |
| `v2` | `v2 - Compact full-context prompt` | Consolidated production prompt preserving v1 behavioral contracts | Experimental candidate |
| `v3` | `v3 - Caveman hybrid prompt` | Telegraphic v1/v2 hybrid with normal user-facing speech | Experimental |
| `v4` | `v4 - Caveman-light hybrid prompt` | Natural compact wording at nearly v3 size | Experimental |

## Measured size comparison

These measurements cover the static `BASE_SYSTEM_PROMPT` strings only. Runtime
date/time, provider capability notes, model-specific overrides, profile cards,
Tool RAG schemas, and conversation context are added separately at request
time.

| Version | Characters | Words | Rough Token Estimate | Character Delta |
| --- | ---: | ---: | ---: | --- |
| `v1` | `31,491` | `4,821` | `7,873-8,179` | Baseline |
| `v2` | `13,524` | `1,904` | `~3,381` | `57.1%` fewer than v1 |
| `v3` | `9,567` | `1,242` | `~2,392` | `69.6%` fewer than v1; `29.3%` fewer than v2 |
| `v4` | `10,039` | `1,317` | `~2,510` | `68.1%` fewer than v1; `25.8%` fewer than v2; `4.9%` more than v3 |

The important live metric is full routing payload size. A compact prompt can
still be dominated by retrieved tool schemas, profile/context overlays, or
provider continuation behavior. Use `logs/llm-calls-YYYY-MM-DD.jsonl` and
`logs/tool-rag/tool-rag-YYYY-MM-DD.jsonl` when comparing real turns.

## v1: Full context system prompt

File: `v1.py`

`v1` is the exact router system prompt that existed before prompt versioning.
It is the control arm for all future experiments. Tool RAG, ghost tools, and
tool schemas are independent of this version.

Baseline measurements:

- Characters: `31,491`
- Physical lines: `417` (`340` nonblank)
- Space-separated words: `4,821`
- Rough token estimate: `7,800-8,200`, depending on provider tokenizer
- Prompt SHA-256: `6c2ecbb0c032af7f7ffc70b6d093d11e918230e31ef4ddb7bfffadf9f4b4efc1`

### Do not edit v1

Do not modify `BASE_SYSTEM_PROMPT` in `v1.py`. The module carries its expected
prompt SHA-256, and `router_prompts/__init__.py` validates it whenever the
router is imported. If the prompt bytes change without matching the pinned
checksum, Jarvis fails closed instead of silently running a modified v1.

Comments and documentation outside `BASE_SYSTEM_PROMPT` do not affect the
prompt checksum. Treat the checksum constant as immutable too. If prompt
behavior needs to change, copy v1 into a new version instead of updating v1 or
its checksum.

Live tool schemas and implementation guards remain authoritative when a
historic v1 example names a parameter that a tool no longer accepts. Do not
patch v1 to follow those runtime changes; update maintained prompt versions and
keep safety-critical validation at the tool boundary.

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
headless operation, and response style. It removes repeated warnings and
tutorial-style good/bad examples, consolidating each rule and its exceptions
into one authoritative section.

Measurements:

- Characters: `13,524` (`57.1%` fewer than v1)
- Physical lines: `88` (`75` nonblank)
- Space-separated words: `1,904`
- Rough token estimate: approximately `3,381`, depending on provider tokenizer
- Prompt SHA-256: `3725ea9dadaf1b62bc9e13d3c1f5c6304ed5cd5e82c9203eb460c71107cc7712`

Tool RAG, schemas, runtime date/time, provider capability notes, response-style
overlays, model overrides, and profile cards remain unchanged. Treat live tests
as an A/B experiment against v1. v2 is an experimental baseline and may evolve
in place when its hash, exact-size tests, documentation, and validation samples
are updated together. v1 remains the immutable control.

## v3: Caveman hybrid prompt

File: `v3.py`

`v3` compresses v1/v2 into short, telegraphic instructions while explicitly
requiring normal fluent user-facing answers. It is not a Grug persona and must
not leak Caveman grammar into responses. Exact tool names, parameters,
exceptions, stop conditions, workflow boundaries, and deterministic
workflow-recipe routing remain explicit.

V3 also makes injected-runtime precedence unambiguous: configured
location/ZIP/timezone questions use the injected values directly, explicit
current-time questions still call `get_time`, and casual greetings may mention
the injected time without a tool call.

Measurements:

- Characters: `9,567` (`69.6%` fewer than v1; `29.3%` fewer than v2)
- Physical lines: `91` (`76` nonblank)
- Space-separated words: `1,242`
- Rough token estimate: approximately `2,392`, depending on provider tokenizer
- Prompt SHA-256: `d10d61134f21dd096ab1dfff93223d5ee3dc19fb70deddaeca95e6fc6c774e37`

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

- Characters: `10,039` (`68.1%` fewer than v1; `25.8%` fewer than v2; `4.9%` more than v3)
- Physical lines: `46` (`31` nonblank)
- Space-separated words: `1,317`
- Rough token estimate: approximately `2,510`, depending on provider tokenizer
- Prompt SHA-256: `558ad32d86156901b2117621b998340b2c35f94ab20f70aec8776b78c2409d96`

V4 intentionally preserves the supplied Unicode comparison arrows and symbols;
provider tokenization may therefore differ slightly from the character-based
estimate. Its key comparison is adherence versus v3, not maximum compression.

## Regression risks from v1 things to keep an eye on

### v1 → v2 Behavioral Contract Comparison

| Area                              | v1 Strength                                      | v2 Status                      | Risk Level   | Comment |
|-----------------------------------|--------------------------------------------------|--------------------------------|--------------|---------|
| **Memory fallback**               | Very explicit "max 2 attempts + specific order"  | Still present but softer       | Medium       | Easy to regress into looping or giving up too early |
| **Canvas discipline**             | Extremely strict ("after Canvas → stop", one append only on new source type) | Present but less sharp     | **High**     | This one caused a lot of pain in v1. Worth keeping stricter. |
| **Voice/spoken constraints**      | Very detailed rules                              | Almost gone                    | Medium       | If you still care about voice output quality, this got diluted |
| **Failure handling nuance**       | Had good examples and "distinguish error vs constraint" language | More generic now     | Medium       | Models still need strong nudging here |
| **"Never claim success unless confirmed"** | Repeated and strong                        | Present but less reinforced    | Medium-High  | One of the most important anti-hallucination rules |
| **Research loop prevention**      | Very explicit stop criteria + "partial answer > endless search" | Good but shorter     | Low-Medium   | Still decent |
| **Opencode rules**                | Very clear single-call + verification via other tools | Still solid              | Low          | One of the better preserved sections |


## Hash helper

The helper hashes the actual runtime `BASE_SYSTEM_PROMPT` string, not the Python
source file. It is shared across modes; cloud and local independently select
the resulting versions through their env or Web overrides.

```bash
# Inspect one version and print a ready-to-paste constant on mismatch.
bin/router-prompt-hash v2

# Intentionally update a non-v1 module after editing its prompt.
bin/router-prompt-hash v2 --write

# Verify every version registered in the shared catalog.
bin/router-prompt-hash --check-all
```

The helper refuses to rewrite v1. Its checksum is a source-controlled integrity
guard against accidental drift, not a secret or a security signature.

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

Prefer Git because it restores the exact version tracked by the chosen branch,
tag, or commit. Back up any intentional local work first.

```bash
V1_REF=587e2ba1b7d3436b3af494b486fc503040765da8
git restore --source="$V1_REF" -- orchestrator/router_prompts/v1.py
```

That commit introduced the immutable v1 baseline. A commit-pinned restore is
safer than relying on a moving branch; `origin/main` remains an option when the
latest upstream copy is intentionally desired.

If Git restoration is unavailable, download the raw file to a temporary path,
inspect it, and then install it. `REF` may be `main`, a tag, or preferably a
known-good commit SHA:

```bash
REF=587e2ba1b7d3436b3af494b486fc503040765da8
curl --fail --location --proto '=https' --tlsv1.2 \
  "https://raw.githubusercontent.com/bigsk1/jarvis-voice/${REF}/orchestrator/router_prompts/v1.py" \
  --output /tmp/jarvis-router-prompt-v1.py

cp /tmp/jarvis-router-prompt-v1.py orchestrator/router_prompts/v1.py
PYTHONPATH=lib:orchestrator python3 -c \
  "from router_prompts import get_router_system_prompt; print(get_router_system_prompt('v1')[0])"
```

The final command imports the prompt registry and therefore runs automatic
integrity validation. It prints `v1` on success and raises an integrity error
if the restored prompt does not match its pinned checksum.

The raw GitHub fallback becomes available only after this prompt-versioning
work has been committed and pushed to the selected ref.

## Cache behavior

The selected static prompt remains before changing runtime context. For a fixed
provider/model, any model-specific prepend is also stable. Date/time and other
per-turn context follow the stable prefix, preserving the cache-friendly
ordering used before prompt extraction. Changing versions intentionally changes
the prefix and should be expected to start a new provider cache lineage.
