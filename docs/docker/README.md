# Jarvis Docker Guide

Run Jarvis **Web UIs, API, and background services** in Docker on your own machine. This is a **local build** workflow (`docker compose build`) — there is no published image on Docker Hub.

For architecture notes, networking deep-dives, and the original design doc, see **[DOCKER_PLANNING.md](../archive/docker/DOCKER_PLANNING.md)**.

---

## What Docker covers

| In Docker | On the host (native) |
|-----------|----------------------|
| Main chat Web UI (`:5001`) | Wake word / `./jarvis` voice loop |
| API (`:8880`, localhost bind) | OpenCode server |
| Canvas, Memory, Intelligence, Docs UIs | Spotify OAuth, SSH tools, host shell |
| Background daemons (reminders, follow-up, scheduled tasks) | Tools that need host hardware or OAuth |

**Hybrid use is supported:** run Web UIs in Docker, use wake word or CLI natively when you need them. Stop native tmux services first so you do not run two stacks against the same `./data` and `./logs`.

Host-only tools (Spotify, phone, printer, OpenCode, etc.) are disabled by the tracked **`docker`** tool profile. Re-enable individual tools in `skills/profiles/docker.json` only if you wire up the host integration.

---

## Prerequisites

- Docker Engine + Docker Compose v2
- Git clone of this repo with `config/cloud.env` and/or `config/local.env` configured (same as native install)
- Existing `./data` databases are reused via bind mounts — nothing is wiped on container recreate
- `./jarvis-intel` is shared across API, Web, Memory, and Intelligence containers, so Web profile edits and ingestion operate on the same files
- Web status-only TTS audio is cached under `./data/cache/status-tts-web/`, so repeated phrases can be reused after a container rebuild or recreation

---

## Quick start

```bash
cd ~/jarvis-voice

# One-time host prep (gitignored paths — Compose will not create the settings file)
# Cloud mode defaults to OpenAI and also requires the configured Ollama embedding daemon.
cp config/cloud.env.example config/cloud.env
# cp config/local.env.example config/local.env   # local/Ollama mode instead
mkdir -p audio jarvis-web/data/uploads
cp -n jarvis-web/config/web_config.json.example jarvis-web/config/web_config.json

# Compose settings (ports, UID, mode) — no API keys here
cp docker.env.example .env
printf "JARVIS_DOCKER_UID=%s\nJARVIS_DOCKER_GID=%s\n" "$(id -u)" "$(id -g)" >> .env
```

`docker-compose.yml` defines seven services. Four start with the default command; three more need the **`extras`** profile.

| Service | Default `up` | `--profile extras` | Role |
|---------|:------------:|:------------------:|------|
| `jarvis-api` | yes | yes | FastAPI, webhooks, workflows (`:8880`, localhost bind) |
| `jarvis-web` | yes | yes | Main chat UI (`:5001`) |
| `jarvis-canvas` | yes | yes | Canvas viewer (`:8890`) |
| `jarvis-services` | yes | yes | Background daemons — reminders, follow-up, scheduled tasks, self-healing |
| `jarvis-memory` | — | yes | Memory browser UI (`:5002`) |
| `jarvis-intelligence` | — | yes | Intelligence dashboard (`:5003`) |
| `jarvis-docs` | — | yes | Docs reader (`:5004`) |

```bash
# Edit config/cloud.env (or local.env) with provider credentials, and edit .env with mode, tool profile, and UID/GID, then build
docker compose build

# Core stack: API, Web UI, Canvas, background daemons
docker compose up -d
```

```bash
# Optional but recommended: also start Memory, Intelligence, and Docs UIs
# (re-run after the core stack is already up — no rebuild needed)
docker compose --profile extras up -d
```

Or bring everything up in one step:

```bash
docker compose --profile extras up -d
```

Open from your browser:

| Service | URL |
|---------|-----|
| Web UI | `http://<host-ip>:5001` |
| Canvas | `http://<host-ip>:8890` |
| Memory | `http://<host-ip>:5002` (extras profile) |
| Intelligence | `http://<host-ip>:5003` (extras profile) |
| Docs | `http://<host-ip>:5004` (extras profile) |
| API | `http://127.0.0.1:8880` on the Docker host only |

