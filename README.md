# MR3000D-CIq-Realtek-RippleMod

面向 **中国移动 CMCC MR3000D-CIq（Realtek RTL8198D 双核 MIPS32r2 大端序，Linux 5.10.70 SMP，256 MiB RAM）** 的双槽位第三方固件（Slot 1）与轻量化插件系统。

本项目在保留原厂内核与核心硬件驱动基础设施的基础上，精简运营商云端与强制升级后台服务，提供现代化的本地 Web 控制台、通用插件引擎与双槽防变砖刷写工具链；所有改动仅作用于 **Slot 1**，**Slot 0 原厂系统** 与底层 BootLoader 分区保持原样不动。

---

> [!WARNING]
> **实机验证与使用须知**
>
> 1. **实机状态与风险提示**：`v0.2.3` 已在作者本人的 MR3000D-CIq 实机上完成 Slot 1 双槽写入、重启固化与网络运行验证；但由于硬件样品有限，尚未在不同批次的多台设备上完成广泛交叉测试。刷机前仍请务必自行评估风险并做好原厂分区备份。
> 2. **请勿停留在旧版 `v0.2.2`**：`v0.2.2` 默认启用了过大的内核套接字缓冲与全开无线调优参数，在 256 MiB 内存机型上连续运行约 20–48 小时后可能触发高负载 / OOM，导致终端无法接入 Wi-Fi 或失联。**强烈建议所有用户升级至 `v0.2.3` 及以上版本。**
> 3. **免责声明**：所有固件、脚本与工具按“现状”（AS-IS）以 MIT 协议开源提供，不附带任何明示或暗示担保。

---

## `v0.2.3` 核心改进亮点

1. **根治 20–48 小时失联与 OOM 风险（核心稳定性重构）**
   - **安全化 256 MiB 内核网络缓冲**：`core_system/network/network_optimizer.sh` 将默认 `rmem_default`/`wmem_default` 由 2 MiB（内核 2× 计账即 4 MiB/socket）回调至 **128 KiB**，`rmem_max`/`wmem_max`/`tcp_rmem`/`tcp_wmem` 上限由 8 MiB 回调至 **1 MiB**，`netdev_max_backlog` 回调至 **2500**；取消对 `dnsmasq`/`dropbear` 的强制单核绑定与抢占提权。
   - **保留原厂纯净 Wi-Fi 驱动 + 激进调优默认关闭**：`tools/build_firmware.py` 默认打包原厂未修改的 `rtk_wifi6.ko`；`core_system/conf/wifi_tuning.conf` 将高风险射频/驱动调优项（功率表覆写、`edcca_mode=0`、ATF、PCIe 中断汇聚调整、Band Steering、在线卸载 `rtk_igmp_hook.ko`）全部调整为默认 `"0"` 按需开启；同时修复了 `TXPWR_LMT.txt` 替换语法问题并将 `deny_legacy=1` 严格限定至 2.4GHz 接口。
2. **启动保护与网络安全加固**
   - **`user.sh` 单次引导保护与看门狗自愈**：新增 `/tmp/ripple_mod_boot.done` 状态锁（支持 `--force` 手动重载），消除与原厂启动钩子的重复并发；启动时自动补齐 `/var/app/scripts/` 下双槽看门狗软链接。
   - **LAN 隔离绑定与服务去重**：`rc37` 与 `user.sh` 等待 `br0` 获取 LAN IP 后再绑定 Telnet/Dropbear 服务端口，修复 `dropbearmulti` 进程识别避免重复拉起 `dropbear`，并新增独立 `RIPPLE_INPUT` netfilter 链拦截非 `br0`/`lo` 来源对 `8080` API 端口的访问。
3. **插件引擎、JSON 解析与 Web/API 全面修复**
   - **纯 POSIX `awk` JSON 解析**：重写 `core_system/lib/sh_json.sh` 的 `json_get()`，修复 BusyBox `awk` 下包含逗号或转义引号的字符串字段截断。
   - **长耗时插件 RPC 自适应超时**：`plugin_engine/api_dispatcher.sh` 为 `bootstrap_entware`、`install_python`、`opkg_install` 等操作放宽至 **180 秒**，常规 RPC 保持 **20 秒**。
   - **插件 GUI 与生命周期完善**：`plugin_engine/plugin_manager.sh` 自动转义清单字段、升级保留用户配置、将插件独立页面发布到 `/var/app/web/plugins/<id>/` 并暴露 `has_gui` 标志；Web 前端接入第三方插件独立面板跳转与插件卸载入口。
   - **Web 长表单改用 HTTP POST 与 DHCP 防冲突**：Wi-Fi 等长表单改用 POST 提交（避开旧版 C 守护进程 GET URL 255 字节截断与敏感字段入 URL），`web/api.cgi` 修复 `system_hwnat_toggle` 控制节点，并在原厂 `udhcpd` 运行时不再向 `dnsmasq` 重复注入 `dhcp-range`。
   - **旧开关自动安全迁移**：升级工具 `tools/flash_full_firmware.py` 与 `tools/deploy_system.py` 会自动把历史 `/var/app/conf/wifi_tuning.conf` 中的高风险项迁回安全默认值，并修复 `web/index.html` 软链接循环。

