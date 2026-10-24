# -*- coding: utf-8 -*-
"""QtWebEngine 内嵌导演台渲染冒烟验证。

验证的事:上游 web 构建产物(fetch_directordesk.py 解包到
data/vendor/directordesk/app/)能在本系统的 QtWebEngine 里完整跑起来 ——
WebGL 上下文可创建、页面无致命报错、真渲染出画面(截图非空白)。
这是「集成后效果与原版同源」的实证:跑起来的是同一段 three.js 代码。

用法:python scripts/previz_smoke.py [入口URL或路径]
"""
from __future__ import annotations

import functools
import json
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "data" / "vendor" / "directordesk"

# QtWebEngine 必须在 QApplication 之前初始化
import PySide6.QtWebEngineWidgets  # noqa: F401,E402
from PySide6.QtCore import QTimer, QUrl  # noqa: E402
from PySide6.QtWebEngineCore import QWebEnginePage  # noqa: E402
from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PROBE_JS = """
(() => {
  const c = document.createElement('canvas');
  const gl = c.getContext('webgl2') || c.getContext('webgl');
  let renderer = null;
  if (gl) {
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    renderer = dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)
                   : gl.getParameter(gl.RENDERER);
  }
  return JSON.stringify({
    webgl: !!gl,
    renderer: renderer,
    title: document.title,
    canvases: document.querySelectorAll('canvas').length,
    bodyChars: (document.body ? document.body.innerText.length : 0),
  });
})()
"""


class _ConsoleCollector:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def on_console(self, level, message, line, source):
        text = f"[console.{level}] {message} ({source}:{line})"
        print(" ", text)
        if level >= 2:  # ErrorMessage
            self.errors.append(text)


class _ProbedPage(QWebEnginePage):
    """PySide6 里 console 消息是虚方法(QWebEnginePage 子类重写),不是信号。"""

    def __init__(self, collector: _ConsoleCollector, parent=None):
        super().__init__(parent)
        self._col = collector

    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        self._col.on_console(level, message, lineNumber, sourceID)


def serve(directory: Path) -> tuple[ThreadingHTTPServer, str]:
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}"


def main() -> int:
    entry_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if entry_arg and entry_arg.startswith("http"):
        url = entry_arg
        httpd = None
    else:
        entry = Path(entry_arg) if entry_arg else None
        if entry is None:
            meta = VENDOR / "VERSION.json"
            rel = json.loads(meta.read_text(encoding="utf-8"))["entry"] if meta.exists() else None
            if not rel:
                print("未找到 web 入口,请先运行 scripts/fetch_directordesk.py")
                return 2
            entry = VENDOR / "app" / rel
        if not entry.exists():
            print(f"入口不存在:{entry}")
            return 2
        httpd, url = serve(entry.parent)
        url = f"{url}/{entry.name}"
    print("加载:", url)

    _app = QApplication(sys.argv)  # 保持引用,否则视图立即被回收
    view = QWebEngineView()
    view.resize(1280, 800)
    console = _ConsoleCollector()
    page = _ProbedPage(console, view)
    view.setPage(page)

    result: dict = {}

    def on_probe(js: object) -> None:
        result["probe"] = js
        loop.quit()

    def on_loaded(ok: bool) -> None:
        print("loadFinished:", ok)
        # 再等 3 秒让 three.js 首帧渲染完
        QTimer.singleShot(3000, lambda: page.runJavaScript(PROBE_JS, 0, on_probe))

    from PySide6.QtCore import QEventLoop

    loop = QEventLoop()
    view.loadFinished.connect(on_loaded)
    view.load(QUrl(url))
    view.show()
    QTimer.singleShot(60000, loop.quit)  # 整体兜底超时
    loop.exec()

    shot_path = VENDOR / "smoke.png"
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    view.grab().save(str(shot_path))

    probe_raw = result.get("probe")
    probe = json.loads(probe_raw) if isinstance(probe_raw, str) else {}
    print("探针:", json.dumps(probe, ensure_ascii=False, indent=2))
    print("截图:", shot_path, "控制台错误数:", len(console.errors))

    ok = bool(probe.get("webgl")) and int(probe.get("canvases") or 0) > 0
    print("结论:", "通过 — 原版渲染内核在 QtWebEngine 内正常工作" if ok
          else "未通过:见上方控制台输出")
    if httpd:
        httpd.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
