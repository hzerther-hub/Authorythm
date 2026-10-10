# -*- coding: utf-8 -*-
"""蒙版擦除对话框 —— 画笔涂抹要擦掉的区域,导出 alpha 蒙版交给 erase.erase_region。

契约与参考项目一致:「透明底 + 不透明白色笔迹」,形状在 alpha 通道(RGB 不参与)。
支持笔刷粗细调节 / 全清 / 橡皮(擦回透明)。
"""
from __future__ import annotations

import io

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import (QImage, QPainter, QPen, QPixmap)
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from ..core.i18n import tr


class MaskCanvas(QWidget):
    """涂鸦画布:白笔在透明底上画,输出 mask PNG(形状=alpha)。"""

    def __init__(self, image_bytes: bytes, parent=None):
        super().__init__(parent)
        self._base = QImage()
        self._base.loadFromData(image_bytes)
        self.setFixedSize(self._base.size())
        # 蒙版层与显示层分离:显示 = 底图 + 半透明红罩
        self._mask = QImage(self._base.size(), QImage.Format_ARGB32)
        self._mask.fill(Qt.transparent)
        self._drawing = False
        self._last = QPoint()
        self._pen_w = 28
        self._erase_mode = False
        self._redo_snapshot: QImage | None = None

    # ── 交互 ──
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drawing = True
            self._last = e.position().toPoint()
            self._redo_snapshot = None
            self._stroke(self._last, self._last)

    def mouseMoveEvent(self, e):
        if self._drawing:
            self._stroke(self._last, e.position().toPoint())
            self._last = e.position().toPoint()

    def mouseReleaseEvent(self, _e):
        self._drawing = False

    def _stroke(self, a: QPoint, b: QPoint) -> None:
        p = QPainter(self._mask)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(Qt.white if not self._erase_mode else Qt.transparent,
                   self._pen_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver if not self._erase_mode
                             else QPainter.CompositionMode_Clear)
        p.drawLine(a, b)
        p.end()
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.drawImage(0, 0, self._base)
        # 半透明红罩显示已涂区域(蒙版 alpha → 红色覆盖层)
        p.setOpacity(0.45)
        red = QImage(self._mask.size(), QImage.Format_ARGB32)
        red.fill(Qt.red)
        red.setAlphaChannel(self._mask.convertToFormat(QImage.Format_Alpha8))
        p.drawImage(0, 0, red)
        p.setOpacity(1.0)
        p.end()

    # ── 工具 ──
    def set_pen_width(self, w: int) -> None:
        self._pen_w = max(4, int(w))

    def set_erase_mode(self, on: bool) -> None:
        self._erase_mode = on

    def clear(self) -> None:
        self._redo_snapshot = self._mask.copy()
        self._mask.fill(Qt.transparent)
        self.update()

    def undo(self) -> None:
        if self._redo_snapshot is not None:
            self._mask, self._redo_snapshot = self._redo_snapshot, self._mask.copy()
            self.update()

    def has_strokes(self) -> bool:
        """是否画过(全透明=没画)。"""
        return any(self._mask.constBits()[i] != 0
                   for i in range(0, self._mask.sizeInBytes(), 997))   # 抽样

    def export_mask_png(self, target_w: int, target_h: int) -> bytes:
        """导出「白色笔迹 + alpha 形状」的 PNG(与参考项目同契约),缩放到目标尺寸。"""
        white = QImage(self._mask.size(), QImage.Format_ARGB32)
        white.fill(Qt.white)
        white.setAlphaChannel(self._mask.convertToFormat(QImage.Format_Alpha8))
        img = white.scaled(target_w, target_h)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()


class MaskEraseDialog(QDialog):
    """画笔擦除对话框:底图 + 涂抹 + 笔刷粗细/橡皮/清空/撤销。accept 后取 export_mask_png。"""

    def __init__(self, parent, image_bytes: bytes, title: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title or tr("擦除区域"))
        self.resize(860, 720)
        root = QVBoxLayout(self)
        self.canvas = MaskCanvas(image_bytes, self)
        root.addWidget(self.canvas, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("笔刷")))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(4, 120)
        self.size_slider.setValue(28)
        self.size_slider.setMaximumWidth(180)
        self.size_slider.valueChanged.connect(lambda v: self.canvas.set_pen_width(v))
        row.addWidget(self.size_slider)
        self.erase_btn = QPushButton(tr("橡皮"))
        self.erase_btn.setCheckable(True)
        self.erase_btn.toggled.connect(self.canvas.set_erase_mode)
        row.addWidget(self.erase_btn)
        undo_btn = QPushButton(tr("撤销"))
        undo_btn.clicked.connect(self.canvas.undo)
        row.addWidget(undo_btn)
        clear_btn = QPushButton(tr("清空"))
        clear_btn.clicked.connect(self.canvas.clear)
        row.addWidget(clear_btn)
        row.addStretch(1)
        hint = QLabel(tr("涂抹要擦掉的区域,确认后程序化填充(线条/地面等结构会自然延续)"))
        hint.setObjectName("muted")
        row.addWidget(hint)
        root.addLayout(row)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr("u_cancel"))
        cancel.clicked.connect(self.reject)
        ok = QPushButton(tr("开始擦除"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

    def export_mask(self) -> bytes:
        return self.canvas.export_mask_png(self.canvas._base.width(), self.canvas._base.height())


def open_erase_dialog(parent, image_url: str, ertype: str, asset_id: int,
                      on_done=None, kind: str = "main", title: str = "") -> None:
    """通用擦除入口:取图 → 涂抹 → 擦除执行 → 回调刷新。

    ertype ∈ panel/character/scene/prop;kind ∈ main/comic(资产双图版本)。
    """
    from ..core import config
    from ..pipeline import erase as ER
    from .toast import err, ok

    try:
        p = config.media_url_to_path(image_url)
        img_bytes = p.read_bytes()
    except Exception as e:  # noqa: BLE001
        err(str(e)[:160])
        return
    dlg = MaskEraseDialog(parent, img_bytes, title)
    if dlg.exec() != MaskEraseDialog.Accepted:
        return
    try:
        new_path = ER.erase_region(ertype, asset_id, dlg.export_mask(), kind)
        ok(tr("擦除完成"))
        if on_done:
            on_done()
        else:
            from .asset_dialogs import ImageViewerDialog
            ImageViewerDialog(parent, config.path_to_media_url(new_path), title or tr("擦除完成")).exec()
    except Exception as e:  # noqa: BLE001
        err(str(e)[:200])
