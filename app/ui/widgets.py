# -*- coding: utf-8 -*-
"""通用 UI 组件:卡片/标签/头像/图片按钮等。"""
from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
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


# Director's Slate:共享 helper —— 按钮在 slate 风的 dialog / panel 里的统一外观
# 用法:`btn = slate_button("REFRESH"); btn.clicked.connect(...)`
# 默认排他(主操作),可选 primary=True 走拍板黑底白字
def slate_button(text: str, *, primary: bool = False) -> "QPushButton":
    """返回带 slate 风 QSS 的 QPushButton;不破坏其他按钮。"""
    from PySide6.QtWidgets import QPushButton
    btn = QPushButton(text)
    if primary:
        btn.setObjectName("slatePrimary")
        btn.setStyleSheet(
            "QPushButton#slatePrimary{background:#0E0F12; border:1px solid #0E0F12;"
            "border-radius:3px; color:#F5F4EF; padding:0 16px; min-height:28px;"
            "font-family:ui-monospace,Menlo,Consolas,monospace; font-size:10px;"
            "font-weight:700; letter-spacing:1.5px;}"
            "QPushButton#slatePrimary:hover{background:#1F2128; border-color:#1F2128;}"
            "QPushButton#slatePrimary:disabled{background:#DCDAD3; color:#A8A6A1;}"
        )
    else:
        btn.setObjectName("slateGhost")
        btn.setStyleSheet(
            "QPushButton#slateGhost{background:transparent; border:1px solid #DCDAD3;"
            "border-radius:3px; color:#6B727A; padding:0 12px; min-height:26px;"
            "font-family:ui-monospace,Menlo,Consolas,monospace; font-size:10px;"
            "font-weight:600; letter-spacing:0.5px;}"
            "QPushButton#slateGhost:hover{border-color:#0E0F12; color:#0E0F12;}"
        )
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def slate_status_label(text: str = "") -> "QLabel":
    """Status bar mono 风的 QLabel:暗色 + letter-spacing,适配场记板。"""
    lab = QLabel(text)
    lab.setObjectName("slateStatus")
    lab.setStyleSheet(
        "QLabel#slateStatus{color:#6B727A;"
        "font-family:ui-monospace,Menlo,Consolas,monospace; font-size:10px;"
        "letter-spacing:0.5px; padding:0 4px;}"
    )
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


def icon_btn(icon, tooltip: str = "", size: int = 20,
             fallback: str = "") -> QPushButton:
    """纯图标小按钮(文字挪到 tooltip),用 Qt 原生图标而不是 Unicode 符号。

    为什么不用 '↓' / '🗑' 这类字符当图标(同 main_window 任务键、project_page 删集卡):
      1. 部分 Windows 字体渲染成方块 / 糊块,用户反馈「没有图标」;
      2. 更致命的是**小尺寸 + 全局 padding** —— QSS 里 QPushButton 是 padding:6px 14px,
         塞进 16×16 的固定尺寸按钮后垂直只剩 4px,字形直接无处可画,整颗按钮是空白
         (实测改前渲染只有 1 种颜色=纯背景,改后原生图标 34/80 种颜色)。

    fallback 仅在平台缺该标准图标时兜底;优先用图标。
    """
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QStyle
    b = QPushButton(fallback if isinstance(icon, str) else "")
    b.setObjectName("iconBtn")
    b.setCursor(Qt.PointingHandCursor)
    if not isinstance(icon, str) and icon is not None:
        ico = b.style().standardIcon(icon)
        if not ico.isNull():
            b.setIcon(ico)
    if tooltip:
        b.setToolTip(tooltip)
    px = max(10, size - 6)
    b.setIconSize(QSize(px, px))
    b.setFixedSize(size, size)
    return b


def svg_icon(name: str, size: int = 16, color: str = "") -> QIcon:
    """iconfont 扁平线性图标(见 app/ui/icons.py 的说明与取舍)。

    color 留空则跟随控件调色板,这样切主题时图标跟着变,不会在深色主题下
    变成看不见的黑图。
    """
    from . import icons
    if not color:
        color = icons.theme_color()
    return icons.icon(name, size=size, color=color)


def svg_icon_btn(name: str, tooltip: str = "", size: int = 24,
                 color: str = "") -> QPushButton:
    """iconfont 图标按钮 —— icon_btn 的 iconfont 版(纯图标 + tooltip)。"""
    b = QPushButton("")
    b.setObjectName("iconBtn")
    b.setCursor(Qt.PointingHandCursor)
    b.setIcon(svg_icon(name, size=size - 6, color=color))
    b.setToolTip(tooltip)
    b.setFixedSize(size, size)
    return b



# 前导 emoji / 变体选择符 / 空白:渲染前剥掉。
# 为什么不直接改 i18n 词典:这些 emoji 是**印在 key 里的**(如 tr("✨ AI 起草简介")),
# ui_strings.py 里 15 种语言各有一份,动它等于 15 处翻译同时改,风险远大于收益。
# 文本在渲染时剥前缀、图标另挂,词典一个字都不用动。
_LEAD_EMOJI = re.compile(r"^[🌀-🫿☀-➿⬀-⯿️‍\s]+")


def strip_emoji(text: str) -> str:
    """去掉文本开头的 emoji 与空白 —— 让「💾 保存」变成「保存」。"""
    return _LEAD_EMOJI.sub("", text or "").strip()


def set_icon(btn, name: str, text: str | None = None, size: int = 16) -> None:
    """给已有按钮挂 iconfont 图标,并顺手把文本里的前导 emoji 剥掉。

    用于两类地方:
      1. 文本来自 tr()、emoji 印在词典 key 里的按钮(primary_btn("💾 " + tr("save")));
      2. 运行期改过 setText 的按钮(WaitingButton.busy()/idle() 会重设文本)。
    图标缺失时静默跳过、只留文字 —— 换错图标名不该把按钮变成空白。
    """
    if btn is None:
        return
    ic = svg_icon(name, size=size)
    if not ic.isNull():
        from PySide6.QtCore import QSize as _QSize
        btn.setIcon(ic)
        btn.setIconSize(_QSize(size, size))
    btn.setText(strip_emoji(text if text is not None else btn.text()))


def add_item(combo, text: str, data=None, user_data=None) -> int:
    """版本无关的 QComboBox.addItem 包装 —— 永远返回新行的索引。

    PySide6 不同小版本对 QComboBox.addItem 的返回值承诺不一致:
      - 6.5+ 文档保证返回 int(刚加进去的索引)
      - 早期版本(实测 6.7.x)实际返回 None
    直接用 `idx = combo.addItem(...)` 然后 setItemData(idx, ...) 在后者上
    会拿到 None → TypeError,被 try/except 吞掉就表现为「点按钮无反应」。
    走这个 helper 一律用 count()-1 算索引,跨版本都稳。
    """
    combo.addItem(text, data)
    idx = combo.count() - 1
    if user_data is not None:
        from PySide6.QtCore import Qt as _Qt
        combo.setItemData(idx, user_data, _Qt.UserRole)
    return idx


def icon_label(name: str, size: int = 20, color: str = "") -> QLabel:
    """图标占位标签 —— 替代 QLabel("🎬") / QLabel("🌐") 这类纯 emoji 占位。"""
    lab = QLabel()
    lab.setAlignment(Qt.AlignCenter)
    lab.setFixedSize(size + 6, size + 6)
    ic = svg_icon(name, size=size, color=color)
    if not ic.isNull():
        lab.setPixmap(ic.pixmap(size, size))
    return lab


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
