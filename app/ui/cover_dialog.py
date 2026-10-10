# -*- coding: utf-8 -*-
"""封面:项目封面 / 单章封面(对齐原版 detail.vue 的项目封面区 + generate-episode-cover)。

项目封面区:3:4 竖版展示 + 提示词输入 + 生成按钮 + 点击放大;
已有角色/场景/道具资产时自动以资产图为参考,保证封面与正片一致。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..core import db
from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from . import widgets as W
from .braille import WaitingButton, BrailleSpinner
from .toast import err, ok


class CoverPreviewDialog(QDialog):
    """封面放大预览。"""
    def __init__(self, parent, url: str | None, title: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("封面预览") + (f" · {title}" if title else ""))
        self.resize(560, 760)
        root = QVBoxLayout(self)
        img = QLabel()
        img.setAlignment(Qt.AlignCenter)
        # 3:4 竖版,contain 完整显示不裁切不拉伸
        pm = W.pixmap_from_media(url, 520, 694)
        img.setPixmap(pm)
        root.addWidget(img, 1)
        close = W.primary_btn(tr("close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)


class CoverPanel(QWidget):
    """项目封面区(项目页头部下方)。"""
    def __init__(self, drama_id: int, on_changed=None):
        super().__init__()
        self.drama_id = drama_id
        self._on_changed = on_changed
        self._busy = False
        self.status = None
        d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(W.muted(tr("项目封面:AI 生成竖版封面;有角色/场景资产时自动以资产图为参考,保证与正片一致")))
        head.addStretch(1)
        root.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.img = QLabel()
        self.img.setFixedSize(150, 200)  # 3:4
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setStyleSheet("border:1px solid rgba(128,128,128,60);border-radius:8px;background:#f7f8fa;")
        self.img.setPixmap(W.pixmap_from_media(d["thumbnail"] if d else None, 146, 196))
        self.img.mousePressEvent = lambda _e: CoverPreviewDialog(self, self._url, d["title"] if d else "").exec()
        self.img.setToolTip(tr("点击查看大图"))
        row.addWidget(self.img)
        right = QVBoxLayout()
        self.prompt = QLineEdit()
        self.prompt.setPlaceholderText(tr("封面提示词(留空则按项目标题/简介/画风自动生成)"))
        gen = WaitingButton(tr("⟳ 生成封面"), primary=True)
        gen.clicked.connect(self._generate)
        self.gen_btn = gen
        right.addWidget(self.prompt)
        right.addWidget(gen, 0, Qt.AlignLeft)
        right.addStretch(1)
        row.addLayout(right, 1)
        root.addLayout(row)
        self._url = d["thumbnail"] if d else None

    def _generate(self):
        if self._busy:
            return
        self._busy = True
        self.gen_btn.busy(tr("正在生成封面"))
        self.img.setPixmap(W.pixmap_from_media(None, 146, 196))
        self.status = BrailleSpinner(color="#f97316", size=17)
        self.status.start(tr("AI 正在绘制封面…"))
        self.gen_btn.layout().addWidget(self.status)

        def job(tid):
            from ..pipeline import novel as novel_pipe
            return novel_pipe.generate_cover(self.drama_id, self.prompt.text().strip())

        def done(tid, result, error):
            self._busy = False
            self.gen_btn.idle()
            if self.status:
                self.status.stop()
                self.gen_btn.layout().removeWidget(self.status)
                self.status = None
            if error:
                err(error)
                return
            self._url = result
            self.img.setPixmap(W.pixmap_from_media(result, 146, 196))
            ok(tr("封面已生成"))
            if self._on_changed:
                self._on_changed()

        tid = TASKMGR.submit("image", job, done, drama_id=self.drama_id)
        if not tid:
            self._busy = False
            self.gen_btn.idle()
            if self.status:
                self.status.stop()


class EpisodeCoverButton(QPushButton):
    """剧集卡上的章封面生成按钮。"""
    def __init__(self, episode: dict, on_done=None, parent=None):
        super().__init__(tr("▣ 章封面"), parent)
        self.episode = dict(episode)
        self._on_done = on_done
        self.setToolTip(tr("AI 生成单章封面(3:4 竖版)"))
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._gen)

    def _gen(self):
        ep_id = self.episode["id"]
        def job(tid):
            from ..pipeline import novel as novel_pipe
            return novel_pipe.generate_episode_cover(ep_id)
        def done(tid, result, error):
            if error:
                err(e_)
                return
            ok(tr("章封面已生成"))
            if self._on_done:
                self._on_done()
        TASKMGR.submit("image", job, done, episode_id=ep_id)
