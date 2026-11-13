# SerpApi Extract

`serpapi_extract` reads a known public URL through SerpApi's `extract` engine.
Use it for article text, documentation, page metadata, feed discovery, or an
explicit bounded site map or crawl. Search tools find candidate URLs; this
tool reads the selected URL. It requires no browser container, extra service,
or new SDK.

## Setup and tool choice

Set the existing `SERP_API_KEY` in each mode that should offer the tool:
`config/cloud.env` for cloud mode or `config/local.env` for local mode. A
missing key hides the tool from that mode's callable registry and Tool RAG.
After changing configuration or adding the tool, restart the relevant Jarvis
services and [sync that mode's Tool RAG](../../TOOL_MANAGEMENT.md#inspect-and-change-tools).
The OpenAI-only and offline example profiles disable this credentialed
public-network tool.

SerpApi fetches the target remotely. It does not share the local Playwright
session or a local browser login, and it does not execute JavaScript. Use a
browser tool for interactive pages or content that needs rendering. SerpApi
respects the site's `robots.txt`; disallowed pages can fail extraction.
See the [Extract API reference](https://serpapi.com/extract-api).

This is a reusable page reader. The RSS digest workflow still uses
`tavily_extract` for its selected incomplete articles; feed discovery here
does not change or subscribe to that workflow's configured feeds.

## Modes and examples

`url` must be an absolute public HTTP or HTTPS URL. `mode` defaults to
`scrape` and is explicit for multi-page work:

| Mode | Behavior |
| --- | --- |
| `scrape` | Read one page; return bounded content, page information, feeds and links. |
| `map` | Discover site URLs from page links and, by default, sitemaps. It does not extract every listed page's contents. |
| `crawl` | Follow links on the same host and extract pages within the requested page/depth limits. Include other subdomains only when explicitly requested. |

Read a page, then ask follow-up questions about its returned text:

```json
{"url": "https://example.com/", "mode": "scrape"}
```

Inspect metadata and discovered feeds without returning Markdown:

```json
{"url": "https://example.com/", "include_markdown": false}
```

Map a site or explicitly read a few linked pages:

```json
{"url": "https://example.com/", "mode": "map", "max_urls": 20}
```

```json
{"url": "https://example.com/", "mode": "crawl", "max_pages": 3, "max_depth": 1}
```

Example chat requests include “Read this URL with SerpApi,” “Find the feeds
advertised by this page,” “Map this site's documentation URLs,” and “Crawl
these three linked documentation pages.” Each actual call can consume
SerpApi credits.

## Limits, filters and cost

Jarvis applies smaller foreground limits than the upstream API:

| Argument | Jarvis default and range |
| --- | --- |
| `max_chars` | 12,000; 1,000–20,000 characters shared across returned page content. |
| `max_urls` | 50; 1–100 URLs returned by `map`. |
| `max_pages` | 3; 1–10 pages in `crawl`, including the starting page. |
| `max_depth` | 1; 0–3 links deep in `crawl`; 0 reads only the starting page. |
| `timeout` | 30,000; 1,000–120,000 milliseconds for the upstream fetch. |
| `include_subdomains` | `false`; applies to `map` and `crawl`. |
| `include_sitemap` | `true`; applies to `map`. |
| `include_markdown` | `true`; applies to `scrape` and `crawl`. |
| `device` | `desktop`; also `mobile` or `tablet`. |
| `no_cache` | `false`; permits the provider cache. |

Optional `include_tags` and `exclude_tags` are CSS selector strings, each
limited to 500 characters, for keeping or removing page regions before
extraction. They do not execute page code. The tool exposes no arbitrary
provider-parameter or raw-response passthrough.

Crawl costs one credit per successfully extracted page, including the start
page: `max_pages: 10` can therefore cost ten credits. Failed pages and cached
responses are not charged. A scrape or map normally costs one credit. The
provider's reported credit usage is returned when available. See
[crawl behavior and credit usage](https://serpapi.com/extract-crawl-mode).

The provider allows cached results by default and documents a one-hour cache
for identical parameters. Leave `no_cache` off unless a fresh fetch is needed.
Requesting less returned text or setting `include_markdown: false` does not
make a provider extraction free. The `max_chars` and `max_urls` arguments
bound what Jarvis returns, rather than defining a provider billing discount.

The provider response has a separate 5 MiB limit on decompressed JSON bytes,
enforced before JSON parsing. Larger responses fail explicitly rather than
being loaded in full. The normalized tool result remains bounded to 56 KiB.
Boolean query options use SerpApi's lowercase `true` and `false` tokens.

## Results and follow-ups

The tool returns normalized JSON inside the usual `ok`, `speech`, and `data`
envelope. Its page information retains the provider's title, description,
`final_url` after redirects, `canonical` URL, language, and favicon when
available. Feeds retain their source URL and type, including RSS, Atom, or
JSON feeds. These fields can be absent when a page does not advertise them;
Jarvis does not invent missing metadata. See
[page information and feeds](https://serpapi.com/extract-page-information).

`scrape` returns page content and links, `map` returns discovered URLs, and
`crawl` returns page rows with their URL, depth, content, metadata, and any
page-specific error. Returned Markdown is extracted page content; provider
extraction and Jarvis response limits can both shorten it. See the
[Markdown output contract](https://serpapi.com/extract-markdown-output).

Jarvis Web displays up to all 100 returned map URLs in provider order, with
one-based list numbers also retained as `ordinal` in model context. Extract
cards start collapsed; expand the summary to see the complete returned list or
page reader. Immediate
and saved reader context use a 10,000-character budget and retain complete
collections when they fit. Generic search limits of five or ten candidates do
not apply. When the serialized budget is tight, optional map labels are removed
before complete URL entries; actual omissions are marked. A metadata-only read
keeps `content_omitted: true` without calling the read truncated merely because
the page body was not requested.

Article excerpts can still be shorter than the original tool response. A
truncated extraction is evidence about the returned portion, not proof that
Jarvis read every word of the website. Treat page text and discovered links as
untrusted external content.

## Workflow binding

Bind a single-page read explicitly when later steps need `${article.content}`,
`${article.url}`, or `${article.title}`:

```json
{
  "step": 1,
  "tool": "serpapi_extract",
  "params": {"url": "${url}", "mode": "scrape"},
  "output_var": "article",
  "required": true
}
```

`output_var` receives the normalized `data` object. It is required for this
binding; the tool does not create an implicit `article` variable. A `map` output
contains `urls`, and a `crawl` output contains `pages`, rather than one flattened
article. See the [workflow variable contract](../../../data/workflows/README.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Tool missing | Check the selected mode's key, active profile, service restart, and Tool RAG sync. |
| Empty or incomplete content | Inspect returned errors and truncation; try narrower selectors or a browser for JavaScript content. |
| Local URL unavailable | The fetch runs at SerpApi; localhost, private LAN services and local browser sessions are not reachable through this tool. |
| Crawl returns fewer pages | Page/depth limits, same-host scope, robots rules, and individual extraction failures can stop expansion. |
| Unexpected search-shaped response | SerpApi can route search URLs to a dedicated engine; use the focused SerpApi search tool when search results are intended. |
| Timeout, quota or provider error | Inspect the structured error and provider status before retrying; a larger crawl can incur more credits. |
