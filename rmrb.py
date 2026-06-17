"""
PDF 网页显示、爬取与合并工具 v2.2
===================================
赛博朋克风格桌面应用，支持：
  - 报纸网站预览与导航
  - PDF 自动爬取与下载（后台线程）
  - 多 PDF 智能合并
  - 网址动态管理（日期自动生成 + 索引页回退）

v2.2 改进：
  - 修复 Linux 系统安装时配置目录检测（PermissionError）
  - 配置/日志写入 ~/.config/newspaper-pdf-tool/，不再写入 /opt/
  - 首次运行自动从安装目录加载网址配置
  - 日志系统增加权限回退机制

v2.1 改进：
  - 修复经济日报 URL 模板（node_1.htm → node_01.html）
  - 讽刺与幽默等周期刊：当天无内容时自动回退到最近一期
  - 学习时报 SSL 证书问题兼容（verify=False 回退）
  - 下载完成后点击关闭自动打开合并后的 PDF
  - 新增下载路径选择按钮
"""

from __future__ import annotations

import sys
import os
import json
import re
import logging
import urllib3
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QListWidget, QSplitter, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QDialog, QFormLayout, QLineEdit, QListWidgetItem,
    QMessageBox, QLabel, QProgressBar, QTextEdit, QStatusBar, QFrame,
    QDialogButtonBox, QSizePolicy, QFileDialog
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import Qt, QUrl, QThread, pyqtSignal, QTimer

# ================================================================
#  常量 & 日志
# ================================================================

# 应用根目录（exe / 脚本所在目录）
APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))

# 配置目录：系统安装时存到用户目录，便携运行时存到程序目录
# 三种方式检测系统安装：
#   1. wrapper 脚本设置 NEWSPAPER_PDF_TOOL_HOME 环境变量
#   2. 程序位于 /opt/ 或 /usr/ 下（Linux 系统安装路径）
#   3. 可执行文件名为 newspaper-pdf-tool（直接调用 wrapper）
_BIN_STEMS = {"newspaper-pdf-tool", "newspaper_pdf_tool"}
_SYSTEM_INSTALL = False

if os.environ.get("NEWSPAPER_PDF_TOOL_HOME"):
    _SYSTEM_INSTALL = True
elif sys.platform.startswith("linux"):
    _app_norm = APP_DIR.replace("\\", "/")
    if _app_norm.startswith("/opt/") or _app_norm.startswith("/usr/"):
        _SYSTEM_INSTALL = True
    elif os.path.basename(sys.argv[0]) in _BIN_STEMS:
        _SYSTEM_INSTALL = True

if _SYSTEM_INSTALL:
    _CONFIG_DIR = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "newspaper-pdf-tool",
    )
    os.makedirs(_CONFIG_DIR, exist_ok=True)
else:
    _CONFIG_DIR = APP_DIR

WEBSITES_FILE = os.path.join(_CONFIG_DIR, "websites.json")
# 安装目录下的只读副本（首次运行时作为回退源）
_WEBSITES_FALLBACK = os.path.join(APP_DIR, "websites.json")
CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")
DEFAULT_DOWNLOAD_DIR = os.path.join(_CONFIG_DIR, "downloaded_pdfs")
LOG_FILE = os.path.join(_CONFIG_DIR, "app.log")

_log_handlers = [logging.StreamHandler()]
try:
    _log_handlers.insert(0, logging.FileHandler(LOG_FILE, encoding="utf-8"))
except (PermissionError, OSError):
    # 无法写入配置目录（不应该发生），尝试临时目录
    import tempfile
    _alt_log = os.path.join(tempfile.gettempdir(), "newspaper-pdf-tool.log")
    try:
        _log_handlers.insert(0, logging.FileHandler(_alt_log, encoding="utf-8"))
    except Exception:
        pass  # 只用 stderr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_log_handlers,
)
logger = logging.getLogger(__name__)

# 抑制 SSL 不安全请求警告（学习时报等站点证书问题）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 全局 requests 会话（带重试）
_http_session = requests.Session()
_http_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
})
_adapter = requests.adapters.HTTPAdapter(max_retries=3)
_http_session.mount("http://", _adapter)
_http_session.mount("https://", _adapter)


# ================================================================
#  工具函数
# ================================================================

def safe_filename(url: str) -> str:
    """从 URL 提取安全文件名，去除查询参数和非法字符。"""
    name = url.split("/")[-1].split("?")[0].split("#")[0]
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    return name or "unnamed.pdf"