---

## 硬件与闪存分区规格

| 项目 | 规格说明 |
| :--- | :--- |
| 主控芯片 | Realtek RTL8198D（双核 MIPS32r2，大端序 Big-Endian MSB） |
| 内存 / 闪存 | 256 MiB DDR3 / 128 MiB SPI NAND Flash（Page 2048 B，Erase Block 128 KiB） |
| 内核版本 | Linux 5.10.70 SMP |
| MTD 分区布局 | `boot` (768K)、`env` (128K)、`env2` (128K)、`static_conf` (128K)、`ubi_device` (127360K) |
| UBI 卷划分 | `ubi_Config` (87 PEB)<br>`ubi_k0` / `ubi_r0`（Slot 0 原厂系统，83 + 207 PEB）<br>`ubi_k1` / `ubi_r1`（Slot 1 Ripple-mod，83 + 207 PEB）<br>`ubi_config_bak` (17 PEB) / `ubi_factory` (17 PEB)<br>`ubi_app`（挂载为 `/var/app`，248 PEB，约 26 MiB 可写空间） |
| 根文件系统 | SquashFS 4.0（XZ 压缩，128 KiB 块大小，镜像上限控制在 20 MiB 内） |

---

## Web 控制台与内置插件

刷入后浏览器访问 `http://192.168.10.1/`（由轻量级 C 守护进程 `ripple_api_daemon` + `api.cgi` 提供）：

- **系统概览**：实时差分 CPU 负载、内存占用、`/var/app` 空间使用率、双槽位与试运行状态、网络接口监控。
- **局域网与工作模式**：自定义 LAN IP / 子网掩码、DHCP 地址池/租期设置、路由模式与纯 AP 桥接模式切换。
- **WAN 与无线配置**：DHCP / 静态 IP / PPPoE 拨号配置，2.4GHz 与 5GHz 独立 SSID、加密模式、信道、频宽与发射功率控制。
- **终端监控与局域网唤醒 (WOL)**：实时终端列表、MAC OUI 厂商识别与一键发送 Magic Packet 唤醒。
- **端口转发、DMZ 与系统维护**：自定义端口映射、Cron 计划任务、网络诊断 Ping、一键释放内存缓存、HWNAT 切换及密码修改。
- **模块化插件中心**：
  - `hosts_adblock_dns`：基于 `dnsmasq` 与 `/var/tmp/hosts` 的域名屏蔽规则与本地域名解析。
  - `custom_userscript`：开机自启自定义 Shell 脚本与第三方 MIPS 大端序常驻程序拉起。
  - `entware_package_mgr`：Entware `/opt` 软件源初始化、Python 3 运行时安装与 `opkg` 包管理。
  - 支持上传第三方 `.tar.gz` 插件包、在线启停、独立插件面板跳转及安全卸载。

---

## 刷入与部署指南（仅写入 Slot 1）

### 方式一：普通用户推荐（Release 一键刷机包）

