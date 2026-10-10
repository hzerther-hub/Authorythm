# -*- coding: utf-8 -*-
"""批量生成面板:三段式进度条 + 阶段显示 + 伏笔台账 + 审校明细。

对齐原版 episode.vue 未提交批次的批量面板:
  - 三段进度条(成功绿 / 失败红 / 进行中条纹动画)
  - 图例:百分比 / 进行中 n / 成功 n / 失败 n
  - 每章阶段(写正文/审校中/修复问题/卷段压缩)
  - 伏笔台账可交互勾选(乐观更新+失败回滚)
  - 审校问题明细(本地标记)
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QListWidget, QProgressBar, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..core import db
from ..core.i18n import tr
from . import widgets as W

STAGE_CN = {"writing": "写正文", "reviewing": "审校中", "repairing": "修复问题",
            "compressing": "卷段压缩", "splitting": "拆分分镜"}


class _SegmentBar(QWidget):
    """三段式进度条:成功 / 失败 / 进行中。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self._ok = self._fail = self._run = 0
        self._total = 1

    def set_counts(self, ok: int, fail: int, running: int, total: int):
        self._ok, self._fail, self._run = ok, fail, running
        self._total = max(1, total)
        self.update()

    def paintEvent(self, ev):
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e8eaf0"))
        p.drawRoundedRect(0, 0, w, h, 6, 6)
        x = 0.0
        for cnt, color in ((self._ok, "#16a34a"), (self._fail, "#dc2626")):
            seg = w * cnt / self._total
            if seg <= 0:
                continue
            p.setBrush(QColor(color))
            p.drawRoundedRect(int(x), 0, max(int(seg), 1), h, 6, 6)
            x += seg
        if self._run:
            seg = w * self._run / self._total
            p.setBrush(QColor("#f97316"))
            p.drawRoundedRect(int(x), 0, max(int(seg), 1), h, 6, 6)
        p.end()


class _BatchProgressDialog(QDialog):
    """批量生成进度面板(模态浮窗)。"""

    def __init__(self, parent, total: int, page=None):
        super().__init__(parent)
        self.page = page
        self.total = max(1, total)
        self.setWindowTitle(tr("批量生成小说"))
        self.resize(560, 480)
        root = QVBoxLayout(self)

        self.bar = _SegmentBar()
        root.addWidget(self.bar)
        self.legend = W.muted("")
        root.addWidget(self.legend)
        self.stage_lab = W.muted("")
        root.addWidget(self.stage_lab)

        self.rows = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:1px solid rgba(128,128,128,40);border-radius:8px;")
        inner = QWidget()
        inner.setLayout(self.rows)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # 伏笔台账
        self.ledger_btn = QPushButton(tr("▾ 伏笔台账"))
        self.ledger_btn.setCheckable(True)
        self.ledger_btn.toggled.connect(self._toggle_ledger)
        root.addWidget(self.ledger_btn)
        self.ledger_box = QWidget()
        self.ledger_list = QVBoxLayout()
        self.ledger_box.setLayout(self.ledger_list)
        self.ledger_box.setVisible(False)
        root.addWidget(self.ledger_box)

        btns = QHBoxLayout()
        self.rewrite_btn = QPushButton(tr("↻ 重写已完成章节"))
        self.rewrite_btn.clicked.connect(lambda: page and page._rewrite_done_chapters())
        close = QPushButton(tr("close"))
        close.clicked.connect(self.accept)
        btns.addWidget(self.rewrite_btn)
        btns.addStretch(1)
        btns.addWidget(close)
        root.addLayout(btns)
        self._render_ledger()

    # 进度
    def update_progress(self, done: int, total: int):
        running = 1 if done < total else 0
        fail = getattr(self, "_fail", 0)
        self.bar.set_counts(done - fail, fail, running, self.total)
        self.legend.setText(tr('{}%  ·  进行中 {}  ·  成功 {}  ·  失败 {}').format(int((done / self.total) * 100), running, done - fail, fail))
        self._refresh_stage()

    def finish(self, ok: int, fail: int):
        self._fail = fail
        self.bar.set_counts(ok, fail, 0, self.total)
        self.legend.setText(tr('100%  ·  成功 {}  ·  失败 {}').format(ok, fail))
        self.stage_lab.setText(tr("完成"))
        self._render_ledger()

    def _refresh_stage(self):
        if not self.page:
            return
        ids = getattr(self.page, "_batch_ids", [])
        cur = next((i for i in ids if self.page._chapter_running_stage(i)), None)
        self.stage_lab.setText(tr('当前阶段:{}').format(STAGE_CN.get(cur, cur)) if cur else "")

    # 伏笔台账
    def _toggle_ledger(self, on: bool):
        self.ledger_box.setVisible(on)
        self.ledger_btn.setText(tr("▾ 伏笔台账") if on else tr("▸ 伏笔台账"))

    def _render_ledger(self):
        if not self.page:
            return
        from ..pipeline import novel as N
        while self.ledger_list.count():
            it = self.ledger_list.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        data = N.get_ledger(self.page.drama_id)
        if not data["items"]:
            lab = W.muted(tr("(台账为空)"))
            self.ledger_list.addWidget(lab)
            return
        for item in data["items"]:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 1, 2, 1)
            cb = QCheckBox()
            cb.setChecked(bool(item.get("closed")))
            cb.toggled.connect(lambda _v, it=item: self._toggle_ledger_item(it))
            rl.addWidget(cb)
            ch = item.get("open_chapter")
            rl.addWidget(W.tag(tr('第{}章').format(ch) if ch else "—"))
            txt = QLabel(item.get("text", "")[:60])
            txt.setObjectName("muted")
            txt.setWordWrap(True)
            if item.get("closed") or item.get("stale"):
                txt.setStyleSheet("color:#c0c6cf;text-decoration:line-through;")
            rl.addWidget(txt, 1)
            self.ledger_list.addWidget(row)

    def _toggle_ledger_item(self, item: dict):
        from ..pipeline import novel as N
        from .toast import err
        if not self.page:
            return
        was = bool(item.get("closed"))
        item["closed"] = not was          # 乐观更新
        self._render_ledger()
        try:
            N.toggle_ledger(self.page.drama_id, item.get("index", 0),
                            self.page._ep["episode_number"])
        except Exception as e:  # noqa: BLE001
            item["closed"] = was           # 失败回滚
            self._render_ledger()
            err(str(e)[:120])


