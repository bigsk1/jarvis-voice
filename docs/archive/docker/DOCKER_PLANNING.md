# Jarvis Docker Deployment (Planning & Design)

> **User guide:** For day-to-day Docker usage (commands, `.env`, hybrid mode, troubleshooting), see **[README.md](../../docker/README.md)**.

**Status:** Experimental. Jarvis ships a root [`Dockerfile`](../../../Dockerfile) and [`docker-compose.yml`](../../../docker-compose.yml) for local testing, but this is not a production/published image path yet.

> **Implemented mode plumbing (2026-06-27):** Compose injects `JARVIS_MODE`
> into every service, the entrypoint validates `config/<mode>.env` before init,
> and all UIs report `startup_mode`. The runnable Compose file—not older
> sketches in this design record—is authoritative.

**Scope:** Run Jarvis **Web UIs and supporting services** in Docker. Voice wake-word, OpenCode, and host-integrated tooling stay **out of scope for v1** or run on the host separately.

**Distribution:** **Local build only** — clone the repo, `docker compose build`, run on your own machine. Jarvis is not planned as a public image on Docker Hub or `ghcr.io`. Too much is machine-specific (secrets, DBs, intel, stash), and a published image would either bloat or leak patterns users should keep private.

---

## Goals

| Goal | How Docker helps |
|------|------------------|
| Simpler install | Copy or mount the repo at `/app` — no `$HOME/jarvis-voice` requirement |
| Reproducible stack | Same Python deps, system packages, and service layout on every machine |
| Headless server + desktop browser | User opens Web UI from a laptop; TTS already works in-browser |
| Cloud **and** local mode | Same container image; mode comes from mounted `cloud.env` / `local.env` |
| Safe tool surface | `JARVIS_TOOL_PROFILE=docker` disables host-only tools |

**Non-goals (v1):**

- Wake-word voice loop inside the container (ALSA/device passthrough)
- OpenCode in-container (defer; use host OpenCode or disable via profile)
- Replacing a user's existing GPU VM for Ollama / Kokoro / Qwen3-TTS

---

## Recommended architecture

Jarvis on a **headless Ubuntu host** (or any Docker host). LLM and TTS infrastructure may live **anywhere reachable on the network**.

```text
┌─────────────────────────────────────────────────────────────────┐
│  Docker host (Jarvis)                                           │
│  ┌─────────────┐ ┌─────────────┐ ┌──────────────┐ ┌──────────┐ │
│  │ jarvis-web  │ │ jarvis-api  │ │ jarvis-memory│ │ canvas   │ │
│  │   :5001     │ │   :8880     │ │   :5002      │ │ :8890    │ │
│  └──────┬──────┘ └──────┬──────┘ └──────────────┘ └──────────┘ │
│         │               │                                         │
│         └───────────────┴── jarvis-services (background daemons)│
│                              data/ + logs/ volumes              │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
   Desktop browser      GPU VM / host         Cloud APIs
   (chat, TTS)          Ollama :11434          xAI / OpenAI / …
                        Kokoro / Qwen3-TTS
```

### Services to containerize

These match what `./bin/start --ui-only` plus API/services already run today:

| Service | Port | Role |
|---------|------|------|
| `jarvis-web` | 5001 | Main chat UI, `/logs`, optional auth |
| `jarvis-api` | 8880 | Proactive API, webhooks, workflows |
| `jarvis-memory` | 5002 | Memory browser |
| `jarvis-intelligence` | 5003 | Intelligence dashboard |
| `jarvis-canvas` | 8890 | Canvas viewer |
| `jarvis-services` | — | Reminders, follow-up, self-healing, scheduled tasks |
| `jarvis-docs` | 5004 | Optional docs reader |

**Not in v1 Docker stack:** `wake-jarvis.py`, OpenCode server, host systemd integration.

Implementation options:

1. **One compose file, multiple services** (mirrors current `bin/start` layout) — easiest to debug.
2. **Single “all-in-one” container** with a process supervisor — fewer moving parts, harder logs.

