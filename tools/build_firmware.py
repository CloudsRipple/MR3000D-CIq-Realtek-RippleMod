#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CMCC MR3000D-CIq Ripple-mod Full Firmware Image Builder
=======================================================
Builds genuine Slot 1 firmware artifacts directly from the current Ripple-mod tree:
  1. firmware_images/ubi0_3_k1_kernel.uImage
  2. firmware_images/ubi0_4_r1_mod.squashfs
  3. firmware_images/ripple_mod_overlay.tar.gz
"""

import os
import sys
import shutil
import struct
import zlib
import tarfile
import subprocess
import tempfile
from typing import Tuple

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
ROOTFS_SRC = os.path.join(ROOT_DIR, "legacy_workspace", "analysis", "rootfs")
BACKUP_DIR = os.path.join(ROOT_DIR, "legacy_workspace", "firmware_backup_20261106_202412")
LEGACY_SCRIPTS = os.path.join(ROOT_DIR, "legacy_workspace", "mr3000d_commercial_mod_pkg", "scripts")
OUT_DIR = os.path.join(ROOT_DIR, "firmware_images")

MAX_SQUASHFS_SIZE = 0x1400000  # 20 MB (20,971,520 bytes)
SQUASHFS_LE_MAGIC = b"hsqs"
UIMAGE_MAGIC = 0x27051956

CRITICAL_BRINGUP_FILES = [
    "lib/libwwc.so",
    "bin/startup",
    "bin/configd",
    "bin/flash",
    "bin/boa",
    "bin/hostapd",
    "bin/systemd",
    "bin/spppd",
    "lib/libmib.so",
    "lib/librtk.so",
    "lib/modules/5.10.70/kernel/drivers/net/wireless/realtek/g6_wifi_driver/rtk_wifi6.ko",
]

DEBLOAT_PATHS = [
    "bin/aosnet",
    "bin/lanNetInfo",
    "bin/lanNetInfo_action",
    "bin/ahsapd",
    "bin/ahsapd_logsrv",
    "bin/do_force_upgrade",
    "bin/check_upgrade_info",
    "usr/bin/vasdocker",
    "usr/bin/vasdocker.conf",
]

INERT_HOST_LIBS = [
    "lib/libcc1.so.0.0.0",
    "lib/libcc1.so.0",
    "lib/libcc1.so",
]


def log(msg: str):
    print(f"[*] {msg}")


def log_ok(msg: str):
    print(f"[+] {msg}")


def log_warn(msg: str):
    print(f"[!] {msg}")


def verify_elf_mips_be(filepath: str) -> Tuple[bool, str]:
    if not os.path.isfile(filepath):
        return False, f"File not found: {filepath}"
    with open(filepath, "rb") as f:
        hdr = f.read(52)
    if len(hdr) < 52 or hdr[:4] != b"\x7fELF":
        return False, "Not an ELF binary"
    if hdr[4] != 1:
        return False, f"Not 32-bit (ei_class={hdr[4]})"
    if hdr[5] != 2:
        return False, f"Not Big-Endian MSB (ei_data={hdr[5]})"
    machine = struct.unpack(">H", hdr[18:20])[0]
    if machine != 8:
        return False, f"Not MIPS architecture (machine={machine})"
    return True, "ELF 32-bit MSB MIPS Big-Endian verified"


def build_kernel_uimage() -> str:
    log("Building Slot 1 Kernel Image (ubi0_3_k1_kernel.uImage)...")
    src_k0 = os.path.join(BACKUP_DIR, "ubi0_1_k0.uImage")
    if not os.path.isfile(src_k0):
        src_k0 = os.path.join(BACKUP_DIR, "ubi0_3_k1.uImage")
    if not os.path.isfile(src_k0):
        raise FileNotFoundError(f"Stock kernel uImage not found in {BACKUP_DIR}")

    with open(src_k0, "rb") as f:
        data = f.read()

    if len(data) < 64:
        raise ValueError("Kernel uImage too small (< 64 bytes)")

    magic, hcrc, _, dsize, _, _, dcrc = struct.unpack(">IIIIIII", data[:28])
    if magic != UIMAGE_MAGIC:
        raise ValueError(f"Invalid uImage magic: 0x{magic:08x}")

    hdr_zero = data[:4] + b"\x00\x00\x00\x00" + data[8:64]
    calc_hcrc = zlib.crc32(hdr_zero) & 0xFFFFFFFF
    if calc_hcrc != hcrc:
        raise ValueError(f"uImage header CRC mismatch: 0x{calc_hcrc:08x} != 0x{hcrc:08x}")

    os.makedirs(OUT_DIR, exist_ok=True)
    dst_k1 = os.path.join(OUT_DIR, "ubi0_3_k1_kernel.uImage")
    shutil.copy2(src_k0, dst_k1)
    log_ok(f"Kernel uImage ready: {dst_k1} ({len(data):,} bytes, payload={dsize:,}, dcrc=0x{dcrc:08x})")
    return dst_k1


def build_overlay_tar() -> str:
    log("Building Ripple-mod /var/app overlay tarball...")
    os.makedirs(OUT_DIR, exist_ok=True)
    dst_tar = os.path.join(OUT_DIR, "ripple_mod_overlay.tar.gz")

    def _filter(ti: tarfile.TarInfo):
        name = ti.name
        if any(p in name for p in (".git", ".DS_Store", "__pycache__")) or name.endswith(".pyc"):
            return None
        return ti

    with tarfile.open(dst_tar, "w:gz") as tar:
        for d in ("bin", "core_system", "plugin_engine", "plugins", "web"):
            full_d = os.path.join(ROOT_DIR, d)
            if os.path.exists(full_d):
                tar.add(full_d, arcname=d, filter=_filter)

    log_ok(f"Overlay tarball ready: {dst_tar} ({os.path.getsize(dst_tar):,} bytes)")
    return dst_tar


def _copy_tree_clean(src: str, dst: str):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        symlinks=True,
        ignore=shutil.ignore_patterns(".git", ".DS_Store", "__pycache__", "*.pyc"),
    )


def prepare_staging_rootfs(staging_dir: str, experimental_patch_wifi: bool = False):
    log(f"Staging RootFS from {ROOTFS_SRC}...")
    if not os.path.isdir(ROOTFS_SRC):
        raise FileNotFoundError(f"Base rootfs not found: {ROOTFS_SRC}")
    if os.path.exists(staging_dir):
        shutil.rmtree(staging_dir)

    shutil.copytree(ROOTFS_SRC, staging_dir, symlinks=True)

    # 1. Verify critical bringup files
    for req in CRITICAL_BRINGUP_FILES:
        target = os.path.join(staging_dir, req)
        if not os.path.lexists(target):
            raise RuntimeError(f"CRITICAL ERROR: Missing bringup file: {req}")
    libwwc = os.path.join(staging_dir, "lib", "libwwc.so")
    if os.path.getsize(libwwc) < 50000:
        raise RuntimeError("CRITICAL ERROR: /lib/libwwc.so is truncated")
    log_ok("Verified /lib/libwwc.so and all core Realtek bringup binaries.")

    # 2. Strip inert libs & CMCC telemetry/force-upgrade daemons
    for rel in INERT_HOST_LIBS + DEBLOAT_PATHS:
        p = os.path.join(staging_dir, rel)
        if os.path.lexists(p):
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)

    # 3. Neutralize CMCC respawn/timers
    inittab = os.path.join(staging_dir, "etc", "inittab")
    if os.path.isfile(inittab):
        with open(inittab, "r") as f:
            lines = f.readlines()
        with open(inittab, "w") as f:
            f.writelines(f"# Neutralized: {l}" if "ahsapd" in l else l for l in lines)

    rc22 = os.path.join(staging_dir, "etc", "init.d", "rc22")
    if os.path.isfile(rc22):
        with open(rc22, "r") as f:
            lines = f.readlines()
        with open(rc22, "w") as f:
            f.writelines(f"# Neutralized: {l}" if ("check_upgrade" in l or "do_force_upgrade" in l) else l for l in lines)

    fw_cmcc = os.path.join(staging_dir, "etc", "scripts", "fw_loaded_cmcc.sh")
    if os.path.isfile(fw_cmcc):
        with open(fw_cmcc, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(fw_cmcc, 0o755)

    rc36 = os.path.join(staging_dir, "etc", "init.d", "rc36")
    if os.path.isfile(rc36):
        with open(rc36, "r") as f:
            lines = f.readlines()
        with open(rc36, "w") as f:
            f.writelines(f"# Neutralized: {l}" if "start_plugin" in l else l for l in lines)

    # 4. Integrate MIPS32 Big-Endian binaries
    bin_src = os.path.join(ROOT_DIR, "bin")
    for b in ("dropbearmulti", "ripple_api_daemon", "busybox_mips"):
        src_b = os.path.join(bin_src, b)
        valid, msg = verify_elf_mips_be(src_b)
        if not valid:
            raise ValueError(f"Binary {b} failed MIPS BE check: {msg}")
        dst_b = os.path.join(staging_dir, "bin", b)
        shutil.copy2(src_b, dst_b)
        os.chmod(dst_b, 0o755)
        log_ok(f"Integrated /bin/{b} ({msg})")

    for sym, target in [
        ("dropbear", "dropbearmulti"),
        ("dbclient", "dropbearmulti"),
        ("dropbearkey", "dropbearmulti"),
        ("scp", "dropbearmulti"),
        ("geek_api_daemon", "ripple_api_daemon"),
    ]:
        dst_sym = os.path.join(staging_dir, "bin", sym)
        if os.path.lexists(dst_sym):
            os.remove(dst_sym)
        os.symlink(target, dst_sym)

    # 5. Integrate Ripple-mod Web UI into /home/httpd/web AND /var/app/web
    web_src = os.path.join(ROOT_DIR, "web")
    for web_dst in (
        os.path.join(staging_dir, "home", "httpd", "web"),
        os.path.join(staging_dir, "var", "app", "web"),
    ):
        os.makedirs(web_dst, exist_ok=True)
        for item in os.listdir(web_src):
            if item in (".DS_Store", "__pycache__"):
                continue
            s = os.path.join(web_src, item)
            d = os.path.join(web_dst, item)
            if os.path.isdir(s):
                _copy_tree_clean(s, d)
            else:
                shutil.copy2(s, d)
                if item.endswith(".cgi"):
                    os.chmod(d, 0o755)
        cgi_bin = os.path.join(web_dst, "cgi-bin", "api.cgi")
        if os.path.isfile(cgi_bin):
            os.chmod(cgi_bin, 0o755)
    log_ok("Integrated latest Web UI into /home/httpd/web and /var/app/web.")

    # 6. Integrate core_system, plugin_engine, plugins, bin into /var/app & /etc/plugins
    var_app = os.path.join(staging_dir, "var", "app")
    os.makedirs(var_app, exist_ok=True)
    for comp in ("bin", "core_system", "plugin_engine", "plugins"):
        _copy_tree_clean(os.path.join(ROOT_DIR, comp), os.path.join(var_app, comp))
    _copy_tree_clean(os.path.join(ROOT_DIR, "plugins"), os.path.join(staging_dir, "etc", "plugins"))

    # Make all scripts/binaries in /var/app executable
    for root, _, files in os.walk(var_app):
        for fn in files:
            if fn.endswith((".sh", ".cgi")) or os.path.basename(root) == "bin":
                p = os.path.join(root, fn)
                if not os.path.islink(p):
                    os.chmod(p, 0o755)

    user_sh_link = os.path.join(var_app, "user.sh")
    if os.path.lexists(user_sh_link):
        os.remove(user_sh_link)
    os.symlink("/var/app/core_system/init.d/user.sh", user_sh_link)
    log_ok("Integrated core_system, plugin_engine, plugins, bin into /var/app.")

    # 7. Integrate failsafe guard scripts into /bin/
    guard_scripts = [
        "slot1_confirm_guard.sh",
        "rollback_guard.sh",
        "confirm_keep.sh",
        "anti_ota_shield.sh",
    ]
    var_app_scripts = os.path.join(var_app, "scripts")
    os.makedirs(var_app_scripts, exist_ok=True)
    for gs in guard_scripts:
        src_gs = os.path.join(LEGACY_SCRIPTS, gs)
        if os.path.isfile(src_gs):
            dst_gs = os.path.join(staging_dir, "bin", gs)
            shutil.copy2(src_gs, dst_gs)
            os.chmod(dst_gs, 0o755)
            link_p = os.path.join(var_app_scripts, gs)
            if os.path.lexists(link_p):
                os.remove(link_p)
            os.symlink(f"/bin/{gs}", link_p)

    # 8. Keep pristine rtk_wifi6.ko by default (32-function stubbing is experimental & unverified)
    ko_rel = "lib/modules/5.10.70/kernel/drivers/net/wireless/realtek/g6_wifi_driver/rtk_wifi6.ko"
    staging_ko = os.path.join(staging_dir, ko_rel)
    patcher = os.path.join(LEGACY_SCRIPTS, "patch_rtk_wifi6_ko.py")
    if experimental_patch_wifi:
        if os.path.isfile(staging_ko) and os.path.isfile(patcher):
            log_warn("Applying EXPERIMENTAL 32-function patch to rtk_wifi6.ko (--experimental-patch-wifi enabled)...")
            res = subprocess.run(
                [sys.executable, patcher, "--input", staging_ko, "--output", staging_ko],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if res.returncode == 0:
                log_ok("Applied experimental patch to rtk_wifi6.ko.")
            else:
                log_warn(f"patch_rtk_wifi6_ko.py warning: {res.stderr.strip()}")
    else:
        log_ok("Keeping pristine stock rtk_wifi6.ko (32-function binary patch disabled by default for stability).")

    # 9. /etc/hosts -> /var/tmp/hosts symlink
    etc_hosts = os.path.join(staging_dir, "etc", "hosts")
    if os.path.lexists(etc_hosts):
        os.remove(etc_hosts)
    os.symlink("/var/tmp/hosts", etc_hosts)

    # 10. Hook clean Ripple-mod startup into /etc/init.d/rc37
    rc37_path = os.path.join(staging_dir, "etc", "init.d", "rc37")
    rc37_content = """#!/bin/sh
