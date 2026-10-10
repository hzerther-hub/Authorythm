# -*- coding: utf-8 -*-
"""小说线 UI:策划与设定面板 / 六维审校结果。"""
from __future__ import annotations

import json

from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core import config, db
from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from . import widgets as W
from .braille import WaitingButton
from .toast import err, ok, warn


# 策划板块的生成顺序与前置依赖
# 顺序同参考项目向导:项目设定 → 总纲 → 世界观 → 故事合约 → 分卷战略 → 章节计划 → 主要角色
# (对齐原版 NOVEL_REQUIRED_STEPS = [1,2,3,4,5,7],6 分卷战略为可选但章数多时需要)
PREREQ: dict[str, list[str]] = {
    "outline": [],          # 地基:没有总纲,后面都写不出来
    "world": ["outline"],   # 世界观要在总纲划定的设定边界内展开
    "contract": ["outline", "world"],   # 叙事视角/调性/硬约束要匹配世界观
    "volume": ["outline"],  # 分卷是把总纲切成卷,依赖总纲与计划章数
}
PREREQ_NAME_KEY = {"outline": "总纲", "world": "世界观", "contract": "故事合约", "volume": "分卷战略"}


def prereq_name(key: str) -> str:
    """前置板块名现取 —— 模块级写 tr() 会把语言定死在 import 那一刻。"""
    return tr(PREREQ_NAME_KEY.get(key, key))


def missing_prereq(drama_id: int, key: str) -> list[str]:
    """返回该板块尚未完成的前置板块名。"""
    out = []
    for p in PREREQ.get(key, []):
        row = db.q1(f"SELECT novel_{p} FROM dramas WHERE id=?", (drama_id,))
        if not (row and (row[0] or "").strip()):
            out.append(prereq_name(p))
    return out


