# Optional Google Workspace service

Jarvis can use a dedicated **consumer Gmail account** through
[Google Workspace MCP](https://github.com/taylorwilsdon/google_workspace_mcp).
The pinned v2.2.0 container exposes 111 tools in its complete tier for Gmail,
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
Gmail, Drive, Docs and Sheets tools have these supplements.

`prerequisite_tools` in the same metadata declares companion schemas needed to
resolve required inputs. The Drive download tool includes Drive search so a
request naming a file can obtain its ID. Existing router bounds, active-profile
filtering and exclusions still apply; this does not force a search call when a
valid file ID is already available.

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

## Upgrading to 2.2.0

The [v2.2.0 release](https://github.com/taylorwilsdon/google_workspace_mcp/releases/tag/v2.2.0)
retains this setup's transport, OAuth scopes, CLI flags and 111-tool count.
Existing OAuth grants and the private service token can be reused. Rebuilding
keeps the existing `data/` bind mount. The Dockerfile pins reviewed source
`b5cf07e6078ae10a596710d77569e9430e01ebd4` and its immutable image digest.
Upstream updates `certifi` to 2026.10.19 but still includes packages with newer
published advisories. The container-only `security-requirements.txt` overlay
pins artifact hashes for `pypdf` 6.21.2, FastMCP 4.1.2 and OpenTelemetry 1.45.1,
plus their required matching packages. The Docker build installs those exact
replacements without resolving unrelated dependencies, then checks installed
requirements for compatibility. These changes remain isolated from Jarvis's
own Python environments; do not re-run upstream `uv sync` inside the built
container, which would restore its older lockfile versions.

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

The upstream Google API socket timeout remains 60 seconds. Jarvis configures a
90-second per-call Google MCP budget through
`tool_call_timeout_seconds` in `config/mcp-servers.json`; its executor allows
95 seconds, including the cleanup margin. Other MCP servers keep their existing
timeouts. Tools making several Google requests can still exceed the overall
budget; a timeout is not proof a write failed.

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
allowlist containing only Dockerfile, entrypoint.py and the public
security-requirements.txt overlay.

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
