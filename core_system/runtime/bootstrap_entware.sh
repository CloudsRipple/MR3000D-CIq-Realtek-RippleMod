#!/bin/sh
# ==============================================================================
# Entware & OPKG Bootstrap Script for Ripple-mod
# Target Architecture: Realtek RTL8198D (MIPS32r2 Big-Endian mipssf-k3.4)
# ==============================================================================
set -e

APP_DIR="/var/app"
OPT_DIR="$APP_DIR/opt"
ARCH="mipssf-k3.4"

# Official & Backup Mirrors
URL_OFFICIAL="http://bin.entware.net/${ARCH}/installer/generic.sh"
URL_MIRROR="https://bin.entware.net/${ARCH}/installer/generic.sh"

echo "============================================================"
echo " Ripple-mod Entware & OPKG Package Manager Installer"
echo " Target Architecture: MIPS Big-Endian (${ARCH})"
echo " Target Directory   : ${OPT_DIR} -> /opt"
echo "============================================================"

# 1. Connectivity Check
echo "[*] Verifying WAN connectivity..."
online=0
for probe_host in 223.5.5.5 119.29.29.29 1.1.1.1 8.8.8.8; do
    if ping -c 1 -W 2 "$probe_host" >/dev/null 2>&1; then
        online=1
        break
    fi
done

if [ $online -eq 0 ]; then
    echo "ERROR: WAN network is unreachable. Please ensure the router is online."
    exit 1
fi

# 2. Prepare persistent directory and /opt symlink
mkdir -p "$OPT_DIR"
if [ -d /opt ] && [ ! -L /opt ]; then
    echo "[*] Migrating existing /opt data..."
    cp -a /opt/* "$OPT_DIR/" 2>/dev/null || true
    rm -rf /opt
fi

if [ ! -L /opt ]; then
    ln -sf "$OPT_DIR" /opt
fi

# 3. Download Installer with Retry and Fallback
INSTALLER_TMP="/tmp/entware_generic_install.sh"
download_ok=0

echo "[*] Downloading installer script..."
for url in "$URL_OFFICIAL" "$URL_MIRROR"; do
    if command -v curl >/dev/null 2>&1; then
        if curl -sSL --connect-timeout 5 -m 30 "$url" -o "$INSTALLER_TMP"; then
            download_ok=1
            break
        fi
    elif command -v wget >/dev/null 2>&1; then
        if wget -q -T 30 "$url" -O "$INSTALLER_TMP"; then
            download_ok=1
            break
        fi
    fi
done

if [ $download_ok -eq 0 ] || [ ! -s "$INSTALLER_TMP" ]; then
    echo "ERROR: Failed to download Entware bootstrap installer from all mirrors."
    exit 1
fi

chmod +x "$INSTALLER_TMP"

# 4. Execute Installer into /opt
echo "[*] Running Entware installer..."
sh "$INSTALLER_TMP"
rm -f "$INSTALLER_TMP"

# 5. Verify & Setup Profile
if [ -x /opt/bin/opkg ]; then
    echo "============================================================"
    echo " SUCCESS: Entware package manager (opkg) is installed!"
    /opt/bin/opkg --version || true
    echo ""
    echo " Available packages: 2500+ MIPS packages"
    echo " Next steps:"
    echo "   opkg update"
    echo "   opkg install python3-light"
    echo "   opkg install nano htop iperf3 tcpdump"
    echo "============================================================"
    exit 0
else
    echo "ERROR: /opt/bin/opkg binary missing after installation."
    exit 1
fi
