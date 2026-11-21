#!/bin/sh
# ==============================================================================
# Ripple-mod - Core Boot Initialization Hook (user.sh)
# Target Platform: Realtek RTL8198D (Linux 5.10.70 SMP MIPS32 MSB)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="/var/app"
LIB_DIR="$APP_ROOT/core_system/lib"

# Load Core Runtime Utilities if available
if [ -f "$LIB_DIR/sys_env.sh" ]; then
    . "$LIB_DIR/sys_env.sh"
else
    export PATH="/var/app/bin:/var/app/opt/bin:/var/app/opt/sbin:/opt/bin:/opt/sbin:/bin:/sbin:/usr/bin:/usr/sbin:$PATH"
    export LD_LIBRARY_PATH="/var/app/lib:/var/app/opt/lib:/opt/lib:/lib:/usr/lib:$LD_LIBRARY_PATH"
fi

CONF_DIR="$APP_ROOT/conf"
BIN_DIR="$APP_ROOT/bin"
PLUGIN_DIR="$APP_ROOT/plugins"
STATE_DIR="/tmp/ripple_mod"

# 1. Atomic Concurrency & One-Shot Boot Guard (Prevent duplicate triggers from rc37 + stock rcS)
FORCE_REINIT=0
[ "$1" = "--force" ] && FORCE_REINIT=1

BOOT_DONE_FLAG="/tmp/ripple_mod_boot.done"
if [ "$FORCE_REINIT" -eq 0 ] && [ -f "$BOOT_DONE_FLAG" ]; then
    echo "[Init] Ripple-mod already bootstrapped ($BOOT_DONE_FLAG present). Skipping duplicate run."
    exit 0
fi

LOCK_FILE="/tmp/ripple_mod_boot.lock"
if ! mkdir "$LOCK_FILE" 2>/dev/null; then
    echo "[Init] Bootloader already executing or locked. Exiting."
    exit 0
fi
trap 'rm -rf "$LOCK_FILE"' EXIT INT TERM

echo "[Init] Bootstrapping Ripple-mod Core Runtime..."

# 1.1 Self-heal /var/app/scripts symlinks to SquashFS failsafe scripts if missing
mkdir -p "$APP_ROOT/scripts" 2>/dev/null || true
for _gs in slot1_confirm_guard.sh rollback_guard.sh confirm_keep.sh anti_ota_shield.sh; do
    if [ -x "/bin/$_gs" ] && [ ! -e "$APP_ROOT/scripts/$_gs" ]; then
        ln -sf "/bin/$_gs" "$APP_ROOT/scripts/$_gs" 2>/dev/null || true
    fi
done

# 2. Initialize Volatile & State Directories on RAMFS (tmpfs)
mkdir -p "$STATE_DIR" /tmp/run /tmp/lock "$CONF_DIR/crontabs" "$CONF_DIR/dnsmasq.d" "$CONF_DIR/hotplug.d/iface"

# 2.1 Universal Toolchain Applets (Ensure standard Unix tools are accessible in PATH)
if [ -x "$BIN_DIR/busybox" ]; then
    for applet in dirname basename awk sed grep tr cut sort uniq head tail wc find xargs tar gzip gunzip expr which; do
        [ ! -e "$BIN_DIR/$applet" ] && ln -sf busybox "$BIN_DIR/$applet" 2>/dev/null || true
    done
fi

# 3. Symlink /opt to persistent app directory for Entware / OpenWrt compatibility
mkdir -p "$APP_ROOT/opt"
if [ ! -L /opt ]; then
    rm -rf /opt 2>/dev/null || true
    ln -s "$APP_ROOT/opt" /opt 2>/dev/null || true
fi

# 4. Enhance /etc/profile if not already configured
if [ -f /etc/profile ] && ! grep -q "Ripple-mod" /etc/profile 2>/dev/null; then
    cat >> /etc/profile << 'EOF'
