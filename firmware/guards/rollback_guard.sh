#!/bin/sh
trap '' HUP
# ==============================================================================
# CMCC MR3000D-CIq A/B Dual-Slot & Rollback Guard Engine
# Location: /var/app/scripts/rollback_guard.sh
# ==============================================================================

ACTION="${1:-status}"
CONF_DIR="/var/app/conf"
GUARD_FILE="$CONF_DIR/.rollback_guard"
UNCONFIRMED_FLAG="/var/app/.unconfirmed"
CONFIRMED_FLAG="/tmp/mod_confirmed"
PID_FILE="/tmp/rollback_guard.pid"

mkdir -p "$CONF_DIR"

# Resolve nv binary path (Fix 3)
NV_BIN=$(which nv 2>/dev/null || echo /bin/nv)

get_active_slot() {
    if [ -x "$NV_BIN" ]; then
        "$NV_BIN" getenv sw_active 2>/dev/null | sed 's/^.*=//g' | tr -d ' \r\n'
    else
        echo "1"
    fi
}

get_commit_slot() {
    if [ -x "$NV_BIN" ]; then
        "$NV_BIN" getenv sw_commit 2>/dev/null | sed 's/^.*=//g' | tr -d ' \r\n'
    else
        echo "0"
    fi
}

do_status() {
    ACTIVE=$(get_active_slot)
    COMMIT=$(get_commit_slot)
    [ -z "$ACTIVE" ] && ACTIVE="1"
    [ -z "$COMMIT" ] && COMMIT="0"

    REMAINING=0
    TRIAL_ACTIVE="NO"

    if [ -f "$UNCONFIRMED_FLAG" ]; then
        TRIAL_ACTIVE="YES"
        if [ -f "$GUARD_FILE" ]; then
            EXPIRY=$(cat "$GUARD_FILE" 2>/dev/null || echo "0")
            NOW=$(date +%s 2>/dev/null || echo "0")
            if [ "$NOW" -gt 0 ] && [ "$EXPIRY" -gt "$NOW" ]; then
                REMAINING=$((EXPIRY - NOW))
            else
                REMAINING=60
            fi
        else
            TIMEOUT=$(cat "$UNCONFIRMED_FLAG" 2>/dev/null | tr -d ' \r\n')
            case "$TIMEOUT" in
                ''|*[!0-9]*) TIMEOUT=90 ;;
            esac
            REMAINING="$TIMEOUT"
        fi
    elif [ "$ACTIVE" = "1" ] && [ "$COMMIT" != "1" ]; then
        # Mode B Slot 1 uncommitted
        TRIAL_ACTIVE="YES"
        if [ -f "$GUARD_FILE" ]; then
            EXPIRY=$(cat "$GUARD_FILE" 2>/dev/null || echo "0")
            NOW=$(date +%s 2>/dev/null || echo "0")
            if [ "$NOW" -gt 0 ] && [ "$EXPIRY" -gt "$NOW" ]; then
                REMAINING=$((EXPIRY - NOW))
            else
                REMAINING=60
            fi
        else
            REMAINING=90
        fi
    fi

    echo "ACTIVE_SLOT: $ACTIVE"
    echo "COMMITTED_SLOT: $COMMIT"
    echo "UNCONFIRMED_FLAG: $([ -f "$UNCONFIRMED_FLAG" ] && echo "YES" || echo "NO")"
    echo "TRIAL_ACTIVE: $TRIAL_ACTIVE"
    echo "ROLLBACK_COUNTDOWN_SEC: $REMAINING"
}

