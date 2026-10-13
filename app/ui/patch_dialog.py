# -*- coding: utf-8 -*-
"""局部修补:涂抹要改的区域,只填这一块,其余像素原样复制。

为什么不用 AI 改图做这件事:参考式图生图每次都重新生成**整张**图,实测
「去掉图片上的文字」会凭空加出无关人物、连画幅比例都从竖变横 —— 提示词写了
「保持不变」也没用,因为模型无从遵守。这里换一条路:用户涂抹要改的区域,交给
inpaint.py 的补丁式结构填充(从洞边缘逐层洋葱填充,线条/墙面/地面能自然延续),
蒙版以外的像素与原图逐字节一致 —— 所以**比例必然相同、绝不加人物、还不花钱**。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPushButton, QWidget,
                               QSlider, QVBoxLayout)

from ..core import config
from ..core.i18n import tr
from ..pipeline.inpaint import inpaint_masked
from . import widgets as W
from .mask_erase_dialog import MaskCanvas
from .toast import err, ok


class PatchDialog(QDialog):
    """单图局部修补:左涂抹,右实时预览修补结果。"""

    def __init__(self, parent, src: str | Path, out_dir: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("patch_title"))
        self.resize(1080, 680)
        self.src = Path(src)
        self.out_dir = Path(out_dir) if out_dir else (config.STATIC_DIR / "processed")
        self._result: bytes | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        body = QHBoxLayout()
        body.setSpacing(10)
        left = QVBoxLayout()
        self.hint = W.muted(tr("patch_hint"))
        self.hint.setWordWrap(True)
        left.addWidget(self.hint)
        self.left_host = QWidget()
        lh = QVBoxLayout(self.left_host)
        lh.setContentsMargins(0, 0, 0, 0)
        self.canvas = MaskCanvas(self.src.read_bytes())
        lh.addWidget(self.canvas, 1)
        left.addWidget(self.left_host, 1)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        cap = QLabel(tr("patch_preview"))
        cap.setObjectName("inspectorLabel")
        cap.setAlignment(Qt.AlignCenter)
        right.addWidget(cap)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumWidth(380)
        right.addWidget(self.preview, 1)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        prow = QHBoxLayout()
        prow.setSpacing(6)
        prow.addWidget(QLabel(tr("patch_pen")))
        self.pen = QSlider(Qt.Horizontal)
        self.pen.setRange(4, 120)
        self.pen.setValue(28)
        self.pen.valueChanged.connect(self._on_pen)
        self.pen_lab = W.muted("")
        self.pen_lab.setFixedWidth(40)
        prow.addWidget(self.pen, 1)
        prow.addWidget(self.pen_lab)
        clear = QPushButton(tr("patch_clear"))
        clear.clicked.connect(self._clear_mask)
        prow.addWidget(clear)
        undo = QPushButton(tr("patch_undo"))
        undo.clicked.connect(self._undo)
        prow.addWidget(undo)
        root.addLayout(prow)

        act = QHBoxLayout()
        self.info = W.muted("")
        act.addWidget(self.info, 1)
        cancel = QPushButton(tr("close"))
        cancel.clicked.connect(self.reject)
        self.run_btn = W.primary_btn(tr("patch_apply"))
        self.run_btn.clicked.connect(self._apply)
        act.addWidget(cancel)
        act.addWidget(self.run_btn)
        root.addLayout(act)

        # 笔迹变化 → 刷新实时预览。之前预览只在构造时算过一次(空蒙版),
        # 用户涂多少右边都纹丝不动,「应用」用的也是那份空蒙版结果。
        self.canvas.on_strokes_changed = self._on_canvas_changed
        self._on_pen(self.pen.value())
        # 画布等比缩到左栏可用区域;蒙版仍按原图分辨率导出
        QTimer.singleShot(0, self._fit_canvas)
        self._update_preview()

    def _on_canvas_changed(self):
        """抬笔/清空/撤销后重算修补(蒙版按原图分辨率导出)。"""
        QTimer.singleShot(0, self._update_preview)

    def _fit_canvas(self):
        avail_w = max(120, self.left_host.width())
        avail_h = max(120, self.left_host.height())
        self.canvas.fit_to(avail_w, avail_h)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        QTimer.singleShot(0, self._fit_canvas)
        QTimer.singleShot(0, self._update_preview)

    # ── 交互 ──
    def _on_pen(self, v: int):
        self.canvas.set_pen_width(v)
        self.pen_lab.setText(f"{v}px")

    def _clear_mask(self):
        self.canvas.clear()
        self._update_preview()

    def _undo(self):
        self.canvas.undo()
        self._update_preview()

    def _update_preview(self):
        """蒙版一改就重算预览 —— 修补是纯本地计算,可以做到实时。"""
        base = self.canvas._base
        mask = self.canvas.export_mask_png(base.width(), base.height())
        try:
            out = inpaint_masked(self.src.read_bytes(), mask)
        except Exception as exc:  # noqa: BLE001
            self.preview.setText(tr("patch_preview_fail"))
            self.info.setText(str(exc)[:120])
            return
        self._result = out
        img = QImage()
        img.loadFromData(out)
        # 必须缩放后显示:直接 setPixmap 原尺寸(1920x1080)会把对话框反向撑到
        # 两千多像素高,左右两栏都看不全
        pm = QPixmap.fromImage(img)
        box = self.preview.size()
        if not box.isEmpty() and pm.width() > 0:
            pm = pm.scaled(box, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.preview.setPixmap(pm)
        self.info.setText(f"{img.width()}×{img.height()}")

    def _apply(self):
        if not self.canvas.has_strokes():
            err(tr("patch_no_mask"))
            return
        self._update_preview()          # 用最新蒙版重算,别拿旧预览落盘
        if not self._result:
            err(tr("patch_no_mask"))
            return
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            dest = self.out_dir / f"{self.src.stem}_patch.png"
            dest.write_bytes(self._result)
        except Exception as exc:  # noqa: BLE001
            err(str(exc)[:160])
            return
        ok(tr("patch_done"))
        self.done_url = config.path_to_media_url(dest)
        self.accept()