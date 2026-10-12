# -*- coding: utf-8 -*-
"""快捷键帮助对话框:列出 4 个文本编辑快捷键 + 详细说明。

被原始内容 / AI改写工具条尾部的「?」按钮调用。两个面板共用同一个 dialog。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
                               QLabel, QVBoxLayout, QWidget)

from ..core.i18n import tr
from ..core.theme import SLATE_FORM_QSS, MONO_STACK


class ShortcutHelpDialog(QDialog):
    """4 个快捷键说明(Ctrl+L/R/F/Q)。每行 = 单色块键帽 + 标题 + 描述。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("kbd_help_title"))
        self.setMinimumWidth(440)
        # 局部 slate 化,跟其他对话框一致
        self.setStyleSheet(SLATE_FORM_QSS)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        lay.setSpacing(8)

        title = QLabel(tr("kbd_help_title"))
        title.setObjectName("slateH2")
        lay.addWidget(title)

        items = [
            ("Ctrl+L", "kbd_l_title", "kbd_l_desc"),
            ("Ctrl+R", "kbd_r_title", "kbd_r_desc"),
            ("Ctrl+F", "kbd_f_title", "kbd_f_desc"),
            ("Ctrl+Q", "kbd_q_title", "kbd_q_desc"),
        ]
        for kbd, t_key, d_key in items:
            lay.addWidget(self._row(kbd, tr(t_key), tr(d_key)))

        lay.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        bb.button(QDialogButtonBox.Close).setText(tr("kbd_close"))
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)

    def _row(self, keycap: str, title: str, desc: str) -> QFrame:
        """单行:左侧黑色键帽(mono caps)+ 右侧标题(白)/描述(灰)。"""
        row = QFrame()
        row.setStyleSheet(
            "QFrame{background:transparent;border:1px solid #DCDAD3;border-radius:4px;}"
        )
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)
        # 键帽 —— 拍板黑底 + 米白字,monospace caps,像键盘键帽
        cap = QLabel(keycap)
        cap.setFixedHeight(38)
        cap.setMinimumWidth(86)
        cap.setAlignment(Qt.AlignCenter)
        cap.setStyleSheet(
            "background:#0E0F12;color:#F5F4EF;border:none;border-radius:3px;"
            f"font-family:{MONO_STACK};font-size:12px;font-weight:700;"
            "letter-spacing:0.5px;"
        )
        lay.addWidget(cap)
        # 标题 + 描述
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet("color:#0E0F12;font-size:13px;font-weight:700;border:none;")
        d = QLabel(desc)
        d.setStyleSheet("color:#6B727A;font-size:11px;border:none;")
        d.setWordWrap(True)
        text.addWidget(t)
        text.addWidget(d)
        wrap = QWidget()
        wrap.setStyleSheet("background:transparent;border:none;")
        wrap.setLayout(text)
        lay.addWidget(wrap, 1)
        return row
