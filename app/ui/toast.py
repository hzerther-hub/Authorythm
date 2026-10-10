# -*- coding: utf-8 -*-
"""全局 Toast + 错误友好化(对齐原版 useToast.ts / mapError)。

- toast():右上角浮层,分级 info/success/warning/error,N 秒自动消失,可堆叠,不阻塞。
- map_error():把后端/网络异常映射为用户可读文案(网络/非 JSON/鉴权/限频/审核/超时/5xx 优先级短路)。
"""
from __future__ import annotations

import re

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, Qt,
                            QTimer, Signal)
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

from ..core.i18n import tr

COLORS = {
    "info": ("#1f2937", "#ffffff"),
    "success": ("#16a34a", "#ffffff"),
    "warning": ("#d97706", "#ffffff"),
    "error": ("#dc2626", "#ffffff"),
}


def map_error(err: object) -> str:
    """把异常映射为用户可读文案(对齐原版 mapError 的优先级短路)。

    注意:下面**左边当针用的中文不能翻**。它们拿去和后端/模型抛出来的原始错误串比对,
    那些串永远是中文;翻了针就永远匹配不上,分支直接失效。所以只有 return 的那半句走 tr()。
    """
    s = str(err) if err is not None else ""
    low = s.lower()
    # AI 服务未就绪(未配置/停用/缺 Key/缺模型)——最高优先级,直接透传并给出去处
    if "未就绪" in s or "未配置" in s and "服务" in s:
        return s.replace("服务未就绪:", "").strip()
    if "failed to fetch" in low or "connection" in low or "connect" in low or "network" in low:
        return tr("网络连接失败,请检查网络或服务地址")
    if "timeout" in low or "timed out" in low or "超时" in s:
        return tr("请求超时,服务响应过慢,请稍后重试")
    if "api key" in low or "unauthorized" in low or "401" in low or "403" in low or "鉴权" in s:
        return tr("鉴权失败,请检查 API Key 是否正确")
    if "429" in low or "rate" in low or "限频" in s or "too many" in low:
        return tr("请求过于频繁(限流),请稍后再试")
    if "invalid temperature" in low:
        return tr("该模型不支持所填 Temperature,请在「设置 → AI 服务」调整")
    if "审核" in s or "moderation" in low or "content policy" in low:
        return tr("内容未通过平台审核,请调整描述后重试")
    if "api error 5" in low or "internal server" in low or "500" in low or "502" in low or "503" in low:
        return tr("服务暂时不可用(5xx),请稍后重试")
    m = re.search(r"api error \d+:?\s*(.*)", s, re.I)
    if m and m.group(1):
        return m.group(1)[:160]
    return s[:160] if s else tr("未知错误")


class _Toast(QFrame):
    closed = Signal()

    def __init__(self, text: str, kind: str, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        bg, fg = COLORS.get(kind, COLORS["info"])
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#toast{{background:{bg};color:{fg};border-radius:8px;}}"
            f"QLabel{{color:{fg};background:transparent;}}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 10)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(380)
        f = self.label.font()
        f.setPointSize(9)
        self.label.setFont(f)
        lay.addWidget(self.label)
        close = QPushButton("✕")
        close.setFixedSize(22, 22)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(f"QPushButton{{color:{fg};background:transparent;border:none;}}")
        close.clicked.connect(self._dismiss)
        lay.addWidget(close, 0, Qt.AlignTop)
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.finished.connect(self._on_anim_done)
        self._closing = False

    def show_in(self):
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_anim_done(self):
        if self._closing:
            self.closed.emit()
            self.deleteLater()

    def _dismiss(self):
        if self._closing:
            return
        self._closing = True
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()
        QTimer.singleShot(220, self.close)


class ToastManager:
    """全局 toast 管理器;挂在主窗口上,跟随窗口 resize 重排。"""
    _host: QWidget | None = None
    _stack: list[_Toast] = []
    _filter = None

    @classmethod
    def attach(cls, host: QWidget):
        from PySide6.QtCore import QObject, QEvent
        cls._host = host
        if cls._filter is None:
            class _Filter(QObject):
                def eventFilter(self, obj, event):
                    if event.type() == QEvent.Resize:
                        ToastManager._reposition()
                    return False
            cls._filter = _Filter()
        host.installEventFilter(cls._filter)

    @classmethod
    def toast(cls, text: str, kind: str = "info", msec: int = 3600):
        if cls._host is None:
            return
        # 最多 5 条
        while len(cls._stack) >= 5:
            oldest = cls._stack.pop(0)
            oldest.deleteLater()
        t = _Toast(text, kind, cls._host)
        cls._stack.append(t)
        cls._reposition()
        t.show_in()
        QTimer.singleShot(msec, t._dismiss)
        return t

    @classmethod
    def success(cls, text: str):
        return cls.toast(text, "success")

    @classmethod
    def info(cls, text: str):
        return cls.toast(text, "info")

    @classmethod
    def warning(cls, text: str):
        return cls.toast(text, "warning")

    @classmethod
    def error(cls, text: str):
        return cls.toast(map_error(text), "error", 5000)

    @classmethod
    def _reposition(cls):
        if not cls._host:
            return
        cls._stack[:] = [t for t in cls._stack if t.parent() is cls._host]
        y = 16
        for t in cls._stack:
            t.adjustSize()
            t.raise_()
            t.move(cls._host.width() - t.width() - 20, y)
            t.show()
            y += t.height() + 8


def toast(text: str, kind: str = "info", msec: int = 3600):
    return ToastManager.toast(text, kind, msec)


def ok(text: str):
    return ToastManager.success(text)


def info(text: str):
    return ToastManager.info(text)


def warn(text: str):
    return ToastManager.warning(text)


def err(text):
    return ToastManager.error(text)
