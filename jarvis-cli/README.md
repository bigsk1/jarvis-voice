# Jarvis CLI

Run the full Jarvis app from a terminal or another agent. Natural-language
requests use the same orchestrator, model configuration, Tool RAG, tool
executor, memory, workflows and optional integrations as other Jarvis surfaces.
This is a one-request-per-process CLI; it does not require a microphone or a
running Web server. Individual tools may need their configured services.

For an agent, read [SKILL.md](SKILL.md). For a person, start here:

```bash
jarvis-cli "Hello, how is it going?"
jarvis-local-cli "Get the current Bitcoin price in USD"
```

The default prints the final answer, without startup messages, MCP discovery,
tool progress or a debug dump. It removes supported speech-delivery tags from
displayed text. It preserves Markdown, links and references in the answer.
It does not change the model's configured answer length.

## Setup and launchers

Complete normal Jarvis setup with `./install.sh`, including the configuration
for your chosen mode. Install the Bash/Zsh command functions with:

```bash
./update-aliases.sh --shell bash
# For Zsh instead: ./update-aliases.sh --shell zsh
```

Reload the indicated shell RC file. The managed functions source the tracked
`.jarvis-aliases` file, so existing managed installations pick up these changes
when sourced again; an unmanaged copied alias block needs updating.

An agent or noninteractive shell can invoke the executable directly, from any
working directory, without sourcing a shell RC file:

```bash
/path/to/jarvis-voice/bin/jarvis-cli "Get the current Bitcoin price" --json
/path/to/jarvis-voice/bin/jarvis-local-cli "Get the current Bitcoin price" --json
```

Both launchers activate the **production** environment at `~/jarvis-venv` and
use its Python interpreter. `JARVIS_VENV` can select a custom production venv.
They ignore the shell's active development venv and refuse the checkout's
`.venv`; repo `.venv` remains the environment for development tests. No new
runtime dependency or daemon is introduced.

`jarvis-cli` defaults to `config/cloud.env`; `jarvis-local-cli` presets local
mode, using `config/local.env`. `--mode cloud|local` explicitly selects a mode.
An inherited `JARVIS_MODE` does not override that CLI selection. A selected
mode ENV must exist. Cloud/local settings continue to determine the model,
provider, available tools, profiles and integration credentials.