def open_file(path: str) -> None:
    """跨平台打开文件：Windows 用 os.startfile，Linux 用 xdg-open。"""
    import subprocess
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def fetch_html(url: str, timeout: int = 20) -> str | None:
    """
    获取页面 HTML 文本，失败返回 None。
    对 SSL 证书问题自动回退 verify=False。
    """
    try:
        resp = _http_session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except requests.exceptions.SSLError:
        # SSL 证书问题 → 尝试不验证证书
        try:
            resp = _http_session.get(url, timeout=timeout, verify=False)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            logger.warning("获取页面失败(SSL回退也失败): %s -> %s", url, exc)
            return None
    except Exception as exc:
        logger.warning("获取页面失败: %s -> %s", url, exc)
        return None


def natural_sort_key(s: str):
    """自然排序键：将字符串中的数字按数值排序。"""
    m = re.search(r"(\d+)", s)
    if m:
        return (s[: m.start()].lower(), int(m.group(1)), s[m.end() :].lower())
    return (s.lower(),)


# ================================================================
#  动态 URL 生成 —— 不再使用硬编码日期
# ================================================================

def generate_newspaper_url(key: str, dt: datetime | None = None) -> str:
    """
    根据报纸标识和日期动态生成 URL。
    dt 默认为当天。每种报纸的 URL 模板来源于原始配置。
    """
    if dt is None:
        dt = datetime.now()

    Y, M, D = str(dt.year), f"{dt.month:02d}", f"{dt.day:02d}"

    if key == "rmrb":
        # 人民日报: .../pc/layout/YYYYMM/DD/node_01.html
        return f"http://paper.people.com.cn/rmrb/pc/layout/{Y}{M}/{D}/node_01.html"

    if key == "fcyym":
        # 讽刺与幽默: .../pc/layout/YYYYMM/DD/node_01.html（周五刊，可能非每日更新）
        return f"http://paper.people.com.cn/fcyym/pc/layout/{Y}{M}/{D}/node_01.html"

    if key == "hnrb":
        # 湖南日报: .../html/YYYY-MM/DD/node_201.htm
        return f"http://epaper.voc.com.cn/hnrb/html/{Y}-{M}/{D}/node_201.htm"

    if key == "jjrb":
        # 经济日报: .../pc/layout/YYYYMM/DD/node_01.html（已修复：node_1.htm → node_01.html）
        return f"http://paper.ce.cn/pc/layout/{Y}{M}/{D}/node_01.html"

    if key == "xxsb":
        # 学习时报: 每周一出刊，URL 含 ISO 周号 YYYY-WNN/nbs.D110000xxsb_A1.htm
        iso = dt.isocalendar()
        return (
            f"https://paper.cntheory.com/html/"
            f"{iso.year}-W{iso.week:02d}/nbs.D110000xxsb_A1.htm"
        )

    if key == "grrb":
        # 工人日报: 固定首页入口
        return "https://www.workercn.cn/papers/grrb/index.html"

    return ""


# 索引页 URL —— 当日期页返回 404 时，从索引页找最近一期
_INDEX_URLS = {
    "rmrb":   "http://paper.people.com.cn/rmrb/pc/layout/index.html",
    "fcyym":  "http://paper.people.com.cn/fcyym/pc/layout/index.html",
    "hnrb":   "http://epaper.voc.com.cn/hnrb/html/index.html",
    "jjrb":   "http://paper.ce.cn/pc/layout/index.html",
    "xxsb":   "",   # 学习时报无可用索引页
    "grrb":   "",   # 工人日报为固定 URL
}


def resolve_latest_url(key: str, url: str) -> str:
    """
    尝试访问 url，如果返回 404 则从索引页获取最近可用的一期 URL。
    对于非 404 的情况（如 SSL 错误），直接返回原 URL 让 web_view 自行处理。
    """
    try:
        resp = _http_session.get(url, timeout=10)
        if resp.status_code == 200:
            return url
        if resp.status_code != 404:
            return url  # 非 404 错误，不做回退
    except requests.exceptions.SSLError:
        return url  # SSL 问题，不做回退
    except Exception:
        return url

    # 404 → 尝试索引页
    index_url = _INDEX_URLS.get(key, "")
    if not index_url:
        return url

    html = fetch_html(index_url)
    if not html:
        return url

    soup = BeautifulSoup(html, "html.parser")
    # 查找索引页中第一个日期链接（形如 YYYYMM/DD/node_XX.html）
    pattern = re.compile(r"\d{6}/\d{2}/node_\d+\.html?")
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if pattern.search(href):
            latest = urljoin(index_url, href)
            logger.info("索引页回退: %s -> %s", url, latest)
            return latest

    return url


