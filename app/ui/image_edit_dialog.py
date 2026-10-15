# -*- coding: utf-8 -*-
"""图像处理对话框(改图)—— 对齐参考项目 9272acf 的 ImageEditModal/ImageEditPanel。

参考版用 Filerobot Image Editor(Web JS),pydrama 用 PyQt 等价实现,能力对齐:
    调整: 裁剪(含 9:16 竖屏/2:3 海报预设)/旋转 90°/水平·垂直翻转
    精调: 亮度/对比度/饱和度 三滑杆实时预览
    滤镜: 黑白/复古/冷调/暖调/锐化/模糊
    水印: 文字水印(透明度/位置)
    尺寸: 按宽高重采样
    去背景: 当前画面 → 换脸边车 rembg /remove → 结果重载进编辑器(与参考同流程)

写回契约与参考一致:保存 → 新 PNG 存 static/images/,按 target 写回 image_url /
comic_image_url(不覆盖原图)。
"""
from __future__ import annotations

import io
import os
import subprocess
import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                               QGridLayout, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from ..core import config, db
from ..core.i18n import tr
from . import widgets as W
from .toast import err, ok

try:
    from PIL import (Image, ImageEnhance, ImageFilter, ImageDraw, ImageFont)
    _PIL_OK = True
except ImportError:  # noqa: BLE001
    _PIL_OK = False

# 裁剪预设(对齐参考:内置常用 + 本项目竖屏成片/竖版海报)
CROP_PRESETS = [
    ("原始", None),
    ("9:16 竖屏成片", (9, 16)),
    ("2:3 竖版海报", (2, 3)),
    ("16:9 横屏", (16, 9)),
    ("1:1 方形", (1, 1)),
    ("3:4 漫画格", (3, 4)),
]

FILTERS = ["无", "黑白", "复古", "冷调", "暖调", "锐化", "柔焦"]

# 水印预设(用户点一下即填好文字 + 颜色 + 字号 + 位置)
# 只给「文字水印」用;图片水印不涉及字体/文字,预设下拉对图片类型无意义。
# 每项:文字 / (R,G,B) / 字号%(占图高) / 位置(归一化) / 是否竖排
_WM_PRESETS = {
    "右下角·白": ("© 版权声明", (255, 255, 255), 5, (0.86, 0.92), False),
    "右下角·半透明": ("© 版权声明", (255, 255, 255), 5, (0.86, 0.92), False),
    "居中大字·白": ("样片", (255, 255, 255), 14, (0.5, 0.5), False),
    "居中大字·描边": ("样片", (240, 240, 240), 14, (0.5, 0.5), False),
    "右上角·红": ("禁止转载", (230, 60, 60), 6, (0.88, 0.1), False),
    "左下角·黄": ("内部资料", (255, 210, 60), 6, (0.1, 0.9), False),
    "右侧竖排": ("机密", (255, 255, 255), 6, (0.94, 0.5), True),
    "左侧竖排": ("机密", (255, 255, 255), 6, (0.06, 0.5), True),
}


