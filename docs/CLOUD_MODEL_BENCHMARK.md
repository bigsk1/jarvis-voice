# Cloud model benchmark for Jarvis

`bin/benchmark-cloud-model` compares OpenAI, Anthropic, xAI and Ollama Cloud chat
models through Jarvis's production adapters. **Suite v4 has 44 tasks**, normally
repeated three times, plus six optional, ungraded tone samples.

It measures completion, discovery, factual grounding, recovery, instruction
following and efficiency. Tool results and personal context are synthetic.
It never executes real tools, starts workers, reads personal memory, sends
email, creates Canvas pages or changes the model running in Jarvis.

## Run and compare

The launcher uses the repository `.venv`. Start with an offline plan:

```bash
./bin/benchmark-cloud-model \
  --provider ollama --model 'deepseek-v4.1-flash:1017-cloud'
```

Only `--run` sends synthetic prompts and public tool descriptions to the selected
provider, consuming normal API billing or subscription quota. It uses that
provider's cloud credentials without including secrets in prompts or reports.

```bash
# Six tasks, one per area, plus tone samples. Diagnostic; no letter grade.
./bin/benchmark-cloud-model \
  --provider ollama --model 'deepseek-v4.1-flash:1017-cloud' \
  --run --smoke --rounds 1 --pause 2

# Full suite: 44 tasks x 3 repetitions = 132 scored trials.
./bin/benchmark-cloud-model \
  --provider ollama --model 'deepseek-v4.1-flash:1017-cloud' \
  --run --rounds 3 --thinking auto --pause 2

# Another provider: use its exact chat model ID, not a UI label.
./bin/benchmark-cloud-model \
  --provider anthropic --model 'YOUR_EXACT_MODEL_ID' \
  --run --rounds 3 --thinking auto --pause 2

# Shared instructions without model-specific routing corrections.
./bin/benchmark-cloud-model \
  --provider ollama --model 'deepseek-v4.1-flash:1017-cloud' \
  --run --prompt-profile baseline --rounds 3 --pause 2

# Offline comparison. Incompatible runs form separate groups.
./bin/benchmark-cloud-model --compare \
  logs/cloud-benchmarks/FIRST-REPORT.json \
  logs/cloud-benchmarks/SECOND-REPORT.json
```

Providers are `openai`, `anthropic`, `xai` and `ollama`. Use a tool-capable chat
model available to your account. Media and embedding IDs are not applicable.
Custom chat IDs are accepted; there is no silent model substitution.

Ollama uses cloud-mode resolution: a configured `OLLAMA_API_KEY` selects direct
cloud; otherwise use the exact cloud-tagged model on a configured signed-in
daemon. Only the first resolved endpoint is used, with no localhost fallback.
Keep the transport consistent across repeat comparisons.

`--case CASE_ID` and `--category CATEGORY` select subsets and are repeatable.
The offline plan lists IDs. `--skip-style-probes` omits tone samples. `--pause 30`
can spread subscription usage out. `--max-requests` is a hard run-wide call limit,
default 500; tasks also have individual ceilings. Each tool continuation is
another provider request. The plan shows a bounded worst case, not an estimate
of the requests a successful model will need.
During calibration, `--rounds 1 --skip-style-probes` keeps usage down. Repeat
trials later to assess consistency; one round's grade is provisional evidence.

## Improvements in suite v2

The full v1 calibration exposed valid routes its mocks rejected. V2 accepts
separate or combined source searches, interleaved reads, individual or batch
crawls, workflow search/describe confirmation, and relevant calculator calls.
Search evidence uses Brave LLM Context's grounding envelope and returns only
matching synthetic sources, not all answers for an unrelated query.

Canvas accepts the requested JSON inside a larger document. A save containing
wrong facts returns its actual success receipt; content grading fails separately.
Conflicting JSON reports do not pass. Correct requested facts retain credit when
extra fields violate the requested output format.

Discovery uses the production summary formatter and a frozen eligible catalog.
Exact-name lookups and reasonable prefetches are valid. Normal learned-strategy
cases use current recipes and the production insight format. Candidate choice,
running before confirmation and final outcomes are separate diagnostics.

