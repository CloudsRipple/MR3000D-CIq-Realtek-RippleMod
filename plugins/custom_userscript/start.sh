#!/bin/sh
PDIR="${0%/*}"
LOG="/tmp/plugin_custom_userscript.log"
CONF="$PDIR/config.conf"
[ -f "$CONF" ] && . "$CONF"

echo "[$(date '+%H:%M:%S')] Executing custom_userscript..." > "$LOG"
if [ -n "$AUTORUN_CMD" ]; then
    sh -c "$AUTORUN_CMD" >> "$LOG" 2>&1 || true
fi
if [ -n "$BG_DAEMON_BIN" ] && [ -x "$BG_DAEMON_BIN" ]; then
    "$BG_DAEMON_BIN" $BG_DAEMON_ARGS >> "$LOG" 2>&1 &
    echo $! > /tmp/plugin_custom_userscript.pid
    echo "[$(date '+%H:%M:%S')] Launched daemon $BG_DAEMON_BIN (PID $!)" >> "$LOG"
fi
touch /tmp/plugin_custom_userscript.active
