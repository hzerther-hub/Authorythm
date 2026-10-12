# -*- coding: utf-8 -*-
"""集制作工作台:六阶段流水线(原始内容 → AI 改写 → 视漫制作 → 分镜 → 漫画 → 拼接导出)。

顶栏:文本/图片/视频模型 + 分辨率 + 任务入口(对齐原版 episode.vue)。
侧栏:剧本 / 制作(资产·分镜·漫画) / 导出 三段步骤导航 + 进度。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QLayout, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QSizePolicy,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter,
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
from .project_page import _chapter_name_missing

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
                     + "\n【本镜画面描述】\n" + str((sb["description"] or sb["content"]) if sb else "")[:800])
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
                            tr('{} → 剧情推进,本镜着装应已不同于基础形象(置信度 {}%):按剧本语境描写当前服装,不要直接套用参考图妆造').format(name, int(round(n * 100))))
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
{r.get('description') or r.get('content') or tr('(无)')}

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


def _page_title(drama, ep) -> str:
    """集页顶部标题:项目名 · 第N集 · 章节名(有则带上,与剧集卡一致)。"""
    parts = [drama["title"], tr('episode_n').format(ep["episode_number"])]
    # ep 可能是 sqlite3.Row(无 .get),统一转 dict 取值
    ep = dict(ep) if not isinstance(ep, dict) else ep
    name = (ep.get("title") or "").strip()
    # 章节名常带「第N集 」前缀,避免与集号重复显示
    head = f"第{ep['episode_number']}集"
    if name.startswith(head):
        name = name[len(head):].strip()
    if name:
        parts.append(name)
    return " · ".join(parts)


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
        from PySide6.QtWidgets import QStyle
        back = QPushButton()
        back.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
        back.setFixedSize(30, 28)
        back.setToolTip(tr("back"))
        back.clicked.connect(self.back_requested.emit)
        top.addWidget(back)
        self.title = W.h2("")
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(QLabel(tr("text_svc") + ":"))
        self.text_model = self._mk_model_combo()
        top.addWidget(self.text_model)
        top.addWidget(QLabel(tr("image_svc") + ":"))
        self.image_model = self._mk_model_combo()
        top.addWidget(self.image_model)
        top.addWidget(QLabel(tr("video_svc") + ":"))
        self.video_model = self._mk_model_combo()
        top.addWidget(self.video_model)
        top.addWidget(QLabel(tr("faceswap_svc") + ":"))
        self.face_model = self._mk_model_combo()
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
        self.task_btn = QPushButton()
        # 原先写的是 "☰"(U+2630 卦象字符),默认字体里渲染成一个 16px 下的小糊块,
        # 几乎看不出是任务列表。改用 Qt 原生图标(与上方返回键同一套做法),跨字体稳定;
        # 拿不到图标时退回文字,不留空白按钮。
        _task_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        if _task_icon.isNull():
            self.task_btn.setText(tr("tasks"))
            self.task_btn.setFixedSize(46, 28)
        else:
            self.task_btn.setIcon(_task_icon)
            self.task_btn.setFixedSize(30, 28)
        self.task_btn.setToolTip(tr("tasks"))
        self.task_btn.clicked.connect(self._open_tasks)
        top.addWidget(self.task_btn)
        # 运行中任务数:按钮后面挂一枚小徽标(无任务时隐藏,不给顶栏添噪音)
        self.task_badge = QLabel("")
        self.task_badge.setObjectName("taskBadge")
        self.task_badge.setVisible(False)
        top.addWidget(self.task_badge)
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
        self.title.setText(_page_title(d, ep))
        # 项目级内容语言:只影响 AI 产出(runner 全部显式传 lang=self._drama_lang)。
        # 绝不能拿它调 set_language() —— 那是界面语言的全局,被内容语言覆盖后,
        # 英文界面一进中文项目就被劫持回中文(还会误触发一次"语言已切换"重建)。
        from ..core.config import resolve_content_language
        self._drama_lang = resolve_content_language(drama_id)
        # 项目画幅:视频生成必须显式下发(不传 seedance 默认 1:1,竖屏项目全变方图)
        self._drama_aspect_ratio = (d["aspect_ratio"] if "aspect_ratio" in d.keys() else "") or "9:16"
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

    def _mk_model_combo(self) -> QComboBox:
        """顶栏模型下拉:可压缩——最小宽度不随内容涨,空间不足时文本省略显示。

        默认 QComboBox 的 sizeHint 取最长条目宽,四种服务 × 长配置名在窄窗口/其它
        语言下会把顶栏撑到溢出(右侧分辨率/生成按钮被裁掉)。
        """
        c = QComboBox()
        c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        c.setMinimumContentsLength(8)
        # Expanding + 固定最小宽:空间充裕时按比例分摊,不够时也不会被压成 0 宽
        # (曾用 Ignored → 下拉框整块消失,只剩标签文字)
        c.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        c.setMinimumWidth(90)
        c.setMaximumWidth(200)
        return c

    def _reload_models(self):
        for combo, stype in ((self.text_model, "text"), (self.image_model, "image"),
                             (self.video_model, "video"), (self.face_model, "faceswap")):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr("configured"), None)
            for r in registry.list_configs(stype):
                combo.addItem((r["model"] or "").split("/")[-1] or r["model"], r["id"])
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
                        # 锁定标记用普通文字(🔒 彩色 emoji 会把下拉框行高撑高一截,
                        # 顶栏两个框比别的高就是这个原因);完整说明放悬停提示
                        name = combo.itemText(i)
                        combo.setItemText(i, "[L] " + name)
                        combo.setToolTip(tr("locked_video_model", name))
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
        """右侧任务抽屉(对齐原版 .task-drawer):浮在**当前页之上**的遮罩层。

        此前是 addWidget 进 MainWindow.stack 再 setCurrentWidget —— 那是「页面栈里的
        另一页」,会把剧集页整个顶掉,半透明遮罩下面是一片空白,看起来不像侧拉。
        现在改成挂在 central 上按页面区绝对定位的浮层:左侧当前界面仍然可见,
        只是被遮罩压暗(与参考项目一致)。
        """
        from .task_panel import TaskDrawer
        win = self.window()
        if getattr(win, "_task_drawer", None) is not None:
            return win._task_drawer          # 已开着就不重复挂
        drawer = TaskDrawer(self.episode_id, win.centralWidget())
        drawer.closed.connect(self._close_task_drawer)
        win._task_drawer = drawer
        win.sync_task_drawer_geometry()
        drawer.show()
        drawer.raise_()
        return drawer

    def _close_task_drawer(self, drawer):
        host = self.window()
        if host._task_drawer is drawer:
            host._task_drawer = None
        drawer.hide()
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
            # 纯图标按钮(用户要求去掉文字):运行中的任务数以按钮后的徽标显示
            self.task_badge.setText(str(active) if active else "")
            self.task_badge.setVisible(bool(active))
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
            # 不要在滚动区前加 stretch:它会分走一半高度,滚动视口只剩一半
            # (资产页容器被腰斩,就是这里)
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
        # WaitingButton:busy() 时内嵌盲文 spinner + 禁用,生成期间按钮自身可见等待
        self.novel_btn = WaitingButton("📕 " + tr("ai_novel"), primary=True)
        self.novel_btn.clicked.connect(self._ai_novel)
        row.addWidget(self.novel_btn)
        self.batch_btn = WaitingButton("📋 " + tr("batch_write"))
        self.batch_btn.clicked.connect(self._batch_novel)
        row.addWidget(self.batch_btn)
        self.review_badge = QPushButton("")
        self.review_badge.setToolTip(tr("review_open_hint"))
        self.review_badge.clicked.connect(self._show_review_detail)
        self.review_badge.setVisible(False)
        row.addWidget(self.review_badge)
        self.save_btn = W.primary_btn("💾 " + tr("save"))
        self.save_btn.clicked.connect(self._save_raw)
        row.addWidget(self.save_btn)
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
        install_ai_edit_shortcut(self.raw_edit, self._open_ai_edit,
                                      self._open_replace, self._open_qa,
                                      self._open_find)
        self.raw_edit.setContextMenuPolicy(Qt.CustomContextMenu)
        # AI 修改不走按钮:Ctrl+L 快捷键触发;这里只放文字提示
        raw_row = QHBoxLayout()
        raw_row.setContentsMargins(12, 4, 12, 0)
        self.ai_edit_hint = QLabel("✨ " + tr("ai_edit_shortcut_hint"))
        self.ai_edit_hint.setObjectName("muted")
        raw_row.addWidget(self.ai_edit_hint)
        # 生成过程状态条:流式思考/输出进度实时显示在这(不进正文编辑器)
        self.raw_status = QLabel("")
        self.raw_status.setObjectName("muted")
        raw_row.addWidget(self.raw_status)
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
        # 必须回库重取:self._ep 是进页面时的缓存行,生成后正文已落库,
        # 拿缓存会把旧的(空)内容又灌回编辑器 —— 表现为"生成成功但界面空白"
        ep = db.q1("SELECT * FROM episodes WHERE id=?", (self.episode_id,))
        if ep:
            self._ep = ep
        else:
            ep = self._ep
        self.raw_edit.blockSignals(True)
        self.raw_edit.setPlainText(ep["content"] or "")
        self.raw_edit.blockSignals(False)
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
            self.title.setText(_page_title(self._drama, self._ep))
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

    def _open_replace(self, editor):
        """Ctrl+R:查找替换(确定性字面替换,不走 AI;对齐原版 openReplaceBar)。"""
        from .ai_edit_dialog import ReplaceDialog
        if ReplaceDialog(self, editor).exec() == QDialog.Accepted:
            self._reload_raw()

    def _open_find(self, editor):
        """Ctrl+F:仅查找定位(替换框留空时同 Ctrl+R)。"""
        from .ai_edit_dialog import ReplaceDialog
        ReplaceDialog(self, editor, find_only=True).exec()

    def _open_qa(self, editor):
        """Ctrl+Q:AI 提问(基于项目设定+当前正文作答,不改正文;对齐原版 openQaDialog)。"""
        from .ai_edit_dialog import QaDialog
        QaDialog(self, editor, self.drama_id).exec()

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
        ok(tr("保存成功,可按 Ctrl+L 让 AI 修改本段"))

    def _novel_redline_hint(self) -> str:
        """写作红线闸门:缺哪几步(对齐原版 batchMissingSteps);齐全返回空串。"""
        try:
            # 直接从库取 work_type,避免 _drama 未就绪导致闸门失效
            row = db.q1("SELECT work_type FROM dramas WHERE id=?", (self.drama_id,))
            if not row or (row["work_type"] or "") != "novel":
                return ""
            from .novel_dialogs import gate_message
            missing = gate_message(self.drama_id)
            return tr('请先完成步骤 {} 的设定').format(missing) if missing else ""
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
            self.batch_btn.setToolTip(hint or tr("batch_write"))
        if hasattr(self, "gate_lab"):
            self.gate_lab.setText(hint)
            self.gate_lab.setVisible(bool(hint))

    def _set_raw_status(self, text: str):
        """更新生成状态条(提示行右侧);页面若已被语言切换重建,静默丢弃。"""
        try:
            if getattr(self, "raw_status", None) is not None:
                self.raw_status.setText(text)
        except RuntimeError:
            pass

    def _ai_novel(self):
        """单章生成:**流式**——思考过程实时显示在提示行右侧状态条,编辑器只放最终正文。

        写完进入审校/修复(写进 sys_task.stage,任务面板可见);按钮 busy + 工具行禁用防误点。
        """
        from ..pipeline import novel as novel_pipe
        from ..agents.prompts import load_prompt
        from ..core.db import get_setting
        from .streaming import StreamWorker
        hint = self._novel_redline_hint()
        if hint:
            warn(hint)
            return
        if getattr(self, "_novel_in_flight", False):
            return
        self._save_raw_silent()
        # 设定未齐:先同步开书规划再写(罕见分支,无流式;规划本身也是一次长调用)
        if not db.q1("SELECT novel_outline FROM dramas WHERE id=?", (self.drama_id,))["novel_outline"]:
            self._novel_in_flight = True
            self.novel_btn.busy(tr("生成中"))
            self._set_raw_row_enabled(False)
            idea = self.raw_edit.toPlainText().strip()[:6000] or self._drama["title"]

            def job0(tid):
                novel_pipe.plan_novel(self.drama_id, idea, config_id=self.text_model.currentData())
                return novel_pipe.write_chapter_with_review(
                    self.episode_id, config_id=self.text_model.currentData(), task_id=tid)

            def done0(tid, result, error):
                self._novel_done(result, error)
            TASKMGR.submit("novel", job0, done0, episode_id=self.episode_id, drama_id=self.drama_id)
            return

        self._novel_in_flight = True
        self.novel_btn.busy(tr("生成中"))
        self._set_raw_row_enabled(False)
        lang = get_setting("content_language", "zh")
        worker = StreamWorker(novel_pipe.chapter_prompt(self.episode_id),
                              system=load_prompt("novel_writer", lang),
                              config_id=self.text_model.currentData(),
                              temperature=0.6, max_tokens=None, parent=self)
        self._novel_stream = worker
        stat = {"r": 0, "c": 0}

        def on_delta(kind, chunk):
            if kind == "reasoning":
                stat["r"] += len(chunk)
                tail = chunk.strip().replace("\n", " ")[-48:]
                self._set_raw_status(f"💭 {tail}  ·  思考 {stat['r']} 字")
            else:
                stat["c"] += len(chunk)
                self._set_raw_status(f"✍️ AI 写作中… 已生成 {stat['c']} 字,完成后自动填入")

        def on_finish(text):
            self._novel_stream = None
            # 思考型模型可能把预算全花在 reasoning 上 → 正文 0 字;从思考流抢回正文
            if len(text.strip()) < 200:
                reason = worker.reasoning
                cand = reason.split("</think>", 1)[1].strip() if "</think>" in reason else ""
                if len(cand) >= 200:
                    text = cand
                    self._set_raw_status(f"⚠️ 思考超预算,已回收正文 {len(text)} 字")
                else:
                    self._novel_in_flight = False
                    if self.novel_btn:
                        self.novel_btn.idle()
                    self._set_raw_row_enabled(True)
                    self._set_raw_status("❌ " + tr("未产出正文"))
                    err(tr("模型把输出预算花在思考上,未产出正文;已提升预算,请重试"))
                    return
            self._set_raw_status("🔍 " + tr("写完,审校中…"))

            def job(tid):
                return novel_pipe.write_chapter_with_review(
                    self.episode_id, config_id=self.text_model.currentData(), task_id=tid,
                    content=text)
            TASKMGR.submit("novel", job, lambda t, r, e: self._novel_done(r, e),
                           episode_id=self.episode_id, drama_id=self.drama_id)

        def on_failed(msg):
            self._novel_stream = None
            self._novel_done(None, msg)

        worker.delta.connect(on_delta)
        worker.finished.connect(on_finish)
        worker.failed.connect(on_failed)
        worker.start()

    def _novel_done(self, result, error):
        self._novel_in_flight = False
        if self.novel_btn:
            self.novel_btn.idle()
        self._set_raw_row_enabled(True)
        self._set_raw_status("")
        if error:
            err(str(error)[:200])
        else:
            self._reload_raw()
            r = (result or {})
            msg = tr("本章已生成") + (tr(";审校发现问题并已自动修复一轮 ✅") if r.get("fixed") else "")
            QMessageBox.information(self, tr("ai_novel"), msg)

    def _set_raw_row_enabled(self, on: bool):
        """原文页工具行整体禁用/恢复(生成期间防误点其它按钮)。"""
        for b in (getattr(self, "batch_btn", None), getattr(self, "chapter_name_btn", None),
                  getattr(self, "save_btn", None), getattr(self, "style_combo", None), getattr(self, "style_combo2", None),
                  getattr(self, "rewrite_btn", None)):
            if b is not None:
                b.setEnabled(on)

    def _cfg_for(self, service_type: str):
        """该类型服务当前下拉选中的配置 id(ensure_ready 用;未选返回 None=默认最高优先级)。"""
        return {"text": getattr(self, "text_model", None),
                "image": getattr(self, "image_model", None),
                "video": getattr(self, "video_model", None),
                "faceswap": getattr(self, "face_model", None)}.get(service_type)

    def _batch_novel(self):
        """批量写本章及后续(对齐原版未提交批次的语义重定义 + 进度条 + 阶段)。"""
        from ..core.preflight import ensure_ready
        # 设定未齐 → 不写小说(按钮虽已置灰,这里再拦一道,防止其它入口绕过)
        hint = self._novel_redline_hint()
        if hint:
            warn(hint)
            return
        combo = self._cfg_for("text")
        if not ensure_ready("text", combo.currentData() if combo else None):
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
                   tr('第 {} 章').format(cur['episode_number'])
                   + (tr('现有 {} 字,未达目标 {} 字').format(body_len, target) if body_len else tr('尚未写作(目标 {} 字)').format(target))
                   + tr(",将重新生成。已有内容会被覆盖且无法撤销。确定继续?")):
                self._run_batch([cur["id"]], force=True)
            return
        # 情形二:本章已完成 → 取后续中「无正文」的前 10 章
        pending = [e for e in all_eps if e["episode_number"] > cur["episode_number"]
                   and len((e["content"] or "").strip()) < 200]
        if not pending:
            # 单集项目 / 后续都写完了:给出可操作的下一步,而不是让用户觉得"点了没反应"
            warn(tr("本章已完成,且没有待写的后续章节(想重写请用「批量」确认框里的重写,或先添加新集)"))
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
        if getattr(self, "_novel_in_flight", False):
            return
        self._novel_in_flight = True
        # 批量进度浮窗已是可见等待;按钮也进入 busy,防再点
        if getattr(self, "batch_btn", None):
            self.batch_btn.busy(tr("生成中"))
        self._set_raw_row_enabled(False)
        self._batch_ids = list(episode_ids)
        self._batch_done = 0
        self._batch_ok = 0
        self._batch_failed = 0
        self._batch_stage = ""
        from .batch_dialogs import _BatchProgressDialog
        self._batch_dialog = _BatchProgressDialog(self, len(episode_ids), self)
        self._batch_dialog.show()
        self._batch_start_ts = 0
        def job(tid):
            import threading
            from ..core import taskmgr as TM
            self._batch_start_ts = 1
            def on_progress(done, total, num):
                # 工作线程只改共享变量;UI 刷新交给已有的浮窗心跳(_tick_merge_elapsed 类),
                # 这里不能 QMetaObject 跨线程碰 UI —— 页面被切换/重建后 C++ 对象已删,会炸
                self._batch_done = done
            return novel_pipe.batch_write_chapters(
                self.drama_id, episode_ids, force=force,
                config_id=self.text_model.currentData(),
                lang=getattr(self, "_drama_lang", None),
                on_progress=on_progress)
        def done(tid, result, error):
            self._novel_in_flight = False
            if getattr(self, "batch_btn", None):
                self.batch_btn.idle()
            self._set_raw_row_enabled(True)
            r = result or {}
            if error:
                r.setdefault("failed", len(episode_ids))
            self._batch_ok = r.get("ok", 0)
            self._batch_failed = r.get("failed", 0)
            if self._batch_dialog:
                self._batch_dialog.finish(self._batch_ok, self._batch_failed)
            if r.get("ok"):
                ok(tr('批量完成:{} 章成功').format(r['ok'])
                   + (tr(',{} 章失败').format(r['failed']) if r.get("failed") else ""))
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
                   tr('将重新生成这 {} 章,已有正文会被覆盖且无法撤销。确定继续?').format(len(eps))):
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
            ok(tr('已合成朗读音频({} 段)').format(result['chunks']))
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
                err(str(error)[:220])
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
                err(str(error)[:220])
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
        # 编辑框隐藏时标题栏会被当成可扩张控件吃掉全部剩余高度(实测撑到 387px,
        # 页面看着"变形"、中间一大片空白)——固定为内容高度
        bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
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
        # 空态用 sizeHint 尺寸并垂直居中(不被拉伸成一大块)
        lay.addWidget(self.rewrite_empty, 1, Qt.AlignCenter)

        self.rewrite_loading = QLabel("⠋ " + tr("rewriting"))
        self.rewrite_loading.setObjectName("muted")
        self.rewrite_loading.setAlignment(Qt.AlignCenter)
        self.rewrite_loading.setVisible(False)
        lay.addWidget(self.rewrite_loading)

        self.script_edit = C.SaveOnBlurEdit()
        self.script_edit.setPlaceholderText(tr("script_ph"))
        self.script_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        install_ai_edit_shortcut(self.script_edit, self._open_ai_edit,
                                      self._open_replace, self._open_qa)
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
        """AI 转剧本:**流式**执行 —— 等待文案随思考/输出实时变化,并显示已生成字数。"""
        from ..pipeline import novel as novel_pipe
        from ..agents import runner
        from ..agents.prompts import load_prompt
        from ..core.db import get_setting
        from .streaming import StreamWorker
        if getattr(self, "_rewrite_running", False):
            return
        self._save_raw_silent()
        style = novel_pipe.get_novel_style(self.drama_id)
        self._rewrite_running = True
        self.rewrite_loading.setVisible(True)
        self.rewrite_empty.setVisible(False)
        btn = getattr(self, "rewrite_btn", None)
        if btn:
            btn.setEnabled(False)
        again = getattr(self, "rewrite_again", None)
        if again:
            again.setEnabled(False)
        prompt = (rewriter.rewrite_prompt(self.episode_id, style)
                  if hasattr(rewriter, "rewrite_prompt")
                  else novel_pipe.chapter_prompt(self.episode_id))
        lang = get_setting("content_language", "zh")
        worker = StreamWorker(prompt, system=load_prompt("script_rewriter", lang),
                              config_id=self.text_model.currentData(),
                              temperature=0.6, max_tokens=None, parent=self)
        self._rewrite_stream = worker
        stat = {"n": 0}

        def _tick():
            """等待文案持续变化,直到任务结束(此前是静态一行字,看着像卡死)。"""
            if not getattr(self, "_rewrite_running", False):
                return
            tail = worker.content[-18:].replace("\n", " ").strip()
            self.rewrite_loading.setText("✍️ " + tr("正在改写剧本…") + (" " + tail if tail else ""))
            QTimer.singleShot(180, _tick)

        def on_finish(text):
            self._rewrite_running = False
            self.rewrite_loading.setVisible(False)
            if btn:
                btn.setEnabled(True)
            if again:
                again.setEnabled(True)
            clean = novel_pipe._strip_think(text)
            if len(clean.strip()) < 50:
                err(tr("模型未产出有效剧本,请重试"))
                self._reload_rewrite()
                return
            db.ex("UPDATE episodes SET script_content=?, updated_at=? WHERE id=?",
                  (clean, db.now(), self.episode_id))
            self._ep = db.q1("SELECT * FROM episodes WHERE id=?", (self.episode_id,))
            self._reload_rewrite()

        def on_failed(msg):
            self._rewrite_running = False
            self.rewrite_loading.setVisible(False)
            if btn:
                btn.setEnabled(True)
            if again:
                again.setEnabled(True)
            err(str(msg)[:220])
            self._reload_rewrite()

        worker.finished.connect(on_finish)
        worker.failed.connect(on_failed)
        worker.start()
        QTimer.singleShot(0, _tick)

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
        # 图片模型下拉放到工具条最前面:先选模型,再做重提/批量等操作
        # 图片模型统一用顶栏那一个,资产页不再重复放(原先两处同步、容易让人困惑)
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
        self.clear_assets_btn = QPushButton(tr("清空资产"))
        self.clear_assets_btn.setToolTip(tr("清空本集角色/场景/道具,可重新提取生成"))
        self.clear_assets_btn.setCursor(Qt.PointingHandCursor)
        self.clear_assets_btn.setStyleSheet(
            "QPushButton{border:1px solid #f0b4b4;border-radius:6px;color:#e5484d;"
            "background:#fff5f5;padding:3px 10px;font-size:12px;}"
            "QPushButton:hover{background:#ffe9e9;}")
        self.clear_assets_btn.clicked.connect(self._clear_assets)
        bar.addWidget(self.clear_assets_btn)
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setFixedHeight(18)
        bar.addWidget(divider)
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
            n_lay.addWidget(C.section_title(
                title, add_label,
                on_add=(lambda k=kind: self._open_add_asset(k))))
            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(10)
            # 关键:不设这行,grid_host 的 sizeHint 只取布局"最小"尺寸,容器被压到
            # 几十 px,13 张角色卡只剩一张露头,其余全被裁掉(看着像"没变高")
            grid.setSizeConstraint(QLayout.SetMinimumSize)
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
                err(str(error)[:220])
            self._reload_comic_assets()
        TASKMGR.submit("image", job, done, drama_id=self.drama_id)

    def _batch_comic_assets(self):
        """漫画风格批量:链式串行(上一个个完成再提下一个)+ 按钮全程等待态。"""
        from ..pipeline import comic as comic_pipe
        tasks = [(kind, r["id"])
                 for kind, table in (("character", "characters"), ("scene", "scenes"), ("prop", "props"))
                 for r in db.q(f"SELECT id FROM {table} WHERE drama_id=? AND comic_image_url IS NULL",
                               (self.drama_id,))]
        if not tasks:
            info(tr("没有待生成的资产"))
            return
        btn = getattr(self, "_comic_batch", None)
        if btn is not None:
            btn.setEnabled(False)
            btn.setText("⠋ " + tr("in_progress"))

        def run(i: int):
            if i >= len(tasks):
                if btn is not None:
                    btn.setEnabled(True)
                    btn.setText("📕 " + tr("batch_comic_style"))
                self._reload_comic_assets()
                return
            kind, row_id = tasks[i]

            def job(tid):
                return comic_pipe.comic_asset_image(self.drama_id, kind, row_id,
                                                    config_id=self.image_model.currentData())

            def done(tid, result, error):
                if error:
                    err(str(error)[:220])
                run(i + 1)

            TASKMGR.submit("image", job, done, drama_id=self.drama_id)

        run(0)

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
        """提取资产。提取只新增、不覆盖已有同名资产,所以「已存在」时新增为 0 是正常的 ——
        必须把结果明确说出来,否则界面毫无变化会让人以为没跑。"""
        def job(tid):
            return extract_pipe.extract_assets(self.episode_id,
                                                config_id=self.text_model.currentData(),
                                                lang=self._drama_lang)
        def done(tid, result, error):
            if error:
                err(str(error)[:220])
                return
            self._reload_assets()
            st = result or {}
            added = st.get("characters", 0) + st.get("scenes", 0) + st.get("props", 0)
            if added:
                ok(tr("提取完成:新增 {} 角色 / {} 场景 / {} 道具").format(
                    st.get("characters", 0), st.get("scenes", 0), st.get("props", 0)))
            else:
                ok(tr("提取完成:没有新增(同名资产已存在)。要重新生成请用「重提角色/场景/道具」,或先「清空资产」"))
        TASKMGR.submit("extract", job, done, episode_id=self.episode_id, drama_id=self.drama_id)

    def _reload_assets(self):
        if not getattr(self, "asset_sections", None):
            return
        from . import episode_cards as C
        cols = {kind: 4 for kind in self.asset_sections}   # 用户指定固定 4 列
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
        # 标签现场翻译:字典值是中文基准,当 tr 键用
        _labels = {k: tr(v) for k, v in ASSET_LABELS.items()}
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
                card = (C.CharacterAssetCard(r, _labels, on_gen_image=self._cb_gen_image(r, kind),
                                              on_gen_text=self._cb_gen_text(r, kind),
                                              on_upload=self._cb_upload(r, kind),
                                              on_face_swap=(lambda rid=r["id"]: self._face_swap(rid))
                                              if kind == "characters" else None,
                                              on_variants=(lambda cid=r["id"]: self._open_variants(cid))
                                              if kind == "characters" else None,
                                              on_prompt=self._cb_prompt(r, kind),
                                              on_open=self._cb_open(r, kind),
                                              on_delete=self._cb_delete_asset(r, kind))
                       if kind == "characters"
                       else C.AssetCard(r, _labels, kind[:-1],
                                        on_gen=self._cb_gen_text(r, kind),
                                        on_gen_text=self._cb_gen_text(r, kind),
                                        on_gen_vary=self._cb_gen_image(r, kind),
                                        on_upload=self._cb_upload(r, kind),
                                        on_prompt=self._cb_prompt(r, kind),
                                        on_open=self._cb_open(r, kind),
                                        on_delete=self._cb_delete_asset(r, kind)))
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
        """图绘回调:基于已有形象图重绘(无图时内部会提示先文绘)。"""
        table = {"characters": "characters", "scenes": "scenes", "props": "props"}[kind]
        return lambda: self._gen_image(r["id"], table, by_text=False)

    def _cb_gen_text(self, r: dict, kind: str):
        """文绘回调:纯文字生图,不依赖也不需要已有形象图。"""
        table = {"characters": "characters", "scenes": "scenes", "props": "props"}[kind]
        return lambda: self._gen_image(r["id"], table, by_text=True)

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
        """图片模型统一由顶栏控制,资产页的重复下拉已移除(保留空实现兼容调用)。"""

    def _active_image_config(self):
        """资产生图统一跟随顶栏的图片模型(资产页重复下拉已移除)。"""
        return self.image_model.currentData()

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
                err(str(error)[:220])
            self._reload_assets()
        TASKMGR.submit("prompt", job, done, drama_id=self.drama_id, character_id=row_id if kind == "character" else None)

    def _open_add_asset(self, kind: str):
        """手动新增资产(对齐参考项目 openAssetCreate):角色/场景/道具。"""
        from .add_asset_dialog import AddAssetDialog
        dlg = AddAssetDialog(self, kind, self.drama_id, self.episode_id,
                             on_done=self._reload_assets)
        dlg.exec()

    def _cb_delete_asset(self, r: dict, kind: str):
        return lambda: self._delete_asset(r["id"], kind, r.get("name") or "")

    def _delete_asset(self, row_id: int, kind: str, name: str):
        """删除单个资产(连同本集关联),用于剔除提取错误/多余的资产。"""
        table = {"characters": "characters", "scenes": "scenes", "props": "props"}[kind]
        if ask(self, tr("删除资产"), tr("确定删除「{}」?该资产的关联记录会一并移除。").format(name)) != QMessageBox.Yes:
            return
        link = {"characters": "episode_characters", "scenes": "episode_scenes",
                "props": "episode_props"}[kind]
        db.ex(f"DELETE FROM {link} WHERE {kind[:-1]}_id=?", (row_id,))
        db.ex(f"DELETE FROM {table} WHERE id=?", (row_id,))
        self._reload_assets()
        ok(tr("已删除资产"))

    def _clear_assets(self):
        """清空本集的角色/场景/道具关联与实体,可重新提取(彻底重来)。

        只删本集独占的资产;被其它集共用的保留(否则会连带清掉别集的数据)。
        """
        if ask(self, tr("清空资产"),
               tr("将删除本集全部角色/场景/道具,可重新提取生成。确定继续?")) != QMessageBox.Yes:
            return
        n = 0
        for link, table, col in (("episode_characters", "characters", "character_id"),
                                 ("episode_scenes", "scenes", "scene_id"),
                                 ("episode_props", "props", "prop_id")):
            ids = [r[col] for r in db.q(f"SELECT {col} FROM {link} WHERE episode_id=?", (self.episode_id,))]
            for i in ids:
                others = db.q1(f"SELECT COUNT(*) c FROM {link} WHERE {col}=? AND episode_id!=?",
                               (i, self.episode_id))
                if others and others["c"]:
                    continue          # 其它集还在用,只断本集关联
                db.ex(f"DELETE FROM {table} WHERE id=?", (i,))
                n += 1
            db.ex(f"DELETE FROM {link} WHERE episode_id=?", (self.episode_id,))
        self._reload_assets()
        ok(tr("已清空本集资产,可重新提取"))

    def _gen_image(self, row_id: int, table: str, by_text: bool = False):
        """图绘(by_text=False):基于已有形象图生图重绘,保人物特征;
        文绘(by_text=True):纯文字生图,不依赖已有形象图。"""
        cur0 = db.q1(f"SELECT image_url FROM {table} WHERE id=?", (row_id,))
        has_img = bool((cur0["image_url"] or "").strip())
        if not by_text and not has_img:
            # 只有「图绘」才需要已有形象图;文绘不受限制
            ok(tr("还没有形象图,建议先用「文绘」出图,之后再用「图绘」重绘"))
            return

        def job(tid):
            return self._gen_one(row_id, table, by_text)

        def done(tid, result, error):
            if error:
                err(str(error)[:220])
            self._reload_assets()
        TASKMGR.submit("image", job, done, drama_id=self.drama_id)

    def _gen_one(self, row_id: int, table: str, by_text: bool) -> str:
        """生成单个资产形象图(文绘/图绘),落库并返回本地 URL。"""
        if True:
            row = dict(db.q1(f"SELECT * FROM {table} WHERE id=?", (row_id,)) or {})
            fp = row.get("final_prompt") or ""
            if not fp:
                kind = {"characters": "character", "scenes": "scene", "props": "prop"}[table]
                try:
                    fp = {"character": prompts_gen.character_prompt, "scene": prompts_gen.scene_prompt,
                          "prop": prompts_gen.prop_prompt}[kind](row_id, config_id=self.text_model.currentData())
                except Exception as exc:  # noqa: BLE001
                    # AI 生成最终提示词失败(模型输出异常/超时)→ 本地拼一条兜底,
                    # 风格用项目选中的视觉风格预设(如 3D 漫剧),保证批量不被打断
                    import re as _re
                    style = prompts_gen._style_prefix(self.drama_id)
                    if kind == "characters":
                        fp = (f"{style}, 单人角色立绘三视图参考图, {row.get('name', '')}, "
                              f"{(row.get('appearance') or '')[:120]}, {(row.get('styling') or '')[:80]}, "
                              "纯白背景, 柔和均匀光线")
                    elif kind == "scenes":
                        fp = (f"{style}, 场景概念图, {row.get('location') or row.get('name') or ''}, "
                              f"{(row.get('prompt') or row.get('description') or '')[:120]}, "
                              f"光照: {row.get('lighting') or '自然光'}")
                    else:
                        fp = (f"{style}, 道具特写, {row.get('name', '')}, "
                              f"{(row.get('description') or '')[:120]}, 纯色背景")
                    fp = _re.sub(r"\s+", " ", fp)
            # 图绘:把已有形象图作为参考图注入(否则与文绘相同);文绘:纯文字,不注入
            refs = []
            cur = (row["image_url"] or "").strip()
            if by_text:
                cur = ""
            if cur:
                lp = (config.media_url_to_path(cur) if cur.startswith(("/static/", "static/"))
                      else __import__("pathlib").Path(cur))
                if lp.exists() and Path(lp).name not in ("demo.png", "demo.jpg", "demo.jpeg"):
                    refs = [str(lp)]
            prompt = fp
            if refs:
                prompt = (fp + "\n严格保持参考图中的角色长相、发型、服装与配色不变，"
                          "只重绘画面细节与质感。")
            # 平台级守卫(对齐参考项目 prompt-guards):角色 1 人;场景/道具 0 人
            # (场景空镜/道具特写不该出现人 —— 此前没传守卫导致全部有人)
            people = 1 if table == "characters" else 0
            if "画面质量要求" not in prompt:   # 详情页生成的最终提示词已含守卫,不重复
                prompt = (prompt + "\n" + image_client.build_image_quality_guard(people))
            # 尺寸对齐参考:角色/场景 1920x1080(三视图/概念图横幅),道具 1024x1024(产品特写)
            size = "1024x1024" if table == "props" else "1920x1080"
            out, _provider = image_client.generate_image(prompt, config_id=self._active_image_config(),
                                                        reference_images=refs or None,
                                                        size=size, people=people)
            url = config.path_to_media_url(out)
            db.ex(f"UPDATE {table} SET image_url=?, updated_at=? WHERE id=?", (url, db.now(), row_id))
            return url

    def _batch_images(self, table: str):
        """批量生图:全走文绘,**单任务串行 + 每个间隔 3 秒**(不并发 ——
        并发会让提示词/生图接口互相踩,实测反复失败)。"""
        import time as _time
        rows = db.q(f"SELECT id FROM {table} WHERE drama_id=? AND image_url IS NULL", (self.drama_id,))
        if not rows:
            ok(tr("没有待生成的资产"))
            return
        n = len(rows)
        ok(tr("开始批量文绘,共 {} 个资产(串行,间隔 3 秒)").format(n))

        def job(tid):
            done_cnt = 0
            for i, r in enumerate(rows):
                if i:
                    _time.sleep(3)      # 延时:上一个完成后再等 3 秒
                try:
                    self._gen_one(r["id"], table, by_text=True)
                    done_cnt += 1
                except Exception as exc:  # noqa: BLE001
                    err(tr("资产 {} 失败:{}").format(r["id"], str(exc)[:100]))
            return {"done": done_cnt, "total": n}

        def done(tid, result, error):
            btn = self._batch_btns.get(table)
            if btn:
                btn.idle()
            self._reload_assets()
            if error:
                err(str(error)[:200])
            else:
                ok(tr("批量文绘完成:{}/{} 成功").format(result["done"], result["total"]))

        btn = self._batch_btns.get(table)
        if btn:
            btn.busy(tr("in_progress"))
        TASKMGR.submit("image", job, done, drama_id=self.drama_id)

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
        # 盲文等待按钮:拆分进行中转圈+禁用(等待效果与其它生成按钮一致)
        from .braille import WaitingButton
        split_btn = WaitingButton(tr("re_split"), primary=True)
        split_btn.setToolTip(tr("re_split_tip"))
        split_btn.clicked.connect(self._split_sb)
        bar.addWidget(split_btn)
        self.split_btn = split_btn
        prompts_btn = WaitingButton(tr("batch_prompts"))
        prompts_btn.clicked.connect(self._batch_vp)
        self.batch_vp_btn = prompts_btn
        bar.addWidget(prompts_btn)
        atmos_btn = WaitingButton(tr("batch_atmos"))
        atmos_btn.setToolTip(tr("batch_atmos_tip"))
        atmos_btn.clicked.connect(self._batch_atmos)
        self.batch_atmos_btn = atmos_btn
        bar.addWidget(atmos_btn)
        self.repair_btn = W.primary_btn("⟳ " + tr("auto_repair", 0))
        self.repair_btn.setToolTip(tr("auto_repair_tip"))
        self.repair_btn.setVisible(False)
        self.repair_btn.clicked.connect(self._repair_storyboards)
        bar.addWidget(self.repair_btn)
        self.batch_video_btn = WaitingButton(tr("batch_video"), primary=True)
        self.batch_video_btn.clicked.connect(self._batch_video)
        bar.addWidget(self.batch_video_btn)
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
        # 首枚常驻「所有」胶囊 —— 之前只能靠「再点同一枚状态胶囊」这种隐式行为取消筛选,
        # 而胶囊选中态只有一圈 2px 描边,用户根本看不出自己正处在筛选视图中。
        self._all_pill = C.MetricPill("all", tr("task_all"), self._filter_tasks)
        self._all_pill.setToolTip(tr("task_show_all_tip"))
        metrics.addWidget(self._all_pill)
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
        self.sb_task_rows: dict[int, "object"] = {}   # sb_id → VideoTaskRow(批量心跳原地换态)
        tl.addStretch(1)
        ll.addWidget(self.sb_task_scroll, 1)
        wb.addWidget(left)

        # 中:检查器 —— 对齐参考项目 video-main-grid:左列(描述/氛围/视频提示词/旁白)
        # 纵向堆叠,右列「参考素材」独立一列自滚动(不再是中栏底部一节)
        center = QWidget()
        cl = QHBoxLayout(center)
        cl.setContentsMargins(14, 14, 10, 14)
        cl.setSpacing(14)
        edit_col = QWidget()
        el = QVBoxLayout(edit_col)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(12)
        # 分镜描述:标题在上、文本框在下;改动后标题行右侧冒出「保存」(对齐原版
        # episode.vue 的受控草稿 + 显式保存/重置,失焦仍会静默存一次)
        desc_head = self._draft_head(tr("sb_desc_label"), "description", "inspectorLabel")
        el.addLayout(desc_head)
        self.sb_content = C.SaveOnBlurEdit()
        self.sb_content.setPlaceholderText(tr("sb_desc_ph"))
        self.sb_content.setMinimumHeight(150)
        self.sb_content.editing_finished.connect(
            lambda: self._save_sb_field("description", self.sb_content))
        el.addWidget(self.sb_content)
        atm_head = self._draft_head(tr("sb_atmosphere"), "atmosphere", "inspectorLabel")
        el.addLayout(atm_head)
        self.sb_atmosphere = C.SaveOnBlurEdit()
        self.sb_atmosphere.setPlaceholderText(tr("sb_atmosphere_ph"))
        self.sb_atmosphere.setFixedHeight(56)
        self.sb_atmosphere.editing_finished.connect(
            lambda: self._save_sb_field("atmosphere", self.sb_atmosphere))
        el.addWidget(self.sb_atmosphere)
        vp_head = self._draft_head(tr("sb_video_prompt"), "video_prompt", "heroLabel")
        self.sb_ai_prompt_btn = WaitingButton(tr("ai_generate"))
        self.sb_ai_prompt_btn.clicked.connect(self._ai_sb_prompt)
        vp_head.insertWidget(vp_head.count() - 1, self.sb_ai_prompt_btn)
        el.addLayout(vp_head)
        self.sb_video_prompt = C.SaveOnBlurEdit()
        self.sb_video_prompt.setPlaceholderText(tr("sb_video_prompt_ph"))
        self.sb_video_prompt.setMinimumHeight(140)
        self.sb_video_prompt.editing_finished.connect(
            lambda: self._save_sb_field("video_prompt", self.sb_video_prompt))
        el.addWidget(self.sb_video_prompt, 1)
        nr_head = self._draft_head(tr("sb_narration"), "narration", "inspectorLabel")
        self.sb_tts_btn = WaitingButton("🔊 " + tr("synth_narration"))
        self.sb_tts_btn.clicked.connect(self._one_tts_selected)
        nr_head.insertWidget(nr_head.count() - 1, self.sb_tts_btn)
        el.addLayout(nr_head)
        self.sb_narration = C.SaveOnBlurEdit()
        self.sb_narration.setPlaceholderText(tr("sb_narration_ph"))
        self.sb_narration.setFixedHeight(60)
        self.sb_narration.textChanged.connect(self._update_narration_count)
        self.sb_narration.editing_finished.connect(
            lambda: self._save_sb_field("narration", self.sb_narration))
        el.addWidget(self.sb_narration)
        for col, ed in (("description", self.sb_content), ("atmosphere", self.sb_atmosphere),
                        ("video_prompt", self.sb_video_prompt), ("narration", self.sb_narration)):
            self._watch_draft(col, ed)
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
        el.addLayout(nr_foot)

        # 参考素材:角色 / 场景 / 道具 三个页签 —— 参考项目里它固定在检查器
        # 右列(video-inspector-refs 占 grid-column 2),与左列编辑区并排、各自滚动
        refs_col = QWidget()
        rlay = QVBoxLayout(refs_col)
        rlay.setContentsMargins(0, 0, 0, 0)
        rlay.setSpacing(8)
        ref_head = QHBoxLayout()
        rl = QLabel(tr("ref_title"))
        rl.setObjectName("inspectorLabel")
        ref_head.addWidget(rl)
        ref_head.addStretch(1)
        self.sb_ref_count = C.mono_tag("")
        ref_head.addWidget(self.sb_ref_count)
        rlay.addLayout(ref_head)
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
        rlay.addLayout(tab_row)
        self.sb_ref_scroll = C.scroll_host(QWidget())
        self.sb_ref_host = self.sb_ref_scroll.widget()
        rl2 = QGridLayout(self.sb_ref_host)
        rl2.setContentsMargins(0, 2, 0, 0)
        rl2.setSpacing(8)
        self.sb_ref_lay = rl2
        rlay.addWidget(self.sb_ref_scroll, 1)
        refs_col.setMinimumWidth(240)
        cl.addWidget(edit_col, 21)
        cl.addWidget(refs_col, 20)
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
        # 空态区(对齐参考项目):图标 + 两行文案 + 内嵌生成按钮,而不是一行纯文本
        self.sb_player_empty = QWidget()
        el = QVBoxLayout(self.sb_player_empty)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(4)
        el.addStretch(1)
        self.sb_empty_icon = QLabel("▶")
        self.sb_empty_icon.setAlignment(Qt.AlignCenter)
        self.sb_empty_icon.setFixedSize(42, 28)
        self.sb_empty_icon.setStyleSheet(
            "border:1px solid rgba(140,140,150,0.55); border-radius:5px;"
            "color:rgba(140,140,150,0.85); font-size:13px; background:transparent;")
        eh = QHBoxLayout()
        eh.addStretch(1)
        eh.addWidget(self.sb_empty_icon)
        eh.addStretch(1)
        el.addLayout(eh)
        self.sb_empty_title = QLabel("")
        self.sb_empty_title.setObjectName("muted")
        self.sb_empty_title.setAlignment(Qt.AlignCenter)
        self.sb_empty_title.setWordWrap(True)
        el.addWidget(self.sb_empty_title)
        self.sb_empty_hint = QLabel("")
        self.sb_empty_hint.setObjectName("muted")
        self.sb_empty_hint.setAlignment(Qt.AlignCenter)
        self.sb_empty_hint.setWordWrap(True)
        el.addWidget(self.sb_empty_hint)
        # 空态生成键走黑底(blackAction),与橙色主行动键区分(用户指定)
        self.sb_empty_btn = WaitingButton(tr("generate"))
        self.sb_empty_btn.setObjectName("blackAction")
        self.sb_empty_btn.setFixedHeight(28)
        self.sb_empty_btn.clicked.connect(self._generate_selected)
        eb = QHBoxLayout()
        eb.addStretch(1)
        eb.addWidget(self.sb_empty_btn)
        eb.addStretch(1)
        el.addLayout(eb)
        el.addStretch(1)
        sl.addWidget(self.sb_player, 1)
        sl.addWidget(self.sb_player_empty)
        rl3.addWidget(stage)
        # 播放控制行:播放/暂停 + 进度条 + 时间;只在有视频时可见
        # (此前只挂了 QVideoWidget 没有任何控件,成片出来也不知道怎么播)
        self.sb_player_ctrl = QWidget()
        self.sb_player_ctrl.setVisible(False)
        pcl = QHBoxLayout(self.sb_player_ctrl)
        pcl.setContentsMargins(0, 0, 0, 0)
        pcl.setSpacing(7)
        self.sb_play_btn = QPushButton("▶")
        self.sb_play_btn.setFixedSize(34, 26)
        self.sb_play_btn.setToolTip(tr("播放"))
        self.sb_play_btn.clicked.connect(self._toggle_play)
        pcl.addWidget(self.sb_play_btn)
        self.sb_pos_slider = QSlider(Qt.Horizontal)
        self.sb_pos_slider.sliderMoved.connect(
            lambda v: self._player and self._player.setPosition(v))
        pcl.addWidget(self.sb_pos_slider, 1)
        self.sb_time_lab = QLabel("0:00 / 0:00")
        self.sb_time_lab.setObjectName("muted")
        pcl.addWidget(self.sb_time_lab)
        rl3.addWidget(self.sb_player_ctrl)
        # 历史视频:标题 + 横滚缩略行(对齐参考项目 .video-player-history;
        # 数据来自 sys_task 里该分镜已完成的 video 记录,可预览/下载/删除)
        self.sb_history = QWidget()
        hl3 = QVBoxLayout(self.sb_history)
        hl3.setContentsMargins(0, 0, 0, 0)
        hl3.setSpacing(4)
        hh = QHBoxLayout()
        self.sb_history_title = W.muted("")
        hh.addWidget(self.sb_history_title)
        self.sb_history_count = C.mono_tag("0")
        hh.addWidget(self.sb_history_count)
        hh.addStretch(1)
        hl3.addLayout(hh)
        self.sb_history_scroll = QScrollArea()
        self.sb_history_scroll.setWidgetResizable(True)
        self.sb_history_scroll.setFrameShape(QFrame.NoFrame)
        self.sb_history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.sb_history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sb_history_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.sb_history_scroll.setFixedHeight(108)
        self.sb_history_row_host = QWidget()
        self.sb_history_row = QHBoxLayout(self.sb_history_row_host)
        self.sb_history_row.setContentsMargins(0, 0, 0, 0)
        self.sb_history_row.setSpacing(6)
        self.sb_history_row.addStretch(1)
        self.sb_history_scroll.setWidget(self.sb_history_row_host)
        hl3.addWidget(self.sb_history_scroll)
        self.sb_history.setVisible(False)
        rl3.addWidget(self.sb_history)
        self._history_preview_path = ""
        bh = QHBoxLayout()
        bl = QLabel(tr("bound_refs"))
        bl.setObjectName("inspectorLabel")
        bh.addWidget(bl)
        bh.addStretch(1)
        self.sb_bound_count = C.mono_tag("")
        bh.addWidget(self.sb_bound_count)
        rl3.addLayout(bh)
        self.sb_bound_host = QWidget()
        # 绑定参考图固定单行 + 横向滚动(对齐参考项目):素材多时不再折成多行把
        # 下方参数卡顶出视野
        self.sb_bound_scroll = QScrollArea()
        self.sb_bound_scroll.setWidgetResizable(True)
        self.sb_bound_scroll.setFrameShape(QFrame.NoFrame)
        self.sb_bound_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.sb_bound_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sb_bound_scroll.setFixedHeight(122)
        self.sb_bound_scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;}"
            "QScrollArea QScrollBar:horizontal{height:9px;}")
        self.sb_bound_lay = QHBoxLayout(self.sb_bound_host)
        self.sb_bound_lay.setContentsMargins(0, 0, 0, 0)
        self.sb_bound_lay.setSpacing(6)
        self.sb_bound_lay.addStretch(1)
        self.sb_bound_scroll.setWidget(self.sb_bound_host)
        rl3.addWidget(self.sb_bound_scroll)
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
        # 卡在「生成中」时的手动停止:线程池里的 worker 没法安全强杀,所以这里做的是
        # 「摘状态」——把分镜与相关 sys_task 从 processing 归位,界面解锁可重试;
        # 真在跑的 worker 回来时会被 _cancelled_sb 拦下,不再回写结果。
        self.sb_stop_btn = QPushButton(tr("stop_generating"))
        self.sb_stop_btn.setFixedHeight(28)
        self.sb_stop_btn.setToolTip(tr("stop_generating_tip"))
        self.sb_stop_btn.clicked.connect(self._cancel_selected_video)
        self.sb_stop_btn.setVisible(False)
        rl3.addWidget(self.sb_stop_btn)
        # 右栏不留尾部 stretch:三栏等高,右栏内容不足时 stretch 会把整行
        # 底部顶出一块空白(中栏的参考素材区吃不满时就往下坠)。
        wb.addWidget(right, 1)

        lay.addWidget(self.sb_workbench, 1)
        self._sb_id = 0
        self._cancelled_sb: set = set()    # 已被用户手动停止的分镜,worker 回来时不再回写
        self._poster_queued: set = set()    # 已排队抽过海报帧的分镜,避免重复起 ffmpeg
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
        prev_id = self._sb_id
        self._render_task_list(rows)
        # 滚动条复位到顶:删除重建后旧滚动位置会保留,看起来像首个分镜排在最后
        bar = getattr(self, "sb_task_scroll", None)
        if bar is not None:
            from PySide6.QtWidgets import QScrollBar
            v = bar.verticalScrollBar()
            if v:
                v.setValue(0)
        self._load_incomplete()
        self._refresh_status()
        # 任务完成回调只走这里:右栏播放器/按钮状态也要跟着刷,否则空态按钮的
        # 旋转子会一直转到用户手动点别的镜头为止
        if self._sb_id:
            srow = db.q1("SELECT * FROM storyboards WHERE id=?", (self._sb_id,))
            if srow:
                self._refresh_video_panel(dict(srow))
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
        if hasattr(self, "sb_task_rows"):
            self.sb_task_rows.clear()
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        # 尾部补一个 stretch,下面每行都插在它前面。这里必须每次重建:
        # 少了它 lay.count()-1 会指向"最后一行",每插一行就把上一行往后挤,
        # 列表会变成 02,03,…,17,01 —— 镜头 01 跑到最后。
        lay.addStretch(1)
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
                self._shot_thumb(r),
                selected=(r["id"] == self._sb_id),
                on_click=lambda _=False, i=r["id"]: self._select_storyboard(i),
                on_action=lambda _=False, i=r["id"]: self._generate_one(i))
            lay.insertWidget(lay.count() - 1, row)
            self.sb_task_rows[r["id"]] = row
        for state, pill in self._metric_pills.items():
            pill.setText(f"{counts.get(state, 0)} {pill.text().split(' ', 1)[1]}")
            pill.setChecked(self._task_filter == state)
        # 「所有」胶囊不带计数(用户要求),状态胶囊才显示数量
        self._all_pill.setText(tr("task_all"))
        self._all_pill.setChecked(not self._task_filter)
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
        if hasattr(self, "_all_pill"):
            self._all_pill.setText(tr("task_all"))

    def _filter_tasks(self, state: str):
        """点击筛选胶囊:「所有」= 清除筛选;再点同一枚状态胶囊也取消筛选。"""
        self._task_filter = "" if (state == "all" or self._task_filter == state) else state
        self._render_task_list(self._sb_rows())

    def _shot_thumb(self, r: dict) -> str | None:
        """列表行缩略图:用视频海报帧(抽好的首帧),没有就先占位并排队抽帧。

        绝不能把视频文件直接当图片传给 pixmap_from_media —— Qt 渲染不了 mp4,
        结果永远是「🎬」占位符,出了片也看不出画面。
        """
        from ..pipeline import video_poster
        vid = r.get("composed_video_url") or r.get("video_url")
        if not vid:
            return None
        url = video_poster.poster_url(vid)
        if url:
            return url
        self._queue_poster(r["id"], vid)
        return None

    def _queue_poster_for(self, sb_id: int, vid: str, on_done=None):
        """后台补抽海报帧(不建 sys_task 记录,避免污染任务列表)。

        on_done 给播放器用:抽完之后回主线程把海报贴上去。
        """
        if sb_id in self._poster_queued:
            return
        self._poster_queued.add(sb_id)

        class _Job(QRunnable):
            def __init__(self, page, sb_id, vid, on_done):
                super().__init__()
                self.page, self.sb_id, self.vid = page, sb_id, vid
                self.on_done = on_done
                self.setAutoDelete(True)

            def run(self):
                from ..pipeline import video_poster
                from ..core import config as _cfg
                from pathlib import Path as _Path
                try:
                    src = _cfg.media_url_to_path(self.vid) if str(self.vid).startswith(
                        ("/static/", "static/")) else _Path(self.vid)
                    video_poster.extract_video_poster(src)
                except Exception:  # noqa: BLE001
                    pass
                # 回主线程刷新那一行(海报可能刚生成好)
                QTimer.singleShot(0, self.page._refresh_poster_row)
                if self.on_done is not None:
                    QTimer.singleShot(0, self.on_done)

            def __getstate__(self):
                raise TypeError  # QRunnable 不会被 pickle

        pool = getattr(self, "_poster_pool", None)
        if pool is None:
            pool = self._poster_pool = QThreadPool.globalInstance()
        pool.start(_Job(self, sb_id, vid, on_done))

    def _queue_poster(self, sb_id: int, vid: str):
        self._queue_poster_for(sb_id, vid)

    def _refresh_poster_row(self):
        """海报补抽完后只重绘受影响的行,不重建整个列表(保住滚动位置)。"""
        row = self.sb_task_rows.get(getattr(self, "_sb_id", 0))
        if row is None:
            return
        sb = db.q1("SELECT * FROM storyboards WHERE id=?", (self._sb_id,))
        if sb:
            row.refresh_thumb(self._shot_thumb(dict(sb)))

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
        # 分镜描述读 description(带【镜头N】子镜头的完整画面描述,和参考项目一致),
        # 老数据只有 content 时回退显示,免得历史分镜开出来是空的。
        for w, col in ((self.sb_atmosphere, "atmosphere"),
                       (self.sb_video_prompt, "video_prompt"), (self.sb_narration, "narration")):
            w.blockSignals(True)
            w.setPlainText(r[col] or "")
            w.blockSignals(False)
        self.sb_content.blockSignals(True)
        self.sb_content.setPlainText(r["description"] or r["content"] or "")
        self.sb_content.blockSignals(False)
        # 灌完值同步草稿基线,否则「保存」键会误以为有未保存改动
        for col in ("description", "atmosphere", "video_prompt", "narration"):
            w = {"description": self.sb_content, "atmosphere": self.sb_atmosphere,
                 "video_prompt": self.sb_video_prompt, "narration": self.sb_narration}[col]
            self._draft_saved[col] = w.toPlainText()
        for btn in getattr(self, "_draft_btn", {}).values():
            btn.setVisible(False)
        self.sb_narr_dur.blockSignals(True)
        self.sb_narr_dur.setValue(max(1, int(r["narration_duration"] or r["duration"] or 10)))
        self.sb_narr_dur.blockSignals(False)
        self.sb_duration.blockSignals(True)
        self.sb_duration.setValue(max(2, min(30, int(r["duration"] or 10))))
        self.sb_duration.blockSignals(False)
        audio = (r["video_prompt"] or "") + (r["content"] or "")
        self.sb_gen_audio.setChecked("--no-audio" not in audio and "--no_audio" not in audio)
        self._update_narration_count()
        self._refresh_video_panel(r)
        self._render_setting_tags(r)
        self._render_refs(r)
        self._render_bound_refs(r)
        self.sb_ai_prompt_btn.setEnabled(True)
        self._render_task_list(self._sb_rows())

    def _refresh_video_panel(self, r: dict):
        """右栏播放器/行动键随分镜状态刷新(不碰编辑器,可在任务完成回调里安全重跑)。"""
        state, state_label = self._sb_state(r)
        vid = r["video_url"] or r["composed_video_url"]
        self.sb_player_title.setText(
            f"{tr('shot_n', r['storyboard_number'])} · {state_label} · {int(r['duration'] or 0)}s")
        if vid:
            self._show_player(vid)
            self.sb_player_empty.setVisible(False)
            self.sb_empty_btn.idle()
        else:
            self._clear_player()
            self.sb_player_empty.setVisible(True)
            pending = state == "pending"
            self.sb_empty_title.setText(tr("video_generating") if pending else tr("no_video_yet"))
            self.sb_empty_hint.setText("" if pending else tr("gen_video_hint"))
            # 生成中 → 盲文旋转子动态等待(与其它生成按钮的等待效果一致),不用静态「生成中」文字
            if pending:
                self.sb_empty_btn.busy()
            else:
                self.sb_empty_btn.idle()
        self.sb_dl_btn.setEnabled(bool(vid))
        self.sb_tts_btn.setEnabled(bool((r["narration"] or "").strip()))
        audio_url = r["narration_audio_url"]
        self.sb_narr_audio.setText(
            f"{tr('tts_done')} · {r['narration_voice']}" if audio_url else "")
        self.sb_effective.setText(
            f"{self._video_model_name()} · {self._ep['resolution'] or '720p'} · {int(r['duration'] or 10)}s")
        self.sb_action_btn.setText(tr("redraw") if state == "done" else
                                   (tr("in_progress") if state == "pending" else tr("generate")))
        self.sb_action_btn.setEnabled(state != "pending")
        self.sb_stop_btn.setVisible(state == "pending")
        self._render_video_history()

    # ── 历史视频(对齐参考项目 sbVideoHistory / removeHistoryVideo) ──
    def _render_video_history(self):
        from . import episode_cards as C
        self._backfill_video_task_paths()
        lay = self.sb_history_row
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        lay.addStretch(1)
        if not self._sb_id:
            self.sb_history.setVisible(False)
            return
        rows = [dict(r) for r in db.q(
            """SELECT * FROM sys_task WHERE type='video' AND storyboard_id=? AND status='completed'
               AND local_path IS NOT NULL AND local_path<>'' ORDER BY created_at DESC""",
            (self._sb_id,))]
        self.sb_history.setVisible(bool(rows))
        if not rows:
            return
        self.sb_history_title.setText(tr("sb_history"))
        self.sb_history_count.setText(str(len(rows)))
        sb = db.q1("SELECT video_url FROM storyboards WHERE id=?", (self._sb_id,))
        cur_url = sb["video_url"] if sb else ""
        for r in rows:
            p = Path(r["local_path"])
            media = config.path_to_media_url(p)
            is_cur = bool(media and cur_url and cur_url == media)
            is_prev = self._history_preview_path == str(p)
            t = (r["created_at"] or "")[11:16] or "--:--"
            card = C.VideoHistoryCard(
                self._video_thumb(p), t, current=is_cur, previewing=is_prev,
                on_preview=lambda pp=str(p): self._preview_history(pp),
                on_download=lambda rr=dict(r): self._download_history(rr),
                on_delete=lambda rr=dict(r): self._delete_history(rr))
            lay.insertWidget(lay.count() - 1, card)

    def _backfill_video_task_paths(self):
        """旧任务行没存 local_path:把各分镜当前视频回填到其最新完成任务(一次性补数)。"""
        for sb in db.q("""SELECT s.id, s.video_url FROM storyboards s WHERE s.episode_id=?
                          AND s.video_url IS NOT NULL""", (self.episode_id,)):
            row = db.q1("""SELECT id FROM sys_task WHERE type='video' AND storyboard_id=?
                           AND status='completed' AND (local_path IS NULL OR local_path='')
                           ORDER BY created_at DESC LIMIT 1""", (sb["id"],))
            if row:
                p = config.media_url_to_path(sb["video_url"])
                if p.exists():
                    db.ex("UPDATE sys_task SET local_path=? WHERE id=?", (str(p), row["id"]))

    @staticmethod
    def _video_thumb(path: Path) -> str | None:
        """ffmpeg 抽第 0.5 秒一帧做视频缩略;缓存到 data/thumbs,无 ffmpeg 返回 None。"""
        import subprocess
        ff = config.find_ffmpeg()
        if not ff or not path.exists():
            return None
        out = config.DATA_DIR / "thumbs" / f"task_{path.stem}.jpg"
        if out.exists():
            return str(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run([ff, "-ss", "0.5", "-i", str(path), "-frames:v", "1",
                            "-vf", "scale=192:-2", "-y", str(out)],
                           capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:  # noqa: BLE001
            return None
        return str(out) if out.exists() else None

    def _shot_thumb_url(self, r: dict) -> str | None:
        """分镜的缩略图地址:首帧图优先,没有就 ffmpeg 抽视频首帧(QPixmap 读不了 mp4)。"""
        ff_img = r.get("first_frame_image")
        if ff_img:
            p = config.media_url_to_path(ff_img) if str(ff_img).startswith(("/static/", "static/")) else Path(ff_img)
            if p.exists():
                return str(p)
        vid = r.get("video_url") or r.get("composed_video_url")
        if vid:
            p = config.media_url_to_path(vid) if str(vid).startswith(("/static/", "static/")) else Path(vid)
            if p.exists():
                return self._video_thumb(p)
        return None

    def _preview_history(self, path_str: str):
        """点历史卡:主播放器切到该文件预览(再点当前视频则回到主视频)。"""
        self._history_preview_path = "" if self._history_preview_path == path_str else path_str
        sb = db.q1("SELECT video_url FROM storyboards WHERE id=?", (self._sb_id,))
        cur = config.media_url_to_path(sb["video_url"]) if sb and sb["video_url"] else None
        target = self._history_preview_path or (str(cur) if cur and cur.exists() else "")
        if target:
            self._show_player(target)
        self._render_video_history()

    def _download_history(self, r: dict):
        from ..core import download as dl_mod
        sb = db.q1("SELECT storyboard_number, title FROM storyboards WHERE id=?", (self._sb_id,))
        n = int(sb["storyboard_number"]) if sb else 0
        title = (sb["title"] if sb else "").strip() if sb else ""
        suffix = "_" + (r["created_at"] or "")[5:16].replace("T", "_").replace(":", "") if r.get("created_at") else ""
        fn = f"第{n:02d}镜{('_' + title) if title else ''}{suffix}.mp4"
        try:
            p = dl_mod.download_media(config.path_to_media_url(Path(r["local_path"])), fn)
            ok(tr('已下载:{}').format(p.name))
        except Exception as e:  # noqa: BLE001
            err(str(e)[:200])

    def _delete_history(self, r: dict):
        """删历史视频:先停播放释放文件句柄(Windows 占用时删不掉),确认后级联。"""
        from ..core import taskmgr as TM
        p = r["local_path"]
        sb = db.q1("SELECT video_url FROM storyboards WHERE id=?", (self._sb_id,))
        is_cur = bool(sb and sb["video_url"]
                      and config.path_to_media_url(Path(p)) == sb["video_url"])
        hint = tr("vid_del_current_hint") if is_cur else ""
        if QMessageBox.question(self, tr("delete"),
                                tr("vid_del_confirm") + (f"\n\n{hint}" if hint else ""),
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        if hasattr(self, "_player"):
            self._player.stop()
        if self._history_preview_path == p:
            self._history_preview_path = ""
        promoted = TM.delete_video_task(int(r["id"]))
        if is_cur and promoted is not None:
            info(tr("vid_promoted_ok") + (f" → {Path(promoted).name}" if promoted else ""))
        srow = db.q1("SELECT * FROM storyboards WHERE id=?", (self._sb_id,))
        if srow:
            self._refresh_video_panel(dict(srow))
        self._render_task_list(self._sb_rows())

    def _show_player(self, url: str):
        from PySide6.QtMultimedia import QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        from PySide6.QtWidgets import QVBoxLayout
        if not hasattr(self, "_player_widget"):
            self._player_widget = QVideoWidget()
            self._player_widget.setStyleSheet("border:none; border-radius:6px;")
            self._player = QMediaPlayer()
            self._player.setVideoOutput(self._player_widget)
            # 音频输出必须显式挂上(Qt6 QMediaPlayer 不再默认出声)
            from PySide6.QtMultimedia import QAudioOutput
            self._audio_out = QAudioOutput(self._player)
            self._player.setAudioOutput(self._audio_out)
            self._player_widget.setMinimumHeight(150)
            # 点击画面 = 播放/暂停(对齐 web 播放器的直觉交互)
            self._player_widget.mousePressEvent = lambda _e: self._toggle_play()
            # sb_player 原是裸 QLabel(承载空态文案),首次挂播放器时补一个布局
            if self.sb_player.layout() is None:
                vl = QVBoxLayout(self.sb_player)
                vl.setContentsMargins(0, 0, 0, 0)
            # 未播放时用海报帧占位(对齐参考项目 <video poster>):QVideoWidget 在
            # 没起播前只有一块黑,看不出这个镜头成片长什么样。
            # 必须放进 QStackedWidget **重叠**占同一格 —— 之前直接 insertWidget 到
            # 播放器下方会纵向堆叠,把 198px 的画面区劈成「上面一块黑 + 下面海报」,
            # 看起来就是图片显示不完整。
            self._poster_label = QLabel()
            self._poster_label.setAlignment(Qt.AlignCenter)
            self._poster_label.setStyleSheet("border:none;")
            self._player_stack = QStackedWidget()
            self._player_stack.setMinimumHeight(150)
            self._player_stack.addWidget(self._poster_label)   # 0 = 海报
            self._player_stack.addWidget(self._player_widget)  # 1 = 真实画面
            self.sb_player.layout().insertWidget(0, self._player_stack)
            self._player.positionChanged.connect(self._on_player_pos)
            self._player.durationChanged.connect(self._on_player_dur)
            self._player.playbackStateChanged.connect(self._on_player_state)
        self._player_widget.setVisible(True)
        self._player_widget.setStyleSheet("border:none; border-radius:6px;")
        from PySide6.QtCore import QUrl
        src = config.media_url_to_path(url) if str(url).startswith(("/static/", "static/")) else url
        self._player.setSource(QUrl.fromLocalFile(str(src)))
        self.sb_player_ctrl.setVisible(True)
        self._apply_player_poster(url)
        self._sync_play_btn()

    def _poster_show(self, on: bool):
        """切 QStackedWidget:True=海报帧,False=真实画面。二者同格,不叠高度。"""
        stack = getattr(self, "_player_stack", None)
        if stack is None:
            return
        stack.setCurrentIndex(0 if on else 1)

    def _apply_player_poster(self, url: str):
        """播放器未起播时显示海报帧;缺海报就后台补抽,抽好再贴上去。"""
        from PySide6.QtMultimedia import QMediaPlayer
        from ..pipeline import video_poster
        poster = video_poster.poster_url(url)
        if not poster:
            self._poster_label.clear()
            self._poster_show(False)      # 没海报就退回真实画面(黑),别留空白
            self._queue_poster_for(getattr(self, "_sb_id", 0), url,
                                   lambda: self._apply_player_poster(url))
            return
        from . import widgets as _W
        self._poster_label.setPixmap(_W.pixmap_from_media(poster, 640, 0))
        self._poster_show(
            self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState)

    def _on_player_state(self, state):
        """起播即切到真实画面;只在还没播过(position=0)时回到海报,避免遮住暂停画面。"""
        from PySide6.QtMultimedia import QMediaPlayer
        self._sync_play_btn()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._poster_show(False)
        elif self._player.position() == 0:
            self._poster_show(True)

    def _toggle_play(self):
        if not hasattr(self, "_player"):
            return
        from PySide6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()
        self._sync_play_btn()

    def _sync_play_btn(self):
        if not hasattr(self, "_player"):
            return
        from PySide6.QtMultimedia import QMediaPlayer
        playing = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.sb_play_btn.setText("⏸" if playing else "▶")

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        s = int(ms // 1000)
        return f"{s // 60}:{s % 60:02d}"

    def _on_player_pos(self, ms: int):
        self.sb_pos_slider.blockSignals(True)
        self.sb_pos_slider.setRange(0, max(1, int(self._player.duration())))
        self.sb_pos_slider.setValue(int(ms))
        self.sb_pos_slider.blockSignals(False)
        self.sb_time_lab.setText(f"{self._fmt_ms(ms)} / {self._fmt_ms(self._player.duration())}")

    def _on_player_dur(self, ms: int):
        self.sb_pos_slider.setRange(0, max(1, int(ms)))
        self.sb_time_lab.setText(f"0:00 / {self._fmt_ms(ms)}")

    def _clear_player(self):
        if hasattr(self, "_player"):
            self._player.stop()
            self._player_stack.setVisible(False)   # 换镜头时别留着上一镜头的画面
            lab = getattr(self, "_poster_label", None)
            if lab is not None:
                lab.clear()          # 也清掉海报,避免下个镜头短暂露出上一镜的图
        self.sb_player_ctrl.setVisible(False)

    def _update_narration_count(self):
        n = len(self.sb_narration.toPlainText())
        self.sb_narr_count.setText(f"{n}/200")

    def _draft_head(self, label: str, col: str, obj_name: str) -> QHBoxLayout:
        """检查器字段的标题行:标题 + stretch + 「保存」。

        保存键默认隐藏,内容与库里的值不一致时才出现(对齐原版受控草稿)。
        行尾留一个 stretch,调用方用 insertWidget(count()-1, …) 往里塞
        「AI 生成」「合成配音」这类操作键,顺序是 标题 …… 操作键 保存。
        """
        if not hasattr(self, "_draft_btn"):
            self._draft_btn = {}
            self._draft_saved = {}
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setObjectName(obj_name)
        row.addWidget(lab)
        row.addStretch(1)
        btn = QPushButton("💾 " + tr("save"))
        btn.setObjectName("draftSaveBtn")
        btn.setVisible(False)
        btn.clicked.connect(lambda _=False, c=col: self._commit_draft(c))
        row.addWidget(btn)
        self._draft_btn[col] = btn
        return row

    def _commit_draft(self, col: str):
        editor = {"description": self.sb_content, "atmosphere": self.sb_atmosphere,
                  "video_prompt": self.sb_video_prompt, "narration": self.sb_narration}.get(col)
        if editor is None:
            return
        self._save_sb_field(col, editor)
        self._draft_saved[col] = editor.toPlainText()
        btn = self._draft_btn.get(col)
        if btn:
            btn.setVisible(False)

    def _watch_draft(self, col: str, editor):
        """把文本框接到该字段的「保存」键上:改了就显示,一致就隐藏。"""
        def sync():
            btn = self._draft_btn.get(col)
            if btn:
                btn.setVisible(editor.toPlainText() != self._draft_saved.get(col, ""))
        editor.textChanged.connect(sync)

    def _save_sb_field(self, col: str, editor):
        if not self._sb_id:
            return
        text = editor.toPlainText()
        db.ex(f"UPDATE storyboards SET {col}=?, updated_at=? WHERE id=?",
              (text, db.now(), self._sb_id))
        self._draft_saved[col] = text
        btn = self._draft_btn.get(col)
        if btn:
            btn.setVisible(False)

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

    # 占位大字取当前语言种类名首字(zh→角/景/具,en→C/S/P,ja→役/景/道)
    REF_KIND_KEY = {"character": "角色", "scene": "场景", "prop": "道具"}

    def _ref_placeholder(self, kind: str) -> str:
        return tr(self.REF_KIND_KEY.get(kind, kind))[:1]

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
            card = C.RefCard(row.get("image_url"), self._ref_placeholder(kind), name,
                             tr(REF_TAB_KEYS[kind]), state,
                             on_generate=(lambda _id=row["id"]: self._goto_assets(_id))
                             if (is_bound and not has_img) else None)
            card.setProperty("bound", "1" if is_bound else "0")
            card.style().unpolish(card)
            card.style().polish(card)
            lay.addWidget(card, i // 2, i % 2)
        lay.setRowStretch((len(rows) + 1) // 2, 1)
        self.sb_ref_count.setText(tr("bound_n", len(bound), len(rows)))
        for k, b in self._ref_tab_btns.items():
            b.setText(f"{tr(REF_TAB_KEYS[k])} {len(self._ref_rows(k))}")

    def _goto_assets(self, row_id: int):
        self._goto_step("assets")

    def _render_bound_refs(self, r: dict):
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
            lay.addWidget(empty)
            lay.addStretch(1)
            return
        for row, kind in cells:
            host = QWidget()
            host.setStyleSheet("border:none;")
            host.setFixedWidth(86)
            hl = QVBoxLayout(host)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(2)
            thumb = QLabel()
            thumb.setFixedSize(78, 60)
            thumb.setAlignment(Qt.AlignCenter)
            # 角色按「人工指定变体 → 按场景标签自动匹配 → 基础形象」的顺序取图,
            # 与 refs._variant_image_of 同一套优先级,保证缩略图 = 实际送进视频的参考图
            if kind == "character":
                from ..pipeline import refs as _refs
                url = _refs._variant_image_of(row["id"], r)
            else:
                url = row.get("image_url")
            thumb.setPixmap(W.pixmap_from_media(url, 78, 60))
            hl.addWidget(thumb)
            nm = QLabel((row.get("name") or row.get("location") or "")[:8])
            nm.setObjectName("muted")
            nm.setAlignment(Qt.AlignCenter)
            nm.setToolTip(row.get("name") or row.get("location") or "")
            hl.addWidget(nm)
            if kind == "character":
                hl.addWidget(self._variant_picker(row["id"]))
            else:
                hl.addStretch(1)
            lay.addWidget(host)
        lay.addStretch(1)

    def _variant_picker(self, character_id: int) -> QComboBox:
        """单个角色的造型变体选择器(对齐参考项目的「自动解析」下拉)。

        首项「自动解析」= 不写variant_id,交由 refs 按分镜 setting_tags 自动匹配;
        其余项为该角色的造型变体,选中即人工锁定。
        """
        cur = db.q1("SELECT variant_id FROM storyboard_characters "
                    "WHERE storyboard_id=? AND character_id=?", (self._sb_id, character_id))
        cur_vid = (cur["variant_id"] if cur else None) or None
        combo = QComboBox()
        combo.setFixedSize(78, 22)
        combo.setToolTip(tr("auto_resolve_variant"))
        combo.addItem(tr("auto_resolve_variant"), None)
        for v in db.q("SELECT id,label FROM character_variants WHERE character_id=? "
                       "ORDER BY is_default DESC, sort_order ASC, id", (character_id,)):
            combo.addItem((v["label"] or "")[:9], v["id"])
        if cur_vid is not None:
            idx = combo.findData(cur_vid)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            else:
                # 变体已被删除:退回自动解析,并清掉悬空的 variant_id
                db.ex("UPDATE storyboard_characters SET variant_id=NULL "
                      "WHERE storyboard_id=? AND character_id=?", (self._sb_id, character_id))
        if combo.count() == 1:
            combo.setToolTip(tr("no_variants_yet"))
        combo.currentIndexChanged.connect(
            lambda _i, cid=character_id, cb=combo: self._set_sb_variant(cid, cb.currentData()))
        return combo

    def _set_sb_variant(self, character_id: int, variant_id):
        """写入分镜↔角色的变体覆盖,并重绘参考图缩略图。"""
        if not self._sb_id:
            return
        db.ex("UPDATE storyboard_characters SET variant_id=? "
              "WHERE storyboard_id=? AND character_id=?",
              (variant_id, self._sb_id, character_id))
        row = db.q1("SELECT * FROM storyboards WHERE id=?", (self._sb_id,))
        if row:
            self._render_bound_refs(dict(row))

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
                err(str(error)[:220])
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
            ok(tr('已下载:{}').format(p.name))
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
            self.repair_btn.setText(tr('⟳ 自动补全 {}').format(n))

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
                warn(tr('补全完成,{} 个失败可重试').format(r['failed']))
            else:
                ok(tr('补全完成,共修复 {} 个分镜').format(r.get('completed', 0)))
            self._reload_storyboard()
        TASKMGR.submit("sb_repair", job, done, episode_id=self.episode_id)

    def _split_sb(self):
        """重新拆分分镜(改后台任务 + 轮询,对齐原版 split-async)。"""
        from ..core.preflight import ensure_ready
        combo = self._cfg_for("text")
        if not ensure_ready("text", combo.currentData() if combo else None):
            return
        if self._sb_split_running:
            return
        split_btn = getattr(self, "split_btn", None)
        if split_btn:
            split_btn.busy(tr("拆分中"))
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

    def _after_split_chain(self):
        """拆分完成后的自动链:修复轮 → 批量补齐提示词(均串行,不并发)。"""
        import time as _time

        def repair_job(tid):
            return R.repair_storyboards(self.episode_id,
                                        config_id=self.text_model.currentData(),
                                        lang=getattr(self, "_drama_lang", None))

        def repair_done(tid, result, error):
            st = (result or {})
            if error:
                err(str(error)[:160])
            else:
                ok(tr("分镜修复完成:{}/{} 成功").format(st.get("completed", 0), st.get("total", 0)))
            self._reload_storyboard()
            # 批量补齐缺 video_prompt 的分镜(串行服务,内部逐镜跑)
            TASKMGR.submit("prompt", _vp_job, _vp_done, episode_id=self.episode_id,
                           drama_id=self.drama_id)

        def _vp_job(tid):
            return sb_pipe.gen_video_prompts(self.episode_id,
                                             config_id=self.text_model.currentData(),
                                             lang=getattr(self, "_drama_lang", None))

        def _vp_done(tid, result, error):
            sb = getattr(self, "split_btn", None)
            if sb:
                sb.idle()
            if error:
                err(str(error)[:160])
            else:
                ok(tr("批量补齐提示词完成:{}"))
            self._reload_storyboard()

        TASKMGR.submit("sb_repair", repair_job, repair_done, episode_id=self.episode_id,
                       drama_id=self.drama_id)

    def _poll_sb_split(self, tid: int, attempt: int):
        """每 6 秒轮询拆分任务(对齐原版 6000ms)。"""
        from PySide6.QtCore import QTimer
        if attempt > 200:            # 约 20 分钟兜底
            self._sb_split_running = False
            sb = getattr(self, "split_btn", None)
            if sb:
                sb.idle()
            warn(tr("分镜拆分超时,请到任务面板查看")); return
        def tick():
            row = db.q1("SELECT status, local_path, error_msg FROM sys_task WHERE id=?", (tid,))
            st = row["status"] if row else "failed"
            if st == "processing":
                QTimer.singleShot(6000, lambda: self._poll_sb_split(tid, attempt + 1))
                return
            self._sb_split_running = False
            sb = getattr(self, "split_btn", None)
            if st != "completed":
                if sb:
                    sb.idle()
                err(row["error_msg"] or tr("分镜拆分失败"))
                return
            self._reload_storyboard()
            ok(row["local_path"] or tr("分镜拆分完成"))
            # ── 自动串(对齐参考项目 split → repair → video-prompts 链):──
            # 修复轮(补 image_prompt/角色绑定)→ 批量补齐缺视频提示词,全程串行
            if sb:
                sb.busy(tr("修复分镜中"))
            self._after_split_chain()
        QTimer.singleShot(6000, tick)

    def _batch_vp(self):
        btn = getattr(self, "batch_vp_btn", None)

        def job(tid):
            return sb_pipe.gen_video_prompts(self.episode_id, config_id=self.text_model.currentData(), lang=self._drama_lang)

        def done(tid, result, error):
            if btn:
                btn.idle()
            if error:
                err(str(error)[:220])
            else:
                QMessageBox.information(self, tr("batch_prompts"), f"OK: {result}")
        if btn:
            btn.busy(tr("in_progress"))
        TASKMGR.submit("prompt", job, done, episode_id=self.episode_id)

    def _batch_atmos(self):
        """整集按四层规范重写氛围(旧规则拆的分镜不用重拆也能升到新规范)。"""
        btn = getattr(self, "batch_atmos_btn", None)
        rows = db.q("SELECT COUNT(*) c FROM storyboards WHERE episode_id=?", (self.episode_id,))["c"]
        if not rows:
            info(tr("请先「重新拆分」生成分镜"))
            return
        if not ask(self, tr("batch_atmos"),
                   tr("batch_atmos_confirm").format(rows)):
            return

        def job(tid):
            return sb_pipe.gen_atmospheres(self.episode_id, config_id=self.text_model.currentData(),
                                           lang=self._drama_lang)

        def done(tid, result, error):
            if btn:
                btn.idle()
            if error:
                err(str(error)[:220])
            else:
                ok(tr("氛围补齐完成:{}/{}").format(result, rows))
            self._reload_storyboard()
            if self._sb_id:
                self._select_storyboard(self._sb_id)
        if btn:
            btn.busy(tr("in_progress"))
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
                   tr("即将生成 {} 个镜头(约 {}s)\n模型:{}\n分辨率:{}\n当前任务:{} {} · {} {}\n\n确认开始?")
                   .format(len(rows), int(total), model_txt, self.res_combo.currentText(),
                           tr("done"), stats["completed"], tr("failed"), stats["failed"])):
            return
        # 串行:单任务内逐镜生成,每个间隔 3 秒(并发会撞上游限流/队列满)
        import time as _time
        from ..core import taskmgr as _TM

        self._batch_video_total = len(rows)
        self._batch_video_done0 = db.q1(
            "SELECT COUNT(*) c FROM storyboards WHERE episode_id=? "
            "AND (video_url IS NOT NULL OR composed_video_url IS NOT NULL)",
            (self.episode_id,))["c"]

        def job(tid):
            done_n = 0
            fails: list[str] = []
            for i, r in enumerate(rows):
                if i:
                    _time.sleep(3)
                _TM.set_stage(tid, f"{i + 1}/{len(rows)}")   # 任务面板显示进行到第几镜
                try:
                    self._gen_one_video(r["id"])
                    done_n += 1
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc).replace("\n", " ")[:120]
                    fails.append(f"#{r['id']}:{msg}")
                    err(tr("镜头 {} 失败:{}").format(i + 1, msg))
                    # 失败也写进阶段标记:toast 一闪就没,任务面板要能查到哪镜为什么挂
                    _TM.set_stage(tid, f"{i + 1}/{len(rows)} · 最近失败 {msg}")
            return {"done": done_n, "total": len(rows), "fails": fails}

        def done(tid, result, error):
            btn = getattr(self, "batch_video_btn", None)
            if btn:
                btn.idle()
            tick = getattr(self, "_batch_tick", None)
            if tick is not None:
                tick.stop()
            if error:
                err(str(error)[:200])
            elif result.get("fails"):
                ok(tr("批量视频完成:{}/{} 成功").format(result["done"], result["total"])
                   + "\n" + "\n".join(result["fails"][:6]))
            else:
                ok(tr("批量视频完成:{}/{} 成功").format(result["done"], result["total"]))
            self._reload_storyboard()

        # 此前这里写的是局部名 video_btn —— 它只是上面工具条方法里的局部变量,
        # _batch_video 是另一个方法,取不到这个名字,一点「批量视频」就 NameError。
        btn = getattr(self, "batch_video_btn", None)
        if btn:
            btn.busy(tr("in_progress"))
        tid = TASKMGR.submit("video", job, done, episode_id=self.episode_id, drama_id=self.drama_id)
        # 批量心跳:任务行/统计胶囊/按钮进度每 2.5s 同步一次(不用等全部跑完),
        # 当前正在生成的行会转圈,一眼看出进行到哪一镜
        if tid:
            self._batch_video_tid = tid
            if not hasattr(self, "_batch_tick"):
                self._batch_tick = QTimer(self)
                self._batch_tick.setInterval(2500)
                self._batch_tick.timeout.connect(self._tick_batch_video)
            self._batch_tick.start()

    def _tick_batch_video(self):
        """批量视频进行中的界面同步:任务行原地换态 + 胶囊计数 + 按钮进度 N/M。"""
        tid = getattr(self, "_batch_video_tid", 0)
        t = db.q1("SELECT status FROM sys_task WHERE id=?", (tid,)) if tid else None
        if not t or t["status"] != "processing":
            self._batch_tick.stop()
            return
        rows = self._sb_rows()
        total = getattr(self, "_batch_video_total", 0)
        done0 = getattr(self, "_batch_video_done0", 0)
        done_now = sum(1 for r in rows if r["video_url"] or r["composed_video_url"])
        btn = getattr(self, "batch_video_btn", None)
        if btn and total:
            btn.setText(f"{min(max(done_now - done0, 0), total)}/{total}")
        self._update_metric_pills(TASKMGR.ep_video_stats(self.episode_id))
        # 行状态原地更新(不重建,保住滚动位置):完成/失败/正在生成的都即时反映
        for sid, row_w in getattr(self, "sb_task_rows", {}).items():
            r = next((x for x in rows if x["id"] == sid), None)
            if not r:
                continue
            state, state_label = self._sb_state(r)
            scene = self._sb_scene_name(r)
            dur = int(r.get("duration") or 0)
            meta = " · ".join([state_label, f"{dur}s"] + ([scene] if scene else []))
            action_tip = {"done": tr("redraw"), "pending": tr("in_progress"),
                          "failed": tr("retry"), "ready": tr("generate")}[state]
            row_w.set_state(state, state_label, meta,
                            r.get("composed_video_url") or r.get("video_url"))
            row_w.act_btn.setToolTip(action_tip)

    def _drama_aspect(self) -> str:
        return getattr(self, "_drama_aspect_ratio", "9:16")

    def _gen_one_video(self, sb_id: int) -> str:
        """同步生成本镜视频(批量串行路径逐镜调用);失败置 failed 并抛出。"""
        from ..pipeline import shot_tools
        res = self.res_combo.currentText()
        sb = db.q1("SELECT * FROM storyboards WHERE id=?", (sb_id,))
        db.ex("UPDATE storyboards SET status='processing' WHERE id=?", (sb_id,))
        try:
            prompt = shot_tools.resolve_prompt(dict(sb))
            ref_list = shot_tools.collect_reference_images(self.episode_id, sb_id)
            # 无首帧先补一张「有景物有人物」的定场帧再生成 —— 纯文生视频
            # 开场常是黑帧/空镜,成片第一眼没有画面(用户要求第一帧必须带景带人)
            first_frame = sb["first_frame_image"]
            # generate_video 的下游(agnes _inline / video_contract)全部按 str 处理,
            # media_url_to_path 返回 Path,必须在这里转掉 —— 不转就是
            # 'WindowsPath' object has no attribute 'startswith' 整镜崩溃
            if first_frame:
                first_frame = str(config.media_url_to_path(first_frame))
            else:
                first_frame = str(config.media_url_to_path(shot_tools.generate_first_frame(
                    self.episode_id, sb_id, config_id=self.image_model.currentData())))
            path, _p = video_client.generate_video(
                prompt[:1500], resolution=res, duration=int(sb["duration"] or 8),
                first_frame=first_frame, reference_images=ref_list,
                config_id=self.video_model.currentData(),
                aspect_ratio=self._drama_aspect())
            # 用户在跑的过程中点了「停止生成」→ 丢弃这次结果,别把已归位的状态再写回去
            if sb_id in self._cancelled_sb:
                self._cancelled_sb.discard(sb_id)
                raise RuntimeError(tr("stopped_by_user"))
            db.ex("UPDATE storyboards SET video_url=?, status='completed', updated_at=? WHERE id=?",
                  (config.path_to_media_url(path), db.now(), sb_id))
            # 出片即抽海报帧(worker 线程里做,不卡界面);列表缩略图直接用首帧,
            # 不用整个视频去渲染(Qt 渲染不了 mp4)
            try:
                from ..pipeline import video_poster
                video_poster.extract_video_poster(path)
            except Exception:  # noqa: BLE001
                pass
            return str(path)
        except Exception:
            db.ex("UPDATE storyboards SET status='failed' WHERE id=?", (sb_id,))
            raise

    def _cancel_selected_video(self):
        """手动停止卡在「生成中」的分镜。

        QThreadPool 里的 worker 无法安全强杀,所以这里做「摘状态」:
        分镜与相关 sys_task 从 processing 归位为 failed,界面立刻解锁可重试。
        真在跑的 worker 结束时会被 _cancelled_sb 拦下,不再回写结果。
        """
        sb_id = self._sb_id
        if not sb_id:
            return
        row = db.q1("SELECT status FROM storyboards WHERE id=?", (sb_id,))
        if not row or row["status"] != "processing":
            return
        if not ask(self, tr("stop_generating"), tr("stop_generating_confirm")):
            return
        self._cancelled_sb.add(sb_id)
        db.ex("UPDATE storyboards SET status='failed', updated_at=? WHERE id=?", (db.now(), sb_id))
        n = db.ex("UPDATE sys_task SET status='failed', error_msg=?, updated_at=? "
                  "WHERE status='processing' AND storyboard_id=?",
                  (tr("stopped_by_user"), db.now(), sb_id))
        self._reload_storyboard()
        if self._sb_id == sb_id:
            self._select_sb(sb_id)
        warn(tr("stopped_by_user") if not n else
             tr("stop_generating_done").format(n))

    def _gen_video_job(self, sb_id: int):
        # 立即置 processing 并刷新:任务行操作键/右栏马上进入旋转等待态,
        # 不用等后台线程真正跑起来(status 由 _gen_one_video 再写一次,值相同)
        db.ex("UPDATE storyboards SET status='processing' WHERE id=?", (sb_id,))
        self._render_task_list(self._sb_rows())
        if self._sb_id == sb_id:
            srow = db.q1("SELECT * FROM storyboards WHERE id=?", (sb_id,))
            if srow:
                self._refresh_video_panel(dict(srow))

        def job(tid):
            p = self._gen_one_video(sb_id)
            # 成片路径落任务行(历史视频列表据此展示;对齐参考项目 local_path)
            from ..core import taskmgr as _TM
            _TM.finish_task(tid, "completed", local_path=str(p))
            return p
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
            self.comic_style.addItem(tr(r["name"]), r["value"])   # 预设名随语言,自建预设原样回退
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
                on_narration_save=lambda t, i=r["id"]: self._save_panel_narration(i, t),
                on_erase=lambda _=False, i=r["id"], u=r["image_url"]: self._erase_panel(i, u))
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

    def _open_merger_tool(self):
        """本地无损合并工具(从成片面板进入)。"""
        from .merger_tool_page import MergerToolPage
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("merger_title"))
        dlg.resize(1080, 720)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(MergerToolPage())
        dlg.exec()

    def _erase_panel(self, panel_id: int, url: str):
        """漫画格擦除:画笔涂抹 → 程序化填充 → 刷新漫画板。"""
        from .mask_erase_dialog import open_erase_dialog
        open_erase_dialog(self, url, "panel", panel_id,
                          on_done=self._reload_comic, title=tr("擦除漫画格"))

    def _restore_panel(self, panel_id: int):
        from ..pipeline import erase as ER
        from .toast import err, ok
        try:
            ER.restore_original("panel", panel_id)
            ok(tr("已还原原图"))
            self._reload_comic()
        except Exception as e:  # noqa: BLE001
            err(str(e)[:200])

    def _split_panels(self):
        def job(tid):
            return comic_pipe.split_panels(self.episode_id, config_id=self.text_model.currentData(), lang=self._drama_lang)
        def done(tid, result, error):
            if error:
                err(str(error)[:220])
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
                size="1024x1536",
                people=comic_pipe.panel_people_count(panel_id))
            db.ex("UPDATE comic_panels SET image_url=?, updated_at=? WHERE id=?",
                  (config.path_to_media_url(out), db.now(), panel_id))
            return str(out)
        def done(tid, result, error):
            self._comic_busy.discard(panel_id)
            if error:
                err(str(error)[:220])
            self._reload_comic()
        TASKMGR.submit("image", job, done, episode_id=self.episode_id)

    def _batch_comic(self):
        """漫画批量配图:逐格**链式串行**(上一格完成再提下一格,不并发踩生图接口),
        按钮全程等待态,最后一格完成才恢复(对齐其它批量按钮的等待效果)。"""
        rows = db.q("SELECT id FROM comic_panels WHERE episode_id=? AND image_url IS NULL", (self.episode_id,))
        if not rows:
            info(tr("没有待生成的资产"))
            return
        if not hasattr(self, "_comic_busy"):
            self._comic_busy = set()
        ids = [r["id"] for r in rows]
        self._comic_busy.update(ids)
        btn = getattr(self, "comic_batch_btn", None)
        if btn:
            btn.busy(tr("in_progress"))

        def run(i: int):
            if i >= len(ids):
                if btn:
                    btn.idle()
                self._reload_comic()
                return
            pid = ids[i]

            def job(tid):
                fp = comic_pipe.panel_image_prompt(pid, self.drama_id,
                                                    config_id=self.text_model.currentData())
                out, _p = image_client.generate_image(
                    fp, config_id=self.image_model.currentData(),
                    size="1024x1536",
                    people=comic_pipe.panel_people_count(pid))
                db.ex("UPDATE comic_panels SET image_url=?, updated_at=? WHERE id=?",
                      (config.path_to_media_url(out), db.now(), pid))
                return str(out)

            def done(tid, result, error):
                self._comic_busy.discard(pid)
                if error:
                    err(str(error)[:220])
                run(i + 1)          # done 在主线程回调,链式提交下一格

            TASKMGR.submit("image", job, done, episode_id=self.episode_id)

        self._reload_comic()
        run(0)

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
        # 本地无损合并工具(独立文件合并,归到成片处;对齐 easymerger)
        self.merger_btn = QPushButton("⧉ " + tr("merger_title"))
        self.merger_btn.setToolTip(tr("merger_intro"))
        self.merger_btn.clicked.connect(self._open_merger_tool)
        head1.addWidget(self.merger_btn)
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

        # 片头行(对齐参考项目 .export-intro-row):「加入片头」单开关 + 片头名 + 编辑键;
        # 开关是**会话内**状态(参考 introEnabled 不落库),模式(标题卡/叠加)在编辑器里设。
        intro_row = QHBoxLayout()
        intro_row.setSpacing(8)
        self.intro_check = QCheckBox(tr("intro_add"))
        self.intro_check.toggled.connect(self._on_intro_toggle)
        intro_row.addWidget(self.intro_check)
        self.intro_title = QLineEdit()
        self.intro_title.setMaximumWidth(260)
        self.intro_title.setMaxLength(60)
        self.intro_title.setPlaceholderText(tr("intro_title_ph"))
        self.intro_title.setVisible(False)
        intro_row.addWidget(self.intro_title)
        intro_btn = QPushButton("⚙ " + tr("edit_intro"))
        intro_btn.clicked.connect(self._open_intro)
        intro_btn.setVisible(False)
        self.intro_edit_btn = intro_btn
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
        self._order: dict[int, int] = {}        # 镜头 → 拼接序号(用户手动调过才有)
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
        from .asset_dialogs import VideoPreviewDialog
        VideoPreviewDialog(self, m["merged_url"], tr("merge_preview_title")).exec()

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
        """镜头卡:16:9 缩略 + #NN + 时长 + 勾选框 + 预览键 + 排序输入 + 描述 + 状态点
        (对齐 .exp-card:选中后缩略上冒出序号框,输 N 与第 N 位互换)。"""
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
        tl.setContentsMargins(4, 4, 4, 4)
        tl.setSpacing(0)
        if vid:
            im = QLabel()
            im.setAlignment(Qt.AlignCenter)
            # 首帧图优先,没有就抽视频首帧(QPixmap 读不了 mp4,直接塞是灰块)
            im.setPixmap(W.pixmap_from_media(self._shot_thumb_url(r) or vid, 184, 112))
            tl.addWidget(im, 1)
        else:
            ph = QLabel("🎬")
            ph.setAlignment(Qt.AlignCenter)
            ph.setStyleSheet("color:#8b909a;")
            tl.addWidget(ph, 1)
        top = QHBoxLayout()
        idx = QLabel(f"#{int(r['storyboard_number']):02d}")
        idx.setObjectName("taskIndex")
        top.addWidget(idx)
        top.addStretch(1)
        dur = QLabel(f"{int(r['duration'] or 0)}s")
        dur.setObjectName("taskIndex")
        top.addWidget(dur)
        tl.addLayout(top)
        bot = QHBoxLayout()
        # 单镜预览(对齐 .exp-play):成片/单镜共用视频预览弹窗
        pv = QPushButton("▶")
        pv.setFixedSize(30, 22)
        pv.setToolTip(tr("preview"))
        pv.setEnabled(bool(vid))
        if vid:
            pv.setStyleSheet("background:rgba(0,0,0,0.55); color:white; border:none; border-radius:4px;")
            pv.clicked.connect(lambda _=False, u=vid: self._preview_shot(u))
        bot.addWidget(pv)
        bot.addStretch(1)
        # 排序输入:选中后出现,输 N 与当前第 N 位互换(对齐 exp-order-input)
        order_spin = QSpinBox()
        order_spin.setFixedSize(46, 22)
        order_spin.setToolTip(tr("order_hint"))
        sel_ids = self._ordered_selected()
        order_spin.setRange(1, max(1, len(sel_ids)))
        if sid in self._order:
            order_spin.setValue(self._order[sid])
        elif sid in sel_ids:
            order_spin.setValue(sel_ids.index(sid) + 1)
        order_spin.setVisible(sid in self._selected)
        order_spin.valueChanged.connect(lambda v, i=sid: self._on_order_spin(i, v))
        bot.addWidget(order_spin)
        cb = QCheckBox("")
        cb.setChecked(sid in self._selected)
        cb.setEnabled(bool(vid))
        cb.toggled.connect(lambda on, i=sid: self._on_shot_checked(i, on))
        bot.addWidget(cb)
        tl.addLayout(bot)
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

    def _ordered_selected(self) -> list[int]:
        """勾选镜头的拼接顺序:手动调过序的优先,其余按镜号。"""
        nums = {r["id"]: int(r["storyboard_number"]) for r in self._all_shots()}
        return sorted(self._selected,
                      key=lambda i: (self._order.get(i, 0) or nums.get(i, 10**9),
                                     nums.get(i, 10**9)))

    def _renumber_order(self):
        """勾选集变化后重排 1..N(去掉已取消的,新勾的按镜号续尾)。"""
        self._order = {sid: k + 1 for k, sid in enumerate(self._ordered_selected())}

    def _on_order_spin(self, sid: int, v: int):
        """输 N 与当前第 N 位互换(对齐参考 onExportOrderInput 的交换语义)。"""
        ids = self._ordered_selected()
        n = len(ids)
        if not n or sid not in ids:
            return
        v = max(1, min(n, int(v)))
        i, j = ids.index(sid), v - 1
        if i == j:
            return
        ids[i], ids[j] = ids[j], ids[i]
        self._order = {s: k + 1 for k, s in enumerate(ids)}
        self._reload_shot_grid()

    def _preview_shot(self, url: str):
        from .asset_dialogs import VideoPreviewDialog
        VideoPreviewDialog(self, url, tr("preview")).exec()

    def _on_shot_checked(self, sid: int, on: bool):
        if on:
            self._selected.add(sid)
        else:
            self._selected.discard(sid)
        self._renumber_order()
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
        self._order = {}
        self._reload_shot_grid()

    # ── 片头 ──
    def _load_intro_state(self):
        d = db.q1("SELECT intro_title FROM dramas WHERE id=?", (self.drama_id,))
        if not d:
            return
        # 「加入片头」是会话内开关(对齐参考 introEnabled:每次进页默认关,不落库);
        # 片头名/字体/位置等持久化字段由编辑器负责
        self.intro_title.blockSignals(True)
        self.intro_title.setText(d["intro_title"] or "")
        self.intro_title.blockSignals(False)
        on = self.intro_check.isChecked()
        self.intro_title.setVisible(on)
        self.intro_edit_btn.setVisible(on)
        if not getattr(self, "_intro_title_wired", False):
            # 行内片头名只回写标题字段(对齐参考 onExportIntroTitle → 保存 intro_title)
            self.intro_title.editingFinished.connect(self._save_intro_title)
            self._intro_title_wired = True

    def _on_intro_toggle(self, on: bool):
        self.intro_title.setVisible(on)
        self.intro_edit_btn.setVisible(on)

    def _save_intro_title(self):
        db.ex("UPDATE dramas SET intro_title=?, updated_at=? WHERE id=?",
              (self.intro_title.text().strip(), db.now(), self.drama_id))

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
        # 拼接顺序 = 用户调过的序号(对齐参考 orderedExportSelectedIds),未调过按镜号
        ids = [i for i in self._ordered_selected()
               if self.shot_checks.get(i) and self.shot_checks[i].isEnabled()]
        if self._merge_in_flight:
            info(tr("merging"))
            return
        if len(ids) < 2:
            QMessageBox.information(self, tr("export_stage"), tr("merge_needs_two"))
            return
        # 片头参数对齐参考:勾了「加入片头」才带上,标题取行内输入(空则回退剧名),
        # 模式(标题卡/叠加)与字体字号位置时长全部读 drama 持久化字段(编辑器实时写库)
        intro_on = self.intro_check.isChecked()
        d = db.q1("SELECT title, intro_title, intro_card, intro_overlay FROM dramas WHERE id=?",
                  (self.drama_id,)) or {}
        intro_title = (self.intro_title.text().strip()
                       or (d.get("intro_title") or d.get("title") or "")) if intro_on else None
        intro_card = bool(d.get("intro_card")) if intro_on else False
        intro_overlay = bool(d.get("intro_overlay")) if intro_on else False

        self._merge_in_flight = True
        self.merge_btn.setEnabled(False)
        self.merge_btn.setText("⠋ " + tr("merging"))

        def job(tid):
            return merge_pipe.merge_episode(
                self.episode_id, ids,
                intro_title=intro_title,
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
