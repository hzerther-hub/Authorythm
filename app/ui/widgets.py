# -*- coding: utf-8 -*-
"""通用 UI 组件:卡片/标签/头像/图片按钮等。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..core import config
from ..core.i18n import tr


def make_card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


def h1(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("h1")
    return lab


def h2(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("h2")
    return lab


def muted(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(True)
    return lab


def tag(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("tag")
    lab.setAlignment(Qt.AlignCenter)
    return lab


def primary_btn(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("primary")
    b.setCursor(Qt.PointingHandCursor)
    return b


def danger_btn(text: str) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("danger")
    b.setCursor(Qt.PointingHandCursor)
    return b


AVATAR_COLORS = ["#f97316", "#e0794b", "#3aa675", "#6366f1", "#c94b62", "#4b9cc9"]


def avatar(initial: str, size: int = 44) -> QLabel:
    lab = QLabel(initial[:1] if initial else "?")
    lab.setFixedSize(size, size)
    lab.setAlignment(Qt.AlignCenter)
    color = AVATAR_COLORS[sum(ord(c) for c in initial) % len(AVATAR_COLORS)] if initial else AVATAR_COLORS[0]
    lab.setStyleSheet(
        f"background:{color}; color:white; border-radius:{size//2}px; font-weight:700; font-size:{size//2}px;")
    return lab


def pixmap_cover_media(url_or_path: str | None, w: int, h: int = 0) -> QPixmap:
    """从媒体地址加载图片并**铺满裁切**成 w×h(对齐参考项目 object-fit:cover)。

    与 pixmap_from_media(KeepAspectRatio 留白)不同:这里按 KeepAspectRatioByExpanding
    放大到完全覆盖 w×h 再居中裁掉溢出部分 —— 封面不出现空白边。
    """
    pm = QPixmap()
    if url_or_path:
        p = config.media_url_to_path(url_or_path) if str(url_or_path).startswith(("/static/", "static/")) else Path(url_or_path)
        if p.exists():
            pm = QPixmap(str(p))
    if pm.isNull():
        pm = QPixmap(w, h or w)
        pm.fill(QColor("#e8eaf0"))
    if h:
        return pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return pm.scaledToWidth(w, Qt.SmoothTransformation)


def pixmap_from_media(url_or_path: str | None, w: int, h: int = 0) -> QPixmap:
    """从 /static/... 或本地路径加载图片;失败给纯色占位。"""
    pm = QPixmap()
    if url_or_path:
        p = config.media_url_to_path(url_or_path) if str(url_or_path).startswith(("/static/", "static/")) else Path(url_or_path)
        if p.exists():
            pm = QPixmap(str(p))
    if pm.isNull():
        pm = QPixmap(w, h or w)
        pm.fill(QColor("#e8eaf0"))
    if h:
        return pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pm.scaledToWidth(w, Qt.SmoothTransformation)


class StatBar(QWidget):
    """统计条:若干「数值 标签」段。"""
    def __init__(self, items: list[tuple[str, str]]):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(18)
        self._values: list[QLabel] = []
        for value, label in items:
            box = QVBoxLayout()
            v = QLabel(value)
            f = QFont()
            f.setBold(True)
            f.setPointSize(15)
            v.setFont(f)
            box.addWidget(v)
            box.addWidget(muted(label))
            wrap = QWidget()
            wrap.setLayout(box)
            lay.addWidget(wrap)
            self._values.append(v)
        lay.addStretch(1)

    def setItemValue(self, index: int, value: str) -> None:
        if 0 <= index < len(self._values):
            self._values[index].setText(value)


class CardButton(QPushButton):
    """可点击卡片(项目卡/剧集卡)。"""
    clicked_data = Signal(int)

    def __init__(self, widget: QWidget, data_id: int):
        super().__init__()
        self.data_id = data_id
        self.setLayout(_wrap(widget))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("text-align:left; padding:0;")
        self.clicked.connect(lambda: self.clicked_data.emit(self.data_id))


def _wrap(inner: QWidget) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setContentsMargins(14, 14, 14, 14)
    lay.addWidget(inner)
    return lay


def kv_row(key: str, value: str) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    k = muted(key)
    k.setFixedWidth(90)
    v = QLabel(value or "-")
    v.setWordWrap(True)
    lay.addWidget(k)
    lay.addWidget(v, 1)
    return w
