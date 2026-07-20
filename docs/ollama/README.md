# Ollama in Jarvis

Status: implemented and regression-hardened on 2026-06-29.

Jarvis supports Ollama in two deployment modes:

| Jarvis mode | Normal Ollama model | Data and embeddings |
|---|---|---|
| `cloud` | `OLLAMA_CLOUD_MODEL`, normally `*:cloud` or `*-cloud` | Cloud Memory/Intelligence DBs and OpenAI embeddings by default |
| `local` | `OLLAMA_MODEL`, normally a model running on your own GPU host | Local DBs and Ollama embeddings by default |

Deployment mode, chat provider, Ollama model execution class, and embedding
provider are separate settings. In particular, `LLM_PROVIDER=ollama` does not
switch Jarvis into local mode.

## Cloud mode with Ollama Cloud

Configure `config/cloud.env`:

```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL="http://your-signed-in-ollama-host:11434"
OLLAMA_CLOUD_MODEL="minimax-m3:cloud"
EMBEDDING_PROVIDER=openai
```

With a signed-in daemon, `OLLAMA_CLOUD_MODEL` must be cloud-tagged. Jarvis
recognizes both forms used by Ollama:

```text
qwen3.5:cloud
gpt-oss:120b-cloud
```

Cloud mode uses only hosts explicitly listed in `OLLAMA_BASE_URL`. It does not
silently append or fail over to localhost. Multiple intentional hosts can be
listed in order:

```bash
OLLAMA_BASE_URL="http://gpu-primary:11434,http://gpu-secondary:11434"
```

Cloud-tagged models:

- use the normal Ollama `/api/chat` protocol;
- omit local `num_ctx` GPU tuning;
- retain reported token counts;
- report subscription/compute billing as unknown rather than `$0`;
- do not receive local-model tool-call correction rewrites.

With `OLLAMA_API_KEY`, the direct API also returns canonical IDs such as
`minimax-m3`, `qwen3.5:397b`, and `gpt-oss:120b`. Jarvis classifies these as
cloud execution from the active transport, so it likewise omits `num_ctx`,
reports cloud billing correctly, and skips local tool-call rewrites.

## Local mode

Configure `config/local.env`:

```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL="http://your-local-gpu-host:11434"
OLLAMA_MODEL="gemma4"
ALLOW_OLLAMA_CLOUD=false
EMBEDDING_PROVIDER=ollama
```

By default the local Settings UI lists non-cloud models returned by the
configured daemon. `OLLAMA_MODEL` is expected to name a model installed on that
daemon. Jarvis keeps localhost as the final fallback in local mode for backward
compatibility.

Set `ALLOW_OLLAMA_CLOUD=true` in `config/local.env` to also show and permit
downloaded cloud-tagged cards. They continue through `OLLAMA_BASE_URL`, require
the daemon user to run `ollama signin`, and do not enable direct API-key access.
The default remains `false`, keeping local inference, databases, and embeddings
local.

## Vision and image analysis

Jarvis routes all image understanding through one shared module:
`lib/vision_provider.py`. That includes:

- Web chat image uploads (SocketIO vision pass before routing)
- Web **Enhance** when an image is attached
- The `analyze_image` tool (voice, CLI, orchestrator)

When `LLM_PROVIDER=ollama`, vision model selection follows **Jarvis mode**, not
the chat/text model variable name alone:

| Jarvis mode | Ollama vision model | Config variable |
|---|---|---|
| `cloud` | The active **cloud** Ollama model | `OLLAMA_CLOUD_MODEL` (or the Web Settings per-mode `llm_model` override when set) |
| `local` | A dedicated **local** vision model | `OLLAMA_VISION_MODEL` (falls back to `OLLAMA_MODEL` if unset) |

**Cloud mode:** multimodal cloud models such as `minimax-m3:cloud` or
`qwen3.5:cloud` are used for vision. Jarvis does **not** use
`OLLAMA_VISION_MODEL` in cloud mode — that variable is for local GPU vision
only.

