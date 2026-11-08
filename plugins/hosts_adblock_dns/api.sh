#!/bin/sh
# ==============================================================================
# Hosts AdBlock DNS - RPC API (api.sh)
# ==============================================================================

SCRIPT_DIR="$(cd "${0%/*}" 2>/dev/null && pwd)"
[ -z "$SCRIPT_DIR" ] && SCRIPT_DIR="/var/app/plugins/hosts_adblock_dns"
CONF_FILE="$SCRIPT_DIR/config.conf"
HOSTS_CONF="/var/app/conf/dnsmasq.d/adblock.conf"

cmd="$1"
shift
args="$@"

case "$cmd" in
    status)
        "$SCRIPT_DIR/status.sh"
        ;;
    start)
        out=$("$SCRIPT_DIR/start.sh" 2>&1)
        echo "{\"status\":0,\"message\":\"AdBlock service started\",\"output\":\"$out\"}"
        ;;
    stop)
        out=$("$SCRIPT_DIR/stop.sh" 2>&1)
        echo "{\"status\":0,\"message\":\"AdBlock service stopped\",\"output\":\"$out\"}"
        ;;
    get_rules)
        rules=""
        [ -f "$CONF_FILE" ] && rules=$(cat "$CONF_FILE")
        printf '{"status":0,"rules":"%s"}\n' "$(printf '%s' "$rules" | sed 's/\\/\\\\/g;s/"/\\"/g' | awk '{printf "%s\\n", $0}')"
        ;;
    set_rules)
        # Parse rules argument
        new_rules=$(echo "$args" | tr '&' '\n' | grep "^rules=" | cut -d'=' -f2-)
        printf '%s\n' "$new_rules" > "$CONF_FILE"
        "$SCRIPT_DIR/start.sh" >/dev/null 2>&1 || true
        echo '{"status":0,"message":"Rules updated and applied successfully"}'
        ;;
    *)
        echo "{\"status\":1,\"error\":\"Unknown adblock command '$cmd'\"}"
        ;;
esac
