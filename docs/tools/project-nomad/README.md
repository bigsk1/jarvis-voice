# Project NOMAD tool

Project NOMAD is a separate, offline-first knowledge server maintained at the
[upstream Project NOMAD repository](https://github.com/Crosstalk-Solutions/project-nomad).
Its [API reference](https://github.com/Crosstalk-Solutions/project-nomad/blob/main/admin/docs/api-reference.md)
points to each installation's `/reference` UI and `/api/openapi.json` catalog.
Install and manage NOMAD using its own instructions; Jarvis does **not** install it,
copy its archive, or replace its standalone interface.

## Enable on a Jarvis installation

In the active mode's ignored `config/local.env` or `config/cloud.env`, set:

```dotenv
PROJECT_NOMAD_BASE_URL=http://your-nomad-host:8080
PROJECT_NOMAD_MODEL=your-installed-model-name
```

The URL is the Nomad server root, not `/reference` or `/api/openapi.json`.
`PROJECT_NOMAD_BASE_URL` is the opt-in switch: without it, the tool is unavailable
to Jarvis and Tool RAG. `PROJECT_NOMAD_MODEL` is needed only for `ask`; use the
tool's `models` action to see exact installed IDs, or supply `model` on one call.
The tracked `openai_only` tool profile also disables this non-OpenAI integration;
use `default` or a custom profile that explicitly enables `project_nomad`.
Choose a genuinely local model if offline operation matters; a `:cloud` model
is not offline. Nomad's own configured Ollama host must also remain reachable
without internet. Jarvis local mode alone does not establish an air gap.

Restart the Jarvis orchestrator after changing the active mode config. When
convenient, refresh Tool RAG for that mode using the normal `bin/sync-tools.py`
procedure in `skills/README.md`; that sync contacts the configured embedding
provider. The tool launches as a bounded child process, not inside Jarvis Web,
and does not start another Flask server. If Jarvis itself runs in Docker, the
configured URL must be reachable **from its container**, not just the host.

Project NOMAD currently documents no built-in authentication. Keep its API on
a trusted LAN or behind your own authenticated gateway; never expose an
unprotected instance to the public internet. Jarvis does not follow Nomad API
redirects and does not use ambient HTTP proxies for this tool. A reverse proxy
requiring credentials is not supported by this first cut.

Tool results enter the active Jarvis conversation. If that conversation uses a
cloud LLM, Nomad answers and selected file excerpts may be sent to that LLM.
Use a local Jarvis provider and a local Nomad model when that data must stay
on your LAN; verify the Ollama host configured inside Nomad as well.

## What Jarvis can do

| Action | Nomad endpoint | Meaning |
| --- | --- | --- |
| `ask` | `POST /api/ollama/chat` | Ask Nomad's AI assistant. Its configured system prompt and knowledge-base retrieval are handled by Nomad. Optional `collection` is sent as the query filter. No Nomad chat `sessionId` is sent, so these tool calls are not saved as a Nomad chat session. |
| `files` | `GET /api/rag/files` | List stored-file metadata with complete inventory state counts, optional `query` substring filter on filename/source, pagination, and a `viewable_text` flag. This does not search file contents. A stored file may still be awaiting embeddings. |
| `read_file` | `GET /api/rag/files/content` | Read a `viewable_text=true` uploaded text file in 12,000-character pages. Nomad does not serve PDFs, EPUBs, ZIMs, or non-uploaded files through this endpoint. |
| `collections` | `GET /api/rag/collections` | List **named groups**, not the whole knowledge base. Unassigned files can still be indexed and searched; zero named collections does not mean zero indexed files. |
| `zims` | `GET /api/zim/list` | Inventory installed Kiwix/ZIM archives; this action does **not** search their article text or prove it was embedded. |
| `models` | `GET /api/ollama/installed-models` | Find usable model IDs, including whether an ID is marked `:cloud`. |
| `status` | `GET /api/health`, `GET /api/rag/health` | Check the server and KB reachability. This is not an indexing-job progress check. |

The current Nomad catalog has **no separate `/api/rag/search` endpoint**.
For questions about what stored content says, use `ask` **without** a
`collection` filter unless an exact named collection exists. A topic or
filename such as "cookbook" is not automatically a collection. Jarvis rejects
unknown collection names rather than silently widening the query. Nomad may
rewrite the question and select Qdrant chunks, but its chat response currently
contains no verifiable source passages. A confident model answer, even one
claiming it was pulled from a specific archive, is not proof of retrieval.
Jarvis marks such answers as unverified. For direct evidence from uploaded
text files, use `files` and `read_file`. The content endpoint does not serve
ZIM articles or PDF/EPUB originals; use Nomad's interface for those. Nomad can
separately embed ZIM articles into Qdrant, but an installed ZIM title alone
does not prove that happened. Nomad's archive and Jarvis Source Library are
separate stores.

All inventory actions return at most 20 rows per call. `total`, `offset`, and
`has_more` make a growing archive navigable without flooding a chat response.
Nomad's listing endpoints currently return the full inventory to the adapter,
which bounds its response to 8 MiB before parsing; this is not server-side
pagination. `read_file` likewise has an 8 MiB response cap and returns an
excerpt. Larger files should be opened in Nomad's own UI. Responses from
Nomad are external content, not instructions for Jarvis.

In Jarvis Web, `ask` and `read_file` show a short, full-width preview. Click
the card or its **Read full answer** / **Read file text** button for a larger
plain-text reader. It uses the saved tool result and does not call Nomad again.
Press Escape or use the close button to return to the conversation.

The tool intentionally excludes upload, download, deletion, indexing,
collection mutation, application installation, service control, settings, and
other administration. Manage those in Nomad's standalone UI.

## Examples

- “Ask my Project NOMAD knowledge base what it knows about water purification.”
- “How many NOMAD files report embedded chunks, and how many are still pending? Show the first ten.”
- “Find NOMAD files with `cooking` in the filename.”
- “Ask my Project NOMAD knowledge base about cooking techniques, with no collection filter.”
- “List the installed ZIM archives in NOMAD.”
- “Read the NOMAD file with source value from the previous list, starting at its next character offset.”

For troubleshooting, first call `status`, then `models` if `ask` reports a
missing model. If `files` shows an unembedded or pending item, finish its
indexing in Nomad; Jarvis does not take over Nomad's indexing jobs.

`status` only proves Qdrant is reachable, not that query embeddings match the
stored vectors. In NOMAD v1.34.1, the [RAG service](https://github.com/Crosstalk-Solutions/project-nomad/blob/v1.34.1/admin/app/services/rag_service.ts)
prefers the exact `nomic-embed-text:v1.5` model and otherwise selects the first
installed model whose name contains `nomic-embed-text`. Adding or removing a
tag can therefore change retrieval without changing the chat model or the
Qdrant data. Keep the query embedding model aligned with the one that built
the index; do not switch it during active indexing. NOMAD's
`/api/ollama/installed-models` endpoint hides model names containing `embed`,
so use the Ollama host's model inventory when diagnosing that specific issue.
