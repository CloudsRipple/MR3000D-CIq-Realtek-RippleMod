#!/bin/sh
# ==============================================================================
# Ripple-mod - Universal Web CGI Gateway (api.cgi)
# Supports both Standard Web CGI (HTTP headers) & Fast Daemon CLI (--raw-json)
# ==============================================================================

export PATH="/var/app/bin:/var/app/opt/bin:/var/app/opt/sbin:/opt/bin:/opt/sbin:/bin:/sbin:/usr/bin:/usr/sbin:$PATH"
export LD_LIBRARY_PATH="/var/app/lib:/var/app/opt/lib:/opt/lib:/lib:/usr/lib:$LD_LIBRARY_PATH"

RAW_JSON_MODE=0
if [ "$1" = "--raw-json" ]; then
    RAW_JSON_MODE=1
    shift
fi

# In standard CGI mode, output HTTP headers
if [ $RAW_JSON_MODE -eq 0 ]; then
    printf "Content-Type: application/json; charset=utf-8\r\n"
    printf "Access-Control-Allow-Origin: *\r\n"
    printf "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
    printf "Access-Control-Allow-Headers: Content-Type\r\n"
    printf "X-Content-Type-Options: nosniff\r\n\r\n"

    if [ "$REQUEST_METHOD" = "OPTIONS" ]; then
        printf '{"status":0}\n'
        exit 0
    fi
fi

DISPATCHER="/var/app/plugin_engine/api_dispatcher.sh"
PLUGIN_MGR="/var/app/plugin_engine/plugin_manager.sh"

# Extract parameters from CLI argument or HTTP query
if [ -n "$1" ]; then
    QUERY="$1"
else
    QUERY="${QUERY_STRING:-}"
    if [ "$REQUEST_METHOD" = "POST" ]; then
        read -r POST_DATA
        if [ -n "$POST_DATA" ]; then
            if [ -n "$QUERY" ]; then
                QUERY="${QUERY}&${POST_DATA}"
            else
                QUERY="${POST_DATA}"
            fi
        fi
    fi
fi

# Robust URL decode function
urldecode() {
    printf '%b' "$(printf '%s' "$1" | sed 's/+/ /g; s/%\([0-9a-fA-F][0-9a-fA-F]\)/\\x\1/g')"
}

get_param() {
    key="$1"
    raw_val=$(printf '%s' "$QUERY" | tr '&' '\n' | grep "^${key}=" | head -n 1 | cut -d'=' -f2-)
    urldecode "$raw_val"
}

action=$(get_param "action")
plugin=$(get_param "plugin")
cmd=$(get_param "cmd")
args=$(get_param "args")

