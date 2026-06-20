# Jarvis Docker Deployment (Design)

**Status:** Design and operational guide. Jarvis does not ship a production `Dockerfile` or root `docker-compose.yml` yet — this document captures the intended approach before implementation.

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

---

## `.dockerignore` (required)

The build context must **not** copy runtime state — or secrets — into the image. Root **[`.dockerignore`](../../.dockerignore)** mirrors [`.gitignore`](../../.gitignore) and adds Docker-specific exclusions.

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

Cloud mode ignores Ollama for the main LLM but still benefits from **both memory DBs** being initialized (see below).

---

## Cloud and local mode together

Jarvis uses **two memory databases** with different embedding spaces:

```text
data/jarvis_memory.db        → cloud mode (OpenAI-class embeddings)
data/jarvis_memory_local.db  → local mode (Ollama embeddings)
```

Startup sync keeps them aligned when you switch modes. See [DUAL_DATABASE_SYSTEM.md](../DUAL_DATABASE_SYSTEM.md).

**Docker implication:** On first boot, run **both** tool and memory sync paths even if you only plan to use cloud (or only local):

```bash
./bin/sync-tools.py cloud
./bin/sync-tools.py local
```

The API and `jarvis-services` entrypoints already perform much of this on startup when run natively; the Docker entrypoint should do the same **once** before serving traffic. You may only *use* one mode day-to-day, but both DBs should exist so mode switches and cross-sync do not surprise you.

Treat **cloud.env and local.env as a pair** — mount both, seed both from examples on first run, set `JARVIS_TOOL_PROFILE` in whichever file matches your active mode (or set the same profile in both).

---

## Reusing existing data (no fresh start)

For developers with **months of existing state** (your case), Docker must **attach** what you already have — not replace it with empty named volumes.

**Recommended:** bind-mount the same directories your native install already uses:

```yaml
volumes:
  - ./data:/app/data
  - ./logs:/app/logs
  - ./stash:/app/stash
  - ./jarvis-intel:/app/jarvis-intel   # if you use custom intel files
```

| Situation | Behavior |
|-----------|----------|
| **`data/jarvis_memory.db` already exists** | Use it as-is; entrypoint skips “create empty DB” |
| **Fresh clone, no DB files** | Same as native: startup / `sync-tools` creates and populates (git never tracked them) |
| **Switching native → Docker on same host** | Point mounts at existing `./data` — zero migration |
| **New machine** | Copy `data/`, `logs/`, `stash/`, env files; mount them; build image locally |

**Entrypoint rule (planned):** init and dual `sync-tools` run only when DBs or tool tables are **missing or explicitly forced** (`JARVIS_FORCE_SYNC=1`) — never wipe or replace existing `*.db` on container recreate.

Named volumes (`jarvis-data:`) are fine for **brand-new** installs with no prior native tree; bind mounts are better for **testing Docker against a live Jarvis tree**.

---

## Configuration: bind mounts

Mount live config files so you can **edit keys and URLs without rebuilding the image**:

```yaml
volumes:
  - ./config/cloud.env:/app/config/cloud.env:ro   # or :rw if you prefer editing in place
  - ./config/local.env:/app/config/local.env:ro
  - ./config/web_config.json:/app/jarvis-web/config/web_config.json:ro
  - jarvis-data:/app/data
  - jarvis-logs:/app/logs
  - jarvis-stash:/app/stash
```

**Why bind-mount env files?**

- API keys and `OLLAMA_BASE_URL` change often
- No `docker compose down && build` for a config tweak
- Restart the affected service (or entire stack) to pick up env changes — Python loads env at process start

Optional: mount `config/mcp-servers.json` if you customize MCP (see MCP section).

**Bind mounts vs named volumes:** Prefer **host `./data` bind mounts** when reusing an existing install (see above). Use named volumes only for greenfield Docker-only setups.

---

## Tool profile: `docker`

Host-only or awkward-in-container tools should be disabled via **`JARVIS_TOOL_PROFILE`**, not by editing dozens of `*.tool.json` files.

Copy the tracked template:

```bash
cp skills/profiles/examples/docker.json skills/profiles/docker.json
```

Set in **both** env files (or only the one you use):

```bash
JARVIS_TOOL_PROFILE="docker"
```

Compose can set it uniformly:

```yaml
environment:
  JARVIS_TOOL_PROFILE: docker
```

After changing profile:

```bash
./bin/sync-tools.py cloud
./bin/sync-tools.py local
# restart jarvis-web / jarvis-api / jarvis-services
```

Inspect: `./bin/manage-tools.py profile show`

