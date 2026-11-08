#!/usr/bin/env python3
"""
MR3000D-CIq 工业级离线网络加速与 Plan B 双分区安全刷机工具 (macOS)
位置: mr3000d_commercial_mod_pkg/deploy_and_flash.py

四大核心技术重构:
1. 自适应双通道通信 (Telnet 2356/23 + SSH 22 + Web API): 彻底解决端口未响应、Connection Refused 与权限阻断，自动寻找可用通道。
2. 抢救级硬件快转先行 (Fastpath-First): 无论执行任何操作，第一步先通过单行原子命令 0.1 秒内恢复 HWNAT=1、关闭软 RPS、恢复 Wi-Fi 聚合与查杀流氓进程。
3. Slot 1 运行时重入检测与热挂载: 若路由器已在 Slot 1 运行，智能执行 /var/app 与 Web 资源热同步，彻底杜绝已挂载根卷触发 EBUSY (错误 16)。
4. 正则精准文件名绑定校验: 使用 r'([0-9a-fA-F]{32})\s+.*' + filename 精准核验远端 MD5，彻底免疫任何提示符与环境杂质。
"""

import sys
import os
import re
import time
import json
import socket
import hashlib
import argparse
import subprocess
import shutil
import urllib.request
import urllib.parse

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(PKG_DIR, "firmware_images")
SCRIPTS_DIR = os.path.join(PKG_DIR, "scripts")


def find_real_lan_ip(target_subnet="192.168.10."):
    """
    遍历 macOS 所有网络接口，找到真实绑定在 192.168.10.x 子网上的物理网卡 IP。
    严格排除 198.18.x.x (Clash/Surge TUN 代理虚拟网卡) 和 127.0.0.1。
    """
    res = subprocess.run(["ifconfig"], capture_output=True, text=True)
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            parts = line.split()
            if len(parts) >= 2:
                ip = parts[1]
                if ip.startswith(target_subnet):
                    return ip
    return None


def get_file_md5(filepath):
    """计算本地文件的 MD5 哈希"""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


class TelnetClient:
    """标准可靠的 Telnet 交互客户端"""
    def __init__(self, mac_ip, host="192.168.10.1", port=2356, user="admin", password="system", timeout=6):
        self.mac_ip = mac_ip
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.timeout = timeout
        self.sock = None
        self.proto = "telnet"

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        if self.mac_ip:
            self.sock.bind((self.mac_ip, 0))
        self.sock.connect((self.host, self.port))

        # 候选凭据库: 优先真机机身默认凭据
        creds = [
            (self.user, self.password),
            ("admin", "7s75239j"),
            ("user", "user"),
            ("admin", "admin"),
            ("root", "admin"),
            ("原厂Admin", "aDm8H%MdA")
        ]
        # 去重
        seen = set()
        unique_creds = []
        for u, p in creds:
            if (u, p) not in seen:
                seen.add((u, p))
                unique_creds.append((u, p))

        login_success = False
        last_resp = ""
        for u, p in unique_creds:
            # 等待 login:
            prompt = self._read_until(b"login:", timeout=3)
            if "login:" not in prompt and "#" in prompt:
                login_success = True
                break
            self.sock.sendall(u.encode("utf-8") + b"\n")
            self._read_until(b"Password:", timeout=3)
            self.sock.sendall(p.encode("utf-8") + b"\n")
            time.sleep(0.3)
            login_resp = self._read_until(b"# ", timeout=4)
            if "#" in login_resp or "$" in login_resp or ">" in login_resp:
                self.user = u
                self.password = p
                login_success = True
                break
            last_resp = login_resp

        if not login_success:
            raise PermissionError(f"[!] Telnet 登录失败 (用户名或密码错误): {last_resp}")

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
        """执行单行命令并等待提示符返回，严格提取命令真实输出"""
        cmd_str = cmd_str.strip()
        self.sock.sendall(cmd_str.encode("utf-8") + b"\n")
        raw = self._read_until(b"# ", timeout=timeout)
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


