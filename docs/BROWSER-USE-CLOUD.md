# Browser Use Cloud

`browser_use_cloud` is an optional hosted browser research tool. It is separate
from [local Browser Use](BROWSER-USE.md): it needs a Browser Use Cloud API key,
but no local Chromium image, Browser Use helper, or incoming task callbacks.
Jarvis's own background-task worker makes one V4 run request, watches its status,
and returns the result to the original Web conversation. The hosted agent uses
Browser Use Cloud's model and network, not the Jarvis conversation's selected LLM
or proxy chain. It works with native Jarvis and the optional Docker task worker.

Add `BROWSER_USE_API_KEY` to the active `config/cloud.env` or `config/local.env`
as appropriate, restart Web and the task worker so they see it, then select
**Browser Use Cloud** under **Settings → Tools → Background tasks** and enable
the background master switch. A new installation without a key cannot select
the tool. Tool RAG may retain its indexed description, but request-time discovery
hides it until the key, saved selection, compatible worker, and Web authorization
are ready. Profile, ENV, and Web blocked-tool controls still apply. The manifest
cannot bind itself; `TRUSTED_BINDINGS` separately permits this reviewed tool.
After installing the new manifest, run `./bin/sync-tools.py cloud` and/or
`./bin/sync-tools.py local` with `~/jarvis-venv` activated for the chat modes you use if
startup did not refresh Tool RAG automatically.

This tool is **Web text chat and background only**. It does not run in foreground
chat, Voice, Talk, Firefox Companion, `/api/query`, CLI, schedules, or nested
workflows. A chat turn receives a receipt and frees the composer. The original
task card shows a **Watch browser live** link after Browser Use emits
`browser.ready`; the link opens the hosted viewer in a new tab. The link is a
bearer capability: anyone with it can interact with that browser. Jarvis accepts
only an HTTPS URL on `live.browser-use.com`, stores it as task progress for Web
card recovery, and excludes it from later LLM context and the final tool result.
Do not share the link. It grants browser control, including access to any
signed-in account in that run; Jarvis does not provide a read-only viewer.

The observer polls V4 events for the live link and the lightweight status route
for completion. After a terminal status, it lists active browsers belonging to
that run's agent session and stops those exact browsers before reading
the final report. If Browser Use does not confirm the stop, the late answer
includes a cleanup warning and the run ID so an operator can check the Cloud
dashboard. A lost create receipt, worker interruption, or lost observation may
leave a cloud run/browser active; Jarvis cannot safely infer its identity or
claim it stopped. V4 does not currently document webhooks, so this tool uses
`remote_skill_v1`, **not** Jarvis's
`http_callback_v1` inbox. Its live progress is short phase text, not a full
activity stream. The final Markdown report is saved to Stash and displayed in
the existing browser-research card with an **Open full research** action. Chat
display is bounded; Stash keeps the full report when saving succeeds. Confirmed
provider failure produces a failed/partial answer. A lost submit receipt or
lost post-submit observation is uncertain and requires operator review; Jarvis
does not start a second run automatically. An interrupted worker also cannot
prove the hosted run stopped. Running cloud jobs therefore have no Cancel action.
If the provider's text identifies one `outputs/*.md` path on a full-report
line, Jarvis checks that file in the run's V4 workspace and imports a bounded
Markdown copy into Stash.
The chat card keeps the concise provider summary and opens the imported report.
If the file is missing, too large, or cannot be downloaded, the card says
**Open saved summary** instead; an `outputs/` path is never presented as a
local Jarvis path or a durable download link.
When the provider returns complete billing metadata, the final card shows its
reported total of run, browser-hosting, and proxy charges. This appears after
the run, not as a live spending meter. A follow-up omits that total because the
browser/proxy endpoint reports session-wide charges that can include earlier
runs; Jarvis does not label those accumulated charges as the follow-up's cost.

By default each run submits only `task` and `maxCostUsd: 3.0` and starts an
anonymous browser. Optionally, put `BROWSER_USE_CLOUD_PROFILE_ID` in the active
ignored `config/cloud.env` or `config/local.env` alongside a Browser Use API key
from the same Browser Use project. When a user asks Jarvis to use their saved
profile or perform an action requiring their signed-in account, such as sending
an email, the model may pass `use_profile: true` without requiring the words
"use my profile." The worker checks
the configured ID and adds `browserSettings.profileId` to that one V4 run. If
`use_profile` is omitted or false, the profile ID is not sent to Browser Use
or passed into the observer process. An invalid or missing configured ID
rejects the request before a run is created. The ID is not a model-visible tool
argument. Browser Use preserves that profile's cookies/login state between
new browser sessions; Jarvis still stops the individual browser after each
terminal run. Sites can expire cookies or demand new verification. A recipient
address is not evidence of which account is signed in. Jarvis should ask the
browser agent to use an existing session if available, put recipient addresses
only in destination fields, and report a login challenge if the session is
unavailable. If the user specifies a required sender account, the agent must
verify it before sending.

