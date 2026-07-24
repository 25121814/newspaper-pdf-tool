# 银河麒麟 / Debian 安装后操作清单（newspaper-pdf-tool v2.6.6）

> 适用包：`newspaper-pdf-tool_2.6.6_arm64.deb`（银河麒麟 V10 SP1 arm64 / 通用 Debian 系）
> 本文基于 deb 实际打包内容（control / postinst / wrapper 脚本）分析得出。

---

## 一、deb 安装时"自动做了什么"（无需手动跑）

执行 `sudo dpkg -i newspaper-pdf-tool_2.6.6_arm64.deb` 后，包内 `postinst` 脚本会自动执行：

1. **清理旧版残留**：删除 `/opt/newspaper-pdf-tool/app.log`、`config.json`（避免旧配置干扰）。
2. **卸载旧的 pip 安装库**（requests/bs4/pypdf2 等，容错，失败不阻塞）。
3. **尝试自动安装 Qt5 系统包**（容错，`|| true`，失败也不中断安装）：
   - `python3-pyqt5`（GUI 核心，必须）
   - `python3-pyqt5.qtwebengine`（网页预览，可选）
4. **设置执行权限**：`/usr/bin/newspaper-pdf-tool`、`/opt/newspaper-pdf-tool/rmrb.py`。
5. **注册桌面菜单**：写入 `.desktop`，刷新 `update-desktop-database` 与图标缓存。

安装程序本体落在：
- `/opt/newspaper-pdf-tool/rmrb.py` + `websites.json` + 内嵌 `libs/`（requests、bs4、PyPDF2、urllib3、certifi、idna、chardet、soupsieve 全部内嵌）
- `/usr/bin/newspaper-pdf-tool`（启动器，自动设置 PYTHONPATH 等环境变量）
- 桌面菜单项「报纸PDF工具」

---

## 二、你最关心的三个问题

### 1) 安装后是否需要执行额外命令或脚本？
**正常情况：不需要。** dpkg 会跑完 postinst，菜单里直接有图标。

唯一例外：若 PyQt5 没自动装成功（见下），需手动补一条（见第四部分）。

### 2) 是否有需要手动下载的依赖或支持文件？
**Python 依赖：已全部内嵌，无需联网下载（pip 不用管）。**

但有三样**系统级**组件 postinst 只"尝试"装、失败会静默跳过，可能需要你手动补：

| 组件 | 是否必需 | 缺失时表现 | 手动补装命令 |
|------|---------|-----------|-------------|
| **PyQt5**（`python3-pyqt5`） | ⚠️ **必需** | 程序启动即 `ImportError` 无法打开 | `sudo apt install python3-pyqt5` |
| **QtWebEngine**（`python3-pyqt5.qtwebengine`） | 可选 | 网页预览区变空白/提示，但下载+合并正常 | `sudo apt install python3-pyqt5.qtwebengine` |
| **qpdf / ghostscript** | 可选（影响性能） | 合并 PDF 回退到内嵌 PyPDF2，**麒麟上明显变慢** | `sudo apt install qpdf`（推荐）或 `sudo apt install ghostscript` |

> 说明：deb 的 `Depends` 字段**只写了 `python3`**，并未把 PyQt5 列为硬依赖，而是靠 postinst 用 apt 容错安装。若目标机 apt 源不可用 / 离线 / 包名不符，PyQt5 就会漏装——这是安装后最容易踩的坑。

### 3) 是否需要配置环境变量或启动服务？
**都不需要。**
- **环境变量**：启动器 `/usr/bin/newspaper-pdf-tool` 会自动 export `PYTHONPATH`、`NEWSPAPER_PDF_TOOL_HOME=1`、`PYTHONDONTWRITEBYTECODE=1`，用户无需手动配。
- **启动服务 / 守护进程**：无。它是桌面 GUI 程序，双击菜单图标或终端输入 `newspaper-pdf-tool` 即可。
- **配置文件**：首次运行时自动在 `~/.config/newspaper-pdf-tool/` 生成（websites.json、config.json、app.log、downloaded_pdfs/），无需预先创建。

---

## 三、完整安装后操作清单（照着做一遍）

```bash
# 1. 安装（必需）
sudo dpkg -i newspaper-pdf-tool_2.6.6_arm64.deb

# 2. 验证 PyQt5 已就绪（必需，缺失则程序打不开）
python3 -c "import PyQt5" 2>/dev/null && echo "PyQt5 OK" || sudo apt install python3-pyqt5

# 3. 【可选】启用网页预览（想要右侧报纸网页预览才需要）
python3 -c "from PyQt5 import QtWebEngineWidgets" 2>/dev/null && echo "WebEngine OK" || sudo apt install python3-pyqt5.qtwebengine

# 4. 【可选·强烈建议】加速合并（麒麟上不装会回退慢速 PyPDF2）
which qpdf >/dev/null 2>&1 && echo "qpdf OK" || sudo apt install qpdf

# 5. 启动
#    方式 A：应用菜单搜索「报纸PDF工具」点击
#    方式 B：终端输入
newspaper-pdf-tool
```

**首次运行后**：配置目录 `~/.config/newspaper-pdf-tool/` 自动生成，下载的 PDF 默认存于其中的 `downloaded_pdfs/`。

---

## 四、常见问题速查

- **双击没反应 / 终端报 ImportError: No module named PyQt5**
  → 执行 `sudo apt install python3-pyqt5`（postinst 的自动安装在该机未成功）。
- **界面能开，但右侧报纸网页空白**
  → `sudo apt install python3-pyqt5.qtwebengine`（预览为可选功能，不影响下载合并）。
- **合并几十个 PDF 特别慢**
  → `sudo apt install qpdf`，重启程序后合并走 C 原生引擎，提速数十倍。
- **卸载**
  → `sudo apt remove newspaper-pdf-tool`（用户配置 `~/.config/newspaper-pdf-tool/` 会保留，如需彻底清理手动删除该目录）。
