#!/usr/bin/env bash
set -Eeuo pipefail

cd "${JARVIS_APP_ROOT:-/app}"

umask "${UMASK:-002}"

export JARVIS_VENV="${JARVIS_VENV:-/opt/venv}"
export VIRTUAL_ENV="${VIRTUAL_ENV:-$JARVIS_VENV}"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$VIRTUAL_ENV}"
export PATH="$VIRTUAL_ENV/bin:$PATH"
export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
export JARVIS_DEPLOYMENT="${JARVIS_DEPLOYMENT:-docker}"

mkdir -p data logs audio

resolved_mode="$(./bin/resolve-jarvis-mode "${JARVIS_MODE:-cloud}")"
export JARVIS_MODE="$resolved_mode"
if [ ! -f "config/${JARVIS_MODE}.env" ]; then
  echo "Required Docker startup config not found: config/${JARVIS_MODE}.env" >&2
  exit 1
fi

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
    # Bump when marker semantics change so older partial-sync markers are retried.
    local marker_value="v3:${profile}:${sync_modes}:${profile_hash}"
    local needs_sync=0
    local can_sync_profile=1

    # Only the jarvis-web service in docker-compose.mcp.yml has the MCP image,
    # Docker socket, and strict partial-sync handling. If docker-mcp was set as
    # the stack-wide profile, base services must defer instead of writing a
    # misleading completed marker after failing to launch sidecars.
    if [ "${JARVIS_DEFER_TOOL_SYNC:-0}" = "1" ]; then
      can_sync_profile=0
    elif [ "$profile" = "docker-mcp" ] && [ "${JARVIS_MCP_SYNC_STRICT:-0}" != "1" ]; then
      can_sync_profile=0
    fi

    local missing_selected_db=0
    for mode in $sync_modes; do
      case "$mode" in
        cloud) db_path="data/jarvis_memory.db" ;;
        local) db_path="data/jarvis_memory_local.db" ;;
        *) echo "Invalid JARVIS_SYNC_MODES entry: $mode" >&2; return 2 ;;
      esac
      if [ ! -f "$db_path" ]; then
        missing_selected_db=1
      fi
    done

    if [ "${JARVIS_FORCE_SYNC:-0}" = "1" ]; then
      needs_sync=1
    elif [ "$missing_selected_db" = "1" ]; then
      needs_sync=1
    elif [ ! -f "$marker" ] || [ "$(cat "$marker" 2>/dev/null || true)" != "$marker_value" ]; then
      needs_sync=1
    fi

    for mode in $sync_modes; do
      db_path="data/jarvis_memory$([ "$mode" = local ] && echo _local).db"
      python -c "from lib.memory_db import MemoryDB; db=MemoryDB('$db_path'); db.close()"
      python bin/migrate-proactive-db.py "$mode"
    done

    if [ "$needs_sync" = "1" ] && [ "$can_sync_profile" = "0" ]; then
      echo "Docker init: deferring tool sync to the MCP-capable jarvis-web service."
    elif [ "$needs_sync" = "1" ]; then
      local mcp_sync_incomplete=0
      local sync_status=0
      for mode in $sync_modes; do
        echo "Syncing tools for Docker profile in ${mode} mode..."
        if python bin/sync-tools.py "$mode"; then
          :
        else
          sync_status=$?
          if [ "$sync_status" = "3" ]; then
            mcp_sync_incomplete=1
            echo "MCP tool sync incomplete in ${mode} mode; continuing startup and retrying next time." >&2
          elif [ "$sync_status" = "4" ]; then
            mcp_sync_incomplete=1
            echo "Tool embedding provider unavailable in ${mode} mode; preserving the existing Tool RAG index, continuing startup, and retrying next time." >&2
          elif [ "$sync_status" = "5" ]; then
            mcp_sync_incomplete=1
            echo "Tool sync incomplete in ${mode} mode; continuing startup without a completion marker so the next start retries." >&2
          else
            status=$sync_status
            break
          fi
        fi
      done
      if [ "$status" != "0" ] || [ "$mcp_sync_incomplete" = "1" ]; then
        rm -f "$marker"
      else
        printf "%s" "$marker_value" > "$marker"
      fi
    else
      echo "Docker init: DBs exist and Docker tool profile is already synced."
    fi
  } || status=$?

  flock -u "$init_lock_fd"
  exec {init_lock_fd}>&-
  return "$status"
}

mode_args=()
if [ "$JARVIS_MODE" = "local" ]; then
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
    exec ./bin/jarvis-web "$JARVIS_MODE"
    ;;
  services)
    run_init
    exec ./docker/services.sh
    ;;
  canvas)
    run_init
    exec ./bin/jarvis-canvas "$JARVIS_MODE"
    ;;
  memory)
    run_init
    exec ./bin/jarvis-memory "$JARVIS_MODE"
    ;;
  intelligence)
    run_init
    exec ./bin/jarvis-intelligence "$JARVIS_MODE"
    ;;
  docs)
    run_init
    exec ./bin/jarvis-docs "$JARVIS_MODE"
    ;;
  bash|sh)
    exec "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
