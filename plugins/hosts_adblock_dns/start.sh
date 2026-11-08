#!/bin/sh
PDIR="${0%/*}"
LOG="/tmp/plugin_hosts_adblock_dns.log"
CONF="$PDIR/config.conf"
[ -f "$CONF" ] && . "$CONF"

mkdir -p /var/tmp
HOSTS_FILE="/var/tmp/hosts"
touch "$HOSTS_FILE" 2>/dev/null || true

sed -i '/# MOD_ADBLOCK_START/,/# MOD_ADBLOCK_END/d' "$HOSTS_FILE" 2>/dev/null || true
{
    echo "# MOD_ADBLOCK_START"
    if [ "${BLOCK_VENDOR_TELEMETRY:-1}" = "1" ]; then
        echo "0.0.0.0 ahsap.hejiaqin.cn"
        echo "0.0.0.0 andlink.vendor.local"
        echo "0.0.0.0 ota.vendor.local"
        echo "0.0.0.0 dpi.vendor.local"
        echo "0.0.0.0 rms.vendor.local"
    fi
    if [ -n "$CUSTOM_DOMAINS" ]; then
        for dom in $(echo "$CUSTOM_DOMAINS" | tr ',;' ' '); do
            [ -n "$dom" ] && echo "0.0.0.0 $dom"
        done
    fi
    echo "# MOD_ADBLOCK_END"
} >> "$HOSTS_FILE" 2>/dev/null

killall -HUP dnsmasq 2>/dev/null || true
touch /tmp/plugin_hosts_adblock_dns.active
echo "[$(date '+%H:%M:%S')] Applied hosts blocklist to $HOSTS_FILE and reloaded dnsmasq." > "$LOG"
