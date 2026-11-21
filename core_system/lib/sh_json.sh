#!/bin/sh
# ==============================================================================
# Ripple-mod - Pure POSIX Shell JSON Parser & Formatter
# Requires NO python or jq; runs natively on minimal BusyBox ash.
# ==============================================================================

# Escape string for JSON inclusion (supports multi-line strings, quotes, and backslashes)
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

# Extract scalar value from JSON string or file by key (handles commas inside quoted strings)
# Usage: json_get "$json_str" "key"
#    or: json_get "/path/to/file.json" "key"
json_get() {
    src="$1"
    key="$2"
    [ -z "$key" ] && return 1

    if [ -f "$src" ]; then
        raw=$(cat "$src" 2>/dev/null || echo "")
    else
        raw="$src"
    fi

    printf '%s' "$raw" | awk -v k="$key" '
    { buf = buf $0 "\n" }
    END {
        pat = "\"" k "\"[ \t\r\n]*:[ \t\r\n]*"
        if (!match(buf, pat)) exit
        rest = substr(buf, RSTART + RLENGTH)
        c = substr(rest, 1, 1)
        if (c == "\"") {
            out = ""
            i = 2
            n = length(rest)
            while (i <= n) {
                ch = substr(rest, i, 1)
                if (ch == "\\") {
                    i++
                    if (i <= n) out = out substr(rest, i, 1)
                } else if (ch == "\"") {
                    break
                } else {
                    out = out ch
                }
                i++
            }
            printf "%s", out
        } else {
            if (match(rest, /^[^,}\]\r\n \t]+/)) {
                printf "%s", substr(rest, RSTART, RLENGTH)
            }
        }
    }'
}

# Output standard JSON API Response
# Usage: json_response 0 "Operation successful" '{"details": "ok"}'
json_response() {
    status="${1:-0}"
    msg="${2:-}"
    data="${3:-}"

    escaped_msg=$(json_escape "$msg")
    
    if [ -n "$data" ]; then
        printf '{"status":%d,"message":"%s","data":%s}\n' "$status" "$escaped_msg" "$data"
    else
        printf '{"status":%d,"message":"%s"}\n' "$status" "$escaped_msg"
    fi
}

# Output standard JSON Error Response
json_error() {
    status="${1:-1}"
    err="${2:-Unknown error}"
    escaped_err=$(json_escape "$err")
    printf '{"status":%d,"error":"%s"}\n' "$status" "$escaped_err"
}
