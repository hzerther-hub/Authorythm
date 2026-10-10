# -*- coding: utf-8 -*-
"""集制作工作台:六阶段流水线(原始内容 → AI 改写 → 视漫制作 → 分镜 → 漫画 → 拼接导出)。

顶栏:文本/图片/视频模型 + 分辨率 + 任务入口(对齐原版 episode.vue)。
侧栏:剧本 / 制作(资产·分镜·漫画) / 导出 三段步骤导航 + 进度。
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QSizePolicy,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSpinBox, QSplitter,
                               QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from .confirm import ask
from ..ai import face_swap, image_client, registry, tts_client, video_client
from ..agents import runner
from ..ai.jev_gate import JevBreaker
from ..core import config, db
from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from ..pipeline import comic as comic_pipe
from ..pipeline import extractor as extract_pipe
from ..pipeline import merge as merge_pipe
from ..pipeline import prompts_gen
from ..pipeline import rewriter
from ..pipeline import storyboard as sb_pipe
from ..pipeline import stitch as stitch_pipe
from . import widgets as W
from .toast import err, info, ok, warn
from .braille import WaitingButton

STEPS = ["raw", "rewrite", "assets", "storyboard", "comic", "export"]
STEP_LABELS = {"raw": "raw_content", "rewrite": "ai_rewrite", "assets": "production",
               "storyboard": "storyboard", "comic": "comic", "export": "export_stage"}
STEP_ICONS = {"raw": "▤", "rewrite": "✎", "assets": "☺",
              "storyboard": "▦", "comic": "▩", "export": "⤓"}
# 三段环节 → 步骤(对齐原版 sidebarSections)
NAV_SECTIONS = [("script", "step_script", ["raw", "rewrite"]),
                ("production", "step_production", ["assets", "storyboard", "comic"]),
                ("export", "step_export", ["export"])]
SECTION_OF = {k: sid for sid, _, keys in NAV_SECTIONS for k in keys}
# 底部四段跑马灯:剧本 / 资产 / 视漫 / 漫画(点击直接跳对应步骤)
PROGRESS_STEPS = [("raw", "stage_script"), ("assets", "stage_assets"),
                  ("storyboard", "stage_video"), ("comic", "stage_comic")]

REF_TAB_KEYS = {"character": "chars", "scene": "scenes", "prop": "props"}


class _MergeTick(QTimer):
    """拼接等待态 1s 心跳:刷新「拼接中」卡片上的已耗时秒数(对齐原版 nowTick + mergeElapsedSec)。"""

    def __init__(self, page):
        super().__init__(page)
        self.setInterval(650)
        self.timeout.connect(page._tick_merge_waiting)
        self._pulse_on = False


_costume_breaker = JevBreaker("video-costume")


def _sb_costume_context(sb_id: int, drama_id: int) -> str:
    """本镜角色剧情着装状态 —— 判断服装是否应已随剧情变化(对齐原版 buildShotStateCostumeContext)。

    两层:
      1. 确定性:状态台账里该角色的「外貌」有记录 → 直接注入「剧情当前着装」
         (台账由批量写作每章提取,是剧情推进后的权威状态)
      2. Jev 判读:台账无外貌记录的角色,把本镜画面描述 + 角色基础形象发给 Jev
         (noul:本镜着装是否应已不同于基础形象 —— 中举/婚礼/上任/败落/季节更替等换装事件),
         置信度 ≥ JEV_COSTUME_MIN_CONFIDENCE(默认 0.6) 才注入,防误报污染提示词

    软失败:JEV_COSTUME_CHECK=0 关判读;未配置 / 连不通(独立熔断)只保留台账确定性注入。
    与造型变体机制互补(变体=人工预设,本功能=剧情状态)。
    """
    import os as _os

    from ..pipeline import state_ledger as _sl
    links = db.q("SELECT character_id FROM storyboard_characters WHERE storyboard_id=?", (sb_id,))
    if not links:
        return ""
    ids = tuple(l["character_id"] for l in links)
    chars = {r["id"]: dict(r) for r in db.q(
        "SELECT * FROM characters WHERE id IN (" + ",".join("?" * len(ids)) + ")", ids)}
    ledger = _sl._meta(drama_id).get("state_ledger") or {}
    sb = db.q1("SELECT content FROM storyboards WHERE id=?", (sb_id,))
    lines: list[str] = []
    need_jev: list[tuple[str, str]] = []
    for link in links:
        ch = chars.get(link["character_id"])
        if not ch:
            continue
        # 状态台账是落库的中文 JSON,键名不能翻 —— 翻了英文界面下就永远取不到
        look = ((ledger.get("characters") or {}).get(ch.get("name") or "") or {}).get("外貌")
        if look:
            lines.append(f"{ch['name']} → 剧情当前着装(状态台账):{str(look)[:80]}")
        else:
            need_jev.append((ch.get("name") or "", (ch.get("appearance") or "")[:80]))

    if need_jev and _os.environ.get("JEV_COSTUME_CHECK") != "0":
        from ..ai.jev_gate import get_jev_gate
        gate = get_jev_gate()
        if gate.usable and not _costume_breaker.in_cooldown():
            questions = {
                f"chg_{i}": {
                    "type": "noul",
                    "instructions": ("按剧情进展与本镜画面,该角色的服装是否应已与其基础形象不同"
                                     "(中举/婚礼/上任/败落/季节更替等换装事件)。"
                                     "1=应已变化,0=应仍是基础形象"),
                } for i in range(len(need_jev))
            }
            # 这段 state 是发给 Jev 的提问内容,保持中文
            state = ("【角色基础形象】" + "；".join(f"{n}:{a or '未描述'}" for n, a in need_jev)
                     + "\n【本镜画面描述】\n" + str((sb["content"] if sb else "") or "")[:800])
            result = gate.client.decide(state, questions)
            if result and result.get("answers"):
                _costume_breaker.note_ok()
                try:
                    th = float(_os.environ.get("JEV_COSTUME_MIN_CONFIDENCE") or 0.6)
                except ValueError:
                    th = 0.6
                for i, (name, _ap) in enumerate(need_jev):
                    try:
                        n = float((result["answers"].get(f"chg_{i}") or {}).get("noul"))
                    except (TypeError, ValueError):
                        continue
                    if n >= th:
                        lines.append(
                            f"{name} → 剧情推进,本镜着装应已不同于基础形象"
                            f"(置信度 {int(round(n * 100))}%):按剧本语境描写当前服装,不要直接套用参考图妆造")
            else:
                _costume_breaker.note_fail()
    if not lines:
        return ""
    return ("\n本镜角色剧情着装状态(着装描写必须与此一致;无着装提示的角色按基础形象):\n"
            + "\n".join(lines))


def _sb_prompt_request(r: dict) -> str:
    """「视频提示词」AI 重生成请求(对齐原版 inspector 的 AI 生成按钮)。"""
    costume = ""
    if r.get("id") and r.get("drama_id"):
        try:
            costume = _sb_costume_context(r["id"], r["drama_id"])
        except Exception:  # noqa: BLE001 —— 着装判读异常不阻断提示词生成
            costume = ""
    return f"""为下面这个镜头生成视频提示词(英文,一段,不要解释)。
{costume}
画面描述:
{r.get('content') or tr('(无)')}

氛围:
{r.get('atmosphere') or tr('(无)')}

运镜与时长:
镜别 {r.get('shot_type') or tr('(无)')} / 角度 {r.get('angle') or tr('(无)')} / 运动 {r.get('movement') or tr('(无)')} / {int(r.get('duration') or 10)}s

