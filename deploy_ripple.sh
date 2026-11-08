#!/usr/bin/env bash
# ==============================================================================
# Ripple-mod - 一键热部署与平滑升级脚本 (macOS 端执行)
# ==============================================================================
# 功能:
# 1. 自动定位局域网直连物理网卡 (避开 Clash / Surge TUN 虚拟网卡);
# 2. 通过 Telnet 连接路由器并执行热部署;
# 3. 本地自动打包 Ripple-mod 纯净套件 (核心库、通用插件引擎、全功能 Web 控制台);
# 4. 高速推送到路由器 /var/app/ 分区并彻底清理原厂 CMCC 专有残留;
# 5. 自动激活内核硬件 NAT 加速 (HWNAT)、配置软链接与开机引导钩子;
# 6. 免重启路由器，秒级完成热更新并保持外网在线。
# ==============================================================================

set -euo pipefail

ROUTER_IP="${ROUTER_IP:-192.168.10.1}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "          🚀 Ripple-mod 一键平滑升级与热部署工具"
echo "============================================================"
echo "[*] 项目源目录: $SCRIPT_DIR"
echo "[*] 目标路由器: $ROUTER_IP"

# 1. 检测路由器连通性
echo -n "[1/6] 检测局域网连通性 ($ROUTER_IP)... "
if ping -c 1 -t 3 "$ROUTER_IP" >/dev/null 2>&1; then
    echo "OK (已连通)"
else
    echo "FAILED"
    echo "❌ 无法连接到 $ROUTER_IP，请检查 Mac 是否已连上路由器 Wi-Fi 或插上网线！"
    exit 1
fi

# 2. 检查 Python 3 工具链依赖
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ 本机缺少 python3，请在终端安装后重试。"
    exit 1
fi

# 3. 本地打包 Ripple-mod 纯净核心套件
echo "[2/6] 正在本地打包 Ripple-mod 纯净核心套件..."
BUNDLE_TAR="/tmp/ripple_mod_bundle_$$.tar.gz"
trap 'rm -f "$BUNDLE_TAR"' EXIT INT TERM

tar --exclude='.git' \
    --exclude='.DS_Store' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    -czf "$BUNDLE_TAR" \
    bin core_system plugin_engine plugins web

BUNDLE_SIZE_MB=$(python3 -c "import os; print(f'{os.path.getsize(\"$BUNDLE_TAR\") / (1024*1024):.2f}')")
echo "  * 压缩包生成完成: $BUNDLE_TAR (体积: ${BUNDLE_SIZE_MB} MB)"

# 4. 执行自动化迁移与无缝部署 (通过 tools/deploy_system.py)
echo "[3/6] 连接路由器 Telnet 终端..."
cat << 'PYEOF' > /tmp/migrate_ripple.py
import sys
import os
import shutil
import subprocess

sys.path.append(os.path.join(os.getcwd(), "tools"))
import deploy_system

lan_ip = deploy_system.find_real_lan_ip()
print(f"  * 探测到 Mac 本机物理网卡 IP: {lan_ip}")
session = deploy_system.connect_router(mac_ip=lan_ip, host="192.168.10.1", port=2356, user="admin", password="system")

bundle_tar = sys.argv[1]
print("[4/6] 正在高速推送 Ripple-mod 套件到路由器 /var/app (TCP 直连)...")
deploy_system.push_file_to_router(session, bundle_tar, "/tmp/ripple_mod_bundle.tar.gz", port=9999, timeout=60)

print("[5/6] 正在解压套件并清理旧版 CMCC 移动私有残留...")
session.run_cmd("rm -rf /var/app/cmcc_netplug /var/app/cmcc_sec2Router /var/app/scripts /var/app/web/mod_control.html /var/app/web/mod_driver.html /var/app/web/mod_dualwan.html /var/app/web/geek_os.html /var/app/web/mod_plugins.html 2>/dev/null || true")
session.run_cmd("tar -xzf /tmp/ripple_mod_bundle.tar.gz -C /var/app/")
session.run_cmd("rm -f /tmp/ripple_mod_bundle.tar.gz")

print("[6/6] 配置执行权限并执行 Ripple-mod 核心引导 (user.sh)...")
session.run_cmd("killall -9 crond 2>/dev/null || true")
session.run_cmd("chmod +x /var/app/bin/* /var/app/core_system/init.d/*.sh /var/app/core_system/runtime/*.sh /var/app/plugin_engine/*.sh /var/app/plugins/*/*.sh /var/app/plugins/*/scripts/*.sh /var/app/web/*.cgi /var/app/web/cgi-bin/*.cgi 2>/dev/null || true")
session.run_cmd("sh /var/app/core_system/init.d/user.sh")

print("  * 正在热挂载全新 Ripple-mod 控制台到 Web 根目录...")
session.run_cmd("mkdir -p /tmp/web_merged /home/httpd/web/cgi-bin /home/httpd/web/admin 2>/dev/null || true")
session.run_cmd("cp -rf /var/app/web/* /tmp/web_merged/ 2>/dev/null || true")
session.run_cmd("umount /home/httpd/web 2>/dev/null || true")
session.run_cmd("mount -o bind /tmp/web_merged /home/httpd/web 2>/dev/null || mount -o bind /var/app/web /home/httpd/web 2>/dev/null || true")
session.run_cmd("ln -sf /var/app/web/cgi-bin/api.cgi /home/httpd/web/cgi-bin/api.cgi 2>/dev/null || true")
session.run_cmd("ln -sf /var/app/web/cgi-bin/api.cgi /home/httpd/web/api.cgi 2>/dev/null || true")
session.run_cmd("ln -sf /var/app/web/cgi-bin/api.cgi /home/httpd/web/admin/api.cgi 2>/dev/null || true")
session.run_cmd("ln -sf /var/app/web/index.html /home/httpd/web/mod_plugins.html 2>/dev/null || true")

# 重启 API 守护进程以加载新路由和静态文件映射
print("  * 重启 Ripple API 守护进程 (Port 8080)...")
session.run_cmd("killall ripple_api_daemon geek_api_daemon 2>/dev/null || true; sleep 1; /var/app/bin/ripple_api_daemon -d 2>/dev/null || true")

# 确保激活 80 端口到 8080 端口的平滑透明穿透 (无需用户输入 :8080)
print("  * 激活 80 端口到 8080 端口透明重定向...")
session.run_cmd("iptables -t nat -C PREROUTING -p tcp -d 192.168.10.1 --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null || iptables -t nat -I PREROUTING 1 -p tcp -d 192.168.10.1 --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null || true")

session.run_cmd("sync")
session.close()
print("  * 部署完成！")
PYEOF

python3 /tmp/migrate_ripple.py "$BUNDLE_TAR"
rm -f /tmp/migrate_ripple.py

echo ""
echo "============================================================"
echo "  🎉🎉🎉 恭喜！Ripple-mod 全量纯净系统已热升级完毕！"
echo "============================================================"
echo "  1. 浏览器打开全新控制台:"
echo "     👉 http://192.168.10.1/"
echo "     (可体验 7 大面板、插件中心、实时日志与纯 CSS 轻量微动效)"
echo ""
echo "  2. 进入 SSH 终端:"
echo "     👉 ssh root@192.168.10.1 (密码: system)"
echo ""
echo "  3. 一键安装轻量 Python 3 运行环境:"
echo "     👉 在控制台点击【一键安装 Python 3】或在终端执行:"
echo "        sh /var/app/core_system/runtime/install_python.sh"
echo "============================================================"
