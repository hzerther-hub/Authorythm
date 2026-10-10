# -*- coding: utf-8 -*-
"""统一确认/警告对话框。

原来是 14 处散落的 QMessageBox.question / warning,问题有三:
  - 标题正文一半没走 tr(),切语言不动
  - 系统原生样式与本项目自绘的卡片/胶囊风格不一致,亮暗主题下尤其明显
  - 删除类操作只有 Yes/No 两个按钮,没有把「要删的东西叫什么」摆出来

ConfirmDialog 统一成一个自绘的:Enter=确认、Esc=取消、危险操作红色描边 + 明确的主语。
ask() 是 question 的替代,warn() 是 warning 的替代,调用点只需换函数名。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..core.i18n import tr

DANGER_BG = "#fef2f2"
DANGER_BORDER = "#fca5a5"
DANGER_BTN = "#dc2626"
NORMAL_BG = "#f8fafc"
NORMAL_BORDER = "#e2e8f0"
NORMAL_BTN = "#f97316"


class ConfirmDialog(QDialog):
    """确认框。默认模态,Enter 确认 / Esc 取消。"""

    def __init__(self, parent, title: str, message: str, *, danger: bool = False,
                 ok_text: str = "", cancel_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        self._result = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        if title:
            t = QLabel(title)
            t.setObjectName("h2")
            t.setWordWrap(True)
            root.addWidget(t)

        m = QLabel(message)
        m.setWordWrap(True)
        m.setTextInteractionFlags(Qt.TextSelectableByMouse)
        m.setStyleSheet(
            f"background:{DANGER_BG if danger else NORMAL_BG};"
            f"border:1px solid {DANGER_BORDER if danger else NORMAL_BORDER};"
            f"border-radius:10px; padding:12px;")
        root.addWidget(m)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(cancel_text or tr("u_cancel"))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(ok_text or (tr("u_delete") if danger else tr("u_apply")))
        ok.setObjectName("primary")
        ok.setStyleSheet(
            f"background:{DANGER_BTN if danger else NORMAL_BTN}; color:#fff;"
            f"border:none; border-radius:8px; padding:8px 20px; font-weight:600;")
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        cancel.setAutoDefault(False)
        row.addWidget(cancel)
        row.addWidget(ok)
        root.addLayout(row)

    def keyPressEvent(self, e: QKeyEvent) -> None:      # noqa: N802 (Qt 命名)
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.accept()
        else:
            super().keyPressEvent(e)


def ask(parent, title: str, message: str, *, danger: bool = False,
        ok_text: str = "") -> bool:
    """确认框;True 表示用户点了确认。"""
    dlg = ConfirmDialog(parent, title, message, danger=danger, ok_text=ok_text)
    return dlg.exec() == QDialog.Accepted


def warn(parent, title: str, message: str) -> None:
    """警告框:只有一个「知道了」。"""
    dlg = ConfirmDialog(parent, title, message, ok_text=tr("u_close"))
    dlg.exec()
