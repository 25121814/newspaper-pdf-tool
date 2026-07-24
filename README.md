# Newspaper PDF Tool

报纸 PDF 下载与合并工具 v2.6.6

在线主页: [[https://newspaper-pdf-tool-25121815-25121815s-projects.vercel.app](https://newspaper-pdf-tool-25121815-25121815s-projects.vercel.app)]
## 功能

- 报纸在线预览（内置 WebEngine 浏览器）
- PDF 自动爬取与下载（后台线程，不阻塞界面）
- 多 PDF 智能合并（qpdf / Ghostscript / pypdf / PyPDF2 多重回退，优先 C 原生加速）
- 首页固定免责声明（居中两行显示）
- URL 根据当前日期自动生成，非每日出版物自动回退到最近一期
- 自定义下载路径
- Windows (.exe) + Linux (.deb) 双平台

## 支持的报纸

- 人民日报
- 湖南日报
- 讽刺与幽默
- 经济日报
- 学习时报
- 工人日报
- 中国证券报

支持手动添加任意报纸网址

## 安装

### Windows

下载 `newspaper-pdf-tool_2.6.6_x64.exe` 直接运行。
通过网盘分享的文件：报纸
链接: https://pan.baidu.com/s/1OzRN73obwe3i5SXJOE1vvg?pwd=52pj 提取码: 52pj

### 银河麒麟 / Linux

```bash
sudo dpkg -i newspaper-pdf-tool_2.6.6_arm64.deb
sudo apt-get install -f
```

启动: `newspaper-pdf-tool` 或在应用菜单搜索「报纸PDF工具」

下载地址：
通过网盘分享的文件：报纸
链接: https://pan.baidu.com/s/1OzRN73obwe3i5SXJOE1vvg?pwd=52pj 提取码: 52pj

### 系统要求

- **Linux**: Python 3.8+, PyQt5, QtWebEngine, libffi8
- **Windows**: Windows 10/11

## 项目结构

```
newspaper-pdf-tool/
├── rmrb.py                     # 主程序
├── websites.json               # 报纸网址配置
├── ico.ico                     # 应用图标
├── icon.png                    # PNG 图标
├── build_deb_windows.py        # Windows 上构建 .deb 的脚本
├── newspaper-pdf-tool_2.6.6_arm64.deb  # Linux 安装包
└── .gitignore
```

## 构建

### Windows .exe

```bash
pip install pyinstaller
pyinstaller rmrb.spec
```

### Linux .deb (在 Windows 上构建)

```bash
python build_deb_windows.py
```

## 技术栈

Python 3.8+ / PyQt5 / QtWebEngine / pypdf / requests / BeautifulSoup4

## 常见问题
双击没反应 / 终端报 ImportError: No module named PyQt5 → 执行 sudo apt install python3-pyqt5（postinst 的自动安装在该机未成功）。
界面能开，但右侧报纸网页空白 → sudo apt install python3-pyqt5.qtwebengine（预览为可选功能，不影响下载合并）。
合并几十个 PDF 特别慢 → sudo apt install qpdf，重启程序后合并走 C 原生引擎，提速数十倍。
卸载 → sudo apt remove newspaper-pdf-tool（用户配置 ~/.config/newspaper-pdf-tool/ 会保留，如需彻底清理手动删除该目录）。

## 联系

欢迎通过 GitHub Issue 反馈问题。
