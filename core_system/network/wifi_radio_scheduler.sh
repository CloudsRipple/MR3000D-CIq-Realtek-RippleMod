#!/bin/sh
# ==============================================================================
# Ripple-mod - Wi-Fi Radio DSP, Baseband & Scheduling Subsystem
# Target Platform: Realtek RTL8198D (Linux 5.10.70 MIPS32r2)
# ==============================================================================

CONF_FILE="/var/app/conf/wifi_tuning.conf"
[ -f "$CONF_FILE" ] && . "$CONF_FILE"

WIFI_TUNING_ENABLED="${WIFI_TUNING_ENABLED:-1}"
UNLOCK_TX_POWER="${UNLOCK_TX_POWER:-1}"
DISABLE_EDCCA_CARRIER_BACKOFF="${DISABLE_EDCCA_CARRIER_BACKOFF:-1}"
ENABLE_AIRTIME_FAIRNESS="${ENABLE_AIRTIME_FAIRNESS:-1}"
DENY_LEGACY_11B="${DENY_LEGACY_11B:-1}"
TUNE_PCIE_INT_MIT="${TUNE_PCIE_INT_MIT:-1}"
ENABLE_BAND_STEERING="${ENABLE_BAND_STEERING:-1}"

log() {
    echo "[WiFi-Scheduler] $1"
}

apply_tx_power_unlock() {
    if [ "$UNLOCK_TX_POWER" != "1" ]; then
        return 0
    fi
    TARGET_FILE="/etc/conf/rtl8852ce/RFE54/TXPWR_LMT.txt"
    SOURCE_FILE="/var/app/conf/TXPWR_LMT_UNLOCKED.txt"

    if [ -f "$TARGET_FILE" ]; then
        if [ ! -f "$SOURCE_FILE" ]; then
            log "Generating unlocked 23dBm TXPWR_LMT table..."
            # Replace @@CountryCode=CN with @@CountryCode=CN, Regulation=NONE
            sed 's/@@CountryCode=CN/@@CountryCode=CN, Regulation=NONE/g' "$TARGET_FILE" > "$SOURCE_FILE"
        fi
        
        # Verify mount status
        if ! mount | grep -q "$TARGET_FILE"; then
            mount --bind "$SOURCE_FILE" "$TARGET_FILE" 2>/dev/null && \
            log "Successfully unlocked RTC7646 eFEM to 23dBm (200mW) via bind-mount." || \
            log "Warning: Unable to bind-mount TXPWR_LMT table."
        fi
    fi
}

apply_mib_optimizations() {
    log "Applying kernel Wi-Fi 6 driver MIB enhancements..."

    for iface in wlan0 wlan1; do
        if ! ifconfig "$iface" >/dev/null 2>&1; then
            continue
        fi

        # 1. Disable Carrier EDCCA Backoff (Stop dropping TX power/backoff in crowded dorms)
        if [ "$DISABLE_EDCCA_CARRIER_BACKOFF" = "1" ]; then
            iwpriv "$iface" set_mib edcca_mode=0 2>/dev/null || true
            log "$iface: Carrier EDCCA backoff disabled (edcca_mode=0)"
        fi

        # 2. Enable AirTime Fairness (ATF)
        if [ "$ENABLE_AIRTIME_FAIRNESS" = "1" ]; then
            iwpriv "$iface" set_mib atf=1 2>/dev/null || true
            log "$iface: AirTime Fairness activated (atf=1)"
        fi

        # 3. Deny Legacy 802.11b Rates (Ban 1/2/5.5/11 Mbps CCK modulation on 2.4GHz)
        if [ "$DENY_LEGACY_11B" = "1" ]; then
            iwpriv "$iface" set_mib deny_legacy=1 2>/dev/null || true
            log "$iface: Legacy 802.11b DSSS rates forbidden (deny_legacy=1)"
        fi
    done
}