A schema-valid route without simulator coverage is a **fixture gap**. The runner
saves evidence and stops without an overall grade. Invented selectors,
unauthorized recipients and prohibited actions remain model errors. Review
gaps and apparently valid rejected paths before judging a model; the simulator
is finite. Repairs to valid alternate routes change the recorded simulator
source fingerprint and form separate comparison groups. Changes to tasks,
expected facts or pinned prompt contracts require a new fixture version.

Stash saves support direct saving or opening a space first, including a named
space. Opening a space does not complete the save. The final answer must use
an actually issued receipt, and the stored JSON is graded independently of the
successful save receipt.

## Live-calibration fixes in suite v4

V4 retains 44 tasks and rubric 2.0. Reviewed aliases accept `Seattle, WA` for
`Seattle, Washington` and PDF `create` for text-only `from_text`, matching the
production tools. PDF saves still grade the actual requested text, title and
filename; wrong content is a scored failure, not a simulator gap.

The runtime-context question accepts the `PST` label actually shown to the model,
as well as the configured IANA name. Human provider names accept declared case
variants in final answers and saved reports. These are per-field fixture aliases;
URLs, references, error codes and literal requested content retain their checks.
Email and screenshot questions now explicitly state when verbatim text or a code
without its explanation is required.

The V3 reports that exposed these issues are preserved. V4 changes both fixture
and runtime fingerprints, so its reports form a separate comparison group. Do
not reinterpret an interrupted V3 conversation as a completed V4 run.

## Relationship to Jarvis

V4 calls production `LLMRouter.build_system_prompt`, the tool-turn and conversation
formatters in `ContextAssembler`, result projections, the discovery-summary
formatter and the learned-insight formatter. The router constructor, executor,
databases and retrieval services are not started. A fixed clock, city, ZIP and
Profile Card replace personal settings. Optional clock arguments keep benchmark
timing fixed while ordinary callers retain the runtime clock.
Supplied clocks must be timezone-aware and are normalized to the configured
timezone; naive values are rejected rather than interpreted using the host zone.

V3 retains V2's tasks and scoring but fixes context fidelity. Its synthetic card
uses the production Profile Card wrapper, including the rule that the current
instruction and active preferences win on conflict. It imports the same router
and context modules as the live app. Background, chat-only and search guidance
use the live route's policy helpers, in the same order. Offline drift checks also
cover those helpers, their policy text and the profile boundary. Synthetic cards
bypass personal profile configuration and storage.

Provider input follows ordinary single-message text replay, including the
original request, bounded result previews, freshness, completion notices and
discovery hints. Prior user turns carry structured, bounded synthetic evidence
through the conversation formatter. Per-trial hashes identify the actual prompt
as tools become visible.

Suite version and system-prompt version are independent: **suite v4 uses the
pinned V2 system prompt**. Prompt, public schema and relevant context-function
drift fail offline validation before inference.

Suite v4 defaults to `--prompt-profile configured`. It applies the selected
model's routing prepend, tool-calling prepend and routing append through the
production loader. `baseline` omits that wording for a shared-prompt comparison.
Reports disclose the profile, matched override and exact prompt hashes; the
profiles form separate comparison groups.

Thinking profiles remain active in both. `--thinking auto` follows the adapter
with trace display off and legacy effort settings cleared. Explicit levels must
be declared by the model profile. `off` may use a documented fallback if reasoning
cannot be disabled. Shared flags do not imply identical reasoning across providers.

This is a controlled model/tool-loop benchmark. It does not measure live hybrid
retrieval quality, actual vision/OCR accuracy, native provider continuations,
real tool reliability, background-worker execution, Web Completion Guard repair,
TTS or arbitrary essay quality. Background cases test receipt interpretation
and follow-up selection. Cross-turn evidence is bounded synthetic data, not a
full Web database/extractor integration. QA and TTS overrides are separate paths.

## Coverage

| Area | Weight | Examples |
| --- | ---: | --- |
| Routing | 15% | Draft/send, hidden tools, location, current time, second attachment, literal recipient, advisory negative hints |
| Completion | 20% | Multiple outputs, research-to-Canvas, append/replace, reminder scheduling, source pagination, session preference and exact-ID revocation |
| Research | 20% | Snippets versus sources, official corrections, multi-provider comparisons, calculations, hint descriptions versus ordering |
| Recovery | 15% | Alternative sources, empty recalls, failed lookup versus absence, honest save retry, partial evidence, pending call status without redial |
| Grounding | 15% | Hostile evidence, freshness, unknown/zero, revised authorization, pending/completed jobs, explicit refresh |
| Long context | 15% | Ledger joins, approved revisions, passage references, source identity across a follow-up |

