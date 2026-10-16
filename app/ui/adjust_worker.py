# -*- coding: utf-8 -*-
"""调色预览的后台计算线程。

为什么必须在后台:11 参全开一次要一两百毫秒(降采样预览)到一秒
(1080p 落盘),放 GUI 线程里拖滑杆会明显卡顿 —— 表现为"拖一下顿一下"。
QThread + Signal 由 Qt 自动跨线程投递回 GUI 线程,worker 里不碰任何控件。

**节流**:拖滑杆会连续触发几十次,每次都算一遍纯属浪费。这里按
`min_interval_ms` 合并 —— 正在算的时候来的请求只记下最新一组参数,
算完如果参数变了就再算一次。滑杆快速拖到底只会算两三次,不是几十次。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QWidget


class AdjustWorker(QThread):
    """在后台跑 img_adjust,出图后 emit(image)。失败 emit(None, 错误文本)。"""

    done = Signal(object, str)      # (PIL.Image | None, 错误信息)

    def __init__(self, src: str, preview_side: int = 640,
                 preview: bool = True, parent=None):
        super().__init__(parent)
        self.src = src
        self.preview_side = preview_side
        self.preview = preview
        self._pending: dict | None = None
        self._running = False
        self._lock_q: list[dict] = []

    def request(self, params: dict):
        """提交一组参数。已在算就只覆盖待算的那组(丢掉中间的)。"""
        self._lock_q[:] = [dict(params)]
        if not self._running:
            self._drain()

    def _drain(self):
        if not self._lock_q:
            self._running = False
            return
        params = self._lock_q.pop(0)
        self._running = True
        self.start()

    def run(self):
        from ..pipeline import img_adjust as IA
        try:
            while self._lock_q:
                params = self._lock_q.pop(0)
                if self.preview:
                    img = IA.adjust_preview(self.src, self.preview_side, **params)
                else:
                    img = IA.adjust(self.src, None, **params)
                # 算完发现又有新参数了 → 继续循环,本次结果不发(避免闪旧图)
                if self._lock_q:
                    continue
                self.done.emit(img, "")
                return
            self._running = False
        except Exception as exc:  # noqa: BLE001
            self._running = False
            self.done.emit(None, str(exc)[:200])


class BusyOverlay(QWidget):
    """盖在预览图上的等待层:半透明遮罩 + 盲文 spinner + 文案。

    放预览区正中而不是右上角 —— 用户的眼睛本来就盯着图,提示在那里才看得到。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QHBoxLayout, QLabel
        from .braille import BrailleSpinner
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("background:rgba(20,20,20,90);")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addStretch(1)
        self.spin = BrailleSpinner(size=18)
        lay.addWidget(self.spin)
        self.label = QLabel("")
        self.label.setStyleSheet("color:#fff;font-size:12px;")
        lay.addWidget(self.label)
        lay.addStretch(1)
        self.hide()

    def start(self, text: str = ""):
        self.label.setText(text)
        self.spin.start()
        self.raise_()
        self.show()

    def stop(self):
        self.spin.stop()
        self.hide()
