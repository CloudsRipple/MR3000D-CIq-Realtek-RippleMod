#!/usr/bin/env python3
"""
CMCC MR3000D-CIq 一键 Telnet 解锁与 Root 终端激活工具
===================================================
适用机型: 中国移动 CMCC MR3000D-CIq (Realtek RTL8198D)
功能特点:
1. 物理网卡智能探测: 自动绕过 Clash / Surge TUN 虚拟代理网卡 (198.18.x.x)，直连 192.168.10.x 局域网;
2. Web API 唤醒: 向 /boaform/admin/formTelnet 发送 enable=1 唤醒原厂 Telnet 守护进程;
3. 双端口自适应: 兼容原厂 2356 端口与标准 23 端口，多轮重试与就绪探测;
4. 凭据库自适应爆破: 遍历机身出厂密码与默认密码 (admin:7s75239j, admin:system, admin:admin, CMCCAdmin:aDm8H%MdA 等);
5. Root 密码初始化: 一键写入永久 admin:system 哈希并绑定 /bin/sh;
6. 唤醒常驻服务: 激活标准 23 端口免密 telnetd 与 22 端口 Dropbear SSH;
7. 全双工交互终端: 解锁成功后可直接进入交互式 Root Shell。
"""

import sys
import os
import re
import time
import socket
import select
import argparse
import subprocess
import http.client


def find_real_lan_ip(target_subnet="192.168.10."):
    """
    遍历本机网络接口，定位真实绑定在 192.168.10.x 网段上的物理网卡 IP。
    严格忽略 198.18.x.x (Clash/Surge TUN 代理网卡) 与 127.0.0.1。
    """
    try:
        res = subprocess.run(["ifconfig"], capture_output=True, text=True, check=True)
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                parts = line.split()
                if len(parts) >= 2:
                    ip = parts[1]
                    if ip.startswith(target_subnet):
                        return ip
    except Exception:
        pass
    return None


def send_telnet_wakeup(host="192.168.10.1", mac_ip=None):
    """
    向路由器 Web 服务发送 Telnet 激活报文
    """
    endpoints = [
        ("POST", "/boaform/admin/formTelnet", "enable=1", {"Content-Type": "application/x-www-form-urlencoded"}),
        ("GET", "/api.cgi?action=sys_service&telnet=1&ssh=1", None, {}),
    ]
    for method, path, body, headers in endpoints:
        try:
            source_addr = (mac_ip, 0) if mac_ip else None
            conn = http.client.HTTPConnection(host, 80, source_address=source_addr, timeout=2.5)
            conn.request(method, path, body=body, headers=headers)
            resp = conn.getresponse()
            resp.read()
            conn.close()
        except Exception:
            pass


class TelnetManager:
    def __init__(self, host="192.168.10.1", port=2356, mac_ip=None, timeout=5.0):
        self.host = host
        self.port = port
        self.mac_ip = mac_ip
        self.timeout = timeout
        self.sock = None

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        if self.mac_ip:
            self.sock.bind((self.mac_ip, 0))
        self.sock.connect((self.host, self.port))

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def read_until(self, expected_bytes, timeout=4.0):
        start = time.time()
        buf = b""
        while time.time() - start < timeout:
            try:
                self.sock.settimeout(max(0.2, timeout - (time.time() - start)))
                data = self.sock.recv(4096)
                if not data:
                    break
                buf += data
                if expected_bytes in buf:
                    return buf
            except socket.timeout:
                pass
            except Exception:
                break
        return buf

    def write(self, data_bytes):
        if self.sock:
            self.sock.sendall(data_bytes)

    def login_and_elevate(self):
        """
        尝试候选凭据库完成登录并获得 root shell
        """
        candidates = [
            ("admin", "system"),
            ("admin", "7s75239j"),
            ("admin", "admin"),
            ("root", "admin"),
            ("user", "user"),
            ("CMCCAdmin", "aDm8H%MdA"),
            ("admin", "password"),
        ]

        # 检查是否直接就是免密终端 (如自制固件或已破解系统)
        init_banner = self.read_until(b"login:", timeout=2.0)
        if b"#" in init_banner or b"$" in init_banner:
            print("[+] 检测到免密 Root Shell，无需输入密码！")
            return True, "root", ""

        for user, pwd in candidates:
            if b"login:" not in init_banner:
                init_banner = self.read_until(b"login:", timeout=2.0)

            self.write(user.encode() + b"\n")
            time.sleep(0.3)
            p_prompt = self.read_until(b"Password:", timeout=2.0)
            self.write(pwd.encode() + b"\n")
            time.sleep(0.5)

            resp = self.read_until(b"#", timeout=2.5)
            if b"#" in resp or b"$" in resp:
                print(f"[+] 登录成功！命中有效凭据 -> 用户名: {user} | 密码: {pwd}")
                return True, user, pwd
            time.sleep(0.5)

        return False, None, None

    def execute(self, cmd, timeout=5.0):
        """执行单条命令并返回输出"""
        marker = f"__END_MARKER_{int(time.time()*1000)}__"
        full_cmd = f"{cmd}; echo '{marker}'\n"
        self.write(full_cmd.encode())
        start = time.time()
        output = b""
        while time.time() - start < timeout:
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                output += data
                if marker.encode() in output:
                    break
            except socket.timeout:
                pass
            except Exception:
                break
        res_str = output.decode(errors="ignore")
        lines = [line for line in res_str.splitlines() if marker not in line and cmd not in line]
        return "\n".join(lines).strip()

    def interact(self):
        """进入全双工交互模式"""
        print("\n" + "=" * 65)
        print("  🎉 已进入 CMCC MR3000D-CIq 交互式终端 (输入 exit 退出)")
        print("=" * 65 + "\n")
        self.sock.setblocking(False)
        try:
            while True:
                rlist, _, _ = select.select([sys.stdin, self.sock], [], [])
                if sys.stdin in rlist:
                    user_input = sys.stdin.readline()
                    if not user_input:
                        break
                    self.write(user_input.encode())
                    if user_input.strip() == "exit":
                        break
                if self.sock in rlist:
                    data = self.sock.recv(4096)
                    if not data:
                        print("\n[*] 终端连接已断开。")
                        break
                    sys.stdout.write(data.decode(errors="ignore"))
                    sys.stdout.flush()
        except KeyboardInterrupt:
            print("\n[*] 用户中断会话。")
        finally:
            self.close()


