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
        wifi2_ssid=$(iwpriv wlan0 get_mib ssid 2>/dev/null | cut -d':' -f2 | tr -d '\r\n' || echo "CMCC-2C3G")
        wifi2_ch=$(iwpriv wlan0 get_mib channel 2>/dev/null | cut -d':' -f2 | tr -d '\r\n' || echo "6")
        wifi5_ssid=$(iwpriv wlan1 get_mib ssid 2>/dev/null | cut -d':' -f2 | tr -d '\r\n' || echo "CMCC-2C3G-5G")
        wifi5_ch=$(iwpriv wlan1 get_mib channel 2>/dev/null | cut -d':' -f2 | tr -d '\r\n' || echo "36")

        # Clean single-line kernel string
        kernel_str=$(head -n 1 /proc/version 2>/dev/null | cut -d' ' -f1-3 | tr -d '\r\n')
        [ -z "$kernel_str" ] && kernel_str="Linux 5.10.70"

        cat << EOF
{
  "status": 0,
  "system": {
    "hostname": "MR3000D-CIq",
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
        "active": true
      },
      "wifi_5g": {
        "ssid": "$wifi5_ssid",
        "channel": "$wifi5_ch",
        "bandwidth": "160 MHz",
        "standard": "Wi-Fi 6 AX (2402 Mbps)",
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

    # Generic Dynamic Plugin RPC Bridge
    plugin_call)
        if [ -x "$DISPATCHER" ]; then
            "$DISPATCHER" call "$plugin" "$cmd" "$args"
        else
            echo '{"status":1,"error":"API dispatcher not installed"}'
        fi
        ;;

    *)
        echo "{\"status\":1,\"error\":\"Unknown action: '$action'\"}"
        ;;
esac
exit 0
