#!/usr/bin/env bash
# Validate Jarvis's OpenCode integration without mutating the workspace by default.
#
#   ./tests/integration/test-opencode-integration.sh
#       Focused mocked/unit coverage only; no server or provider calls.
#
#   ./tests/integration/test-opencode-integration.sh --health cloud
#       Read-only health check using the selected mode's URL and authentication.
#
#   ./tests/integration/test-opencode-integration.sh --live cloud
#       Health check plus one real plan-mode OpenCode request. This creates an
#       OpenCode session and can incur provider cost, but does not request files.

set -uo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
JARVIS_VENV=${JARVIS_VENV:-"$HOME/jarvis-venv"}
PYTHON="$JARVIS_VENV/bin/python"

usage() {
    cat <<'EOF'
Usage: ./tests/integration/test-opencode-integration.sh [--health|--live cloud|local]

No arguments: run deterministic OpenCode unit tests only.
--health: read-only check of the configured OpenCode server.
--live: health check plus one real plan-mode request (creates a session/cost).
EOF
}

require_runtime() {
    if [[ ! -x "$PYTHON" ]]; then
        echo "ERROR: Jarvis Python not found at $PYTHON" >&2
        echo "Set JARVIS_VENV to the external Jarvis virtual environment." >&2
        exit 2
    fi
}

run_static_checks() {
    "$PYTHON" -m pytest -q \
        "$ROOT_DIR/tests/test_opencode_client.py" \
        "$ROOT_DIR/tests/test_opencode_tool.py" \
        "$ROOT_DIR/tests/test_check_opencode_sessions.py" \
        "$ROOT_DIR/tests/test_status_updater_opencode_auth.py"
}

run_health_check() {
    local mode=$1
    "$PYTHON" - "$ROOT_DIR" "$mode" <<'PY'
import json
import sys

root, mode = sys.argv[1:]
sys.path.insert(0, f"{root}/lib")

from config_loader import config_scope, get_config_value
from opencode_client import OpenCodeClient

with config_scope(mode):
    enabled = str(get_config_value("OPENCODE_ENABLED", "false")).lower() == "true"
    client = OpenCodeClient()
    health = client.health_check()
    health["configured_enabled"] = enabled
    health["mode"] = mode
    health["base_url"] = client.base_url

print(json.dumps(health, indent=2, sort_keys=True))
raise SystemExit(0 if health.get("healthy") else 1)
PY
}

run_live_check() {
    local mode=$1
    local payload result
    if ! command -v jq >/dev/null; then
        echo "ERROR: jq is required for live OpenCode result validation." >&2
        return 2
    fi
    payload='{"task":"In plan mode, reply with exactly: OpenCode integration OK. Do not create or modify files.","task_type":"test","agent_mode":"plan"}'

    echo "Running one live plan-mode OpenCode request; this creates a session and may incur cost."
    if ! result=$(JARVIS_MODE="$mode" "$PYTHON" "$ROOT_DIR/skills/opencode.py" "$payload"); then
        echo "$result"
        return 1
    fi
    echo "$result" | jq '.'
    jq -e '.ok == true and (.data.session_id | type == "string" and length > 0)' \
        >/dev/null <<<"$result"
}

main() {
    require_runtime
    cd "$ROOT_DIR" || exit 2

    if [[ $# -eq 0 ]]; then
        run_static_checks
        return
    fi
    if [[ $# -ne 2 || ("$1" != "--health" && "$1" != "--live") ]]; then
        usage >&2
        exit 2
    fi
    if [[ "$2" != "cloud" && "$2" != "local" ]]; then
        usage >&2
        exit 2
    fi

    run_static_checks || exit 1
    run_health_check "$2" || exit 1
    if [[ "$1" == "--live" ]]; then
        run_live_check "$2"
    fi
}

main "$@"