case "$action" in
    # System Telemetry & Metrics
    sysinfo)
        uptime_sec=$(cut -d'.' -f1 /proc/uptime 2>/dev/null || echo "0")
        [ -z "$uptime_sec" ] && uptime_sec="0"

        # Memory usage
        mem_total=$(awk '/MemTotal/ {print $2}' /proc/meminfo 2>/dev/null || echo "243616")
        [ -z "$mem_total" ] && mem_total="243616"
        mem_free=$(awk '/MemAvailable/ {print $2}' /proc/meminfo 2>/dev/null || awk '/MemFree/ {print $2}' /proc/meminfo 2>/dev/null || echo "0")
        [ -z "$mem_free" ] && mem_free="0"
        mem_used=$((mem_total - mem_free))
        [ $mem_used -lt 0 ] && mem_used=0
        mem_pct=$(( (mem_used * 100) / (mem_total > 0 ? mem_total : 1) ))

        # Real CPU usage from /proc/stat differential ticks
        cpu_pct=$(awk 'NR==1 {
            curr_t=$2+$3+$4+$5+$6+$7+$8; curr_i=$5+$6;
            pct = 5;
            if ((getline < "/tmp/.last_cpu_stat") > 0) {
                dt = curr_t - $1;
                di = curr_i - $2;
                if (dt > 0) pct = int((dt - di) * 100 / dt);
            }
            if (pct < 0) pct = 0;
            if (pct > 100) pct = 100;
            print pct;
        }' /proc/stat 2>/dev/null || echo "5")
        awk 'NR==1 {print $2+$3+$4+$5+$6+$7+$8, $5+$6}' /proc/stat > /tmp/.last_cpu_stat 2>/dev/null || true
        [ -z "$cpu_pct" ] && cpu_pct=5
        [ $cpu_pct -lt 0 ] && cpu_pct=0
        [ $cpu_pct -gt 100 ] && cpu_pct=100
        load=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || echo "0.00 0.00 0.00")
        
        # Disk usage for persistent storage (/var/app)
        app_disk_total_kb=$(df -k /var/app 2>/dev/null | awk 'NR==2 {print $2}' || echo "26624")
        [ -z "$app_disk_total_kb" ] && app_disk_total_kb="26624"
        app_disk_used_kb=$(df -k /var/app 2>/dev/null | awk 'NR==2 {print $3}' || echo "13312")
        [ -z "$app_disk_used_kb" ] && app_disk_used_kb="13312"
        app_disk_free_kb=$(df -k /var/app 2>/dev/null | awk 'NR==2 {print $4}' || echo "13312")
        [ -z "$app_disk_free_kb" ] && app_disk_free_kb="13312"
        storage_pct=$(( (app_disk_used_kb * 100) / (app_disk_total_kb > 0 ? app_disk_total_kb : 1) ))
        
        # Check Python and Package Managers
        has_python="false"
        py_ver=""
        if [ -x /opt/bin/python3 ] || command -v python3 >/dev/null 2>&1; then
            has_python="true"
            py_ver=$(python3 --version 2>&1 | cut -d' ' -f2 | tr -d '\r\n')
        fi
        
        has_opkg="false"
        [ -x /opt/bin/opkg ] && has_opkg="true"
        
        # Check SSH and Cron (robust check matching BusyBox multi-call binaries)
        has_ssh="false"
        if ps 2>/dev/null | grep -v grep | grep -q dropbear; then
            has_ssh="true"
        fi
        has_crond="false"
        if ps 2>/dev/null | grep -v grep | grep -q crond; then
            has_crond="true"
        fi

        # WAN Interface detection
        wan_ip=$(ip -4 addr show nas0 2>/dev/null | awk '/inet / {print $2}' | cut -d'/' -f1 | tr -d '\r\n')
        [ -z "$wan_ip" ] && wan_ip=$(ip -4 addr show eth0 2>/dev/null | awk '/inet / {print $2}' | cut -d'/' -f1 | tr -d '\r\n')
        [ -z "$wan_ip" ] && wan_ip="未连接"

        # LAN Gateway & Clients
        lan_ip=$(ip -4 addr show br0 2>/dev/null | awk '/inet / {print $2}' | cut -d'/' -f1 | tr -d '\r\n')
        [ -z "$lan_ip" ] && lan_ip="192.168.10.1"
        lan_clients=$(grep -c "br0" /proc/net/arp 2>/dev/null || echo "1")
        [ -z "$lan_clients" ] && lan_clients="1"

        # HWNAT Status
        hwnat_active="true"
        if [ -f /proc/fc/ctrl/hwnat ]; then
            head -n 1 /proc/fc/ctrl/hwnat 2>/dev/null | grep -qi "Disable" && hwnat_active="false"
        fi

        # Wi-Fi Status
        wifi2_ssid=$(iwpriv wlan0 get_mib ssid 2>/dev/null | cut -d':' -f2 | tr -d '\r\n' || echo "MR3000D-2.4G")
        wifi2_ch=$(iwpriv wlan0 get_mib channel 2>/dev/null | cut -d':' -f2 | tr -d '\r\n' || echo "6")
        wifi5_ssid=$(iwpriv wlan1 get_mib ssid 2>/dev/null | cut -d':' -f2 | tr -d '\r\n' || echo "MR3000D-5G")
        wifi5_ch=$(iwpriv wlan1 get_mib channel 2>/dev/null | cut -d':' -f2 | tr -d '\r\n' || echo "36")

        w2_scale=$(flash get WLAN_RFPOWER_SCALE 2>/dev/null | cut -d'=' -f2-)
        case "$w2_scale" in
            1) w2_power_str="标准模式 (70%)" ;;
            2) w2_power_str="节能模式 (50%)" ;;
            3) w2_power_str="微功率 (35%)" ;;
            *) w2_power_str="穿墙模式 (100%)" ;;
        esac
        w5_scale=$(flash get WLAN1_RFPOWER_SCALE 2>/dev/null | cut -d'=' -f2-)
        case "$w5_scale" in
            1) w5_power_str="标准模式 (70%)" ;;
            2) w5_power_str="节能模式 (50%)" ;;
            3) w5_power_str="微功率 (35%)" ;;
            *) w5_power_str="穿墙模式 (100%)" ;;
        esac

        # Clean single-line kernel string
        kernel_str=$(head -n 1 /proc/version 2>/dev/null | cut -d' ' -f1-3 | tr -d '\r\n')
        [ -z "$kernel_str" ] && kernel_str="Linux 5.10.70"

        cat << EOF
{
  "status": 0,
  "system": {
    "hostname": "MR3000D-CIq",
    "version": "v0.2.1",
    "kernel": "$kernel_str",
    "uptime_seconds": $uptime_sec,
    "cpu": {
      "cores": 2,
      "arch": "MIPS32r2 (RTL8198D 1.0GHz)",
      "load_average": "$load",
      "load_percent": $cpu_pct
    },
    "memory": {
      "total_kb": $mem_total,
      "used_kb": $mem_used,
      "free_kb": $mem_free,
      "percent": $mem_pct
    },
    "storage": {
      "total_kb": $app_disk_total_kb,
      "used_kb": $app_disk_used_kb,
      "free_kb": $app_disk_free_kb,
      "percent": $storage_pct
    },
    "network": {
      "wan_ip": "$wan_ip",
      "lan_ip": "$lan_ip",
      "lan_clients": $lan_clients,
      "hwnat": $hwnat_active
    },
    "wifi": {
      "wifi_2g": {
        "ssid": "$wifi2_ssid",
        "channel": "$wifi2_ch",
        "standard": "802.11b/g/n (574 Mbps)",
        "power": "$w2_power_str",
        "active": true
      },
      "wifi_5g": {
        "ssid": "$wifi5_ssid",
        "channel": "$wifi5_ch",
        "bandwidth": "160 MHz",
        "standard": "Wi-Fi 6 AX (2402 Mbps)",
        "power": "$w5_power_str",
        "active": true
      }
    },
    "services": {
      "ssh": $has_ssh,
      "crond": $has_crond,
      "opkg": $has_opkg,
      "python": $has_python,
      "python_version": "$py_ver"
    }
  }
}
EOF
        ;;

    # Plugin Management APIs
    plugin_list)
        [ -x "$PLUGIN_MGR" ] && "$PLUGIN_MGR" list || echo '{"status":1,"error":"Plugin manager missing"}'
        ;;

    plugin_start)
        [ -x "$PLUGIN_MGR" ] && "$PLUGIN_MGR" start "$plugin" || echo '{"status":1,"error":"Plugin manager missing"}'
        ;;

    plugin_stop)
        [ -x "$PLUGIN_MGR" ] && "$PLUGIN_MGR" stop "$plugin" || echo '{"status":1,"error":"Plugin manager missing"}'
        ;;

    plugin_restart)
        [ -x "$PLUGIN_MGR" ] && "$PLUGIN_MGR" restart "$plugin" || echo '{"status":1,"error":"Plugin manager missing"}'
        ;;

    plugin_enable)
        [ -x "$PLUGIN_MGR" ] && "$PLUGIN_MGR" enable "$plugin" || echo '{"status":1,"error":"Plugin manager missing"}'
        ;;

    plugin_disable)
        [ -x "$PLUGIN_MGR" ] && "$PLUGIN_MGR" disable "$plugin" || echo '{"status":1,"error":"Plugin manager missing"}'
        ;;

    plugin_status)
        [ -x "$PLUGIN_MGR" ] && "$PLUGIN_MGR" status "$plugin" || echo '{"status":1,"error":"Plugin manager missing"}'
        ;;

    plugin_uninstall)
        [ -x "$PLUGIN_MGR" ] && "$PLUGIN_MGR" uninstall "$plugin" || echo '{"status":1,"error":"Plugin manager missing"}'
        ;;

    plugin_install_url)
        pkg_url=$(get_param "url")
        if [ -z "$pkg_url" ]; then
            echo '{"status":1,"error":"缺少插件下载 URL"}'
            exit 1
        fi
        tmp_tar="/tmp/plugin_dl_$$.tar.gz"
        rm -f "$tmp_tar"
        if command -v curl >/dev/null 2>&1; then
            curl -sSL -m 30 "$pkg_url" -o "$tmp_tar" || true
        elif command -v wget >/dev/null 2>&1; then
            wget -q -T 30 "$pkg_url" -O "$tmp_tar" || true
        fi
        if [ ! -s "$tmp_tar" ]; then
            rm -f "$tmp_tar"
            echo '{"status":1,"error":"下载插件失败，请检查网络或 URL 有效性"}'
            exit 1
        fi
        res=$("$PLUGIN_MGR" install "$tmp_tar")
        rm -f "$tmp_tar"
        echo "$res"
        ;;

    plugin_install_base64)
        pkg_b64=$(get_param "data")
        if [ -z "$pkg_b64" ]; then
            echo '{"status":1,"error":"缺少插件上传数据"}'
            exit 1
        fi
        tmp_tar="/tmp/plugin_upload_$$.tar.gz"
        rm -f "$tmp_tar"
        printf '%s' "$pkg_b64" | openssl base64 -d > "$tmp_tar" 2>/dev/null || true
        if [ ! -s "$tmp_tar" ]; then
            rm -f "$tmp_tar"
            echo '{"status":1,"error":"插件解包数据解码失败"}'
            exit 1
        fi
        res=$("$PLUGIN_MGR" install "$tmp_tar")
        rm -f "$tmp_tar"
        echo "$res"
        ;;

    # Generic Dynamic Plugin RPC Bridge
    plugin_call)
        if [ -x "$DISPATCHER" ]; then
            "$DISPATCHER" call "$plugin" "$cmd" "$args"
        else
            echo '{"status":1,"error":"API dispatcher not installed"}'
        fi
        ;;

    # Wi-Fi Configuration APIs
    wifi_get)
        w2_ssid=$(flash get SSID 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w2_ssid" ] && w2_ssid="MR3000D-2.4G"
        w2_pass=$(flash get WLAN_WPA_PSK 2>/dev/null | cut -d'=' -f2-)
        w2_auto=$(flash get AUTO_CHANNEL 2>/dev/null | cut -d'=' -f2-)
        w2_ch=$(flash get CHANNEL 2>/dev/null | cut -d'=' -f2-)
        [ "$w2_auto" = "1" ] && w2_ch="0"
        [ -z "$w2_ch" ] && w2_ch="0"
        w2_bw=$(flash get WLAN_CHANNELWIDTH 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w2_bw" ] && w2_bw="1"
        w2_hide=$(flash get HIDDEN_SSID 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w2_hide" ] && w2_hide="0"
        w2_dis=$(flash get WLAN_DISABLED 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w2_dis" ] && w2_dis="0"
        w2_power=$(flash get WLAN_RFPOWER_SCALE 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w2_power" ] && w2_power="0"
        w2_pct=$(flash get WLAN__TX_POWER_PCT 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w2_pct" ] && w2_pct="100"
        w2_enc=$(flash get WLAN_ENCRYPT 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w2_enc" ] && w2_enc="6"
        w2_iso=$(flash get WLAN_BLOCK_RELAY 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w2_iso" ] && w2_iso="0"

        w5_ssid=$(flash get WLAN1_SSID 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w5_ssid" ] && w5_ssid="MR3000D-5G"
        w5_pass=$(flash get WLAN1_WPA_PSK 2>/dev/null | cut -d'=' -f2-)
        w5_auto=$(flash get WLAN1_AUTO_CHANNEL 2>/dev/null | cut -d'=' -f2-)
        w5_ch=$(flash get WLAN1_CHANNEL 2>/dev/null | cut -d'=' -f2-)
        [ "$w5_auto" = "1" ] && w5_ch="0"
        [ -z "$w5_ch" ] && w5_ch="0"
        w5_bw=$(flash get WLAN1_CHANNELWIDTH 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w5_bw" ] && w5_bw="3"
        w5_hide=$(flash get WLAN1_HIDDEN_SSID 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w5_hide" ] && w5_hide="0"
        w5_dis=$(flash get WLAN1_DISABLED 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w5_dis" ] && w5_dis="0"
        w5_power=$(flash get WLAN1_RFPOWER_SCALE 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w5_power" ] && w5_power="0"
        w5_pct=$(flash get WLAN1_TX_POWER_PCT 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w5_pct" ] && w5_pct="100"
        w5_enc=$(flash get WLAN1_ENCRYPT 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w5_enc" ] && w5_enc="6"
        w5_iso=$(flash get WLAN1_BLOCK_RELAY 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w5_iso" ] && w5_iso="0"
        w5_ofdma=$(flash get WLAN1_OFDMA_ENABLED_FOR_WEB 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w5_ofdma" ] && w5_ofdma="1"
        w5_mimo=$(flash get WLAN1_MIMO_ENABLED 2>/dev/null | cut -d'=' -f2-)
        [ -z "$w5_mimo" ] && w5_mimo="0"

        cat << EOF
{
  "status": 0,
  "wifi_2g": {
    "ssid": "$w2_ssid",
    "password": "$w2_pass",
    "channel": $w2_ch,
    "bandwidth": $w2_bw,
    "power": $w2_power,
    "power_pct": $w2_pct,
    "encrypt": $w2_enc,
    "isolation": $([ "$w2_iso" = "1" ] && echo true || echo false),
    "hidden": $([ "$w2_hide" = "1" ] && echo true || echo false),
    "enabled": $([ "$w2_dis" = "1" ] && echo false || echo true)
  },
  "wifi_5g": {
    "ssid": "$w5_ssid",
    "password": "$w5_pass",
    "channel": $w5_ch,
    "bandwidth": $w5_bw,
    "power": $w5_power,
    "power_pct": $w5_pct,
    "encrypt": $w5_enc,
    "isolation": $([ "$w5_iso" = "1" ] && echo true || echo false),
    "ofdma": $([ "$w5_ofdma" = "1" ] && echo true || echo false),
    "mimo": $([ "$w5_mimo" = "1" ] && echo true || echo false),
    "hidden": $([ "$w5_hide" = "1" ] && echo true || echo false),
    "enabled": $([ "$w5_dis" = "1" ] && echo false || echo true)
  }
}
EOF
        ;;

    wifi_set)
        val_ssid_2g=$(get_param "ssid_2g")
        val_pass_2g=$(get_param "pass_2g")
        val_ch_2g=$(get_param "ch_2g")
        val_bw_2g=$(get_param "bw_2g")
        val_hide_2g=$(get_param "hide_2g")
        val_enable_2g=$(get_param "enable_2g")
        val_power_2g=$(get_param "power_2g")
        val_encrypt_2g=$(get_param "encrypt_2g")
        val_isolate_2g=$(get_param "isolate_2g")

        val_ssid_5g=$(get_param "ssid_5g")
        val_pass_5g=$(get_param "pass_5g")
        val_ch_5g=$(get_param "ch_5g")
        val_bw_5g=$(get_param "bw_5g")
        val_hide_5g=$(get_param "hide_5g")
        val_enable_5g=$(get_param "enable_5g")
        val_power_5g=$(get_param "power_5g")
        val_encrypt_5g=$(get_param "encrypt_5g")
        val_isolate_5g=$(get_param "isolate_5g")
        val_ofdma_5g=$(get_param "ofdma_5g")
        val_mimo_5g=$(get_param "mimo_5g")

        if [ -n "$val_ssid_2g" ] || [ -n "$val_power_2g" ] || [ -n "$val_enable_2g" ]; then
            [ -n "$val_ssid_2g" ] && flash set SSID "$val_ssid_2g" >/dev/null 2>&1
            [ -n "$val_pass_2g" ] && flash set WLAN_WPA_PSK "$val_pass_2g" >/dev/null 2>&1
            if [ -n "$val_ch_2g" ]; then
                if [ "$val_ch_2g" = "0" ]; then
                    flash set AUTO_CHANNEL 1 >/dev/null 2>&1
                else
                    flash set AUTO_CHANNEL 0 >/dev/null 2>&1
                    flash set CHANNEL "$val_ch_2g" >/dev/null 2>&1
                fi
            fi
            [ -n "$val_bw_2g" ] && flash set WLAN_CHANNELWIDTH "$val_bw_2g" >/dev/null 2>&1
            [ -n "$val_hide_2g" ] && flash set HIDDEN_SSID "$val_hide_2g" >/dev/null 2>&1
            [ -n "$val_enable_2g" ] && flash set WLAN_DISABLED "$([ "$val_enable_2g" = "1" ] && echo 0 || echo 1)" >/dev/null 2>&1
            if [ -n "$val_power_2g" ]; then
                flash set WLAN_RFPOWER_SCALE "$val_power_2g" >/dev/null 2>&1
                case "$val_power_2g" in
                    0) p2_pct=100 ;;
                    1) p2_pct=70 ;;
                    2) p2_pct=50 ;;
                    3) p2_pct=35 ;;
                    *) p2_pct=100 ;;
                esac
                flash set WLAN__TX_POWER_PCT "$p2_pct" >/dev/null 2>&1
            fi
            [ -n "$val_encrypt_2g" ] && flash set WLAN_ENCRYPT "$val_encrypt_2g" >/dev/null 2>&1
            [ -n "$val_isolate_2g" ] && flash set WLAN_BLOCK_RELAY "$val_isolate_2g" >/dev/null 2>&1
        fi

        if [ -n "$val_ssid_5g" ] || [ -n "$val_power_5g" ] || [ -n "$val_enable_5g" ]; then
            [ -n "$val_ssid_5g" ] && flash set WLAN1_SSID "$val_ssid_5g" >/dev/null 2>&1
            [ -n "$val_pass_5g" ] && flash set WLAN1_WPA_PSK "$val_pass_5g" >/dev/null 2>&1
            if [ -n "$val_ch_5g" ]; then
                if [ "$val_ch_5g" = "0" ]; then
                    flash set WLAN1_AUTO_CHANNEL 1 >/dev/null 2>&1
                else
                    flash set WLAN1_AUTO_CHANNEL 0 >/dev/null 2>&1
                    flash set WLAN1_CHANNEL "$val_ch_5g" >/dev/null 2>&1
                fi
            fi
            [ -n "$val_bw_5g" ] && flash set WLAN1_CHANNELWIDTH "$val_bw_5g" >/dev/null 2>&1
            [ -n "$val_hide_5g" ] && flash set WLAN1_HIDDEN_SSID "$val_hide_5g" >/dev/null 2>&1
            [ -n "$val_enable_5g" ] && flash set WLAN1_DISABLED "$([ "$val_enable_5g" = "1" ] && echo 0 || echo 1)" >/dev/null 2>&1
            if [ -n "$val_power_5g" ]; then
                flash set WLAN1_RFPOWER_SCALE "$val_power_5g" >/dev/null 2>&1
                case "$val_power_5g" in
                    0) p5_pct=100 ;;
                    1) p5_pct=70 ;;
                    2) p5_pct=50 ;;
                    3) p5_pct=35 ;;
                    *) p5_pct=100 ;;
                esac
                flash set WLAN1_TX_POWER_PCT "$p5_pct" >/dev/null 2>&1
            fi
            [ -n "$val_encrypt_5g" ] && flash set WLAN1_ENCRYPT "$val_encrypt_5g" >/dev/null 2>&1
            [ -n "$val_isolate_5g" ] && flash set WLAN1_BLOCK_RELAY "$val_isolate_5g" >/dev/null 2>&1
            if [ -n "$val_ofdma_5g" ]; then
                flash set WLAN1_OFDMA_ENABLED_FOR_WEB "$val_ofdma_5g" >/dev/null 2>&1
                flash set WLAN1_OFDMA_ENABLED "$val_ofdma_5g" >/dev/null 2>&1
            fi
            [ -n "$val_mimo_5g" ] && flash set WLAN1_MIMO_ENABLED "$val_mimo_5g" >/dev/null 2>&1
        fi

        (sleep 1; /bin/wlan_apply restart >/dev/null 2>&1 || /sbin/wlan_apply restart >/dev/null 2>&1) &
        echo '{"status":0,"message":"Wi-Fi 射频参数与发射功率已保存，正在重新加载无线驱动..."}'
        ;;

    # Network: Query full network parameters (LAN, WAN, OP_MODE, DMZ, UPNP)
    network_get)
        # Operation mode (0=gateway, 1=bridge)
        op_mode=$(flash get OP_MODE 2>/dev/null | cut -d'=' -f2-)
        [ -z "$op_mode" ] && op_mode="0"

        # LAN Settings
        lan_ip=$(flash get LAN_IP_ADDR 2>/dev/null | cut -d'=' -f2-)
        [ -z "$lan_ip" ] && lan_ip=$(ip -4 addr show br0 2>/dev/null | grep -o 'inet [0-9.]*' | cut -d' ' -f2 || echo "192.168.10.1")
        lan_mask=$(flash get LAN_SUBNET 2>/dev/null | cut -d'=' -f2-)
        [ -z "$lan_mask" ] && lan_mask="255.255.255.0"
        
        # DHCP server status & range
        dhcp_mode=$(flash get DHCP_MODE 2>/dev/null | cut -d'=' -f2-)
        [ -z "$dhcp_mode" ] && dhcp_mode="2"
        dhcp_en="true"
        [ "$dhcp_mode" = "0" ] && dhcp_en="false"

        dhcp_start=$(flash get LAN_DHCP_POOL_START 2>/dev/null | cut -d'=' -f2-)
        [ -z "$dhcp_start" ] && dhcp_start="192.168.10.2"
        dhcp_end=$(flash get LAN_DHCP_POOL_END 2>/dev/null | cut -d'=' -f2-)
        [ -z "$dhcp_end" ] && dhcp_end="192.168.10.254"
        dhcp_lease=$(flash get LAN_DHCP_LEASE 2>/dev/null | cut -d'=' -f2-)
        [ -z "$dhcp_lease" ] && dhcp_lease="86400"

        lan_dns1=$(flash get DHCPS_DNS1 2>/dev/null | cut -d'=' -f2-)
        [ "$lan_dns1" = "0.0.0.0" ] && lan_dns1=""
        lan_dns2=$(flash get DHCPS_DNS2 2>/dev/null | cut -d'=' -f2-)
        [ "$lan_dns2" = "0.0.0.0" ] && lan_dns2=""

        # WAN Status & Configuration
        wan_proto_code=$(flash get WAN_DHCP 2>/dev/null | cut -d'=' -f2-)
        case "$wan_proto_code" in
            0) wan_proto="static" ;;
            3) wan_proto="pppoe" ;;
            *) wan_proto="dhcp" ;;
        esac

        wan_ip=$(ip -4 addr show nas0 2>/dev/null | grep -o 'inet [0-9.]*' | cut -d' ' -f2 || echo "")
        [ -z "$wan_ip" ] && wan_ip=$(ip -4 addr show ppp0 2>/dev/null | grep -o 'inet [0-9.]*' | cut -d' ' -f2 || echo "")
        
        wan_mask=$(ifconfig nas0 2>/dev/null | grep -o 'Mask:[0-9.]*' | cut -d':' -f2 || echo "255.255.255.0")
        wan_gw=$(ip route 2>/dev/null | grep default | awk '{print $3}' | head -n1 || echo "")
        wan_dns=$(grep nameserver /etc/resolv.conf 2>/dev/null | awk '{print $2}' | tr '\n' ',' | sed 's/,$//' || echo "")
        wan_mtu=$(ifconfig nas0 2>/dev/null | grep -o 'MTU:[0-9]*' | cut -d':' -f2 || echo "1500")
        wan_mac=$(ifconfig nas0 2>/dev/null | grep -o 'HWaddr [0-9A-Fa-f:]*' | cut -d' ' -f2 || echo "")
        ppp_user=$(flash get PPP_USER_NAME 2>/dev/null | cut -d'=' -f2-)

        # DMZ & UPnP
        dmz_en=$(flash get DMZ_ENABLE 2>/dev/null | cut -d'=' -f2-)
        dmz_ip=$(flash get DMZ_IP 2>/dev/null | cut -d'=' -f2-)
        [ "$dmz_ip" = "0.0.0.0" ] && dmz_ip=""
        upnp_en=$(flash get UPNP 2>/dev/null | cut -d'=' -f2-)

        cat << EOF
{
  "status": 0,
  "op_mode": $op_mode,
  "lan": {
    "ip": "$lan_ip",
    "netmask": "$lan_mask",
    "dhcp_enabled": $dhcp_en,
    "dhcp_start": "$dhcp_start",
    "dhcp_end": "$dhcp_end",
    "dhcp_lease": $dhcp_lease,
    "dns1": "$lan_dns1",
    "dns2": "$lan_dns2"
  },
  "wan": {
    "proto": "$wan_proto",
    "ip": "$wan_ip",
    "netmask": "$wan_mask",
    "gateway": "$wan_gw",
    "dns": "$wan_dns",
    "mtu": "$wan_mtu",
    "mac": "$wan_mac",
    "pppoe_user": "$ppp_user"
  },
  "nat": {
    "dmz_enabled": $([ "$dmz_en" = "1" ] && echo true || echo false),
    "dmz_ip": "$dmz_ip",
    "upnp_enabled": $([ "$upnp_en" = "1" ] && echo true || echo false)
  }
}
EOF
        ;;

    # Operation Mode Switching (Gateway vs AP Bridge)
    network_set_mode)
        target_mode=$(get_param "mode")
        if [ "$target_mode" = "1" ]; then
            # Switch to AP Bridge Mode
            flash set OP_MODE 1 >/dev/null 2>&1
            /etc/scripts/wan2lan.sh on >/dev/null 2>&1 || true
            brctl addif br0 nas0 2>/dev/null || true
            echo '{"status":0,"message":"已切换为 AP 桥接模式 (WAN 接口已桥接至内网 br0，NAT 已旁路)"}'
        else
            # Switch to Gateway / Router NAT Mode
            flash set OP_MODE 0 >/dev/null 2>&1
            /etc/scripts/wan2lan.sh off >/dev/null 2>&1 || true
            brctl delif br0 nas0 2>/dev/null || true
            echo '{"status":0,"message":"已切换为 网关路由模式 (开启 NAT 硬件加速与独立 WAN 出口)"}'
        fi
        ;;

    # LAN & DHCP Configuration
    network_set_lan)
        v_ip=$(get_param "ip")
        v_mask=$(get_param "netmask")
        v_dhcp=$(get_param "dhcp_enable")
        v_start=$(get_param "dhcp_start")
        v_end=$(get_param "dhcp_end")
        v_lease=$(get_param "dhcp_lease")
        v_dns1=$(get_param "dns1")
        v_dns2=$(get_param "dns2")

        [ -n "$v_ip" ] && flash set LAN_IP_ADDR "$v_ip" >/dev/null 2>&1
        [ -n "$v_mask" ] && flash set LAN_SUBNET "$v_mask" >/dev/null 2>&1
        
        if [ "$v_dhcp" = "1" ]; then
            flash set DHCP_MODE 2 >/dev/null 2>&1
            flash set LAN_DHCP 1 >/dev/null 2>&1
        else
            flash set DHCP_MODE 0 >/dev/null 2>&1
            flash set LAN_DHCP 0 >/dev/null 2>&1
        fi

        [ -n "$v_start" ] && flash set LAN_DHCP_POOL_START "$v_start" >/dev/null 2>&1
        [ -n "$v_end" ] && flash set LAN_DHCP_POOL_END "$v_end" >/dev/null 2>&1
        [ -n "$v_lease" ] && flash set LAN_DHCP_LEASE "$v_lease" >/dev/null 2>&1
        [ -n "$v_dns1" ] && flash set DHCPS_DNS1 "$v_dns1" >/dev/null 2>&1
        [ -n "$v_dns2" ] && flash set DHCPS_DNS2 "$v_dns2" >/dev/null 2>&1

        # Synchronize Dnsmasq Drop-in Config
        mkdir -p /var/app/conf/dnsmasq.d
        if [ "$v_dhcp" = "1" ] && [ -n "$v_start" ] && [ -n "$v_end" ]; then
            cat > /var/app/conf/dnsmasq.d/lan_dhcp.conf << EOF
