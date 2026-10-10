# -*- coding: utf-8 -*-
"""资产·角色卡换脸对话框:

角色当前形象 → 选源脸(上传照片 / 从其他角色形象选) → 参数 → 换脸预览
→ 「应用替换形象」写回 characters.image_url(取消则不动)。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                               QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QVBoxLayout)

from ..ai import face_swap
from ..core import config, db
from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from . import widgets as W
from .toast import err, ok


class CharacterFaceSwapDialog(QDialog):
    def __init__(self, parent, character: dict, face_cfg_id: int | None, face_cfg_label: str = ""):
        super().__init__(parent)
        self.character = character
        self.cfg_id = face_cfg_id
        self.source_path: str | None = None
        self.result_path: str | None = None
        self._original_snapshot: dict | None = None  # 恢复原貌快照
        self._batch_running = False
        self.setWindowTitle(f"{tr('face_swap')} · {character['name']}")
        self.resize(760, 560)
        root = QVBoxLayout(self)
        root.setSpacing(12)

        root.addWidget(W.h2(f"🎭 {tr('face_swap')} · {character['name']}"))
        root.addWidget(W.muted(tr("为角色形象换脸:选择源脸照片(可上传或取自其他角色),换脸预览满意后替换角色形象。")
                              + (f"  换脸模型:{face_cfg_label}" if face_cfg_label else "")))

        cols = QHBoxLayout()
        # 当前形象
        cur_box = QVBoxLayout()
        cur_box.addWidget(QLabel(tr("appearance") + tr("(当前形象)")))
        self.cur_img = QLabel()
        self.cur_img.setFixedSize(240, 240)
        self.cur_img.setAlignment(Qt.AlignCenter)
        self.cur_img.setStyleSheet("border:1px solid rgba(128,128,128,50);border-radius:8px;")
        self.cur_img.setPixmap(W.pixmap_from_media(character["image_url"], 236, 236))
        cur_box.addWidget(self.cur_img)
        cols.addLayout(cur_box)
        # 源脸
        src_box = QVBoxLayout()
        src_box.addWidget(QLabel(tr("源脸照片")))
        self.src_img = QLabel(tr("未选择"))
        self.src_img.setFixedSize(240, 240)
        self.src_img.setAlignment(Qt.AlignCenter)
        self.src_img.setStyleSheet("border:1px dashed rgba(128,128,128,80);border-radius:8px;color:#888;")
        src_box.addWidget(self.src_img)
        btns = QHBoxLayout()
        up = QPushButton("▣ " + tr("upload"))
        up.clicked.connect(self._pick_source)
        other = QComboBox()
        other.addItem(tr("从其他角色形象选…"), None)
        for r in db.q("SELECT id,name,image_url FROM characters WHERE id!=? AND image_url IS NOT NULL",
                      (character["id"],)):
            other.addItem(r["name"], r["image_url"])
        other.currentIndexChanged.connect(self._use_other_character)
        btns.addWidget(up)
        btns.addWidget(other, 1)
        src_box.addLayout(btns)
        cols.addLayout(src_box)
        # 结果
        res_box = QVBoxLayout()
        res_box.addWidget(QLabel(tr("换脸预览")))
        self.res_img = QLabel("—")
        self.res_img.setFixedSize(240, 240)
        self.res_img.setAlignment(Qt.AlignCenter)
        self.res_img.setStyleSheet("border:1px solid rgba(75,110,245,60);border-radius:8px;color:#888;")
        res_box.addWidget(self.res_img)
        cols.addLayout(res_box)
        root.addLayout(cols, 1)

        opt = QHBoxLayout()
        self.all_faces = QCheckBox(tr("替换图中所有脸"))
        self.all_faces.setChecked(True)          # 对齐原版:默认全替换
        self.enhance = QCheckBox(tr("人脸增强"))
        self.style_combo = QComboBox()
        for k, label in (("photorealistic", tr("写实")), ("cinematic", tr("电影感")), ("anime", tr("动漫"))):
            self.style_combo.addItem(label, k)
        self.style_combo.setCurrentIndex(1)     # 默认 cinematic
        opt.addWidget(QLabel(tr("引擎")))
        self.engine_combo = QComboBox()
        self._engines = []
        for st in ("faceswap", "image"):       # 换脸组 + 图片组(风格化重绘)
            for r in db.q("SELECT id,provider,remark,base_url FROM ai_service_configs "
                          "WHERE service_type=? AND is_active=1 ORDER BY priority DESC", (st,)):
                self.engine_combo.addItem(f"{r['remark'] or r['provider']}", (r["id"], r["provider"]))
        if self.engine_combo.count() == 0:
            self.engine_combo.addItem(tr("本地 InsightFace"), (None, "local-faceswap"))
        opt.addWidget(self.engine_combo)
        opt.addWidget(QLabel(tr("风格")))
        opt.addWidget(self.style_combo)
        opt.addSpacing(10)
        opt.addWidget(self.all_faces)
        opt.addWidget(self.enhance)
        self.size_tip = W.muted("")
        opt.addWidget(self.size_tip)
        opt.addStretch(1)
        self.go_btn = W.primary_btn("▶ " + tr("face_swap"))
        self.go_btn.clicked.connect(self._run)
        opt.addWidget(self.go_btn)
        root.addLayout(opt)

        mid_row = QHBoxLayout()
        self.batch_btn = QPushButton(tr("▶ 批量换脸(全部形象)"))
        self.batch_btn.clicked.connect(self._batch)
        self.download_btn = QPushButton(tr("↓ 批量下载结果"))
        self.download_btn.setEnabled(False)
        self.download_btn.clicked.connect(self._download_all)
        revert_btn = QPushButton(tr("↺ 恢复原貌"))
        revert_btn.clicked.connect(self._restore_original)
        self.results: dict[str, str] = {}  # label -> 结果路径
        mid_row.addWidget(self.batch_btn)
        mid_row.addWidget(self.download_btn)
        mid_row.addWidget(revert_btn)
        mid_row.addStretch(1)
        root.addLayout(mid_row)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        self.apply_btn = W.primary_btn(tr("✅ 应用替换形象"))
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._apply)
        bottom.addWidget(cancel)
        bottom.addWidget(self.apply_btn)
        root.addLayout(bottom)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        root.addWidget(self.status)

    def _load_char_images(self) -> list[tuple[str, str, str]]:
        """返回该角色全部待换脸图片 [(label, image_url, local_path)],含基础形象与所有变体。"""
        c = self.character
        items: list[tuple[str, str, str]] = []
        if c.get("image_url"):
            items.append((tr("基础形象"), c["image_url"], str(config.media_url_to_path(c["image_url"]))))
        for v in db.q("SELECT * FROM character_variants WHERE character_id=? AND image_url IS NOT NULL",
                      (c["id"],)):
            items.append((v["label"] or tr("变体"), v["image_url"],
                          str(config.media_url_to_path(v["image_url"]))))
        if not self._original_snapshot and c.get("image_url"):
            self._original_snapshot = {"image_url": c["image_url"]}
        return items

    def _restore_original(self):
        """恢复原貌:把快照写回角色形象(仅在存在快照时可用)。"""
        if not self._original_snapshot:
            QMessageBox.information(self, tr("face_swap"), tr("no_snapshot_to_restore"))
            return
        db.ex("UPDATE characters SET image_url=?, updated_at=? WHERE id=?",
              (self._original_snapshot["image_url"], db.now(), self.character["id"]))
        QMessageBox.information(self, tr("face_swap"), tr("restored_original"))

    # ── 源脸 ──
    def _pick_source(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("upload"), "", "Images (*.png *.jpg *.jpeg *.webp)")
        if p:
            self.source_path = p
            self.src_img.setPixmap(W.pixmap_from_media(p, 236, 236))
            self.src_img.setStyleSheet("border:1px solid rgba(128,128,128,50);border-radius:8px;")
            self._check_source_size(p)

    # 源脸分辨率:≥512 可用;<512 警告;<256 直接判失败(换脸模型需要足够的人脸细节)
    SIZE_FAIL_PX = 256
    SIZE_WARN_PX = 512

    def _check_source_size(self, path) -> bool:
        """检查源脸分辨率并更新提示条;返回是否可用。"""
        from PySide6.QtGui import QPixmap
        pm = QPixmap(str(path))
        w, h = pm.width(), pm.height()
        shortest = min(w, h)
        if not w or not h:
            self.size_tip.setText("")
            self.go_btn.setEnabled(True)
            return True
        if shortest < self.SIZE_FAIL_PX:
            self.size_tip.setText(tr("src_size_fail", shortest))
            self.size_tip.setStyleSheet("color:#dc2626;font-size:12px;")
            self.go_btn.setEnabled(False)
            return False
        if shortest < self.SIZE_WARN_PX:
            self.size_tip.setText(tr("src_size_warn", w, h, shortest))
            self.size_tip.setStyleSheet("color:#d97706;font-size:12px;")
            self.go_btn.setEnabled(True)
            return True
        self.size_tip.setText(tr("src_size_ok", w, h))
        self.size_tip.setStyleSheet("color:#16a34a;font-size:12px;")
        self.go_btn.setEnabled(True)
        return True

    def _use_other_character(self, _idx: int):
        sender = self.sender()
        url = sender.currentData()
        if not url:
            return
        p = config.media_url_to_path(url)
        if p.exists():
            self.source_path = str(p)
            self.src_img.setPixmap(W.pixmap_from_media(url, 236, 236))
            self.src_img.setStyleSheet("border:1px solid rgba(128,128,128,50);border-radius:8px;")
            self._check_source_size(p)

    # ── 换脸 ──
    def _run(self):
        if not self.character["image_url"]:
            QMessageBox.information(self, tr("face_swap"), tr("该角色还没有形象图,请先生成或上传"))
            return
        if not self.source_path:
            QMessageBox.information(self, tr("face_swap"), tr("请先选择源脸照片"))
            return
        healthy, msg = face_swap.health(config_id=self.cfg_id)
        if not healthy:
            QMessageBox.warning(self, tr("face_swap"), msg)
            return
        self.go_btn.setEnabled(False)
        self.status.setText(tr("in_progress") + "…")
        template = str(config.media_url_to_path(self.character["image_url"]))
        src, all_faces, enhance, cfg_id = self.source_path, self.all_faces.isChecked(), self.enhance.isChecked(), self.cfg_id
        eng = self.engine_combo.currentData() or (cfg_id, "local-faceswap")
        engine_id, provider = eng[0], eng[1]

        def job(tid):
            return str(face_swap.swap_one_by_provider(
                src, template, provider=provider, config_id=engine_id,
                swap_all_faces=all_faces, face_enhance=enhance))
        def done(tid, result, error):
            self.go_btn.setEnabled(True)
            if error:
                self.status.setText("❌ " + str(err)[:200])
                return
            self.result_path = result
            self.res_img.setPixmap(W.pixmap_from_media(result, 236, 236))
            self.res_img.setStyleSheet("border:1px solid rgba(128,128,128,50);border-radius:8px;")
            self.apply_btn.setEnabled(True)
            self.status.setText(tr("✅ 完成,可预览后应用"))
        TASKMGR.submit("face_swap", job, done)

    def _batch(self):
        """批量换脸:对该角色全部形象(基础+变体)逐张换脸,单张失败不中断。"""
        if not self.source_path:
            QMessageBox.information(self, tr("face_swap"), tr("请先选择源脸照片"))
            return
        ok_, msg = face_swap.health(config_id=self.cfg_id)
        if not ok_:
            QMessageBox.warning(self, tr("face_swap"), msg)
            return
        items = self._load_char_images()
        if not items:
            QMessageBox.information(self, tr("face_swap"), tr("该角色还没有形象图"))
            return
        self._batch_running = True
        self.batch_btn.setEnabled(False)
        all_faces, enhance, cfg_id = self.all_faces.isChecked(), self.enhance.isChecked(), self.cfg_id
        eng = self.engine_combo.currentData() or (self.cfg_id, "local-faceswap")
        engine_id, provider = eng[0], eng[1]
        src = self.source_path

        def job(tid):
            out = {}
            for label, _url, local in items:
                try:
                    p = face_swap.swap_one_by_provider(
                        src, local, provider=provider, config_id=engine_id,
                        swap_all_faces=all_faces, face_enhance=enhance)
                    out[label] = str(p)
                except Exception:  # noqa: BLE001
                    out[label] = ""
            return out

        def done(tid, result, error):
            self._batch_running = False
            self.batch_btn.setEnabled(True)
            if error:
                QMessageBox.warning(self, tr("face_swap"), str(error)[:400])
                return
            self.results = result or {}
            okn = sum(1 for v in self.results.values() if v)
            first = next((v for v in self.results.values() if v), None)
            if first:
                self.result_path = first
                self.res_img.setPixmap(W.pixmap_from_media(first, 236, 236))
            self.download_btn.setEnabled(okn > 0)
            self.status.setText(f"✅ 完成 {okn}/{len(self.results)} 张")

        from ..core.taskmgr import TASKMGR
        TASKMGR.submit("face_swap_batch", job, done)

    def _download_all(self):
        from ..core import download as dl_mod
        n = 0
        for label, p in (self.results or {}).items():
            if not p:
                continue
            try:
                dl_mod.download_media("/static/" + p.split("static/")[-1].replace("\\", "/"),
                                      f"{self.character['name']}_{label}.png")
                n += 1
            except Exception:  # noqa: BLE001
                continue
        ok(f"已下载 {n} 张结果")

    def _apply(self):
        if not self.result_path:
            return
        db.ex("UPDATE characters SET image_url=?, updated_at=? WHERE id=?",
              (config.path_to_media_url(self.result_path), db.now(), self.character["id"]))
        self.accept()
