# -*- coding: utf-8 -*-
"""封面加字:文字内容 / 字号 / 颜色 / 位置 / 字体,实时预览,应用后写回封面。

渲染骨架借自 image_edit_dialog 的文字水印(RGBA 图层 + alpha_composite),但把
那里写死的白色、字号(高//22)、右下角位置都改成可调 —— 水印是"贴边角的小字",
封面标题要的是能排版的主字,两者诉求不同。

额外加了描边:纯色大字压在复杂封面上容易糊,一圈暗色描边保证任何底图上都可读。
"""
from __future__ import annotations

import io
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog, QHBoxLayout,
                               QLabel, QPlainTextEdit, QPushButton, QSlider,
                               QVBoxLayout)

from ..core import config, db
from ..core.i18n import tr
from . import widgets as W
from .toast import err, ok


class CoverTextDialog(QDialog):
    """封面加字编辑器。"""

    def __init__(self, parent, url: str | None, drama_id: int = 0, on_saved=None):
        super().__init__(parent)
        self.setWindowTitle(tr("cover_add_text"))
        self.resize(760, 640)
        self.url = url
        self.drama_id = drama_id
        self._on_saved = on_saved
        self._color = QColor("#FFFFFF")
        self._font_file = ""
        self._size_pct = 8

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(280)
        root.addWidget(self.preview, 1)

        row0 = QHBoxLayout()
        row0.addWidget(QLabel(tr("cover_text_content")))
        self.text = QPlainTextEdit()
        self.text.setFixedHeight(58)
        self.text.setPlaceholderText(tr("cover_text_hint"))
        self.text.textChanged.connect(self._render)
        row0.addWidget(self.text, 1)
        root.addLayout(row0)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel(tr("cover_text_size")))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(3, 20)
        self.size_slider.setValue(self._size_pct)
        self.size_slider.valueChanged.connect(self._on_size)
        self.size_lab = QLabel("")
        self.size_lab.setObjectName("muted")
        self.size_lab.setFixedWidth(64)
        row1.addWidget(self.size_slider, 1)
        row1.addWidget(self.size_lab)
        row1.addSpacing(12)
        row1.addWidget(QLabel(tr("cover_text_color")))
        self.color_btn = QPushButton()
        self.color_btn.setFixedSize(46, 26)
        self.color_btn.setToolTip(tr("cover_text_color"))
        self.color_btn.clicked.connect(self._pick_color)
        row1.addWidget(self.color_btn)
        root.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel(tr("cover_text_font")))
        self.font_combo = QComboBox()
        self.font_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        from ..pipeline import intro as _INTRO
        for it in _INTRO.list_fonts():
            self.font_combo.addItem(it["name"], it["file"])
        self.font_combo.currentIndexChanged.connect(self._on_font)
        row2.addWidget(self.font_combo)
        row2.addSpacing(12)
        row2.addWidget(QLabel(tr("cover_text_pos")))
        self.pos_combo = QComboBox()
        for key in ("top", "center", "bottom"):
            self.pos_combo.addItem(tr("cover_pos_" + key), key)
        self.pos_combo.setCurrentIndex(2)
        self.pos_combo.currentIndexChanged.connect(self._render)
        row2.addWidget(self.pos_combo)
        row2.addStretch(1)
        root.addLayout(row2)

        act = QHBoxLayout()
        act.addStretch(1)
        cancel = QPushButton(tr("close"))
        cancel.clicked.connect(self.reject)
        self.apply_btn = W.primary_btn(tr("cover_text_apply"))
        self.apply_btn.clicked.connect(self._apply)
        act.addWidget(cancel)
        act.addWidget(self.apply_btn)
        root.addLayout(act)

        self._set_color_btn()
        self._on_size(self._size_pct)

    # ── 控件回调 ──
    def _on_size(self, v: int):
        self._size_pct = v
        self.size_lab.setText(f"{v}%")
        self._render()

    def _on_font(self):
        self._font_file = self.font_combo.currentData() or ""
        self._render()

    def _pick_color(self):
        c = QColorDialog.getColor(self._color, self, tr("cover_text_color"))
        if c.isValid():
            self._color = c
            self._set_color_btn()
            self._render()

    def _set_color_btn(self):
        self.color_btn.setStyleSheet(
            f"background:{self._color.name()}; border:1px solid rgba(128,128,128,120);"
            "border-radius:5px;")

    # ── 渲染 ──
    def _load_font(self, px: int):
        from PIL import ImageFont
        fonts = config.ROOT_DIR / "app" / "assets" / "fonts"
        cands = ([fonts / self._font_file] if self._font_file else []) + [fonts / "msyh.ttc"]
        for fp in cands:
            if fp and fp.exists():
                try:
                    return ImageFont.truetype(str(fp), max(8, int(px)))
                except Exception:  # noqa: BLE001
                    continue
        return ImageFont.load_default()

    def _compose(self, im):
        from PIL import Image, ImageDraw
        text = self.text.toPlainText().strip()
        if not text:
            return im
        base = im.convert("RGBA")
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        px = max(10, int(base.size[1] * self._size_pct / 100.0))
        font = self._load_font(px)
        r, g, b, _a = self._color.getRgb()
        stroke = max(1, int(px / 18))
        lines = text.splitlines() or [text]
        line_h = int(px * 1.35)
        total = line_h * len(lines)
        y0 = {"top": int(base.size[1] * 0.08),
              "center": (base.size[1] - total) // 2,
              "bottom": int(base.size[1] * 0.86) - total}[self.pos_combo.currentData()]
        for i, ln in enumerate(lines):
            if not ln.strip():
                continue
            bbox = draw.textbbox((0, 0), ln, font=font, stroke_width=stroke)
            tw = bbox[2] - bbox[0]
            x = (base.size[0] - tw) // 2
            draw.text((x, y0 + i * line_h), ln, font=font, fill=(r, g, b, 255),
                      stroke_width=stroke, stroke_fill=(0, 0, 0, 200))
        out = base.copy()
        out.alpha_composite(layer)
        return out.convert("RGB")

    def _base_image(self):
        if not self.url:
            return None
        p = (config.media_url_to_path(self.url)
             if str(self.url).startswith(("/static/", "static/")) else Path(str(self.url)))
        if not p.exists():
            return None
        try:
            from PIL import Image
            with Image.open(p) as im:
                im.load()
                return im.copy()
        except Exception:  # noqa: BLE001
            return None

    def _render(self):
        src = self._base_image()
        if src is None:
            self.preview.setText(tr("cover_text_no_base"))
            return
        try:
            out = self._compose(src)
        except Exception:  # noqa: BLE001
            self.preview.setText(tr("cover_text_no_base"))
            return
        buf = io.BytesIO()
        out.save(buf, "PNG")
        pm = QPixmap()
        pm.loadFromData(buf.getvalue())
        self.preview.setPixmap(pm.scaled(self.preview.width() - 20, self.preview.height() - 20,
                                        Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _apply(self):
        if not self.text.toPlainText().strip():
            err(tr("cover_text_required"))
            return
        src = self._base_image()
        if src is None:
            err(tr("cover_text_no_base"))
            return
        try:
            out = self._compose(src)
        except Exception as exc:  # noqa: BLE001
            err(str(exc)[:180])
            return
        d = config.STATIC_DIR / "images"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"cover_txt_{int(time.time())}.png"
        out.save(dest)
        url = config.path_to_media_url(dest)
        if self.drama_id:
            db.ex("UPDATE dramas SET thumbnail=?, updated_at=? WHERE id=?",
                  (url, db.now(), self.drama_id))
        self.url = url
        self._render()
        ok(tr("cover_text_done"))
        if self._on_saved:
            self._on_saved(url)