Check status:

```bash
docker compose ps
docker compose logs -f jarvis-web
curl -fsS http://127.0.0.1:8880/api/health
```

Stop (containers stop; data on disk stays):

```bash
docker compose down
```

Rebuild after code or dependency changes:

```bash
docker compose build
docker compose up -d --force-recreate
```

### Pulling updates from Git

The image contains the app code (`COPY . /app` in `Dockerfile`). Bind mounts are for live config and runtime state: `config/*.env`, `data/`, `logs/`, `audio/`, Web UI settings, and uploads.

After changing only bind-mounted config or runtime files, recreate containers without rebuilding:

```bash
docker compose up -d --force-recreate
```

After pulling code, frontend, route, tool, script, Dockerfile, or dependency changes, rebuild the image:

```bash
docker compose down
git pull
docker compose build --pull
docker compose up -d --force-recreate
```

If the change adds or modifies tools, refresh Tool RAG after the stack is up:

```bash
docker compose exec jarvis-api python bin/sync-tools.py cloud --force
docker compose exec jarvis-api python bin/sync-tools.py local --force
```

For an MCP stack, keep `JARVIS_DOCKER_TOOL_PROFILE=docker` in root `.env` and
run discovery through the MCP-capable `jarvis-web` startup path instead of
`jarvis-api`:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml exec -T jarvis-web rm -f data/.docker_tool_profile_synced
docker compose -f docker-compose.yml -f docker-compose.mcp.yml up -d --force-recreate jarvis-web
```

---

## Configuration files

Two layers — do not mix them up:

| File | Purpose |
|------|---------|
| **`.env`** (repo root) | Docker Compose only: ports, `JARVIS_MODE`, tool profile, UID/GID, `JARVIS_DOCKER_API_AUTH`. No secrets. |
| **`config/cloud.env`** / **`config/local.env`** | Jarvis runtime: API keys, LLM provider, `JARVIS_API_KEY`, Ollama URLs, etc. Bind-mounted read-only into containers. |

Compose mounts the `config/` directory read-only and validates only the file
selected by `JARVIS_MODE`. A local-only checkout therefore needs
`config/local.env` but does not need an empty `config/cloud.env` placeholder.

Mutable price-alert thresholds live in `data/price-alerts.yaml`, which Jarvis
creates from tracked `data/price-alerts.yaml.example` on first use; the base
stack already mounts that directory read-write. The Web tool and API therefore
share the same file without an additional Compose override. MCP still uses its
optional override:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml up -d
```

This leaves env files, `ssh.json`, and the rest of `config/` read-only.

### `JARVIS_MODE` vs `JARVIS_SYNC_MODES`

- **`JARVIS_MODE`** — which stack runs (`cloud` or `local`). Set in `.env`.
- **`JARVIS_SYNC_MODES`** — optional; controls which DBs get `sync-tools.py` on first container boot. If omitted, sync follows `JARVIS_MODE`.

For normal use, set only:

```env
JARVIS_MODE=cloud
```

Every container, including Canvas, Memory, Intelligence, and Docs, uses this
startup mode and reports it as `startup_mode` from its health/status endpoint.

Use `JARVIS_SYNC_MODES="cloud local"` only if you want both tool databases synced on first bring-up while running one mode day-to-day.

### Ollama: local models vs Ollama Cloud

Ollama does not select Jarvis mode. The root `.env` value `JARVIS_MODE`
selects the config/database boundary; `LLM_PROVIDER=ollama` in that selected
config chooses Ollama as the chat backend.

| Docker mode | Config | Model variable | Ollama host |
|---|---|---|---|
| `local` | `config/local.env` | `OLLAMA_MODEL` (normal local model) | Host/LAN daemon, commonly `http://host.docker.internal:11434` |
| `cloud` | `config/cloud.env` | `OLLAMA_CLOUD_MODEL` (`*:cloud` or `*-cloud`) | Reachable daemon signed in with `ollama signin` |

