#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CMCC MR3000D-CIq Ripple-mod Full Firmware Flasher (Slot 1 Kernel + RootFS)
==========================================================================
1. Waits for Mac to connect to router (Wi-Fi or Ethernet, bypassing TUN proxies).
2. Verifies Realtek RTL8198D hardware.
3. If currently booted in Slot 1 (ubi0_4 mounted as /), safely reboots to Slot 0 first
   so ubi0_3 and ubi0_4 can be cleanly flashed without EBUSY.
4. Updates /var/app overlay, flashes ubi0_3 (Kernel) and ubi0_4 (SquashFS RootFS).
5. Trial-boots into new Slot 1, verifies HTTP 200 on 192.168.10.1, and commits Slot 1.
"""

import os
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))
IMG_DIR = os.path.join(ROOT_DIR, "firmware_images")

sys.path.insert(0, SCRIPT_DIR)
import deploy_system


def wait_for_router(label="等待 Mac 连入路由器局域网"):
    attempt = 0
    while True:
        attempt += 1
        target_host = "192.168.10.1"
        lan_ip = deploy_system.find_real_lan_ip("192.168.10.")
        if not lan_ip:
            lan_ip = deploy_system.find_real_lan_ip("192.168.1.")
            if lan_ip:
                target_host = "192.168.1.1"

        if not lan_ip:
            sys.stdout.write(f"\r[*] {label} (轮次 {attempt})... 请连上路由器 Wi-Fi 或插上网线")
            sys.stdout.flush()
            time.sleep(1.5)
            continue

        print(f"\n[+] 检测到局域网 IP: {lan_ip} -> 目标路由器: {target_host}")
        for user, pwd in [("admin", "system"), ("root", "system"), ("CMCCAdmin", "aDm8H%MdA"), ("admin", "admin")]:
            try:
                session = deploy_system.connect_router(mac_ip=lan_ip, host=target_host, user=user, password=pwd)
                return session, lan_ip, target_host
            except Exception:
                pass

        print("[-] 暂未连上路由器控制端口，2 秒后重试...")
        time.sleep(2.0)


def verify_http_ok(host="192.168.10.1", timeout=5):
    try:
        req = urllib.request.Request(f"http://{host}/", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if resp.status == 200 and "404 Not Found" not in body and "resource not found" not in body:
                return True, resp.status
            return False, resp.status
    except Exception as e:
        return False, str(e)


def detect_running_slot(session):
    """
    可靠识别当前运行槽位 (Slot 0 vs Slot 1)，免疫终端回显污染与 SquashFS 根设备名差异。
    返回 (slot_int_or_None, raw_diag)。
    """
    # 命令文本故意拆开标记字面量，防止 Telnet/SSH 命令回显命中关键字
    cmd = (
        's="UNKNOWN"; '
        'cl=$(cat /proc/cmdline 2>/dev/null || true); '
        'mt=$(cat /proc/mounts 2>/dev/null || true); '
        'nv_act=$(/bin/nv getenv sw_active 2>/dev/null || true); '
        'case "$cl" in '
        '*ubi_r1*|*ubi0_4*|*root=31:4*) s="SLOT1" ;; '
        '*ubi_r0*|*ubi0_2*|*root=31:2*) s="SLOT0" ;; '
        'esac; '
        'if [ "$s" = "UNKNOWN" ]; then '
        '  if echo "$mt" | awk \'$2=="/" && ($1 ~ /ubi0_4|ubi_r1|ubiblock0_4/){found=1} END{exit !found}\'; then s="SLOT1"; '
        '  elif echo "$mt" | awk \'$2=="/" && ($1 ~ /ubi0_2|ubi_r0|ubiblock0_2/){found=1} END{exit !found}\'; then s="SLOT0"; '
        '  fi; '
        'fi; '
        'if [ "$s" = "UNKNOWN" ]; then '
        '  case "$nv_act" in *sw_active=1*) s="SLOT1" ;; *sw_active=0*) s="SLOT0" ;; esac; '
        'fi; '
        'printf "RUN_%s=%s\\n" "SLOT_DETECT" "$s"; '
        'printf "NV_ACT=%s\\n" "$nv_act"'
    )
    out = session.run_cmd(cmd)
    if "RUN_SLOT_DETECT=SLOT1" in out:
        return 1, out
    if "RUN_SLOT_DETECT=SLOT0" in out:
        return 0, out
    return None, out


def is_running_slot1(session):
    slot, diag = detect_running_slot(session)
    if slot is None:
        raise RuntimeError(f"无法可靠识别当前运行槽位，已中止以防误刷活动分区:\n{diag}")
    return slot == 1


def run_checked_cmd(session, cmd, label, timeout=120):
    """执行远端命令并严格校验 POSIX 退出码 $? == 0（避免仅靠子串猜测成功）。"""
    wrapped = f'( {cmd} ); rc=$?; printf "CMD_%s=%d\\n" "EXIT_CODE" "$rc"'
    out = session.run_cmd(wrapped, timeout=timeout)
    if "CMD_EXIT_CODE=0" not in out:
        raise RuntimeError(f"{label} 失败 (未返回 CMD_EXIT_CODE=0):\n{out}")
    return out


def push_with_retry(session, local_path, remote_path, base_port=9990, timeout=90, retries=3):
    for i in range(retries):
        try:
            deploy_system.push_file_to_router(session, local_path, remote_path, port=base_port + i, timeout=timeout)
            return
        except Exception as e:
            if i == retries - 1:
                raise
            print(f"[!] 传输重试 ({i+1}/{retries}): {e}")
            session.run_cmd("killall nc 2>/dev/null || true")
            time.sleep(1)


def main():
    print("=" * 68)
    print("  🚀 CMCC MR3000D-CIq Ripple-mod 完整固件包一键刷机工具")
    print("=" * 68)

    k1_path = os.path.join(IMG_DIR, "ubi0_3_k1_kernel.uImage")
    r1_path = os.path.join(IMG_DIR, "ubi0_4_r1_mod.squashfs")
    tar_path = os.path.join(IMG_DIR, "ripple_mod_overlay.tar.gz")

    for p in (k1_path, r1_path, tar_path):
        if not os.path.isfile(p):
            print(f"[*] 缺少镜像 {os.path.basename(p)}，正在自动构建完整固件包...")
            import build_firmware
            build_firmware.main()
            break

    print(f"[+] 固件包就绪:")
    print(f"    - Kernel:  {k1_path} ({os.path.getsize(k1_path)/1024/1024:.2f} MB)")
    print(f"    - RootFS:  {r1_path} ({os.path.getsize(r1_path)/1024/1024:.2f} MB)")
    print(f"    - Overlay: {tar_path} ({os.path.getsize(tar_path)/1024/1024:.2f} MB)\n")

    session, lan_ip, target_host = wait_for_router("等待连接路由器")

    # 1. 硬件核验
    cpu_info = session.run_cmd("cat /proc/cpuinfo | grep -E 'machine|cpu model' | head -n 2")
    if "8198" not in cpu_info and "interAptiv" not in cpu_info:
        print(f"[-] 硬件不匹配，已中止: {cpu_info}")
        session.close()
        sys.exit(1)
    print(f"[+] 硬件校验通过: {cpu_info.replace(chr(10), ' | ')}")

    # 2. 若当前正运行在 Slot 1，先安全切回 Slot 0 以便完整重写 ubi0_3 & ubi0_4
    if is_running_slot1(session):
        print("\n[!] 检测到路由器当前正运行在旧版 Slot 1 (/dev/ubi0_4 已挂载为 /)。")
        print("[*] 为完整刷入新版 SquashFS 底层固件，正在自动切回原厂 Slot 0 后再刷入...")
        session.run_cmd("/bin/nv setenv sw_commit 0 2>/dev/null || true")
        session.run_cmd("/bin/nv setenv sw_active 0 2>/dev/null || true")
        session.run_cmd("/bin/nv setenv sw_tryactive 0 2>/dev/null || true")
        session.run_cmd("/bin/nv setenv sw_updater 2>/dev/null || true")
        session.run_cmd("sync")
        try:
            session.run_cmd("sleep 1 && reboot &")
        except Exception:
            pass
        session.close()

        print("[*] 路由器正在重启进入 Slot 0 (约 40~50 秒)，请保持网线/Wi-Fi 连接...")
        time.sleep(20)
        session, lan_ip, target_host = wait_for_router("等待路由器从 Slot 0 重新上线")

        if is_running_slot1(session):
            print("[-] 路由器仍在 Slot 1，无法安全覆写 /dev/ubi0_4，请手动断电或确认 U-Boot 槽位。")
            session.close()
            sys.exit(1)

    print("\n[+] 确认当前处于 Slot 0，/dev/ubi0_3 与 /dev/ubi0_4 处于安全可写状态！")

    # 2.5 恢复 HWNAT 快转并清理任何限速/流控规则，确保传输高速且不丢包
    deploy_system.emergency_restore_fastpath(session)
    session.run_cmd("tc qdisc del dev eth0 root 2>/dev/null; tc qdisc del dev br0 root 2>/dev/null; tc qdisc del dev ifb0 root 2>/dev/null; killall nc 2>/dev/null || true")
    session.run_cmd("rm -f /tmp/k1.uImage /tmp/r1.squashfs /tmp/ripple_overlay.tar.gz /tmp/ripple_mod_bundle.tar.gz")
    df_out = session.run_cmd("df -h /tmp /var/app 2>/dev/null || df -h")
    print(f"[*] 路由器存储空间状态:\n{df_out}")

    # 3. 清理并更新 /var/app 独立应用分区
    print("\n[1/4] 正在更新 /var/app 持久化应用分区...")
    push_with_retry(session, tar_path, "/tmp/ripple_overlay.tar.gz", base_port=9990, timeout=90)
    session.run_cmd("rm -rf /var/app/cmcc_netplug /var/app/cmcc_sec2Router /var/app/web/mod_control.html /var/app/web/mod_driver.html /var/app/web/mod_dualwan.html /var/app/web/geek_os.html 2>/dev/null || true")
    session.run_cmd("mkdir -p /var/app /var/app/scripts && cd /var/app && (gzip -dc /tmp/ripple_overlay.tar.gz 2>/dev/null | tar -xf - || tar -xzf /tmp/ripple_overlay.tar.gz) 2>/dev/null || true")
    session.run_cmd("rm -f /tmp/ripple_overlay.tar.gz")
    session.run_cmd("chmod +x /var/app/bin/* /var/app/core_system/init.d/*.sh /var/app/core_system/network/*.sh /var/app/core_system/runtime/*.sh /var/app/plugin_engine/*.sh /var/app/plugins/*/*.sh /var/app/plugins/*/scripts/*.sh /var/app/web/*.cgi /var/app/web/cgi-bin/*.cgi 2>/dev/null || true")
    session.run_cmd("ln -sf /var/app/core_system/init.d/user.sh /var/app/user.sh 2>/dev/null || true")
    session.run_cmd("for gs in slot1_confirm_guard.sh rollback_guard.sh confirm_keep.sh anti_ota_shield.sh; do ln -sf /bin/$gs /var/app/scripts/$gs 2>/dev/null || true; done")
    # 迁移旧版 /var/app/conf 中可能导致 20-48h 无线失联的历史遗留开关
    session.run_cmd(
        'if [ -f /var/app/conf/wifi_tuning.conf ]; then '
        'sed -i \'s/^UNLOCK_TX_POWER=.*/UNLOCK_TX_POWER="0"/; s/^DISABLE_EDCCA_CARRIER_BACKOFF=.*/DISABLE_EDCCA_CARRIER_BACKOFF="0"/; s/^ENABLE_AIRTIME_FAIRNESS=.*/ENABLE_AIRTIME_FAIRNESS="0"/; s/^DENY_LEGACY_11B=.*/DENY_LEGACY_11B="0"/; s/^TUNE_PCIE_INT_MIT=.*/TUNE_PCIE_INT_MIT="0"/; s/^ENABLE_BAND_STEERING=.*/ENABLE_BAND_STEERING="0"/; s/^UNLOAD_IGMP_HOOK=.*/UNLOAD_IGMP_HOOK="0"/\' /var/app/conf/wifi_tuning.conf 2>/dev/null || true; '
        'fi; '
        'rm -f /var/app/conf/TXPWR_LMT_UNLOCKED.txt 2>/dev/null || true'
    )

    # 4. 刷写 Slot 1 Kernel (/dev/ubi0_3)
    print("\n[2/4] 正在传输并刷写 Slot 1 内核 (/dev/ubi0_3)...")
    push_with_retry(session, k1_path, "/tmp/k1.uImage", base_port=9980, timeout=120)
    run_checked_cmd(session, "ubiupdatevol /dev/ubi0_3 /tmp/k1.uImage && rm -f /tmp/k1.uImage", "Slot 1 内核烧录", timeout=120)
    print("[+] Slot 1 内核 (/dev/ubi0_3) 烧录成功！")

    # 5. 刷写 Slot 1 RootFS (/dev/ubi0_4)
    print("\n[3/4] 正在传输并刷写 Slot 1 新版 SquashFS 根系统 (/dev/ubi0_4)...")
    push_with_retry(session, r1_path, "/tmp/r1.squashfs", base_port=9970, timeout=180)
    session.run_cmd("umount -f -l /dev/ubi0_4 2>/dev/null || true")
    run_checked_cmd(session, "ubiupdatevol /dev/ubi0_4 /tmp/r1.squashfs && rm -f /tmp/r1.squashfs", "Slot 1 RootFS 烧录", timeout=150)
    print("[+] Slot 1 RootFS (/dev/ubi0_4) 烧录成功！")

    # 6. 配置试启动并重启
    print("\n[4/4] 正在设置试启动标记并重启进入新版 Slot 1...")
    session.run_cmd("echo 90 > /var/app/.unconfirmed")
    session.run_cmd("/bin/nv setenv sw_commit 0")
    session.run_cmd("/bin/nv setenv sw_tryactive 1")
    session.run_cmd("/bin/nv setenv sw_updater")
    session.run_cmd("sync")
    try:
        session.run_cmd("sleep 1 && reboot &")
    except Exception:
        pass
    session.close()

    print("[*] 路由器正在重启进入新版 Slot 1 (约 45 秒)，完成后将自动校验并固化...")
    time.sleep(25)
    session, lan_ip, target_host = wait_for_router("等待新版 Slot 1 系统上线")

    # 7. 校验槽位与 Web，仅在校验通过时才永久固化（否则保留 90s 自动回滚！）
    booted_slot, slot_diag = detect_running_slot(session)
    if booted_slot != 1:
        print(f"[-] 警告: 重启后未进入 Slot 1 (检测结果: {booted_slot})，已中止固化！\n{slot_diag}")
        session.close()
        sys.exit(1)

    time.sleep(3)
    ok, status = verify_http_ok(target_host)
    if ok:
        print(f"[+] Web 控制台校验通过 (http://{target_host}/ -> HTTP {status})！")
    else:
        print(f"[!] Web 初次校验状态: {status}，正在触发 user.sh 并复检...")
        session.run_cmd("sh /var/app/core_system/init.d/user.sh --force")
        time.sleep(2)
        ok, status = verify_http_ok(target_host)
        print(f"[*] 复检结果: ok={ok}, status={status}")

    if not ok:
        print("[-] Web 控制台校验未通过，为保护设备安全，拒绝固化 Slot 1（90 秒看门狗将自动回滚至原厂 Slot 0）！")
        session.close()
        sys.exit(1)

    print("[*] 正在执行 /bin/confirm_keep.sh 永久固化新版 Slot 1...")
    confirm_out = run_checked_cmd(
        session,
        "([ -x /bin/confirm_keep.sh ] && /bin/confirm_keep.sh) || (/bin/nv setenv sw_commit 1 && rm -f /var/app/.unconfirmed)",
        "永久固化 Slot 1",
        timeout=30,
    )
    print(confirm_out)
    session.close()

    print("\n" + "=" * 68)
    print("  🎉🎉🎉 完整固件刷机与固化全部完成！")
    print(f"  👉 管理后台: http://{target_host}/")
    print(f"  👉 SSH 登录: ssh root@{target_host} (密码: system)")
    print("=" * 68)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] 已手动取消。")
        sys.exit(0)
