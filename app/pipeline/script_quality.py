# -*- coding: utf-8 -*-
"""剧本可拍性质量门:杜绝「满篇内心独白、一个人在一间屋里自说自话」的剧本。

背景(实测 2026-10-20):
    某次短剧改写产出 11 场剧本,全部发生在同一间出租屋,每场只有林岁晚一个人的
    画外音。这种剧本拆不成有对手戏的分镜,生成了视频也只是一个人对着空气说话。
    根因是技能文件里写着「心理描写可转化为角色表情/动作**或画外音**」,
    模型就把几乎全部心理描写转成了画外音。

两道防线:
    1) 提示词层:prompt / skill 里明确禁止画外音、要求心理外化、要求对手戏;
    2) 程序层(本模块):生成后按可拍性指标体检,不合格就返工重写,仍不合格直接
       RuntimeError —— 坏剧本不会落库,进不了下游分镜/视频。

体检指标(与语言无关的硬指标,文案措辞可按语言变化):
    1. 画外音/内心独白占比
    2. 单人独白场景占比(一场戏里只有一个人说话,且是画外音)
    3. 全剧说话角色数(只有 1 个角色说话 = 没有对手戏)
    4. 地点重复度(连续多场同一地点 = 生成的视频画面几乎一样)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- 阈值
VO_RATIO_LIMIT = 0.25        # 画外音/内心独白占全部台词的上限
MONO_SCENE_LIMIT = 0.5       # 单人独白场景占全部场景的上限
LOCATION_RATIO_LIMIT = 0.5   # 地点数 / 场景数 的下限(低于此说明场景高度重复)
MIN_SCENES_FOR_LOCATION = 5  # 场景少于这个数不做地点重复检查

# ---------------------------------------------------------------- 画外音标记(15 语言)
# 拉丁文缩写用词边界匹配,避免 "V.O." 之类误伤普通单词。
_VO_PATTERNS: tuple[str, ...] = (
    # 中文 / 繁中
    r"画外音", r"旁白", r"独白", r"心声", r"内心独白", r"自言自語", r"內心獨白",
    # 英文
    r"\bvoice[\s\-]?over\b", r"\bvoiceover\b", r"\bv\.?\s*o\.?\b", r"\bo\.?\s*s\.?\b",
    r"\boff[\s\-]?screen\b", r"\binside voice\b", r"\binner (?:voice|monologue|thought)\b",
    r"\bmonologue\b", r"\bnarration\b",
    # 日文
    r"モノローグ", r"ナレーション", r"ボイスオーバー", r"内面", r"心の声", r"声の外出",
    # 韩文
    r"내면", r"독백", r"혼잣말", r"화면 밖",
    # 西班牙语
    r"\bvoz en off\b", r"\ben off\b", r"\bvoz fuera de campo\b", r"monólogo", r"narración",
    # 法语
    r"\bvoix off\b", r"\bhors champ\b", r"\bmonologue\b", r"\bnarration\b",
    # 德语
    r"\boff-screen\b", r"\bmonolog\b", r"\berzähler\b", r"\bstimme\b",
    # 葡萄牙语
    r"\bvoz off\b", r"fora de quadro", r"monólogo",
    # 意大利语
    r"voce fuori campo", r"monologo",
    # 土耳其语 / 越南语 / 泰语 / 印尼语 / 印地语 / 阿拉伯语
    r"iç ses", r"iç konuşma", r"\bmonolog\b",
    r"lời dẫn", r"nội tâm", r"độc thoại nội tâm",
    r"บทพูดนอกภาพ", r"ละครพูดในใจ", r"เสียงพากย์",
    r"suara dalam", r"monolog dalam hati",
    r"आंतरिक", r"मोनोलॉग", r"वॉइस ओवर",
    r"صوت خارجي", r"مونولوج", r"صوت داخلي",
    # 俄语(不在 15 语言之列,但模型偶尔会混用,多认一种不吃亏)
    r"за кадром", r"закадровый голос", r"внутренний монолог", r"внутренний голос",
)
_VO_RE = re.compile("|".join(_VO_PATTERNS), re.IGNORECASE)

# 整个提示语只有「内心」这类词时才算画外音 —— 「你这内心倒是挺强」这种正常
# 台词绝不能误伤,所以裸词只在"提示语 == 该词"时才认。
_VO_WEAK_ONLY_RE = re.compile(r"^\s*(内心|內心|inner|Inner|INNER)\s*$")

# 场景头:## S01 | 内景 · 地点 | 时间
_SCENE_RE = re.compile(r"^##\s*S(\d+)\s*\|(.*)$", re.MULTILINE)

# 台词行:角色名:台词  /  角色名：（状态）台词
_DIALOGUE_RE = re.compile(
    r"^\s*([^\s:：，。、；！？“”\"'‘’()（）\[\]【】]{1,8})\s*[:：]\s*(\S.*)$"
)
# 说话人里出现这些字,基本可以判定是句子的一部分而不是人名
_SPEAKER_STOPWORDS = (
    "是", "的", "了", "在", "和", "与", "就", "都", "也", "很", "更", "又", "还", "不", "没",
    "有", "被", "把", "给", "对", "从", "向", "这", "那", "些", "什", "么", "谁", "怎", "样",
    "听", "见", "说", "讲", "问", "记", "想", "觉", "知", "认", "们", "个", "如", "若", "但",
)

# 地点归一:剥掉内/外景前缀与末尾时间段
_SCENE_KIND_RE = re.compile(r"^\s*(内景|外景|内|外|INT\.|EXT\.?|int\.|ext\.?)", re.IGNORECASE)
_TIME_WORDS = (
    "清晨", "早晨", "早上", "上午", "中午", "午间", "下午", "傍晚", "黄昏", "夜晚", "夜里",
    "深夜", "凌晨", "白天", "日间", "夜间", "清晨", "时间", "回忆", "往事", "过去", "现在",
    "morning", "afternoon", "evening", "night", "dawn", "dusk", "noon", "day", "nighttime",
)


@dataclass
class ScriptStats:
    """剧本结构体检结果。"""

    scenes: int = 0
    dialogue_lines: int = 0
    action_blocks: int = 0
    vo_lines: int = 0
    vo_scenes: int = 0
    monologue_scenes: int = 0
    speakers: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)

    @property
    def vo_ratio(self) -> float:
        return (self.vo_lines / self.dialogue_lines) if self.dialogue_lines else 0.0

    @property
    def mono_ratio(self) -> float:
        return (self.monologue_scenes / self.scenes) if self.scenes else 0.0

    @property
    def location_ratio(self) -> float:
        return (len(self.locations) / self.scenes) if self.scenes else 0.0


def _norm_location(header: str) -> str:
    """从场景头取地点:``内景 · 石榴巷出租屋 | 清晨`` → ``石榴巷出租屋``。"""
    parts = [p.strip() for p in header.split("|")]
    raw = parts[1] if len(parts) > 1 else (parts[0] if parts else "")
    raw = _SCENE_KIND_RE.sub("", raw)
    raw = raw.replace("·", " ").replace("・", " ").replace("•", " ")
    segs = [s.strip() for s in raw.split() if s.strip()]
    # 末尾若时间段(且不止一段),丢掉它
    if len(segs) > 1 and any(t in segs[-1].lower() for t in _TIME_WORDS):
        segs = segs[:-1]
    return " ".join(segs) or raw.strip()


def _speaker_of(line: str) -> str:
    """判断这一行是不是台词,返回说话人名;不是台词返回空串。"""
    m = _DIALOGUE_RE.match(line)
    if not m:
        return ""
    name = m.group(1).strip()
    if not name or any(w in name for w in _SPEAKER_STOPWORDS):
        return ""
    if len(name) > 8:
        return ""
    return name


def _dialogue_text(line: str) -> str:
    """取冒号后的台词正文(不含角色名与冒号);不是台词返回空串。"""
    m = _DIALOGUE_RE.match(line)
    return m.group(2).strip() if m else ""


def _is_vo(text: str) -> bool:
    """台词正文是否带画外音/内心独白标记。

    括号提示语优先:``(voice-over)`` / ``（画外音，声音很轻）`` 一命中就是画外音;
    没有括号时才看台词开头一小段 —— 避免正文里出现"内心"二字被误伤。
    """
    m = re.match(r"^\s*[（(]([^）)]{0,60})[）)]", text)
    if m:
        hint = m.group(1)
        if _VO_RE.search(hint):
            return True
        return bool(_VO_WEAK_ONLY_RE.match(hint))
    return bool(_VO_RE.search(text[:12]))


def _split_scenes(script: str) -> list[tuple[str, list[str]]]:
    """切场景:返回 [(场景头, 行列表)];没有场景头时返回空。"""
    marks = list(_SCENE_RE.finditer(script))
    out: list[tuple[str, list[str]]] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(script)
        body = script[m.end():end]
        lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
        out.append((m.group(0), lines))
    return out


def analyze(script: str) -> ScriptStats:
    """统计剧本结构(场景数 / 台词 / 画外音 / 说话人 / 地点)。"""
    st = ScriptStats()
    if not script or not script.strip():
        return st
    scenes = _split_scenes(script)
    st.scenes = len(scenes)
    speakers: list[str] = []
    locations: list[str] = []
    for header, lines in scenes:
        loc = _norm_location(header)
        if loc and loc not in locations:
            locations.append(loc)
        scene_speakers: dict[str, int] = {}
        vo_in_scene = 0
        action_buf = False
        for ln in lines:
            name = _speaker_of(ln)
            if name:
                st.dialogue_lines += 1
                scene_speakers[name] = scene_speakers.get(name, 0) + 1
                if name not in speakers:
                    speakers.append(name)
                if _is_vo(_dialogue_text(ln)):
                    st.vo_lines += 1
                    vo_in_scene += 1
                action_buf = False
            else:
                if not action_buf:
                    st.action_blocks += 1
                    action_buf = True
        if vo_in_scene:
            st.vo_scenes += 1
        # 单人独白场景:全场只有一个人说话,且这个人有画外音
        if scene_speakers and vo_in_scene:
            total = sum(scene_speakers.values())
            if len(scene_speakers) == 1 and total == vo_in_scene:
                st.monologue_scenes += 1
    st.speakers = speakers
    st.locations = locations
    return st


def check(script: str) -> list[str]:
    """体检:返回问题列表(空列表 = 合格)。"""
    st = analyze(script)
    problems: list[str] = []
    if st.scenes == 0:
        return problems          # 场景头缺失属于格式问题,交给格式校验处理

    if st.dialogue_lines and st.vo_ratio > VO_RATIO_LIMIT:
        problems.append(
            f"画外音/内心独白占台词 {st.vo_ratio * 100:.0f}%(上限 {int(VO_RATIO_LIMIT * 100)}%)"
        )
    if st.scenes >= 3 and st.mono_ratio > MONO_SCENE_LIMIT:
        problems.append(
            f"{st.monologue_scenes}/{st.scenes} 场是单人独白,没有对手戏"
            f"(上限 {int(MONO_SCENE_LIMIT * 100)}%)"
        )
    if len(st.speakers) <= 1 and st.dialogue_lines >= 3:
        problems.append(f"全剧只有 {len(st.speakers)} 个角色说话,没有对手戏")
    if st.scenes >= MIN_SCENES_FOR_LOCATION and st.location_ratio < LOCATION_RATIO_LIMIT:
        problems.append(
            f"{st.scenes} 场只用了 {len(st.locations)} 个地点,生成的视频画面会几乎一样"
        )
    return problems


def repair_instruction(problems: list[str], lang: str | None = None) -> str:
    """生成返工指令(交给模型重写)。``lang`` 为内容语言,要求模型用同语言输出。"""
    lang_line = ""
    if lang:
        try:
            from ..core.i18n import LANG_OUTPUT_NAME
            name = LANG_OUTPUT_NAME.get(lang)
        except Exception:  # noqa: BLE001
            name = None
        if name:
            lang_line = f"\n- 输出语言必须与原剧本完全一致({name}),不要换成别的语言"
    items = "\n".join(f"{i}. {p}" for i, p in enumerate(problems, 1))
    return f"""上一版剧本不可用,体检发现以下问题:
{items}

