# Jarvis Web UIs on macOS and Windows

Run the Jarvis Web UI stack through Docker Desktop without installing Ubuntu, Python 3.12, the Jarvis virtual environment, or native audio dependencies on the host.

This is an experimental Web UI deployment path. The native Ubuntu installation remains the primary tested target for wake word, microphones, speakers, the terminal dashboard, host automation, and hardware integrations.

## What this Docker setup provides

| Available in Docker Desktop | Not part of this setup |
|---|---|
| Main chat Web UI | Wake-word listener and microphone capture |
| FastAPI service | Native `jarvis-dashboard` and tmux management |
| Canvas UI | Host speaker and volume control |
| Memory, Intelligence, and Docs UIs | Printer, SSH, OpenCode, and Spotify OAuth on the host |
| Optional reminder and scheduler daemons | A native macOS or Windows Jarvis installation |
| Cloud or local Ollama mode | Formal macOS or Windows support guarantees |

The repository can be cloned into any directory. Docker builds a Linux image with Python 3.12 and runs the application under `/app`, so the native `$HOME/jarvis-voice` requirement does not apply.

## Current platform status

- Ubuntu 24.04 on `linux/amd64`: tested.
- Windows 10/11 with Docker Desktop, WSL 2, and Linux containers: expected to work, but not yet part of automated testing.
- Intel macOS with Docker Desktop: expected to work, but not yet part of automated testing.
- Apple Silicon macOS: native `linux/arm64` builds are not yet verified against every pinned Python/ML dependency. An `amd64` emulation fallback is included below.
- The optional `docker-compose.mcp.yml` Docker socket integration is currently Linux-host tested only. Do not use it as the first macOS or Windows setup.

Docker Desktop runs Linux containers in a VM and supports bind mounting files from macOS and Windows into that VM. See Docker's [bind mount documentation](https://docs.docker.com/engine/storage/bind-mounts/) and [Docker Desktop documentation](https://docs.docker.com/desktop/).

## Before you begin

Install and start:

