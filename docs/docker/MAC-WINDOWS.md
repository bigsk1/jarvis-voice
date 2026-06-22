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

cp config/cloud.env.example config/cloud.env
cp config/local.env.example config/local.env
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

Edit `config/cloud.env` and configure the selected cloud LLM and embedding provider credentials. Keep secrets out of root `.env`; that file is only for Compose ports, mode, UID/GID, API auth, and tool profile settings.

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

Copy-Item config/cloud.env.example config/cloud.env
Copy-Item config/local.env.example config/local.env
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

copy config\cloud.env.example config\cloud.env
copy config\local.env.example config\local.env
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

## Cloud and local modes

Cloud mode is the simplest Docker Desktop starting point:

```env
JARVIS_MODE=cloud
```

Set this in root `.env`, then configure the matching provider values in `config/cloud.env`.

For local mode, install and start Ollama on the Mac or Windows host. In `config/local.env`, use the Docker Desktop host address rather than container-local `localhost`:

```env
OLLAMA_BASE_URL="http://host.docker.internal:11434"
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

```bash
docker compose down
git pull
docker compose build --pull
docker compose --profile extras up -d
```

Back up `data/` and your live configuration files before major upgrades. Never commit `config/cloud.env`, `config/local.env`, root `.env`, `jarvis-web/config/web_config.json`, or database files.

## MCP on Docker Desktop

Remote HTTP or SSE MCP servers can work without Docker socket access when their URL is reachable from the Jarvis containers. A server running directly on the Mac or Windows host should normally use `host.docker.internal`, not `localhost`, in `config/mcp-servers.json`.

The tracked `docker` tool profile disables the existing stdio MCP servers because they launch child containers through the host Docker daemon. The optional `docker-compose.mcp.yml` socket workflow is currently tested only on a trusted Linux host. It relies on a Unix socket and numeric socket GID, so it is not included in these macOS and Windows steps.

## Troubleshooting

### A configuration path became a directory

Compose short bind-mount syntax can create a directory when a required source file is missing. Stop the stack, remove the incorrectly created directory, and copy the corresponding example file again:

- `config/cloud.env.example` to `config/cloud.env`
- `config/local.env.example` to `config/local.env`
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

### Web UI cannot reach host Ollama or another host service

Use `host.docker.internal` instead of `127.0.0.1` or `localhost`. From inside a container, `localhost` means that container itself.

### Build fails on Apple Silicon or ARM Windows

Retry with the `DOCKER_DEFAULT_PLATFORM=linux/amd64` fallback shown above. If it works only under emulation, capture the failing package name so native ARM compatibility can be addressed separately.

### Inspect the effective Compose configuration

```bash
docker compose --profile extras config
```

This output should not contain API key values. Runtime secrets belong only in the bind-mounted `config/cloud.env` and `config/local.env` files.

## Limitations and support boundary

- This path runs Linux containers; it does not turn Jarvis into a native macOS or Windows application.
- Browser UI audio playback can work, but wake word, direct microphone capture, host TTS, and speaker controls remain native-install features.
- Host-specific tools remain disabled unless separately and safely integrated.
- Docker Desktop resource use and the initial image build are substantial.
- `linux/arm64` dependency compatibility still needs automated validation.
- Native Ubuntu and Docker-on-Ubuntu remain the currently tested environments.
- No promises and no formal support.

For the Linux-tested Docker architecture and advanced options, see [README.md](README.md) and [DOCKER_PLANNING.md](DOCKER_PLANNING.md).
