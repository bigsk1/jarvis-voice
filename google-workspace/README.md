# Optional Google Workspace service

Jarvis can use a dedicated **consumer Gmail account** through
[Google Workspace MCP](https://github.com/taylorwilsdon/google_workspace_mcp).
The pinned v2.0.1 container exposes 111 tools in its complete tier for Gmail,
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

Tool descriptions prefer `send_email` for ordinary outgoing email when that
tool is available. Explicit Gmail/Google Workspace delivery and Gmail replies
or forwards use `send_gmail_message`. This is description guidance under the
existing profile and block-list checks; it does not enable either tool.

## Access and results

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
The Drive search/download and Docs PDF export tools have these supplements.

`prerequisite_tools` in the same metadata declares companion schemas needed to
resolve required inputs. The Drive download tool includes Drive search so a
request naming a file can obtain its ID. Existing router bounds, active-profile
filtering and exclusions still apply; this does not force a search call when a
valid file ID is already available.

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
Account identity is supplied automatically. Routine Google searches, reads,
edits and sharing do not create Stash copies.

The service keeps its own temporary attachment cache. Only an explicit Stash
transfer adds a persistent copy, using the canonical helper and the active
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
return 401, `/health` must return 200, and authorized discovery must succeed.
The downloaded `client_secret*.json` filenames are ignored by Git and excluded
from application build archives. The entire standalone `google-workspace/`
folder is excluded from the Jarvis application image; its own image uses the
existing allowlist containing only Dockerfile and entrypoint.py.
