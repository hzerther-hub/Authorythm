"""封面加字:文字 / 字体 / 字号 / 颜色 / 透明度 / 位置(九宫格 + 鼠标拖拽)/ 竖排。

交互对齐「改图」页的文字水印面板(image_edit_dialog):3×3 位置九宫格 +
**预览图上直接拖拽定位** + 透明度滑杆 + 预设一键填参 —— 用户实测反馈
「封面加字参考改图水印做,同时要选字体、可以用鼠标拖拽」。字体下拉本就来自
intro.list_fonts()(app/assets/fonts 下 10 款,含之芒行楷)。

渲染仍是 RGBA 图层 + alpha_composite(借自 image_edit_dialog 的文字水印),
位置从「上/中/下」离散档升级为**归一化坐标 (fx, fy)**(与改图水印同体系,
拖拽与九宫格共用);多行横排与竖排都以 (fx, fy) 为块中心定位。描边保留:
纯色大字压在复杂封面上容易糊,一圈暗色描边保证任何底图上都可读。
"""
from __future__ import annotations

import io
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from ..core import config, db
from ..core.i18n import tr
from . import widgets as W
from .toast import err, ok

# 封面标题预设(参考改图水印的 _WM_PRESETS 形态):(颜色, 字号%, (fx, fy), 竖排)。
# 封面是「排版主字」不是贴边角的小字,预设围绕标题排版给,不含文字内容。
_COVER_PRESETS = {
    "cover_preset_bottom_white": ("#FFFFFF", 8, (0.5, 0.86), False),
    "cover_preset_top_white": ("#FFFFFF", 6, (0.5, 0.12), False),
    "cover_preset_corner_white": ("#FFFFFF", 4, (0.85, 0.9), False),
    "cover_preset_vertical_white": ("#FFFFFF", 9, (0.5, 0.5), True),
}

# 九宫格按钮的归一化坐标(与改图水印一致):边、中、角
_GRID_POS = (0.12, 0.5, 0.88)


class _DragPreview(QLabel):
    """可拖拽预览图:按住左键拖动,把位置实时喂回对话框(改图水印同款交互)。

    九宫格只能落在 9 个离散点上,拖拽才是「差一点挪一点」的连续定位;
    两者写同一个 self._dlg._pos,互不冲突。
    """

    def __init__(self, dialog):
        super().__init__()
        self._dlg = dialog
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.setCursor(Qt.ClosedHandCursor)
            self._dlg._on_preview_drag(ev)

    def mouseMoveEvent(self, ev):
        if ev.buttons() & Qt.LeftButton:
            self._dlg._on_preview_drag(ev)

    def mouseReleaseEvent(self, _ev):
        self.setCursor(Qt.OpenHandCursor)


