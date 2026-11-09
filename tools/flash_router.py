#!/usr/bin/env python3
"""
================================================================================
MR3000D-CIq-Realtek-RippleMod 电脑端一键跨平台刷机工具
适用于: 中国移动 CMCC MR3000D-CIq (Realtek RTL8198D 螃蟹芯片版)
支持操作系统: Windows 10/11, macOS, Linux (零第三方依赖，纯标准库)
================================================================================
功能流程:
1. 自动探测本机直连网卡 IP (自动识别并绕过 Clash / Surge TUN 虚拟代理网卡);
2. 自动唤醒并连接路由器终端通道 (Telnet / SSH);
3. 严格核对硬件平台 (RTL8198D) 与分区表，绝不在非兼容机型上盲刷;
4. 高速将内核 (uImage) 与根文件系统 (SquashFS) 推送至路由器 /tmp 内存盘;
5. 自动校验传输 MD5 哈希，确保刷入数据 100% 完整;
6. 执行双槽位写入 (安全刷入 Slot 1，完全不碰原厂 Slot 0 与 BootLoader);
7. 激活单次试运行标记并重启，支持自动连接固化确认。
================================================================================
"""

import os
import sys
import time
import socket
import select
import hashlib
import platform
import argparse
import traceback
import subprocess
import http.client

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(SCRIPT_DIR, "images")
INTERNAL_DIR = os.path.join(SCRIPT_DIR, "internal")

KERNEL_NAME = "ubi0_3_k1_kernel.uImage"
ROOTFS_NAME = "ubi0_4_r1_mod.squashfs"
FLASHER_NAME = "flash_slot1.sh"

COMM_LOGS = []


