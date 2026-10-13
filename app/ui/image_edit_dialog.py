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
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                               QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from ..core import config, db
from ..core.i18n import tr
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
        apply_f = QPushButton(tr("应用滤镜"))
        apply_f.clicked.connect(self._apply_filter)
        tools.addWidget(apply_f)

        tools.addWidget(self._section_label(tr("文字水印")))
        self.wm_text = QWidget()
        wl = QVBoxLayout(self.wm_text)
        wl.setContentsMargins(0, 0, 0, 0)
        from PySide6.QtWidgets import QLineEdit as _QLE
        self.wm_input = _QLE()
        self.wm_input.setPlaceholderText(tr("水印文字"))
        wl.addWidget(self.wm_input)
        wrow = QHBoxLayout()
        self.wm_opacity = self._slider(wrow, tr("透明度"), 10, 100, 45, compact=True)
        apply_wm = QPushButton(tr("加水印"))
        apply_wm.clicked.connect(self._apply_watermark)
        wrow.addWidget(apply_wm)
        tools.addLayout(wrow)
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
        self.patch_btn.setToolTip(tr("patch_in_editor_tip"))
        self.patch_btn.clicked.connect(self._open_patch)
        tools.addWidget(self.patch_btn)
        self.bg_btn = QPushButton("🌫 " + tr("去背景"))
        self.bg_btn.setToolTip(tr("rembg 抠出主体(含未保存修改);首次使用需下载模型,请耐心等待"))
        self.bg_btn.clicked.connect(self._remove_background)
        tools.addWidget(self.bg_btn)
        self._probe_bg()

        tools.addStretch(1)
        hrow = QHBoxLayout()
        undo = QPushButton(tr("撤销"))
        undo.clicked.connect(self._undo)
        hrow.addWidget(undo)
        dl = QPushButton(tr("下载"))
        dl.clicked.connect(self._download)
        hrow.addWidget(dl)
        save = QPushButton(tr("保存" + ("" if self.target else "(下载到本地)")))
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
            err(str(e)[:180])
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

    def _apply_watermark(self):
        text = self.wm_input.text().strip()
        if not text:
            return
        opacity = self.wm_opacity.value() / 100.0

        def fn(im):
            layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            fs = max(14, im.size[1] // 22)
            try:
                font = ImageFont.truetype(str(config.ROOT_DIR / "app" / "assets" / "fonts" / "msyh.ttc"), fs)
            except Exception:  # noqa: BLE001
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x, y = im.size[0] - tw - fs, im.size[1] - th - fs     # 右下角
            draw.text((x, y), text, font=font, fill=(255, 255, 255, int(255 * opacity)))
            out = im.convert("RGBA")
            out.alpha_composite(layer)
            return out
        self._apply(fn)

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
                err(str(error)[:200])
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

    def _download(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("下载"), f"{self.current_name}.png", "PNG (*.png)")
        if not path:
            return
        self.current.convert("RGB").save(path, "PNG")
        ok(tr("已下载到本地"))

    def _save(self):
        """写回资产(有 target)或下载(独立模式);新文件不覆盖原图(对齐参考 onPanelSave)。"""
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
