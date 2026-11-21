#!/bin/sh
# ==============================================================================
# Ripple-mod - Universal Plugin Engine & Lifecycle Manager
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd)"
APP_ROOT="${APP_ROOT:-/var/app}"
PLUGIN_DIR="${PLUGIN_DIR:-$APP_ROOT/plugins}"
STATE_DIR="${STATE_DIR:-/tmp/ripple_mod/plugins}"
LIB_DIR="${LIB_DIR:-$APP_ROOT/core_system/lib}"

# Intelligent directory fallback
if [ ! -d "$PLUGIN_DIR" ] && [ -d "$SCRIPT_DIR/../plugins" ]; then
    PLUGIN_DIR="$SCRIPT_DIR/../plugins"
fi
if [ ! -d "$LIB_DIR" ] && [ -d "$SCRIPT_DIR/../core_system/lib" ]; then
    LIB_DIR="$SCRIPT_DIR/../core_system/lib"
fi

[ -f "$LIB_DIR/sys_env.sh" ] && . "$LIB_DIR/sys_env.sh"
[ -f "$LIB_DIR/sh_json.sh" ] && . "$LIB_DIR/sh_json.sh"

mkdir -p "$PLUGIN_DIR" "$STATE_DIR"

usage() {
    cat << EOF
Usage: $0 <command> [arguments...]

Commands:
  list                      List all installed plugins and their run states
  install <package.tar.gz>  Install a plugin package (.tar.gz)
  start <plugin_id>         Start a plugin
  stop <plugin_id>          Stop a plugin
  restart <plugin_id>       Restart a plugin
  status <plugin_id>        Query status of a plugin
  enable <plugin_id>        Enable plugin autostart
  disable <plugin_id>       Disable plugin autostart
  uninstall <plugin_id>     Uninstall a plugin
  autostart                 Launch all enabled plugins (system boot hook)
  hotplug <action> <iface>  Broadcast network hotplug event to plugins
EOF
    exit 1
}

# Validate Plugin Identifier (alphanumeric, underscores, hyphens only)
validate_id() {
    clean=$(printf '%s' "$1" | tr -cd 'a-zA-Z0-9_-')
    if [ -z "$clean" ] || [ "$clean" != "$1" ]; then
        echo "{\"status\":1,\"error\":\"Invalid plugin identifier '$1'\"}"
        exit 1
    fi
}

is_plugin_enabled() {
    _pdir="$1"
    [ -f "$_pdir/.disabled" ] && return 1
    [ -f "$_pdir/.enabled" ] && return 0
    grep -qi '"autostart"[ \t]*:[ \t]*true' "$_pdir/manifest.json" 2>/dev/null && return 0
    return 1
}

