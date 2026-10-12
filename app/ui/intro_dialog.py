# -*- coding: utf-8 -*-
"""片头模拟器弹窗(对齐原版 IntroEditorDialog.vue)。

预览项目画幅 → 拖拽定位文字中心点 → 真字体 WYSIWYG → 播放预览模拟淡入淡出 → 改动即存。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen
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
    """片头预览:撑满舞台区,内部按项目画幅(竖屏 9:16 / 横屏 16:9)居中出画幅框,
    黑底(或首帧图)+ 真字体文字 + 九宫格辅助线,支持拖拽定位(坐标相对画幅框)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setMouseTracking(True)
        self.px = 0.5
        self.py = 0.5
        self.size_pct = 0.09
        self.title = ""
        self.font_file = ""
        self.show_grid = True
        self.bg_image: str | None = None
        self._font_id = -1
        self._aw, self._ah = 9, 16       # 项目画幅,默认竖屏
        self._load_font()

    def set_aspect(self, aw: int, ah: int):
        self._aw, self._ah = max(1, aw), max(1, ah)
        self.update()

    def stage_rect(self) -> QRectF:
        """画幅框:舞台内按比例居中的最大矩形(信箱式)。"""
        r = self.rect()
        aw, ah = self._aw, self._ah
        if r.width() / r.height() > aw / ah:      # 舞台更宽 → 高度撑满,宽按比例收
            h = r.height()
            w = h * aw / ah
        else:                                     # 舞台更高 → 宽度撑满,高按比例收
            w = r.width()
            h = w * ah / aw
        return QRectF((r.width() - w) / 2, (r.height() - h) / 2, w, h)

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
        r = self.stage_rect()
        self._off = (x - (r.x() + self.px * r.width()), y - (r.y() + self.py * r.height()))

    def _move_to(self, x, y):
        r = self.stage_rect()
        self.px = max(0.02, min(0.98, (x - self._off[0] - r.x()) / max(1.0, r.width())))
        self.py = max(0.02, min(0.98, (y - self._off[1] - r.y()) / max(1.0, r.height())))
        self.update()

    def set_pos(self, px, py):
        self.px, self.py = px, py
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        whole = self.rect()
        p.fillRect(whole, QColor("#2e3138"))     # 舞台底(画幅框外的信箱区,明显浅于卡片)
        rect = self.stage_rect().toAlignedRect()
        p.fillRect(rect, Qt.black)
        if self.bg_image:                      # 叠加模式:铺分镜真实首帧/合成图当背景
            pm = W.pixmap_from_media(self.bg_image, rect.width(), rect.height())
            # drawPixmap 目标/源矩形类型必须一致(混用 QRect 与 QRectF 会直接抛签名错)
            p.drawPixmap(rect, pm, pm.rect())
        if self.show_grid:                      # 九宫格辅助线
            p.setPen(QPen(Qt.darkGray, 1, Qt.DotLine))
            for i in (1, 2):
                p.drawLine(rect.x() + int(rect.width() * i / 3), rect.y(),
                           rect.x() + int(rect.width() * i / 3), rect.y() + rect.height())
                p.drawLine(rect.x(), rect.y() + int(rect.height() * i / 3),
                           rect.x() + rect.width(), rect.y() + int(rect.height() * i / 3))
        if self.title:
            f = QFont(self.font())
            f.setPixelSize(max(10, int(rect.height() * self.size_pct)))
            f.setBold(True)
            p.setFont(f)
            p.setPen(Qt.white)
            fm = p.fontMetrics()
            tw, th = fm.horizontalAdvance(self.title), fm.height()
            x = int(rect.x() + self.px * rect.width() - tw / 2)
            y = int(rect.y() + self.py * rect.height() + th / 2)
            p.drawText(x, y, self.title)
        p.end()


