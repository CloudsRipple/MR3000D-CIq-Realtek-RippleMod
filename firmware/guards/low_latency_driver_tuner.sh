#!/bin/sh
# ==============================================================================
# CMCC MR3000D-CIq Driver-Level Low-Latency & HWNAT Fastpath Engine
# File: /var/app/scripts/low_latency_driver_tuner.sh
# ==============================================================================
# Optimizes:
# 1. Realtek G6 Wi-Fi 6 Driver (RTL8852CE 5GHz & RTL8192XB 2.4GHz):
#    - Disables Leisure Power Save (ps_level=0, lps_level=0) to eliminate wakeup spikes
#    - Preserves full hardware A-MPDU/A-MSDU aggregation (agg_enable=3)
# 2. Restores Realtek FleetConntrack HWNAT (/proc/fc/ctrl/hwnat = 1) & wifi_fast_fwd
# 3. Disables software RPS (rps_cpus = 0) so packets stay in hardware/driver fastpath
# 4. Ensures full Gigabit ring depth (txqueuelen = 1000) & TCP MSS PMTU Clamping
# ==============================================================================

MODE="${1:-enable}"

log_msg() {
    echo "[LowLatencyDriver] $1"
    logger -t LowLatencyDriver "$1" 2>/dev/null
}

apply_low_latency() {
    log_msg "Applying Realtek HWNAT Fastpath & Wi-Fi 6 Low-Latency Tuning..."

    # 1. Wi-Fi 6 Driver MIB Tuning (preserve full A-MPDU aggregation agg_enable=3, disable PS lag)
    for IFACE in wlan0 wlan1; do
        if [ -d "/sys/class/net/$IFACE" ]; then
            iwpriv "$IFACE" set_mib ps_level=0 2>/dev/null || true
            iwpriv "$IFACE" set_mib lps_level=0 2>/dev/null || true
            iwpriv "$IFACE" set_mib qos_enable=1 2>/dev/null || true
            iwpriv "$IFACE" set_mib agg_enable=3 2>/dev/null || true
            iwpriv "$IFACE" set_mib shortgi20=1 2>/dev/null || true
            iwpriv "$IFACE" set_mib shortgi40=1 2>/dev/null || true
            iwpriv "$IFACE" set_mib shortgi80=1 2>/dev/null || true
            ip link set dev "$IFACE" txqueuelen 1000 2>/dev/null || true
        fi
    done

    # 2. Ensure full 1000-packet TX ring depth on all wired/bridge interfaces
    for ETH in eth0 eth0.2 eth0.3 eth0.4 eth0.5 nas0 br0; do
        [ -d "/sys/class/net/$ETH" ] && ip link set dev "$ETH" txqueuelen 1000 2>/dev/null || true
    done

    # 3. CRITICAL: Disable Linux software RPS (rps_cpus=0) so Realtek FleetConntrack (fc)
    #    and wifi_fast_fwd zero-copy fastpath are NEVER hijacked by cross-CPU softirq IPIs!
    for RPS in /sys/class/net/eth0*/queues/rx-0/rps_cpus /sys/class/net/wlan*/queues/rx-0/rps_cpus /sys/class/net/nas*/queues/rx-0/rps_cpus /sys/class/net/br*/queues/rx-0/rps_cpus; do
        [ -w "$RPS" ] && echo 0 > "$RPS" 2>/dev/null || true
    done

    # 4. Kernel Network Stack Fastpath Sysctl Tuning
    sysctl -w net.core.netdev_budget=600 >/dev/null 2>&1 || true
    sysctl -w net.core.netdev_max_backlog=4096 >/dev/null 2>&1 || true
    sysctl -w net.ipv4.tcp_fastopen=3 >/dev/null 2>&1 || true
    sysctl -w net.ipv4.tcp_low_latency=1 >/dev/null 2>&1 || true
    sysctl -w net.ipv4.tcp_tw_reuse=1 >/dev/null 2>&1 || true

    # 5. TCP MSS Clamping to PMTU (prevents campus network / PPPoE / VLAN MTU blackholes)
    iptables -t mangle -D FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
    iptables -t mangle -I FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true

    # 6. Enable Realtek FleetConntrack Hardware NAT ASIC Fastpath (unless Dual-WAN policy routing is active)
    if ! ip rule list 2>/dev/null | grep -q "lookup 200"; then
        iptables -t mangle -F PREROUTING 2>/dev/null || true
        [ -w /proc/fc/ctrl/hwnat ] && echo 1 > /proc/fc/ctrl/hwnat 2>/dev/null || true
    fi

    log_msg "Realtek HWNAT fastpath (hwnat=1, rps=0, agg=3, txq=1000, MSS clamp) active."
}

restore_stock_latency() {
    log_msg "Restoring stock driver queue & HWNAT parameters..."
    for IFACE in wlan0 wlan1 eth0 eth0.2 eth0.3 eth0.4 eth0.5 nas0 br0; do
        [ -d "/sys/class/net/$IFACE" ] && ip link set dev "$IFACE" txqueuelen 1000 2>/dev/null || true
    done
    for IFACE in wlan0 wlan1; do
        if [ -d "/sys/class/net/$IFACE" ]; then
            iwpriv "$IFACE" set_mib agg_enable=3 2>/dev/null || true
        fi
    done
    for RPS in /sys/class/net/eth0*/queues/rx-0/rps_cpus /sys/class/net/wlan*/queues/rx-0/rps_cpus; do
        [ -w "$RPS" ] && echo 0 > "$RPS" 2>/dev/null || true
    done
    if ! ip rule list 2>/dev/null | grep -q "lookup 200"; then
        [ -w /proc/fc/ctrl/hwnat ] && echo 1 > /proc/fc/ctrl/hwnat 2>/dev/null || true
    fi
    log_msg "Stock HWNAT & aggregation parameters restored."
}

case "$MODE" in
    enable|start)
        apply_low_latency
        ;;
    disable|stop)
        restore_stock_latency
        ;;
    *)
        echo "Usage: $0 {enable|disable}"
        exit 1
        ;;
esac
