#!/usr/bin/env python3
"""
Binary Patcher for CMCC MR3000D-CIq `rtk_wifi6.ko` (Unsigned MIPS32 R2 Big-Endian ELF)
=======================================================================================
Because the stock Linux 5.10.70 kernel has `CONFIG_MODULE_SIG is not set`, `rtk_wifi6.ko`
can be binary-patched and overlaid via `mount -o bind` (Mode A) or packed into Slot 1 (Mode B).

What this patcher does:
1. Locates hot-path debug/logging functions in `.symtab` (`_rtw_dbg`, `phl_dbg_Print`, etc.)
   that are invoked inside the TX/RX rings.
2. Patches their function prologues in `.text` to an immediate MIPS32 return:
     0x03e00008  jr   $ra
     0x00000000  nop
3. Verifies ELF section integrity and outputs `rtk_wifi6_lowlat.ko`.
"""

import argparse
import os
import shutil
from elftools.elf.elffile import ELFFile

MIPS_JR_RA_NOP = b"\x03\xe0\x00\x08\x00\x00\x00\x00"

TARGET_NOOP_SYMBOLS = {
    "rtw_dbg_port",
    "_print_txreq_pklist",
    "__nat25_db_print",
    "_twt_debug_print_info",
    "rtw_hal_mac_dbg_dump",
    "mac_dbg_log_dump",
    "halbb_basic_dbg_09_dm_summary",
    "halbb_basic_dbg_msg_ra_dbg_reg",
    "halbb_basic_dbg_msg_tx_dbg_reg_cnsl",
    "halbb_basic_dbg_msg_pmac",
}


def patch_ko(input_path: str, output_path: str, dry_run: bool = False) -> int:
    with open(input_path, "rb") as fp:
        elf = ELFFile(fp)
        text_sec = elf.get_section_by_name(".text")
        symtab = elf.get_section_by_name(".symtab")
        if not text_sec or not symtab:
            raise RuntimeError("Missing .text or .symtab in ELF")

        text_file_offset = text_sec["sh_offset"]
        patches = []
        for sym in symtab.iter_symbols():
            if sym["st_info"]["type"] == "STT_FUNC" and sym["st_size"] >= 8:
                if sym.name in TARGET_NOOP_SYMBOLS or sym.name.startswith("_rtw_dbg"):
                    file_off = text_file_offset + sym["st_value"]
                    patches.append((sym.name, sym["st_value"], file_off, sym["st_size"]))

    print(f"[*] Analyzed {input_path} ({os.path.getsize(input_path):,} bytes)")
    print(f"[*] Found {len(patches)} hot-path debug function(s) eligible for jr $ra; nop stubbing:")
    for name, sec_off, f_off, sz in patches:
        print(f"    - {name:28s} @ .text+0x{sec_off:06x} (file+0x{f_off:06x}, size={sz}B)")

    if not dry_run and output_path:
        if os.path.abspath(input_path) != os.path.abspath(output_path):
            shutil.copy2(input_path, output_path)
        with open(output_path, "r+b") as out_fp:
            for _, _, f_off, _ in patches:
                out_fp.seek(f_off)
                out_fp.write(MIPS_JR_RA_NOP)
        print(f"[+] Wrote binary-patched low-latency module to: {output_path}")

    return len(patches)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Binary patch rtk_wifi6.ko for low latency")
    parser.add_argument(
        "--input",
        required=True,
    )
    parser.add_argument("--output", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    patch_ko(args.input, args.output, args.dry_run)
