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

`OLLAMA_CLOUD_MODEL` must be cloud-tagged. Jarvis recognizes both forms used by
Ollama:

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

## Local mode

Configure `config/local.env`:

```bash
LLM_PROVIDER=ollama
OLLAMA_BASE_URL="http://your-local-gpu-host:11434"
OLLAMA_MODEL="qwen3:latest"
EMBEDDING_PROVIDER=ollama
```

The local Settings UI lists non-cloud models returned by the configured daemon.
`OLLAMA_MODEL` is expected to name a model installed on that daemon. Jarvis keeps
localhost as the final fallback in local mode for backward compatibility.

Local deployment mode does not technically make cloud-tagged models impossible:
model execution class is deliberately separate from data mode. The supported
default is nevertheless a non-cloud `OLLAMA_MODEL`, which keeps inference,
databases, and embeddings local.

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

Phase-one cloud access uses an Ollama daemon signed in with:

```bash
ollama signin
```

Authentication belongs to the Ollama daemon user, not the Jarvis checkout. A
fresh Jarvis clone on the same machine can reuse the signed-in daemon without
copying credentials.

The Web System tab lazily calls the daemon's `POST /api/me` endpoint and exposes
only:

- host reachability;
- signed-in, signed-out, or unknown state;
- account plan when supplied;
- a validated Ollama sign-in link when supplied;
- the official Ollama settings link.

Ollama currently does not expose the session/weekly quota bars through this
endpoint. Jarvis therefore does not fabricate percentages and links to
<https://ollama.com/settings> instead. Malformed or changed `/api/me` responses
are reported as unknown rather than signed in.

Direct `https://ollama.com/api` access using `OLLAMA_API_KEY` is not implemented.
It is a separate topology and is never selected as an automatic fallback.

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

Run the focused regression suites:

```bash
source /home/boss/jarvis-venv/bin/activate
pytest -q \
  tests/test_scoped_config.py \
  tests/test_ollama_cloud_primary.py \
  tests/test_ollama_provider_usage.py \
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
- provider `ollama` and the selected cloud-tagged model;
- cloud DB paths and 1536-dimensional embeddings;
- token usage with subscription/unknown cost;
- no localhost fallback in provider diagnostics.

Local Ollama should report:

- `startup_mode=local`;
- provider `ollama` and `OLLAMA_MODEL`;
- local DB paths and 768-dimensional embeddings;
- local `num_ctx` behavior and `$0` local usage.

The detailed architecture and acceptance matrix are retained in
`docs/personal/ollama-cloud-primary-provider-plan.md`.
