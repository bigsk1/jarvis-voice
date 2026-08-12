# Document OCR Tool

`document_ocr` connects Jarvis to an optional self-hosted [OVIS FastAPI service](https://github.com/bigsk1/ovis-fastapi). It is intended for scanned or image-only PDFs and text-heavy images. Born-digital PDF reading, metadata, search, merge, split, and rendering remain the job of `pdf_read`.

## Configuration

Set the service root in the active Jarvis mode file (`config/cloud.env` or `config/local.env`):

```bash
OVIS_OCR_URL="http://your-ovis-host:17860"
OVIS_OCR_TIMEOUT_SECONDS=900
OVIS_OCR_CONNECT_TIMEOUT_SECONDS=5
```

Only `OVIS_OCR_URL` is required. When it is blank or absent, Jarvis excludes the tool from the available registry. It can also be disabled with `BLOCKED_TOOLS`, a tool profile override, or the Web UI blocked-tools setting.

Use the service root, not `/docs` or a `/v1/...` path. A LAN/private address is allowed because the endpoint is administrator-configured; users cannot supply a different request URL to the tool.

Jarvis does not need `OVIS_GENERATE_BACKEND`, the Ollama URL/model, or an OpenAI-compatible key. Those stay on the OVIS host. With a local Ollama backend, both OCR and instruction extraction remain local to that host.

## Actions

- `status` checks `/health/live`, `/health/ready`, and `/v1/capabilities`. It reports model/device state and whether structured extraction is configured.
- `ocr` calls `/v1/ocr` and returns a bounded Markdown excerpt plus page/model/timing metadata. Full Markdown and service JSON are saved to Stash by default.
- `extract` calls `/v1/generate`. OVIS first runs fixed-prompt OvisOCR2 OCR, then applies `prompt` through the text backend configured on the OVIS host. It supports document/page scope and text, Markdown, or JSON output. For strict JSON, send `response_format=json` and `json_schema`. Page-scoped extraction returns bounded, page-attributed inline results and saves a clean page-results JSON artifact in addition to the complete service envelope.
- `archive` calls `/v1/ocr/archive` and saves the returned ZIP to Stash.

The tool accepts PDF, PNG, JPEG, WebP, BMP, and TIFF inputs through exactly one of `stash_ref`, `space_id` plus `file_id`, or a policy-approved `file_path`. Conflicting sources are rejected instead of silently selecting one. Web uploads should use their `stash://...` reference.

Example strict extraction arguments:

```json
{
  "action": "extract",
  "stash_ref": "stash://space_.../f_...",
  "prompt": "Extract the invoice number, total, and due date.",
  "scope": "document",
  "response_format": "json",
  "json_schema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "invoice_number": {"type": "string"},
      "total": {"type": "string"},
      "due_date": {"type": "string"}
    },
    "required": ["invoice_number", "total", "due_date"]
  }
}
```

## Runtime behavior

Before a document upload, Jarvis performs a short readiness check. A loading or unavailable service fails cleanly without attempting the upload. POST requests are not automatically retried because a timeout does not prove whether the remote inference completed.

Jarvis also disables HTTP redirects for document requests. Configure
`OVIS_OCR_URL` with the service's canonical root URL rather than relying on an
HTTP redirect that could forward an uploaded document elsewhere.

The HTTP read timeout defaults to 15 minutes and the Jarvis tool subprocess allows 20 minutes. Set `OVIS_OCR_TIMEOUT_SECONDS` between 10 and 1100 seconds for the deployment; the subprocess remains the outer bound.

Inputs are limited to 50 MB. JSON responses are bounded to 25 MB and archives to 100 MB. Full successful content is stored as Stash artifacts by default while inline tool and Web follow-up context is deliberately bounded. Page-scoped extraction uses one shared inline budget instead of multiplying a per-page excerpt by every selected page. If `save_to_stash=false`, truncation notices explicitly state that omitted content was not saved. This lets later turns answer questions about the OCR text without repeatedly placing an entire large document into routing prompts.

`max_new_tokens` has action-specific budget semantics. OCR applies it per OCR
page. Document-scoped extraction makes one generation call. Page-scoped
extraction makes one call per selected page, so the selected page count times
the effective token limit must fit the OVIS host's
`max_generate_request_tokens` aggregate. Use `action=status` to inspect the
active per-call and aggregate limits, and choose a narrow page range or smaller
`max_new_tokens` for page scope.

`include_region_data=true` embeds figure crops as Base64 data URLs and can
exceed Jarvis's JSON response bound even when OVIS accepts the request. Use it
only for narrow page ranges. Prefer `action=archive` when complete figure crops
are needed; the ZIP is always saved to Stash.

`document_ocr` does not call OVIS image-generation routes. The service's `/v1/generate` name refers to text instruction/extraction after OCR, not image generation.

## Quick checks

From the Jarvis host, first confirm the OVIS service itself:

```bash
curl --fail --show-error "$OVIS_OCR_URL/health/ready"
curl --fail --show-error "$OVIS_OCR_URL/v1/capabilities"
```

Then refresh Tool RAG for the active mode and verify availability:

```bash
./bin/sync-tools.py cloud  # or local; use the Jarvis operator venv
./bin/manage-tools.py --mode cloud list
```
