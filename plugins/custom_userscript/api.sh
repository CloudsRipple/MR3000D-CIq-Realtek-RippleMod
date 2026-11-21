#!/bin/sh
# ==============================================================================
# Custom UserScript - RPC API (api.sh)
# ==============================================================================

SCRIPT_DIR="$(cd "${0%/*}" 2>/dev/null && pwd)"
[ -z "$SCRIPT_DIR" ] && SCRIPT_DIR="/var/app/plugins/custom_userscript"
CONF_FILE="$SCRIPT_DIR/config.conf"
SCRIPT_FILE="$SCRIPT_DIR/user_run.sh"

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
    get_script)
        content=""
        [ -f "$SCRIPT_FILE" ] && content=$(cat "$SCRIPT_FILE" 2>/dev/null)
        printf '{"status":0,"script":"%s"}\n' "$(json_escape "$content")"
        ;;
    set_script)
        raw_code=$(echo "$args" | tr '&' '\n' | grep "^script=" | cut -d'=' -f2-)
        urldecode "$raw_code" > "$SCRIPT_FILE"
        chmod +x "$SCRIPT_FILE" 2>/dev/null || true
        echo '{"status":0,"message":"Custom script saved successfully"}'
        ;;
    run_now)
        if [ -f "$SCRIPT_FILE" ]; then
            out=$(sh "$SCRIPT_FILE" 2>&1)
            ec=$?
            printf '{"status":%d,"output":"%s"}\n' "$ec" "$(json_escape "$out")"
        else
            echo '{"status":1,"error":"user_run.sh does not exist"}'
        fi
        ;;
    *)
        echo "{\"status\":1,\"error\":\"Unknown custom_userscript command '$cmd'\"}"
        ;;
esac
