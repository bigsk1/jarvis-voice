# Jarvis email commands

This optional channel lets approved senders ask Jarvis questions by email and
receive a reply in the same Gmail thread. It uses the existing Google Workspace
service, normal Tool RAG/orchestration, and a regular scheduled workflow. There
is no new daemon, external service, Python dependency, or scheduler task type.

## Sequence and data-flow diagrams

[![Jarvis email inbox data flow](../../diagrams/jarvis-email-inbox-dataflow.svg)](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-email-inbox-dataflow.html)

- [Request sequence](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-email-inbox-sequence.html): polling,
  admission, restricted orchestration, durable state and threaded reply.
- [Data flow](https://bigsk1.com/jarvis-voice/docs/diagrams/jarvis-email-inbox-dataflow.html): mailbox data,
  independent scan cursors, private ledger, model context and failure paths.

The links open the published diagrams. For a local checkout, open the matching
HTML files under `docs/diagrams/` directly. Both include dark/light themes
and PNG/JPEG/WebP/SVG export controls. Vector copies are available as
[sequence SVG](../../diagrams/jarvis-email-inbox-sequence.svg) and
[data-flow SVG](../../diagrams/jarvis-email-inbox-dataflow.svg). The neighboring
`.sequence.json` and `.dataflow.json` files are the editable Archify sources.

## Prerequisites and enablement

1. Set up the [dedicated Google Workspace account](../../../google-workspace/README.md).
  Enable its MCP integration in the mode you will schedule. Gmail search,
  message reads and sending must remain enabled in that mode's tool profile.
   `email_inbox` uses the shared availability mechanism: it is unavailable if
   `GOOGLE_WORKSPACE_MCP_ENABLED` is off or any of those three Gmail tools is
   undiscovered, profile-disabled or blocked. Normal sync disables its old Tool
   RAG row too. Runtime checks remain as a backstop for stale/in-flight callers.
2. Copy `config/contacts.json.example` to `config/contacts.json` if the private
   contacts file does not exist. Preserve your existing `contacts` map; add this
   **separate top-level** property:

   ```json
   "jarvis_email": {
     "enabled": true,
     "mode": "cloud",
     "approved_senders": ["boss", "another-address@example.com"],
     "max_messages_per_poll": 1,
     "lookback_days": 1
   }
   ```

   Each entry is either a bare email address or an existing contact key/display
   name. Ordinary contacts are **not automatically authorized**. Adding/removing
   senders takes effect on the next poll and is checked again before execution
   and delivery. Outgoing “email Boss” lookup continues using `contacts`.
  Only one configured mode processes this mailbox. The default is disabled;
  a missing/malformed file or an empty approved list never admits requests.
3. Check setup and inspect candidates without executing requests or replying:

   ```bash
   bin/jarvis-email --mode cloud status
   bin/jarvis-email --mode cloud preview
   ```

   `status` reads local policy and ledger state without MCP discovery or a
   mailbox health check, so it remains usable during a Workspace outage.
   It reports the global tool list and effective per-contact sender tool lists
   separately, so you can inspect the permissions before polling.
   Commands print JSON to stdout and diagnostics to stderr. The native launcher
   uses `~/jarvis-venv` or `JARVIS_VENV`, matching the production Jarvis CLI.
4. Run one actual poll when ready:

   ```bash
   bin/jarvis-email --mode cloud poll
   ```

   This can execute approved requests and send real replies. Each poll reads
   a recent page of up to 25 candidates, plus up to one page each from the
   initial backlog and the arrivals scan. Those scans have independent cursors
   and frozen time windows. The arrivals watermark advances only after its
   entire window is recorded, so bursts larger than 25 messages cannot fall
   between scans. The recent page allows prompt handling of new mail. It also retries up
   to 25 incomplete reads recorded by earlier polls and handles
   up to `max_messages_per_poll` requests (1 by default, maximum 5). Unprocessed
   admitted requests remain queued locally. The search includes read messages;
   opening mail yourself does not prevent processing. It does not mark mail read.
   Windows use second-based `after:`/`before:` bounds as documented in
   [Gmail API filtering](https://developers.google.com/workspace/gmail/api/guides/filtering).
5. Create the normal repeating schedule:

   ```bash
   bin/jarvis-email --mode cloud schedule --every 30
   ```

   This creates an enabled `workflow` task for `jarvis_email_inbox` with no
   overlap, no automatic task retry, and a 600-second worker deadline. Repeating
   this setup command returns the existing task rather than adding another one;
   it does not re-enable a paused task or change its interval. A cancelled task
   is replaced. Manage the task
   in Jarvis Memory → Scheduled Tasks. The API/services scheduler must be running.
   Restart Jarvis after installing the new code. For natural-language discovery
   of `email_inbox`, sync Tool RAG using the production environment as usual.

The explicit `/email_inbox` workflow also works through Jarvis Web or
`bin/jarvis-cli --mode cloud --json /email_inbox`. Its one step calls the
in-process `email_inbox` tool, reusing the live registry. This trusted app entry
point runs inside the scheduled worker; it does not launch a local tool child
with inherited provider keys. It is not eligible for Web background admission.

For Docker, the existing `./config:/app/config:ro` and `./data:/app/data` mounts
provide the private contacts and ledger. Use the existing Google Compose overlay
and its internal MCP URL; rebuild the Jarvis image for new code. The Google
container itself needs no update for this feature. Windows/macOS browsers can
send requests to the same mailbox; the client device needs no Jarvis install.

## Send a request

Send a plain-text-capable email to the dedicated Jarvis Gmail address:

```text
Subject: Jarvis: current stock price

Hey Jarvis, get the current stock price for Microsoft and explain its daily change.
```

Every admitted email from an approved, authenticated sender uses its latest
plain-text body as the request. No greeting, subject prefix or previous thread
history is required. The dedicated mailbox and approved-sender configuration
express the operator's intent to accept questions and tasks from those senders.
The subject is retained for replying in the original thread, not used to choose
tools or override the body. That sender's last three completed exchanges supply
conversational history. Verified attachment names, MIME types, sizes and Stash
references are also recovered from completed requests in the same sender/thread,
even when the original request is older than those three exchanges. The newest
64 distinct file references are included, with an explicit notice if more exist.
Other participants' messages/files do not enter the execution conversation.
Common quoted/forwarded
sections and signatures are removed from the latest plain-text request.

The dispatcher fixes the recipient to the approved From address. It ignores
Reply-To redirection, CC/BCC and requests for reply-all. It passes the Gmail
thread ID and original RFC Message-ID for a proper reply. No model chooses
recipients or invokes the sending tool as part of an email request.
Replies use the full model answer when available, with supported voice cues
removed for readable email. A short spoken summary is only the fallback.

## Attachments: PDF, images and other files

Attachment handling defaults to enabled **inside an opted-in email channel**.
It does not enable the channel or grant additional model tools. Optional
`jarvis_email` settings in `config/contacts.json` are:

```json
"attachments_enabled": true,
"max_attachment_bytes": 52428800,
"max_attachments": 500
```

The default byte limit is 50 MiB per file **and in total per message**; it can
be lowered but not raised above the existing Workspace-to-Stash bridge limit.
The count limit is 500 and can also be lowered. Gmail's personal-account sending
limit is [25 MB across attachments](https://support.google.com/mail/answer/6584?hl=en);
larger files normally become Drive links. Workspace limits depend on the
account/administrator. The complete MIME transport has a separate 100 MiB bound
because Base64 encoding increases message size. A Drive link is not an attachment
and is not automatically downloaded by the inbox.

Enable `mcp_google_workspace_get_gmail_attachment_content` in the receiving
mode/profile for attached files. This tool is used by the trusted dispatcher
only for the authenticated message, before the model runs. It does **not** need
to be added to the email model's `allowed_tools`. Plain-text requests can still
work if attachment downloading is unavailable. To disable new attachment
ingestion, set `attachments_enabled` to false; requests receive context explaining
that newly attached files are unavailable. Existing saved file references still
follow normal thread context, tool permissions and Stash retention.

`preview` authenticates the message and shows filenames, MIME types and sizes
without saving attachments or executing requests. During a real poll, the
inbox downloads named attachments through the existing authenticated Workspace
bridge, checks their size and SHA-256 against the complete authenticated MIME
message, and saves them into an ordinary project Stash space on the **Jarvis
host**. The model receives exact `stash://` references, names, types and sizes,
not binary/Base64 data. The temporary complete EML is not saved to Jarvis Stash
or the ledger. Workspace retains its normal temporary export cache.

### Inline files and attached emails

Thunderbird/Gmail can display a file inline while still transmitting it as a
MIME file part. Named inline files use the same verified Stash path as ordinary
attachments, with `inline: true` in the model context. They count toward the
same size/count limits. Jarvis does not discard inline files or assume every
inline image is a signature: it may be the very image you want edited/printed.

The model uses the request, filenames, MIME types and inline flags to select
the relevant file. A receipt PDF accompanied by an inline logo does not
necessarily require a clarification. Several equally plausible files may.
No parser forces that selection or changes the tools available to the model.

This path requires a filename and a downloadable Gmail attachment ID. Unnamed
CID images and HTML remote-image links are not automatically ingested. The
request must still have a plain-text alternative; HTML-only email is not admitted.
Sending a file as a normal attachment is the clearest option if your mail
client omits a name or plain-text alternative when embedding it.

Named attached email files (`message/rfc822`, commonly `.eml`) are preserved as
opaque files. Their hash is calculated from the original MIME payload, with
transfer encoding decoded and MIME boundary framing removed, rather than from
re-serialized headers/text. The attached email's own body and nested files are
not promoted into commands or separately ingested. Gmail downloads must still
match those original file bytes before the request runs.

The model still chooses among your permitted, enabled tools through normal
Tool RAG. No tool hint or attachment-specific routing is forced. Attached files
are untrusted data; their contents do not grant permission to run other actions.
Quoted mail and the subject do not replace the latest body as the model's request.

Examples, assuming the named tools are enabled and in your email allowlist:

- **“Hey Jarvis, print this receipt.”** With an attached PDF, Jarvis is given its
  file reference and told that “this” means the attachment. `printer` accepts it
  as `file_path`; `pdf_read`/OCR is unnecessary to print the original. With several
  plausible targets, Jarvis should ask which file. Explicit requests to print the
  body or a summary remain possible. Tool selection and intent are model decisions.
- **“Hey Jarvis, convert the attached PDF to Markdown using Docling.”** Enable
  `docling_convert`; the file reference is already available. Parsing is not
  automatically invoked just because a PDF is attached.
- **“Hey Jarvis, save these attachments and tell me their filenames.”** Files
  are already in Stash before the model responds; it can report their references.
- **“Hey Jarvis, add a caption to the attached image.”** Enable `craft_image`
  and its gateway. The same Stash references work as ordinary tool inputs.

### Reusing attachments in a follow-up

Reply in the same thread, for example **“Yes, extract the text from that PDF.”**
The model receives the original saved filename/reference alongside recent
conversation history. It can choose a permitted tool and use that `stash://`
input without a new upload, Gmail download, or repeated execution of the old
request. This also works for already-completed attachment requests: the verified
receipts were saved in their envelopes, so no migration or reattachment is needed.

This preserves references to inbound attachments; it does not grant new tools or
extend file retention. If Stash has expired/deleted a file, the reference no longer
makes its contents available and the sender may need to attach it again. Generated
outputs are not separately indexed by this attachment-context mechanism; their
references may appear in the ordinary recent answers. Replies remain text-only.

A failed transfer is retried across polls, up to three failed attachment
preparations. Files already verified/saved are reused when preparation resumes.
No requested business action runs until all required files are prepared.
A limit/integrity rejection, or exhausted retries, generates a sender-only
failure reply saying that no requested actions ran. `status` lists pending
`attachment_retries`. Saved files use ordinary Stash project retention (normally
120 days); the inbox ledger has its own independent lifetime. Removing a Stash
file does not delete its recorded receipt. Filename collisions use Stash's
versioning and safe filename rules.

## Permitted actions and authentication

The default client-tool allowlist is `get_time`, `stash`, `stock_price`, `crypto_price`,
`weather`, `calculator`, `mcp_brave_search_brave_web_search`, `brave_llm_context`,
`tavily_search` and `tavily_extract`. `tool_search` is included for discovery, with
the same allowlist applied. Normal mode/profile/credential checks still apply;
tools are not force-enabled or preferred in Tool RAG. Provider-hosted tools
and explicit workflows are disabled for this restricted request surface.
Other Web, voice, CLI and scheduled queries retain their normal behavior.
Automatic operator memory, shared conversation context and Intelligence insights
are not injected into email requests. Their conversations/experiences are not
written to the operator's shared Memory/Intelligence stores or sampled feedback.
Only this sender's ledger history supplies conversation context. Tool RAG ranking
and normal private diagnostic logs still apply.

To change the list, add `allowed_tools` inside `jarvis_email` with exact tool
names. This is an operator-controlled execution permission, not a hint. Adding
a tool that writes files, executes code or calls another service broadens what
email commands can do. The defaults include lookups and Stash operations;
`stash` also permits artifact reads/writes and its explicit `remember` action.
The setting rejects `send_email`, Gmail send/draft tools, `email_inbox`, and
`workflow`. Granting other service or wrapper tools can also indirectly grant
additional actions; keep the list limited to tools you intend to authorize.
Omitting `allowed_tools` uses the defaults. An explicit `[]` permits only
discovery; it does not mean all tools. `crawl_url` is excluded from the defaults
because its general URL fetcher can reach private network addresses. Adding it,
or memory tools, explicitly grants that broader access.

### Per-contact inbound tools

An approved sender can have a separate tool policy through
`allowed_tools_limited` on their entry inside `contacts`. For example, merge
this entry into your existing contacts map:

```json
"contacts": {
  "restricted_contact": {
    "name": "Restricted Contact",
    "email": "robot@example.com",
    "allowed_tools_limited": ["printer"]
  }
}
```

The field accepts one exact tool-name string, such as `"printer"`, or a list of
exact tool names. The key is **`allowed_tools_limited`**; the common typo
`allowed_tools_limted` is rejected with a corrective error.

| Contact field | Effective tools for that approved sender |
|---------------|------------------------------------------|
| Omitted | The existing global `jarvis_email.allowed_tools`, or the built-in defaults if the global list is omitted, plus `tool_search`. |
| `[]` | The built-in email defaults listed above, plus `tool_search`. |
| `"printer"` or `["printer"]` | The built-in email defaults, plus `printer` and `tool_search`. |

A present field replaces the global tool-list selection for this sender. Its
extras are added to the built-in defaults; they are **not intersected with**
`jarvis_email.allowed_tools`, and tools granted only by that global list are
not inherited. In particular, an empty contact list keeps the baseline tools,
while an empty global list permits only discovery. This is a fixed baseline,
not a read-only policy: `stash` includes artifact writes and its explicit
`remember` action. Normal mode/profile/credential checks still apply.

Approval remains separate. Add the contact key, its display name, or its bare
address to `jarvis_email.approved_senders` only when you intend to authorize
inbound commands. The authenticated canonical sender address selects the contact
policy, so approving `robot@example.com` directly does not bypass the settings on
`restricted_contact`. Adding the contact or its tool field alone grants no
approval and does not change outgoing email lookup or delivery.

Invalid field values and forbidden tools fail closed instead of falling back to
the global or full tool set. Duplicate contacts for the same canonical email
share its explicit limit; an alias with the field omitted does not bypass it.
Multiple explicit lists must grant the same effective tools; conflicting lists
fail closed rather than merging permissions. The dispatcher-only exclusions
above still apply. To authorize
another tool, edit the operator-owned contact policy; email text cannot expand it.

Before admission, code checks the exact approved sender and the first receiving
Gmail `Authentication-Results` header: `mx.google.com`, passing DKIM aligned to
the From domain, and passing DMARC for that domain. Missing/failing evidence
rejects the request. It never accepts a later passing header after a failure.
Authentication verifies the sending domain, not the human or their intent;
account compromise remains possible. Spam/trash/sent mail is excluded from the
search. Automated/list mail, self-sends, ambiguous From/Message-ID headers,
HTML-only mail, malformed MIME and requests over 4,000 characters are rejected. Incomplete MIME,
unrecognized read receipts and transport errors are kept for read retry; they
never authorize execution. The inbox reads a complete authenticated temporary
EML export, bounded to 100 MiB, rather than the truncated display preview.
The Workspace service may impose a smaller file-export limit.
Each message gets at most three failed read attempts across polls; after that
it becomes `read_failed` and automatic reads stop. No incomplete request executes.
Attachments and arbitrary thread text are not executed. Forwarding and unusual
quoting formats may require you to send a clean new request.

## Processing state and recovery

Private state lives in `data/email-inbox/<account-hash>/ledger.sqlite3` on the
Jarvis host, with an OS file lock preventing overlapping polls. It is ignored
by Git and excluded from image builds. Persist this directory across restarts;
removing the ledger can cause recent requests to be admitted again. A new
table is created only in this independent SQLite file, not in Memory's schema.
Existing ledgers gain read and attachment attempt counters automatically; saved answers and
delivery state are preserved. Earlier scan checkpoints are upgraded on the next
poll, retaining their frozen cutoff for arrivals coverage. Scan checkpoints are
committed together after candidate IDs have been saved.
Accepted latest text, attachment metadata/references and answers are stored there; normal orchestration/tool
logs may also retain the authorized request and tool results. Treat backups
as private. The ledger has no automatic retention cleanup in this first version.
Switching the configured mode retains this mailbox ledger and its thread
history, so switching cannot execute a completed email a second time.

- `pending`: authenticated request recorded before execution.
- `read_retry`: only message/thread IDs saved; a complete authenticated envelope
  has not been obtained, and no request can execute yet.
- `read_failed`: three failed reads; automatic retry stopped. `status` lists the
  latest ten IDs, reasons and attempt counts. Send a new clean request after
  resolving the content/service issue; deleting the ledger is not a retry method.
- `running`: Jarvis is executing it.
- `reply_ready`: answer saved; sending has not started.
- `sending`: delivery attempted; its outcome must be recorded.
- `completed`: Gmail returned a send receipt; `request_ok` separately reports
  whether Jarvis completed the requested operation.
- `ignored`: rejected mail or sender approval removed.
- `needs_attention`: delivery outcome unconfirmed; no automatic resend.

A crash or scheduler timeout during execution does not rerun the request. At
the next poll, Jarvis prepares an interruption notice for the still-approved
sender. A saved answer can be delivered without repeating its tools. If a send
was interrupted or returned no clear receipt, check Gmail Sent before manually
retrying: the remote send might already have succeeded. A new follow-up email
is a new request; completed message IDs are never executed again automatically.
Mailbox discovery failures do not prevent delivery of already saved answers.
A missing/unreadable or invalid JSON contacts file stops processing while
preserving pending requests and saved replies. Restoring valid policy resumes
them; explicitly disabling the channel or removing approval still prevents
execution/delivery. No automatic resend is added for uncertain delivery.
Individual read failures are warnings in `read_errors` and do not fail the
scheduled workflow. A mailbox discovery/scan failure or a newly unconfirmed
send still returns `ok: false`, with any successful deliveries also reported.

## Troubleshooting

- **Disabled:** verify `enabled: true`, the selected mode and approved entries
  in the private contacts file. Contacts alone never opt in.
- **No candidates:** confirm the recipient is Jarvis's configured account,
  your exact sender is approved, the message is in Inbox within the lookback,
  and it includes a non-empty plain-text request. `preview` lists rejection reasons.
- **Authentication rejection:** inspect Gmail's Show original authentication
  results. Send directly from the approved account; forwarded/list mail can
  lack the required aligned evidence. Do not bypass authentication with a prompt.
- **Tool unavailable:** check the email allowlist and the mode's enabled tool
  profile/credentials. Ask a clean lookup request; email cannot implicitly gain
  the host's full tool set.
- **No reply:** inspect `status`, the scheduled task's run history, and Gmail
  Sent. `needs_attention` prevents automatic duplicate sends. A stopped scheduler
  cannot check mail, and polling latency is up to the configured interval.
- **Bad page token/read failure:** a failed paginated search clears only its
  cursor and restarts the same frozen window; it does not advance that scan's
  watermark. Recorded message IDs still prevent replay. Read failures are retried
  from the ledger independently of cursors, until three failures. Inspect
  `read_errors`, `discovery_error`, `read_retry` counts and the `read_failed` list.
  Fix service/OAuth health or send a shorter new request for persistent truncation.
  The lookback bounds initial coverage and coverage after changing sender/lookback
  policy. Once initialized, the arrivals scan retains coverage since its last
  watermark even across a longer scheduler outage.
- **Attachment preparation:** inspect `attachment_retries`, mode/profile availability
  of the Gmail attachment tool, Stash storage and configured limits. The service
  setting `WORKSPACE_MCP_MAX_FILE_BYTES`, if set, must also allow the complete
  encoded EML export, not just the decoded PDF. After three failures, fix the
  service/content issue and send a fresh request; do not delete the ledger.
- **Disable:** set `jarvis_email.enabled` to false, and optionally pause the
  scheduled task. Existing ledger/contacts stay intact. Revocation is checked
  before dispatch and reply; it cannot undo a tool already executing.