Learned-strategy variants change description ordering using the production
format. They do not inject fictitious individual similarity labels. Jarvis can
show aggregate tool-preference biases; individual insight similarity values are
not normally displayed. These trials do not prove internal reasoning or how live
retrieval ranked the hints.

## Reading results

- **Completed trials** reports whether the runner finished the requested cases.
  A failed model response can still be a completed, scored trial.
- **Scored / unscored / not run** distinguish model outcomes from simulator or
  transport interruptions. Task and strict success percentages use only scored
  trials. For example, nine passes before a fixture gap in a 44-task run mean
  9/9 scored passes, one unscored trial and 34 tasks not run; there is no overall
  grade. Missing actions in an interrupted trial are not model failure counts.
- **Task success** requires requested actions, correct answer/artifact facts and
  no critical failure. A recovered minor policy mistake or format error can
  coexist with a delivered outcome.
- **Strict success** additionally requires policy compliance, requested JSON
  shape and staying within the call budget.
- **Quality** combines action completion (40%), factual grounding (35%), format
  (5%), policy (10%) and efficiency (10%), then applies the area weights above.
  Fabricated receipts/completion, invented tools and unauthorized actions zero
  the trial. Exhaustion caps the score at 60.

Letter grades require a complete full-suite run:

| Grade | Requirements |
| --- | --- |
| A | Quality >=95; task and strict success >=90%; every area >=80; no critical trial |
| B | Quality >=85; task success >=75%; no critical trial |
| C | Quality >=70 |
| D | Quality >=55 |
| F | Below those thresholds |

These are explicit rubric thresholds, not an independent intelligence measure.
Do not tune them to favor a candidate. Deterministic checks cover an oracle,
weak/early-stop behavior, real adapter wire formats, valid alternate paths,
wrong content, unauthorized targets and fabricated completion. Multi-model live
calibration is still needed to establish score separation and daily-use correlation.

Reports explain failed trials with problematic calls, mismatched facts,
dimension scores, insight diagnostics, latency and provider usage. Speed is
non-streaming request time, not time to first token. Cost remains unknown without
a usable provider estimate; subscription compute is not described as free.
Authentication, billing, timeouts and rate limits stop the run with no overall
grade. Explicit output/context limits and refusals are scored capability failures.

## Why tone questions appear twice

The terminal labels them **personal-touch hint included** and **omitted**.
Three questions each get both versions: fresh casual, urgent troubleshooting
and mid-thread follow-up. Both retain the synthetic Profile Card, so either may
sound personal. These six samples do not affect the grade. The opener is optional.

They are single paired samples, not three repetitions or proof of causation.
Review tone manually. Failed tone samples are reported separately from the
graded trials. If the task run stops before tone sampling, they are labeled
not run rather than failed.

## Reports and historical results

Timestamped JSON, Markdown and response checkpoints live under ignored
`logs/cloud-benchmarks/`. Responses and completed trials are flushed as they
arrive; the final report is checkpointed before rendering. A rerun starts a new,
potentially billable run. Checkpoints do not automatically resume requests.
Existing reports are never overwritten.

Comparison groups include fixture/rubric hashes, selected cases, repetitions,
thinking, prompt profile, tone selection, source/SDK fingerprints and the
model-override tree hash. Model identity is excluded. Configured profiles may
use different model-specific wording, which is disclosed. Source changes create
a new comparison group.

The original V1, V2 and V3 fixture files are preserved byte for byte.
`--suite v1` retains its cases and original rubric, defaulting to baseline. V1
has known fixture limitations. The archived V2 fixture rejects the changed
production-context contract in this checkout; replay it using its original
checkout. Existing reports still work with `--compare`. V4 is the default
and retains report schema 2 and rubric 2.0 because the data format and grading
are unchanged. Do not compare grades across fixture versions as the same test.
Runtime changes can also create separate groups with an unchanged suite.
Preserve old reports; changed simulator behavior requires a new run, not a
retroactive regrade of the old conversation.

Deterministic checks:

```bash
.venv/bin/python -m pytest \
  tests/test_cloud_model_benchmark.py tests/test_cloud_benchmark_v2.py -q
```