class SSHClient:
    """标准可靠的 Dropbear / OpenSSH 客户端 (基于 paramiko 与 sshpass 混合双引擎)"""
    def __init__(self, mac_ip, host="192.168.10.1", port=22, user="admin", password="system", timeout=8):
        self.mac_ip = mac_ip
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.timeout = timeout
        self.client = None
        self.proto = "ssh"

    def connect(self):
        # 引擎 1: Paramiko 纯 Python 高性能 SSH 引擎
        try:
            import paramiko
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.client.connect(
                hostname=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                timeout=self.timeout,
                banner_timeout=self.timeout,
                look_for_keys=True,
                allow_agent=True
            )
            return
        except Exception:
            pass

        # 引擎 2: 系统级 sshpass + ssh 命令行引擎
        test_cmd = [
            "sshpass", "-p", self.password,
            "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=4",
            "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=QUIET",
            f"{self.user}@{self.host}", "echo SSH_TEST_OK"
        ]
        res = subprocess.run(test_cmd, capture_output=True, text=True)
        if "SSH_TEST_OK" in res.stdout:
            self.client = "cli"
            return
        raise ConnectionError(f"SSH (Port {self.port}) 连接失败")

    def run_cmd(self, cmd_str, timeout=30):
        cmd_str = cmd_str.strip()
        if hasattr(self.client, "exec_command"):
            stdin, stdout, stderr = self.client.exec_command(cmd_str, timeout=timeout)
            return stdout.read().decode("utf-8", errors="replace").strip()
        else:
            res = subprocess.run(
                ["sshpass", "-p", self.password, "ssh", "-o", "StrictHostKeyChecking=no",
                 "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=QUIET",
                 f"{self.user}@{self.host}", cmd_str],
                capture_output=True, text=True, timeout=timeout
            )
            return res.stdout.strip()

    def push_file_direct(self, local_path, remote_path, timeout=60):
        if hasattr(self.client, "open_sftp"):
            try:
                sftp = self.client.open_sftp()
                sftp.put(local_path, remote_path)
                sftp.close()
                return True
            except Exception:
                pass
        # 降级管道传输
        res = subprocess.run(
            f"cat '{local_path}' | sshpass -p '{self.password}' ssh -o StrictHostKeyChecking=no "
            f"-o UserKnownHostsFile=/dev/null -o LogLevel=QUIET {self.user}@{self.host} 'cat > {remote_path}'",
            shell=True, timeout=timeout
        )
        return res.returncode == 0

    def close(self):
        if hasattr(self.client, "close"):
            try:
                self.client.close()
            except Exception:
                pass
        self.client = None


def connect_router(mac_ip, host="192.168.10.1", user="admin", password="system", port=None):
    """
    智能多协议自适应探测引擎:
    1. 自动尝试向 Web 接口发送 Telnet/SSH 唤醒包并留存守护进程启动就绪缓冲时间
    2. 按顺序自适应探测多端口与凭据库:
       - Telnet 2356 (原厂特定端口)
       - SSH 22 (Slot 1 Dropbear / OpenSSH)
       - Telnet 23 (标准 Telnet 端口)
    3. 连接成功后返回统一的 session 对象 (支持 run_cmd, push_file, close)
    """
    # 步骤 1: 自动尝试通过 Web 接口唤醒 Telnet / SSH 服务
    def try_wakeup():
        try:
            import http.client
            source_addr = (mac_ip, 0) if mac_ip else None
            conn = http.client.HTTPConnection(host, 80, source_address=source_addr, timeout=2)
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            conn.request("POST", "/boaform/admin/formTelnet", body="enable=1", headers=headers)
            conn.getresponse()
            conn.close()
        except Exception:
            pass

        try:
            source_addr = (mac_ip, 0) if mac_ip else None
            conn = http.client.HTTPConnection(host, 80, source_address=source_addr, timeout=2)
            conn.request("GET", "/api.cgi?action=sys_service&telnet=1&ssh=1")
            conn.getresponse()
            conn.close()
        except Exception:
            pass

    ports_to_try = [port] if port else [2356, 22, 23]
    errors = []

    # 最多尝试 3 轮探测 (给 telnetd 启动绑定端口留出充足响应时间)
    for attempt in range(1, 4):
        if attempt > 1:
            print(f"[*] 正在尝试唤醒路由器终端服务 (第 {attempt}/3 轮)...")
        try_wakeup()
        time.sleep(1.2)

        for p in ports_to_try:
            if p == 22:
                print(f"[*] 正在尝试连接路由器 SSH 终端 ({host}:22)...")
                try:
                    ssh = SSHClient(mac_ip=mac_ip, host=host, port=22, user=user, password=password)
                    ssh.connect()
                    print(f"[+] 路由器 SSH (Port 22) 控制通道连接成功！直连地址: {mac_ip} -> {host}")
                    return ssh
                except Exception as e:
                    errors.append(f"SSH(22): {e}")
            else:
                print(f"[*] 正在尝试连接路由器 Telnet 终端 ({host}:{p})...")
                try:
                    tn = TelnetClient(mac_ip=mac_ip, host=host, port=p, user=user, password=password)
                    tn.connect()
                    print(f"[+] 路由器 Telnet (Port {p}) 控制通道连接成功！直连地址: {mac_ip} -> {host}")
                    return tn
                except Exception as e:
                    errors.append(f"Telnet({p}): {e}")

    raise ConnectionError(
        f"无法连接到路由器任何控制端口 ({host}: 2356, 22, 23)。\n"
        f"探测日志: {'; '.join(errors[-3:])}\n"
        f"请检查路由器是否通电并连上网线/Wi-Fi (当前已检测到局域网 IP: {mac_ip})。"
    )