# Ripple-mod Environment Enhancements
export PATH="/var/app/bin:/var/app/opt/bin:/var/app/opt/sbin:/opt/bin:/opt/sbin:$PATH"
export LD_LIBRARY_PATH="/var/app/lib:/var/app/opt/lib:/opt/lib:$LD_LIBRARY_PATH"
export TERM=xterm-256color
alias ll='ls -la'
alias opkg='/opt/bin/opkg'
export PS1='\[\033[01;32m\]root@Ripple-mod\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]# '
EOF
fi

# 5. OpenWrt Hotplug Hooks Installation (only when /etc/hotplug.d/iface exists and is writable)
HOTPLUG_DIR="/etc/hotplug.d/iface"
if [ -d "$HOTPLUG_DIR" ] && [ -w "$HOTPLUG_DIR" ] && [ ! -f "$HOTPLUG_DIR/99-ripple-plugins" ]; then
    cat > "$HOTPLUG_DIR/99-ripple-plugins" << 'EOF'
#!/bin/sh
# Ripple-mod WAN/LAN Hotplug Event Forwarder
if [ -f /var/app/plugin_engine/plugin_manager.sh ]; then
    sh /var/app/plugin_engine/plugin_manager.sh hotplug "$ACTION" "$INTERFACE" "$DEVICE" >/dev/null 2>&1 &
fi
EOF
    chmod +x "$HOTPLUG_DIR/99-ripple-plugins" 2>/dev/null || true
fi

# 6. Integrate Custom Netfilter Chains (Clean & Non-intrusive to HWNAT)
echo "[Init] Initializing custom Netfilter plugin chains..."
iptables -t mangle -N PLUGIN_PREROUTING 2>/dev/null || iptables -t mangle -F PLUGIN_PREROUTING
iptables -t mangle -C PREROUTING -j PLUGIN_PREROUTING 2>/dev/null || iptables -t mangle -I PREROUTING 1 -j PLUGIN_PREROUTING

iptables -N PLUGIN_FORWARD 2>/dev/null || iptables -F PLUGIN_FORWARD
iptables -C FORWARD -j PLUGIN_FORWARD 2>/dev/null || iptables -I FORWARD 1 -j PLUGIN_FORWARD

iptables -t nat -N PLUGIN_NAT 2>/dev/null || iptables -t nat -F PLUGIN_NAT
iptables -t nat -C POSTROUTING -j PLUGIN_NAT 2>/dev/null || iptables -t nat -I POSTROUTING 1 -j PLUGIN_NAT

# Port 80 -> 8080 redirect is applied in Step 10 only after verifying Web UI + API daemon are ready

# Wait briefly for stock startup to assign br0 IPv4 address (avoid boot race with rc22 startup&)
LAN_IP=""
_br_wait=0
while [ $_br_wait -lt 15 ]; do
    LAN_IP=$(ip -4 addr show dev br0 2>/dev/null | awk '/inet /{print $2; exit}' | cut -d/ -f1)
    [ -z "$LAN_IP" ] && LAN_IP=$(ifconfig br0 2>/dev/null | awk -F'[: ]+' '/inet addr/{print $4; exit}')
    [ -n "$LAN_IP" ] && break
    sleep 1
    _br_wait=$((_br_wait + 1))
done
[ -z "$LAN_IP" ] && LAN_IP="192.168.10.1"
LAN_SUBNET="${LAN_IP%.*}.0/24"

# Universal LAN NAT MASQUERADE & IP Forwarding
[ -w /proc/sys/net/ipv4/ip_forward ] && echo 1 > /proc/sys/net/ipv4/ip_forward 2>/dev/null || true
iptables -t nat -C POSTROUTING -s "$LAN_SUBNET" ! -d "$LAN_SUBNET" -j MASQUERADE 2>/dev/null || \
iptables -t nat -A POSTROUTING -s "$LAN_SUBNET" ! -d "$LAN_SUBNET" -j MASQUERADE 2>/dev/null || true

