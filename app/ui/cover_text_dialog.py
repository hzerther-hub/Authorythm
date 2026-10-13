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
        # 竖排:逐字向下排(书名/古装标题风)
        from PySide6.QtWidgets import QCheckBox as _QChk
        self.vertical_chk = _QChk(tr("wm_vertical"))
        self.vertical_chk.setToolTip(tr("wm_vertical_tip"))
        self.vertical_chk.toggled.connect(self._render)
        row2.addWidget(self.vertical_chk)
        row2.addStretch(1)
        root.addLayout(row2)

        act = QHBoxLayout()
        act.addStretch(1)
        add_item = QPushButton(tr("add_watermark_item"))
        add_item.setToolTip(tr("add_text_item_tip"))
        add_item.clicked.connect(self._add_item)
        clear_item = QPushButton(tr("clear_watermarks"))
        clear_item.setToolTip(tr("clear_items_tip"))
        clear_item.clicked.connect(self._clear_items)
        act.addWidget(add_item)
        act.addWidget(clear_item)
        cancel = QPushButton(tr("close"))
        cancel.clicked.connect(self.reject)
        self.apply_btn = W.primary_btn(tr("cover_text_apply"))
        self.apply_btn.clicked.connect(self._apply)
        act.addWidget(cancel)
        act.addWidget(self.apply_btn)
        root.addLayout(act)
        # 已加入的文字条目:支持封面上的标题+副标题+书名号等多组文字共存
        self.items: list[dict] = []

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
    def _load_font(self, px: int, file: str = ""):
        """file 参数与 _draw_item 的 font_of 约定对齐;缺省用正在编辑的字体。"""
        if not file:
            file = self._font_file
        from PIL import ImageFont
        fonts = config.ROOT_DIR / "app" / "assets" / "fonts"
        cands = ([fonts / file] if file else []) + [fonts / "msyh.ttc"]
        for fp in cands:
            if fp and fp.exists():
                try:
                    return ImageFont.truetype(str(fp), max(8, int(px)))
                except Exception:  # noqa: BLE001
                    continue
        return ImageFont.load_default()

    def _snapshot(self) -> dict:
        """当前控件状态 → 一个文字条目。"""
        return {"text": self.text.toPlainText().strip(),
                "color": self._color,
                "font_file": self._font_file,
                "size_pct": self._size_pct,
                "pos": self.pos_combo.currentData(),
                "vertical": self.vertical_chk.isChecked()}

    def _draw_item(self, base_size, draw, it, font_of):
        """画一个文字条目;竖排 = 逐字向下排,横排 = 多行居中。"""
        px = max(10, int(base_size[1] * it["size_pct"] / 100.0))
        font = font_of(px, it["font_file"])
        r, g, b, _a = it["color"].getRgb()
        stroke = max(1, int(px / 18))
        lines = [ln for ln in it["text"].splitlines() if ln.strip()]
        if it.get("vertical"):
            text = "".join(lines)                      # 多行合一后竖排
            line_h = int(px * 1.18)
            y0 = {"top": int(base_size[1] * 0.08),
                  "center": (base_size[1] - line_h * len(text)) // 2,
                  "bottom": int(base_size[1] * 0.86) - line_h * len(text)}[it["pos"]]
            for i, ch in enumerate(text):
                draw.text((base_size[0] / 2, y0 + i * line_h + line_h / 2), ch,
                          font=font, anchor="mm", fill=(r, g, b, 255),
                          stroke_width=stroke, stroke_fill=(0, 0, 0, 200))
        else:
            line_h = int(px * 1.35)
            total = line_h * len(lines)
            y0 = {"top": int(base_size[1] * 0.08),
                  "center": (base_size[1] - total) // 2,
                  "bottom": int(base_size[1] * 0.86) - total}[it["pos"]]
            for i, ln in enumerate(lines):
                bbox = draw.textbbox((0, 0), ln, font=font, stroke_width=stroke)
                tw = bbox[2] - bbox[0]
                draw.text(((base_size[0] - tw) // 2, y0 + i * line_h), ln, font=font,
                          fill=(r, g, b, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 200))

    def _compose(self, im):
        from PIL import Image, ImageDraw
        live = self.text.toPlainText().strip()
        if not live and not self.items:
            return im
        base = im.convert("RGBA")
        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for it in self.items:
            self._draw_item(base.size, draw, it, self._load_font)
        # 正在编辑的这条实时叠加(提交后由 items 渲染,防画两遍)
        if live:
            self._draw_item(base.size, draw, self._snapshot(), self._load_font)
        out = base.copy()
        out.alpha_composite(layer)
        return out.convert("RGB")

    def _add_item(self):
        """把当前参数存为一个文字条目(改文字/颜色/位置后可再加下一组)。"""
        text = self.text.toPlainText().strip()
        if not text:
            err(tr("cover_text_required"))
            return
        self.items.append(self._snapshot())
        self.text.clear()
        ok(tr("watermark_added", len(self.items)))
        self._render()

    def _clear_items(self):
        self.items.clear()
        self._render()

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
        live = self.text.toPlainText().strip()
        if not live and not self.items:
            err(tr("cover_text_required"))
            return
        src = self._base_image()
        if src is None:
            err(tr("cover_text_no_base"))
            return
        if live:
            self.items.append(self._snapshot())   # 正在编辑的也一并提交
        self.text.clear()
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
        self.items.clear()          # 文字已烘焙进新封面;留着会导致下次应用重复叠画
        self._render()
        ok(tr("cover_text_done"))
        if self._on_saved:
            self._on_saved(url)