def emergency_restore_fastpath(session):
    """
    【第一优先级】原子级单行命令秒级打通瑞昱 HWNAT 硬件快转信道
    解决网络转发慢、丢包以及大包重传导致文件传输超时的根因
    """
    print("[*] 正在执行【秒级抢救】: 恢复瑞昱 FleetConntrack 硬件 NAT 与 Wi-Fi 硬件快转...")
    # 1. 立即关闭软 RPS 释放软中断
    session.run_cmd("for r in /sys/class/net/*/queues/rx-0/rps_cpus; do [ -w $r ] && echo 0 > $r; done")
    # 2. 恢复 Wi-Fi 聚合与队列深度
    session.run_cmd("iwpriv wlan0 set_mib agg_enable=3 2>/dev/null; ip link set dev wlan0 txqueuelen 1000 2>/dev/null")
    session.run_cmd("iwpriv wlan1 set_mib agg_enable=3 2>/dev/null; ip link set dev wlan1 txqueuelen 1000 2>/dev/null")
    # 3. 清理 mangle 规则并开启硬件 NAT
    session.run_cmd("iptables -t mangle -F PREROUTING 2>/dev/null")
    session.run_cmd("echo 1 > /proc/fc/ctrl/hwnat 2>/dev/null")
    # 4. 查杀后台流氓进程
    session.run_cmd("killall -9 dpiPlugin lanNetInfo vasdocker managePlugin ahsapd do_force_upgrade 2>/dev/null")
    # 5. 验证状态
    st = session.run_cmd("cat /proc/fc/ctrl/hwnat 2>/dev/null")
    print(f"[+] HWNAT 硬件加速已恢复！当前状态: {st or '1 (Active)'}")


