#!/bin/sh
# ==============================================================================
# Ripple-mod - Modern Traffic Scheduler & Bufferbloat Mitigation Engine
# Target Platform: Realtek RTL8198D (Linux 5.10.70 MIPS32r2)
# ==============================================================================

CONF_FILE="/var/app/conf/sqm.conf"
[ -f "$CONF_FILE" ] && . "$CONF_FILE"

SQM_ENABLED="${SQM_ENABLED:-1}"
WAN_DEV="${WAN_DEV:-eth0}"
IFB_DEV="${IFB_DEV:-ifb0}"
UPLOAD_RATE_KBIT="${UPLOAD_RATE_KBIT:-50000}"
DOWNLOAD_RATE_KBIT="${DOWNLOAD_RATE_KBIT:-300000}"
QDISC_TYPE="${QDISC_TYPE:-sfq}"
SFQ_PERTURB="${SFQ_PERTURB:-10}"
ENABLE_DSCP_QOS="${ENABLE_DSCP_QOS:-1}"

log() {
    echo "[Scheduler] $1"
}

setup_wmm_dscp() {
    if [ "$ENABLE_DSCP_QOS" != "1" ]; then
        return 0
    fi
    log "Configuring Netfilter DSCP priority tagging for Realtek WMM Hardware Queues..."
    iptables -t mangle -N RIPPLE_QOS 2>/dev/null || iptables -t mangle -F RIPPLE_QOS

    # 1. DNS Queries & Replies -> CS6 (Network Control / AC_VO queue)
    iptables -t mangle -A RIPPLE_QOS -p udp --dport 53 -j DSCP --set-dscp-class CS6
    iptables -t mangle -A RIPPLE_QOS -p udp --sport 53 -j DSCP --set-dscp-class CS6
    iptables -t mangle -A RIPPLE_QOS -p tcp --dport 53 -j DSCP --set-dscp-class CS6

    # 2. NTP, ICMP -> EF / Expedited Forwarding (AC_VO queue)
    iptables -t mangle -A RIPPLE_QOS -p udp --dport 123 -j DSCP --set-dscp-class EF
    iptables -t mangle -A RIPPLE_QOS -p icmp -j DSCP --set-dscp-class CS5

    # 3. Game Netcode Priority (三角洲行动 Delta Force / CS2 / Steam / Tencent Games)
    # 3.1 CS2 / Counter-Strike (Valve Network Sockets / SDR dedicated servers)
    iptables -t mangle -A RIPPLE_QOS -p udp -m multiport --dports 27000:27050,3478,4379,4380 -j DSCP --set-dscp-class EF
    iptables -t mangle -A RIPPLE_QOS -p udp -m multiport --sports 27000:27050,3478,4379,4380 -j DSCP --set-dscp-class EF

    # 3.2 三角洲行动 (Delta Force: Hawk Ops) / 腾讯 GCloud / UE5 Netcode
    iptables -t mangle -A RIPPLE_QOS -p udp -m multiport --dports 7000:9000,10000:12000,30000:40000 -j DSCP --set-dscp-class EF
    iptables -t mangle -A RIPPLE_QOS -p udp -m multiport --sports 7000:9000,10000:12000,30000:40000 -j DSCP --set-dscp-class EF

    # 3.3 Universal Game Real-Time Tick Packets (All games: UDP packet length <= 384 bytes)
    # Distinguishes compact position/velocity/input frames from bulk download streams
    iptables -t mangle -A RIPPLE_QOS -p udp -m length --length 0:384 -j DSCP --set-dscp-class EF

    # 3.4 Low-latency Voice Communications (Discord, KOOK, In-Game Voice: UDP 50000-65535 <= 512B)
    iptables -t mangle -A RIPPLE_QOS -p udp -m multiport --dports 50000:65535 -m length --length 0:512 -j DSCP --set-dscp-class CS5
    iptables -t mangle -A RIPPLE_QOS -p tcp --tcp-flags SYN,RST,ACK ACK -m length --length 0:64 -j DSCP --set-dscp-class CS5

    # 4. Bulk Download & Heavy Stream Demotion (>2MB accumulated connbytes or MTU-sized packets)
    # Confines bulk data to Best Effort (CS0 / AC_BE queue) so it never starves gaming
    iptables -t mangle -A RIPPLE_QOS -m connbytes --connbytes 2097152: --connbytes-mode bytes --connbytes-direction both -m length --length 1024:1500 -j DSCP --set-dscp-class CS0 2>/dev/null || true

    # Hook into POSTROUTING
    iptables -t mangle -C POSTROUTING -j RIPPLE_QOS 2>/dev/null || \
    iptables -t mangle -A POSTROUTING -j RIPPLE_QOS
}

