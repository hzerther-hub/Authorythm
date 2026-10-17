# -*- coding: utf-8 -*-
"""图库搜图弹窗 —— 「图片处理」「聊天改图」共用。

选中的图**下载到本地**再交给调用方:下游逻辑(prompt 拼装、图像 API、
缩略图渲染)都按本地路径写的,直接塞一个远程 URL 会在一半的地方炸掉。

软失败:没配 key / 全网不通都只提示,弹窗照常打开 —— 搜图是增强项,
不能因为它没配就让用户连本地图片都改不了。
"""
from __future__ import annotations

import uuid
import pathlib

from PySide6.QtCore import Qt, QThread, QTimer, Signal
import requests

from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
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

    def __init__(self, query, source, page: int = 1, parent=None):
        super().__init__(parent)
        self._q, self._s, self._page = query, source, page

    def run(self):
        photos, errs = sp.search(self._q, self._s, page=self._page, per_page=PER_PAGE)
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

    def __init__(self, url: str, out_path: str, parent=None, timeout: int = 30):
        super().__init__(parent)
        self._url, self._out = url, out_path
        self._timeout = timeout        # 大尺寸原图 30s 可能不够

    def run(self):
        from ..ai import stock_photo as sp
        ok = sp.download(self._url, self._out, timeout=self._timeout)
        self.done.emit(bool(ok), self._out)


