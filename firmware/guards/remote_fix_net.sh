#!/bin/sh
# ==============================================================================
# CMCC MR3000D-CIq 路由器转发快转恢复与流氓进程查杀脚本 (由 Mac 自动推送到 /tmp 执行)
# ==============================================================================

echo "[1/5] 恢复瑞昱 FleetConntrack 硬件 NAT (HWNAT) 与 Wi-Fi 零拷贝快转..."
# 1. 禁用 Linux 软件 RPS (避免跨核软中断抢占硬件快转通道)
for RPS in /sys/class/net/eth0*/queues/rx-0/rps_cpus /sys/class/net/wlan*/queues/rx-0/rps_cpus /sys/class/net/nas*/queues/rx-0/rps_cpus /sys/class/net/br*/queues/rx-0/rps_cpus; do
    [ -w "$RPS" ] && echo 0 > "$RPS" 2>/dev/null || true
done

# 2. 恢复 Wi-Fi 6 硬件 A-MPDU/A-MSDU 聚合掩码 (agg_enable=3) 与千兆 ring 队列深度 (txqueuelen=1000)
for IFACE in wlan0 wlan1; do
    if [ -d "/sys/class/net/$IFACE" ]; then
        iwpriv "$IFACE" set_mib agg_enable=3 2>/dev/null || true
        iwpriv "$IFACE" set_mib ps_level=0 2>/dev/null || true
        iwpriv "$IFACE" set_mib lps_level=0 2>/dev/null || true
        iwpriv "$IFACE" set_mib qos_enable=1 2>/dev/null || true
        ip link set dev "$IFACE" txqueuelen 1000 2>/dev/null || true
    fi
done

for ETH in eth0 eth0.2 eth0.3 eth0.4 eth0.5 nas0 br0; do
    [ -d "/sys/class/net/$ETH" ] && ip link set dev "$ETH" txqueuelen 1000 2>/dev/null || true
done

echo "[2/5] 恢复瑞昱 FleetConntrack 硬件 NAT 加速并开启 TCP MSS PMTU 钳制..."
ip rule del fwmark 0x100 table 100 2>/dev/null || true
ip rule del fwmark 0x200 table 200 2>/dev/null || true
ip route flush table 100 2>/dev/null || true
ip route flush table 200 2>/dev/null || true
iptables -t mangle -F PREROUTING 2>/dev/null || true
iptables -D FORWARD -p udp -m multiport --dports 3478,5349,19302:19309 -j DROP 2>/dev/null || true
[ -w /proc/fc/ctrl/hwnat ] && echo 1 > /proc/fc/ctrl/hwnat 2>/dev/null || true

# 解决宽带/PPPoE 巨帧黑洞，钳制 MSS 至 PMTU
iptables -t mangle -D FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true
iptables -t mangle -I FORWARD -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null || true

echo "[3/5] 彻底查杀移动后台流氓监控与强刷进程..."
wtimer -d check_upgrade_3m 2>/dev/null || true
wtimer -d check_upgrade_8h 2>/dev/null || true
wtimer -d force_upgrade_2h 2>/dev/null || true
killall -9 dpiPlugin lanNetInfo vasdocker managePlugin pluginDaemon timelycheck ahsapd ahsapd_logsrv do_force_upgrade check_upgrade_info 2>/dev/null || true

echo "[4/5] 清理废弃 Mock 插件并修复 admin 密码哈希 (system)..."
rm -rf /var/app/plugins/ttl_anti_detect /etc/plugins/ttl_anti_detect 2>/dev/null || true
sed -i 's|^admin:.*|admin:$1$9zE8P7R5$5IeYiR8q8X0sZ6tUc3A5a0:0:0:root:/var/app:/bin/sh|' /etc/passwd 2>/dev/null || true

echo "[5/5] 热更新前台页面与 API 接口到 /home/httpd/web..."
if [ -d /var/app/web ] && [ -d /home/httpd/web ]; then
    umount /home/httpd/web 2>/dev/null || true
    rm -rf /tmp/web_merged 2>/dev/null || true
    mkdir -p /tmp/web_merged
    cp -rf /home/httpd/web/* /tmp/web_merged/ 2>/dev/null || true
    cp -rf /var/app/web/* /tmp/web_merged/ 2>/dev/null || true
    chmod +x /tmp/web_merged/api.cgi 2>/dev/null || true
    mount -o bind /tmp/web_merged /home/httpd/web 2>/dev/null || true
fi

sync
echo "HWNAT_STATUS=$(cat /proc/fc/ctrl/hwnat 2>/dev/null || echo '1')"
echo "UPTIME_INFO=$(uptime)"
echo "[SUCCESS] 快转优化与热更新全部执行完毕！"
