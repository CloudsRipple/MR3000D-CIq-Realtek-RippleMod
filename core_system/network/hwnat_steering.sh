#!/bin/sh
# ==============================================================================
# Ripple-mod - Modern Traffic Steering & HWNAT Coexistence Engine
# Target Platform: Realtek RTL8198D (Linux 5.10.70 MIPS32r2)
# ==============================================================================

CONF_FILE="/var/app/conf/steering.conf"
[ -f "$CONF_FILE" ] && . "$CONF_FILE"

# Defaults
STEERING_ENABLED="${STEERING_ENABLED:-1}"
TUN_DEV="${TUN_DEV:-tun0}"
STEER_ROUTE_TABLE="${STEER_ROUTE_TABLE:-100}"
BYPASS_MARK_BIT="${BYPASS_MARK_BIT:-30}"
BYPASS_MARK_HEX="${BYPASS_MARK_HEX:-0x40000000}"
CHINA_IPSET_NAME="${CHINA_IPSET_NAME:-ripple_china_ip}"
CHINA_IP_FILE="${CHINA_IP_FILE:-/var/app/conf/china_ip_list.txt}"
INTRANET_BYPASS_CIDRS="${INTRANET_BYPASS_CIDRS:-10.0.0.0/8 172.16.0.0/12 172.20.0.0/14 172.28.0.0/16 192.168.0.0/16}"
DISABLE_CARRIER_DNS_TRAP="${DISABLE_CARRIER_DNS_TRAP:-1}"

log() {
    echo "[Steering] $1"
}

init_hwnat_bypass() {
    log "Configuring Realtek FleetConntrack HWNAT mark bypass..."
    # 1. Register HWNAT bypass bit in FleetConntrack
    if [ -f /proc/fc/ctrl/skbmark_skipFcFunc ]; then
        echo "$BYPASS_MARK_BIT" > /proc/fc/ctrl/skbmark_skipFcFunc 2>/dev/null || true
        log "Registered bit $BYPASS_MARK_BIT to /proc/fc/ctrl/skbmark_skipFcFunc"
    fi
    if [ -f /proc/fc/ctrl/skbmark_fwdByPs ]; then
        echo "$BYPASS_MARK_BIT" > /proc/fc/ctrl/skbmark_fwdByPs 2>/dev/null || true
        log "Registered bit $BYPASS_MARK_BIT to /proc/fc/ctrl/skbmark_fwdByPs"
    fi

    # 2. Neutralize Carrier DNS Trap Hook in Kernel
    if [ "$DISABLE_CARRIER_DNS_TRAP" = "1" ] && [ -f /proc/driver/realtek/dns_trap_enable ]; then
        echo 0 > /proc/driver/realtek/dns_trap_enable 2>/dev/null || true
        log "Deactivated /proc/driver/realtek/dns_trap_enable (zero carrier DNS interception)"
    fi
}

init_ipsets() {
    log "Initializing IPSet collections..."
    # 1. Reserved Private & Special Subnets
    ipset create ripple_reserved_ip hash:net family inet hashsize 64 maxelem 64 2>/dev/null || ipset flush ripple_reserved_ip
    for net in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4 240.0.0.0/4 255.255.255.255/32; do
        ipset add ripple_reserved_ip "$net" 2>/dev/null || true
    done

    # 2. Intranet & Direct LAN Bypass
    ipset create ripple_intranet_ip hash:net family inet hashsize 128 maxelem 256 2>/dev/null || ipset flush ripple_intranet_ip
    for cidr in $INTRANET_BYPASS_CIDRS; do
        ipset add ripple_intranet_ip "$cidr" 2>/dev/null || true
    done

    # 3. China Direct CIDR IPSet (for 1Gbps HWNAT Wire-speed Acceleration)
    ipset create "$CHINA_IPSET_NAME" hash:net family inet hashsize 4096 maxelem 65536 2>/dev/null || true
    if [ -f "$CHINA_IP_FILE" ]; then
        log "Loading China IP list from $CHINA_IP_FILE..."
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            case "$line" in \#*) continue ;; esac
            ipset add "$CHINA_IPSET_NAME" "$line" 2>/dev/null || true
        done < "$CHINA_IP_FILE"
    else
        # Essential domestic backbone DNS fallbacks if file not yet downloaded
        for ip in 114.114.114.114 114.114.115.115 223.5.5.5 223.6.6.6 119.29.29.29 180.76.76.76; do
            ipset add "$CHINA_IPSET_NAME" "$ip" 2>/dev/null || true
        done
    fi
}

