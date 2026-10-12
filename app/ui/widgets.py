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


_DPR_CACHE: list[float] = []


def _ui_dpr() -> float:
    """UI 缩放倍数(取所有屏幕最大值并缓存,封顶 2.5)。

    HiDPI(Windows 125%/150% 缩放)下按逻辑像素出图会被系统拉伸发糊,
    缩略图一律按 dpr 倍的物理像素加载再 setDevicePixelRatio。
    """
    if not _DPR_CACHE:
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            dprs = [s.devicePixelRatio() for s in app.screens()] if app else []
            _DPR_CACHE.append(min(2.5, max(dprs, default=2.0)))
        except Exception:  # noqa: BLE001  —— 无实例/无屏幕时按 2 倍出图
            _DPR_CACHE.append(2.0)
    return _DPR_CACHE[0]


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
    dpr = _ui_dpr()
    if pm.isNull():
        pm = QPixmap(int(w * dpr), int((h or w) * dpr))
        pm.fill(QColor("#e8eaf0"))
    if h:
        pm = pm.scaled(int(w * dpr), int(h * dpr), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    else:
        pm = pm.scaledToWidth(int(w * dpr), Qt.SmoothTransformation)
    pm.setDevicePixelRatio(dpr)
    return pm


def pixmap_from_media(url_or_path: str | None, w: int, h: int = 0) -> QPixmap:
    """从 /static/... 或本地路径加载图片;失败给纯色占位。

    按 dpr 倍物理像素缩放再挂 devicePixelRatio,HiDPI 屏不再被系统拉伸发糊。
    """
    pm = QPixmap()
    if url_or_path:
        p = config.media_url_to_path(url_or_path) if str(url_or_path).startswith(("/static/", "static/")) else Path(url_or_path)
        if p.exists():
            pm = QPixmap(str(p))
    dpr = _ui_dpr()
    if pm.isNull():
        pm = QPixmap(int(w * dpr), int((h or w) * dpr))
        pm.fill(QColor("#e8eaf0"))
    if h:
        pm = pm.scaled(int(w * dpr), int(h * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
    else:
        pm = pm.scaledToWidth(int(w * dpr), Qt.SmoothTransformation)
    pm.setDevicePixelRatio(dpr)
    return pm


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
