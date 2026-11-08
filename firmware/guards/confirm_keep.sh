#!/bin/sh
# ==============================================================================
# CMCC MR3000D-CIq User Confirmation CLI Utility
# Location: /var/app/scripts/confirm_keep.sh
# Purpose: Manually confirm modifications, remove .unconfirmed, commit slot, and sync.
# ==============================================================================

NV_BIN=$(which nv 2>/dev/null || echo /bin/nv)
UNCONFIRMED_FLAG="/var/app/.unconfirmed"
CONFIRMED_FLAG="/tmp/mod_confirmed"
CONF_DIR="/var/app/conf"

echo "=========================================================="
echo "    🚀 CMCC MR3000D-CIq Mod Permanent Confirmation"
echo "=========================================================="

# Fix 1: Remove persistent unconfirmed flag and touch runtime confirmed flag
if [ -f "$UNCONFIRMED_FLAG" ]; then
    rm -f "$UNCONFIRMED_FLAG"
    echo "[*] Removed persistent unconfirmed flag: $UNCONFIRMED_FLAG"
fi
rm -f "$CONF_DIR/.rollback_guard" /tmp/.rollback_guard
touch "$CONFIRMED_FLAG"
echo "[*] Runtime confirmed flag created: $CONFIRMED_FLAG"

# Fix 2 & Fix 3: Check Slot 1 commit status and unset sw_updater without ""
if [ -x "$NV_BIN" ]; then
    ACTIVE_SLOT=$($NV_BIN getenv sw_active 2>/dev/null | sed 's/^.*=//g' | tr -d ' \r\n')
    CURRENT_COMMIT=$($NV_BIN getenv sw_commit 2>/dev/null | sed 's/^.*=//g' | tr -d ' \r\n')
    [ -z "$ACTIVE_SLOT" ] && ACTIVE_SLOT="1"

    if [ "$ACTIVE_SLOT" = "1" ] && [ "$CURRENT_COMMIT" != "1" ]; then
        echo "[*] Mode B Slot 1 uncommitted detected (sw_commit=$CURRENT_COMMIT)."
        echo "[*] Committing Slot 1 permanently..."
        $NV_BIN setenv sw_commit 1
        # Fix 3: unset sw_updater with only key name
        $NV_BIN setenv sw_updater
        echo "[OK] Slot 1 committed in U-Boot environment (sw_commit=1)."
    else
        echo "[*] Slot commit status verified (active=$ACTIVE_SLOT, commit=${CURRENT_COMMIT:-1})."
    fi
fi

# Stop any active countdown background job
for pid_f in /tmp/rollback_guard.pid /tmp/slot1_guard.pid; do
    if [ -f "$pid_f" ]; then
        PID=$(cat "$pid_f" 2>/dev/null)
        [ -n "$PID" ] && kill -9 "$PID" 2>/dev/null || true
        rm -f "$pid_f"
    fi
done

sync
echo "----------------------------------------------------------"
echo "  ✅ SUCCESS: Router modifications permanently confirmed!"
echo "  ✅ /var/app/.unconfirmed removed (Persistence Trap Safe)."
echo "  ✅ Future reboots & power outages will run normally."
echo "=========================================================="
exit 0
