#!/usr/bin/env bash
# Manually run Jarvis Head on a dedicated Linux virtual terminal.

set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HEAD_LAUNCHER="$PROJECT_ROOT/bin/jarvis-head"
UNIT_NAME="jarvis-head-kiosk.service"
DEV_ROOT="${JARVIS_HEAD_KIOSK_DEV_ROOT:-/dev}"
CONFIG_DIR="${JARVIS_HEAD_KIOSK_CONFIG_DIR:-$PROJECT_ROOT/config}"
SELECTED_MODE=""
HEAD_CONFIG_KEYS=(
    JARVIS_HEAD_SOCKET
    JARVIS_HEAD_CELL_ASPECT
    JARVIS_HEAD_IDLE_TIMEOUT
    JARVIS_HEAD_KIOSK_VT
    JARVIS_HEAD_RETURN_VT
    JARVIS_HEAD_KIOSK_USER
    JARVIS_HEAD_KIOSK_CPU_QUOTA
    JARVIS_HEAD_KIOSK_MEMORY_MAX
)

usage() {
    cat <<'EOF'
Usage: ./bin/kiosk.sh start [-- JARVIS_HEAD_ARGS...]
       ./bin/kiosk.sh stop
       ./bin/kiosk.sh status

Manually runs Jarvis Head on a dedicated Linux virtual terminal using a
transient systemd service. Nothing is enabled at boot and bin/start is not
changed.

Environment overrides:
  JARVIS_HEAD_KIOSK_VT=8          Dedicated VT (2-63; never the login VT)
  JARVIS_HEAD_RETURN_VT=N         VT restored on exit (default: active VT)
  JARVIS_HEAD_KIOSK_USER=USER     Non-root display user (default: caller)
  JARVIS_HEAD_KIOSK_CPU_QUOTA=50% Transient service CPU limit
  JARVIS_HEAD_KIOSK_MEMORY_MAX=256M

Examples:
  ./bin/kiosk.sh start
  ./bin/kiosk.sh start -- --fps 45 --color green --cell-aspect 0.4
  ./bin/kiosk.sh status
  ./bin/kiosk.sh stop
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 2
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

validate_vt() {
    local label="$1"
    local value="$2"
    [[ "$value" =~ ^[0-9]+$ ]] || die "$label must be a number from 1 to 63"
    ((value >= 1 && value <= 63)) || die "$label must be a number from 1 to 63"
}

as_root() {
    if ((EUID == 0)); then
        "$@"
    else
        sudo "$@"
    fi
}

unit_state() {
    local state
    state="$(systemctl show "$UNIT_NAME" --property=ActiveState --value 2>/dev/null || true)"
    printf '%s' "${state:-inactive}"
}

load_kiosk_config() {
    SELECTED_MODE="${JARVIS_MODE:-cloud}"
    case "$SELECTED_MODE" in
        cloud|local) ;;
        *) die "JARVIS_MODE must be cloud or local" ;;
    esac

    local config_file="$CONFIG_DIR/$SELECTED_MODE.env"
    local key override_key
    local -A explicit_values=()
    local -A explicit_keys=()
    for key in "${HEAD_CONFIG_KEYS[@]}"; do
        if [[ -v $key ]]; then
            explicit_keys["$key"]=1
            explicit_values["$key"]="${!key}"
        fi
    done

    if [[ -f "$config_file" ]]; then
        set -a
        # shellcheck disable=SC1090  # Runtime mode selects the trusted Jarvis env file.
        source "$config_file"
        set +a
    fi

    for key in "${HEAD_CONFIG_KEYS[@]}"; do
        override_key="JARVIS_OVERRIDE_$key"
        if [[ -v $override_key ]]; then
            printf -v "$key" '%s' "${!override_key}"
            export "${key?}"
        elif [[ -n "${explicit_keys[$key]:-}" ]]; then
            printf -v "$key" '%s' "${explicit_values[$key]}"
            export "${key?}"
        fi
    done
    export JARVIS_MODE="$SELECTED_MODE"
}

