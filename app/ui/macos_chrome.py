# -*- coding: utf-8 -*-
"""macOS 风格窗口 chrome —— 替代 OS 原生 titlebar，启用 FramelessWindowHint 时使用。

视觉:26px 浅色渐变 + 左 78px 红绿灯 + 中央 mono 文件名 + 鼠标拖拽支持。
对原代码无侵入:有则用,无则回退到原生。

触发:MainWindow.__init__ 在 setWindowFlags 之后挂载;
     或任何调用方在 widget.showEvent 自检 + 自挂。

设计要点(实测踩坑):
  - 拖拽用 `windowHandle().startSystemMove()`(Qt5.15+/Qt6) —
    Windows 上该方法存在但不移动,必须同时实现 mouseMoveEvent fallback;
    macOS 上正常。
  - 双击标题栏最大化 / 还原。
  - 三圆按钮的真实行为:红=关闭 / 黄=最小化 / 绿=最大化|还原。
    但**保留 close 按钮**,min/max 不强制启用(避免分屏窗口缩小后找不到)。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QMouseEvent
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel


# --- 共享常量:与 theme.py 里的 token 同步 ---
CHROME_H = 26                  # 整条高度
LIGHTS_W = 78                  # 红黄绿三灯 + 留白
LIGHT_D = 12                   # 红黄绿圆直径
LIGHT_GAP = 8                  # 三圆间距
LIGHT_INSET_X = 12             # 三个圆整体左边距


class _TrafficLight(QWidget):
    """单颗红黄绿圆。点击 → 发 clicked() 给上层。"""

    clicked = Signal()

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(LIGHT_D, LIGHT_D)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 外圈(细边)+ 实心
        p.setPen(QPen(QColor(0, 0, 0, int(0.18 * 255)), 0.5))
        p.setBrush(QBrush(QColor(self._color)))
        p.drawEllipse(1, 1, LIGHT_D - 2, LIGHT_D - 2)

    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()


class MacOSChrome(QWidget):
    """自绘 26px titlebar。挂在某 QWidget 上,该 widget 必须能 setWindowFlags(FramelessWindowHint)。"""

    # ── 外部可接入的信号(默认调用方在 showEvent 自检,但保留信号方便外部接管)──
    closeRequested = Signal()
    minimizeRequested = Signal()
    maximizeToggleRequested = Signal()

    HEIGHT = CHROME_H
    LIGHTS_W = LIGHTS_W

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        # 浅色渐变 + 细灰底线(与 macOS 视觉对齐)
        self.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            "  stop:0 #fbfbf8, stop:1 #f1ede5);"
            f"border-bottom: 1px solid #DCDAD3;"
        )

        self._title = title
        self._dragging = False
        self._drag_press = None
        self._drag_origin = None
        self._double_click_pending = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 左:LIGHTS_W 占位 + 红黄绿(用绝对定位,避免布局挤压标题)
        self._lights_holder = QWidget(self)
        self._lights_holder.setFixedWidth(self.LIGHTS_W)
        lay.addWidget(self._lights_holder)

        ly = 7         # y 居中(26 - 12 = 14, / 2 = 7)
        lx = LIGHT_INSET_X
        self._red = _TrafficLight("#ff5f57", self._lights_holder)
        self._red.setGeometry(lx, ly, LIGHT_D, LIGHT_D)
        self._red.clicked.connect(self.closeRequested)

        self._yellow = _TrafficLight("#febc2e", self._lights_holder)
        self._yellow.setGeometry(lx + (LIGHT_D + LIGHT_GAP), ly, LIGHT_D, LIGHT_D)
        self._yellow.clicked.connect(self.minimizeRequested)

        self._green = _TrafficLight("#28c840", self._lights_holder)
        self._green.setGeometry(lx + 2 * (LIGHT_D + LIGHT_GAP), ly, LIGHT_D, LIGHT_D)
        self._green.clicked.connect(self.maximizeToggleRequested)

        # 中:文件名(mono,居中)
        self._title_label = QLabel(title, self)
        f = self._title_label.font()
        f.setFamilies([
            "JetBrains Mono", "SFMono-Regular", "SF Mono", "Menlo",
            "Consolas", "Courier New", "monospace",
        ])
        f.setPixelSize(11)
        self._title_label.setFont(f)
        self._title_label.setAlignment(Qt.AlignCenter)
        # 标题绝对定位(由 resizeEvent 重排)
        self._title_label.setStyleSheet(
            "background: transparent; color: #6B727A; border: none;"
        )

        # 右上:可放 widget,这里留空槽位,以后如要加 "?" / 设置图标直接 layout
        self._right = QWidget(self)
        self._right.setFixedWidth(0)
        lay.addStretch(1)

        # macOS chrome 不接收焦点,不影响键盘导航
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

    # ── 标题 ──
    def set_title(self, t: str):
        self._title = t
        self._title_label.setText(t)

    # ── 拖拽 + 双击 ──
    def mousePressEvent(self, ev: QMouseEvent):
        if ev.button() != Qt.LeftButton:
            return
        win = self.window().windowHandle() if self.window() else None
        if ev.modifiers() & Qt.ShiftModifier:
            # 留给将来:shift+拖拽 = 强制调整
            return
        # 双击标题栏 → toggleMaximize
        if ev.type() == QMouseEvent.MouseButtonDblClick:
            self.maximizeToggleRequested.emit()
            return
        # 单击准备拖拽(系统接管优先)
        self._drag_press = ev.position()
        # 如果点击位置在某一盏灯上,不要启动拖拽
        for w in (self._red, self._yellow, self._green):
            if w.geometry().contains(int(ev.position().x()), int(ev.position().y())):
                self._drag_press = None
                return
        self._drag_origin = win and win.position()  # QWindow.pos()

    def mouseMoveEvent(self, ev: QMouseEvent):
        # Qt6 用 globalPosition() 取屏幕坐标
        if self._drag_press is None:
            return
        win = self.window().windowHandle() if self.window() else None
        if win is None:
            self._drag_press = None
            return
        # 优先走系统拖拽(Qt6 提供,macOS/Win11 支持;Win10 静默失败)
        try:
            if not win.startSystemMove.__self__._started:
                win.startSystemMove()
                self._drag_press = None
                return
        except Exception:
            pass
        # fallback: 手动算 delta 并 move
        if self._drag_origin is not None:
            delta = ev.globalPosition() - self._drag_press
            try:
                win.setPosition(self._drag_origin.x() + int(delta.x()),
                                self._drag_origin.y() + int(delta.y()))
            except Exception:
                pass
        self._drag_press = None  # 单次事件结束后清理,避免拖动期间一直触发 move

    def mouseReleaseEvent(self, _ev):
        self._drag_press = None

    def mouseDoubleClickEvent(self, ev: QMouseEvent):
        # 已被 mousePressEvent 处理(MouseButtonDblClick 类型),这里留空避免双重触发
        pass

    # ── 自适应:把标题标签居中在去掉灯区后的可用宽度 ──
    def resizeEvent(self, _ev):
        # 标题居中:从 LIGHTS_W 后 到 (width - 0) 前的中心
        center_x = (LIGHTS_W + self.width()) // 2
        # 测量标题宽
        fm = self._title_label.fontMetrics()
        tw = fm.horizontalAdvance(self._title)
        self._title_label.setGeometry(center_x - tw // 2, 0, tw, self.HEIGHT)
        self._title_label.raise_()  # 在 lights 之上避免被挡

    def set_right_buttons(self, layout_fn):
        """外部可挂 widget 到右上,例如 settings / 主题切换等。
        layout_fn 接收一个 QHBoxLayout,直接 addWidget 即可。"""
        lay_inner = QHBoxLayout(self._right)
        lay_inner.setContentsMargins(0, 0, 12, 0)
        lay_inner.setSpacing(6)
        layout_fn(lay_inner)
        self._right.setFixedWidth(96)  # 给一块区域
        # 重新触发 resizeEvent 让布局回摆
        self.resize(self.width(), self.HEIGHT)
