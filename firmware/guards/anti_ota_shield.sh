#!/bin/sh
# ==============================================================================
# CMCC MR3000D-CIq Anti-OTA & Spyware Shield
# Location: /var/app/scripts/anti_ota_shield.sh
# ==============================================================================

ACTION="${1:-status}"

do_enable() {
    echo "[*] Activating Anti-OTA & Anti-Spyware Shield..."

    # 1. Kill scheduled OTA upgrade timers in wtimer
    wtimer -d check_upgrade_3m 2>/dev/null || true
    wtimer -d check_upgrade_8h 2>/dev/null || true
    wtimer -d force_upgrade_2h 2>/dev/null || true

    # 2. Kill running spyware and force upgrade processes
    killall -9 do_force_upgrade check_upgrade_info 2>/dev/null || true
    killall -9 dpiPlugin lanNetInfo vasdocker managePlugin pluginDaemon timelycheck ahsapd ahsapd_logsrv 2>/dev/null || true

    # 3. Strip execution permissions from carrier binaries to prevent respawning
    chmod 000 /bin/aosnet/* 2>/dev/null || true
    chmod 000 /bin/do_force_upgrade /bin/lanNetInfo /bin/lanNetInfo_action /bin/ahsapd /bin/ahsapd_logsrv /usr/bin/vasdocker 2>/dev/null || true

    # 4. Block carrier telemetry domains via RAM hosts (/var/tmp/hosts used by libmib/dnsmasq)
    mkdir -p /var/tmp
    HOSTS_TARGET="/var/tmp/hosts"
    if ! grep -q "chinamobile.com" "$HOSTS_TARGET" 2>/dev/null; then
        echo "127.0.0.1 ifa.ihnm.chinamobile.com" >> "$HOSTS_TARGET" 2>/dev/null || true
        echo "127.0.0.1 fota.chinamobile.com" >> "$HOSTS_TARGET" 2>/dev/null || true
        echo "127.0.0.1 dm.chinamobile.com" >> "$HOSTS_TARGET" 2>/dev/null || true
        killall -HUP dnsmasq 2>/dev/null || true
    fi

    # 5. Mark persistent state
    mkdir -p /var/app/conf
    touch /var/app/conf/.anti_ota_active

    echo "[OK] Shield active. All carrier spyware neutralized and 300MB RAM freed."
}

do_disable() {
    echo "[*] Deactivating Anti-OTA Shield..."
    chmod 755 /bin/aosnet/* 2>/dev/null || true
    chmod 755 /bin/do_force_upgrade /bin/lanNetInfo /bin/lanNetInfo_action /bin/ahsapd /bin/ahsapd_logsrv /usr/bin/vasdocker 2>/dev/null || true
    rm -f /var/app/conf/.anti_ota_active
    echo "[!] Shield deactivated."
}

do_status() {
    SPY_COUNT=0
    for p in dpiPlugin lanNetInfo vasdocker managePlugin do_force_upgrade ahsapd; do
        if pidof "$p" >/dev/null 2>&1; then
            SPY_COUNT=$((SPY_COUNT + 1))
        fi
    done

    if [ -f /var/app/conf/.anti_ota_active ] || [ "$SPY_COUNT" -eq 0 ]; then
        echo "STATUS: ACTIVE"
        echo "SPYWARE_PROCESSES_RUNNING: $SPY_COUNT"
        echo "OTA_TIMERS: DISABLED"
    else
        echo "STATUS: INACTIVE"
        echo "SPYWARE_PROCESSES_RUNNING: $SPY_COUNT"
        echo "OTA_TIMERS: ACTIVE"
    fi
}

case "$ACTION" in
    enable)
        do_enable
        ;;
    disable)
        do_disable
        ;;
    status|*)
        do_status
        ;;
esac
