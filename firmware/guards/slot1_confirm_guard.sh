#!/bin/sh
trap '' HUP
# ==============================================================================
# CMCC MR3000D-CIq Mode B Slot 1 Guard Engine
# Location: /var/app/scripts/slot1_confirm_guard.sh
# ==============================================================================

NV_BIN=$(which nv 2>/dev/null || echo /bin/nv)

# Fix 2: Mode B Slot 1 Guard Re-Entrancy Check
# BEFORE starting 60-120s countdown, ALWAYS check if Slot 1 is already committed:
CURRENT_COMMIT=$($NV_BIN getenv sw_commit 2>/dev/null | sed 's/^.*=//g' | tr -d ' \r\n')
if [ "$CURRENT_COMMIT" = "1" ]; then
    echo "[*] Slot 1 is already committed (sw_commit=1). Guard re-entrancy bypassed."
    exit 0
fi

ACTION="${1:-guard}"
CONF_DIR="/var/app/conf"
GUARD_FILE="$CONF_DIR/.rollback_guard"
UNCONFIRMED_FLAG="/var/app/.unconfirmed"
CONFIRMED_FLAG="/tmp/mod_confirmed"
PID_FILE="/tmp/slot1_guard.pid"

mkdir -p "$CONF_DIR"

do_confirm() {
    echo "[*] Confirming Slot 1 trial boot permanently..."
    $NV_BIN setenv sw_commit 1
    # Fix 3: Unset sw_updater by passing only the key name (no second argument "")
    $NV_BIN setenv sw_updater
    rm -f "$UNCONFIRMED_FLAG" "$GUARD_FILE" /tmp/.rollback_guard
    touch "$CONFIRMED_FLAG"
    sync
    echo "[OK] Slot 1 permanently committed. Rollback disarmed."
}

do_rollback() {
    echo "[!] Rolling back from Slot 1 to Slot 0 (Stock Recovery)..."
    $NV_BIN setenv sw_commit 0
    $NV_BIN setenv sw_tryactive 0
    # Fix 3: Unset sw_updater by passing only the key name (no second argument "")
    $NV_BIN setenv sw_updater
    rm -f "$UNCONFIRMED_FLAG" "$GUARD_FILE" /tmp/.rollback_guard
    sync
    sleep 2
    reboot 2>/dev/null || true
}

do_guard() {
    TIMEOUT="${2:-90}"
    if [ -f "$UNCONFIRMED_FLAG" ]; then
        VAL=$(cat "$UNCONFIRMED_FLAG" 2>/dev/null | tr -d ' \r\n')
        case "$VAL" in
            *[0-9]*) [ "$VAL" -ge 60 ] 2>/dev/null && [ "$VAL" -le 120 ] 2>/dev/null && TIMEOUT="$VAL" ;;
        esac
    fi
    [ "$TIMEOUT" -lt 60 ] 2>/dev/null && TIMEOUT=60
    [ "$TIMEOUT" -gt 120 ] 2>/dev/null && TIMEOUT=120

    echo "[*] Mode B Slot 1 trial boot detected (sw_commit=$CURRENT_COMMIT != 1)."
    echo "[*] Arming ${TIMEOUT}-second Slot 1 confirmation guard..."

    NOW=$(date +%s 2>/dev/null || echo "0")
    EXPIRY=$((NOW + TIMEOUT))
    echo "$EXPIRY" > "$GUARD_FILE"
    echo "$EXPIRY" > /tmp/.rollback_guard

    (
        REMAIN="$TIMEOUT"
        while [ "$REMAIN" -gt 0 ]; do
            # Check commit status
            CHK_COMMIT=$($NV_BIN getenv sw_commit 2>/dev/null | sed 's/^.*=//g' | tr -d ' \r\n')
            if [ "$CHK_COMMIT" = "1" ] || ([ -f "$CONFIRMED_FLAG" ] && [ ! -f "$UNCONFIRMED_FLAG" ]); then
                echo "[OK] Slot 1 confirmation detected. Guard disarmed."
                rm -f "$GUARD_FILE" /tmp/.rollback_guard "$PID_FILE"
                exit 0
            fi
            sleep 1
            REMAIN=$((REMAIN - 1))
        done

        # Re-check commit before rollback
        FINAL_COMMIT=$($NV_BIN getenv sw_commit 2>/dev/null | sed 's/^.*=//g' | tr -d ' \r\n')
        if [ "$FINAL_COMMIT" != "1" ]; then
            echo "[!] Slot 1 trial period (${TIMEOUT}s) expired without confirmation!"
            echo "[!] Triggering fallback to Slot 0..."
            do_rollback
        else
            echo "[OK] Slot 1 committed before timeout. Guard disarmed."
            rm -f "$GUARD_FILE" /tmp/.rollback_guard "$PID_FILE"
        fi
    ) >/dev/null 2>&1 &
    echo $! > "$PID_FILE"
}

case "$ACTION" in
    confirm|commit)
        do_confirm
        ;;
    rollback)
        do_rollback
        ;;
    guard)
        do_guard "$@"
        ;;
    status)
        echo "SLOT1_COMMITTED: NO"
        echo "CURRENT_COMMIT: $CURRENT_COMMIT"
        ;;
    *)
        echo "Usage: $0 {guard [timeout]|confirm|rollback|status}"
        exit 1
        ;;
esac
