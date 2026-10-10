# -*- coding: utf-8 -*-
"""整书导入 → 分析 → 仿写 对话框(三段式流水线,依赖先行 + 后台执行)。

段①导入:TXT 选文件 → 三级切章入库(替换本项目既有章节)
段②分析:12 章一组 Map → Reduce 出仿写档案;失败率过高自动暂停
段③仿写:设定 → 总纲 → 分卷 → 建项目(专名全换 / 情节仿而不抄 / 结构保留)

依赖规则:没导入不能分析,没分析不能仿写——未满足时对应按钮置灰并给原因。
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget)

from ..core import db
from ..core.taskmgr import TASKMGR
from . import widgets as W
from .braille import BrailleBar, WaitingButton
from .toast import err, ok


class BookImportDialog(QDialog):
    def __init__(self, parent, drama_id: int):
        super().__init__(parent)
        self.drama_id = drama_id
        d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
        self.setWindowTitle(tr("▤ 导入整本书 · 分析 · 仿写"))
        self.resize(720, 560)
        root = QVBoxLayout(self)

        head = QHBoxLayout()
        head.addWidget(W.h2(f"▤ {d['title']}"))
        head.addStretch(1)
        root.addLayout(head)
        root.addWidget(W.muted(
            tr("导入会替换本项目现有全部章节(旧章节与分镜一并删除)。"
            "分析只读不改;仿写会新建一个项目,原项目不受影响。")))

        # ── 段① 导入 ──
        box1 = QWidget()
        box1.setObjectName("card")
        l1 = QVBoxLayout(box1)
        l1.addWidget(W.h2(tr("① 导入整本书")))
        row1 = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText(tr("选择 .txt 文件(UTF-8 / GBK / GB18030 / Big5 自动识别)"))
        row1.addWidget(self.file_edit, 1)
        pick = W.primary_btn(tr("选择文件"))
        pick.clicked.connect(self._pick)
        row1.addWidget(pick)
        enc = W.muted(tr("编码"))
        row1.addWidget(enc)
        self.enc_combo = QLineEdit("auto")
        self.enc_combo.setFixedWidth(90)
        self.enc_combo.setToolTip(tr("留空或填 auto = 自动判定;也可填 gbk / utf-8 等"))
        row1.addWidget(self.enc_combo)
        l1.addLayout(row1)
        row1b = QHBoxLayout()
        self.import_btn = WaitingButton(tr("▶ 开始导入"))
        self.import_btn.clicked.connect(self._do_import)
        row1b.addWidget(self.import_btn)
        self.import_stat = W.muted("")
        row1b.addWidget(self.import_stat)
        row1b.addStretch(1)
        l1.addLayout(row1b)
        root.addWidget(box1)

        # ── 段② 分析 ──
        box2 = QWidget()
        box2.setObjectName("card")
        l2 = QVBoxLayout(box2)
        l2.addWidget(W.h2(tr("② 结构分析(Map → Reduce)")))
        l2.addWidget(W.muted(
            "每 12 章一组交给文本模型抽取节拍,再汇总成「仿写档案」。"
            "失败率≥30%(且已跑满 50 组)会自动暂停,不基于残缺数据出档案。"))
        row2 = QHBoxLayout()
        self.analyze_btn = WaitingButton(tr("▶ 开始分析"))
        self.analyze_btn.clicked.connect(self._do_analyze)
        row2.addWidget(self.analyze_btn)
        self.analyze_bar = BrailleBar(cells=16)
        row2.addWidget(self.analyze_bar, 1)
        self.analyze_stat = W.muted("")
        row2.addWidget(self.analyze_stat)
        l2.addLayout(row2)
        self.profile_view = QPlainTextEdit()
        self.profile_view.setReadOnly(True)
        self.profile_view.setMaximumHeight(140)
        self.profile_view.setPlaceholderText(tr("分析完成后,仿写档案(题材/结构/角色/冲突线/节奏/文风)显示在这里"))
        l2.addWidget(self.profile_view)
        root.addWidget(box2)

        # ── 段③ 仿写 ──
        box3 = QWidget()
        box3.setObjectName("card")
        l3 = QVBoxLayout(box3)
        l3.addWidget(W.h2(tr("③ 依样仿写(新建项目)")))
        form = QFormLayout()
        self.imit_title = QLineEdit()
        self.imit_title.setPlaceholderText(tr("留空 = 由 AI 依档案起名"))
        form.addRow(tr("新书名"), self.imit_title)
        self.imit_count = QLineEdit()
        self.imit_count.setPlaceholderText(tr("留空 = 由 AI 依档案与节拍时间线决定"))
        form.addRow(tr("计划章数"), self.imit_count)
        l3.addLayout(form)
        l3.addWidget(W.muted(tr("三条铁律:专名全换 · 情节仿而不抄 · 结构与节奏保留")))
        row3 = QHBoxLayout()
        self.imitate_btn = WaitingButton(tr("▶ 开始仿写"))
        self.imitate_btn.clicked.connect(self._do_imitate)
        row3.addWidget(self.imitate_btn)
        self.imitate_stat = W.muted("")
        row3.addWidget(self.imitate_stat)
        row3.addStretch(1)
        l3.addLayout(row3)
        root.addWidget(box3)
        root.addStretch(1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close = W.primary_btn(tr("关闭"))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

        self._refresh_state()

    # ── 状态 ──
    def _analysis(self) -> dict:
        nm = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?",
                            (self.drama_id,))["novel_meta"], {}) or {}
        return nm.get("analysis") or {}

    def _chapter_count(self) -> int:
        return db.q1("SELECT COUNT(*) c FROM episodes WHERE drama_id=?",
                     (self.drama_id,))["c"]

    def _refresh_state(self):
        n = self._chapter_count()
        analysis = self._analysis()
        self.import_stat.setText(f"当前 {n} 章" if n else tr("尚未导入任何章节"))
        prof = analysis.get("profile")
        if prof:
            self.profile_view.setPlainText(json.dumps(prof, ensure_ascii=False, indent=1))
        elif analysis.get("status") == "paused":
            self.profile_view.setPlainText(
                f"(已暂停:失败 {analysis.get('failed')}/{analysis.get('total')} 组,"
                f"成功 {analysis.get('done')} 组。请检查文本模型配置后重跑)")
        # 依赖:导入 → 分析 → 仿写
        self.analyze_btn.setEnabled(bool(n))
        self.analyze_btn.setToolTip("" if n else tr("先导入整本书"))
        self.imitate_btn.setEnabled(bool(prof))
        self.imitate_btn.setToolTip("" if prof else tr("先完成章节分析"))

    # ── 段① ──
    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("选择小说 TXT"), "", tr("文本文件 (*.txt);;所有文件 (*)"))
        if path:
            self.file_edit.setText(path)

    def _do_import(self):
        from ..core.preflight import ensure_ready
        path = self.file_edit.text().strip()
        if not path:
            err(tr("请先选择 TXT 文件"))
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            err(f"读取失败:{exc}")
            return
        enc = self.enc_combo.text().strip()
        if enc.lower() in ("", "auto"):
            enc = ""
        if not ensure_ready("text", None):
            return
        btn = self.import_btn
        btn.busy(tr("切章入库中"))

        def job(tid):
            from ..pipeline import book_import
            return book_import.import_book(self.drama_id, data=data, encoding=enc)

        def done(tid, result, error):
            btn.idle()
            if error:
                err(error)
                return
            ok(f"已导入 {result['chapters']} 章,共 {result['total_chars']} 字")
            self._refresh_state()

        TASKMGR.submit("prompt", job, done, drama_id=self.drama_id)

    # ── 段② ──
    def _do_analyze(self):
        from ..core.preflight import ensure_ready
        if not ensure_ready("text", None):
            return
        btn = self.analyze_btn
        btn.busy(tr("分析中"))
        self.analyze_bar.start()
        self.analyze_stat.setText("…")

        def job(tid):
            from ..core import taskmgr
            from ..pipeline import book_import
            return book_import.run_analysis(
                self.drama_id,
                on_progress=lambda done_n, total, label: taskmgr.set_stage(
                    tid, f"{label} · {done_n}/{total} 组"))

        def done(tid, result, error):
            btn.idle()
            self.analyze_bar.stop()
            self.analyze_stat.setText("")
            if error:
                err(error)
                self._refresh_state()
                return
            if result.get("status") == "paused":
                err(f"分析已暂停:成功 {result['done']}/{result['total']} 组,"
                    f"失败 {result['failed']} 组(失败率过高)")
            else:
                ok(f"分析完成:{result['chapters']} 章已归为仿写档案")
            self._refresh_state()

        TASKMGR.submit("prompt", job, done, drama_id=self.drama_id)

    # ── 段③ ──
    def _do_imitate(self):
        from ..core.preflight import ensure_ready
        if not ensure_ready("text", None):
            return
        title = self.imit_title.text().strip()
        count = self.imit_count.text().strip()
        btn = self.imitate_btn
        btn.busy(tr("四阶段生成中"))

        def job(tid):
            from ..core import db as _db
            from ..core import taskmgr
            from ..pipeline import book_import
            out = book_import.run_imitation(
                self.drama_id, title=title,
                on_progress=lambda msg: taskmgr.set_stage(tid, msg))
            if count.isdigit() and int(count) > 0:
                n = max(1, min(999, int(count)))
                meta = _db.jload(_db.q1("SELECT novel_meta FROM dramas WHERE id=?",
                                        (out["drama_id"],))["novel_meta"], {}) or {}
                meta["chapter_count"] = n
                _db.ex("UPDATE dramas SET total_episodes=?, novel_meta=?, updated_at=? WHERE id=?",
                       (n, json.dumps(meta, ensure_ascii=False), _db.now(), out["drama_id"]))
                out["planned_chapters"] = n
            return out

        def done(tid, result, error):
            btn.idle()
            if error:
                err(error)
                return
            ok(f"新书已创建:《{result['title']}》· {result['characters']} 个角色"
               f" · 计划 {result['planned_chapters']} 章")

        TASKMGR.submit("prompt", job, done, drama_id=self.drama_id)