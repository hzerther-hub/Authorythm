# -*- coding: utf-8 -*-
"""片头模拟器弹窗(对齐原版 IntroEditorDialog.vue)。

预览项目画幅 → 拖拽定位文字中心点 → 真字体 WYSIWYG → 播放预览模拟淡入淡出 → 改动即存。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)

from ..core.i18n import tr
from ..core import config, db
from ..pipeline import intro as INTRO
from . import widgets as W
from .braille import WaitingButton


class IntroPreview(QWidget):
    """片头预览:黑底(或首帧图)+ 真字体文字 + 九宫格辅助线,支持拖拽定位。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self.setMouseTracking(True)
        self.px = 0.5
        self.py = 0.5
        self.size_pct = 0.09
        self.title = ""
        self.font_file = ""
        self.show_grid = True
        self.bg_image: str | None = None
        self._font_id = -1
        self._load_font()

    def _load_font(self):
        if not self.font_file:
            return
        p = INTRO.font_dir() / self.font_file
        if p.exists():
            self._font_id = QFontDatabase.addApplicationFont(str(p))
            fams = QFontDatabase.applicationFontFamilies(self._font_id)
            if fams:
                self.setFont(QFont(fams[0], 12))

    def set_font(self, file: str):
        self.font_file = file
        self._load_font()
        self.update()

    def mousePressEvent(self, e):
        self._drag_from(e.position().x(), e.position().y())
        self._dragging = True

    def mouseMoveEvent(self, e):
        if getattr(self, "_dragging", False):
            self._move_to(e.position().x(), e.position().y())

    def mouseReleaseEvent(self, e):
        self._dragging = False
        self.on_moved()

    def on_moved(self):
        """拖拽结束回调(子类/外部绑定)。"""

    def _drag_from(self, x, y):
        self._off = (x - self.px * self.width(), y - self.py * self.height())

    def _move_to(self, x, y):
        self.px = max(0.02, min(0.98, (x - self._off[0]) / max(1, self.width())))
        self.py = max(0.02, min(0.98, (y - self._off[1]) / max(1, self.height())))
        self.update()

    def set_pos(self, px, py):
        self.px, self.py = px, py
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        p.fillRect(rect, Qt.black)
        if self.bg_image:                      # 叠加模式:铺分镜真实首帧/合成图当背景
            pm = W.pixmap_from_media(self.bg_image, rect.width(), rect.height())
            p.drawPixmap(rect, pm, QRectF(pm.rect()))
        if self.show_grid:                      # 九宫格辅助线
            p.setPen(QPen(Qt.darkGray, 1, Qt.DotLine))
            for i in (1, 2):
                p.drawLine(int(rect.width() * i / 3), 0, int(rect.width() * i / 3), rect.height())
                p.drawLine(0, int(rect.height() * i / 3), rect.width(), int(rect.height() * i / 3))
        if self.title:
            f = QFont(self.font())
            f.setPixelSize(max(10, int(self.height() * self.size_pct)))
            f.setBold(True)
            p.setFont(f)
            p.setPen(Qt.white)
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(self.title), fm.height()
            x = int(self.px * self.width() - tw / 2)
            y = int(self.py * self.height() + th / 2)
            p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignTop, self.title) if False else None
            p.drawText(x, y, self.title)
        p.end()


