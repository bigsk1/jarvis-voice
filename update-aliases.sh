#!/usr/bin/env bash
# Install the managed Jarvis alias source block for Bash or Zsh.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
START_MARKER="# >>> Jarvis Voice Assistant >>>"
END_MARKER="# <<< Jarvis Voice Assistant <<<"
SHELL_CHOICE=""
RCFILE=""
ASSUME_YES=false

usage() {
    cat <<'EOF'
Usage: ./update-aliases.sh [--shell bash|zsh] [--rc-file PATH] [--yes]

Installs one managed source block in ~/.bashrc or ~/.zshrc. The commands live
in the tracked .jarvis-aliases file, so future git pulls update them without
copying another block into your shell configuration.

Options:
  --shell bash|zsh  Override shell detection.
  --rc-file PATH    Write a specific shell RC file.
  --yes, -y         Replace legacy Jarvis definitions without prompting.
  --help, -h        Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --shell)
            [[ $# -ge 2 ]] || { echo "ERROR: --shell requires bash or zsh" >&2; exit 2; }
            SHELL_CHOICE=$2
            shift 2
            ;;
        --rc-file)
            [[ $# -ge 2 ]] || { echo "ERROR: --rc-file requires a path" >&2; exit 2; }
            RCFILE=$2
            shift 2
            ;;
        --yes|-y)
            ASSUME_YES=true
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -n "$SHELL_CHOICE" && "$SHELL_CHOICE" != "bash" && "$SHELL_CHOICE" != "zsh" ]]; then
    echo "ERROR: --shell must be bash or zsh" >&2
    exit 2
fi

detect_shell() {
    local parent_shell configured_shell account_shell
    parent_shell=$(ps -p "$PPID" -o comm= 2>/dev/null | sed 's/^-//' | xargs || true)
    configured_shell=${SHELL##*/}
    account_shell=$(getent passwd "$(id -un)" 2>/dev/null | awk -F: '{print $7}' | awk -F/ '{print $NF}' || true)

    case "$parent_shell" in zsh|bash) echo "$parent_shell"; return;; esac
    case "$configured_shell" in zsh|bash) echo "$configured_shell"; return;; esac
    case "$account_shell" in zsh|bash) echo "$account_shell"; return;; esac
    echo bash
}

if [[ -z "$SHELL_CHOICE" ]]; then
    SHELL_CHOICE=$(detect_shell)
fi
if [[ -z "$RCFILE" ]]; then
    if [[ "$SHELL_CHOICE" == "zsh" ]]; then
        RCFILE="$HOME/.zshrc"
    else
        RCFILE="$HOME/.bashrc"
    fi
fi
RCFILE=${RCFILE/#\~/$HOME}

mkdir -p "$(dirname "$RCFILE")"
touch "$RCFILE"

start_count=$(grep -Fc "$START_MARKER" "$RCFILE" || true)
end_count=$(grep -Fc "$END_MARKER" "$RCFILE" || true)
if [[ "$start_count" -ne "$end_count" ]]; then
    echo "ERROR: Incomplete Jarvis managed block in $RCFILE; repair its markers before retrying." >&2
    exit 2
fi
has_managed_block=false
[[ "$start_count" -gt 0 ]] && has_managed_block=true

legacy_pattern='^(alias )?(jarvis|jarvis-local|jarvis-cli|jarvis-local-cli|jarvis-cli-json|jarvis-local-cli-json|jarvis-d|jarvis-start|jarvis-start-local|jarvis-stop|jarvis-status|jarvis-web|jarvis-web-local|jarvis-api|jarvis-api-local|jarvis-cd|jarvis-env|jarvis-logs|jarvis-help)(=|\(\))'
has_legacy=false
if grep -Eq "$legacy_pattern" "$RCFILE"; then
    has_legacy=true
fi

if [[ "$has_legacy" == true && "$has_managed_block" == false && "$ASSUME_YES" == false ]]; then
    echo "Existing Jarvis aliases/functions found in $RCFILE."
    read -r -p "Replace them with the managed Jarvis block? (y/N): " replace
    if [[ "$replace" != "y" && "$replace" != "Y" ]]; then
        echo "Aborted. No changes made."
        exit 0
    fi
fi

backup=""
if [[ -s "$RCFILE" && ("$has_managed_block" == true || "$has_legacy" == true) ]]; then
    backup="$RCFILE.backup-$(date +%Y%m%d-%H%M%S)"
    cp "$RCFILE" "$backup"
fi

temp_file=$(mktemp)
trap 'rm -f "$temp_file"' EXIT

awk -v start="$START_MARKER" -v end="$END_MARKER" '
    $0 == start { in_managed = 1; next }
    in_managed && $0 == end { in_managed = 0; next }
    !in_managed { print }
' "$RCFILE" > "$temp_file"

# Remove exact legacy alias lines and the four old CLI function bodies. Other
# user shell configuration is preserved verbatim.
sed -E -i \
    -e '/^alias (jarvis|jarvis-local|jarvis-cli|jarvis-local-cli|jarvis-cli-json|jarvis-local-cli-json|jarvis-d|jarvis-start|jarvis-start-local|jarvis-stop|jarvis-status|jarvis-web|jarvis-web-local|jarvis-api|jarvis-api-local|jarvis-cd|jarvis-env|jarvis-logs|jarvis-help|say|say-local|question|question-local|question-mic|question-mic-local)=/d' \
    "$temp_file"
awk '
    /^(jarvis-cli|jarvis-local-cli|jarvis-cli-json|jarvis-local-cli-json)\(\)[[:space:]]*\{/ { in_legacy_function = 1; next }
    in_legacy_function && /^}/ { in_legacy_function = 0; next }
    !in_legacy_function { print }
' "$temp_file" > "$temp_file.cleaned"
mv "$temp_file.cleaned" "$temp_file"

{
    cat "$temp_file"
    [[ ! -s "$temp_file" ]] || printf '\n'
    printf '%s\n' "$START_MARKER"
    printf 'export JARVIS_ROOT=%q\n' "$SCRIPT_DIR"
    # shellcheck disable=SC2016
    printf 'source "$JARVIS_ROOT/.jarvis-aliases"\n'
    printf '%s\n' "$END_MARKER"
} > "$RCFILE"

echo "Jarvis shell setup updated"
echo "  Shell: $SHELL_CHOICE"
echo "  RC file: $RCFILE"
[[ -z "$backup" ]] || echo "  Backup: $backup"
echo
echo "Reload with: source $RCFILE"
echo
echo "Common commands:"
echo "  jarvis / jarvis-local             Wake-word listeners"
echo "  jarvis-cli / jarvis-local-cli     Text-only orchestrator"
echo "  jarvis-d                           TUI dashboard"
echo "  jarvis-start / jarvis-start-local Start all services"
echo "  jarvis-stop / jarvis-status       Stop or inspect all sessions"
echo "  jarvis-web[-local]                 Start Web UI"
echo "  jarvis-api[-local]                 Start API"
echo "  jarvis-help                        Show the complete command list"
