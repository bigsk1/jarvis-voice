#!/usr/bin/env bash
# Validate Jarvis's opt-in provider thinking integration.
#
# Default behavior is deterministic and does not call provider APIs:
#   ./tests/integration/test-thinking-mode.sh
#
# Live behavior is explicit because it incurs provider cost and writes normal
# conversation/thinking logs:
#   ./tests/integration/test-thinking-mode.sh --live cloud
#   ./tests/integration/test-thinking-mode.sh --live local
#   ./tests/integration/test-thinking-mode.sh --live all

set -uo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
JARVIS_VENV=${JARVIS_VENV:-"$HOME/jarvis-venv"}
PYTHON="$JARVIS_VENV/bin/python"
ORCHESTRATOR="$ROOT_DIR/orchestrator/orchestrator_v2.py"

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

TOTAL=0
PASSED=0
FAILED=0

usage() {
    cat <<'EOF'
Usage: ./tests/integration/test-thinking-mode.sh [--live cloud|local|all]

Without --live, runs focused unit/catalog tests only (no API calls).
Live mode makes two real LLM requests per selected mode and may incur cost.
EOF
}

record_pass() {
    PASSED=$((PASSED + 1))
    printf '%bPASS%b %s\n' "$GREEN" "$NC" "$1"
}

record_fail() {
    FAILED=$((FAILED + 1))
    printf '%bFAIL%b %s\n' "$RED" "$NC" "$1"
}

run_check() {
    local name=$1
    shift
    TOTAL=$((TOTAL + 1))
    if "$@"; then
        record_pass "$name"
    else
        record_fail "$name"
    fi
}

require_runtime() {
    if [[ ! -x "$PYTHON" ]]; then
        printf '%bERROR:%b Jarvis Python not found at %s\n' "$RED" "$NC" "$PYTHON" >&2
        printf 'Set JARVIS_VENV to the external Jarvis virtual environment.\n' >&2
        exit 2
    fi
    if [[ ! -x "$ORCHESTRATOR" ]]; then
        printf '%bERROR:%b orchestrator is not executable: %s\n' "$RED" "$NC" "$ORCHESTRATOR" >&2
        exit 2
    fi
}

run_static_checks() {
    printf '%bThinking configuration checks (no provider API calls)%b\n' "$CYAN" "$NC"
    run_check \
        "catalog-backed thinking and provider request tests" \
        "$PYTHON" -m pytest -q \
        "$ROOT_DIR/tests/test_thinking_adaptive.py" \
        "$ROOT_DIR/tests/test_llm_provider_anthropic_blocks.py" \
        "$ROOT_DIR/tests/test_model_catalog.py"
}

read_mode_info() {
    local mode=$1
    "$PYTHON" - "$ROOT_DIR" "$mode" <<'PY'
import sys

root, mode = sys.argv[1:]
sys.path.insert(0, f"{root}/lib")

from config_loader import config_scope, get_config_value
from thinking import is_thinking_supported

with config_scope(mode):
    provider = str(get_config_value("LLM_PROVIDER", "ollama" if mode == "local" else "xai")).lower()
    model_key = {
        "anthropic": "ANTHROPIC_MODEL",
        "openai": "OPENAI_MODEL",
        "xai": "XAI_MODEL",
        "ollama": "OLLAMA_MODEL" if mode == "local" else "OLLAMA_CLOUD_MODEL",
    }.get(provider, "")
    model = str(get_config_value(model_key, "")) if model_key else ""

if provider == "anthropic":
    expectation = "true" if is_thinking_supported(provider, model) else "false"
elif provider in {"openai", "xai"}:
    # These providers reason internally but Jarvis does not normally receive
    # displayable raw reasoning text.
    expectation = "false"
else:
    # Ollama's native `think` support and returned field are model/runtime specific.
    expectation = "optional"

print(f"{provider}\t{model}\t{expectation}")
PY
}

run_live_request() {
    local mode=$1
    local debug_thinking=$2
    local expected_display=$3
    local label=$4
    local -a command=("$PYTHON" "$ORCHESTRATOR" "$mode" "Reply with exactly OK.")
    local output

    if [[ "$debug_thinking" == "true" ]]; then
        command+=("--debug-thinking")
    fi

    TOTAL=$((TOTAL + 1))
    printf '\n%b%s%b\n' "$YELLOW" "$label" "$NC"
    printf 'Running:'
    printf ' %q' "${command[@]}"
    printf '\n'

    if ! output=$(JARVIS_DEBUG_THINKING=false "${command[@]}" 2>&1); then
        printf '%s\n' "$output"
        record_fail "$label (request failed)"
        return
    fi

    local found=false
    if grep -q "LLM Thinking:" <<<"$output"; then
        found=true
    fi

    if [[ "$expected_display" == "optional" ]]; then
        record_pass "$label (displayed thinking: $found; model-dependent)"
    elif [[ "$found" == "$expected_display" ]]; then
        record_pass "$label (displayed thinking: $found)"
    else
        printf '%s\n' "$output"
        record_fail "$label (expected display=$expected_display, got $found)"
    fi
}

run_live_mode() {
    local mode=$1
    local provider model expected

    IFS=$'\t' read -r provider model expected < <(read_mode_info "$mode")
    printf '\n%bLive %s mode: provider=%s model=%s%b\n' \
        "$CYAN" "$mode" "$provider" "${model:-<provider default>}" "$NC"

    run_live_request "$mode" false false "$mode without --debug-thinking"
    run_live_request "$mode" true "$expected" "$mode with --debug-thinking"
}

print_summary() {
    printf '\n%bSummary%b: %d passed, %d failed, %d total\n' \
        "$CYAN" "$NC" "$PASSED" "$FAILED" "$TOTAL"
    [[ "$FAILED" -eq 0 ]]
}

main() {
    require_runtime
    cd "$ROOT_DIR" || exit 2

    if [[ $# -eq 0 ]]; then
        run_static_checks
        print_summary
        return
    fi

    if [[ $# -ne 2 || "$1" != "--live" ]]; then
        usage >&2
        exit 2
    fi

    run_static_checks
    case "$2" in
        cloud|local)
            run_live_mode "$2"
            ;;
        all)
            run_live_mode cloud
            run_live_mode local
            ;;
        *)
            usage >&2
            exit 2
            ;;
    esac
    print_summary
}

main "$@"