dhcp-range=$v_start,$v_end,$v_mask,${v_lease:-86400}s
$([ -n "$v_dns1" ] && echo "dhcp-option=6,$v_dns1${v_dns2:+,$v_dns2}")
EOF
        else
            rm -f /var/app/conf/dnsmasq.d/lan_dhcp.conf
        fi
        killall -SIGHUP dnsmasq 2>/dev/null || true

        echo '{"status":0,"message":"局域网与 DHCP 参数已保存并应用"}'
        ;;

    # WAN Uplink Settings
    network_set_wan)
        v_proto=$(get_param "proto")
        v_mtu=$(get_param "mtu")
        v_mac=$(get_param "mac")

        if [ "$v_proto" = "pppoe" ]; then
            v_user=$(get_param "pppoe_user")
            v_pass=$(get_param "pppoe_pass")
            flash set WAN_DHCP 3 >/dev/null 2>&1
            [ -n "$v_user" ] && flash set PPP_USER_NAME "$v_user" >/dev/null 2>&1
            [ -n "$v_pass" ] && flash set PPP_PASSWORD "$v_pass" >/dev/null 2>&1
            [ -z "$v_mtu" ] && v_mtu="1492"
        elif [ "$v_proto" = "static" ]; then
            flash set WAN_DHCP 0 >/dev/null 2>&1
            v_wan_ip=$(get_param "ip")
            v_wan_mask=$(get_param "netmask")
            v_wan_gw=$(get_param "gateway")
            v_wan_dns1=$(get_param "dns1")
            v_wan_dns2=$(get_param "dns2")
            [ -n "$v_wan_ip" ] && flash set WAN_IP_ADDR "$v_wan_ip" >/dev/null 2>&1
            [ -n "$v_wan_mask" ] && flash set WAN_SUBNET_MASK "$v_wan_mask" >/dev/null 2>&1
            [ -n "$v_wan_gw" ] && flash set WAN_DEFAULT_GATEWAY "$v_wan_gw" >/dev/null 2>&1
            [ -n "$v_wan_dns1" ] && flash set DNS1 "$v_wan_dns1" >/dev/null 2>&1
            [ -n "$v_wan_dns2" ] && flash set DNS2 "$v_wan_dns2" >/dev/null 2>&1
        else
            flash set WAN_DHCP 1 >/dev/null 2>&1
        fi

        [ -n "$v_mtu" ] && ifconfig nas0 mtu "$v_mtu" 2>/dev/null || true
        [ -n "$v_mac" ] && ifconfig nas0 hw ether "$v_mac" 2>/dev/null || true

        echo '{"status":0,"message":"WAN 上行接入设置已保存并提交执行"}'
        ;;

    # Port Forwarding: Get list
    portfw_get)
        pf_conf="/var/app/conf/port_forward.json"
        if [ -f "$pf_conf" ]; then
            cat "$pf_conf"
        else
            echo '{"status":0,"rules":[]}'
        fi
        ;;

    # Port Forwarding: Save list and apply
    portfw_set)
        rules_json=$(get_param "rules")
        mkdir -p /var/app/conf
        printf '%s\n' "$rules_json" > /var/app/conf/port_forward.json

        # Parse rules and generate iptables commands
        cat > /var/app/conf/port_forward.sh << 'PFECHO'