# Port Forwarding Chain Integration
iptables -t nat -N PORT_FORWARD 2>/dev/null || true
iptables -t nat -C PREROUTING -j PORT_FORWARD 2>/dev/null || iptables -t nat -I PREROUTING 1 -j PORT_FORWARD 2>/dev/null || true
if [ -f "$CONF_DIR/port_forward.sh" ]; then
    sh "$CONF_DIR/port_forward.sh" 2>/dev/null || true
fi

# 6.1 Ensure Login-Protected Console Access (LAN-bound Telnet on port 2356, requires /bin/login)
if ! pidof telnetd >/dev/null 2>&1 && [ -x /bin/telnetd ]; then
    /bin/telnetd -b "$LAN_IP" -p 2356 -l /bin/login 2>/dev/null || \
    /bin/telnetd -p 2356 -l /bin/login 2>/dev/null || true
fi

# 6.2 Wi-Fi Radio DSP, Baseband & Scheduling Subsystem (RF unlock, ATF, EDCCA, latency)
if [ -x "$APP_ROOT/core_system/network/wifi_radio_scheduler.sh" ]; then
    echo "[Init] Launching Wi-Fi radio scheduling & DSP tuning..."
    "$APP_ROOT/core_system/network/wifi_radio_scheduler.sh" start 2>/dev/null || true
fi

# 6.3 Comprehensive Network & High-Throughput Buffer Optimization (综合网络优化)
if [ -x "$APP_ROOT/core_system/network/network_optimizer.sh" ]; then
    "$APP_ROOT/core_system/network/network_optimizer.sh" tune 2>/dev/null || true
fi

# 7. Dnsmasq Drop-in Directory Integration
for conf in /var/dnsmasq.conf /etc/dnsmasq.conf; do
    if [ -f "$conf" ]; then
        if ! grep -q "conf-dir=$CONF_DIR/dnsmasq.d" "$conf"; then
            echo "conf-dir=$CONF_DIR/dnsmasq.d" >> "$conf"
            killall -SIGHUP dnsmasq 2>/dev/null || true
        fi
    fi
done

# 8. Start Dropbear SSH Daemon (persistent keys on writable /var/app/conf/ssh)
if [ -x "$BIN_DIR/dropbear" ]; then
    mkdir -p "$CONF_DIR/ssh" 2>/dev/null || true
    KEY_RSA="$CONF_DIR/ssh/dropbear_rsa_host_key"
    KEY_ED25519="$CONF_DIR/ssh/dropbear_ed25519_host_key"
    
    if [ ! -f "$KEY_RSA" ] && [ -x "$BIN_DIR/dropbearkey" ]; then
        "$BIN_DIR/dropbearkey" -t rsa -f "$KEY_RSA" 2>/dev/null || true
    fi
    if [ ! -f "$KEY_ED25519" ] && [ -x "$BIN_DIR/dropbearkey" ]; then
        "$BIN_DIR/dropbearkey" -t ed25519 -f "$KEY_ED25519" 2>/dev/null || true
    fi

    if ! pidof dropbear dropbearmulti >/dev/null 2>&1; then
        echo "[Init] Starting Dropbear SSH service on ${LAN_IP}:22..."
        DROPBEAR_KEY_ARGS=""
        [ -f "$KEY_ED25519" ] && DROPBEAR_KEY_ARGS="$DROPBEAR_KEY_ARGS -r $KEY_ED25519"
        [ -f "$KEY_RSA" ] && DROPBEAR_KEY_ARGS="$DROPBEAR_KEY_ARGS -r $KEY_RSA"
        "$BIN_DIR/dropbear" -p "${LAN_IP}:22" $DROPBEAR_KEY_ARGS -R -P "$STATE_DIR/dropbear.pid" 2>/dev/null || \
        "$BIN_DIR/dropbear" -p 22 $DROPBEAR_KEY_ARGS -R -P "$STATE_DIR/dropbear.pid" 2>/dev/null || true
    fi
fi

# 9. Start System Crond Scheduler
if [ -x "$BIN_DIR/busybox" ] && ! ps 2>/dev/null | grep -v grep | grep -q crond; then
    echo "[Init] Starting BusyBox crond service..."
    "$BIN_DIR/busybox" crond -c "$CONF_DIR/crontabs" -l 8 2>/dev/null || true