1. 前往 [Releases 最新页面](https://github.com/CloudsRipple/MR3000D-CIq-Realtek-RippleMod/releases/latest) 下载 **`MR3000D-CIq-RippleMod-v0.2.3-OneClick-Flashing-Kit.zip`** 并解压。
2. 用网线或无线连接路由器，确保电脑获取到 `192.168.10.x` 网段 IP 并可访问 `http://192.168.10.1/`。
3. 运行包内一键刷机程序：
   - **Windows**：双击 `flash.bat`
   - **macOS / Linux**：终端执行 `sh flash.sh`（或 `python3 flash_router.py`）
4. **重启后固化 Slot 1（重要）**：
   - 刷入重启后系统处于约 **90 秒试运行保护窗口**；若超时未固化，看门狗将自动回退至 **Slot 0 原厂系统**，防止变砖。
   - 路由器重启上线后，如工具未自动完成固化，请立即通过 SSH 或 Telnet 登录路由器执行：
     ```sh
     /bin/confirm_keep.sh
     ```

### 方式二：源码全量构建与刷机工具（开发者 / 进阶用户）

```bash
# 1. 在具备 legacy_workspace 原厂底包的环境下构建 Slot 1 内核、SquashFS 与 /var/app Overlay 包
python3 tools/build_firmware.py

# 2. 一键完成 Slot 1 全量推送（/var/app + ubi0_3 + ubi0_4）、旧配置安全迁移与重启固化
python3 tools/flash_full_firmware.py
```

### 方式三：免刷机热部署模式（仅更新 `/var/app` 应用层）

在不触动底层 UBI 闪存与启动槽位的前提下，仅将新版 Web 控制台、插件引擎与系统调优脚本推送到可写的 `/var/app`：

```bash
./deploy_ripple.sh
# 或指定主机地址直接部署：
python3 tools/deploy_system.py deploy --host 192.168.10.1
```

<details>
<summary>手动终端刷入步骤（flash_slot1.sh）</summary>

1. 将 `ubi0_3_k1_kernel.uImage`、`ubi0_4_r1_mod.squashfs` 与 `firmware/flash_slot1.sh` 上传至路由器 `/tmp`。
2. 仅预检不写入：
   ```sh
   sh /tmp/flash_slot1.sh check /tmp/ubi0_3_k1_kernel.uImage /tmp/ubi0_4_r1_mod.squashfs
   ```
3. 正式刷写至 Slot 1：
   ```sh
   sh /tmp/flash_slot1.sh flash /tmp/ubi0_3_k1_kernel.uImage /tmp/ubi0_4_r1_mod.squashfs
   ```
4. 重启恢复连接后执行 `/bin/confirm_keep.sh` 完成固化。

</details>

---

## 仓库目录结构

```text
MR3000D-CIq-Realtek-RippleMod/
├── AI_PROMPT_CONTEXT.md       # 面向开发者与 AI 的硬件/分区/工具链上下文说明
├── LICENSE                    # MIT 开源许可证
├── THIRD_PARTY_NOTICES.md     # BusyBox / Dropbear 等第三方开源组件声明
├── deploy_ripple.sh           # 一键应用层热部署入口脚本
├── bin/                       # MIPS32 大端序静态二进制 (busybox/dropbear/ripple_api_daemon) 及 C 源码
├── core_system/               # 开机引导 (user.sh)、运行时脚本、网络/射频调优与默认配置
├── firmware/                  # 路由器端 Slot 1 刷写与安全守护脚本 (flash_slot1.sh / guards/)
├── plugin_engine/             # 通用插件生命周期管理 (plugin_manager.sh) 与 RPC 分发器
├── plugins/                   # 内置通用插件 (hosts_adblock_dns / custom_userscript / entware_package_mgr)
├── tools/                     # 宿主机构建、刷机、热部署与救援工具链 (零第三方 Python 依赖)
└── web/                       # 轻量化路由器 Web 控制台 (HTML/CSS/JS + api.cgi)
```

---

## 已知工程边界与注意事项

1. **C 守护进程重编译提醒**：`bin/ripple_api_daemon.c` 已在源码层面修补 POST `--raw-json-file` 请求透传（取消 2048 B 限制与单引号替换）、参数白名单校验、`SIGPIPE` 防护与安全修复；仓库中预编的 `bin/ripple_api_daemon` 二进制需在拥有 MIPS32 大端序交叉工具链环境下重新编译后方可在路由器端完整生效新版 C 特性。
2. **内核队列能力约束**：原厂 Linux 5.10.70 内核未启用 `CONFIG_NET_ACT_MIRRED`、`CAKE`、`fq_codel`；切勿对承载 ASIC–CPU 总线的根接口 `eth0` 或网桥 `br0` 配置会破坏 HWNAT 转发的整形队列。
3. **射频进阶调优为按需启用**：`v0.2.3` 默认关闭高风险无线参数以保 7×24 小时稳定性；有需求的用户可自行编辑 `/var/app/conf/wifi_tuning.conf` 分项测试开启。
4. **双槽共享 `/var/app`**：Slot 0 与 Slot 1 共用 `/var/app` 可写分区，切回原厂 Slot 0 不会自动清理 `/var/app` 中的扩展文件。

---

## 开源许可

- 本项目源码与脚本采用 [MIT 许可证](LICENSE)。
- 集成的第三方二进制工具（BusyBox、Dropbear 等）遵循其各自的原开源协议，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
