"""
在 Windows 上直接构建 newspaper-pdf-tool 的 .deb 安装包（v4 - 修复权限问题）。

改进：
  - 所有 Python 依赖（requests, bs4, pypdf, urllib3 等）以 wheel 解包形式
    内嵌到 /opt/newspaper-pdf-tool/libs/ 中
  - wrapper 脚本设置 NEWSPAPER_PDF_TOOL_HOME 环境变量，
    确保 rmrb.py 将配置写入用户目录而非 /opt/
  - 声明 libffi8 | libffi7 系统依赖（解决 libffi.so.7 报错）

输出: newspaper-pdf-tool_2.2.0_all.deb
"""

import io
import os
import sys
import tarfile
import zipfile
import time
import glob

# ---- 配置 ----
PKG = "newspaper-pdf-tool"
VER = "2.2.0"
ARCH = "all"

BASE = os.path.dirname(os.path.abspath(__file__))
SRC_PY      = os.path.join(BASE, "source", "rmrb.py")
SRC_JSON    = os.path.join(BASE, "source", "websites.json")
SRC_ICO     = os.path.join(BASE, "source", "ico.ico")
SRC_ICON_PNG = os.path.join(BASE, "source", "icon.png")
WHEEL_DIR = os.path.join(BASE, "wheels")

# ---- 文件内容 ----

CONTROL = f"""\
Package: {PKG}
Version: {VER}
Section: utils
Priority: optional
Architecture: {ARCH}
Depends: python3 (>= 3.8), python3-pyqt5, python3-pyqt5.qtwebengine, libffi8 | libffi7
Installed-Size: 2500
Maintainer: Newspaper PDF Tool <25121814@qq.com>
Description: 报纸 PDF 爬取与合并工具
 赛博朋克风格桌面应用，支持报纸网站预览、PDF 自动爬取下载与智能合并。
 内置人民日报、湖南日报、经济日报等多家报纸，URL 根据当前日期自动生成。
 所有 Python 依赖已内嵌，无需联网安装。
 支持银河麒麟 / 统信 UOS / Ubuntu 等基于 Debian 的 Linux 发行版。
"""

DESKTOP = f"""\
[Desktop Entry]
Name=报纸PDF工具
Name[en]=Newspaper PDF Tool
Comment=报纸 PDF 爬取与合并工具
Exec={PKG}
Icon={PKG}
Terminal=false
Type=Application
Categories=Office;Utility;
StartupNotify=true
"""

# wrapper 脚本：设置环境变量 + PYTHONPATH 指向内嵌的 libs 目录
WRAPPER = f"""\
#!/bin/bash
# newspaper-pdf-tool launcher
# 设置 NEWSPAPER_PDF_TOOL_HOME 让程序将配置写入用户目录而非 /opt/
# 优先使用内嵌 Python 依赖，避免系统包冲突

export NEWSPAPER_PDF_TOOL_HOME=1

LIBS="/opt/{PKG}/libs"
if [ -d "$LIBS" ]; then
    export PYTHONPATH="$LIBS"
fi
export PYTHONDONTWRITEBYTECODE=1
exec python3 -W ignore::ImportWarning /opt/{PKG}/rmrb.py "$@"
"""

POSTINST = f"""\
#!/bin/bash
set -e

# 清理旧版（v2.1）残留在 /opt/ 下的用户数据（旧版错误地写入 /opt/）
rm -f /opt/{PKG}/app.log 2>/dev/null || true
rm -f /opt/{PKG}/config.json 2>/dev/null || true
# 注意：不删除 /opt/{PKG}/websites.json，它是安装配置副本

# 清理旧版安装残留的 pip 包（旧版 postinst 会 pip install，可能留下 broken 包）
pip3 uninstall -y --break-system-packages requests beautifulsoup4 pypdf2 pypdf urllib3 certifi idna charset-normalizer soupsieve 2>/dev/null || true
pip3 uninstall -y --user requests beautifulsoup4 pypdf2 pypdf urllib3 certifi idna charset-normalizer soupsieve 2>/dev/null || true

# 设置权限
chmod +x /usr/bin/{PKG} 2>/dev/null || true
chmod +x /opt/{PKG}/rmrb.py 2>/dev/null || true

# 更新桌面数据库
update-desktop-database /usr/share/applications/ 2>/dev/null || true
gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true

echo ""
echo "========================================"
echo "  {PKG} v{VER} 安装完成！"
echo "========================================"
echo ""
echo "  启动方式："
echo "    1. 应用菜单搜索「报纸PDF工具」"
echo "    2. 终端输入 {PKG}"
echo ""
echo "  配置文件: ~/.config/{PKG}/"
echo ""
"""