# CMCC MR3000D-CIq Ripple-mod Slot 1 Startup Hook

# 1. Arm failsafe rollback guard (90s trial boot protection)
if [ -x /bin/slot1_confirm_guard.sh ]; then
    /bin/slot1_confirm_guard.sh guard 90 &
fi

# 2. Seed /var/app/plugins only if missing (never clobber user configs)
if [ -d /etc/plugins ] && [ ! -d /var/app/plugins/hosts_adblock_dns ]; then
    mkdir -p /var/app/plugins
    cp -rf /etc/plugins/* /var/app/plugins/ 2>/dev/null || true
    chmod +x /var/app/plugins/*/*.sh /var/app/plugins/*/scripts/*.sh 2>/dev/null || true
fi

# 3. Deferred LAN-bound console + one-shot Ripple-mod bootstrap (wait for stock startup& to bring up br0)
(
    LAN_IP=""
    _w=0
    while [ $_w -lt 20 ]; do
        LAN_IP=$(ip -4 addr show dev br0 2>/dev/null | awk '/inet /{print $2; exit}' | cut -d/ -f1)
        [ -z "$LAN_IP" ] && LAN_IP=$(ifconfig br0 2>/dev/null | awk -F'[: ]+' '/inet addr/{print $4; exit}')
        [ -n "$LAN_IP" ] && break
        sleep 1
        _w=$((_w + 1))
    done

    if [ -x /bin/telnetd ] && ! pidof telnetd >/dev/null 2>&1; then
        if [ -n "$LAN_IP" ]; then
            /bin/telnetd -b "$LAN_IP" -p 2356 -l /bin/login 2>/dev/null || /bin/telnetd -p 2356 -l /bin/login 2>/dev/null &
        else
            /bin/telnetd -p 2356 -l /bin/login 2>/dev/null &
        fi
    fi

    if [ -x /bin/dropbearmulti ] && ! pidof dropbear >/dev/null 2>&1; then
        KEY_DIR="/var/app/conf/ssh"
        mkdir -p "$KEY_DIR" 2>/dev/null || KEY_DIR="/tmp/dropbear"
        mkdir -p "$KEY_DIR" 2>/dev/null || true
        KEY_FILE="$KEY_DIR/dropbear_ed25519_host_key"
        if [ ! -f "$KEY_FILE" ] && [ -x /bin/dropbearkey ]; then
            /bin/dropbearkey -t ed25519 -f "$KEY_FILE" 2>/dev/null || true
        fi
        if [ -w /var/passwd ]; then
            sed -i 's|^admin:.*|admin:$1$9zE8P7R5$5IeYiR8q8X0sZ6tUc3A5a0:0:0:root:/var/app:/bin/sh|' /var/passwd 2>/dev/null || true
        fi
        DROPBEAR_ADDR="22"
        [ -n "$LAN_IP" ] && DROPBEAR_ADDR="${LAN_IP}:22"
        if [ -f "$KEY_FILE" ]; then
            /bin/dropbearmulti dropbear -p "$DROPBEAR_ADDR" -r "$KEY_FILE" -R 2>/dev/null || \
            /bin/dropbearmulti dropbear -p 22 -r "$KEY_FILE" -R 2>/dev/null || true
        else
            /bin/dropbearmulti dropbear -p "$DROPBEAR_ADDR" -R 2>/dev/null || \
            /bin/dropbearmulti dropbear -p 22 -R 2>/dev/null || true
        fi
    fi

    if [ -f /var/app/core_system/init.d/user.sh ] && [ ! -f /tmp/ripple_mod_boot.done ]; then
        sh /var/app/core_system/init.d/user.sh >/tmp/ripple_boot.log 2>&1
    fi
) </dev/null >/dev/null 2>&1 &
"""
    with open(rc37_path, "w") as f:
        f.write(rc37_content)
    os.chmod(rc37_path, 0o755)
    log_ok("Configured /etc/init.d/rc37 startup hook.")


def build_squashfs_image(staging_dir: str) -> str:
    log("Packing SquashFS 4.0 XZ RootFS (ubi0_4_r1_mod.squashfs)...")
    os.makedirs(OUT_DIR, exist_ok=True)
    dst_squashfs = os.path.join(OUT_DIR, "ubi0_4_r1_mod.squashfs")
    if os.path.exists(dst_squashfs):
        os.remove(dst_squashfs)

    mksquashfs_bin = shutil.which("mksquashfs")
    if not mksquashfs_bin:
        raise FileNotFoundError("mksquashfs not found in PATH!")

    cmd = [
        mksquashfs_bin,
        staging_dir,
        dst_squashfs,
        "-comp", "xz",
        "-b", "131072",
        "-always-use-fragments",
        "-no-xattrs",
        "-noappend",
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"mksquashfs failed: {res.stderr}")

    size = os.path.getsize(dst_squashfs)
    with open(dst_squashfs, "rb") as f:
        magic = f.read(4)
    if magic != SQUASHFS_LE_MAGIC:
        raise ValueError(f"Invalid SquashFS magic: {magic!r}")
    if size >= MAX_SQUASHFS_SIZE:
        raise ValueError(f"SquashFS size {size:,} exceeds 20MB limit ({MAX_SQUASHFS_SIZE:,})")

    log_ok(f"SquashFS ready: {dst_squashfs} ({size / (1024 * 1024):.2f} MB, magic=hsqs)")
    return dst_squashfs


def main(argv=None):
    import argparse

    parser = argparse.ArgumentParser(description="CMCC MR3000D-CIq Ripple-mod Full Firmware Image Builder")
    parser.add_argument(
        "--experimental-patch-wifi",
        action="store_true",
        help="Opt-in: apply experimental 32-function stub patch to rtk_wifi6.ko (disabled by default)",
    )
    args = parser.parse_args(argv if argv is not None else [])

    print("=" * 64)
    print("  CMCC MR3000D-CIq Ripple-mod Full Firmware Image Builder")
    print("=" * 64)
    build_kernel_uimage()
    build_overlay_tar()
    with tempfile.TemporaryDirectory(prefix="ripple_rootfs_") as staging_dir:
        prepare_staging_rootfs(staging_dir, experimental_patch_wifi=args.experimental_patch_wifi)
        build_squashfs_image(staging_dir)
    print("=" * 64)
    print(f"  [SUCCESS] All firmware artifacts built in: {OUT_DIR}")
    print("=" * 64)


if __name__ == "__main__":
    main(sys.argv[1:])
