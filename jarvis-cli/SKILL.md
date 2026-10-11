---
name: jarvis-cli
description: Drive a configured Jarvis Voice installation through its CLI to answer questions, run tools and workflows, manipulate files, and inspect structured outcomes from another agent harness.
---

# Drive Jarvis CLI

Use Jarvis when the user wants its configured models, tools, workflows or
integrations to perform the task. Read [README.md](README.md) for flags, setup,
output fields and troubleshooting. Locate the actual Jarvis checkout and its
production environment from the session; do not assume this skill's installed
folder is the checkout.

Use the absolute executable `JARVIS_CHECKOUT/bin/jarvis-cli`, or
`bin/jarvis-local-cli` for local mode. Shell aliases need a sourced Bash/Zsh RC
file; executable launchers work directly in other harnesses. They use
`~/jarvis-venv` or the explicitly configured production `JARVIS_VENV`, not the
checkout's development `.venv`. Use `--help` for current supported options.
Do not install packages or reconfigure models/credentials merely to run a
request against an already configured installation.

For agent calls, use `--json --stdin --no-context` with a subprocess argument
array and the user's request supplied as stdin. A quoted literal shell prompt
also works, but never interpolate arbitrary user text into shell code. Select
`--mode cloud|local` explicitly when mode matters. On another host, use the
user's authorized SSH connection and feed the prompt through stdin.

Express the authorized task naturally, naming an integration when relevant
and passing exact source paths or `stash://` references when available. Jarvis
uses its own normal tool policies; delegating a task does not expand the user's
authorization to unrelated actions. `--no-tools` is available for direct Q&A;
`--exclude-tool` can narrow calls for this request.

Read the process exit status and parse the whole stdout as one JSON object.
Parse returned JSON even when the exit status is nonzero; failed requests can
still carry speech, errors and tool evidence. If there is no JSON, inspect
stderr for usage/launcher errors.
Check `ok`, `error`, `tools_used`, `tool_trace` and domain-specific `data`.
Report actual output references and verified states; the model's summary alone
is not proof of execution. Keep relevant job IDs, Stash references and native
project IDs for follow-ups. File paths belong to the Jarvis host; transfer files
only through the user's authorized transport when needed.

For a live feature test, use a small disposable input and a representative
request through this CLI. Verify the actual returned artifact or service state
with the appropriate file inspector, service query or logs. Distinguish tool
routing, accepted/running jobs and verified completion in the report. The CLI's
JSON and verbose diagnostics provide the starting evidence; use additional
read-only checks when they do not establish the outcome.

A running receipt or unknown completion is not a completed manipulation.
Inspect or collect the accepted job instead of repeating the task. An outer
agent timeout, lost SSH connection or Ctrl+C does not prove remote cancellation.
Do not replay a successful task because optional TTS/QA delivery failed.
Use `--verbose` for diagnostics on stderr, preferably on a read-only inspection
after an uncertain side effect. Keep diagnostic output private.

`--no-context` disables recent-conversation auto-context, not memory retrieval
or learning/logging. There is no named isolated CLI conversation in this
version. Include the needed prior facts and exact references in each follow-up
when the outer harness owns the conversation. Let ordinary users keep normal
automatic context unless they request otherwise.

Return a concise account of what Jarvis did, usable file/job references, and
any actual error or unfinished work. Do not claim success from exit code 0
alone when a remote job is still running.
