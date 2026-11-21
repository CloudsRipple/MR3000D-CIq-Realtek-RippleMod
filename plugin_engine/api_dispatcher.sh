#!/bin/sh
# ==============================================================================
# Ripple-mod - Generic Plugin RPC Gateway Dispatcher
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
APP_ROOT="${APP_ROOT:-/var/app}"
PLUGIN_DIR="${PLUGIN_DIR:-$APP_ROOT/plugins}"
PLUGIN_MGR="${PLUGIN_MGR:-$APP_ROOT/plugin_engine/plugin_manager.sh}"
LIB_DIR="${LIB_DIR:-$APP_ROOT/core_system/lib}"

# Intelligent directory fallback
if [ ! -d "$PLUGIN_DIR" ] && [ -d "$SCRIPT_DIR/../plugins" ]; then
    PLUGIN_DIR="$SCRIPT_DIR/../plugins"
fi
if [ ! -f "$PLUGIN_MGR" ] && [ -f "$SCRIPT_DIR/plugin_manager.sh" ]; then
    PLUGIN_MGR="$SCRIPT_DIR/plugin_manager.sh"
fi
if [ ! -d "$LIB_DIR" ] && [ -d "$SCRIPT_DIR/../core_system/lib" ]; then
    LIB_DIR="$SCRIPT_DIR/../core_system/lib"
fi

[ -f "$LIB_DIR/sys_env.sh" ] && . "$LIB_DIR/sys_env.sh"
[ -f "$LIB_DIR/sh_json.sh" ] && . "$LIB_DIR/sh_json.sh"

# Fallback JSON helpers if not loaded from sh_json.sh
if ! command -v json_escape >/dev/null 2>&1; then
    json_escape() {
        [ -z "$1" ] && return 0
        printf '%s' "$1" | awk '{
            gsub(/\\/, "\\\\");
            gsub(/"/, "\\\"");
            gsub(/\t/, "\\t");
            gsub(/\r/, "");
            if (NR > 1) { printf "\\\\n"; }
            printf "%s", $0;
        }'
    }
fi

if ! command -v json_response >/dev/null 2>&1; then
    json_response() {
        status="${1:-0}"
        msg="${2:-}"
        data="${3:-}"
        esc_msg=$(json_escape "$msg")
        if [ -n "$data" ]; then
            printf '{"status":%d,"message":"%s","data":%s}\n' "$status" "$esc_msg" "$data"
        else
            printf '{"status":%d,"message":"%s"}\n' "$status" "$esc_msg"
        fi
    }
fi

if ! command -v json_error >/dev/null 2>&1; then
    json_error() {
        status="${1:-1}"
        err="${2:-Unknown error}"
        esc_err=$(json_escape "$err")
        printf '{"status":%d,"error":"%s"}\n' "$status" "$esc_err"
    }
fi

dispatch_call() {
    plugin="$1"
    cmd="$2"
    shift 2
    args="$@"

    # Sanitize plugin ID
    clean_plugin=$(printf '%s' "$plugin" | tr -cd 'a-zA-Z0-9_-')
    if [ -z "$clean_plugin" ] || [ "$clean_plugin" != "$plugin" ]; then
        json_error 1 "Invalid plugin identifier: '$plugin'"
        return 1
    fi

    target_dir="$PLUGIN_DIR/$clean_plugin"
    if [ ! -d "$target_dir" ]; then
        json_error 1 "Plugin '$clean_plugin' is not installed"
        return 1
    fi

    api_script="$target_dir/api.sh"
    if [ ! -f "$api_script" ]; then
        json_error 1 "Plugin '$clean_plugin' does not implement api.sh"
        return 1
    fi

    # Adaptive timeout: allow long-running package installs (180s), keep normal RPC snappy (20s)
    rpc_timeout=20
    case "$cmd" in
        bootstrap_entware|install_python|opkg_install)
            rpc_timeout=180
            ;;
    esac

    if command -v timeout >/dev/null 2>&1; then
        out=$( timeout "$rpc_timeout" sh "$api_script" "$cmd" "$args" 2>&1 )
        ec=$?
    else
        out=$( sh "$api_script" "$cmd" "$args" 2>&1 )
        ec=$?
    fi

    # Check if output is already valid JSON
    if echo "$out" | grep -q '^[ \t]*{' && echo "$out" | grep -q '}[ \t]*$'; then
        printf '%s\n' "$out"
    else
        json_response "$ec" "Execution completed" "{\"raw_output\":\"$(json_escape "$out")\"}"
    fi
}

case "$1" in
    call)
        dispatch_call "$2" "$3" "$4"
        ;;
    list|install|start|stop|restart|status|enable|disable|uninstall)
        act="$1"
        shift
        if [ -f "$PLUGIN_MGR" ]; then
            sh "$PLUGIN_MGR" "$act" "$@"
        else
            json_error 1 "Plugin manager CLI is missing at $PLUGIN_MGR"
        fi
        ;;
    *)
        # Fallback: support direct plugin name as first argument
        if [ -d "$PLUGIN_DIR/$1" ]; then
            dispatch_call "$1" "$2" "$3"
        else
            json_error 1 "Unknown RPC action or uninstalled plugin '$1'"
        fi
        ;;
esac
exit 0