class NovelPlanDialog(QDialog):
    """策划与设定:总纲/世界观/合约/卷战略 可查看编辑保存 + 章节计划 + AI 封面。"""

    def __init__(self, parent, drama_id: int):
        super().__init__(parent)
        self.drama_id = drama_id
        d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
        self.setWindowTitle(tr("§ 小说策划与设定"))
        self.resize(760, 620)
        root = QVBoxLayout(self)
        head = QHBoxLayout()
        head.addWidget(W.h2(f"§ {d['title']}"))
        head.addStretch(1)
        cover_btn = QPushButton(tr("◑ AI 生成封面"))
        cover_btn.clicked.connect(self._gen_cover)
        head.addWidget(cover_btn)
        root.addLayout(head)

        meta0 = db.jload(d["metadata"], {}) or {}
        meta_row = QHBoxLayout()
        self.intro_edit = QLineEdit(meta0.get("intro", ""))
        self.intro_edit.setPlaceholderText(tr("项目简介(AI 起草会读取)"))
        self.genre_edit = QLineEdit(meta0.get("genre", ""))
        self.genre_edit.setPlaceholderText(tr("题材"))
        meta_row.addWidget(QLabel(tr("简介")))
        meta_row.addWidget(self.intro_edit, 2)
        meta_row.addWidget(QLabel(tr("题材")))
        meta_row.addWidget(self.genre_edit, 1)
        root.addLayout(meta_row)

        # 全书规模:每章多少字 / 共多少章(AI 生成章节计划与角色时按此执行)
        nm0 = db.jload(d["novel_meta"], {}) or {}
        size_row = QHBoxLayout()
        self.word_spin = QSpinBox()
        self.word_spin.setRange(500, 20000)
        self.word_spin.setSingleStep(100)
        self.word_spin.setValue(int(nm0.get("word_count") or 2500))
        self.chapter_spin = QSpinBox()
        self.chapter_spin.setRange(1, 999)
        self.chapter_spin.setValue(int(nm0.get("chapter_count") or d["total_episodes"] or 60))
        self.word_spin.valueChanged.connect(self._on_size_changed)
        self.chapter_spin.valueChanged.connect(self._on_size_changed)
        size_row.addWidget(QLabel("每章字数"))
        size_row.addWidget(self.word_spin)
        size_row.addSpacing(16)
        size_row.addWidget(QLabel(tr("全书章数")))
        size_row.addWidget(self.chapter_spin)
        size_row.addWidget(W.muted(tr("  · 改这里后,「AI 生成章节计划」按新规模重排;已建的集不变")))
        size_row.addStretch(1)
        root.addLayout(size_row)

        self.cover_lab = QLabel()
        self.cover_lab.setFixedHeight(120)
        self.cover_lab.setAlignment(Qt.AlignCenter)
        self.cover_lab.setPixmap(W.pixmap_from_media(d["thumbnail"], 220, 116))
        root.addWidget(self.cover_lab)

        # 每个设定板块:AI 起草 + 保存(对齐原版 draftNovelSection/saveWizardSection)
        self.edits: dict[str, QPlainTextEdit] = {}
        self.tabs = QTabWidget()
        self._draft_btns: dict[str, WaitingButton] = {}
        self._save_btns: dict[str, QPushButton] = {}
        for i, (key, name) in enumerate((("outline", tr("总纲")), ("world", tr("世界观")),
                                        ("contract", tr("故事合约")), ("volume", tr("分卷战略")))):
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 8, 0, 0)
            row = QHBoxLayout()
            edit = QPlainTextEdit(d[f"novel_{key}"] or "")
            edit.setMinimumHeight(260)
            self.edits[key] = edit
            btn = WaitingButton(tr("✨ AI 起草") + (f"第 {i + 1} 步" if i else ""))
            btn.clicked.connect(lambda _=False, k=key, n=name: self._draft_section(k, n))
            self._draft_btns[key] = btn
            save_btn = QPushButton(tr("保存"))
            save_btn.setToolTip(tr("把当前内容写入项目"))
            save_btn.clicked.connect(lambda _=False, k=key: self._save_section(k))
            self._save_btns[key] = save_btn
            row.addWidget(btn)
            row.addWidget(save_btn)
            row.addStretch(1)
            self._order_lab = self._order_lab if hasattr(self, "_order_lab") else {}
            self._order_lab[key] = W.muted("")
            row.addWidget(self._order_lab[key])
            row.addWidget(W.muted(tr("AI 起草会覆盖当前内容")))
            lay.addLayout(row)
            lay.addWidget(edit, 1)
            self.tabs.addTab(page, name)
        self.tabs.addTab(self._build_plan_tab(d), tr("章节计划"))
        root.addWidget(self.tabs, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        save = W.primary_btn(tr("save"))
        save.clicked.connect(self._save)
        close = QPushButton(tr("close"))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        bottom.addWidget(save)
        root.addLayout(bottom)


    # ── 章节计划 + 主要角色(同一页,各自可 AI 生成)──
    def _build_plan_tab(self, d) -> QWidget:
        from ..pipeline import novel as novel_pipe
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 0)

        row = QHBoxLayout()
        self.chapters_btn = WaitingButton(tr("✨ AI 生成章节计划"))
        self.chapters_btn.clicked.connect(self._ai_chapters)
        self.chars_btn = WaitingButton(tr("✨ AI 生成主要角色"))
        self.chars_btn.clicked.connect(self._ai_characters)
        save_btn = QPushButton(tr("保存本章节与角色"))
        save_btn.clicked.connect(self._save_plan_tab)
        row.addWidget(self.chapters_btn)
        row.addWidget(self.chars_btn)
        row.addWidget(save_btn)
        row.addStretch(1)
        self.plan_stat = W.muted("")
        row.addWidget(self.plan_stat)
        lay.addLayout(row)

        lay.addWidget(W.h2(tr("章节计划")))
        self.chapters_edit = QPlainTextEdit(novel_pipe.chapters_to_text(db.jload(d["novel_chapters"], [])))
        self.chapters_edit.setPlaceholderText(
            "尚未生成章节计划。格式:第1章 标题 | 目标:… | 事件:… | 钩子:…\n"
            "先在上方填好「每章字数 / 全书章数」,再点 AI 生成。")
        self.chapters_edit.setMinimumHeight(200)
        lay.addWidget(self.chapters_edit, 3)

        lay.addWidget(W.h2(tr("主要角色")))
        nm = db.jload(d["novel_meta"], {}) or {}
        self.chars_edit = QPlainTextEdit(
            json.dumps(nm.get("main_characters", []), ensure_ascii=False, indent=1))
        self.chars_edit.setPlaceholderText('尚未生成角色。JSON 数组:[{"name":"","role":"主角",'
                                           '"identity":"","motivation":"","appearance":"","styling":""}]')
        self.chars_edit.setMinimumHeight(140)
        lay.addWidget(self.chars_edit, 2)
        self.chapters_edit.textChanged.connect(self._update_plan_stat)
        self.chars_edit.textChanged.connect(self._update_plan_stat)
        self._update_plan_stat()
        return page

    def _update_plan_stat(self):
        from ..pipeline import novel as novel_pipe
        if not hasattr(self, "plan_stat"):
            return
        chapters = novel_pipe.chapters_from_text(self.chapters_edit.toPlainText())
        chars = 0
        try:
            data = json.loads(self.chars_edit.toPlainText() or "[]")
            chars = len(data) if isinstance(data, list) else 0
        except Exception:  # noqa: BLE001
            chars = -1
        self.plan_stat.setText(f"共 {len(chapters)} 章 · {chars if chars >= 0 else tr('角色 JSON 有误')} 个角色")

    def _on_size_changed(self):
        """规模改动即时落库,保证 AI 任务在后台读到的是用户当前设定。"""
        nm = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?",
                            (self.drama_id,))["novel_meta"], {}) or {}
        nm["word_count"] = self.word_spin.value()
        nm["chapter_count"] = self.chapter_spin.value()
        db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
              (json.dumps(nm, ensure_ascii=False), db.now(), self.drama_id))

    def _ai_chapters(self):
        """AI 生成章节计划:**流式**显示思考与结果,完成才落库。"""
        from ..core.preflight import ensure_ready
        from ..pipeline import novel as novel_pipe
        from .streaming import stream_into
        if not ensure_ready("text", None):
            return
        n, words = self.chapter_spin.value(), self.word_spin.value()
        self._save_project_meta()
        self._on_size_changed()
        btn = self.chapters_btn
        btn.busy(f"生成 {n} 章计划中")
        self.tabs.setCurrentIndex(self.tabs.count() - 1)     # 章节计划页
        editor = self.chapters_edit
        editor.clear()

        def finished(text: str) -> None:
            btn.idle()
            try:
                result = novel_pipe.persist_chapters(self.drama_id, text,
                                                    chapter_count=n, word_count=words)
            except Exception as exc:  # noqa: BLE001
                editor.setPlainText("")
                err(f"章节计划保存失败:{str(exc)[:160]}")
                return
            self._reload_tabs()
            self._update_plan_stat()
            ok(f"章节计划已生成:{result['count']} 章 / 每章约 {result['word_count']} 字")

        def failed(msg: str) -> None:
            btn.idle()
            editor.setPlainText("")
            err(f"章节计划生成失败:{msg[:160]}")

        worker = stream_into(editor, novel_pipe.chapters_prompt(self.drama_id, n, words),
                             # 板块名是提示词路由键(SECTION_SPEC 按中文名匹配),翻了模型就认不出要写哪一块
                             system=novel_pipe._draft_system("章节计划"),
                             config_id=None, temperature=0.4, json_mode=True,
                             on_finished=finished, on_failed=failed, owner=self)
        self._stream_worker = worker

    def _ai_characters(self):
        """角色依赖章节计划:计划缺失时后台先补计划,再生成角色。"""
        from ..core.preflight import ensure_ready
        from ..pipeline import novel as novel_pipe
        if not ensure_ready("text", None):
            return
        d = db.q1("SELECT novel_chapters FROM dramas WHERE id=?", (self.drama_id,))
        need_plan = not (db.jload(d["novel_chapters"], []) if d else [])
        btn = self.chars_btn
        btn.busy(tr("先生成章节计划…") if need_plan else tr("生成角色中"))
        self._save_project_meta()
        self._on_size_changed()

        def job(tid):
            return novel_pipe.plan_characters(self.drama_id)

        def done(tid, result, error):
            btn.idle()
            if error:
                err(error)
                return
            self._reload_tabs()
            ok(f"主要角色已生成:{result['count']} 个(章节计划缺失时已自动补齐)")

        TASKMGR.submit("prompt", job, done, drama_id=self.drama_id)

    def _save_plan_tab(self):
        from ..pipeline import novel as novel_pipe
        try:
            raw = json.loads(self.chars_edit.toPlainText() or "[]")
            if not isinstance(raw, list):
                raise ValueError(tr("主要角色需要是 JSON 数组"))
        except Exception as exc:  # noqa: BLE001
            err(f"主要角色 JSON 有误:{exc}")
            return
        chapters = novel_pipe.chapters_from_text(self.chapters_edit.toPlainText())
        if not chapters and self.chapters_edit.toPlainText().strip():
            err("章节计划无法解析,请按「第N章 标题 | 目标:… | 事件:… | 钩子:…」格式填写")
            return
        novel_pipe.save_chapters(self.drama_id, chapters)
        n_char = novel_pipe.save_characters(self.drama_id, raw)
        self._update_plan_stat()
        ok(f"已保存:{len(chapters)} 章计划 · {n_char} 个角色(角色已同步到资产库)")

    def closeEvent(self, ev):
        """关闭时停掉还在跑的流式线程(QThread 仍在运行时析构会崩)。"""
        w = getattr(self, "_stream_worker", None)
        if w is not None and w.isRunning():
            w.cancel()
            w.wait(3000)
        super().closeEvent(ev)

    def reject(self):
        self.close()

    # ── AI 起草(对齐原版 draftNovelSection)──
    SECTION_CN = {"outline": tr("总纲"), "world": tr("世界观"), "contract": tr("故事合约"), "volume": tr("分卷战略")}
    SECTION_MAP = {"outline": ("novel_outline", "outline"),
                   "world": ("novel_world", "world"),
                   "contract": ("novel_contract", "contract"),
                   "volume": ("novel_volume", "volume")}

    def _draft_section(self, key: str, name: str):
        """AI 起草该板块:**流式**显示 + 直接落库(见 novel.draft_section 的说明)。"""
        from ..core.preflight import ensure_ready
        from ..pipeline import novel as novel_pipe
        from .streaming import stream_into
        if not ensure_ready("text", None):
            return
        miss = missing_prereq(self.drama_id, key)
        if miss:
            warn(f"请先生成「{'、'.join(miss)}」再起草{name}")
            return
        self._save_project_meta()          # 先落库,上下文里才有题材/简介
        btn = self._draft_btns[key]
        btn.busy(f"起草{name}中")
        save_btn = self._save_btns.get(key)
        if save_btn:
            save_btn.setEnabled(False)      # 流式期间禁止保存:框里是思考的半截内容
        cid = self.text_combo.currentData() if hasattr(self, "text_combo") else None
        config_id = int(cid) if cid else None
        editor = self.edits[key]
        self.tabs.setCurrentWidget(editor.parentWidget().parentWidget())
        spec = novel_pipe.SECTION_SPEC[key]
        prompt = novel_pipe.draft_prompt(self.drama_id, key)

        def finished(text: str) -> None:
            btn.idle()
            if save_btn:
                save_btn.setEnabled(True)
            try:
                result = novel_pipe.persist_draft(self.drama_id, key, text)
            except Exception as exc:  # noqa: BLE001
                err(f"{name}保存失败:{str(exc)[:160]}")
                return
            self._reload_tabs()
            self._update_plan_stat()
            ok(f"{name}已生成并保存{result.get('extra', '')}")

        def failed(msg: str) -> None:
            btn.idle()
            if save_btn:
                save_btn.setEnabled(True)
            editor.setPlainText("")     # 别把思考过程留在框里冒充结果
            err(f"{name}起草失败:{msg[:160]}")

        worker = stream_into(editor, prompt, system=novel_pipe._draft_system(spec["name"]),
                             config_id=config_id, temperature=0.6,
                             json_mode=(spec["fmt"] == "json"),
                             on_finished=finished, on_failed=failed, owner=self)
        self._stream_worker = worker          # 持有引用,防被 GC;关闭对话框时 cancel

    def _save_section(self, key: str):
        field, _ = self.SECTION_MAP[key]
        db.ex(f"UPDATE dramas SET {field}=?, updated_at=? WHERE id=?",
              (self.edits[key].toPlainText(), db.now(), self.drama_id))
        ok(f"{self.SECTION_CN[key]}已保存")

    def _save_project_meta(self):
        """保存简介/题材(供 Agent read_novel_context 读取)。"""
        d = db.q1("SELECT metadata FROM dramas WHERE id=?", (self.drama_id,))
        meta = db.jload(d["metadata"], {}) if d else {}
        if self.intro_edit is not None:
            meta["intro"] = self.intro_edit.text().strip()
        if self.genre_edit is not None:
            meta["genre"] = self.genre_edit.text().strip()
        db.ex("UPDATE dramas SET metadata=?, updated_at=? WHERE id=?",
              (json.dumps(meta, ensure_ascii=False), db.now(), self.drama_id))

    def _reload_tabs(self):
        """AI 起草后从库重载各板块 + 章节计划/主要角色。"""
        from ..pipeline import novel as novel_pipe
        d = db.q1("SELECT * FROM dramas WHERE id=?", (self.drama_id,))
        for key, (field, _) in self.SECTION_MAP.items():
            self.edits[key].setPlainText(d[field] or "")
        nm = db.jload(d["novel_meta"], {}) or {}
        if hasattr(self, "chapters_edit"):
            self.chars_edit.blockSignals(True)
            self.chapters_edit.blockSignals(True)
            self.word_spin.blockSignals(True)
            self.chapter_spin.blockSignals(True)
            self.chapters_edit.setPlainText(novel_pipe.chapters_to_text(db.jload(d["novel_chapters"], [])))
            self.chars_edit.setPlainText(
                json.dumps(nm.get("main_characters", []), ensure_ascii=False, indent=1))
            self.word_spin.setValue(int(nm.get("word_count") or 2500))
            self.chapter_spin.setValue(int(nm.get("chapter_count") or d["total_episodes"] or 60))
            self.chars_edit.blockSignals(False)
            self.chapters_edit.blockSignals(False)
            self.word_spin.blockSignals(False)
            self.chapter_spin.blockSignals(False)
            self._update_plan_stat()

    def _save(self):
        from ..pipeline import novel as novel_pipe
        self._save_project_meta()
        novel_pipe.save_plan(self.drama_id,
                             self.edits["outline"].toPlainText(), self.edits["world"].toPlainText(),
                             self.edits["contract"].toPlainText(), self.edits["volume"].toPlainText())
        self.accept()

    def _gen_cover(self):
        from ..pipeline import novel as novel_pipe
        def job(tid):
            return novel_pipe.generate_cover(self.drama_id)
        def done(tid, result, error):
            if error:
                err("AI")
            else:
                self.cover_lab.setPixmap(W.pixmap_from_media(result, 220, 116))
        TASKMGR.submit("image", job, done, drama_id=self.drama_id)


