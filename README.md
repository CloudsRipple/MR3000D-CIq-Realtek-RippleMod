# MR3000D-CIq-Realtek-RippleMod

针对 **MR3000D-CIq**（瑞昱 Realtek RTL8198D 芯片方案）制作的第三方修改版固件（ROM）与插件系统。

本项目在原厂 Linux 5.10 固件的基础上，精简了部分常驻后台服务以释放系统内存，加入了轻量级的 Web 管理界面和模块化插件机制。系统采用双槽位方案，仅写入备用槽位（Slot 1），保留原厂槽位（Slot 0）以防异常。

---

> [!WARNING]
> **开发背景与免责声明**
> 
> 1. **AI 辅助开发**：本项目代码、配置和文档由个人借助 AI 工具辅助生成与整理。由于开发人员与 AI 的局限性，部分实现可能存在缺陷、考虑不周或未预料到的错误。
> 2. **实机验证状态**：最新固件版本已在作者本人的实机设备（MR3000D-CIq 瑞昱 RTL8198D 平台）上完成双槽位写入、启动与日常网络运行验证。但由于手头硬件资源有限，**尚未在不同批次的多台设备上进行大范围交叉测试**，初次刷入仍请务必做好原厂分区备份。
> 3. **操作风险**：刷写闪存存在设备无法开机（变砖）的风险。所有资源均按“现状”（AS-IS）提供，不包含任何明示或暗示的保证。请自行评估风险并承担后果。

---

## 硬件与存储布局规格

数据基于原厂整机备份和 U-Boot 环境变量整理：

| 项目 | 参数 |
| :--- | :--- |
| 处理器架构 | Realtek RTL8198D（双核 MIPS32r2，大端序 Big-Endian） |
| 内核版本 | Linux 5.10.70 |
| 存储介质 | SPI NAND Flash，容量 128 MiB（页大小 2048 B，擦除块 128 KiB） |
| MTD 分区 | `boot` (768K), `env` (128K), `env2` (128K), `static_conf` (128K), `ubi_device` (127360K) |
| UBI 卷划分 | `ubi_Config` (87 PEB)<br>`ubi_k0` / `ubi_r0` (Slot 0 原厂系统，83 + 207 PEB)<br>`ubi_k1` / `ubi_r1` (Slot 1 本固件，83 + 207 PEB)<br>`ubi_config_bak` (17 PEB)<br>`ubi_factory` (17 PEB)<br>`ubi_app` (挂载为 `/var/app`，248 PEB，约 26MB 可写空间) |
| 根文件系统 | SquashFS 4.0（XZ 压缩，块大小 128 KiB），镜像大小限制在 20 MiB 内 |

---

## 主要调整与功能特性

### 1. 系统服务精简
- 精简了部分原厂预装的非必要后台进程与计划任务，降低内存占用。
- 完整保留瑞昱平台的底层驱动、网络协议栈与硬件支持。

### 2. 软件运行底座
- 打包集成静态编译的 BusyBox（1.36.1）与 Dropbear SSH 服务（2024.86）。
- 将运行数据规范至 `/var/app` 及内存临时文件系统（`/tmp`），适配只读的 SquashFS 根目录。
- 新增开机初始化脚本 `/etc/init.d/rc37`，用于加载应用层环境与安全看门狗。

### 3. Web 管理界面功能
访问地址为 `http://192.168.10.1/`，由轻量级 C 守护进程 `ripple_api_daemon` 承载：
- **系统概览**：实时 CPU 使用率（差分计算）、内存占用仪表盘、存储空间与网络接口状态。
- **局域网与 DHCP**：自定义网关 IP、子网掩码、DHCP 服务启闭、分配池范围、租期时间及内网域名。
- **工作模式切换**：支持常规路由网关模式与纯 AP 桥接模式快速切换。
- **WAN 外网配置**：支持 DHCP 动态获取、静态 IP 与 PPPoE 拨号配置。
- **无线网络配置**：2.4GHz 与 5GHz 独立配置（SSID、加密方式、信道、频宽、发射功率及隐藏 SSID 开关）。
- **客户端监控**：实时展示当前 DHCP 租约终端列表（主机名、分配 IP、MAC 地址与租期倒计时）。
- **端口转发与 DMZ**：支持自定义外网端口映射转发规则及 DMZ 主机指定。
- **插件管理**：内置用户自定义启动脚本、Hosts 域名自定义拦截与 Entware 环境管理插件。

