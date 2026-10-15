# -*- coding: utf-8 -*-
"""生成任务抽屉:从右侧滑出的任务队列(对齐原版 episode.vue 的 .task-drawer)。

头部「生成任务列表 / 按创建时间倒序 · N 个任务」+ 刷新/关闭,
下面是「N 生成中 / N 完成 / N 失败」三枚统计胶囊,再下面是任务行列表
(缩略图 + 名称 + provider/model/耗时/ID + 状态点);空态给出引导文案。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSlider, QTextEdit,
                               QVBoxLayout, QWidget)

from datetime import datetime

from ..core.i18n import tr
from ..core import db
from ..core.taskmgr import TASKMGR
from ..core.theme import (SLATE_ASSET_QSS, SLATE_BAR, SLATE_HAIR, SLATE_MUTED,
                          SLATE_ST_DONE, SLATE_ST_PROG, SLATE_ST_FAIL,
                          SLATE_BG, SLATE_PAPER, MONO_STACK)
from . import episode_cards as C
from . import widgets as W

STATE_OF = {"processing": ("pending", "in_progress"), "completed": ("done", "done"),
            "failed": ("failed", "failed"), "blocked": ("failed", "failed"),
            "pending": ("ready", "pending")}
# slate 状态点:不用 SaaS 的橘/绿/红三色,走 SLATE_ST_* 低饱和 —— 与启动台/工作台一致
DOT_COLOR = {"pending": SLATE_ST_PROG, "done": SLATE_ST_DONE,
             "failed": SLATE_ST_FAIL, "ready": SLATE_MUTED}


class ErrorDialog(QDialog):
    """完整错误详情:等宽只读框(可选中)+ 一键复制。

    错误常常是 4KB 级别的 traceback,列表里只截断显示 120 字符,tooltip 也没法
    方便地拿走全文 —— 排查时要贴给日志/工单,这里给一个能直接 Ctrl+A / 复制的框。
    """

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 12)
        lay.setSpacing(8)
        box = QTextEdit()
        box.setReadOnly(True)
        box.setPlainText(text)
        box.setLineWrapMode(QTextEdit.NoWrap)
        # 等宽:traceback 要按行读。必须走样式表 —— 主题的 FONT_STACK 是全局
        # font-family,优先级高于 setFont,直接 setFont(Consolas) 会被吃掉。
        # 报错文案里混着中文,Consolas 无 CJK 字形时 Qt 会自动回退,不影响。
        box.setObjectName("errDetail")
        box.setStyleSheet("#errDetail{font-family:Consolas,'Courier New',monospace;"
                          "font-size:12px;}")
        lay.addWidget(box, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        copy_btn = QPushButton(tr("copy"))
        close_btn = QPushButton(tr("u_close"))
        copy_btn.setDefault(True)
        row.addWidget(copy_btn)
        row.addWidget(close_btn)
        lay.addLayout(row)
        close_btn.clicked.connect(self.accept)
        copy_btn.clicked.connect(lambda: self._copy(box, text))

    @staticmethod
    def _copy(box, text: str) -> None:
        """全选后走 Qt 剪贴板 —— 比构造隐藏 textarea 稳,也不依赖焦点。"""
        box.selectAll()
        QApplication.clipboard().setText(text)
        from .toast import ok
        ok(tr("copied"))


def show_error_dialog(title: str, text: str, parent=None) -> None:
    ErrorDialog(title, text, parent).exec()


class TaskDrawer(QWidget):
    """右侧抽屉(无边框浮层);由 MainWindow 或 EpisodePage 摆进 QStackedWidget。"""

    closed = Signal(object)  # 发出自身,便于宿主移除

    def __init__(self, episode_id: int | None = None, parent=None):
        super().__init__(parent)
        self.episode_id = episode_id
        # Director's Slate:本抽屉继承 SLATE_ASSET_QSS(#inspector / #taskHead /
        # #taskTitle / #taskRow / #taskIndex / #taskName / #taskMeta / #taskError /
        # #statusDot 全部生效),不需逐 widget 设 inline
        self.setStyleSheet(SLATE_ASSET_QSS)
        # 抽屉本体是「不绘制背景」的普通子控件 —— 主题里没有裸的 QWidget 背景规则,
        # 所以遮罩之外自然透出下层页面(与参考项目一致:当前界面被压暗但仍可见)。
        # 刻意**不要**用 WA_TranslucentBackground:该属性只适用于顶层窗口,用在子控件上
        # 会让 Windows 把整个窗口切到分层合成,抽屉销毁后主区域留下不重绘的暗块。
        self.setAutoFillBackground(False)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scrim = QFrame()
        scrim.setStyleSheet("background:rgba(0,0,0,0.18); border:none;")
        scrim.mousePressEvent = lambda _e: self.closed.emit(self)
        root.addWidget(scrim, 1)

        aside = QFrame()
        aside.setObjectName("inspector")
        self.aside = aside
        al = QVBoxLayout(aside)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(0)

        head = QFrame()
        head.setObjectName("taskHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(16, 14, 14, 12)
        hl.setSpacing(2)
        top = QHBoxLayout()
        t = QLabel(tr("gen_task_list"))
        t.setObjectName("taskTitle")
        top.addWidget(t)
        top.addStretch(1)
        refresh = QPushButton("⟳ " + tr("refresh"))
        refresh.clicked.connect(self.reload)
        top.addWidget(refresh)
        close = W.svg_icon_btn("close", "", size=28)
        close.setFixedWidth(28)
        close.setStyleSheet("border:none; background:transparent;")
        close.clicked.connect(lambda: self.closed.emit(self))
        top.addWidget(close)
        hl.addLayout(top)
        self.meta = QLabel("")
        self.meta.setObjectName("muted")
        hl.addWidget(self.meta)
        al.addWidget(head)

        metrics = QFrame()
        metrics.setObjectName("taskHead")
        ml = QHBoxLayout(metrics)
        ml.setContentsMargins(16, 10, 16, 10)
        ml.setSpacing(8)
        self.pills: dict[str, QLabel] = {}
        for state, key in (("pending", "in_progress"), ("done", "done"), ("failed", "failed")):
            lab = C.status_pill(state, f"0 {tr(key)}")
            ml.addWidget(lab)
            self.pills[state] = lab
        ml.addStretch(1)
        al.addWidget(metrics)

        self.scroll = C.scroll_host(QWidget())
        self.host = self.scroll.widget()
        self.list_lay = QVBoxLayout(self.host)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(0)
        self.list_lay.addStretch(1)
        al.addWidget(self.scroll, 1)
        root.addWidget(aside)

        TASKMGR.updated.connect(self.reload)
        # 进度信号:上游每变一次百分比就重跑一次 reload() 代价太大
        #(全量 destroy+insert 100 行),所以只把这一行原地换掉
        self._connect_progress_signal()
        self.reload()

    def _connect_progress_signal(self):
        """把 taskmgr 的全局 progress 信号接到本面板的局部刷新。"""
        from ..core.taskmgr import _signals
        try:
            sig = _signals()
            sig.progress.connect(self._on_progress, Qt.QueuedConnection)
        except Exception:  # noqa: BLE001
            pass      # 没有信号通道时退回「只有转圈」的旧行为,不影响生成

    def _on_progress(self, task_id: int, _pct: int):
        """只重渲受影响的那一行;找不到(不在本集/已滑出列表)就整表刷新兜底。"""
        try:
            row = db.q1("SELECT * FROM sys_task WHERE id=?", (task_id,))
            if not row:
                return
            r = dict(row)
            if self.episode_id and r.get("episode_id") != self.episode_id:
                return
            state, label = STATE_OF.get(r.get("status") or "processing",
                                        ("pending", tr("in_progress")))
            # 进度变化频率远高于任务增删,整表刷新在 100 行规模下会明显卡顿
            self._patch_row(r["id"], state, label, _pct)
        except Exception:  # noqa: BLE001
            pass

    def _patch_row(self, task_id: int, state: str, label: str, pct: int = 0):
        """只换这一行的状态文字;行不在列表里(滑出 limit 或还没渲染)退回整表刷新。"""
        widget = getattr(self, "_row_by_id", {}).get(task_id)
        if widget is None:
            self.reload()
            return
        widget._pct = max(0, min(100, int(pct or 0)))
        for lab in widget.findChildren(QLabel):
            if lab.objectName() == "taskState":
                pv = widget._pct
                lab.setText(f"{label} {pv}%" if pv > 0 else label)
                return

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # 侧栏宽度随窗口走(对齐参考项目:约占界面 1/3 宽),小窗口不至于挤成一条缝
        self.aside.setFixedWidth(max(360, min(660, int(self.width() * 0.34))))

    def reload(self):
        rows = TASKMGR.list_tasks(self.episode_id, limit=100)
        while self.list_lay.count():
            it = self.list_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        counts = {"pending": 0, "done": 0, "failed": 0, "ready": 0}
        # 行 → 任务 id 的索引:progress 信号按 id 定位行做局部刷新,避免整表重建
        self._row_by_id = {}
        for r in rows:
            state, label = STATE_OF.get(r["status"], ("ready", r["status"]))
            counts[state] = counts.get(state, 0) + 1
            widget = self._task_row(dict(r), state, label)
            self._row_by_id[r["id"]] = widget
            self.list_lay.insertWidget(self.list_lay.count() - 1, widget)
        self.list_lay.addStretch(1)
        if not rows:
            self.list_lay.insertWidget(0, C.empty_state(
                "☰", tr("gen_task_empty_title"), tr("gen_task_empty_desc")))
        self.meta.setText(tr("gen_task_meta", len(rows)))
        for state, lab in self.pills.items():
            lab.setText(f"{counts.get(state, 0)} {lab.text().split(' ', 1)[1]}")

    def _task_row(self, r: dict, state: str, label: str) -> QWidget:
        row = QFrame()
        row.setObjectName("taskRow")
        row.setProperty("state", state)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)
        thumb = QFrame()
        thumb.setFixedSize(56, 34)
        thumb.setStyleSheet("border-radius:4px; background:rgba(128,128,128,0.14);")
        tl = QVBoxLayout(thumb)
        tl.setContentsMargins(0, 0, 0, 0)
        if r.get("result_url") or r.get("local_path"):
            im = QLabel()
            im.setAlignment(Qt.AlignCenter)
            im.setPixmap(W.pixmap_from_media(r["result_url"] or r["local_path"], 56, 34))
            tl.addWidget(im)
        else:
            ph = QLabel("⠋" if state == "pending" else "○")
            ph.setAlignment(Qt.AlignCenter)
            ph.setStyleSheet(f"color:{DOT_COLOR.get(state, '#86909c')}; border:none;")
            tl.addWidget(ph)
        kind = QLabel(r.get("type") or "")
        kind.setObjectName("taskIndex")
        tl.addWidget(kind, 0, Qt.AlignLeft)
        lay.addWidget(thumb)
        main = QVBoxLayout()
        main.setSpacing(1)
        name = QLabel(tr(r.get("type") or "task"))
        name.setObjectName("taskName")
        name.setToolTip(name.text())
        name.setWordWrap(True)
        main.addWidget(name)
        bits = [b for b in (r.get("provider"), r.get("model")) if b]
        if r.get("created_at") and r.get("updated_at"):
            try:
                span = (datetime.fromisoformat(r["updated_at"])
                        - datetime.fromisoformat(r["created_at"])).total_seconds()
                bits.append(tr("elapsed", round(span, 1)))
            except (TypeError, ValueError):
                pass
        bits.append(f"#{r['id']}")
        meta = QLabel(" · ".join(bits))
        meta.setObjectName("taskMeta")
        meta.setWordWrap(True)
        main.addWidget(meta)
        if r.get("error_msg"):
            er = QLabel(str(r["error_msg"])[:120])
            er.setObjectName("taskError")
            er.setWordWrap(True)
            er.setToolTip(tr("click_view_error"))
            er.setCursor(Qt.PointingHandCursor)
            full = str(r["error_msg"])
            er.mouseReleaseEvent = lambda _e, t=full: show_error_dialog(
                tr("error_detail"), t, parent=self.window())
            main.addWidget(er)
        lay.addLayout(main, 1)
        # 生成中的任务把官方 progress 百分比拼在状态词后面 ——
        # 否则 50 分钟的等待里用户只能看到一个转圈,分不清排队还是卡死
        pct = r.get("progress")
        if state == "pending":
            try:
                pv = int(pct or 0)
            except (TypeError, ValueError):
                pv = 0
            if pv > 0:
                label = f"{label} {pv}%"
        state_lab = QLabel(label)
        state_lab.setObjectName("taskState")
        state_lab.setStyleSheet(f"color:{DOT_COLOR.get(state, '#86909c')}; font-size:11px;")
        lay.addWidget(state_lab)
        # 供 _on_progress 局部刷新:记住这行的百分比与所属任务 id
        row.setProperty("taskId", r.get("id"))
        try:
            row._pct = int(pct or 0)
        except (TypeError, ValueError):
            row._pct = 0
        return row

class BigPlayerDialog(QDialog):
    """弹出的大窗播放器:独立可缩放,带播放/暂停与进度条。

    内嵌播放器固定 198px 高,竖屏短剧在那点高度里几乎看不清;这里给一个
    可自由缩放的窗口,默认按视频比例撑大,方便逐帧核对画面。
    """

    def __init__(self, title: str, path: str, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        self.setWindowTitle(title)
        self.resize(960, 760)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 10)
        lay.setSpacing(8)
        self._vw = QVideoWidget()
        self._vw.setMinimumHeight(360)
        self._vw.setStyleSheet("border:none; border-radius:8px; background:#000;")
        lay.addWidget(self._vw, 1)
        self._player = QMediaPlayer(self)
        self._player.setVideoOutput(self._vw)
        self._player.setAudioOutput(QAudioOutput(self._player))
        self._player.setSource(QUrl.fromLocalFile(str(path)))
        ctl = QHBoxLayout()
        self._btn = QPushButton("▶")
        self._btn.setFixedSize(44, 32)
        self._btn.clicked.connect(self._toggle)
        self._pos = QSlider(Qt.Horizontal)
        self._pos.setEnabled(False)
        self._pos.sliderMoved.connect(lambda v: self._player.setPosition(v))
        self._lab = QLabel("0:00 / 0:00")
        self._lab.setObjectName("muted")
        self._player.durationChanged.connect(
            lambda d: (self._pos.setRange(0, max(1, int(d))), self._lab.setText(
                f"0:00 / {int(d//60000)}:{int(d//1000)%60:02d}")))
        self._player.positionChanged.connect(
            lambda ms: self._lab.setText(f"{int(ms//60000)}:{int(ms//1000)%60:02d} / "
                                         f"{int(self._player.duration()//60000)}:"
                                         f"{int(self._player.duration()//1000)%60:02d}"))
        self._player.playbackStateChanged.connect(
            lambda st: self._btn.setText("⏸" if st == QMediaPlayer.PlaybackState.PlayingState else "▶"))
        ctl.addWidget(self._btn)
        ctl.addWidget(self._pos, 1)
        ctl.addWidget(self._lab)
        lay.addLayout(ctl)
        # 按视频实际比例给个合适的初始窗口尺寸
        from pathlib import Path as _P
        import subprocess as _sp
        try:
            from ..core import config as _cfg
            exe = _cfg.find_ffprobe()
            if exe:
                import json as _json
                r = _sp.run([exe, "-v", "quiet", "-print_format", "json", "-show_streams",
                             "-select_streams", "v:0", str(path)], capture_output=True, text=True)
                st = _json.loads(r.stdout)["streams"][0]
                w, h = int(st["width"]), int(st["height"])
                hgt = min(900, max(480, int(w * 0.62) + 120))
                self.resize(min(1400, w + 60), hgt)
        except Exception:  # noqa: BLE001
            pass
        self._player.play()

    def _toggle(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()