from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402


class ReviewDialog(QDialog):
    """六维审校结果:连贯性/人设/设定/物件状态/文风/节奏,pass/fail + 问题清单。"""

    DIM_CN = {"coherence": "连贯性", "character": "人设", "setting": "设定",
              "props": "物件状态", "style": "文风", "pacing": "节奏"}

    def __init__(self, parent, review: dict, episode_number: int = 0):
        super().__init__(parent)
        self.setWindowTitle(tr("◇ 六维审校结果"))
        self.resize(640, 520)
        root = QVBoxLayout(self)
        overall = review.get("overall", "")
        head = QHBoxLayout()
        head.addWidget(W.h2(f"◇ 第 {episode_number} 章审校 · " + (tr("✅ 通过") if overall == "pass" else tr("⚠️ 需修复"))))
        head.addStretch(1)
        root.addLayout(head)
        if review.get("summary"):
            root.addWidget(W.muted(str(review["summary"])))
        dims = review.get("dimensions") or {}
        for key in ("coherence", "character", "setting", "props", "style", "pacing"):
            v = dims.get(key) or {}
            ok = bool(v.get("pass", True))
            issues = v.get("issues") or []
            text = f"{'✅' if ok else '❌'} {self.DIM_CN.get(key, key)}"
            if issues:
                text += "：" + "；".join(str(i) for i in issues[:4])
            lab = QLabel(text)
            lab.setWordWrap(True)
            root.addWidget(lab)
        root.addSpacing(8)
        close = W.primary_btn(tr("close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

# 写作红线:NOVEL_REQUIRED_STEPS 全部完成才能生成小说(对齐原版 5933)
NOVEL_REQUIRED_STEPS = [1, 2, 3, 4, 5, 7]
STEP_NAME_KEY = {1: "项目设定", 2: "总纲", 3: "世界观", 4: "故事合约",
                 5: "角色设定", 6: "卷战略", 7: "章节计划"}


def step_name(step: int) -> str:
    """向导步骤名现取 —— 同 prereq_name,模块级不能写 tr()。"""
    return tr(STEP_NAME_KEY.get(step, ""))


def wizard_step_done(drama_id: int, step: int) -> bool:
    """步骤完成判定(对齐原版 wizardStepDone)。

    ★ 步骤 3/4 读**已落库的** novel_meta,而非向导内存草稿 —— 刷新页面后未开向导也能正确判定。
    """
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    if not d:
        return False
    meta = db.jload(d["novel_meta"], {}) or {}
    if step == 1:                        # 项目设定 = 标题 + 简介
        m = db.jload(d["metadata"], {}) or {}
        return bool((d["title"] or "").strip() and (m.get("intro") or "").strip())
    if step == 2:
        return bool((d["novel_outline"] or "").strip())
    if step == 3:                        # 世界观 = era + location
        w = meta.get("world") or {}
        return bool(str(w.get("era") or "").strip() and str(w.get("location") or "").strip())
    if step == 4:                        # 故事合约 = pov + rules + tones
        c = meta.get("contract") or {}
        rules = c.get("rules") or []
        tones = c.get("tones") or []
        rules_ok = any(str(r or "").strip() for r in rules)
        return bool(c.get("pov") and rules_ok and len(tones) > 0)
    if step == 5:                        # 角色设定
        return bool(db.q1("SELECT id FROM characters WHERE drama_id=? LIMIT 1", (drama_id,)))
    if step == 6:
        return bool((d["novel_volume"] or "").strip())
    if step == 7:                        # 章节计划
        return len(db.jload(d["novel_chapters"], []) or []) > 0
    return False


def missing_steps(drama_id: int) -> list[int]:
    return [s for s in NOVEL_REQUIRED_STEPS if not wizard_step_done(drama_id, s)]


def gate_message(drama_id: int) -> str:
    """闸门提示:缺哪几步(对齐原版 batchMissingSteps)。"""
    miss = missing_steps(drama_id)
    if not miss:
        return ""
    return tr("、").join(f"{s}({step_name(s)})" for s in miss)
