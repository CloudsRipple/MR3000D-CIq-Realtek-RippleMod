# MR3000D-CIq-Realtek-RippleMod

中国移动 **CMCC MR3000D-CIq**（Realtek RTL8198D）的第三方 ROM：基于原厂固件，移除厂商遥测与强制升级，加入插件系统和 Web 控制台，以双槽位方式安装，原厂系统保留在 Slot 0 作为退路。

> [!WARNING]
> **本项目由 AI 辅助开发，存在不足。**
> 代码、脚本、固件构建流程和本文档大量由 AI 编写或修改，作者做了整理和部分验证，但**最新构建的镜像没有经过完整的真机验证**，可能有未发现的 bug。刷机有变砖风险，请先阅读[已知问题与不足](#已知问题与不足)，并自行备份、自行承担后果。

## 目录

- [硬件与闪存信息](#硬件与闪存信息)
- [相对原厂固件的改动](#相对原厂固件的改动)
- [安装](#安装)
- [刷入限制](#刷入限制)
- [回滚与恢复机制](#回滚与恢复机制)
- [Web 控制台与插件](#web-控制台与插件)
- [热部署](#热部署)
- [从源码构建](#从源码构建)
- [仓库结构](#仓库结构)
- [已知问题与不足](#已知问题与不足)
- [安全提示](#安全提示)
- [许可与免责](#许可与免责)

## 硬件与闪存信息

以下数据来自原厂固件的整机备份和 U-Boot 环境变量，不是推测：

| 项目 | 值 |
| --- | --- |
| SoC | Realtek RTL8198D（MIPS32r2，大端） |
| 内核 | Linux 5.10.70 |
| 闪存 | SPI NAND，128 MiB，页 2048 B，擦除块 128 KiB（备份中没有颗粒型号） |
| MTD 分区 | `boot` 768K · `env` 128K · `env2` 128K · `static_conf` 128K · `ubi_device` 127360K |
| UBI 卷（单位 PEB） | `ubi_Config` 87 · `ubi_k0` 83 · `ubi_r0` 207 · `ubi_k1` 83 · `ubi_r1` 207 · `ubi_config_bak` 17 · `ubi_factory` 17 · `ubi_app` 248 |
| 双槽位 | Slot 0 = `ubi_k0` + `ubi_r0`（原厂）；Slot 1 = `ubi_k1` + `ubi_r1`（本 ROM） |
| 持久化分区 | `ubi_app` 挂载到 `/var/app`，约 26 MB，本 ROM 的套件和插件配置放在这里 |
| rootfs | SquashFS（XZ，128K 块），本项目限制在 20 MiB 以内 |

Slot 1 的内核直接复制自原厂 `ubi_k0`，没有修改。

## 相对原厂固件的改动

- **移除**：`aosnet`、`lanNetInfo`、`ahsapd`、`ahsapd_logsrv`、`do_force_upgrade`、`check_upgrade_info`、`vasdocker`；注释掉 `inittab` / `rc22` / `rc36` 里对应的拉起和定时升级项。
- **保留**：Realtek 底层启动链路（`startup`、`configd`、`flash`、`boa`、`hostapd`、`libmib.so`、`librtk.so`、Wi-Fi 驱动等），构建时会检查这些文件存在。
- **新增**：
  - Ripple-mod 套件（BusyBox 1.36.1、Dropbear 2024.86、`ripple_api_daemon`、插件引擎、Web 控制台），随固件放在 `/etc/ripple-mod`，开机时同步到 `/var/app`，已有的插件配置和启用状态会保留。
  - `/etc/init.d/rc37` 开机钩子：启动回滚守护、Telnet（端口 2356）、同步套件、延迟 20 秒后运行 `user.sh`、应用低延迟调优。
  - 回滚守护与调优脚本，在 `/bin` 和 `/var/app/scripts` 下：`slot1_confirm_guard.sh`、`rollback_guard.sh`、`confirm_keep.sh`、`anti_ota_shield.sh`、`remote_fix_net.sh`、`wifi_tuner.sh`、`low_latency_driver_tuner.sh`。
- **修改**：对 `rtk_wifi6.ko` 做二进制补丁，把若干热路径上的调试函数改成直接返回（`jr $ra; nop`），目的是降低延迟。这是**有风险的改动**，见[已知问题](#已知问题与不足)。
- **`/etc/hosts`** 改为指向 `/var/tmp/hosts` 的符号链接，因为 rootfs 只读。

## 安装

### 前置条件

- 设备型号确实是 MR3000D-CIq，当前运行原厂固件（`sw_active=0`，即 Slot 0）。
- 电脑与路由器直连，路由器地址为 `192.168.10.1`。
- 已经备份。至少保留原厂整机备份；原厂系统本身会留在 Slot 0，但这不能代替备份。

### 步骤

1. 在 [Releases](https://github.com/CloudsRipple/MR3000D-CIq-Realtek-RippleMod/releases/latest) 下载：
   `ubi0_3_k1_kernel.uImage`、`ubi0_4_r1_mod.squashfs`、`MD5SUMS`、`flash_slot1.sh`。
2. 开启 Telnet 并取得 root（`tools/unlock_telnet.py` 主要在 macOS 上使用，会自动避开 Clash/Surge 的虚拟网卡）：

   ```bash
   python3 tools/unlock_telnet.py --host 192.168.10.1
   ```

3. 把四个文件传到路由器同一目录（例如 `/tmp`）。镜像和 `MD5SUMS` 必须在同一目录。
4. **先检查，不写入**：

   ```sh
   sh flash_slot1.sh check ubi0_3_k1_kernel.uImage ubi0_4_r1_mod.squashfs
   ```

   全部显示 `[ ok ]` 并输出 `All guards passed` 才可以继续。任何一项 `[REFUSE]` 都说明设备或镜像和预期不符，请不要绕过。
5. 刷入 Slot 1：

   ```sh
   sh flash_slot1.sh flash ubi0_3_k1_kernel.uImage ubi0_4_r1_mod.squashfs
   ```

   脚本会写入 `ubi_k1`、`ubi_r1`，设置一次性试启动，然后重启。
6. 重启后约 40～50 秒路由器上线。**倒计时从开机钩子启动时开始计算，留给你的时间不足 90 秒**，请尽快通过 Telnet（2356）登录，执行：

   ```sh
   /bin/confirm_keep.sh
   ```

   确认后才会永久固化 Slot 1。超时没有确认，会自动回到原厂系统。

## 刷入限制

`flash_slot1.sh` 在路由器上运行，只写 `/dev/ubi0_3`（`ubi_k1`）和 `/dev/ubi0_4`（`ubi_r1`），不碰 bootloader、env 和任何原始 NAND。下面任一项不符就拒绝，**没有强制刷入选项**：

| 检查 | 条件 |
| --- | --- |
| 权限 | 必须是 root |
| 内核 / 架构 | `5.10.70*`，MIPS；存在设备树时必须含 `8198` |
| MTD 布局 | `boot`、`env` 大小和 128 KiB 擦除块、`ubi_device` = `0x7c60000`、至少 6 个 mtd |
| UBI 几何 | 页大小 2048、LEB 126976、共 8 个卷 |
| UBI 卷 | 8 个卷的名称和大小都和原厂一致 |
| 运行槽位 | `sw_active=0`，且 `ubi_r1` 未被挂载，不会覆盖正在运行的系统 |
| 镜像 | 内核是 uImage 且不超过 `ubi_k1`；rootfs 是 SquashFS 且不超过 20 MiB |
| 校验 | 同目录必须有 `MD5SUMS`，两个镜像都要匹配 |

## 回滚与恢复机制

依据 U-Boot 环境变量的启动逻辑，有两层保护：

1. **一次性试启动**：`flash_slot1.sh` 设置 `sw_commit=0`、`sw_tryactive=1`。U-Boot 看到 `sw_tryactive` 不是 2 时，会改成 2 再启动 Slot 1，并打开硬件看门狗。如果内核或系统起不来，看门狗复位后，U-Boot 会按 `sw_commit` 回到 Slot 0。
2. **软件倒计时**：Slot 1 起来后，`slot1_confirm_guard.sh` 开始 90 秒倒计时。没有执行 `confirm_keep.sh`，就把 `sw_commit` 设为 0 并重启，回到 Slot 0。

如果两层保护都没生效，可以接串口进入 U-Boot，执行 `setenv sw_commit 0` 和 `saveenv` 后重启。这是根据环境变量逻辑推断的恢复方式，**没有实际演练过**。

## Web 控制台与插件

启动后访问 `http://192.168.10.1/`（80 端口会重定向到 `ripple_api_daemon` 的 8080 端口）。标签页：系统概览、运行环境与 Python、插件中心、DNS 与去广告、自定义脚本、实时日志。

Web 通过 `api.cgi` 的 `plugin_call` 动作调用插件，由 `plugin_engine/api_dispatcher.sh` 转发到对应插件的 `api.sh`。

内置插件：

| 插件 | 作用 |
| --- | --- |
| `hosts_adblock_dns` | 基于 dnsmasq 和 hosts 的域名拦截，默认拦截几个厂商上报、OTA 域名，支持自定义规则 |
| `custom_userscript` | 开机自启的自定义 Shell 脚本和 Cron 任务 |
| `entware_package_mgr` | 引导安装 Entware（架构 `mipssf-k3.4`）和 Python 3，**尚不完善，见已知问题** |

### 开发自己的插件

在 `plugins/<id>/` 下放：

| 文件 | 说明 |
| --- | --- |
| `manifest.json` | `id`、`name`、`version`、`description`、`autostart`、`icon` |
| `start.sh` / `stop.sh` / `status.sh` | 生命周期；`status.sh` 输出 JSON |
| `api.sh` | 接收 `<cmd> [args]`，输出 JSON，供 Web 调用 |
| `install.sh` | 可选，安装时运行 |
| `.enabled` | 存在则开机自启 |

可参考 `plugins/custom_userscript`。插件管理命令：

```sh
sh /var/app/plugin_engine/plugin_manager.sh list|start|stop|status ...
```

## 热部署

已经在运行本 ROM 或者想临时更新 `/var/app` 里的套件时，不写闪存：

```bash
./deploy_ripple.sh
```

脚本会打包 `bin core_system plugin_engine plugins web`，通过 Telnet 推送并解压到 `/var/app`，然后重启 API 守护进程。注意它**不含 `scripts/`**，所以这种方式下槽位和回滚相关功能不可用。

## 从源码构建

固件镜像需要原厂文件，这些文件**不随仓库分发**，请自备：

- 原厂 rootfs 的解包目录（SquashFS 解包结果）；
- 原厂备份目录，需包含 `ubi0_1_k0.uImage`。

依赖：Python 3 和 `mksquashfs`（squashfs-tools）。

```bash
python3 tools/build_firmware.py \
  --rootfs <原厂rootfs目录> \
  --backup-dir <原厂备份目录> \
  --out-dir firmware_images
```

输出 `ubi0_3_k1_kernel.uImage`（校验 uImage 头和 CRC）和 `ubi0_4_r1_mod.squashfs`（超过 20 MiB 会报错）。

仓库里的三个二进制都是 MIPS32 大端静态 ELF，不能在宿主机上运行：

| 文件 | 来源 |
| --- | --- |
| `bin/busybox_mips` | BusyBox 1.36.1，GPL-2.0，源码见 <https://busybox.net/> |
| `bin/dropbearmulti` | Dropbear 2024.86，源码见 <https://matt.ucc.asn.au/dropbear/> |
| `bin/ripple_api_daemon` | 源码为 `bin/ripple_api_daemon.c`，**当前二进制不是由最新源码重新编译的**，见已知问题 |

## 仓库结构

```text
bin/              MIPS32 BE 静态二进制与 API 守护进程源码
core_system/      开机引导 user.sh、运行库、Entware / Python 引导脚本
plugin_engine/    插件管理器与 RPC 分发网关
plugins/          内置插件
web/              Web 控制台（HTML / CSS / JS / CGI）
firmware/         回滚守护与调优脚本，以及 Slot 1 刷入脚本 flash_slot1.sh
tools/            宿主机工具：unlock_telnet.py、deploy_system.py、build_firmware.py
deploy_ripple.sh  热部署脚本
```

## 已知问题与不足

请在使用前认真阅读：

- **未经完整真机验证**：最新构建的镜像只做了静态检查和模拟测试（语法、镜像结构、`rc37` 同步逻辑、刷入限制的各种拒绝场景）。真机上才能确认的部分，例如 sysfs 路径、`/proc/device-tree` 判断、开机时序，都可能出问题。
- **`ripple_api_daemon` 二进制**：它是旧二进制把部分字符串替换为等长占位值得到的，没有用最新的 C 源码重新编译，二进制和源码的行为可能不完全一致。
- **Entware / Python 安装**：Web 里的下载安装按钮不完善，点击后可能报错，仍在修复。可以尝试用命令行运行 `core_system/runtime/bootstrap_entware.sh` 和 `install_python.sh`，同样没有充分测试。
- **部分接口没有对应脚本**：`ripple_api_daemon` 里仍引用了 `dual_wan_engine.sh` 等脚本，本仓库没有提供，相关接口会失败。
- **Wi-Fi 驱动补丁**：对 `rtk_wifi6.ko` 的二进制补丁可能影响稳定性，没有长期稳定性和射频方面的测试。
- **确认时间窗口较短**：见[安装](#安装)第 6 步，错过后会回滚，需要重新刷入。
- **只针对 MR3000D-CIq**：其他硬件版本没有验证，`flash_slot1.sh` 的限制也是按本机分区布局写的。
- **工具链偏向 macOS**：`unlock_telnet.py`、`deploy_system.py` 里的网卡探测和提示主要面向 macOS。
- **文档由 AI 辅助编写**：描述可能有疏漏，以代码和实测为准，欢迎提 Issue。

## 安全提示

- `unlock_telnet.py` 会把 `admin` 的口令设成默认的 `system`，ROM 在开机时会在 2356 端口启动 Telnet。**这两者都不安全，请安装后立即修改口令，并避免把路由器管理口暴露到外网。**
- 本 ROM 默认拦截部分厂商上报和 OTA 域名，同时会让原厂的在线升级失效。

## 许可与免责

- 原创代码采用 [MIT](LICENSE) 许可。
- 第三方组件（BusyBox 为 GPL-2.0、Dropbear 等）与厂商固件的说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。Release 中的固件基于厂商原版固件改造，权利归原厂所有，仅供个人学习研究。
- 刷机有风险，按现状提供，不附带任何担保，因使用造成的损失由使用者自行承担。
