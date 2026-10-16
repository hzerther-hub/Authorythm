# -*- coding: utf-8 -*-
"""图库搜图弹窗 —— 「图片处理」「聊天改图」共用。

选中的图**下载到本地**再交给调用方:下游逻辑(prompt 拼装、图像 API、
缩略图渲染)都按本地路径写的,直接塞一个远程 URL 会在一半的地方炸掉。

软失败:没配 key / 全网不通都只提示,弹窗照常打开 —— 搜图是增强项,
不能因为它没配就让用户连本地图片都改不了。
"""
from __future__ import annotations

import uuid

from PySide6.QtCore import Qt, QThread, Signal
import requests

from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..ai import stock_photo as sp
from ..core import config
from ..core.i18n import tr
from . import widgets as W
from .toast import err, info

THUMB_W = 172
THUMB_H = 130
PER_PAGE = 12
COLS = 4          # 网格列数:改这里即可,布局与宽度都跟着算


class _Searcher(QThread):
    """网络搜索放线程里,别把 UI 冻住。"""
    done = Signal(list, list)

    def __init__(self, query, source, parent=None):
        super().__init__(parent)
        self._q, self._s = query, source

    def run(self):
        photos, errs = sp.search(self._q, self._s, per_page=PER_PAGE)
        self.done.emit(photos, errs)


class _ThumbFetcher(QThread):
    """批量下载缩略图 —— **绝不能在主线程逐张同步下载**。

    实测 24 张缩略图同步加载会把窗口卡死十几秒(每张一次 HTTPS 往返),
    而且窗口此时无法重绘,用户看到的是一片空白/错位。
    一次请求拿回一张,emit 后回主线程贴图。
    """
    one = Signal(object, bytes)          # (idx, jpeg/png bytes)

    def __init__(self, jobs, parent=None):
        super().__init__(parent)
        self._jobs = jobs                # [(idx, url)]

    def run(self):
        for idx, url in self._jobs:
            if not url:
                continue
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200 and r.content:
                    self.one.emit(idx, r.content)
            except Exception:  # noqa: BLE001 —— 单张失败不影响其它
                continue


def _drama_id_of(widget) -> int | None:
    """沿父链找当前项目 id。

    「图片处理」「聊天改图」都是**跨项目复用**的独立页签,自己不存 drama_id,
    真正的当前项目在 MainWindow 上(_cur_drama_id)。没有上下文就返回 None,
    此时「换画风」会退回到默认 3d 画风,而不是崩掉。
    """
    w = widget
    for _ in range(8):                     # 最多往上找 8 层,防意外的环
        if w is None:
            break
        did = getattr(w, "_cur_drama_id", None)
        if did:
            return int(did)
        w = w.parent()
    return None


def _current_project_style(drama_id: int | None) -> str:
    """当前项目生效的画风(漫画优先于通用视觉风格,与 comic._style_for 同口径)。"""
    from ..core import db
    if not drama_id:
        return "3d"
    r = db.q1("SELECT comic_style, style FROM dramas WHERE id=?", (drama_id,))
    return (r["comic_style"] or r["style"] or "3d") if r else "3d"


def _is_local(url: str) -> bool:
    return str(url).startswith(("/", "http://", "https://")) is False


class _Downloader(QThread):
    """原图下载(后台线程)。"""
    done = Signal(bool, str)

    def __init__(self, url: str, out_path: str, parent=None):
        super().__init__(parent)
        self._url, self._out = url, out_path

    def run(self):
        from ..ai import stock_photo as sp
        ok = sp.download(self._url, self._out)
        self.done.emit(bool(ok), self._out)