do_arm() {
    TIMEOUT="${1:-90}"
    # Clamp between 60 and 120 seconds
    if [ -z "$TIMEOUT" ] || ! [ "$TIMEOUT" -ge 0 ] 2>/dev/null; then
        TIMEOUT=90
    fi
    if [ "$TIMEOUT" -lt 60 ]; then
        TIMEOUT=60
    elif [ "$TIMEOUT" -gt 120 ]; then
        TIMEOUT=120
    fi

    echo "[*] Arming persistent trial mode with ${TIMEOUT}s timeout..."
    echo "$TIMEOUT" > "$UNCONFIRMED_FLAG"
    NOW=$(date +%s 2>/dev/null || echo "0")
    EXPIRY=$((NOW + TIMEOUT))
    echo "$EXPIRY" > "$GUARD_FILE"
    echo "$EXPIRY" > /tmp/.rollback_guard
    sync
    echo "[OK] Persistent arming flag created: $UNCONFIRMED_FLAG (${TIMEOUT}s countdown)"
}

do_commit() {
    ACTIVE=$(get_active_slot)
    [ -z "$ACTIVE" ] && ACTIVE="1"

    echo "[*] Confirming and committing router mod permanently..."

    # Fix 1: Remove persistent unconfirmed flag and touch runtime confirmed flag
    rm -f "$UNCONFIRMED_FLAG" "$GUARD_FILE" /tmp/.rollback_guard
    touch "$CONFIRMED_FLAG"
    touch "$CONF_DIR/.slot_committed"

    # Fix 2 & Fix 3: Slot 1 commit and sw_updater unset syntax (without "")
    if [ -x "$NV_BIN" ]; then
        COMMIT=$(get_commit_slot)
        if [ "$ACTIVE" = "1" ] && [ "$COMMIT" != "1" ]; then
            echo "[*] Committing Slot 1 to U-Boot environment..."
            "$NV_BIN" setenv sw_commit "$ACTIVE"
            # Fix 3: pass only key name to unset sw_updater
            "$NV_BIN" setenv sw_updater
        fi
    fi

    # Kill background countdown if running
    if [ -f "$PID_FILE" ]; then
        KILL_PID=$(cat "$PID_FILE" 2>/dev/null)
        [ -n "$KILL_PID" ] && kill -9 "$KILL_PID" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi

    sync
    echo "[OK] Modifications permanently confirmed. Rollback guard disarmed."
    echo "[OK] Normal power-cycles will NOT trigger rollback."
}

