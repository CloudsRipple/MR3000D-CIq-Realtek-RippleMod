#!/bin/sh
# Ripple-mod: Slot 1 flasher with hardware/layout guard (runs ON the router, busybox sh)
#
# Usage:  sh flash_slot1.sh check|flash <k1.uImage> <r1.squashfs>
#   check  run every guard, write nothing
#   flash  run guards, write ubi_k1 + ubi_r1, arm 90s trial boot, reboot
#
# Reference layout (MR3000D-CIq, read from the factory dump):
#   SPI NAND 128 MiB, page 2048 B, PEB 128 KiB, LEB 126976 B
#   mtd: boot 768K | env 128K | env2 128K | static_conf 128K | ubi_device 127360K
#   UBI vols: 0 ubi_Config 87 | 1 ubi_k0 83 | 2 ubi_r0 207 | 3 ubi_k1 83 | 4 ubi_r1 207
#             5 ubi_config_bak 17 | 6 ubi_factory 17 | 7 ubi_app 248   (PEBs)
# Only /dev/ubi0_3 and /dev/ubi0_4 are ever written. Raw NAND, boot and env are never touched.

MODE="$1"; K1="$2"; R1="$3"
LEB=126976
K1_MAX=$((83 * LEB))
R1_MAX=$((20 * 1024 * 1024))     # build budget, below the 207-PEB volume

fail() { echo "[REFUSE] $*" >&2; exit 1; }
ok()   { echo "[ ok ] $*"; }

[ "$MODE" = check ] || [ "$MODE" = flash ] || fail "usage: sh $0 check|flash <k1.uImage> <r1.squashfs>"
[ -f "$K1" ] && [ -f "$R1" ] || fail "image files not found"
[ "$(id -u 2>/dev/null)" = 0 ] || fail "must run as root"

# 1. SoC / kernel
case "$(uname -r)" in 5.10.70*) ok "kernel $(uname -r)";; *) fail "kernel $(uname -r) is not 5.10.70 (not the stock MR3000D-CIq firmware)";; esac
case "$(uname -m)" in mips*) ok "arch $(uname -m)";; *) fail "arch $(uname -m) is not MIPS";; esac
if [ -r /proc/device-tree/compatible ]; then
    tr '\0' ' ' < /proc/device-tree/compatible | grep -q "8198" || fail "device tree is not RTL8198"
    ok "device tree: RTL8198"
fi

# 2. Flash chip / MTD layout
mtd_field() { awk -v n="\"$1\"" '$4==n {print $2, $3}' /proc/mtd; }
[ "$(mtd_field ubi_device)" = "07c60000 00020000" ] || fail "mtd 'ubi_device' is not 0x7c60000 with 128KiB erase blocks (not this NAND)"
[ "$(mtd_field boot)" = "000c0000 00020000" ] || fail "mtd 'boot' layout mismatch"
[ "$(mtd_field env)" = "00020000 00020000" ] || fail "mtd 'env' layout mismatch"
[ "$(wc -l < /proc/mtd)" -ge 6 ] || fail "unexpected mtd count"
ok "SPI NAND layout: 128 MiB, 128 KiB erase block, ubi_device 0x7c60000"

# 3. UBI geometry and volumes
U=/sys/class/ubi/ubi0
[ -d "$U" ] || fail "ubi0 not attached"
[ "$(cat $U/min_io_size)" = 2048 ]       || fail "UBI min_io_size is not 2048"
[ "$(cat $U/eraseblock_size)" = $LEB ]   || fail "UBI LEB size is not $LEB"
[ "$(cat $U/volumes_count)" = 8 ]        || fail "UBI volume count is not 8"
check_vol() { # id name pebs
    [ "$(cat /sys/class/ubi/ubi0_$1/name 2>/dev/null)" = "$2" ] || fail "ubi0_$1 is not '$2'"
    [ "$(cat /sys/class/ubi/ubi0_$1/reserved_ebs 2>/dev/null)" = "$3" ] || fail "ubi0_$1 size is not $3 PEBs"
}
check_vol 0 ubi_Config 87;  check_vol 1 ubi_k0 83;  check_vol 2 ubi_r0 207;  check_vol 3 ubi_k1 83
check_vol 4 ubi_r1 207;     check_vol 5 ubi_config_bak 17;  check_vol 6 ubi_factory 17;  check_vol 7 ubi_app 248
ok "UBI volumes match the factory layout"

# 4. Running slot: never overwrite the slot we are running from
ACT="$(/bin/nv getenv sw_active 2>/dev/null | sed 's/^.*=//' | tr -d ' \r\n')"
[ "$ACT" = 0 ] || fail "sw_active is '$ACT', must be 0 (boot Slot 0 / stock first)"
mount | grep -qE 'ubi0_4|ubi_r1' && fail "ubi_r1 is mounted (running from Slot 1)"
ok "running from Slot 0, Slot 1 is free"

# 5. Image checks
KSZ=$(wc -c < "$K1"); RSZ=$(wc -c < "$R1")
[ "$(od -An -tx1 -N4 "$K1" | tr -d ' \n')" = 27051956 ] || fail "$K1 is not a uImage"
[ "$KSZ" -le "$K1_MAX" ] || fail "kernel image $KSZ B exceeds ubi_k1 ($K1_MAX B)"
[ "$(od -An -c -N4 "$R1" | tr -d ' \n')" = hsqs ] || fail "$R1 is not a little-endian SquashFS"
[ "$RSZ" -le "$R1_MAX" ] || fail "rootfs image $RSZ B exceeds $R1_MAX B"
ok "images: kernel $KSZ B, rootfs $RSZ B"
SUMS="$(dirname "$R1")/MD5SUMS"
if [ -f "$SUMS" ]; then
    for f in "$K1" "$R1"; do
        want=$(grep " $(basename "$f")\$" "$SUMS" | awk '{print $1}')
        [ -n "$want" ] || fail "no checksum for $(basename "$f") in MD5SUMS"
        [ "$(md5sum "$f" | awk '{print $1}')" = "$want" ] || fail "checksum mismatch: $f"
    done
    ok "checksums verified"
else
    fail "MD5SUMS next to the images is required (download it from the Release)"
fi

[ "$MODE" = check ] && { echo "All guards passed. Nothing was written."; exit 0; }

# 6. Write Slot 1 only, then arm trial boot with 90s rollback
echo "[*] flashing ubi_k1 (/dev/ubi0_3)"; ubiupdatevol /dev/ubi0_3 "$K1" || fail "kernel write failed (Slot 0 is untouched)"
echo "[*] flashing ubi_r1 (/dev/ubi0_4)"; ubiupdatevol /dev/ubi0_4 "$R1" || fail "rootfs write failed (Slot 0 is untouched)"
echo 90 > /var/app/.unconfirmed
/bin/nv setenv sw_commit 0
/bin/nv setenv sw_tryactive 1
/bin/nv setenv sw_updater
sync
echo "[+] done. Rebooting into Slot 1; confirm within 90s or it rolls back to Slot 0."
sleep 1; reboot
