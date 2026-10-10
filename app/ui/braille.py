# -*- coding: utf-8 -*-
"""盲文式等待指示器(全项目统一):以点字方块(⠿ Braille pattern)循环变化表示忙碌。

用法:
    from .braille import BrailleSpinner, braille_wait

    # 1) 组件内嵌
    sp = BrailleSpinner(); layout.addWidget(sp); sp.start("正在生成封面…")
    ...
    sp.stop()

    # 2) 包裹一个按钮(点击后自动进入等待态)
    btn = WaitingButton("⟳ 生成封面")
    btn.busy("生成中")          # 内嵌 spinner + 禁用
    btn.idle()                  # 恢复
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget
from ..core.i18n import tr

# 盲文点字(Unicode Braille Patterns)——8 点一格,循环即"变化"的等待感
BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧",
                  "⠇", "⠏", "⠛", "⠹", "⠸", "⠼", "⠴", "⠦"]
BRAILLE_DOTS = "⠿⠻⠽⠾⠷"      # 静态"忙碌中"标记
BRAILLE_OK = "⠿⠿"            # 完成


class BrailleSpinner(QWidget):
    """盲文点字旋转指示器。start(text) / stop()。"""

    def __init__(self, color: str = "#f97316", size: int = 15, parent=None):
        super().__init__(parent)
        self._i = 0
        self._color = QColor(color)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setFixedSize(size + 6, 20)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setVisible(False)

    def _tick(self):
        self._i = (self._i + 1) % len(BRAILLE_FRAMES)
        self.update()

    def start(self, label: str = ""):
        self._i = 0
        self._timer.start(90)
        self.setVisible(True)
        self.update()
        if label:
            self.setToolTip(label)
        return self

    def stop(self):
        self._timer.stop()
        self.setVisible(False)
        return self

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont("Segoe UI Symbol", 13)
        p.setFont(f)
        p.setPen(self._color)
        p.drawText(self.rect(), Qt.AlignCenter, BRAILLE_FRAMES[self._i])
        p.end()


class WaitingButton(QPushButton):
    """带盲文等待态的按钮:busy(文案) 时内嵌 spinner + 禁用;idle() 恢复。"""

    def __init__(self, text: str = "", primary: bool = False, parent=None):
        super().__init__(text, parent)
        self._orig_text = text
        self._lay: QHBoxLayout | None = None
        self._spin: BrailleSpinner | None = None
        if primary:
            self.setObjectName("primary")
        self.setCursor(Qt.PointingHandCursor)

    def busy(self, text: str = ""):
        self.setEnabled(False)
        if self._lay is None:
            self._lay = QHBoxLayout(self)
            self._lay.setContentsMargins(12, 0, 12, 0)
            self._lay.setSpacing(6)
        if self._spin is None:
            self._spin = BrailleSpinner(color="#ffffff" if self.objectName() == "primary" else "#f97316", parent=self)
            self._lay.addWidget(self._spin)
        self._spin.start(text)
        if text:
            lab = QLabel(f" {text}")
            lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            self._lay.addWidget(lab)
        self.setText("")

    def idle(self):
        if self._spin:
            self._spin.stop()
        # 清掉 busy 时加的 label
        if self._lay:
            while self._lay.count():
                it = self._lay.takeAt(0)
                w = it.widget()
                if w is not self._spin and w is not None:
                    w.deleteLater()
        self.setText(self._orig_text)
        self.setEnabled(True)


class BrailleBar(QWidget):
    """盲文进度条:点字逐格填充表示进度(未知总量时循环滚动)。"""

    def __init__(self, cells: int = 12, parent=None):
        super().__init__(parent)
        self._cells = cells
        self._done = 0
        self._i = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(16)
        self.setVisible(False)

    def start(self, cells: int | None = None):
        if cells:
            self._cells = max(1, cells)
        self._done = 0
        self._i = 0
        self._timer.start(120)
        self.setVisible(True)
        return self

    def advance(self, n: int = 1):
        self._done = min(self._cells, self._done + n)
        if self._done >= self._cells:
            self.stop()
        self.update()

    def set_done(self, n: int, total: int):
        self._cells = max(1, total)
        self._done = min(self._cells, n)
        self.update()

    def stop(self):
        self._timer.stop()
        self.setVisible(False)

    def _tick(self):
        self._i = (self._i + 1) % len(BRAILLE_FRAMES)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont("Segoe UI Symbol", 11)
        p.setFont(f)
        p.setPen(QColor("#f97316"))
        text = "".join("⣿" if i < self._done else "⠄" for i in range(self._cells))
        p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, text)
        p.end()


def braille_wait(parent_widget, message: str = tr("处理中…")):
    """快捷方式:在 parent 上挂一个盲文等待条(调用方负责 stop)。"""
    bar = BrailleBar(parent=parent_widget)
    bar.start()
    bar.setToolTip(message)
    return bar