Prefer **multi-service compose** on a shared **`jarvis` Docker network** for parity with how Jarvis runs natively today. See [Inter-service networking and auth](#inter-service-networking-and-auth) — `localhost` shortcuts from native installs do not automatically work across containers.

### Container user and file ownership

For Docker against a **live git checkout with host cron jobs**, prefer running containers as your host UID/GID. Jarvis writes SQLite journals, logs, generated media, uploaded files, and Web UI config overrides across several bind-mounted directories; matching the host user keeps those files editable by your normal user, avoids root-owned cleanup failures, and reduces the chance of noisy permission churn in a tracked repo.

Create a compose `.env` beside `docker-compose.yml`. This file is **Docker Compose interpolation only**; it is not Jarvis runtime config and does not replace `config/cloud.env` or `config/local.env`.

```bash
JARVIS_DOCKER_UID=1000
JARVIS_DOCKER_GID=1000
```

Or generate it:

```bash
printf "JARVIS_DOCKER_UID=%s\nJARVIS_DOCKER_GID=%s\n" "$(id -u)" "$(id -g)" > .env
```

Use it in each Jarvis service:

```yaml
services:
  jarvis-web:
    user: "${JARVIS_DOCKER_UID:-1000}:${JARVIS_DOCKER_GID:-1000}"
    environment:
      HOME: /tmp
      PYTHONDONTWRITEBYTECODE: "1"
      UMASK: "002"
```

The entrypoint should run `umask "${UMASK:-002}"` before creating files or starting Jarvis.

Root is still acceptable for a throwaway test stack or a greenfield install using named volumes. The tradeoff is that anything newly created in bind mounts may be owned by `root` on the Docker host:

```text
data/*.db-journal
logs/*.log
audio/*/tts/*
jarvis-intel/*
jarvis-web/data/uploads/*
data/generated_*
jarvis-web/config/web_config.json  # when saved by the Settings UI
```

If that happens, fix ownership from the host:

```bash
sudo chown -R "$USER:$USER" data logs audio jarvis-intel jarvis-web/data/uploads jarvis-web/config/web_config.json
```

Do **not** combine root containers with privileged mounts like `/var/run/docker.sock` unless this is a trusted single-user host.

---

## `.dockerignore` (required)

The build context must **not** copy runtime state — or secrets — into the image. Root **[`.dockerignore`](../../../.dockerignore)** mirrors [`.gitignore`](../../../.gitignore) and adds Docker-specific exclusions.

**Never in the image (always mount or omit):**

| Category | Examples | Why |
|----------|----------|-----|
| Secrets | `config/cloud.env`, `config/local.env`, `*.key` | Mount at runtime |
| Memory / Tool RAG DBs | `data/jarvis_memory.db`, `data/jarvis_memory_local.db` | Bind-mount existing host `data/` |
| Conversations & uploads | `data/web_conversations/`, `jarvis-web/data/uploads/` | User data |
| Logs & audio | `logs/`, `audio/` | Large, ephemeral |
| Personal intel | `jarvis-intel/*` (except tracked templates) | Machine-specific |
| Stash & generated media | `data/stash/`, `data/generated_*`, `data/canvas/` | Artifacts |
| Dev noise | `.git/`, `.cursor/`, `__pycache__/`, `jarvis-venv/` | Bloat |

The image should contain **code + committed config templates + skills** only. Everything accumulated at runtime lives on **host bind mounts**, same as a git clone where untracked files are created on first run.

Rebuild the image when **code or dependencies** change — not when you edit an API key or add a memory row.

---

## Ollama and TTS: keep them external

Do **not** bundle Ollama inside the Jarvis image. Users already run it:

- Natively on the host
- In their own Ollama Docker container
- On a **separate GPU VM** on the LAN (common pattern)

Point local mode at that endpoint in `config/local.env`:

```bash
# Same machine as Docker host
OLLAMA_BASE_URL="http://host.docker.internal:11434"

# Remote GPU box (example)
OLLAMA_BASE_URL="http://192.168.1.50:11434"
```

Same pattern for optional TTS sidecars:

```bash
QWEN3_TTS_URL="http://192.168.1.50:8881/v1/audio/speech"
KOKORO_TTS_URL="http://192.168.1.50:8880/v1/audio/speech"
```

In compose, add for Linux:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

Cloud mode may use xAI, Anthropic, OpenAI, or **Ollama Cloud**. When
`LLM_PROVIDER=ollama` in `config/cloud.env`, use a signed-in daemon reachable
from the container and set a cloud-tagged `OLLAMA_CLOUD_MODEL`. Normal local
Ollama models remain the supported default for local mode. See
[../ollama/README.md](../../ollama/README.md).

---

## Cloud and local mode together

Jarvis uses **two memory databases** with different embedding spaces:

```text
data/jarvis_memory.db        → cloud mode (OpenAI-class embeddings)
data/jarvis_memory_local.db  → local mode (Ollama embeddings)
```

Startup sync keeps them aligned when you switch modes. See [DUAL_DATABASE_SYSTEM.md](../../DUAL_DATABASE_SYSTEM.md).

**Docker implication:** sync only the modes you intend to use. Compose defaults
`JARVIS_SYNC_MODES` to the selected `JARVIS_MODE`; set it to `"cloud local"`
when both databases should be prepared:

```bash
./bin/sync-tools.py cloud
./bin/sync-tools.py local
```

The Docker entrypoint performs the selected sync once before serving traffic.
A one-mode installation needs only its selected env file and database. Prepare
both configs/DBs only when you intend to switch modes or synchronize both.

Compose mounts the full `config/` directory read-only but validates only the
file selected by root `.env` `JARVIS_MODE`. The Docker tool profile comes from
root `.env` `JARVIS_DOCKER_TOOL_PROFILE` and is injected as an authoritative
runtime override.

**Docker venv note:** `sync-tools.py` refuses to run outside the expected Jarvis virtual environment so bad fallback embeddings are not written by accident. In the image, set:

```dockerfile
ENV JARVIS_VENV=/opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
```

Then run sync commands with `/opt/venv/bin/python` or with that venv on `PATH`.

---

## Reusing existing data (no fresh start)

For developers with **months of existing state** (your case), Docker must **attach** what you already have — not replace it with empty named volumes.

**Recommended:** bind-mount the same directories your native install already uses:

```yaml
volumes:
  - ./data:/app/data
  - ./logs:/app/logs
  - ./jarvis-intel:/app/jarvis-intel   # if you use custom intel files
```

| Situation | Behavior |
|-----------|----------|
| **`data/jarvis_memory.db` already exists** | Use it as-is; entrypoint skips “create empty DB” |
| **Fresh clone, no DB files** | Same as native: startup / `sync-tools` creates and populates (git never tracked them) |
| **Switching native → Docker on same host** | Point mounts at existing `./data` — zero migration |
| **New machine** | Copy `data/` (includes stash/canvas/generated artifacts), `logs/`, env files; mount them; build image locally |

**Entrypoint rule (planned):** never wipe or replace existing `*.db` on container recreate. Create/migrate only when DBs or required tables are missing. Still run `sync-tools` when the active tool profile changes (for example, native `default` → Docker `docker`) or when explicitly forced (`JARVIS_FORCE_SYNC=1`), so profile-disabled host tools are disabled in Tool RAG. Unchanged tools skip re-embedding by content hash.

Named volumes (`jarvis-data:`) are fine for **brand-new** installs with no prior native tree; bind mounts are better for **testing Docker against a live Jarvis tree**.

---

## Configuration: bind mounts

Mount the live config directory so you can **edit keys and URLs without rebuilding the image** while allowing one-mode-only installs to omit the other env file:

```yaml
volumes:
  - ./config:/app/config:ro
  - ./jarvis-web/config/web_config.json:/app/jarvis-web/config/web_config.json:rw
  - ./data:/app/data
  - ./logs:/app/logs
  - ./audio:/app/audio
  - ./jarvis-web/data/uploads:/app/jarvis-web/data/uploads
```

**Why bind-mount the config directory?**

- API keys and `OLLAMA_BASE_URL` change often
- `mcp-servers.json`, contacts, webhook registry, and other read-only config are available without rebuilding
- A local-only install does not need a placeholder `cloud.env` (and vice versa)
- No `docker compose down && build` for a config tweak
- Restart the affected service (or entire stack) to pick up env changes — Python loads env at process start

Keep this directory read-only. Mutable application state belongs under the
read-write `data/` mount; price-alert thresholds use
`data/price-alerts.yaml`.

**Why mount `web_config.json` read-write?**

- The Web UI Settings panel saves model, provider, TTS, response-style, and Completion Guard overrides there
- These overrides can take effect without editing `cloud.env` / `local.env`
- Values that are not exposed in the Settings UI still belong in env files and require a container restart

Optional: mount `config/mcp-servers.json` if you customize MCP (see MCP section).

**Bind mounts vs named volumes:** Prefer **host `./data` bind mounts** when reusing an existing install (see above). Use named volumes only for greenfield Docker-only setups.

---

## Tool profile: `docker`

Host-only or awkward-in-container tools should be disabled via **`JARVIS_TOOL_PROFILE`**, not by editing dozens of `*.tool.json` files.

The tracked baseline profile lives at `skills/profiles/docker.json` and is copied into the image with the rest of the source tree. The example file is a reference template for custom profiles.

```bash
cp skills/profiles/examples/docker.json skills/profiles/my-docker.json
```

Set in **both** env files (or only the one you use):

```bash
JARVIS_TOOL_PROFILE="docker"
```

Compose can set it uniformly without editing shared env files by using the runtime override form. Plain `JARVIS_TOOL_PROFILE` from Compose can be overwritten when `load_config()` reads `config/cloud.env` or `config/local.env`.

```yaml
environment:
  JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE: docker
```

Important build-context detail: root `.dockerignore` includes the tracked `default.json`, `docker.json`, and `skills/profiles/examples/**`, while excluding other machine-specific profiles.

After changing profile:

```bash
./bin/sync-tools.py cloud
./bin/sync-tools.py local
# restart jarvis-web / jarvis-api / jarvis-services
```

Inspect: `./bin/manage-tools.py profile show`

See [skills/README.md](../../../skills/README.md) (Tool profiles) and [ADVANCED_AI_TECHNIQUES.md](../../ADVANCED_AI_TECHNIQUES.md#design-note-runtime-aware-capability-narration-qa) for the known Q&A vs profile gap.

**Optional advanced:** Mount `/var/run/docker.sock` and remove MCP / `docker_control` overrides from a custom profile — only on trusted single-user hosts.

Template: [`skills/profiles/examples/docker.json`](../../../skills/profiles/examples/docker.json)

---

## MCP in Docker

Default MCP config launches **`docker run ... --network host`**, which assumes a Docker CLI on the same machine as Jarvis. Inside a container:

| Approach | Pros | Cons |
|----------|------|------|
| **Disable MCP** (docker profile default) | Simple, secure | No Brave/fetch MCP tools |
| **Mount `docker.sock`** | Works with existing `mcp-servers.json`; implemented as the opt-in `docker-compose.mcp.yml` override | High privilege; DooD risk |
| **MCP as sibling compose services** | Clean networking | Requires config changes (future) |
| **MCP on host, Jarvis via `host.docker.internal`** | Split responsibility | Manual wiring |

The default remains to disable MCP tools in the `docker` profile. Trusted single-user hosts can opt in with `docker-compose.mcp.yml`, which gives only `jarvis-web` the Docker CLI and socket and selects the `docker-mcp` profile. Remote HTTP/SSE MCP servers do not need the socket; they only need a URL reachable from `jarvis-net` or `host.docker.internal`.

---

## Browser audio: TTS vs microphone

**TTS in the Web UI** uses browser playback — it works when you connect from a desktop to a headless server over HTTP.

**Push-to-talk STT** uses `getUserMedia()`. Browsers require a **[secure context](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts)** for microphone access:

- `https://` — works
- `http://localhost` — works
- `http://<lan-ip>:5001` — **mic often disabled (greyed out)**

That matches many headless setups today: TTS yes, mic no.

**Docker does not fix HTTP-by-IP by itself.** Options when you want mic from a remote desktop:

1. **TLS reverse proxy** (Caddy, nginx, Traefik) in front of `jarvis-web` with a real or internal CA cert
2. **SSH tunnel** — browse `http://localhost:5001` on the laptop (secure context + localhost)
3. **Tailscale Serve / similar** — HTTPS to the host

Document this in deployment notes so Docker users know mic STT is a **front-end TLS** problem, not a container audio passthrough problem.

Wake-word voice (`./jarvis`) remains a **host** concern for v1.

---

## Inter-service networking and auth

Native Jarvis assumes many internal URLs are **`http://localhost:<port>`** and that **`127.0.0.1` is trusted** when API auth is on.

### The localhost whitelist problem

With `JARVIS_API_AUTH=true`, the FastAPI middleware (`api/server.py`) allows requests from **`127.0.0.1`, `::1`, and `localhost`** without a Bearer token. External IPs need `Authorization: Bearer $JARVIS_API_KEY`.

On a **single machine**, `jarvis-web` → `localhost:8880`, `jarvis-canvas` → `localhost:8880`, and background daemons behave as “internal” calls.

In **multi-container compose**, service A calling `http://jarvis-api:8880` arrives with **`request.client.host` = the caller container’s IP** on the bridge network — **not** loopback. Those requests are treated as external and **401 without a Bearer token**.

Same class of issue for env vars still defaulting to localhost:

```bash
CANVAS_INTERNAL_URL="http://localhost:8890"   # wrong from jarvis-web container
# proactive_service, canvas gallery routes, self_healing_daemon → localhost:8880
```

These callers need env-configurable base URLs before multi-service compose is fully functional:

| Current caller | Native assumption | Docker target |
|----------------|-------------------|---------------|
| `jarvis-web/server/services/proactive_service.py` | `http://localhost:8880` | `JARVIS_API_INTERNAL_URL=http://jarvis-api:8880` |
| `jarvis-canvas/server/routes/gallery.py` | `http://localhost:8880` | `JARVIS_API_INTERNAL_URL=http://jarvis-api:8880` |
| `services/self_healing_daemon.py` | `http://localhost:8880` | `JARVIS_API_INTERNAL_URL=http://jarvis-api:8880` |
| `skills/canvas.py` | `http://localhost:8890` | `CANVAS_INTERNAL_URL=http://jarvis-canvas:8890` |

### Planned compose network

Put every Jarvis service on one user-defined network (e.g. `jarvis-net`). Docker DNS resolves service names:

```yaml
networks:
  jarvis-net:
    name: jarvis-net

services:
  jarvis-api:
    networks: [jarvis-net]
    # hostname: jarvis-api  (default = service name)

  jarvis-web:
    networks: [jarvis-net]
    depends_on: [jarvis-api]
```

**Internal base URLs (compose / docker env overlay — future):**

| Setting | Native default | Docker multi-service |
|---------|----------------|----------------------|
| Proactive API | `http://localhost:8880` | `http://jarvis-api:8880` |
| Canvas (internal) | `http://localhost:8890` | `http://jarvis-canvas:8890` |
| Memory / Intel UIs | localhost ports | `jarvis-memory:5002`, etc. |

`CANVAS_PUBLIC_URL` stays whatever **browsers** use (LAN IP or HTTPS hostname) — unchanged.

### Auth strategies for v1 Docker stack

| Strategy | When | Notes |
|----------|------|-------|
| **`JARVIS_API_AUTH=false` on private `jarvis-net`** | Simplest v1 | Stack not published to internet; only edge ports (5001, 8880) exposed on host |
| **Pass `JARVIS_API_KEY` on internal HTTP clients** | Auth enabled | Same key as external; requires code/env updates in callers (canvas gallery, proactive service, daemons) — see [auth/README.md](../../auth/README.md) |
| **Extend trusted IP list** (future env) | Auth enabled | e.g. trust Docker `172.18.0.0/16` — fragile if network CIDR changes |
| **Single container + supervisord** | Avoid networking/auth churn | All `localhost` calls work; heavier container, worse isolation |

**Web UI JWT auth (`WEBUI_PASSWORD`)** is separate — browser login across ports still works if all UIs share the same password and JWT secret in mounted env files. No localhost whitelist involved.

**Recommendation for first implementation:** private `jarvis-net`, document required **internal URL env overrides**, keep `JARVIS_API_AUTH=false` inside the stack unless/until internal clients send Bearer tokens. Users who expose 8880 to LAN can enable auth on the **host-facing** boundary (reverse proxy or API auth + keys on external clients only).

If `JARVIS_API_AUTH=false`, prefer not publishing API broadly. Bind to localhost on the host when possible:

```yaml
ports:
  - "127.0.0.1:8880:8880"
```

Expose `jarvis-web` to LAN or a reverse proxy; keep direct API access private unless auth is enabled.

Remote webhooks are the exception: n8n, UniFi Protect, `jarvis-monitor`, or other machines cannot POST to `127.0.0.1:8880`. For those, expose the API through a LAN bind plus `JARVIS_API_AUTH=true`, a reverse proxy with auth, a tunnel, or a webhook sidecar on the same host.

See also: [SECURITY_HARDENING.md](../../SECURITY_HARDENING.md) (API auth), [auth/README.md](../../auth/README.md) (Web UI SSO).

---

## CLI and TUI inside the container

No major refactor required for exploratory use:

```bash
docker compose exec jarvis-web bash
cd /app
source /opt/venv/bin/activate   # however the image lays out Python
./bin/question.sh "What time is it?"
python orchestrator/orchestrator_v2.py cloud "Hello"
```

**Caveats:**

- `bin/jarvis-dashboard` assumes `~/jarvis-venv` on the host — use exec + direct scripts instead, or set `JARVIS_VENV` inside the image
- Interactive audio commands will not work without device passthrough
- `tmux` sessions inside Docker are possible but not the primary ops model

---

## Compose sketch

The root [`docker-compose.yml`](../../../docker-compose.yml) is the runnable source. The sketch below is a trimmed reference for the important wiring:

```yaml
networks:
  jarvis-net:
    name: jarvis-net

services:
  jarvis-api:
    build: .
    command: ["./bin/jarvis-api"]
    user: "${JARVIS_DOCKER_UID:-1000}:${JARVIS_DOCKER_GID:-1000}"
    ports: ["127.0.0.1:8880:8880"]
    networks: [jarvis-net]
    environment:
      JARVIS_MODE: "${JARVIS_MODE:-cloud}"
      HOME: /tmp
      PYTHONDONTWRITEBYTECODE: "1"
      UMASK: "002"
      JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE: docker
      JARVIS_VENV: /opt/venv
      VIRTUAL_ENV: /opt/venv
      # JARVIS_API_AUTH: "false"   # see Inter-service networking section
    volumes:
      - ./config:/app/config:ro
      - ./skills/profiles/docker.json:/app/skills/profiles/docker.json:ro
      - ./data:/app/data
      - ./logs:/app/logs
    extra_hosts:
      - "host.docker.internal:host-gateway"

  jarvis-web:
    build: .
    command: ["./bin/jarvis-web"]
    user: "${JARVIS_DOCKER_UID:-1000}:${JARVIS_DOCKER_GID:-1000}"
    ports: ["5001:5001"]
    networks: [jarvis-net]
    depends_on: [jarvis-api]
    environment:
      HOME: /tmp
      PYTHONDONTWRITEBYTECODE: "1"
      UMASK: "002"
      JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE: docker
      JARVIS_VENV: /opt/venv
      VIRTUAL_ENV: /opt/venv
      JARVIS_API_INTERNAL_URL: "http://jarvis-api:8880"
      CANVAS_INTERNAL_URL: "http://jarvis-canvas:8890"
    volumes:
      - ./config:/app/config:ro
      - ./jarvis-web/config/web_config.json:/app/jarvis-web/config/web_config.json:rw
      - ./skills/profiles/docker.json:/app/skills/profiles/docker.json:ro
      - ./data:/app/data
      - ./logs:/app/logs
      - ./audio:/app/audio
      - ./jarvis-web/data/uploads:/app/jarvis-web/data/uploads

  jarvis-services:
    build: .
    # Do not use ./bin/jarvis-services unchanged as PID 1: it daemonizes with nohup
    # and exits. Use a Docker foreground wrapper, split each daemon into its own
    # service, or run a supervisor.
    command: ["services"]  # handled by docker/entrypoint.sh
    user: "${JARVIS_DOCKER_UID:-1000}:${JARVIS_DOCKER_GID:-1000}"
    networks: [jarvis-net]
    depends_on: [jarvis-api]
    environment:
      HOME: /tmp
      PYTHONDONTWRITEBYTECODE: "1"
      UMASK: "002"
      JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE: docker
      JARVIS_VENV: /opt/venv
      VIRTUAL_ENV: /opt/venv
      JARVIS_API_INTERNAL_URL: "http://jarvis-api:8880"
    volumes:
      - ./config:/app/config:ro
      - ./skills/profiles/docker.json:/app/skills/profiles/docker.json:ro
      - ./data:/app/data
      - ./logs:/app/logs

  jarvis-canvas:
    build: .
    command: ["./bin/jarvis-canvas"]
    user: "${JARVIS_DOCKER_UID:-1000}:${JARVIS_DOCKER_GID:-1000}"
    ports: ["8890:8890"]
    networks: [jarvis-net]
    environment:
      HOME: /tmp
      PYTHONDONTWRITEBYTECODE: "1"
      UMASK: "002"
      JARVIS_API_INTERNAL_URL: "http://jarvis-api:8880"
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
      - ./logs:/app/logs

  # jarvis-memory, jarvis-intelligence, jarvis-docs — same network + volume pattern
```

Startup entrypoint should:

1. Ensure `data/`, `logs/`, `audio/`, and `jarvis-web/data/uploads/` exist
2. Ensure `skills/profiles/docker.json` exists, copying the tracked example if needed
3. Ensure `/opt/venv` is active via `JARVIS_VENV`, `VIRTUAL_ENV`, and `PATH`
4. Acquire a simple init lock so API and services do not sync at the same time
5. If `data/jarvis_memory.db` / `data/jarvis_memory_local.db` missing → run dual `sync-tools` (and memory init same as native)
6. If DBs **exist** → skip destructive init, but run `sync-tools` when the active profile changed or `JARVIS_FORCE_SYNC=1`
7. Start the target service in the foreground

The current native `./bin/jarvis-services` script is not a Docker foreground process: it launches daemons with `nohup` and exits. For Docker, either split the four daemons into separate compose services, use a tiny supervisor, or add a Docker wrapper that starts them and `wait`s on the child PIDs.

---

## Image contents (planned)

Base: Python 3.12 on Debian/Ubuntu slim.

System packages from [`system-packages.txt`](../../../system-packages.txt) (subset for Web UI stack):

- `ffmpeg`, `sox`, `jq`, `curl`, `sqlite3`, `imagemagick`, …
- Skip or optional: `alsa-utils` (voice not in container v1)

Python: `uv sync` or `pip install -r requirements.txt` at build time.

`WORKDIR /app` — `get_project_root()` already resolves from code location; no `$HOME/jarvis-voice` at runtime.

The image should set:

```dockerfile
ENV JARVIS_VENV=/opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
```

Do not let runtime containers install missing packages on boot. Build all dependencies into the image so restarts are predictable.

---

## Comparison to native install

| Topic | Native (`install.sh`) | Docker (planned) |
|-------|----------------------|------------------|
| Repo location | `$HOME/jarvis-voice` enforced by installer | Any path → `/app` |
| Venv | `~/jarvis-venv` | Inside image (`/opt/venv`) |
| Voice wake word | Full support | Host only (v1) |
| Web UIs | `./bin/start` | `docker compose up` |
| Ollama | localhost or LAN | Same URLs; often `host.docker.internal` or GPU VM IP |
| OpenCode | Supported | Out of scope v1; disabled in profile |
| Config changes | Edit env files | Bind-mount env files + restart |
| Tool surface | Full | `docker` profile |
| Distribution | Git clone + `install.sh` | **Local `docker compose build` only** (no Hub publish) |
| Existing DBs | N/A | Bind-mount `./data` — no wipe on recreate |
| Service auth | `localhost` whitelisted | `jarvis-net` + env URL overrides; see auth section |

---

## Implementation checklist

- [x] `.dockerignore` (root — see above)
- [x] `Dockerfile` (Python 3.12 + system deps)
- [x] `docker-compose.yml` (`jarvis-net`, multi-service)
- [x] Run containers as host UID/GID by default for live-checkout bind mounts; keep root only as an explicit throwaway/named-volume fallback
- [x] Entrypoint: conditional init + optional `JARVIS_FORCE_SYNC`
- [x] Image build includes the tracked `skills/profiles/docker.json` baseline
- [x] Set `JARVIS_VENV=/opt/venv`, `VIRTUAL_ENV=/opt/venv`, and `PATH` so `sync-tools.py` passes its venv guard
- [x] Replace `jarvis-services` daemonizing behavior with foreground Docker wrapper
- [x] Internal URL env vars for cross-container calls (`jarvis-api`, `jarvis-canvas`, …)
- [x] Mount `jarvis-web/config/web_config.json` read-write if Web UI Settings should persist
- [x] Bind API to `127.0.0.1:8880` or keep it unexposed when `JARVIS_API_AUTH=false`
- [x] Auth story: document `JARVIS_API_AUTH` + Bearer on internal clients OR private network default
- [x] Document TLS options for browser mic
- [x] Optional: `JARVIS_DEPLOYMENT=docker` env flag for logging/health
- [x] Inject and validate `JARVIS_MODE` before init; pass it to every UI launcher
- [x] Mount `config/` read-only so the unselected env file may be absent
- [x] Expose `startup_mode` from UI health/status endpoints
- [ ] Local CI smoke test: `docker compose build && docker compose up -d` + `curl localhost:5001/api/status`

---

## Related docs

- [INSTALL_GUIDE.md](../../INSTALL_GUIDE.md) — native install path
- [JARVIS_WEB_UI.md](../../JARVIS_WEB_UI.md) — Web UI features and ports
- [DUAL_DATABASE_SYSTEM.md](../../DUAL_DATABASE_SYSTEM.md) — cloud/local DB sync
- [config/README.md](../../../config/README.md) — env file reference
- [skills/README.md](../../../skills/README.md) — tool profiles
- [JARVIS_PLAYGROUND.md](../../JARVIS_PLAYGROUND.md) — earlier CLI-only Docker sketch (superseded by this doc for Web UI scope)
- [monitoring/docker-compose.yml](../../../monitoring/docker-compose.yml) — Grafana/Loki stack (already containerized; mounts host `logs/`)