已绑定的 @角色名 / @场景名 会自动映射为参考图,请原样保留这些 @ 标记。
只输出提示词正文。"""

# 资产卡文案(对齐原版 zh.json 的 episode.asset.* / episode.prod.*)
ASSET_LABELS = {
    "cover_todo": "形象待生成", "cover_done": "已生成", "cover_tag": "视图",
    "lead": "主角", "supporting": "配角", "extra": "龙套",
    "gen_image": "图绘", "gen_image_tip": "基于当前形象图生图重绘,保留人物特征",
    "gen_text": "文绘", "gen_text_tip": "仅用文字重新生成(全新 AI 相貌,可避开真人审核)",
    "upload": "上传", "upload_tip": "上传资产图",
    "face_swap": "换脸", "face_swap_tip": "换脸:用一张参考图替换当前形象",
    "variants": "◑ 造型变体", "variants_tip": "同一角色的多套服装造型",
    "prompt_ph": "首次生成图片时由提示词 Agent 自动生成",
    "redraw": "重绘", "generate": "生成", "prop": "道具", "desc_empty": "暂无描述",
    "gen_done": "已就绪", "gen_todo": "待生成",
}


class StepNav(QWidget):
    """流水线侧栏(对齐原版 episode.vue):三段环节 + 环节状态 + 四段进度 + 折叠/刷新。"""

    step_changed = Signal(str)
    refresh_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(196)
        self._collapsed = False
        self._active = "raw"
        self._states: dict[str, str] = {}
        self._section_hidden: dict[str, bool] = {}
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 10, 6, 10)
        lay.setSpacing(2)

        self._section_state: dict[str, QLabel] = {}
        self._section_tag: dict[str, QLabel] = {}
        self._section_head: dict[str, QWidget] = {}
        self._btns: dict[str, QPushButton] = {}

        for sid, group_key, keys in NAV_SECTIONS:
            head = QWidget()
            hrow = QHBoxLayout(head)
            hrow.setContentsMargins(4, 0, 4, 0)
            hrow.setSpacing(6)
            state = QLabel("·")
            state.setObjectName("pipeState")
            name = QLabel(tr(group_key))
            name.setObjectName("pipeSection")
            tag = QLabel(tr("doing_now"))
            tag.setObjectName("pipeTag")
            tag.setVisible(False)
            hrow.addWidget(state)
            hrow.addWidget(name)
            hrow.addStretch(1)
            hrow.addWidget(tag)
            self._section_state[sid] = state
            self._section_tag[sid] = tag
            self._section_head[sid] = head
            lay.addWidget(head)
            for k in keys:
                b = QPushButton("   " + STEP_ICONS[k] + "  " + tr(STEP_LABELS[k]))
                b.setObjectName("pipeItem")
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, kk=k: self.step_changed.emit(kk))
                self._btn_group.addButton(b)
                self._btns[k] = b
                lay.addWidget(b)
            lay.addSpacing(6)

        lay.addStretch(1)

        # ── 底部:折叠 + 四段跑马灯 + 刷新 ──
        self.collapse_btn = QPushButton("‹  " + tr("collapse_sidebar"))
        self.collapse_btn.setObjectName("pipeToggle")
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.clicked.connect(self.toggle_collapsed)
        lay.addWidget(self.collapse_btn)

        prog = QWidget()
        prog.setObjectName("pipeProgress")
        pl = QVBoxLayout(prog)
        pl.setContentsMargins(4, 4, 4, 4)
        pl.setSpacing(4)
        top = QHBoxLayout()
        self.prog_title = QLabel(tr("stage_script"))
        self.prog_title.setObjectName("pipeProgLabel")
        self.progress = QLabel("1/4")
        self.progress.setObjectName("pipeProgLabel")
        top.addWidget(self.prog_title)
        top.addStretch(1)
        top.addWidget(self.progress)
        pl.addLayout(top)
        seg_row = QHBoxLayout()
        seg_row.setSpacing(4)
        self._segs: dict[str, QPushButton] = {}
        for key, label_key in PROGRESS_STEPS:
            seg = QPushButton()
            seg.setObjectName("pipeSeg")
            seg.setFixedHeight(6)
            seg.setCursor(Qt.PointingHandCursor)
            seg.setToolTip(tr(label_key))
            seg.clicked.connect(lambda _=False, kk=key: self.step_changed.emit(kk))
            self._segs[key] = seg
            seg_row.addWidget(seg, 1)
        pl.addLayout(seg_row)
        lab_row = QHBoxLayout()
        lab_row.setSpacing(4)
        self._seg_labels: dict[str, QLabel] = {}
        for key, label_key in PROGRESS_STEPS:
            lb = QLabel(tr(label_key))
            lb.setObjectName("pipeProgLabel")
            lb.setAlignment(Qt.AlignCenter)
            self._seg_labels[key] = lb
            lab_row.addWidget(lb, 1)
        pl.addLayout(lab_row)
        self.prog_box = prog
        lay.addWidget(prog)

        self.refresh_btn = QPushButton("⟳  " + tr("refresh_data"))
        self.refresh_btn.setObjectName("pipeToggle")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.clicked.connect(self.refresh_requested.emit)
        lay.addWidget(self.refresh_btn)

    # ── 折叠 ──
    def toggle_collapsed(self):
        self._collapsed = not self._collapsed
        self.setFixedWidth(44 if self._collapsed else 196)
        for k, b in self._btns.items():
            b.setText(f"   {STEP_ICONS[k]}" if self._collapsed
                      else f"   {STEP_ICONS[k]}  {tr(STEP_LABELS[k])}")
            b.setToolTip(tr(STEP_LABELS[k]) if self._collapsed else "")
        self.collapse_btn.setText("›" if self._collapsed else "‹  " + tr("collapse_sidebar"))
        self.refresh_btn.setText("⟳" if self._collapsed else "⟳  " + tr("refresh_data"))
        self.prog_box.setVisible(not self._collapsed)
        self._apply_visibility()

    # ── 状态 ──
    def set_active(self, key: str):
        self._active = key
        b = self._btns.get(key)
        if b and not b.isChecked():
            b.setChecked(True)
        self._refresh_sections()

    def set_step_states(self, states: dict):
        """states: {step_key: done|pending} —— 用于环节状态判定。"""
        self._states = states
        self._refresh_sections()

    def set_progress(self, current_key: str, done_keys: list):
        """四段跑马灯:当前段高亮 + 已完成段填色。"""
        order = [k for k, _ in PROGRESS_STEPS]
        idx = order.index(current_key) if current_key in order else 0
        for i, (key, label_key) in enumerate(PROGRESS_STEPS):
            seg = self._segs[key]
            seg.setProperty("state", "done" if key in done_keys else ("current" if i == idx else ""))
            seg.style().unpolish(seg)
            seg.style().polish(seg)
            lb = self._seg_labels[key]
            lb.setProperty("on", "1" if i == idx else "0")
            lb.setProperty("done", "1" if key in done_keys else "0")
            lb.style().unpolish(lb)
            lb.style().polish(lb)
        self.progress.setText(f"{idx + 1}/4")
        self.prog_title.setText(tr(PROGRESS_STEPS[idx][1]))

    def _refresh_sections(self):
        """环节状态:✓ 已完成 / ◐ 进行中(带「进行中」标签)/ · 未开始;整段不可用则隐藏。"""
        for sid, _, keys in NAV_SECTIONS:
            states = [self._states.get(k, "pending") for k in keys]
            usable = any(s != "locked" for s in states)
            self._section_hidden[sid] = not usable
            for k in keys:
                self._btns[k].setVisible(usable or self._collapsed)
                self._btns[k].setEnabled(self._states.get(k, "pending") != "locked")
            if not usable:
                continue
            if sid == "export":                       # 导出段不标状态(对齐原版 'none')
                self._section_state[sid].setText("·")
                self._section_state[sid].setProperty("done", "0")
                self._section_tag[sid].setVisible(False)
            else:
                done = all(s == "done" for s in states)
                started = any(s in ("done", "active") for s in states)
                active = not done and (SECTION_OF.get(self._active) == sid
                                       or (started and sid == "production"))
                lab = self._section_state[sid]
                lab.setText("✓" if done else ("◐" if active else "·"))
                lab.setProperty("done", "1" if (done or active) else "0")
                lab.style().unpolish(lab)
                lab.style().polish(lab)
                self._section_tag[sid].setVisible(active and not done)
        self._apply_visibility()

    def _apply_visibility(self):
        """折叠态 + 整段不可用的合并可见性。"""
        for sid, head in self._section_head.items():
            head.setVisible(not self._collapsed and not self._section_hidden.get(sid))
        for sid, _, keys in NAV_SECTIONS:
            if self._section_hidden.get(sid):
                continue
            for k in keys:
                self._btns[k].setVisible(True)


class EpisodePage(QWidget):
    back_requested = Signal()

    def __init__(self):
        super().__init__()
        self.drama_id = 0
        self.episode_id = 0
        self._step = "raw"
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
        root.setSpacing(10)

        # 顶栏
        top = QHBoxLayout()
        back = QPushButton("← " + tr("back"))
        back.clicked.connect(self.back_requested.emit)
        top.addWidget(back)
        self.title = W.h2("")
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(QLabel(tr("text_svc") + ":"))
        self.text_model = QComboBox()
        top.addWidget(self.text_model)
        top.addWidget(QLabel(tr("image_svc") + ":"))
        self.image_model = QComboBox()
        top.addWidget(self.image_model)
        top.addWidget(QLabel(tr("video_svc") + ":"))
        self.video_model = QComboBox()
        top.addWidget(self.video_model)
        top.addWidget(QLabel(tr("faceswap_svc") + ":"))
        self.face_model = QComboBox()
        top.addWidget(self.face_model)
        top.addWidget(QLabel(tr("resolution") + ":"))
        self.res_combo = QComboBox()
        for r in ("480p", "720p", "1080p"):
            self.res_combo.addItem(r)
        self.res_combo.setCurrentIndex(1)
        top.addWidget(self.res_combo)
        self.status_lab = QLabel("")
        self.status_lab.setObjectName("muted")
        top.addWidget(self.status_lab)
        self.task_btn = QPushButton(tr("tasks"))
        self.task_btn.clicked.connect(self._open_tasks)
        top.addWidget(self.task_btn)
        root.addLayout(top)
        self.subtitle = W.muted("")
        root.addWidget(self.subtitle)

        # 主体:侧栏 + 内容栈
        body = QSplitter(Qt.Horizontal)
        self.nav = StepNav()
        self.nav.step_changed.connect(self._goto_step)
        self.nav.refresh_requested.connect(self.refresh)
        body.addWidget(self.nav)

        self.stack_holder = QWidget()
        self.stack_lay = QVBoxLayout(self.stack_holder)
        self.stack_lay.setContentsMargins(0, 0, 0, 0)
        self.panels: dict[str, QWidget] = {}
        for k in STEPS:
            p = self._build_panel(k)
            self.panels[k] = p
            self.stack_lay.addWidget(p)
        body.addWidget(self.stack_holder)
        body.setStretchFactor(1, 1)
        root.addWidget(body, 1)
        TASKMGR.updated.connect(self._refresh_status)
        self._loading = False
        self._sb_split_running = False
        self._sb_split_task = 0

    # ── 数据加载 ──
    def load(self, drama_id: int, episode_id: int):
        self.drama_id, self.episode_id = drama_id, episode_id
        d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
        ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
        self._drama, self._ep = d, ep
        self.title.setText(f"{d['title']} · {tr('episode_n').format(ep['episode_number'])}")
        # 项目级内容语言:只影响 AI 产出(runner 全部显式传 lang=self._drama_lang)。
        # 绝不能拿它调 set_language() —— 那是界面语言的全局,被内容语言覆盖后,
        # 英文界面一进中文项目就被劫持回中文(还会误触发一次"语言已切换"重建)。
        from ..core.config import resolve_content_language
        self._drama_lang = resolve_content_language(drama_id)
        nc = db.q1("SELECT COUNT(*) c FROM episode_characters WHERE episode_id=?", (episode_id,))["c"]
        nb = db.q1("SELECT COUNT(*) c FROM storyboards WHERE episode_id=?", (episode_id,))["c"]
        self.subtitle.setText(f"{tr('characters_n', nc)} · {tr('segments', nb)}")
        self.res_combo.setCurrentText(ep["resolution"] or "720p")
        # 小说项目隐藏制作/导出;宣传项目隐藏漫画
        work = d["work_type"]
        for k in ("assets", "storyboard", "export"):
            self.panels[k].setVisible(work != "novel")
        self.panels["comic"].setVisible(work not in ("novel", "promotion", "video_clone"))
        self._reload_models()
        self._reload_raw()
        self._reload_rewrite()
        self._update_novel_gate()
        self._reload_assets()
        self._reload_storyboard()
        self._reload_comic()
        self._reload_export()
        self._goto_step("raw")

    def _reload_models(self):
        for combo, stype in ((self.text_model, "text"), (self.image_model, "image"),
                             (self.video_model, "video"), (self.face_model, "faceswap")):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr("configured"), None)
            for r in registry.list_configs(stype):
                combo.addItem(f"{r['remark'] or r['provider']}/{r['model']}", r["id"])
            # 恢复上次选择(全局记忆)
            saved = db.get_setting(f"yihao.model.{stype}")
            if saved:
                i = combo.findData(int(saved))
                if i >= 0:
                    combo.setCurrentIndex(i)
            combo.blockSignals(False)
            combo.currentIndexChanged.connect(lambda _i, c=combo, s=stype: self._remember_model(c, s))
        # 集级锁定(创建集后首次生成即锁定图片/视频配置,对齐原版)
        ep = getattr(self, "_ep", None)
        if ep:
            for combo, col in ((self.image_model, "image_config_id"), (self.video_model, "video_config_id")):
                locked = ep[col]
                if locked:
                    i = combo.findData(locked)
                    if i >= 0:
                        combo.blockSignals(True)
                        combo.setCurrentIndex(i)
                        combo.setItemText(i, "🔒 " + combo.itemText(i))
                        combo.blockSignals(False)
        self.video_model.currentIndexChanged.connect(self._sync_res_tiers)
        self._sync_res_tiers()
        saved_res = db.get_setting("yihao.resolution")
        if saved_res:
            i = self.res_combo.findText(saved_res)
            if i >= 0:
                self.res_combo.setCurrentIndex(i)
        self.res_combo.currentTextChanged.connect(lambda t: db.set_setting("yihao.resolution", t))

    def _remember_model(self, combo, stype: str):
        cid = combo.currentData()
        if cid:
            db.set_setting(f"yihao.model.{stype}", str(cid))
        # 集级锁定回写
        ep = getattr(self, "_ep", None)
        if ep:
            col = {"image": "image_config_id", "video": "video_config_id"}.get(stype)
            if col:
                db.ex(f"UPDATE episodes SET {col}=?, updated_at=? WHERE id=?",
                      (cid, db.now(), self.episode_id))
                self._ep = db.q1("SELECT * FROM episodes WHERE id=?", (self.episode_id,))

    def _sync_res_tiers(self):
        """分辨率档位随视频厂商联动(对齐原版 RESOLUTION_TIERS)。"""
        from ..ai.video_client import RESOLUTION_TIERS
        cid = self.video_model.currentData()
        provider = None
        if cid:
            row = db.q1("SELECT provider FROM ai_service_configs WHERE id=?", (cid,))
            provider = row["provider"] if row else None
        tiers = RESOLUTION_TIERS.get(provider or "", ["480p", "720p", "1080p"])
        cur = self.res_combo.currentText()
        self.res_combo.blockSignals(True)
        self.res_combo.clear()
        for t in tiers:
            self.res_combo.addItem(t)
        if cur in tiers:
            self.res_combo.setCurrentText(cur)
        self.res_combo.blockSignals(False)


    def _set_busy(self, on: bool, label: str = ""):
        """D 类:全局忙碌态(按钮禁用 + 状态栏提示),避免重复点击。"""
        self._busy = on
        self.status_lab.setText(("⏳ " + label) if on else "")

    def _goto_step(self, key: str):
        self._step = key
        self.nav.set_active(key)
        for k, p in self.panels.items():
            p.setVisible(k == key)
        self._sync_nav_progress(key)

    def _sync_nav_progress(self, key: str):
        """四段跑马灯跟随当前步骤:导出归到「漫画」段(与原版四段一致)。"""
        order = [k for k, _ in PROGRESS_STEPS]
        cur = key if key in order else ("comic" if key == "export" else order[0])
        self.nav.set_progress(cur, self._progress_done_keys())

    def _progress_done_keys(self) -> list:
        """已完成的四段(对齐原版 mainStageDone):剧本有内容 / 资产齐 / 视频齐 / 漫画齐。"""
        if not self.episode_id:
            return []
        ep = db.q1("SELECT content FROM episodes WHERE id=?", (self.episode_id,))
        script_ok = bool((ep["content"] if ep else "") or "")
        if not script_ok:
            d = db.q1("SELECT novel_outline, novel_chapters FROM dramas WHERE id=?",
                      (self.drama_id,)) if self.drama_id else None
            script_ok = bool(d and ((d["novel_outline"] or "").strip()
                                    or (db.jload(d["novel_chapters"], []) or [])))
        nb, nv = db.q1("""SELECT COUNT(*) c,
                          SUM(CASE WHEN COALESCE(video_url, composed_video_url,'')!='' THEN 1 ELSE 0 END) v
                          FROM storyboards WHERE episode_id=? AND deleted_at IS NULL""",
                       (self.episode_id,))
        na, nr = db.q1("""SELECT COUNT(*) c,
                          SUM(CASE WHEN COALESCE(c.image_url,'')!='' THEN 1 ELSE 0 END) r
                          FROM episode_characters ec JOIN characters c ON c.id=ec.character_id
                          WHERE ec.episode_id=?""", (self.episode_id,))
        ns, nrs = db.q1("""SELECT COUNT(*) c,
                           SUM(CASE WHEN COALESCE(s.image_url,'')!='' THEN 1 ELSE 0 END) r
                           FROM episode_scenes es JOIN scenes s ON s.id=es.scene_id
                           WHERE es.episode_id=?""", (self.episode_id,))
        np, nrp = db.q1("""SELECT COUNT(*) c,
                           SUM(CASE WHEN COALESCE(p.image_url,'')!='' THEN 1 ELSE 0 END) r
                           FROM episode_props ep JOIN props p ON p.id=ep.prop_id
                           WHERE ep.episode_id=?""", (self.episode_id,))
        nc, nci = db.q1("""SELECT COUNT(*) c,
                           SUM(CASE WHEN COALESCE(image_url,'')!='' THEN 1 ELSE 0 END) i
                           FROM comic_panels WHERE episode_id=?""", (self.episode_id,))
        done = []
        if script_ok:
            done.append("raw")
        total_assets = (na or 0) + (ns or 0) + (np or 0)
        ready_assets = (nr or 0) + (nrs or 0) + (nrp or 0)
        if total_assets and ready_assets == total_assets:
            done.append("assets")
        if nb and (nv or 0) == nb:
            done.append("storyboard")
        if nc and (nci or 0) == nc:
            done.append("comic")
        return done

    def _step_states(self) -> dict:
        """环节状态供侧栏 ✓ 标记与可用性:done / pending / locked(项目类型不支持)。"""
        done_keys = self._progress_done_keys()
        work = self._drama["work_type"] if self._drama else None
        st = {}
        for k in STEPS:
            if k in ("assets", "storyboard", "export") and work == "novel":
                st[k] = "locked"
            elif k == "comic" and work in ("novel", "promotion", "video_clone"):
                st[k] = "locked"
            elif k == "export":
                st[k] = "done" if ("comic" in done_keys or "storyboard" in done_keys) else "pending"
            elif k in ("raw", "rewrite"):
                st[k] = "done" if "raw" in done_keys else "pending"
            else:
                st[k] = "done" if k in done_keys else "pending"
        return st

    def _open_tasks(self):
        """右侧任务抽屉(对齐原版 .task-drawer):挂在窗口最上层,点遮罩关闭。"""
        from .task_panel import TaskDrawer
        win = self.window()
        if getattr(win, "_task_drawer", None) is not None:
            try:
                win._task_drawer.close()
            except RuntimeError:
                pass
        drawer = TaskDrawer(self.episode_id, win)
        drawer.closed.connect(lambda d: self._close_task_drawer(d))
        win._task_drawer = drawer
        win.stack.addWidget(drawer)
        win.stack.setCurrentWidget(drawer)
        return drawer

    def _close_task_drawer(self, drawer):
        host = self.window()
        if host._task_drawer is drawer:
            host._task_drawer = None
        host.stack.removeWidget(drawer)
        drawer.deleteLater()

    def refresh(self):
        """侧栏「刷新数据」:重载当前集与各面板状态。"""
        if not self.episode_id:
            return
        keep = self._step
        self.load(self.drama_id, self.episode_id)
        self._goto_step(keep)
        ok(tr("refresh_data"))

    def _refresh_status(self):
        if self._loading or not self.episode_id:
            return
        self._loading = True
        try:
            nb = db.q1("SELECT COUNT(*) c FROM storyboards WHERE episode_id=?", (self.episode_id,))["c"]
            nc = db.q1("SELECT COUNT(*) c FROM episode_characters WHERE episode_id=?", (self.episode_id,))["c"]
            self.subtitle.setText(f"{tr('characters_n', nc)} · {tr('segments', nb)}")
            stats = TASKMGR.ep_video_stats(self.episode_id)
            self._update_metric_pills(TASKMGR.ep_video_stats(self.episode_id))
            active = TASKMGR.active_count()
            self.task_btn.setText(f"☰ {tr('tasks')}" + (f" · {active}" if active else ""))
            self.nav.set_step_states(self._step_states())
            self._sync_nav_progress(self._step)
        finally:
            self._loading = False

    # ── 阶段① 原始内容 ──
    # 主编辑区需要撑满剩余高度(自身内部滚动),其余阶段由外层滚动区承载
    FILL_PANELS = ("raw", "rewrite")

    def _build_panel(self, key: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        getattr(self, f"_panel_{key}")(lay)
        if key not in self.FILL_PANELS:
            lay.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
            scroll.setWidget(w)
            return scroll
        # 撑满型:直接返回,文本框自身内部滚动
        return w

    def _panel_raw(self, lay):
        """原始内容页:步骤指示器 + 字数统计在左,操作按钮群在右(对齐 .step-toolbar)。"""
        from . import episode_cards as C
        from .ai_edit_dialog import install_ai_edit_shortcut
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("taskHead")
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._step_indicator("01", tr("raw_content")))
        self.raw_count = QLabel("")
        self.raw_count.setObjectName("muted")
        row.addWidget(self.raw_count)
        self.words_spin = QSpinBox()
        self.words_spin.setRange(0, 200000)
        self.words_spin.setFixedWidth(96)
        self.words_spin.setSpecialValueText(tr("no_limit"))
        self.words_spin.setToolTip(tr("target_words"))
        self.words_spin.valueChanged.connect(lambda _v: self._update_raw_count())
        row.addWidget(self.words_spin)
        row.addStretch(1)

        # 文风:6 预设 + 自定义(对齐原版 NOVEL_STYLES)
        from ..pipeline.novel import NOVEL_STYLES, NOVEL_STYLE_CUSTOM
        row.addWidget(QLabel(tr("style_label")))
        self.style_combo = QComboBox()
        self.style_combo.setMinimumWidth(116)
        self.style_combo.addItem("", "")
        for name, prompt in NOVEL_STYLES:
            # 名字走 tr(),提示词保持中文 —— 后者是发给模型的指令,不是界面文案
            self.style_combo.addItem(tr(name), prompt)
        self.style_combo.addItem(tr("style_custom"), NOVEL_STYLE_CUSTOM)
        self.style_combo.currentIndexChanged.connect(self._on_style_pick)
        row.addWidget(self.style_combo)

        self.chapter_name_btn = QPushButton("✎ " + tr("gen_title"))
        self.chapter_name_btn.setToolTip(tr("gen_title_tip"))
        self.chapter_name_btn.clicked.connect(lambda: self._gen_chapter_title())
        row.addWidget(self.chapter_name_btn)
        self.novel_btn = W.primary_btn("📕 " + tr("ai_novel"))
        self.novel_btn.clicked.connect(self._ai_novel)
        row.addWidget(self.novel_btn)
        self.batch_btn = QPushButton("📋 " + tr("batch_write"))
        self.batch_btn.clicked.connect(self._batch_novel)
        row.addWidget(self.batch_btn)
        self.review_badge = QPushButton("")
        self.review_badge.setToolTip(tr("review_open_hint"))
        self.review_badge.clicked.connect(self._show_review_detail)
        self.review_badge.setVisible(False)
        row.addWidget(self.review_badge)
        save_btn = W.primary_btn("💾 " + tr("save"))
        save_btn.clicked.connect(self._save_raw)
        row.addWidget(save_btn)
        bl.addLayout(row)

        self.gate_lab = W.muted("")
        self.gate_lab.setStyleSheet(
            "color:#ad6800; background:#fff7e6; border-radius:6px; padding:4px 8px;")
        self.gate_lab.setVisible(False)
        bl.addWidget(self.gate_lab)
        lay.addWidget(bar)

        # 自定义文风编辑区(选「自定义…」时展开)
        self.style_edit = C.SaveOnBlurEdit()
        self.style_edit.setPlaceholderText(tr("style_label"))
        self.style_edit.setFixedHeight(52)
        self.style_edit.setToolTip(tr("style_custom_tip"))
        self.style_edit.editing_finished.connect(self._save_novel_style)
        self.style_edit.setVisible(False)
        lay.addWidget(self.style_edit)

        self.raw_edit = C.SaveOnBlurEdit()
        self.raw_edit.setPlaceholderText(tr("paste_hint"))
        self.raw_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        install_ai_edit_shortcut(self.raw_edit, self._open_ai_edit)
        self.raw_edit.setContextMenuPolicy(Qt.CustomContextMenu)
        ai_btn = QPushButton("✨ " + tr("ai_edit"))
        ai_btn.setToolTip(tr("ai_edit_tip"))
        ai_btn.clicked.connect(lambda: self._open_ai_edit(self.raw_edit))
        raw_row = QHBoxLayout()
        raw_row.setContentsMargins(12, 4, 12, 0)
        raw_row.addWidget(ai_btn)
        raw_row.addStretch(1)
        lay.addLayout(raw_row)
        lay.addWidget(self.raw_edit, 1)

        # 小说线第二行:审校 / 改稿 / 朗读
        bar2 = QFrame()
        bar2.setObjectName("taskHead")
        b2 = QHBoxLayout(bar2)
        b2.setContentsMargins(12, 6, 12, 6)
        b2.setSpacing(8)
        self.review_btn = QPushButton("🔎 " + tr("ai_review"))
        self.review_btn.setToolTip(tr("ai_review_tip"))
        self.review_btn.clicked.connect(self._review_chapter)
        b2.addWidget(self.review_btn)
        self.summary_btn = QPushButton("✅ " + tr("review_summary"))
        self.summary_btn.clicked.connect(self._open_review_summary)
        b2.addWidget(self.summary_btn)
        read_btn = QPushButton("🔊 " + tr("read_aloud"))
        read_btn.clicked.connect(self._read_aloud)
        b2.addWidget(read_btn)
        self.ledger_btn = WaitingButton("🧾 " + tr("state_ledger"))
        self.ledger_btn.setToolTip(tr("state_ledger_tip"))
        self.ledger_btn.clicked.connect(self._update_ledger)
        b2.addWidget(self.ledger_btn)
        self.edit_instr = QLineEdit()
        self.edit_instr.setPlaceholderText(tr("edit_instr_ph"))
        edit_btn = QPushButton("✏ " + tr("edit_chapter"))
        edit_btn.clicked.connect(self._edit_chapter)
        b2.addWidget(self.edit_instr, 1)
        b2.addWidget(edit_btn)
        lay.addWidget(bar2)
        self._update_raw_count()

    def _step_indicator(self, num: str, name: str) -> QWidget:
        """步骤指示器:方块序号 + 名称(对齐 .step-indicator)。"""
        box = QWidget()
        box.setStyleSheet("background:transparent; border:none;")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(7)
        chip = QLabel(num)
        chip.setFixedSize(26, 26)
        chip.setAlignment(Qt.AlignCenter)
        chip.setStyleSheet(
            "background:#fdf0e6; color:#f97316; border-radius:10px;"
            "font-family:monospace; font-size:10px; font-weight:800;")
        lay.addWidget(chip)
        lab = QLabel(name)
        lab.setStyleSheet("font-size:12.5px; font-weight:700;")
        lay.addWidget(lab)
        return box

    def _update_raw_count(self):
        n = len(self.raw_edit.toPlainText()) if hasattr(self, "raw_edit") else 0
        target = self.words_spin.value() if hasattr(self, "words_spin") else 0
        self.raw_count.setText(tr("raw_count", n, target if target else "∞"))

    def _reload_raw(self):
        from ..pipeline import novel as novel_pipe
        ep = self._ep
        self.raw_edit.setPlainText(ep["content"] or "")
        self.words_spin.blockSignals(True)
        self.words_spin.setValue(ep["target_words"] or 0)
        self.words_spin.blockSignals(False)
        cur = novel_pipe.get_novel_style(self.drama_id)
        idx = self.style_combo.findData(cur)
        if idx < 0 and cur:
            idx = self.style_combo.findData(novel_pipe.NOVEL_STYLE_CUSTOM)
        self.style_combo.blockSignals(True)
        self.style_combo.setCurrentIndex(max(0, idx))
        self.style_combo.blockSignals(False)
        self.style_edit.blockSignals(True)
        self.style_edit.setPlainText(cur)
        self.style_edit.blockSignals(False)
        self.style_edit.setVisible(self.style_combo.currentData() == novel_pipe.NOVEL_STYLE_CUSTOM)
        self._update_raw_count()
        issues = self._review_issues()
        self.review_badge.setText(tr("review_n", len(issues)))
        self.review_badge.setVisible(bool(issues))
        # 「章节名」按钮:标题缺失且已有正文才出现(对齐原版 chapterNameMissing)
        has = bool((ep["content"] or "").strip())
        self.chapter_name_btn.setVisible(has and _chapter_name_missing(dict(ep)))
        self._update_novel_gate()

    def _on_style_pick(self):
        """选预设即写本项目;选「自定义…」展开编辑框继续改。"""
        from ..pipeline import novel as novel_pipe
        data = self.style_combo.currentData()
        custom = data == novel_pipe.NOVEL_STYLE_CUSTOM
        self.style_edit.setVisible(custom)
        if not data:
            return
        if custom:
            self.style_edit.setFocus()
            return
        self.style_edit.setPlainText(data)
        self._save_novel_style()

    def _save_novel_style(self):
        from ..pipeline import novel as novel_pipe
        if not self.drama_id:
            return
        text = self.style_edit.toPlainText().strip()
        if text == novel_pipe.get_novel_style(self.drama_id):
            return
        novel_pipe.set_novel_style(self.drama_id, text)
        idx = self.style_combo.findData(text)
        self.style_combo.blockSignals(True)
        self.style_combo.setCurrentIndex(
            idx if idx >= 0 else self.style_combo.findData(novel_pipe.NOVEL_STYLE_CUSTOM))
        self.style_combo.blockSignals(False)
        ok(tr("style_saved"))


    def _gen_chapter_title(self):
        """AI 生成章节名:优先从正文首行提取,提取不到才调模型。"""
        from ..core.taskmgr import TASKMGR

        def job(tid):
            from ..pipeline import novel as novel_pipe
            return novel_pipe.gen_chapter_title(self.episode_id)

        def done(tid, result, error):
            if error:
                err(error)
                return
            name, src = result
            ok((tr("已提取章节名:") if src == "content" else tr("章节名已写入:")) + str(name))
            self._ep = db.q1("SELECT * FROM episodes WHERE id=?", (self.episode_id,))
            self.title.setText(f"{self._drama['title']} · {tr('episode_n').format(self._ep['episode_number'])}")
            self.chapter_name_btn.setVisible(False)

        TASKMGR.submit("novel_title", job, done, episode_id=self.episode_id, drama_id=self.drama_id)

    def _generate_one(self, sb_id: int):
        """单镜生成视频(任务行右侧操作键 / 主行动键)。"""
        self._one_video(sb_id)

    def _update_ledger(self):
        """手动重跑本章状态台账(提取 → 合并 → Jev 门控);对应参考项目 update-state-ledger。"""
        from ..core.preflight import ensure_ready
        if not ensure_ready("text", None):
            return
        btn = self.ledger_btn
        btn.busy(tr("updating_ledger"))

        def job(tid):
            from ..pipeline import novel as novel_pipe
            return novel_pipe.update_state_ledger(
                self.episode_id, config_id=self.text_model.currentData())

        def done(tid, result, error):
            btn.idle()
            if error:
                err(error)
                return
            jev = (result or {}).get("jev") or {}
            verdict = jev.get("verdict")
            n = (result or {}).get("changes", 0)
            if verdict == "conflict":
                warn(f"{tr('ledger_conflict')}{int(round((jev.get('conflict') or 0) * 100))}% · {tr('see_review')}")
            elif verdict == "skipped":
                info(f"{tr('ledger_ok')} {n} · Jev {tr('skipped')}({jev.get('reason', '')})")
            else:
                ok(f"{tr('ledger_ok')} {n}")

        TASKMGR.submit("prompt", job, done, episode_id=self.episode_id, drama_id=self.drama_id)

    def _open_ai_edit(self, editor):
        """Ctrl+L:选中→改写选中;未选中→光标处插入;可勾选整章处理。"""
        from .ai_edit_dialog import AiEditDialog
        text = editor.toPlainText()
        if not text.strip():
            return
        sel = editor.textCursor()
        start, end = sel.selectionStart(), sel.selectionEnd()
        mode = "selection" if end > start else "insert"
        col = "content" if editor is self.raw_edit else "script_content"
        def apply(new_text: str, s: int, e: int):
            editor.setPlainText(new_text)
            if col == "content":
                db.ex("UPDATE episodes SET content=?, updated_at=? WHERE id=?",
                      (new_text, db.now(), self.episode_id))
                self._ep = db.q1("SELECT * FROM episodes WHERE id=?", (self.episode_id,))
            else:
                self._save_script()
        AiEditDialog(self, editor, mode, start, end, apply, episode_id=self.episode_id).exec()

    def _save_raw(self):
        db.ex("UPDATE episodes SET content=?, target_words=?, updated_at=? WHERE id=?",
              (self.raw_edit.toPlainText(), self.words_spin.value(), db.now(), self.episode_id))
        self._ep = db.q1("SELECT * FROM episodes WHERE id=?", (self.episode_id,))
        QMessageBox.information(self, tr("save"), "OK")

    def _novel_redline_hint(self) -> str:
        """写作红线闸门:缺哪几步(对齐原版 batchMissingSteps);齐全返回空串。"""
        try:
            # 直接从库取 work_type,避免 _drama 未就绪导致闸门失效
            row = db.q1("SELECT work_type FROM dramas WHERE id=?", (self.drama_id,))
            if not row or (row["work_type"] or "") != "novel":
                return ""
            from .novel_dialogs import gate_message
            missing = gate_message(self.drama_id)
            return f"请先完成步骤 {missing} 的设定" if missing else ""
        except Exception:  # noqa: BLE001
            return ""

    def _update_novel_gate(self):
        """设定未齐时禁用「AI 生成小说/批量写」并在工具条提示(对齐原版前端守卫)。"""
        hint = self._novel_redline_hint()
        if hasattr(self, "novel_btn"):
            self.novel_btn.setEnabled(not hint)
            self.novel_btn.setToolTip(hint or tr("AI 生成本章"))
        if hasattr(self, "batch_btn"):
            self.batch_btn.setEnabled(not hint)
            self.batch_btn.setToolTip(hint or tr("批量写本章及后续"))
        if hasattr(self, "gate_lab"):
            self.gate_lab.setText(hint)
            self.gate_lab.setVisible(bool(hint))

    def _ai_novel(self):
        from ..pipeline import novel as novel_pipe
        hint = self._novel_redline_hint()
        if hint:
            warn(hint)
            return
        def job(tid):
            if not db.q1("SELECT novel_outline FROM dramas WHERE id=?", (self.drama_id,))["novel_outline"]:
                idea = self.raw_edit.toPlainText().strip()[:6000] or self._drama["title"]
                novel_pipe.plan_novel(self.drama_id, idea, config_id=self.text_model.currentData())
            return novel_pipe.write_chapter_with_review(self.episode_id, config_id=self.text_model.currentData())
        def done(tid, result, error):
            if error:
                err("AI")
            else:
                self._reload_raw()
                r = (result or {})
                msg = tr("本章已生成") + (tr(";审校发现问题并已自动修复一轮 ✅") if r.get("fixed") else "")
                QMessageBox.information(self, tr("ai_novel"), msg)
        self._save_raw_silent()
        TASKMGR.submit("novel", job, done, episode_id=self.episode_id, drama_id=self.drama_id)

    def _batch_novel(self):
        """批量写本章及后续(对齐原版未提交批次的语义重定义 + 进度条 + 阶段)。"""
        from ..core.preflight import ensure_ready
        # 设定未齐 → 不写小说(按钮虽已置灰,这里再拦一道,防止其它入口绕过)
        hint = self._novel_redline_hint()
        if hint:
            warn(hint)
            return
        if not ensure_ready("text", self._cfg_for("text")):
            return
        self._save_raw_silent()
        all_eps = [dict(r) for r in db.q(
            "SELECT * FROM episodes WHERE drama_id=? AND episode_number>=? ORDER BY episode_number",
            (self.drama_id, self._ep["episode_number"]))]
        cur = self._ep
        # 情形一:本章未写完(空 或 低于目标 80%)→ 确认后只重写本章
        body_len = len((cur["content"] or "").strip())
        target = cur["target_words"] or 3000
        if body_len < int(target * 0.8):
            if ask(self, tr("batch_write"),
                   f"第 {cur['episode_number']} 章"
                   + (f"现有 {body_len} 字,未达目标 {target} 字" if body_len else f"尚未写作(目标 {target} 字)")
                   + tr(",将重新生成。已有内容会被覆盖且无法撤销。确定继续?")):
                self._run_batch([cur["id"]], force=True)
            return
        # 情形二:本章已完成 → 取后续中「无正文」的前 10 章
        pending = [e for e in all_eps if e["episode_number"] > cur["episode_number"]
                   and len((e["content"] or "").strip()) < 200]
        if not pending:
            warn(tr("后续章节都已有正文,没有待写内容"))
            return
        self._run_batch([e["id"] for e in pending[:10]], force=False)

    def _run_batch(self, episode_ids: list[int], force: bool):
        """执行批量写章:三段式进度条 + 阶段显示 + 完成后提示。

        批量写作的所有入口都收口到这里,设定未齐一律不放行。
        """
        from ..pipeline import novel as novel_pipe
        hint = self._novel_redline_hint()
        if hint:
            warn(hint)
            return
        self._batch_ids = list(episode_ids)
        self._batch_done = 0
        self._batch_ok = 0
        self._batch_failed = 0
        self._batch_stage = ""
        self._batch_dialog = _BatchProgressDialog(self, len(episode_ids), self)
        self._batch_dialog.show()
        self._batch_start_ts = 0
        def job(tid):
            from ..core import taskmgr as TM
            self._batch_start_ts = 1
            def on_progress(done, total, num):
                self._batch_done = done
                from PySide6.QtCore import QMetaObject, Qt as _Qt
                def _ui():
                    if self._batch_dialog:
                        self._batch_dialog.update_progress(done, total)
                QMetaObject.invokeMethod(self, "_noop", _Qt.QueuedConnection)
            return novel_pipe.batch_write_chapters(
                self.drama_id, episode_ids, force=force,
                config_id=self.text_model.currentData(),
                lang=getattr(self, "_drama_lang", None),
                on_progress=on_progress)
        def done(tid, result, error):
            r = result or {}
            if error:
                r.setdefault("failed", len(episode_ids))
            self._batch_ok = r.get("ok", 0)
            self._batch_failed = r.get("failed", 0)
            if self._batch_dialog:
                self._batch_dialog.finish(self._batch_ok, self._batch_failed)
            if r.get("ok"):
                ok(f"批量完成:{r['ok']} 章成功"
                   + (f",{r['failed']} 章失败" if r.get("failed") else ""))
            self._reload_raw()
        TASKMGR.submit("novel_batch", job, done, drama_id=self.drama_id, episode_id=self.episode_id)

    def _rewrite_done_chapters(self):
        """重写已完成章节(force=True 显式放行覆盖)。"""
        eps = [dict(r) for r in db.q(
            "SELECT * FROM episodes WHERE drama_id=? ORDER BY episode_number", (self.drama_id,))
            if len((r["content"] or "").strip()) >= 200]
        if not eps:
            return
        if not ask(self, tr("batch_write"),
                   f"将重新生成这 {len(eps)} 章,已有正文会被覆盖且无法撤销。确定继续?"):
            return
        self._run_batch([e["id"] for e in eps], force=True)

    def _chapter_running_stage(self, ep_id: int) -> str:
        """该集当前生成阶段(来自 sys_task.params.stage)。"""
        from ..core import taskmgr as TM
        row = db.q1("""SELECT id FROM sys_task WHERE episode_id=? AND status='processing'
                      ORDER BY id DESC LIMIT 1""", (ep_id,))
        return TM.get_stage(row["id"]) if row else ""

    def _review_issues(self) -> list:
        rj = db.jload(self._ep["review_json"], {}) or {}
        issues = rj.get("issues") or []
        for dim, v in (rj.get("dimensions") or {}).items():
            if isinstance(v, dict) and not v.get("pass", True):
                for s in (v.get("issues") or []):
                    issues.append(f"[{dim}] {s}")
        return issues

    def _show_review_detail(self):
        from .batch_dialogs import ReviewPanelDialog
        issues = self._review_issues()
        if not issues:
            info(tr("本章没有未处理的审校问题"))
            return
        ReviewPanelDialog(self, issues, self._ep["episode_number"], self._ep["title"] or "").exec()

    def _open_review_summary(self):
        from ..pipeline import novel as N
        from .batch_dialogs import ReviewSummaryDialog
        data = N.review_summary(self.drama_id)
        ReviewSummaryDialog(self, data, on_goto=self._goto_episode_by_id).exec()

    def _goto_episode_by_id(self, episode_id: int):
        ep = db.q1("SELECT drama_id, episode_number FROM episodes WHERE id=?", (episode_id,))
        if ep and ep["drama_id"] == self.drama_id:
            self.load(self.drama_id, episode_id)
            self._goto_step("raw")

    def _read_aloud(self):
        from ..core.preflight import ensure_ready
        if not ensure_ready("tts", None):
            return
        from ..pipeline import novel as N
        def job(tid):
            return N.read_aloud(self.episode_id)
        def done(tid, result, error):
            if error:
                err(error); return
            import os
            from ..core import config
            p = config.media_url_to_path(result["audio_url"])
            if p.exists():
                os.startfile(str(p))
            ok(f"已合成朗读音频({result['chunks']} 段)")
        TASKMGR.submit("tts", job, done, episode_id=self.episode_id)

    def _open_plan(self):
        from .novel_dialogs import NovelPlanDialog
        self._save_raw_silent()
        NovelPlanDialog(self, self.drama_id).exec()

    def _review_chapter(self):
        self._save_raw_silent()
        from .novel_dialogs import ReviewDialog
        from ..pipeline import novel as novel_pipe
        def job(tid):
            return novel_pipe.review_chapter(self.episode_id, config_id=self.text_model.currentData())
        def done(tid, result, error):
            if error:
                err("AI")
            else:
                ReviewDialog(self, result or {}, self._ep["episode_number"]).exec()
        TASKMGR.submit("review", job, done, episode_id=self.episode_id)

    def _edit_chapter(self):
        instr = self.edit_instr.text().strip()
        if not instr:
            self.edit_instr.setFocus()
            return
        self._save_raw_silent()
        from ..pipeline import novel as novel_pipe
        def job(tid):
            return novel_pipe.edit_chapter(self.episode_id, instr, config_id=self.text_model.currentData())
        def done(tid, result, error):
            if error:
                err("AI")
            else:
                self._reload_raw()
                self.edit_instr.clear()
        TASKMGR.submit("novel_edit", job, done, episode_id=self.episode_id)

    def _save_raw_silent(self):
        db.ex("UPDATE episodes SET content=?, target_words=?, updated_at=? WHERE id=?",
              (self.raw_edit.toPlainText(), self.words_spin.value(), db.now(), self.episode_id))
        db.set_setting("novel_style", self.style_edit.toPlainText().strip())   # 全局兜底
        self._save_novel_style()                                  # 项目级为准
        self._ep = db.q1("SELECT * FROM episodes WHERE id=?", (self.episode_id,))

    # ── 阶段② AI 改写 ──
    def _panel_rewrite(self, lay):
        """AI 改写页:步骤指示器 + 字数 + 文风 + 改写/保存,正文区三态(空/加载/编辑)。"""
        from . import episode_cards as C
        from .ai_edit_dialog import install_ai_edit_shortcut
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(0)
        bar = QFrame()
        bar.setObjectName("taskHead")
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self._step_indicator("02", tr("ai_rewrite")))
        self.script_len_lab = W.muted("")
        row.addWidget(self.script_len_lab)
        row.addStretch(1)
        row.addWidget(QLabel(tr("style_label")))
        self.style_combo2 = QComboBox()
        self.style_combo2.setMinimumWidth(116)
        self.style_combo2.addItem("", "")
        for name, prompt in self.style_combo_items():
            self.style_combo2.addItem(tr(name), prompt)
        self.style_combo2.addItem(tr("style_custom"), "__custom__")
        self.style_combo2.currentIndexChanged.connect(self._on_style_pick2)
        row.addWidget(self.style_combo2)
        self.rewrite_btn = W.primary_btn("⚡ " + tr("ai_to_script"))
        self.rewrite_btn.setToolTip(tr("ai_to_script_tip"))
        self.rewrite_btn.clicked.connect(self._rewrite)
        row.addWidget(self.rewrite_btn)
        rewrite_again = QPushButton("↻ " + tr("rewrite"))
        rewrite_again.clicked.connect(self._rewrite)
        row.addWidget(rewrite_again)
        # 保存:dirty 门控(无改动置灰)+ 落库 + toast —— 该编辑框此前无保存机制,手改会静默丢失
        self.script_save_btn = W.primary_btn("💾 " + tr("save"))
        self.script_save_btn.clicked.connect(self._save_script)
        row.addWidget(self.script_save_btn)
        bl.addLayout(row)
        lay.addWidget(bar)

        self.rewrite_empty = C.empty_state("→", tr("rewrite_empty_title"), tr("rewrite_empty_desc"))
        start_btn = W.primary_btn(tr("start_rewrite"))
        start_btn.clicked.connect(self._rewrite)
        self.rewrite_empty.layout().addWidget(start_btn, 0, Qt.AlignCenter)
        lay.addWidget(self.rewrite_empty)

        self.rewrite_loading = QLabel("⠋ " + tr("rewriting"))
        self.rewrite_loading.setObjectName("muted")
        self.rewrite_loading.setAlignment(Qt.AlignCenter)
        self.rewrite_loading.setVisible(False)
        lay.addWidget(self.rewrite_loading)

        self.script_edit = C.SaveOnBlurEdit()
        self.script_edit.setPlaceholderText(tr("script_ph"))
        self.script_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        install_ai_edit_shortcut(self.script_edit, self._open_ai_edit)
        self.script_edit.textChanged.connect(self._update_script_dirty)
        lay.addWidget(self.script_edit, 1)
        ai_row = QHBoxLayout()
        ai_row.setContentsMargins(12, 4, 12, 0)
        ai_btn2 = QPushButton("✨ " + tr("ai_edit"))
        ai_btn2.setToolTip(tr("ai_edit_tip"))
        ai_btn2.clicked.connect(lambda: self._open_ai_edit(self.script_edit))
        ai_row.addWidget(ai_btn2)
        ai_row.addStretch(1)
        lay.addLayout(ai_row)

    def style_combo_items(self):
        from ..pipeline.novel import NOVEL_STYLES
        return NOVEL_STYLES

    def _on_style_pick2(self):
        from ..pipeline import novel as novel_pipe
        data = self.style_combo2.currentData()
        if data and data != "__custom__":
            novel_pipe.set_novel_style(self.drama_id, data)
            self.style_combo.blockSignals(True)
            self.style_combo.setCurrentIndex(max(0, self.style_combo.findData(data)))
            self.style_combo.blockSignals(False)

    def _update_script_dirty(self):
        """保存按钮的 dirty 门控:与库内内容一致时置灰。"""
        if not hasattr(self, "script_save_btn"):
            return
        cur = self.script_edit.toPlainText()
        same = cur == (self._ep["script_content"] or "")
        self.script_save_btn.setEnabled(not same)
        self.script_save_btn.setToolTip(tr("save") if same else tr("save_dirty_hint"))

    def _reload_rewrite(self):
        from ..pipeline import novel as novel_pipe
        text = self._ep["script_content"] or ""
        self.script_edit.blockSignals(True)
        self.script_edit.setPlainText(text)
        self.script_edit.blockSignals(False)
        self._update_script_dirty()
        self.script_len_lab.setText(tr("chars_n", len(text)) if text else "")
        has = bool(text)
        self.rewrite_empty.setVisible(not has)
        self.script_edit.setVisible(has)
        cur = novel_pipe.get_novel_style(self.drama_id)
        idx = self.style_combo2.findData(cur)
        if idx < 0 and cur:
            idx = self.style_combo2.findData("__custom__")
        self.style_combo2.blockSignals(True)
        self.style_combo2.setCurrentIndex(max(0, idx))
        self.style_combo2.blockSignals(False)
        self.rewrite_again = getattr(self, "rewrite_again", None)
        self.rewrite_btn.setEnabled(True)

    def _rewrite(self):
        from ..pipeline import novel as novel_pipe
        self._save_raw_silent()
        style = novel_pipe.get_novel_style(self.drama_id)
        self.rewrite_loading.setVisible(True)
        self.rewrite_empty.setVisible(False)
        btn = getattr(self, "rewrite_btn", None)
        if btn:
            btn.setEnabled(False)
        def job(tid):
            return rewriter.rewrite_script(self.episode_id, style,
                                           config_id=self.text_model.currentData(), lang=self._drama_lang)
        def done(tid, result, error):
            self.rewrite_loading.setVisible(False)
            if btn:
                btn.setEnabled(True)
            if error:
                err("AI")
                self._reload_rewrite()
                return
            self._ep = db.q1("SELECT * FROM episodes WHERE id=?", (self.episode_id,))
            self._reload_rewrite()
        TASKMGR.submit("script", job, done, episode_id=self.episode_id, drama_id=self.drama_id)

    def _save_script(self):
        db.ex("UPDATE episodes SET script_content=?, updated_at=? WHERE id=?",
              (self.script_edit.toPlainText(), db.now(), self.episode_id))
        self._ep = db.q1("SELECT * FROM episodes WHERE id=?", (self.episode_id,))
        self._update_script_dirty()
        ok(tr("script_saved"))

    # ── 阶段③ 视漫制作(资产) ──
    def _panel_assets(self, lay):
        from . import episode_cards as C
        lay.setContentsMargins(10, 8, 12, 10)
        lay.setSpacing(8)

        # ── 工具条 .prod-section-bar:胶囊页签 + 就绪计数 + 右侧动作区 ──
        bar = QHBoxLayout()
        bar.setSpacing(7)
        seg = QFrame()
        seg.setObjectName("segWrap")
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(2, 2, 2, 2)
        seg_lay.setSpacing(2)
        self._asset_mode = "regular"
        self._seg_btns = {}
        seg_group = QButtonGroup(self)
        seg_group.setExclusive(True)
        for key, label in (("regular", tr("normal_assets")), ("comic", tr("comic_assets"))):
            b = QPushButton(label)
            b.setObjectName("segTab")
            b.setCheckable(True)
            b.setChecked(key == "regular")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._switch_asset_mode(k))
            seg_group.addButton(b)
            self._seg_btns[key] = b
            seg_lay.addWidget(b)
        bar.addWidget(seg)
        self.asset_stat = C.mono_tag("")
        bar.addWidget(self.asset_stat)
        bar.addStretch(1)
        self._extract_btns = {}
        for kind, key in (("characters", "re_extract_chars"), ("scenes", "re_extract_scenes"),
                          ("props", "re_extract_props")):
            b = QPushButton(tr(key))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=kind: self._extract(k))
            self._extract_btns[kind] = b
            bar.addWidget(b)
        self.extract_all_btn = W.primary_btn(tr("extract"))
        self.extract_all_btn.clicked.connect(lambda: self._extract("all"))
        bar.addWidget(self.extract_all_btn)
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setFixedHeight(18)
        bar.addWidget(divider)
        bar.addWidget(QLabel(tr("image_svc") + ":"))
        self.asset_model = QComboBox()
        self.asset_model.setFixedWidth(120)
        bar.addWidget(self.asset_model)
        self._batch_btns = {}
        for kind, key in (("characters", "batch_chars"), ("scenes", "batch_scenes"),
                          ("props", "batch_props")):
            b = WaitingButton(tr(key))
            b.clicked.connect(lambda _=False, k=kind: self._batch_images(k))
            self._batch_btns[kind] = b
            bar.addWidget(b)
        lay.addLayout(bar)

        # 漫画资产工具条(仅 comic 模式可见)
        self._comic_bar = QWidget()
        cb_lay = QHBoxLayout(self._comic_bar)
        cb_lay.setContentsMargins(0, 0, 0, 0)
        self._comic_batch = W.primary_btn("📕 " + tr("batch_comic_style"))
        self._comic_batch.setToolTip(tr("batch_comic_style_tip"))
        self._comic_batch.clicked.connect(self._batch_comic_assets)
        cb_lay.addWidget(self._comic_batch)
        cb_lay.addStretch(1)
        lay.addWidget(self._comic_bar)

        self.asset_stack = QStackedWidget()
        self.asset_stack.setObjectName("prodContent")

        # ── 常规资产:三段区块 + 网格 ──
        normal = QWidget()
        n_lay = QVBoxLayout(normal)
        n_lay.setContentsMargins(0, 4, 0, 4)
        n_lay.setSpacing(10)
        self.asset_sections: dict[str, dict] = {}
        for kind, title, add_label in (("characters", tr("chars"), tr("add")),
                                       ("scenes", tr("scenes"), tr("add")),
                                       ("props", tr("props"), tr("add"))):
            n_lay.addWidget(C.section_title(title, add_label))
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(10)
            n_lay.addWidget(grid_host)
            self.asset_sections[kind] = {"grid": grid, "host": grid_host, "empty": None}
        self.asset_empty = C.empty_state("🔍", tr("asset_empty_title"), tr("asset_empty_desc"))
        n_lay.addWidget(self.asset_empty)
        n_lay.addStretch(1)
        self.asset_stack.addWidget(C.scroll_host(normal))

        # ── 漫画资产:三段区块 + 横条 ──
        comic = QWidget()
        c_lay = QVBoxLayout(comic)
        c_lay.setContentsMargins(0, 4, 0, 4)
        c_lay.setSpacing(12)
        self.comic_asset_sections: dict[str, dict] = {}
        for kind, title in (("characters", tr("chars")), ("scenes", tr("scenes")),
                            ("props", tr("props"))):
            c_lay.addWidget(C.section_title(title))
            host = QWidget()
            hl = QVBoxLayout(host)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(6)
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(8)
            grid.setVerticalSpacing(8)
            hl.addLayout(grid)
            c_lay.addWidget(host)
            self.comic_asset_sections[kind] = {"grid": grid, "host": host}
        self.comic_asset_empty = C.empty_state("📕", tr("comic_asset_empty"))
        c_lay.addWidget(self.comic_asset_empty)
        c_lay.addStretch(1)
        self.asset_stack.addWidget(C.scroll_host(comic))
        lay.addWidget(self.asset_stack, 1)
        self._switch_asset_mode("regular")

    def _switch_asset_mode(self, mode: str):
        """常规资产 / 漫画资产(对齐 .asset-view-tabs)。"""
        self._asset_mode = mode
        self.asset_stack.setCurrentIndex(0 if mode == "regular" else 1)
        for b in self._extract_btns.values():
            b.setVisible(mode == "regular")
        self.extract_all_btn.setVisible(mode == "regular")
        self.asset_model.setVisible(mode == "regular")
        for b in self._batch_btns.values():
            b.setVisible(mode == "regular")
        self._comic_bar.setVisible(mode == "comic")
        self._reload_assets()

    def _gen_comic_asset(self, kind: str, row_id: int):
        from ..pipeline import comic as comic_pipe
        def job(tid):
            return comic_pipe.comic_asset_image(self.drama_id, kind, row_id,
                                                config_id=self.image_model.currentData())
        def done(tid, result, error):
            if error:
                err("AI")
            self._reload_comic_assets()
        TASKMGR.submit("image", job, done, drama_id=self.drama_id)

    def _batch_comic_assets(self):
        for kind, table in (("character", "characters"), ("scene", "scenes"), ("prop", "props")):
            for r in db.q(f"SELECT id FROM {table} WHERE drama_id=? AND comic_image_url IS NULL", (self.drama_id,)):
                self._gen_comic_asset(kind, r["id"])

    def _reload_comic_assets(self):
        if not getattr(self, "comic_asset_list", None):
            return
        while self.comic_asset_list.count():
            item = self.comic_asset_list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for kind, table, label in (("character", "characters", tr("chars")),
                                   ("scene", "scenes", tr("scenes")),
                                   ("prop", "props", tr("props"))):
            for r in db.q(f"SELECT * FROM {table} WHERE drama_id=? ORDER BY id", (self.drama_id,)):
                box = W.make_card()
                lay = QHBoxLayout(box)
                lay.setContentsMargins(10, 6, 10, 6)
                img = QLabel()
                img.setPixmap(W.pixmap_from_media(r["comic_image_url"], 72))
                img.setFixedWidth(80)
                lay.addWidget(img)
                name = W.h2(r["name"])
                lay.addWidget(name)
                lay.addWidget(W.tag(label))
                if r["comic_image_url"]:
                    lay.addWidget(W.tag(tr("generated")))
                lay.addStretch(1)
                btn = QPushButton(tr("redraw"))
                btn.clicked.connect(lambda _=False, k=kind, i=r["id"]: self._gen_comic_asset(k, i))
                lay.addWidget(btn)
                self.comic_asset_list.addWidget(box)

    def _extract(self, scope: str):
        def job(tid):
            return extract_pipe.extract_assets(self.episode_id, config_id=self.text_model.currentData(), lang=self._drama_lang)
        def done(tid, result, error):
            if error:
                err("AI")
            else:
                self._reload_assets()
        TASKMGR.submit("extract", job, done, episode_id=self.episode_id, drama_id=self.drama_id)

    def _reload_assets(self):
        if not getattr(self, "asset_sections", None):
            return
        from . import episode_cards as C
        cols = {kind: 3 for kind in self.asset_sections}
        groups = {
            "characters": [dict(r) for r in db.q(
                "SELECT * FROM characters WHERE drama_id=? ORDER BY id", (self.drama_id,))],
            "scenes": [dict(r) for r in db.q(
                "SELECT * FROM scenes WHERE drama_id=? ORDER BY id", (self.drama_id,))],
            "props": [dict(r) for r in db.q(
                "SELECT * FROM props WHERE drama_id=? ORDER BY id", (self.drama_id,))],
        }
        total = ready = 0
        comic_total = comic_ready = 0
        for kind, rows in groups.items():
            sec = self.asset_sections[kind]
            grid = sec["grid"]
            while grid.count():
                it = grid.takeAt(0)
                w = it.widget()
                if w:
                    w.deleteLater()
            n = 0
            for r in rows:
                total += 1
                if r.get("image_url"):
                    ready += 1
                if r.get("comic_image_url"):
                    comic_ready += 1
                comic_total += 1
                card = (C.CharacterAssetCard(r, ASSET_LABELS, on_gen_image=self._cb_gen_image(r, kind),
                                              on_gen_text=self._cb_gen_image(r, kind),
                                              on_upload=self._cb_upload(r, kind),
                                              on_face_swap=(lambda rid=r["id"]: self._face_swap(rid))
                                              if kind == "characters" else None,
                                              on_variants=(lambda cid=r["id"]: self._open_variants(cid))
                                              if kind == "characters" else None,
                                              on_prompt=self._cb_prompt(r, kind),
                                              on_open=self._cb_open(r, kind))
                       if kind == "characters"
                       else C.AssetCard(r, ASSET_LABELS, kind[:-1],
                                        on_gen=self._cb_gen_image(r, kind),
                                        on_upload=self._cb_upload(r, kind),
                                        on_prompt=self._cb_prompt(r, kind),
                                        on_open=self._cb_open(r, kind)))
                grid.addWidget(card, n // cols[kind], n % cols[kind])
                n += 1
            sec["host"].setVisible(n > 0)
            if kind == "props" and n == 0:
                holder = QFrame()
                holder.setObjectName("propsEmpty")
                hl = QLabel(tr("props_empty"))
                hl.setObjectName("muted")
                hl.setAlignment(Qt.AlignCenter)
                hlay = QHBoxLayout(holder)
                hlay.setContentsMargins(8, 14, 8, 14)
                hlay.addWidget(hl)
                grid.addWidget(holder, 0, 0)
                sec["host"].setVisible(True)
            # 漫画资产行
            csec = self.comic_asset_sections[kind]
            cgrid = csec["grid"]
            while cgrid.count():
                it = cgrid.takeAt(0)
                w = it.widget()
                if w:
                    w.deleteLater()
            cn = 0
            for r in rows:
                cid, name = r["id"], (r.get("name") or r.get("location") or "")
                if kind == "scenes" and r.get("time"):
                    name = f"{name} · {r['time']}"
                roww = C.ComicAssetRow(r.get("comic_image_url"), name,
                                       bool(r.get("comic_image_url")), False,
                                       tr("comic_gen_tip"),
                                       lambda _c=cid, _k=kind: self._gen_comic_asset(_k, _c))
                cgrid.addWidget(roww, cn // 2, cn % 2)
                cn += 1
            csec["host"].setVisible(cn > 0)
        self.asset_empty.setVisible(total == 0)
        self.comic_asset_empty.setVisible(total == 0)
        self.asset_stat.setText(
            tr("ready_n").format(ready, total) if self._asset_mode == "regular"
            else tr("comic_asset_ready_n").format(comic_ready, comic_total))
        self._refresh_asset_model_combo()

    def _cb_gen_image(self, r: dict, kind: str):
        table = {"characters": "characters", "scenes": "scenes", "props": "props"}[kind]
        return lambda: self._gen_image(r["id"], table)

    def _cb_upload(self, r: dict, kind: str):
        table = {"characters": "characters", "scenes": "scenes", "props": "props"}[kind]
        return lambda: self._upload_image(r["id"], table)

    def _cb_prompt(self, r: dict, kind: str):
        singular = {"characters": "character", "scenes": "scene", "props": "prop"}[kind]
        return lambda: self._gen_prompt(r["id"], singular)

    def _cb_open(self, r: dict, kind: str):
        table = {"characters": "character", "scenes": "scene", "props": "prop"}[kind]
        def _open():
            from .asset_dialogs import AssetDetailDialog
            AssetDetailDialog(self, table, dict(r), on_changed=self._reload_assets).exec()
        return _open

    def _refresh_asset_model_combo(self):
        """资产页的图片模型下拉与顶栏保持一致(跟随顶部选中项)。"""
        if not hasattr(self, "asset_model"):
            return
        cur = self.image_model.currentData()
        self.asset_model.blockSignals(True)
        self.asset_model.clear()
        self.asset_model.addItem(tr("follow_top"), None)
        for r in registry.list_configs("image"):
            self.asset_model.addItem(f"{r['remark'] or r['provider']}/{r['model']}", r["id"])
        i = self.asset_model.findData(cur)
        self.asset_model.setCurrentIndex(i if i >= 0 else 0)
        self.asset_model.blockSignals(False)
        if not getattr(self, "_asset_model_wired", False):
            self.asset_model.currentIndexChanged.connect(self._asset_model_picked)
            self._asset_model_wired = True

    def _active_image_config(self):
        """资产页下拉优先,没选就跟随顶栏图片模型。"""
        if hasattr(self, "asset_model") and self.asset_model.currentData() is not None:
            return self.asset_model.currentData()
        return self.image_model.currentData()

    def _asset_model_picked(self, _idx: int):
        """资产页选了图片模型 → 同步顶栏,两处始终一致。"""
        data = self.asset_model.currentData()
        if data is None:
            return
        i = self.image_model.findData(data)
        if i >= 0 and i != self.image_model.currentIndex():
            self.image_model.setCurrentIndex(i)

    def _open_variants(self, character_id: int):
        from .variants_dialog import VariantsDialog
        c = db.q1("SELECT * FROM characters WHERE id=?", (character_id,))
        if c:
            VariantsDialog(self, dict(c)).exec()
            self._reload_assets()

    def _gen_prompt(self, row_id: int, kind: str):
        fn = {"character": prompts_gen.character_prompt, "scene": prompts_gen.scene_prompt,
              "prop": prompts_gen.prop_prompt}[kind]
        def job(tid):
            return fn(row_id, config_id=self.text_model.currentData())
        def done(tid, result, error):
            if error:
                err("AI")
            self._reload_assets()
        TASKMGR.submit("prompt", job, done, drama_id=self.drama_id, character_id=row_id if kind == "character" else None)

    def _gen_image(self, row_id: int, table: str):
        col = {"characters": "final_prompt", "scenes": "final_prompt", "props": "final_prompt"}[table]

        def job(tid):
            row = db.q1(f"SELECT * FROM {table} WHERE id=?", (row_id,))
            fp = row["final_prompt"]
            if not fp:
                kind = {"characters": "character", "scenes": "scene", "props": "prop"}[table]
                fp = {"character": prompts_gen.character_prompt, "scene": prompts_gen.scene_prompt,
                      "prop": prompts_gen.prop_prompt}[kind](row_id, config_id=self.text_model.currentData())
            out, _provider = image_client.generate_image(fp, config_id=self._active_image_config())
            url = config.path_to_media_url(out)
            db.ex(f"UPDATE {table} SET image_url=?, updated_at=? WHERE id=?", (url, db.now(), row_id))
            return url
        def done(tid, result, error):
            if error:
                err("AI")
            self._reload_assets()
        TASKMGR.submit("image", job, done, drama_id=self.drama_id)

    def _batch_images(self, table: str):
        rows = db.q(f"SELECT id FROM {table} WHERE drama_id=? AND image_url IS NULL", (self.drama_id,))
        for r in rows:
            self._gen_image(r["id"], table)

    def _upload_image(self, row_id: int, table: str):
        p, _ = QFileDialog.getOpenFileName(self, tr("upload"), "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not p:
            return
        import shutil
        dst = config.STATIC_DIR / "uploads" / f"up_{row_id}_{config.uuid.uuid4().hex[:6]}{p[p.rfind('.'):][:8]}"
        shutil.copy(p, dst)
        db.ex(f"UPDATE {table} SET image_url=?, updated_at=? WHERE id=?",
              (config.path_to_media_url(dst), db.now(), row_id))
        self._reload_assets()

    def _face_swap(self, character_id: int):
        """资产·角色卡换脸:打开对话框(当前形象 → 选源脸 → 预览 → 应用替换)。"""
        c = db.q1("SELECT * FROM characters WHERE id=?", (character_id,))
        if not c:
            return
        if not c["image_url"]:
            QMessageBox.information(self, tr("face_swap"), tr("该角色还没有形象图,请先「重绘」生成或「上传」"))
            return
        from .character_face_swap_dialog import CharacterFaceSwapDialog
        dlg = CharacterFaceSwapDialog(self, dict(c), self.face_model.currentData(),
                                      self.face_model.currentText())
        if dlg.exec() == CharacterFaceSwapDialog.Accepted:
            self._reload_assets()

    # ── 阶段④ 分镜 ──
    def _panel_storyboard(self, lay):
        """分镜 / 视漫工作台:左任务列表 + 中检查器(含参考素材) + 右播放器与参数。"""
        from . import episode_cards as C
        lay.setContentsMargins(10, 8, 12, 10)
        lay.setSpacing(8)

        # ── 工具条 ──
        bar = QHBoxLayout()
        bar.setSpacing(7)
        bar.addWidget(QLabel(tr("storyboard")))
        self.sb_seg_stat = C.mono_tag("")
        bar.addWidget(self.sb_seg_stat)
        bar.addStretch(1)
        split_btn = W.primary_btn(tr("re_split"))
        split_btn.setToolTip(tr("re_split_tip"))
        split_btn.clicked.connect(self._split_sb)
        bar.addWidget(split_btn)
        prompts_btn = QPushButton(tr("batch_prompts"))
        prompts_btn.clicked.connect(self._batch_vp)
        bar.addWidget(prompts_btn)
        self.repair_btn = W.primary_btn("⟳ " + tr("auto_repair", 0))
        self.repair_btn.setToolTip(tr("auto_repair_tip"))
        self.repair_btn.setVisible(False)
        self.repair_btn.clicked.connect(self._repair_storyboards)
        bar.addWidget(self.repair_btn)
        video_btn = WaitingButton(tr("batch_video"), primary=True)
        video_btn.clicked.connect(self._batch_video)
        bar.addWidget(video_btn)
        lay.addLayout(bar)

        # ── 空态 ──
        self.sb_empty = C.empty_state("🎞", tr("sb_empty_title"), tr("sb_empty_desc"))
        lay.addWidget(self.sb_empty)
        self.sb_locked = W.muted("")
        lay.addWidget(self.sb_locked)

        # ── 三栏工作台 ──
        self.sb_workbench = QWidget()
        wb = QHBoxLayout(self.sb_workbench)
        wb.setContentsMargins(0, 0, 0, 0)
        wb.setSpacing(0)

        # 左:视频任务列表
        left = QFrame()
        left.setObjectName("taskList")
        left.setFixedWidth(252)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        head = QFrame()
        head.setObjectName("taskHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(12, 10, 12, 10)
        hl.setSpacing(5)
        self.sb_list_title = QLabel(tr("video_task_list"))
        self.sb_list_title.setObjectName("taskTitle")
        hl.addWidget(self.sb_list_title)
        self.sb_list_meta = QLabel("")
        self.sb_list_meta.setObjectName("muted")
        hl.addWidget(self.sb_list_meta)
        metrics = QHBoxLayout()
        metrics.setSpacing(5)
        self._metric_pills: dict[str, QPushButton] = {}
        for state, key in (("pending", "in_progress"), ("done", "done"), ("failed", "failed")):
            p = C.MetricPill(state, f"0 {tr(key)}", self._filter_tasks)
            self._metric_pills[state] = p
            metrics.addWidget(p)
        metrics.addStretch(1)
        hl.addLayout(metrics)
        ll.addWidget(head)
        self.sb_task_scroll = C.scroll_host(QWidget())
        self.sb_task_host = self.sb_task_scroll.widget()
        tl = QVBoxLayout(self.sb_task_host)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        self.sb_task_lay = tl
        tl.addStretch(1)
        ll.addWidget(self.sb_task_scroll, 1)
        wb.addWidget(left)

        # 中:检查器(画面描述 / 氛围 / 视频提示词 / 旁白 + 参考素材)
        center = QWidget()
        cl = QVBoxLayout(center)
        cl.setContentsMargins(14, 14, 10, 14)
        cl.setSpacing(12)
        desc_lab = QLabel(tr("sb_desc_label"))
        desc_lab.setObjectName("inspectorLabel")
        cl.addWidget(desc_lab)
        self.sb_content = C.SaveOnBlurEdit()
        self.sb_content.setPlaceholderText(tr("sb_desc_ph"))
        self.sb_content.setFixedHeight(112)
        self.sb_content.editing_finished.connect(
            lambda: self._save_sb_field("content", self.sb_content))
        cl.addWidget(self.sb_content)
        atm_lab = QLabel(tr("sb_atmosphere"))
        atm_lab.setObjectName("inspectorLabel")
        cl.addWidget(atm_lab)
        self.sb_atmosphere = C.SaveOnBlurEdit()
        self.sb_atmosphere.setPlaceholderText(tr("sb_atmosphere_ph"))
        self.sb_atmosphere.setFixedHeight(56)
        self.sb_atmosphere.editing_finished.connect(
            lambda: self._save_sb_field("atmosphere", self.sb_atmosphere))
        cl.addWidget(self.sb_atmosphere)
        vp_head = QHBoxLayout()
        vp_lab = QLabel(tr("sb_video_prompt"))
        vp_lab.setObjectName("heroLabel")
        vp_head.addWidget(vp_lab)
        vp_head.addStretch(1)
        self.sb_ai_prompt_btn = WaitingButton(tr("ai_generate"))
        self.sb_ai_prompt_btn.clicked.connect(self._ai_sb_prompt)
        vp_head.addWidget(self.sb_ai_prompt_btn)
        cl.addLayout(vp_head)
        self.sb_video_prompt = C.SaveOnBlurEdit()
        self.sb_video_prompt.setPlaceholderText(tr("sb_video_prompt_ph"))
        self.sb_video_prompt.setMinimumHeight(140)
        self.sb_video_prompt.editing_finished.connect(
            lambda: self._save_sb_field("video_prompt", self.sb_video_prompt))
        cl.addWidget(self.sb_video_prompt, 1)
        nr_head = QHBoxLayout()
        nr_lab = QLabel(tr("sb_narration"))
        nr_lab.setObjectName("inspectorLabel")
        nr_head.addWidget(nr_lab)
        nr_head.addStretch(1)
        self.sb_tts_btn = WaitingButton("🔊 " + tr("synth_narration"))
        self.sb_tts_btn.clicked.connect(self._one_tts_selected)
        nr_head.addWidget(self.sb_tts_btn)
        cl.addLayout(nr_head)
        self.sb_narration = C.SaveOnBlurEdit()
        self.sb_narration.setPlaceholderText(tr("sb_narration_ph"))
        self.sb_narration.setFixedHeight(60)
        self.sb_narration.textChanged.connect(self._update_narration_count)
        self.sb_narration.editing_finished.connect(
            lambda: self._save_sb_field("narration", self.sb_narration))
        cl.addWidget(self.sb_narration)
        nr_foot = QHBoxLayout()
        self.sb_narr_count = QLabel("0/200")
        self.sb_narr_count.setObjectName("muted")
        nr_foot.addWidget(self.sb_narr_count)
        nr_foot.addWidget(QLabel(tr("narration_duration")))
        self.sb_narr_dur = QSpinBox()
        self.sb_narr_dur.setRange(1, 60)
        self.sb_narr_dur.setSuffix(" s")
        self.sb_narr_dur.setFixedWidth(76)
        self.sb_narr_dur.valueChanged.connect(self._save_narration_duration)
        nr_foot.addWidget(self.sb_narr_dur)
        self.sb_narr_audio = QLabel("")
        self.sb_narr_audio.setObjectName("chip")
        nr_foot.addWidget(self.sb_narr_audio)
        nr_foot.addStretch(1)
        cl.addLayout(nr_foot)

        # 参考素材:角色 / 场景 / 道具 三个页签
        ref_head = QHBoxLayout()
        rl = QLabel(tr("ref_title"))
        rl.setObjectName("inspectorLabel")
        ref_head.addWidget(rl)
        ref_head.addStretch(1)
        self.sb_ref_count = C.mono_tag("")
        ref_head.addWidget(self.sb_ref_count)
        cl.addLayout(ref_head)
        self._ref_tab_btns: dict[str, QPushButton] = {}
        tab_row = QHBoxLayout()
        tab_row.setSpacing(4)
        for kind, key in (("character", "chars"), ("scene", "scenes"), ("prop", "props")):
            b = QPushButton(tr(key))
            b.setObjectName("refTab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=kind: self._switch_ref_tab(k))
            self._ref_tab_btns[kind] = b
            tab_row.addWidget(b)
        tab_row.addStretch(1)
        cl.addLayout(tab_row)
        self.sb_ref_scroll = C.scroll_host(QWidget())
        self.sb_ref_host = self.sb_ref_scroll.widget()
        rl2 = QGridLayout(self.sb_ref_host)
        rl2.setContentsMargins(0, 2, 0, 0)
        rl2.setSpacing(8)
        self.sb_ref_lay = rl2
        cl.addWidget(self.sb_ref_scroll, 1)
        wb.addWidget(center, 1)

        # 右:播放器 + 历史 + 绑定参考图 + 参数卡 + 主行动键
        right = QFrame()
        right.setObjectName("inspector")
        right.setFixedWidth(322)
        rl3 = QVBoxLayout(right)
        rl3.setContentsMargins(12, 12, 12, 12)
        rl3.setSpacing(10)
        pl_head = QHBoxLayout()
        self.sb_player_title = QLabel("")
        self.sb_player_title.setObjectName("taskTitle")
        pl_head.addWidget(self.sb_player_title)
        pl_head.addStretch(1)
        self.sb_dl_btn = QPushButton("↓")
        self.sb_dl_btn.setToolTip(tr("download"))
        self.sb_dl_btn.clicked.connect(self._download_selected)
        pl_head.addWidget(self.sb_dl_btn)
        rl3.addLayout(pl_head)
        stage = QFrame()
        stage.setObjectName("playerStage")
        stage.setFixedHeight(198)
        sl = QVBoxLayout(stage)
        sl.setContentsMargins(10, 10, 10, 10)
        self.sb_player = QLabel()
        self.sb_player.setAlignment(Qt.AlignCenter)
        self.sb_player_empty = QLabel("")
        self.sb_player_empty.setAlignment(Qt.AlignCenter)
        self.sb_player_empty.setWordWrap(True)
        sl.addWidget(self.sb_player, 1)
        sl.addWidget(self.sb_player_empty)
        rl3.addWidget(stage)
        self.sb_history = QWidget()
        hl3 = QVBoxLayout(self.sb_history)
        hl3.setContentsMargins(0, 0, 0, 0)
        hl3.setSpacing(4)
        self.sb_history_title = W.muted("")
        hl3.addWidget(self.sb_history_title)
        self.sb_history_row = QHBoxLayout()
        self.sb_history_row.setSpacing(6)
        self.sb_history_row_host = QWidget()
        self.sb_history_row_host.setLayout(self.sb_history_row)
        hl3.addWidget(self.sb_history_row_host)
        self.sb_history.setVisible(False)
        rl3.addWidget(self.sb_history)
        bh = QHBoxLayout()
        bl = QLabel(tr("bound_refs"))
        bl.setObjectName("inspectorLabel")
        bh.addWidget(bl)
        bh.addStretch(1)
        self.sb_bound_count = C.mono_tag("")
        bh.addWidget(self.sb_bound_count)
        rl3.addLayout(bh)
        self.sb_bound_host = QWidget()
        self.sb_bound_lay = QGridLayout(self.sb_bound_host)
        self.sb_bound_lay.setContentsMargins(0, 0, 0, 0)
        self.sb_bound_lay.setSpacing(6)
        rl3.addWidget(self.sb_bound_host)
        # 参数卡
        self.sb_params = QFrame()
        self.sb_params.setObjectName("paramCard")
        pl4 = QVBoxLayout(self.sb_params)
        pl4.setContentsMargins(10, 9, 10, 9)
        pl4.setSpacing(6)
        r1 = QHBoxLayout()
        r1.addWidget(QLabel(tr("sb_duration")))
        self.sb_duration = QSpinBox()
        self.sb_duration.setRange(2, 30)
        self.sb_duration.setValue(10)
        self.sb_duration.setSuffix(" s")
        self.sb_duration.setFixedWidth(74)
        self.sb_duration.valueChanged.connect(self._save_duration)
        r1.addWidget(self.sb_duration)
        r1.addWidget(W.muted("2-30"))
        r1.addStretch(1)
        pl4.addLayout(r1)
        r2 = QHBoxLayout()
        r2.addWidget(QLabel(tr("gen_audio")))
        self.sb_gen_audio = QCheckBox("")
        self.sb_gen_audio.setToolTip(tr("gen_audio_tip"))
        self.sb_gen_audio.toggled.connect(self._save_gen_audio)
        r2.addWidget(self.sb_gen_audio)
        r2.addStretch(1)
        pl4.addLayout(r2)
        r3 = QHBoxLayout()
        r3.addWidget(QLabel(tr("setting_tags")))
        r3.addStretch(1)
        pl4.addLayout(r3)
        self.sb_tags_row = QHBoxLayout()
        self.sb_tags_row.setSpacing(4)
        self.sb_tags_host = QWidget()
        self.sb_tags_host.setLayout(self.sb_tags_row)
        pl4.addWidget(self.sb_tags_host)
        self.sb_tag_input = QLineEdit()
        self.sb_tag_input.setPlaceholderText(tr("tags_ph"))
        self.sb_tag_input.returnPressed.connect(self._add_setting_tag)
        pl4.addWidget(self.sb_tag_input)
        pl4.addWidget(W.muted(tr("params_hint")))
        rl3.addWidget(self.sb_params)
        self.sb_effective = QLabel("")
        self.sb_effective.setObjectName("effective")
        self.sb_effective.setAlignment(Qt.AlignCenter)
        rl3.addWidget(self.sb_effective)
        self.sb_action_btn = WaitingButton(tr("generate"), primary=True)
        self.sb_action_btn.clicked.connect(self._generate_selected)
        rl3.addWidget(self.sb_action_btn)
        rl3.addStretch(1)
        wb.addWidget(right)

        lay.addWidget(self.sb_workbench, 1)
        self._sb_id = 0
        self._task_filter = ""
        self._ref_kind = "character"

    def _reload_storyboard(self):
        """刷新左栏任务列表 + 统计;选中态不清空,避免正在编辑的内容被重置。"""
        if not getattr(self, "sb_task_lay", None):
            return
        rows = self._sb_rows()
        total = sum(r["duration"] or 0 for r in rows)
        self.sb_seg_stat.setText(tr("segments", len(rows)) + f" · {tr('total_dur', int(total))}")
        self.sb_empty.setVisible(not rows)
        self.sb_workbench.setVisible(bool(rows))
        self.sb_locked.setText(tr("locked_video_model", self._video_model_name()) if rows else "")
        self._render_task_list(rows)
        self._load_incomplete()
        self._refresh_status()
        if rows and not self._sb_id:
            self._select_storyboard(rows[0]["id"])

    def _sb_rows(self) -> list:
        return [dict(r) for r in db.q(
            "SELECT * FROM storyboards WHERE episode_id=? AND deleted_at IS NULL "
            "ORDER BY storyboard_number", (self.episode_id,))]

    def _video_model_name(self) -> str:
        cid = self.video_model.currentData()
        if cid:
            for r in registry.list_configs("video"):
                if r["id"] == cid:
                    return f"{r['remark'] or r['provider']}/{r['model']}"
        return tr("configured")

    @staticmethod
    def _sb_state(r) -> tuple[str, str]:
        """(state, 文案) —— 与原版 videoTaskState / videoTaskStatusLabel 同口径。
        兼容 sqlite3.Row 与 dict 两种入参。"""
        get = (lambda k: r[k]) if not isinstance(r, dict) else r.get
        if get("video_url") or get("composed_video_url"):
            return "done", tr("done")
        if get("status") == "processing":
            return "pending", tr("in_progress")
        if get("status") == "failed":
            return "failed", tr("failed")
        return "ready", tr("pending")

    def _render_task_list(self, rows: list):
        from . import episode_cards as C
        lay = self.sb_task_lay
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        counts = {"pending": 0, "done": 0, "failed": 0}
        shown = 0
        for r in rows:
            state, state_label = self._sb_state(r)
            counts[state] = counts.get(state, 0) + 1
            if self._task_filter and state != self._task_filter:
                continue
            shown += 1
            dur = int(r.get("duration") or 0)
            scene = self._sb_scene_name(r)
            meta = " · ".join([state_label, f"{dur}s"] + ([scene] if scene else []))
            action_tip = {"done": tr("redraw"), "pending": tr("in_progress"),
                          "failed": tr("retry"), "ready": tr("generate")}[state]
            row = C.VideoTaskRow(
                int(r["storyboard_number"]), (r["content"] or "")[:40] or tr("shot_n", r["storyboard_number"]),
                meta, state, state_label, action_tip,
                r.get("composed_video_url") or r.get("video_url"),
                selected=(r["id"] == self._sb_id),
                on_click=lambda _=False, i=r["id"]: self._select_storyboard(i),
                on_action=lambda _=False, i=r["id"]: self._generate_one(i))
            lay.insertWidget(lay.count() - 1, row)
        for state, pill in self._metric_pills.items():
            pill.setText(f"{counts.get(state, 0)} {pill.text().split(' ', 1)[1]}")
            pill.setChecked(self._task_filter == state)
        self.sb_list_meta.setText(
            tr("task_meta_filter", shown, len(rows)) if self._task_filter
            else tr("task_meta", len(rows)))

    def _update_metric_pills(self, stats: dict | None = None):
        """后台任务状态变化时刷新左侧三枚筛选胶囊(不重建列表,保住滚动位置)。"""
        if not hasattr(self, "_metric_pills"):
            return
        if stats is None:
            counts = {"pending": 0, "done": 0, "failed": 0}
            for r in self._sb_rows():
                counts[self._sb_state(r)[0]] = counts.get(self._sb_state(r)[0], 0) + 1
        else:
            counts = {"pending": stats.get("processing", 0),
                      "done": stats.get("completed", 0),
                      "failed": stats.get("failed", 0)}
        for state, pill in self._metric_pills.items():
            pill.setText(f"{counts.get(state, 0)} {pill.text().split(' ', 1)[1]}")

    def _filter_tasks(self, state: str):
        """点击筛选胶囊:再点同一枚取消筛选。"""
        self._task_filter = "" if self._task_filter == state else state
        self._render_task_list(self._sb_rows())

    def _sb_scene_name(self, r: dict) -> str:
        row = db.q1("SELECT s.location, s.time FROM storyboards sb "
                    "LEFT JOIN scenes s ON s.id=sb.scene_id WHERE sb.id=?", (r["id"],))
        if not row or not row["location"]:
            return ""
        return f"{row['location']} · {row['time']}" if row["time"] else row["location"]

    # ── 选中分镜:把数据灌进中/右两栏 ──
    def _select_storyboard(self, sb_id: int):
        row = db.q1("SELECT * FROM storyboards WHERE id=?", (sb_id,))
        if not row:
            return
        r = dict(row)
        self._sb_id = sb_id
        for w, col in ((self.sb_content, "content"), (self.sb_atmosphere, "atmosphere"),
                       (self.sb_video_prompt, "video_prompt"), (self.sb_narration, "narration")):
            w.blockSignals(True)
            w.setPlainText(r[col] or "")
            w.blockSignals(False)
        self.sb_narr_dur.blockSignals(True)
        self.sb_narr_dur.setValue(max(1, int(r["narration_duration"] or r["duration"] or 10)))
        self.sb_narr_dur.blockSignals(False)
        self.sb_duration.blockSignals(True)
        self.sb_duration.setValue(max(2, min(30, int(r["duration"] or 10))))
        self.sb_duration.blockSignals(False)
        audio = (r["video_prompt"] or "") + (r["content"] or "")
        self.sb_gen_audio.setChecked("--no-audio" not in audio and "--no_audio" not in audio)
        self._update_narration_count()
        state, state_label = self._sb_state(r)
        vid = r["video_url"] or r["composed_video_url"]
        self.sb_player_title.setText(
            f"{tr('shot_n', r['storyboard_number'])} · {state_label} · {int(r['duration'] or 0)}s")
        if vid:
            self._show_player(vid)
            self.sb_player_empty.setVisible(False)
        else:
            self._clear_player()
            self.sb_player_empty.setText(
                tr("video_generating") if state == "pending"
                else tr("no_video_yet"))
        self.sb_dl_btn.setEnabled(bool(vid))
        self.sb_tts_btn.setEnabled(bool((r["narration"] or "").strip()))
        audio_url = r["narration_audio_url"]
        self.sb_narr_audio.setText(
            f"{tr('tts_done')} · {r['narration_voice']}" if audio_url else "")
        self._render_setting_tags(r)
        self._render_refs(r)
        self._render_bound_refs(r)
        self.sb_effective.setText(
            f"{self._video_model_name()} · {self._ep['resolution'] or '720p'} · {int(r['duration'] or 10)}s")
        self.sb_action_btn.setText(tr("redraw") if state == "done" else
                                   (tr("in_progress") if state == "pending" else tr("generate")))
        self.sb_action_btn.setEnabled(state != "pending")
        self.sb_ai_prompt_btn.setEnabled(True)
        self._render_task_list(self._sb_rows())

    def _show_player(self, url: str):
        from PySide6.QtMultimedia import QMediaPlayer, QVideoWidget
        if not hasattr(self, "_player_widget"):
            self._player_widget = QVideoWidget()
            self._player_widget.setStyleSheet("border:none; border-radius:6px;")
            self._player = QMediaPlayer()
            self._player.setVideoOutput(self._player_widget)
            self._player_widget.setMinimumHeight(150)
            self.sb_player.layout().insertWidget(0, self._player_widget)
        self._player_widget.setVisible(True)
        self._player_widget.setStyleSheet("border:none; border-radius:6px;")
        src = config.media_url_to_path(url) if str(url).startswith(("/static/", "static/")) else url
        self._player.setSource(QUrl.fromLocalFile(str(src)))

    def _clear_player(self):
        if hasattr(self, "_player"):
            self._player.stop()
            self._player_widget.setVisible(False)

    def _update_narration_count(self):
        n = len(self.sb_narration.toPlainText())
        self.sb_narr_count.setText(f"{n}/200")

    def _save_sb_field(self, col: str, editor):
        if not self._sb_id:
            return
        db.ex(f"UPDATE storyboards SET {col}=?, updated_at=? WHERE id=?",
              (editor.toPlainText(), db.now(), self._sb_id))

    def _save_narration_duration(self, value: int):
        if not self._sb_id:
            return
        db.ex("UPDATE storyboards SET narration_duration=?, updated_at=? WHERE id=?",
              (float(value), db.now(), self._sb_id))

    def _save_duration(self, value: int):
        if not self._sb_id:
            return
        db.ex("UPDATE storyboards SET duration=?, updated_at=? WHERE id=?",
              (float(value), db.now(), self._sb_id))
        self._render_task_list(self._sb_rows())

    def _save_gen_audio(self, on: bool):
        if not self._sb_id:
            return
        row = db.q1("SELECT video_prompt, content FROM storyboards WHERE id=?", (self._sb_id,))
        text = (row["video_prompt"] or "") + "\n" + (row["content"] or "")
        text = text.replace("--no-audio", "").replace("--no_audio", "")
        if not on:
            text += "\n--no-audio"
        db.ex("UPDATE storyboards SET video_prompt=?, content=?, updated_at=? WHERE id=?",
              ((row["video_prompt"] or "").replace("--no-audio", "").replace("--no_audio", ""),
               (row["content"] or "").replace("--no-audio", "").replace("--no_audio", ""),
               db.now(), self._sb_id))
        self.sb_video_prompt.setPlainText(text.strip())

    def _add_setting_tag(self):
        tag = self.sb_tag_input.text().strip()
        if not tag or not self._sb_id:
            return
        row = db.q1("SELECT setting_tags FROM storyboards WHERE id=?", (self._sb_id,))
        tags = json.loads(row["setting_tags"] or "[]") if row["setting_tags"] else []
        if isinstance(tags, str):
            tags = []
        if tag not in tags:
            tags.append(tag)
        db.ex("UPDATE storyboards SET setting_tags=?, updated_at=? WHERE id=?",
              (json.dumps(tags, ensure_ascii=False), db.now(), self._sb_id))
        self.sb_tag_input.clear()
        self._render_setting_tags(dict(row, setting_tags=json.dumps(tags, ensure_ascii=False)))

    def _remove_setting_tag(self, tag: str):
        if not self._sb_id:
            return
        row = db.q1("SELECT setting_tags FROM storyboards WHERE id=?", (self._sb_id,))
        tags = json.loads(row["setting_tags"] or "[]") if row["setting_tags"] else []
        tags = [t for t in tags if t != tag]
        db.ex("UPDATE storyboards SET setting_tags=?, updated_at=? WHERE id=?",
              (json.dumps(tags, ensure_ascii=False), db.now(), self._sb_id))
        self._render_setting_tags(dict(row, setting_tags=json.dumps(tags, ensure_ascii=False)))

    def _render_setting_tags(self, r: dict):
        while self.sb_tags_row.count():
            it = self.sb_tags_row.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        raw = (r.get("setting_tags") if isinstance(r, dict) else r["setting_tags"]) or "[]"
        try:
            tags = json.loads(raw) if isinstance(raw, str) else list(raw)
        except (TypeError, ValueError):
            tags = []
        if not isinstance(tags, list):
            tags = []
        for tag in tags:
            chip = QLabel(f"{tag}  ×")
            chip.setObjectName("chip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.mousePressEvent = lambda _e, t=tag: self._remove_setting_tag(t)
            self.sb_tags_row.addWidget(chip)
        self.sb_tags_row.addStretch(1)

    def _switch_ref_tab(self, kind: str):
        self._ref_kind = kind
        for k, b in self._ref_tab_btns.items():
            b.setChecked(k == kind)
        row = db.q1("SELECT * FROM storyboards WHERE id=?", (self._sb_id,)) if self._sb_id else None
        r = dict(row) if row else {}
        self._render_refs(r)
        self._render_bound_refs(r)

    REF_PLACEHOLDER = {"character": "角", "scene": "景", "prop": "具"}

    def _ref_rows(self, kind: str) -> list:
        """本集可参考的资产(与分镜绑定的优先)。"""
        tables = {"character": ("episode_characters", "characters", "name"),
                  "scene": ("episode_scenes", "scenes", "location"),
                  "prop": ("episode_props", "props", "name")}
        link, table, namecol = tables[kind]
        return [dict(r) for r in db.q(
            f"SELECT t.* FROM {link} l JOIN {table} t ON t.id = l."
            + {"episode_characters": "character_id", "episode_scenes": "scene_id",
               "episode_props": "prop_id"}[link]
            + " WHERE l.episode_id=? ORDER BY t.id", (self.episode_id,))]

    def _bound_ids(self, kind: str) -> set:
        if not self._sb_id:
            return set()
        if kind == "character":
            return {r["character_id"] for r in db.q(
                "SELECT character_id FROM storyboard_characters WHERE storyboard_id=?",
                (self._sb_id,))}
        if kind == "prop":
            return {r["prop_id"] for r in db.q(
                "SELECT prop_id FROM storyboard_props WHERE storyboard_id=?", (self._sb_id,))}
        row = db.q1("SELECT scene_id FROM storyboards WHERE id=?", (self._sb_id,))
        return {row["scene_id"]} if row and row["scene_id"] else set()

    def _render_refs(self, r: dict):
        from . import episode_cards as C
        lay = self.sb_ref_lay
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        kind = self._ref_kind
        rows = self._ref_rows(kind)
        bound = self._bound_ids(kind)
        for i, row in enumerate(rows):
            name = row.get("name") or row.get("location") or ""
            has_img = bool(row.get("image_url"))
            is_bound = row["id"] in bound
            state = tr("ref_ok") if (is_bound and has_img) else (
                tr("ref_no_image") if not has_img else tr("ref_unbound"))
            card = C.RefCard(row.get("image_url"), self.REF_PLACEHOLDER[kind], name,
                             tr(REF_TAB_KEYS[kind]), state,
                             on_generate=(lambda _id=row["id"]: self._goto_assets(_id))
                             if (is_bound and not has_img) else None)
            card.setProperty("bound", "1" if is_bound else "0")
            card.style().unpolish(card)
            card.style().polish(card)
            lay.addWidget(card, i // 3, i % 3)
        lay.setRowStretch((len(rows) + 2) // 3, 1)
        self.sb_ref_count.setText(tr("bound_n", len(bound), len(rows)))
        for k, b in self._ref_tab_btns.items():
            b.setText(f"{tr(REF_TAB_KEYS[k])} {len(self._ref_rows(k))}")

    def _goto_assets(self, row_id: int):
        self._goto_step("assets")

    def _render_bound_refs(self, r: dict):
        from . import episode_cards as C
        lay = self.sb_bound_lay
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        cells = []
        for kind in ("character", "scene", "prop"):
            for row in self._ref_rows(kind):
                if row["id"] in self._bound_ids(kind):
                    cells.append((row, kind))
        self.sb_bound_count.setText(tr("bound_count_n", len(cells)))
        if not cells:
            empty = QLabel(tr("bound_refs_empty"))
            empty.setObjectName("muted")
            empty.setAlignment(Qt.AlignCenter)
            lay.addWidget(empty, 0, 0)
            return
        for i, (row, kind) in enumerate(cells):
            host = QWidget()
            host.setStyleSheet("border:none;")
            hl = QVBoxLayout(host)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(2)
            thumb = QLabel()
            thumb.setFixedSize(78, 60)
            thumb.setAlignment(Qt.AlignCenter)
            thumb.setPixmap(W.pixmap_from_media(row.get("image_url"), 78, 60))
            hl.addWidget(thumb)
            nm = QLabel((row.get("name") or row.get("location") or "")[:8])
            nm.setObjectName("muted")
            nm.setAlignment(Qt.AlignCenter)
            nm.setToolTip(row.get("name") or row.get("location") or "")
            hl.addWidget(nm)
            lay.addWidget(host, i // 3, i % 3)

    # ── 分镜动作 ──
    def _generate_selected(self):
        if self._sb_id:
            self._generate_one(self._sb_id)

    def _download_selected(self):
        row = db.q1("SELECT * FROM storyboards WHERE id=?", (self._sb_id,))
        if row:
            self._download_sb(dict(row))

    def _one_tts_selected(self):
        if self._sb_id:
            self._one_tts(self._sb_id)

    def _ai_sb_prompt(self):
        """按当前画面描述 + 氛围重生成视频提示词。"""
        if not self._sb_id:
            return
        row = db.q1("SELECT * FROM storyboards WHERE id=?", (self._sb_id,))
        if not row:
            return
        r = dict(row)
        r["drama_id"] = self.drama_id
        btn = self.sb_ai_prompt_btn
        btn.busy(tr("ai_generate"))

        def job(tid):
            return runner.run_agent("prompt_generator", _sb_prompt_request(r), lang=self._drama_lang)

        def done(tid, result, error):
            btn.idle()
            if error:
                err("AI")
                return
            text = (result or "").strip()
            if not text:
                err(tr("ai_empty"))
                return
            db.ex("UPDATE storyboards SET video_prompt=?, updated_at=? WHERE id=?",
                  (text, db.now(), self._sb_id))
            self.sb_video_prompt.setPlainText(text)
            ok(tr("video_prompt_saved"))

        TASKMGR.submit("prompt", job, done, episode_id=self.episode_id)

    def _download_sb(self, sb: dict):
        from ..core import download as dl_mod
        try:
            p = dl_mod.download_storyboard_video(sb)
            ok(f"已下载:{p.name}")
        except Exception as e:  # noqa: BLE001
            err(str(e))

    def _gen_first_frame(self, sb_id: int):
        from ..pipeline import shot_tools
        def job(tid):
            return shot_tools.generate_first_frame(self.episode_id, sb_id,
                                                   config_id=self.image_model.currentData())
        def done(tid, result, error):
            if error:
                err("▣")
            self._reload_storyboard()
        TASKMGR.submit("image", job, done, episode_id=self.episode_id, storyboard_id=sb_id)

    def _compose_i2v(self, sb_id: int):
        from ..pipeline import shot_tools
        db.ex("UPDATE storyboards SET status='processing' WHERE id=?", (sb_id,))
        res = self.res_combo.currentText()
        def job(tid):
            return shot_tools.compose_from_image(self.episode_id, sb_id, res,
                                                 config_id=self.video_model.currentData())
        def done(tid, result, error):
            if error:
                db.ex("UPDATE storyboards SET status='failed' WHERE id=?", (sb_id,))
                err("▷")
            self._reload_storyboard()
        TASKMGR.submit("video", job, done, episode_id=self.episode_id, storyboard_id=sb_id)

    def _burn_sub(self, sb_id: int):
        from ..pipeline import shot_tools
        def job(tid):
            return shot_tools.burn_subtitle(sb_id)
        def done(tid, result, error):
            if error:
                err("T")
            self._reload_storyboard()
        TASKMGR.submit("video", job, done, episode_id=self.episode_id, storyboard_id=sb_id)

    def _load_incomplete(self):
        """检测残缺分镜;有才显示补全按钮(无残缺自动消失不占位)。"""
        if not getattr(self, "repair_btn", None) or not self.episode_id:
            return
        try:
            from ..pipeline import storyboard_repair as R
            self._incomplete = R.list_incomplete(self.episode_id)
        except Exception:  # noqa: BLE001
            self._incomplete = []
        n = len(self._incomplete or [])
        self.repair_btn.setVisible(n > 0)
        if n:
            self.repair_btn.setText(f"⟳ 自动补全 {n}")

    def _repair_storyboards(self):
        from ..core.taskmgr import TASKMGR
        ids = [x["id"] for x in (self._incomplete or [])]
        if not ids:
            return
        self.repair_btn.setEnabled(False)
        self.repair_btn.setText(tr("⟳ 补全中 0/0"))
        def job(tid):
            from ..pipeline import storyboard_repair as R
            return R.repair_storyboards(self.episode_id, ids,
                                        config_id=self.text_model.currentData(),
                                        lang=getattr(self, "_drama_lang", None))
        def done(tid, result, error):
            self.repair_btn.setEnabled(True)
            if error:
                err(e_)
                return
            r = result or {}
            if r.get("failed"):
                warn(f"补全完成,{r['failed']} 个失败可重试")
            else:
                ok(f"补全完成,共修复 {r.get('completed', 0)} 个分镜")
            self._reload_storyboard()
        TASKMGR.submit("sb_repair", job, done, episode_id=self.episode_id)

    def _split_sb(self):
        """重新拆分分镜(改后台任务 + 轮询,对齐原版 split-async)。"""
        from ..core.preflight import ensure_ready
        if not ensure_ready("text", self._cfg_for("text")):
            return
        if self._sb_split_running:
            return
        try:
            tid = sb_pipe.split_storyboards_bg(
                self.episode_id, self._drama["aspect_ratio"],
                config_id=self.text_model.currentData(),
                lang=getattr(self, "_drama_lang", None))
        except Exception as e:  # noqa: BLE001
            err(str(e)[:200]); return
        self._sb_split_running = True
        self._sb_split_task = tid
        info(tr("分镜拆解已开始(后台运行,约 5-10 分钟)"))
        self._poll_sb_split(tid, 0)

    def _poll_sb_split(self, tid: int, attempt: int):
        """每 6 秒轮询拆分任务(对齐原版 6000ms)。"""
        from PySide6.QtCore import QTimer
        if attempt > 200:            # 约 20 分钟兜底
            self._sb_split_running = False
            warn(tr("分镜拆分超时,请到任务面板查看")); return
        def tick():
            row = db.q1("SELECT status, local_path, error_msg FROM sys_task WHERE id=?", (tid,))
            st = row["status"] if row else "failed"
            if st == "processing":
                QTimer.singleShot(6000, lambda: self._poll_sb_split(tid, attempt + 1))
                return
            self._sb_split_running = False
            if st == "completed":
                self._reload_storyboard()
                ok(row["local_path"] or tr("分镜拆分完成"))
            else:
                err(row["error_msg"] or tr("分镜拆分失败"))
        QTimer.singleShot(6000, tick)

    def _batch_vp(self):
        def job(tid):
            return sb_pipe.gen_video_prompts(self.episode_id, config_id=self.text_model.currentData(), lang=self._drama_lang)
        def done(tid, result, error):
            if error:
                err("AI")
            else:
                QMessageBox.information(self, tr("batch_prompts"), f"OK: {result}")
        TASKMGR.submit("prompt", job, done, episode_id=self.episode_id)

    def _one_video(self, sb_id: int):
        self._gen_video_job(sb_id)

    def _batch_video(self):
        rows = db.q("SELECT id FROM storyboards WHERE episode_id=? AND video_url IS NULL AND composed_video_url IS NULL",
                    (self.episode_id,))
        if not rows:
            QMessageBox.information(self, tr("batch_video"), tr("全部镜头已有视频"))
            return
        # 批量生成前确认:镜头数 / 总时长 / 模型 / 分辨率(对齐原版)
        total = db.q1("SELECT COALESCE(SUM(duration),0) s FROM storyboards WHERE episode_id=? AND video_url IS NULL AND composed_video_url IS NULL",
                      (self.episode_id,))["s"]
        model_txt = self.video_model.currentText()
        stats = TASKMGR.ep_video_stats(self.episode_id)
        if not ask(self, tr("batch_video"),
                   f"即将生成 {len(rows)} 个镜头(约 {int(total)}s)\n模型:{model_txt}\n分辨率:{self.res_combo.currentText()}\n"
                   f"当前任务:{tr('done')} {stats['completed']} · {tr('failed')} {stats['failed']}\n\n确认开始?"):
            return
        for r in rows:
            self._gen_video_job(r["id"])
        QTimer.singleShot(1200, lambda: getattr(self, "_video_btn", None) and self._video_btn.idle())
        self._video_btn = video_btn

    def _gen_video_job(self, sb_id: int):
        res = self.res_combo.currentText()
        def job(tid):
            from ..pipeline import shot_tools
            sb = db.q1("SELECT * FROM storyboards WHERE id=?", (sb_id,))
            db.ex("UPDATE storyboards SET status='processing' WHERE id=?", (sb_id,))
            prompt = shot_tools.resolve_prompt(dict(sb))
            ref_list = shot_tools.collect_reference_images(self.episode_id, sb_id)
            path, _p = video_client.generate_video(
                prompt[:1500], resolution=res, duration=int(sb["duration"] or 8),
                first_frame=sb["first_frame_image"], reference_images=ref_list,
                config_id=self.video_model.currentData())
            db.ex("UPDATE storyboards SET video_url=?, status='completed', updated_at=? WHERE id=?",
                  (config.path_to_media_url(path), db.now(), sb_id))
            return str(path)
        def done(tid, result, error):
            if error:
                db.ex("UPDATE storyboards SET status='failed' WHERE id=?", (sb_id,))
                err(tr("batch_video"))
            self._reload_storyboard()
        TASKMGR.submit("video", job, done, episode_id=self.episode_id, storyboard_id=sb_id)

    def _one_tts(self, sb_id: int):
        def job(tid):
            sb = db.q1("SELECT * FROM storyboards WHERE id=?", (sb_id,))
            text = (sb["narration"] or "").strip() or (sb["content"] or "")[:120]
            if not text:
                raise RuntimeError(tr("无旁白文本"))
            p = tts_client.synthesize(text, target_duration=sb["duration"], config_id=None)
            db.ex("UPDATE storyboards SET narration_audio_url=?, updated_at=? WHERE id=?",
                  (config.path_to_media_url(p), db.now(), sb_id))
            return str(p)
        def done(tid, result, error):
            if error:
                err("♪")
        TASKMGR.submit("tts", job, done, episode_id=self.episode_id, storyboard_id=sb_id)

    def _play_video(self, url: str | None):
        if not url:
            return
        import os
        import subprocess
        p = config.media_url_to_path(url)
        if p.exists():
            os.startfile(str(p))  # noqa  Windows 默认播放器

    # ── 阶段⑤ 漫画 ──
    def _panel_comic(self, lay):
        """漫画页:工具条 + 整话长条图预览 + 3:4 格网格(对齐 .prod-section-bar / .comic-panel-grid)。"""
        from . import episode_cards as C
        lay.setContentsMargins(10, 8, 12, 10)
        lay.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(7)
        bar.addWidget(QLabel(tr("comic")))
        self.comic_panel_tag = C.mono_tag("")
        bar.addWidget(self.comic_panel_tag)
        self.comic_done_tag = C.mono_tag("")
        bar.addWidget(self.comic_done_tag)
        bar.addStretch(1)
        bar.addWidget(QLabel(tr("comic_style") + ":"))
        self.comic_style = QComboBox()
        self.comic_style.setFixedWidth(150)
        self.comic_style.addItem(tr("follow_project"), "")
        for r in db.q("SELECT value,name FROM style_presets WHERE is_active=1 ORDER BY sort_order"):
            self.comic_style.addItem(r["name"], r["value"])
        self.comic_style.addItem(tr("comic_style_custom"), "__custom__")
        self.comic_style.currentIndexChanged.connect(self._on_comic_style)
        bar.addWidget(self.comic_style)
        re_panel = W.primary_btn(tr("gen_panels"))
        re_panel.setToolTip(tr("gen_panels_tip"))
        re_panel.clicked.connect(self._split_panels)
        bar.addWidget(re_panel)
        self.comic_batch_btn = WaitingButton("▦ " + tr("batch_image"))
        self.comic_batch_btn.clicked.connect(self._batch_comic)
        bar.addWidget(self.comic_batch_btn)
        stitch_btn = W.primary_btn("⤓ " + tr("stitch_long"))
        stitch_btn.clicked.connect(self._stitch)
        bar.addWidget(stitch_btn)
        lay.addLayout(bar)

        self.comic_style_edit = C.SaveOnBlurEdit()
        self.comic_style_edit.setPlaceholderText(tr("comic_style"))
        self.comic_style_edit.setFixedHeight(52)
        self.comic_style_edit.editing_finished.connect(self._save_comic_style)
        self.comic_style_edit.setVisible(False)
        lay.addWidget(self.comic_style_edit)

        # 整话长条图(拼接后出现)
        self.comic_stitch_box = QFrame()
        self.comic_stitch_box.setObjectName("stitchBox")
        sl = QVBoxLayout(self.comic_stitch_box)
        sl.setContentsMargins(12, 12, 12, 12)
        sh = QHBoxLayout()
        st = W.h2(tr("stitch_long_img"))
        sh.addWidget(st)
        sh.addStretch(1)
        self.comic_stitch_dl = QPushButton("↓ " + tr("download"))
        self.comic_stitch_dl.clicked.connect(self._download_stitch)
        sh.addWidget(self.comic_stitch_dl)
        sl.addLayout(sh)
        self.comic_stitch_img = QLabel()
        self.comic_stitch_img.setAlignment(Qt.AlignCenter)
        self.comic_stitch_img.setFixedHeight(320)
        sl.addWidget(self.comic_stitch_img)
        self.comic_stitch_box.setVisible(False)
        lay.addWidget(self.comic_stitch_box)

        self.comic_empty = C.empty_state("▦", tr("comic_empty_title"), tr("comic_empty_desc"))
        lay.addWidget(self.comic_empty)
        self.comic_host = QWidget()
        self.comic_grid = QGridLayout(self.comic_host)
        self.comic_grid.setContentsMargins(0, 0, 0, 0)
        self.comic_grid.setHorizontalSpacing(12)
        self.comic_grid.setVerticalSpacing(12)
        lay.addWidget(self.comic_host, 1)

    def _on_comic_style(self, _idx):
        data = self.comic_style.currentData()
        self.comic_style_edit.setVisible(data == "__custom__")
        if data and data != "__custom__":
            self.comic_style_edit.setPlainText(data)
            self._save_comic_style()

    def _save_comic_style(self):
        if not hasattr(self, "comic_style_edit") or not self.comic_style_edit.isVisible():
            return
        text = self.comic_style_edit.toPlainText().strip()
        if not text:
            return
        db.ex("UPDATE dramas SET comic_style=?, updated_at=? WHERE id=?",
              (text, db.now(), self.drama_id))

    def _reload_comic(self):
        if not getattr(self, "comic_grid", None):
            return
        from . import episode_cards as C
        grid = self.comic_grid
        while grid.count():
            it = grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        rows = [dict(r) for r in db.q(
            "SELECT * FROM comic_panels WHERE episode_id=? ORDER BY panel_number",
            (self.episode_id,))]
        done_n = sum(1 for r in rows if r["image_url"])
        self.comic_panel_tag.setText(tr("panels_n", len(rows)))
        self.comic_done_tag.setText(tr("images_done", done_n, len(rows)) if rows else "")
        self.comic_empty.setVisible(not rows)
        self.comic_host.setVisible(bool(rows))
        self.comic_batch_btn.setEnabled(bool(rows))
        labels = {
            "draw": tr("draw"), "prompt_label": tr("out_prompt"),
            "narration_label": tr("narration_note"), "narration_ph": tr("comic_narration_ph"),
            "narration_hint": tr("comic_narration_hint"),
        }
        busy_ids = getattr(self, "_comic_busy", set())
        for i, r in enumerate(rows):
            card = C.ComicPanelCard(
                r, labels, busy=(r["id"] in busy_ids),
                on_draw=lambda _=False, i=r["id"]: self._one_panel_image(i),
                on_open=lambda _=False, u=r["image_url"]: self._open_image(u),
                on_narration_save=lambda t, i=r["id"]: self._save_panel_narration(i, t))
            grid.addWidget(card, i // 3, i % 3)
        grid.setRowStretch((len(rows) + 2) // 3, 1)
        self._reload_comic_stitch()

    def _save_panel_narration(self, panel_id: int, text: str):
        db.ex("UPDATE comic_panels SET narration=?, updated_at=? WHERE id=?",
              (text, db.now(), panel_id))

    def _reload_comic_stitch(self):
        row = db.q1("SELECT merged_url FROM video_merges WHERE episode_id=? AND model='comic_stitch' "
                    "ORDER BY id DESC LIMIT 1", (self.episode_id,))
        path = row["merged_url"] if row else ""
        if not path:
            self.comic_stitch_box.setVisible(False)
            return
        self.comic_stitch_box.setVisible(True)
        self.comic_stitch_img.setPixmap(W.pixmap_from_media(path, 700, 300))

    def _download_stitch(self):
        import os
        row = db.q1("SELECT merged_url FROM video_merges WHERE episode_id=? AND model='comic_stitch' "
                    "ORDER BY id DESC LIMIT 1", (self.episode_id,))
        if row and row["merged_url"]:
            os.startfile(str(config.media_url_to_path(row["merged_url"])))  # noqa

    def _open_image(self, url: str):
        from .asset_dialogs import ImageViewerDialog
        ImageViewerDialog(self, url).exec()

    def _split_panels(self):
        def job(tid):
            return comic_pipe.split_panels(self.episode_id, config_id=self.text_model.currentData(), lang=self._drama_lang)
        def done(tid, result, error):
            if error:
                err("AI")
            self._reload_comic()
        TASKMGR.submit("comic", job, done, episode_id=self.episode_id)

    def _one_panel_image(self, panel_id: int):
        if not hasattr(self, "_comic_busy"):
            self._comic_busy = set()
        self._comic_busy.add(panel_id)
        self._reload_comic()
        def job(tid):
            fp = comic_pipe.panel_image_prompt(panel_id, self.drama_id, config_id=self.text_model.currentData())
            out, _p = image_client.generate_image(
                fp, config_id=self.image_model.currentData(),
                people=comic_pipe.panel_people_count(panel_id))
            db.ex("UPDATE comic_panels SET image_url=?, updated_at=? WHERE id=?",
                  (config.path_to_media_url(out), db.now(), panel_id))
            return str(out)
        def done(tid, result, error):
            self._comic_busy.discard(panel_id)
            if error:
                err("AI")
            self._reload_comic()
        TASKMGR.submit("image", job, done, episode_id=self.episode_id)

    def _batch_comic(self):
        rows = db.q("SELECT id FROM comic_panels WHERE episode_id=? AND image_url IS NULL", (self.episode_id,))
        for r in rows:
            self._one_panel_image(r["id"])

    def _stitch(self):
        if not db.q1("SELECT id FROM video_merges WHERE episode_id=? AND model='comic_stitch'",
                     (self.episode_id,)):
            db.ex("""INSERT INTO video_merges(episode_id,provider,model,status,created_at,updated_at)
                   VALUES(?,'pillow','comic_stitch','processing',?,?)""",
                  (self.episode_id, db.now(), db.now()))
        def job(tid):
            return stitch_pipe.stitch_panels(self.episode_id)
        def done(tid, result, error):
            if error:
                err(tr("stitch_long"))
                return
            db.ex("UPDATE video_merges SET merged_url=?, updated_at=? WHERE episode_id=? AND model='comic_stitch'",
                  (config.path_to_media_url(result), db.now(), self.episode_id))
            self._reload_comic_stitch()
            ok(tr("stitch_done"))
        TASKMGR.submit("stitch", job, done, episode_id=self.episode_id)

    # ── 阶段⑥ 拼接导出 ──
    def _panel_export(self, lay):
        """成片:成片列表(横向卡带)+ 镜头素材(网格选择)+ 片头设置行。"""
        from . import episode_cards as C
        lay.setContentsMargins(16, 14, 20, 20)
        lay.setSpacing(18)

        self.export_empty = C.empty_state("⤓", tr("export_guard_title"), tr("export_guard_desc"))
        goto = W.primary_btn(tr("goto_script"))
        goto.clicked.connect(lambda: self._goto_step("raw"))
        self.export_empty.layout().addWidget(goto, 0, Qt.AlignCenter)
        lay.addWidget(self.export_empty)

        self.export_body = QWidget()
        body = QVBoxLayout(self.export_body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        # ── 成片列表 ──
        head1 = QHBoxLayout()
        t1 = QLabel(tr("merge_list_title"))
        t1.setObjectName("taskTitle")
        head1.addWidget(t1)
        self.export_count = W.muted("")
        head1.addWidget(self.export_count)
        head1.addStretch(1)
        self.export_done_btn = QPushButton("✓ " + tr("mark_done"))
        self.export_done_btn.clicked.connect(self._mark_done)
        head1.addWidget(self.export_done_btn)
        refresh = QPushButton("⟳ " + tr("refresh"))
        refresh.clicked.connect(self._reload_export)
        head1.addWidget(refresh)
        body.addLayout(head1)
        self.merge_scroll = QScrollArea()
        self.merge_scroll.setWidgetResizable(True)
        self.merge_scroll.setFixedHeight(196)
        self.merge_scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;}"
            "QScrollArea QScrollBar:horizontal{height:10px;}")
        self.merge_strip_host = QWidget()
        self.merge_strip = QHBoxLayout(self.merge_strip_host)
        self.merge_strip.setContentsMargins(0, 0, 0, 4)
        self.merge_strip.setSpacing(12)
        self.merge_strip_host.setLayout(self.merge_strip)
        self.merge_scroll.setWidget(self.merge_strip_host)
        self.merge_scroll.horizontalScrollBar().setVisible(True)
        body.addWidget(self.merge_scroll)
        self.merge_empty = QLabel(tr("merge_empty_hint"))
        self.merge_empty.setObjectName("muted")
        body.addWidget(self.merge_empty)

        # ── 镜头素材 ──
        head2 = QHBoxLayout()
        t2 = QLabel(tr("shot_materials"))
        t2.setObjectName("taskTitle")
        head2.addWidget(t2)
        self.shot_stat = W.muted("")
        head2.addWidget(self.shot_stat)
        head2.addStretch(1)
        self.sel_btn = QPushButton(tr("select_all"))
        self.sel_btn.clicked.connect(self._toggle_select_all)
        head2.addWidget(self.sel_btn)
        self.merge_btn = WaitingButton("▦ " + tr("merge_selected", 0), primary=True)
        self.merge_btn.clicked.connect(self._merge)
        head2.addWidget(self.merge_btn)
        body.addLayout(head2)
        # 拼接等待态:1s 心跳刷新「已耗时秒数」(对齐原版 mergeElapsedSec + nowTick)
        self._merge_tick = _MergeTick(self)

        # 片头设置行(导出页唯一的合并设置)。
        # 两个开关分列而非单一「加入片头」:原版 d262ac1 修的就是「叠加开了但卡片被默认值强开」——
        # 前端必须把 intro_card / intro_overlay 显式透传,否则服务端默认 true 会盖掉用户选择。
        intro_row = QHBoxLayout()
        intro_row.setSpacing(8)
        self.intro_check = QCheckBox(tr("intro_card_mode"))
        self.intro_check.toggled.connect(self._on_intro_toggle)
        intro_row.addWidget(self.intro_check)
        self.intro_overlay_check = QCheckBox(tr("intro_overlay_mode"))
        self.intro_overlay_check.toggled.connect(self._on_intro_toggle)
        intro_row.addWidget(self.intro_overlay_check)
        self.intro_title = QLineEdit()
        self.intro_title.setMaximumWidth(260)
        self.intro_title.setMaxLength(60)
        self.intro_title.setPlaceholderText(tr("intro_title_ph"))
        intro_row.addWidget(self.intro_title)
        intro_btn = QPushButton("⚙ " + tr("edit_intro"))
        intro_btn.clicked.connect(self._open_intro)
        intro_row.addWidget(intro_btn)
        intro_row.addStretch(1)
        self.intro_row = intro_row
        body.addLayout(intro_row)

        self.shot_scroll = C.scroll_host(QWidget())
        self.shot_host = self.shot_scroll.widget()
        self.shot_grid = QGridLayout(self.shot_host)
        self.shot_grid.setContentsMargins(0, 0, 0, 0)
        self.shot_grid.setSpacing(12)
        body.addWidget(self.shot_scroll, 1)
        lay.addWidget(self.export_body, 1)

        self.shot_checks: dict[int, QCheckBox] = {}
        self.shot_cards: dict[int, QWidget] = {}
        self._selected: set[int] = set()
        self._merge_cards: list[QWidget] = []     # 用于心跳刷新耗时
        self._pulse_on = False                     # 「拼接中」文字呼吸明暗
        self._merge_in_flight = False              # 有拼接在进行:按钮防重入
        self._active_merge: dict | None = None     # 拼好后自动打开的成片

    # ── 成片列表 ──
    def _reload_export(self):
        """成片页刷新:成片卡带 + 镜头素材网格 + 片头状态。"""
        if not getattr(self, "export_body", None):
            return
        from . import episode_cards as C
        rows = [dict(r) for r in db.q(
            "SELECT * FROM video_merges WHERE episode_id=? AND model='comic_stitch' "
            "ORDER BY id DESC LIMIT 1", (self.episode_id,))]
        rows += [dict(r) for r in db.q(
            "SELECT * FROM video_merges WHERE episode_id=? AND (model IS NULL OR model!='comic_stitch') "
            "ORDER BY id DESC LIMIT 30", (self.episode_id,))]
        ready = db.q1("""SELECT COUNT(*) c FROM storyboards WHERE episode_id=? AND deleted_at IS NULL
                         AND (COALESCE(video_url,'')!='' OR COALESCE(composed_video_url,'')!='')""",
                      (self.episode_id,))["c"]
        self.export_empty.setVisible(ready == 0)
        self.export_body.setVisible(ready > 0)
        self.export_count.setText(tr("items_n", len(rows)) if rows else "")
        ep = db.q1("SELECT status FROM episodes WHERE id=?", (self.episode_id,))
        self.export_done_btn.setText("✓ " + (tr("done") if ep["status"] == "done" else tr("mark_done")))
        while self.merge_strip.count():
            it = self.merge_strip.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._merge_cards = []
        self.merge_empty.setVisible(not rows)
        self.merge_scroll.setVisible(bool(rows))
        for r in rows:
            card = self._merge_card(r)
            self._merge_cards.append(card)
            self.merge_strip.addWidget(card)
        self.merge_strip.addStretch(1)
        self._reload_shot_grid()
        self._load_intro_state()

    def _merge_card(self, m: dict) -> QWidget:
        """成片卡:16:9 缩略 + 时间/时长 + 下载(对齐 .merge-card)。"""
        card = W.make_card()
        card.setFixedWidth(260)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        done = m["status"] == "completed" and bool(m["merged_url"])
        thumb = QFrame()
        thumb.setFixedHeight(146)
        thumb.setStyleSheet("background:#14161a; border-radius:8px; border:none;")
        tl = QVBoxLayout(thumb)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        if done:
            im = QLabel()
            im.setAlignment(Qt.AlignCenter)
            im.setPixmap(W.pixmap_from_media(m["merged_url"], 244, 146))
            im.setCursor(Qt.PointingHandCursor)
            im.mousePressEvent = lambda _e, mm=m: self._play_merge(mm)
            tl.addWidget(im, 1)
            play = QLabel("▶")
            play.setAlignment(Qt.AlignCenter)
            play.setStyleSheet("color:white; font-size:22px; background:transparent; border:none;")
            tl.addWidget(play, 1)
        elif m["status"] == "failed":
            lab = QLabel(m["error_msg"] or tr("merge_failed"))
            lab.setAlignment(Qt.AlignCenter)
            lab.setWordWrap(True)
            lab.setStyleSheet("color:#dc2626;")
            tl.addWidget(lab, 1)
        else:
            # 等待态:文字呼吸闪烁 + 已耗时秒数逐秒跳动,一眼可见还在拼接
            holder = QWidget()
            holder.setObjectName("mergePending")
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(4)
            wait = QLabel(tr("merging"))
            wait.setAlignment(Qt.AlignCenter)
            wait.setObjectName("mergingWait")
            hl.addWidget(wait)
            elapsed = QLabel("0s")
            elapsed.setAlignment(Qt.AlignCenter)
            elapsed.setObjectName("monoTag")
            elapsed.setProperty("mergeElapsed", m["id"])
            hl.addWidget(elapsed)
            tl.addWidget(holder, 1)
        lay.addWidget(thumb)
        meta = QHBoxLayout()
        meta.addWidget(C.mono_tag((m["created_at"] or "")[:16].replace("T", " ")))
        if m["duration"]:
            meta.addWidget(C.mono_tag(f"{int(m['duration'])}s"))
        meta.addStretch(1)
        dl = QPushButton(tr("download"))
        dl.setEnabled(done)
        dl.clicked.connect(lambda _=False, mm=m: self._download_merge(mm))
        meta.addWidget(dl)
        lay.addLayout(meta)
        return card

    def _play_merge(self, m: dict):
        from .asset_dialogs import ImageViewerDialog
        ImageViewerDialog(self, m["merged_url"], tr("merge_preview_title")).exec()

    # ── 镜头素材网格 ──
    def _all_shots(self) -> list:
        return [dict(r) for r in db.q(
            "SELECT * FROM storyboards WHERE episode_id=? AND deleted_at IS NULL "
            "ORDER BY storyboard_number", (self.episode_id,))]

    def _reload_shot_grid(self):
        grid = self.shot_grid
        while grid.count():
            it = grid.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.shot_checks.clear()
        self.shot_cards.clear()
        rows = self._all_shots()
        usable_ids = {r["id"] for r in rows if r["video_url"] or r["composed_video_url"]}
        self._selected &= usable_ids
        if not self._selected and usable_ids:
            self._selected = set(usable_ids)
        for i, r in enumerate(rows):
            grid.addWidget(self._shot_card(r), i // 4, i % 4)
        grid.setRowStretch((len(rows) + 3) // 4, 1)
        self._update_shot_stat(len(rows), len(usable_ids))

    def _shot_card(self, r: dict) -> QWidget:
        """镜头卡:16:9 缩略 + #NN + 时长 + 勾选框 + 描述 + 状态点(对齐 .exp-card)。"""
        card = W.make_card()
        card.setMinimumWidth(200)
        sid = r["id"]
        vid = r["video_url"] or r["composed_video_url"]
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        thumb = QFrame()
        thumb.setFixedHeight(112)
        thumb.setStyleSheet("background:#14161a; border-radius:6px; border:none;")
        tl = QVBoxLayout(thumb)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        if vid:
            im = QLabel()
            im.setAlignment(Qt.AlignCenter)
            im.setPixmap(W.pixmap_from_media(r["first_frame_image"] or vid, 184, 112))
            tl.addWidget(im, 1)
        else:
            ph = QLabel("🎬")
            ph.setAlignment(Qt.AlignCenter)
            ph.setStyleSheet("color:#8b909a;")
            tl.addWidget(ph, 1)
        idx = QLabel(f"#{int(r['storyboard_number']):02d}")
        idx.setObjectName("taskIndex")
        tl.addWidget(idx, 0, Qt.AlignLeft | Qt.AlignTop)
        dur = QLabel(f"{int(r['duration'] or 0)}s")
        dur.setObjectName("taskIndex")
        tl.addWidget(dur, 0, Qt.AlignRight | Qt.AlignTop)
        cb = QCheckBox("")
        cb.setChecked(sid in self._selected)
        cb.setEnabled(bool(vid))
        cb.toggled.connect(lambda on, i=sid: self._on_shot_checked(i, on))
        tl.addWidget(cb, 0, Qt.AlignRight | Qt.AlignBottom)
        lay.addWidget(thumb)
        line = QHBoxLayout()
        name = QLabel((r["content"] or r["title"] or "—")[:26])
        name.setObjectName("muted")
        name.setToolTip(r["content"] or "")
        line.addWidget(name, 1)
        dot = QLabel("●")
        dot.setStyleSheet("color:#16a34a;" if vid else "color:#c0c6cf;")
        dot.setToolTip(tr("done") if vid else tr("pending"))
        line.addWidget(dot)
        lay.addLayout(line)
        self._paint_shot_card(sid, card)
        self.shot_checks[sid] = cb
        self.shot_cards[sid] = card
        card.setCursor(Qt.PointingHandCursor)
        card.mousePressEvent = lambda _e, i=sid: self._toggle_shot(i)
        return card

    @staticmethod
    def _paint_shot_card(sid: int, card: QWidget):
        card.setStyleSheet(
            "QFrame#card{border:2px solid #f97316;}" if getattr(card, "_sel", False)
            else "QFrame#card{border:1px solid #e4e7ec;}")

    def _toggle_shot(self, sid: int):
        self._on_shot_checked(sid, sid not in self._selected)

    def _on_shot_checked(self, sid: int, on: bool):
        if on:
            self._selected.add(sid)
        else:
            self._selected.discard(sid)
        card = self.shot_cards.get(sid)
        cb = self.shot_checks.get(sid)
        if card:
            card._sel = sid in self._selected
            self._paint_shot_card(sid, card)
        if cb and cb.isChecked() != (sid in self._selected):
            cb.blockSignals(True)
            cb.setChecked(sid in self._selected)
            cb.blockSignals(False)
        rows = self._all_shots()
        usable = len([r for r in rows if r["video_url"] or r["composed_video_url"]])
        self._update_shot_stat(len(rows), usable)

    def _update_shot_stat(self, total: int, usable: int):
        self.shot_stat.setText(tr("shot_stat", usable, total, len(self._selected)))
        self.merge_btn.setText("▦ " + tr("merge_selected", len(self._selected)))
        self.merge_btn.setEnabled(len(self._selected) >= 2)
        self.sel_btn.setEnabled(bool(usable))
        self.sel_btn.setText(tr("clear_selection") if self._selected else tr("select_all"))

    def _toggle_select_all(self):
        usable = {r["id"] for r in self._all_shots() if r["video_url"] or r["composed_video_url"]}
        self._selected = set() if self._selected else set(usable)
        self._reload_shot_grid()

    # ── 片头 ──
    def _load_intro_state(self):
        d = db.q1("SELECT intro_title, intro_card, intro_overlay FROM dramas WHERE id=?",
                  (self.drama_id,))
        if not d:
            return
        # 两个勾选各自回填(此前把 intro_overlay 并进卡片勾选,重启后叠加开关永远显示未勾)
        self.intro_check.blockSignals(True)
        self.intro_check.setChecked(bool(d["intro_card"]))
        self.intro_check.blockSignals(False)
        self.intro_overlay_check.blockSignals(True)
        self.intro_overlay_check.setChecked(bool(d["intro_overlay"]))
        self.intro_overlay_check.blockSignals(False)
        self.intro_title.blockSignals(True)
        self.intro_title.setText(d["intro_title"] or "")
        self.intro_title.blockSignals(False)
        self.intro_title.setVisible(self.intro_check.isChecked() or self.intro_overlay_check.isChecked())
        if not getattr(self, "_intro_title_wired", False):
            self.intro_title.editingFinished.connect(self._save_intro_state)
            self._intro_title_wired = True

    def _on_intro_toggle(self, on: bool):
        self.intro_title.setVisible(self.intro_check.isChecked() or self.intro_overlay_check.isChecked())
        self._save_intro_state()

    def _save_intro_state(self):
        if not hasattr(self, "intro_check"):
            return
        # intro_overlay 此前漏存:勾了叠加、关掉应用,下次打开就回到未勾
        db.ex("UPDATE dramas SET intro_title=?, intro_card=?, intro_overlay=?, updated_at=? WHERE id=?",
              (self.intro_title.text().strip(), 1 if self.intro_check.isChecked() else 0,
               1 if self.intro_overlay_check.isChecked() else 0,
               db.now(), self.drama_id))

    def _merge_elapsed_sec(self, m: dict) -> str:
        """从成片记录的创建时间算已耗时秒数(心跳里逐秒跳动)。"""
        try:
            t0 = datetime.fromisoformat((m.get("created_at") or "").replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return "0s"
        return f"{max(0, int((time.time() - t0.timestamp())))}s"

    def _tick_merge_waiting(self):
        """心跳:1s 刷耗时秒数 + 0.65s 交替「拼接中」文字的呼吸明暗。"""
        self._tick_merge_elapsed()
        self._pulse_on = not self._pulse_on
        for card in getattr(self, "_merge_cards", []):
            for lab in card.findChildren(QLabel):
                if lab.objectName() == "mergingWait":
                    lab.setProperty("pulse", "1" if self._pulse_on else "0")
                    lab.style().unpolish(lab)
                    lab.style().polish(lab)

    def _tick_merge_elapsed(self):
        """心跳:只改文本,不重建列表(保住滚动位置)。"""
        rows = {r["id"]: dict(r) for r in db.q(
            "SELECT * FROM video_merges WHERE episode_id=?", (self.episode_id,))}
        for card in getattr(self, "_merge_cards", []):
            for lab in card.findChildren(QLabel):
                mid = lab.property("mergeElapsed")
                if mid is not None and mid in rows:
                    lab.setText(self._merge_elapsed_sec(rows[mid]))

    def _merge(self):
        ids = [i for i in self._selected if self.shot_checks.get(i) and self.shot_checks[i].isEnabled()]
        if self._merge_in_flight:
            info(tr("merging"))
            return
        if len(ids) < 2:
            QMessageBox.information(self, tr("export_stage"), tr("merge_needs_two"))
            return
        intro_title = self.intro_title.text().strip() or None
        # 显式传两个标志(不给 None),否则服务端 intro_card 默认 true 会把「只叠加」的设置顶开
        intro_card = self.intro_check.isChecked()
        intro_overlay = self.intro_overlay_check.isChecked()

        self._merge_in_flight = True
        self.merge_btn.setEnabled(False)
        self.merge_btn.setText("⠋ " + tr("merging"))

        def job(tid):
            return merge_pipe.merge_episode(
                self.episode_id, ids,
                intro_title=intro_title if (intro_card or intro_overlay) else None,
                intro_card=intro_card, intro_overlay=intro_overlay)

        def done(tid, result, error):
            self._merge_in_flight = False
            if self.merge_btn:
                self.merge_btn.idle()
                self.merge_btn.setText("▦ " + tr("merge_selected", len(self._selected)))
            if error:
                err(tr("export_stage"))
            else:
                ok(tr("merge_done"))
            # 先把结果刷进成片列表(「拼接中」→ 完成卡),再重选按钮态
            self._reload_export()
            # 拼好后自动打开成片预览 —— 结果立刻可见,不用再点一次
            row = db.q1("SELECT * FROM video_merges WHERE episode_id=? ORDER BY id DESC LIMIT 1",
                        (self.episode_id,))
            if result and row and row["status"] == "completed" and row["merged_url"]:
                self._play_merge(dict(row))

        TASKMGR.submit("merge", job, done, episode_id=self.episode_id)

    def _mark_done(self):
        db.ex("UPDATE episodes SET status='completed', updated_at=? WHERE id=?",
              (db.now(), self.episode_id))
        ok(tr("mark_done"))
        self._reload_export()

    def _download_merge(self, merge: dict):
        from ..core import download as dl_mod
        try:
            p = dl_mod.download_merge(merge)
            ok(f"{tr('download_ok')}:{p.name}")
        except Exception as e:  # noqa: BLE001
            err(str(e))

    def _open_intro(self):
        from .intro_dialog import IntroEditorDialog
        d = db.q1("SELECT aspect_ratio FROM dramas WHERE id=?", (self.drama_id,))
        aspect = (d["aspect_ratio"] or "16:9") if d else "16:9"
        IntroEditorDialog(self, self.drama_id, aspect, on_saved=self._reload_export).exec()
        self._load_intro_state()

    def _open_file(self, url: str | None):
        if url:
            import os
            p = config.media_url_to_path(url)
            if p.exists():
                os.startfile(str(p))  # noqa


def QInputDialog_getInt(parent, title, label, value=1, lo=1, hi=99):
    from PySide6.QtWidgets import QInputDialog
    return QInputDialog.getInt(parent, title, label, value, lo, hi)
