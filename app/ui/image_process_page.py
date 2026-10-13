# -*- coding: utf-8 -*-
"""图片处理(AI 改图)页:选素材 → 输入指令 → 批量出图到输出目录。

与 ImageEditDialog 的分工:那个是**手动编辑器**(裁剪/调色/滤镜/水印/去背景,
全是 PIL 确定性操作);这里是**指令驱动**的 AI 改图 —— 「去掉图片上的人物」
「把图里的中文换成英文」这类语义修改,走图生图(原图作参考图 + 指令作提示词)。

素材来源支持三种:本地多选图片、本地目录(递归扫描)、远程图片 URL。
处理结果全部落到输出目录,不覆盖原图。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..ai import image_client
from ..ai import registry
from ..core import config
from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from . import episode_cards as C
from . import widgets as W
from .toast import err, ok

IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


class ImageProcessPage(QWidget):
    """AI 改图工作台。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sources: list[str] = []          # 本地路径 / 远程 URL 混合
        self._busy = False
        self._build()
        self._reload_models()
        self._reset_output_dir()

    # ── 界面 ──
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(10)

        # 顶部:标题 + 文本模型 / 图像模型(对齐剧集页顶栏的写法)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = W.h2(tr("image_process"))
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(QLabel(tr("text_svc") + ":"))
        self.text_model = self._mk_combo()
        top.addWidget(self.text_model)
        top.addWidget(QLabel(tr("image_svc") + ":"))
        self.image_model = self._mk_combo()
        top.addWidget(self.image_model)
        root.addLayout(top)

        # 来源
        src_card = W.make_card()
        sl = QVBoxLayout(src_card)
        sl.setContentsMargins(12, 10, 12, 10)
        sl.setSpacing(8)
        sl.addWidget(self._section(tr("source_images")))
        row = QHBoxLayout()
        row.setSpacing(6)
        b1 = QPushButton(tr("pick_local_images"))
        b1.clicked.connect(self._pick_files)
        b2 = QPushButton(tr("pick_local_dir"))
        b2.clicked.connect(self._pick_dir)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        self.clear_btn = QPushButton(tr("clear_all"))
        self.clear_btn.clicked.connect(self._clear)
        row.addWidget(self.clear_btn)
        sl.addLayout(row)

        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(tr("remote_url_hint"))
        self.url_edit.returnPressed.connect(self._add_url)
        url_add = QPushButton(tr("add"))
        url_add.clicked.connect(self._add_url)
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(url_add)
        sl.addLayout(url_row)

        self.src_host = QWidget()
        self.src_lay = QVBoxLayout(self.src_host)
        self.src_lay.setContentsMargins(0, 0, 0, 0)
        self.src_lay.setSpacing(4)
        src_scroll = QScrollArea()
        src_scroll.setWidgetResizable(True)
        src_scroll.setFrameShape(QFrame.NoFrame)
        src_scroll.setFixedHeight(150)
        src_scroll.setWidget(self.src_host)
        sl.addWidget(src_scroll)
        self.src_empty = W.muted(tr("no_source"))
        self.src_lay.addWidget(self.src_empty)
        root.addWidget(src_card)

        # 指令 + 输出目录(底部)
        foot_card = W.make_card()
        fl = QVBoxLayout(foot_card)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(8)

        out_row = QHBoxLayout()
        out_row.setSpacing(6)
        out_row.addWidget(QLabel(tr("output_dir")))
        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(True)
        out_row.addWidget(self.out_edit, 1)
        b_out = QPushButton(tr("choose"))
        b_out.clicked.connect(self._pick_out_dir)
        b_open = QPushButton(tr("open_dir"))
        b_open.clicked.connect(self._open_out_dir)
        out_row.addWidget(b_out)
        out_row.addWidget(b_open)
        fl.addLayout(out_row)

        self.instr = QPlainTextEdit()
        self.instr.setPlaceholderText(tr("image_instr_hint"))
        self.instr.setFixedHeight(88)
        fl.addWidget(self.instr)

        act = QHBoxLayout()
        self.status_lab = W.muted("")
        act.addWidget(self.status_lab, 1)
        self.run_btn = W.primary_btn(tr("start_process"))
        self.run_btn.clicked.connect(self._run)
        act.addWidget(self.run_btn)
        fl.addLayout(act)
        root.addWidget(foot_card)

    @staticmethod
    def _section(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("inspectorLabel")
        return lab

    @staticmethod
    def _mk_combo() -> QComboBox:
        c = QComboBox()
        c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        c.setMinimumWidth(90)
        c.setMaximumWidth(260)
        return c

    # ── 数据 ──
    def _reload_models(self):
        for combo, stype in ((self.text_model, "text"), (self.image_model, "image")):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr("configured"), None)
            for r in registry.list_configs(stype):
                combo.addItem((r["model"] or "").split("/")[-1] or r["model"], r["id"])
            combo.blockSignals(False)

    def _reset_output_dir(self):
        d = config.STATIC_DIR / "processed"
        d.mkdir(parents=True, exist_ok=True)
        self.out_edit.setText(str(d))

    # ── 来源操作 ──
    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("pick_local_images"), "",
            f"Images ({' '.join('*' + e for e in IMG_EXTS)})")
        self._add_paths(paths)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("pick_local_dir"))
        if not d:
            return
        found = [str(p) for p in sorted(Path(d).rglob("*"))
                 if p.suffix.lower() in IMG_EXTS]
        if not found:
            warn_or = tr("dir_no_images")
            self.status_lab.setText(warn_or)
            return
        self._add_paths(found)

    def _add_url(self):
        u = self.url_edit.text().strip()
        if not u:
            return
        if not u.startswith(("http://", "https://")):
            err(tr("url_invalid"))
            return
        if u not in self._sources:
            self._sources.append(u)
        self.url_edit.clear()
        self._render_sources()

    def _add_paths(self, paths):
        for p in paths:
            if p and p not in self._sources:
                self._sources.append(p)
        self._render_sources()

    def _clear(self):
        self._sources.clear()
        self._render_sources()

    def _render_sources(self):
        while self.src_lay.count():
            it = self.src_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        if not self._sources:
            self.src_lay.addWidget(W.muted(tr("no_source")))
            return
        for i, s in enumerate(self._sources[:200]):
            row = QFrame()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 3, 6, 3)
            rl.setSpacing(8)
            thumb = QLabel()
            thumb.setFixedSize(40, 30)
            thumb.setAlignment(Qt.AlignCenter)
            if not str(s).startswith("http"):
                thumb.setPixmap(W.pixmap_from_media(s, 40, 30))
            else:
                thumb.setText("🌐")
            rl.addWidget(thumb)
            name = QLabel(Path(str(s)).name if not str(s).startswith("http") else str(s))
            name.setObjectName("muted")
            name.setToolTip(str(s))
            rl.addWidget(name, 1)
            rm = QPushButton("✕")
            rm.setObjectName("slateIconBtn")
            rm.setFixedSize(24, 24)
            rm.setCursor(Qt.PointingHandCursor)
            rm.clicked.connect(lambda _=False, x=str(s): self._remove_one(x))
            rl.addWidget(rm)
            self.src_lay.addWidget(row)
        if len(self._sources) > 200:
            self.src_lay.addWidget(W.muted(tr("sources_truncated", 200, len(self._sources))))

    def _remove_one(self, path: str):
        if path in self._sources:
            self._sources.remove(path)
        self._render_sources()

    def _pick_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("output_dir"), self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def _open_out_dir(self):
        import os
        d = self.out_edit.text().strip()
        if d and Path(d).is_dir():
            os.startfile(d)  # noqa: Windows 默认资源管理器

    # ── 执行 ──
    def _run(self):
        if self._busy:
            return
        if not self._sources:
            err(tr("no_source"))
            return
        instr = self.instr.toPlainText().strip()
        if not instr:
            err(tr("instr_required"))
            return
        out_dir = Path(self.out_edit.text().strip())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            err(str(e)[:160])
            return

        self._busy = True
        self.run_btn.busy(tr("in_progress"))
        srcs = list(self._sources)
        cfg = self.image_model.currentData()
        total = len(srcs)

        def job(tid):
            done_n = 0
            outs: list[str] = []
            fails: list[str] = []
            for i, s in enumerate(srcs):
                if i:
                    time.sleep(1)      # 串行 + 间隔,避免撞上游限流
                TASKMGR.set_stage(tid, f"{i + 1}/{total}")
                try:
                    outs.append(self._process_one(s, instr, out_dir, cfg))
                    done_n += 1
                except Exception as exc:  # noqa: BLE001
                    fails.append(f"{Path(str(s)).name}: {str(exc)[:60]}")
            return {"done": done_n, "total": total, "out_dir": str(out_dir), "fails": fails}

        def done(tid, result, error):
            self._busy = False
            self.run_btn.idle()
            self.status_lab.setText("")
            if error:
                err(str(error)[:220])
                return
            r = result or {}
            ok(tr("process_done").format(r.get("done", 0), r.get("total", 0)))
            if r.get("fails"):
                self.status_lab.setText(" | ".join(r["fails"][:3]))

        TASKMGR.submit("image", job, done, detail=tr("image_process"))

    @staticmethod
    def _process_one(src: str, instr: str, out_dir: Path, cfg_id) -> str:
        """按指令改一张图,落到 out_dir;返回输出路径。"""
        # 远程图先下载到临时文件,图生图只吃本地路径
        local = src
        tmp = None
        if str(src).startswith(("http://", "https://")):
            import tempfile
            import requests
            resp = requests.get(src, timeout=60)
            resp.raise_for_status()
            fd, tmp = tempfile.mkstemp(suffix=".img")
            with open(fd, "wb") as f:
                f.write(resp.content)
            local = tmp
        try:
            refs = [local] if local else []
            stem = Path(str(src)).stem or "image"
            out_name = f"{stem}_ai.png"
            out, _p = image_client.generate_image(
                instr, out_name=out_name, config_id=cfg_id,
                reference_images=refs, people=1)
            dest = out_dir / Path(out).name
            Path(out).replace(dest) if Path(out).exists() and dest != Path(out) else None
            if not dest.exists():
                dest = out_dir / out_name
                Path(out).replace(dest)
            return str(dest)
        finally:
            if tmp and Path(tmp).exists():
                Path(tmp).unlink(missing_ok=True)