class CoverTextDialog(QDialog):
    """封面加字编辑器。"""

    def __init__(self, parent, url: str | None, drama_id: int = 0, on_saved=None):
        super().__init__(parent)
        self.setWindowTitle(tr("cover_add_text"))
        self.resize(760, 700)
        self.url = url
        self.drama_id = drama_id
        self._on_saved = on_saved
        self._color = QColor("#FFFFFF")
        self._font_file = ""
        self._size_pct = 8
        self._pos = (0.5, 0.86)      # 归一化坐标,默认下方居中(与旧版 bottom 一致)
        self._opacity = 100

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        self.preview = _DragPreview(self)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(280)
        self.preview.setToolTip(tr("cover_text_drag_tip"))
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
        row2.addWidget(QLabel(tr("cover_text_opacity")))
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(self._opacity)
        self.opacity_slider.valueChanged.connect(self._on_opacity)
        self.opacity_lab = QLabel("")
        self.opacity_lab.setObjectName("muted")
        self.opacity_lab.setFixedWidth(48)
        row2.addWidget(self.opacity_slider, 1)
        row2.addWidget(self.opacity_lab)
        # 竖排:逐字向下排(书名/古装标题风)
        self.vertical_chk = QCheckBox(tr("wm_vertical"))
        self.vertical_chk.setToolTip(tr("wm_vertical_tip"))
        self.vertical_chk.toggled.connect(self._render)
        row2.addWidget(self.vertical_chk)
        root.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel(tr("cover_text_preset")))
        self.preset_combo = QComboBox()
        for key in _COVER_PRESETS:
            self.preset_combo.addItem(tr(key), key)
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        row3.addWidget(self.preset_combo)
        row3.addSpacing(12)
        row3.addWidget(QLabel(tr("cover_text_pos")))
        # 3×3 九宫格:9 个离散落点;拖拽预览图可连续微调(两者共用 _pos)
        self._pos_btns: dict[tuple[float, float], QPushButton] = {}
        grid = QGridLayout()
        grid.setSpacing(2)
        for fy in _GRID_POS:
            for fx in _GRID_POS:
                b = QPushButton()
                b.setFixedSize(22, 22)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, fx=fx, fy=fy: self._set_pos(fx, fy))
                grid.addWidget(b, _GRID_POS.index(fy), _GRID_POS.index(fx))
                self._pos_btns[(fx, fy)] = b
        grid_wrap = QHBoxLayout()
        grid_wrap.addLayout(grid)
        grid_wrap.addStretch(1)
        row3.addLayout(grid_wrap, 1)
        root.addLayout(row3)

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
        self._on_opacity(self._opacity)
        self._sync_pos_btns()

    # ── 控件回调 ──
    def _on_size(self, v: int):
        self._size_pct = v
        self.size_lab.setText(f"{v}%")
        self._render()

    def _on_opacity(self, v: int):
        self._opacity = v
        self.opacity_lab.setText(f"{v}%")
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

    def _apply_preset(self, idx: int):
        """预设一键填参:颜色/字号/位置/竖排(文字内容不动,由用户填)。"""
        key = self.preset_combo.itemData(idx)
        if not key:
            return
        color, size, pos, vertical = _COVER_PRESETS[key]
        self._color = QColor(color)
        self._set_color_btn()
        self.size_slider.setValue(size)
        self._set_pos(*pos)
        self.vertical_chk.setChecked(vertical)

    def _set_pos(self, fx: float, fy: float):
        self._pos = (float(fx), float(fy))
        self._sync_pos_btns()
        self._render()

    def _sync_pos_btns(self):
        """九宫格高亮当前落点(±0.02 容差,拖拽后的连续坐标也能对上格)。"""
        for (fx, fy), b in self._pos_btns.items():
            hit = abs(fx - self._pos[0]) <= 0.02 and abs(fy - self._pos[1]) <= 0.02
            b.setStyleSheet(
                "QPushButton{background:#f97316;border:none;border-radius:4px;}"
                if hit else
                "QPushButton{background:#e4e7ec;border:none;border-radius:4px;}")

    def _on_preview_drag(self, ev):
        """预览图拖拽 → 归一化坐标(改图水印 _wm_pos_from_event 同款换算)。

        QPixmap 以 KeepAspectRatio 缩放后**居中**贴在 QLabel 里,先把鼠标坐标
        平移回贴图区、再按贴图尺寸归一化,否则留白也算进位置,字会飘出图外。
        """
        pm = self.preview.pixmap()
        if pm is None or pm.width() <= 0:
            return
        lw, lh = self.preview.width(), self.preview.height()
        ox = max(0, (lw - pm.width()) // 2)
        oy = max(0, (lh - pm.height()) // 2)
        x, y = ev.position().x() - ox, ev.position().y() - oy
        if x < 0 or y < 0 or x > pm.width() or y > pm.height():
            return      # 拖出图外不更新,松手前停在哪就停在哪
        fx = min(0.98, max(0.02, x / pm.width()))
        fy = min(0.98, max(0.02, y / pm.height()))
        self._pos = (fx, fy)
        self._sync_pos_btns()
        self._render()

    # ── 渲染 ──
    def _load_font(self, px: int, file: str = ""):
        """file 参数与 _draw_item 的 font_of 约定对齐;缺省用正在编辑的字体。"""
        if not file:
            file = self._font_file
        from PIL import ImageFont

        from ..pipeline.intro import font_dir
        fonts = font_dir()
        cands = ([fonts / file] if file else []) + [fonts / "msyh.ttc"]
        for fp in cands:
            if fp and fp.exists():
                try:
                    return ImageFont.truetype(str(fp), max(8, int(px)))
                except Exception:  # noqa: BLE001
                    continue
        return ImageFont.load_default()

    def _snapshot(self) -> dict:
        """当前控件状态 → 一个文字条目(pos/opacity 一并入库,旧条目不受影响)。"""
        return {"text": self.text.toPlainText().strip(),
                "color": self._color,
                "font_file": self._font_file,
                "size_pct": self._size_pct,
                "pos": tuple(self._pos),
                "opacity": self._opacity / 100.0,
                "vertical": self.vertical_chk.isChecked()}

    def _draw_item(self, base_size, draw, it, font_of):
        """画一个文字条目;以归一化 pos 为**块中心**,横排多行 / 竖排逐字。"""
        px = max(10, int(base_size[1] * it["size_pct"] / 100.0))
        font = font_of(px, it["font_file"])
        r, g, b = it["color"].getRgb()[:3]
        op = float(it.get("opacity", 1.0))
        fill = (r, g, b, int(255 * op))
        stroke = max(1, int(px / 18))
        stroke_fill = (0, 0, 0, int(200 * op))
        fx, fy = (it.get("pos") or (0.5, 0.86))[:2]
        cx = base_size[0] * fx
        lines = [ln for ln in it["text"].splitlines() if ln.strip()]
        if it.get("vertical"):
            text = "".join(lines)                      # 多行合一后竖排
            line_h = int(px * 1.18)
            y0 = base_size[1] * fy - line_h * len(text) / 2
            for i, ch in enumerate(text):
                draw.text((cx, y0 + i * line_h + line_h / 2), ch,
                          font=font, anchor="mm", fill=fill,
                          stroke_width=stroke, stroke_fill=stroke_fill)
        else:
            line_h = int(px * 1.35)
            total = line_h * max(1, len(lines))
            y0 = base_size[1] * fy - total / 2
            for i, ln in enumerate(lines):
                bbox = draw.textbbox((0, 0), ln, font=font, stroke_width=stroke)
                tw = bbox[2] - bbox[0]
                draw.text((int(cx - tw / 2), int(y0 + i * line_h)), ln, font=font,
                          fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)

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
