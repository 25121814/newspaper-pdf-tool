# Newspaper PDF Tool

报纸 PDF 爬取与合并工具 v2.2.0

在线主页: [[https://newspaper-pdf-tool-25121815-25121815s-projects.vercel.app](https://newspaper-pdf-tool-25121815-25121815s-projects.vercel.app)]
## 功能

- 报纸在线预览（内置 WebEngine 浏览器）
- PDF 自动爬取与下载（后台线程，不阻塞界面）
- 多 PDF 智能合并（pypdf / PyPDF2 / Ghostscript 多重回退）
- URL 根据当前日期自动生成，非每日出版物自动回退到最近一期
- 自定义下载路径
- Windows (.exe) + Linux (.deb) 双平台

## 支持的报纸

- 人民日报
- 湖南日报
- 讽刺与幽默
- 学习时报
- 工人日报

支持手动添加任意报纸网址

## 安装

### Windows

下载 `NewspaperPDFTool.exe` 直接运行。
通过网盘分享的文件：报纸
链接: https://pan.baidu.com/s/1BBq7yAhafSGJxUp7kNPx5Q?pwd=cvis 提取码: cvis

### 银河麒麟 / Linux

```bash
sudo dpkg -i newspaper-pdf-tool_2.2.0_all.deb
sudo apt-get install -f
```

启动: `newspaper-pdf-tool` 或在应用菜单搜索「报纸PDF工具」

下载地址：通过网盘分享的文件：报纸
链接: https://pan.baidu.com/s/1BBq7yAhafSGJxUp7kNPx5Q?pwd=cvis 提取码: cvis

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
├── newspaper-pdf-tool_2.2.0_all.deb  # Linux 安装包
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

## 联系

欢迎通过 GitHub Issue 反馈问题。
