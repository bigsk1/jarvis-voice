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
# Optional direct evidence search (all three required for `passages`):
PROJECT_NOMAD_QDRANT_URL=http://your-nomad-host:6333
PROJECT_NOMAD_EMBEDDING_URL=http://your-ollama-host:11434
PROJECT_NOMAD_EMBEDDING_MODEL=exact-model-used-to-build-the-nomad-index
```

The URL is the Nomad server root, not `/reference` or `/api/openapi.json`.
`PROJECT_NOMAD_BASE_URL` is the opt-in switch: without it, the tool is unavailable
to Jarvis and Tool RAG. `PROJECT_NOMAD_MODEL` is needed only for `ask`; use the
tool's `models` action to see exact installed IDs, or supply `model` on one call.
The three retrieval settings are needed only for `passages`; Jarvis will not
guess them from its own embedding configuration. Match the model that built
NOMAD's index, including its tag. Equal vector dimensions do **not** establish
model compatibility. These URLs are operator settings, never model arguments.
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

Project NOMAD currently documents no built-in authentication. Keep its API,
Qdrant, and Ollama on a trusted LAN or behind your own authenticated gateway;
never expose these unprotected services to the public internet. Jarvis does
not follow redirects or use ambient HTTP proxies for this tool. A reverse proxy
requiring credentials is not supported by this first cut.

Tool results enter the active Jarvis conversation. If that conversation uses a
cloud LLM, Nomad answers, retrieved passages, and selected file excerpts may
be sent to that LLM.
Use a local Jarvis provider and a local Nomad model when that data must stay
on your LAN; verify the Ollama host configured inside Nomad as well.

## What Jarvis can do

| Action | Nomad endpoint | Meaning |
| --- | --- | --- |
| `passages` | Ollama `POST /api/embed` + Qdrant `POST /collections/nomad_knowledge_base/points/search` | Retrieve up to ten indexed chunks (five by default) with text, archive/article titles, source/path, and similarity score. The query uses NOMAD's `search_query: ` prefix and a fixed 0.3 score threshold. No second LLM call. Requires the three retrieval settings above. |
| `ask` | `POST /api/ollama/chat` | Ask Nomad's AI assistant. Its configured system prompt and knowledge-base retrieval are handled by Nomad. Optional `collection` is sent as the query filter. No Nomad chat `sessionId` is sent, so these tool calls are not saved as a Nomad chat session. |
| `files` | `GET /api/rag/files` | List stored-file metadata with complete inventory state counts, optional `query` substring filter on filename/source, pagination, and a `viewable_text` flag. This does not search file contents. A stored file may still be awaiting embeddings. |
| `read_file` | `GET /api/rag/files/content` | Read a `viewable_text=true` uploaded text file in 12,000-character pages. Nomad does not serve PDFs, EPUBs, ZIMs, or non-uploaded files through this endpoint. |
| `collections` | `GET /api/rag/collections` | List **named groups**, not the whole knowledge base. Unassigned files can still be indexed and searched; zero named collections does not mean zero indexed files. |
| `zims` | `GET /api/zim/list` | Inventory installed Kiwix/ZIM archives; this action does **not** search their article text or prove it was embedded. |
| `models` | `GET /api/ollama/installed-models` | Find usable model IDs, including whether an ID is marked `:cloud`. |
| `status` | `GET /api/health`, `GET /api/rag/health` | Check the server and KB reachability. This is not an indexing-job progress check. |

The current Nomad catalog has **no separate `/api/rag/search` endpoint**.
For questions about what stored content says, use `passages` **without** a
`collection` filter unless an exact named collection exists. A topic or
filename such as "cookbook" is not automatically a collection. Jarvis rejects
unknown collection names rather than silently widening the query. Retrieved
text is indexed evidence, not an original-layout page or a guarantee that the
passage answers the question. No match does not prove the entire archive lacks
the answer. Direct search is semantic-only: it does not reproduce Nomad's chat
question rewrite or RAG reranking, and it does not search ZIMs that have not
been embedded. `ask` remains available for Nomad's own AI voice, but its chat
response hides the passages it used, so Jarvis marks that answer unverified.
For uploaded text files, `files` and `read_file` can retrieve exact file text;
the content endpoint does not serve ZIM articles or PDF/EPUB originals. Nomad's
archive and Jarvis Source Library are separate stores.

All inventory actions return at most 20 rows per call. `total`, `offset`, and
`has_more` make a growing archive navigable without flooding a chat response.
Nomad's listing endpoints currently return the full inventory to the adapter,
which bounds its response to 8 MiB before parsing; this is not server-side
pagination. `read_file` likewise has an 8 MiB response cap and returns an
excerpt. Larger files should be opened in Nomad's own UI. Responses from
Nomad are external content, not instructions for Jarvis.

In Jarvis Web, `passages`, `ask`, and `read_file` show short, full-width previews.
Click a passage card or its **Read passage** button for the saved full text;
`ask` and `read_file` have their own plain-text reader buttons. The reader
does not call Nomad again.
Press Escape or use the close button to return to the conversation.

The tool intentionally excludes upload, download, deletion, indexing,
collection mutation, application installation, service control, settings, and
other administration. Manage those in Nomad's standalone UI.

## Examples

- “Ask NOMAD's own assistant for its take on water purification.”
- “Search my NOMAD archives for passages on making a sourdough starter, and cite the article titles.”
- “How many NOMAD files report embedded chunks, and how many are still pending? Show the first ten.”
- “Find NOMAD files with `cooking` in the filename.”
- “Search indexed NOMAD passages about cooking techniques, with no collection filter.”
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
For example, a host with both `nomic-embed-text-v2-moe:latest` and
`nomic-embed-text:latest` must not pick a query model merely because both
produce 768-dimensional vectors. Confirm which one indexed the stored points;
if that changed partway through indexing, rebuild in NOMAD before trusting
retrieval. Jarvis does not mutate the Qdrant collection.
