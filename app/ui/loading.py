"""Loading 基座:按钮内嵌 spinner + 忙碌守卫(对齐原版 Loader2 / running 态)。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QPushButton, QWidget


class Spinner(QWidget):
    """轻量旋转指示器(纯 QPaint,不依赖资源)。"""
    def __init__(self, size: int = 14, color: str = "#ffffff", parent=None):
        super().__init__(parent)
        self._angle = 0
        self._size = size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._color = QColor(color)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)

    def _tick(self):
        self._angle = (self._angle + 30) % 360
        self.update()

    def stop(self):
        self._timer.stop()

    def paintEvent(self, ev: QPaintEvent):
        from PySide6.QtGui import QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(self._color, 2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        import math
        cx = cy = self._size / 2
        r = self._size / 2 - 2
        for i in range(8):
            a0 = math.radians(self._angle + i * 45)
            a1 = a0 + math.radians(28)
            p.setOpacity(0.25 + 0.75 * (i / 7))
            p.drawLine(int(cx + r * math.cos(a0)), int(cy + r * math.sin(a0)),
                       int(cx + r * math.cos(a1)), int(cy + r * math.sin(a1)))
        p.end()


class BusyButton(QPushButton):
    """带 spinner 的按钮:start(text=可选替换文案)/stop()。"""
    def __init__(self, text: str = "", primary: bool = False, parent=None):
        super().__init__(text, parent)
        if primary:
            self.setObjectName("primary")
        self._orig_text = text
        self._spinner: Spinner | None = None
        self._busy_text: str | None = None

    def start(self, busy_text: str | None = None):
        self._busy_text = busy_text
        self.setEnabled(False)
        if self._spinner is None:
            self._spinner = Spinner(14, "#ffffff" if self.objectName() == "primary" else "#f97316", self)
        lay = self.layout()
        if lay is None:
            from PySide6.QtWidgets import QHBoxLayout
            lay = QHBoxLayout(self)
            lay.setContentsMargins(10, 0, 10, 0)
        self.setText(busy_text if busy_text else self._orig_text)
        lay.addWidget(self._spinner, 0, Qt.AlignVCenter)

    def stop(self):
        self.setEnabled(True)
        if self._spinner is not None:
            if self._spinner.parent() is self.layout():
                self.layout().removeWidget(self._spinner)
            self._spinner.deleteLater()
            self._spinner = None
        self.setText(self._orig_text)
