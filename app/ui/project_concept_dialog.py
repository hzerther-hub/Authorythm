# -*- coding: utf-8 -*-
"""「项目说明」弹窗:写一句想法 → AI 生成 项目名称/简介/创意描述/题材 → 确认后写回新建表单。

对齐 Web 版(xiaoshuo)新建项目里的「项目说明」那一层:
  - 想法 textarea(打开时预填当前项目名称)+ 可选参考图(每张带一条自己的要求);
  - 点「生成」在后台线程跑 LLM,期间按钮转圈,主线程不卡;
  - 生成结果在弹窗内**可以直接改**,点「应用到项目」才写回新建对话框;
  - 同款复刻(video_clone)不给这个入口 —— 题材来自参考视频拆解,凭空生成会和视频打架。

**线程纪律**(见 AGENTS.md「线程模型」):worker 线程里绝不碰 Qt 控件 ——
所有控件值在主线程先快照成普通变量再传进 worker;完成回调经 TASKMGR 的
queued 信号回到主线程,可以安全更新 UI。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from ..core.theme import SLATE_FORM_QSS
from . import widgets as W
from .braille import WaitingButton
from .toast import err, info, ok

# 参考图上限(对齐 Web 版 CONCEPT_REF_MAX)
REF_MAX = 12


class ProjectConceptDialog(QDialog):
    """项目说明生成器。result_data() 返回 title/description/creative_description/genre。"""

    def __init__(self, parent=None, *, work_type: str = "drama",
                 title: str = "", idea: str = "", config_id: int | None = None,
                 lang: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("concept_dialog_title"))
        self.setStyleSheet(SLATE_FORM_QSS)
        self.resize(620, 720)
        self._work_type = work_type
        self._config_id = config_id
        self._lang = lang
        self._refs: list[dict] = []          # [{path, note}]
        self._has_result = False

        root = QVBoxLayout(self)

        # ── 头部 ──
        head = QHBoxLayout()
        head.addWidget(W.icon_label("magic", 20))
        head.addWidget(W.h2(tr("concept_dialog_title")))
        head.addStretch(1)
        close_btn = W.svg_icon_btn("close", tr("close"), 24)
        close_btn.clicked.connect(self.reject)
        head.addWidget(close_btn)
        root.addLayout(head)
        root.addWidget(W.muted(tr("concept_dialog_desc")))

        # ── 想法 + 参考图 ──
        idea_head = QHBoxLayout()
        idea_head.addWidget(W.muted(tr("concept_idea")))
        idea_head.addStretch(1)
        self.add_img_btn = W.slate_button(tr("concept_add_image"))
        W.set_icon(self.add_img_btn, "image", tr("concept_add_image"), 14)
        self.add_img_btn.clicked.connect(self._pick_refs)
        idea_head.addWidget(self.add_img_btn)
        root.addLayout(idea_head)

        self.idea_edit = QPlainTextEdit()
        self.idea_edit.setPlaceholderText(tr("concept_idea_ph"))
        self.idea_edit.setMaximumHeight(96)
        # idea 优先:项目设置里从「现有名称/简介/创意描述」拼一段上下文预填,
        # 让 AI 知道这个项目已经长什么样,而不是从零另起炉灶。
        self.idea_edit.setPlainText(idea or title or "")
        root.addWidget(self.idea_edit)
        root.addWidget(W.muted(tr("concept_idea_hint")))

        self.ref_box = QWidget()
        self.ref_layout = QVBoxLayout(self.ref_box)
        self.ref_layout.setContentsMargins(0, 6, 0, 0)
        self.ref_layout.setSpacing(4)
        self.ref_box.setVisible(False)
        root.addWidget(self.ref_box)

        # ── 生成结果(可改)──
        self.result_box = QWidget()
        rl = QVBoxLayout(self.result_box)
        rl.setContentsMargins(0, 8, 0, 0)
        rl.setSpacing(6)
        rl.addWidget(W.muted(tr("concept_result_title")))

        self.res_name = QLineEdit()
        self.res_name.setPlaceholderText(tr("concept_result_name_ph"))
        rl.addWidget(self.res_name)
        rl.addWidget(W.muted(tr("concept_result_desc")))
        self.res_desc = QPlainTextEdit()
        self.res_desc.setMaximumHeight(72)
        rl.addWidget(self.res_desc)
        rl.addWidget(W.muted(tr("concept_result_creative")))
        self.res_creative = QPlainTextEdit()
        self.res_creative.setMaximumHeight(96)
        rl.addWidget(self.res_creative)
        rl.addWidget(W.muted(tr("concept_result_genre")))
        self.res_genre = QLineEdit()
        self.res_genre.setPlaceholderText(tr("concept_result_genre_ph"))
        rl.addWidget(self.res_genre)
        self.result_box.setVisible(False)
        root.addWidget(self.result_box)

        root.addStretch(1)

        # ── 底部按钮 ──
        foot = QHBoxLayout()
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        self.gen_btn = WaitingButton(W.strip_emoji(tr("concept_generate")))
        W.set_icon(self.gen_btn, "magic", tr("concept_generate"), 14)
        self.gen_btn.clicked.connect(self._generate)
        self.apply_btn = W.primary_btn(tr("concept_apply"))
        self.apply_btn.clicked.connect(self._apply)
        self.apply_btn.setVisible(False)
        foot.addStretch(1)
        foot.addWidget(cancel)
        foot.addWidget(self.gen_btn)
        foot.addWidget(self.apply_btn)
        root.addLayout(foot)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)

    # ── 参考图 ──
    def _pick_refs(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("选择参考图"), "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not paths:
            return
        room = REF_MAX - len(self._refs)
        if room <= 0:
            info(tr("concept_ref_limit").format(n=REF_MAX))
            return
        picked = paths[:room]
        if len(paths) > room:
            info(tr("concept_ref_limit").format(n=REF_MAX))
        for p in picked:
            self._refs.append({"path": p, "note": ""})
        self._rebuild_refs()

    def _rebuild_refs(self):
        while self.ref_layout.count():
            it = self.ref_layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        if not self._refs:
            self.ref_box.setVisible(False)
            return
        self.ref_box.setVisible(True)
        self.ref_layout.addWidget(W.muted(tr("concept_ref_images")))
        for i, ref in enumerate(self._refs):
            row = QHBoxLayout()
            thumb = QLabel()
            pm = QPixmap(ref["path"])
            if not pm.isNull():
                thumb.setPixmap(pm.scaled(56, 56, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
            thumb.setFixedSize(60, 60)
            row.addWidget(thumb)
            note = QLineEdit(ref.get("note") or "")
            note.setPlaceholderText(tr("concept_ref_note_ph").format(n=i + 1))
            note.textChanged.connect(lambda t, k=i: self._refs[k].__setitem__("note", t))
            row.addWidget(note, 1)
            del_btn = W.svg_icon_btn("delete", tr("delete"), 22)
            del_btn.clicked.connect(lambda _=False, k=i: self._remove_ref(k))
            row.addWidget(del_btn)
            holder = QWidget()
            holder.setLayout(row)
            self.ref_layout.addWidget(holder)
        self.ref_layout.addWidget(W.muted(tr("concept_ref_note_hint")))

    def _remove_ref(self, idx: int):
        if 0 <= idx < len(self._refs):
            self._refs.pop(idx)
        self._rebuild_refs()

    # ── 生成 ──
    def _generate(self):
        from ..pipeline import project_concept as pc
        idea = self.idea_edit.toPlainText().strip()
        if not idea:
            info(tr("concept_need_idea"))
            self.idea_edit.setFocus()
            return
        if self._work_type not in pc.CONCEPT_PLAYBOOK:
            err(tr("concept_not_supported"))
            return
        # ── 主线程快照:worker 线程里绝不能碰 Qt 控件 ──
        snap = {
            "work_type": self._work_type,
            "idea": idea,
            "refs": [(r["path"], r.get("note") or "") for r in self._refs],
            "config_id": self._config_id,
            "lang": self._lang,
        }
        self.gen_btn.busy(tr("concept_generating"))
        self.apply_btn.setVisible(False)

        def job(tid):
            return pc.generate_project_concept(
                work_type=snap["work_type"],
                idea=snap["idea"],
                ref_images=[p for p, _ in snap["refs"]],
                ref_notes=[n for _, n in snap["refs"]],
                config_id=snap["config_id"],
                lang=snap["lang"],
            )

        def done(tid, result, error):
            self.gen_btn.idle()
            if error:
                err(str(error))
                return
            data = result or {}
            self.res_name.setText(str(data.get("title") or ""))
            self.res_desc.setPlainText(str(data.get("description") or ""))
            self.res_creative.setPlainText(str(data.get("creative_description") or ""))
            self.res_genre.setText(str(data.get("genre") or ""))
            self._has_result = True
            self.result_box.setVisible(True)
            self.apply_btn.setVisible(True)
            self.gen_btn.setText(tr("concept_regenerate"))
            ok(tr("concept_done"))

        TASKMGR.submit("concept", job, done)

    def _apply(self):
        if not self.res_name.text().strip():
            info(tr("concept_need_title"))
            self.res_name.setFocus()
            return
        self.accept()

    def result_data(self) -> dict:
        return {
            "title": self.res_name.text().strip(),
            "description": self.res_desc.toPlainText().strip(),
            "creative_description": self.res_creative.toPlainText().strip(),
            "genre": self.res_genre.text().strip(),
        }
