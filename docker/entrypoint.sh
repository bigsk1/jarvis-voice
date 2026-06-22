#!/usr/bin/env bash
set -Eeuo pipefail

cd /app

umask "${UMASK:-002}"

export JARVIS_VENV="${JARVIS_VENV:-/opt/venv}"
export VIRTUAL_ENV="${VIRTUAL_ENV:-$JARVIS_VENV}"
export PATH="$VIRTUAL_ENV/bin:$PATH"
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export JARVIS_DEPLOYMENT="${JARVIS_DEPLOYMENT:-docker}"

mkdir -p data logs audio

if [ ! -f skills/profiles/docker.json ] && [ -f skills/profiles/examples/docker.json ]; then
  cp skills/profiles/examples/docker.json skills/profiles/docker.json
fi

run_init() {
  if [ "${JARVIS_SKIP_INIT:-0}" = "1" ]; then
    return 0
  fi

  local lock_file="logs/docker-init.lock"
  local init_lock_fd
  exec {init_lock_fd}>"$lock_file"
  echo "Waiting for Docker init lock..."
  flock "$init_lock_fd"

  local status=0
  {
    local profile="${JARVIS_OVERRIDE_JARVIS_TOOL_PROFILE:-${JARVIS_TOOL_PROFILE:-default}}"
    local sync_modes="${JARVIS_SYNC_MODES:-}"
    if [ -z "$sync_modes" ]; then
      sync_modes="${JARVIS_MODE:-cloud}"
    fi
    local profile_path="skills/profiles/${profile}.json"
    local profile_hash="missing"
    if [ -f "$profile_path" ]; then
      profile_hash="$(sha256sum "$profile_path" | cut -d' ' -f1)"
    fi
    local marker="data/.docker_tool_profile_synced"
    local marker_value="${profile}:${sync_modes}:${profile_hash}"
    local needs_sync=0

    if [ "${JARVIS_FORCE_SYNC:-0}" = "1" ]; then
      needs_sync=1
    elif [ ! -f data/jarvis_memory.db ] || [ ! -f data/jarvis_memory_local.db ]; then
      needs_sync=1
    elif [ ! -f "$marker" ] || [ "$(cat "$marker" 2>/dev/null || true)" != "$marker_value" ]; then
      needs_sync=1
    fi

    python bin/migrate-proactive-db.py

    if [ "$needs_sync" = "1" ]; then
      for mode in $sync_modes; do
        echo "Syncing tools for Docker profile in ${mode} mode..."
        python bin/sync-tools.py "$mode"
      done
      printf "%s" "$marker_value" > "$marker"
    else
      echo "Docker init: DBs exist and Docker tool profile is already synced."
    fi
  } || status=$?

  flock -u "$init_lock_fd"
  exec {init_lock_fd}>&-
  return "$status"
}

mode_args=()
if [ "${JARVIS_MODE:-cloud}" = "local" ]; then
  mode_args=(--local)
fi

case "${1:-web}" in
  api)
    run_init
    exec ./bin/jarvis-api "${mode_args[@]}"
    ;;
  web)
    mkdir -p jarvis-web/data/uploads
    run_init
    exec ./bin/jarvis-web "${JARVIS_MODE:-cloud}"
    ;;
  services)
    run_init
    exec ./docker/services.sh
    ;;
  canvas)
    run_init
    exec ./bin/jarvis-canvas
    ;;
  memory)
    run_init
    exec ./bin/jarvis-memory
    ;;
  intelligence)
    run_init
    exec ./bin/jarvis-intelligence
    ;;
  docs)
    run_init
    exec ./bin/jarvis-docs
    ;;
  bash|sh)
    exec "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