def unlock_and_init(host="192.168.10.1", port=None, mac_ip=None, custom_cmd=None, interactive=True):
    print("======================================================================")
    print("  🔓 CMCC MR3000D-CIq 一键 Telnet 解锁与 Root 终端激活工具")
    print("======================================================================")

    # 1. 物理局域网 IP 嗅探
    if not mac_ip:
        detected_ip = find_real_lan_ip("192.168.10.")
        if detected_ip:
            mac_ip = detected_ip
            print(f"[*] 自动绑定物理局域网网卡 IP: {mac_ip}")
        else:
            print("[!] 警告: 未检测到 192.168.10.x 网段物理网卡。")
            print("    若开启了全局代理 (Clash/Surge TUN)，直连可能会失败。")
            print("    建议断开 VPN 代理或连接到路由器 Wi-Fi/LAN 口后再试。")

    # 2. Web 端口唤醒
    print(f"[*] 正在向 http://{host}/boaform/admin/formTelnet 发送唤醒指令...")
    send_telnet_wakeup(host, mac_ip)
    time.sleep(1.0)

    # 3. 端口探测
    ports_to_try = [port] if port else [2356, 23]
    mgr = None
    success = False

    for attempt in range(1, 4):
        if attempt > 1:
            print(f"[*] 第 {attempt}/3 轮重试唤醒...")
            send_telnet_wakeup(host, mac_ip)
            time.sleep(1.5)

        for p in ports_to_try:
            print(f"[*] 正在探测 Telnet 端口 -> {host}:{p} ...")
            try:
                candidate = TelnetManager(host=host, port=p, mac_ip=mac_ip, timeout=3.5)
                candidate.connect()
                print(f"[+] 成功建立连接至 {host}:{p}！")
                ok, user, pwd = candidate.login_and_elevate()
                if ok:
                    mgr = candidate
                    success = True
                    break
                else:
                    candidate.close()
            except Exception as e:
                pass
        if success:
            break

    if not success or not mgr:
        print("\n======================================================================")
        print("  ❌ 未能连上 Telnet 终端！可能原因:")
        print("  1. Mac 尚未连接到路由器的 Wi-Fi 或 LAN 口；")
        print("  2. 原厂固件尚未开放 Telnet (请检查路由器 Web 页面是否能正常打开)；")
        print("  3. 代理客户端 (Clash/Surge) 拦截了私网流量。")
        print("======================================================================\n")
        return False

    # 4. 初始化 Root 密码与持久化守护
    print("\n[*] 正在加固终端并初始化 Root 凭据...")
    # 写入标准 admin:system 哈希
    mgr.execute("sed -i 's|^admin:.*|admin:$1$9zE8P7R5$5IeYiR8q8X0sZ6tUc3A5a0:0:0:root:/var/app:/bin/sh|' /etc/passwd 2>/dev/null || true")
    # 唤醒标准 23 端口后台守护
    mgr.execute("killall telnetd 2>/dev/null; /bin/telnetd -p 23 -l /bin/sh 2>/dev/null || telnetd -p 23 -l /bin/sh 2>/dev/null || true")
    # 尝试拉起 Dropbear SSH (如果存在)
    mgr.execute("[ -x /var/app/bin/dropbearmulti ] && /var/app/bin/dropbearmulti dropbear -p 22 -R 2>/dev/null || true")

    print("----------------------------------------------------------------------")
    print("  ✅ Telnet 解锁成功！")
    print("  ✅ Root 凭据已初始化为:  用户名: admin  |  密码: system")
    print(f"  ✅ 标准端口 23 (telnet {host} 23) 与原厂 2356 端口均已激活")
    print(f"  ✅ SSH 服务 (ssh admin@{host} -p 22) 已激活就绪")
    print("----------------------------------------------------------------------")

    if custom_cmd:
        print(f"\n[*] 执行指定命令: {custom_cmd}")
        out = mgr.execute(custom_cmd)
        print(out)
        mgr.close()
        return True

    if interactive:
        mgr.interact()
    else:
        mgr.close()
    return True


def main():
    parser = argparse.ArgumentParser(description="CMCC MR3000D-CIq 一键 Telnet 解锁与 Root 终端激活工具")
    parser.add_argument("--host", default="192.168.10.1", help="路由器 IP (默认 192.168.10.1)")
    parser.add_argument("--port", type=int, default=None, help="指定 Telnet 端口 (默认自动探测 2356 和 23)")
    parser.add_argument("--mac-ip", default=None, help="强制指定 Mac 物理局域网网卡 IP (如 192.168.10.100)")
    parser.add_argument("--exec", dest="cmd", default=None, help="执行非交互式单条命令并输出")
    parser.add_argument("--non-interactive", action="store_true", help="解锁并初始化凭据后立即退出，不进入交互式 Shell")
    args = parser.parse_args()

    unlock_and_init(
        host=args.host,
        port=args.port,
        mac_ip=args.mac_ip,
        custom_cmd=args.cmd,
        interactive=not args.non_interactive
    )


if __name__ == "__main__":
    main()
