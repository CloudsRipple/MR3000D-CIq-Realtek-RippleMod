#!/bin/sh
# Entware & Python API Handler
export PATH="/var/app/bin:/var/app/opt/bin:/var/app/opt/sbin:/opt/bin:/opt/sbin:$PATH"

cmd="$1"
shift
args="$@"

case "$cmd" in
    status)
        installed="false"
        has_python="false"
        py_ver=""
        [ -x /opt/bin/opkg ] && installed="true"
        if [ -x /opt/bin/python3 ] || command -v python3 >/dev/null 2>&1; then
            has_python="true"
            py_ver=$(python3 --version 2>&1 | cut -d' ' -f2)
        fi
        cat << EOF
{
  "status": 0,
  "entware_installed": $installed,
  "python_installed": $has_python,
  "python_version": "$py_ver"
}
EOF
        ;;

    bootstrap_entware)
        if [ -f /var/app/core_system/runtime/bootstrap_entware.sh ]; then
            out=$(sh /var/app/core_system/runtime/bootstrap_entware.sh 2>&1 || true)
            clean_out=$(printf '%s' "$out" | tr -d '\r' | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\n", $0}' | tr '\n' ' ')
            echo "{\"status\":0,\"message\":\"Entware 部署操作已完成\",\"log\":\"$clean_out\"}"
        else
            echo "{\"status\":1,\"error\":\"bootstrap_entware.sh script not found\"}"
        fi
        ;;

    install_python)
        if [ -f /var/app/core_system/runtime/install_python.sh ]; then
            out=$(sh /var/app/core_system/runtime/install_python.sh 2>&1 || true)
            clean_out=$(printf '%s' "$out" | tr -d '\r' | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\n", $0}' | tr '\n' ' ')
            echo "{\"status\":0,\"message\":\"Python 3 安装操作已执行\",\"log\":\"$clean_out\"}"
        else
            echo "{\"status\":1,\"error\":\"install_python.sh script not found\"}"
        fi
        ;;

    opkg_install)
        pkg=$(echo "$args" | tr -cd 'a-zA-Z0-9_-')
        if [ -z "$pkg" ]; then
            echo "{\"status\":1,\"error\":\"Package name required\"}"
            exit 1
        fi
        if [ ! -x /opt/bin/opkg ] && [ ! -x /var/app/opt/bin/opkg ]; then
            echo "{\"status\":1,\"error\":\"Entware opkg not installed\"}"
            exit 1
        fi
        OPKG_BIN="/opt/bin/opkg"
        [ -x /var/app/opt/bin/opkg ] && OPKG_BIN="/var/app/opt/bin/opkg"
        out=$("$OPKG_BIN" install "$pkg" 2>&1 || true)
        clean_out=$(printf '%s' "$out" | tr -d '\r' | sed 's/\\/\\\\/g; s/"/\\"/g' | awk '{printf "%s\\n", $0}' | tr '\n' ' ')
        echo "{\"status\":0,\"package\":\"$pkg\",\"output\":\"$clean_out\"}"
        ;;

    list_installed)
        if [ -x /opt/bin/opkg ]; then
            pkgs=$(/opt/bin/opkg list-installed | awk '{printf "\"%s\": \"%s\",", $1, $3}' | sed 's/,$//')
            echo "{\"status\":0,\"packages\":{$pkgs}}"
        else
            echo "{\"status\":0,\"packages\":{}}"
        fi
        ;;

    *)
        echo "{\"status\":1,\"error\":\"Unknown entware_package_mgr command '$cmd'\"}"
        ;;
esac
