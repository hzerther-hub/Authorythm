# -*- coding: utf-8 -*-
"""新建项目对话框:5 种创作目标(含同款复刻)+ 视觉风格 + 画面比例 + 面孔文化(+宣传平台/格式)。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QRadioButton, QScrollArea, QVBoxLayout, QWidget)

from ..core import db
from ..core.i18n import tr
from . import widgets as W

WORK_TYPES = [
    ("novel", "§", "wt_novel", "wt_novel_desc"),
    ("drama", "▷", "wt_drama", "wt_drama_desc"),
    ("comic", "▤", "wt_comic", "wt_comic_desc"),
    ("promotion", "◈", "wt_promotion", "wt_promotion_desc"),
    ("video_clone", "▷", "wt_clone", "wt_clone_desc"),
]
ASPECTS = [("16:9", "u_ratio_16_9"), ("9:16", "u_ratio_9_16"), ("1:1", "u_ratio_1_1"),
                        ("adaptive", "u_ratio_adaptive")]
ETHNICITIES = [("auto", "ethnicity_auto"), ("east_asian", "u_eth_east_asian"), ("middle_eastern", "u_eth_middle_eastern"),
                       ("western", "u_eth_western"), ("south_asian", "u_eth_south_asian"),
                       ("latin", "u_eth_latin"), ("african", "u_eth_african"), ("mixed", "u_eth_mixed")]
PLATFORM_KEYS = [("douyin", "抖音"), ("xiaohongshu", "小红书"), ("wechat_channels", "视频号"),
                 ("wechat_mp", "公众号"), ("bilibili", "B站"), ("zhihu", "知乎")]
FORMAT_KEYS = [("video", "短视频"), ("image_set", "图文集"), ("card_burst", "卡点"),
               ("mixed_clip", "混剪"), ("voiceover", "口播"), ("article", "长图文")]


def platforms() -> list[tuple[str, str]]:
    """平台/形式选项现取标签 —— 模块级写 tr() 会把语言定死在 import 那一刻。"""
    return [(v, tr(name)) for v, name in PLATFORM_KEYS]


def formats() -> list[tuple[str, str]]:
    return [(v, tr(name)) for v, name in FORMAT_KEYS]


def style_choices(work_type: str) -> list[tuple[str, str]]:
    rows = db.q("SELECT name,value,work_type FROM style_presets WHERE is_active=1 ORDER BY sort_order")
    out = []
    for r in rows:
        wt = r["work_type"]
        if work_type in wt.split(",") or "all" in wt.split(","):
            out.append((r["value"], r["name"]))
    return out or [("3d", tr("3D 漫剧"))]


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("new_project"))
        self.resize(560, 680)
        self._ref_video = ""
        self._product_img = ""
        self._presenter_img = ""
        root = QVBoxLayout(self)

        root.addWidget(W.h2(tr("new_project")))
        root.addWidget(W.muted(tr("创建后进入项目页选择集")))

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("name_placeholder"))
        form = QFormLayout()
        form.addRow(tr("project_name") + " *", self.name_edit)
        root.addLayout(form)

        # 创作目标
        root.addWidget(W.muted(tr("work_type")))
        goal_box = QVBoxLayout()
        self._radios: dict[str, QRadioButton] = {}
        for wt, icon, name_key, desc_key in WORK_TYPES:
            rb = QRadioButton(f"{icon}  {tr(name_key)}    —  {tr(desc_key)}")
            if wt == "drama":
                rb.setChecked(True)
            self._radios[wt] = rb
            goal_box.addWidget(rb)
        root.addLayout(goal_box)

        # 动态区(宣传/复刻专属字段)
        self.dynamic = QVBoxLayout()
        root.addLayout(self.dynamic)

        # 风格 / 比例 / 面孔文化
        self.style_combo = QComboBox()
        self.aspect_combo = QComboBox()
        for v, label in ASPECTS:
            self.aspect_combo.addItem(tr(label), v)
        self.eth_combo = QComboBox()
        for v, label in ETHNICITIES:
            self.eth_combo.addItem(tr(label), v)
        more = QFormLayout()
        more.addRow(tr("visual_style"), self.style_combo)
        more.addRow(tr("aspect_ratio"), self.aspect_combo)
        more.addRow(tr("ethnicity"), self.eth_combo)
        root.addLayout(more)
        root.addWidget(W.muted(tr("ratio_note")))

        root.addStretch(1)

        btns = QHBoxLayout()
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        ok = W.primary_btn(tr("create"))
        ok.clicked.connect(self._submit)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)

        for rb in self._radios.values():
            rb.toggled.connect(self._rebuild_dynamic)
        self._rebuild_dynamic()

    # ── 动态字段 ──
    def _clear_dynamic(self):
        while self.dynamic.count():
            item = self.dynamic.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _rebuild_dynamic(self):
        self._clear_dynamic()
        wt = self.work_type()
        self.style_combo.blockSignals(True)
        self.style_combo.clear()
        for v, name in style_choices(wt):
            self.style_combo.addItem(name, v)
        if wt == "promotion":
            i = self.style_combo.findData("healing")
            if i >= 0:
                self.style_combo.setCurrentIndex(i)
        else:
            i = self.style_combo.findData("3d")
            if i >= 0:
                self.style_combo.setCurrentIndex(i)
        self.style_combo.blockSignals(False)

        if wt == "promotion":
            self.platform_combo = QComboBox()
            for v, name in platforms():
                self.platform_combo.addItem(name, v)
            self.fmt_combo = QComboBox()
            for v, name in formats():
                self.fmt_combo.addItem(name, v)
            lay = QFormLayout()
            lay.addRow(tr("target_platform") + " *", self.platform_combo)
            lay.addRow(tr("output_format") + " *", self.fmt_combo)
            box = QWidget()
            box.setLayout(lay)
            self.dynamic.addWidget(box)
        elif wt == "video_clone":
            lay = QFormLayout()
            self.ref_btn = QPushButton(tr("📹 选择参考视频…"))
            self.ref_btn.clicked.connect(self._pick_video)
            self.product_btn = QPushButton(tr("▣ 选择产品照片…"))
            self.product_btn.clicked.connect(self._pick_product)
            self.presenter_btn = QPushButton(tr("👤 选择出镜照片(可选)…"))
            self.presenter_btn.clicked.connect(self._pick_presenter)
            lay.addRow(tr("参考视频 *"), self.ref_btn)
            lay.addRow(tr("产品照片 *"), self.product_btn)
            lay.addRow(tr("出镜人照片"), self.presenter_btn)
            box = QWidget()
            box.setLayout(lay)
            self.dynamic.addWidget(box)
            note = W.muted(tr("复刻流程:AI 看懂原片出分镜表 → 备好产品/主角素材 → 逐镜重拍 → 按原片节奏无损拼接成片。"))
            self.dynamic.addWidget(note)

    def _pick_video(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("选择参考视频"), "", "Videos (*.mp4 *.mov *.mkv *.webm)")
        if p:
            self._ref_video = p
            self.ref_btn.setText("📹 " + p.split("/")[-1].split("\\")[-1])

    def _pick_product(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("选择产品照片"), "", "Images (*.png *.jpg *.jpeg *.webp)")
        if p:
            self._product_img = p
            self.product_btn.setText("▣ " + p.split("/")[-1].split("\\")[-1])

    def _pick_presenter(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("选择出镜照片"), "", "Images (*.png *.jpg *.jpeg *.webp)")
        if p:
            self._presenter_img = p
            self.presenter_btn.setText("👤 " + p.split("/")[-1].split("\\")[-1])

    def work_type(self) -> str:
        for wt, rb in self._radios.items():
            if rb.isChecked():
                return wt
        return "drama"

    def _submit(self):
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setFocus()
            return
        if self.work_type() == "video_clone" and not self._ref_video:
            self.ref_btn.setFocus()
            return
        self.accept()

    def result_data(self) -> dict:
        import json
        meta: dict = {}
        wt = self.work_type()
        if wt == "promotion":
            meta = {"platform": self.platform_combo.currentData(),
                    "format": self.fmt_combo.currentData()}
        elif wt == "video_clone":
            meta = {"clone": {"reference_src": self._ref_video,
                              "product_src": self._product_img,
                              "presenter_src": self._presenter_img}}
        return {
            "title": self.name_edit.text().strip(),
            "work_type": wt,
            "style": self.style_combo.currentData() or "3d",
            "aspect_ratio": self.aspect_combo.currentData(),
            "ethnicity": self.eth_combo.currentData(),
            "metadata": json.dumps(meta, ensure_ascii=False),
        }
