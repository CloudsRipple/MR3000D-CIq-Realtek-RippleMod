#!/usr/bin/env python3
"""
Ripple-mod 固件镜像构建器 (CMCC MR3000D-CIq / RTL8198D)

输入 (均由使用者自备, 不随仓库分发):
  --rootfs      已解包的原厂 rootfs 目录 (SquashFS 解包结果)
  --backup-dir  原厂备份目录, 需含 ubi0_1_k0.uImage

输出 (--out-dir):
  ubi0_3_k1_kernel.uImage   Slot 1 内核 (复制自原厂 k0, 校验 uImage 头/CRC)
  ubi0_4_r1_mod.squashfs    Slot 1 rootfs (XZ, 128K 块, 必须 < 20MB)

rootfs 处理: 保留 bringup 必需文件 -> 移除厂商遥测/强制升级 -> 清理 inittab/rc22/rc36 ->
把 Ripple-mod 套件放入 /etc/ripple-mod, 并由 /etc/init.d/rc37 在开机时同步到 /var/app 后启动。
"""
import argparse, os, shutil, struct, subprocess, sys, tempfile, zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_SQUASHFS = 0x1400000
UIMAGE_MAGIC = 0x27051956

CRITICAL = [
    "lib/libwwc.so", "bin/startup", "bin/configd", "bin/flash", "bin/boa", "bin/hostapd",
    "bin/systemd", "bin/spppd", "lib/libmib.so", "lib/librtk.so",
    "lib/modules/5.10.70/kernel/drivers/net/wireless/realtek/g6_wifi_driver/rtk_wifi6.ko",
]
DEBLOAT = [
    "bin/aosnet", "bin/lanNetInfo", "bin/lanNetInfo_action", "bin/ahsapd", "bin/ahsapd_logsrv",
    "bin/do_force_upgrade", "bin/check_upgrade_info", "usr/bin/vasdocker", "usr/bin/vasdocker.conf",
]
INERT = ["lib/libcc1.so.0.0.0", "lib/libcc1.so.0", "lib/libcc1.so"]
GUARDS = ["slot1_confirm_guard.sh", "rollback_guard.sh", "confirm_keep.sh", "anti_ota_shield.sh",
          "remote_fix_net.sh", "wifi_tuner.sh", "low_latency_driver_tuner.sh"]
SUITE_DIRS = ["bin", "core_system", "plugin_engine", "plugins", "web"]
KO_REL = CRITICAL[-1]

RC37 = r"""#!/bin/sh
# Ripple-mod Slot 1 startup hook (run by /etc/init.d/rcS)

# 1. 90s rollback guard: unless confirmed, boot falls back to Slot 0
if [ -x /bin/slot1_confirm_guard.sh ]; then
    /bin/slot1_confirm_guard.sh guard 90 &
fi

# 2. Telnet (2356) for recovery
[ -x /bin/telnetd ] && /bin/telnetd -p 2356 2>/dev/null &

# 3. Sync Ripple-mod suite to writable /var/app, keep user settings
SRC=/etc/ripple-mod
APP=/var/app
if [ -d "$SRC" ] && [ -d "$APP" ]; then
    KEEP=/tmp/ripple_keep
    rm -rf "$KEEP"; mkdir -p "$KEEP"
    for p in "$APP"/plugins/*; do
        [ -d "$p" ] || continue
        n=${p##*/}
        mkdir -p "$KEEP/$n"
        for f in config.conf .enabled user_run.sh; do
            [ -e "$p/$f" ] && cp -p "$p/$f" "$KEEP/$n/$f"
        done
    done
    (cd "$SRC" && tar cf - .) | (cd "$APP" && tar xf -)
    for d in "$KEEP"/*; do
        [ -d "$d" ] || continue
        n=${d##*/}
        # plugin existed before: respect its enabled/disabled state
        [ -e "$d/.enabled" ] || rm -f "$APP/plugins/$n/.enabled"
        for f in config.conf .enabled user_run.sh; do
            [ -e "$d/$f" ] && cp -p "$d/$f" "$APP/plugins/$n/$f"
        done
    done
    rm -rf "$KEEP"
    chmod +x "$APP"/bin/* "$APP"/core_system/init.d/*.sh "$APP"/core_system/runtime/*.sh \
        "$APP"/plugin_engine/*.sh "$APP"/scripts/*.sh "$APP"/plugins/*/*.sh "$APP"/web/*.cgi "$APP"/web/cgi-bin/*.cgi 2>/dev/null
    # user.sh needs dirname before it links applets itself
    if [ -x "$APP/bin/busybox" ]; then
        for a in dirname basename; do [ -e "$APP/bin/$a" ] || ln -sf busybox "$APP/bin/$a"; done
    fi
    export PATH="$APP/bin:$PATH"
    # delay like stock rcS does for /var/app/user.sh, so the stock firewall/network init finishes first
    (sleep 20; sh "$APP/core_system/init.d/user.sh") &
fi

# 4. Wi-Fi / IRQ low-latency tuning
[ -x /bin/low_latency_driver_tuner.sh ] && /bin/low_latency_driver_tuner.sh enable >/dev/null 2>&1 &
"""


def log(m): print(f"[*] {m}")
def ok(m): print(f"[+] {m}")


def mips_be(path):
    with open(path, "rb") as f:
        h = f.read(52)
    return (len(h) == 52 and h[:4] == b"\x7fELF" and h[4] == 1 and h[5] == 2
            and struct.unpack(">H", h[18:20])[0] == 8)


