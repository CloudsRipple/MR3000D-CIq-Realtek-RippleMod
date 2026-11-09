# MR3000D-CIq Realtek RippleMod - AI Full Context & Architecture Reference

This document provides a concise, structured architecture summary for AI agents (such as Claude, ChatGPT, Gemini, Antigravity) reading this codebase.

## 1. Hardware & Platform
- **Device Model**: CMCC MR3000D-CIq (Realtek variant)
- **SoC**: Realtek RTL8198D Dual-Core, 4 hardware VPE threads (MIPS interAptiv V2.0, 1.0 GHz, MIPS32 Release 2, Big-Endian / MSB)
- **Linux Kernel**: Linux 5.10.70 SMP (`mips`)
- **RAM**: 256 MiB DDR3
- **Flash Storage**: 128 MiB SPI NAND Flash (Macronix MX35LF2G14AC)
  - Page size: 2048 Bytes
  - Physical Erase Block (PEB): 128 KiB
  - Logical Erase Block (LEB): 126976 Bytes (124 KiB)
- **Switch & HWNAT**: Realtek RTL9607C + FleetConntrack (`fc_core`) hardware NAT acceleration
- **Wireless Radios**:
  - 5 GHz: Realtek RTL8852CE (Wi-Fi 6 802.11ax, HE160, 2402 Mbps, 2T2R)
  - 2.4 GHz: Realtek RTL8192XBE (Wi-Fi 6 802.11ax, HE40, 574 Mbps, 2T2R)

## 2. Flash Layout & Safe Dual-Slot Partitioning
- **MTD Layout**:
  - `mtd0`: `boot` (768 KiB) - Factory Bootloader (DO NOT TOUCH)
  - `mtd1`: `env` (128 KiB) - U-Boot environment (DO NOT TOUCH)
  - `mtd2`: `env2` (128 KiB) - Redundant U-Boot environment
  - `mtd3`: `static_conf` (128 KiB) - Factory calibration & MAC
  - `mtd4`: `ubi_device` (127360 KiB) - Attached as `/dev/ubi0`
- **UBI Volumes**:
  - `ubi0_0`: `ubi_Config` (87 PEBs, ~10.5 MB, UBIFS)
  - `ubi0_1`: `ubi_k0` (83 PEBs, ~10 MB) - Slot 0 Stock Kernel
  - `ubi0_2`: `ubi_r0` (207 PEBs, ~25 MB) - Slot 0 Stock RootFS (SquashFS)
  - `ubi0_3`: `ubi_k1` (83 PEBs, ~10 MB) - Slot 1 RippleMod Kernel
  - `ubi0_4`: `ubi_r1` (207 PEBs, ~25 MB) - Slot 1 RippleMod RootFS
  - `ubi0_5`: `ubi_config_bak` (17 PEBs)
  - `ubi0_6`: `ubi_factory` (17 PEBs)
  - `ubi0_7`: `ubi_app` (248 PEBs, ~30 MB, UBIFS) - Mounted at `/var/app` (Writable user partition)

## 3. Directory Structure
- `tools/flash_router.py`: PC-side cross-platform flasher (Python 3 standard library only, zero dependencies).
- `web/`: Modern single-page web console (HTML/CSS/JS) and `api.cgi` RESTful endpoint.
- `bin/`: MIPS32 Big-Endian userland binaries (`busybox`, `dropbear`, `ripple_api_daemon`).
- `core_system/`: System startup, watchdog, and network scripts.
- `plugins/`: Modular plugins (`custom_userscript`, `hosts_adblock_dns`, `entware_package_mgr`).

## 4. Key Rules for Agents
- Dual-slot safety: Only write to Slot 1 (`/dev/ubi0_3` and `/dev/ubi0_4`). Never write to Slot 0 or MTD boot blocks.
- Endianness: MIPS32 Big-Endian (MSB). Do NOT cross-compile with `mipsel-` (little-endian) toolchains.
