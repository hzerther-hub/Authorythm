# -*- coding: utf-8 -*-
"""文本框 AI 智能修改(对齐原版 Ctrl/Cmd+L):

- 选中若干行 → 改写选中片段(selection)
- 未选中 → 在光标位置插入新内容(insert)
- 勾选「整章处理」→ 输出修改后的完整正文(chapter)
上下文拼接与输出规则逐条对齐原版 runAiEdit。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from . import widgets as W
from .toast import err, ok

RULES = {
    "selection": "只输出修改后的片段文本(不要输出整章,不要解释)。",
    "insert": "只输出要插入的新内容(不要重复原文,不要解释)。",
    "chapter": "输出修改后的完整章节全文(未涉及的部分保持原样,不要解释)。",
}


class AiEditDialog(QDialog):
    """AI 修改浮层:指令输入 + 整章处理勾选 + 选中片段预览。"""

    def __init__(self, parent, editor: QPlainTextEdit, mode: str,
                 start: int, end: int, on_result, episode_id: int = 0):
        super().__init__(parent)
        self.editor = editor
        self.episode_id = episode_id
        self.mode = mode
        self.start, self.end = start, end
        self._on_result = on_result
        self.setWindowTitle(tr("✨ AI 修改"))
        self.resize(620, 420)
        root = QVBoxLayout(self)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(W.h2(tr("✨ AI 修改")))
        head.addStretch(1)
        mode_label = {"selection": f"改写选中片段({end - start} 字)",
                      "insert": "在光标位置插入", "chapter": tr("整章处理")}[mode]
        head.addWidget(W.tag(mode_label))
        root.addLayout(head)

        if mode == "selection":
            preview = QPlainTextEdit()
            sel = editor.toPlainText()[start:end]
            preview.setPlainText(sel if len(sel) <= 400 else sel[:400] + "…")
            preview.setReadOnly(True)
            preview.setMaximumHeight(110)
            preview.setStyleSheet("background:rgba(128,128,128,25);")
            root.addWidget(QLabel(tr("选中片段预览")))
            root.addWidget(preview)

        self.instruction = QLineEdit()
        self.instruction.setPlaceholderText(tr("修改要求,如:把开头改得更抓人 / 加强母亲戏份 / 精简重复描写"))
        self.instruction.returnPressed.connect(self._run)
        root.addWidget(self.instruction)

        row = QHBoxLayout()
        self.whole = QCheckBox(tr("整章处理"))
        self.whole.setEnabled(mode != "chapter")
        row.addWidget(self.whole)
        row.addStretch(1)
        self.run_btn = W.primary_btn(tr("应用"))
        self.run_btn.clicked.connect(self._run)
        cancel = QPushButton(tr("取消"))
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addWidget(self.run_btn)
        root.addLayout(row)
        root.addWidget(W.muted(tr("注意:只输出结果文本,不会输出解释或前后缀。")))
        self.instruction.setFocus()


    def _context_parts(self) -> list[str]:
        """上下文:项目设定(总纲/世界观/合约/文风)+ 前三章摘要,保证改写/插入不产生前后矛盾。"""
        from ..core import db
        ctx: list[str] = []
        try:
            ep = db.q1("SELECT * FROM episodes WHERE id=?", (self.episode_id,))
            if not ep:
                return ctx
            d = db.q1("SELECT * FROM dramas WHERE id=?", (ep["drama_id"],))
        except Exception:  # noqa: BLE001
            return ctx
        # 1) 设定
        settings = []
        if d["novel_outline"]:
            settings.append(f"总纲: {d['novel_outline'][:600]}")
        if d["novel_world"]:
            settings.append(f"世界观: {d['novel_world'][:600]}")
        if d["novel_contract"]:
            settings.append(f"故事合约: {d['novel_contract'][:400]}")
        if settings:
            # 这段是喂给模型的提示词,和上面几行一样保持中文,不要跟界面语言联动
            ctx += ["【作品设定(必须严格遵守,不得冲突)】", *settings]
        style = db.get_setting("novel_style", "")
        if style:
            ctx.append(f"【文风要求】{style}")
        # 2) 章节计划(当前章目标/钩子)
        chapters = db.jload(d["novel_chapters"], [])
        plan = next((c for c in chapters if int(c.get("number", 0)) == ep["episode_number"]), {})
        if plan:
            ctx.append(f"【本章计划】第{ep['episode_number']}章 {plan.get('title','')} — "
                       f"目标:{plan.get('goal','')} 事件:{plan.get('events','')} 钩子:{plan.get('cliffhanger','')}")
        # 3) 前三章摘要(含本章之前的全部章节,至多 3 章,每章尾部 600 字)
        prev = db.q("SELECT episode_number, content FROM episodes WHERE drama_id=? AND episode_number<? "
                    "ORDER BY episode_number LIMIT 3", (ep["drama_id"], ep["episode_number"]))
        if prev:
            ctx.append("【前情提要(必须与之一致,不得出现未发生的事)】")
            for r in reversed(prev):
                tail = (r["content"] or "")[-600:]
                ctx.append(f"第{r['episode_number']}章结尾: {tail}")
        ctx.append("【连贯性硬规则】"
                   "1) 不得与作品设定、前情提要冲突;"
                   "2) 不得写出前文未发生的事件;"
                   "3) 人称、时态、称谓、文风与前文保持一致;"
                   "4) 不得输出与要求无关的额外内容。")
        return ctx

    def _run(self):
        instruction = self.instruction.text().strip()
        if not instruction:
            self.instruction.setFocus()
            return
        chapter = self.editor.toPlainText()
        mode = "chapter" if self.whole.isChecked() else self.mode
        sel = chapter[self.start:self.end]
        parts = self._context_parts() + ["以下是小说本章全文:", "【全文开始】", chapter, "【全文结束】"]
        if mode == "selection":
            parts.append(f"【选中片段】\n{sel}")
        elif mode == "insert":
            parts.append(f"【光标位置前文】\n{chapter[max(0, self.start - 120):self.start]}")
        parts.append(f"【修改要求】{instruction}", RULES[mode],
                     "注意:只输出结果文本,绝对不要输出解释或前后缀。")
        prompt = "\n".join(parts)
        self.run_btn.setEnabled(False)
        self.run_btn.setText(tr("处理中…"))

        def job(tid):
            from ..agents import runner
            return runner.run_agent("novel_editor", prompt)

        def done(tid, result, e):
            self.run_btn.setEnabled(True)
            self.run_btn.setText(tr("应用"))
            if e:
                err(e)
                return
            text = (result or "").strip()
            if not text:
                err(tr("AI 未返回内容"))
                return
            if mode == "chapter":
                new_text = text
            elif mode == "selection":
                new_text = chapter[:self.start] + text + chapter[self.end:]
            else:
                pos = min(self.start, len(chapter))
                before, after = chapter[:pos], chapter[pos:]
                new_text = (f"{before}"
                            f"{'\n\n' if pos > 0 and not before.endswith(chr(10)) else ''}"
                            f"{text}"
                            f"{'\n\n' if pos < len(chapter) and not after.startswith(chr(10)) else ''}"
                            f"{after}")
            self._on_result(new_text, self.start, self.end)
            ok(tr("AI 修改已应用"))
            self.accept()

        TASKMGR.submit("novel_edit", job, done)


def install_ai_edit_shortcut(editor: QPlainTextEdit, get_cb):
    """给 QPlainTextEdit 装 Ctrl/Cmd+L 快捷键,回调查打开对话框的回调。"""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut

    def _on_activated():
        get_cb(editor)

    sc = QShortcut(QKeySequence("Ctrl+L"), editor)
    sc.activated.connect(_on_activated)
    sc2 = QShortcut(QKeySequence("Meta+L"), editor)
    sc2.activated.connect(_on_activated)
    editor._ai_edit_shortcuts = (sc, sc2)  # 保持引用