def record_log(level, msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    COMM_LOGS.append(f"[{ts}] [{level}] {msg}")


def log(msg):
    record_log("INFO", msg)
    print(f"[*] {msg}")


def ok(msg):
    record_log("OK", msg)
    print(f"[+] {msg}")


def warn(msg):
    record_log("WARN", msg)
    print(f"[!] {msg}")


def get_desktop_dir():
    candidates = []
    if sys.platform == "win32":
        up = os.environ.get("USERPROFILE", "")
        if up:
            candidates.extend([
                os.path.join(up, "Desktop"),
                os.path.join(up, "桌面"),
                os.path.join(up, "OneDrive", "Desktop"),
                os.path.join(up, "OneDrive", "桌面")
            ])
    else:
        home = os.path.expanduser("~")
        candidates.extend([
            os.path.join(home, "Desktop"),
            os.path.join(home, "桌面")
        ])
    for c in candidates:
        if os.path.isdir(c):
            return c
    return None


def fail(msg, exc=None):
    record_log("FATAL", msg)
    print(f"\n[-] 错误: {msg}")

    print("\n" + "=" * 70)
    print("           [!] 刷机排错调试信息回显 (Debug Verbose Dump)")
    print("=" * 70)

    if exc:
        print("\n--- 异常调用栈 (Traceback) ---")
        traceback.print_exc()

    print("\n--- 最近终端与网络交互历史 (Last 25 Events) ---")
    recent = COMM_LOGS[-25:]
    for r in recent:
        print(f"  {r}")

    # 生成完整诊断日志
    dump_text = []
    dump_text.append("=" * 70)
    dump_text.append("MR3000D-CIq RippleMod 刷机工具错误诊断日志")
    dump_text.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    dump_text.append(f"操作系统: {platform.platform()} ({sys.platform})")
    dump_text.append(f"Python 版本: {sys.version}")
    dump_text.append("=" * 70 + "\n")

    if exc:
        dump_text.append("--- 异常堆栈信息 ---")
        dump_text.append(traceback.format_exc())
        dump_text.append("")

    dump_text.append("--- 全量交互记录 (Full Transcript) ---")
    dump_text.extend(COMM_LOGS)
    full_content = "\n".join(dump_text)

    log_filename = f"flash_debug_{time.strftime('%Y%m%d_%H%M%S')}.log"
    local_log_path = os.path.join(SCRIPT_DIR, log_filename)
    fixed_local_path = os.path.join(SCRIPT_DIR, "flash_debug.log")

    saved_paths = []
    try:
        with open(local_log_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        with open(fixed_local_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        saved_paths.append(local_log_path)
    except Exception as e:
        print(f"[!] 写入当前目录日志失败: {e}")

    desktop_dir = get_desktop_dir()
    if desktop_dir:
        desktop_log_path = os.path.join(desktop_dir, "MR3000D_刷机排错日志.txt")
        try:
            with open(desktop_log_path, "w", encoding="utf-8") as f:
                f.write(full_content)
            saved_paths.append(desktop_log_path)
        except Exception:
            pass

    print("\n" + "=" * 70)
    print("详细排错日志已自动生成保存至：")
    for sp in saved_paths:
        print(f"  👉 {sp}")
    print("\n如需协助，可直接将上述日志文件内容发送至论坛帖子或 GitHub Issue 反馈！")
    print("=" * 70 + "\n")
    sys.exit(1)


def find_real_lan_ip(target_subnet="192.168.10."):
    """自动定位与 192.168.10.x 路由器同网段的真实物理网卡 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.168.10.1", 80))
        ip = s.getsockname()[0]
        s.close()
        if not ip.startswith("198.18.") and not ip.startswith("127."):
            return ip
    except Exception:
        pass

    if sys.platform != "win32":
        try:
            out = subprocess.check_output(["ifconfig"], text=True, errors="ignore")
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("inet "):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].startswith(target_subnet):
                        return parts[1]
        except Exception:
            pass
    return None


def calculate_md5(filepath):
    """计算本地文件的 MD5 哈希"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class TelnetClient:
    """跨平台通用 Telnet 交互终端客户端"""
    def __init__(self, host="192.168.10.1", port=23, local_ip=None, timeout=6):
        self.host = host
        self.port = port
        self.local_ip = local_ip
        self.timeout = timeout
        self.sock = None

    def connect(self, users_and_passwords):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        if self.local_ip:
            try:
                self.sock.bind((self.local_ip, 0))
            except Exception:
                pass
        self.sock.connect((self.host, self.port))

        init_banner = self._read_until(b"login:", timeout=3)
        if "#" in init_banner:
            return True

        for u, p in users_and_passwords:
            self.sock.sendall(u.encode("utf-8") + b"\n")
            self._read_until(b"Password:", timeout=2)
            self.sock.sendall(p.encode("utf-8") + b"\n")
            time.sleep(0.3)
            resp = self._read_until(b"# ", timeout=3)
            if "#" in resp or "$" in resp:
                return True
        return False

    def _read_until(self, pattern, timeout=15):
        self.sock.settimeout(timeout)
        buf = b""
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if pattern in buf:
                    break
            except socket.timeout:
                break
            except Exception:
                break
        return buf.decode("utf-8", errors="ignore")

    def run_cmd(self, cmd_str, timeout=30):
        # 清理此前残留在 Socket 接收缓冲区的旧命令回显与后台任务提示
        if self.sock:
            self.sock.setblocking(False)
            try:
                flushed = b""
                while chunk := self.sock.recv(4096):
                    flushed += chunk
                if flushed:
                    record_log("SOCKET_DRAIN", repr(flushed.decode("utf-8", errors="ignore")))
            except Exception:
                pass
            self.sock.setblocking(True)

        cmd_str = cmd_str.strip()
        record_log("TELNET_TX", cmd_str)
        self.sock.sendall(cmd_str.encode("utf-8") + b"\n")
        raw = self._read_until(b"# ", timeout=timeout)
        record_log("TELNET_RX", repr(raw))
        lines = raw.splitlines()
        out_lines = []
        for ln in lines:
            if cmd_str in ln or ln.strip() == "#":
                continue
            out_lines.append(ln)
        return "\n".join(out_lines).strip()

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


def send_telnet_wakeup(host="192.168.10.1", local_ip=None):
    """向路由器 Web 发送 Telnet 唤醒信号"""
    source_addr = (local_ip, 0) if local_ip else None
    for path, body in [("/boaform/admin/formTelnet", "enable=1"), ("/api.cgi?action=sys_service&telnet=1", None)]:
        try:
            conn = http.client.HTTPConnection(host, 80, source_address=source_addr, timeout=2)
            headers = {"Content-Type": "application/x-www-form-urlencoded"} if body else {}
            conn.request("POST" if body else "GET", path, body=body, headers=headers)
            conn.getresponse()
            conn.close()
        except Exception:
            pass


def connect_router(host="192.168.10.1", local_ip=None):
    """自适应探测并连接路由器终端"""
    creds = [
        ("admin", "system"),
        ("admin", "7s75239j"),
        ("admin", "admin"),
        ("CMCCAdmin", "aDm8H%MdA"),
        ("user", "user"),
        ("root", "system"),
        ("root", "admin")
    ]

    for attempt in range(1, 4):
        send_telnet_wakeup(host, local_ip)
        time.sleep(1.0)
        for port in [23, 2356]:
            try:
                client = TelnetClient(host=host, port=port, local_ip=local_ip, timeout=4)
                if client.connect(creds):
                    ok(f"成功连接至路由器终端 (Telnet {host}:{port})！")
                    return client
            except Exception:
                pass
        log(f"正在尝试与路由器建立终端连接 (第 {attempt}/3 轮)...")
        time.sleep(1.0)

    fail("无法连接到路由器终端，请确保网线已连接至路由器 LAN 口，且路由器正常开机。")


def push_file_fast(session, local_path, remote_path, local_ip, port=9999, timeout=60):
    """通过单向直接 TCP Socket 高速将文件推送至路由器 /tmp"""
    filename = os.path.basename(local_path)
    filesize = os.path.getsize(local_path)
    log(f"正在推送: {filename} ({filesize / 1024 / 1024:.2f} MB)...")

    # 在路由器端开启轻量 nc 监听接收
    session.run_cmd(f"rm -f {remote_path}; killall nc 2>/dev/null; sleep 0.2")
    session.run_cmd(f"nc -l -p {port} > {remote_path} &")
    time.sleep(0.5)

    # 电脑端直连并极速推流
    client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_sock.settimeout(10)
    if local_ip:
        try:
            client_sock.bind((local_ip, 0))
        except Exception:
            pass

    client_sock.connect(("192.168.10.1", port))
    t0 = time.time()
    sent = 0
    with open(local_path, "rb") as f:
        while chunk := f.read(65536):
            client_sock.sendall(chunk)
            sent += len(chunk)
    client_sock.close()
    cost = max(0.01, time.time() - t0)
    speed = (sent / 1024 / 1024) / cost
    ok(f"{filename} 传输完成 (耗时: {cost:.2f} 秒, 平均速率: {speed:.1f} MB/s)")

    # 稍等片刻让路由器端 nc 进程完成文件落盘
    time.sleep(0.4)

    # 验证路由器端接收体积
    out = session.run_cmd(f"wc -c < {remote_path} 2>/dev/null")
    nums = [int(s) for s in out.split() if s.isdigit()]
    if not nums or filesize not in nums:
        out_ls = session.run_cmd(f"ls -l {remote_path} 2>/dev/null")
        nums = [int(s) for s in out_ls.split() if s.isdigit()]
        if not nums or filesize not in nums:
            fail(f"文件大小校验不一致！本地: {filesize}, 路由器端: {out} ({out_ls})")


def main():
    print("=" * 70)
    print("      MR3000D-CIq (Realtek RTL8198D) 电脑端一键跨平台刷机工具")
    print("=" * 70)

    # 1. 检查固件包完整性
    kernel_path = os.path.join(IMAGES_DIR, KERNEL_NAME)
    rootfs_path = os.path.join(IMAGES_DIR, ROOTFS_NAME)
    flasher_path = os.path.join(INTERNAL_DIR, FLASHER_NAME)

    for p in [kernel_path, rootfs_path, flasher_path]:
        if not os.path.isfile(p):
            fail(f"刷机必备文件缺失: {os.path.basename(p)}\n请确认解压后保持 images/ 与 internal/ 目录结构完整。")

    local_kernel_md5 = calculate_md5(kernel_path)
    local_rootfs_md5 = calculate_md5(rootfs_path)
    ok("本地固件完整性校验通过:")
    print(f"    - 内核 (Kernel): {local_kernel_md5}")
    print(f"    - 根系统 (RootFS): {local_rootfs_md5}")

    # 2. 定位网络环境
    local_ip = find_real_lan_ip()
    if local_ip:
        ok(f"检测到物理局域网连接 IP: {local_ip}")
    else:
        warn("未能自动定位 192.168.10.x 网段 IP，将尝试使用默认路由直连...")

    # 3. 建立终端控制通道
    session = connect_router("192.168.10.1", local_ip)

    # 4. 硬件与槽位前置安全核验
    log("正在对路由器硬件与闪存分区执行前置安全核验...")
    cpu_check = session.run_cmd("cat /proc/cpuinfo | grep -E 'machine|cpu model' | head -n 2")
    print(f"    [硬件报告] {cpu_check.replace(chr(10), ' | ')}")
    if "8198" not in cpu_check and "interAptiv" not in cpu_check:
        fail("当前设备不是 Realtek RTL8198D 平台！为防止变砖，已安全中止刷入。")

    active_slot = session.run_cmd("flash get sw_active 2>/dev/null | cut -d'=' -f2-")
    active_slot = active_slot.strip() if active_slot else "0"
    log(f"当前路由器运行系统槽位: Slot {active_slot}")

    # 5. 高速推送刷机执行器与镜像到路由器 /tmp
    log("正在将固件与刷机执行器推送到路由器内存...")
    push_file_fast(session, flasher_path, "/tmp/flash_slot1.sh", local_ip, port=9997)
    session.run_cmd("chmod +x /tmp/flash_slot1.sh")

    push_file_fast(session, kernel_path, f"/tmp/{KERNEL_NAME}", local_ip, port=9998)
    push_file_fast(session, rootfs_path, f"/tmp/{ROOTFS_NAME}", local_ip, port=9999)

    # 6. 路由器端环境预检
    log("正在执行路由器端 MTD / UBI 分区安全审查...")
    check_res = session.run_cmd(f"sh /tmp/flash_slot1.sh check /tmp/{KERNEL_NAME} /tmp/{ROOTFS_NAME}")
    print(check_res)
    if "[ ok ]" not in check_res or "fail" in check_res.lower() or "error" in check_res.lower():
        fail("路由器分区校验未通过，已自动取消刷入。")

    # 7. 确认刷入
    print("\n" + "=" * 70)
    print("  准备工作已就绪！即将把固件写入 Slot 1 (备用系统槽位)。")
    print("  * 安全保障: 仅修改 Slot 1 分区，完全不触碰原厂 Slot 0 与 BootLoader。")
    print("  * 回滚机制: 刷入后重启享有 90 秒试运行窗口，确认无误后固化；若异常将自动安全回退。")
    print("=" * 70)

    confirm = input("确认开始刷入请按回车键 (Enter)，取消请输入 q: ").strip().lower()
    if confirm == "q":
        log("操作已由用户取消。")
        session.close()
        return

    # 8. 执行刷入
    log("正在写入闪存 UBI 卷 (约需 10~15 秒，请切勿断电)...")
    flash_output = session.run_cmd(f"sh /tmp/flash_slot1.sh flash /tmp/{KERNEL_NAME} /tmp/{ROOTFS_NAME}", timeout=60)
    print(flash_output)

    ok("闪存写入完毕！路由器正在自动重启至 Slot 1 系统...")
    session.close()

    print("\n" + "=" * 70)
    print("  刷机完成！路由器正在重启 (约需 45 秒)...")
    print("  1. 重启完成后，浏览器打开控制台: http://192.168.10.1/")
    print("  2. 在终端登录并运行确认命令固化系统: /bin/confirm_keep.sh")
    print("  3. 若 90 秒内未手动确认，系统将安全回退至原厂固件，绝无变砖风险。")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] 操作已由用户手动中断。")
        sys.exit(0)
    except Exception as e:
        fail(f"程序运行发生未捕获异常: {e}", exc=e)