setup_wan_egress_sqm() {
    if [ "$UPLOAD_RATE_KBIT" -le 0 ]; then
        log "Upload shaping disabled (UPLOAD_RATE_KBIT=0)"
        return 0
    fi
    log "Configuring WAN egress HTB + SFQ shaper on $WAN_DEV (${UPLOAD_RATE_KBIT} kbit/s)..."
    
    tc qdisc del dev "$WAN_DEV" root 2>/dev/null || true
    tc qdisc add dev "$WAN_DEV" root handle 1: htb default 10
    tc class add dev "$WAN_DEV" parent 1: classid 1:1 htb rate "${UPLOAD_RATE_KBIT}kbit" ceil "${UPLOAD_RATE_KBIT}kbit"

    # Bulk traffic class (70% guaranteed, burst up to 100%)
    BULK_RATE=$(( UPLOAD_RATE_KBIT * 7 / 10 ))
    tc class add dev "$WAN_DEV" parent 1:1 classid 1:10 htb rate "${BULK_RATE}kbit" ceil "${UPLOAD_RATE_KBIT}kbit" prio 2
    tc qdisc add dev "$WAN_DEV" parent 1:10 handle 10: sfq perturb "$SFQ_PERTURB" quantum 1514

    # High-priority interactive / gaming / DNS class (30% guaranteed, prio 0)
    PRIO_RATE=$(( UPLOAD_RATE_KBIT * 3 / 10 ))
    tc class add dev "$WAN_DEV" parent 1:1 classid 1:20 htb rate "${PRIO_RATE}kbit" ceil "${UPLOAD_RATE_KBIT}kbit" prio 0
    tc qdisc add dev "$WAN_DEV" parent 1:20 handle 20: sfq perturb "$SFQ_PERTURB" quantum 1514

    # Direct DSCP CS6 / EF / DNS packets into high-priority queue
    tc filter add dev "$WAN_DEV" parent 1:0 protocol ip prio 1 u32 match ip dport 53 0xffff flowid 1:20 2>/dev/null || true
    tc filter add dev "$WAN_DEV" parent 1:0 protocol ip prio 1 u32 match ip sport 53 0xffff flowid 1:20 2>/dev/null || true
    tc filter add dev "$WAN_DEV" parent 1:0 protocol ip prio 1 u32 match ip tos 0xc0 0xfc flowid 1:20 2>/dev/null || true
    tc filter add dev "$WAN_DEV" parent 1:0 protocol ip prio 1 u32 match ip tos 0xb8 0xfc flowid 1:20 2>/dev/null || true
}

setup_wan_ingress_sqm() {
    if [ "$DOWNLOAD_RATE_KBIT" -le 0 ]; then
        log "Download shaping disabled (DOWNLOAD_RATE_KBIT=0)"
        return 0
    fi
    log "Configuring WAN ingress bufferbloat control via $IFB_DEV (${DOWNLOAD_RATE_KBIT} kbit/s)..."

    # Ensure IFB device is available and up
    ip link set dev "$IFB_DEV" up 2>/dev/null || true

    # Redirect WAN ingress packets to IFB
    tc qdisc del dev "$WAN_DEV" ingress 2>/dev/null || true
    tc qdisc add dev "$WAN_DEV" handle ffff: ingress 2>/dev/null || true
    tc filter add dev "$WAN_DEV" parent ffff: protocol all u32 match u32 0 0 action mirred egress redirect dev "$IFB_DEV" 2>/dev/null || true

    # Apply HTB + SFQ shaper on IFB device
    tc qdisc del dev "$IFB_DEV" root 2>/dev/null || true
    tc qdisc add dev "$IFB_DEV" root handle 1: htb default 10
    tc class add dev "$IFB_DEV" parent 1: classid 1:1 htb rate "${DOWNLOAD_RATE_KBIT}kbit" ceil "${DOWNLOAD_RATE_KBIT}kbit"
    tc class add dev "$IFB_DEV" parent 1:1 classid 1:10 htb rate "${DOWNLOAD_RATE_KBIT}kbit" ceil "${DOWNLOAD_RATE_KBIT}kbit"
    tc qdisc add dev "$IFB_DEV" parent 1:10 handle 10: sfq perturb "$SFQ_PERTURB" quantum 1514
}

start() {
    if [ "$SQM_ENABLED" != "1" ]; then
        log "SQM is disabled in $CONF_FILE"
        exit 0
    fi
    log "Starting Modern Traffic Scheduler (SQM + WMM DSCP)..."
    setup_wmm_dscp
    setup_wan_egress_sqm
    setup_wan_ingress_sqm
    log "Traffic scheduler successfully running."
}

stop() {
    log "Stopping Traffic Scheduler..."
    tc qdisc del dev "$WAN_DEV" root 2>/dev/null || true
    tc qdisc del dev "$WAN_DEV" ingress 2>/dev/null || true
    tc qdisc del dev "$IFB_DEV" root 2>/dev/null || true
    ip link set dev "$IFB_DEV" down 2>/dev/null || true

    iptables -t mangle -D POSTROUTING -j RIPPLE_QOS 2>/dev/null || true
    iptables -t mangle -F RIPPLE_QOS 2>/dev/null || true
    iptables -t mangle -X RIPPLE_QOS 2>/dev/null || true
    log "Traffic scheduler stopped. Native FIFO queues restored."
}

status() {
    echo "=== Traffic Scheduler Status ==="
    echo "WAN Egress ($WAN_DEV):"
    tc -s qdisc show dev "$WAN_DEV" 2>/dev/null || echo "  No qdisc"
    echo "WAN Ingress ($IFB_DEV):"
    tc -s qdisc show dev "$IFB_DEV" 2>/dev/null || echo "  No qdisc"
    echo "DSCP Mangle Rules:"
    iptables -t mangle -L RIPPLE_QOS -v -n 2>/dev/null || echo "  RIPPLE_QOS chain not loaded"
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