Do not use `localhost:11434` for an Ollama daemon running on the Docker host;
inside a Jarvis container, localhost is the container. Cloud mode uses only the
hosts explicitly listed in `OLLAMA_BASE_URL` and does not silently append a
localhost fallback. See [Ollama in Jarvis](../ollama/README.md) for setup and
diagnostics.

### Tool profile

Compose uses `JARVIS_DOCKER_TOOL_PROFILE=docker` by default. The profile file **`skills/profiles/docker.json`** is git-tracked and baked into the image as a safe baseline for current container limitations.

For a hybrid setup where native wake word, CLI, and TUI should retain every tool, set:

```env
JARVIS_DOCKER_TOOL_PROFILE=default
```

Then use **Web UI Settings → Tools** to block Spotify, printer, host MCP, OpenCode, or other tools that do not yet work inside the Web UI container. The Web UI `tools.blocked` list applies only to Web UI chat; native terminal, TUI, and wake-word flows keep the full `default` tool surface.

This is a layered system:

1. `*.tool.json` provides the base enabled state.
2. `JARVIS_DOCKER_TOOL_PROFILE` selects a Tool RAG profile for the running stack.
3. Web UI `tools.blocked` removes tools only from Web UI requests.

The `docker` profile remains the safer choice when all requests execute inside containers. The `default` plus Web UI blocklist approach is useful for hybrid operation, but direct API/tool execution outside Web UI does not receive that Web UI-only blocklist.

### Optional Docker MCP tools

Brave Search and Fetch in `config/mcp-servers.json` are stdio MCP servers launched with `docker run`. The normal Jarvis image intentionally has neither the Docker CLI nor access to the host daemon. Use the opt-in Compose override to enable them:

Keep root `.env` set to `JARVIS_DOCKER_TOOL_PROFILE=docker`. The MCP override
changes only `jarvis-web` to `docker-mcp`; do not set `docker-mcp` as the
stack-wide profile because the API and other base services do not have the
Docker CLI or socket.

```bash
# Add the host Docker socket group to root .env (one time).
# Linux native shell:
printf 'JARVIS_DOCKER_SOCKET_GID=%s\n' \
  "$(stat -c '%g' /var/run/docker.sock)" >> .env
```

On **Windows (PowerShell)**, **macOS**, or any host without GNU `stat`, use the same socket path Compose mounts:

```powershell
$gid = docker run --rm -v /var/run/docker.sock:/var/run/docker.sock alpine stat -c '%g' /var/run/docker.sock
Add-Content -Path .env -Value "JARVIS_DOCKER_SOCKET_GID=$gid"
```

Optional on Windows with Docker Desktop’s WSL 2 backend: `wsl stat -c '%g' /var/run/docker.sock`

**Pull MCP sidecar images before first start.** Enabled stdio servers in `config/mcp-servers.json` use `docker run` from inside `jarvis-web`. Missing images are skipped during tool sync (logged as unavailable — same as disabled for Tool RAG). The Web UI still starts, but Docker init withholds its completed-sync marker so recreating `jarvis-web` retries Tool RAG sync after the images become available. Pull each image for enabled servers so discovery succeeds on first boot:

```bash
docker pull mcp/fetch
docker pull mcp/brave-search
# Add any other enabled server images from mcp-servers.json "args"
```

The MCP override sets `JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE=docker` and `JARVIS_DEFER_TOOL_SYNC=1` on **all** Jarvis services. Only **`jarvis-web`** additionally gets the Docker CLI/socket mount and `docker-mcp` profile. Combine both compose files with **`--profile extras`** the same way as a normal bring-up.

```bash
# Build (jarvis-web uses the MCP image target; other services unchanged)
docker compose -f docker-compose.yml -f docker-compose.mcp.yml build

# APIs + all Web UIs (extras), no background daemons — same scope as the quick-start UIs-only command
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d \
  jarvis-api jarvis-web jarvis-canvas jarvis-memory jarvis-intelligence jarvis-docs

# Full stack including jarvis-services (reminders, scheduled tasks, self-healing)
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d

# Confirm Docker access and MCP discovery from jarvis-web
docker compose -f docker-compose.yml -f docker-compose.mcp.yml \
  exec -T jarvis-web docker version
docker compose -f docker-compose.yml -f docker-compose.mcp.yml \
  exec -T jarvis-web ./bin/test-mcp --discover
```