class _ImgLabel(QLabel):
    """缩略图 + 点击选中。"""

    clicked = Signal(str, str)

    def __init__(self, photo, parent=None):
        super().__init__(parent)
        self.remote_path = photo["download_url"] or photo["preview_url"]
        self.photo = photo
        self._w, self._h = THUMB_W, THUMB_H
        w0, h0 = photo.get("width") or 0, photo.get("height") or 0
        self._label = f"{sp.SOURCE_CN.get(photo['source'], photo['source'])}"                       + (f" · {w0}×{h0}" if w0 and h0 else "")
        self.setFixedSize(self._w, self._h + 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("background:#f0f0f0;border:1px solid #ddd;border-radius:4px;")
        self.setText("…")

    def apply_bytes(self, data: bytes):
        from PySide6.QtGui import QPixmap
        pm = QPixmap()
        if not pm.loadFromData(data):
            return
        scaled = pm.scaled(self._w - 8, self._h - 8,
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.setPixmap(scaled)
        self.setText("")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # 传三个参数:预览大图时带来源与尺寸,用户能知道图是哪来的
            self.clicked.emit(self.remote_path, self._label)
        super().mousePressEvent(e)


class StockPhotoDialog(QDialog):
    """搜图库 → 选中 → 下载到本地 → accepted(local_path)。"""

    def __init__(self, parent=None, drama_id: int | None = None):
        super().__init__(parent)
        # drama_id 决定「换画风」转成哪个项目的画风;没有项目上下文就禁用该动作
        self._drama_id = drama_id or _drama_id_of(parent)
        self.setWindowTitle(tr("搜图库"))
        self.resize(880, 640)
        self._thread = None
        self._fetcher = None
        self._dl = None
        self._labels = []
        self.local_path = ""
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(tr("图库搜索关键词"))
        self.query_edit.returnPressed.connect(self._search)
        top.addWidget(self.query_edit, 1)
        self.src_combo = QComboBox()
        self.src_combo.addItem(tr("全部图库"), "all")
        for s in sp.configured_sources():
            self.src_combo.addItem(sp.SOURCE_CN.get(s, s), s)
        top.addWidget(self.src_combo)
        btn = W.primary_btn(tr("搜索"))
        btn.clicked.connect(self._search)
        top.addWidget(btn)
        root.addLayout(top)

        self.hint = W.muted(self._hint_text())
        root.addWidget(self.hint)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.grid = QVBoxLayout(self.host)
        self.scroll.setWidget(self.host)
        root.addWidget(self.scroll, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("取消"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        root.addLayout(row)

        if not sp.configured_sources():
            self.hint.setText(tr("未配置图库 API Key — 到「设置 → AI 服务」添加(类型选「图库」)"))

    def closeEvent(self, e):
        """关闭前把后台线程停干净。

        否则 Qt 会在 QThread 还在跑的时候析构它,报
        "QThread: Destroyed while thread is still running" —— 关闭弹窗时必崩一次。
        """
        for th in (self._fetcher, self._dl, self._thread):
            if th is not None and th.isRunning():
                th.quit()
                if not th.wait(3000):
                    th.terminate()
                    th.wait(1000)
        super().closeEvent(e)

    def _hint_text(self) -> str:
        return tr("点击任意一张即下载到本地并使用。图库是真实照片,适合找参考图/氛围图。")

    def _search(self):
        q = self.query_edit.text().strip()
        if not q:
            info(tr("请输入搜索关键词"))
            return
        if self._thread and self._thread.isRunning():
            return
        self._clear()
        self.hint.setText(tr("正在搜索…"))
        self._thread = _Searcher(q, self.src_combo.currentData(), self)
        self._thread.done.connect(self._on_done)
        self._thread.start()

    def _clear(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _on_done(self, photos, errs):
        self._clear()
        for e in errs:
            print(f"[stock] {e}", flush=True)
        if not photos:
            msg = tr("没有搜到图片")
            if errs:
                msg += "  ·  " + "; ".join(errs)
            self.hint.setText(msg)
            return
        # 每行 4 张。用 addWidget(host, 0, AlignLeft) 之外的固定宽 QLabel:
        # 网格容器默认 stretch=1 会让它们吃满父宽(见 AGENTS.md 网格约定)。
        from PySide6.QtWidgets import QGridLayout
        self.grid_host = QWidget()
        self.g = QGridLayout(self.grid_host)
        self.g.setContentsMargins(0, 0, 0, 0)
        self.g.setSpacing(8)
        self._labels: list[_ImgLabel] = []
        jobs = []
        for i, ph in enumerate(photos):
            lab = _ImgLabel(ph)
            lab.clicked.connect(self._pick)
            self._labels.append(lab)
            self.g.addWidget(lab, i // COLS, i % COLS)
            if ph.get("preview_url"):
                jobs.append((i, ph["preview_url"]))
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.grid.addWidget(self.grid_host)
        # 缩略图在后台线程下载,不阻塞窗口
        self._fetcher = _ThumbFetcher(jobs, self)
        self._fetcher.one.connect(self._on_thumb)
        self._fetcher.start()
        note = f"{len(photos)} 张"
        if errs:
            note += "  ·  " + "; ".join(errs)
        self.hint.setText(note)

    def _on_thumb(self, idx: int, data: bytes):
        if 0 <= idx < len(self._labels):
            self._labels[idx].apply_bytes(data)

    def _pick(self, url: str, label: str = ""):
        """点缩略图 → 先放大看,再决定用不用。

        之前是点一下直接下载并关掉弹窗,想关都没法关 —— 用户看不清就没法判断,
        只能硬着头皮用或者整个取消重来。现在点开是大图预览,里面给
        「使用这张」和「关闭」两个动作,**关闭回到搜索结果,弹窗不关**。

        大图里多一个「换画风」:把搜来的这张先转成项目画风再拿去用。
        图库是真实照片,直接当参考图风格对不上。转完原图仍在,
        不满意关掉重开即可 —— 与资产详情里的「换画风」同一套实现,不落库。
        """
        if not url:
            return
        from .asset_dialogs import ImageViewerDialog
        dlg = ImageViewerDialog(self, url, label or tr("预览"),
                                confirm_text=tr("使用这张"),
                                extra_text=tr("换画风"),
                                on_extra=self._on_transform)
        dlg.remote_url_hint = url
        if not dlg.exec() == ImageViewerDialog.Accepted or not dlg.used:
            return                                  # 关闭:回到搜索结果,弹窗继续开着
        # 用了换过画风的版本就用它,否则下原图
        self._download(getattr(dlg, "transformed_url", None) or url)

    # ── 预览里的「换画风」 ──
    def _on_transform(self, viewer):
        """就地执行:下载原图 → 转项目画风 → 刷新显示。

        `style_convert.convert_path` 只返回新图路径、**不落库**(手动流程
        先看效果),所以这里不会动任何资产表。
        """
        from ..ai import image_client
        from ..pipeline import style_convert as SC
        from ..core.taskmgr import TASKMGR
        try:
            cfg = image_client.registry.check_ready("image", None)
        except Exception as exc:  # noqa: BLE001
            err(str(exc)[:160])
            return
        if not image_client.supports_reference_images(cfg["provider"]):
            err(tr("换画风需要支持参考图的图像模型(agnes/local/comfyui/sdwebui/fooocus),"
                   "当前是「{p}」——请到顶栏切换图像模型").format(p=cfg["provider"]))
            return

        src = getattr(viewer, "_src_cache", "") or self._fetch_to_temp(
            getattr(viewer, "remote_url_hint", ""))
        if not src:
            err(tr("图片下载失败,无法换画风"))
            return
        viewer._src_cache = src
        viewer.setEnabled(False)        # 一次 30-60 秒,禁掉防连点
        self.hint.setText(tr("正在转换为项目画风…"))

        def job(tid):
            return SC.convert_path(src, _current_project_style(self._drama_id), cfg["id"])

        def done(tid, result, error):
            viewer.setEnabled(True)
            self.hint.setText(self._hint_text())
            if error or not result:
                err(tr("换画风失败:{}").format(str(error or "")[:120]))
                return
            viewer.transformed_url = str(result)
            viewer.show_local_image(str(result))
            info(tr("已转成项目画风 —— 满意点「使用这张」,不满意可关闭后重选"))

        TASKMGR.submit("image", job, done)

    def _fetch_to_temp(self, url: str) -> str:
        """远程图下到本地临时文件(换画风要本地路径作参考图)。"""
        if not url:
            return ""
        out_dir = config.STATIC_DIR / "uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"stocksrc_{uuid.uuid4().hex[:10]}.jpg"
        return str(out) if sp.download(url, out) else ""

    def _download(self, url: str):
        """下载原图到本地静态目录,完成后 accept。

        下载走后台线程:原图常有几百 KB 到几 MB,同步下会把窗口冻住,
        用户点了没反应以为程序卡死。
        """
        if self._dl.isRunning():
            return
        out_dir = config.STATIC_DIR / "uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        ext = ".jpg"
        for cand in (".jpg", ".png", ".jpeg", ".webp"):
            if url.split("?")[0].lower().endswith(cand):
                ext = cand
                break
        out = out_dir / f"stock_{uuid.uuid4().hex[:10]}{ext}"
        self.hint.setText(tr("正在下载…"))
        self._dl = _Downloader(url, str(out), self)
        self._dl.done.connect(self._on_downloaded)
        self._dl.start()

    def _on_downloaded(self, ok: bool, path: str):
        if ok:
            self.local_path = path
            self.accept()
        else:
            err(tr("图片下载失败,请换一张"))
            self.hint.setText(self._hint_text())
