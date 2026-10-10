# -*- coding: utf-8 -*-
"""换脸工具页 —— ① 源人脸 → ② 角色模板图 → ③ 结果 三段式向导。

对齐参考项目 views/tools/face-swap.vue + components/FaceSwapPanel.vue:

    ① 源人脸   上传 / 剪贴板粘贴 / URL 粘贴 / 从其他角色形象选;分辨率告警
    ② 模板图   选角色 → 载入其基础形象 + 全部造型变体(逐张保持原比例)
    ③ 结果     独立结果区 + 逐张 ok/失败角标 + 进度条

引擎下拉合并 faceswap 与 image 两类服务(未配置时给本地服务占位项),
风格下拉 + 自由提示词;逐张重绘、灯箱、全部下载、全部应用、恢复原貌。
上次选择(provider / 风格 / 提示词 / 角色)记在 app_settings,
避免按优先级排序把用户静默切到风格化模型。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..ai import face_swap, registry
from ..core import config, db
from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from . import widgets as W
from .braille import WaitingButton
from .toast import err, ok

SIZE_FAIL_PX = 256          # 短边低于此值直接判失败
SIZE_WARN_PX = 512          # 低于此值给警告
LAST_SELECTION_KEY = "yihao:face_swap:last_selection"

# 模块级写 tr() 会在 import 时就把语言定死(踩过:模块级常量里的语言永远切不动),
# 所以这里只存键,标签由 style_label() 现取。
STYLE_KEYS = ["photorealistic", "cinematic", "anime"]


def style_label(key: str) -> str:
    return {"photorealistic": tr("写实真人"), "cinematic": tr("电影质感"),
            "anime": tr("动漫风格")}.get(key, key)


STYLES = [(k, style_label(k)) for k in STYLE_KEYS]
STYLE_PROMPT = {
    "photorealistic": "写实真人摄影,自然皮肤纹理,真实光影",
    "cinematic": "电影质感,戏剧化布光,浅景深",
    "anime": "日系动漫风格,干净线条,赛璐璐上色",
}


class _TargetCard(QFrame):
    """②/③ 段里的一张模板图卡:原比例缩略 + 标签 + 逐张重绘 + 灯箱。"""

    def __init__(self, url: str, label: str, variant_id: int | None = None,
                 on_remove=None, on_redraw=None, on_preview=None):
        super().__init__()
        self.setObjectName("card")
        self.url = url
        self.label = label
        self.variant_id = variant_id
        self.result_path: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(5)
        self.img = QLabel()
        self.img.setFixedSize(150, 118)
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setPixmap(W.pixmap_from_media(url, 150, 118))
        self.img.setCursor(Qt.PointingHandCursor)
        self.img.mousePressEvent = lambda _e: on_preview() if on_preview else None
        lay.addWidget(self.img)
        name = QLabel(label[:16])
        name.setObjectName("muted")
        name.setToolTip(label)
        lay.addWidget(name)
        self.status = QLabel(tr("pending"))
        self.status.setObjectName("muted")
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.setSpacing(4)
        redraw = QPushButton("⟳")
        redraw.setToolTip(tr("redraw_this"))
        redraw.setFixedSize(26, 24)
        redraw.setCursor(Qt.PointingHandCursor)
        redraw.clicked.connect(lambda _=False: on_redraw() if on_redraw else None)
        row.addWidget(redraw)
        if on_remove:
            rm = QPushButton("×")
            rm.setStyleSheet("border:none;color:#dc2626;")
            rm.setFixedSize(24, 24)
            rm.setToolTip(tr("remove_from_list"))
            rm.clicked.connect(lambda _=False: on_remove())
            row.addWidget(rm)
        row.addStretch(1)
        lay.addLayout(row)

    def set_result(self, path: str):
        self.result_path = path
        self.status.setText("✅ " + tr("swapped"))
        self.img.setPixmap(W.pixmap_from_media(path, 150, 118))

    def set_busy(self):
        self.status.setText("⠋ " + tr("in_progress"))

    def set_failed(self, msg: str):
        self.status.setText("❌ " + msg[:24])


class _StepPanel(QFrame):
    """带序号与标题的一段容器(① / ② / ③)。"""

    def __init__(self, num: str, title: str):
        super().__init__()
        self.setObjectName("stepPanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        chip = QLabel(num)
        chip.setFixedSize(22, 22)
        chip.setAlignment(Qt.AlignCenter)
        chip.setStyleSheet("background:#f97316;color:#ffffff;border-radius:11px;"
                           "font-size:11px;font-weight:800;border:none;")
        head.addWidget(chip)
        lab = QLabel(title)
        lab.setStyleSheet("font-weight:700;font-size:13px;border:none;")
        head.addWidget(lab)
        head.addStretch(1)
        self.head_extra = head
        lay.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        lay.addLayout(self.body)


class FaceSwapPage(QWidget):
    def __init__(self):
        super().__init__()
        self.character: dict | None = None
        self.targets: list[_TargetCard] = []
        self.source_path: str | None = None
        self._original_snapshot: dict | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 20)
        root.setSpacing(10)

        head = QHBoxLayout()
        t = W.h1("🎭 " + tr("face_swap"))
        head.addWidget(t)
        head.addStretch(1)
        root.addLayout(head)
        root.addWidget(W.muted(tr("face_swap_hint")))

        # 引擎 / 风格 / 参数
        opt = QHBoxLayout()
        opt.addWidget(QLabel(tr("engine")))
        self.engine_combo = QComboBox()
        self.engine_combo.setMinimumWidth(200)
        self.engine_combo.setToolTip(tr("engine_tip"))
        self.engine_combo.currentIndexChanged.connect(lambda _i: self._check_health())
        opt.addWidget(self.engine_combo)
        self.health_lab = W.muted("…")
        opt.addWidget(self.health_lab)
        opt.addSpacing(10)
        opt.addWidget(QLabel(tr("style") + ":"))
        self.style_combo = QComboBox()
        for key in STYLE_KEYS:
            self.style_combo.addItem(style_label(key), key)
        self.style_combo.setCurrentIndex(1)
        opt.addWidget(self.style_combo)
        self.all_faces = QCheckBox(tr("replace_all_faces"))
        self.all_faces.setChecked(True)
        opt.addWidget(self.all_faces)
        self.enhance = QCheckBox(tr("face_enhance"))
        opt.addWidget(self.enhance)
        opt.addStretch(1)
        self.src_size_lab = W.muted("")
        opt.addWidget(self.src_size_lab)
        root.addLayout(opt)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(tr("style_prompt_ph"))
        self.prompt_edit.setFixedHeight(46)
        root.addWidget(self.prompt_edit)

        body = QHBoxLayout()
        body.setSpacing(10)

        # ① 源人脸
        p1 = _StepPanel("①", tr("step1_source"))
        pick = QPushButton("📁 " + tr("pick_source_file"))
        pick.clicked.connect(self._pick_source)
        paste = QPushButton("📋 " + tr("paste_from_clipboard"))
        paste.clicked.connect(self._paste_source)
        row1 = QHBoxLayout()
        row1.addWidget(pick)
        row1.addWidget(paste)
        row1.addStretch(1)
        p1.body.addLayout(row1)
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(tr("source_url_ph"))
        self.url_edit.returnPressed.connect(self._use_url)
        url_btn = QPushButton(tr("use_url"))
        url_btn.clicked.connect(self._use_url)
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(url_btn)
        p1.body.addLayout(url_row)
        p1.body.addWidget(W.muted(tr("step1_source_hint")))
        self.src_img = QLabel(tr("no_source"))
        self.src_img.setFixedSize(200, 200)
        self.src_img.setAlignment(Qt.AlignCenter)
        self.src_img.setObjectName("fsPreview")
        self.src_img.setCursor(Qt.PointingHandCursor)
        self.src_img.mousePressEvent = lambda _e: self._preview_source()
        p1.body.addWidget(self.src_img, 0, Qt.AlignLeft)
        self.src_note = W.muted("")
        p1.body.addWidget(self.src_note)
        p1.body.addStretch(1)          # 没有 stretch 项时 Qt 会把余量平分,把标题挤到中间
        body.addWidget(p1)

        # ② 角色模板图
        p2 = _StepPanel("②", tr("step2_template"))
        self.char_combo = QComboBox()
        self.char_combo.setMinimumWidth(200)
        self.char_combo.currentIndexChanged.connect(lambda _i: self._load_character())
        row2 = QHBoxLayout()
        row2.addWidget(self.char_combo)
        row2.addStretch(1)
        p2.body.addLayout(row2)
        p2.body.addWidget(W.muted(tr("step2_template_hint")))
        self.tpl_scroll = QScrollArea()
        self.tpl_scroll.setWidgetResizable(True)
        self.tpl_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.tpl_host = QWidget()
        self.tpl_grid = QGridLayout(self.tpl_host)
        self.tpl_grid.setContentsMargins(0, 0, 0, 0)
        self.tpl_grid.setSpacing(8)
        self.tpl_scroll.setWidget(self.tpl_host)
        self.tpl_empty = QLabel(tr("pick_character_first"))
        self.tpl_empty.setObjectName("muted")
        self.tpl_empty.setAlignment(Qt.AlignCenter)
        p2.body.addWidget(self.tpl_scroll, 1)
        p2.body.addWidget(self.tpl_empty)
        add_row = QHBoxLayout()
        add_files = QPushButton(tr("add_local_files"))
        add_files.setToolTip(tr("add_local_files_tip"))
        add_files.clicked.connect(self._add_local_targets)
        clear_all = QPushButton(tr("clear_all"))
        clear_all.clicked.connect(self._clear_targets)
        add_row.addWidget(add_files)
        add_row.addWidget(clear_all)
        add_row.addStretch(1)
        p2.body.addLayout(add_row)
        body.addWidget(p2, 1)

        # ③ 结果
        p3 = _StepPanel("③", tr("step3_result"))
        self.prog = QProgressBar()
        self.prog.setVisible(False)
        p3.body.addWidget(self.prog)
        self.res_scroll = QScrollArea()
        self.res_scroll.setWidgetResizable(True)
        self.res_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.res_host = QWidget()
        self.res_grid = QGridLayout(self.res_host)
        self.res_grid.setContentsMargins(0, 0, 0, 0)
        self.res_grid.setSpacing(8)
        self.res_scroll.setWidget(self.res_host)
        p3.body.addWidget(self.res_scroll, 1)
        self.res_empty = QLabel(tr("no_result_yet"))
        self.res_empty.setObjectName("muted")
        self.res_empty.setAlignment(Qt.AlignCenter)
        p3.body.addWidget(self.res_empty)
        act = QHBoxLayout()
        act.setSpacing(6)
        self.go_btn = WaitingButton("▶ " + tr("start_swap"), primary=True)
        self.go_btn.clicked.connect(self._run)
        act.addWidget(self.go_btn)
        self.dl_btn = QPushButton(tr("download_all"))
        self.dl_btn.clicked.connect(self._download_all)
        self.dl_btn.setEnabled(False)
        act.addWidget(self.dl_btn)
        self.apply_btn = QPushButton(tr("apply_to_character"))
        self.apply_btn.clicked.connect(self._apply_all)
        self.apply_btn.setEnabled(False)
        act.addWidget(self.apply_btn)
        self.revert_btn = QPushButton(tr("revert_original"))
        self.revert_btn.clicked.connect(self._revert_all)
        self.revert_btn.setEnabled(False)
        act.addWidget(self.revert_btn)
        act.addStretch(1)
        p3.body.addLayout(act)
        body.addWidget(p3, 1)
        root.addLayout(body, 1)

        self.reload_models()
        self._load_characters()
        self._restore_selection()

    # ── 引擎 / 风格 ──
    def reload_models(self):
        self.engine_combo.blockSignals(True)
        self.engine_combo.clear()
        rows = [dict(r) for r in registry.list_configs("faceswap")] + \
               [dict(r) for r in registry.list_configs("image")]
        rows = [r for r in rows if r.get("is_active")]
        rows.sort(key=lambda r: -(int(r.get("priority") or 0)))
        if not rows:
            self.engine_combo.addItem(tr("local_service_not_configured"), None)
        for r in rows:
            label = f"{r['remark'] or r['provider']} / {r['model']}"
            tag = tr("faceswap_service") if r["service_type"] == "faceswap" else tr("image_service")
            self.engine_combo.addItem(f"{label}  ({tag})", r["id"])
        self.engine_combo.blockSignals(False)
        self._check_health()

    def _check_health(self):
        cfg_id = self.engine_combo.currentData()
        if cfg_id is None:
            self.health_lab.setText("")
            self.go_btn.setEnabled(False)
            return
        cfg = db.q1("SELECT service_type FROM ai_service_configs WHERE id=?", (cfg_id,))
        if cfg and cfg["service_type"] == "image":
            # 图片模型走通用连通性,不跑换脸健康检查
            self.health_lab.setText("")
            self.go_btn.setEnabled(True)
            return
        healthy, msg = face_swap.health(config_id=cfg_id)
        self.health_lab.setText(("✅ " if healthy else "❌ ") + msg)
        self.go_btn.setEnabled(bool(healthy) and bool(self.targets) and bool(self.source_path))

    # ── ① 源人脸 ──
    def _set_source(self, path: str):
        if not path:
            return
        p = Path(path)
        if not p.exists():
            err(tr("source_not_found"))
            return
        self.source_path = str(p)
        self.src_img.setPixmap(W.pixmap_from_media(str(p), 196, 196))
        self._check_source_size(p)
        self._check_health()

    def _pick_source(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("pick_source_file"), "",
                                          "Images (*.png *.jpg *.jpeg *.webp)")
        if p:
            self._set_source(p)

    def _paste_source(self):
        """从剪贴板粘贴:优先读 image mime,否则把文本当本地路径 / URL 处理。"""
        cb = QGuiApplication.clipboard()
        mime = cb.mimeData()
        if mime and mime.hasImage():
            import uuid as _uuid
            out_dir = config.STATIC_DIR / "uploads"
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"clip_src_{_uuid.uuid4().hex[:8]}.png"
            if cb.image().save(str(path)):
                self._set_source(str(path))
                return
        text = cb.text().strip() if mime else ""
        if not text:
            err(tr("clipboard_empty"))
            return
        if text.lower().startswith(("http://", "https://")):
            self.url_edit.setText(text)
            self._use_url()
        else:
            self._set_source(text)

    def _use_url(self):
        url = self.url_edit.text().strip()
        if not url:
            return
        try:
            from ..ai.image_client import _download as fetch_image   # 复用既有下载器
            out = fetch_image(url)
        except Exception as exc:  # noqa: BLE001
            err(tr("source_url_failed") + str(exc)[:120])
            return
        self._set_source(str(out))

    def _check_source_size(self, path) -> bool:
        from PySide6.QtGui import QPixmap
        pm = QPixmap(str(path))
        w, h = pm.width(), pm.height()
        shortest = min(w, h) if w and h else 0
        if not shortest:
            self.src_size_lab.setText("")
            self.go_btn.setEnabled(True)
            return True
        if shortest < SIZE_FAIL_PX:
            self.src_size_lab.setText(tr("src_size_fail", shortest))
            self.src_size_lab.setStyleSheet("color:#dc2626;")
            self.go_btn.setEnabled(False)
            return False
        if shortest < SIZE_WARN_PX:
            self.src_size_lab.setText(tr("src_size_warn", w, h, shortest))
            self.src_size_lab.setStyleSheet("color:#d97706;")
            self.go_btn.setEnabled(True)
            return True
        self.src_size_lab.setText(tr("src_size_ok", w, h))
        self.src_size_lab.setStyleSheet("color:#16a34a;")
        self.go_btn.setEnabled(True)
        return True

    def _preview_source(self):
        if self.source_path:
            from .asset_dialogs import ImageViewerDialog
            ImageViewerDialog(self, self.source_path, tr("step1_source")).exec()

    # ── ② 角色模板图 ──
    def _load_characters(self):
        self.char_combo.blockSignals(True)
        self.char_combo.clear()
        rows = db.q("SELECT id, name, role_type, image_url FROM characters "
                    "WHERE image_url IS NOT NULL AND image_url!='' ORDER BY name")
        for r in rows:
            role = {"lead": tr("lead"), "supporting": tr("supporting")}.get(
                r["role_type"] or "", tr("supporting"))
            self.char_combo.addItem(f"{r['name']}({role})", r["id"])
        self.char_combo.blockSignals(False)
        if rows:
            self.char_combo.setCurrentIndex(0)

    def _load_character(self):
        """载入角色的基础形象 + 全部造型变体(逐张保持原比例)。"""
        cid = self.char_combo.currentData()
        if not cid:
            return
        self.character = dict(db.q1("SELECT * FROM characters WHERE id=?", (cid,)))
        items = [("", self.character["image_url"], None)]
        for v in db.q("SELECT * FROM character_variants WHERE character_id=? "
                      "AND image_url IS NOT NULL AND image_url!='' "
                      "ORDER BY is_default DESC, sort_order ASC, id", (cid,)):
            items.append((v["label"] or tr("u_variants"), v["image_url"], v["id"]))
        self._render_targets([it for it in items if it[1]])

    def _add_local_targets(self):
        paths, _ = QFileDialog.getOpenFileNames(self, tr("add_local_files"), "",
                                                "Images (*.png *.jpg *.jpeg *.webp)")
        if not paths:
            return
        self._render_targets([(Path(p).name[:24], p, None) for p in paths])

    def _render_targets(self, items):
        while self.tpl_grid.count():
            it = self.tpl_grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.targets = []
        for i, (label, url, vid) in enumerate(items):
            card = _TargetCard(url, label, vid,
                               on_remove=lambda k=i: self._remove_target(k),
                               on_redraw=lambda k=i: self._redraw_one(k),
                               on_preview=lambda k=i: self._preview_target(k))
            self.targets.append(card)
            self.tpl_grid.addWidget(card, i // 3, i % 3)
        self.tpl_grid.setRowStretch((len(items) + 2) // 3, 1)
        self.tpl_empty.setVisible(not items)
        self._snapshot_original()
        self._render_results()
        self._check_health()

    def _remove_target(self, idx: int):
        self._render_targets([(c.label, c.url, c.variant_id)
                              for k, c in enumerate(self.targets) if k != idx])

    def _clear_targets(self):
        self._render_targets([])

    def _snapshot_original(self):
        """记录原始形象,供「恢复原貌」。"""
        if self.character:
            self._original_snapshot = {"id": self.character["id"],
                                      "image_url": self.character["image_url"]}
            self.revert_btn.setEnabled(True)

    # ── ③ 结果 ──
    def _render_results(self):
        while self.res_grid.count():
            it = self.res_grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        for i, c in enumerate(self.targets):
            self.res_grid.addWidget(c, i // 2, i % 2)
        self.res_grid.setRowStretch((len(self.targets) + 1) // 2, 1)
        self.res_empty.setVisible(not self.targets)
        done = sum(1 for c in self.targets if c.result_path)
        self.dl_btn.setEnabled(done > 0)
        self.apply_btn.setEnabled(done > 0)
        if self.targets:
            self.prog.setRange(0, len(self.targets))
            self.prog.setValue(done)

    def _preview_target(self, idx: int):
        c = self.targets[idx]
        from .asset_dialogs import ImageViewerDialog
        ImageViewerDialog(self, c.result_path or c.url, c.label).exec()

    # ── 执行 ──
    def _cfg_id(self):
        return self.engine_combo.currentData()

    def _style_suffix(self) -> str:
        key = self.style_combo.currentData() or "cinematic"
        return STYLE_PROMPT.get(key, "")

    def _run(self):
        if not self.source_path:
            err(tr("pick_source_first"))
            return
        if not self.targets:
            err(tr("no_target_yet"))
            return
        cfg_id = self._cfg_id()
        if cfg_id is None:
            err(tr("local_service_not_configured"))
            return
        extra = "，".join(x for x in (self._style_suffix(),
                                      self.prompt_edit.toPlainText().strip()) if x)
        cards = list(self.targets)
        all_faces = self.all_faces.isChecked()
        enhance = self.enhance.isChecked()

        self.go_btn.busy(tr("in_progress"))
        self.prog.setVisible(True)
        self.prog.setValue(0)
        for c in cards:
            c.set_busy()
        self._persist_selection()

        def job(tid):
            outs = []
            for c in cards:
                try:
                    out = face_swap.swap_one_by_provider(
                        c.url, self.source_path, provider="remote-faceswap" if False else None,
                        config_id=cfg_id, output_format="jpg",
                        swap_all_faces=all_faces, face_enhance=enhance,
                        prompt=extra or None) if hasattr(face_swap, "swap_one_by_provider") \
                        else face_swap.swap_one(c.url, self.source_path,
                                                swap_all_faces=all_faces,
                                                face_enhance=enhance, config_id=cfg_id)
                    outs.append((c, str(out), ""))
                except Exception as exc:  # noqa: BLE001
                    outs.append((c, "", str(exc)[:80]))
            return outs

        def done(tid, result, error):
            self.go_btn.idle()
            self.prog.setVisible(False)
            if error:
                err(str(error)[:200])
                return
            ok_n = 0
            for card, out, msg in (result or []):
                if out:
                    card.set_result(out)
                    ok_n += 1
                else:
                    card.set_failed(msg or tr("failed"))
            self._render_results()
            ok(f"{tr('swapped')} {ok_n}/{len(cards)}")

        TASKMGR.submit("face_swap", job, done)

    def _redraw_one(self, idx: int):
        """逐张重绘(只重跑这一张,秒级)。"""
        if not self.source_path or idx >= len(self.targets):
            return
        card = self.targets[idx]
        cfg_id = self._cfg_id()
        card.set_busy()
        extra = "，".join(x for x in (self._style_suffix(),
                                      self.prompt_edit.toPlainText().strip()) if x)

        def job(tid):
            return str(face_swap.swap_one_by_provider(
                self.source_path, card.url, config_id=cfg_id,
                swap_all_faces=self.all_faces.isChecked(),
                face_enhance=self.enhance.isChecked()))

        def done(tid, result, error):
            if error:
                card.set_failed(str(error)[:24])
            else:
                card.set_result(result)
                self._render_results()

        TASKMGR.submit("face_swap", job, done)

    def _download_all(self):
        from ..core import download as dl_mod
        n = 0
        for c in self.targets:
            if not c.result_path:
                continue
            try:
                dl_mod.download_media(c.result_path, f"{c.label or 'face'}_{n:02d}.jpg")
                n += 1
            except Exception:  # noqa: BLE001
                continue
        if n:
            ok(f"{tr('download')} {n}")
        else:
            err(tr("no_result_yet"))

    def _apply_all(self):
        """把结果写回角色形象(有变体的写变体,否则写角色主形象)。"""
        if not self.character:
            return
        n = 0
        for c in self.targets:
            if not c.result_path:
                continue
            url = config.path_to_media_url(c.result_path)
            if c.variant_id:
                db.ex("UPDATE character_variants SET image_url=?, comic_image_url=? WHERE id=?",
                      (url, url, c.variant_id))
            else:
                db.ex("UPDATE characters SET image_url=?, updated_at=? WHERE id=?",
                      (url, db.now(), self.character["id"]))
            n += 1
        if n:
            ok(f"{tr('apply_to_character')} {n}")

    def _revert_all(self):
        if not self._original_snapshot:
            return
        db.ex("UPDATE characters SET image_url=?, updated_at=? WHERE id=?",
              (self._original_snapshot["image_url"], db.now(),
               self._original_snapshot["id"]))
        ok(tr("restored_original"))
        self._load_character()

    # ── 上次选择记忆 ──
    def _persist_selection(self):
        db.set_setting(LAST_SELECTION_KEY, json.dumps({
            "engine": self._cfg_id(),
            "style": self.style_combo.currentData(),
            "prompt": self.prompt_edit.toPlainText(),
            "character": self.char_combo.currentData(),
        }, ensure_ascii=False))

    def _restore_selection(self):
        raw = db.get_setting(LAST_SELECTION_KEY, "")
        if not raw:
            return
        try:
            sel = json.loads(raw)
        except (TypeError, ValueError):
            return
        i = self.char_combo.findData(sel.get("character"))
        if i >= 0:
            self.char_combo.setCurrentIndex(i)
        i = self.engine_combo.findData(sel.get("engine"))
        if i >= 0:
            self.engine_combo.setCurrentIndex(i)
        i = self.style_combo.findData(sel.get("style"))
        if i >= 0:
            self.style_combo.setCurrentIndex(i)
        if sel.get("prompt"):
            self.prompt_edit.setPlainText(sel["prompt"])