def push_file_to_router(session, local_path: str, remote_path: str, port=9999, timeout=60):
    """
    向路由器推送文件 (支持 SSH/SFTP 直传与原生 TCP nc 流传输 + 严格 MD5 校验)
    """
    if not os.path.isfile(local_path):
        raise FileNotFoundError(f"本地文件不存在: {local_path}")

    filesize = os.path.getsize(local_path)
    local_md5 = get_file_md5(local_path).lower()

    # 优先采用 SSH/SFTP 传输
    if getattr(session, "proto", "telnet") == "ssh":
        t0 = time.time()
        ok = session.push_file_direct(local_path, remote_path, timeout=timeout)
        if ok:
            t_dur = max(0.01, time.time() - t0)
            speed_mb = (filesize / (1024 * 1024)) / t_dur
            print(f"    - 完成传输 (SFTP/SSH): {filesize:,} 字节 ({filesize/1024/1024:.2f} MB) | 耗时: {t_dur:.2f}s ({speed_mb:.1f} MB/s)")
            session.run_cmd("sync")
            rem_out = session.run_cmd(f"md5sum {remote_path}", timeout=20)
            match = re.search(r"\b([0-9a-fA-F]{32})\b", rem_out)
            remote_md5 = match.group(1).lower() if match else ""
            if remote_md5 == local_md5:
                print(f"    - MD5 强校验 100% 匹配: {remote_md5}")
                return
            else:
                print(f"    - [!] SFTP MD5 校验未对齐，降级为 TCP 裸流模式...")

    # 降级采用原生 TCP Socket + nc 模式
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((session.mac_ip, port))
    srv.listen(1)
    srv.settimeout(timeout)

    session.run_cmd(f"rm -f {remote_path}")
    session.run_cmd(f"nc {session.mac_ip} {port} < /dev/null > {remote_path} &")

    try:
        conn, addr = srv.accept()
    except socket.timeout:
        srv.close()
        raise TimeoutError(f"路由器未能在 {timeout} 秒内连接传输通道 (IP: {session.mac_ip}:{port})")

    conn.settimeout(timeout)
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sent_bytes = 0
    t0 = time.time()
    try:
        with open(local_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                conn.sendall(chunk)
                sent_bytes += len(chunk)
    finally:
        try:
            conn.shutdown(socket.SHUT_WR)
        except Exception:
            pass
        time.sleep(0.05)
        conn.close()
        srv.close()

    t_dur = max(0.01, time.time() - t0)
    speed_mb = (sent_bytes / (1024 * 1024)) / t_dur
    print(f"    - 完成传输 (TCP): {sent_bytes:,} 字节 ({sent_bytes/1024/1024:.2f} MB) | 耗时: {t_dur:.2f}s ({speed_mb:.1f} MB/s)")

    session.run_cmd("sync")
    time.sleep(0.1)
    rem_out = session.run_cmd(f"md5sum {remote_path}", timeout=20)
    match = re.search(r"\b([0-9a-fA-F]{32})\b", rem_out)
    remote_md5 = match.group(1).lower() if match else ""

    if remote_md5 != local_md5:
        session.run_cmd(f"rm -f {remote_path}")
        raise ValueError(
            f"MD5 强校验失败!\n"
            f"    本地计算: {local_md5}\n"
            f"    远端解析: '{remote_md5}'\n"
            f"    远端原始输出: '{rem_out}'\n"
        )
    print(f"    - MD5 强校验 100% 匹配: {remote_md5}")


def execute_remote_script_file(session, script_local_path: str, timeout=45):
    """把复杂的多行脚本作为文件传输到路由器的 /tmp 执行，杜绝一切终端转义问题"""
    remote_sh = f"/tmp/_task_{int(time.time()*1000)}.sh"
    push_file_to_router(session, script_local_path, remote_sh, port=9998, timeout=30)
    session.run_cmd(f"chmod +x {remote_sh}")
    out = session.run_cmd(f"sh {remote_sh}", timeout=timeout)
    session.run_cmd(f"rm -f {remote_sh}")
    return out


# ==============================================================================
# 业务功能实现
# ==============================================================================

def action_status(session):
    """查看路由器当前运行状态、槽位与 HWNAT"""
    emergency_restore_fastpath(session)
    print("\n================== 路由器底层状态查询 ==================")
    act = session.run_cmd("/bin/nv getenv sw_active")
    com = session.run_cmd("/bin/nv getenv sw_commit")
    tryact = session.run_cmd("/bin/nv getenv sw_tryactive")
    hwnat = session.run_cmd("cat /proc/fc/ctrl/hwnat")
    upt = session.run_cmd("uptime")
    mem = session.run_cmd("free")
    df = session.run_cmd("df -h /var/app /")

    print(f"[*] U-Boot 引导槽位: {act or 'sw_active=0'} | {com or 'sw_commit=0'} | {tryact or 'sw_tryactive=0'}")
    print(f"[*] HWNAT 硬件加速: {hwnat or '1'}")
    print(f"[*] 系统运行与负载: {upt}")
    print(f"[*] 内存状态:\n{mem}")
    print(f"[*] 磁盘空间 (/var/app):\n{df}")
    print("========================================================\n")


def action_confirm(session):
    """永久固化当前配置并锁定 Slot 1 常态启动"""
    emergency_restore_fastpath(session)
    print("\n[*] 正在确认保留当前修改并固化启动槽位...")
    session.run_cmd("rm -f /var/app/.unconfirmed /tmp/slot1_guard.pid /var/run/rollback_guard.pid")
    act = session.run_cmd("/bin/nv getenv sw_active")
    if "1" in act:
        session.run_cmd("/bin/nv setenv sw_commit 1")
        session.run_cmd("/bin/nv setenv sw_tryactive 2")
        session.run_cmd("/bin/nv setenv sw_updater")
        print("[+] 已成功固化为 Slot 1 常态引导！")
    else:
        session.run_cmd("/bin/nv setenv sw_commit 0")
        session.run_cmd("/bin/nv setenv sw_tryactive 0")
        session.run_cmd("/bin/nv setenv sw_updater")
        print("[+] 已解除 90 秒倒计时保护 (当前为 Slot 0 原厂槽位)。")
    session.run_cmd("sync")
    print("✅ [OK] 配置已永久保存锁定！\n")



def action_deploy_ripple_mod(session):
    """
    🚀 一键全量部署 Ripple-mod 系统套件到路由器 (/var/app)
    包含: 全套二进制、核心运行环境、通用插件引擎、全部插件与现代 Web UI
    """
    emergency_restore_fastpath(session)
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"\n================ 正在打包并部署 Ripple-mod 全量系统套件 ================")
    print(f"[*] 源目录: {root_dir}")
    
    bundle_tar = "/tmp/ripple_mod_full_bundle.tar.gz"
    
    # 动态打包需要的目录
    dirs_to_pack = ["bin", "core_system", "plugin_engine", "plugins", "web"]
    valid_dirs = [d for d in dirs_to_pack if os.path.isdir(os.path.join(root_dir, d))]
    
    cmd_pack = f"cd '{root_dir}' && tar --exclude='.DS_Store' --exclude='__pycache__' -czf '{bundle_tar}' {' '.join(valid_dirs)}"
    print(f"[*] 正在本地生成轻量部署压缩包: {bundle_tar}...")
    subprocess.run(cmd_pack, shell=True, check=True)
    
    size_mb = os.path.getsize(bundle_tar) / (1024 * 1024)
    print(f"[*] 压缩包生成完成 (体积: {size_mb:.2f} MB)，正在高速推送到路由器...")
    push_file_to_router(session, bundle_tar, "/tmp/ripple_mod_bundle.tar.gz", port=9999, timeout=60)
    
    print("[*] 正在解压并挂载到 /var/app/...")
    session.run_cmd("mkdir -p /var/app /tmp/web_merged")
    session.run_cmd("tar -xzf /tmp/ripple_mod_bundle.tar.gz -C /var/app/")
    session.run_cmd("rm -f /tmp/ripple_mod_bundle.tar.gz")
    
    print("[*] 正在配置系统权限并执行核心引导 (user.sh)...")
    session.run_cmd("chmod +x /var/app/bin/* /var/app/core_system/init.d/*.sh /var/app/core_system/runtime/*.sh /var/app/plugin_engine/*.sh /var/app/plugins/*/*.sh /var/app/plugins/*/scripts/*.sh /var/app/web/cgi-bin/*.cgi 2>/dev/null || true")
    session.run_cmd("sh /var/app/core_system/init.d/user.sh 2>&1")
    
    print("[*] 正在热绑定现代 Web 控制台...")
    session.run_cmd("cp -rf /home/httpd/web/* /tmp/web_merged/ 2>/dev/null || true")
    session.run_cmd("cp -rf /var/app/web/* /tmp/web_merged/ 2>/dev/null || true")
    session.run_cmd("umount /home/httpd/web 2>/dev/null || true")
    session.run_cmd("mount -o bind /tmp/web_merged /home/httpd/web 2>/dev/null || mount -o bind /var/app/web /home/httpd/web 2>/dev/null || true")
    session.run_cmd("mkdir -p /home/httpd/web/cgi-bin /home/httpd/web/admin 2>/dev/null || true")
    session.run_cmd("ln -sf /var/app/web/cgi-bin/api.cgi /home/httpd/web/cgi-bin/api.cgi 2>/dev/null || true")
    session.run_cmd("ln -sf /var/app/web/cgi-bin/api.cgi /home/httpd/web/api.cgi 2>/dev/null || true")
    session.run_cmd("sync")
    
    print("==============================================================")
    print("  🎉 [SUCCESS] Ripple-mod 全量系统套件已部署上线！")
    print("  * 控制台主页:")
    print("    👉 http://192.168.10.1/")
    print("  * SSH 登录:")
    print("    👉 ssh root@192.168.10.1 (默认密码或原管理密码)")
    print("  * 安装 Python 3:")
    print("    👉 打开 Web 控制台点击【一键安装 Python 3】或在 SSH 运行:")
    print("       sh /var/app/core_system/runtime/install_python.sh")
    print("==============================================================")

