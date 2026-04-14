# HTTP proxy configuration (`LOCAL_PROXY` / `LOCAL_PROXY2`)

Some networks block direct outbound HTTPS. Jarvis supports an **ordered proxy chain** for tools that use shared HTTP helpers or subprocess-based downloaders.

## Observability

`lib/http_client.py` emits grep-friendly lines to **stderr** and the `http_client` logger, for example:

- `[HTTP] proxy_used=true proxy_slot=LOCAL_PROXY proxy=http://user:****@host:8888 url=https://...`
- `[HTTP] proxy_used=false direct=fallback_after_proxy_failed url=...` after the proxy chain fails and direct fallback succeeds
- With **no** proxy configured, `proxy_used=false` is logged at **DEBUG** only (to avoid noise). Set **`JARVIS_HTTP_LOG_DIRECT=true`** in env to log `direct=no_proxy_config` at **INFO** as well.

`get_session()` prints a one-line `[HTTP] proxy_used=true ... session=1` when a sticky session uses the primary proxy.

## Environment variables

Set these in `config/cloud.env` or `config/local.env` (whichever mode you run). Only non-empty values take part in the chain.

| Variable | Role |
|----------|------|
| `LOCAL_PROXY` | Primary HTTP/HTTPS proxy URL (e.g. `http://user:pass@host:8888`). |
| `LOCAL_PROXY2` | Optional fallback if the primary fails. |
| `JARVIS_HTTP_LOG_DIRECT` | When `true` / `1` / `yes`, log **`proxy_used=false`** `direct=no_proxy_config` at INFO when no proxy is configured (otherwise DEBUG only). |

**Direct-only:** If both are unset or commented out, Jarvis does **not** configure application-level proxies for the paths below; requests use normal host networking (no `proxies=` from these vars).

**Note:** If the OS or shell already exports global `HTTP_PROXY`/`http_proxy`, some libraries may still honor those independently of Jarvis. Jarvis’s own helpers primarily use explicit `proxies` from config via `lib/http_client.py`.

## Behavior (`lib/http_client.py`)

Central API: **`http_request()`**, **`get_proxy_chain()`**, **`get_proxy_config()`**, **`get_proxy_url_chain()`**.

1. **Order:** Try `LOCAL_PROXY`, then `LOCAL_PROXY2`, then (when `fallback_on_proxy_fail=True`) **direct** connection.
2. **Failures that advance the chain:**
   - **`requests`** raises (`ConnectionError`, timeouts, many `ProxyError`s, etc.).
   - **Tunnel-style HTTP responses** without a raised exception: **407**, **502**, **503**, **504** (common when a proxy returns an error to the HTTPS `CONNECT` instead of connecting upstream).
3. **`get_proxy_config()`** returns a **single** proxy dict (first non-empty of `LOCAL_PROXY`, then `LOCAL_PROXY2`) for callers that need one sticky setting, e.g. `get_session()`.
4. **`get_proxy_url_chain()`** returns ordered URL strings for tools that pass a proxy to **yt-dlp** (`--proxy`).

## What uses this

| Area | Mechanism |
|------|-----------|
| Weather, SerpApi helpers, stash URL downloads, crypto/HTTP-using paths | `http_request()` → full chain + tunnel status handling |
| **yfinance** (`skills/stock_price.py`) | Sets `http_proxy` / `https_proxy` env per proxy in order, then clears and retries direct on tunnel-style failures |
| **GitHub** (`skills/git_release_notes.py`) | Session GETs with each proxy in chain, then direct |
| **yt-dlp** (`youtube_video`, `youtube_transcript`) | Tries each URL from `get_proxy_url_chain()` in order |

## MCP / browser `--proxy-server`

`config/mcp-servers.json` may reference **`${LOCAL_PROXY}`** for a **single** Chromium-style `--proxy-server` argument. That expansion does **not** walk `LOCAL_PROXY2`. Put your preferred upstream on `LOCAL_PROXY` for MCP/browser traffic; use `LOCAL_PROXY2` for the Python/yt-dlp stack when the primary proxy is unreliable.

## Related

- Examples in `config/cloud.env.example` and `config/local.env.example` (Proxy section).
- Tool Builder proxy patterns: [`docs/TOOL_BUILDER.md`](TOOL_BUILDER.md) (Network/Proxy section).
- Video / yt-dlp: [`docs/tools/video/README.md`](tools/video/README.md).