cmd_list() {
    printf '{\n  "status": 0,\n  "plugins": [\n'
    first=1
    for pdir in "$PLUGIN_DIR"/*; do
        if [ -d "$pdir" ] && [ -f "$pdir/manifest.json" ]; then
            pid=$(basename "$pdir")
            [ $first -eq 0 ] && printf ',\n'
            first=0

            # Determine running status strictly from JSON running field (fallback to RUNNING token)
            is_running="false"
            if [ -f "$pdir/status.sh" ]; then
                stat_out=$(sh "$pdir/status.sh" 2>/dev/null || echo "")
                if echo "$stat_out" | grep -qi '"running"[[:space:]]*:[[:space:]]*true'; then
                    is_running="true"
                elif ! echo "$stat_out" | grep -qi '"running"[[:space:]]*:' && \
                     echo "$stat_out" | grep -q 'RUNNING'; then
                    is_running="true"
                fi
            fi

            # Determine enabled status (.disabled explicitly overrides manifest autostart)
            is_enabled="false"
            if is_plugin_enabled "$pdir"; then
                is_enabled="true"
            fi

            # Detect built-in or packaged plugin GUI
            has_gui="false"
            case "$pid" in
                hosts_adblock_dns|custom_userscript|entware_package_mgr)
                    has_gui="true"
                    ;;
                *)
                    [ -f "$pdir/web/ui.html" ] || [ -f "$APP_ROOT/web/plugins/$pid/ui.html" ] && has_gui="true"
                    ;;
            esac

            # Merge running and enabled into manifest (properly JSON-escaped)
            p_name=$(json_escape "$(json_get "$pdir/manifest.json" "name")")
            p_ver=$(json_escape "$(json_get "$pdir/manifest.json" "version")")
            p_desc=$(json_escape "$(json_get "$pdir/manifest.json" "description")")
            p_icon=$(json_escape "$(json_get "$pdir/manifest.json" "icon")")

            cat << EOF
    {
      "id": "$pid",
      "name": "$p_name",
      "version": "$p_ver",
      "description": "$p_desc",
      "icon": "$p_icon",
      "running": $is_running,
      "enabled": $is_enabled,
      "has_gui": $has_gui
    }
EOF
        fi
    done
    printf '\n  ]\n}\n'
}

cmd_install() {
    pkg="$1"
    if [ -z "$pkg" ] || [ ! -f "$pkg" ]; then
        json_error 1 "Package file not found or inaccessible"
        exit 1
    fi

    tmp_ext="/tmp/plugin_extract_$$"
    mkdir -p "$tmp_ext"
    
    # Safe extraction
    if ! tar -zxf "$pkg" -C "$tmp_ext" 2>/dev/null; then
        rm -rf "$tmp_ext"
        json_error 1 "Failed to decompress archive. Ensure it is a valid gzip tarball."
        exit 1
    fi

    # Locate manifest.json (in root or single subfolder)
    manifest_path="$tmp_ext/manifest.json"
    content_dir="$tmp_ext"
    if [ ! -f "$manifest_path" ]; then
        subfolder=$(find "$tmp_ext" -mindepth 1 -maxdepth 1 -type d | head -n 1)
        if [ -n "$subfolder" ] && [ -f "$subfolder/manifest.json" ]; then
            manifest_path="$subfolder/manifest.json"
            content_dir="$subfolder"
        else
            rm -rf "$tmp_ext"
            json_error 1 "Invalid plugin package: manifest.json is missing"
            exit 1
        fi
    fi

    pid=$(json_get "$manifest_path" "id")
    validate_id "$pid"

    target_dir="$PLUGIN_DIR/$pid"
    
    # Preserve user-edited configs/scripts across upgrade installations
    preserve_dir="/tmp/plugin_preserve_$$"
    if [ -d "$target_dir" ]; then
        [ -x "$target_dir/stop.sh" ] && "$target_dir/stop.sh" >/dev/null 2>&1 || true
        mkdir -p "$preserve_dir"
        for pf in config.conf user_run.sh .disabled; do
            [ -f "$target_dir/$pf" ] && cp -f "$target_dir/$pf" "$preserve_dir/$pf" 2>/dev/null || true
        done
        rm -rf "$target_dir"
    fi

    mkdir -p "$target_dir"
    cp -a "$content_dir"/* "$target_dir/"
    rm -rf "$tmp_ext"
    if [ -d "$preserve_dir" ]; then
        for pf in config.conf user_run.sh; do
            [ -f "$preserve_dir/$pf" ] && cp -f "$preserve_dir/$pf" "$target_dir/$pf" 2>/dev/null || true
        done
        rm -rf "$preserve_dir"
    fi
    chmod +x "$target_dir"/*.sh "$target_dir"/scripts/*.sh 2>/dev/null || true

    # Publish packaged plugin Web UI if provided
    if [ -d "$target_dir/web" ]; then
        mkdir -p "$APP_ROOT/web/plugins/$pid" 2>/dev/null || true
        cp -rf "$target_dir/web/"* "$APP_ROOT/web/plugins/$pid/" 2>/dev/null || true
        if [ -d /tmp/web_merged ]; then
            mkdir -p "/tmp/web_merged/plugins/$pid" 2>/dev/null || true
            cp -rf "$target_dir/web/"* "/tmp/web_merged/plugins/$pid/" 2>/dev/null || true
        fi
    fi

    # Run installation hook
    if [ -x "$target_dir/install.sh" ]; then
        "$target_dir/install.sh" >/dev/null 2>&1 || true
    fi

    # Mark enabled by default (clear any stale .disabled marker)
    rm -f "$target_dir/.disabled"
    touch "$target_dir/.enabled"

    json_response 0 "Plugin '$pid' installed successfully" "{\"plugin_id\":\"$pid\"}"
}

cmd_start() {
    validate_id "$1"
    target="$PLUGIN_DIR/$1"
    [ ! -d "$target" ] && { json_error 1 "Plugin '$1' is not installed"; exit 1; }
    
    if [ -f "$target/start.sh" ]; then
        out=$(sh "$target/start.sh" 2>&1)
        ec=$?
        json_response "$ec" "Plugin '$1' started" "{\"output\":\"$(json_escape "$out")\"}"
    else
        json_error 1 "No start.sh script in plugin '$1'"
    fi
}

cmd_stop() {
    validate_id "$1"
    target="$PLUGIN_DIR/$1"
    [ ! -d "$target" ] && { json_error 1 "Plugin '$1' is not installed"; exit 1; }
    
    if [ -f "$target/stop.sh" ]; then
        out=$(sh "$target/stop.sh" 2>&1)
        ec=$?
        json_response "$ec" "Plugin '$1' stopped" "{\"output\":\"$(json_escape "$out")\"}"
    else
        json_error 1 "No stop.sh script in plugin '$1'"
    fi
}

cmd_restart() {
    validate_id "$1"
    target="$PLUGIN_DIR/$1"
    [ ! -d "$target" ] && { json_error 1 "Plugin '$1' is not installed"; exit 1; }
    
    if [ -f "$target/stop.sh" ]; then
        sh "$target/stop.sh" >/dev/null 2>&1 || true
    fi
    sleep 1
    if [ -f "$target/start.sh" ]; then
        out=$(sh "$target/start.sh" 2>&1)
        ec=$?
        json_response "$ec" "Plugin '$1' restarted" "{\"output\":\"$(json_escape "$out")\"}"
    else
        json_error 1 "No start.sh script in plugin '$1'"
    fi
}

cmd_status() {
    validate_id "$1"
    target="$PLUGIN_DIR/$1"
    [ ! -d "$target" ] && { json_error 1 "Plugin '$1' is not installed"; exit 1; }
    
    if [ -f "$target/status.sh" ]; then
        sh "$target/status.sh"
    else
        json_response 0 "Plugin '$1' installed" "{\"running\":false}"
    fi
}

cmd_enable() {
    validate_id "$1"
    target="$PLUGIN_DIR/$1"
    [ ! -d "$target" ] && { json_error 1 "Plugin '$1' is not installed"; exit 1; }
    rm -f "$target/.disabled"
    touch "$target/.enabled"
    json_response 0 "Plugin '$1' enabled for autostart"
}

cmd_disable() {
    validate_id "$1"
    target="$PLUGIN_DIR/$1"
    [ ! -d "$target" ] && { json_error 1 "Plugin '$1' is not installed"; exit 1; }
    rm -f "$target/.enabled"
    touch "$target/.disabled"
    json_response 0 "Plugin '$1' disabled from autostart"
}

cmd_uninstall() {
    validate_id "$1"
    target="$PLUGIN_DIR/$1"
    [ ! -d "$target" ] && { json_error 1 "Plugin '$1' is not installed"; exit 1; }
    
    [ -f "$target/stop.sh" ] && sh "$target/stop.sh" >/dev/null 2>&1 || true
    [ -f "$target/uninstall.sh" ] && sh "$target/uninstall.sh" >/dev/null 2>&1 || true
    rm -rf "$target"
    json_response 0 "Plugin '$1' uninstalled successfully"
}

cmd_autostart() {
    for pdir in "$PLUGIN_DIR"/*; do
        if [ -d "$pdir" ] && [ -f "$pdir/start.sh" ]; then
            if is_plugin_enabled "$pdir"; then
                pid=$(basename "$pdir")
                echo "[Autostart] Starting plugin '$pid'..."
                sh "$pdir/start.sh" >/dev/null 2>&1 &
            fi
        fi
    done
}

cmd_hotplug() {
    action="$1"
    iface="$2"
    for pdir in "$PLUGIN_DIR"/*; do
        if [ -d "$pdir" ]; then
            if [ -x "$pdir/hotplug.sh" ]; then
                "$pdir/hotplug.sh" "$action" "$iface" >/dev/null 2>&1 &
            fi
        fi
    done
}

case "$1" in
    list) cmd_list ;;
    install) cmd_install "$2" ;;
    start) cmd_start "$2" ;;
    stop) cmd_stop "$2" ;;
    restart) cmd_restart "$2" ;;
    status) cmd_status "$2" ;;
    enable) cmd_enable "$2" ;;
    disable) cmd_disable "$2" ;;
    uninstall) cmd_uninstall "$2" ;;
    autostart) cmd_autostart ;;
    hotplug) cmd_hotplug "$2" "$3" ;;
    *) usage ;;
esac