do_rollback() {
    echo "[!] Triggering immediate rollback..."

    ACTIVE=$(get_active_slot)
    COMMIT=$(get_commit_slot)

    # 1. Stop background timer
    if [ -f "$PID_FILE" ]; then
        KILL_PID=$(cat "$PID_FILE" 2>/dev/null)
        [ -n "$KILL_PID" ] && kill -9 "$KILL_PID" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi

    # 2. Mode B Slot 1 rollback if active
    if [ "$ACTIVE" = "1" ] && [ "$COMMIT" != "1" ] && [ -x "$NV_BIN" ]; then
        echo "[!] Reverting U-Boot boot target to Slot 0 (Stock Recovery)..."
        "$NV_BIN" setenv sw_commit 0
        "$NV_BIN" setenv sw_tryactive 0
        # Fix 3: pass only key name to unset sw_updater
        "$NV_BIN" setenv sw_updater
    fi

    # 3. Mode A user.sh neutralization & instant non-disruptive overlay unmount
    if [ -f /var/app/user.sh ]; then
        echo "[!] Disabling /var/app/user.sh hook..."
        mv /var/app/user.sh /var/app/user.sh.disabled 2>/dev/null || true
    fi
    umount /home/httpd/web 2>/dev/null || true
    killall ripple_api_daemon 2>/dev/null || true
    [ -w /proc/fc/ctrl/hwnat ] && echo 1 > /proc/fc/ctrl/hwnat 2>/dev/null || true

    # Restore carrier binaries if anti_ota was enabled
    chmod 755 /bin/aosnet/* /bin/do_force_upgrade /bin/lanNetInfo /bin/ahsapd 2>/dev/null || true

    rm -f "$UNCONFIRMED_FLAG" "$GUARD_FILE" /tmp/.rollback_guard
    sync
    if [ "$ACTIVE" = "1" ]; then
        echo "[OK] Rollback complete. Rebooting into Slot 0 in 2 seconds..."
        sleep 2
        reboot 2>/dev/null || true
    else
        echo "[OK] Mode A rollback complete. Stock Web UI and system state restored without reboot."
    fi
}

do_start_guard() {
    ACTIVE=$(get_active_slot)
    COMMIT=$(get_commit_slot)

    # Fix 2: Re-entrancy check for Slot 1
    if [ "$ACTIVE" = "1" ] && [ "$COMMIT" = "1" ] && [ ! -f "$UNCONFIRMED_FLAG" ]; then
        echo "[*] Slot 1 is already committed and no unconfirmed flag exists. Guard bypassed."
        exit 0
    fi

    # Fix 1: Only run countdown if persistent unconfirmed flag exists OR Slot 1 is uncommitted
    if [ ! -f "$UNCONFIRMED_FLAG" ] && [ "$COMMIT" = "1" ]; then
        echo "[*] Mod is confirmed. Normal startup without rollback countdown."
        exit 0
    fi

    # Read timeout
    TIMEOUT=90
    if [ -f "$UNCONFIRMED_FLAG" ]; then
        VAL=$(cat "$UNCONFIRMED_FLAG" 2>/dev/null | tr -d ' \r\n')
        case "$VAL" in
            *[0-9]*) [ "$VAL" -ge 60 ] 2>/dev/null && [ "$VAL" -le 120 ] 2>/dev/null && TIMEOUT="$VAL" ;;
        esac
    fi

    echo "[!] Unconfirmed trial mode active! Arming ${TIMEOUT}s automatic rollback guard..."
    NOW=$(date +%s 2>/dev/null || echo "0")
    EXPIRY=$((NOW + TIMEOUT))
    echo "$EXPIRY" > "$GUARD_FILE"
    echo "$EXPIRY" > /tmp/.rollback_guard

    # Spawn background countdown loop
    (
        REMAIN="$TIMEOUT"
        while [ "$REMAIN" -gt 0 ]; do
            # Check if confirmed (flag removed or mod_confirmed touched)
            if [ ! -f "$UNCONFIRMED_FLAG" ]; then
                # If slot 1, also verify sw_commit
                if [ "$ACTIVE" = "1" ]; then
                    CURR_C=$(get_commit_slot)
                    if [ "$CURR_C" = "1" ] || [ -f "$CONFIRMED_FLAG" ]; then
                        echo "[OK] User confirmation detected. Rollback guard disarmed."
                        rm -f "$GUARD_FILE" /tmp/.rollback_guard "$PID_FILE"
                        exit 0
                    fi
                else
                    echo "[OK] User confirmation detected. Rollback guard disarmed."
                    rm -f "$GUARD_FILE" /tmp/.rollback_guard "$PID_FILE"
                    exit 0
                fi
            fi

            sleep 1
            REMAIN=$((REMAIN - 1))
        done

        # Countdown expired! Check one last time
        if [ -f "$UNCONFIRMED_FLAG" ] || ([ "$ACTIVE" = "1" ] && [ "$(get_commit_slot)" != "1" ]); then
            echo "[!] ${TIMEOUT}-second trial guard expired without user confirmation!"
            echo "[!] Automatically executing rollback for router safety..."
            do_rollback
        else
            echo "[OK] Trial confirmed before expiration. Rollback disarmed."
            rm -f "$GUARD_FILE" /tmp/.rollback_guard "$PID_FILE"
        fi
    ) >/dev/null 2>&1 &
    echo $! > "$PID_FILE"
}

case "$ACTION" in
    --arm|arm)
        do_arm "$2"
        ;;
    commit|confirm)
        do_commit
        ;;
    rollback)
        do_rollback
        ;;
    guard|start)
        do_start_guard
        ;;
    status|*)
        do_status
        ;;
esac
