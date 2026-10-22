# -*- coding: utf-8 -*-
"""「海外题材改写」弹窗。

把中文原文改成目标平台(GoodNovel / Dreame / Webnovel)的英文短篇网文,
四步都在这个弹窗里看得见:**诊断 → 术语表 → 改写 → 质检**。

三件必须做对的事:
1. **不覆盖中文原稿** —— 改写稿只显示在「改写结果」页,原稿一个字都不动。
2. **术语表可人工编辑** —— 这是防「同一人名前后不一致」的唯一有效手段
   (上下文窗口有限,模型自己记不住 200 万字的人名一致性)。
3. **线程纪律** —— worker 线程里绝不碰 Qt 控件:所有控件值在主线程先快照成
   普通变量再传进 worker;完成回调经 TASKMGR 的 queued 信号回到主线程,
   可以安全更新 UI。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QSplitter,
                               QTabWidget, QTableWidget, QTableWidgetItem,
                               QTextEdit, QVBoxLayout)

from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from ..core.theme import SLATE_FORM_QSS
from . import widgets as W
from .braille import WaitingButton
from .toast import err, info, ok, warn

LEVELS = ("A", "B", "C")


class OverseasDialog(QDialog):
    """海外题材改写。"""

    def __init__(self, parent=None, *, drama_id: int = 0,
                 episode_id: int | None = None,
                 text_config_id: int | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("overseas_dialog_title"))
        self.setStyleSheet(SLATE_FORM_QSS)
        self.resize(1120, 820)
        self._drama_id = drama_id
        self._episode_id = episode_id
        self._config_id = text_config_id
        self._glossary: dict[str, str] = {}
        self._issues: list = []
        self._level = "B"
        self._zh_source = ""

        root = QVBoxLayout(self)

        # ── 头部 ──
        # **不要在这里加自定义关闭按钮**:本对话框走原生标题栏(Windows 自带 X),
        # 头部再加一个 X 就是右上角两个关闭按钮 —— 实测被用户当成「多了一个按钮」。
        head = QHBoxLayout()
        head.addWidget(W.icon_label("globe", 20))
        head.addWidget(W.h2(tr("overseas_dialog_title")))
        head.addStretch(1)
        root.addLayout(head)
        root.addWidget(W.muted(tr("overseas_dialog_desc")))

        # ── 中文原文 ──
        root.addWidget(QLabel(tr("overseas_source")))
        self.source_edit = QPlainTextEdit()
        self.source_edit.setPlaceholderText(tr("overseas_source_ph"))
        self.source_edit.setMinimumHeight(120)
        root.addWidget(self.source_edit)

        # ── 参数行 ──
        row = QHBoxLayout()
        row.setSpacing(10)
        self.use_ep_btn = QPushButton(tr("overseas_use_episode"))
        W.set_icon(self.use_ep_btn, "doc")
        self.use_ep_btn.clicked.connect(self._use_episode)
        row.addWidget(self.use_ep_btn)

        row.addWidget(QLabel(tr("overseas_platform")))
        self.platform_combo = QComboBox()
        self._fill_combo(self.platform_combo, self._platform_items())
        row.addWidget(self.platform_combo)

        row.addWidget(QLabel(tr("overseas_category")))
        self.category_combo = QComboBox()
        self._fill_combo(self.category_combo, self._category_items())
        row.addWidget(self.category_combo)

        row.addWidget(QLabel(tr("overseas_level")))
        self.level_combo = QComboBox()
        for lv in LEVELS:
            self.level_combo.addItem(f"{lv} · {tr('overseas_level_' + lv)}", lv)
        self.level_combo.setCurrentIndex(1)
        row.addWidget(self.level_combo)
        row.addStretch(1)
        root.addLayout(row)

        # ── 操作行 ──
        act = QHBoxLayout()
        self.diag_btn = WaitingButton(tr("overseas_diagnose"))
        W.set_icon(self.diag_btn, "search")
        self.diag_btn.clicked.connect(self._on_diagnose)
        act.addWidget(self.diag_btn)
        self.rw_btn = WaitingButton(tr("overseas_rewrite"), primary=True)
        W.set_icon(self.rw_btn, "globe")
        self.rw_btn.clicked.connect(self._on_rewrite)
        act.addWidget(self.rw_btn)
        self.status_lab = QLabel("")
        self.status_lab.setStyleSheet("color:#8a9099;")
        act.addWidget(self.status_lab)
        act.addStretch(1)
        root.addLayout(act)

        # ── 结果页 ──
        self.tabs = QTabWidget()
        self.diag_view = QTextEdit()
        self.diag_view.setReadOnly(True)
        self.tabs.addTab(self.diag_view, tr("overseas_tab_diag"))

        self.glossary_table = QTableWidget(0, 2)
        self.glossary_table.setHorizontalHeaderLabels(["中文", "English"])
        self.glossary_table.horizontalHeader().setStretchLastSection(True)
        self.glossary_table.verticalHeader().setVisible(False)
        self.glossary_table.setToolTip(tr("overseas_glossary_hint"))
        self.tabs.addTab(self.glossary_table, tr("overseas_tab_glossary"))

        self.zh_view = QTextEdit()
        self.zh_view.setReadOnly(True)
        self.en_view = QTextEdit()
        self.en_view.setReadOnly(True)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.zh_view)
        split.addWidget(self.en_view)
        self.tabs.addTab(split, tr("overseas_tab_result"))

        self.qc_table = QTableWidget(0, 3)
        self.qc_table.setHorizontalHeaderLabels(["规则", "级别", "说明"])
        self.qc_table.horizontalHeader().setStretchLastSection(True)
        self.qc_table.verticalHeader().setVisible(False)
        self.qc_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabs.addTab(self.qc_table, tr("overseas_tab_qc"))
        root.addWidget(self.tabs, 1)

        root.addWidget(W.muted(tr("overseas_rules_note")))

    # ------------------------------------------------------------ 组合框

    @staticmethod
    def _fill_combo(combo: QComboBox, items: list[tuple[str, str]]) -> None:
        for label, data in items:
            combo.addItem(label, data)

    def _platform_items(self) -> list[tuple[str, str]]:
        try:
            from ..pipeline import overseas_rules
            return [(f"{p.get('name', p['id'])}", p["id"])
                    for p in overseas_rules.list_platforms()]
        except Exception:  # noqa: BLE001
            return []

    def _category_items(self) -> list[tuple[str, str]]:
        try:
            from ..pipeline import overseas_rules
            return [(f"{c.get('name_zh') or c.get('name', c['id'])}", c["id"])
                    for c in overseas_rules.list_categories()]
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------ 输入

    def set_source(self, text: str) -> None:
        self.source_edit.setPlainText(text or "")
        self._zh_source = text or ""

    def _use_episode(self) -> None:
        """从库里取本集正文/剧本填进原文框(用户在编辑框里改过的内容不覆盖,
        只在原文框为空时填)。"""
        if self.source_edit.toPlainText().strip():
            info(tr("overseas_source_ph"))
            return
        if not self._episode_id:
            warn(tr("overseas_no_project"))
            return
        from ..core import db
        row = db.q1("SELECT content, script_content FROM episodes WHERE id=?",
                    (self._episode_id,))
        if not row:
            warn(tr("overseas_no_project"))
            return
        text = (row.get("content") or "").strip() or (row.get("script_content") or "").strip()
        if not text:
            warn(tr("overseas_no_source"))
            return
        self.set_source(text)

    # ------------------------------------------------------------ 参数快照

    def _snapshot(self) -> dict:
        """**主线程**里把控件值快照成普通变量 —— worker 线程绝不能碰控件。"""
        return {
            "source": self.source_edit.toPlainText().strip(),
            "platform": self.platform_combo.currentData() or "",
            "category": self.category_combo.currentData() or "",
            "level": self.level_combo.currentData() or "B",
            "config_id": self._config_id,
        }

    # ------------------------------------------------------------ 诊断

    def _on_diagnose(self) -> None:
        from ..pipeline import overseas
        snap = self._snapshot()
        if not snap["source"]:
            warn(tr("overseas_no_source"))
            return
        if not snap["platform"] or not snap["category"]:
            warn(tr("overseas_rules_note"))
            return
        self.diag_btn.busy(tr("overseas_diag_running"))
        self.status_lab.setText(tr("overseas_diag_running"))

        def job(tid):
            return overseas.diagnose(
                source=snap["source"], platform=snap["platform"],
                category=snap["category"], level=snap["level"],
                text_config_id=snap["config_id"])

        def done(tid, result, error):
            self.diag_btn.idle()
            if error:
                self.status_lab.setText("")
                err(f"{tr('overseas_diagnose')}: {str(error)[:200]}")
                return
            res = result or {}
            self._level = res.get("level") or snap["level"]
            self._issues = res.get("issues") or []
            self._glossary = res.get("glossary") or {}
            self._fill_diag(res)
            self._fill_glossary(self._glossary)
            self.tabs.setCurrentIndex(0)
            n = len(self._issues)
            self.status_lab.setText(
                tr("overseas_diag_done").format(level=self._level, n=n))
            ok(tr("overseas_diag_done").format(level=self._level, n=n))

        TASKMGR.submit("overseas_diag", job, done, episode_id=self._episode_id)

    def _fill_diag(self, res: dict) -> None:
        rows = ["<h3>改写级别建议</h3>"]
        rows.append(f"<p><b>{res.get('level', 'B')}</b> — "
                    f"{res.get('level_reason', '')}</p>")
        rows.append("<h3>五维诊断</h3><table cellpadding='4' cellspacing='0' "
                    "border='1' width='100%'>")
        for key, label in (("setting", "设定"), ("structure", "结构"),
                            ("pacing", "节奏"), ("language", "语言"),
                            ("compliance", "合规")):
            item = (res.get("diagnosis") or {}).get(key) or {}
            score = item.get("score", 0)
            rows.append(f"<tr><td width='60'><b>{label}</b></td>"
                        f"<td width='40'>{score}/5</td>"
                        f"<td>{item.get('notes', '')}</td></tr>")
        rows.append("</table>")
        issues = res.get("issues") or []
        if issues:
            rows.append("<h3>问题清单</h3><table cellpadding='4' cellspacing='0' "
                        "border='1' width='100%'>"
                        "<tr><th>类型</th><th>原文</th><th>怎么改</th></tr>")
            for it in issues:
                if not isinstance(it, dict):
                    continue
                rows.append(f"<tr><td>{it.get('type', '')}</td>"
                            f"<td>{it.get('quote', '')}</td>"
                            f"<td>{it.get('fix', '')}</td></tr>")
            rows.append("</table>")
        maps = res.get("culture_mappings") or []
        if maps:
            rows.append("<h3>文化映射</h3><table cellpadding='4' cellspacing='0' "
                        "border='1' width='100%'>"
                        "<tr><th>中式设定</th><th>目标设定</th><th>理由</th></tr>")
            for m in maps:
                if not isinstance(m, dict):
                    continue
                rows.append(f"<tr><td>{m.get('source', '')}</td>"
                            f"<td>{m.get('target', '')}</td>"
                            f"<td>{m.get('note', '')}</td></tr>")
            rows.append("</table>")
        self.diag_view.setHtml("".join(rows))

    def _fill_glossary(self, glossary: dict) -> None:
        self.glossary_table.setRowCount(0)
        for k, v in (glossary or {}).items():
            r = self.glossary_table.rowCount()
            self.glossary_table.insertRow(r)
            self.glossary_table.setItem(r, 0, QTableWidgetItem(str(k)))
            self.glossary_table.setItem(r, 1, QTableWidgetItem(str(v)))

    def _glossary_from_table(self) -> dict:
        out: dict[str, str] = {}
        for r in range(self.glossary_table.rowCount()):
            a = self.glossary_table.item(r, 0)
            b = self.glossary_table.item(r, 1)
            if a and b and a.text().strip() and b.text().strip():
                out[a.text().strip()] = b.text().strip()
        return out

    # ------------------------------------------------------------ 改写

    def _on_rewrite(self) -> None:
        from ..pipeline import overseas
        snap = self._snapshot()
        if not snap["source"]:
            warn(tr("overseas_no_source"))
            return
        glossary = self._glossary_from_table() or self._glossary
        if not glossary:
            warn(tr("overseas_no_glossary"))
            return
        self.rw_btn.busy(tr("overseas_rewrite_running"))
        self.status_lab.setText(tr("overseas_rewrite_running"))

        def job(tid):
            res = overseas.rewrite(
                source=snap["source"], platform=snap["platform"],
                category=snap["category"], level=snap["level"],
                glossary=glossary, issues=self._issues,
                text_config_id=snap["config_id"])
            issues = overseas.check(
                res["content"], platform=snap["platform"],
                category=snap["category"], glossary=glossary)
            res["qc"] = issues
            return res

        def done(tid, result, error):
            self.rw_btn.idle()
            if error:
                self.status_lab.setText("")
                err(f"{tr('overseas_rewrite')}: {str(error)[:200]}")
                return
            res = result or {}
            en = res.get("content") or ""
            self.zh_view.setPlainText(snap["source"])
            self.en_view.setPlainText(en)
            self.tabs.setCurrentIndex(2)
            self._fill_qc(res.get("qc") or [])
            warns = sum(1 for i in (res.get("qc") or [])
                        if getattr(i, "severity", "") == "warn")
            msg = tr("overseas_rewrite_done").format(chapters=1, warns=warns)
            self.status_lab.setText(msg)
            ok(msg)

        TASKMGR.submit("overseas_rewrite", job, done, episode_id=self._episode_id)

    def _fill_qc(self, issues) -> None:
        self.qc_table.setRowCount(0)
        for it in issues:
            r = self.qc_table.rowCount()
            self.qc_table.insertRow(r)
            self.qc_table.setItem(r, 0, QTableWidgetItem(str(getattr(it, "rule", ""))))
            sev = getattr(it, "severity", "")
            self.qc_table.setItem(r, 1, QTableWidgetItem(
                "错误" if sev == "error" else "警告"))
            self.qc_table.setItem(r, 2, QTableWidgetItem(
                str(getattr(it, "message", ""))))
