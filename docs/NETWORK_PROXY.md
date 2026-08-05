# HTTP proxy configuration (`LOCAL_PROXY` / `LOCAL_PROXY2`)

Some networks block direct outbound HTTPS. Jarvis supports an **ordered proxy
chain** for tools that use shared HTTP helpers or subprocess-based downloaders,
plus per-tool/server `proxy_policy` metadata.

## Observability

`lib/http_client.py` emits grep-friendly lines to **stderr** and the `http_client` logger, for example:

- `[HTTP] proxy_used=true proxy_slot=LOCAL_PROXY proxy=http://user:****@host:8888 url=https://...`
- `[HTTP] proxy_used=false direct=fallback_after_proxy_failed url=...` after the proxy chain fails and direct fallback succeeds
- With **no** proxy configured, `proxy_used=false` is logged at **DEBUG** only (to avoid noise). Set **`JARVIS_HTTP_LOG_DIRECT=true`** in env to log `direct=no_proxy_config` at **INFO** as well.

`get_session()` prints a one-line `[HTTP] proxy_used=true ... session=1` when a sticky session uses the primary proxy.

Every MCP invocation also records credential-free route metadata in its normal
tool-call record under `logs/tools/tool-calls-YYYY-MM-DD.jsonl`:

```json
"proxy": {
  "policy": "prefer",
  "used": true,
  "slot": "LOCAL_PROXY",
  "basis": "mcp_environment"
}
```

The Web UI tool-log details and `check_tool_logs` expose the same fields. A
direct `prefer` call records `"used": false` with
`"direct_reason": "no_reachable_proxy"`. The record never contains the proxy
URL, host, port, username, or password.

For MCP calls, `used` means the server process handling that invocation was
launched with Jarvis-derived conventional proxy variables. This confirms the
configured network route without attempting an extra public-IP lookup for
every call.

## Environment variables

Set these in `config/cloud.env` or `config/local.env` (whichever mode you run). Only non-empty values take part in the chain.

| Variable | Role |
|----------|------|
| `LOCAL_PROXY` | Primary HTTP/HTTPS proxy URL (e.g. `http://user:pass@host:8888`). |
| `LOCAL_PROXY2` | Optional fallback if the primary fails. |
| `JARVIS_HTTP_LOG_DIRECT` | When `true` / `1` / `yes`, log **`proxy_used=false`** `direct=no_proxy_config` at INFO when no proxy is configured (otherwise DEBUG only). |

**Direct-only:** If both are unset or commented out, Jarvis does **not** configure application-level proxies for the paths below; requests use normal host networking (no `proxies=` from these vars).

**Note:** If the OS or shell already exports global `HTTP_PROXY`/`http_proxy`, some libraries may still honor those independently of Jarvis. Jarvis’s own helpers primarily use explicit `proxies` from config via `lib/http_client.py`.

## Per-tool and MCP proxy policy

Native `*.tool.json` manifests and individual entries in
`config/mcp-servers.json` may set:

```json
"proxy_policy": "prefer"
```

| Policy | Behavior |
|--------|----------|
| Omitted / `inherit` | Preserve the tool's existing code-controlled behavior. This is the migration-safe default. |
| `off` | Force direct access. Jarvis suppresses `LOCAL_PROXY*` and conventional proxy variables in native tool subprocesses. |
| `prefer` | Use the configured proxy chain and permit a direct fallback. |
| `require` | Use the configured proxy chain and fail closed; never intentionally retry direct. It also fails immediately if no proxy is configured. |

The field is runtime metadata. It is not included in the function schema shown
to the LLM and cannot be changed by a model tool call.

## Behavior (`lib/http_client.py`)

Central API: **`http_request()`**, **`get_proxy_chain()`**, **`get_proxy_config()`**, **`get_proxy_url_chain()`**.

1. **Order:** Try `LOCAL_PROXY`, then `LOCAL_PROXY2`, then (when `fallback_on_proxy_fail=True`) **direct** connection.
2. **Failures that advance the chain:**
   - **`requests`** raises (`ConnectionError`, timeouts, many `ProxyError`s, etc.).
   - **Tunnel-style HTTP responses** without a raised exception: **407**, **502**, **503**, **504** (common when a proxy returns an error to the HTTPS `CONNECT` instead of connecting upstream).