PRERM = f"""\
#!/bin/bash
rm -f /usr/bin/{PKG} 2>/dev/null || true
"""


# ---- 工具函数 ----

def make_tar_gz(files: dict[str, bytes], dirs: list[str] | None = None) -> bytes:
    """将 {路径: 内容} 打成 tar.gz，支持显式目录条目。"""
    buf = io.BytesIO()
    now = int(time.time())
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if dirs:
            for d in dirs:
                info = tarfile.TarInfo(name=d)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.mtime = now
                info.uid = 0
                info.gid = 0
                info.uname = "root"
                info.gname = "root"
                tar.addfile(info)
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = now
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            base = name.rsplit("/", 1)[-1]
            if base in ("postinst", "prerm", "preinst", "postrm"):
                info.mode = 0o755
            elif base == PKG and "/bin/" in name:
                info.mode = 0o755
            elif name.endswith("/wrapper"):
                info.mode = 0o755
            else:
                info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _collect_dirs(file_paths: list[str]) -> list[str]:
    """从文件路径列表自动收集所有父目录。"""
    dirs = set()
    for p in file_paths:
        parts = p.replace("\\", "/").split("/")
        for i in range(1, len(parts)):
            d = "/".join(parts[:i]) + "/"
            dirs.add(d)
    return sorted(dirs, key=len)


def ar_write_entry(buf: io.BytesIO, name: str, data: bytes, mode: int = 0o100644):
    """向 ar 归档追加一个条目。"""
    mtime = str(int(time.time())).encode().ljust(12)
    uid = b"0     "
    gid = b"0     "
    mode_b = f"{mode:o}".encode().ljust(8)
    size_b = str(len(data)).encode().ljust(10)
    magic = b"`\n"
    header = name.encode().ljust(16) + mtime + uid + gid + mode_b + size_b + magic
    assert len(header) == 60
    buf.write(header)
    buf.write(data)
    if len(data) % 2 != 0:
        buf.write(b"\n")


def extract_wheels_to_dict(wheel_dir: str, prefix: str) -> dict[str, bytes]:
    """
    解压 wheel_dir 下所有 .whl 文件，返回 {prefix/相对路径: 内容}。
    .whl 就是 zip 文件，直接解压即可。
    """
    result = {}
    whl_files = glob.glob(os.path.join(wheel_dir, "*.whl"))
    if not whl_files:
        print(f"  [警告] wheels 目录为空: {wheel_dir}")
        return result

    # 需要跳过的文件：可能触发系统上 broken C 扩展的模块
    _SKIP_PATTERNS = [
        "bs4/builder/_lxml.py",      # 依赖 lxml → libffi
        "bs4/builder/_html5lib.py",  # 依赖 html5lib
        "_cffi",                     # cffi C 扩展
    ]

    for whl_path in sorted(whl_files):
        whl_name = os.path.basename(whl_path)
        skipped = 0
        print(f"  解压: {whl_name}")
        with zipfile.ZipFile(whl_path, "r") as zf:
            for zi in zf.infolist():
                if ".dist-info/" in zi.filename:
                    continue
                if zi.is_dir():
                    continue
                if "__pycache__" in zi.filename:
                    continue
                # 跳过可能触发 C 扩展的模块
                fname = zi.filename.replace("\\", "/")
                if any(p in fname for p in _SKIP_PATTERNS):
                    skipped += 1
                    continue
                target = f"{prefix}/{zi.filename}"
                target = target.replace("\\", "/")
                while "//" in target:
                    target = target.replace("//", "/")
                result[target] = zf.read(zi.filename)

        if skipped:
            print(f"    (跳过 {skipped} 个 C 扩展相关文件)")

    return result


