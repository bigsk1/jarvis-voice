# Crawl4AI Integration

Jarvis uses a separately hosted Crawl4AI REST service for page text and screenshots.
The integration uses the secured Crawl4AI 0.9.5 API with native Bearer tokens.

## Configuration and authentication

Configure the service in the selected mode file (`config/cloud.env` or
`config/local.env`). For a native-token API deployment:

```bash
CRAWL4AI_URL=https://your-crawl4ai-api.example.com
CRAWL4AI_API_KEY=your-native-api-token
```

Jarvis sends the required API key as `Authorization: Bearer ...`.
Set the same native token as `CRAWL4AI_API_TOKEN`
on the Crawl4AI server; the names on the client and server differ.

Both tools require nonblank `CRAWL4AI_URL` and `CRAWL4AI_API_KEY` to register.
A tool profile or
`BLOCKED_TOOLS` can still disable them. Keep the configured URL at its final
HTTPS origin: authenticated requests refuse redirects. Requests go directly to
the configured service with the explicit `off` proxy policy; destination-page
fetches happen in the remote browser, under the server's network policy.

## Tools and workflow contracts

`crawl_url` POSTs `/crawl` with `urls`, `BrowserConfig`, and `CrawlerRunConfig`
using Crawl4AI's serialized `type`/`params` format. It accepts one public HTTP(S)
URL or a batch of up to 10. Each URL is validated before any request is sent.
Stealth mode, CSS selectors, tag exclusions, page waits and cache settings remain
available.

The result preserves `data.results[]` containing `url`, `markdown`, `title`,
`success`, and optional `extracted_content`, plus `data.count`. Titles use the
server's metadata when there is no top-level title. Failed page results are
excluded and listed in `data.failed_urls`; if none succeeds, the tool fails.
Markdown is limited to 10,000 characters per page. Shortened results explicitly
include `truncated: true` and `original_characters`.

CSS and built-in regex extraction can run without an LLM. Cosine extraction
requires the server's optional model dependencies; the standard image may not
include them. `regex_patterns` selects one or more built-in families: `email`,
`phone`, `url`, `currency`, `date`, `percentage`. Omitting it selects all six;
phone includes international/US formats and date includes ISO/US formats.
Only these family names are accepted. The client sends their combined integer
flags and extracts from markdown, which does not require an HTML content filter.
Extraction failures return an error; Jarvis does not silently retry a structured
request as plain markdown.

JavaScript snippets, LLM extraction, custom regex patterns and queue priority
are not exposed by these tools. The shipped workflows use the supported
API features without server-side code execution or LLM credentials.

`screenshot_url` POSTs `/screenshot` with `url` and `screenshot_wait_for`, accepts
the inline base64 `screenshot`, and saves a local JPEG resized to at most 2000px.
Its result preserves `url`, `screenshot_path`, `size_bytes`, `wait_seconds`, and
optional `analysis`. `analyze: true` uses Jarvis's configured vision provider.
Capture requests time out after 45 seconds; optional vision work still shares
the existing foreground caller's deadline. The default file is temporary;
a workflow can copy it into Stash for durable references.

`deep_dive` requires the screenshot and its vision analysis path; its text crawl
is optional. `deep_research`, `crypto_market_report`, `github_ai_radar_daily`,
`url_ingest` and `web_archive` use the same crawl result envelope. Their
`${article.content}`, title and URL bindings remain supported. None requires
LLM extraction, custom regex or JavaScript snippets on the server.

## Deployment security

Keep API access authenticated over HTTPS. For a dedicated Jarvis API instance,
expose only authenticated POST `/crawl` and POST `/screenshot` through the proxy.
Keep playgrounds, docs, monitor/admin, token creation and job routes unavailable
at that public origin. Avoid a published host port that bypasses proxy rules.

Crawl4AI still registers its bundled MCP, docs and UI routes internally; the
proxy restriction is what makes this deployment API-only from outside Docker.
On Coolify, store custom `config.yml` content as a managed file and mount it
with a read-only bind (`...:/app/config.yml:ro`). Compose can reject an inline
`configs.content` mount in a read-only service after creating the container.
Check the rendered mount: some Coolify parsers drop `read_only` from the long
bind syntax, while the short `:ro` form is preserved.

Jarvis URL checks are a preflight, not a remote network sandbox. The remote
browser resolves names again and may follow redirects or load subresources.
Enforce private-network/metadata restrictions at the Crawl4AI server and its
network boundary too. Do not attach unnecessary provider secrets, host mounts,
Docker sockets or privileged capabilities to the browser container.

The crawl tool uses a restricted child environment containing its service URL
and API token plus common runtime settings. Screenshot capture uses the
selected mode environment because its optional vision path can invoke multiple
provider/auth configurations. That limitation is separate from remote API auth.

## Upgrade verification

Pin the image version or digest and save the deployment configuration before
upgrades. Before cutting over either mode, verify:

- Requests without a token and with a wrong token fail; valid-token crawl and
  screenshot requests succeed.
- UI/docs/admin/token paths and direct host-port access cannot bypass protection.
- Raw markdown, stealth, CSS/regex extraction and inline screenshots match the
  expected contract; test cosine only with its optional dependencies installed.
- `/deep_dive` and a representative research/archive workflow retain their text,
  screenshot and Stash/Canvas outputs.

Focused deterministic coverage:

```bash
.venv/bin/python -m pytest tests/test_crawl4ai_tools.py tests/test_tool_url_security.py tests/test_pipeline_executor.py -q
```

These tests mock the remote service. They establish request and result contracts,
not live browser success or the deployment's authentication and egress rules.
