#!/bin/sh
# ==============================================================================
# Ripple-mod - Comprehensive Network Optimizer & High-Throughput Buffer Tuning
# 综合网络优化与高并发传输加速引擎
# Target Architecture: Realtek RTL8198D (MIPS32r2 Big-Endian)
# ==============================================================================

log() {
    echo "[Net-Opt] $1"
}

tune_kernel_network_buffers() {
    log "正在应用适配 256MB MIPS32 平台的稳健内核网络缓冲配置..."
    # Safe limits for 256 MiB RAM (Linux doubles rmem_default/wmem_default internally;
    # excessive defaults like 2MB/8MB exhaust lowmem/DMA sk_buffs and trigger OOM after 20-48h)
    echo 1048576 > /proc/sys/net/core/rmem_max 2>/dev/null || true
    echo 1048576 > /proc/sys/net/core/wmem_max 2>/dev/null || true
    echo 131072 > /proc/sys/net/core/rmem_default 2>/dev/null || true
    echo 131072 > /proc/sys/net/core/wmem_default 2>/dev/null || true

    # TCP Buffer limits: min, default, max (1 MiB cap prevents sk_buff OOM on 256MB DDR3)
    echo "4096 87380 1048576" > /proc/sys/net/ipv4/tcp_rmem 2>/dev/null || true
    echo "4096 65536 1048576" > /proc/sys/net/ipv4/tcp_wmem 2>/dev/null || true

    # TCP Window Scaling & SACK (提升高时延广域网长链路传输稳定性)
    echo 1 > /proc/sys/net/ipv4/tcp_window_scaling 2>/dev/null || true
    echo 1 > /proc/sys/net/ipv4/tcp_timestamps 2>/dev/null || true
    echo 1 > /proc/sys/net/ipv4/tcp_sack 2>/dev/null || true

    # 保持温和的设备积压队列上限（贴近原厂 rc10 的 2000，避免突发时占满低端原子内存）
    echo 2500 > /proc/sys/net/core/netdev_max_backlog 2>/dev/null || true

    # 启用 PMTU 动态路径发现 (Linux 5.10: ip_no_pmtu_disc=0 表示启用 PMTUD, 1 为关闭)
    echo 0 > /proc/sys/net/ipv4/ip_no_pmtu_disc 2>/dev/null || true
}

optimize_process_affinity() {
    # 仅对可选高吞吐测速/代理进程绑定 CPU 1，不强行钉死 dnsmasq/dropbear 以防单核饥饿
    DAEMONS="iperf3 nginx"
    for daemon in $DAEMONS; do
        pids=$(pidof "$daemon" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            for pid in $pids; do
                taskset -p -c 1 "$pid" >/dev/null 2>&1 || true
            done
        fi
    done
}

get_recommended_env() {
    cat << 'EOF'
# Recommended Runtime Environment for MIPS32r2 Soft-Float (RTL8198D 256MB RAM):
export GOMAXPROCS=2
export GOGC=30
export GOMEMLIMIT=64MiB
export MALLOC_ARENA_MAX=2
EOF
}

case "$1" in
    tune)
        tune_kernel_network_buffers
        optimize_process_affinity
        ;;
    env)
        get_recommended_env
        ;;
    *)
        tune_kernel_network_buffers
        optimize_process_affinity
        ;;
esac
