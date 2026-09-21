# SearXNG search

Jarvis exposes a configurable SearXNG instance as the `searxng_search` tool.
It calls the instance's `/search` endpoint with `format=json`, then returns
bounded source URLs, snippets, engine names, answers, and suggestions. The
same tool works with a reachable local instance or a remote HTTPS instance.
See the [SearXNG Search API](https://docs.searxng.org/dev/search_api).

## Configure an instance

Set `SEARXNG_BASE_URL` in the active mode's ignored `config/cloud.env` or
`config/local.env`. Use the instance root, such as
`https://searx.example.org`; a URL ending in `/search` also works. Do not
include `q`, `format`, credentials, or other query parameters in the setting.
Keep private instance addresses out of the tracked example files.

SearXNG itself does not require an API key for JSON search. The instance must
enable JSON output, and its enabled engines determine coverage. Many public
instances disable JSON. When `SEARXNG_BASE_URL` is absent, the tool is
unavailable in that mode.
The SearXNG `server.secret_key` signs cookies and is not a client API key.
Keys used by individual search engines belong to the SearXNG server.

For an instance behind a reverse proxy, all authentication settings are
optional:

| Setting | Purpose |
| --- | --- |
| `SEARXNG_USERNAME` and `SEARXNG_PASSWORD` | HTTP Basic auth; set both together. |
| `SEARXNG_AUTHORIZATION` | Complete Authorization header value, such as a Bearer scheme; do not combine with Basic auth. |
| `SEARXNG_HEADER_NAME` and `SEARXNG_HEADER_VALUE` | One additional custom proxy header; set both together. |

Use HTTPS when sending credentials to a remote instance. SearXNG engine
tokens are preferences, not HTTP authentication; this tool does not set them.
The manifest's restricted child environment passes the configured base URL
and these optional settings, without unrelated mode credentials. This limits
accidental environment inheritance; it is not a filesystem sandbox.

## Probe and use

After setting the active mode, check the JSON endpoint from this host:

~~~bash
JARVIS_MODE=local "$HOME/jarvis-venv/bin/python" skills/searxng_search.py --probe
~~~

The probe performs one search and reports readiness without returning source
content. A 403 without an authentication challenge usually means JSON is
disabled or access is denied. A 401 or 403 with `WWW-Authenticate` points to
front-door auth. A 429 means the instance limiter or rate limit rejected the
client. The tool sends a browser-style User-Agent, but public instances may
still restrict automated requests.

Example chat requests:

~~~text
Use SearXNG to find recent Linux kernel release notes.
Search SearXNG news for open source browser updates from this week.
~~~

`query` is required. Optional `categories`, `language`, `page`,
`time_range`, and `safesearch` are sent to the instance. Time and safe-search
filters work only where its engines support them. `max_results` caps the
results returned to Jarvis at 20; it does not limit how many results SearXNG
collects. Source text is marked untrusted, and Jarvis Web shows clickable
source cards with engine attribution.

To make the tool discoverable after configuration, restart Jarvis and run Tool
RAG sync with the legacy operator environment specified in the repository
AGENTS.md. The tool uses direct HTTP to the configured host; ensure that host
is reachable from the Jarvis process or container.
