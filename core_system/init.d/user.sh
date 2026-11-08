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

# 1. Concurrency Guard (Prevent duplicate boot triggers)
LOCK_FILE="/tmp/ripple_mod_boot.lock"
if [ -d "$LOCK_FILE" ]; then
    echo "[Init] Bootloader already executing or locked. Exiting."
    exit 0
fi
mkdir -p "$LOCK_FILE" 2>/dev/null || exit 0
trap 'rm -rf "$LOCK_FILE"' EXIT INT TERM

echo "[Init] Bootstrapping Ripple-mod Core Runtime..."

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

# 5. OpenWrt Hotplug Hooks Installation
HOTPLUG_DIR="/etc/hotplug.d/iface"
if [ -d "$HOTPLUG_DIR" ] && [ ! -f "$HOTPLUG_DIR/99-ripple-plugins" ]; then
    cat > "$HOTPLUG_DIR/99-ripple-plugins" << 'EOF'
#!/bin/sh
# Ripple-mod WAN/LAN Hotplug Event Forwarder
if [ -x /var/app/plugin_engine/plugin_manager.sh ]; then
    /var/app/plugin_engine/plugin_manager.sh hotplug "$ACTION" "$INTERFACE" "$DEVICE" >/dev/null 2>&1 &
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

# Seamless Port 80 -> 8080 Web Console Access
iptables -t nat -C PREROUTING -p tcp -d 192.168.10.1 --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null || \
iptables -t nat -I PREROUTING 1 -p tcp -d 192.168.10.1 --dport 80 -j REDIRECT --to-ports 8080 2>/dev/null || true

# Port Forwarding Chain Integration
iptables -t nat -N PORT_FORWARD 2>/dev/null || true
iptables -t nat -C PREROUTING -j PORT_FORWARD 2>/dev/null || iptables -t nat -I PREROUTING 1 -j PORT_FORWARD 2>/dev/null || true
if [ -f "$CONF_DIR/port_forward.sh" ]; then
    sh "$CONF_DIR/port_forward.sh" 2>/dev/null || true
fi

# 6.1 Ensure Console Access (Telnet daemon on port 23 and 2356)
if ! pidof telnetd >/dev/null 2>&1; then
    /bin/telnetd -p 23 -l /bin/sh 2>/dev/null || true
    /bin/telnetd -p 2356 -l /bin/sh 2>/dev/null || true
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

# 8. Start Dropbear SSH Daemon
if [ -x "$BIN_DIR/dropbear" ]; then
    mkdir -p /etc/dropbear "$CONF_DIR/ssh"
    KEY_RSA="$CONF_DIR/ssh/dropbear_rsa_host_key"
    KEY_ED25519="$CONF_DIR/ssh/dropbear_ed25519_host_key"
    
    if [ ! -f "$KEY_RSA" ] && [ -x "$BIN_DIR/dropbearkey" ]; then
        "$BIN_DIR/dropbearkey" -t rsa -f "$KEY_RSA" 2>/dev/null
    fi
    if [ ! -f "$KEY_ED25519" ] && [ -x "$BIN_DIR/dropbearkey" ]; then
        "$BIN_DIR/dropbearkey" -t ed25519 -f "$KEY_ED25519" 2>/dev/null
    fi

    if ! pidof dropbear >/dev/null 2>&1; then
        echo "[Init] Starting Dropbear SSH service on port 22..."
        "$BIN_DIR/dropbear" -p 22 -R -P "$STATE_DIR/dropbear.pid" 2>/dev/null || true
    fi
fi

# 9. Start System Crond Scheduler
if [ -x "$BIN_DIR/busybox" ] && ! ps 2>/dev/null | grep -v grep | grep -q crond; then
    echo "[Init] Starting BusyBox crond service..."
    "$BIN_DIR/busybox" crond -c "$CONF_DIR/crontabs" -l 8 2>/dev/null || true
fi

# 10. Start C-based Fast API Daemon
API_BIN=""
[ -x "$BIN_DIR/ripple_api_daemon" ] && API_BIN="$BIN_DIR/ripple_api_daemon"
[ -z "$API_BIN" ] && [ -x "$BIN_DIR/geek_api_daemon" ] && API_BIN="$BIN_DIR/geek_api_daemon"

if [ -n "$API_BIN" ] && ! pidof ripple_api_daemon geek_api_daemon >/dev/null 2>&1; then
    echo "[Init] Starting Ripple API Daemon on port 8080..."
    "$API_BIN" -d >/dev/null 2>&1 &
fi

# 11. Autostart Enabled Plugins via Universal Plugin Engine
if [ -x "$APP_ROOT/plugin_engine/plugin_manager.sh" ]; then
    echo "[Init] Launching enabled plugins..."
    "$APP_ROOT/plugin_engine/plugin_manager.sh" autostart >/dev/null 2>&1 &
fi

echo "[Init] Ripple-mod core runtime bootstrap complete."
exit 0