class IntroEditorDialog(QDialog):
    """片头编辑器(对齐参考 IntroEditorDialog):左预览舞台 + 右控制列,改动即存。

    预览舞台可用鼠标拖拽标题调位置;控制列的字号/位置滑杆带 % 实时数值,
    模式(黑底标题卡 / 正片文字叠加)也在这里设,导出页只留一个「加入片头」总开关。
    """

    def __init__(self, parent, drama_id: int, aspect: str = "16:9", on_saved=None):
        super().__init__(parent)
        self.drama_id = drama_id
        self._on_saved = on_saved
        d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
        self.setWindowTitle(tr("edit_intro"))
        self.resize(880, 520)
        root = QVBoxLayout(self)

        self.aspect = aspect or "16:9"

        # ── 左:预览舞台(撑满)+ 拖拽提示 + 播放/重置 ──
        left = QVBoxLayout()
        self.preview = IntroPreview()
        self.preview.setMinimumHeight(300)
        self._set_preview_aspect()
        left.addWidget(self.preview, 1)
        hint = W.muted(tr("intro_drag_hint"))
        hint.setAlignment(Qt.AlignCenter)
        left.addWidget(hint)
        stage_btns = QHBoxLayout()
        self.play_btn = QPushButton(tr("▶ 播放预览"))
        self.play_btn.clicked.connect(self._play)
        reset = QPushButton(tr("intro_reset"))
        reset.clicked.connect(self._reset)
        stage_btns.addWidget(self.play_btn)
        stage_btns.addWidget(reset)
        stage_btns.addStretch(1)
        left.addLayout(stage_btns)

        # ── 右:控制列(模式/片头名/字体/字号/位置/时长) ──
        right = QVBoxLayout()
        right.setSpacing(8)
        mode_lab = QLabel(tr("intro_mode"))
        mode_lab.setObjectName("inspectorLabel")
        right.addWidget(mode_lab)
        self.card_cb = QCheckBox(tr("黑底标题卡(前置)"))
        self.card_cb.setChecked(bool(d["intro_card"]))
        self.overlay_cb = QCheckBox(tr("文字叠加正片开头"))
        self.overlay_cb.setChecked(bool(d["intro_overlay"]))
        right.addWidget(self.card_cb)
        right.addWidget(self.overlay_cb)
        self.overlay_cb.toggled.connect(self._sync_preview_bg)
        self._sync_preview_bg(self.overlay_cb.isChecked())

        def _lab(text: str) -> QLabel:
            l = QLabel(text)
            l.setObjectName("inspectorLabel")
            return l

        right.addWidget(_lab(tr("片头名")))
        self.title_edit = QLineEdit(d["intro_title"] or d["title"] or "")
        self.title_edit.setMaxLength(60)
        right.addWidget(self.title_edit)

        right.addWidget(_lab(tr("字体")))
        self.font_combo = QComboBox()
        for it in INTRO.list_fonts():
            self.font_combo.addItem(it["name"], it["file"])
        if d["intro_font"]:
            i = self.font_combo.findData(d["intro_font"])
            self.font_combo.setCurrentIndex(i if i >= 0 else 0)
        right.addWidget(self.font_combo)

        self.size_lab = _lab(tr("intro_font_size"))
        right.addWidget(self.size_lab)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(2, 50)
        self.size_slider.setValue(int((d["intro_font_size"] or 0.09) * 100))
        right.addWidget(self.size_slider)

        self.pos_lab = _lab(tr("intro_pos"))
        right.addWidget(self.pos_lab)
        self.x_slider = QSlider(Qt.Horizontal)
        self.x_slider.setRange(2, 98)
        self.x_slider.setValue(int((d["intro_pos_x"] if d["intro_pos_x"] is not None else 0.5) * 100))
        right.addWidget(self.x_slider)
        self.y_slider = QSlider(Qt.Horizontal)
        self.y_slider.setRange(2, 98)
        self.y_slider.setValue(int((d["intro_pos_y"] if d["intro_pos_y"] is not None else 0.5) * 100))
        right.addWidget(self.y_slider)

        dur_row = QHBoxLayout()
        dl = _lab(tr("intro_duration"))
        dur_row.addWidget(dl)
        dur_row.addStretch(1)
        self.dur_spin = QSpinBox()
        self.dur_spin.setRange(0, 10)
        self.dur_spin.setSingleStep(1)
        self.dur_spin.setSpecialValueText(tr("自动"))
        self.dur_spin.setValue(int(d["intro_duration"] or 0))
        self.dur_spin.setSuffix(" s")
        dur_row.addWidget(self.dur_spin)
        right.addLayout(dur_row)
        right.addStretch(1)

        body = QHBoxLayout()
        body.addLayout(left, 3)
        body.addLayout(right, 2)
        root.addLayout(body, 1)

        btns = QHBoxLayout()
        save = W.primary_btn(tr("save"))
        save.clicked.connect(self._save)
        close = QPushButton(tr("close"))
        close.clicked.connect(self.accept)
        btns.addStretch(1)
        btns.addWidget(save)
        btns.addWidget(close)
        root.addLayout(btns)

        # 预览联动(滑杆数值同步进 % 标签)
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
        # 滑杆标签带 % 实时数值(对齐参考 introFontSize · 9% / X 50% / Y 50%)
        self.size_lab.setText(f"{tr('intro_font_size')} · {self.size_slider.value()}%")
        self.pos_lab.setText(f"{tr('intro_pos')} · X {self.x_slider.value()}% / Y {self.y_slider.value()}%")

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

    def _set_preview_aspect(self):
        """把项目画幅交给预览(冒号/斜杠都收):舞台撑满,画幅框在内部按比例居中。"""
        raw = str(self.aspect or "9:16")
        try:
            aw, ah = (int(x) for x in raw.replace(":", "/").split("/"))
        except (ValueError, TypeError):
            aw, ah = 9, 16
        if aw <= 0 or ah <= 0:
            aw, ah = 9, 16
        self.preview.set_aspect(aw, ah)

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
