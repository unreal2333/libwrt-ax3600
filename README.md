# LibWrt 25.12-nss + AX3600 大分区（240 MB 单 UBI）

在保持 u-boot_mod + 240 MB 单 UBI 布局的前提下，把 Kwrt 换成 LibWrt
（IPQ807X 满血 NSS，含 Wi-Fi offload）。

**本次是全新安装（`sysupgrade -n`），不保留任何旧配置。**

## 目录

| 路径 | 作用 |
|---|---|
| `patches/ax3600-bigpart.py` | 把 AX3600 从「官方展开布局」改成「大分区布局」，带断言 |
| `configs/ax3600_nss_defconfig` | 编译配置（设备 + 中文 LuCI + OpenClash 运行时 kmod + zram） |
| `.github/workflows/build.yml` | 自动编译（ccache / dl 缓存 / DTB 产物校验） |

## 目标布局（与当前 Kwrt 实测一致）

```
分区        offset      size
rootfs      0x0a00000   0xf000000   (240 MiB)
rsvd0       0xfa00000   0x80000     (512 KiB)

UBI 卷：kernel(0) / rootfs(1) / rootfs_data(2)
DTB bootargs-append: root=/dev/ubiblock0_1    ← 卷 1（官方布局是卷 0，这是最易踩的坑）
```

## 一、推仓并触发构建

```sh
cd libwrt-ax3600
git init -b main
git add -A
git commit -m "AX3600 big-partition LibWrt NSS build"
git remote add origin git@github.com:<你>/libwrt-ax3600.git
git push -u origin main
```

GitHub → Actions → `build-ax3600-nss` → **Run workflow**。

> 建议把仓库设为 **public**：不受 Actions 免费额度限制，runner 为 4 核，构建快约一倍。
> 首次约 60–90 分钟；有了 ccache 缓存后约 15–30 分钟。

## 二、构建产物（CI 会自动校验）

`Actions → 该次运行 → Artifacts → libwrt-ax3600-nss`

- `openwrt-qualcommax-ipq807x-xiaomi_ax3600-squashfs-sysupgrade.bin` ← 刷这个
- `sha256sums` ← 校验用

CI 里有两道自动校验，任意一道失败就说明不能刷：

1. `Verify patched DTS source`：源码级检查三个锚点
2. `Verify DTB inside build tree`：**从编译产物里反编译 DTB**，确认真正烧进固件的分区是
   `0xf000000` / `0xfa00000` / `ubiblock0_1`

## 三、刷机

```sh
# 本机
scp openwrt-...-squashfs-sysupgrade.bin root@192.168.1.1:/tmp/new.bin

# 路由器上（-n = 不保留配置，全新安装）
sha256sum /tmp/new.bin
sysupgrade -n /tmp/new.bin
```

设备会自动重启，约 2–4 分钟后 `192.168.1.1` 可访问。

## 四、刷完验证（按顺序）

```sh
cat /proc/cmdline
# 期望包含：ubi.mtd=rootfs ... root=/dev/ubiblock0_1

cat /proc/mtd
# 期望：rootfs 大小 0xf000000(240M)，且没有 ubi_kernel

ubinfo -a | head -20
# 期望卷：kernel / rootfs / rootfs_data

lsmod | grep -c qca_nss
# 期望 > 0，说明 NSS 驱动加载了

dmesg | grep -iE 'nss|ecm|hppe'
free -m
```

## 登录

首次启动会执行 `/etc/uci-defaults/99-root-pw`，把 root 密码设成构建时注入的
crypt 哈希（`$1$` md5crypt，与 OpenWrt 默认格式一致）对应的口令。

- 明文密码**不写入镜像**，只存在于 GitHub Secret `ROOT_PW_HASH` 或 `assets/root-pw-hash` 的哈希里
- 登录后建议立刻在 LuCI 改密码；改完把新哈希写进 Secret，以后重刷自动生效
- 生成新哈希（在任意 OpenWrt 设备上）：
  ```sh
  python3 -c "import crypt,getpass;print(crypt.crypt(getpass.getpass(),crypt.mksalt(crypt.METHOD_MD5)))"
  ```

## 五、安装 OpenClash（本体后装，kmod 已内置）

先确认包管理器是哪个（25.12 正在 opkg → apk 切换）：

```sh
which apk opkg
```

- **opkg**：
  ```sh
  opkg update
  opkg install luci-app-openclash
  ```
- **apk**：
  ```sh
  apk update
  apk add luci-app-openclash
  ```

若 feed 里没有 openclash，从 GitHub release 下载 ipk/apk 后本地安装：

```sh
opkg install /tmp/luci-app-openclash_*.ipk
```

## 回滚

断电 → 按住 reset → 上电 → `http://192.168.1.1` → 上传 Kwrt / 任意可开机镜像。

## 已知风险

1. 内核 6.12 + NSS + 自改分区，此组合无人验证过，属于首次尝试。
2. NSS 常驻会增加内存占用；本机此前出现过 OpenClash 被 OOM kill。
   已在 defconfig 里打开 `zram-swap`，但刷完仍建议先观察 `free -m`。
3. 若构建产物校验不通过，**不要刷**，先看 CI 日志里 DTB 那段输出的实际分区。