For an existing Docker installation, rebuild to include these launchers, then
use `docker compose exec -T jarvis-web ./bin/jarvis-cli REQUEST --json`.
The image configures its production `JARVIS_VENV=/opt/venv`; its mounted
configuration, network and tool profile still apply. See the
[Docker CLI guide](../docs/docker/README.md#shell-and-cli-commands-inside-docker).
Native launchers and container launchers use their own production environments.

## Dashboard TUI

The dashboard's **CLI** tab uses these production launchers and displays answers
in its right-hand **System Output** pane. **Ask Jarvis** shows a question input
inside that pane; type your request and press Enter, or Escape to cancel.
**User Context** asks the model what it knows about you and your preferences;
**Personalization Check** asks how it would approach a code change for you.
Each entry has Cloud and Local versions. **CLI Help** displays flags in the
dashboard output pane without making a model call.

These are ordinary live requests. They use the selected mode's configured
profile, memory, recent context, tools and learning settings. The dashboard
does not enable those features or change their settings. The model's response
shows its behavior with that runtime; it is not a separate configuration audit.

Each selection runs once, with ordinary CLI conversation logging and automatic
context behavior. CLI requests do not open tmux sessions or require leaving the
dashboard. The existing tmux behavior for voice and service commands is unchanged.

## Options

Options can precede or follow a quoted request. Use `--` before a request that
starts with a dash or contains a literal CLI option such as `--json`.

| Option | Behavior |
| --- | --- |
| `-h`, `--help` | Show usage without starting models or MCP discovery. |
| `--mode cloud\|local` | Select the mode; cloud is the ordinary launcher's default. |
| `--json` | Print exactly one complete result object on stdout. |
| `--verbose` | Stream startup, MCP, routing, tool and cleanup diagnostics on stderr. Can be combined with `--json`. |
| `--stdin` | Read one request from stdin, preserving indentation, leading/trailing whitespace and newlines. Whitespace-only requests are rejected. Cannot be combined with request arguments. |
| `--no-context` | Disable automatic recent-conversation context for this invocation. |
| `--no-tools` | Direct model answer; disables client tools, workflows and provider-hosted tools for the request. |
| `--exclude-tool NAME` | Exclude a tool for this request; repeat for multiple tools. Combines with configured process exclusions. |
| `--prompt NAME` | Apply `jarvis-web/data/prompts/NAME.md` as request context. Nested names such as `personal/example` work; omit `.md`. |
| `--speak` | Also speak the final result using the configured TTS provider. Voice progress is disabled by default. |
| `--voice-progress` | Honor the selected mode's spoken-progress settings. Wake-word question wrappers pass this automatically; it does not force progress on when configuration disables it. |
| `--debug-thinking` | Enable visible reasoning where supported; show the boxed thinking display on stderr and retain the raw reasoning in JSON. |
| `--feedback` | Collect an additional LLM QA assessment. Human mode shows its rating, summary and issues on stderr; JSON mode includes `feedback`. May invoke an additional model and update Intelligence feedback. |

The compatibility commands `jarvis-cli-json` and `jarvis-local-cli-json` append
`--json` through the same launchers. Direct Python invocation remains supported
as `orchestrator/orchestrator_v2.py cloud|local REQUEST [OPTIONS]`, with the same
output and exit-code behavior; activate the production environment first.

Examples:

```bash
jarvis-cli "Inspect Craft capabilities" --json
jarvis-cli --verbose "Get the current Bitcoin price"
jarvis-cli --no-context --no-tools "Explain this short paragraph"
jarvis-cli --prompt deep_research "Research the requested topic"
printf '%s\n' 'Rotate page 1 of stash://SPACE/FILE by 90 degrees with PdfCraft' \
  | /path/to/jarvis-voice/bin/jarvis-cli --stdin --json --no-context
```

## Output and exit codes

Human output is the final `raw_llm_response` when present, otherwise `speech`
or the error text. No JSON dump appears unless requested. Quiet mode suppresses
runtime diagnostic stdout and stderr; it does **not** suppress the returned
request failure. Use `--verbose` to investigate provider or MCP problems.

`--json` preserves the complete orchestrator result rather than reducing it to
a conversational summary. Typical fields are:

| Field | What to inspect |
| --- | --- |
| `ok` | Whether Jarvis reports the request succeeded. |
| `speech`, `raw_llm_response` | Voice-friendly and full response text when available. |
| `tools_used`, `tool_trace` | Actual calls, arguments, duration, success and errors when provided. |
| `data` | Tool results keyed by tool name; output paths, Stash references, job IDs and other domain-specific evidence. |
| `error`, `error_type`, `completion` | Failure details and outcome uncertainty when available. |
| `usage` | Model/token/billing metadata; unknown costs remain unknown. |
| `feedback`, `feedback_error`, `tts_error` | Optional QA or speech-delivery outcomes. |

Fields depend on the route and tool. Do not assume every field exists. Files
stay in their normal Stash/output storage; JSON does not inline binary media.
A reference/path points to the Jarvis host, not automatically the calling
agent's machine. Normal Stash retention still applies.

A failed request can return a complete JSON result with exit code 1. Parse
stdout before treating the exit status as a transport/launcher failure; error,
speech and tool evidence remain useful even when `ok` is false.

| Exit | Meaning |
| --- | --- |
| `0` | Jarvis returned `ok: true`; inspect tool/job state to distinguish completed work from a running receipt. |
| `1` | Request failure, runtime exception, or requested TTS delivery failure. A TTS error can coexist with successful core work. |
| `2` | Invalid/missing arguments, missing production venv, or invalid launcher configuration. Argument/launcher errors print to stderr and may have no JSON body. |
| `130` | Interrupted execution. A structured interruption result is returned when interruption happens during request execution. Remote work may continue. |

No automatic extra invocation/retry is added by the CLI. A tool's existing
bounded provider retries remain in effect. After an unknown outcome or running
receipt, inspect the returned job/request identifiers before submitting again.
For Craft, use `craft_inspect` to inspect or collect existing work.

## Calling from another agent

Prefer the absolute executable, stdin and JSON. Use an argument array, without
shell interpolation of the user's request:

```python
import json
import subprocess

proc = subprocess.run(
    ["/path/to/jarvis-voice/bin/jarvis-cli", "--json", "--stdin", "--no-context"],
    input=user_request,
    text=True,
    capture_output=True,
)
result = json.loads(proc.stdout) if proc.stdout.strip() else None
# Check proc.returncode, result.get("ok"), tool_trace and data before reporting success.
```

An outer timeout or lost connection does not prove remote work stopped. Choose
an observation budget appropriate to the tools: media jobs can take minutes.
Store returned job IDs and use inspection rather than replaying uncertain work.
Do not retry an entire request merely because requested TTS or QA failed.

By default CLI requests may receive recent CLI/voice conversation context from
Memory, according to `AUTO_CONTEXT_*`. `--no-context` avoids that ambient recent
history for agents supplying explicit instructions or file references. It does
not disable memory retrieval, learned strategies, conversation logging or
Intelligence. There is no named isolated CLI conversation/session API in this
version; pass relevant facts and references explicitly for deterministic
follow-ups. Ordinary users can keep the existing automatic context behavior.

For a remote Jarvis host, use the user's authorized SSH connection to run the
same absolute executable. Keep requests on stdin; do not interpolate them into
a remote shell command. For example:

```bash
printf '%s\n' 'Inspect Craft capabilities' \
  | ssh user@jarvis-host '/path/to/jarvis-voice/bin/jarvis-cli --stdin --json --no-context'
```

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Command not found in an agent shell | Use `/path/to/jarvis-voice/bin/jarvis-cli`; functions defined in Bash/Zsh RC files are not automatically present in noninteractive shells. |
| Missing production environment | Complete `./install.sh`, or set `JARVIS_VENV` to the actual production environment. Do not point it at repo `.venv`. |
| Missing mode configuration | Complete ordinary setup for `config/cloud.env` or `config/local.env`, or select the configured mode. |
| Provider/MCP error without diagnostics | Rerun a read-only inspection with `--verbose`; do not repeat a side-effecting request with an uncertain outcome merely to obtain logs. |
| Tools unavailable | Check mode ENV, tool profile and availability requirements. After changing manifests/settings, reload services and sync Tool RAG using the production environment. |
| JSON parser fails | Read exit status and stderr first; usage/launcher errors do not emit result JSON. Do not merge stderr into stdout when using `--verbose`. |
| Speech markup in JSON | JSON retains canonical voice output. Prefer `raw_llm_response` for display; the default human CLI removes supported delivery cues. |
| Unexpected reference to an earlier request | Use `--no-context`, and provide source references explicitly. Memory retrieval and learned guidance remain active. |
| Remote job still running after CLI exits | Inspect/collect by its job ID; process exit or Ctrl+C does not prove remote cancellation. |

JSON results and verbose diagnostics can contain user content and tool data.
Keep diagnostic files private. The CLI reads existing configuration and does
not print a credential/config dump.