请按下列硬性要求重写整份剧本(保持原来的格式,保持故事主线、人物关系与结局走向):
- 禁止画外音/旁白/内心独白:所有台词必须是角色当面说出口的话
- 心理活动一律外化:用动作、表情、停顿、选择或说出口的话来表达;
  不要写「她想起…」「她心里明白…」「她意识到…」这类内心叙述
- 每场戏至少有两个角色在场互动,不要一个人自说自话
- 相邻场景至少换一个地点或时间段,不要连续多场同一间屋子
- 每场都要有能拍出来的动作:谁做了什么、看到了什么
{lang_line}
只输出重写后的完整剧本,不要解释、不要写 <think>。"""


def try_repair(script: str, repair_fn, *, max_repair: int = 1) -> tuple[str, list[str]]:
    """体检不合格就返工重写。

    Args:
        script:初版剧本。
        repair_fn:``prompt -> str``,调模型重写并返回新剧本正文。
        max_repair:最多返工几次。

    Returns:
        ``(合格剧本, 仍存在的问题)``;仍不合格时合格剧本为空串。
    """
    problems = check(script)
    if not problems:
        return script, []
    current = script
    for _ in range(max(1, max_repair)):
        try:
            fixed = repair_fn(repair_instruction(problems)) or ""
        except Exception:  # noqa: BLE001
            break
        if not fixed.strip():
            break
        current = fixed
        problems = check(current)
        if not problems:
            return current, []
    return "", problems


def enforce(script: str, repair_fn, *, max_repair: int = 1) -> str:
    """体检不合格就返工重写;仍不合格抛 RuntimeError(调用方据此不落库)。"""
    ok, problems = try_repair(script, repair_fn, max_repair=max_repair)
    if ok:
        return ok
    raise RuntimeError("剧本质量不合格:" + ";".join(problems))