## Follow up on a finished run

Reply in the same Jarvis Web conversation with the clarification or next
instruction. Jarvis can pass the earlier background job ID as
`continue_job_id` to `browser_use_cloud`; it resolves that conversation-owned
job to the provider's V4 session and creates a capped follow-up run there.
The earlier profile choice carries forward. The V4 session retains the agent
conversation, and the workspace retains files. Jarvis stops the hosted browser
after each finished run, so a later reply may need to reopen the page; the
configured profile ID is sent again so the new browser can restore login state.
A new background job and its own $3 run cap
apply to each follow-up. Jobs in another Jarvis conversation or generation
cannot be used as a follow-up. The prior job result must still be retained in
Jarvis's background task store. Each Cloud job can have one accepted follow-up;
continue the latest finished follow-up for the next reply. A definite rejection
before a run starts permits retrying the same prior job. Jarvis checks that the
provider session still points to the prior run and has finished before submitting.

Wait for the earlier task card to finish before replying with a continuation.
The V4 session queue can accept a message while a run is busy, but its message
request has no per-run `maxCostUsd` field, so Jarvis does not use it here.

Optionally, put `BROWSER_USE_CLOUD_WORKSPACE_ID` in the same env file. When set
to a V4 workspace UUID from the same Browser Use project, each new session run
includes `workspaceId` so uploads and generated files persist across jobs and
sessions. A follow-up run inherits the earlier session's workspace.
Leave it empty to let Browser Use create a fresh workspace per run. An invalid
configured ID rejects the request before a run is created. The ID is not a
model-visible tool argument. A workspace is file storage, not login state;
`use_profile` is unchanged. Browser Use does not treat a shared workspace as a
live filesystem between simultaneous runs: finish one writer before starting
another job that needs its files. A V3 workspace ID is not a V4 workspace ID.

The Cloud observer is a supervised Python child process. Its reviewed child
environment contains the Browser Use API key, the workspace ID when configured,
the profile ID only for a profile-requested run, and the minimum runtime
settings needed for Stash, HTTPS, mode and process supervision. It does not
inherit the whole cloud/local ENV or unrelated provider/Jarvis API credentials.
This narrows environment exposure; it is not a filesystem sandbox against files
readable by the worker's OS user. Do not put credentials into the task prompt
or the live-view URL.

This integration does not upload Jarvis files, attach staged Cloud file IDs,
pass Jarvis credentials, or select a custom proxy. A configured V4 workspace
only reuses that Cloud workspace; previous uploads there are restored by
Browser Use. The run cap does not replace browser shutdown; a run may stop before
the research goal is complete. The reviewed Jarvis deadline is 30 minutes including
queue time. The script never retries the create POST, but safe status/result GETs
may retry until that deadline. Browser Use Cloud can interact with websites,
including a signed-in profile's accounts. Tool descriptions tell the model to
use the saved profile only when requested and to avoid unrequested changes;
these are instructions, not a browser-enforced authorization or read-only policy.
Jarvis does not select a Cloud model in this version; the API chooses its default,
and the result card shows the model actually used.

Official API references: [V4 quickstart](https://docs.browser-use.com/cloud/quickstart),
[sessions](https://docs.browser-use.com/cloud/agent/sessions),
[run creation](https://docs.browser-use.com/cloud/api-v4/runs/create-run),
[run detail](https://docs.browser-use.com/cloud/api-v4/runs/get-run),
[run status](https://docs.browser-use.com/cloud/api-v4/runs/get-run-status),
[workspaces](https://docs.browser-use.com/cloud/agent/workspaces),
[workspace files](https://docs.browser-use.com/cloud/api-v4/workspaces/list-workspace-files),
[browser list](https://docs.browser-use.com/cloud/api-v4/browsers/list-browser-sessions),
[browser stop](https://docs.browser-use.com/cloud/api-v4/browsers/update-browser-session),
[live preview](https://docs.browser-use.com/cloud/browser/live-preview), and
[webhooks](https://docs.browser-use.com/cloud/guides/webhooks).