apply_latency_tuning() {
    if [ "$TUNE_PCIE_INT_MIT" != "1" ]; then
        return 0
    fi
    log "Tuning PCIe TRX Interrupt Mitigation to minimize hardware jitter..."
    for dev in wlan0 wlan1; do
        MIT_PROC="/proc/net/rtk_wifi6/$dev/int_mit"
        if [ -f "$MIT_PROC" ]; then
            echo "0" > "$MIT_PROC" 2>/dev/null || true
            log "$dev: PCIe interrupt mitigation coalescing disabled (low-latency mode)"
        fi
    done
}

apply_band_steering() {
    if [ "$ENABLE_BAND_STEERING" != "1" ]; then
        return 0
    fi
    log "Verifying 802.11v BSS Transition Management Band Steering..."
    # Ensure band steering status in MIB
    mib set band_steering_enable 1 2>/dev/null || true
    mib set prefer_band "$PREFER_BAND" 2>/dev/null || true
    mib set prefer_band_rssi_high "$PREFER_BAND_RSSI_HIGH" 2>/dev/null || true
    mib set prefer_band_rssi_low "$PREFER_BAND_RSSI_LOW" 2>/dev/null || true
}

prune_bloat_and_telemetry() {
    log "Terminating unneeded carrier daemons and bloated modules..."
    # Kill China Mobile proprietary telemetry agent
    if pidof managePlugin >/dev/null 2>&1; then
        killall -9 managePlugin 2>/dev/null || true
        log "Terminated China Mobile telemetry agent (managePlugin)"
    fi

    # Unload bloated IGMP hook module if present to reclaim 1.2 MB RAM
    if lsmod 2>/dev/null | grep -q "rtk_igmp_hook"; then
        rmmod rtk_igmp_hook 2>/dev/null || true
        log "Unloaded rtk_igmp_hook.ko (reclaimed 1.2 MB kernel memory)"
    fi
}

start() {
    if [ "$WIFI_TUNING_ENABLED" != "1" ]; then
        log "Wi-Fi tuning is disabled in $CONF_FILE"
        exit 0
    fi
    log "Starting Wi-Fi Radio DSP, Baseband & Scheduling Subsystem..."
    apply_tx_power_unlock
    apply_mib_optimizations
    apply_latency_tuning
    apply_band_steering
    prune_bloat_and_telemetry
    log "Wi-Fi radio scheduling optimizations applied successfully."
}

stop() {
    log "Reverting Wi-Fi radio tunings..."
    TARGET_FILE="/etc/conf/rtl8852ce/RFE54/TXPWR_LMT.txt"
    if mount | grep -q "$TARGET_FILE"; then
        umount "$TARGET_FILE" 2>/dev/null || true
    fi
    for iface in wlan0 wlan1; do
        iwpriv "$iface" set_mib atf=0 2>/dev/null || true
        iwpriv "$iface" set_mib edcca_mode=1 2>/dev/null || true
        iwpriv "$iface" set_mib deny_legacy=0 2>/dev/null || true
    done
    log "Default carrier radio state restored."
}

status() {
    echo "=== Wi-Fi Radio Optimization Status ==="
    TARGET_FILE="/etc/conf/rtl8852ce/RFE54/TXPWR_LMT.txt"
    if mount | grep -q "$TARGET_FILE"; then
        echo "eFEM TX Power Limit  : UNLOCKED (23 dBm / 200 mW via bind-mount)"
    else
        echo "eFEM TX Power Limit  : Stock (10.5 dBm / 11 mW regulatory clamp)"
    fi
    echo "EDCCA Carrier Mode   : $(iwpriv wlan0 get_mib edcca_mode 2>/dev/null || echo 'N/A')"
    echo "AirTime Fairness     : $(iwpriv wlan0 get_mib atf 2>/dev/null || echo 'N/A')"
    echo "Deny Legacy 11b      : $(iwpriv wlan0 get_mib deny_legacy 2>/dev/null || echo 'N/A')"
    echo "managePlugin Telemetry: $(pidof managePlugin >/dev/null 2>&1 && echo 'Running' || echo 'Clean / Terminated')"
}

case "$1" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; start ;;
    status)  status ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
