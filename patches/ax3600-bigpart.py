#!/usr/bin/env python3
"""
把 LibWrt (25.12-nss) 的 Xiaomi AX3600 从「官方展开布局」改成
「大分区 / u-boot mod 布局」（单 UBI：kernel + rootfs + rootfs_data）。

用法（在 LibWrt 源码根目录的上一级执行）:
    python3 patches/ax3600-bigpart.py openwrt

改动点 3 处：
  1. ipq8071-ax3600.dtsi : ubi_kernel + rootfs 两个分区 -> 单个 rootfs(240M) + rsvd0
  2. ipq8071-ax3600.dtsi : bootargs-append root=/dev/ubiblock0_0 -> ubiblock0_1
  3. platform.sh         : xiaomi,ax3600 走 CI_UBIPART="rootfs"（单 UBI 升级）

任一处锚点找不到都会直接 exit 1，不会静默改错。
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "openwrt")
DTS = ROOT / "target/linux/qualcommax/files/arch/arm64/boot/dts/qcom/ipq8071-ax3600.dtsi"
PLAT = ROOT / "target/linux/qualcommax/ipq807x/base-files/lib/upgrade/platform.sh"


def die(msg):
    sys.exit("ERROR: " + msg)


# ---------------------------------------------------------------- 1) DTS 分区
dts = DTS.read_text()

new_parts = '''\t\t\t/* Large-partition (u-boot mod) layout:
\t\t\t * a single UBI partition holds kernel + rootfs + rootfs_data
\t\t\t * rootfs  : 0x0a00000 .. 0xfa00000 (240 MiB)
\t\t\t * rsvd0   : 0xfa00000 .. 0x1000000 (512 KiB)
\t\t\t */
\t\t\trootfs: partition@a00000 {
\t\t\t\tlabel = "rootfs";
\t\t\t\treg = <0xa00000 0xf000000>;
\t\t\t};

\t\t\tpartition@fa00000 {
\t\t\t\tlabel = "rsvd0";
\t\t\t\treg = <0xfa00000 0x80000>;
\t\t\t\tread-only;
\t\t\t};
'''

pat = re.compile(
    r"[ \t]*/\* Make the first rootfs a dedicated ubi partition for kernel \*/"
    r".*?label\s*=\s*\"rootfs\";\s*reg\s*=\s*<0x2dc0000 0xd240000>;\s*\};",
    re.S,
)
dts, n = pat.subn(new_parts, dts)
if n != 1:
    die("DTS 分区块锚点匹配到 %d 处（应为 1）" % n)

# ------------------------------------------------- 2) root= 指向 rootfs 卷(1)
dts, n = re.subn(
    r'(bootargs-append\s*=\s*" root=)/dev/ubiblock0_0"',
    r'\1/dev/ubiblock0_1"',
    dts,
)
if n != 1:
    die("bootargs-append 锚点匹配到 %d 处（应为 1）" % n)

DTS.write_text(dts)
print("[ok] DTS patched: %s" % DTS)

# ------------------------------------------------------- 3) platform.sh 升级臂
plat = PLAT.read_text()

cut = plat.find("platform_do_upgrade() {")
if cut < 0:
    die("找不到 platform_do_upgrade()")
head, body = plat[:cut], plat[cut:]

# 把 xiaomi,ax3600 从「两 UBI」分支里摘出来
body, n = re.subn(
    r"(\tredmi,ax6\|\\\n)\txiaomi,ax3600\|\\\n(\txiaomi,ax9000\))",
    r"\1\2",
    body,
)
if n != 1:
    die("platform.sh 的 redmi,ax6|xiaomi,ax3600|xiaomi,ax9000 分支锚点匹配到 %d 处" % n)

new_arm = (
    '\txiaomi,ax3600)\n'
    '\t\t# Large-partition (u-boot mod) layout:\n'
    '\t\t# kernel + rootfs live in ONE UBI, so write both to "rootfs"\n'
    '\t\tfw_setenv boot_wait on\n'
    '\t\tfw_setenv uart_en 1\n'
    '\t\tfw_setenv flag_boot_rootfs 0\n'
    '\t\tfw_setenv flag_last_success 0\n'
    '\t\tfw_setenv flag_boot_success 1\n'
    '\t\tCI_UBIPART="rootfs"\n'
    '\t\tnand_do_upgrade "$1"\n'
    '\t\t;;\n'
)

anchor = "\tredmi,ax6|\\\n"
pos = body.find(anchor)
if pos < 0:
    die("platform.sh 插入点（redmi,ax6 分支）未找到")

body = body[:pos] + new_arm + body[pos:]
PLAT.write_text(head + body)
print("[ok] platform.sh patched: %s" % PLAT)
print("done.")
