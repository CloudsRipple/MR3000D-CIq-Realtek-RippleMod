# MR3000D-CIq-Realtek-RippleMod

CMCC MR3000D-CIq（Realtek RTL8198D）的轻量插件引擎与 Web 控制台。

- 插件引擎：每个插件含 `start.sh` / `stop.sh` / `status.sh` / `api.sh` / `manifest.json`，Web 通过 `api.cgi?action=plugin_call` 调用。
- 内置插件：DNS 去广告 / 自定义 Hosts、开机自定义脚本、Entware 软件包管理。
- 管理界面：`web/`，由 `bin/ripple_api_daemon`（8080 端口）提供。

## 下载

固件、刷机脚本和套件包见 [Releases](https://github.com/CloudsRipple/MR3000D-CIq-Realtek-RippleMod/releases/latest)。

## 部署（免刷机）

电脑与路由器直连，在仓库根目录执行：

```bash
./deploy_ripple.sh
```

完成后访问 `http://192.168.10.1/`。

## 免责声明

刷机有风险，请先备份并确认设备型号。按现状提供，使用后果自负。

## 许可

原创代码采用 [MIT](LICENSE)；第三方组件与厂商固件见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 自行构建固件

需要自备原厂 rootfs 解包目录和原厂备份（含 `ubi0_1_k0.uImage`），不随仓库分发：

```bash
python3 tools/build_firmware.py --rootfs <原厂rootfs目录> --backup-dir <原厂备份目录>
```

## 许可证

自有代码使用 [MIT](LICENSE)。内置的 BusyBox（GPL-2.0）、Dropbear 等第三方组件见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