The override selects the tracked `docker-mcp` profile. It enables configured MCP tools while keeping `docker_control`, host shell, SSH, Spotify, printer, phone, and OpenCode disabled. The base Compose file already mounts the full `config/` directory read-only, so server configuration changes do not require rebuilding the image; recreate `jarvis-web` after changing `config/mcp-servers.json`.

Remote MCP servers configured with `"type": "http"` or `"type": "sse"` do not need Docker socket access. Use a Compose service URL such as `http://my-mcp:PORT/mcp` for a server on `jarvis-net`, or `http://host.docker.internal:PORT/mcp` for a server running directly on the Docker host.

`/var/run/docker.sock` is effectively root-level control of the Docker host. Use this only on a trusted single-user machine with MCP images you trust. The socket is mounted only into `jarvis-web`; the API, background daemons, and other UIs do not receive it. Ordinary `docker compose up` remains socket-free.

To return to the standard image and profile:

```bash
docker compose up -d --build --force-recreate jarvis-web
```

---

## Native install vs Docker

### Reminder and alert speech

Docker sets `JARVIS_DEPLOYMENT=docker`. Jarvis Web forwards proactive reminder
and alert events to browser TTS only in that deployment mode, because the
container normally cannot play through the host speaker. Keep the Web tab open,
enable its audio control, and interact with the tab once if the browser blocks
autoplay.

