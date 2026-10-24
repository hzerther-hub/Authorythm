# -*- coding: utf-8 -*-
"""海外题材改写 · 静态校验器。

只报**可查证的事实**(缺什么 / 越界 / 冲突),不做审美打分:

  R1  第一视角自我观察违背 —— 写了自己看不见的脸/表情/眼睛颜色
  R2  第一视角被动链       —— 连续「看到→感觉→反应→等待」
  R3  赘述                 —— 相邻重复句 / 高频重复片段
  R4  中文残留(漏译检测)  —— 英文稿里出现汉字或全角中文标点
  R5  术语一致性冲突       —— 姓名顺序颠倒 / 大小写空格变体
  R6  章节字数越界         —— 超出平台区间
  R7  付费卡点位置         —— 卡点章节不在平台允许范围
  R8  开篇爽点缺失         —— 开篇 N 章内检不到品类爽点关键词
  R9  章末钩子缺失         —— 末段检不到钩子标记
  R10 翻译腔               —— 超长句 / 被动句占比 / 填充词过多
  R11 章末任务—奖励闭环    —— 男频系统流品类强制

**误伤控制**:一律只报高置信问题,宁可漏报不误报(沿用
`novel.check_pov_violation` 的既定口径:只做高置信判断,避免误伤)。

与 `novel.check_pov_violation()` 的关系:那是**粗粒度人称漂移**检查
(数「我」和「他/她」的次数),本模块 R1/R2 是**细粒度自我观察/主动性**检查,
语义不同 —— 不复用、也不改它(小说线有回归测试保护,改它容易误伤)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CJK = re.compile(r"[\u4e00-\u9fff]")

# CJK 三系的「一个字」要分别数:
#   汉字 U+4E00-9FFF · 假名 U+3040-30FF(平/片假名)· 谚文 U+AC00-D7AF
# 旧正则只认汉字,日文稿的字数就只算得到汉字那部分 ——「彼は彼女を見た」七个字里
# 只有三个是汉字,字数直接砍掉一半以上,再按 1.8 折算就完全失真(实测 408 字的
# 日文稿被算成 86 词,平台下限 800 一律误报「字数不足」)。
_CJK_ALL = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
# 全角标点里**只有这些**是中文独有的 —— “ ” ‘ ’ — … 在英文排版里是正规用法
# (英文稿用弯引号是标准,不是翻译腔)。实测真实改写稿全是 “ ”，早期版本把它们
# 当成中文标点报错,纯属误伤。
_CJK_PUNCT = "，。、；：！？（）【】《》〈〉「」～"
_CJK_PUNCT_RE = re.compile("[" + re.escape(_CJK_PUNCT) + "]")
_MD_HEADING = re.compile(r"^#{1,6}\s.*$", re.M)
_FENCE = re.compile(r"```.*?```", re.S)

# ---- R1 自我观察(第一视角看不见自己)
# 一律用「邻接」匹配而不是中间夹任意字符:夹字符会误伤
# 「我的眼睛盯着红酒杯」「我的脸被手挡住了」这类完全正常的句子。
_SELF_OBS_ZH = (
    r"我的(?:脸|脸颊|皮肤)(?:都)?(?:泛红|通红|红得|红了|变红|白了|发白|苍白|发烫|滚烫|热得)",
    r"我的(?:眼睛|眼神)(?:都)?(?:泛红|通红|红了|红得|发红)",
    r"我的(?:嘴角|笑容|眉毛)(?:微微)?(?:上扬|一扬|一沉|僵住|僵了)",
)
# 「我的表情/脸色/神态」本身可能是合理的(照镜子),只作提示不作错误
_SELF_OBS_ZH_WEAK = (r"我的(?:表情|脸色|神态)",)
_SELF_OBS_EN = (
    r"my (?:face|cheeks?)\s+(?:flush(?:ed|ing)?|turn(?:ed|ing)?\s+red|went\s+red"
    r"|burn(?:ed|ing)?|went\s+pale|paled|whiten(?:ed)?)",
    r"my skin\s+(?:went\s+pale|paled|whiten(?:ed)?)",
    r"my (?:eyes?|gaze|look)\s+(?:widened|narrowed|softened|darkened|dilated|gleamed|brightened)",
    r"my (?:expression|countenance|features?|face)\s+(?:was|is|went|fell|became|turned)"
    r"\b[^.!?\n]{0,24}\b(?:pale|red|white|blank|stiff|shocked|frozen)",
    r"a (?:smile|blush|flush)\s+(?:tugged|spread|crept)\b[^.!?\n]{0,20}\bmy\b",
    r"my (?:face|expression)\s+(?:fell|dropped)\s+(?:blank|still)",
)

# ---- R2 被动链
_PERCEPTION_EN = r"\b(?:saw|watched|heard|felt|noticed|realized|observed|glanced|stared|listened)\b"
_REACTION_EN = r"\b(?:froze|shuddered|trembled|gasped|blinked|hesitated|paused|stiffened)\b"
_ACTION_EN = (
    r"\b(?:decided|turned|walked|ran|grabbed|pushed|opened|closed|said|asked|shouted|refused"
    r"|agreed|stepped|reached|threw|slammed|pulled|stood|sat|took|picked|kissed|hit|left"
    r"|moved|put|dropped|lifted|wrote|called|held|brought|paid|swallowed|breathed|knelt"
    r"|smiled|laughed|cried|sighed|knocked|rang|answered|ended)\b"
)
_PERCEPTION_ZH = r"(?:看到|看见|听见|听到|感觉|觉得|发现|注意到|盯着|望着)"
_REACTION_ZH = r"(?:愣住了|怔住|心头一紧|心里一颤|说不出话|发呆|浑身一僵|倒吸一口)"

# 章末钩子标记的兜底集(语言规则文件没给时用这个)。
# 「began to / started to / was about to」是真实改写稿里最常见的收尾句式 ——
# 「The access panel beside them began to blink red.」就是一个标准断点,
# 早期版本没收录,把它误报成「章末无钩子」。
_HOOK_MARKERS_DEFAULT = (
    "before she could", "before he could", "before i could", "suddenly",
    "but then", "too late", "never", "wasn't", "hadn't", "didn't", "what if",
    "until", "the moment", "a sound", "a voice", "it was then", "reached for",
    "no one spoke", "began to", "started to", "was about to", "one more",
    "not until", "the sound of", "had not",
    # 「before + 物主代词」= 动作被打断(未完成动作钩子)。真实改写稿的收尾
    # 「It opened from the inside before my hand touched the handle.」就是这类,
    # 早期版本没收录,把它误报成「章末无钩子」。
    "before my", "before his", "before her", "before its", "before their",
)
_ACTION_ZH = (
    r"(?:决定|转身|推开|开口|拒绝|答应|打断|站起来|冲|砸|抓|握|低头|抬头|递|跑|坐下"
    r"|拨|挂|点|写|掏|塞|丢|扔|扑|抱|吻|拿起|拿出|抬头看|伸手)"
)


@dataclass
class Issue:
    """一条校验结果。severity: error(硬错) / warn(提示)。"""

    rule: str
    severity: str
    message: str
    snippet: str = ""

    def __str__(self) -> str:
        tag = {"error": "错误", "warn": "警告"}.get(self.severity, self.severity)
        s = f"[{self.rule}] {tag}:{self.message}"
        if self.snippet:
            s += f" —— {self.snippet}"
        return s


# ---------------------------------------------------------------- 文本工具

def _body(text: str) -> str:
    """去掉 Markdown 标题与代码块 —— 标题常含原文标题,不该算进正文残留。"""
    t = _FENCE.sub(" ", text or "")
    return _MD_HEADING.sub("", t)


# 书写系统 → 字数折算。平台给的章节字数区间(800-1500 词)是**按英文词数**标的,
# 拿它去卡日文/泰文/阿拉伯文,必须先把字符数折算成可比的「词数」,否则:
#   · 拉丁系:直接数词,1:1
#   · CJK 系(中日韩):1 汉字 ≈ 1.8 个英文词(实测日文小说 1 字 ≈ 1.5-2 词)
#   · 其它(泰/阿/印地):按空格分词,再对无空格书写的部分按字符折算
CJK_LANGS = ("zh", "ja", "ko")
_LATIN_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿĀ-ſ][A-Za-zÀ-ÖØ-öø-ÿĀ-ſ'’-]*")
_UNSPLIT = re.compile(r"[^\s]{2,}")


def script_of(lang: str | None) -> str:
    """内容语言的书写系统:latin / cjk / other。判不出来按 latin 处理(最保守)。"""
    code = (lang or "").lower()
    if code.startswith("zh") or code.startswith("ja") or code.startswith("ko"):
        return "cjk"
    return "latin"


def _is_chinese(text: str, lang: str | None = None) -> bool:
    """是不是**中文**(不是「是不是 CJK」)。

    旧实现用「CJK 占比 > 0.3」判断,把日文/韩文一并算成中文。后果是双向的:
      · 日文稿被 `check_translationese` / `check_chinese_residue` 当成中文原稿直接短路
        → R10 翻译腔检查静默跳过 → **假绿**;
      · 泰文/阿拉伯文既不是中文又几乎不含拉丁字母 → 字数恒为 0 →
        R6 每章误报「章节字数 0 低于平台下限 800」→ **假红**。
    传了 lang 就按语种判;没传时退回旧的 CJK 占比启发式。
    """
    if lang:
        return (lang or "").lower().startswith("zh")
    letters = sum(1 for ch in text if ch.isalpha())
    if not letters:
        return False
    cjk = sum(1 for ch in text if _CJK.match(ch))
    return cjk / letters > 0.3


def _count_words(text: str, lang: str | None = None) -> int:
    """按目标语言的书写系统折算「词数」,与平台规格(按英文词数标)可比。"""
    kind = script_of(lang) if lang else ("cjk" if _is_chinese(text) else "latin")
    if kind == "cjk":
        return int(sum(1 for ch in text if _CJK_ALL.match(ch)) / 1.8)
    words = len(_LATIN_WORD.findall(text))
    if lang:
        # 泰/阿/印地等:空格分词数不到总量的一半,说明主体是非拉丁脚本,
        # 补一段「无空格串按 3 字符≈1 词」折算,否则字数会被严重低估。
        chars = sum(1 for ch in text if not ch.isspace() and not _LATIN_WORD.match(ch))
        words += int(chars / 3)
    return words


def _sentences(text: str) -> list[str]:
    """切句。中文的句号后面没有空格,所以要单独处理全角标点,
    否则「我看到…。我感觉…。我听见…。」会被当成一整句 —— R2/R3 直接失效。"""
    parts = re.split(r"(?<=[.!?])\s+|(?<=[。！？])|\n+", text or "")
    return [p.strip() for p in parts if p and p.strip()]


def _paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text or "")
    return [p.strip() for p in parts if p and p.strip()]


def _at_sentence_start(text: str, idx: int) -> bool:
    """idx 处是否是句子开头(句首大写合法)。

    判据:往前跳过引号/括号/破折号/空白,要么到头了,要么紧挨着句末标点。
    """
    head = text[:idx]
    i = len(head)
    while i > 0 and (head[i - 1].isspace() or head[i - 1] in "\"'“”‘’()[]—-"):
        i -= 1
    if i == 0:
        return True
    return head[i - 1] in ".!?…"


def _glossary_entries(glossary) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(glossary, dict):
        for k, v in glossary.items():
            if v:
                out.append((str(k), str(v)))
    elif isinstance(glossary, list):
        for it in glossary:
            if isinstance(it, dict):
                s = it.get("source") or it.get("zh")
                t = it.get("target") or it.get("en")
                if s and t:
                    out.append((str(s), str(t)))
    return out


# ---------------------------------------------------------------- 单条规则

def check_self_observation(content: str, *, patterns_zh=None,
                           patterns_en=None, patterns=None,
                           lang=None) -> list[Issue]:
    """R1:第一视角不能写自己看不见的脸/表情/眼睛颜色。

    `patterns` 是**语言无关**的入口:语言规则包可以直接给一个正则列表,
    不必再按 `.en` / `.zh` 这类硬编码 key 分类 —— 那是给英语和源文两种语言
    开的特例,扩到 14 个语言包时必然漏(漏了不报错,只是静默套用英语正则
    去匹配日文,永远匹配不上 → 假绿)。
    """
    body = _body(content)
    if patterns is not None:
        pats = list(patterns)
    else:
        pats = list(_SELF_OBS_ZH if patterns_zh is None else patterns_zh)
        pats += list(_SELF_OBS_EN if patterns_en is None else patterns_en)
    if not pats:
        # 语言包没给模式:宁可不报,也不拿英语正则去套非英语正文(AGENTS.md:
        # 宁可漏报不误报)。
        return []
    # 弱模式(「我的表情」这类可能合理的)也要被检出,只是降级为提示。
    # 只有在**明确是非中文目标语种**时才剔除 —— 目标语种是日/法/泰时,
    # 中文弱模式匹配不到任何东西,留着无害;反过来漏了会让中文稿少检一条。
    if lang and not (lang or "").lower().startswith("zh"):
        weak: list = []
    else:
        weak = list(_SELF_OBS_ZH_WEAK)
    pats += [w for w in weak if w not in pats]
    issues: list[Issue] = []
    seen: set[str] = set()
    for pat in pats:
        if not pat:
            continue
        for m in re.finditer(pat, body, flags=re.I):
            frag = m.group(0).strip()
            if not frag or frag in seen:
                continue
            seen.add(frag)
            is_weak = any(re.search(w, frag) for w in weak)
            issues.append(Issue(
                "R1", "warn" if is_weak else "error",
                "第一视角自我观察违背:写了「她自己的眼睛看不见」的描写", frag))
            if len(issues) >= 5:
                return issues
    return issues


def check_passivity(content: str, *, run_length: int = 3, lang=None) -> list[Issue]:
    """R2:连续被动链(看到→感觉→反应→等待)。"""
    body = _body(content)
    sents = _sentences(body)
    if len(sents) < run_length:
        return []
    flags: list[bool] = []
    for s in sents:
        if _is_chinese(s, lang):
            is_p = bool(re.search(_PERCEPTION_ZH, s) or re.search(_REACTION_ZH, s))
            has_a = bool(re.search(_ACTION_ZH, s))
        else:
            is_p = bool(re.search(_PERCEPTION_EN, s, re.I) or re.search(_REACTION_EN, s, re.I))
            has_a = bool(re.search(_ACTION_EN, s, re.I))
        flags.append(is_p and not has_a)
    issues: list[Issue] = []
    run = 0
    for i, flag in enumerate(flags):
        if flag:
            run += 1
            if run >= run_length:
                seg = " ".join(sents[i - run_length + 1: i + 1])
                issues.append(Issue(
                    "R2", "warn",
                    f"连续 {run} 句呈被动链,应改为「看到→判断→决定→行动」",
                    seg[:120]))
                run = 0
        else:
            run = 0
    return issues[:3]


def check_redundancy(content: str, *, ngram: int = 5, min_hits: int = 3,
                   lang=None) -> list[Issue]:
    """R3:相邻重复句 + 高频重复片段。"""
    body = _body(content)
    issues: list[Issue] = []
    sents = [re.sub(r"\s+", " ", s).strip().lower() for s in _sentences(body)]
    for i in range(len(sents) - 1):
        a, b = sents[i], sents[i + 1]
        if len(a) >= 20 and a == b:
            issues.append(Issue("R3", "warn", "相邻两句内容完全重复", a[:80]))
    if _is_chinese(body, lang):
        chars = [c for c in body if not c.isspace()]
        n = 6
        if len(chars) >= n * min_hits:
            counts: dict[str, int] = {}
            for i in range(len(chars) - n + 1):
                g = "".join(chars[i:i + n])
                counts[g] = counts.get(g, 0) + 1
            worst = sorted(((c, g) for g, c in counts.items() if c >= min_hits), reverse=True)
            if worst:
                c, g = worst[0]
                issues.append(Issue("R3", "warn", f"同一片段重复出现 {c} 次(赘述/复读)", g))
    else:
        words = re.findall(r"[A-Za-z][A-Za-z'’-]*", body)
        if len(words) >= ngram * min_hits:
            counts = {}
            for i in range(len(words) - ngram + 1):
                g = " ".join(w.lower() for w in words[i:i + ngram])
                counts[g] = counts.get(g, 0) + 1
            worst = sorted(((c, g) for g, c in counts.items() if c >= min_hits), reverse=True)
            if worst:
                c, g = worst[0]
                issues.append(Issue("R3", "warn", f"同一片段重复出现 {c} 次(赘述/复读)", g))
    return issues[:3]


def check_chinese_residue(content: str, forbid: list[str] | None = None,
                          lang=None) -> list[Issue]:
    """R4:英文稿里的汉字/全角标点(漏译检测)。中文原稿不做此项。

    `forbid` 传语言规则文件里的「全角禁用集」,为空则用内置默认。
    """
    body = _body(content)
    if not body.strip() or _is_chinese(body, lang):
        return []
    chars = set(forbid) if forbid else set(_CJK_PUNCT)
    issues: list[Issue] = []
    frags = [m.group(0)[:12] for m in list(re.finditer(r"[\u4e00-\u9fff]+", body))[:5]]
    if frags:
        total = len(re.findall(r"[\u4e00-\u9fff]", body))
        issues.append(Issue("R4", "error",
                            f"检出 {total} 个汉字(漏译/未替换的文化专名)", "、".join(frags)))
    punct = sorted({c for c in body if c in chars})
    if punct:
        issues.append(Issue("R4", "error",
                            "检出全角中文标点(会被英文读者一眼看出)", " ".join(punct)))
    return issues


def check_glossary_consistency(content: str, glossary) -> list[Issue]:
    """R5:人名/术语与术语表不一致(顺序颠倒 / 写法变体)。"""
    body = _body(content)
    issues: list[Issue] = []
    for _src, tgt in _glossary_entries(glossary):
        toks = [t for t in re.split(r"\s+", tgt.strip()) if t]
        if not toks:
            continue
        canon = re.sub(r"\s+", " ", tgt.strip())
        if len(toks) >= 2:
            rev_pat = r"\b" + r"\s+".join(re.escape(t) for t in reversed(toks)) + r"\b"
            fwd_pat = r"\b" + r"\s+".join(re.escape(t) for t in toks) + r"\b"
            rev = re.search(rev_pat, body, re.I)
            fwd = re.search(fwd_pat, body)
            if rev:
                sev = "error" if fwd else "warn"
                issues.append(Issue("R5", sev,
                                    f"人名/术语顺序与术语表不一致(应为「{canon}」)",
                                    rev.group(0)))
                continue
        # 大小写/空格变体:用 re.I 找出来,再按原文比对是否与术语表完全一致
        pat = re.compile(r"\b" + r"\s+".join(re.escape(t) for t in toks) + r"\b", re.I)
        for m in pat.finditer(body):
            raw = m.group(0)
            got = re.sub(r"\s+", " ", raw)
            if got == canon:
                # 空格写法变体(双空格/换行)也算不一致 —— 术语要逐字照用。
                # 注意 got 已经把空白压成单空格,所以只有 raw 不同才是真的变体。
                if raw != canon:
                    issues.append(Issue("R5", "warn",
                                        f"人名/术语写法与术语表不一致(应为「{canon}」)", raw))
                    break
                continue
            # 句首大写**不算**术语不一致:术语表里是小写起头的普通名词短语
            # (「总裁」-> the CEO),正文写「The CEO」是英文的正常句首大写,不是错译。
            # 实测真实改写稿因此被误报过一次。
            # 但术语表本身是大写起头的专名(「陈默」-> Chen Mo)时,小写出现仍是错。
            if (got.lower() == canon.lower() and canon[:1].islower()
                    and _at_sentence_start(body, m.start())):
                continue
            issues.append(Issue("R5", "warn",
                                f"人名/术语写法与术语表不一致(应为「{canon}」)", got))
            break
    return issues[:8]


def check_chapter_words(content: str, bounds: tuple[int, int] | None,
                         lang=None) -> list[Issue]:
    """R6:章节字数越界。"""
    if not bounds:
        return []
    lo, hi = bounds
    n = _count_words(_body(content), lang)
    if n < lo:
        return [Issue("R6", "warn", f"章节字数 {n} 低于平台下限 {lo}", f"还差 {lo - n}")]
    if n > hi:
        return [Issue("R6", "warn", f"章节字数 {n} 超出平台上限 {hi}", f"超出 {n - hi}")]
    return []


def check_paywall_position(paywall_chapters, rng: tuple[int, int] | None) -> list[Issue]:
    """R7:付费卡点章节不在平台允许区间。"""
    if not rng or not paywall_chapters:
        return []
    lo, hi = rng
    bad = [c for c in paywall_chapters if not (lo <= int(c) <= hi)]
    if bad:
        return [Issue("R7", "warn",
                      f"付费卡点章节 {bad} 不在平台允许区间(第 {lo}-{hi} 章)", "")]
    return []


def check_opening_payoff(content: str, keywords, within_chapters: int | None,
                         chapter_no: int | None = None) -> list[Issue]:
    """R8:开篇 N 章内必须出现核心爽点。"""
    if not keywords or not within_chapters:
        return []
    if chapter_no is not None and chapter_no > within_chapters:
        return []
    low = _body(content).lower()
    if any(str(k).lower() in low for k in keywords):
        return []
    preview = "、".join(str(k) for k in list(keywords)[:6])
    return [Issue("R8", "warn",
                  f"开篇 {within_chapters} 章内未检出品类爽点关键词(可能漏写)", preview)]


def check_cliffhanger(content: str, markers) -> list[Issue]:
    """R9:章末钩子。"""
    paras = _paragraphs(_body(content))
    if not paras:
        return []
    last = paras[-1].strip()
    low = last.lower()
    if any(str(m).lower() in low for m in (markers or [])):
        return []
    if last.endswith("?"):
        return []
    return [Issue("R9", "warn",
                  "章末未检出钩子标记(开放式问题/倒计时/反转/未完成动作)", last[:100])]


def check_translationese(content: str, cfg: dict | None = None,
                          lang=None) -> list[Issue]:
    """R10:翻译腔(超长句 / 被动句占比 / 填充词过多)。"""
    cfg = cfg or {}
    max_words = int(cfg.get("max_sentence_words", 35))
    max_ratio = float(cfg.get("max_passive_ratio", 0.3))
    max_filler = int(cfg.get("max_filler_total", 5))
    filler_words = [str(w).lower() for w in cfg.get("filler_words") or []]
    passive_raw = cfg.get("passive_pattern")
    # 语言包把 passive_pattern 显式写成空串 = 「该语言的翻译腔阈值尚未校准」。
    # 这时**不能**回落到英语默认正则 —— 那条正则在泰文/阿拉伯文里永远匹配不到,
    # R10 会静默全过,用户看到「质检通过」其实什么都没检(假绿)。
    # 正确做法是跳过 R10:宁可漏报不误报。
    if passive_raw == "":
        return []
    passive_re = passive_raw or r"\b(?:was|were|is|are|been|being|be)\s+\w+(?:ed|en)\b"
    body = _body(content)
    if not body.strip() or _is_chinese(body, lang):
        return []
    issues: list[Issue] = []
    sents = _sentences(body)
    longs = [s for s in sents
             if len(re.findall(r"[A-Za-z][A-Za-z'’-]*", s)) > max_words]
    if longs:
        issues.append(Issue("R10", "warn",
                            f"{len(longs)} 句超过 {max_words} 词(英文长句不自然)",
                            longs[0][:100]))
    if sents:
        passive_n = len(re.findall(passive_re, body, re.I))
        ratio = passive_n / max(1, len(sents))
        if ratio > max_ratio:
            issues.append(Issue("R10", "warn",
                                f"被动句占比约 {ratio:.0%}(阈值 {max_ratio:.0%}),有翻译腔",
                                f"{passive_n}/{len(sents)} 句"))
    if filler_words:
        counts = {w: len(re.findall(r"\b" + re.escape(w) + r"\b", body, re.I))
                  for w in filler_words}
        total = sum(counts.values())
        if total > max_filler:
            worst = sorted(counts.items(), key=lambda kv: -kv[1])[:3]
            issues.append(Issue("R10", "warn",
                                f"填充词过多({total} 次,上限 {max_filler})",
                                "、".join(f"{k}×{v}" for k, v in worst)))
    return issues


def check_task_reward(content: str, task_reward: dict | None) -> list[Issue]:
    """R11:章末「任务—奖励」闭环(男频系统流品类强制)。"""
    tr = task_reward or {}
    if not tr.get("required"):
        return []
    markers = [str(m).lower() for m in tr.get("markers") or []]
    if not markers:
        return []
    paras = _paragraphs(_body(content))
    if not paras:
        return []
    tail = " ".join(paras[-2:]).lower()
    if any(m in tail for m in markers):
        return []
    return [Issue("R11", "warn",
                  "章末未检出「任务—奖励」闭环标记(该品类要求每章有可结算的收益反馈)",
                  paras[-1][:100])]


# ---------------------------------------------------------------- 汇总

def run_checks(content: str, *,
               chapter_no: int | None = None,
               glossary=None,
               platform: dict | None = None,
               category: dict | None = None,
               language: dict | None = None,
               lang_id: str | None = None,
               paywall_chapters=None) -> list[Issue]:
    """跑全部 applicable 的规则,返回问题清单(空=通过)。

    platform / category / language 直接传规则 dict,便于测试与复用;
    要按 id 取的话用 `check_with_ids()`。

    lang_id(如 "fr-FR")决定书写系统:字数折算、「是不是中文」的判定都依赖它。
    漏传会让日/韩稿被当成中文稿跳过 R10(假绿),泰/阿/印地稿字数算成 0(假红)。
    """
    platform = platform or {}
    category = category or {}
    language = language or {}
    lang_id = lang_id or (language.get("id") or None)

    issues: list[Issue] = []
    # 语言规则文件里的模式优先(用户可编辑)。**只认语言无关的 `patterns` 列表**,
    # 外加向后兼容的 `.en` / `.zh`;两者都没有就**不跑 R1** —— 拿英语正则去套
    # 日文正文永远匹配不上,报「全过」比报错更危险(用户会以为质检真的过了)。
    sob = language.get("self_observation_forbidden") or {}
    pats: list | None = None
    if isinstance(sob, dict):
        pats = sob.get("patterns")
        if pats is None and (sob.get("en") or sob.get("zh")):
            pats = list(sob.get("en") or []) + list(sob.get("zh") or [])
        issues += check_self_observation(content, patterns=pats, lang=lang_id)
    elif isinstance(sob, list):
        issues += check_self_observation(content, patterns=sob, lang=lang_id)
    else:
        issues += check_self_observation(content, lang=lang_id)
    issues += check_passivity(content, lang=lang_id)
    issues += check_redundancy(content, lang=lang_id)
    issues += check_chinese_residue(
        content, forbid=(language.get("punctuation") or {}).get("forbid_fullwidth"),
        lang=lang_id)
    issues += check_glossary_consistency(content, glossary)

    ch = platform.get("chapter") or {}
    lo, hi = ch.get("min_words"), ch.get("max_words")
    bounds = (lo, hi) if isinstance(lo, int) and isinstance(hi, int) else None
    issues += check_chapter_words(content, bounds, lang=lang_id)

    pay = platform.get("paywall") or {}
    rng = pay.get("paywall_chapter_range")
    rng_t: tuple[int, int] | None = None
    if isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, int) for x in rng):
        rng_t = (rng[0], rng[1])
    issues += check_paywall_position(paywall_chapters, rng_t)

    opening = platform.get("opening") or {}
    issues += check_opening_payoff(content, category.get("payoff_keywords"),
                                   opening.get("payoff_within_chapters"), chapter_no)

    # 章末钩子标记:认 `patterns` 列表 / 任意语言 key 的 dict / 裸列表。
    # 仍认 `.en` + `.zh` 是为了兼容已发布的 en-US.json。
    markers: list[str] = []
    lang_markers = (language.get("hook_markers") or {})
    if isinstance(lang_markers, dict):
        pats_h = lang_markers.get("patterns")
        if isinstance(pats_h, list):
            markers = list(pats_h)
        else:
            for k, v in lang_markers.items():
                if k == "note" or not isinstance(v, list):
                    continue
                markers += list(v)
    elif isinstance(lang_markers, list):
        markers = list(lang_markers)
    issues += check_cliffhanger(content, markers)

    issues += check_translationese(content, language.get("translationese"), lang=lang_id)
    issues += check_task_reward(content, category.get("task_reward"))
    return issues


def check_with_ids(content: str, *, platform_id: str, category_id: str,
                   target_lang: str = "en-US", **kwargs) -> list[Issue]:
    """按规则 id 跑校验(从规则库取平台/品类/语言)。"""
    from . import overseas_rules
    return run_checks(
        content,
        platform=overseas_rules.get_platform(platform_id),
        category=overseas_rules.get_category(category_id),
        language=overseas_rules.get_language(target_lang),
        lang_id=target_lang,
        **kwargs)


def format_issues(issues) -> list[str]:
    """把问题清单转成可直接展示的文本行。"""
    return [str(i) for i in issues]
