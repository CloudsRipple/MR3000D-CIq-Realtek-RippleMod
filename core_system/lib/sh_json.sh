#!/bin/sh
# ==============================================================================
# Ripple-mod - Pure POSIX Shell JSON Parser & Formatter
# Requires NO python or jq; runs natively on minimal BusyBox ash.
# ==============================================================================

# Escape string for JSON inclusion
json_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' \
                           -e 's/"/\\"/g' \
                           -e 's/\t/\\t/g' \
                           -e 's/\r/\\r/g' \
                           -e 's/\n/\\n/g'
}

# Extract scalar value from JSON string or file by key
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

    line=$(printf '%s\n' "$raw" | tr ',' '\n' | grep "\"$key\"[[:space:]]*:" | head -n 1)
    [ -z "$line" ] && return 0

    val=$(printf '%s' "$line" | sed \
        -e "s/.*\"$key\"[[:space:]]*:[[:space:]]*//" \
        -e 's/^[[:space:]]*"//' \
        -e 's/"[[:space:]}]*$//' \
        -e 's/[[:space:]}]*$//')
    printf '%s' "$val"
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
