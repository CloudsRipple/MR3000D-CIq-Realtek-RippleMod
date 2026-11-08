#!/bin/sh
# ==============================================================================
# MR3000D-CIq Wi-Fi 6 AX3000 & RF Studio Tuner
# Location: /var/app/scripts/wifi_tuner.sh
# ==============================================================================

ACTION="${1:-status}"
ARG2="$2"
ARG3="$3"
ARG4="$4"
ARG5="$5"

CONF_DIR="/var/app/conf/wifi"
mkdir -p "$CONF_DIR"

do_status() {
    WLAN0_SSID=$(iwpriv wlan0 get_mib ssid 2>/dev/null | awk -F: '{print $2}' | tr -d ' ')
    WLAN0_CH=$(iwpriv wlan0 get_mib channel 2>/dev/null | awk -F: '{print $2}' | tr -d ' ')
    WLAN0_BW=$(iwpriv wlan0 get_mib use40M 2>/dev/null | awk -F: '{print $2}' | tr -d ' ')
    WLAN0_PWR=$(iwpriv wlan0 get_mib powerpercent 2>/dev/null | awk -F: '{print $2}' | tr -d ' ')
    WLAN0_STA=$(iwpriv wlan0 get_sta_num 2>/dev/null | awk -F: '{print $2}' | tr -d ' ')

    WLAN1_SSID=$(iwpriv wlan1 get_mib ssid 2>/dev/null | awk -F: '{print $2}' | tr -d ' ')
    WLAN1_CH=$(iwpriv wlan1 get_mib channel 2>/dev/null | awk -F: '{print $2}' | tr -d ' ')
    WLAN1_BW=$(iwpriv wlan1 get_mib use40M 2>/dev/null | awk -F: '{print $2}' | tr -d ' ')
    WLAN1_PWR=$(iwpriv wlan1 get_mib powerpercent 2>/dev/null | awk -F: '{print $2}' | tr -d ' ')
    WLAN1_STA=$(iwpriv wlan1 get_sta_num 2>/dev/null | awk -F: '{print $2}' | tr -d ' ')

    BW5_STR="80MHz"
    [ "$WLAN0_BW" = "3" ] && BW5_STR="160MHz"
    [ "$WLAN0_BW" = "1" ] && BW5_STR="40MHz"
    [ "$WLAN0_BW" = "0" ] && BW5_STR="20MHz"

    echo "=== Wi-Fi 6 AX3000 RF Status ==="
    echo "WLAN0 (5GHz AX 2402M): SSID=${WLAN0_SSID:-Wi-Fi-5G}, Ch=${WLAN0_CH:-44}, BW=${BW5_STR}, Power=${WLAN0_PWR:-100}%, Clients=${WLAN0_STA:-0}"
    echo "WLAN1 (2.4GHz AX 574M): SSID=${WLAN1_SSID:-Wi-Fi-2.4G}, Ch=${WLAN1_CH:-6}, BW=40MHz, Power=${WLAN1_PWR:-100}%, Clients=${WLAN1_STA:-0}"
    
    if [ -f /var/app/conf/.rf_unlocked ]; then
        echo "REGULATION_OVERRIDE: UNLOCKED (Regulation=NONE, Max EIRP)"
    else
        echo "REGULATION_OVERRIDE: STOCK_RESTRICTED"
    fi
}

do_set() {
    BAND="${ARG2:-5g}"
    POWER="${ARG3:-100}"
    CHANNEL="${ARG4:-44}"
    BW="${ARG5:-160}"

    IFACE="wlan0"
    [ "$BAND" = "2.4g" ] && IFACE="wlan1"

    echo "[*] Configuring $IFACE ($BAND)..."

    # Bandwidth mapping: 20M=0, 40M=1, 80M=2, 160M=3
    BW_VAL=2
    if [ "$BW" = "160" ] || [ "$BW" = "3" ]; then
        BW_VAL=3
    elif [ "$BW" = "80" ] || [ "$BW" = "2" ]; then
        BW_VAL=2
    elif [ "$BW" = "40" ] || [ "$BW" = "1" ]; then
        BW_VAL=1
    elif [ "$BW" = "20" ] || [ "$BW" = "0" ]; then
        BW_VAL=0
    fi

    # Set parameters via Realtek private ioctl
    [ "$POWER" != "0" ] && iwpriv "$IFACE" set_mib "powerpercent=$POWER" 2>/dev/null
    [ "$CHANNEL" != "0" ] && iwpriv "$IFACE" set_mib "channel=$CHANNEL" 2>/dev/null
    iwpriv "$IFACE" set_mib "use40M=$BW_VAL" 2>/dev/null

    echo "[OK] Applied to $IFACE: Power=$POWER%, Channel=$CHANNEL, use40M=$BW_VAL"
}

do_unlock() {
    echo "[*] Unlocking Maximum RF Transmit Power (Regulation=NONE)..."
    mkdir -p /var/app/conf/rtl8852ce /var/app/conf/rtl8192xbe

    # Copy template if available
    if [ -d /etc/conf/rtl8852ce ]; then
        cp -rf /etc/conf/rtl8852ce/* /var/app/conf/rtl8852ce/ 2>/dev/null || true
    fi
    if [ -d /etc/conf/rtl8192xbe ]; then
        cp -rf /etc/conf/rtl8192xbe/* /var/app/conf/rtl8192xbe/ 2>/dev/null || true
    fi

    # Patch TXPWR_LMT.txt to Regulation=NONE
    find /var/app/conf -name "TXPWR_LMT.txt" -exec sed -i 's/Regulation=.*/Regulation=NONE/g' {} + 2>/dev/null || true

    # Force powerpercent to 100 on both radios
    iwpriv wlan0 set_mib powerpercent=100 2>/dev/null || true
    iwpriv wlan1 set_mib powerpercent=100 2>/dev/null || true

    touch /var/app/conf/.rf_unlocked
    echo "[OK] RF Power restriction removed. 160MHz full TX power active."
}

do_raw_mib() {
    IFACE="${ARG2:-wlan0}"
    PARAM="$ARG3"

    if [ -z "$PARAM" ]; then
        echo "Usage: $0 mib <wlan0|wlan1> <mib_name>[=<value>]"
        exit 1
    fi

    if echo "$PARAM" | grep -q "="; then
        iwpriv "$IFACE" set_mib "$PARAM"
        echo "[OK] Set MIB on $IFACE: $PARAM"
    else
        VAL=$(iwpriv "$IFACE" get_mib "$PARAM" 2>/dev/null)
        echo "$VAL"
    fi
}

case "$ACTION" in
    set)
        do_set
        ;;
    unlock)
        do_unlock
        ;;
    mib)
        do_raw_mib
        ;;
    status|*)
        do_status
        ;;
esac