See [skills/README.md](../../skills/README.md) (Tool profiles) and [ADVANCED_AI_TECHNIQUES.md](../ADVANCED_AI_TECHNIQUES.md#design-note-runtime-aware-capability-narration-qa) for the known Q&A vs profile gap.

**Optional advanced:** Mount `/var/run/docker.sock` and remove MCP / `docker_control` overrides from a custom profile — only on trusted single-user hosts.

Template: [`skills/profiles/examples/docker.json`](../../skills/profiles/examples/docker.json)

---

## MCP in Docker

Default MCP config launches **`docker run ... --network host`**, which assumes a Docker CLI on the same machine as Jarvis. Inside a container:

| Approach | Pros | Cons |
|----------|------|------|
| **Disable MCP** (docker profile default) | Simple, secure | No Brave/fetch MCP tools |
| **Mount `docker.sock`** | Works with existing `mcp-servers.json` | High privilege; DooD risk |
| **MCP as sibling compose services** | Clean networking | Requires config changes (future) |
| **MCP on host, Jarvis via `host.docker.internal`** | Split responsibility | Manual wiring |

v1 recommendation: **disable MCP tools in the docker profile**; rely on provider-native search (xAI, etc.) and HTTP-based skills (`crawl_url`, SerpApi, …).

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
| **Pass `JARVIS_API_KEY` on internal HTTP clients** | Auth enabled | Same key as external; requires code/env updates in callers (canvas gallery, proactive service, daemons) — see [auth/README.md](../auth/README.md) |
| **Extend trusted IP list** (future env) | Auth enabled | e.g. trust Docker `172.18.0.0/16` — fragile if network CIDR changes |
| **Single container + supervisord** | Avoid networking/auth churn | All `localhost` calls work; heavier container, worse isolation |

**Web UI JWT auth (`WEBUI_PASSWORD`)** is separate — browser login across ports still works if all UIs share the same password and JWT secret in mounted env files. No localhost whitelist involved.

**Recommendation for first implementation:** private `jarvis-net`, document required **internal URL env overrides**, keep `JARVIS_API_AUTH=false` inside the stack unless/until internal clients send Bearer tokens. Users who expose 8880 to LAN can enable auth on the **host-facing** boundary (reverse proxy or API auth + keys on external clients only).

See also: [SECURITY_HARDENING.md](../SECURITY_HARDENING.md) (API auth), [auth/README.md](../auth/README.md) (Web UI SSO).

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

## Illustrative compose sketch

Not shipped yet — reference for implementers:

```yaml
networks:
  jarvis-net:
    name: jarvis-net

services:
  jarvis-api:
    build: .
    command: ["./bin/jarvis-api"]
    ports: ["8880:8880"]
    networks: [jarvis-net]
    env_file: [./config/cloud.env]
    environment:
      JARVIS_TOOL_PROFILE: docker
      # JARVIS_API_AUTH: "false"   # see Inter-service networking section
    volumes:
      - ./config/cloud.env:/app/config/cloud.env:ro
      - ./config/local.env:/app/config/local.env:ro
      - ./data:/app/data
      - ./logs:/app/logs
      - ./stash:/app/stash
    extra_hosts:
      - "host.docker.internal:host-gateway"

  jarvis-web:
    build: .
    command: ["./bin/jarvis-web"]
    ports: ["5001:5001"]
    networks: [jarvis-net]
    depends_on: [jarvis-api]
    environment:
      CANVAS_INTERNAL_URL: "http://jarvis-canvas:8890"
      # Future: JARVIS_API_INTERNAL_URL=http://jarvis-api:8880
    volumes:
      - ./config/cloud.env:/app/config/cloud.env:ro
      - ./config/local.env:/app/config/local.env:ro
      - ./data:/app/data
      - ./logs:/app/logs
      - ./stash:/app/stash

  jarvis-services:
    build: .
    command: ["./bin/jarvis-services"]
    networks: [jarvis-net]
    depends_on: [jarvis-api]
    volumes:
      - ./config/cloud.env:/app/config/cloud.env:ro
      - ./config/local.env:/app/config/local.env:ro
      - ./data:/app/data
      - ./logs:/app/logs

  jarvis-canvas:
    build: .
    command: ["./bin/jarvis-canvas"]
    ports: ["8890:8890"]
    networks: [jarvis-net]

  # jarvis-memory, jarvis-intelligence, jarvis-docs — same network + volume pattern
```

Startup entrypoint should:

1. Ensure `data/` and `logs/` exist
2. If `data/jarvis_memory.db` / `data/jarvis_memory_local.db` missing → run dual `sync-tools` (and memory init same as native)
3. If DBs **exist** → skip init; optional `JARVIS_FORCE_SYNC=1` to refresh tool RAG
4. Start the target service

---

## Image contents (planned)

Base: Python 3.12 on Debian/Ubuntu slim.

System packages from [`system-packages.txt`](../../system-packages.txt) (subset for Web UI stack):

- `ffmpeg`, `sox`, `jq`, `curl`, `sqlite3`, `imagemagick`, …
- Skip or optional: `alsa-utils` (voice not in container v1)

Python: `uv sync` or `pip install -r requirements.txt` at build time.

`WORKDIR /app` — `get_project_root()` already resolves from code location; no `$HOME/jarvis-voice` at runtime.

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

## Implementation checklist (future)

- [x] `.dockerignore` (root — see above)
- [ ] `Dockerfile` (Python 3.12 + system deps)
- [ ] `docker-compose.yml` (`jarvis-net`, multi-service)
- [ ] Entrypoint: conditional init (skip if DBs exist) + optional `JARVIS_FORCE_SYNC`
- [ ] Internal URL env vars for cross-container calls (`jarvis-api`, `jarvis-canvas`, …)
- [ ] Auth story: document `JARVIS_API_AUTH` + Bearer on internal clients OR private network default
- [ ] Document TLS options for browser mic
- [ ] Optional: `JARVIS_DEPLOYMENT=docker` env flag for logging/health
- [ ] Local CI smoke test: `docker compose build && docker compose up -d` + `curl localhost:5001/api/status`

---

## Related docs

- [INSTALL_GUIDE.md](../INSTALL_GUIDE.md) — native install path
- [JARVIS_WEB_UI.md](../JARVIS_WEB_UI.md) — Web UI features and ports
- [DUAL_DATABASE_SYSTEM.md](../DUAL_DATABASE_SYSTEM.md) — cloud/local DB sync
- [config/README.md](../../config/README.md) — env file reference
- [skills/README.md](../../skills/README.md) — tool profiles
- [JARVIS_PLAYGROUND.md](../JARVIS_PLAYGROUND.md) — earlier CLI-only Docker sketch (superseded by this doc for Web UI scope)
- [monitoring/docker-compose.yml](../../monitoring/docker-compose.yml) — Grafana/Loki stack (already containerized; mounts host `logs/`)