**Local mode:** set `OLLAMA_VISION_MODEL` to a vision-capable model installed on
your Ollama host (for example `llava:latest`, `llama3.2-vision:latest`, or
`gemma4`). This can differ from `OLLAMA_MODEL` when your main chat model is
text-only or you want a smaller vision model.

Ollama vision requests use the documented `/api/generate` payload with a base64
`images` array. Jarvis does not use a separate vision endpoint. Before explicit
image analysis, it checks `/api/show` when available. If the active model does
not declare the `vision` capability, Web chat reports that the model is
text-only and stops the turn instead of silently passing the question to normal
text chat. The Web UI restores the uploaded image to the composer so the user
can switch to a vision-capable model or provider and resend without uploading
it again.

When cloud/local Web Settings pick a non-Ollama provider (xAI, Anthropic,
OpenAI), vision uses that provider's chat/vision API instead. The
`VISION_MODEL` env pin in `cloud.env` applies to the `analyze_image` tool path
for those providers; Web chat and Enhance prefer the per-mode Web `llm_model`
override when present.

If **Enhance** is run with an attached image but the selected model rejects
image input, Jarvis falls back to conservative text-only enhancement, returns
`vision_grounded: false`, and shows a short UI warning instead of HTTP 500.

## Mode-related configuration reference

| Variable | Valid values / default | Applies to | Notes |
|---|---|---|---|
| `JARVIS_MODE` | `cloud` or `local`; defaults to `cloud` at startup | Launchers, Docker, background services | Selects env/data boundaries; never inferred from `LLM_PROVIDER` |
| `LLM_PROVIDER` | `xai`, `anthropic`, `openai`, or `ollama` | Selected mode config | Chooses chat backend; does not select mode |
| `OLLAMA_MODEL` | Ollama model name | Normally local mode | Required for the primary local Ollama path; local auxiliary calls retain a compatibility fallback |
| `OLLAMA_CLOUD_MODEL` | Cloud card or direct API model ID | Cloud mode with `LLM_PROVIDER=ollama` | Signed-in daemon requires `*:cloud` / `*-cloud`; direct API accepts IDs returned by ollama.com; also used for vision |
| `OLLAMA_VISION_MODEL` | Ollama model name | Local mode with `LLM_PROVIDER=ollama` | Vision/image analysis only; not used in cloud mode (see Vision section above) |
| `ALLOW_OLLAMA_CLOUD` | `false` (default) or `true` | Local mode | When true, permits cloud-tagged cards through the signed-in daemon; never enables direct API routing |
| `OLLAMA_BASE_URL` | One URL or comma-separated URLs | Both configs | Cloud tries only explicit hosts; local retains localhost as a final compatibility fallback |
| `EMBEDDING_PROVIDER` | Commonly `openai` in cloud, `ollama` in local | Memory, Tool RAG, Intelligence | Independent of the chat provider; keep DB dimensions aligned with the selected data mode |
| `JARVIS_SYNC_MODES` | Space-separated `cloud` / `local`; defaults to `JARVIS_MODE` in Docker | First-boot Docker tool sync | Does not change the running stack's mode |

Do not set both model variables expecting automatic mode switching. The active
mode chooses which model variable is resolved.

Check the configured host without making an inference request:

```bash
set -a
source config/local.env
set +a
curl -fsS "${OLLAMA_BASE_URL%%,*}/api/tags" | jq -r '.models[].name'
```

If `OLLAMA_MODEL` is absent from that list, either pull it on the Ollama host or
select an installed non-cloud model.

## Authentication and account status

Cloud-mode Ollama access is **either/or** — never both at once:

| Config | Path | How it works |
|--------|------|--------------|
| No `OLLAMA_API_KEY` | **Signed-in daemon** | `OLLAMA_BASE_URL` → local/remote daemon that ran `ollama signin`; cloud models use `:cloud` tags |
| `OLLAMA_API_KEY` set | **Direct ollama.com API** | Jarvis talks only to `https://ollama.com` with `Authorization: Bearer …`; no daemon required |

### Signed-in daemon (default)

