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
    log "正在应用系统级内核网络套接字缓冲优化 (支持高吞吐与低时延)..."
    # 8MB TCP/UDP socket buffer limits (提升高突发大吞吐传输容限，防止高速丢包)
    echo 8388608 > /proc/sys/net/core/rmem_max 2>/dev/null || true
    echo 8388608 > /proc/sys/net/core/wmem_max 2>/dev/null || true
    echo 2097152 > /proc/sys/net/core/rmem_default 2>/dev/null || true
    echo 2097152 > /proc/sys/net/core/wmem_default 2>/dev/null || true

    # TCP Buffer limits: min, default, max (最大支持千兆带宽时延积 BDP 吞吐)
    echo "4096 87380 8388608" > /proc/sys/net/ipv4/tcp_rmem 2>/dev/null || true
    echo "4096 65536 8388608" > /proc/sys/net/ipv4/tcp_wmem 2>/dev/null || true

    # TCP Window Scaling & SACK (提升高时延越洋/广域网长链路传输稳定性)
    echo 1 > /proc/sys/net/ipv4/tcp_window_scaling 2>/dev/null || true
    echo 1 > /proc/sys/net/ipv4/tcp_timestamps 2>/dev/null || true
    echo 1 > /proc/sys/net/ipv4/tcp_sack 2>/dev/null || true

    # 扩展网络设备积压队列至 10,000，缓解突发 UDP/TCP 流量的队列溢出
    echo 10000 > /proc/sys/net/core/netdev_max_backlog 2>/dev/null || true

    # 启用 PMTU 动态路径发现
    echo 1 > /proc/sys/net/ipv4/ip_no_pmtu_disc 2>/dev/null || true
}

optimize_process_affinity() {
    # 将高负载网络服务进程绑定至 CPU 1，与处理 Wi-Fi 射频中断的 CPU 0/2/3 进行物理隔离调度
    DAEMONS="iperf3 nginx dnsmasq dropbear"
    for daemon in $DAEMONS; do
        pids=$(pidof "$daemon" 2>/dev/null || true)
        if [ -n "$pids" ]; then
            for pid in $pids; do
                taskset -p -c 1 "$pid" >/dev/null 2>&1 || true
                renice -n -5 -p "$pid" >/dev/null 2>&1 || true
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