Native installs keep the existing background-daemon → host-speaker path and do
not repeat proactive speech in the browser. This avoids double audio in hybrid
setups. See [MAC-WINDOWS.md](MAC-WINDOWS.md#proactive-speech-reminders-and-alerts)
for browser caveats and safe test requests.

**Before starting Docker**, stop native Jarvis:

```bash
./bin/start --stop
./bin/jarvis-services --stop
```

**Do not** run the native watchdog cron while Docker is up. If you installed it from the install guide, comment it out:

```bash
crontab -e
# */5 * * * * $HOME/jarvis-voice/bin/watchdog-services.sh >> ...
```

The watchdog reads `logs/self_healing_daemon.pid`. Docker uses `logs/docker/*.pid` instead, but a stale native cron entry will still spawn host daemons and cause duplicate reminders and TTS crash announcements.

---

## API authentication (`JARVIS_DOCKER_API_AUTH`)

On native installs you may have `JARVIS_API_AUTH=true` in `config/cloud.env`. Docker defaults auth to **off** via compose:

```yaml
JARVIS_OVERRIDE_JARVIS_API_AUTH: "${JARVIS_DOCKER_API_AUTH:-false}"
```

That override wins over `cloud.env` inside containers. First-time Docker bring-up keeps internal traffic simple while you validate the stack.

**To enable auth in Docker:**

1. Set `JARVIS_API_KEY` in `config/cloud.env` (or `local.env`) — required; auth disables itself if the key is missing.
2. Set in root `.env`:
   ```env
   JARVIS_DOCKER_API_AUTH=true
   ```
3. Recreate containers: `docker compose up -d --force-recreate`

Internal services (`jarvis-web`, background daemons) already call the API with `get_internal_api_headers()` and send `Authorization: Bearer …` when auth is on.

**What still works without a token:**

- Health checks inside the API container (`127.0.0.1`)
- Host scripts calling `http://127.0.0.1:8880` (localhost is whitelisted)
- Browser traffic through `jarvis-web` (proxied server-side with auth headers)

**What needs a token when auth is on:**

- Remote webhooks posting to the API from another machine (API is bound to `127.0.0.1` by default — expose via reverse proxy or change the bind if needed)
- Any external client that is not localhost

---

## Services and restart policy

All services use `restart: unless-stopped`. If Docker is running, you intend the stack to stay up; stop with `docker compose down` when you are done.

| Compose service | Role |
|---------------|------|
| `jarvis-api` | FastAPI, webhooks, workflows |
| `jarvis-web` | Main chat UI |
| `jarvis-canvas` | Canvas viewer |
| `jarvis-services` | Reminder, follow-up, scheduled tasks, self-healing (foreground wrapper) |
| `jarvis-memory` | Memory browser (extras) |
| `jarvis-intelligence` | Intelligence dashboard (extras) |
| `jarvis-docs` | Docs reader (extras) |

Background daemons run inside the `jarvis-services` container. Self-healing **does not** use host-style PID restart loops in Docker (`JARVIS_DEPLOYMENT=docker` disables that). Container restart policy handles crashes.

---

## Shell and CLI commands inside Docker

The image contains the repository source under `/app`, so you can start additional shell or CLI processes alongside the running Python server:

```bash
# Interactive shell in the running Web UI container
docker compose exec -it jarvis-web bash

# Inspect the active tool profile
docker compose exec -T jarvis-web ./bin/manage-tools.py profile show

# Run a CLI question in the existing container
docker compose exec -T jarvis-web ./bin/question.sh "What reminders are pending?"

# Or use a temporary one-off container with the same mounts and network
docker compose run --rm --no-deps jarvis-web \
  ./bin/question.sh "Summarize today's alerts"
```

The prompt may display `I have no name!@<container-id>`. Compose runs the container with your numeric host UID/GID so bind-mounted files keep correct ownership, but that UID usually has no matching name in the image's `/etc/passwd`. It is harmless; commands still run as the intended numeric user and `HOME` is set to `/tmp`.

`jarvis-dashboard` is still primarily native-oriented: it expects tmux and localhost-managed services, while Docker services use Compose DNS and separate containers. Run the dashboard natively for now; ordinary Jarvis CLI commands can run either natively or through `docker compose exec/run`.

---

## Hybrid: Docker Web UI + native voice/CLI

1. Keep Docker stack running for UIs and API.
2. Run wake word or CLI on the host against the same repo (`./data` is shared).
3. Keep native tmux API/web/canvas **stopped** to avoid port conflicts.
4. Native wake/CLI talks to `http://127.0.0.1:8880` — works with API localhost bind.
5. Set `JARVIS_DOCKER_TOOL_PROFILE=default` if native flows need all tools, then block container-incompatible tools in Web UI Settings.

---

## Troubleshooting

**`web_config.json` bind source does not exist**

Compose refuses to start `jarvis-web` until the host file exists (`create_host_path: false` on that bind). Copy the example before the first `docker compose up`:

```bash
cp -n jarvis-web/config/web_config.json.example jarvis-web/config/web_config.json
```

If an older bring-up created `jarvis-web/config/web_config.json` as a **directory**, stop the stack, remove that directory, copy the example file above, then rerun `docker compose up -d`. A directory mount lets the Web UI start but Settings saves fail with HTTP 500.

**Permission denied on startup (`jarvis-web/data/uploads`)**

Fixed in current entrypoint — rebuild the image. Only the web service creates the uploads path.

**TTS: “scheduler crashed, restarting…”**

Usually native watchdog or host daemons still running. Run `./bin/jarvis-services --stop`, kill stragglers, comment out watchdog cron, clear stale `logs/*.pid` (not `logs/docker/`).

**UI works from host IP but not `:5003` / extras**

Ensure extras profile is up: `docker compose --profile extras ps`.

**API 500 on every request after rebuild**

Pin `fastapi<0.137` in `requirements.txt` (prometheus instrumentator compatibility) — rebuild image.

**Files owned by root in `./data` or `./logs`**

Set `JARVIS_DOCKER_UID` / `JARVIS_DOCKER_GID` in `.env` to your host user (`id -u` / `id -g`).

---

## Related docs

- [MAC-WINDOWS.md](MAC-WINDOWS.md) - experimental Docker Desktop setup for macOS, PowerShell, and Command Prompt
- [INSTALL_GUIDE.md](../INSTALL_GUIDE.md) — full native install (watchdog cron notes)
- [DOCKER_PLANNING.md](../archive/docker/DOCKER_PLANNING.md) — design, auth matrix, MCP, TTS/mic TLS
- [skills/README.md](../../skills/README.md) — tool profiles
- [SECURITY_HARDENING.md](../SECURITY_HARDENING.md) — `JARVIS_API_AUTH` behavior
