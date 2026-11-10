# Optional Google Workspace service

Jarvis can use a dedicated **consumer Gmail account** through
[Google Workspace MCP](https://github.com/taylorwilsdon/google_workspace_mcp).
The pinned v2.4.0 container exposes 111 tools in its complete tier for Gmail,
Drive, Calendar, Docs, Sheets, Slides, Forms, Tasks, Contacts and Apps Script.
This standalone Compose project is optional. A fresh clone has the MCP ENV
gate off and never connects to or starts this service.

The service owns Google OAuth, automatically refreshes access tokens, and stores
grants in its ignored `data/` directory. Jarvis only sends a private service
token and tool arguments. Neither `cloud.env` nor `local.env` is mounted into
the container. Account passwords and app passwords are not used for these APIs.
There are no new Jarvis Python dependencies or database migrations.

## Google Cloud setup (once)

1. Sign in to [Google Cloud Console](https://console.cloud.google.com/) and
   create/select a project for Jarvis. The project owner can be your operator
   account; the later consent login must be Jarvis's dedicated account.
2. Enable these APIs under **APIs & Services → Library**:

   | Service | API ID |
   | --- | --- |
   | Gmail | `gmail.googleapis.com` |
   | Drive | `drive.googleapis.com` |
   | Calendar | `calendar-json.googleapis.com` |
   | Docs | `docs.googleapis.com` |
   | Sheets | `sheets.googleapis.com` |
   | Slides | `slides.googleapis.com` |
   | Forms | `forms.googleapis.com` |
   | Tasks | `tasks.googleapis.com` |
   | Contacts / People | `people.googleapis.com` |
   | Apps Script | `script.googleapis.com` |

   With an already authenticated project-administrator `gcloud` session, an
   operator/AI can enable them together (replace `YOUR_PROJECT_ID`):

   ```bash
   gcloud services enable --project=YOUR_PROJECT_ID \
     gmail.googleapis.com drive.googleapis.com calendar-json.googleapis.com \
     docs.googleapis.com sheets.googleapis.com slides.googleapis.com \
     forms.googleapis.com tasks.googleapis.com people.googleapis.com \
     script.googleapis.com
   ```

3. Under **Google Auth Platform → Branding**, configure an app name and
   required support/developer email. Choose **External** audience, since this
   is a consumer account. Under **Audience**, publish to **In production**
   **before granting access**. Testing grants with these scopes expire in
   seven days; changing HTTP to HTTPS does not fix that.
4. Under **Clients**, create a **Web application** OAuth client. Add exactly
   `http://localhost:8765/oauth2callback` under **Authorized redirect URIs**.
   The localhost callback needs no JavaScript origin, domain, certificate, or
   public ingress. Google may require app-domain URLs on **Branding** before
   **Publish app** becomes available. Add the corresponding authorized domain;
   use a domain you control if pursuing domain/brand verification. These URLs
   describe the app and its privacy practices, and do not require exposing MCP.
5. Put these settings in the selected `config/cloud.env` or `config/local.env`:

   ```dotenv
   GOOGLE_ACCOUNT=jarvis-account@gmail.com
   GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
   GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
   ```

   Alternatively, keep a downloaded Web client JSON outside Git and supply
   `--client-json /absolute/private/path/client_secret.json` to `prepare`.
   Never paste secrets into an AI conversation or commit them.
6. For Apps Script operations, also enable **Google Apps Script API** in the
   dedicated account's [Apps Script user settings](https://script.google.com/home/usersettings).

Google permits a personal-use verification exception for a few known users.
The **Publish branding** prompt is separate from **Audience → Publishing status**.
Check that the latter explicitly says **In production**; a pending branding
review does not itself establish that the app is in Testing. See Google's
[audience settings](https://support.google.com/cloud/answer/15549945?hl=en),
[branding settings](https://support.google.com/cloud/answer/15549049?hl=en), and
[personal-use exception](https://support.google.com/cloud/answer/13464323?hl=en).
An unverified-app warning and user cap can still apply. Authorize only your
own known client; use the Advanced continuation if Google offers it. “In
production” controls OAuth token lifetime; it does not put this server on the
internet. Refresh tokens can still be revoked, or expire for other Google
reasons, so this is not a promise that consent is permanent. See
[Google's OAuth policies](https://developers.google.com/identity/protocols/oauth2/policies)
and [token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

## Start and consent on a headless native host

From the Jarvis checkout, with Docker Engine and Compose installed:

```bash
bin/jarvis-google --mode cloud prepare
bin/jarvis-google start
bin/jarvis-google check
bin/jarvis-google auth
```

The helper explicitly requests offline access and fresh consent, preserving
OAuth state and PKCE. If you first authorized in Testing, publish to production
and run `auth` once more to replace that Testing grant with a newly issued grant.

`prepare` copies only account identity and OAuth client settings from the
selected mode, generates a private MCP token, and creates storage with mode
0700 and a service `.env` with mode 0600. The optional client JSON flag goes
after `prepare`. The account is pinned; preparing with a different account
refuses to mix its grants. `check` can list tools before Google consent.
After changing OAuth settings, run `prepare` and `start` again to recreate
the container with the new settings.

On the desktop where your browser runs, open an SSH tunnel and keep it open
until consent finishes (replace `user@server`):

```bash
ssh -N -L 8765:127.0.0.1:8765 user@server
```

Open the Google URL printed by `auth`, log in as the **dedicated** account,
and grant all requested permissions. The callback reaches the server through
the tunnel and saves an offline refresh token. The tunnel is only needed for
browser consent. Do not open the callback URL manually or copy its authorization
code into chat. If port 8765 is occupied on the desktop, stop that listener
before opening the tunnel; the redirect URI must continue to match.

```bash
bin/jarvis-google check --live
bin/jarvis-google --mode cloud enable
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
# Restart your Jarvis Web/voice process to rebuild its MCP registry.
```

`check --live` reads Gmail labels, one Drive result, and one calendar, printing
only pass/fail. `enable` refuses an absent refresh token or mismatched OAuth
client, repeats those read checks, then writes the MCP enable flag, URL and
service token into **only the selected mode ENV**. For local mode, set the same
`GOOGLE_ACCOUNT` in `local.env` and run `--mode local enable` and a local sync.
The service can be shared by cloud/local Jarvis, but each mode opts in explicitly.
Tool RAG sync uses the operator environment because the repository `.venv`
intentionally cannot perform production embedding sync. Codex must request
network escalation on the first sync attempt, per the project instructions.

Tool names use `mcp_google_workspace_<upstream_name>`. Jarvis binds every call
to the configured dedicated account and removes `user_google_email` from the
model-facing parameters. Tool descriptions identify that account; the model
never needs to guess or search memory for the login address. Recipient and
sharing-target fields remain available. Existing profiles can disable particular
tools, and enabling a server does not override a profile's explicit false entries.
Native sends to Gmail do not use the n8n/Mailgun HTML template; the existing
`send_email` tool continues to work separately.

Gmail sends and drafts share `send_email`'s local `config/contacts.json` lookup.
The `to`, `cc` and `bcc` fields accept contact keys or display names
(case-insensitive), explicit email addresses, or comma-separated recipients.
For example, “use Gmail to email Boss” can pass `Boss` directly to the Gmail
tool. Unknown names fail before a Google call; a missing or malformed contacts
file still permits explicit addresses. Lookup reads the current file on each
call, and only the selected recipient addresses are sent to Google. The local
contact list is separate from Google Contacts and does not select the sending
account or configure Gmail Send As aliases.

The read-only `email_contacts` tool lists or searches these local aliases without
sending mail; use `tool_search` to discover it if needed. A lookup is optional
when the user already supplied a recipient. Google Workspace
`list_contacts`, `search_contacts`, and `get_contact` inspect Google Contacts,
not `config/contacts.json`. Neither a Google Contacts miss nor a memory miss
establishes that a local alias is absent or that an explicit address cannot be used.

Tool descriptions prefer `send_email` for ordinary outgoing email when that
tool is available. Explicit Gmail/Google Workspace delivery and Gmail replies
or forwards use `send_gmail_message`. This is description guidance under the
existing profile and block-list checks; it does not enable either tool.

## Access and results

For opt-in scheduled email-to-Jarvis requests, see the
[email command inbox guide](../docs/tools/email-inbox-tool/README.md). Its
approved senders are separate from ordinary recipient contacts.
The published [request sequence](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-email-inbox-sequence.html)
and [data-flow chart](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-email-inbox-dataflow.html)
show Gmail polling, sender authentication, private state and threaded replies.

For **Jarvis itself in Docker**, use the optional root overlay after preparing
and authorizing the standalone service. Stop that standalone instance first,
then run your normal Compose stack with `docker-compose.google.yml` added last
and `--env-file google-workspace/.env` added after any existing env-file options:

```bash
bin/jarvis-google stop
docker compose --env-file .env --env-file google-workspace/.env \
  -f docker-compose.yml -f docker-compose.google.yml up -d --build
```

This reuses the same private storage and adds the service to Jarvis's network.
The overlay overrides the MCP URL to `http://google-workspace:8000/mcp` only
inside the Jarvis containers. `127.0.0.1` inside a Jarvis container cannot reach
the host's standalone listener. The host still publishes only loopback 8765 for
browser consent; no additional public port or Google credentials are attached
to Jarvis. Keep any existing MCP/browser overlays in your normal stack command.
The helper's `start`/`stop` commands operate on the standalone project; when
using the overlay, manage service lifecycle with that stack's Compose command.
The selected mode ENV still needs `enable`, Tool RAG sync, and a registry restart.

The default complete tier uses the upstream **full** permission levels.
This dedicated-account setup runs autonomously: sends, sharing, deletion, uploads
and script execution do not require a Web confirmation. Upstream annotations
classify side effects, while `auto_approve=true` preserves this explicit operator
policy. Email and document text remains untrusted data, not authorization to act. It
includes writes, sends, sharing, modifications and supported deletions rather
than a read-only subset. These are the server's supported Google API operations,
not authority to change account passwords, security settings or organization
administration. Gmail full uses the upstream Gmail scopes, not unrestricted
`mail.google.com` access. Chat requires managed Workspace and is excluded.
Custom Search needs its own API key/search-engine configuration and is excluded.
Other Google products are not automatically covered by this MCP server.

The upstream legacy HTTP mode has no MCP authentication. The small container
entrypoint adds a constant-time Bearer-token check for MCP and attachment routes.
Only GET `/health` and `/oauth2callback` are public, with the callback protected
by upstream OAuth state handling. The host port is bound to `127.0.0.1:8765`;
the container's internal network listener requires the token. Keep this setup
local. A remote/Coolify deployment needs a separately configured HTTPS ingress
and a matching callback URL; this configuration does not expose a public service.
Jarvis's server policy is `off` so this local service token is never sent through
`LOCAL_PROXY` or process HTTP proxies. The service makes its own outbound HTTPS
requests directly to Google.

The HTTP Host allowlist is `localhost,127.0.0.1,google-workspace`, covering
native loopback requests and the Docker service name. Upstream
`WORKSPACE_MCP_ALLOWED_HOSTS` takes bare hostnames or IP addresses, without a
scheme or port; it checks the host while allowing that host's ports. A matching
browser Origin does not authorize an unlisted Host. This check also applies to
public health and callback routes; the Bearer check still protects MCP and
attachments. If you customize the service hostname, review both the allowlist
and endpoint configuration rather than disabling the Host check.

OAuth grants, cached attachments and logs are inside `google-workspace/data/`,
which is ignored by Git and excluded from both Docker build contexts. The
upstream image is fixed by tag **and digest**. It runs as the host operator's
UID/GID with dropped capabilities. Treat its persistent directory as a secret
backup: it contains refresh tokens. Uvicorn access logging is disabled to avoid
recording OAuth callback codes. No Google credentials reach the language model.

Jarvis normalizes actual upstream text/structured receipts, preserving labeled
IDs, response links and request identity. Web results show a Google Workspace
card with an escaped plain-text reader and creation-receipt/consent links. Saved
follow-ups and provider/workflow context retain bounded evidence for the latest
runs without combining IDs from different requests. Mail/document contents are
untrusted data, and excerpts explicitly report truncation. A response can only
identify an item when upstream actually supplied its ID/link; no receipt or URL
is invented. Labeled IDs are cleaned in both structured references and model-facing
prose, so punctuation cannot turn a returned file ID into a different ID.
Freshness reuse windows apply to configured time-sensitive tools such as prices;
a successful Google read is a current snapshot and a successful write is an
operation receipt. Internal freshness/trust flags and context sizes are not
user-facing caveats. Compacting a complete receipt or dropping its duplicate
upstream text does not imply missing content; actual omissions remain flagged.
Gmail Draft IDs and Message IDs are separate. To inspect a created draft, search
with `in:drafts` and its subject, then pass the returned Message ID to
`get_gmail_message_content`. Jarvis rejects draft IDs at that message endpoint.

### Tool RAG descriptions and discovery

The server-level `description` in `config/mcp-servers.json` documents the
integration; it is not copied into every tool or independently embedded. Tool
RAG indexes each registered tool's description, and the model sees descriptions
for the tools selected for that turn (or explicitly discovered with `tool_search`).

Local `tool_metadata.<upstream_tool_name>.description_prefix` supplements an
upstream description with practical wording and example requests. The original
upstream description and schema are retained. Change these local prefixes and
sync Tool RAG to tune discovery without modifying the upstream Docker image.
Gmail, Drive, Docs, Sheets and Apps Script tools have these supplements.

`prerequisite_tools` in the same metadata declares companion schemas needed to
resolve required inputs. The Drive download tool includes Drive search so a
request naming a file can obtain its ID. Existing router bounds, active-profile
filtering and exclusions still apply; this does not force a search call when a
valid file ID is already available.

Apps Script execution includes `get_script_project` as a companion schema.
Listing projects returns names and IDs together, with pagination when needed;
it does not discover callable functions. When a function or its arguments are
unknown, inspect the project and read the relevant named source file before
execution. Known functions can run directly. Source reads show current saved
code; ordinary execution selects a deployed version unless the user requests
latest-code execution with `dev_mode=true`.

Named Apps Script source reads have a bounded 6,000-character model-context
budget, including receipt metadata and JSON escaping. Saved Web follow-ups share
7,500 characters across up to three recent results from this tool and reuse spare
space from short receipts for source. A file that fits is retained completely;
longer files remain explicitly marked as truncated. Ordinary Google result
excerpts keep their existing limits. A partial source excerpt does not establish
a callable function or its arguments.

### Apps Script workflows and scheduled tasks

A deterministic recipe can read the time, run a known function, then save its
actual execution receipt to Canvas without LLM parameter filling or a summary.
Save an adapted recipe under `data/workflows/personal/`; replace the script ID and verified
function name, and adjust positional `parameters` to that function's signature
(`[]` for no arguments). Keep a short natural-language description so normal
`workflow` discovery can find it, for example: "run the Apps Script readiness
report workflow". The explicit command and Scheduled Tasks remain available too.

```json
{
  "id": "apps_script_report",
  "name": "Apps Script report",
  "description": "Get the time, run the configured Apps Script readiness check, and save its result to Canvas.",
  "enabled": true,
  "allow_workflow_tool": true,
  "triggers": {"explicit": ["/apps_script_report"]},
  "variables": {
    "report_timezone": {"from": "env", "key": "JARVIS_TIMEZONE", "default": "UTC"}
  },
  "steps": [
    {
      "step": 1, "tool": "get_time", "required": true,
      "params": {"timezone": "${report_timezone}"}, "output_var": "clock"
    },
    {
      "step": 2, "tool": "mcp_google_workspace_run_script_function", "required": true,
      "params": {
        "script_id": "REPLACE_WITH_SCRIPT_ID",
        "function_name": "REPLACE_WITH_VERIFIED_FUNCTION",
        "parameters": ["${clock.date}", "${clock.time}"]
      },
      "output_var": "script_run"
    },
    {
      "step": 3, "tool": "canvas", "action": "create", "required": true,
      "params": {
        "title": "Apps Script report ${filename_timestamp}",
        "content": "# Apps Script report\n\nStarted: ${clock.date} ${clock.time} ${clock.timezone}\n\nReceipt truncated: ${script_run.response_truncated}\n\n```text\n${script_run.response_text}\n```"
      }
    }
  ],
  "success_speech": "Apps Script finished and its receipt was saved to Canvas."
}
```

The time step uses the existing configured `JARVIS_TIMEZONE`, falling back to
UTC; an empty `get_time` request would use the host's local time. Parameter
binding uses canonical tool data, without the general Google chat preview's
2,200-character cap. `response_text` retains at most 16,000 characters;
`response_truncated=true` means the receipt was shortened. The report saves that
receipt and flag directly, rather than a queued-job receipt or an LLM summary.

The workflow waits for the foreground Apps Script call before creating Canvas.
Scheduled Tasks uses this same path, independently of Web's optional background
feature. The tool budget is 390 seconds and its executor guard is 395 seconds;
a scheduled task's default **300-second whole-run timeout** can cut it short.
For this basic flow, select workflow `apps_script_report` and set the task's
`timeout_seconds` to **600**, allowing time for startup and the other steps.

Saving a workflow installs no recurring schedule. To test through Scheduled
Tasks, create a disabled task and choose **Run Now**: that queues one execution
while keeping the task disabled afterward. No new service or environment
setting is required. If Google execution becomes uncertain after a timeout or
lost response, inspect that execution before rerunning the workflow.

### Practical Apps Script examples

Apps Script is useful for repeatable work across several Google apps in one
function. These are ideas for scripts to build or adapt and deploy, rather than
additional preinstalled Jarvis tools. Once connected to a workflow, requests can
look like these:

| Services | Useful automation | Example chat request after setup |
| --- | --- | --- |
| Drive | Sort new uploads into client/project folders and record their links in a Sheet. | "Run my Drive filing workflow and show what was organized." |
| Docs + Sheets | Fill a proposal, contract, or weekly-report template from spreadsheet rows; save the finished documents. | "Generate this week's client reports from the reporting sheet." |
| Sheets | Clean imported rows, remove duplicates, update formulas and charts, and calculate a weekly summary. | "Refresh my sales dashboard and save the totals to Canvas." |
| Gmail + Sheets | Personalize a mail merge from a Gmail draft and mark successfully sent rows. | "Run the approved customer follow-up mail merge." |
| Forms + Drive + Gmail | Process registration responses, organize uploaded files, and send confirmation emails. | "Process the new event registrations and report the count." |
| Slides + Sheets | Populate a presentation template with current metrics and spreadsheet charts. | "Build this month's performance deck from the metrics sheet." |
| Calendar + Sheets | Create events from approved spreadsheet rows and write event IDs back for later updates. | "Sync the approved training sessions to my calendar." |
| Sheets + Drive + Gmail | Generate invoice PDFs, save them in Drive, send them to the intended customers, and record delivery. | "Generate and send this month's invoices, then publish a Canvas summary." |

For example, a scheduled workflow could run **get time → refresh sales data and
build a Slides deck → Canvas report with totals and document links**. Return
created file IDs, URLs, counts, and per-item outcomes from the script so Jarvis
can report what actually happened. For repeatable sends or creates, keep a
processed-row marker or existing resource ID so later runs resume correctly.

Google provides starting points for [mail merge](https://developers.google.com/apps-script/samples/automations/mail-merge),
[invoice PDFs and email](https://developers.google.com/apps-script/samples/automations/generate-pdfs),
[Forms uploads organized in Drive](https://developers.google.com/apps-script/samples/automations/upload-files),
and [Sheets charts in Slides](https://developers.google.com/codelabs/apps-script-fundamentals-5),
plus a broader [sample catalog](https://developers.google.com/apps-script/samples).
Adapt menu- or trigger-driven samples into callable functions with explicit
file IDs and positional arguments for Jarvis execution; they should not depend
on an open spreadsheet, editor dialog, or a form-submit event being present.

### Formatted documents, sheets and Gmail

These operations use existing tool names; upgrading does not add a separate
application or workflow. Use `mcp_google_workspace_` before the names below
when calling them through Jarvis.

- **New Markdown document:** `import_to_google_doc` accepts inline `content`
  with `source_format="md"` or a `file_name` ending in `.md`. `create_doc`
  inserts plain text, so Markdown syntax in its content remains literal.
- **Markdown in an existing document:** inspect the document for its `tab_id`,
  then call `manage_doc_tab(action="populate_from_markdown", markdown_text=...,
  tab_id=..., document_id=..., replace_existing=false)` to append. The default
  `replace_existing=true` clears the target tab body. Top-level pipe tables
  become native tables; tables nested in lists or blockquotes, or above the
  converter's size limits, fall back to text. Unknown tabs now fail instead of
  silently targeting the first tab. `debug_table_structure` also accepts `tab_id`.
- **Recovery copy before a large rewrite:** `copy_drive_file` creates a separate
  file. Use the original's parent folder ID, a recognizable snapshot name and
  optional `copy_comments=true` for open comments. Keep the returned copy ID.
  Search before retrying an uncertain copy because Drive permits duplicate
  names. Copies do not preserve revision history or the original's direct
  sharing. Restoring content into the original preserves its ID and links;
  switching to the copy requires reviewing sharing and updating links. This is
  a recovery copy, not a named revision or automatic undo.
- **Sheet formatting:** `format_sheet_range` adds `borders`, dropdown choices
  through `dropdown_values`, and `merge_cells`/`merge_type`. Inspect the sheet
  and read affected cells first: merging retains only each merged group's
  top-left value. `clear_dropdown=true` removes every validation rule in the
  range, including checkboxes. `manage_sheet_tab(action="style")` sets
  `tab_color` and `show_gridlines`; gridlines apply to GRID sheets.
- **Gmail composition:** send and draft support `direction="auto"`, `"ltr"`
  or `"rtl"`. Use `thread_id` for a reply and `quote_original=true` when the
  previous message should appear; quoting defaults to false. Forward with
  `forward_message_id` so upstream carries the original content and attachments.
  Attachment-free composition uses the new Gmail-style MIME builder; ordinary
  compose/reply with attachments retains the existing builder. HTML input must
  contain real markup: an entity-escaped opening tag with no real HTML tags is
  rejected before sending or drafting. Do not unescape arbitrary message text
  to work around this validation.
- **Whole Gmail conversations:** `batch_modify_gmail_message_labels` accepts
  `thread_ids` as well as individual `message_ids`. Remove `INBOX` to archive
  a conversation or `UNREAD` to mark it read. Read the Applied, missing and
  Failed outcomes before reporting success; a partial result does not establish
  that every conversation changed.

Omit `from_email` unless a sending alias is requested. Upstream checks aliases
against readable Gmail Send As identities, but this is best-effort validation:
regular sends/replies skip it when `include_signature=false`, regular drafts
skip it for an explicit alias with signatures disabled, and missing settings
authorization skips validation. Forward sends check explicit aliases regardless
of the signature flag; forward drafts look up the identity. The settings-list
API accepts `gmail.readonly`, so an optional `gmail:readonly+send` scope union
does not inherently lose alias/signature lookup. This setup retains its full
permission policy; changing scopes would require reviewing lost tools and the
existing grant separately. See the [Google Send As scope reference](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.settings.sendAs/list).

Account binding uses discovered tool properties that survive a transport cache
reset. The pinned account-independent `generate_trigger_code` helper also works
before any discovery, without receiving `user_google_email`. The private
container wrapper bypasses upstream's blanket account injection only for this
pure code-generation helper; base validation and MCP middleware still run.
All Google API tools keep their normal upstream account handling.

### Optional Stash transfers

Jarvis extends the discovered file tools with small optional parameters. These
options are handled by the Jarvis MCP client, without changing the upstream tool
names or sending Stash options to Google:

- `get_drive_file_download_url`, `get_gmail_attachment_content`, and
  `get_gmail_message_content`: set `stash=true` to copy the returned file into
  Jarvis Stash. The default is false. For a full Gmail message, this also requests
  the upstream `full=true` export; `body_format=raw` produces an EML file.
- `stash_space_id`: optionally reuse an existing Stash space on these downloads.
  Identical bytes with the same MIME type already in that space reuse the stored
  file, rather than creating another copy.
- `create_drive_file`, `update_drive_file`, and the three
  `import_to_google_doc` / `import_to_google_sheets` / `import_to_google_slides`
  tools: supply `stash_ref` instead of another file source. Jarvis stages only
  that selected file in the service attachment cache and removes the staging
  copy after the call. Interrupted cleanup leaves an expiring cache file.
  Container `file_path` is hidden from the model and `file://` input is rejected;
  only staging supplies a container path. Inline content and public HTTP(S) URL
  sources remain supported, with the pinned upstream's private-network, DNS,
  redirect and local-directory validation.

For example, download a Drive PDF with `file_id` and `stash=true`, then pass the
returned `data.artifacts[0].ref` (`stash://...`) to a PDF or file manipulation tool.
Upload a resulting Stash file with `create_drive_file(file_name=..., stash_ref=...)`.
Account identity is supplied automatically. Routine Google searches, text reads,
edits and sharing do not create Stash copies. Inline images returned by the
v2.2.0 image readers use the bounded image bridge described below.

The service keeps its own temporary attachment cache. Explicit Stash transfers
and returned inline images add persistent copies, using the canonical helper and the active
mode's `STASH_DIR` / runtime override, with normal source-artifact retention
(default 120 days). No Stash directory is mounted in the Google container and
no symlinks are created. A reentrant lock on the Stash root directory inode
serializes local mutations, including deduplication/saves, without leaving lock
files behind after spaces are deleted. Network transfers happen outside the lock, and
atomic manifest edits retain concurrent files and metadata changes. Transfers are bounded to 50 MiB and the MCP call deadline.
Stash upload references survive follow-ups; downloaded artifacts retain their
Stash reference, filename, MIME type, size and mode-specific Web download link.
When a Stash copy exists, model previews use its same-origin browser download
route instead of the private Google attachment-cache URL. Original upstream
receipts remain saved for inspection; the Stash link does not inherit the
Google cache's one-hour expiry.
Web result cards offer **Download file** through the authenticated Jarvis Stash
route. Message/document body URLs stay in the untrusted text. Links default to
untrusted for every tool, including future tools; only `create_doc`,
`create_spreadsheet`, `create_presentation`, `create_form`, `create_drive_file`,
and `create_drive_folder`
receipts can add Google resource buttons. Explicit authentication-required
receipts can add consent buttons. This also applies to older saved results. The
untrusted-content note is visible on the card, not only in its expanded reader. Temporary service attachment URLs still require the service token.

If Google finishes a download but the optional Stash copy fails, the receipt
reports `google_ok=true` alongside `stash_error` and overall `ok=false`; it does
not claim that the Stash file exists. Never repeat a write merely because its
transport timed out.

### Recovery without a Jarvis restart

Streamable HTTP retries once after an explicit HTTP 404 **Session not found**
for a known session: initialize a new session, then repeat the rejected request.
Authentication errors, unrelated 404s and network timeouts do not replay writes.
Notifications include the session header. Tool discovery follows `nextCursor`
with a bounded page count and rejects repeated cursors.
Malformed individual tool schemas are skipped without hiding the valid tools.
Synthesis context keeps projected JSON blocks complete within its total budget
and explicitly reports omitted results.

If an HTTP server with `retry_discovery=true` was unavailable during startup,
subsequent tool selection retries it on demand, at most every 30 seconds per
server, with its own three-second probe deadline. Google opts in; DeepWiki and
Malwarebytes retain their existing startup discovery. Ordinary tool lookup and
listing do not perform network probes. Concurrent selectors share the probe
and see the same recovered catalog. Healthy clients and stdio Docker processes
are left running. Recovery applies the same allowlist and active profile, then
restores permitted search rows without an embedding call. New or changed rows
with pending embeddings can qualify by keyword coverage in normal hybrid Tool
RAG even while other tools have healthy vectors; a normal sync later embeds
them. This is a general hybrid-search fallback for unembedded, enabled rows;
active registry/profile/allowlist visibility still governs callable tools. A
stored vector below the dense threshold does not gain this exception. `BLOCKED_TOOLS` remains
excluded. Changing enablement, credentials or profiles still needs the normal
registry reload; temporary downtime no longer requires restarting Jarvis.

## Upgrading to 2.4.0

The [v2.4.0 release](https://github.com/taylorwilsdon/google_workspace_mcp/releases/tag/v2.4.0)
retains 111 tools in this configuration, with one breaking rename:
`create_calendar` is removed. Use `manage_calendar(action="create", summary=...)`
with the same creation parameters. Calendar creation remains separate from
creating an event with `manage_event`. Refresh Tool RAG and each enabled mode's
registry so the removed name is no longer offered.

The Dockerfile pins the multi-platform image digest and reviewed source
`53c392dc426ca8795e27dcf0301f92b5abe85688`. Existing Google grants, the private
service token, localhost binding and `data/` storage are reused; this upgrade
does not require fresh consent, Jarvis dependency changes or a database migration.

Useful additions through existing tools:

- **Calendar sharing:** `manage_calendar` supports `list_sharing`, `share`,
  `update_sharing` and `unshare`. Read current ACLs and use the returned `rule_id`
  for a change. Select the intended user/group/domain scope explicitly;
  `scope_type="default"` is public access. Sharing notifications default on;
  account for the requested recipients and notification behavior. Upstream
  explicitly protects the authenticated account's primary-calendar owner rule;
  preserve owner access on other calendars too. Jarvis retains the Calendar and
  ACL rule IDs in saved follow-ups and uses upstream side-effect annotations with the existing
  dedicated-account approval policy.
- **Docs section reads:** `get_doc_content` and `get_doc_as_markdown` accept
  `heading` and optional `heading_level`, matching a unique heading and including
  its subsections through the next equal/shallower heading. Use the intended
  `tab_id` for multi-tab documents. `get_doc_content` section selection is for
  native Google Docs. Treat the result as a section, not a full-document read;
  add the reported section start index to section-relative text offsets before
  indexed edits. `preserve_context` annotations are not edit offsets. Markdown
  comments remain document-wide even when body content is filtered by heading.
- **Copy a tab across spreadsheets:** `create_sheet` accepts the source tab
  and `destination_spreadsheet_id`, preserving formatting and formulas before
  renaming/positioning the copy. A failed rename attempts to remove the new copy;
  inspect the destination if cleanup fails. Keep source and destination IDs
  distinct and inspect the destination before retrying
  after an uncertain response.
- **Drive shortcuts:** `create_drive_file(shortcut_target_id=...)` creates a
  shortcut to an existing file or folder without copying the target. Preserve
  the shortcut's returned ID separately from `shortcut_target_id`.

Streamable HTTP clients can optionally narrow tools per request with
`X-MCP-Toolsets` and `X-MCP-Tools`. Both headers together form a union of their
filters, and can only narrow the services/tier/permissions already loaded.
Excluded calls are rejected too. Jarvis leaves these headers unset to retain
its configured complete catalog. This feature does not replace Bearer auth,
account binding or the Host boundary. Chat pagination does not enable Chat for
this dedicated consumer account; Chat remains excluded. Multi-account refresh,
case-insensitive single-account credential lookup and fast-restart port fixes
are inherited from upstream without new Jarvis patches.

The pinned upstream image now contains all 14 packages from the former security
overlay at the same versions and with the same locked artifact hashes:
FastMCP/slim 4.1.4, openapi-pydantic 0.6.0, OpenTelemetry 1.45.1/0.66b1 and
pypdf 6.21.4. The redundant `security-requirements.txt` and replacement-install
layer are removed; the build still checks installed dependency compatibility.
The runtime entrypoint remains necessary for machine Bearer authentication,
authenticated staging, account-independent helper handling, OAuth access-log
suppression and Apps Script deadlines/completion evidence. Upstream legacy
HTTP still has no machine authentication. Recheck actual pinned image packages
on later upgrades instead of restoring old overlay versions or running `uv sync`
inside the built container.

```bash
bin/jarvis-google start
bin/jarvis-google check --live
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
# Sync local too when enabled, then reload the affected Jarvis registries.
```

Keep the previous image available until dependency, HTTP authentication/Host,
discovery and Google read checks pass. Use the existing stack overlay for Docker
Jarvis installations; rebuilding preserves OAuth storage. Validate writes with
owned disposable artifacts, inspect returned IDs, test saved follow-ups and Web
cards, and clean up only those test artifacts. Do not send mail or sharing
notifications as an incidental upgrade test.

### Earlier 2.3.0 migration notes

The [v2.3.0 release](https://github.com/taylorwilsdon/google_workspace_mcp/releases/tag/v2.3.0)
kept the same 111 tool names, OAuth scopes, transport and command-line options.
That upgrade pinned the multi-platform image digest and reviewed source
`395d881d246fc9ef3f8f8c299b08e7d9f1359b89`. It reused existing grants, the private
service token and the `data/` bind mount without changing Jarvis's Python
environments, databases or optional-service enablement.

Two output changes need attention:

- **Drive content is paged:** `get_drive_file_content` returns at most 40,000
  text characters by default. Continue with `offset`, keeping the same `file_id`;
  compare the returned file version and restart from zero if it changes. Jarvis
  preserves pagination metadata before shortening results. Follow its
  `pagination.next_offset`, which accounts for text actually included in the
  model's excerpt, rather than skipping ahead to `upstream_next_offset`.
  `full_content=true` opts out of the upstream page limit, but Jarvis still
  bounds its excerpts. Do not disable the service limit globally just to work
  around a continuation problem. Upstream caches text for ten minutes, bounded
  to 32 MiB by default; this is not a permanent local copy of Drive.
- **Sheets output is tab-separated:** `read_sheet_values` labels rows with
  their actual sheet row numbers. A read of `A20:C22` starts at row 20. If the
  server cannot resolve the start row, its legend explicitly reports numbering
  within the range; resolve the actual A1 range before using those labels to write.
  External scripts parsing the old Python-list-style `Row 1: [...]` output need
  updating. Jarvis preserves the returned text and does not parse that old format.

Useful additions through existing tools:

- **Paged Gmail bodies:** call `get_gmail_message_content` with `page_offset=0`,
  `format="full"`, `full=false`, and `body_format="text"` or `"html"`.
  `page_size` is 1–20,000 characters. Follow `pagination.next_offset` as
  `page_offset` and pass `body_sha256` as `expected_sha256`; keep `body_format`
  and `include_links` unchanged. Restart when the representation changes.
  `page_complete` describes the upstream response; it does not prove all of it
  reached the model when `content_delivered` is false. These pages exclude
  attachments and attached messages; use attachment tools or full exports for
  those. The email command inbox still uses its independent complete raw EML
  export and authentication checks.
- **Calendar read-back:** `get_events(detailed=true)` now includes custom
  reminders, non-default visibility and transparent events, making those
  `manage_event` settings inspectable. Default values may remain omitted.
- **Google Drawings downloads:** `get_drive_file_download_url` exports Drawings
  to PNG by default, or PDF (`pdf`), JPEG (`jpg`) or SVG (`svg`) using
  `export_format`. Use `stash=true`
  for a local artifact through the existing download bridge.

Descriptions are injected only when the corresponding tools are available.
The new arguments arrive through upstream schema discovery; this does not add
new tools, consent requirements or approval screens. Returned documents and
messages remain untrusted content, including their excerpts and links.

That base included Authlib 1.9.1 and dnspython 2.9.0 on Python 3.13.
At that upgrade, the hash-locked security overlay retained FastMCP 4.1.4 and
OpenTelemetry 1.45.1 and upgraded the base's pypdf 6.21.3 to
[6.21.4](https://github.com/py-pdf/pypdf/releases/tag/6.21.4) for xref EOF loops,
page-tree expansion and dictionary-cloning cycles. The new page-dictionary
budget can reject unusually expansive PDFs; failed extraction retains the
existing download guidance. The current 2.4.0 base includes these fixes directly,
so the overlay has been removed. Do not run upstream `uv sync` inside the built
container.

```bash
bin/jarvis-google start
bin/jarvis-google check --live
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
# Sync local too when enabled, then reload the affected Jarvis registries.
```

Docker Jarvis installations use their existing stack and Google overlay instead
of the standalone helper. Keep the previous image available until live health,
authorized discovery and read checks pass; rebuilding preserves OAuth storage.

### Earlier 2.2.1 migration notes

The [v2.2.1 release](https://github.com/taylorwilsdon/google_workspace_mcp/releases/tag/v2.2.1)
keeps the existing 111 tool names, transport, OAuth scopes and command-line
options. Reuse the current grants, private service token and `data/` bind mount.
That release used source `0801afb3e58f51754f5a40161c07675f50565448` and Python
3.13, without changing Jarvis's Python environments. It still needed a security
overlay; the current pin and its replacement of that overlay are documented in
the 2.4.0 section above. Do not run upstream `uv sync` inside the built container.

Useful changes through existing tools:

- **Email links:** use `include_links=true` with `body_format="text"` when
  reading an email for its links. This applies to `get_gmail_message_content`,
  `get_gmail_messages_content_batch`, `get_gmail_thread_content`, and
  `get_gmail_threads_content_batch`. It adds a LINKS section for HTTP(S) URLs
  in the HTML body that plain text omits; it defaults to false and has no
  effect for HTML/raw or metadata-only reads. These links remain untrusted
  message content, not verified destinations or commands.
- **Body-only reads:** only `get_gmail_message_content` accepts
  `include_headers=false`. It omits the Subject/From/To/Date summary, so retain
  the original Message ID from search/request context for follow-ups. It
  requires `format="full"`; inline raw MIME cannot hide headers, so use text
  or export raw MIME with `full=true`. Headerless full exports use the Message
  ID as filename. This is a presentation option, not a way to remove raw MIME
  headers or authenticate a sender. Thread and batch tools do not accept it.
- **Read reliability:** non-UTF-8 message bodies use their declared charset,
  and text/HTML parts stored behind Gmail attachment IDs are fetched instead
  of appearing empty. Complete EML exports and the command inbox retain their
  existing independent byte/authentication checks. Signature spacing is fixed.
- **This and following events:** `manage_event(action="update",
  this_and_following=true, event_id=...)` needs a recurring instance ID from
  `get_events`. It ends the original series before that occurrence and creates
  a new series for it and later occurrences, retaining earlier ones. Use a
  series ID for a whole-series edit; changing that series' start or recurrence
  can drop past occurrences. Fixed-COUNT series require an explicit recurrence
  for the new series, and RDATE series cannot be split. Do not substitute a
  whole-series rewrite for an unsupported split. Inspect the resulting IDs
  before retrying an uncertain request; restoring the original recurrence on
  insertion failure is best effort, not a transaction across both writes.
- **Comment corrections:** `manage_document_comment`,
  `manage_spreadsheet_comment`, and `manage_presentation_comment` add
  `action="update"` with `comment_id` and `comment_content`, or
  `action="delete"` with `comment_id`. List the file's comments first to obtain
  the real ID. Update/delete apply to top-level comments authored by the
  dedicated account, not another user's comments or reply IDs. A Sheets `cell`
  target is for create only. Deleting removes a comment; resolving retains it.
- **Docs chips:** `batch_update_doc` accepts an operation such as
  `{"type":"insert_person","email":"person@example.com","end_of_segment":true}`.
  Use the intended `tab_id`, or inspect the real index before indexed insertion.
  A person chip does not grant document sharing. Existing dropdown chips now
  render their selected label in Markdown/plain-text reads; that read fix does
  not add dropdown creation or expose every option. Markdown imports use
  paragraph spacing instead of extra empty paragraphs between blocks.

The comment tools now advertise `destructiveHint=true` because deletion is
available. Jarvis still classifies those side effects and preserves the existing
dedicated-account `auto_approve=true` policy. This does not add confirmation
screens, scopes, services or database migrations. The new parameters arrive via
normal upstream schema discovery; local description prefixes guide their use.

```bash
bin/jarvis-google start
bin/jarvis-google check --live
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
# Reload Jarvis registries to use the refreshed schemas and descriptions.
```

Sync every enabled mode separately. Docker Jarvis installations use their
existing stack and Google overlay instead of the standalone helper. No new
consent is required just for the version upgrade; normal revoked/expired-grant
recovery still applies.

### Earlier 2.2.0 migration notes

The [v2.2.0 release](https://github.com/taylorwilsdon/google_workspace_mcp/releases/tag/v2.2.0)
retains this setup's transport, OAuth scopes, CLI flags and 111-tool count.
Existing OAuth grants and the private service token can be reused. Rebuilding
keeps the existing `data/` bind mount. Its reviewed source was
`b5cf07e6078ae10a596710d77569e9430e01ebd4`; the current Dockerfile pin is listed
in the 2.4.0 section above.
Upstream updates `certifi` to 2026.10.19 but still includes packages with newer
published advisories. At that upgrade, a container-only overlay pinned artifact
hashes for `pypdf` 6.21.2, FastMCP 4.1.2 and OpenTelemetry 1.45.1 plus matching
packages, without changing Jarvis's Python environments. The current 2.4.0 base
includes the later patched versions directly; the obsolete overlay is removed.
Do not re-run upstream `uv sync` inside the built container.

The breaking tool rename is `get_page_thumbnail` → `render_page_to_image`.
Replace `thumbnail_size` with `size` and remove `inline`; the server now attempts
to attach the rendered image on every call. Existing workflows using the old
name must be updated. Re-sync Tool RAG and reload registries so the removed tool
is no longer offered. This checkout has no workflow using the removed name.

Useful capabilities through the existing tools:

- **Slide and Drive images:** `render_page_to_image(presentation_id=...,
  page_object_id=..., size="MEDIUM")` returns an image of a slide or notes page.
  `MEDIUM` is 800 pixels wide; use `LARGE` for small labels. `get_drive_file_content`
  returns PNG/JPEG/GIF/WebP images and raster images embedded in SVGs. Jarvis saves
  returned image blocks to Stash, then the existing `analyze_image` tool can
  inspect their references. A successful read alone does not establish that the
  model has visually inspected an image. See the delivery status for unavailable
  or partially saved images. The bridge accepts at most four images, 8 MiB per
  image and 16 MiB total, with a 40-million-pixel limit per image. It validates
  inline bytes and never fetches temporary image URLs. BMP/TIFF and compressed
  SVG inputs do not gain native image-block support.
- **Docs sections:** `modify_doc_text(heading="Status", text=...)` replaces the
  section under a unique heading, preserving the heading. Use
  `end_of_segment=true` to append; omit `text` to apply formatting only. Narrow
  duplicate headings with `heading_level`; multi-tab documents need `tab_id`.
  Inspect the document and keep a recovery copy before replacing important
  content. `get_doc_as_markdown(include_colors=true)` reads explicit foreground
  colors as `[color: #rrggbb]` annotations; theme colors are not included.
- **Contacts changes:** start with `list_contacts(request_sync_token=true)`,
  follow every page, then use the final `next_sync_token` as `sync_token` on
  later reads. Deleted contacts are explicitly marked. Tokens expire after
  seven days; an expired token needs a fresh full sync. This exposes the upstream
  incremental API, without adding a background contact cache or mirroring Google
  Contacts into local email aliases.
- **Gmail replies:** sends can inherit the thread subject when it is omitted.
  Sends and drafts support `reply_all=true` with `thread_id`; explicit `to`/`cc`
  override derived recipients. This can include other thread participants, so
  use it when the user requests reply-all. Drafting remains available without
  sending mail.
- **Calendar colors:** `manage_event` accepts color names or IDs 1–11 in
  `color_id`. Out-of-Office and Focus Time writes now require timezone-aware
  boundaries. These special event types remain subject to Google account support.

Apps Script deployment/version listings now read every page. The release also
fixes Drive query escaping, Sheets row/column resizing, contact-address clearing
with an empty value, and several validation errors. Chat changes do not enable
Chat for this dedicated consumer account.

```bash
bin/jarvis-google start
bin/jarvis-google check --live
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
# Restart Jarvis processes to load updated tool schemas and descriptions.
```

Sync each enabled Jarvis mode separately. For a Docker Jarvis deployment, use
the existing stack and Google overlay command instead of the standalone helper.
Local discovery guidance supplements the refreshed upstream schemas; existing
router bounds, exclusions, profiles and autonomous approval settings still apply.

Gmail sends and forwards retain the single-send behavior from v2.1.2. A timeout, connection
drop or server error can mean delivery already happened: inspect Sent before
trying again. Jarvis's HTTP transport also avoids replaying ambiguous failures.
The corrected destructive annotation on `send_gmail_message` does not change
this setup's configured autonomous approval policy.

Ordinary Google tools retain the upstream 60-second Google API socket timeout
and Jarvis's 90-second MCP budget, with a five-second executor cleanup margin.
In `config/mcp-servers.json`, `tool_call_timeout_seconds` supplies that default;
`tool_call_timeout_overrides` gives only `run_script_function` a **390-second**
foreground budget. Its executor guard is 395 seconds. This applies to CLI and
ordinary foreground Web calls in either configured mode. Explicit scheduled-task
or workflow deadlines still apply. Other MCP servers keep their existing limits.

The opt-in background binding for `run_script_function` uses an isolated MCP
client and carries its remaining job budget in MCP request metadata. The service
wrapper applies that deadline to this call's Google HTTP requests using separate
transports. Foreground `run_script_function` uses the same isolated transport
with a 390-second deadline and no background job metadata; other foreground
Google tools and the shared connection pool retain their existing limits.
Google still limits script execution to six minutes. Queue time counts toward
the existing 420-second background job deadline.

Credential refresh is part of that same deadline: scoped Apps Script OAuth requests use
one owned, socket-bounded transport and disable token-endpoint retries. Cancelling
or reaching the deadline interrupts its active socket, including response headers
and slowly arriving bodies; it cannot start another refresh afterward. Other Google
tools retain their existing authentication timeout and retry behavior. The Google image
copies the shared HTTP observer from `lib/http_observation.py`; its Dockerfile-specific
allowlist exposes only the Dockerfile, entrypoint and that helper.

The wrapper records actual `scripts.run` responses in job-bound completion
metadata. A script exception is a settled failure even though upstream renders
it as ordinary text. A socket timeout, lost response, or observer cancellation
does not prove that a script stopped and remains uncertain. Background execution
disables Google request and credential-refresh retries; Jarvis never replays an
uncertain script invocation. This requires rebuilding/recreating the optional
Google Workspace service to load the updated entrypoint. An older service
without completion metadata cannot prove a background execution settled.

Attachment storage stays local; GCS storage, Valkey and OpenTelemetry
identity attribution are optional and are not enabled by this Compose setup.
The existing Stash staging bridge continues to supply container-local paths;
the stricter refusal of local files in stateless/disabled-local-file modes does
not require changing this stateful service.
The new OAuth proxy `WORKSPACE_MCP_OAUTH_PROXY_REQUIRE_CONSENT=remember`
option applies to OAuth 2.1 proxy deployments. This setup uses legacy HTTP
with `MCP_ENABLE_OAUTH21=false` and its own Bearer wrapper, so that option does
not replace or simplify the documented Google browser consent flow.

## Stop, disable, troubleshoot

```bash
bin/jarvis-google --mode cloud disable
# Sync cloud Tool RAG and restart Jarvis to remove the tools from active use.
bin/jarvis-google stop
```

Stopping retains grants. Restarting with `start` reuses them. Disabling a mode
does not stop the shared service or disable another mode. Do not delete its
data to troubleshoot token expiry; first check consent status and client identity.

- **No OAuth client:** passwords/app passwords only support different protocols.
  Create the Web OAuth client above; `auth` cannot work without it.
- **Seven-day reconnects:** switch the consent app out of Testing, then run `auth`
  again for a newly issued production grant.
- **Redirect mismatch / callback unreachable:** use the exact localhost URI,
  keep the SSH tunnel open, and make sure the same port is free on the desktop.
- **API denied or disabled:** enable the corresponding API in the OAuth client's
  project, grant all requested scopes, and re-run `check --live`. Enable Apps
  Script user API access separately. No account password fixes a scope failure.
  Google Tasks uses `tasks.googleapis.com`, which is different from Cloud Tasks
  (`cloudtasks.googleapis.com`). Google API enablement can take time to propagate.
- **401:** use the matching private service token; `prepare` preserves an existing
  token. Never print `docker compose config` or raw container environment when
  investigating credentials.
- **Missing tools:** check the selected mode's enable flag, account and service
  token, live service health, Tool RAG sync, active tool profile, and process restart.
- **Update upstream:** review its auth/tool changes, pin a new image digest,
  rebuild, check discovery and OAuth refresh, then verify representative reads,
  owned test-artifact writes, follow-ups and Web previews before switching.

The repository [setup skill](SKILL.md) gives an AI the operational sequence.

`bin/jarvis-google --mode local prepare` requires
that mode's account and OAuth client ID/secret, or an explicitly provided client
JSON. It never fills missing OAuth fields from the existing service `.env`.
An already configured service can be enabled for another matching-account mode
through `enable` without changing the service's OAuth client configuration.

`bin/jarvis-google check` includes a live HTTP smoke: unauthenticated `/mcp` must
return 401, `/health` must return 200, an unlisted Host with matching Origin
must return 403, and authorized discovery must succeed.
The downloaded `client_secret*.json` filenames are ignored by Git and excluded
from application build archives. The entire standalone `google-workspace/`
folder is excluded from the Jarvis application image; its own image uses the
allowlist containing only the Dockerfile, entrypoint and public shared HTTP observer.

### Email inbox attachments

The optional [email command inbox](../docs/tools/email-inbox-tool/README.md)
uses full raw EML exports to authenticate complete messages, then the existing
Gmail attachment download/Stash bridge for named files. No upstream container
update is required. If you set `WORKSPACE_MCP_MAX_FILE_BYTES`, allow enough for
the encoded complete message: the inbox caps raw downloads at 100 MiB and decoded
attachments at 50 MiB in aggregate. Plain display previews are not used to parse
large MIME messages. Preview does not save files; the complete EML is not copied
to Jarvis Stash. Enable the Gmail attachment tool in the receiving mode/profile;
its use by the dispatcher does not require granting it to the email model.