def build_kernel(backup, out):
    src = os.path.join(backup, "ubi0_1_k0.uImage")
    dst = os.path.join(out, "ubi0_3_k1_kernel.uImage")
    shutil.copy2(src, dst)
    with open(dst, "rb") as f:
        hdr, data = f.read(64), None
        data = f.read()
    (magic, hcrc, _t, size, _l, _e, dcrc, osn, arch, _ty, _c, name) = struct.unpack(">IIIIIIIBBBB32s", hdr)
    if magic != UIMAGE_MAGIC or arch != 5 or osn != 5:
        raise ValueError("bad uImage header")
    if zlib.crc32(hdr[:4] + b"\0\0\0\0" + hdr[8:]) != hcrc or zlib.crc32(data[:size]) != dcrc:
        raise ValueError("uImage CRC mismatch")
    ok(f"kernel uImage verified: {name.rstrip(chr(0).encode()).decode('latin1')}")


def comment_lines(path, needles, tag):
    if not os.path.isfile(path):
        return
    out = []
    for line in open(path):
        out.append(f"# {tag}: {line}" if any(n in line for n in needles) else line)
    open(path, "w").writelines(out)


def stage(rootfs, staging):
    shutil.copytree(rootfs, staging, symlinks=True)
    for req in CRITICAL:
        if not os.path.lexists(os.path.join(staging, req)):
            raise RuntimeError(f"rootfs missing required file: {req}")
    for rel in INERT + DEBLOAT:
        p = os.path.join(staging, rel)
        if os.path.lexists(p):
            shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
    tag = "Neutralized by Ripple-mod"
    comment_lines(os.path.join(staging, "etc/inittab"), ["ahsapd"], tag)
    comment_lines(os.path.join(staging, "etc/init.d/rc22"), ["check_upgrade", "do_force_upgrade"], tag)
    comment_lines(os.path.join(staging, "etc/init.d/rc36"), ["start_plugin"], tag)
    fw = os.path.join(staging, "etc/scripts/fw_loaded_cmcc.sh")
    if os.path.isfile(fw):
        open(fw, "w").write("#!/bin/sh\n# Neutralized by Ripple-mod (aosnet removed)\nexit 0\n")
        os.chmod(fw, 0o755)

    # Ripple-mod suite -> /etc/ripple-mod
    dst_suite = os.path.join(staging, "etc", "ripple-mod")
    for d in SUITE_DIRS:
        shutil.copytree(os.path.join(REPO, d), os.path.join(dst_suite, d), symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store", "*.c"))
    for b in ["dropbearmulti", "busybox_mips", "ripple_api_daemon"]:
        if not mips_be(os.path.join(dst_suite, "bin", b)):
            raise ValueError(f"{b} is not MIPS32 big-endian ELF")
    # stock busybox/dropbear names stay untouched; suite binaries live under /var/app/bin

    # rollback guard + tuning scripts -> /bin, and -> suite scripts/ (ripple_api_daemon calls /var/app/scripts/*)
    gdir = os.path.join(REPO, "firmware", "guards")
    os.makedirs(os.path.join(dst_suite, "scripts"), exist_ok=True)
    for g in GUARDS:
        for d in (os.path.join(staging, "bin"), os.path.join(dst_suite, "scripts")):
            dst = os.path.join(d, g)
            shutil.copy2(os.path.join(gdir, g), dst)
            os.chmod(dst, 0o755)

    ko = os.path.join(staging, KO_REL)
    r = subprocess.run([sys.executable, os.path.join(gdir, "patch_rtk_wifi6_ko.py"),
                        "--input", ko, "--output", ko], capture_output=True, text=True)
    ok("rtk_wifi6.ko low-latency patch applied") if r.returncode == 0 else log(f"ko patch skipped: {r.stderr.strip()}")

    hosts = os.path.join(staging, "etc", "hosts")
    if os.path.lexists(hosts):
        os.remove(hosts)
    os.symlink("/var/tmp/hosts", hosts)

    rc37 = os.path.join(staging, "etc", "init.d", "rc37")
    open(rc37, "w").write(RC37)
    os.chmod(rc37, 0o755)


def build_squashfs(staging, out):
    dst = os.path.join(out, "ubi0_4_r1_mod.squashfs")
    if os.path.exists(dst):
        os.remove(dst)
    mk = shutil.which("mksquashfs")
    if not mk:
        raise FileNotFoundError("mksquashfs not found")
    r = subprocess.run([mk, staging, dst, "-comp", "xz", "-b", "131072", "-always-use-fragments",
                        "-no-xattrs", "-noappend", "-all-root"], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr)
    size = os.path.getsize(dst)
    if open(dst, "rb").read(4) != b"hsqs":
        raise ValueError("bad squashfs magic")
    if size >= MAX_SQUASHFS:
        raise ValueError(f"squashfs {size} bytes exceeds 20MB budget")
    ok(f"squashfs built: {size:,} bytes, {MAX_SQUASHFS - size:,} bytes headroom")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rootfs", required=True)
    ap.add_argument("--backup-dir", required=True)
    ap.add_argument("--out-dir", default=os.path.join(REPO, "firmware_images"))
    a = ap.parse_args()
    os.makedirs(a.out_dir, exist_ok=True)
    build_kernel(a.backup_dir, a.out_dir)
    st = tempfile.mkdtemp(prefix="ripple_rootfs_")
    try:
        shutil.rmtree(st)
        stage(a.rootfs, st)
        build_squashfs(st, a.out_dir)
    finally:
        shutil.rmtree(st, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