```bash
OLLAMA_BASE_URL="http://your-signed-in-ollama-host:11434"
# Do not set OLLAMA_API_KEY
```

Authentication belongs to the Ollama daemon user, not the Jarvis checkout. Run
`ollama signin` on the daemon host. Jarvis calls the daemon API; the daemon
proxies cloud models to ollama.com.

The Web System tab calls `POST {OLLAMA_BASE_URL}/api/me` and exposes only
reachability, signed-in/signed-out/unknown, plan when supplied, and validated
sign-in links — never raw profile data.

### Direct API key (alternative)

```bash
OLLAMA_API_KEY=your_key_from_ollama_com_settings_keys
OLLAMA_CLOUD_MODEL="qwen3.5:397b"
# OLLAMA_BASE_URL is ignored for cloud-model inference when the key is set
```

Create a key at <https://ollama.com/settings/keys>. When `OLLAMA_API_KEY` is
present and nonblank in cloud mode, Jarvis uses **only**
`https://ollama.com/api/*` with Bearer auth. Model discovery also comes from
ollama.com, not your local daemon list. Like the other provider gates, a
nonblank key is treated as configured; authentication errors surface on use.
The Web Settings list pins any current override and `OLLAMA_CLOUD_MODEL` first,
then orders the remaining direct catalog by Ollama's `modified_at` metadata
newest-first. The empty-value choice names the actual env default explicitly.

Keep an active `OLLAMA_API_KEY=""` assignment when direct access is disabled.
This masks a same-named variable exported by `.bashrc` or another parent
process. A commented `# OLLAMA_API_KEY=` line does not mask inherited values.

Local mode always uses the daemon; `OLLAMA_API_KEY` is ignored there so GPU
inference is unaffected.

Ollama currently does not expose session/weekly quota bars through `/api/me`.
Jarvis links to <https://ollama.com/settings> instead of fabricating percentages.

## Migrating from the older local-only Ollama setup

Existing local installations can keep `LLM_PROVIDER=ollama`, `OLLAMA_MODEL`,
and their local `OLLAMA_BASE_URL` in `config/local.env`; no rename is required.

To add Ollama Cloud without disturbing local mode:

1. Put `LLM_PROVIDER=ollama` in `config/cloud.env`, then configure either a
   signed-in daemon plus cloud-tagged model or `OLLAMA_API_KEY` plus a canonical
   direct API model.
2. Leave the normal GPU-backed `OLLAMA_MODEL` in `config/local.env`.
3. Start cloud and local modes explicitly; do not use provider values to imply
   the mode.
4. Recreate Docker containers after changing root `.env` `JARVIS_MODE`.

A legacy cloud config that placed an already cloud-tagged value in
`OLLAMA_MODEL` remains compatible, but moving it to `OLLAMA_CLOUD_MODEL` makes
the boundary explicit and is the supported configuration going forward.

## Troubleshooting

| Symptom | Check |
|---|---|
| `OLLAMA_CLOUD_MODEL must be a cloud-tagged Ollama model` | The signed-daemon path requires `*:cloud` or `*-cloud`; canonical IDs are accepted only on the direct API-key path |
| `OLLAMA_MODEL is cloud-tagged but ALLOW_OLLAMA_CLOUD is disabled` | Use a local model or set `ALLOW_OLLAMA_CLOUD=true` in `config/local.env` and sign the daemon in |
| `No cloud Ollama model configured` | Add `OLLAMA_CLOUD_MODEL` to `config/cloud.env`; `OLLAMA_MODEL` is only a compatibility fallback when it is already cloud-tagged |
| `No local Ollama model configured` | Add `OLLAMA_MODEL` to `config/local.env` and confirm it appears in `/api/tags` |
| `No Ollama base URLs configured` or connection failures | Check `OLLAMA_BASE_URL`, daemon reachability, and firewall/listen settings |
| Docker cannot reach host Ollama | Use `host.docker.internal`, not container-local `localhost` |
| Cloud host is reachable but inference fails | Run `ollama signin` as the daemon user, verify `/api/me`, and confirm the cloud model is available to that account |
| UI, API, or scheduled task uses the wrong DB/provider | Check startup `JARVIS_MODE`, request/task `mode`, and the matching env file separately |
| Expected logs are missing | Native: inspect the relevant tmux session and `logs/llm-calls-YYYY-MM-DD.jsonl`; Docker: use `docker compose logs jarvis-web jarvis-api jarvis-services` |