class _ImgLabel(QFrame):
    """缩略图卡片:图 + 底部「来源 · 宽×高」标注,点击选中。

    尺寸必须直接印在卡片上:搜图的人往往是在找特定画幅(9:16 竖版封面 /
    16:9 横版背景),只把尺寸放进点开后的预览标题,等于要一张张点开才知道
    有没有合适的。三家 API(pexels/unsplash/pixabay)都返回 width/height,
    `_photo()` 已解析,之前只是没显示。
    """

    clicked = Signal(str, str)          # 单击:看大图(延迟触发,等是否变双击)
    picked = Signal(str, str)           # 双击:直接选用(下载后关闭弹窗)

    def __init__(self, photo, parent=None):
        super().__init__(parent)
        self.remote_path = photo["download_url"] or photo["preview_url"]
        self.photo = photo
        self._w, self._h = THUMB_W, THUMB_H
        # 单击→看大图的防抖:双击的第二击到来就取消预览、改走「直接选用」
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(280)
        self._click_timer.timeout.connect(
            lambda: self.clicked.emit(self.remote_path, self._label))
        self._busy_overlay = None
        w0, h0 = photo.get("width") or 0, photo.get("height") or 0
        self._label = f"{sp.SOURCE_CN.get(photo['source'], photo['source'])}"                       + (f" · {w0}×{h0}" if w0 and h0 else "")
        self.setFixedSize(self._w, self._h + 26)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background:#f0f0f0;border:1px solid #ddd;border-radius:4px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._img = QLabel("…")
        self._img.setAlignment(Qt.AlignCenter)
        # 子控件不吃鼠标事件:点卡片任何位置都算点这张图(不然点在图上没反应)
        self._img.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(self._img, 1)
        cap = QLabel(self._label)
        cap.setAlignment(Qt.AlignCenter)
        cap.setFixedHeight(18)
        cap.setStyleSheet("color:#64748b;font-size:10px;border:none;background:transparent;")
        cap.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay.addWidget(cap)

    def apply_bytes(self, data: bytes):
        from PySide6.QtGui import QPixmap
        pm = QPixmap()
        if not pm.loadFromData(data):
            return
        scaled = pm.scaled(self._w - 8, self._h - 8,
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._img.setPixmap(scaled)
        self._img.setText("")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # 单击延迟 280ms 触发预览 —— 期间第二次按下按双击处理(直接选用)
            self._click_timer.start()
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._click_timer.stop()
            self.picked.emit(self.remote_path, self._label)
        super().mouseDoubleClickEvent(e)

    def set_busy(self, on: bool, text: str = ""):
        """下载等待效果:卡片上盖转圈遮罩(照片保持原色,不整卡变灰)。"""
        if on:
            if self._busy_overlay is None:
                from .adjust_worker import BusyOverlay
                self._busy_overlay = BusyOverlay(self)
                self._busy_overlay.setGeometry(self.rect())
            self._busy_overlay.start(text or tr("正在下载…"))
        elif self._busy_overlay is not None:
            self._busy_overlay.stop()


class StockPhotoDialog(QDialog):
    """搜图库 → 选中 → 下载到本地 → accepted(local_path)。

    「使用这张」走**先关窗后下载**模式:accept 后远程下载在后台继续,
    完成时 emit downloaded(本地路径)(失败 emit "")—— 调用方连此信号把图
    放进聊天当前图框,两层弹窗即刻关闭,不用干等大图下载。
    """

    downloaded = Signal(str)

    def __init__(self, parent=None, drama_id: int | None = None,
                 query: str = "", auto_search: bool = False):
        super().__init__(parent)
        # drama_id 决定「换画风」转成哪个项目的画风;没有项目上下文就禁用该动作
        self._drama_id = drama_id or _drama_id_of(parent)
        self.setWindowTitle(tr("搜图库"))
        self.resize(880, 640)
        self._thread = None
        self._fetcher = None
        self._dl = None
        self._labels = []
        self._page = 1
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

        self._page = 1
        row = QHBoxLayout()
        # 分页(用户要求):三家图库 API 都支持 page;满页才亮「下一页」
        self.pg_prev = QPushButton("◀ " + tr("上一页"))
        self.pg_prev.setCursor(Qt.PointingHandCursor)
        self.pg_prev.setEnabled(False)
        self.pg_prev.clicked.connect(lambda: self._search(self._page - 1))
        row.addWidget(self.pg_prev)
        self.pg_lab = QLabel("")
        self.pg_lab.setStyleSheet("color:#64748b; font-size:12px;")
        row.addWidget(self.pg_lab)
        self.pg_next = QPushButton(tr("下一页") + " ▶")
        self.pg_next.setCursor(Qt.PointingHandCursor)
        self.pg_next.setEnabled(False)
        self.pg_next.clicked.connect(lambda: self._search(self._page + 1))
        row.addWidget(self.pg_next)
        row.addStretch(1)
        cancel = QPushButton(tr("取消"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        root.addLayout(row)

        if not sp.configured_sources():
            self.hint.setText(tr("未配置图库 API Key — 到「设置 → AI 服务」添加(类型选「图库」)"))
        elif query:
            # 聊天里说「我想找一张美女图片」→ 直接带着关键词进来开搜
            # (singleShot 等一拍,让对话框先显示,别在构造期就起线程)
            self.query_edit.setText(query)
            if auto_search:
                QTimer.singleShot(0, self._search)

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

    def _search(self, page: int = 1):
        q = self.query_edit.text().strip()
        if not q:
            info(tr("请输入搜索关键词"))
            return
        if self._thread and self._thread.isRunning():
            return
        self._page = max(1, int(page or 1))
        self._clear()
        self.hint.setText(tr("正在搜索…"))
        self._thread = _Searcher(q, self.src_combo.currentData(), self._page, self)
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
        note = f"第 {self._page} 页 · 共 {len(photos)} 张"
        if errs:
            note += "  ·  " + "; ".join(errs)
        self.hint.setText(note)
        # 满页才可能有下一页;第 1 页没有上一页
        self.pg_lab.setText(f"{self._page} / ?")
        self.pg_prev.setEnabled(self._page > 1)
        self.pg_next.setEnabled(len(photos) >= PER_PAGE)

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
                                on_extra=self._on_transform,
                                style_choices=self._style_choices(),
                                style_default=self._default_style())
        dlg.remote_url_hint = url
        if not dlg.exec() == ImageViewerDialog.Accepted or not dlg.used:
            return                                  # 关闭:回到搜索结果,弹窗继续开着
        # 用了换过画风的版本就用它,否则下原图
        self._download(getattr(dlg, "transformed_url", None) or url,
                       close_immediately=True)

    # ── 预览里的「换画风」 ──
    def _style_choices(self) -> list[tuple[str, str]]:
        """画风下拉的选项:全部启用的风格预设(与制作台画面风格同源)。"""
        from ..core import db
        return [(r["value"], tr(r["name"])) for r in
                db.q("SELECT value, name FROM style_presets "
                     "WHERE is_active=1 ORDER BY sort_order, id")]

    def _default_style(self) -> str:
        """下拉预选值:有项目跟项目画风,没项目给 3d —— 聊天改图里经常没开
        项目,不能拿「项目默认画风」当选项糊弄(用户实测提出)。"""
        d = self._drama_id or _drama_id_of(self)
        return _current_project_style(d) if d else "3d"

    def _on_transform(self, viewer):
        """就地执行:下载原图 → 转下拉选定的画风 → 刷新显示。

        `style_convert.convert_path` 只返回新图路径、**不落库**(手动流程
        先看效果),所以这里不会动任何资产表。
        """
        from ..ai import image_client
        from ..pipeline import style_convert as SC
        from ..core.taskmgr import TASKMGR
        style = (viewer.selected_style() if hasattr(viewer, "selected_style")
                 else None) or self._default_style()
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
        # 等待效果:图片上盖转圈遮罩,只禁动作按钮 —— **不要**整窗
        # setEnabled(False):禁用态走 disabled 调色板,彩色原图整体变灰,
        # 用户以为「生成了黑白」(实测反馈)
        viewer.set_busy(True, tr("正在转换为「{}」画风…").format(style))
        self.hint.setText(tr("正在转换为「{}」画风…").format(style))

        def job(tid):
            return SC.convert_path(src, style, cfg["id"])

        def done(tid, result, error):
            viewer.set_busy(False)
            self.hint.setText(self._hint_text())
            if error or not result:
                err(tr("换画风失败:{}").format(str(error or "")[:120]))
                return
            viewer.transformed_url = str(result)
            viewer.show_local_image(str(result))
            info(tr("已转成「{}」画风 —— 满意点「使用这张」,不满意可换一款再转").format(style))

        TASKMGR.submit("image", job, done)

    def _fetch_to_temp(self, url: str) -> str:
        """远程图下到本地临时文件(换画风要本地路径作参考图)。"""
        if not url:
            return ""
        out_dir = config.STATIC_DIR / "uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"stocksrc_{uuid.uuid4().hex[:10]}.jpg"
        return str(out) if sp.download(url, out) else ""

    def _select_direct(self, url: str, lab=None):
        """双击直接选用:下载等待遮罩盖在该卡片上,成功即 accept
        (聊天流程的调用方会把 local_path 设为当前图)。"""
        if not url:
            return
        if self._dl is not None and self._dl.isRunning():
            return
        self._selecting_lab = lab
        self._download(url)

    def _download(self, url: str, close_immediately: bool = False):
        """把选中的图落地到本地静态目录,完成后 accept。

        close_immediately=True(「使用这张」):弹窗马上关闭,下载转后台,
        完成走 downloaded 信号(而非等在 exec 里的 local_path)。
        """
        self._close_when_done = bool(close_immediately)
        # 两条路:本地路径直接复制(换画风的产物就是本地文件);远程 URL 走后台线程
        out_dir = config.STATIC_DIR / "uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        if url and not str(url).startswith(("http://", "https://")):
            import shutil
            src = pathlib.Path(url)
            if not src.exists():
                err(tr("图片下载失败,请换一张"))
                return
            out = out_dir / f"stock_{uuid.uuid4().hex[:10]}{src.suffix or '.png'}"
            shutil.copy2(src, out)
            self.local_path = str(out)
            self.downloaded.emit(self.local_path)
            self.accept()
            return
        # _dl 首次下载前是 None —— 直接 .isRunning() 会 AttributeError,被 Qt
        # 事件吞掉,表现为「使用这张」关不掉图库页、图也进不来(实测)
        if self._dl is not None and self._dl.isRunning():
            if close_immediately:
                self.accept()      # 关窗不阻塞;上一次下载完成会经信号回填
            return
        ext = ".jpg"
        for cand in (".jpg", ".png", ".jpeg", ".webp"):
            if url.split("?")[0].lower().endswith(cand):
                ext = cand
                break
        out = out_dir / f"stock_{uuid.uuid4().hex[:10]}{ext}"
        self.hint.setText(tr("正在下载…"))
        self._dl = _Downloader(url, str(out), self, timeout=90)
        self._dl.done.connect(self._on_downloaded)
        self._dl.start()
        if getattr(self, "_close_when_done", False):
            # 「使用这张」:两层弹窗立即关闭,后台继续下载(对话框对象因
            # parent 存活,线程完成信号照常回填)
            self.accept()

    def _on_downloaded(self, ok: bool, path: str):
        if ok:
            self.local_path = path
            if getattr(self, "_close_when_done", False):
                self.downloaded.emit(path)   # 弹窗已关,调用方经信号接图
            else:
                self.accept()
        else:
            err(tr("图片下载失败,请换一张"))
            self.hint.setText(self._hint_text())
            lab = getattr(self, "_selecting_lab", None)
            if lab is not None:
                lab.set_busy(False)      # 失败解遮罩,卡片可再选
            if getattr(self, "_close_when_done", False):
                self.downloaded.emit("")  # 先关窗模式:聊天侧弹失败提示
