#!/bin/sh
LOG="/tmp/plugin_hosts_adblock_dns.log"
HOSTS_FILE="/var/tmp/hosts"
sed -i '/# MOD_ADBLOCK_START/,/# MOD_ADBLOCK_END/d' "$HOSTS_FILE" 2>/dev/null || true
killall -HUP dnsmasq 2>/dev/null || true
rm -f /tmp/plugin_hosts_adblock_dns.active
echo "[$(date '+%H:%M:%S')] Removed hosts blocklist from $HOSTS_FILE and reloaded dnsmasq." >> "$LOG"