setup_policy_routing() {
    log "Configuring Linux policy routing (Table $STEER_ROUTE_TABLE)..."
    
    # Check if TUN device exists
    if ip link show "$TUN_DEV" >/dev/null 2>&1; then
        ip route replace default dev "$TUN_DEV" table "$STEER_ROUTE_TABLE" 2>/dev/null || true
        log "Default route via $TUN_DEV established in table $STEER_ROUTE_TABLE"
    else
        log "Warning: Virtual device $TUN_DEV not yet active. Policy route will apply once daemon starts."
    fi

    # Ensure rule is not duplicated
    while ip rule del fwmark "$BYPASS_MARK_HEX" table "$STEER_ROUTE_TABLE" 2>/dev/null; do :; done
    ip rule add fwmark "$BYPASS_MARK_HEX" table "$STEER_ROUTE_TABLE" pref 10000 2>/dev/null || true
}

setup_netfilter_rules() {
    log "Setting up Netfilter mangle chains for zero-conflict traffic steering..."
    
    # Create or flush dedicated steering chain
    iptables -t mangle -N RIPPLE_STEERING 2>/dev/null || iptables -t mangle -F RIPPLE_STEERING

    # A. Bypass locally originated traffic & loopback
    iptables -t mangle -A RIPPLE_STEERING -i lo -j RETURN

    # B. Bypass Reserved Private IP ranges -> directly route via HWNAT
    iptables -t mangle -A RIPPLE_STEERING -m set --match-set ripple_reserved_ip dst -j RETURN

    # C. Bypass Intranet Subnets -> directly route via HWNAT
    iptables -t mangle -A RIPPLE_STEERING -m set --match-set ripple_intranet_ip dst -j RETURN

    # D. Bypass China Domestic Subnets -> directly route via HWNAT ASIC (1Gbps line-rate)
    iptables -t mangle -A RIPPLE_STEERING -m set --match-set "$CHINA_IPSET_NAME" dst -j RETURN

    # E. Remaining Foreign/International Traffic -> Mark with BYPASS_MARK_HEX
    # This mark directs packets into table 100 (tun0) AND signals FleetConntrack to bypass HWNAT
    iptables -t mangle -A RIPPLE_STEERING -p tcp -j MARK --set-xmark "$BYPASS_MARK_HEX/$BYPASS_MARK_HEX"
    iptables -t mangle -A RIPPLE_STEERING -p udp -j MARK --set-xmark "$BYPASS_MARK_HEX/$BYPASS_MARK_HEX"

    # Hook chain into PREROUTING
    iptables -t mangle -C PREROUTING -j RIPPLE_STEERING 2>/dev/null || \
    iptables -t mangle -A PREROUTING -j RIPPLE_STEERING
}

start() {
    if [ "$STEERING_ENABLED" != "1" ]; then
        log "Steering is disabled in $CONF_FILE"
        exit 0
    fi
    log "Starting Modern Traffic Steering & HWNAT Coexistence Subsystem..."
    init_hwnat_bypass
    init_ipsets
    setup_policy_routing
    setup_netfilter_rules
    log "Steering successfully activated with zero HWNAT conflict."
}

stop() {
    log "Stopping Traffic Steering Subsystem..."
    iptables -t mangle -D PREROUTING -j RIPPLE_STEERING 2>/dev/null || true
    iptables -t mangle -F RIPPLE_STEERING 2>/dev/null || true
    iptables -t mangle -X RIPPLE_STEERING 2>/dev/null || true

    while ip rule del fwmark "$BYPASS_MARK_HEX" table "$STEER_ROUTE_TABLE" 2>/dev/null; do :; done
    ip route flush table "$STEER_ROUTE_TABLE" 2>/dev/null || true

    ipset destroy ripple_reserved_ip 2>/dev/null || true
    ipset destroy ripple_intranet_ip 2>/dev/null || true
    ipset destroy "$CHINA_IPSET_NAME" 2>/dev/null || true

    log "Steering deactivated. Full native routing restored."
}

status() {
    echo "=== Traffic Steering Status ==="
    echo "HWNAT skipFcFunc bit : $(cat /proc/fc/ctrl/skbmark_skipFcFunc 2>/dev/null || echo 'N/A')"
    echo "HWNAT fwdByPs bit    : $(cat /proc/fc/ctrl/skbmark_fwdByPs 2>/dev/null || echo 'N/A')"
    echo "Carrier DNS Trap     : $(cat /proc/driver/realtek/dns_trap_enable 2>/dev/null || echo 'N/A') (0=Disabled/Clean)"
    echo "TUN Device           : $(ip link show "$TUN_DEV" 2>/dev/null | head -n 1 || echo 'Not active')"
    echo "Policy Rules         :"
    ip rule show | grep "$STEER_ROUTE_TABLE" || echo "  No rules for table $STEER_ROUTE_TABLE"
    echo "Routing Table $STEER_ROUTE_TABLE :"
    ip route show table "$STEER_ROUTE_TABLE" || echo "  Empty"
    echo "Netfilter Mangle Rule Count:"
    iptables -t mangle -L RIPPLE_STEERING -v -n 2>/dev/null || echo "  RIPPLE_STEERING chain not loaded"
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
