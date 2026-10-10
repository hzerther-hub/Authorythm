# -*- coding: utf-8 -*-
"""无损视频合并工具页(独立菜单,对齐 easymerger 主界面):

导入文件/文件夹 → 检测参数(分辨率/编码/帧率/Profile/采样率) → 结论
→ 一键对齐异类(只转那几个) → 无损合并(-c copy)/智能直通 → 输出。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHeaderView, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import config
from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from ..pipeline import merge as M

PARAM_COLS = ["name", "resolution", "codec", "profile", "fps", "sample_rate"]


class MergerToolPage(QWidget):
    def __init__(self):
        super().__init__()
        self.files: list[str] = []
        self.result: M.AnalyzeResult | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        root.addWidget(W_h1())
        root.addWidget(W_muted())

        bar = QHBoxLayout()
        import_files = QPushButton("▦ " + tr("import_files"))
        import_files.clicked.connect(self._import_files)
        import_folder = QPushButton("📂 " + tr("import_folder"))
        import_folder.clicked.connect(self._import_folder)
        detect_btn = QPushButton("◇ " + tr("detect"))
        detect_btn.clicked.connect(self._detect)
        align_btn = QPushButton(tr("align_outliers"))
        align_btn.setObjectName("primary")
        align_btn.clicked.connect(self._align)
        merge_btn = QPushButton("▶ " + tr("merge_now"))
        merge_btn.setObjectName("primary")
        merge_btn.clicked.connect(self._merge)
        self.out_btn = QPushButton(tr("output_file") + ": " + tr("choose"))
        self.out_btn.clicked.connect(self._pick_out)
        bar.addWidget(import_files)
        bar.addWidget(import_folder)
        bar.addWidget(detect_btn)
        bar.addWidget(align_btn)
        bar.addWidget(merge_btn)
        bar.addStretch(1)
        bar.addWidget(self.out_btn)
        root.addLayout(bar)

        self.verdict = QLabel("—")
        self.verdict.setWordWrap(True)
        self.verdict.setStyleSheet("font-weight:700; padding:6px;")
        root.addWidget(self.verdict)

        self.table = QTableWidget(0, len(PARAM_COLS))
        self.table.setHorizontalHeaderLabels([tr("resolution") if c == "resolution" else
                                              tr("codec") if c == "codec" else
                                              tr("profile") if c == "profile" else
                                              tr("fps") if c == "fps" else
                                              tr("sample_rate") if c == "sample_rate" else tr("文件")
                                              for c in PARAM_COLS])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table, 1)
        self._out: Path | None = None
        self.hint = QLabel(tr("import_files") + " / " + tr("import_folder") + " → " + tr("detect"))
        self.hint.setObjectName("muted")
        root.addWidget(self.hint)

    def _import_files(self):
        ps, _ = QFileDialog.getOpenFileNames(self, tr("import_files"), "", "Videos (*.mp4 *.mov *.mkv *.webm *.ts *.avi)")
        if ps:
            self.files = ps
            self._after_import()

    def _import_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("import_folder"))
        if d:
            exts = {".mp4", ".mov", ".mkv", ".webm", ".ts", ".avi"}
            self.files = sorted(str(p) for p in Path(d).iterdir() if p.suffix.lower() in exts)
            self._after_import()

    def _after_import(self):
        self.result = None
        self.verdict.setText(f"{len(self.files)} files")
        self.table.setRowCount(len(self.files))
        for i, f in enumerate(self.files):
            self.table.setItem(i, 0, QTableWidgetItem(Path(f).name))
        # 后台检测
        def job(tid):
            return M.analyze(self.files)
        def done(tid, result, error):
            if err:
                err(tr("detect"))
                return
            self.result = result
            self._render()
        TASKMGR.submit("merge_detect", job, done)

    def _render(self):
        r = self.result
        if not r:
            return
        self.table.setRowCount(len(r.files))
        for i, f in enumerate(r.files):
            outlier = f["path"] in r.outliers
            vals = [f["name"], f"{f['width']}x{f['height']}", str(f["vcodec"] or "-"),
                    str(f["vprofile"] or "-"), str(f["fps"] or "-"), str(f["sample_rate"] or "-")]
            for j, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if outlier:
                    item.setForeground(Qt.red)
                    item.setToolTip("outlier")
                self.table.setItem(i, j, item)
        self.verdict.setText(("✅ " if r.can_lossless else "⚠️ ") + r.summary())

    def _detect(self):
        if not self.files:
            self._import_files()
        else:
            self._after_import()

    def _pick_out(self):
        p, _ = QFileDialog.getSaveFileName(self, tr("output_file"), "merged.mp4", "MP4 (*.mp4)")
        if p:
            self._out = Path(p)
            self.out_btn.setText(tr("output_file") + ": " + self._out.name)

    def _align(self):
        if not self.result or not self.result.need_align:
            QMessageBox.information(self, tr("align_outliers"), tr("lossless_ok"))
            return
        r = self.result
        def job(tid):
            files = M.align_outliers(r)
            return M.analyze(files)
        def done(tid, result, error):
            if err:
                err(tr("align_outliers"))
                return
            self.result = result
            self.files = [f["path"] for f in result.files]
            self._render()
        TASKMGR.submit("merge_align", job, done)

    def _merge(self):
        if not self.files:
            QMessageBox.information(self, tr("merge_now"), tr("import_files"))
            return
        out = self._out or (config.STATIC_DIR / "merged" / f"tool_{Path(self.files[0]).stem}_{_uid()}.mp4")
        def job(tid):
            path, channel = M.auto_merge(self.files, out)
            return f"{channel} → {path}"
        def done(tid, result, error):
            if err:
                err(tr("merge_now"))
            else:
                import os
                self.verdict.setText("✅ " + tr("merge_done", str(result)))
                os.startfile(str(out.parent))  # noqa 打开输出目录
        TASKMGR.submit("merge", job, done)


def _uid() -> str:
    import uuid
    return uuid.uuid4().hex[:6]


def W_h1() -> QLabel:
    from . import widgets as W
    return W.h1("▷ " + tr("merger_title"))


def W_muted() -> QLabel:
    from . import widgets as W
    return W.muted(tr("merger_intro"))