## Testing the configured host

Use the configured URL rather than assuming localhost:

```bash
set -a
source config/cloud.env
set +a

OLLAMA_URL="${OLLAMA_BASE_URL%%,*}"

curl -fsS "$OLLAMA_URL/api/tags" | jq -r '.models[].name'

curl -fsS "$OLLAMA_URL/api/show" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg model "$OLLAMA_CLOUD_MODEL" '{model: $model}')"

curl -fsS "$OLLAMA_URL/api/chat" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg model "$OLLAMA_CLOUD_MODEL" '{
    model: $model,
    messages: [{role: "user", content: "Reply with exactly: ready"}],
    stream: false
  }')"
```

The first two commands do not make a chat inference. The final command consumes
Ollama Cloud allowance.

For direct API-key mode, use `https://ollama.com` and include the bearer header:

```bash
curl -fsS https://ollama.com/api/tags \
  -H "Authorization: Bearer $OLLAMA_API_KEY" | jq -r '.models[].name'
```

## Docker

Docker preserves `JARVIS_MODE` and mounts the selected Jarvis config read-only.
Compose also defines `host.docker.internal` on Linux.

When Ollama runs on the Docker host, use:

```bash
OLLAMA_BASE_URL="http://host.docker.internal:11434"
```

When Ollama runs on another LAN machine, use its reachable LAN hostname or IP.
Do not use `localhost:11434` for a host daemon: inside the Jarvis container,
localhost is the container itself.

Validate both Compose modes before starting:

```bash
docker compose config --quiet
JARVIS_MODE=local docker compose config --quiet
```

Then rebuild so the container contains the current provider implementation:

```bash
docker compose up -d --build
```

For the optional MCP-enabled setup, keep using the tracked override described in
`docs/docker/README.md`. Ollama host addressing and mode selection are unchanged
by that override.

## Web overrides and concurrency

Cloud and local Web settings are stored independently. Provider/model values are
passed directly to the Orchestrator. Image, video, TTS, response-style, and word
limit overrides live in a request-local config scope and are explicitly exported
to child tools. They do not mutate the Web process environment.

This matters even on a single-user machine because background feedback,
Completion Guard, local/cloud tabs, and child tools can overlap in time.

## Operational checks

Run the full project suite (optional examples under `docs/` are excluded by
the project pytest configuration):

```bash
source ~/jarvis-venv/bin/activate
pytest -q
```

For a faster provider-focused pass:

```bash
pytest -q \
  tests/test_scoped_config.py \
  tests/test_ollama_cloud_primary.py \
  tests/test_ollama_provider_usage.py \
  tests/test_ollama_aux_routing.py \
  tests/test_ollama_utils.py \
  tests/test_ollama_cloud_status.py \
  tests/test_api_mode_scopes.py \
  tests/test_web_settings_mode.py \
  tests/test_intelligence_mode_cache.py
```

Useful runtime checks:

```bash
./bin/check-embeddings-health.py cloud
./bin/check-embeddings-health.py local
```

Cloud Ollama should report:

- `startup_mode=cloud`;
- provider `ollama` and the selected cloud model (tagged daemon card or canonical direct ID);
- cloud DB paths and 1536-dimensional embeddings;
- token usage with subscription/unknown cost;
- no localhost fallback in provider diagnostics.

Local Ollama should report:

- `startup_mode=local`;
- provider `ollama` and `OLLAMA_MODEL`;
- local DB paths and 768-dimensional embeddings;
- local `num_ctx` behavior and `$0` local usage.

For implementation details, inspect `lib/ollama_utils.py`,
`lib/config_loader.py`, and the focused tests listed above. Private planning
notes under `docs/personal/` are intentionally not part of the public guide.
