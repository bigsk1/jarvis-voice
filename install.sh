#!/usr/bin/env bash
# Jarvis Voice — one-shot installer for Ubuntu 24.04+ (Python 3.12+).
# Intended for a fresh clone on a new machine. Does NOT overwrite existing config/*.env.
#
# Typical new machine: clone to ~/jarvis-voice, then:
#   cd ~/jarvis-voice && chmod +x install.sh && ./install.sh
#
# Usage:
#   chmod +x install.sh && ./install.sh
#
# Environment:
#   SKIP_SYSTEM_DEPS=1        Skip sudo apt / install-system-deps.sh (deps already installed)
#   SKIP_JARVIS_HOME_CHECK=1  Allow running when the repo is not at $HOME/jarvis-voice (advanced)
#
# See: docs/INSTALL_GUIDE.md (OpenCode, n8n, and other optional steps are left to you)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

REPO_ROOT="$SCRIPT_DIR"
VENV="${JARVIS_VENV:-$HOME/jarvis-venv}"

die() { echo "ERROR: $*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

ensure_uv_in_path() {
  export PATH="${HOME}/.local/bin:${HOME}/.cargo/bin:${PATH}"
}

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi
  echo "Installing uv (https://docs.astral.sh/uv/) ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ensure_uv_in_path
  command -v uv >/dev/null 2>&1 || die "uv not on PATH after install; add ~/.local/bin to PATH and re-run"
}

require_python312() {
  need_cmd python3
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
    || die "Python 3.12+ required (found: $(python3 -V 2>&1))"
}

# Repo must live at ~/jarvis-voice (aliases + docs assume this). Compare real paths so symlinks OK.
require_jarvis_voice_home() {
  if [[ "${SKIP_JARVIS_HOME_CHECK:-}" == "1" ]]; then
    echo "SKIP_JARVIS_HOME_CHECK=1 — not requiring \$HOME/jarvis-voice"
    return 0
  fi
  local expected="$HOME/jarvis-voice"
  if [[ ! -d "$expected" ]]; then
    echo "ERROR: Clone the repository to exactly: $expected" >&2
    echo "       Then run: cd $expected && ./install.sh" >&2
    exit 1
  fi
  local actual exp
  actual="$(cd "$REPO_ROOT" && pwd -P)"
  exp="$(cd "$expected" && pwd -P)"
  if [[ "$actual" != "$exp" ]]; then
    echo "ERROR: install.sh must be run from \$HOME/jarvis-voice" >&2
    echo "       Repository root is: $actual" >&2
    echo "       Expected:            $exp" >&2
    echo "       Fix: move/re-clone to $expected and run ./install.sh from there." >&2
    echo "       Advanced: SKIP_JARVIS_HOME_CHECK=1 ./install.sh (non-standard layout)" >&2
    exit 1
  fi
}

run_system_deps() {
  if [[ "${SKIP_SYSTEM_DEPS:-}" == "1" ]]; then
    echo "SKIP_SYSTEM_DEPS=1 — skipping install-system-deps.sh"
    return 0
  fi
  if [[ ! -x "${REPO_ROOT}/install-system-deps.sh" ]]; then
    die "install-system-deps.sh not found or not executable in ${REPO_ROOT}"
  fi
  echo "Installing system packages (sudo) ..."
  "${REPO_ROOT}/install-system-deps.sh"
}

create_venv_and_sync() {
  ensure_uv_in_path
  install_uv

  if [[ ! -d "$VENV" ]]; then
    echo "Creating virtual environment: $VENV"
    uv venv "$VENV" --python "$(command -v python3)"
  else
    echo "Using existing virtual environment: $VENV"
  fi

  # Keep ordinary `uv run` / `uv sync` commands on Jarvis's shared venv.
  # uv otherwise ignores VIRTUAL_ENV for project commands and creates .venv.
  if ! grep -q "UV_PROJECT_ENVIRONMENT=.*VIRTUAL_ENV" "${VENV}/bin/activate"; then
    cat >> "${VENV}/bin/activate" <<'EOF'

# Jarvis uses one shared environment outside the repository. Tell uv project
# commands to use it instead of creating jarvis-voice/.venv.
export JARVIS_VENV="$VIRTUAL_ENV"
export UV_PROJECT_ENVIRONMENT="$VIRTUAL_ENV"
EOF
  fi

  # shellcheck source=/dev/null
  source "${VENV}/bin/activate"
  export JARVIS_VENV="$VENV"
  export UV_PROJECT_ENVIRONMENT="$VENV"

  cd "$REPO_ROOT"
  if [[ -f uv.lock ]]; then
    echo "Installing Python dependencies (uv sync from lockfile) ..."
    uv sync --active --no-install-project
  elif [[ -f requirements.txt ]]; then
    echo "No uv.lock — falling back to pip install -r requirements.txt"
    uv pip install -r requirements.txt
  else
    die "No uv.lock or requirements.txt in repo root"
  fi

  echo "Installing Rich (installer summary only) ..."
  uv pip install "rich>=13.0.0"
}

seed_env_files() {
  cd "$REPO_ROOT"
  local created=0
  if [[ ! -f config/cloud.env ]]; then
    cp config/cloud.env.example config/cloud.env
    created=1
    echo "Created config/cloud.env from example (edit API keys and audio devices)."
  else
    echo "Keeping existing config/cloud.env (not overwritten)."
  fi
  if [[ ! -f config/local.env ]]; then
    cp config/local.env.example config/local.env
    created=1
    echo "Created config/local.env from example."
  else
    echo "Keeping existing config/local.env (not overwritten)."
  fi
  chmod 600 config/cloud.env config/local.env 2>/dev/null || true
  if [[ "$created" -eq 1 ]]; then
    echo "Set permissions on env files (chmod 600)."
  fi
}