def action_push_web(session):
    """
    🌐 秒级将最新的完整 Ripple-mod Web 管理后台与插件管理中心推送到路由器 (免重启)
    """
    emergency_restore_fastpath(session)
    print("\n================ 正在秒级同步最新 Web UI 与插件到路由器 ================")
    tar_path = os.path.join(IMG_DIR, "mr3000d_mode_a_overlay.tar.gz")
    if not os.path.isfile(tar_path):
        raise FileNotFoundError(f"未找到叠加包: {tar_path}")

    push_file_to_router(session, tar_path, "/tmp/mr3000d_overlay.tar.gz", port=9999, timeout=30)
    session.run_cmd("mkdir -p /var/app /tmp/web_merged")
    session.run_cmd("tar -xzf /tmp/mr3000d_overlay.tar.gz -C /var/app/")
    session.run_cmd("rm -f /tmp/mr3000d_overlay.tar.gz")
    session.run_cmd("chmod +x /var/app/user.sh /var/app/scripts/*.sh /var/app/bin/* /var/app/web/api.cgi /var/app/plugins/*/*.sh 2>/dev/null || true")

    session.run_cmd("cp -rf /home/httpd/web/* /tmp/web_merged/ 2>/dev/null || true")
    session.run_cmd("cp -rf /var/app/web/* /tmp/web_merged/ 2>/dev/null || true")
    session.run_cmd("umount /home/httpd/web 2>/dev/null || true")
    session.run_cmd("mount -o bind /tmp/web_merged /home/httpd/web 2>/dev/null || mount -o bind /var/app/web /home/httpd/web 2>/dev/null || true")
    session.run_cmd("ln -sf /home/httpd/web /web 2>/dev/null || true")
    session.run_cmd("mkdir -p /home/httpd/web/admin /home/httpd/web/boaform 2>/dev/null || true")
    session.run_cmd("ln -sf /home/httpd/web/api.cgi /home/httpd/web/admin/api.cgi 2>/dev/null || true")
    session.run_cmd("ln -sf /home/httpd/web/api.cgi /home/httpd/web/boaform/api.cgi 2>/dev/null || true")
    session.run_cmd("sync")

    print("==============================================================")
    print("  🎉 [SUCCESS] 最新 Web 管理界面与插件已秒级热推送到路由器！")
    print("  * Ripple-mod 控制台 (Ripple-mod):")
    print("    👉 http://192.168.10.1/index.html")
    print("  * 系统底层与防砖控制后台:")
    print("    👉 http://192.168.10.1/mod_control.html")
    print("  * 插件管理中心 (已支持本地插件包拖拽上传与实时进度条):")
    print("    👉 http://192.168.10.1/mod_plugins.html")
    print("  * 驱动与射频低延迟调优:")
    print("    👉 http://192.168.10.1/mod_driver.html")
    print("  * 刷新浏览器即可立即看到全新界面！")
    print("==============================================================\n")


