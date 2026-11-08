#!/bin/sh
# ==============================================================================
# Custom UserScript - RPC API (api.sh)
# ==============================================================================

SCRIPT_DIR="$(cd "${0%/*}" 2>/dev/null && pwd)"
[ -z "$SCRIPT_DIR" ] && SCRIPT_DIR="/var/app/plugins/custom_userscript"
CONF_FILE="$SCRIPT_DIR/config.conf"
SCRIPT_FILE="$SCRIPT_DIR/user_run.sh"

cmd="$1"
shift
args="$@"

case "$cmd" in
    status)
        "$SCRIPT_DIR/status.sh"
        ;;
    get_script)
        content=""
        [ -f "$SCRIPT_FILE" ] && content=$(cat "$SCRIPT_FILE")
        printf '{"status":0,"script":"%s"}\n' "$(printf '%s' "$content" | sed 's/\\/\\\\/g;s/"/\\"/g' | awk '{printf "%s\\n", $0}')"
        ;;
    set_script)
        new_code=$(echo "$args" | tr '&' '\n' | grep "^script=" | cut -d'=' -f2-)
        printf '%s\n' "$new_code" > "$SCRIPT_FILE"
        chmod +x "$SCRIPT_FILE" 2>/dev/null || true
        echo '{"status":0,"message":"Custom script saved successfully"}'
        ;;
    run_now)
        if [ -x "$SCRIPT_FILE" ]; then
            out=$("$SCRIPT_FILE" 2>&1)
            ec=$?
            echo "{\"status\":$ec,\"output\":\"$(printf '%s' "$out" | sed 's/\\/\\\\/g;s/"/\\"/g')\"}"
        else
            echo '{"status":1,"error":"user_run.sh is empty or not executable"}'
        fi
        ;;
    get_logs)
        n="${args:-80}"
        logs=""
        [ -f /tmp/ripple_mod.log ] && logs=$(tail -n "$n" /tmp/ripple_mod.log 2>/dev/null)
        printf '{"status":0,"logs":"%s"}\n' "$(printf '%s' "$logs" | sed 's/\\/\\\\/g;s/"/\\"/g' | awk '{printf "%s\\n", $0}')"
        ;;
    *)
        echo "{\"status\":1,\"error\":\"Unknown custom_userscript command '$cmd'\"}"
        ;;
esac
