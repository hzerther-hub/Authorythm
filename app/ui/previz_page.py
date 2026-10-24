# -*- coding: utf-8 -*-
"""导演台预演页:内嵌 DirectorDesk 原版 web 构建(QWebEngineView)。

「效果不低于原版」的实现方式:**渲染/动画/视频导出跑的就是原版那一份代码**
(fetch_directordesk.py 解包到 data/vendor/directordesk/),本页只是宿主 ——
Python 侧负责生成分镜工程(previz_gen),导出的参考视频经下载拦截落回
data/previz/exports/,再走本系统既有视频流水线。

坑位备忘:
- QtWebEngine 必须在 QApplication 之前 import(app/main.py 顶部已做);
- web 构建里的 ES Module 在 file:// 下会被 Chromium 拦,所以用 127.0.0.1 回环
  HTTP 服务(进程级单例,页面随语言切换重建也不重启);
- 导出视频在浏览器端是 blob 下载,必须拦截 profile.downloadRequested,否则
  QtWebEngine 会静默丢弃(QWebEngineProfile 默认不弹保存框)。
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ..core import config, db
from ..core.i18n import tr
from ..core.logging_setup import get_logger
from .toast import err, ok

log = get_logger(__name__)

VENDOR_DIR = config.DATA_DIR / "vendor" / "directordesk"
APP_DIR = VENDOR_DIR / "app"
PREVIZ_DIR = config.DATA_DIR / "previz"
EXPORT_DIR = PREVIZ_DIR / "exports"

_server: ThreadingHTTPServer | None = None
_server_root: Path | None = None


def _vendor_meta() -> dict:
    import contextlib
    with contextlib.suppress(Exception):  # 没获取过内核是常态,不算错误
        return json.loads((VENDOR_DIR / "VERSION.json").read_text(encoding="utf-8"))
    return {}


def vendor_ready() -> bool:
    meta = _vendor_meta()
    entry = meta.get("entry")
    return bool(entry) and (APP_DIR / entry).exists()


def _start_server(root: Path) -> str:
    """进程级单例回环 HTTP 服务,返回 base url。root 变了才重启。"""
    global _server, _server_root
    if _server is not None and _server_root == root:
        port = _server.server_address[1]
        return f"http://127.0.0.1:{port}"
    _stop_server()
    handler = type("H", (SimpleHTTPRequestHandler,),
                   {"__init__": lambda self, *a, **kw:
                    SimpleHTTPRequestHandler.__init__(self, *a, directory=str(root), **kw),
                    "log_message": lambda *a, **k: None})
    _server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    _server_root = root
    threading.Thread(target=_server.serve_forever, daemon=True,
                     name="previz-http").start()
    port = _server.server_address[1]
    log.info("预演 web 服务已启动:http://127.0.0.1:%d ← %s", port, root)
    return f"http://127.0.0.1:{port}"


def _stop_server() -> None:
    global _server
    if _server is not None:
        import contextlib
        with contextlib.suppress(Exception):
            _server.shutdown()
        _server = None


class PrevizPage(QWidget):
    """预演工作台:上工具条 + 内嵌导演台画面。"""

    def __init__(self):
        super().__init__()
        self._loaded = False  # 首次可见才启动 web 内核(别拖慢主程序启动)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.ep_combo = QComboBox()
        self.ep_combo.setMinimumWidth(260)
        bar.addWidget(self.ep_combo)
        self.btn_gen = QPushButton(tr("previz_gen"))
        self.btn_gen.clicked.connect(self._generate)
        bar.addWidget(self.btn_gen)
        self.btn_demo = QPushButton(tr("previz_demo"))
        self.btn_demo.clicked.connect(self._open_demo)
        bar.addWidget(self.btn_demo)
        self.btn_folder = QPushButton(tr("previz_open_folder"))
        self.btn_folder.clicked.connect(self._open_folder)
        bar.addWidget(self.btn_folder)
        bar.addStretch(1)
        self.btn_fetch = QPushButton(tr("previz_fetch"))
        self.btn_fetch.clicked.connect(self._fetch_kernel)
        bar.addWidget(self.btn_fetch)
        root.addLayout(bar)

        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        # 双层栈:内核未就绪时显示引导层,就绪后显示 web 视图
        self.stack = QStackedLayout()
        self.guide = QLabel(tr("previz_need_fetch"))
        self.guide.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.guide.setWordWrap(True)
        self.stack.addWidget(self.guide)
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.view = QWebEngineView()
        self.view.page().profile().downloadRequested.connect(self._on_download)
        self.stack.addWidget(self.view)
        host = QWidget()
        host.setLayout(self.stack)
        root.addWidget(host, 1)

        self._reload_episodes()

    # ── 数据 ───────────────────────────────────────────────────────
    def _reload_episodes(self):
        cur = self.ep_combo.currentData()
        self.ep_combo.clear()
        rows = db.q("SELECT e.id, e.episode_number, e.title, d.title AS drama "
                    "FROM episodes e JOIN dramas d ON d.id=e.drama_id "
                    "ORDER BY e.drama_id, e.episode_number") or []
        for r in rows:
            label = f"{r['drama']} · E{r['episode_number']}" + (f" {r['title']}" if r["title"] else "")
            self.ep_combo.addItem(label, r["id"])
        if cur:
            i = self.ep_combo.findData(cur)
            if i >= 0:
                self.ep_combo.setCurrentIndex(i)

    def reload(self):
        """_goto 进入本页时调用:刷剧集列表 + 惰性加载 web 内核。"""
        self._reload_episodes()
        self._refresh_kernel_state()
        if vendor_ready():
            if not self._loaded:
                self._load_app()
        else:
            self.stack.setCurrentWidget(self.guide)

    def _refresh_kernel_state(self):
        ready = vendor_ready()
        self.btn_fetch.setVisible(not ready)
        self.status.setText(tr("previz_done_hint") if ready else tr("previz_need_fetch"))

    # ── web 内核 ───────────────────────────────────────────────────
    def _load_app(self):
        entry = _vendor_meta().get("entry")  # 形如 "dist/index.html"
        if not entry:
            return
        # HTTP 根必须指到 entry 所在目录:构建产物里是绝对路径 /assets/...
        parts = Path(entry).parts
        root = APP_DIR.joinpath(*parts[:-1]) if len(parts) > 1 else APP_DIR
        url = f"{_start_server(root)}/{parts[-1]}"
        self._loaded = True
        self.stack.setCurrentWidget(self.view)
        self.view.load(QUrl(url))

    def _on_download(self, item):  # QWebEngineDownloadRequest
        """拦截导演台导出的视频下载,落到 data/previz/exports/。"""
        try:
            EXPORT_DIR.mkdir(parents=True, exist_ok=True)
            item.setDownloadDirectory(str(EXPORT_DIR))
            item.setDownloadFileName(item.downloadFileName() or "export.mp4")
            item.accept()
            ok(tr("previz_export_saved").format(name=item.downloadFileName()))
            log.info("预演导出:%s/%s", EXPORT_DIR, item.downloadFileName())
        except Exception as exc:
            err(tr("previz_fail").format(err=str(exc)[:120]))

    # ── 动作 ───────────────────────────────────────────────────────
    def _generate(self):
        from ..core.taskmgr import TASKMGR
        episode_id = self.ep_combo.currentData()  # 主线程快照,worker 里不碰控件
        if not episode_id:
            err(tr("previz_no_storyboard"))
            return
        from ..pipeline import previz_gen
        out_path = PREVIZ_DIR / f"ep{episode_id}.directordesk.json"

        def job(tid):
            return previz_gen.generate_from_episode(episode_id, out_path=out_path)

        def done(tid, result, e):
            if e:
                err(tr("previz_fail").format(err=str(e)[:160]))
                return
            ok(tr("previz_done").format(path=result["path"]))

        TASKMGR.submit("previz", job, done, episode_id=episode_id)

    def _open_demo(self):
        from ..pipeline import previz
        path = PREVIZ_DIR / "demo.directordesk.json"
        if not path.exists():
            previz.save_project(previz.demo_project(), path)
        self._reveal(path.parent)

    def _open_folder(self):
        self._reveal(PREVIZ_DIR)

    @staticmethod
    def _reveal(path: Path):
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            err(str(exc))

    def _fetch_kernel(self):
        """跑 scripts/fetch_directordesk.py(子进程;167MB 下载别占 taskmgr 线程池)。"""
        self.btn_fetch.setEnabled(False)
        self.status.setText(tr("previz_fetching"))
        script = Path(config.__file__).parent.parent / "scripts" / "fetch_directordesk.py"

        def work():
            r = subprocess.run([sys.executable, str(script)], capture_output=True,
                               text=True, timeout=3600, cwd=str(script.parent.parent))
            return r.returncode, (r.stdout or "")[-800:], (r.stderr or "")[-800:]

        def after(tid, result, e):
            self.btn_fetch.setEnabled(True)
            if e is not None:
                err(tr("previz_fetch_fail").format(err=str(e)[:160]))
                self.status.setText(tr("previz_need_fetch"))
                return
            code, out, errtext = result
            if code == 0:
                ok(tr("previz_fetch_ok"))
                self._refresh_kernel_state()
                self._load_app()
            else:
                err(tr("previz_fetch_fail").format(err=(errtext or out)[-160:]))
                self.status.setText(tr("previz_need_fetch"))

        from ..core.taskmgr import TASKMGR
        TASKMGR.submit("previz", work, after)
