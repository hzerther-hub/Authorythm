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
                               QPushButton, QScrollArea, QTextEdit, QVBoxLayout,
                               QWidget)

from datetime import datetime

from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from . import episode_cards as C
from . import widgets as W

STATE_OF = {"processing": ("pending", "in_progress"), "completed": ("done", "done"),
            "failed": ("failed", "failed"), "blocked": ("failed", "failed"),
            "pending": ("ready", "pending")}
DOT_COLOR = {"pending": "#e0794b", "done": "#16a34a", "failed": "#dc2626", "ready": "#86909c"}


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
        close = QPushButton("✕")
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
        self.reload()

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
        for r in rows:
            state, label = STATE_OF.get(r["status"], ("ready", r["status"]))
            counts[state] = counts.get(state, 0) + 1
            self.list_lay.insertWidget(self.list_lay.count() - 1,
                                       self._task_row(dict(r), state, label))
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
        state_lab = QLabel(label)
        state_lab.setStyleSheet(f"color:{DOT_COLOR.get(state, '#86909c')}; font-size:11px;")
        lay.addWidget(state_lab)
        return row