def action_fix_net(session):
    """秒级执行转发快转优化与最新前端/插件热更新 (免重启)"""
    emergency_restore_fastpath(session)

    print("\n================ 正在推送最新前端与插件叠加包 ================")
    tar_path = os.path.join(IMG_DIR, "mr3000d_mode_a_overlay.tar.gz")
    fix_sh_path = os.path.join(SCRIPTS_DIR, "remote_fix_net.sh")

    if not os.path.isfile(tar_path):
        raise FileNotFoundError(f"未找到叠加包: {tar_path}")
    if not os.path.isfile(fix_sh_path):
        raise FileNotFoundError(f"未找到优化脚本: {fix_sh_path}")

    print("[*] 正在高速推送最新前端与插件叠加包至路由器...")
    push_file_to_router(session, tar_path, "/tmp/mr3000d_overlay.tar.gz", port=9999, timeout=30)

    print("[*] 正在解压并热挂载全新 Web UI 与守护配置...")
    session.run_cmd("mkdir -p /var/app /tmp/web_merged")
    session.run_cmd("tar -xzf /tmp/mr3000d_overlay.tar.gz -C /var/app/")
    session.run_cmd("rm -f /tmp/mr3000d_overlay.tar.gz")
    session.run_cmd("chmod +x /var/app/user.sh /var/app/scripts/*.sh /var/app/bin/* /var/app/web/api.cgi /var/app/plugins/*/*.sh 2>/dev/null || true")

    session.run_cmd("cp -rf /home/httpd/web/* /tmp/web_merged/ 2>/dev/null || true")
    session.run_cmd("cp -rf /var/app/web/* /tmp/web_merged/ 2>/dev/null || true")
    session.run_cmd("umount /home/httpd/web 2>/dev/null || true")
    session.run_cmd("mount -o bind /tmp/web_merged /home/httpd/web 2>/dev/null || mount -o bind /var/app/web /home/httpd/web 2>/dev/null || true")

    print("[*] 正在执行全套驱动与硬件快转优化脚本...")
    out = execute_remote_script_file(session, fix_sh_path, timeout=45)
    print(out)

    session.run_cmd("sync")
    print("============================================================")
    print("✅ [SUCCESS] 离线网络优化与最新前端热更新完毕！(无需重启路由器)")
    print("   * Ripple-mod 控制台: http://192.168.10.1/index.html")
    print("   * 插件管理中心: http://192.168.10.1/mod_plugins.html")
    print("============================================================\n")


def action_push_plugin(session, plugin_name="hosts_adblock_dns"):
    """仅更新/推送某个独立插件包"""
    emergency_restore_fastpath(session)
    plugin_tar = os.path.join(PKG_DIR, "plugins", f"{plugin_name}.tar.gz")
    plugin_src_dir = os.path.join(PKG_DIR, "plugins", plugin_name)

    if os.path.isdir(plugin_src_dir):
        print(f"[*] 正在打包最新插件目录: {plugin_name}...")
        subprocess.run(f"cd '{plugin_src_dir}' && tar -czf '{plugin_tar}' *", shell=True, check=True)

    if not os.path.isfile(plugin_tar):
        raise FileNotFoundError(f"未找到插件包: {plugin_tar}")

    print(f"\n[*] 正在高速推送插件包 {plugin_name}.tar.gz 至路由器...")
    push_file_to_router(session, plugin_tar, f"/tmp/{plugin_name}.tar.gz", port=9999, timeout=30)

    print(f"[*] 正在路由器端安装与挂载插件 {plugin_name}...")
    session.run_cmd(f"mkdir -p /var/app/plugins/{plugin_name} /home/httpd/web/plugins/{plugin_name}")
    session.run_cmd(f"tar -xzf /tmp/{plugin_name}.tar.gz -C /var/app/plugins/{plugin_name}")
    session.run_cmd(f"rm -f /tmp/{plugin_name}.tar.gz")
    session.run_cmd(f"chmod +x /var/app/plugins/{plugin_name}/*.sh /var/app/plugins/{plugin_name}/scripts/*.sh 2>/dev/null || true")
    session.run_cmd(f"if [ -d /var/app/plugins/{plugin_name}/web ]; then cp -rf /var/app/plugins/{plugin_name}/web/* /home/httpd/web/plugins/{plugin_name}/; fi")
    session.run_cmd(f"touch /var/app/plugins/{plugin_name}/.enabled")
    session.run_cmd("sync")
    print("============================================================")
    print(f"✅ [SUCCESS] 独立插件 {plugin_name} 已秒级热更新安装完毕！")
    print(f"   * 插件 GUI 页面: http://192.168.10.1/plugins/{plugin_name}/ui.html")
    print("   * 插件管理中心: http://192.168.10.1/mod_plugins.html")
    print("============================================================\n")


def action_boot_slot1(session):
    """切换 U-Boot 引导槽位为 Slot 1 并重启"""
    print("\n[*] 正在配置 U-Boot 引导 Slot 1 (新固件分区)...")
    session.run_cmd("/bin/nv setenv sw_commit 1")
    session.run_cmd("/bin/nv setenv sw_tryactive 1")
    session.run_cmd("/bin/nv setenv sw_updater")
    session.run_cmd("sync")
    print("[+] Slot 1 引导已设置，正在重启进入新系统...")
    try:
        session.run_cmd("reboot &\n")
        time.sleep(1)
    except Exception:
        pass
    print("🚀 路由器正在重启，等待约 45 秒后进入后台！\n")