class ReviewPanelDialog(QDialog):
    """审校问题明细(勾选标记已处理,仅本地不改正文)。"""

    def __init__(self, parent, issues: list, chapter: int = 0, title: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("审校问题明细"))
        self.resize(560, 460)
        root = QVBoxLayout(self)
        root.addWidget(W.h2(tr('第 {} 章 · {}').format(chapter, title) if title else tr('第 {} 章').format(chapter)))
        self.resolved: set[int] = set()
        self.boxes: dict[int, QCheckBox] = {}
        for i, iss in enumerate(issues or []):
            txt = iss if isinstance(iss, str) else str(iss.get("description") or iss.get("issue") or iss)
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 2, 2, 2)
            cb = QCheckBox()
            cb.toggled.connect(lambda v, i=i: self._mark(i, v))
            rl.addWidget(cb)
            lab = QLabel(txt)
            lab.setWordWrap(True)
            rl.addWidget(lab, 1)
            self.boxes[i] = cb
            root.addWidget(row)
        root.addWidget(W.muted(tr("勾选表示你已处理该项(仅本地标记,不修改正文)")))
        close = W.primary_btn(tr("close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

    def _mark(self, i: int, v: bool):
        if v:
            self.resolved.add(i)
        else:
            self.resolved.discard(i)


class ReviewSummaryDialog(QDialog):
    """全书审校清单:逐章列出问题,可跳转。"""

    def __init__(self, parent, data: dict, on_goto=None):
        super().__init__(parent)
        self.setWindowTitle(tr("全书审校清单"))
        self.resize(680, 560)
        self._on_goto = on_goto
        root = QVBoxLayout(self)
        root.addWidget(W.h2(tr('{} 章有问题 · 共 {} 项').format(data.get('total', 0), data.get('issues', 0))))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        items = data.get("items") or []
        if not items:
            lay.addWidget(W.muted(tr("全书没有审校问题")))
        for it in items:
            box = W.make_card()
            bl = QVBoxLayout(box)
            head = QHBoxLayout()
            head.addWidget(W.tag(tr('第{}章').format(it.get('episode_number'))))
            head.addWidget(QLabel(it.get("title") or ""))
            head.addWidget(W.tag(tr('{} 项').format(it.get('count', 0))))
            head.addStretch(1)
            go = QPushButton(tr("去这章"))
            go.clicked.connect(lambda _=False, e=it.get("episode_id"): self._goto(e))
            head.addWidget(go)
            bl.addLayout(head)
            for s in (it.get("issues") or [])[:20]:
                lab = QLabel("· " + str(s))
                lab.setObjectName("muted")
                lab.setWordWrap(True)
                bl.addWidget(lab)
            lay.addWidget(box)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)
        close = W.primary_btn(tr("close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

    def _goto(self, episode_id):
        if self._on_goto:
            self._on_goto(episode_id)
        self.accept()