---

## 刷入指引（刷写至 Slot 1）

### 推荐方法：电脑端一键全自动刷入

1. 从 [Releases 最新发布页面](https://github.com/CloudsRipple/MR3000D-CIq-Realtek-RippleMod/releases/latest) 下载 **`MR3000D-CIq-RippleMod-v0.2.2-OneClick-Flashing-Kit.zip`** 并解压。
2. 用网线将电脑连接至路由器的任意 LAN 口（确保电脑获取到 `192.168.10.x` 网段 IP，浏览器能打开原厂 `http://192.168.10.1/` 登录页）。
3. 运行刷机程序：
   - **Windows 用户**：直接双击包内的 `flash.bat`。
   - **macOS / Linux 用户**：终端执行 `sh flash.sh`（或 `python3 flash_router.py`）。
4. 电脑端程序将全自动完成局域网探测、终端通道唤醒、硬件与分区审查、固件高速推送与 MD5 校验，随后将固件安全刷入 Slot 1 分区。
5. **重启后手动固化（重要）**：
   - 路由器写入完毕后将自动重启（耗时约 45 秒）。
   - 系统内置约 90 秒的看门狗试运行保护。若在超时前未能确认，路由器将自动回退至 Slot 0 原厂系统，杜绝变砖。
   - 重新连上路由器后，请立即通过终端（Telnet 或 SSH）执行确认命令：
     ```sh
     /bin/confirm_keep.sh
     ```
   - 提示确认成功后，Slot 1 即可成为永久默认启动系统。

<details>
<summary>高级开发者：手动终端刷入步骤</summary>

若您希望在终端内完全手动控制刷写流程：
1. 下载 `ubi0_3_k1_kernel.uImage`、`ubi0_4_r1_mod.squashfs` 和 `flash_slot1.sh` 推送到路由器 `/tmp`。
2. 执行刷前预检（不写入闪存）：
   ```sh
   sh /tmp/flash_slot1.sh check /tmp/ubi0_3_k1_kernel.uImage /tmp/ubi0_4_r1_mod.squashfs
   ```
3. 执行写入：
   ```sh
   sh /tmp/flash_slot1.sh flash /tmp/ubi0_3_k1_kernel.uImage /tmp/ubi0_4_r1_mod.squashfs
   ```
4. 重启后执行 `/bin/confirm_keep.sh` 固化。
</details>

---

## 免刷机热部署模式（仅更新应用层）

如果不想对底层闪存进行刷写，或者在原厂固件下仅想体验轻量管理控制台与插件机制，可以在电脑端执行：

```bash
./deploy_ripple.sh
```

该脚本仅将管理程序推送到可写的 `/var/app` 空间中运行，不触及底层只读系统和启动槽位。

---

## 当前已知缺陷与不足

1. **Web 端 Entware / Python 安装**：在管理页面中调用安装 Python 3 或 Entware 时，可能因网络镜像连通性或耗时较长出现超时，建议亦可通过命令行手动执行对应脚本。
2. **Wi-Fi 驱动补丁影响未测**：为降低网络延迟，固件构建脚本对无线驱动模块的部分内部调试函数打入了返回补丁，尚未经过长时间高吞吐稳定性测试。
3. **回滚确认窗口较紧**：由于开机过程耗费时间，留给用户手动运行 `confirm_keep.sh` 的时间实际不足 90 秒，初次操作需准备好连接终端。

---

## 开源许可

- 本项目采用 [MIT 许可证](LICENSE)。
- 内置及引用的第三方程序（如 BusyBox、Dropbear 等）遵循其各自的原开源协议（详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)）。