3. **`get_proxy_config()`** returns a **single** proxy dict (first non-empty of `LOCAL_PROXY`, then `LOCAL_PROXY2`) for callers that need one sticky setting, e.g. `get_session()`.
4. **`get_proxy_url_chain()`** returns ordered URL strings for tools that pass a proxy to **yt-dlp** (`--proxy`).
5. Helper-aware manual clients use the same policy: `off` returns a direct-only
   attempt, `prefer` permits the final direct attempt, and `require` prohibits it.

## What uses this

| Area | Mechanism |
|------|-----------|
| Weather, SerpApi helpers, stash URL downloads, crypto/HTTP-using paths | `http_request()` → policy-aware chain + tunnel status handling |
| **yfinance** (`skills/stock_price.py`) | Sets `http_proxy` / `https_proxy` env per proxy in order, then clears and retries direct on tunnel-style failures |
| **GitHub** (`skills/git_release_notes.py`) | Session GETs with each proxy in chain, then direct |
| **yt-dlp** (`youtube_video`, `youtube_transcript`) | Tries each URL from `get_proxy_url_chain()` in order |

Tools without `proxy_policy` keep these existing behaviors. Adding a policy is
only necessary when a tool needs to override its current default.

All shipped SerpApi-backed tools, including `flight_search`, explicitly use
`proxy_policy: "off"` so their normal Jarvis execution is direct and
consistent. Their requests still use the shared proxy-aware helpers. Changing
one manifest to `inherit` restores that tool's normal configured proxy chain;
`prefer` forces proxy-first with direct fallback, and `require` fails closed.

## MCP proxy translation

An MCP stdio subprocess receives only variables declared in its `env` object.
Jarvis intentionally does **not** copy the full host environment.

When an MCP entry explicitly sets `proxy_policy` to `prefer` or `require`,
Jarvis makes one narrow exception: it resolves only `LOCAL_PROXY` and
`LOCAL_PROXY2`, performs a short TCP reachability check in that order, and
derives the conventional `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` variables
(plus lowercase equivalents) from the first reachable URL. Docker MCP entries
receive only those derived names through explicit `docker run -e NAME`
arguments. The container does not receive `LOCAL_PROXY`, `LOCAL_PROXY2`, or
unrelated API keys/secrets.

Conventional proxy variables accept one active upstream, not a failover list.
Jarvis therefore:

1. Checks `LOCAL_PROXY`, then `LOCAL_PROXY2`, before starting the MCP server.
2. Rechecks the selected listener before each MCP tool call.
3. Restarts the MCP server and reselects the chain immediately when that
   listener is unavailable, avoiding the upstream client's normal 30-second
   connect timeout.
4. Starts direct when none is reachable under `prefer`; `require` fails closed.

This fast check verifies listener reachability. If a proxy accepts TCP but
cannot relay a particular destination, the upstream MCP client's request
timeout can still apply.

DuckDuckGo is the shipped example:

```json
{
  "duckduckgo": {
    "command": "docker",
    "args": [
      "run", "-i", "--rm",
      "ghcr.io/nickclyde/duckduckgo-mcp-server:0.6.0"
    ],
    "env": {
      "DDG_REGION": "us-en",
      "DDG_SAFE_SEARCH": "STRICT"
    },
    "proxy_policy": "prefer",
    "enabled": true
  }
}
```

DuckDuckGo v0.6 uses the standard proxy variables for outbound traffic. Its
`DDG_CA_CERTS` option is only needed when the proxy re-signs TLS with a private
CA; do not disable TLS verification to configure an ordinary VPN-style proxy.

## Browser `--proxy-server`

`config/mcp-servers.json` may reference **`${LOCAL_PROXY}`** for a **single**
Chromium-style `--proxy-server` argument. That direct argument expansion does
**not** walk `LOCAL_PROXY2`; use `proxy_policy` for MCP servers whose own HTTP
clients honor conventional proxy environment variables.

## Related

- Examples in `config/cloud.env.example` and `config/local.env.example` (Proxy section).
- Tool Builder proxy patterns: [`docs/TOOL_BUILDER.md`](TOOL_BUILDER.md) (Network/Proxy section).
- Video / yt-dlp: [`docs/tools/video/README.md`](tools/video/README.md).