fi

# 10. Prepare Web Console & Start C-based Fast API Daemon
if [ -d "$APP_ROOT/web" ]; then
    [ ! -s "$APP_ROOT/web/mod_plugins.html" ] && [ -s "$APP_ROOT/web/index.html" ] && \
        cp -f "$APP_ROOT/web/index.html" "$APP_ROOT/web/mod_plugins.html" 2>/dev/null || true
    [ ! -s "$APP_ROOT/web/index.html" ] && [ -s "$APP_ROOT/web/mod_plugins.html" ] && \
        cp -f "$APP_ROOT/web/mod_plugins.html" "$APP_ROOT/web/index.html" 2>/dev/null || true

    mkdir -p /tmp/web_merged /home/httpd/web/cgi-bin /home/httpd/web/admin 2>/dev/null || true
    cp -rf "$APP_ROOT/web/"* /tmp/web_merged/ 2>/dev/null || true
    umount /home/httpd/web 2>/dev/null || true
    mount -o bind /tmp/web_merged /home/httpd/web 2>/dev/null || mount -o bind "$APP_ROOT/web" /home/httpd/web 2>/dev/null || true
    ln -sf "$APP_ROOT/web/cgi-bin/api.cgi" /home/httpd/web/cgi-bin/api.cgi 2>/dev/null || true
    ln -sf "$APP_ROOT/web/cgi-bin/api.cgi" /home/httpd/web/api.cgi 2>/dev/null || true
    ln -sf "$APP_ROOT/web/cgi-bin/api.cgi" /home/httpd/web/admin/api.cgi 2>/dev/null || true
fi

API_BIN=""
[ -x "$BIN_DIR/ripple_api_daemon" ] && API_BIN="$BIN_DIR/ripple_api_daemon"
[ -z "$API_BIN" ] && [ -x "$BIN_DIR/geek_api_daemon" ] && API_BIN="$BIN_DIR/geek_api_daemon"

if [ -n "$API_BIN" ] && ! pidof ripple_api_daemon geek_api_daemon >/dev/null 2>&1; then
    echo "[Init] Starting Ripple API Daemon on port 8080..."
    "$API_BIN" -d >/dev/null 2>&1 &
    sleep 1
fi

# Only redirect port 80 -> 8080 when API daemon is running and mod_plugins.html exists (avoid 404 on boot)
if pidof ripple_api_daemon geek_api_daemon >/dev/null 2>&1 && [ -s "$APP_ROOT/web/mod_plugins.html" ]; then
    iptables -t nat -C PREROUTING -p tcp -d "$LAN_IP" --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null || \
    iptables -t nat -I PREROUTING 1 -p tcp -d "$LAN_IP" --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null || true
    # Restrict port 8080 strictly to LAN (br0) & loopback (lo) so WAN cannot reach API daemon
    iptables -N RIPPLE_INPUT 2>/dev/null || iptables -F RIPPLE_INPUT
    iptables -A RIPPLE_INPUT -i br0 -j RETURN 2>/dev/null || true
    iptables -A RIPPLE_INPUT -i lo -j RETURN 2>/dev/null || true
    iptables -A RIPPLE_INPUT -p tcp --dport 8080 -j DROP 2>/dev/null || true
    iptables -C INPUT -j RIPPLE_INPUT 2>/dev/null || iptables -I INPUT 1 -j RIPPLE_INPUT 2>/dev/null || true
fi

# 11. Autostart Enabled Plugins via Universal Plugin Engine
if [ -f "$APP_ROOT/plugin_engine/plugin_manager.sh" ]; then
    echo "[Init] Launching enabled plugins..."
    sh "$APP_ROOT/plugin_engine/plugin_manager.sh" autostart >/dev/null 2>&1 &
fi

touch /tmp/ripple_mod_boot.done 2>/dev/null || true
echo "[Init] Ripple-mod core runtime bootstrap complete."
exit 0
