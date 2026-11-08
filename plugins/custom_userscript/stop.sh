#!/bin/sh
LOG="/tmp/plugin_custom_userscript.log"
if [ -f /tmp/plugin_custom_userscript.pid ]; then
    PID=$(cat /tmp/plugin_custom_userscript.pid 2>/dev/null)
    [ -n "$PID" ] && kill -9 "$PID" 2>/dev/null || true
    rm -f /tmp/plugin_custom_userscript.pid
fi
rm -f /tmp/plugin_custom_userscript.active
echo "[$(date '+%H:%M:%S')] Stopped custom_userscript." >> "$LOG"