# 默认报纸配置（首次运行或重置时使用）
DEFAULT_WEBSITES = [
    {"name": "人民日报", "newspaper": "rmrb"},
    {"name": "湖南日报", "newspaper": "hnrb"},
    {"name": "讽刺与幽默", "newspaper": "fcyym"},
    {"name": "经济日报", "newspaper": "jjrb"},
    {"name": "学习时报", "newspaper": "xxsb"},
    {"name": "工人日报", "newspaper": "grrb"},
]


# ================================================================
#  用户配置（下载路径等）
# ================================================================

def load_user_config() -> dict:
    """加载用户配置。"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_user_config(cfg: dict):
    """保存用户配置。"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
    except Exception as exc:
        logger.error("保存配置失败: %s", exc)


# ================================================================
#  赛博朋克样式表
# ================================================================

CYBERPUNK_QSS = """
/* ---------- 全局 ---------- */
QMainWindow, QDialog {
    background-color: #ffffff;
    color: #000000;
}
QWidget {
    background-color: #ffffff;
    color: #000000;
}

/* ---------- 列表 ---------- */
QListWidget {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 4px;
    color: #000000;
    font-size: 14px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    padding: 8px 12px;
    margin: 1px 2px;
    border-radius: 3px;
    color: #000000;
}
QListWidget::item:hover {
    background-color: #e8e8e8;
    color: #000000;
}
QListWidget::item:selected {
    background-color: #cce0ff;
    color: #000000;
}

/* ---------- 按钮 ---------- */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #999999;
    border-radius: 4px;
    color: #000000;
    padding: 8px 16px;
    font-size: 13px;
    min-height: 18px;
}
QPushButton:hover {
    background-color: #e8e8e8;
    border-color: #000000;
}
QPushButton:pressed {
    background-color: #cccccc;
}
QPushButton#btnDanger {
    border-color: #cc0000;
    color: #cc0000;
}
QPushButton#btnDanger:hover {
    background-color: #ffe0e0;
}
QPushButton#btnPrimary {
    background-color: #000000;
    border-color: #000000;
    color: #ffffff;
    font-size: 14px;
    font-weight: bold;
}
QPushButton#btnPrimary:hover {
    background-color: #333333;
}
QPushButton#btnPath {
    border-color: #666666;
    color: #000000;
    font-size: 12px;
}
QPushButton#btnPath:hover {
    background-color: #e8e8e8;
}

/* ---------- 输入框 ---------- */
QLineEdit {
    background-color: #ffffff;
    border: 1px solid #999999;
    border-radius: 4px;
    color: #000000;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: #000000;
    selection-color: #ffffff;
}
QLineEdit:focus {
    border-color: #000000;
}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical {
    background: #ffffff;
    width: 8px;
    margin: 0;
    border: none;
}
QScrollBar::handle:vertical {
    background: #cccccc;
    min-height: 28px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #999999;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

/* ---------- 状态栏 ---------- */
QStatusBar {
    background-color: #ffffff;
    color: #000000;
    border-top: 1px solid #cccccc;
    font-size: 12px;
    padding: 2px 8px;
}

/* ---------- 进度条 ---------- */
QProgressBar {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 4px;
    text-align: center;
    color: #000000;
    font-weight: bold;
    min-height: 22px;
}
QProgressBar::chunk {
    background-color: #333333;
    border-radius: 3px;
}

/* ---------- 文本编辑（日志区） ---------- */
QTextEdit {
    background-color: #ffffff;
    border: 1px solid #cccccc;
    border-radius: 4px;
    color: #000000;
    font-family: Consolas, 'Courier New', monospace;
    font-size: 11px;
    padding: 4px;
}

/* ---------- 标签 ---------- */
QLabel {
    color: #000000;
    background: transparent;
}

/* ---------- 消息框 ---------- */
QMessageBox {
    background-color: #ffffff;
}
QMessageBox QLabel {
    color: #000000;
    font-size: 13px;
    min-width: 280px;
}

/* ---------- 文件选择对话框 ---------- */
QFileDialog {
    background-color: #ffffff;
    color: #000000;
}
QFileDialog QLabel {
    color: #000000;
}
QFileDialog QTreeView, QFileDialog QListView {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid #cccccc;
}
QFileDialog QComboBox {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid #cccccc;
    padding: 4px 8px;
}
QFileDialog QLineEdit {
    background-color: #ffffff;
    color: #000000;
    border: 1px solid #cccccc;
    padding: 6px;
}

/* ---------- 分割线 ---------- */
QSplitter::handle {
    background-color: #cccccc;
    width: 2px;
}
QSplitter::handle:hover {
    background-color: #000000;
}
"""