1. [Git](https://git-scm.com/downloads)
2. [Docker Desktop](https://docs.docker.com/desktop/)
3. On Windows, enable the WSL 2 backend and make sure Docker Desktop is using **Linux containers**, not Windows containers.

Allocate enough Docker Desktop memory for the image build and Python services. The current image includes voice and machine-learning packages even when only the Web UIs are used, so the first build is large and can take several minutes.

Live configuration files and databases are gitignored. They remain in the cloned repository on the host and are bind-mounted into the Linux containers.

## macOS installation

Open Terminal and run:

```bash
git clone https://github.com/bigsk1/jarvis-voice.git
cd jarvis-voice

# Choose the mode you will run; the other file is optional.
cp config/cloud.env.example config/cloud.env
# cp config/local.env.example config/local.env
cp jarvis-web/config/web_config.json.example jarvis-web/config/web_config.json
cp docker.env.example .env
```

Match the container user to your macOS account so bind-mounted files remain writable:

```bash
sed -i.bak \
  -e "s/^JARVIS_DOCKER_UID=.*/JARVIS_DOCKER_UID=$(id -u)/" \
  -e "s/^JARVIS_DOCKER_GID=.*/JARVIS_DOCKER_GID=$(id -g)/" \
  .env
rm -f .env.bak
```

Edit `config/cloud.env` and configure the selected cloud LLM and embedding provider credentials. Keep secrets out of root `.env`; that file is only for Compose ports, mode, UID/GID, API auth, tool profile settings, and optional Docker-only Ollama/helper overrides.

```bash
open -e config/cloud.env
```

Build the image:

```bash
docker compose build
```

Start only the APIs and Web UIs, without reminder/scheduler daemons:

```bash
docker compose --profile extras up -d \
  jarvis-api jarvis-web jarvis-canvas \
  jarvis-memory jarvis-intelligence jarvis-docs
```

Or start the complete Docker stack, including background services:

```bash
docker compose --profile extras up -d
```

Open the main UI:

```bash
open http://localhost:5001
```

### Apple Silicon fallback

Try the normal build first. If an ML dependency does not provide a compatible `linux/arm64` package, build and run the `amd64` image through Docker Desktop emulation:

```bash
export DOCKER_DEFAULT_PLATFORM=linux/amd64
docker compose build --no-cache
docker compose --profile extras up -d
```

Emulation is slower and uses more resources. This is a fallback, not a verified performance configuration. Docker documents the available architecture strategies in its [multi-platform build guide](https://docs.docker.com/build/building/multi-platform/).

## Windows installation with PowerShell

Open PowerShell. The repository does not have to be under your Windows home directory.

```powershell
git clone https://github.com/bigsk1/jarvis-voice.git
Set-Location jarvis-voice

# Choose the mode you will run; the other file is optional.
Copy-Item config/cloud.env.example config/cloud.env
# Copy-Item config/local.env.example config/local.env
Copy-Item jarvis-web/config/web_config.json.example jarvis-web/config/web_config.json
Copy-Item docker.env.example .env
```

Keep the default Docker UID/GID values of `1000:1000` initially. Docker Desktop normally handles access to files shared from Windows. If logs report permission errors, see [Troubleshooting](#troubleshooting).

Edit the cloud configuration and add the selected provider credentials:

```powershell
notepad config\cloud.env
```

Build and start only the APIs and Web UIs:

```powershell
docker compose build
docker compose --profile extras up -d jarvis-api jarvis-web jarvis-canvas jarvis-memory jarvis-intelligence jarvis-docs
Start-Process http://localhost:5001
```

To include reminder and scheduled-task background services instead:

```powershell
docker compose --profile extras up -d
```

If an ARM-based Windows machine cannot build a dependency, use the same `amd64` fallback for the current PowerShell session:

```powershell
$env:DOCKER_DEFAULT_PLATFORM = "linux/amd64"
docker compose build --no-cache
docker compose --profile extras up -d
```

## Windows installation with Command Prompt

Open Command Prompt and run:

```bat
git clone https://github.com/bigsk1/jarvis-voice.git
cd jarvis-voice

REM Choose the mode you will run; the other file is optional.
copy config\cloud.env.example config\cloud.env
REM copy config\local.env.example config\local.env
copy jarvis-web\config\web_config.json.example jarvis-web\config\web_config.json
copy docker.env.example .env
notepad config\cloud.env
```

Build and start only the APIs and Web UIs:

```bat
docker compose build
docker compose --profile extras up -d jarvis-api jarvis-web jarvis-canvas jarvis-memory jarvis-intelligence jarvis-docs
start http://localhost:5001
```

To include background services:

```bat
docker compose --profile extras up -d
```

For an `amd64` emulation fallback in the current Command Prompt:

```bat
set DOCKER_DEFAULT_PLATFORM=linux/amd64
docker compose build --no-cache
docker compose --profile extras up -d
```

## URLs

| Service | Address |
|---|---|
| Main Web UI | `http://localhost:5001` |
| Canvas | `http://localhost:8890` |
| Memory | `http://localhost:5002` |
| Intelligence | `http://localhost:5003` |
| Docs | `http://localhost:5004` |
| API health | `http://localhost:8880/api/health` |

The extra Memory, Intelligence, and Docs UIs require the `extras` profile used in the commands above.

### Use one hostname consistently

Choose one hostname and use it for every Jarvis UI port. For example, use either `localhost` everywhere or the Windows/Mac LAN IP everywhere. Do not mix `localhost`, `127.0.0.1`, and `192.168.x.x` during one browser session.

The shared authentication cookie works across ports on the same hostname, but browsers intentionally isolate cookies between different hostnames. Signing in at `http://localhost:5001` therefore shares authentication with `http://localhost:8890`, but not with `http://127.0.0.1:8890` or a LAN-IP URL.

## Browser audio, reminders, and alerts

Docker containers cannot drive system's physical speaker. Browser TTS is the intended path when you use Jarvis from a laptop or desktop.

### Chat TTS (Jarvis Web replies)

When **🔊 TTS is enabled** in Jarvis Web, chat responses are synthesized via `POST /api/tts` and played in **your browser**. That is true for both **Docker** and **native** installs when you access Jarvis through the browser on a headless server — chat audio does not come out of the server’s speaker.

### Proactive speech (reminders and alerts)

Spoken reminders and alerts use a **separate** path from chat. On **Docker**, Jarvis Web polls the API and plays TTS in the browser when a new reminder or alert arrives. On a **native** install, the background daemons speak through the **host speaker** (`bin/say.sh` / `say-local.sh`); Jarvis Web does **not** repeat them in the browser (avoids double audio).

| | Chat TTS in browser | Spoken reminders/alerts |
|---|---|---|
| **Docker** (browser on laptop/desktop) | Yes — `/api/tts` | Yes — Jarvis Web proactive + `/api/tts` |
| **Native** (headless server + browser on another device) | Yes — `/api/tts` | No in browser — host speaker only |

The Memory UI alert **ding** (port 5002) is unrelated: it is a short tab alert when the Memory browser tab is open, not full spoken TTS.

### Requirements for spoken reminders/alerts in Docker

1. **`jarvis-services` must be running** — use the full-stack `docker compose --profile extras up -d` line, not the UIs-only line that omits `jarvis-services`. The reminder scheduler inside that container marks reminders as `triggered`; without it, nothing reaches the proactive poller.
2. **🔊 TTS enabled** in Jarvis Web (header toggle or Settings).
3. **TTS provider configured** in `config/cloud.env` or `config/local.env` (same keys chat TTS uses — ElevenLabs, xAI, Qwen3, etc.).
4. **Jarvis Web tab must stay open** — see below.

### Keep the Jarvis Web tab open (it does not need to be the active tab)

Proactive polling runs in **Jarvis Web’s JavaScript** on port **5001**. It is client-side: closing that tab stops checks and spoken notifications.

You do **not** need Jarvis Web to be the front-most tab. You can work in **Memory** (`:5002`), **Intelligence** (`:5003`), or another app while a **background** Jarvis Web tab stays open — polling and TTS can still run there.

What does **not** work:

- **Closing** the Jarvis Web tab entirely — proactive stops.
- Expecting Memory or Intelligence tabs alone to play spoken reminders — those UIs are separate apps; they do not run Jarvis Web’s proactive poller (Memory’s alert ding is separate).

**Browser caveats:** Background tabs may poll slower than every 10 seconds (browser throttling). Some browsers block autoplay until you have clicked or toggled audio on the Jarvis Web tab at least once in that session. If speech is delayed, bring the Jarvis Web tab forward once or click 🔊.

**Typical delay:** Reminder scheduler runs about every 60 seconds; proactive polls about every 10 seconds — expect up to roughly a minute after the due time before speech.

### Test proactive audio from the host

Use the API on **`127.0.0.1:8880`** (default `JARVIS_API_PORT`). These calls hit `jarvis-api` only — Web UI login (`WEBUI_PASSWORD`) is separate. With `JARVIS_API_AUTH=true`, add `-H "Authorization: Bearer YOUR_JARVIS_API_KEY"` to each request.

Before testing: full stack running (including `jarvis-services`), Jarvis Web open on `:5001`, **🔊 TTS enabled**, and TTS provider keys configured.

**Windows (PowerShell)** — use `curl.exe` (not `curl`, which aliases to `Invoke-WebRequest`):

```powershell
curl.exe -s http://127.0.0.1:8880/api/health

curl.exe -s -X POST http://127.0.0.1:8880/api/alerts -H "Content-Type: application/json" -d '{"title":"Docker alert test","description":"Manual test alert","severity":"medium","source":"docker_test"}'

curl.exe -s -X POST http://127.0.0.1:8880/api/reminders -H "Content-Type: application/json" -d '{"title":"Docker reminder test","description":"Should speak after scheduler runs","trigger_time":"2020-01-01T00:00:00Z"}'
```

The alert should speak in the browser within about 10 seconds. The reminder uses a past `trigger_time` so the scheduler picks it up on its next pass (up to ~60 seconds), then proactive TTS follows.

**macOS (Terminal)** — same payloads with `curl`:

```bash
curl -s http://127.0.0.1:8880/api/health

curl -s -X POST http://127.0.0.1:8880/api/alerts -H "Content-Type: application/json" -d '{"title":"Docker alert test","description":"Manual test alert","severity":"medium","source":"docker_test"}'

curl -s -X POST http://127.0.0.1:8880/api/reminders -H "Content-Type: application/json" -d '{"title":"Docker reminder test","description":"Should speak after scheduler runs","trigger_time":"2020-01-01T00:00:00Z"}'
```

Acknowledge items from the Jarvis Web notification panel (🔔) or the Memory UI when finished testing.

## Cloud and local modes

Cloud mode is the simplest Docker Desktop starting point:

```env
JARVIS_MODE=cloud
```

Set this in root `.env`, then configure the matching provider values in `config/cloud.env`.

Cloud mode can also use Ollama Cloud. Set the signed-in daemon in root `.env`
when the mode ENV uses a native-only hostname:

```env
JARVIS_DOCKER_OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Then set `OLLAMA_CLOUD_MODEL` in `config/cloud.env` to a recognized `*:cloud`
or `*-cloud` model. Do not put a normal local Ollama model in
`OLLAMA_CLOUD_MODEL`. The Docker endpoint also serves the required Jarvis
Embedding model.

The optional Jarvis helper model uses the same external daemon by default.
Pull it on that daemon:

```bash
ollama pull bigsk1/jarvis-helper:minicpm5-1b-q4_k_m-v3
```

Then opt in through the selected mode ENV, or use the commented
`JARVIS_DOCKER_*` role overrides in root `.env`. The helper inherits the Docker
Ollama endpoint by default; use `JARVIS_DOCKER_HELPER_LLM_BASE_URL` only when it
intentionally runs on another daemon.

Only the selected env file is required. A cloud-only setup may omit
`config/local.env`; a local-only setup may omit `config/cloud.env`.

For local mode, install and start Ollama on the Mac or Windows host. Keep the
native endpoint in `config/local.env` and put the Docker Desktop host address in
root `.env`:

```env
JARVIS_DOCKER_OLLAMA_BASE_URL=http://host.docker.internal:11434
```

Then set root `.env` to:

```env
JARVIS_MODE=local
```

Recreate the stack after changing modes:

```bash
docker compose --profile extras up -d --force-recreate
```

The same `docker compose` command works in Terminal, PowerShell, and Command Prompt.

## Checking and stopping the stack

```bash
docker compose --profile extras ps
docker compose logs --tail=100 jarvis-web
docker compose logs --tail=100 jarvis-api
docker compose down
```

`docker compose down` removes containers and the Compose network. It does not delete the bind-mounted `data`, `logs`, `audio`, uploads, configuration, or databases in the repository.

## Updating Jarvis

From the repository directory:

If you only changed bind-mounted config or runtime files, recreate containers without rebuilding:

```bash
docker compose --profile extras up -d --force-recreate
```

For the MCP stack, keep both Compose files on the recreate command:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d --force-recreate
```

Use the same Compose file set that started the current stack. Omitting the MCP
override during a recreate replaces `jarvis-web` with the base image and removes
its Docker socket configuration.

Bind mounts include the read-only `config/` directory,
`jarvis-web/config/web_config.json`, `data/`, `logs/`, `audio/`, and uploads.
Root `.env` is read by Compose for interpolation; it is not mounted into a
container.

### Config change cheat sheet

Editing `config/cloud.env` or `config/local.env` updates the bind mount on disk
immediately, but **running containers keep old values** until recreated. Python
services call `load_config()` at startup. Tool subprocesses re-read the file on
each run, so some tool-only settings can look updated before you restart — do not
rely on that for LLM, auth, or UI behavior.

**Web UI settings** live in `jarvis-web/config/web_config.json` and often apply
without a container restart. This cheat sheet is for **`cloud.env` / `local.env`**
and other bind-mounted config.

Use the same Compose file set that started your stack. MCP commands below include
`-f docker-compose.yml -f docker-compose.mcp.yml`.

| You changed | Recreate |
|-------------|----------|
| LLM keys, `LLM_PROVIDER`, models, embeddings, `OLLAMA_*` | `jarvis-web`, `jarvis-api`, `jarvis-services` |
| `CANVAS_PUBLIC_URL`, `CANVAS_INTERNAL_URL` | `jarvis-web`, `jarvis-canvas` |
| `WEBUI_PASSWORD` / JWT auth | all Web UIs (see below) |
| `config/mcp-servers.json` | `jarvis-web` only (MCP stack) |
| Root `.env` (`JARVIS_MODE`, ports, UID/GID, tool profile) | full stack |

#### LLM / provider / API keys

Standard stack:

```bash
docker compose --profile extras up -d --force-recreate jarvis-web jarvis-api jarvis-services
```

MCP stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d --force-recreate jarvis-web jarvis-api jarvis-services
```

#### Canvas public or internal URL

Standard stack:

```bash
docker compose --profile extras up -d --force-recreate jarvis-web jarvis-canvas
```

MCP stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d --force-recreate jarvis-web jarvis-canvas
```

#### Web UI password / auth

Standard stack:

```bash
docker compose --profile extras up -d --force-recreate jarvis-web jarvis-canvas jarvis-memory jarvis-intelligence jarvis-docs
```

MCP stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d --force-recreate jarvis-web jarvis-canvas jarvis-memory jarvis-intelligence jarvis-docs
```

#### MCP server list (`config/mcp-servers.json`)

MCP stack only — then rerun Tool RAG sync on `jarvis-web`:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d --force-recreate jarvis-web
```

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml exec -T jarvis-web rm -f data/.docker_tool_profile_synced
```

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml up -d --force-recreate jarvis-web
```

Standard stack (no Docker-socket MCP — HTTP/SSE MCP servers only):

```bash
docker compose --profile extras up -d --force-recreate jarvis-web
```

#### Root `.env` (Compose settings)

Standard stack:

```bash
docker compose --profile extras up -d --force-recreate
```

MCP stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d --force-recreate
```

#### When in doubt (config only — no rebuild)

Recreates every service and re-reads env files. `./data` and `./logs` are unchanged.

Standard stack:

```bash
docker compose --profile extras up -d --force-recreate
```

MCP stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d --force-recreate
```

Before pulling, inspect what GitHub will change. The commands below assume the
tracked branch is `origin/main`, as it is after the normal clone instructions:

```bash
git status --short
git fetch origin
git log --oneline --decorate HEAD..origin/main
git diff --stat HEAD..origin/main
git diff --name-status HEAD..origin/main
git pull --ff-only
```

`git status --short` should be clean before pulling. The live env files,
`web_config.json`, root `.env`, and databases are gitignored, so back them up
separately when an update changes configuration examples or database behavior.

After pulling app code, frontend, routes, tools, scripts, the Dockerfile, or
dependencies, a no-cache rebuild is the most predictable update path. It is
slower, but avoids accidentally reusing an older application layer.

### Clean rebuild: standard stack

Use this when the stack was started without `docker-compose.mcp.yml`:

```bash
docker compose --profile extras down
docker compose build --pull --no-cache
docker compose --profile extras up -d --force-recreate
```

If the update adds or changes tools, refresh Tool RAG after the stack is up:

```bash
docker compose exec jarvis-api python bin/sync-tools.py cloud --force
docker compose exec jarvis-api python bin/sync-tools.py local --force
```

### Clean rebuild: MCP stack

Use both Compose files on **every** command when the stack uses the MCP Docker
socket override:

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras down
docker compose -f docker-compose.yml -f docker-compose.mcp.yml build --pull --no-cache
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d --force-recreate
```

The MCP override runs `jarvis-web` from the separate `jarvis-voice:mcp` image.
Running only `docker compose build --pull` rebuilds the base
`jarvis-voice:local` image and can leave an older MCP Web UI running. Adding the
override files only to `up` does not rebuild that MCP image.

If the update adds or changes tools or MCP server config, refresh Tool RAG
through **`jarvis-web`**, not `jarvis-api` (the API container has no Docker CLI
or socket for MCP sidecars):

```bash
docker compose -f docker-compose.yml -f docker-compose.mcp.yml exec -T jarvis-web rm -f data/.docker_tool_profile_synced
docker compose -f docker-compose.yml -f docker-compose.mcp.yml up -d --force-recreate jarvis-web
```

After a frontend update, use **Ctrl+Shift+R** or **Ctrl+F5** on Windows, or
**Cmd+Shift+R** on macOS. If behavior still looks stale, enable **Disable Cache**
in browser DevTools while reloading. The Network panel should show request URLs
and payloads that match the newly pulled code.

Back up `data/` and your live configuration files before major upgrades. Never commit `config/cloud.env`, `config/local.env`, root `.env`, `jarvis-web/config/web_config.json`, or database files.

## MCP on Docker Desktop

Remote HTTP or SSE MCP servers can work without Docker socket access when their URL is reachable from the Jarvis containers. A server running directly on the Mac or Windows host should normally use `host.docker.internal`, not `localhost`, in `config/mcp-servers.json`.

The tracked `docker` tool profile disables the existing stdio MCP servers because they launch child containers through the host Docker daemon. The optional `docker-compose.mcp.yml` socket workflow is currently tested only on a trusted Linux host. It relies on a Unix socket and numeric socket GID. Treat macOS and Windows as **experimental** if you try it.

### Optional: stdio MCP via `docker-compose.mcp.yml` (experimental)

Keep `JARVIS_DOCKER_TOOL_PROFILE=docker` in root `.env`. This override assigns
`docker-mcp` only to `jarvis-web`, which is the only service receiving the
Docker CLI and socket. A stack-wide `docker-mcp` value makes base services try
to discover sidecars they cannot launch.

`stat -c '%g' /var/run/docker.sock` is a Linux command and does not run in PowerShell or macOS Terminal. Use Docker instead — it reads the same `/var/run/docker.sock` path that Compose mounts:

**PowerShell** (from the repo directory, Docker Desktop running):

```powershell
$gid = docker run --rm -v /var/run/docker.sock:/var/run/docker.sock alpine stat -c '%g' /var/run/docker.sock
Add-Content -Path .env -Value "JARVIS_DOCKER_SOCKET_GID=$gid"
```

**macOS Terminal** (same one-liner, then append manually or use `echo "JARVIS_DOCKER_SOCKET_GID=$gid" >> .env`).

**Optional WSL-only check** (Docker Desktop WSL 2 backend): `wsl stat -c '%g' /var/run/docker.sock` — the value should match the Docker one-liner above. **`0` is valid** on some Docker Desktop installs.

### Pull MCP sidecar images first (required for stdio MCP)

Stdio MCP servers in `config/mcp-servers.json` run as **`docker run …`** sidecars from inside `jarvis-web`. On a fresh clone, Docker init runs **`sync-tools.py`**, which discovers MCP tools before the Web UI starts. If an enabled server's image is not on the host yet, that server is skipped (same effect as disabled) and logged. The Web UI still starts, but Docker init does not record the tool sync as complete, so recreating `jarvis-web` retries it after the images become available. Pulling first avoids the partial first sync and empty MCP tool lists.

Check which servers have `"enabled": true`, then pull each **image** referenced in `"args"` (the token after `run`, before flags like `-e` or `--network`).

With the stock config (`fetch` and `brave_search` enabled):

```powershell
docker pull mcp/fetch
docker pull mcp/brave-search
```

If you enable other entries (for example `mcp/sequentialthinking` or `mcr.microsoft.com/playwright/mcp`), pull those images too before starting.

The MCP override applies `JARVIS_DEFER_TOOL_SYNC=1` and the docker tool profile to **all** Jarvis services. Only **`jarvis-web`** additionally gets Docker CLI/socket access and the `docker-mcp` profile; use the same **`--profile extras`** pattern as the standard install, with both compose files on every command.

**PowerShell** — build and start (pick one `up` line):

```powershell
docker compose -f docker-compose.yml -f docker-compose.mcp.yml build --pull --no-cache

# APIs + all Web UIs (extras), no background daemons
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d jarvis-api jarvis-web jarvis-canvas jarvis-memory jarvis-intelligence jarvis-docs

# Full stack including jarvis-services (reminders, scheduled tasks, self-healing)
docker compose -f docker-compose.yml -f docker-compose.mcp.yml --profile extras up -d

Start-Process http://localhost:5001
```

**Verify MCP inside jarvis-web:**

```powershell
docker compose -f docker-compose.yml -f docker-compose.mcp.yml exec -T jarvis-web docker version
docker compose -f docker-compose.yml -f docker-compose.mcp.yml exec -T jarvis-web ./bin/test-mcp --discover
```

**macOS Terminal** — same compose flags; swap `Start-Process` for `open http://localhost:5001`.

**Command Prompt** — same `docker compose -f docker-compose.yml -f docker-compose.mcp.yml ...` lines; use `start http://localhost:5001` to open the UI.

If `docker version` inside `jarvis-web` fails with permission denied, the GID may not match your Docker Desktop socket — re-run the Alpine `stat` command and recreate `jarvis-web`. See [README.md](README.md) for security notes on mounting `docker.sock`.

## Troubleshooting

### A configuration path became a directory

The base stack mounts the existing `config/` directory and no longer creates
missing env paths as directories. The Web settings bind uses
`create_host_path: false`, so a missing `web_config.json` fails at
`docker compose up` instead of silently becoming a directory. If an **older**
bring-up left a directory at that path, stop the stack, remove the directory,
and copy the example before retrying:

- `jarvis-web/config/web_config.json.example` to `jarvis-web/config/web_config.json`

Then rerun `docker compose up -d`.

### Shell script reports `bad interpreter` or `bash\r`

The repository `.gitattributes` forces Linux-executed scripts to use LF endings. Update Git and use a fresh clone if an older checkout still contains CRLF line endings. Do not manually convert live env files while containers are running.

### Permission denied under `data`, `logs`, or uploads

On macOS, confirm `.env` contains your `id -u` and `id -g` values. On Windows, confirm the repository drive or directory is available to Docker Desktop and that Docker Desktop is using its WSL 2 Linux backend. Avoid cloning under a protected system directory.

To inspect the Windows host directories mounted into Canvas without PowerShell quoting problems:

```powershell
docker inspect jarvis-voice-jarvis-canvas-1 --format '{{json .Mounts}}' |
  ConvertFrom-Json |
  Select-Object Source, Destination
```

### Port already allocated

Stop native Jarvis processes or other applications using ports `5001`-`5004`, `8880`, or `8890`. Alternatively, change the corresponding `JARVIS_*_PORT` value in root `.env`.

### MCP stdio: `brave_search crashed (exit code: 9)` or Web UI slow to start

Usually the MCP sidecar image was not pulled yet (`mcp/fetch`, `mcp/brave-search`, etc.). Pull images for every `"enabled": true` server in `config/mcp-servers.json`, then recreate `jarvis-web`:

```powershell
docker pull mcp/fetch
docker pull mcp/brave-search
docker compose -f docker-compose.yml -f docker-compose.mcp.yml up -d --force-recreate jarvis-web
```

Init logs may show `MCP servers skipped` — those tools stay out of Tool RAG until the image is available. The recreate above reruns an incomplete MCP sync; after a successful retry, the tools are added to Tool RAG and the completed-sync marker is written. Runtime auto-restart still applies during chat; discovery/sync skips unavailable servers instead of looping restarts.

### Web UI cannot reach host Ollama or another host service

Use `host.docker.internal` instead of `127.0.0.1` or `localhost`. From inside a container, `localhost` means that container itself.

### Local mode: LLM keeps calling `tool_search` (Tool RAG empty)

**Memory sync ≠ tool sync.** API startup logs such as `Syncing data: local → cloud` come from `sync-memory-db.py`. They do **not** populate `tool_definitions` in `jarvis_memory_local.db`. Tool RAG is filled only by `bin/sync-tools.py local`.

Compose init is supposed to run both modes when root `.env` has `JARVIS_SYNC_MODES="cloud local"`, and `data/.docker_tool_profile_synced` may already show `v3:docker:cloud local:<hash>`. If Web UI **local mode** still loops on `tool_search` (bitcoin price, SerpAPI, etc.), the local tools DB may never have been embedded at first boot — run the checks below from **PowerShell** in the repo directory.

**1. Check local tool embeddings** (expect dozens of tools, 768 dimensions for local/Ollama):

```powershell
docker compose exec jarvis-api python bin/check-embeddings-health.py local
```

If **Tool Definitions** shows `Checked: 0 tools` or errors, local Tool RAG was not synced.

**2. Force local tool sync** (safe; re-embeds enabled tools into `jarvis_memory_local.db`):

```powershell
docker compose exec jarvis-api python bin/sync-tools.py local --force
```

If this is an MCP stack, use the tool-sync steps under
[Clean rebuild: MCP stack](#clean-rebuild-mcp-stack) instead; `jarvis-api` cannot
launch MCP sidecars.

Then switch Web UI back to **local** mode and retry the request.

**3. Optional — confirm init logged both sync passes:**

```powershell
docker compose logs jarvis-api jarvis-web 2>&1 | Select-String "Syncing tools"
```

You should see both `cloud mode` and `local mode`. If only cloud appears, or local mode still misbehaves after a healthy health check, the manual `--force` sync above is the supported fix.

**Note:** Docker init follows `JARVIS_SYNC_MODES`, or the selected
`JARVIS_MODE` when that override is unset. UI health/status responses expose
`startup_mode` for mode verification.

### Build fails on Apple Silicon or ARM Windows

Retry with the `DOCKER_DEFAULT_PLATFORM=linux/amd64` fallback shown above. If it works only under emulation, capture the failing package name so native ARM compatibility can be addressed separately.

### Inspect the effective Compose configuration

```bash
docker compose --profile extras config
```

This output should not contain API key values. Runtime secrets belong in the
selected file under the bind-mounted `config/` directory, not in root `.env`.

## Limitations and support boundary

- This path runs Linux containers; it does not turn Jarvis into a native macOS or Windows application.
- Browser UI audio playback can work, but wake word, direct microphone capture, host TTS, and speaker controls remain native-install features.
- Host-specific tools remain disabled unless separately and safely integrated.
- Docker Desktop resource use and the initial image build are substantial.
- `linux/arm64` dependency compatibility still needs automated validation.
- Native Ubuntu and Docker-on-Ubuntu remain the currently tested environments.
- No promises and no formal support.

For the Linux-tested Docker architecture and advanced options, see [README.md](README.md) and [DOCKER_PLANNING.md](../archive/docker/DOCKER_PLANNING.md).
