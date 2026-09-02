#!/usr/bin/env bash
# Manually run Jarvis Head on a dedicated Linux virtual terminal.

set -euo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HEAD_LAUNCHER="$PROJECT_ROOT/bin/jarvis-head"
UNIT_NAME="jarvis-head-kiosk.service"
DEV_ROOT="${JARVIS_HEAD_KIOSK_DEV_ROOT:-/dev}"
# 80 x 50 ms = 4 s of chvt retries, inside the unit's 5 s TimeoutStopSec.
RETURN_VT_ATTEMPTS="${JARVIS_HEAD_KIOSK_RETURN_VT_ATTEMPTS:-80}"
RETURN_VT_RETRY_SECONDS="${JARVIS_HEAD_KIOSK_RETURN_VT_RETRY_SECONDS:-0.05}"
CONFIG_DIR="${JARVIS_HEAD_KIOSK_CONFIG_DIR:-$PROJECT_ROOT/config}"
SELECTED_MODE=""
RENDERER_CONFIG_KEYS=(
    JARVIS_HEAD_RENDERER
    JARVIS_HEAD_FRAMEBUFFER
    JARVIS_HEAD_FONT
    JARVIS_HEAD_FONT_PX
    JARVIS_HEAD_FACE_BRIGHTNESS
    JARVIS_HEAD_FACE_PRESENCE
    JARVIS_HEAD_SCAN_LEVELS
    JARVIS_HEAD_AMBIENT_SCAN
    JARVIS_HEAD_AMBIENT_SCAN_FIRST_SECONDS
    JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS
    JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS
    JARVIS_HEAD_AMBIENT_SCAN_DOUBLE_CHANCE
)
HEAD_CONFIG_KEYS=(
    JARVIS_HEAD_SOCKET
    JARVIS_HEAD_CELL_ASPECT
    JARVIS_HEAD_IDLE_TIMEOUT
    "${RENDERER_CONFIG_KEYS[@]}"
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
  JARVIS_HEAD_RENDERER=curses     curses cells, or fb for framebuffer pixels
  JARVIS_HEAD_FRAMEBUFFER=/dev/fb0
  JARVIS_HEAD_FONT=PATH           Monospace TrueType font for the fb renderer
  JARVIS_HEAD_FONT_PX=10          fb glyph size, 6-24
  JARVIS_HEAD_FACE_BRIGHTNESS=1.0 fb face gain above the rain floor, 0.2-1.5
  JARVIS_HEAD_FACE_PRESENCE=1.0   how far the face condenses, 0.3-1.0
  JARVIS_HEAD_SCAN_LEVELS=72      signed scan offset; negative makes a dark sweep
  JARVIS_HEAD_AMBIENT_SCAN=false  visual-only scan while the face is visible
  JARVIS_HEAD_AMBIENT_SCAN_FIRST_SECONDS=3.0
  JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS=10.0
  JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS=14.0
  JARVIS_HEAD_AMBIENT_SCAN_DOUBLE_CHANCE=0.15

Examples:
  ./bin/kiosk.sh start
  ./bin/kiosk.sh start -- --fps 45 --color green --cell-aspect 0.4
  ./bin/kiosk.sh start -- --renderer fb --font-px 9
  ./bin/kiosk.sh start -- --renderer fb --face-presence 0.45 --face-brightness 0.4
  ./bin/kiosk.sh start -- --renderer fb --scan-levels -48
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

# Usage: check_number_in_range LABEL VALUE LOW HIGH [given]
# With no fifth argument an empty VALUE means "unset" and passes; with "given"
# (the operator typed the flag) an empty VALUE is an error like any other, so
# `--face-presence=` or a trailing `--face-presence` is refused here instead of
# by the launcher after "started". The shell preflight accepts conventional
# decimal/scientific forms operators use: 0.6, .45, +.45, 5e-1, 1E0. Python's
# float() also accepts exotic spellings such as digit separators; those are
# intentionally outside this shell grammar.
check_number_in_range() {
    local label="$1" value="$2" low="$3" high="$4" given="${5:-}"
    if [[ -z "$value" && -z "$given" ]]; then
        return 0
    fi
    if ! [[ "$value" =~ ^[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?$ ]] \
        || ! awk -v v="$value" -v lo="$low" -v hi="$high" 'BEGIN { exit !(v + 0 >= lo + 0 && v + 0 <= hi + 0) }'; then
        die "$label must be a number between $low and $high (got '$value')"
    fi
}

check_integer_in_range() {
    local label="$1" value="$2" low="$3" high="$4" given="${5:-}"
    if [[ -z "$value" && -z "$given" ]]; then
        return 0
    fi
    if ! [[ "$value" =~ ^[-+]?[0-9]+$ ]] \
        || ! awk -v v="$value" -v lo="$low" -v hi="$high" \
            'BEGIN { exit !(v + 0 >= lo + 0 && v + 0 <= hi + 0) }'; then
        die "$label must be an integer between $low and $high (got '$value')"
    fi
}

run_session() (
    [[ $# -ge 11 ]] || die "invalid internal kiosk session arguments"
    local target_user="$1"
    local target_uid="$2"
    local target_gid="$3"
    local target_home="$4"
    local target_vt="$5"
    local return_vt="$6"
    local socket_override="$7"
    local cell_aspect="$8"
    local idle_timeout="$9"
    shift 9
    local selected_mode="$1"
    shift
    # Optional renderer settings ride along as explicit KEY=VALUE pairs so an
    # operator override in the launching shell survives the clean environment.
    local -a passthrough_env=()
    while [[ "${1:-}" == "--env" ]]; do
        [[ "${2:-}" =~ ^JARVIS_HEAD_[A-Z_]+=.*$ ]] || die "invalid kiosk environment passthrough"
        passthrough_env+=("$2")
        shift 2
    done
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
    ((${#passthrough_env[@]} == 0)) || clean_env+=("${passthrough_env[@]}")

    # shellcheck disable=SC2317  # Invoked indirectly by the EXIT trap.
    cleanup_session() {
        local status=$?
        trap - EXIT
        # On `systemctl stop` every process here is signalled at once, so this
        # runs while the display is still restoring KD_TEXT a few milliseconds
        # later. The kernel refuses to switch away from a console that is still
        # in graphics mode, so retry until it takes (bounded well inside
        # TimeoutStopSec) instead of silently leaving the panel on the kiosk VT.
        local -i attempt
        local chvt_error=""
        for ((attempt = 0; attempt < RETURN_VT_ATTEMPTS; attempt++)); do
            if chvt_error="$(chvt "$return_vt" 2>&1)"; then
                exit "$status"
            fi
            sleep "$RETURN_VT_RETRY_SECONDS"
        done
        # stderr of the transient unit is the journal: a stranded panel must
        # not read as a clean stop.
        echo "WARNING: could not switch the console back to tty$return_vt after" \
            "$RETURN_VT_ATTEMPTS attempts (last error: ${chvt_error:-none});" \
            "press Ctrl+Alt+F$return_vt on the panel" >&2
        exit "$status"
    }
    trap cleanup_session EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM

    # setpriv, not runuser: it execs the launcher directly with the user's ids
    # and groups (video included) and nothing in between. runuser would open a
    # PAM session, catch the group-wide SIGTERM itself, forward a second SIGTERM
    # to the display mid-cleanup, sleep two seconds, and print "Session
    # terminated, killing shell" on the panel.
    echo "Starting Jarvis Head as $target_user (uid $target_uid) on tty$target_vt"
    openvt -c "$target_vt" -s -w -- \
        setpriv --reuid "$target_uid" --regid "$target_gid" --init-groups -- \
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
    local state target_uid target_gid target_home key
    local -a head_args=("$@")
    local -a session_env=()
    for key in "${RENDERER_CONFIG_KEYS[@]}"; do
        [[ -z "${!key:-}" ]] || session_env+=(--env "$key=${!key}")
    done

    # Preflight the framebuffer here, where the operator can read the error.
    # Head flags after -- win over config, exactly as the launcher resolves them;
    # otherwise the transient unit would die asynchronously after "started".
    local effective_renderer="${JARVIS_HEAD_RENDERER:-curses}"
    local effective_framebuffer="${JARVIS_HEAD_FRAMEBUFFER:-/dev/fb0}"
    local effective_face_brightness="${JARVIS_HEAD_FACE_BRIGHTNESS:-}"
    local effective_face_presence="${JARVIS_HEAD_FACE_PRESENCE:-}"
    local effective_scan_levels="${JARVIS_HEAD_SCAN_LEVELS:-}"
    local ambient_scan="${JARVIS_HEAD_AMBIENT_SCAN:-false}"
    local ambient_first="${JARVIS_HEAD_AMBIENT_SCAN_FIRST_SECONDS:-3.0}"
    local ambient_min="${JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS:-10.0}"
    local ambient_max="${JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS:-14.0}"
    local ambient_double="${JARVIS_HEAD_AMBIENT_SCAN_DOUBLE_CHANCE:-0.15}"
    local face_brightness_given="" face_presence_given="" scan_levels_given=""
    local -i index=0
    while ((index < ${#head_args[@]})); do
        case "${head_args[index]}" in
            --renderer)
                effective_renderer="${head_args[index + 1]:-}"
                index+=1
                ;;
            --renderer=*)
                effective_renderer="${head_args[index]#--renderer=}"
                ;;
            --framebuffer)
                effective_framebuffer="${head_args[index + 1]:-}"
                index+=1
                ;;
            --framebuffer=*)
                effective_framebuffer="${head_args[index]#--framebuffer=}"
                ;;
            --face-brightness)
                effective_face_brightness="${head_args[index + 1]:-}"
                face_brightness_given=given
                index+=1
                ;;
            --face-brightness=*)
                effective_face_brightness="${head_args[index]#--face-brightness=}"
                face_brightness_given=given
                ;;
            --face-presence)
                effective_face_presence="${head_args[index + 1]:-}"
                face_presence_given=given
                index+=1
                ;;
            --face-presence=*)
                effective_face_presence="${head_args[index]#--face-presence=}"
                face_presence_given=given
                ;;
            --scan-levels)
                effective_scan_levels="${head_args[index + 1]:-}"
                scan_levels_given=given
                index+=1
                ;;
            --scan-levels=*)
                effective_scan_levels="${head_args[index]#--scan-levels=}"
                scan_levels_given=given
                ;;
            --snapshot|--snapshot=*)
                die "--snapshot renders a PNG and exits; run bin/jarvis-head directly instead of the kiosk"
                ;;
        esac
        index+=1
    done
    case "$effective_renderer" in
        curses|fb) ;;
        *) die "renderer must be curses or fb (got '$effective_renderer')" ;;
    esac
    if [[ "$effective_renderer" == "fb" ]]; then
        [[ -c "$effective_framebuffer" ]] || die "$effective_framebuffer is not a framebuffer device; the fb renderer needs one"
    fi
    # Same windows the launcher enforces, checked here before "started". The
    # effective value is the head flag when given, else config, like the launcher.
    check_number_in_range "face brightness (JARVIS_HEAD_FACE_BRIGHTNESS / --face-brightness)" \
        "$effective_face_brightness" 0.2 1.5 "$face_brightness_given"
    check_number_in_range "face presence (JARVIS_HEAD_FACE_PRESENCE / --face-presence)" \
        "$effective_face_presence" 0.3 1.0 "$face_presence_given"
    check_integer_in_range "scan levels (JARVIS_HEAD_SCAN_LEVELS / --scan-levels)" \
        "$effective_scan_levels" -255 255 "$scan_levels_given"
    case "${ambient_scan,,}" in
        true|false) ;;
        *) die "JARVIS_HEAD_AMBIENT_SCAN must be true or false (got '$ambient_scan')" ;;
    esac
    check_number_in_range "JARVIS_HEAD_AMBIENT_SCAN_FIRST_SECONDS" "$ambient_first" 0 600 given
    check_number_in_range "JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS" "$ambient_min" 0.1 600 given
    check_number_in_range "JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS" "$ambient_max" 0.1 600 given
    check_number_in_range "JARVIS_HEAD_AMBIENT_SCAN_DOUBLE_CHANCE" "$ambient_double" 0 1 given
    if ! awk -v lo="$ambient_min" -v hi="$ambient_max" 'BEGIN { exit !(hi + 0 >= lo + 0) }'; then
        die "JARVIS_HEAD_AMBIENT_SCAN_MAX_SECONDS must be at least JARVIS_HEAD_AMBIENT_SCAN_MIN_SECONDS"
    fi

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
    target_gid="$(id -g "$target_user")"
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
        "$target_user" "$target_uid" "$target_gid" "$target_home" \
        "$target_vt" "$return_vt" "$socket_override" "$cell_aspect" "$idle_timeout" \
        "$SELECTED_MODE" "${session_env[@]}" -- "${head_args[@]}"

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
            require_command setpriv
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
