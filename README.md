# MR3000D-CIq-Realtek-RippleMod

CMCC MR3000D-CIq（Realtek RTL8198D，128 MiB SPI NAND）的第三方 ROM。基于原厂固件，移除厂商遥测与强制升级，加入插件系统和 Web 控制台。

- 双槽位安装：刷入 Slot 1，Slot 0 保留原厂系统；刷入后 90 秒内不确认会自动回滚。
- 插件系统，内置 DNS 去广告 / 自定义 Hosts、开机自定义脚本、Entware 软件包管理。
- Web 控制台：`http://192.168.10.1/`。

## 安装

1. 在 [Releases](https://github.com/CloudsRipple/MR3000D-CIq-Realtek-RippleMod/releases/latest) 下载 `ubi0_3_k1_kernel.uImage`、`ubi0_4_r1_mod.squashfs`、`MD5SUMS`、`flash_slot1.sh`。
2. 开启 Telnet：`python3 tools/unlock_telnet.py`。
3. 把四个文件放到路由器同一目录（如 `/tmp`），先检查再刷入：

```sh
sh flash_slot1.sh check ubi0_3_k1_kernel.uImage ubi0_4_r1_mod.squashfs
sh flash_slot1.sh flash ubi0_3_k1_kernel.uImage ubi0_4_r1_mod.squashfs
```

4. 重启进入新系统后，90 秒内执行 `/bin/confirm_keep.sh` 确认保留。

## 刷入限制

`flash_slot1.sh` 只写 `ubi_k1` / `ubi_r1` 两个卷，不碰 bootloader 和 env。以下任一项不符就拒绝刷入：

- 内核为 5.10.70、MIPS 架构；
- MTD 布局为 `boot 768K / env / env2 / static_conf / ubi_device 127360K`，擦除块 128 KiB；
- UBI 页 2048 B，8 个卷的名称与大小和原厂一致；
- 当前运行在 Slot 0（`sw_active=0`）；
- 镜像类型、大小和 `MD5SUMS` 校验通过。

## 热部署

已有系统上只更新 `/var/app` 里的套件，不写闪存：

```bash
./deploy_ripple.sh
```

## 自行构建固件

需要自备原厂 rootfs 解包目录和原厂备份（含 `ubi0_1_k0.uImage`），它们不随仓库分发：

```bash
python3 tools/build_firmware.py --rootfs <原厂rootfs目录> --backup-dir <原厂备份目录>
```

## 免责声明与许可

刷机有风险，请先备份并确认设备型号。按现状提供，使用后果自负。

原创代码采用 [MIT](LICENSE)；第三方组件与厂商固件见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
