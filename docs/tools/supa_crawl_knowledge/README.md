# Supa-Crawl-Knowledge Tool

`supa_crawl_knowledge` gives Jarvis read-only access to a Supa-Crawl-Chat instance:

- Repo: [bigsk1/supa-crawl-chat](https://github.com/bigsk1/supa-crawl-chat)
- Jarvis tool files:
  - `skills/supa_crawl_knowledge.py`
  - `skills/supa_crawl_knowledge.tool.json`

Use it when the answer is likely already inside your crawled corpus and you want stable, indexed content instead of a live fetch.

## What it does

This tool queries your Supa-Crawl-Chat API for:

- semantic search over crawled pages and chunks
- site listings and crawl status
- page lists for a site
- full stored page content
- child chunk rows for a parent page
- basic corpus health and crawl activity

It complements `crawl_url`:

- `crawl_url` is for live web pages right now
- `supa_crawl_knowledge` is for content you already crawled and embedded

## Why it is read-only

Jarvis treats this tool as a retrieval tool, not a crawler controller.

That is deliberate:

- it keeps the tool safe to auto-run
- it avoids accidental recrawls or database writes
- it makes the tool predictable in multi-turn conversations
- it keeps "search/read" separate from "store/save/curate"

If Jarvis finds something worth keeping, it can follow up with other tools:

- `remember` for durable facts
- `stash` for temporary full text or JSON blobs
- `manage_intel` / `ingest_intel` for curated notes
- `canvas` for a readable page in the Web UI

## Config

Set the API base URL in your env:

```bash
SUPA_CRAWL_CHAT_URL=http://localhost:8001
```

If your Supa-Crawl-Chat API has auth enabled:

```bash
SUPA_API_KEY=your-secret
```

Header style:

- default or unset `SUPA_API_KEY_STYLE`:
  - `Authorization: Bearer $SUPA_API_KEY`
- `SUPA_API_KEY_STYLE=x-api-key`:
  - `X-API-Key: $SUPA_API_KEY`

The Jarvis tool reads these from env automatically. You do not pass secrets in tool arguments.

## How Jarvis maps actions to the API

- `action=search` -> `GET /api/search`
- `action=list_sites` -> `GET /api/sites`
- `action=site` -> `GET /api/sites/{site_id}`
- `action=site_status` -> `GET /api/crawl/status/{site_id}`
- `action=site_pages` -> `GET /api/sites/{site_id}/pages`
- `action=page` -> `GET /api/pages/{page_id}`
- `action=page_chunks` -> `GET /api/pages/{page_id}/chunks`
- `action=health` -> `GET /api/health`
- `action=crawl_activity` -> `GET /api/crawl/activity`

## Search modes

There are two main search result modes:

### Preview mode

Use this for fast scanning:

- `include_search_content=false`
- `search_preview_chars=500` by default

The API returns `content_preview`, not the full body.

### Full-content mode

Use this when Jarvis may be able to answer directly from search hits:

- `include_search_content=true`
- `search_content_chars=10000` by default

The API returns truncated full content per hit.

These are different modes. `search_preview_chars` is for preview mode, while `search_content_chars` controls full-content mode.

## Important page vs chunk note

If search returns a chunk hit:

- `action=page` with that chunk row's `id` will return that chunk's stored body
- `action=page_chunks` usually wants the parent page id

In practice:

- if `is_chunk=true`, use `parent_id` for `page_chunks`
- use the row's own `id` for `page` if you want that exact chunk body

This is the most common point of confusion when testing the API by hand.

## curl examples

### Bearer auth

```bash
curl -sS \
  -H "Authorization: Bearer $SUPA_API_KEY" \
  "$SUPA_CRAWL_CHAT_URL/api/search?query=ollama%20linux%20install&limit=3"
```

### X-API-Key auth

```bash
curl -sS \
  -H "x-api-key: $SUPA_API_KEY" \
  "$SUPA_CRAWL_CHAT_URL/api/search?query=ollama%20linux%20install&limit=3"
```

### Search in preview mode

```bash
curl -sS \
  -H "Authorization: Bearer $SUPA_API_KEY" \
  "$SUPA_CRAWL_CHAT_URL/api/search?query=ollama&limit=3&include_content=false&preview_chars=1000"
```

### Search in full-content mode

```bash
curl -sS \
  -H "Authorization: Bearer $SUPA_API_KEY" \
  "$SUPA_CRAWL_CHAT_URL/api/search?query=ollama&limit=3&include_content=true&content_chars=5000"
```

### List pages for one site with preview bodies

```bash
curl -sS \
  -H "Authorization: Bearer $SUPA_API_KEY" \
  "$SUPA_CRAWL_CHAT_URL/api/sites/3/pages?limit=10&offset=0&include_content=false&preview_chars=800"
```

### Read one page

```bash
curl -sS \
  -H "Authorization: Bearer $SUPA_API_KEY" \
  "$SUPA_CRAWL_CHAT_URL/api/pages/1589"
```

### Read all chunks for a parent page

```bash
curl -sS \
  -H "Authorization: Bearer $SUPA_API_KEY" \
  "$SUPA_CRAWL_CHAT_URL/api/pages/1370/chunks"
```

## Example tool calls

### Search a topic

```json
{
  "action": "search",
  "query": "ollama linux install",
  "limit": 5,
  "include_search_content": false,
  "search_preview_chars": 1000
}
```

### Search with full content

```json
{
  "action": "search",
  "query": "ollama linux install",
  "limit": 3,
  "include_search_content": true,
  "search_content_chars": 5000
}
```

### Drill into one page

```json
{
  "action": "page",
  "page_id": 1589,
  "content_chars": 12000
}
```

### Get all chunks for a parent page

```json
{
  "action": "page_chunks",
  "page_id": 1370,
  "content_chars": 6000
}
```

### Paginate site pages

```json
{
  "action": "site_pages",
  "site_id": 3,
  "limit": 20,
  "pages_offset": 20,
  "include_pages_content": false,
  "pages_preview_chars": 700
}
```

## Good Jarvis prompts

These are the kinds of prompts that tend to produce useful multi-tool chains.

### Search, then answer directly

`Use supa_crawl_knowledge to find the Ollama Linux install guide and explain the steps in plain English.`

### Search, then save to Canvas

`Use supa_crawl_knowledge to find the best Ollama GPU setup docs, summarize the important parts, and save the summary to canvas.`

### Search, then save raw material to Stash

`Search my Supa-Crawl corpus for Traefik v3 docker examples, put the most relevant full page content into stash, and tell me the stash ref.`

### Search, then save distilled facts to memory

`Use supa_crawl_knowledge to find the Ollama Linux requirements, then save the key requirements to memory so we can reuse them later.`

### Search, then create curated intel

`Search my Supa-Crawl corpus for Supabase realtime docs, pull the most relevant snippets, and create an intel note with only the important implementation details.`

### Search, then compare multiple hits

`Use supa_crawl_knowledge to find docs about Ollama tool calling, compare the top 3 hits, and save the comparison to canvas.`

## Recommended workflows

### Fast answer workflow

1. `search` with preview mode
2. If one hit is enough, answer from previews
3. If not, call `page` or `page_chunks`

### Research workflow

1. `search`
2. `page` or `page_chunks`
3. `canvas` for readable output
4. optional `remember` or `manage_intel`

### Archive workflow inside Jarvis

1. `supa_crawl_knowledge` finds relevant stored content
2. `stash` keeps a temporary working copy
3. `text_summarizer`, `canvas`, `remember`, or intel tools shape the final artifact

## Notes on context size

The API can return large bodies, but Jarvis does not blindly feed all of that back into every later turn.

In practice:

- the Web UI can still show the full tool payload
- the orchestrator builds a smaller preview for later LLM turns
- follow-up turns should narrow to `page`, `page_chunks`, or smaller limits when more detail is needed

That keeps the tool useful without flooding context on every turn.

## Troubleshooting

### "401 unauthorized"

Check:

- `SUPA_API_KEY`
- `SUPA_API_KEY_STYLE`
- whether the server expects Bearer or `x-api-key`

### "page_chunks returned 0 rows"

You probably passed a chunk row id instead of the parent page id.

Try the hit's `parent_id`.

### "Jarvis used crawl_url instead"

That is a routing decision. Be explicit:

`Use supa_crawl_knowledge, not crawl_url.`

### "Jarvis found results but did not save them"

Ask for the next step directly:

- `save the summary to canvas`
- `put the raw page in stash`
- `remember the key requirements`
- `create an intel note from the important snippets`

## Related docs

- `docs/crawl4ai/README.md`
- `docs/CANVAS_SYSTEM.md`
- `docs/STASH_SYSTEM.md`
- `docs/MEMORY_SYSTEM.md`
- `docs/TOOL_CALLING_SYSTEM.md`
