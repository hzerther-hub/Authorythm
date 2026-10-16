# -*- coding: utf-8 -*-
"""小说线 UI:策划与设定面板 / 六维审校结果。"""
from __future__ import annotations

import json
import threading
import time

from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSizePolicy, QSpinBox, QTabWidget,
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
        # 全书章数存 novel_meta.chapter_count,**不用 total_episodes** ——
        # 后者是「集数」,且会被 generate_chapters_batched 写成实际生成章数,
        # 用户设的 999 会被自己跑出来的 60 覆盖(实测)。
        self.chapter_spin.setValue(
            int(nm0.get("chapter_count") or d["total_episodes"] or 60))
        self.word_spin.valueChanged.connect(self._on_size_changed)
        self.chapter_spin.valueChanged.connect(self._on_size_changed)
        size_row.addWidget(QLabel("每章字数"))
        size_row.addWidget(self.word_spin)
        size_row.addSpacing(16)
        size_row.addWidget(QLabel(tr("全书章数")))
        size_row.addWidget(self.chapter_spin)
        size_hint = W.muted(tr("  · 改这里后,「AI 生成章节计划」按新规模重排;已建的集不变"))
        size_hint.setMinimumWidth(240)
        size_hint.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        size_row.addWidget(size_hint)
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
        # 生成互斥:同一时刻只允许一个 AI 生成任务(并发会互相覆盖设定/正文)
        self._busy = False
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
            btn = WaitingButton(tr("✨ AI 起草") + (tr('第 {} 步').format(i + 1) if i else ""))
            W.set_icon(btn, "magic")
            btn.clicked.connect(lambda _=False, k=key, n=name: self._draft_section(k, n))
            self._draft_btns[key] = btn
            save_btn = QPushButton(tr("保存"))
            save_btn.setToolTip(tr("把当前内容写入项目"))
            save_btn.clicked.connect(lambda _=False, k=key: self._save_section(k))
            # 自动保存:停手 1.2s 后落库,不必记得点保存
            edit.textChanged.connect(lambda *a, k=key: self._autosave(k))
            self._save_btns[key] = save_btn
            row.addWidget(btn)
            row.addWidget(save_btn)
            row.addStretch(1)
            self._order_lab = self._order_lab if hasattr(self, "_order_lab") else {}
            self._order_lab[key] = W.muted("")
            # 窄屏时这两段说明会被压成一个字宽、竖着排出来(实测见过)。
            # 给下限宽度 + 忽略水平 sizeHint,让它们保持一行、溢出时省略。
            self._order_lab[key].setMinimumWidth(120)
            self._order_lab[key].setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
            row.addWidget(self._order_lab[key])
            hint = W.muted(tr("AI 起草会覆盖当前内容"))
            hint.setMinimumWidth(160)
            hint.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
            row.addWidget(hint)
            lay.addLayout(row)
            if key == "volume":
                # 卷结构列表:novel_chapters 里存着真正的分卷(标题/章号范围/
                # 目标/关键事件/钩子),编辑器只显示 text 字段(总体说明)。
                # 不展示出来的话用户会以为"生成的内容很少",也看不出哪卷缺细节。
                self.volume_list_host = QWidget()
                self.volume_list_lay = QVBoxLayout(self.volume_list_host)
                self.volume_list_lay.setContentsMargins(0, 8, 0, 0)
                self.volume_list_lay.setSpacing(6)
                lay.addWidget(self.volume_list_host)
                self._render_volume_list()
            if key == "contract":
                # 叙事人称(对齐参考项目故事合约向导的 pov 四选项)
                from PySide6.QtWidgets import QComboBox
                from ..pipeline.novel import POV_LABELS
                pov_row = QHBoxLayout()
                pov_row.addWidget(W.muted(tr("叙事人称")))
                self.pov_combo = QComboBox()
                for code, desc in POV_LABELS.items():
                    self.pov_combo.addItem(tr(desc), code)
                from ..pipeline.novel import get_novel_pov
                cur_pov = get_novel_pov(drama_id)      # novel_meta / novel_contract 两处都认
                if cur_pov in POV_LABELS:
                    self.pov_combo.setCurrentIndex(self.pov_combo.findData(cur_pov))
                self.pov_combo.setToolTip(tr("写章与审校都会按此人称强制校验"))
                self.pov_combo.currentIndexChanged.connect(self._apply_pov)
                pov_row.addWidget(self.pov_combo)
                pov_row.addStretch(1)
                lay.addLayout(pov_row)
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

        # 这一行控件很多(两个模型下拉 + 按卷 + 两个按钮 + 统计文字),挤一行会互相
        # 压缩 —— 被挤到极限的 QLabel 会一个字一行竖着排(实测右侧出现一列竖字)。
        # 分两行:第一行放两个模型,第二行放生成相关的。
        row_model = QHBoxLayout()
        row_model.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.chapters_btn = WaitingButton(tr("✨ AI 生成章节计划"))
        W.set_icon(self.chapters_btn, "magic")
        self.chapters_btn.clicked.connect(self._ai_chapters)
        save_btn = QPushButton(tr("保存本章节与角色"))
        save_btn.clicked.connect(self._save_plan_tab)
        # 按卷生成下拉:999 章一次生成不现实(20 分钟+、中途无产出、质量不稳),
        # 分卷已把叙事切段,按卷生成既快又与分卷对齐。None = 全书分批。
        self.vol_combo = QComboBox()
        self.vol_combo.setMinimumWidth(150)
        self.vol_combo.currentIndexChanged.connect(lambda _i: self._update_plan_stat())
        # 规划模型 / 正文模型 分设(实测依据见 novel.plan_config_id 注释):
        #   规划用 deepseek-v4-pro —— 结构化输出规整(分卷/合约字段完整)
        #   正文用 minimax-M3       —— 篇幅稳定,连续三章无衰减
        # 未单独选择时各自回退全局默认,不强制。
        plan_lab = QLabel(tr("规划模型"))
        plan_lab.setObjectName("inspectorLabel")
        row_model.addWidget(plan_lab)
        self.plan_model_combo = QComboBox()
        self.plan_model_combo.setMinimumWidth(110)
        # 宽度够放模型名但不无限撑:长模型名按比例缩放,不把整行顶开
        self.plan_model_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.plan_model_combo.setMinimumContentsLength(14)
        row_model.addWidget(self.plan_model_combo)
        prose_lab = QLabel(tr("正文模型"))
        prose_lab.setObjectName("inspectorLabel")
        row_model.addWidget(prose_lab)
        self.prose_model_combo = QComboBox()
        self.prose_model_combo.setMinimumWidth(110)
        self.prose_model_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.prose_model_combo.setMinimumContentsLength(14)
        row_model.addWidget(self.prose_model_combo)
        self.plan_model_combo.currentIndexChanged.connect(
            lambda _i: self._remember_split_model("plan"))
        self.prose_model_combo.currentIndexChanged.connect(
            lambda _i: self._remember_split_model("prose"))
        self._reload_split_models()
        row_model.addStretch(1)
        lay.addLayout(row_model)

        row.addWidget(self.vol_combo)
        row.addWidget(self.chapters_btn)
        save_btn = QPushButton(tr("保存本章节与角色"))
        save_btn.clicked.connect(self._save_plan_tab)
        row.addWidget(save_btn)
        row.addStretch(1)
        lay.addLayout(row)

        # 统计文字单独一行。它是生成进度的主要反馈,挤进操作行就必然被吃掉 ——
        # 实测在 760 宽(对话框默认宽)下按卷下拉 + 两个按钮就占满了,统计直接消失。
        self.plan_stat = W.muted("")
        self.plan_stat.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(self.plan_stat)
        self._reload_volume_combo()

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

    def _reload_split_models(self):
        """填充规划/正文模型下拉,选中已保存的(没有则用全局默认)。"""
        from ..ai import registry
        from ..pipeline import novel as novel_pipe
        cfg = registry.default_config("text", None) or {}
        pairs = (("plan", self.plan_model_combo, novel_pipe.plan_config_id()),
                 ("prose", self.prose_model_combo, novel_pipe.prose_config_id()))
        for kind, combo, cur in pairs:
            combo.blockSignals(True)
            combo.clear()
            for r in registry.list_configs("text"):
                combo.addItem((r["model"] or "").split("/")[-1] or r["model"], r["id"])
            i = combo.findData(cur if cur is not None else cfg.get("id"))
            combo.setCurrentIndex(i if i >= 0 else 0)
            combo.blockSignals(False)

    def _remember_split_model(self, kind: str):
        from ..core import db as _db
        combo = (self.plan_model_combo if kind == "plan"
                 else getattr(self, "prose_model_combo", None))
        if combo is None:
            return
        v = combo.currentData()
        if not v:
            return
        _db.set_setting("yihao.novel.plan_cfg" if kind == "plan"
                        else "yihao.novel.prose_cfg", str(v))
        ok(tr("{k}模型已切换").format(
            k=tr("规划") if kind == "plan" else tr("正文")))

    def _reload_volume_combo(self):
        """填充「按卷生成」下拉:全书 + 每一卷,并默认选中**下一卷该生成的**。"""
        from ..pipeline import novel as novel_pipe
        combo = getattr(self, "vol_combo", None)
        if combo is None:
            return
        cur = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("全书（分批）"), None)
        for i, v in enumerate(novel_pipe.load_volume_chapters(self.drama_id), 1):
            title = str(v.get("title") or "").strip() or tr("未命名")
            rng = str(v.get("range") or "").strip()
            combo.addItem(f"{i:02d} · {title}" + (f"  [{rng}]" if rng else ""), i)
        i = combo.findData(cur) if cur else self._next_volume_no()
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)

    def _next_volume_no(self) -> int:
        """下一卷该生成哪一卷:找出第一个「还没有章节」的卷,全有则返回最后一卷。"""
        from ..pipeline import novel as novel_pipe
        vols = novel_pipe.load_volume_chapters(self.drama_id)
        if not vols:
            return 0
        have = {int(c.get("number") or 0)
                 for c in (db.jload(db.q1(
                     "SELECT novel_chapters FROM dramas WHERE id=?",
                     (self.drama_id,))["novel_chapters"], []) or [])}
        for i, v in enumerate(vols, 1):
            a, b = novel_pipe._range_of(v)
            if a and not any(n in have for n in range(a, b + 1)):
                return i
        return len(vols)

    def _vol_progress(self) -> dict[int, tuple[int, int]]:
        """每卷的 (已生成章数, 应生成章数)。用于卷联动与前序校验。"""
        from ..pipeline import novel as novel_pipe
        chs = db.jload(db.q1("SELECT novel_chapters FROM dramas WHERE id=?",
                              (self.drama_id,))["novel_chapters"], []) or []
        done = {int(c.get("number") or 0) for c in chs if c.get("number")}
        out: dict[int, tuple[int, int]] = {}
        for i, vol in enumerate(novel_pipe.load_volume_chapters(self.drama_id), 1):
            a, b = novel_pipe._range_of(vol)
            if not a or not b:
                out[i] = (0, 0)
                continue
            out[i] = (sum(1 for n in done if a <= n <= b), b - a + 1)
        return out

    def _update_plan_stat(self):
        """状态栏:跟着**当前所选卷**显示它的进度,而不是全书概况。

        之前只看全书「已生成到第几章」,用户在第二卷下拉里看到的却是
        「下次生成第一卷」——下拉和状态对不上,等于没联动。现在按所选卷报。
        """
        from ..pipeline import novel as novel_pipe
        stat = getattr(self, "plan_stat", None)
        if stat is None or getattr(self, "_busy", False):
            return
        chs = db.jload(db.q1("SELECT novel_chapters FROM dramas WHERE id=?",
                              (self.drama_id,))["novel_chapters"], []) or []
        vols = novel_pipe.load_volume_chapters(self.drama_id)
        total = novel_pipe._plan_scale(self.drama_id, None, None)[0]
        nums = sorted(int(c.get("number") or 0) for c in chs if c.get("number"))
        vol_no = (self.vol_combo.currentData()
                  if hasattr(self, "vol_combo") else None)

        # 所选卷视角
        if vol_no and 1 <= int(vol_no) <= len(vols):
            v = vols[int(vol_no) - 1]
            a, b = novel_pipe._range_of(v)
            got = sum(1 for n in nums if a and b and a <= n <= b)
            head = tr("{t} · 第 {a}-{b} 章,已生成 {got}/{all} 章").format(
                t=v.get("title") or "", a=a or "?", b=b or "?",
                got=got, all=(b - a + 1) if a and b else 0)
            stat.setText(head + self._prev_volume_note(int(vol_no), vols, nums))
            self._sync_generate_enabled(int(vol_no), vols, nums)
            return

        # 全书视角(None = 全书分批)
        if not nums:
            stat.setText(tr("尚未生成章节计划 · 全书 {n} 章 · 共 {v} 卷").format(
                n=total, v=len(vols)))
            self.chapters_btn.setEnabled(True)
            return
        lo, hi = nums[0], nums[-1]
        head = tr("已生成 {cnt} 章 · 覆盖第 {lo}-{hi} 章 / 全书 {n} 章").format(
            cnt=len(nums), lo=lo, hi=hi, n=total)
        nxt = ""
        if hi < total:
            nv = novel_pipe.find_volume_of_chapter(self.drama_id, hi + 1)
            if nv:
                a, b = novel_pipe._range_of(nv)
                nxt = tr("  ·  下次生成【{t}】第 {a}-{b} 章").format(
                    t=nv.get("title") or "", a=a, b=b)
            else:
                nxt = tr("  ·  下次从第 {c} 章继续").format(c=hi + 1)
        elif vols:
            nxt = tr("  ·  全书章节计划已生成完毕")
        stat.setText(head + nxt)
        self.chapters_btn.setEnabled(True)

    def _prev_volume_missing(self) -> dict | None:
        """所选卷之前的**第一卷未生成完**的情况;都齐了返回 None。

        章节计划有依赖顺序:第 N 卷的钩子要接第 N-1 卷的结果,跳过前序卷直接
        生成,产出的章节会和已有内容对不上。所以取**最早**那个没生成完的卷来报错 ——
        用户先补第 1 卷,补完自动指向第 2 卷,而不是一次告诉他要补五卷。
        """
        from ..pipeline import novel as novel_pipe
        vol_no = (self.vol_combo.currentData()
                  if hasattr(self, "vol_combo") else None)
        if not vol_no:
            return None                     # 「全书(分批)」不按卷校验
        vols = novel_pipe.load_volume_chapters(self.drama_id)
        vol_no = int(vol_no)
        if not 1 <= vol_no <= len(vols):
            return None
        chs = db.jload(db.q1("SELECT novel_chapters FROM dramas WHERE id=?",
                              (self.drama_id,))["novel_chapters"], []) or []
        nums = {int(c.get("number") or 0) for c in chs if c.get("number")}
        for i in range(1, vol_no):
            a, b = novel_pipe._range_of(vols[i - 1])
            if not a or not b:
                continue
            got = sum(1 for n in nums if a <= n <= b)
            if got < b - a + 1:
                return {"index": i, "title": vols[i - 1].get("title") or "",
                        "a": a, "b": b, "got": got, "all": b - a + 1}
        return None

    def _prev_volume_note(self, vol_no: int, vols: list, nums: list) -> str:
        """所选卷之前有未生成的卷时,补一句提醒(不拦,只提示)。"""
        from ..pipeline import novel as novel_pipe
        for i in range(1, vol_no):
            a, b = novel_pipe._range_of(vols[i - 1])
            if not a or not b:
                continue
            got = sum(1 for n in nums if a <= n <= b)
            if got < b - a + 1:
                return tr("  ·  ⚠ 第 {i} 卷【{t}】只生成了 {got}/{all} 章,建议先补齐").format(
                    i=i, t=vols[i - 1].get("title") or "", got=got, all=b - a + 1)
        return ""

    def _sync_generate_enabled(self, vol_no: int, vols: list, nums: list):
        """前序卷没生成完 → 禁掉生成按钮(按钮禁用只是提示,拦截在 _ai_chapters)。"""
        miss = self._prev_volume_missing()
        if miss:
            self.chapters_btn.setEnabled(False)
            self.chapters_btn.setToolTip(
                tr("前序卷【{t}】尚未生成完(第 {a}-{b} 章只生成了 {got} 章),"
                   "请先生成它再继续").format(
                       t=miss["title"], a=miss["a"], b=miss["b"], got=miss["got"]))
        else:
            self.chapters_btn.setEnabled(True)
            self.chapters_btn.setToolTip("")

    def _on_size_changed(self):
        """规模改动即时落库,保证 AI 任务在后台读到的是用户当前设定。"""
        nm = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?",
                            (self.drama_id,))["novel_meta"], {}) or {}
        nm["word_count"] = self.word_spin.value()
        nm["chapter_count"] = self.chapter_spin.value()
        # 只写 novel_meta,**不再覆盖 total_episodes**(那是集数,与章数无关)
        db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
              (json.dumps(nm, ensure_ascii=False), db.now(), self.drama_id))

    def _enter_busy(self) -> bool:
        """占用生成槽;已被占用返回 False(提示并中止,避免并发互相覆盖)。

        **带看门狗**:后台线程一旦异常且收尾没走到 _leave_busy,_busy 会永久为 True,
        之后点多少次「AI 起草」都被静默挡掉 —— 实测用户连点数次、界面毫无反应,
        根本不知道是"还在跑"还是"已经死了"。这里超过 30 分钟自动放行,
        保证界面永远不会锁死。
        """
        if getattr(self, "_busy", False):
            from datetime import datetime as _dt
            since = getattr(self, "_busy_since", None)
            if since and (_dt.now() - since).total_seconds() > 1800:
                self._busy = False
                self._busy_since = None
            else:
                warn(tr("已有生成任务在进行,请等它完成后再试"))
                return False
        from datetime import datetime as _dt
        self._busy = True
        self._busy_since = _dt.now()
        self._sync_busy_buttons()
        return True

    def _leave_busy(self) -> None:
        self._busy = False
        self._sync_busy_buttons()

    def _sync_busy_buttons(self) -> None:
        """生成中禁用其余生成入口,避免并发。"""
        busy = getattr(self, "_busy", False)
        for b in list(getattr(self, "_draft_btns", {}).values()) +                 [getattr(self, "chapters_btn", None), getattr(self, "chars_btn", None)]:
            if b is not None and not busy:
                b.setEnabled(True)

    def _ai_chapters(self):
        """AI 生成章节计划:**流式**显示思考与结果,完成才落库。"""
        from ..core.preflight import ensure_ready
        from ..pipeline import novel as novel_pipe
        from .streaming import stream_into
        if not ensure_ready("text", None):
            return
        # 依赖顺序校验:前序卷没生成完就不许跳着生成。
        # 不依赖按钮禁用 —— 按钮禁用只是视觉提示,这里是唯一的**强制点**,
        # 免得以后新增的入口(批量面板/快捷键)绕过它。
        block = self._prev_volume_missing()
        if block:
            warn(tr("请先生成【{t}】第 {a}-{b} 章(已生成 {got} 章),再生成这一卷").format(
                t=block.get("title") or "", a=block["a"], b=block["b"], got=block["got"]))
            self._update_plan_stat()
            return
        if not self._enter_busy():
            return
        n, words = self.chapter_spin.value(), self.word_spin.value()
        self._save_project_meta()
        self._on_size_changed()
        btn = self.chapters_btn
        self.tabs.setCurrentIndex(self.tabs.count() - 1)     # 章节计划页
        editor = self.chapters_edit

        vol_no = self.vol_combo.currentData() if hasattr(self, "vol_combo") else None
        # 选了卷 → 本次只生成那一卷,进度上限是**该卷章数**而不是全书章数。
        # 原先用全书 n 做进度分母,选卷生成第一卷(120 章)时状态栏写的是
        # 「分批生成中 0/999 章…」,用户以为在生成整本书,也对不上实际产出。
        if vol_no:
            vols = novel_pipe.load_volume_chapters(self.drama_id)
            v = vols[int(vol_no) - 1] if 0 < int(vol_no) <= len(vols) else None
            va, vb = (novel_pipe._range_of(v) if v else (None, None))
            n_target = (vb - va + 1) if va and vb else n
            label = tr('第 {no} 卷 · 第 {a}-{b} 章').format(
                no=vol_no, a=va or "?", b=vb or "?")
        else:
            n_target, label = n, tr('全书')

        if n > novel_pipe.CHAPTER_PLAN_LIMIT or vol_no:
            # 长篇:一次请求写不下(999 章会被模型压成散文、解析全废)→ 分批生成
            from ..core.taskmgr import TASKMGR
            btn.busy(tr('生成 {} 章计划中').format(n_target))
            # 不清空编辑器:清空后若第一批就失败,用户原来已有的章节计划
            # 在界面上也一并消失,像是把内容弄丢了(库里其实还在)。
            self.plan_stat.setText(tr('正在生成 {lab}…0/{n} 章').format(lab=label, n=n_target))

            # 进度回写走 **TASKMGR 的信号**(跨线程安全),不用 QTimer.singleShot ——
            # 后者在 worker 线程里排队等主线程事件循环,界面繁忙时更新会整段丢失,
            # 表现为状态栏卡在「分批生成中 0/999 章…」不动(实测)。
            prog = _PlanProgress(self, btn, n_target, label)
            prog.beat()          # 先起心跳:第一批 82 秒,期间界面不能是死的
            snap = _PlanPartial(self, editor)

            def job(tid):
                # 选了卷 → 只生成该卷章节(并顺带抽该卷角色);
                # 没选(「全书(分批)」)→ 退回原全书分批。
                if vol_no:
                    return novel_pipe.generate_chapters_for_volume(
                        self.drama_id, vol_no, word_count=words,
                        progress=prog.on_progress, on_partial=snap.on_partial)
                return novel_pipe.generate_chapters_batched(
                    self.drama_id, chapter_count=n, word_count=words,
                    progress=prog.on_progress, on_partial=snap.on_partial)

            def done(tid, result, error):
                btn.idle()
                self._leave_busy()
                if error:
                    err(tr('章节计划生成失败:{}').format(str(error)[:160]))
                    return
                self._reload_tabs()
                self._update_plan_stat()
                editor.setPlainText(novel_pipe.chapters_to_text(result['chapters']))
                ok(tr('章节计划已生成:{} 章 / 每章约 {} 字').format(
                    result['count'], result['word_count']))

            TASKMGR.submit("prompt", job, done, drama_id=self.drama_id)
            return

        btn.busy(tr('生成 {} 章计划中').format(n))
        editor.clear()

        def finished(text: str) -> None:
            btn.idle()
            self._leave_busy()
            try:
                result = novel_pipe.persist_chapters(self.drama_id, text,
                                                    chapter_count=n, word_count=words)
            except Exception as exc:  # noqa: BLE001
                editor.setPlainText("")
                err(tr('章节计划保存失败:{}').format(str(exc)[:160]))
                return
            self._reload_tabs()
            self._update_plan_stat()
            if key == "volume" and hasattr(self, "_render_volume_list"):
                self._render_volume_list()      # 卷结构列表要跟着刷新
            ok(tr('章节计划已生成:{} 章 / 每章约 {} 字').format(result['count'], result['word_count']))

        def failed(msg: str) -> None:
            btn.idle()
            self._leave_busy()
            editor.setPlainText("")
            err(tr('章节计划生成失败:{}').format(msg[:160]))

        worker = stream_into(editor, novel_pipe.chapters_prompt(self.drama_id, n, words),
                             # 板块名是提示词路由键(SECTION_SPEC 按中文名匹配),翻了模型就认不出要写哪一块
                             system=novel_pipe._draft_system("章节计划"),
                             config_id=None, temperature=0.4, json_mode=True,
                             # 输出预算取该服务配置的「最大输出 token」
                             max_tokens=None,
                             on_finished=finished, on_failed=failed, owner=self)
        self._stream_worker = worker

    def _save_plan_tab(self):
        from ..pipeline import novel as novel_pipe
        try:
            raw = json.loads(self.chars_edit.toPlainText() or "[]")
            if not isinstance(raw, list):
                raise ValueError(tr("主要角色需要是 JSON 数组"))
        except Exception as exc:  # noqa: BLE001
            err(tr('主要角色 JSON 有误:{}').format(exc))
            return
        chapters = novel_pipe.chapters_from_text(self.chapters_edit.toPlainText())
        if not chapters and self.chapters_edit.toPlainText().strip():
            err("章节计划无法解析,请按「第N章 标题 | 目标:… | 事件:… | 钩子:…」格式填写")
            return
        novel_pipe.save_chapters(self.drama_id, chapters)
        n_char = novel_pipe.save_characters(self.drama_id, raw)
        self._update_plan_stat()
        ok(tr('已保存:{} 章计划 · {} 个角色(角色已同步到资产库)').format(len(chapters), n_char))

    def closeEvent(self, ev):
        """关闭时停掉还在跑的流式线程(QThread 仍在运行时析构会崩)。"""
        w = getattr(self, "_stream_worker", None)
        if w is not None and w.isRunning():
            w.cancel()
            w.wait(3000)
        self._busy = False          # 关闭时释放生成槽,重开对话框不会卡在禁用态
        super().closeEvent(ev)

    def reject(self):
        self.close()

    # ── AI 起草(对齐原版 draftNovelSection)──
    SECTION_CN = {"outline": tr("总纲"), "world": tr("世界观"), "contract": tr("故事合约"), "volume": tr("分卷战略")}
    SECTION_MAP = {"outline": ("novel_outline", "outline"),
                   "world": ("novel_world", "world"),
                   "contract": ("novel_contract", "contract"),
                   "volume": ("novel_volume", "volume")}

    def _apply_pov(self) -> None:
        """写回项目叙事人称。

        统一走 novel.set_novel_pov(存 novel_meta.contract.pov) —— 与「项目设置 → 叙事人称」
        同一个数据源、get_novel_pov 也优先读它。此前这里另写合约 JSON 的 structured.pov,
        两处不同源,切换后读回来还是旧值。
        """
        from ..pipeline import novel as novel_pipe
        combo = getattr(self, "pov_combo", None)
        if combo is None:
            return
        pov = novel_pipe.set_novel_pov(self.drama_id, combo.currentData())
        # 合约正文是 JSON 时同步 structured.pov,保持两处表述一致
        try:
            raw = self.edits["contract"].toPlainText() if "contract" in self.edits else ""
            if raw.strip().startswith("{"):
                data = json.loads(raw)
                if isinstance(data, dict):
                    st = data.get("structured")
                    if not isinstance(st, dict):
                        st = {}
                    st["pov"] = pov
                    data["structured"] = st
                    self.edits["contract"].setPlainText(json.dumps(data, ensure_ascii=False, indent=2))
                    self._save_section("contract")
        except Exception:  # noqa: BLE001 —— 合约非 JSON 时只写 meta 即可
            pass
        ok(tr("叙事人称已设为:{}").format(combo.currentText()))

    def _draft_section(self, key: str, name: str):
        """AI 起草该板块:**流式**显示 + 直接落库(见 novel.draft_section 的说明)。"""
        from ..core.preflight import ensure_ready
        from ..pipeline import novel as novel_pipe
        from .streaming import stream_into
        if not ensure_ready("text", None):
            return
        if not self._enter_busy():
            return
        miss = missing_prereq(self.drama_id, key)
        if miss:
            self._leave_busy()
            warn(tr('请先生成「{}」再起草{}').format('、'.join(miss), name))
            return
        self._save_project_meta()          # 先落库,上下文里才有题材/简介
        btn = self._draft_btns[key]
        btn.busy(tr('起草{}中').format(name))
        save_btn = self._save_btns.get(key)
        if save_btn:
            save_btn.setEnabled(False)      # 流式期间禁止保存:框里是思考的半截内容
        # 规划侧的 7 个板块(总纲/世界观/合约/角色/卷战略/章节规划)一律走「规划模型」。
        # 旧代码读的是 self.text_combo,该控件已被 plan/prose 两个下拉取代,
        # hasattr 恒为 False → 永远传 None,规划模型的选择形同虚设。
        cid = self.plan_model_combo.currentData()
        config_id = int(cid) if cid else None
        editor = self.edits[key]
        self.tabs.setCurrentWidget(editor.parentWidget().parentWidget())
        spec = novel_pipe.SECTION_SPEC[key]
        prompt = novel_pipe.draft_prompt(self.drama_id, key)

        def finished(text: str) -> None:
            btn.idle()
            self._leave_busy()          # 解锁所有起草按钮
            if save_btn:
                save_btn.setEnabled(True)
            try:
                result = novel_pipe.persist_draft(self.drama_id, key, text)
            except Exception as exc:  # noqa: BLE001
                err(tr('{}保存失败:{}').format(name, str(exc)[:160]))
                return
            self._reload_tabs()
            self._update_plan_stat()
            ok(tr('{}已生成并保存{}').format(name, result.get('extra', '')))

        def failed(msg: str) -> None:
            btn.idle()
            self._leave_busy()          # 解锁所有起草按钮
            if save_btn:
                save_btn.setEnabled(True)
            editor.setPlainText("")     # 别把思考过程留在框里冒充结果
            err(tr('{}起草失败:{}').format(name, msg[:160]))

        # 分卷:章数大时走**分批**(骨架 + 逐批展开),单次输出必被 max_tokens
        # 截断(实测 999 章 → 34 卷 ≈ 8800 字 > 默认 8192 tokens)。
        if key == "volume" and novel_pipe.volume_plan_size(self.drama_id) > novel_pipe.VOLUME_BATCH_THRESHOLD:
            btn.busy(tr('起草{name}中').format(name=name))
            if save_btn:
                save_btn.setEnabled(False)

            # 过程必须**看得见**:分批要跑好几分钟,编辑器空白 + 按钮转圈
            # 分不清是在跑还是卡死(实测用户反复点、以为没生成)。
            # 所以每批把进度追加到编辑器里,像日志一样逐行滚动。
            def _log(line: str):
                # 控制台永远留痕:UI 更新若因事件循环繁忙而丢失,
                # 控制台这一行仍在,排查时不至于完全无线索。
                print(f"[novel][分卷] {line}", flush=True)
                cur = editor.textCursor()
                cur.movePosition(cur.MoveOperation.End)
                cur.insertText(line + "\n")
                editor.setTextCursor(cur)
                editor.ensureCursorVisible()

            def on_prog(done_n: int, total_n: int):
                btn.busy(tr('起草{name}中 {a}/{b}').format(
                    name=name, a=done_n, b=total_n))
                _log(tr('已完成 {a}/{b} 卷').format(a=done_n, b=total_n))

            def batches():
                # 无论成功失败,收尾必须**一定**回到主线程解锁;
                # 否则 _busy 永久为 True,之后每次点「AI 起草」都被
                # _enter_busy() 静默挡掉 —— 表现为"点了几次都没反应"。
                try:
                    chapters = novel_pipe.draft_volume_in_batches(
                        self.drama_id, config_id=config_id,
                        on_progress=on_prog, on_stage=_log)
                except Exception as exc:  # noqa: BLE001
                    import traceback
                    print(f"[novel] 分卷起草异常: {exc}", flush=True)
                    traceback.print_exc()
                    _log(tr('{}起草失败:{}').format(name, str(exc)[:160]))
                    failed(tr('{}起草失败:{}').format(name, str(exc)[:160]))
                    return
                raw = json.dumps({"chapters": chapters}, ensure_ascii=False)
                finished(raw)

            _log(tr('全书 {n} 章,约 {v} 卷,开始分批生成(先生成卷骨架,再逐批补细节)…')
                 .format(n=novel_pipe.volume_plan_size(self.drama_id),
                         v=max(1, -(-novel_pipe.volume_plan_size(self.drama_id)
                                 // novel_pipe.VOLUME_CHAPTERS_PER_VOL))))
            from ..core.taskmgr import TASKMGR

            # 用 TASKMGR 而不是裸 threading.Thread:裸线程的异常无人捕获
            # (实测分卷失败时控制台一行输出都没有,界面只停在启动行),
            # 且它派发的 on_main 在事件循环繁忙时可能丢失。TASKMGR 有
            # 完整的失败回调与错误落库。
            TASKMGR.submit("novel_volume", lambda _tid: batches(),
                           lambda _tid, _r, _e: None,
                           drama_id=self.drama_id)
            # 注意:这里**不能**只置 self._busy=False —— 起草按钮是在
            # _enter_busy 里被 _sync_busy_buttons 全禁用的,不走 _leave_busy
            # 就没人把按钮点回来(实测:点「AI 起草」毫无反应,按钮一直是灰的)。
            # 解锁交给 batches 里的 finished/failed 统一做。
            return

        worker = stream_into(editor, prompt, system=novel_pipe._draft_system(spec["name"]),
                             config_id=config_id, temperature=0.6,
                             json_mode=(spec["fmt"] == "json"),
                             on_finished=finished, on_failed=failed, owner=self)
        self._stream_worker = worker          # 持有引用,防被 GC;关闭对话框时 cancel

    @staticmethod
    def _vol_line(label: str, body: str) -> QLabel:
        """卷卡片里的一行「标签 + 正文」,正文完整换行展示。"""
        lab = QLabel(f"{label}：{body}")
        lab.setWordWrap(True)               # 换行,不横向溢出
        lab.setTextFormat(Qt.RichText)      # 支持换行符

        lab.setStyleSheet("color:#86909c;")
        return lab

    def _render_volume_list(self):
        """渲染卷结构列表:标题 / 章号范围 / 目标 / 关键事件 / 卷末钩子。

        缺 goal 或 key_events 的卷标红提示 —— 分批生成时单批失败会留下
        "只有骨架、没细节"的卷,这里直接标出来,不用去翻 JSON。
        """
        from ..pipeline import novel as novel_pipe
        host = getattr(self, "volume_list_host", None)
        if host is None:
            return
        lay = self.volume_list_lay
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        # 读独立的分卷字段(metadata.volume_chapters),不读 novel_chapters ——
        # 那个是「章节计划」,共用会把分卷清空。
        chapters = novel_pipe.load_volume_chapters(self.drama_id)
        if not chapters:
            lay.addWidget(W.muted(tr("暂无卷结构 —— 点「AI 起草」生成分卷战略后会显示在这里")))
            return
        head = QHBoxLayout()
        head.addWidget(W.h2(tr("卷结构")))
        ok_n = sum(1 for c in chapters if c.get("goal") and c.get("key_events"))
        head.addWidget(W.muted(tr("{ok}/{total} 卷含完整细节").format(
            ok=ok_n, total=len(chapters))))
        head.addStretch(1)
        lay.addLayout(head)
        for i, c in enumerate(chapters, 1):
            if not isinstance(c, dict):
                continue
            missing = not (c.get("goal") and c.get("key_events"))
            title = str(c.get("title") or tr("未命名"))
            rng = str(c.get("range") or "").strip()
            goal = str(c.get("goal") or "").strip()
            ev = [str(x).strip() for x in (c.get("key_events") or []) if str(x).strip()]

            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(2)

            # 标题行:永远可见,点击展开/收起
            head_btn = QPushButton(f"{i:02d} · {title}" + (f"  [{rng}]" if rng else ""))
            head_btn.setObjectName("refTab")
            head_btn.setCheckable(True)
            head_btn.setCursor(Qt.PointingHandCursor)
            head_btn.setToolTip(tr("点击展开/收起完整内容"))
            if missing:
                head_btn.setText(head_btn.text() + "   ⚠ " + tr("缺细节"))
            bl.addWidget(head_btn)

            # 详情区:默认隐藏,展开后显示**完整**内容(不截断)
            detail = QWidget()
            dl = QVBoxLayout(detail)
            dl.setContentsMargins(18, 4, 0, 0)
            dl.setSpacing(2)
            if goal:
                dl.addWidget(self._vol_line(tr("目标"), goal))
            if ev:
                dl.addWidget(self._vol_line(
                    tr("关键事件"), "\n".join(f"· {x}" for x in ev)))
            if c.get("cliffhanger"):
                dl.addWidget(self._vol_line(tr("钩子"), str(c["cliffhanger"])))
            # 动态高度用 **setMaximumHeight + updateGeometry** 驱动,
            # 不用 setVisible:详情面板若整体 hidden,其 sizeHint 会被 Qt 缓存成 0,
            # 展开后布局不重算,表现为"点了没反应"(实测页高恒定不变)。
            detail_h = detail.sizeHint().height() or 176
            detail.setMaximumHeight(0)
            bl.addWidget(detail)

            # clicked 信号会传一个 bool(是否勾选),必须用 *args 忽略它 ——
            # 否则默认值 btn=head_btn 收不到按钮对象,直接 AttributeError,
            # 展开功能完全失效(实测页高恒为 202 纹丝不动)。
            def _toggle(*_args, btn=head_btn, panel=detail, host=bl,
                        full_h=detail_h):
                show = panel.maximumHeight() == 0
                btn.setChecked(show)
                # 0 表示收起,full_h 表示完全展开 —— 直接改高度并刷新布局链,
                # 保证容器(以及外层滚动区)跟着变高/变矮。
                panel.setMaximumHeight(full_h if show else 0)
                panel.updateGeometry()
                host.invalidate()
                for child in panel.findChildren(QLabel):
                    child.updateGeometry()
                vl_host = getattr(self, "volume_list_host", None)
                if vl_host is not None:
                    vl_host.updateGeometry()
            head_btn.clicked.connect(_toggle)
            lay.addWidget(box)

    def _save_section(self, key: str, quiet: bool = False):
        """保存单个板块。**不关闭对话框** —— 手动点「保存」也要留在当前页签
        连着改下一个板块,否则每存一次就要重新打开。
        quiet=True 供自动保存调用,不弹 toast(每敲几个字弹一次会烦)。
        """
        field, _ = self.SECTION_MAP[key]
        db.ex(f"UPDATE dramas SET {field}=?, updated_at=? WHERE id=?",
              (self.edits[key].toPlainText(), db.now(), self.drama_id))
        if not quiet:
            ok(tr('{}已保存').format(self.SECTION_CN[key]))
            self._reload_tabs()

    def _autosave(self, key: str):
        """编辑停止 1.2s 后自动落库(防抖)。

        没有它的话:AI 起草完内容只在编辑器里,必须手动点保存;中途切页签/关窗口
        就白生成一次(模型调用要花钱)。分批生成尤其明显 —— 等 6 批跑完再手点保存,
        中间崩了就全丢。

        **生成期间必须跳过**:分批模式会把进度日志写进编辑器(让用户看到过程),
        若不跳过,自动保存会把「全书 999 章,约 34 卷…」这种日志行当成正文存进
        novel_volume(实测已发生,39 字的日志污染了数据)。真正的落库由
        persist_draft 在 finished 里做。
        """
        if getattr(self, "_busy", False):
            return
        if getattr(self, "_autosave_timer", None) is not None:
            self._autosave_timer.stop()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(lambda k=key: self._save_section(k, quiet=True))
        self._autosave_timer.start(1200)

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
            self.chapter_spin.setValue(
                int(nm.get("chapter_count") or d["total_episodes"] or 60))
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
            # 必须显式传生图配置:不传就落到 registry 的默认服务,而默认可能
            # 是额度耗尽的百炼 → HTTP 429 Throttling.AllocationQuota(实测)。
            from ..core.db import selected_config_id
            return novel_pipe.generate_cover(self.drama_id,
                                             config_id=selected_config_id("image"))
        def done(tid, result, error):
            if error:
                err("AI")
            else:
                self.cover_lab.setPixmap(W.pixmap_from_media(result, 220, 116))
        TASKMGR.submit("image", job, done, drama_id=self.drama_id)


from PySide6.QtCore import QObject, QTimer, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402


class _PlanPartial(QObject):
    """把分批产出的章节计划**实时追加**到编辑器。

    之前只在全部 25 批跑完后一次性 setPlainText,期间编辑器全空,
    用户看到的就是「点了没反应」(实测)。这里每批写一次,过程可见。
    """

    _sig = Signal(object)

    def __init__(self, dialog, editor):
        super().__init__(dialog)
        self._editor = editor
        self._sig.connect(self._apply)

    def on_partial(self, chapters):
        """worker 线程调用:只 emit。"""
        self._sig.emit(list(chapters))

    def _apply(self, chapters):
        from ..pipeline import novel as novel_pipe
        try:
            self._editor.setPlainText(novel_pipe.chapters_to_text(chapters))
            self._editor.moveCursor(self._editor.textCursor().MoveOperation.End)
        except Exception:  # noqa: BLE001
            pass


class _PlanProgress(QObject):
    """章节计划分批进度:worker 线程 emit → 主线程更新界面。

    直接在 worker 线程改控件是跨线程操作(Qt 会警告甚至崩),而
    QTimer.singleShot 又依赖主线程事件循环繁忙度、丢更新。信号是
    项目里其它后台任务(如 StreamWorker)已经在用的可靠通道,这里沿用。
    """

    _sig = Signal(int, int, int)          # done, total, percent

    def __init__(self, dialog, btn, total, label=""):
        super().__init__(dialog)
        self._dlg, self._btn, self._total = dialog, btn, total
        self._label = label or ""
        self._sig.connect(self._apply)

    def on_progress(self, _pct, done, total):
        """worker 线程调用:只 emit,绝不碰界面。"""
        self._sig.emit(int(done), int(total), int(done * 100 / max(1, total)))

    def beat(self):
        """第一批还没回来时的心跳,让用户知道「在跑,不是卡死」。

        **必须有**:实测 deepseek-v4-pro 生成一批要 82 秒,第一卷 3 批共
        4-5 分钟。期间 on_progress 一次都不触发,状态栏纹丝不动地写着
        「0/120 章」,用户看到的就是"点了没反应"。心跳每 10 秒把已等时长
        说出来,「已等待 30 秒…」比静止的数字可信得多。
        """
        self._t0 = time.time()
        self._tick()

    def _tick(self):
        if not self._dlg.plan_stat.isVisible():
            return
        secs = int(time.time() - self._t0)
        base = self._dlg.plan_stat.text().split("  ·  已等待")[0]
        self._dlg.plan_stat.setText(f"{base}  ·  已等待 {secs} 秒…")
        QTimer.singleShot(10_000, self._tick)

    def _apply(self, done, total, _pct):
        """主线程槽:更新状态栏与按钮文字。"""
        self._dlg.plan_stat.setText(
            tr('{lab}生成中 {done}/{total} 章…').format(
                lab=(self._label + " ") if self._label else "",
                done=done, total=total))
        self._btn.setText(tr('生成中 {done}/{total}').format(done=done, total=total))


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
        head.addWidget(W.h2(tr('◇ 第 {} 章审校 · ').format(episode_number) + (tr("✅ 通过") if overall == "pass" else tr("⚠️ 需修复"))))
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
