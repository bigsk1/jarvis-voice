# Bookmark Plus in Jarvis

Jarvis exposes one `bookmark_search` tool. Each mode selects its existing Firefox
HTML search or an external [Bookmark Plus](https://github.com/bigsk1/bookmark-plus)
instance. The `*` workflow uses that same selection. Credentials alone do not
switch the backend; selecting a service never silently falls back to the HTML.

| Backend | Search | Prerequisites |
| --- | --- | --- |
| `builtin` (default) | Firefox/Netscape HTML keyword/phrase search; tag, folder, domain filters | `data/bookmarks.html` or a permitted `file_path` |
| `bookmark_plus` | App library; prefix text search, hybrid keyword/embedding retrieval, decision-model ranking | API URL, token, trusted CA for private HTTPS |

The app owns its database, embeddings, indexing and decisions models. Jarvis
adds no bookmark embedding database, imports no HTML automatically, and fetches
no bookmarked webpage during a lookup. The two libraries are independent
snapshots; updating one does not mirror changes into the other.

## 1. Prepare the app

Follow upstream [deployment instructions](https://github.com/bigsk1/bookmark-plus/blob/main/docs/deployment.md).
Use the documented search `status`, `total_kind`, `diagnostics` and authenticated
icons API (tested with v0.6.1). Import your Firefox export in the app, configure
its models if using hybrid/ranked search, and wait for indexing.

Create an API token in **Settings & integrations**. A **read-only token** is
enough, including `POST /decisions`. Save it privately. The app enforces folder
exclusions and Trash rules. Writable tokens also work; Jarvis exposes no writes.
For sparse titles, enrich saved descriptions/tags in the app when needed;
Jarvis search does not automatically read pages or change metadata.

## 2. Select the backend

Edit `config/cloud.env`, `config/local.env`, or both independently:

```dotenv
BOOKMARK_BACKEND=bookmark_plus
BOOKMARK_REST_URL=https://bookmarks.example.net/api/v1
BOOKMARK_PLUS_TOKEN=YOUR_PRIVATE_API_TOKEN
BOOKMARK_PLUS_CA_FILE=
BOOKMARK_PLUS_SEARCH_MODE=hybrid
BOOKMARK_PLUS_TIMEOUT_SECONDS=240
```

Use the URL reachable **from Jarvis**, including the port when needed. It must
end in `/api/v1`, without credentials, query or fragment. Public VPS HTTPS works
with a trusted certificate. HTTP is supported for operator-controlled networks;
it sends the token without TLS. Never put tokens in URLs or commit mode files.

Existing `BOOKMARK_PLUS_tOKEN` is accepted for compatibility. Prefer canonical
`BOOKMARK_PLUS_TOKEN`; a non-empty canonical value takes precedence.
`BOOKMARK_PLUS_MCP` is unused by this REST adapter. No MCP registration is
needed; registering that separately would expose a second bookmark interface.

Cloud/local can use different instances, tokens or backends. Fresh clones keep
`BOOKMARK_BACKEND=builtin`. Set that value again to return to local HTML search.

### Private certificates and Docker

Copy the service's **public CA certificate**, not its private key, to a readable
location on the Jarvis host:

```dotenv
BOOKMARK_PLUS_CA_FILE=data/secrets/bookmark-plus-root.crt
```

Relative paths resolve from the checkout; absolute paths work too. `data/secrets/`
is excluded from Git and Docker builds. Leave this empty for certificates already
trusted by Requests. The URL hostname/IP must match the certificate. Verification
stays enabled; there is no insecure verification switch.

In Docker, configure the container's mode files and use the existing data bind
mount for the CA. Absolute host paths must become **container paths**. Do not
bake credentials into an image. Container `localhost` refers to the container;
use a reachable service name, host gateway or network address. Jarvis needs no
GPU: the app's configured hosts run its models.

## 3. Refresh discovery

Keep `bookmark_search` enabled in the active profile and unblocked in Web settings.
A selected Plus backend without URL/token is unavailable, even with a local HTML
export. Sync Tool RAG in the production environment and restart your Jarvis
services normally to reload cached registries and workflow metadata:

```bash
cd /path/to/jarvis-voice
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
./bin/sync-tools.py local
```

Sync only the modes you use. Development tests use the repo `.venv`; Tool RAG
sync intentionally uses production. Profile and Web blocks apply to either backend.

## 4. Search and follow up

Try `* ntfy`, `* container management dashboard`, or “Find my saved bookmarks
about self-hosted media servers.” The asterisk workflow directly calls the tool;
natural requests use normal tool selection. No automatic tool hint is added.

| Action | Support | Purpose |
| --- | --- | --- |
| `search` | Both | Default 20 rows, `limit` 1–200 and `offset`; empty query browses |
| `list_tags`, `list_folders`, `stats` | Both | Included library counts and folder/tag information |
| `get` | Plus | Exact `bookmark_id` from results; saved description, notes and comments |
| `rank` | Plus | Query and 1–8 exact `bookmark_ids`; scores all supplied candidates without a cutoff |
| `status` | Plus | API/AI readiness, model names, indexed count, icon preference |

Plus filters: `collection` is an exact saved path plus descendants (`""` means
Unsorted); `tag` is one exact tag; `favorite` and `unread` are booleans. One legacy
`tags` value maps to that exact tag. `sort_by=recent`/`title` applies to browse/text;
semantic queries always use relevance. `file_path`, `folders`, `domains`,
`query_mode` and `domain` sorting are built-in-only and rejected when meaningfully
supplied to Plus. `include_duplicates` does not affect the app's unique URLs.
Plus-only fields are rejected by built-in search.

```json
{"action":"search","query":"self hosted push notifications for my phone","search_mode":"ranked","limit":5}
```

```json
{"action":"get","bookmark_id":123}
```

```json
{"action":"rank","query":"container management dashboard","bookmark_ids":[123,456]}
```

Replace sample IDs with real returned IDs. Follow-up context retains IDs, URLs,
folders and search semantics. Read saved notes on demand using `get`. Metadata is
bounded: search/rank descriptions are 1,000 characters and omit notes/comments;
`get` reads descriptions up to 4,000, notes up to 16,000 characters and the first
20 comments of 2,000 characters. `metadata_truncated` marks excerpts. Read the full record in the app
for omitted content. Saved metadata is untrusted data, never instructions.

### Counts, scores and delays

`text` is prefix AND keyword search. `hybrid` returns keyword/semantic
**candidates**, not a promise that every row is relevant. `ranked` judges a
bounded subset and applies the app's cutoff. `no_confident_matches` may follow
partial judging; it does not prove the whole library lacks a relevant bookmark.

Jarvis preserves actual mode, status, `total_kind`, warnings, typo corrections,
judged counts and `rerank_truncated`. Compatibility `matched_count` equals
`total`; interpret it with `total_kind`:

- `library_records`: saved records in a browse scope.
- `lexical_matches`: full keyword match count.
- `retrieval_candidates`: bounded candidates, including fallback.
- `judged_matches`: ranked results above the service cutoff.

Only decisions results get relevance scores. Built-in keyword points are not
probabilities. First use may load models; subsequent requests are usually faster.
The default observation budget is 240 seconds, configurable from 30–300; the
executor adds 30 seconds for cleanup. These are foreground read-only requests,
not background jobs. A timeout can leave inference finishing, but submits no
bookmark mutation. See upstream [search details](https://github.com/bigsk1/bookmark-plus/blob/main/docs/search.md).

### Icons and Web cards

Both backends show clickable titles, full URLs, folders and tags. Plus adds
descriptions and decision scores when available. Private IP/LAN URLs are valid
click targets; Jarvis does not automatically fetch those pages.

Optionally enable **Show website icons via Bitwarden** in the app. Jarvis honors
that preference and displays eligible icons through its authenticated
`/api/bookmarks/plus/{id}/icon?mode=cloud|local` route. The service token stays on
the backend, absent from image URLs/HTML. Missing, disabled or failed icons show
a bookmark placeholder and do not fail search. The proxy serves bounded PNGs
with `no-store` and checks that the selected tool is enabled.

On a cache miss the app sends the **hostname** to Bitwarden/CDN, which may fetch
the site's icon. Private IPs and reserved/local names are skipped. This upstream
feature is an external lookup; leave it off to avoid that disclosure. Jarvis does
not enable the preference or bulk-fetch icons outside displayed results. See
upstream [icon privacy](https://github.com/bigsk1/bookmark-plus/blob/main/docs/icons.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Unavailable tool | Mode's selector, URL/token, profile/Web block; resync/restart after switching |
| Wrong library | Selected cloud/local mode and its endpoint; libraries are independent snapshots |
| TLS failure | CA readable on Jarvis/container, hostname/IP certificate match; keep verification on |
| 401/403 | Token validity and canonical-vs-legacy precedence; app exclusions |
| Redirect rejected | Final `/api/v1` URL, protocol and port; bearer requests do not follow redirects |
| Slow/timeout | Cold models, index status, observation budget; try hybrid/text or lower app judging budget |
| Weak natural-language search | Index coverage and sparse metadata; compare text/hybrid/ranked |
| No ranked results | Cutoff, judged count, truncation, filters; hybrid shows unjudged candidates |
| Unsupported response | Upgrade to the documented status/count API; Jarvis does not invent semantics |
| Missing icon | Owner setting, eligible hostname, current Jarvis login, enabled tool, upstream cache/network |

The adapter ignores implicit proxy/netrc credentials, confines the bearer to
fixed API routes, and exposes no duplicate MCP server. Restricted child
environments carry only bookmark settings plus shared runtime plumbing.

See [tool management](../../TOOL_MANAGEMENT.md),
[CLI usage](../../../jarvis-cli/README.md), and upstream
[REST API documentation](https://github.com/bigsk1/bookmark-plus/blob/main/docs/api.md).
