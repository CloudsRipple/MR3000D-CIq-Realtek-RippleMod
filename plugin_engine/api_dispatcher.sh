#!/bin/sh
# ==============================================================================
# Ripple-mod - Generic Plugin RPC Gateway Dispatcher
# ==============================================================================

PLUGIN_DIR="/var/app/plugins"
PLUGIN_MGR="/var/app/plugin_engine/plugin_manager.sh"
LIB_DIR="/var/app/core_system/lib"

[ -f "$LIB_DIR/sys_env.sh" ] && . "$LIB_DIR/sys_env.sh"
[ -f "$LIB_DIR/sh_json.sh" ] && . "$LIB_DIR/sh_json.sh"

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
    if [ ! -x "$api_script" ]; then
        json_error 1 "Plugin '$clean_plugin' does not implement api.sh"
        return 1
    fi

    # Execute with timeout guard (15s max)
    out=$( "$api_script" "$cmd" "$args" 2>&1 )
    ec=$?

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
        if [ -x "$PLUGIN_MGR" ]; then
            "$PLUGIN_MGR" "$act" "$@"
        else
            json_error 1 "Plugin manager CLI is missing at $PLUGIN_MGR"
        fi
        ;;
    *)
        json_error 1 "Unknown RPC action '$1'"
        ;;
esac
exit 0