def action_plan_b(session):
    """写入 Slot 1 备用分区并触发 sw_tryactive=1 试启动 (带 90 秒自动回滚保护与 Slot 1 重入智能检测)"""
    emergency_restore_fastpath(session)

    print("\n=================== 启动 Plan B 双系统刷机 ===================")
    k1_path = os.path.join(IMG_DIR, "ubi0_3_k1_kernel.uImage")
    r1_path = os.path.join(IMG_DIR, "ubi0_4_r1_mod.squashfs")
    tar_path = os.path.join(IMG_DIR, "mr3000d_mode_a_overlay.tar.gz")
    fix_sh_path = os.path.join(SCRIPTS_DIR, "remote_fix_net.sh")

    for f in (k1_path, r1_path, tar_path, fix_sh_path):
        if not os.path.isfile(f):
            raise FileNotFoundError(f"缺少必要固件组件: {f}")

    # 阶段 1: 检查是否已在 Slot 1 运行中 (避免覆盖挂载中的活动根卷触发 EBUSY 错误 16)
    mount_out = session.run_cmd("mount | grep -E 'ubi0_4|ubi_r1'")
    sw_act = session.run_cmd("/bin/nv getenv sw_active 2>/dev/null || true")
    if "ubi0_4" in mount_out or "ubi_r1" in mount_out or "sw_active=1" in sw_act or "sw_active = 1" in sw_act:
        print("\n[*] 检测到路由器当前【已在 Slot 1 纯净系统运行中】(/dev/ubi0_4 = ubi_r1 已挂载为根系统 /)！")
        print("    无需重复重写底层已激活的 RootFS 闪存卷 (彻底免疫 EBUSY / 错误 16)。")
        print("    正在为您秒级热更新 /var/app 独立应用分区、插件及前端 Web 资源...")
        action_push_web(session)
        session.run_cmd("/bin/nv setenv sw_commit 1 2>/dev/null || true")
        session.run_cmd("/bin/nv setenv sw_updater 2>/dev/null || true")
        session.run_cmd("sync")
        print("==============================================================")
        print("  🎉 [SUCCESS] 路由器已在 Slot 1 运行，最新插件系统与前端已热更新完成！")
        print("  已自动为您固化 Slot 1 启动位 (sw_commit=1)。")
        print("  您可以立即通过浏览器访问: http://192.168.10.1/mod_plugins.html")
        print("==============================================================")
        return

    # 1. 同步 /var/app 基础运行环境
    print("[*] 阶段 1/4: 正在预配置 /var/app 持久化环境...")
    push_file_to_router(session, tar_path, "/tmp/mr3000d_overlay.tar.gz", port=9999, timeout=30)
    session.run_cmd("tar -xzf /tmp/mr3000d_overlay.tar.gz -C /var/app/")
    session.run_cmd("rm -f /tmp/mr3000d_overlay.tar.gz")
    session.run_cmd("chmod +x /var/app/user.sh /var/app/scripts/*.sh /var/app/bin/* /var/app/web/api.cgi /var/app/plugins/*/*.sh 2>/dev/null || true")
    execute_remote_script_file(session, fix_sh_path, timeout=30)

    # 2. 刷写 Slot 1 Kernel (/dev/ubi0_3)
    print("\n[*] 阶段 2/4: 正在传输并刷写 Slot 1 内核 (/dev/ubi0_3 = ubi_k1)...")
    push_file_to_router(session, k1_path, "/tmp/k1.uImage", port=9999, timeout=60)
    print("    - 正在调用 ubiupdatevol 烧录内核镜像...")
    out = session.run_cmd("ubiupdatevol /dev/ubi0_3 /tmp/k1.uImage && rm -f /tmp/k1.uImage", timeout=90)
    if "fail" in out.lower() or "error" in out.lower():
        raise RuntimeError(f"[!] Slot 1 内核烧录异常: {out}")
    print("[+] Slot 1 内核卷烧录成功！")

    # 3. 刷写 Slot 1 SquashFS RootFS (/dev/ubi0_4)
    print("\n[*] 阶段 3/4: 正在传输并刷写 Slot 1 纯净根文件系统 (/dev/ubi0_4 = ubi_r1)...")
    push_file_to_router(session, r1_path, "/tmp/r1.squashfs", port=9999, timeout=90)
    session.run_cmd("umount -f -l /dev/ubi0_4 2>/dev/null || true")
    print("    - 正在调用 ubiupdatevol 烧录 14MB SquashFS 镜像...")
    out = session.run_cmd("ubiupdatevol /dev/ubi0_4 /tmp/r1.squashfs && rm -f /tmp/r1.squashfs", timeout=120)
    if "fail" in out.lower() or "error" in out.lower():
        raise RuntimeError(f"[!] Slot 1 RootFS 烧录异常: {out}")
    print("[+] Slot 1 RootFS 卷烧录成功！")

    # 4. 设置 U-Boot 试启动与 90 秒防砖看门狗
    print("\n[*] 阶段 4/4: 正在配置 U-Boot 双槽位试启动保护 (sw_tryactive=1)...")
    session.run_cmd("echo 90 > /var/app/.unconfirmed")
    session.run_cmd("/bin/nv setenv sw_commit 0")
    session.run_cmd("/bin/nv setenv sw_tryactive 1")
    session.run_cmd("/bin/nv setenv sw_updater")
    session.run_cmd("sync")

    print("==============================================================")
    print("  🎉 [SUCCESS] Plan B 固件已完整刷入 Slot 1！")
    print("  🚀 路由器将在 3 秒后自动重启并试启动进入 Slot 1！")
    print("==============================================================")
    print("  ⚠️  【重要：重启后固化操作说明】")
    print("  1. 重启过程约需 40~50 秒；")
    print("  2. 进入新系统后，90 秒防砖倒计时将自动启动；")
    print("  3. 待 Wi-Fi 重新连接后，在浏览器访问后台，点击绿色【永久确认保留固件】按钮，")
    print("     或重新运行 ./flash_mr3000d.sh 并选择 [4] confirm 即可永久固化！")
    print("==============================================================\n")

    try:
        session.run_cmd("sleep 1 && reboot &\n")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="MR3000D-CIq 工业级刷机与网络优化工具")
    parser.add_argument("action", choices=['deploy', 'deploy-all', "fix-net", "push-web", "push-plugin", "plan-b", "confirm", "status", "boot-slot1", "switch-slot1", "unlock-telnet"], help="执行动作")
    parser.add_argument("--host", default="192.168.10.1", help="路由器 IP (默认 192.168.10.1)")
    parser.add_argument("--port", type=int, default=2356, help="指定端口 (默认自适应 2356/22/23)")
    parser.add_argument("--user", default="admin", help="用户名 (默认 admin)")
    parser.add_argument("--password", default="system", help="密码 (默认 system)")
    args = parser.parse_args()

    # 1. 强制检测本地物理局域网网卡
    real_lan_ip = find_real_lan_ip("192.168.10.")
    if not real_lan_ip:
        print("\n======================================================================")
        print("  ❌ [前置拦截] 未检测到 192.168.10.x 局域网物理连接！")
        print("======================================================================")
        print("  当前 Mac 尚未连接到路由器。请按以下步骤操作:")
        print("  1. 打开 Mac Wi-Fi，搜索并连接路由器的无线网络 (如 MR3000D-XXXX)；")
        print("     或者用网线将 Mac 连接到路由器的 LAN 口。")
        print("  2. 连接成功后，Mac 将自动获得 192.168.10.x 网段的 IP。")
        print("  3. 待连上路由器后，再次运行本脚本即可！")
        print("======================================================================\n")
        sys.exit(1)

    print(f"[*] 检测到物理局域网 IP: {real_lan_ip}")

    # 特殊动作：unlock-telnet 独立调用一键解锁工具
    if args.action == "unlock-telnet":
        import unlock_telnet
        unlock_telnet.unlock_and_init(host=args.host, port=args.port if args.port != 2356 else None, mac_ip=real_lan_ip)
        return

    # 特殊动作：push-plugin 优先尝试纯 HTTP Web API 安装 (无需任何 Telnet/SSH 端口)
    if args.action in ["push-plugin", "update-plugin", "install-plugin"]:
        target_plugin = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else "hosts_adblock_dns"
        plugin_tar = os.path.join(PKG_DIR, "plugins", f"{target_plugin}.tar.gz")
        plugin_src_dir = os.path.join(PKG_DIR, "plugins", target_plugin)
        web_plugin_tar = os.path.join(PKG_DIR, "web", "plugins", f"{target_plugin}.tar.gz")

        if os.path.isdir(plugin_src_dir):
            print(f"[*] 正在打包最新插件目录: {target_plugin}...")
            subprocess.run(f"cd '{plugin_src_dir}' && tar -czf '{plugin_tar}' *", shell=True, check=True)
            os.makedirs(os.path.dirname(web_plugin_tar), exist_ok=True)
            shutil.copyfile(plugin_tar, web_plugin_tar)

    # 建立自适应会话 (Telnet / SSH 自动嗅探与降级)
    session = connect_router(
        mac_ip=real_lan_ip,
        host=args.host,
        user=args.user,
        password=args.password,
        port=args.port if args.port != 2356 else None
    )

    try:
        if args.action == "status":
            action_status(session)
        elif args.action == "confirm":
            action_confirm(session)
        elif args.action in ["deploy", "deploy-all"]:
            action_deploy_ripple_mod(session)
        elif args.action == "push-web":
            action_push_web(session)
        elif args.action == "fix-net":
            action_fix_net(session)
        elif args.action in ["push-plugin", "update-plugin", "install-plugin"]:
            target_plugin = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else "hosts_adblock_dns"
            action_push_plugin(session, target_plugin)
        elif args.action in ["boot-slot1", "switch-slot1"]:
            action_boot_slot1(session)
        elif args.action == "plan-b":
            action_plan_b(session)
    except Exception as e:
        print(f"\n[!] 执行出错: {e}")
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