def build_deb(output_path: str):
    """构建 .deb 文件。"""
    print("读取源文件...")
    with open(SRC_PY, "rb") as f:
        rmrb_py = f.read()
    with open(SRC_JSON, "rb") as f:
        websites_json = f.read()
    with open(SRC_ICO, "rb") as f:
        ico_data = f.read()

    # 图标：优先使用预转换的 PNG，否则用 Pillow 从 ico 转换
    icon_png = None
    if os.path.exists(SRC_ICON_PNG):
        with open(SRC_ICON_PNG, "rb") as f:
            icon_png = f.read()
        print(f"  图标: 使用预转换 icon.png ({len(icon_png)} bytes)")
    else:
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(ico_data))
            png_buf = io.BytesIO()
            img.save(png_buf, "PNG")
            icon_png = png_buf.getvalue()
            print(f"  图标: ico -> png ({len(icon_png)} bytes)")
        except Exception:
            print("  [提示] Pillow 不可用，直接使用 .ico 图标")

    # 解压所有 wheel 到 libs/
    print("\n解压 Python 依赖 wheels...")
    libs_prefix = f"./opt/{PKG}/libs"
    lib_files = extract_wheels_to_dict(WHEEL_DIR, libs_prefix)
    print(f"  共 {len(lib_files)} 个库文件")

    # ---- control.tar.gz ----
    print("\n生成 control.tar.gz...")
    control_files = {
        "control": CONTROL.encode("utf-8"),
        "postinst": POSTINST.encode("utf-8"),
        "prerm": PRERM.encode("utf-8"),
    }
    control_tar = make_tar_gz(control_files)

    # ---- data.tar.gz ----
    print("生成 data.tar.gz...")
    data_files = {
        f"./opt/{PKG}/rmrb.py": rmrb_py,
        f"./opt/{PKG}/websites.json": websites_json,
        f"./usr/bin/{PKG}": WRAPPER.encode("utf-8"),
        f"./usr/share/applications/{PKG}.desktop": DESKTOP.encode("utf-8"),
    }
    if icon_png:
        # 安装多种标准尺寸的 PNG 图标，确保各种桌面环境都能正确显示
        data_files[f"./usr/share/icons/hicolor/48x48/apps/{PKG}.png"] = icon_png
        data_files[f"./usr/share/icons/hicolor/64x64/apps/{PKG}.png"] = icon_png
        data_files[f"./usr/share/icons/hicolor/128x128/apps/{PKG}.png"] = icon_png
        # 同时安装到 pixmaps 作为后备
        data_files[f"./usr/share/pixmaps/{PKG}.png"] = icon_png
    else:
        data_files[f"./usr/share/pixmaps/{PKG}.ico"] = ico_data

    # 加入所有库文件
    data_files.update(lib_files)

    # 自动收集目录
    data_dirs = _collect_dirs(list(data_files.keys()))
    print(f"  文件: {len(data_files)} 个")
    print(f"  目录: {len(data_dirs)} 个")

    data_tar = make_tar_gz(data_files, dirs=data_dirs)

    # ---- 组装 .deb ----
    print("\n组装 .deb 包...")
    deb_buf = io.BytesIO()
    deb_buf.write(b"!<arch>\n")
    ar_write_entry(deb_buf, "debian-binary", b"2.0\n")
    ar_write_entry(deb_buf, "control.tar.gz", control_tar)
    ar_write_entry(deb_buf, "data.tar.gz", data_tar)

    with open(output_path, "wb") as f:
        f.write(deb_buf.getvalue())

    size_kb = len(deb_buf.getvalue()) / 1024
    print(f"")
    print(f"==============================================")
    print(f"  构建成功！")
    print(f"==============================================")
    print(f"")
    print(f"  输出: {output_path}")
    print(f"  大小: {size_kb:.1f} KB")
    print(f"  架构: {ARCH} (Python 源码 + 纯 Python 依赖)")
    print(f"  内嵌依赖: requests, bs4, pypdf, urllib3, certifi, idna,")
    print(f"           charset-normalizer, soupsieve")
    print(f"")
    print(f"  在银河麒麟上安装：")
    print(f"    sudo dpkg -i {os.path.basename(output_path)}")
    print(f"    sudo apt-get install -f")
    print(f"")


if __name__ == "__main__":
    out = os.path.join(BASE, f"{PKG}_{VER}_{ARCH}.deb")
    build_deb(out)