#!/bin/sh
iptables -t nat -F PORT_FORWARD 2>/dev/null || iptables -t nat -N PORT_FORWARD
iptables -t nat -C PREROUTING -j PORT_FORWARD 2>/dev/null || iptables -t nat -I PREROUTING 1 -j PORT_FORWARD
PFECHO
        if command -v jq >/dev/null 2>&1; then
            jq -r '.rules[] | select(.enabled == true) | "iptables -t nat -A PORT_FORWARD -p \(.proto) --dport \(.ext_port) -j DNAT --to-destination \(.int_ip):\(.int_port)\niptables -A FORWARD -p \(.proto) -d \(.int_ip) --dport \(.int_port) -j ACCEPT"' /var/app/conf/port_forward.json >> /var/app/conf/port_forward.sh 2>/dev/null || true
        fi
        sh /var/app/conf/port_forward.sh 2>/dev/null || true
        echo '{"status":0,"message":"端口转发规则已保存并实时生效"}'
        ;;

    # DMZ & UPnP Settings
    dmz_set)
        v_dmz_en=$(get_param "enable")
        v_dmz_ip=$(get_param "ip")
        v_upnp=$(get_param "upnp")

        flash set DMZ_ENABLE "$v_dmz_en" >/dev/null 2>&1
        [ -n "$v_dmz_ip" ] && flash set DMZ_IP "$v_dmz_ip" >/dev/null 2>&1
        [ -n "$v_upnp" ] && flash set UPNP "$v_upnp" >/dev/null 2>&1

        iptables -t nat -D PREROUTING -i nas0 -j DNAT --to-destination "$v_dmz_ip" 2>/dev/null || true
        if [ "$v_dmz_en" = "1" ] && [ -n "$v_dmz_ip" ]; then
            iptables -t nat -A PREROUTING -i nas0 -j DNAT --to-destination "$v_dmz_ip" 2>/dev/null || true
        fi
        echo '{"status":0,"message":"DMZ 与 UPnP 配置已更新"}'
        ;;

    # Admin Password Management
    password_set)
        new_pass=$(get_param "password")
        if [ -z "$new_pass" ] || [ ${#new_pass} -lt 5 ]; then
            echo '{"status":1,"error":"密码长度不能少于 5 个字符"}'
        else
            flash set USER_PASSWORD "$new_pass" >/dev/null 2>&1
            flash set SUSER_PASSWORD "$new_pass" >/dev/null 2>&1
            echo "admin:$new_pass" | chpasswd 2>/dev/null || true
            echo "root:$new_pass" | chpasswd 2>/dev/null || true
            echo '{"status":0,"message":"管理员登录密码已成功更新"}'
        fi
        ;;

    # Connected Clients API
    client_list)
        printf '{\n  "status": 0,\n  "clients": [\n'
        c_first=1
        while read -r arp_ip arp_hw arp_flags arp_mac arp_mask arp_dev; do
            [ "$arp_dev" = "br0" ] || continue
            [ "$arp_mac" = "00:00:00:00:00:00" ] && continue
            [ $c_first -eq 0 ] && printf ',\n'
            c_first=0
            c_host=$(grep -i "$arp_mac" /var/lib/misc/dnsmasq.leases 2>/dev/null | awk '{print $4}' || echo "")
            [ -z "$c_host" ] || [ "$c_host" = "*" ] && c_host=$(grep "$arp_ip" /etc/hosts 2>/dev/null | awk '{print $2}' || echo "")
            [ -z "$c_host" ] && c_host="局域网终端"
            cat << EOF
    {
      "ip": "$arp_ip",
      "mac": "$arp_mac",
      "hostname": "$c_host",
      "interface": "LAN / Wi-Fi",
      "online": true
    }
EOF
        done < /proc/net/arp
        printf '\n  ]\n}\n'
        ;;

    # System Power & Maintenance APIs
    system_reboot)
        (sleep 1; sync; /sbin/reboot -f) &
        echo '{"status":0,"message":"系统重启指令已执行，设备正在重启..."}'
        ;;

    system_drop_caches)
        sync
        echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
        new_free=$(awk '/MemAvailable/ {print $2}' /proc/meminfo 2>/dev/null || awk '/MemFree/ {print $2}' /proc/meminfo 2>/dev/null || echo "0")
        echo "{\"status\":0,\"message\":\"内存缓存深度释放成功，当前可用: $((new_free / 1024)) MB\"}"
        ;;

    system_hwnat_toggle)
        hwnat_val=$(get_param "enable")
        if [ "$hwnat_val" = "1" ]; then
            [ -f /proc/fc/status ] && echo 1 > /proc/fc/status 2>/dev/null || true
            msg="HWNAT 硬件直通加速已启用"
        else
            [ -f /proc/fc/status ] && echo 0 > /proc/fc/status 2>/dev/null || true
            msg="HWNAT 硬件直通加速已关闭"
        fi
        echo "{\"status\":0,\"message\":\"$msg\"}"
        ;;

    system_ping)
        target=$(get_param "target")
        [ -z "$target" ] && target="223.5.5.5"
        target=$(echo "$target" | tr -cd 'a-zA-Z0-9.-')
        ping_out=$(ping -c 3 -W 2 "$target" 2>&1 | tr '\r' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\n", $0}' | tr '\n' ' ')
        echo "{\"status\":0,\"target\":\"$target\",\"output\":\"$ping_out\"}"
        ;;

    # Crontab Scheduled Tasks
    cron_get)
        cron_file="/var/app/conf/crontabs/root"
        [ -f "$cron_file" ] || cron_file="/etc/crontabs/root"
        cron_content=""
        if [ -f "$cron_file" ]; then
            cron_content=$(cat "$cron_file" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\n", $0}' | tr '\n' ' ')
        fi
        echo "{\"status\":0,\"crontab\":\"$cron_content\"}"
        ;;

    cron_set)
        val_cron=$(get_param "crontab")
        cron_file="/var/app/conf/crontabs/root"
        mkdir -p "${cron_file%/*}"
        printf '%s\n' "$val_cron" > "$cron_file"
        killall -HUP crond 2>/dev/null || true
        echo '{"status":0,"message":"计划任务已保存并生效"}'
        ;;

    system_logs)
        log_content=$(logread 2>/dev/null | tail -n 80 || dmesg 2>/dev/null | tail -n 80 || echo "暂无系统运行日志")
        esc_log=$(printf '%s\n' "$log_content" | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\n", $0}' | tr '\n' ' ')
        echo "{\"status\":0,\"log\":\"$esc_log\"}"
        ;;

    *)
        echo "{\"status\":1,\"error\":\"Unknown action: '$action'\"}"
        ;;
esac
exit 0