# ================================================================
#  欢迎页 HTML
# ================================================================

WELCOME_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    background: #ffffff;
    color: #000000;
    font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
    display: flex; justify-content: center; align-items: center;
    height: 100vh; overflow: hidden;
}}
.card {{
    text-align: center;
    padding: 60px 80px;
    border: 1px solid #cccccc;
    border-radius: 8px;
    background: #ffffff;
}}
h1 {{
    font-size: 42px;
    color: #000000;
    margin-bottom: 16px;
    letter-spacing: 4px;
}}
.date {{
    font-size: 20px;
    color: #000000;
    margin-bottom: 8px;
}}
.hint {{
    font-size: 14px;
    color: #666666;
    margin-top: 24px;
}}
.line {{
    width: 120px; height: 2px; margin: 20px auto;
    background: #cccccc;
}}
</style></head>
<body>
<div class="card">
    <h1>NEWSPAPER PDF</h1>
    <div class="line"></div>
    <div class="date">{date}</div>
    <div class="date" style="font-size:14px;color:#666666;">{weekday}</div>
    <div class="hint">&larr; 从左侧列表选择报纸开始浏览</div>
</div>
</body></html>"""


# ================================================================
#  添加网址对话框
# ================================================================

class AddWebsiteDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加网址")
        self.setFixedWidth(460)
        layout = QFormLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("例如：人民日报")
        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText("例如：http://paper.people.com.cn/...")

        layout.addRow("名  称:", self.name_edit)
        layout.addRow("网  址:", self.url_edit)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addRow(btn_box)

    def _on_accept(self):
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "提示", "名称不能为空")
            return
        if not self.url_edit.text().strip():
            QMessageBox.warning(self, "提示", "网址不能为空")
            return
        self.accept()


# ================================================================
#  下载进度对话框（带后台线程通信）
# ================================================================

class DownloadWorker(QThread):
    """后台线程：爬取页面 → 下载 PDF → 合并。"""
    progress = pyqtSignal(int, int, str)   # (当前序号, 总数, 文件名)
    log = pyqtSignal(str)                  # 日志消息
    finished_ok = pyqtSignal(str)          # 成功：合并文件路径
    finished_err = pyqtSignal(str)         # 失败：错误信息

    def __init__(self, seed_url: str, download_dir: str, parent=None):
        super().__init__(parent)
        self.seed_url = seed_url
        self.download_dir = download_dir

    # ---------- 爬取同栏目页面 ----------
    def _crawl_pages(self, start_url: str) -> list[str]:
        visited, queue = [], [start_url]
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.append(current)
            html = fetch_html(current)
            if html is None:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if "node_" in href and (".html" in href or ".htm" in href):
                    full = urljoin(current, href)
                    if full not in visited and full not in queue:
                        queue.append(full)
            self.log.emit(f"已扫描页面 ({len(visited)}) : {current}")
        return visited

    # ---------- 下载单个 PDF ----------
    def _download_one(self, pdf_url: str) -> str | None:
        fname = safe_filename(pdf_url)
        fpath = os.path.join(self.download_dir, fname)
        if os.path.exists(fpath):
            self.log.emit(f"已存在，跳过: {fname}")
            return fpath
        try:
            resp = _http_session.get(pdf_url, timeout=60)
            resp.raise_for_status()
        except requests.exceptions.SSLError:
            try:
                resp = _http_session.get(pdf_url, timeout=60, verify=False)
                resp.raise_for_status()
            except Exception as exc:
                self.log.emit(f"下载失败(SSL): {pdf_url} -> {exc}")
                return None
        except Exception as exc:
            self.log.emit(f"下载失败: {pdf_url} -> {exc}")
            return None
        with open(fpath, "wb") as f:
            f.write(resp.content)
        self.log.emit(f"下载完成: {fname}  ({len(resp.content)/1024:.0f} KB)")
        return fpath

    # ---------- 合并 PDF ----------
    @staticmethod
    def _merge_pdfs(pdf_files: list[str], output: str) -> None:
        """
        合并多个 PDF，按优先级尝试多种方式：
          1. pypdf (>=3.0)
          2. PyPDF2
          3. 系统 ghostscript (gs / gswin64c)
          4. 简单二进制拼接（最后手段）
        """
        import shutil as _shutil

        # --- 方法 1: pypdf ---
        _PdfWriter = None
        try:
            from pypdf import PdfWriter as _PdfWriter
        except ImportError:
            pass

        if _PdfWriter is not None:
            try:
                writer = _PdfWriter()
                for p in pdf_files:
                    writer.append(p)
                with open(output, "wb") as f:
                    writer.write(f)
                logger.info("pypdf 合并成功 (%d 个文件)", len(pdf_files))
                return
            except Exception as exc:
                logger.warning("pypdf 合并出错: %s", exc)

        # --- 方法 2: PyPDF2 ---
        _PdfMerger = None
        try:
            from PyPDF2 import PdfMerger as _PdfMerger
        except ImportError:
            pass

        if _PdfMerger is not None:
            try:
                merger = _PdfMerger()
                for p in pdf_files:
                    merger.append(p)
                merger.write(output)
                merger.close()
                logger.info("PyPDF2 合并成功 (%d 个文件)", len(pdf_files))
                return
            except Exception as exc:
                logger.warning("PyPDF2 合并出错: %s", exc)

        # --- 方法 3: Ghostscript (系统命令) ---
        _gs = _shutil.which("gs") or _shutil.which("gswin64c") or _shutil.which("gswin32c")
        if _gs:
            try:
                import subprocess as _sp
                cmd = [_gs, "-sDEVICE=pdfwrite", "-dNOPAUSE", "-dBATCH", "-dQUIET",
                       f"-sOutputFile={output}"] + list(pdf_files)
                _sp.run(cmd, check=True, capture_output=True, timeout=300)
                logger.info("Ghostscript 合并成功 (%d 个文件)", len(pdf_files))
                return
            except Exception as exc:
                logger.warning("Ghostscript 合并出错: %s", exc)

        # --- 方法 4: 如果只有一个 PDF，直接复制 ---
        if len(pdf_files) == 1:
            _shutil.copy2(pdf_files[0], output)
            logger.info("单个 PDF，直接复制")
            return

        # --- 全部失败 ---
        raise RuntimeError(
            f"PDF 合并失败：已尝试 pypdf / PyPDF2 / Ghostscript 均不可用。\n"
            f"已下载 {len(pdf_files)} 个文件到: {os.path.dirname(pdf_files[0])}\n"
            f"请安装 pypdf (pip install pypdf) 或 ghostscript 后重试。"
        )

    # ---------- 主流程 ----------
    def run(self):
        try:
            self.log.emit(f"开始爬取，种子: {self.seed_url}")
            pages = self._crawl_pages(self.seed_url)
            if not pages:
                self.finished_err.emit("未找到任何可爬取的页面。")
                return

            # 收集 PDF 链接
            pdf_urls: list[str] = []
            for page in pages:
                html = fetch_html(page)
                if html is None:
                    continue
                soup = BeautifulSoup(html, "html.parser")
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"].strip()
                    if ".pdf" in href.lower():
                        full = urljoin(page, href)
                        if full not in pdf_urls:
                            pdf_urls.append(full)

            if not pdf_urls:
                self.finished_err.emit("页面中未找到任何 PDF 链接。")
                return

            self.log.emit(f"共发现 {len(pdf_urls)} 个 PDF，开始下载...")
            os.makedirs(self.download_dir, exist_ok=True)

            downloaded: list[str] = []
            for idx, url in enumerate(pdf_urls):
                self.progress.emit(idx + 1, len(pdf_urls), safe_filename(url))
                fpath = self._download_one(url)
                if fpath:
                    downloaded.append(fpath)

            if not downloaded:
                self.finished_err.emit("没有成功下载任何 PDF 文件。")
                return

            # 合并 —— 以日期命名
            date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            merged_name = f"merged_{date_str}.pdf"
            merged_path = os.path.join(self.download_dir, merged_name)
            self.log.emit(f"正在合并 {len(downloaded)} 个 PDF...")
            self._merge_pdfs(downloaded, merged_path)

            # 清理临时文件（仅合并成功后的中间产物）
            for p in downloaded:
                try:
                    if os.path.normpath(p) != os.path.normpath(merged_path):
                        os.remove(p)
                except Exception:
                    pass

            self.finished_ok.emit(merged_path)

        except Exception as exc:
            logger.exception("下载任务异常")
            self.finished_err.emit(f"下载过程出错: {exc}")


class DownloadProgressDialog(QDialog):
    """模态进度对话框，驱动 DownloadWorker。"""

    def __init__(self, seed_url: str, download_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PDF 下载进度")
        self.setFixedSize(560, 440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.merged_file: str | None = None   # 成功后记录路径

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("正在下载并合并 PDF...")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #000000;")
        layout.addWidget(title)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("准备中...")
        self.status_label.setStyleSheet("color: #000000; font-size: 12px;")
        layout.addWidget(self.status_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.close_btn = QPushButton("关闭并打开 PDF")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self._on_close)
        layout.addWidget(self.close_btn)

        # 启动后台线程
        self.worker = DownloadWorker(seed_url, download_dir, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self._on_log)
        self.worker.finished_ok.connect(self._on_success)
        self.worker.finished_err.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, current, total, name):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"[{current}/{total}]  {name}")

    def _on_log(self, msg):
        self.log_text.append(msg)

    def _on_success(self, merged_path):
        self.merged_file = merged_path
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.status_label.setText("完成!")
        self.log_text.append(f"\n合并文件已保存: {merged_path}")
        self.close_btn.setText("关闭并打开 PDF")
        self.close_btn.setEnabled(True)

    def _on_error(self, msg):
        self.status_label.setText("出错")
        self.log_text.append(f"\n[错误] {msg}")
        self.close_btn.setText("关闭")
        self.close_btn.setEnabled(True)
        QMessageBox.warning(self, "下载失败", msg)

    def _on_close(self):
        """点击关闭：如果有成功的合并文件，自动打开。"""
        if self.merged_file and os.path.exists(self.merged_file):
            try:
                open_file(self.merged_file)
            except Exception as exc:
                logger.warning("打开 PDF 失败: %s", exc)
        self.accept()

    def closeEvent(self, event):
        if self.worker.isRunning():
            self.worker.quit()
            self.worker.wait(3000)
        # 窗口 X 关闭也尝试打开 PDF
        if self.merged_file and os.path.exists(self.merged_file):
            try:
                open_file(self.merged_file)
            except Exception:
                pass
        super().closeEvent(event)


# ================================================================
#  主窗口
# ================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Newspaper PDF Tool")
        self.resize(1280, 820)

        # 用户配置
        self.user_config = load_user_config()
        self.download_dir = self.user_config.get(
            "download_dir", DEFAULT_DOWNLOAD_DIR
        )

        self.websites: list[dict] = []
        self._load_websites()

        self._build_ui()
        self._show_welcome()

    # -------------------- 数据加载/保存 --------------------

    def _load_websites(self):
        """加载网址配置；首次运行时使用默认配置并自动生成当天 URL。"""
        if os.path.exists(WEBSITES_FILE):
            try:
                with open(WEBSITES_FILE, "r", encoding="utf-8") as f:
                    self.websites = json.load(f)
            except Exception as exc:
                logger.error("加载网址数据失败: %s", exc)
                self.websites = []

        # 回退：检查安装目录下的副本（首次运行系统安装时）
        if not self.websites and os.path.exists(_WEBSITES_FALLBACK):
            try:
                with open(_WEBSITES_FALLBACK, "r", encoding="utf-8") as f:
                    self.websites = json.load(f)
                logger.info("从安装目录加载网址配置: %s", _WEBSITES_FALLBACK)
            except Exception:
                pass

        if not self.websites:
            self.websites = [dict(e) for e in DEFAULT_WEBSITES]

        # 自动刷新已知报纸的 URL 为当天日期
        self._refresh_urls()
        self._save_websites()

    def _save_websites(self):
        try:
            with open(WEBSITES_FILE, "w", encoding="utf-8") as f:
                json.dump(self.websites, f, ensure_ascii=False, indent=4)
        except Exception as exc:
            logger.error("保存网址数据失败: %s", exc)

    def _refresh_urls(self):
        """将所有已知报纸的 URL 刷新为当天日期，兼容旧格式。"""
        known_names = {e["name"] for e in DEFAULT_WEBSITES}
        for entry in self.websites:
            np_key = entry.get("newspaper")
            # 如果没有 newspaper 字段但名字匹配 → 旧格式，补上
            if not np_key and entry.get("name") in known_names:
                for d in DEFAULT_WEBSITES:
                    if d["name"] == entry["name"]:
                        np_key = d["newspaper"]
                        entry["newspaper"] = np_key
                        break
            if np_key:
                fresh = generate_newspaper_url(np_key)
                if fresh:
                    entry["url"] = fresh

    # -------------------- UI 构建 --------------------

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # — 顶部标题栏 —
        header = QFrame()
        header.setFixedHeight(52)
        header.setStyleSheet(
            "QFrame { background: #ffffff;"
            "border-bottom: 1px solid #cccccc; }"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 0, 18, 0)

        title_label = QLabel("NEWSPAPER  PDF  TOOL")
        title_label.setStyleSheet(
            "font-size: 18px; font-weight: bold; letter-spacing: 6px;"
            "color: #000000; background: transparent;"
        )
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        author_label = QLabel("25121814@qq.com")
        author_label.setStyleSheet(
            "font-size: 11px; color: #000000; background: transparent;"
        )
        header_layout.addWidget(author_label)

        date_label = QLabel(datetime.now().strftime("%Y-%m-%d  %A"))
        date_label.setStyleSheet(
            "font-size: 13px; color: #000000; background: transparent;"
        )
        header_layout.addWidget(date_label)

        root_layout.addWidget(header)

        # — 主体：左侧列表 + 右侧预览 —
        splitter = QSplitter(Qt.Horizontal)

        # 左侧面板
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 6, 12)
        left_layout.setSpacing(8)

        section_label = QLabel("  报纸列表")
        section_label.setStyleSheet(
            "font-size: 12px; color: #000000; font-weight: bold;"
        )
        left_layout.addWidget(section_label)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(False)
        left_layout.addWidget(self.list_widget, stretch=1)
        self._populate_list()
        self.list_widget.currentItemChanged.connect(self._on_item_changed)

        # 按钮组
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_add = QPushButton("+ 添加")
        self.btn_add.clicked.connect(self._add_website)
        btn_row.addWidget(self.btn_add)

        self.btn_edit = QPushButton("编辑")
        self.btn_edit.clicked.connect(self._edit_website)
        btn_row.addWidget(self.btn_edit)

        self.btn_del = QPushButton("删除")
        self.btn_del.setObjectName("btnDanger")
        self.btn_del.clicked.connect(self._delete_website)
        btn_row.addWidget(self.btn_del)

        left_layout.addLayout(btn_row)

        # 分隔线
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #cccccc;")
        left_layout.addWidget(sep)

        # 刷新日期按钮
        self.btn_refresh = QPushButton("刷新日期")
        self.btn_refresh.setToolTip("将所有报纸 URL 刷新为今天的日期")
        self.btn_refresh.clicked.connect(self._on_refresh_clicked)
        left_layout.addWidget(self.btn_refresh)

        # 下载路径选择
        path_row = QHBoxLayout()
        path_row.setSpacing(6)

        self.btn_path = QPushButton("下载路径")
        self.btn_path.setObjectName("btnPath")
        self.btn_path.setToolTip(f"当前: {self.download_dir}")
        self.btn_path.clicked.connect(self._choose_download_dir)
        path_row.addWidget(self.btn_path)

        self.path_label = QLabel(self._shorten_path(self.download_dir))
        self.path_label.setStyleSheet(
            "color: #000000; font-size: 11px; padding: 0 4px;"
        )
        self.path_label.setToolTip(self.download_dir)
        path_row.addWidget(self.path_label, stretch=1)

        left_layout.addLayout(path_row)

        # PDF 下载按钮
        self.btn_download = QPushButton("PDF 爬取 & 合并")
        self.btn_download.setObjectName("btnPrimary")
        self.btn_download.clicked.connect(self._download_pdfs)
        left_layout.addWidget(self.btn_download)

        # 右侧 Web 预览
        self.web_view = QWebEngineView()
        self.web_view.setStyleSheet("background: #ffffff;")

        splitter.addWidget(left)
        splitter.addWidget(self.web_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 1000])

        root_layout.addWidget(splitter, stretch=1)
        self.setCentralWidget(central)

        # 状态栏
        self.statusBar().showMessage("就绪")

    @staticmethod
    def _shorten_path(p: str) -> str:
        """缩短路径显示，只保留最后两级目录。"""
        parts = p.replace("\\", "/").split("/")
        if len(parts) > 3:
            return "..." + "/" + "/".join(parts[-2:])
        return p

    def _show_welcome(self):
        now = datetime.now()
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        html = WELCOME_HTML.format(
            date=now.strftime("%Y 年 %m 月 %d 日"),
            weekday=weekdays[now.weekday()],
        )
        self.web_view.setHtml(html, QUrl("about:blank"))

    # -------------------- 列表操作 --------------------

    def _populate_list(self):
        self.list_widget.clear()
        for entry in self.websites:
            item = QListWidgetItem(entry["name"])
            item.setData(Qt.UserRole, entry.get("url", ""))
            item.setData(Qt.UserRole + 1, entry.get("newspaper", ""))
            item.setToolTip(entry.get("url", ""))
            self.list_widget.addItem(item)

    def _on_item_changed(self, current, previous=None):
        item = self.list_widget.currentItem()
        if not item:
            return
        url = item.data(Qt.UserRole)
        np_key = item.data(Qt.UserRole + 1)

        if url:
            # 智能解析：如果当天 URL 返回 404，自动回退到最近一期
            if np_key:
                self.statusBar().showMessage(f"正在解析最新可用期次...")
                resolved = resolve_latest_url(np_key, url)
                if resolved != url:
                    # 更新列表中的 URL
                    item.setData(Qt.UserRole, resolved)
                    for entry in self.websites:
                        if entry.get("newspaper") == np_key:
                            entry["url"] = resolved
                            break
                    self._save_websites()
                    self.statusBar().showMessage(
                        f"当天无内容，已自动切换到最近一期"
                    )
                    url = resolved

            self.web_view.load(QUrl(url))
            self.statusBar().showMessage(f"正在加载: {url}")

    # -------------------- 添加 / 编辑 / 删除 --------------------

    def _add_website(self):
        dlg = AddWebsiteDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        name = dlg.name_edit.text().strip()
        url = dlg.url_edit.text().strip()
        self.websites.append({"name": name, "url": url})
        self._save_websites()
        self._populate_list()
        # 自动选中新条目
        items = self.list_widget.findItems(name, Qt.MatchExactly)
        if items:
            self.list_widget.setCurrentItem(items[-1])
        self.statusBar().showMessage(f"已添加: {name}")

    def _edit_website(self):
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先在列表中选择一个条目")
            return
        old_name = item.text()
        old_url = item.data(Qt.UserRole)

        dlg = AddWebsiteDialog(self)
        dlg.setWindowTitle("编辑网址")
        dlg.name_edit.setText(old_name)
        dlg.url_edit.setText(old_url)
        if dlg.exec_() != QDialog.Accepted:
            return
        new_name = dlg.name_edit.text().strip()
        new_url = dlg.url_edit.text().strip()
        if not new_name or not new_url:
            return

        for entry in self.websites:
            if entry["name"] == old_name and entry.get("url") == old_url:
                entry["name"] = new_name
                entry["url"] = new_url
                # 如果用户改了 URL，移除 newspaper 标识（变成自定义条目）
                if new_url != old_url:
                    entry.pop("newspaper", None)
                break
        self._save_websites()
        self._populate_list()
        items = self.list_widget.findItems(new_name, Qt.MatchExactly)
        if items:
            self.list_widget.setCurrentItem(items[0])
        self.statusBar().showMessage(f"已更新: {new_name}")

    def _delete_website(self):
        item = self.list_widget.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先在列表中选择一个条目")
            return
        name = item.text()
        reply = QMessageBox.question(
            self, "确认删除",
            f'确定要删除 "{name}" 吗？',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        url = item.data(Qt.UserRole)
        self.websites = [
            e for e in self.websites
            if not (e["name"] == name and e.get("url") == url)
        ]
        self._save_websites()
        self._populate_list()
        self.statusBar().showMessage(f"已删除: {name}")

    # -------------------- 刷新日期 --------------------

    def _on_refresh_clicked(self):
        self._refresh_urls()
        self._save_websites()
        self._populate_list()
        self.statusBar().showMessage(
            f"已将所有报纸 URL 刷新为 {datetime.now().strftime('%Y-%m-%d')}"
        )

    # -------------------- 下载路径 --------------------

    def _choose_download_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择 PDF 下载保存路径", self.download_dir
        )
        if path:
            self.download_dir = path
            self.user_config["download_dir"] = path
            save_user_config(self.user_config)
            self.path_label.setText(self._shorten_path(path))
            self.path_label.setToolTip(path)
            self.btn_path.setToolTip(f"当前: {path}")
            self.statusBar().showMessage(f"下载路径已更新: {path}")

    # -------------------- PDF 下载 --------------------

    def _download_pdfs(self):
        seed = self.web_view.url().toString()
        if not seed or seed == "about:blank":
            QMessageBox.information(self, "提示", "请先在右侧预览一个有效的报纸页面")
            return
        self.statusBar().showMessage("正在下载 PDF...")
        dlg = DownloadProgressDialog(seed, self.download_dir, self)
        dlg.exec_()
        self.statusBar().showMessage("就绪")


# ================================================================
#  入口
# ================================================================

def main():
    # 高 DPI 支持
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # QtWebEngine 需要共享 OpenGL 上下文
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(CYBERPUNK_QSS)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
