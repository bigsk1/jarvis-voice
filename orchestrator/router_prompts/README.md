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
provenance payload. Since a prompt version is hash-validated when selected (and
v1 is also validated at startup), the version identifies the pinned contents.

## Comparing prompt versions

The CLI/env path is the controlled experiment surface. Set
`JARVIS_ROUTER_PROMPT_VERSION` (or its `JARVIS_OVERRIDE_*` form), restart the
process, and run the same question with the same provider, model, tools, Tool
RAG configuration, and runtime settings. Start a fresh provider session for
each sample. Model variance, temperature, runtime overlays, and retrieved tool
schemas can still add noise; record them or hold them fixed as appropriate.

The Web UI selector is operational control: for example, cloud Web may use v2
while local Web uses v1. It is convenient for live evaluation, but saved Web
overrides and ongoing provider sessions make it a less controlled benchmark
surface than a fixed CLI/env run.

## Version summary

| Version | UI label | Purpose | Status |
| --- | --- | --- | --- |
| `v1` | `v1 - Full context system prompt` | Exact established Jarvis router prompt accumulated through production use and provider/model testing | Immutable baseline |
| `v2` | `v2 - Full context without blank lines` | Whitespace-only experiment derived from v1 | Experimental |

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

Jarvis always validates v1 because it is the recovery baseline. Other versions
are validated when selected. A stale hash in an unused experimental version
therefore cannot prevent Jarvis from starting with v1, while selecting that
broken version still fails closed with its expected and actual hashes.

## v2: Full context without blank lines

File: `v2.py`

`v2` derives from immutable v1 and removes blank lines while preserving every
instruction and its order. This is deliberately a narrow whitespace-only test
of the version-selection, integrity, persistence, and comparison workflow—not
the semantic compression pass.

Measurements:

- Characters: `31,396` (`95` fewer than v1)
- Physical lines: `340`
- Space-separated words: `4,821`
- Prompt SHA-256: `2eac90483f6908db2308d1c2cedd79d35cd7e73c70704b4a2ee18a74285dbb90`

Because v2 is an established experiment once committed, broader removal of
emoji, Markdown, or repeated instructions belongs in v3 rather than silently
changing v2.

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
git fetch origin
git restore --source=origin/main -- orchestrator/router_prompts/v1.py
```

For a release or experiment, replace `origin/main` with a known-good tag or
commit. A commit-pinned restore is safer than relying on a moving branch.

If Git restoration is unavailable, download the raw file to a temporary path,
inspect it, and then install it. `REF` may be `main`, a tag, or preferably a
known-good commit SHA:

```bash
REF=main
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
