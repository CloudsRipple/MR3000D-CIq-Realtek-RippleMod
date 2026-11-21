#!/bin/sh
# ==============================================================================
# Hosts AdBlock DNS - RPC API (api.sh)
# ==============================================================================

SCRIPT_DIR="$(cd "${0%/*}" 2>/dev/null && pwd)"
[ -z "$SCRIPT_DIR" ] && SCRIPT_DIR="/var/app/plugins/hosts_adblock_dns"
CONF_FILE="$SCRIPT_DIR/config.conf"
HOSTS_CONF="/var/app/conf/dnsmasq.d/adblock.conf"

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

urldecode() {
    printf '%s' "$1" | awk '
    BEGIN { for (i = 0; i < 256; i++) hex[sprintf("%02X", i)] = sprintf("%c", i) }
    {
        gsub(/\+/, " ")
        out = ""
        s = $0
        while (match(s, /%[0-9A-Fa-f][0-9A-Fa-f]/)) {
            out = out substr(s, 1, RSTART - 1) hex[toupper(substr(s, RSTART + 1, 2))]
            s = substr(s, RSTART + 3)
        }
        printf "%s%s", (NR > 1 ? "\n" : ""), out s
    }'
}

cmd="$1"
shift
args="$@"

case "$cmd" in
    status)
        sh "$SCRIPT_DIR/status.sh"
        ;;
    start)
        out=$(sh "$SCRIPT_DIR/start.sh" 2>&1)
        esc_out=$(json_escape "$out")
        echo "{\"status\":0,\"message\":\"AdBlock service started\",\"output\":\"$esc_out\"}"
        ;;
    stop)
        out=$(sh "$SCRIPT_DIR/stop.sh" 2>&1)
        esc_out=$(json_escape "$out")
        echo "{\"status\":0,\"message\":\"AdBlock service stopped\",\"output\":\"$esc_out\"}"
        ;;
    get_rules)
        rules=""
        [ -f "$CONF_FILE" ] && rules=$(cat "$CONF_FILE")
        printf '{"status":0,"rules":"%s"}\n' "$(json_escape "$rules")"
        ;;
    set_rules)
        raw_rules=$(echo "$args" | tr '&' '\n' | grep "^rules=" | cut -d'=' -f2-)
        urldecode "$raw_rules" > "$CONF_FILE"
        sh "$SCRIPT_DIR/start.sh" >/dev/null 2>&1 || true
        echo '{"status":0,"message":"Rules updated and applied successfully"}'
        ;;
    *)
        echo "{\"status\":1,\"error\":\"Unknown adblock command '$cmd'\"}"
        ;;
esac
