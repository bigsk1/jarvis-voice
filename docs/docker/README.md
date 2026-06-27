# Jarvis Docker Guide

Run Jarvis **Web UIs, API, and background services** in Docker on your own machine. This is a **local build** workflow (`docker compose build`) — there is no published image on Docker Hub.

For architecture notes, networking deep-dives, and the original design doc, see **[DOCKER_PLANNING.md](DOCKER_PLANNING.md)**.

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

---

## Quick start

```bash
cd ~/jarvis-voice

# One-time: compose settings (ports, UID, mode) — no API keys here
cp docker.env.example .env
printf "JARVIS_DOCKER_UID=%s\nJARVIS_DOCKER_GID=%s\n" "$(id -u)" "$(id -g)" >> .env

# Build and start core stack
docker compose build
docker compose up -d

# Optional UIs: memory, intelligence, docs
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

Compose uses `--force-recreate`; there is no `--force-restart` flag.

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

Read-only consumers such as the API price-alert endpoints can use other files
from that directory without additional mounts. To let the Web UI `price_alert`
tool update thresholds, opt in to a writable mount for that file only:

```bash
test -f config/price-alerts.yaml
docker compose -f docker-compose.yml -f docker-compose.price-alerts.yml up -d
```

Compose overrides are additive, so MCP plus writable price alerts uses all
three files:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml \
  -f docker-compose.price-alerts.yml up -d
```

This leaves env files, `ssh.json`, and the rest of `config/` read-only. The
override refuses to start if `config/price-alerts.yaml` is absent rather than
letting Docker create a directory at that path.

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

```bash
# Add the host Docker socket group to root .env (one time).
printf 'JARVIS_DOCKER_SOCKET_GID=%s\n' \
  "$(stat -c '%g' /var/run/docker.sock)" >> .env

# Build and start with the MCP override.
docker compose -f docker-compose.yml -f docker-compose.mcp.yml build jarvis-web
docker compose -f docker-compose.yml -f docker-compose.mcp.yml up -d

# Confirm Docker access and MCP discovery from jarvis-web.
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
- [DOCKER_PLANNING.md](DOCKER_PLANNING.md) — design, auth matrix, MCP, TTS/mic TLS
- [skills/README.md](../../skills/README.md) — tool profiles
- [SECURITY_HARDENING.md](../SECURITY_HARDENING.md) — `JARVIS_API_AUTH` behavior
