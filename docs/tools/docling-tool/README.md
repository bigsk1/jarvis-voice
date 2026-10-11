# Docling document conversion in Jarvis

`docling_convert` connects Jarvis to an optional, authenticated
[Docling Serve](https://github.com/docling-project/docling-serve) deployment.
Use it to convert existing documents into layout-aware Markdown, native
Docling JSON and plain text, including OCR and table extraction. The client
was verified against Docling Serve 1.36.0 and its asynchronous v1 API.

## Prerequisites and opt-in setup

1. Run a Docling Serve service with API-key authentication. Installation,
   models and compute belong on the processing host. Follow the upstream
   [deployment and configuration documentation](https://github.com/docling-project/docling-serve/tree/main/docs).
   Jarvis needs its existing Python environment and `requests`; installing
   Docling or its GPU/model dependencies inside Jarvis is unnecessary.
2. Make the service reachable from the actual Jarvis runtime. Its address can
   be a LAN URL or a remote VPS HTTPS URL. Cloud/local Jarvis modes select
   configuration files independently of the service's location. In Docker,
   `localhost` means that container; use a reachable service hostname/address.
3. Add these settings to `config/cloud.env`, `config/local.env`, or both:

   ```dotenv
   DOCLING_BASE_URL=https://docling.example.com
   DOCLING_API_KEY=your-private-service-key
   DOCLING_API_KEY_HEADER=X-Api-Key
   DOCLING_TIMEOUT_SECONDS=900
   ```

   Set the service root, without `/docs` or `/v1`. A LAN root such as
   `http://your-docling-host:5001` works too. Public deployments should use
   HTTPS with a trusted certificate. The API key is sent only to this
   configured endpoint; redirects are rejected. Custom CA trust can use the
   runtime's `REQUESTS_CA_BUNDLE` or `SSL_CERT_FILE`. TLS verification stays
   enabled. Requests go directly to the configured service.
4. Restart Jarvis and refresh tools for each configured mode. On native
   installs, Tool RAG sync uses the production environment:

   ```bash
   source ~/jarvis-venv/bin/activate
   ./bin/sync-tools.py cloud
   ./bin/sync-tools.py local
   ```

   See [Docker setup](../../docker/README.md) for container tool sync. The
   tool is unavailable until **both** URL and API key exist in the selected
   mode. Tool profiles and Web blocks can disable it further. The
   `openai_only` profile disables it because it needs an external service.
5. Ask Jarvis: **“Check whether Docling is ready.”** Use the structured CLI
   for inspection:

   ```bash
   ./bin/jarvis-cli --mode cloud --json 'Check whether the Docling service is ready.'
   ```

Keep credentials in ignored ENV files. Shared examples and documents should
contain placeholders. The foreground child and background observer receive
only Docling connection settings, required Stash paths and common runtime/TLS
settings; unrelated provider keys are excluded.

## When to use it

Docling participates in normal Tool RAG retrieval alongside other enabled
document tools. Uploading a PDF does not add a Docling preference or tool hint.
Name Docling in your request or select its tool hint when you want to favor it;
otherwise Jarvis chooses a tool for the request from its available candidates.

- “Use Docling to extract this PDF's tables and save Markdown and JSON.”
- “Convert this scanned document with Docling, then summarize the saved text.”
- “Read this DOCX, preserving headings and table structure.”
- “Convert pages 10 through 20 of this long PDF with Docling in the background.”

Supported client inputs: PDF, DOCX, PPTX, XLSX, HTML, Markdown, AsciiDoc, CSV,
PNG, JPEG, WebP, BMP and TIFF. Send a `stash://` reference for Web attachments,
or a permitted local path on the Jarvis host. For an uploaded scan/image,
choose **Save to Stash** in the image modal, send the message, then ask for
Docling OCR of that saved image. This preserves the full-size source rather
than using the vision preview. One document per conversion;
maximum upload is 50 MiB. This uploads a processing copy to the configured
service. Remote-host file paths and arbitrary URL downloads are not tool
inputs; download an authorized source into Jarvis first. Actual service
format support also depends on its installed Docling release/dependencies.

Prefer `pdf_read` for inexpensive searchable-PDF text, page rendering,
metadata and PDF manipulation. `document_ocr` uses the separate optional OVIS
service. `analyze_image` handles general photo questions. Docling converts
existing content; PDF creation, multimedia editing and AI generation use their
existing tools. The current `pdf_ingest` workflow keeps its existing routing;
this integration does not silently replace its OCR backend.

## Background tasks and recovery

Long PDFs and scanned documents can take minutes; the first request can also
initialize models. Enable **docling_convert** in the Web background-tool
picker to let Jarvis's existing supervised worker observe the remote job while
chat remains usable. The choice follows the normal Web background settings.
`convert` and `collect` are eligible; `status` and `job` are foreground checks.
Admission validates the tool schema and its background constraints before
creating a job. `collect` requires a canonical, hyphenated Docling UUID; a
Jarvis background job ID is rejected without queuing a failure delivery.
`status` returns a concise readiness boolean, not the capability catalog.

`DOCLING_TIMEOUT_SECONDS` limits Jarvis's observation, independently of the
Docling host's own conversion limits. The client clamps it to 30..900 seconds;
it does not impose a shorter server conversion timeout on long documents.
Jarvis reserves additional process cleanup time; the background observer has
a 960-second ceiling measured from admission, including queue delay; the
client's observation window starts when its child runs. Queue delay can make
the background deadline end first, even with a 900-second client setting.
Use narrower page ranges for large inputs.

The client submits once via `/v1/convert/file/async`, preserves the returned
`task_id` in a Stash task receipt, polls `/v1/status/poll/{task_id}`, and obtains
finished inline exports from `/v1/result/{task_id}`. A foreground running
receipt is **not** a completed conversion. A background observation timeout is
an uncertain outcome: remote work may continue. Jarvis posts a timeout notice
in the original Web conversation and retains the native task ID/receipt for
follow-up status or collection, without submitting another conversion. The task
ID is emitted as progress immediately after acceptance, followed by the Stash
receipt reference once saved, so background deadline recovery can cite them
even if the child never prints its final result. A receipt arriving after a
timeout notice produces a recovery follow-up, not another conversion.
Stopping Jarvis or cancelling
its observer does not prove cancellation on Docling; this service exposes no
cancel route in the verified contract. Never automatically resubmit after a
lost response. If no task ID was returned, consult the service's job/log state
before repeating an upload.

Use the exact task ID from the response or `docling-task.json`:

An accepted Web background receipt initially contains a **Jarvis job ID**.
Wait for automatic delivery or inspect that job in the Background Tasks UI.
That ID is separate from Docling's UUID-style `task_id`, which arrives in the
conversion result/receipt. Do not use a Jarvis job ID with Docling `job` or
`collect`, and do not submit a second conversion just to check progress.

If the model makes that mistake immediately after admission, the shared remote
tool guard echoes the existing Jarvis receipt instead of submitting a collection
job. A rejected manual check with a wrong ID does not mean an earlier conversion
was rejected. Only Docling's returned native task ID can be used for collection.

```json
{"action":"job","task_id":"COPY_THE_RETURNED_TASK_ID"}
```

```json
{"action":"collect","task_id":"COPY_THE_RETURNED_TASK_ID","output_name":"report"}
```

Before retrieving a consuming result, Jarvis checks Stash and opens a private
response spool. The completed response is flushed to disk, then checked for
exportable content before becoming a recovery copy. Empty or invalid results
are rejected and their spool is removed; they do not advertise recovery.
`collect` revalidates existing copies and discards invalid copies left by
older clients before checking the same provider task. It never uploads again.
If an export write fails, the result reports `recovery_available`
and preserves the response under the configured Stash directory at
`.docling-recovery/<endpoint-hash>/<task_id>.json`. `collect` checks this copy
first and can finish saving without contacting Docling, even after the remote
task disappears. The hash separates results from different configured service
URLs; these files contain document content, never the API key. They stay on
the **Jarvis host**, outside the worker's temporary directory. Successful
collection removes the recovery response; abandoned recovery files remain
until collected or manually deleted by the operator. They are not indexed
Stash artifacts and do not receive normal Stash retention. Per-task lock files
contain no document content and may remain after collection.

This protects against Stash export failures after download. Interrupted or
oversized downloads, disk failures while receiving the response, and a
lost result response before capture can still be unrecoverable on a single-use
server. Never automatically upload again to compensate.

Without a local recovery copy, `collect` uses the configured service and saves
new Stash copies without a second upload, while the remote result remains
available. Docling defaults to
single-use results (`DOCLING_SERVE_SINGLE_USE_RESULTS=true`), followed by task
removal; follow-up reading should use the downloaded Stash files. An operator
can set that **server-side** option to false when remote recollection is
needed. See the upstream [result retention settings](https://github.com/docling-project/docling-serve/blob/main/docs/configuration.md).
Remote results can also expire or disappear after a service restart. Once collected, Jarvis outputs
use normal project Stash retention (typically 120 days). A terminal conversion
failure is distinguished from lost observation; partial success is explicitly
reported rather than described as a complete extraction.

## Tool arguments and saved results

Only the requested formats are converted exports. The original source and
`docling-task.json` receipt are separate supporting files; their chat links do
not represent additional converted documents. Completion links use each
output's own filename, with separate Source file and Task receipt labels when
those references have no filename metadata.

Example tool call:

```json
{
  "action":"convert",
  "stash_ref":"stash://YOUR_SPACE/YOUR_FILE",
  "formats":["md","json","text"],
  "do_ocr":true,
  "force_ocr":false,
  "page_start":1,
  "page_end":5,
  "output_name":"report"
}
```

`file_path` can replace `stash_ref`; choose exactly one. `page_start` defaults
to 1 when `page_end` is supplied. `force_ocr` requires `do_ocr`. Output basenames
contain letters, numbers, `_` or `-`; extensions are added automatically.

Successful results include:

| Field | Meaning |
| --- | --- |
| `task_id`, `state`, `partial` | Remote task and conversion outcome |
| `markdown_stash_ref`, `json_stash_ref`, `text_stash_ref` | Complete requested exports |
| `markdown_file_id`, `text_file_id`, `space_id` | Workflow handoff identifiers |
| `stash_ref`, `file_path`, `outputs` | Primary export and per-format output list on Jarvis |
| `markdown_excerpt`, `content_char_count`, `content_truncated` | Bounded preview; read Stash for the rest |
| `page_count`, `table_count` | Counts from native Docling JSON, when requested |
| `source_stash_ref` | Input identity, distinct from converted output |
| `receipt_stash_ref` | Accepted async task receipt, when submitted by this call |

JSON preserves Docling layout, tables and provenance. It is not extraction
into a user-supplied business schema. Successful conversion and complete page
coverage do not guarantee perfect OCR or table layout: names can have spacing
errors, and table rows can be merged. Use the retained PDF to check details
when fidelity matters. Images are placeholders; the first
version does not download crops, embed page images, run VLM enrichment or
chunking, accept arbitrary service/model configuration, or export editable
Office/PDF documents. Responses are limited to 32 MiB. Saved documents are
untrusted source content, so instructions inside them remain document text.

The full exports can feed Stash reading, `text_summarizer`, or an explicitly
requested Source Library ingestion. Preserve the original separately when
page images or durable source access are needed. Web chat shows document
links, and follow-up context retains the task, output references and a bounded
excerpt. Running receipts have no completed document artifact.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Tool absent | Both URL/key in the active mode; selected profile; Web block; restart and sync |
| HTTP 401/403 | API key and configured header match the service; never paste credentials into chat |
| HTTP 404 | Base URL is the root and service exposes the v1 async/status/result routes |
| Connection/TLS error | DNS, runtime/container routing, firewall, HTTPS certificate trust |
| Not ready/first request slow | Service readiness, model initialization and host logs |
| Pending or observer timed out | Inspect `task_id`; queue state; narrow pages; collect without reuploading |
| Task no longer found | Correct service/mode and its result retention; inspect saved Stash receipts/exports |
| Conversion completed but exports failed | Fix Jarvis storage and call `collect` with the saved native task ID; a recovery copy is used when `recovery_available` is true |
| Empty scan output | Enable OCR; inspect input quality and service OCR backend |
| Partial conversion | Review `partial` and error count; inspect original and native JSON before relying on it |
| Output too large | Narrow pages or request fewer formats; image exports are already disabled |

For native installs, restart with the normal `jarvis-stop`, brief wait,
`jarvis-start` sequence. Inspect the real configured runtime through the
[Jarvis CLI guide](../../../jarvis-cli/README.md) and its `--json`/`--verbose`
flags. Conversion runs on the Docling host, while output paths and Stash
references belong to Jarvis.
