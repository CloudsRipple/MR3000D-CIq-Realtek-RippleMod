#!/bin/sh
# ==============================================================================
# Ripple-mod - System Environment & Core Runtime Utilities
# ==============================================================================

# 1. Standard Environment Variables
export PATH="/var/app/bin:/var/app/opt/bin:/var/app/opt/sbin:/opt/bin:/opt/sbin:/bin:/sbin:/usr/bin:/usr/sbin:$PATH"
export LD_LIBRARY_PATH="/var/app/lib:/var/app/opt/lib:/opt/lib:/lib:/usr/lib:$LD_LIBRARY_PATH"
export LC_ALL="C.UTF-8"
export LANG="C.UTF-8"

# 2. System Paths
APP_ROOT="/var/app"
CONF_ROOT="$APP_ROOT/conf"
PLUGIN_ROOT="$APP_ROOT/plugins"
STATE_ROOT="/tmp/ripple_mod"
LOCK_ROOT="/tmp/ripple_mod/locks"
LOG_DIR="$STATE_ROOT/logs"

# Ensure runtime directories exist on tmpfs
mkdir -p "$STATE_ROOT" "$LOCK_ROOT" "$LOG_DIR" "$CONF_ROOT" 2>/dev/null || true

# 3. Logging Functions
log_format() {
    level="$1"
    module="${2:-SYSTEM}"
    shift 2
    msg="$*"
    now=$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || uptime | awk '{print $1}')
    echo "[$now] [$level] [$module] $msg"
}

log_info()  { log_format "INFO"  "${1:-SYS}" "${2:-}" ; }
log_warn()  { log_format "WARN"  "${1:-SYS}" "${2:-}" >&2 ; }
log_err()   { log_format "ERROR" "${1:-SYS}" "${2:-}" >&2 ; }
log_debug() { [ "${DEBUG:-0}" = "1" ] && log_format "DEBUG" "${1:-SYS}" "${2:-}" ; }

# 4. Atomic File Operations
atomic_write() {
    target_file="$1"
    content="$2"
    target_dir="$(dirname "$target_file")"
    mkdir -p "$target_dir" 2>/dev/null || true
    tmp_file="${target_file}.tmp.$$"
    printf "%s\n" "$content" > "$tmp_file" && mv -f "$tmp_file" "$target_file"
}

# 5. Process Lifecycle Helpers
is_pid_running() {
    pid="$1"
    expected_name="${2:-}"
    [ -z "$pid" ] && return 1
    
    # Check if process exists in /proc or via kill -0
    if [ -d "/proc/$pid" ]; then
        if [ -n "$expected_name" ] && [ -f "/proc/$pid/cmdline" ]; then
            if grep -q "$expected_name" "/proc/$pid/cmdline" 2>/dev/null; then
                return 0
            fi
            return 1
        fi
        return 0
    fi
    kill -0 "$pid" 2>/dev/null
}

# 6. Robust Mutual Exclusion Lock (flock + PID fallback)
_SYS_HELD_LOCKS=""

sys_acquire_lock() {
    lock_name="$1"
    timeout_sec="${2:-5}"
    lock_file="$LOCK_ROOT/${lock_name}.lock"
    
    # Check if already held in current process
    case " $_SYS_HELD_LOCKS " in
        *" $lock_file "*) return 0 ;;
    esac

    waited=0
    while [ $waited -lt $timeout_sec ]; do
        if mkdir "${lock_file}.dir" 2>/dev/null; then
            echo "$$" > "$lock_file"
            _SYS_HELD_LOCKS="$_SYS_HELD_LOCKS $lock_file"
            return 0
        fi

        # Check existing holder staleness
        if [ -f "$lock_file" ]; then
            holder_pid=$(cat "$lock_file" 2>/dev/null || echo "")
            if [ -n "$holder_pid" ] && ! is_pid_running "$holder_pid"; then
                rm -rf "${lock_file}.dir" "$lock_file" 2>/dev/null || true
                continue
            fi
        fi

        sleep 1
        waited=$((waited + 1))
    done

    log_warn "LOCK" "Failed to acquire lock $lock_name within ${timeout_sec}s"
    return 1
}

sys_release_lock() {
    lock_name="$1"
    lock_file="$LOCK_ROOT/${lock_name}.lock"
    rm -rf "${lock_file}.dir" "$lock_file" 2>/dev/null || true
    
    # Remove from held locks list
    new_held=""
    for lk in $_SYS_HELD_LOCKS; do
        [ "$lk" != "$lock_file" ] && new_held="$new_held $lk"
    done
    _SYS_HELD_LOCKS="$new_held"
}

# Automatic lock release on script exit/signal
sys_lock_cleanup_trap() {
    for lk in $_SYS_HELD_LOCKS; do
        rm -rf "${lk}.dir" "$lk" 2>/dev/null || true
    done
}
trap 'sys_lock_cleanup_trap' EXIT INT TERM HUP