class ImageEditDialog(QDialog):
    """改图对话框:左侧预览 + 右侧工具列;保存写回资产或下载。"""

    def __init__(self, parent, image_path: str | Path, target: dict | None = None,
                 title: str = ""):
        """
        image_path: 当前图(本地路径或 /static/...)
        target: {"type": "character|scene|prop", "id": int, "kind": "main|comic"};
                None = 独立工具(保存即下载)
        """
        super().__init__(parent)
        self.setWindowTitle(title or tr("改图"))
        self.resize(980, 700)
        self.target = target or {}
        self._history: list = []          # 撤销栈
        self._bg_busy = False

        if not _PIL_OK:
            err(tr("缺少 Pillow,无法使用改图"))
            raise RuntimeError("Pillow unavailable")

        src = Path(config.media_url_to_path(image_path) if str(image_path).startswith(("/static/", "static/"))
                   else image_path)
        if not src.exists():
            err(tr("图片文件不存在"))
            raise FileNotFoundError(str(src))
        self.base = Image.open(src).convert("RGBA")
        self.current = self.base.copy()
        self.current_name = src.stem

        root = QHBoxLayout(self)
        # ── 左:预览 ──
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(560, 520)
        self.preview.setStyleSheet("background:#14161a; border-radius:8px;")
        root.addWidget(self.preview, 1)
        # 水印拖动定位:在预览图上按住拖动,松手即位置生效。
        # 位置以归一化坐标存储(相对当前画面),换尺寸/裁剪后仍相对正确。
        self.wm_pos = (0.86, 0.92)
        from PySide6.QtGui import QColor
        self.wm_color = QColor(Qt.white)
        # 多水印:「加水印」把当前参数存为一个条目,支持多个共存;竖排逐字竖着排
        self.wm_items: list[dict] = []
        # 图片水印:选中的本地图片路径(空 = 未选)
        self._wm_image_file: str = ""
        self.preview.mousePressEvent = self._wm_press
        self.preview.mouseMoveEvent = self._wm_move
        self.preview.mouseReleaseEvent = self._wm_release
        self._wm_dragging = False
        self._wm_editing_live = True   # 预览时叠加"正在编辑"的这条;提交时关掉防画两遍

        # ── 右:工具列 ──
        tools = QVBoxLayout()
        tools.addWidget(self._section_label(tr("调整")))
        crow = QHBoxLayout()
        self.crop_combo = QComboBox()
        for name, _r in CROP_PRESETS:
            self.crop_combo.addItem(name)
        crow.addWidget(self.crop_combo, 1)
        apply_crop = QPushButton(tr("裁剪"))
        apply_crop.clicked.connect(self._apply_crop)
        crow.addWidget(apply_crop)
        tools.addLayout(crow)

        rrow = QHBoxLayout()
        rot_l = QPushButton("↺ " + tr("左旋"))
        rot_l.clicked.connect(lambda: self._apply(lambda im: im.rotate(90, expand=True)))
        rot_r = QPushButton("↻ " + tr("右旋"))
        rot_r.clicked.connect(lambda: self._apply(lambda im: im.rotate(-90, expand=True)))
        flip_h = QPushButton(tr("水平翻转"))
        flip_h.clicked.connect(lambda: self._apply(lambda im: im.transpose(Image.FLIP_LEFT_RIGHT)))
        flip_v = QPushButton(tr("垂直翻转"))
        flip_v.clicked.connect(lambda: self._apply(lambda im: im.transpose(Image.FLIP_TOP_BOTTOM)))
        for b in (rot_l, rot_r, flip_h, flip_v):
            rrow.addWidget(b)
        tools.addLayout(rrow)

        tools.addWidget(self._section_label(tr("精调")))
        # 实时预览:拖动滑杆 → 在「已固化画面」上叠加调整显示;点「应用调整」才写入
        # (此前只有"应用"按钮,拖滑杆没有任何反应,像"精调无效")
        self._adjust_base = self.current.copy()          # 合成基准
        self.brightness = self._slider(tools, tr("亮度"), 0, 200, 100)
        self.contrast = self._slider(tools, tr("对比度"), 0, 200, 100)
        self.saturation = self._slider(tools, tr("饱和度"), 0, 200, 100)
        for s_ in (self.brightness, self.contrast, self.saturation):
            s_.valueChanged.connect(self._preview_adjust)
            s_.sliderReleased.connect(self._preview_adjust)
        apply_adj = QPushButton(tr("应用调整"))
        apply_adj.clicked.connect(self._apply_adjust)
        tools.addWidget(apply_adj)

        tools.addWidget(self._section_label(tr("滤镜")))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([tr(f) for f in FILTERS])
        tools.addWidget(self.filter_combo)      # 此前下拉框从未加进布局——
        # 界面上只有「应用滤镜」按钮,用户既选不了滤镜,也不知道按钮会把
        # 一个看不见的选项(黑白)套到画面上
        apply_f = QPushButton(tr("应用滤镜"))
        apply_f.clicked.connect(self._apply_filter)
        tools.addWidget(apply_f)

        tools.addWidget(self._section_label(tr("文字水印")))
        # ── 水印类型:文字 / 图片 ──
        # 用户可选用文字还是图片当水印。两者参数不同(文字有字体/竖排,图片有
        # 缩放/形状),所以做成互斥切换,各自显示自己的参数行。
        type_row = QHBoxLayout()
        type_row.setSpacing(6)
        type_row.addWidget(QLabel(tr("水印类型")))
        self.wm_type = QComboBox()
        self.wm_type.addItem(tr("文字水印"), "text")
        self.wm_type.addItem(tr("图片水印"), "image")
        self.wm_type.currentIndexChanged.connect(self._on_wm_type)
        type_row.addWidget(self.wm_type, 1)
        tools.addLayout(type_row)

        # ── 预设样式(点一下即填好文字+颜色+字号+位置)──
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        preset_row.addWidget(QLabel(tr("水印预设")))
        self.wm_preset = QComboBox()
        self.wm_preset.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for name in _WM_PRESETS:
            self.wm_preset.addItem(name, name)
        self.wm_preset.currentIndexChanged.connect(self._apply_wm_preset)
        preset_row.addWidget(self.wm_preset, 1)
        tools.addLayout(preset_row)

        self.wm_text = QWidget()
        wl = QVBoxLayout(self.wm_text)
        wl.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QLineEdit as _QLE
        self.wm_input = _QLE()
        self.wm_input.setPlaceholderText(tr("水印文字"))
        self.wm_input.textChanged.connect(lambda: self._render())
        wl.addWidget(self.wm_input)
        # 颜色 / 字体 / 字号:此前只有白色+固定字号+固定右下角,白字压亮背景几乎隐形
        crow = QHBoxLayout()
        crow.setSpacing(6)
        crow.addWidget(QLabel(tr("cover_text_color")))
        self.wm_color_btn = QPushButton()
        self.wm_color_btn.setFixedSize(40, 24)
        self.wm_color_btn.setCursor(Qt.PointingHandCursor)
        self.wm_color_btn.clicked.connect(self._pick_wm_color)
        crow.addWidget(self.wm_color_btn)
        crow.addSpacing(8)
        crow.addWidget(QLabel(tr("cover_text_font")))
        self.wm_font = QComboBox()
        self.wm_font.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        from ..pipeline import intro as _INTRO
        for _it in _INTRO.list_fonts():
            self.wm_font.addItem(_it["name"], _it["file"])
        crow.addWidget(self.wm_font, 1)
        tools.addLayout(crow)

        srow = QHBoxLayout()
        srow.setSpacing(6)
        srow.addWidget(QLabel(tr("cover_text_size")))
        self.wm_size = self._slider(srow, "", 3, 20, 8, compact=True)
        from PySide6.QtWidgets import QLabel as _QLab
        self.wm_size_lab = _QLab("")
        self.wm_size_lab.setObjectName("muted")
        self.wm_size_lab.setFixedWidth(40)
        srow.addWidget(self.wm_size_lab)
        from PySide6.QtWidgets import QCheckBox as _QChk
        self.wm_vertical = _QChk(tr("wm_vertical"))
        self.wm_vertical.setToolTip(tr("wm_vertical_tip"))
        self.wm_vertical.toggled.connect(lambda: self._render())
        srow.addWidget(self.wm_vertical)
        srow.addStretch(1)
        tools.addLayout(srow)
        # 这些接线依赖水印控件,必须在其创建之后(预览块在第 81 行就存在了)
        self.wm_font.currentIndexChanged.connect(lambda: self._render())
        self.wm_size.valueChanged.connect(self._on_wm_size)
        self._sync_wm_color_btn()

        # ── 图片水印参数(切到「图片水印」时显示)──
        self.wm_image_box = QWidget()
        il = QVBoxLayout(self.wm_image_box)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(6)
        pick_row = QHBoxLayout()
        pick_row.setSpacing(6)
        pick_row.addWidget(QLabel(tr("水印图片")))
        self.wm_image_path = QLabel(tr("未选择图片"))
        self.wm_image_path.setObjectName("muted")
        pick_row.addWidget(self.wm_image_path, 1)
        pick_img = QPushButton(tr("选择图片…"))
        pick_img.setCursor(Qt.PointingHandCursor)
        pick_img.clicked.connect(self._pick_wm_image)
        pick_row.addWidget(pick_img)
        il.addLayout(pick_row)
        irow = QHBoxLayout()
        irow.setSpacing(6)
        irow.addWidget(QLabel(tr("图片大小")))
        self.wm_img_size = self._slider(irow, "", 5, 60, 20, compact=True)
        irow.addStretch(1)
        il.addLayout(irow)
        self.wm_image_box.setVisible(False)
        tools.addWidget(self.wm_image_box)

        wrow = QHBoxLayout()
        self.wm_opacity = self._slider(wrow, tr("透明度"), 10, 100, 80, compact=True)
        add_wm = QPushButton(tr("add_watermark_item"))
        add_wm.setToolTip(tr("add_watermark_item_tip"))
        add_wm.clicked.connect(self._add_watermark_item)
        wrow.addWidget(add_wm)
        clear_wm = QPushButton(tr("clear_watermarks"))
        clear_wm.setToolTip(tr("clear_watermarks_tip"))
        clear_wm.clicked.connect(self._clear_watermarks)
        wrow.addWidget(clear_wm)
        tools.addLayout(wrow)

        # ── 水印位置:九宫格快捷 ──
        # 预览上可以拖,但拖拽对"文字 / 图片"两类水印都要先手上有水印才生效;
        # 这里给 9 个归一化坐标按钮(0.1/0.5/0.9),点一下即定位,文字图片通用。
        pos_row = QHBoxLayout()
        pos_row.setSpacing(6)
        pos_row.addWidget(QLabel(tr("水印位置")))
        grid = QWidget()
        gl = QGridLayout(grid)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(2)
        self._pos_btns: dict[tuple[float, float], QPushButton] = {}
        for r, fy in enumerate((0.12, 0.5, 0.88)):
            for c, fx in enumerate((0.12, 0.5, 0.88)):
                b = QPushButton()
                b.setFixedSize(22, 22)
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip(f"{int(fx*100)}%, {int(fy*100)}%")
                b.clicked.connect(lambda _=False, x=fx, y=fy: self._set_wm_pos(x, y))
                gl.addWidget(b, r, c)
                self._pos_btns[(fx, fy)] = b
        pos_row.addWidget(grid)
        pos_row.addStretch(1)
        tools.addLayout(pos_row)
        tools.addWidget(self.wm_text)

        tools.addWidget(self._section_label(tr("尺寸")))
        srow = QHBoxLayout()
        from PySide6.QtWidgets import QLineEdit as _QLE
        self.resize_w = _QLE()
        self.resize_w.setPlaceholderText(str(self.base.width))
        self.resize_h = _QLE()
        self.resize_h.setPlaceholderText(str(self.base.height))
        srow.addWidget(self.resize_w)
        srow.addWidget(QLabel("×"))
        srow.addWidget(self.resize_h)
        tools.addLayout(srow)
        apply_rs = QPushButton(tr("应用尺寸"))
        apply_rs.clicked.connect(self._apply_resize)
        tools.addWidget(apply_rs)

        tools.addWidget(self._section_label(tr("AI")))
        # 修补(涂抹去文字/水印/路人):与去背景并列,结果重载回编辑器继续编辑
        self.patch_btn = QPushButton("🩹 " + tr("patch_local"))
        W.set_icon(self.patch_btn, "edit")
        self.patch_btn.setToolTip(tr("patch_in_editor_tip"))
        self.patch_btn.clicked.connect(self._open_patch)
        tools.addWidget(self.patch_btn)
        self.bg_btn = QPushButton("🌫 " + tr("去背景"))
        W.set_icon(self.bg_btn, "image")
        self.bg_btn.setToolTip(tr("rembg 抠出主体(含未保存修改);首次使用需下载模型,请耐心等待"))
        self.bg_btn.clicked.connect(self._remove_background)
        tools.addWidget(self.bg_btn)
        self._probe_bg()

        tools.addStretch(1)
        hrow = QHBoxLayout()
        # 「应用」:把当前所有未固化操作(精调滑杆 + 滤镜)一次性落到画面上,
        # 然后清空控件,作为链式编辑的下一轮起点 —— 不用分别点「应用调整」+「应用滤镜」两次。
        apply_all = QPushButton(tr("应用"))
        apply_all.setToolTip("把当前精调和滤镜一次性落到画面,作为下一轮编辑的起点")
        apply_all.clicked.connect(self._apply_all)
        hrow.addWidget(apply_all)
        undo = QPushButton(tr("撤销"))
        undo.clicked.connect(self._undo)
        hrow.addWidget(undo)
        # 「外部打开」:PhotoCraft 桌面端打开当前图,改完自动同步回来(写入 _current
        # 图层)。需要先在设置里填好 PhotoCraft 安装路径,否则按钮置灰。
        from ..ai import photocraft_bridge as _pcb
        self._open_ext_btn = QPushButton(tr("外部打开"))
        self._open_ext_btn.setToolTip(tr("open_external_photocraft_tip"))
        pc_ok = bool(_pcb.resolve_app_path() or _pcb.resolve_cli_path())
        self._open_ext_btn.setEnabled(pc_ok)
        if not pc_ok:
            self._open_ext_btn.setToolTip(self._open_ext_btn.toolTip() + " —— " + tr("open_external_no_pccraft"))
        self._open_ext_btn.clicked.connect(self._open_external_editor)
        hrow.addWidget(self._open_ext_btn)
        dl = QPushButton(tr("下载"))
        dl.clicked.connect(self._download)
        hrow.addWidget(dl)
        # 按钮文案按模式区分:资产=「保存」写回;会话=「应用」接着用;
        # 独立工具=「保存(下载到本地)」会弹文件框
        if self.target.get("type") == "session":
            _save_label = tr("应用")
        elif self.target:
            _save_label = tr("保存")
        else:
            _save_label = tr("保存(下载到本地)")
        save = QPushButton(_save_label)
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        hrow.addWidget(save)
        tools.addLayout(hrow)

        wrap = QWidget()
        wrap.setLayout(tools)
        root.addWidget(wrap, 0, Qt.AlignTop)
        self._render()

    # ── UI 小件 ──
    def _section_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet("color:#86909c; font-size:11px; font-weight:700; padding-top:4px;")
        return lab

    def _slider(self, layout, label: str, lo: int, hi: int, val: int, compact: bool = False):
        box = QWidget()
        l = QHBoxLayout(box)
        l.setContentsMargins(0, 0, 0, 0)
        if not compact:
            l.addWidget(QLabel(label))
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        if compact:
            l.addWidget(QLabel(label))
        l.addWidget(s, 1)
        if isinstance(layout, QVBoxLayout):
            layout.addWidget(box)
        else:
            layout.addWidget(box)
        return s

    # ── 操作 ──
    def _push_history(self):
        self._history.append(self.current.copy())
        if len(self._history) > 20:
            self._history.pop(0)

    def _apply(self, fn, name: str = ""):
        self._push_history()
        try:
            self.current = fn(self.current).convert("RGBA")
        except Exception as e:  # noqa: BLE001
            err(e)
            self._history.pop()
        self._adjust_base = self.current.copy()
        for s_ in (getattr(self, "brightness", None), getattr(self, "contrast", None),
                   getattr(self, "saturation", None)):
            if s_ is not None:
                s_.blockSignals(True)
                s_.setValue(100)
                s_.blockSignals(False)
        self._render()

    def _apply_crop(self):
        ratio = CROP_PRESETS[self.crop_combo.currentIndex()][1]
        if not ratio:
            return                       # 原始:不裁
        w, h = self.current.size
        target_r = ratio[0] / ratio[1]
        if w / h > target_r:             # 太宽 → 裁两侧
            nw = int(h * target_r)
            box = ((w - nw) // 2, 0, (w + nw) // 2, h)
        else:
            nh = int(w / target_r)
            box = (0, (h - nh) // 2, w, (h + nh) // 2)
        self._apply(lambda im: im.crop(box))

    @staticmethod
    def _enhance(im, b: float, c: float, s: float):
        out = im.convert("RGB")
        if b != 1.0:
            out = ImageEnhance.Brightness(out).enhance(b)
        if c != 1.0:
            out = ImageEnhance.Contrast(out).enhance(c)
        if s != 1.0:
            out = ImageEnhance.Color(out).enhance(s)
        return out

    def _preview_adjust(self, *_):
        """拖动滑杆实时预览:基准画面 + 当前三滑杆值(不进撤销栈、不改原图)。"""
        self.current = self._enhance(self._adjust_base,
                                     self.brightness.value() / 100.0,
                                     self.contrast.value() / 100.0,
                                     self.saturation.value() / 100.0).convert("RGBA")
        self._render()

    def _apply_adjust(self):
        b = self.brightness.value() / 100.0
        c = self.contrast.value() / 100.0
        s = self.saturation.value() / 100.0
        if (b, c, s) == (1.0, 1.0, 1.0):
            return
        self._apply(lambda im: self._enhance(im, b, c, s))
        # 固化后基准同步、滑杆复位,避免"再拖一点"在已增强画面上二次叠加
        self._adjust_base = self.current.copy()
        for s_ in (self.brightness, self.contrast, self.saturation):
            s_.blockSignals(True)
            s_.setValue(100)
            s_.blockSignals(False)

    def _apply_all(self):
        """一键应用:精调滑杆 + 当前滤镜一次性落到画面,作为下一轮编辑起点。

        用途:用户拖完滑杆 + 选完滤镜后,不必分别点「应用调整」「应用滤镜」;
        点「应用」直接落到当前画面,控件复位(滑杆回 100、滤镜回「无」),
        用户可以接着在已应用画面上继续做下一轮修改。
        """
        # 1) 精调滑杆(等同 _apply_adjust,但不弹 toast —— toast 留给「应用」一次)
        b = self.brightness.value() / 100.0
        c = self.contrast.value() / 100.0
        s = self.saturation.value() / 100.0
        if (b, c, s) != (1.0, 1.0, 1.0):
            self._apply(lambda im: self._enhance(im, b, c, s))
            self._adjust_base = self.current.copy()
        # 2) 当前滤镜 —— 复用 _apply_filter 的 lambda(不弹 toast)
        if self.filter_combo.currentIndex() != 0:
            name = self.filter_combo.currentText()
            def fn(im):
                rgb = im.convert("RGB")
                if name == tr("黑白"):
                    return rgb.convert("L").convert("RGB")
                if name == tr("复古"):
                    sepia = rgb.convert("L").convert("RGB")
                    r, g, b = sepia.split()
                    return Image.merge("RGB", (r.point(lambda v: min(255, int(v * 1.07))),
                                               g, b.point(lambda v: int(v * 0.85))))
                if name == tr("冷调"):
                    r, g, b = rgb.split()
                    return Image.merge("RGB", (r.point(lambda v: int(v * 0.92)), g, b.point(lambda v: min(255, int(v * 1.08)))))
                if name == tr("暖调"):
                    r, g, b = rgb.split()
                    return Image.merge("RGB", (r.point(lambda v: min(255, int(v * 1.08))), g, b.point(lambda v: int(v * 0.92))))
                if name == tr("锐化"):
                    return rgb.filter(ImageFilter.UnsharpMask(radius=2, percent=120))
                if name == tr("柔焦"):
                    return rgb.filter(ImageFilter.GaussianBlur(2))
                return rgb
            self._apply(fn)
        # 3) 控件复位(滑杆回中、滤镜回「无」,作为下一轮起点)
        for s_ in (self.brightness, self.contrast, self.saturation):
            s_.blockSignals(True)
            s_.setValue(100)
            s_.blockSignals(False)
        self.filter_combo.blockSignals(True)
        self.filter_combo.setCurrentIndex(0)
        self.filter_combo.blockSignals(False)

    def _apply_filter(self):
        name = self.filter_combo.currentText()
        def fn(im):
            rgb = im.convert("RGB")
            if name == tr("黑白"):
                return rgb.convert("L").convert("RGB")
            if name == tr("复古"):
                sepia = rgb.convert("L").convert("RGB")
                r, g, b = sepia.split()
                return Image.merge("RGB", (r.point(lambda v: min(255, int(v * 1.07))),
                                           g, b.point(lambda v: int(v * 0.85))))
            if name == tr("冷调"):
                r, g, b = rgb.split()
                return Image.merge("RGB", (r.point(lambda v: int(v * 0.92)), g, b.point(lambda v: min(255, int(v * 1.08)))))
            if name == tr("暖调"):
                r, g, b = rgb.split()
                return Image.merge("RGB", (r.point(lambda v: min(255, int(v * 1.08))), g, b.point(lambda v: int(v * 0.92))))
            if name == tr("锐化"):
                return rgb.filter(ImageFilter.UnsharpMask(radius=2, percent=120))
            if name == tr("柔焦"):
                return rgb.filter(ImageFilter.GaussianBlur(2))
            return rgb
        self._apply(fn)

    def _on_wm_size(self, v: int | None = None):
        # v 可省:预设/程序化设置 size 时会直接调本方法刷新百分比标签
        if v is None:
            v = self.wm_size.value()
        self.wm_size_lab.setText(f"{v}%")
        self._render()

    def _wm_font_of(self, px: int):
        from PIL import ImageFont
        fonts = config.ROOT_DIR / "app" / "assets" / "fonts"
        file = self.wm_font.currentData() if hasattr(self, "wm_font") else ""
        cands = ([fonts / file] if file else []) + [fonts / "msyh.ttc"]
        for fp in cands:
            if fp and fp.exists():
                try:
                    return ImageFont.truetype(str(fp), max(8, int(px)))
                except Exception:  # noqa: BLE001
                    continue
        return ImageFont.load_default()

    def _wm_snapshot(self) -> dict:
        """当前控件状态 → 一个水印条目。

        kind="text" 时带字体/文字/竖排;kind="image" 时带图片路径 + 缩放百分比。
        两种共用 color / size_pct / opacity / pos,渲染时按 kind 分派。
        """
        kind = self.wm_type.currentData() or "text"
        if kind == "image":
            return {"kind": "image",
                    "text": "",
                    "image": self._wm_image_file or "",
                    "color": self.wm_color,
                    "font_file": "",
                    "size_pct": self.wm_img_size.value(),
                    "opacity": self.wm_opacity.value() / 100.0,
                    "pos": self.wm_pos,
                    "vertical": False}
        return {"kind": "text",
                "text": self.wm_input.text().strip(),
                "image": "",
                "color": self.wm_color,
                "font_file": self.wm_font.currentData() or "",
                "size_pct": self.wm_size.value(),
                "opacity": self.wm_opacity.value() / 100.0,
                "pos": self.wm_pos,
                "vertical": self.wm_vertical.isChecked()}

    def _on_wm_type(self, _idx: int = 0):
        """切换文字/图片水印:显示对应的参数块,并刷新预览。"""
        kind = self.wm_type.currentData() or "text"
        self.wm_image_box.setVisible(kind == "image")
        self.wm_text.setVisible(kind == "text")
        # 预设只对文字有意义(图片水印没有字体/文字内容)
        self.wm_preset.setEnabled(kind == "text")
        self._render()

    def _set_wm_pos(self, fx: float, fy: float):
        """九宫格按钮:设置水印归一化位置。"""
        self.wm_pos = (fx, fy)
        self._sync_pos_btns()
        self._render()

    def _sync_pos_btns(self):
        """高亮当前所处九宫格位置(误差内算命中)。"""
        for (fx, fy), b in getattr(self, "_pos_btns", {}).items():
            hit = abs(fx - self.wm_pos[0]) < 0.02 and abs(fy - self.wm_pos[1]) < 0.02
            b.setStyleSheet(
                "QPushButton{background:#f97316;border:1px solid #f97316;border-radius:4px;}"
                if hit else
                "QPushButton{background:#fff;border:1px solid #dcdad3;border-radius:4px;}"
                "QPushButton:hover{border-color:#f97316;}")

    def _apply_wm_preset(self, _idx: int = 0):
        """点预设:把文字/颜色/字号/位置/竖排一次性填好。"""
        name = self.wm_preset.currentData()
        p = _WM_PRESETS.get(name or "")
        if not p:
            return
        text, rgb, size_pct, pos, vertical = p
        self.wm_input.setText(text)
        from PySide6.QtGui import QColor as _QC
        self.wm_color = _QC(*rgb)
        self._sync_wm_color_btn()
        self.wm_size.setValue(int(size_pct))
        self._on_wm_size()
        self.wm_vertical.setChecked(bool(vertical))
        self.wm_pos = pos
        self._sync_pos_btns()
        self._render()

    def _pick_wm_image(self):
        from PySide6.QtWidgets import QFileDialog as _QFD
        path, _ = _QFD.getOpenFileName(
            self, tr("选择水印图片"), "",
            tr("图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*.*)"))
        if not path:
            return
        self._wm_image_file = path
        from pathlib import Path as _Path
        self.wm_image_path.setText(_Path(path).name)
        self._render()

    def _draw_one_wm(self, layer_draw, im_size, it, font_of, layer=None):
        """在 layer 上画一个水印;竖排 = 逐字向下排。中心对齐 pos。

        按 it["kind"] 分派:图片水印需要 layer 图对象(alpha_composite 贴图),
        文字只靠 ImageDraw。layer 缺省时退化为只画文字。
        """
        if (it.get("kind") or "text") == "image":
            if layer is not None:
                self._wm_paste_image(layer, im_size, it)
            return
        text = it["text"]
        px = max(10, int(im_size[1] * it["size_pct"] / 100.0))
        font = font_of(it["font_file"], px)
        opacity = it["opacity"]
        c = it["color"]
        stroke = max(1, int(px / 18))
        cx, cy = im_size[0] * it["pos"][0], im_size[1] * it["pos"][1]
        fill = (c.red(), c.green(), c.blue(), int(255 * opacity))
        sf = (0, 0, 0, int(200 * opacity))
        if it.get("vertical"):
            line_h = int(px * 1.18)
            y0 = cy - line_h * (len(text) - 1) / 2
            for i, ch in enumerate(text):
                layer_draw.text((cx, y0 + i * line_h), ch, font=font, anchor="mm",
                                fill=fill, stroke_width=stroke, stroke_fill=sf)
        else:
            layer_draw.text((cx, cy), text, font=font, anchor="mm",
                            fill=fill, stroke_width=stroke, stroke_fill=sf)

    def _wm_paste_image(self, layer, im_size, it):
        """把一张图片水印贴到 layer_draw 所在的 layer 上,按 pos 中心对齐。

        ImageDraw 没有贴图 API,只能拿到 layer_draw 的底层图再 paste 回去;
        这里用 layer_draw.im 直接操作(PIL 的 Draw.im 是核心图像对象)。
        size_pct = 图片高度占原图高的百分比,保持宽高比。
        """
        path = it.get("image") or ""
        if not path:
            return
        try:
            from PIL import Image as _Img
            p = config.media_url_to_path(path) if str(path).startswith(
                ("/static/", "static/")) else __import__("pathlib").Path(path)
            if not p.exists():
                return
            wm = _Img.open(p).convert("RGBA")
        except Exception:  # noqa: BLE001 —— 图片读不了就跳过,别拖垮整张图
            return
        target_h = max(8, int(im_size[1] * it["size_pct"] / 100.0))
        scale = target_h / max(1, wm.height)
        target_w = max(1, int(wm.width * scale))
        wm = wm.resize((target_w, target_h), _Img.LANCZOS)
        alpha = int(255 * it["opacity"])
        if alpha < 255:
            # 整体透明度:改 alpha 通道,不碰 RGB(避免半透明时颜色发灰)
            a = wm.getchannel("A").point(lambda v: int(v * alpha / 255))
            wm.putalpha(a)
        cx = int(im_size[0] * it["pos"][0])
        cy = int(im_size[1] * it["pos"][1])
        left = cx - target_w // 2
        upper = cy - target_h // 2
        # layer 是调用方传下来的 RGBA 图(ImageDraw 只管画点线,贴图要用图对象)。
        # alpha_composite 天然按 alpha 混合,不需要额外遮罩;目标区域越界自动裁剪。
        layer.alpha_composite(wm, dest=(left, upper))

    def _draw_wm(self, im):
        """画**全部**已加入的水印条目 + 正在编辑的这条(实时预览)。"""
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for it in self.wm_items:
            self._draw_one_wm(draw, im.size, it, self._wm_font_of_file, layer)
        # 正在编辑的这条只在预览时叠加;提交后由 wm_items 渲染,避免画两遍
        if self._has_pending_wm() and self._wm_editing_live:
            self._draw_one_wm(draw, im.size, self._wm_snapshot(), self._wm_font_of_file, layer)
        out = im.convert("RGBA")
        out.alpha_composite(layer)
        return out

    def _wm_font_of_file(self, file: str, px: int):
        from PIL import ImageFont
        fonts = config.ROOT_DIR / "app" / "assets" / "fonts"
        for fp in ([fonts / file] if file else []) + [fonts / "msyh.ttc"]:
            if fp.exists():
                try:
                    return ImageFont.truetype(str(fp), max(8, int(px)))
                except Exception:  # noqa: BLE001
                    continue
        return ImageFont.load_default()

    def _has_pending_wm(self) -> bool:
        """当前控件上是否有一条"还没加入"的待生效水印(文字或图片任一)。"""
        if (self.wm_type.currentData() or "text") == "image":
            return bool(self._wm_image_file)
        return bool(self.wm_input.text().strip())

    def _add_watermark_item(self):
        """把当前参数存为一个水印条目(加入后可改参数再加下一个)。"""
        if (self.wm_type.currentData() or "text") == "image":
            if not self._wm_image_file:
                err(tr("请先选择水印图片"))
                return
        elif not self.wm_input.text().strip():
            err(tr("cover_text_required"))
            return
        self.wm_items.append(self._wm_snapshot())
        ok(tr("watermark_added", len(self.wm_items)))
        self._render()

    def _clear_watermarks(self):
        self.wm_items.clear()
        self._render()

    def _apply_watermark(self):
        """提交:已加入的条目 + 正在编辑的这条,一次画定。"""
        self.wm_dragging = False
        items = list(self.wm_items)
        if self._has_pending_wm():
            items.append(self._wm_snapshot())
        if not items:
            err(tr("cover_text_required"))
            return

        def fn(im):
            layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            for it in items:
                self._draw_one_wm(draw, im.size, it, self._wm_font_of_file, layer)
            out = im.convert("RGBA")
            out.alpha_composite(layer)
            return out
        self.wm_items.clear()          # 已画定,条目清空;文字框留着可继续加新的
        self._apply(fn)

    # ── 水印拖动定位 ──
    def _wm_pos_from_event(self, e):
        """预览控件坐标 → 归一化画面坐标(考虑 pixmap 在 label 内居中的偏移)。"""
        pm = self.preview.pixmap()
        if pm is None or pm.isNull():
            return None
        lw, lh = self.preview.width(), self.preview.height()
        pw, ph = pm.width(), pm.height()
        ox, oy = (lw - pw) // 2, (lh - ph) // 2
        x, y = e.position().x() - ox, e.position().y() - oy
        if x < 0 or y < 0 or x > pw or y > ph:
            return None
        return (max(0.02, min(0.98, x / pw)), max(0.02, min(0.98, y / ph)))

    def _wm_press(self, e):
        pos = self._wm_pos_from_event(e)
        if pos is None:
            return
        self.wm_pos = pos
        self._wm_dragging = True
        self._render()

    def _wm_move(self, e):
        if not self._wm_dragging:
            return
        pos = self._wm_pos_from_event(e)
        if pos is not None:
            self.wm_pos = pos
            self._render()

    def _wm_release(self, _e):
        self._wm_dragging = False

    def _pick_wm_color(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(self.wm_color, self, tr("cover_text_color"))
        if c.isValid():
            self.wm_color = c
            self._sync_wm_color_btn()
            self._render()

    def _sync_wm_color_btn(self):
        self.wm_color_btn.setStyleSheet(
            f"background:{self.wm_color.name()}; border:1px solid rgba(128,128,128,120);"
            "border-radius:4px;")

    def _apply_resize(self):
        try:
            w = int(self.resize_w.text() or self.current.width)
            h = int(self.resize_h.text() or self.current.height)
        except ValueError:
            return
        if w <= 0 or h <= 0 or (w, h) == self.current.size:
            return
        self._apply(lambda im: im.resize((w, h), Image.LANCZOS))

    def _open_patch(self):
        """在当前画面上开修补窗口,完成后把结果载回编辑器(可继续调色/裁剪)。"""
        import tempfile
        from .patch_dialog import PatchDialog
        buf = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            self.current.convert("RGB").save(buf.name, "PNG")
            buf.flush()
            dlg = PatchDialog(self, buf.name, None)
            dlg.exec()
            res = getattr(dlg, "_result", None)
            if res:
                import io as _io
                from PIL import Image
                self._push_history()
                self.current = Image.open(_io.BytesIO(res)).convert("RGB")
                self._render()
        finally:
            try:
                buf.close()
                Path(buf.name).unlink(missing_ok=True)
            except OSError:
                pass

    def _remove_background(self):
        """当前画面(含未保存修改)→ rembg → 结果重载(对齐参考 removeBackground 流程)。"""
        if self._bg_busy:
            return
        from ..ai import registry
        from ..pipeline import erase as ER
        try:
            cfg = registry.check_ready("faceswap", None)
        except Exception as e:  # noqa: BLE001
            err(f"{e}")
            return
        healthy, detail = ER.bg_remove_health(cfg)
        if not healthy:
            err(detail)
            return
        self._bg_busy = True
        self.bg_btn.setEnabled(False)
        self.bg_btn.setText("⠋ " + tr("去背景中…"))

        def job():
            buf = io.BytesIO()
            self.current.save(buf, "PNG")
            return ER.bg_remove(cfg, buf.getvalue())

        def done(result, error):
            self._bg_busy = False
            self.bg_btn.setEnabled(True)
            self.bg_btn.setText("🌫 " + tr("去背景"))
            if error:
                err(error)
                return
            self._push_history()
            self.current = Image.open(io.BytesIO(result)).convert("RGBA")
            self.current_name += "_nobg"
            self._render()
            ok(tr("去背景完成,已载入编辑器"))

        from ..core.taskmgr import TASKMGR
        TASKMGR.submit("image", lambda _tid: job(),
                       lambda _tid, result, error: done(result, error))

    def _probe_bg(self):
        """探测去背景可用性:不可用置灰并给原因(与参考 probeBg 同语义)。"""
        from ..ai import registry
        from ..pipeline import erase as ER
        try:
            cfg = registry.check_ready("faceswap", None)
            healthy, detail = ER.bg_remove_health(cfg)
        except Exception as e:  # noqa: BLE001
            healthy, detail = False, str(e)[:80]
        if not healthy:
            self.bg_btn.setEnabled(False)
            self.bg_btn.setToolTip(detail or tr("正在检测去背景服务…"))

    def _undo(self):
        if self._history:
            self.current = self._history.pop()
            self._adjust_base = self.current.copy()
            self._render()

    def _open_external_editor(self):
        """外部打开:用 PhotoCraft 桌面端编辑当前图,改完自动同步回来。

        复用 PhotoCraftWatcher(三路监听 + mtime+size 双检),与 chat-edit 的
        「✋ 我手动改」同套机制 —— 监听当前 self.current 的 PNG 副本,保存即更新。
        """
        from .photocraft_watcher import PhotoCraftWatcher
        from ..ai import photocraft_bridge as _pcb
        import os, tempfile, shutil

        app_path = _pcb.resolve_app_path()
        if not app_path:
            from .toast import err as _err
            _err(tr("open_external_no_pccraft"))
            return

        # 把当前图保存到临时目录,PhotoCraft 打开这个临时文件
        tmpdir = Path(tempfile.gettempdir()) / "pydrama_edit"
        tmpdir.mkdir(parents=True, exist_ok=True)
        tmpfile = tmpdir / f"edit_{uuid.uuid4().hex[:8]}.png"
        self.current.convert("RGB").save(str(tmpfile), "PNG")

        # 复用 watcher 实例(同一个 dialog 只跑一个)
        if not hasattr(self, "_pc_watcher") or self._pc_watcher is None:
            self._pc_watcher = PhotoCraftWatcher(self)
            self._pc_watcher.changed.connect(self._on_external_save)
        self._pc_watcher.stop()
        ok, err = self._pc_watcher.watch(str(tmpfile))
        if not ok:
            from .toast import err as _err
            _err(err)
            return

        # 启动 PhotoCraft
        try:
            subprocess.Popen([app_path, str(tmpfile.resolve())], close_fds=True)
        except Exception as exc:
            from .toast import err as _err
            _err(str(exc)[:200])
            return

        # 按钮变 busy,提示用户改完保存会同步
        self._open_ext_btn.setEnabled(False)
        self._open_ext_btn.setText(tr("外部打开") + " · 等待同步…")
        from .toast import ok as _ok
        _ok("PhotoCraft 已打开 · 改完保存会自动同步回此处")

    def _on_external_save(self, new_path: str):
        """PhotoCraft 保存触发:把外部编辑器改好的图同步到当前图层。

        同时把 self.current 替换成新图 —— 用户接着点「保存」就直接写回资产 / 下载,
        不需要再点「应用」键把外部改动落地。
        """
        try:
            from PIL import Image as _PILImage
            new_img = _PILImage.open(new_path).convert("RGB")
            self.current = new_img
            self._adjust_base = new_img.copy()
            self._history.append(new_img.copy())
            self._render()
            self._open_ext_btn.setEnabled(True)
            self._open_ext_btn.setText(tr("外部打开"))
            from .toast import ok
            ok(f"已同步 PhotoCraft 修改:{Path(new_path).name}")
        except Exception as exc:
            from .toast import err
            err(str(exc)[:200])

    def _download(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("下载"), f"{self.current_name}.png", "PNG (*.png)")
        if not path:
            return
        self.current.convert("RGB").save(path, "PNG")
        ok(tr("已下载到本地"))

    def _save(self):
        """写回资产(有 target)或下载(独立模式);新文件不覆盖原图(对齐参考 onPanelSave)。

        target.type == "session" 是聊天改图专用:产物存 static/images/,**不弹下载框**
        (会话里的图本来就是工作副本,用户要的是"改完接着用",不是存到磁盘),
        由调用方的 on_saved 回调接管(把新图同步成会话当前图)。
        """
        out_dir = config.STATIC_DIR / "images"
        out_dir.mkdir(parents=True, exist_ok=True)
        import uuid
        out = out_dir / f"edit_{uuid.uuid4().hex[:10]}.png"
        self.current.save(out, "PNG")
        url = config.path_to_media_url(out)
        t = self.target
        if t and t.get("type") in ("character", "scene", "prop"):
            table = {"character": "characters", "scene": "scenes", "prop": "props"}[t["type"]]
            col = "comic_image_url" if t.get("kind") == "comic" else "image_url"
            db.ex(f"UPDATE {table} SET {col}=?, updated_at=? WHERE id=?",
                  (url, db.now(), t["id"]))
            ok(tr("已写回资产图"))
        elif t and t.get("type") == "session":
            ok(tr("已应用到当前图,可继续在会话里修改"))
        else:
            path, _ = QFileDialog.getSaveFileName(self, tr("下载"), f"{self.current_name}_edited.png", "PNG (*.png)")
            if path:
                self.current.convert("RGB").save(path, "PNG")
                ok(tr("已下载到本地"))
        self.saved_url = url
        self.accept()

    # ── 渲染 ──
    def _render(self):
        im = self.current.convert("RGB")
        im.thumbnail((680, 620), Image.LANCZOS)
        # 水印实时预览:有待生效水印(文字或图片)就叠加显示(未提交),拖动位置/换色/换字体即时可见。
        # preview_scale = 缩略图高 / 实际高,把字号比例换算到缩略图坐标系。
        if self._has_pending_wm() or self.wm_items:
            try:
                im = self._draw_wm(im).convert("RGB")
            except Exception:  # noqa: BLE001 —— 预览叠加失败不拖垮正常渲染
                pass
        data = im.tobytes("raw", "RGB")
        qimg = QImage(data, im.size[0], im.size[1], im.size[0] * 3, QImage.Format_RGB888)
        self.preview.setPixmap(QPixmap.fromImage(qimg))


def open_image_edit(parent, image_url: str, target: dict | None = None, title: str = "",
                    on_saved=None) -> None:
    """通用改图入口(对齐参考资产 lightbox「改图」)。on_saved(url) 在写回后回调刷新。"""
    try:
        dlg = ImageEditDialog(parent, image_url, target=target, title=title)
    except (RuntimeError, FileNotFoundError):
        return
    if dlg.exec() == QDialog.Accepted and on_saved and getattr(dlg, "saved_url", None):
        on_saved(dlg.saved_url)