class IntroEditorDialog(QDialog):
    """片头编辑器:显示方式 / 片头名 / 字体 / 字号 / 位置 / 时长,改动即存。"""

    def __init__(self, parent, drama_id: int, aspect: str = "16:9", on_saved=None):
        super().__init__(parent)
        self.drama_id = drama_id
        self._on_saved = on_saved
        d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
        self.setWindowTitle(tr("片头设置"))
        self.resize(680, 620)
        root = QVBoxLayout(self)

        self.aspect = aspect or "16:9"
        self.preview = IntroPreview()
        self.preview.setMinimumHeight(180)
        self.preview.setMaximumHeight(260)
        self._apply_preview_aspect()
        root.addWidget(self.preview)

        f = QFormLayout()
        mode_row = QWidget()
        m_lay = QHBoxLayout(mode_row)
        m_lay.setContentsMargins(0, 0, 0, 0)
        self.card_cb = QCheckBox(tr("黑底标题卡(前置)"))
        self.card_cb.setChecked(bool(d["intro_card"]))
        self.overlay_cb = QCheckBox(tr("文字叠加正片开头"))
        self.overlay_cb.setChecked(bool(d["intro_overlay"]))
        m_lay.addWidget(self.card_cb)
        m_lay.addWidget(self.overlay_cb)
        m_lay.addStretch(1)
        f.addRow(tr("显示方式"), mode_row)
        # 叠加模式的预览背景:取本集首个有 first_frame_image / composed_image 的分镜
        # (storyboards 表没有 image_url 列,用错字段会让预览永远黑底)
        self.overlay_cb.toggled.connect(self._sync_preview_bg)
        self._sync_preview_bg(self.overlay_cb.isChecked())

        self.title_edit = QLineEdit(d["intro_title"] or d["title"] or "")
        self.title_edit.setMaxLength(60)
        f.addRow(tr("片头名"), self.title_edit)

        self.font_combo = QComboBox()
        for it in INTRO.list_fonts():
            self.font_combo.addItem(it["name"], it["file"])
        if d["intro_font"]:
            i = self.font_combo.findData(d["intro_font"])
            self.font_combo.setCurrentIndex(i if i >= 0 else 0)
        f.addRow(tr("字体"), self.font_combo)

        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(2, 50)
        self.size_slider.setValue(int((d["intro_font_size"] or 0.09) * 100))
        f.addRow(tr("字号"), self.size_slider)

        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.setRange(2, 98)
        self.x_slider.setValue(int((d["intro_pos_x"] if d["intro_pos_x"] is not None else 0.5) * 100))
        f.addRow(tr("位置X"), self.x_slider)
        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.setRange(2, 98)
        self.y_slider.setValue(int((d["intro_pos_y"] if d["intro_pos_y"] is not None else 0.5) * 100))
        f.addRow(tr("位置Y"), self.y_slider)

        self.dur_spin = QSpinBox()
        self.dur_spin.setRange(0, 10)
        self.dur_spin.setSingleStep(1)
        self.dur_spin.setSpecialValueText(tr("自动"))
        self.dur_spin.setValue(int(d["intro_duration"] or 0))
        f.addRow(tr("时长(秒)"), self.dur_spin)
        root.addLayout(f)

        hint = W.muted(tr("在预览区拖拽文字可调整位置;点「播放」预览淡入淡出效果"))
        root.addWidget(hint)

        btns = QHBoxLayout()
        self.play_btn = QPushButton(tr("▶ 播放预览"))
        self.play_btn.clicked.connect(self._play)
        reset = QPushButton(tr("重置布局"))
        reset.clicked.connect(self._reset)
        save = W.primary_btn(tr := tr("保存"))
        save.clicked.connect(self._save)
        close = QPushButton(tr("关闭"))
        close.clicked.connect(self.accept)
        for b in (self.play_btn, reset, save, close):
            btns.addWidget(b)
        btns.addStretch(1)
        root.addLayout(btns)

        # 预览联动
        self.preview.on_moved = lambda: (self.x_slider.setValue(int(self.preview.px * 100)),
                                         self.y_slider.setValue(int(self.preview.py * 100)))
        self._sync_preview()
        self.title_edit.textChanged.connect(self._sync_preview)
        self.font_combo.currentIndexChanged.connect(self._sync_preview)
        self.size_slider.valueChanged.connect(self._sync_preview)
        self.x_slider.valueChanged.connect(self._sync_preview)
        self.y_slider.valueChanged.connect(self._sync_preview)

    def _sync_preview(self):
        p = self.preview
        p.title = self.title_edit.text()
        p.set_font(self.font_combo.currentData() or "")
        p.size_pct = self.size_slider.value() / 100
        p.px = self.x_slider.value() / 100
        p.py = self.y_slider.value() / 100
        p.update()

    def _sync_preview_bg(self, overlay_on: bool):
        if not overlay_on:
            self.preview.bg_image = None
            self.preview.update()
            return
        row = db.q1("""SELECT sb.first_frame_image, sb.composed_image FROM storyboards sb
                       JOIN episodes e ON e.id = sb.episode_id
                       WHERE e.drama_id=? AND sb.deleted_at IS NULL
                       AND (COALESCE(sb.first_frame_image,'')!='' OR COALESCE(sb.composed_image,'')!='')
                       ORDER BY sb.storyboard_number LIMIT 1""", (self.drama_id,))
        self.preview.bg_image = (row["first_frame_image"] or row["composed_image"]) if row else None
        self.preview.update()

    def _apply_preview_aspect(self):
        """预览按项目画幅比例定尺寸:冒号形式必须转斜杠,否则比例失效、预览高度塌 0。"""
        raw = str(self.aspect or "16:9")
        try:
            aw, ah = (int(x) for x in raw.replace(":", "/").split("/"))
        except (ValueError, TypeError):
            aw, ah = 16, 9
        if aw <= 0 or ah <= 0:
            aw, ah = 16, 9
        # 按比例算预览高度(目标宽 440),夹在 [180, 260];竖版时宽度随之收窄
        h = max(180, min(260, int(440 * ah / aw)))
        self.preview.setFixedSize(max(140, int(h * aw / ah)), h)

    def _play(self):
        """模拟 ffmpeg 同款淡入淡出:fade = min(0.4, dur/3)。"""
        dur = self.dur_spin.value() or 3.0
        fade = min(0.4, dur / 3)
        self.play_btn.setEnabled(False)
        effect = QGraphicsOpacityEffect(self.preview)
        self.preview.setGraphicsEffect(effect)
        seq = [(0.0, 0.0), (fade, 1.0), (max(0.0, dur - fade), 1.0), (dur, 0.0)]
        step = 0
        def tick():
            nonlocal step
            if step >= len(seq):
                self.play_btn.setEnabled(True)
                return
            t, o = seq[step]
            effect.setOpacity(o)
            QTimer.singleShot(int(t * 1000) if step else 0, tick)
            step += 1
        tick()

    def _reset(self):
        self.x_slider.setValue(50)
        self.y_slider.setValue(50)
        self.size_slider.setValue(9)
        self.dur_spin.setValue(0)
        self._save()

    def _save(self):
        payload = {
            "intro_title": self.title_edit.text(),
            "intro_font": self.font_combo.currentData(),
            "intro_font_size": self.size_slider.value() / 100,
            "intro_pos_x": self.x_slider.value() / 100,
            "intro_pos_y": self.y_slider.value() / 100,
            "intro_duration": self.dur_spin.value() or None,
            "intro_card": self.card_cb.isChecked(),
            "intro_overlay": self.overlay_cb.isChecked(),
        }
        clean = INTRO.sanitize_intro(payload)
        sets = ",".join(f"{k}=?" for k in clean)
        db.ex(f"UPDATE dramas SET {sets}, updated_at=? WHERE id=?",
              (*clean.values(), db.now(), self.drama_id))
        if self._on_saved:
            self._on_saved()
