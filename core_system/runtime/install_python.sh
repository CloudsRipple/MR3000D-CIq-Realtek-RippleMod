#!/bin/sh
# ==============================================================================
# One-Click Python 3 Runtime Installer for Ripple-mod
# ==============================================================================
set -e

echo "[*] Checking Python runtime environment..."

if command -v python3 >/dev/null 2>&1 || [ -x /opt/bin/python3 ]; then
    echo "Python 3 is already installed:"
    /opt/bin/python3 --version 2>/dev/null || python3 --version
    exit 0
fi

# Ensure Entware is available
if [ ! -x /opt/bin/opkg ]; then
    echo "[*] Entware / OPKG not detected. Bootstrapping Entware first..."
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    if [ -f "$SCRIPT_DIR/bootstrap_entware.sh" ]; then
        sh "$SCRIPT_DIR/bootstrap_entware.sh"
    else
        echo "ERROR: bootstrap_entware.sh not found."
        exit 1
    fi
fi

echo "[*] Updating Entware package repository index..."
/opt/bin/opkg update

echo "[*] Installing Python 3 Lightweight runtime..."
# python3-light contains standard lib + socket + ssl + json + os with minimal RAM overhead
/opt/bin/opkg install python3-light python3-pip

if [ -x /opt/bin/python3 ]; then
    # Configure Fast Domestic PyPI Mirror
    mkdir -p /root/.pip
    cat > /root/.pip/pip.conf << 'EOF'
[global]
index-url = https://mirrors.aliyun.com/pypi/simple/
trusted-host = mirrors.aliyun.com
timeout = 30
EOF

    echo "============================================================"
    echo " SUCCESS: Python 3 runtime is ready on Ripple-mod!"
    /opt/bin/python3 --version
    echo " Binary: /opt/bin/python3"
    echo " Pip   : /opt/bin/pip3 (Configured with Aliyun mirror)"
    echo "============================================================"
else
    echo "ERROR: python3 package installation failed."
    exit 1
fi