run_project_setup() {
  cd "$REPO_ROOT"
  # shellcheck source=/dev/null
  source "${VENV}/bin/activate"
  export JARVIS_VENV="$VENV"
  export UV_PROJECT_ENVIRONMENT="$VENV"

  if [[ -x ./setup.sh ]]; then
    echo "Running ./setup.sh ..."
    ./setup.sh
  else
    die "setup.sh missing or not executable"
  fi

  if [[ -x ./setup_tools.sh ]]; then
    echo "Running ./setup_tools.sh ..."
    ./setup_tools.sh
  else
    echo "WARN: setup_tools.sh not found — skip chmod/git fileMode setup" >&2
  fi
}

run_verify_env() {
  cd "$REPO_ROOT"
  # shellcheck source=/dev/null
  source "${VENV}/bin/activate"
  export JARVIS_VENV="$VENV"
  export UV_PROJECT_ENVIRONMENT="$VENV"

  if [[ -x ./verify-env.sh ]]; then
    echo "Running ./verify-env.sh ..."
    ./verify-env.sh || true
  else
    echo "WARN: verify-env.sh not found — skipping environment check" >&2
  fi
}

collect_audio_hints() {
  local play cap
  play="$(aplay -L 2>/dev/null | grep -E '^(plughw|hw):' || true)"
  cap="$(arecord -L 2>/dev/null | grep -E '^(plughw|hw):' || true)"
  export JARVIS_AUDIO_PLAYBACK_LINES="${play:-}"
  export JARVIS_AUDIO_CAPTURE_LINES="${cap:-}"
}

rich_summary() {
  # shellcheck source=/dev/null
  source "${VENV}/bin/activate"
  export JARVIS_VENV="$VENV"
  export UV_PROJECT_ENVIRONMENT="$VENV"
  export JARVIS_INSTALL_ROOT="$REPO_ROOT"
  python3 <<'PY'
import os
from pathlib import Path

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

root = Path(os.environ["JARVIS_INSTALL_ROOT"]).resolve()
venv = Path(os.environ.get("JARVIS_VENV", Path.home() / "jarvis-venv"))

playback = os.environ.get("JARVIS_AUDIO_PLAYBACK_LINES", "").strip()
capture = os.environ.get("JARVIS_AUDIO_CAPTURE_LINES", "").strip()

def block(title: str, body: str) -> str:
    if not body:
        return f"### {title}\n\n*(none detected — try `aplay -L` / `arecord -L` or use `pulse` / `default` in env)*\n"
    return f"### {title}\n\n```\n{body}\n```\n"

md = f"""## Installer finished

Repo: `{root}`  
Venv: `{venv}`  

### What this script did
- System packages via `install-system-deps.sh` (unless `SKIP_SYSTEM_DEPS=1`)
- `uv` + `uv sync` (or `pip` fallback) into `~/jarvis-venv`
- Seed `config/cloud.env` / `config/local.env` **only if missing** (never overwrites)
- Ran `setup.sh`, `verify-env.sh`, and `setup_tools.sh`
- **Did not** run OpenCode workspace, n8n, or plugin installs

### Paths & config
- Repo is expected at **`$HOME/jarvis-voice`** (this run: `{root}`). Seeded `config/*.env` use **`$HOME`** for values like `AUDIO_DIR`; the app expands that on load—no need to hand-edit paths if you keep that layout.
- Full walkthrough: **`docs/INSTALL_GUIDE.md`**

### You must do manually
1. **API keys & providers** — Edit `config/cloud.env` (and `config/local.env` for local/Ollama). Minimum: LLM + STT/TTS keys per `docs/INSTALL_GUIDE.md`.
2. **Audio devices** — Set `IN_DEV` and `OUT_DEV` in both env files. Hints below (typical ALSA `plughw:...` lines; servers often use `pulse` or `default`).
3. **Re-run verify after edits**: `./verify-env.sh`
4. **Tool DB sync** (after keys work):  
   `source {venv}/bin/activate && cd {root} && ./bin/sync-tools.py cloud && ./bin/sync-tools.py local`
5. **Smoke test**:  
   `./orchestrator/orchestrator_v2.py cloud "what time is it"`
6. **Shell commands (optional)**: Run `./update-aliases.sh`, then use the exact `source` command it prints for Bash or Zsh.
7. **Run stack**: `./bin/start` (see `docs/INSTALL_GUIDE.md`)

### Optional (skipped by design)
- OpenCode: `./setup_opencode_workspace.sh` — `docs/opencode/OPENCODE.md`
- n8n / other integrations — not part of this script

{block("Playback devices (speakers) — paste into `OUT_DEV` or pick `pulse`", playback)}
{block("Capture devices (mics) — paste into `IN_DEV` or pick `pulse`", capture)}
"""
console = Console()
console.print()
console.print(Panel(Markdown(md), title="[bold green]Jarvis install — next steps[/bold green]", border_style="green", box=box.ROUNDED))
console.print()
PY
}

# --- main ---
echo "=========================================="
echo "  Jarvis Voice — install.sh"
echo "=========================================="
echo ""

[[ -f "${REPO_ROOT}/pyproject.toml" ]] || die "Run this script from the jarvis-voice repo root (pyproject.toml missing)."
require_jarvis_voice_home
require_python312

run_system_deps
create_venv_and_sync
seed_env_files
run_project_setup
run_verify_env
collect_audio_hints

export JARVIS_VENV="$VENV"
rich_summary

echo "Done."