run_session() (
    [[ $# -ge 10 ]] || die "invalid internal kiosk session arguments"
    local target_user="$1"
    local target_uid="$2"
    local target_home="$3"
    local target_vt="$4"
    local return_vt="$5"
    local socket_override="$6"
    local cell_aspect="$7"
    local idle_timeout="$8"
    shift 8
    local selected_mode="$1"
    shift
    [[ "${1:-}" == "--" ]] || die "invalid internal kiosk argument separator"
    shift
    local -a head_args=("$@")
    local -a clean_env=(
        env -i
        "HOME=$target_home"
        "USER=$target_user"
        "LOGNAME=$target_user"
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        "TERM=linux"
        "LANG=${LANG:-C.UTF-8}"
        "PYTHONUNBUFFERED=1"
        "JARVIS_MODE=$selected_mode"
    )

    [[ -z "$socket_override" ]] || clean_env+=("JARVIS_HEAD_SOCKET=$socket_override")
    [[ -z "$cell_aspect" ]] || clean_env+=("JARVIS_HEAD_CELL_ASPECT=$cell_aspect")
    [[ -z "$idle_timeout" ]] || clean_env+=("JARVIS_HEAD_IDLE_TIMEOUT=$idle_timeout")

    # shellcheck disable=SC2317  # Invoked indirectly by the EXIT trap.
    cleanup_session() {
        local status=$?
        trap - EXIT
        chvt "$return_vt" >/dev/null 2>&1 || true
        exit "$status"
    }
    trap cleanup_session EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM

    echo "Starting Jarvis Head as $target_user (uid $target_uid) on tty$target_vt"
    openvt -c "$target_vt" -s -w -- \
        runuser -u "$target_user" -- \
        "${clean_env[@]}" \
        "$HEAD_LAUNCHER" "${head_args[@]}"
)

start_kiosk() {
    local target_vt="${JARVIS_HEAD_KIOSK_VT:-8}"
    local return_vt="${JARVIS_HEAD_RETURN_VT:-}"
    local target_user="${JARVIS_HEAD_KIOSK_USER:-${SUDO_USER:-$(id -un)}}"
    local cpu_quota="${JARVIS_HEAD_KIOSK_CPU_QUOTA:-50%}"
    local memory_max="${JARVIS_HEAD_KIOSK_MEMORY_MAX:-256M}"
    local socket_override="${JARVIS_HEAD_SOCKET:-}"
    local cell_aspect="${JARVIS_HEAD_CELL_ASPECT:-}"
    local idle_timeout="${JARVIS_HEAD_IDLE_TIMEOUT:-}"
    local state target_uid target_home
    local -a head_args=("$@")

    if [[ -n "$socket_override" && "$socket_override" != /* ]]; then
        die "JARVIS_HEAD_SOCKET must be an absolute path"
    fi
    validate_vt "JARVIS_HEAD_KIOSK_VT" "$target_vt"
    ((target_vt >= 2)) || die "tty1 is reserved as the local recovery console"
    [[ -c "$DEV_ROOT/tty$target_vt" ]] || die "$DEV_ROOT/tty$target_vt is not a virtual console"
    [[ -x "$HEAD_LAUNCHER" ]] || die "Jarvis Head launcher is missing: $HEAD_LAUNCHER"

    if [[ "$target_user" == "root" ]]; then
        die "run the kiosk as a non-root user so wake, TTS, and the display share one socket"
    fi
    id "$target_user" >/dev/null 2>&1 || die "unknown kiosk user: $target_user"
    target_uid="$(id -u "$target_user")"
    target_home="$(getent passwd "$target_user" | awk -F: '{print $6}')"
    [[ -n "$target_home" ]] || die "cannot resolve home directory for $target_user"

    state="$(unit_state)"
    case "$state" in
        active|activating)
            if ((EUID != 0)); then
                require_command sudo
                sudo -v
            fi
            as_root chvt "$target_vt"
            echo "Jarvis Head kiosk is already running ($state); switched to tty$target_vt."
            return 0
            ;;
        deactivating)
            die "Jarvis Head kiosk is still stopping; retry in a moment"
            ;;
    esac

    if systemctl is-active --quiet "getty@tty$target_vt.service" 2>/dev/null; then
        die "tty$target_vt has an active getty; choose an unused VT"
    fi

    if ((EUID != 0)); then
        require_command sudo
        sudo -v
    fi
    if [[ -z "$return_vt" ]]; then
        return_vt="$(as_root fgconsole)"
    fi
    validate_vt "JARVIS_HEAD_RETURN_VT" "$return_vt"
    [[ "$return_vt" != "$target_vt" ]] || die "return VT must differ from kiosk tty$target_vt"
    [[ -c "$DEV_ROOT/tty$return_vt" ]] || die "$DEV_ROOT/tty$return_vt is not a virtual console"

    as_root systemctl reset-failed "$UNIT_NAME" >/dev/null 2>&1 || true
    as_root systemd-run \
        --unit="$UNIT_NAME" \
        --collect \
        --service-type=exec \
        --description="Jarvis Head manual VT kiosk" \
        --property=KillMode=control-group \
        --property=TimeoutStopSec=5s \
        --property=SendSIGKILL=yes \
        --property="CPUQuota=$cpu_quota" \
        --property="MemoryMax=$memory_max" \
        -- \
        "$SCRIPT_PATH" __session \
        "$target_user" "$target_uid" "$target_home" \
        "$target_vt" "$return_vt" "$socket_override" "$cell_aspect" "$idle_timeout" \
        "$SELECTED_MODE" -- "${head_args[@]}"

    echo "Jarvis Head kiosk started on tty$target_vt."
    echo "Exit there with q, Escape, or Ctrl+C; use Ctrl+Alt+F$return_vt for the local console."
    echo "Remote stop: ./bin/kiosk.sh stop"
}

stop_kiosk() {
    local state
    state="$(unit_state)"
    case "$state" in
        inactive|failed)
            echo "Jarvis Head kiosk is not running ($state)."
            return 0
            ;;
    esac
    if ((EUID != 0)); then
        require_command sudo
        sudo -v
    fi
    as_root systemctl stop "$UNIT_NAME"
    echo "Jarvis Head kiosk stopped."
}

show_status() {
    local state
    state="$(unit_state)"
    echo "Jarvis Head kiosk: $state"
    if [[ "$state" != "inactive" ]]; then
        systemctl show "$UNIT_NAME" \
            --property=SubState \
            --property=MainPID \
            --property=ExecMainStatus \
            --no-pager 2>/dev/null || true
    fi
}

main() {
    local action="${1:-}"
    [[ -n "$action" ]] || { usage; exit 2; }
    shift || true

    if [[ "$action" == "__session" ]]; then
        run_session "$@"
        return
    fi

    require_command systemctl
    case "$action" in
        start)
            require_command systemd-run
            require_command openvt
            require_command chvt
            require_command fgconsole
            require_command runuser
            if [[ "${1:-}" == "--" ]]; then
                shift
            elif [[ $# -gt 0 ]]; then
                die "place Jarvis Head arguments after --"
            fi
            load_kiosk_config
            start_kiosk "$@"
            ;;
        stop)
            [[ $# -eq 0 ]] || die "stop does not accept arguments"
            stop_kiosk
            ;;
        status)
            [[ $# -eq 0 ]] || die "status does not accept arguments"
            show_status
            ;;
        --help|-h|help)
            usage
            ;;
        *)
            usage >&2
            die "unknown action: $action"
            ;;
    esac
}

main "$@"
