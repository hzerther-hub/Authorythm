# -*- coding: utf-8 -*-
"""小说线:策划(novel_planner)→ 逐章生成(novel_writer)→ 六维审校(novel_reviewer)→ 改稿(novel_editor)。"""
from __future__ import annotations

import json
import re

from ..agents import runner
from ..core import config, db


# 写法风格预设(逐字对齐原版 episode.vue 的 NOVEL_STYLES):选中值全文写入 dramas.novel_style
NOVEL_STYLES = [
    ("爽感快节奏", "短句为主，情绪外露，段落简短，冲突直给，爽点前置，每章末尾必有小高潮"),
    ("细腻情感流", "重人物内心与情绪层次，描写细腻，节奏舒缓，重氛围与共情"),
    ("悬疑紧张", "信息差驱动，多伏笔，短段制造压迫感，章末反转"),
    ("古风雅致", "文白相间，用词考究，意境优先，节奏沉稳"),
    ("幽默轻松", "吐槽视角，反差与梗密集，轻松诙谐但不脱离主线"),
    ("硬核写实", "细节考据，冷静克制但不冷漠——动作与器物描写精确，同时保留人物内心戏与环境氛围，强逻辑因果"),
]
NOVEL_STYLE_CUSTOM = "__custom__"
DEFAULT_NOVEL_STYLE = NOVEL_STYLES[0][1]


# ── 叙事人称(对齐参考项目 episode.vue 故事合约向导的 pov 四选项 + novel.ts 的「视角=」注入)──
POV_OPTIONS: list[tuple[str, str]] = [
    ('first', '第一人称(以「我」叙述,只写主角可知可感的)'),
    ('second', '第二人称(以「你」叙述)'),
    ('third_limited', '第三人称限知(跟随主角视角,不写他人内心)'),
    ('third_omniscient', '第三人称全知(可自由出入任何人物内心)'),
]
POV_LABELS = dict(POV_OPTIONS)
POV_DEFAULT = "third_limited"


def get_novel_pov(drama_id: int) -> str:
    """项目叙事人称。

    两个存放位置都要认(历史上两套结构并存):
      1) dramas.novel_meta.contract.pov —— 向导产出的 JSON 合约
      2) dramas.novel_contract 的 JSON structured.pov —— 故事合约页存的
    都取不到(或不是合法 pov 值)时回退第三人称限知。
    """
    d = db.q1("SELECT novel_meta, novel_contract FROM dramas WHERE id=?", (drama_id,))
    if not d:
        return POV_DEFAULT
    meta = db.jload(d["novel_meta"], {}) or {}
    pov = str(((meta.get("contract") or {}) if isinstance(meta.get("contract"), dict)
               else {}).get("pov") or "").strip()
    if pov in POV_LABELS:
        return pov
    raw = (d["novel_contract"] or "")
    try:
        st = (json.loads(raw) or {}).get("structured") or {}
        pov = str(st.get("pov") or "").strip()
        if pov in POV_LABELS:
            return pov
    except Exception:  # noqa: BLE001 —— 纯文本合约走回退
        pass
    return POV_DEFAULT


def pov_rule(pov: str | None = None) -> str:
    """写章硬约束里的人称条款。"""
    return POV_LABELS.get(pov or "", POV_LABELS[POV_DEFAULT])


def set_novel_pov(drama_id: int, pov: str) -> str:
    """写回项目叙事人称(存novel_meta.contract.pov,兼容已有向导结构)。"""
    pov = pov if pov in POV_LABELS else POV_DEFAULT
    d = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
    meta = db.jload(d["novel_meta"], {}) or {} if d else {}
    contract = meta.get("contract")
    if not isinstance(contract, dict):
        contract = {}
    contract["pov"] = pov
    meta["contract"] = contract
    db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
    return pov


def get_novel_style(drama_id: int | None = None) -> str:
    """项目级文风优先;没有项目则回落到全局设置,再回落到默认预设。"""
    if drama_id:
        d = db.q1("SELECT novel_style FROM dramas WHERE id=?", (drama_id,))
        if d and (d["novel_style"] or "").strip():
            return d["novel_style"].strip()
    return db.get_setting("novel_style", "") or DEFAULT_NOVEL_STYLE


def set_novel_style(drama_id: int, style: str) -> None:
    db.ex("UPDATE dramas SET novel_style=?, updated_at=? WHERE id=?",
          ((style or "").strip(), db.now(), drama_id))


def plan_novel(drama_id: int, idea: str, config_id: int | None = None) -> dict:
    """开书策划:总纲/世界观/合约/卷战略/章节清单/主要角色,写入 dramas。"""
    prompt = f"新书创意:\n{idea[:6000]}\n\n请给出完整开书规划。"
    data = runner.run_agent_json("novel_planner", prompt, config_id=config_id)
    chapters = data.get("chapters", [])
    db.ex("""UPDATE dramas SET novel_outline=?, novel_world=?, novel_contract=?, novel_volume=?,
             novel_chapters=?, novel_meta=?, updated_at=? WHERE id=?""",
          (data.get("outline", ""), data.get("world", ""), data.get("contract", ""),
           json.dumps(data.get("volume", ""), ensure_ascii=False),
           json.dumps(chapters, ensure_ascii=False),
           json.dumps({"main_characters": data.get("main_characters", [])}, ensure_ascii=False),
           db.now(), drama_id))
    # 主要角色直接入资产库
    _sync_characters(drama_id, data.get("main_characters", []) or [])
    return data


def _sync_characters(drama_id: int, chars: list) -> int:
    """主要角色 → 资产库 characters(同名不重复插入),返回新增数。"""
    ts = db.now()
    added = 0
    for c in chars:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        if db.q1("SELECT id FROM characters WHERE drama_id=? AND name=?", (drama_id, name)):
            continue
        db.ex("INSERT INTO characters(drama_id,name,role_type,appearance,styling,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
              (drama_id, name, "lead" if c.get("role") in ("主角", "lead") else "supporting",
               c.get("appearance", ""), c.get("styling", ""), ts, ts))
        added += 1
    return added


def _novel_settings_ctx(drama_id: int) -> str:
    """已确定的项目设定(供策划阶段保持一致)。"""
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    if not d:
        return "(项目不存在)"
    meta = db.jload(d["metadata"], {}) or {}
    nm = db.jload(d["novel_meta"], {}) or {}
    return f"""书名:{d['title']}
题材:{meta.get('genre','') or '未定'}
简介:{meta.get('intro','') or '未定'}
写法文风:{(d['novel_style'] or '').strip() or '未选(按默认网文写法)'}
视觉风格:{d['style'] or '未定'}
总纲:{(d['novel_outline'] or '未定')[:1200]}
世界观:{(d['novel_world'] or '未定')[:1200]}
故事合约:{(d['novel_contract'] or '未定')[:800]}
分卷战略:{str(d['novel_volume'] or '未定')[:1200]}
已有章节计划:{len(db.jload(d['novel_chapters'], []) or [])} 章
目标全书:{d['total_episodes'] or '未定'} 章 / 每章 {nm.get('word_count') or '未定'} 字
人物状态台账:{_ledger_ctx(drama_id)}"""


def _ledger_ctx(drama_id: int) -> str:
    """写作上下文里的状态台账(事实层)。为空返回「未建立」。"""
    from . import state_ledger
    led = state_ledger.ledger_for_context(drama_id)
    if not led or not led.get("characters"):
        return "未建立(首章写完后自动生成)"
    return json.dumps(led, ensure_ascii=False)[:1800]


CHAPTER_PLAN_LIMIT = 200
CHAPTER_PLAN_PROMPT = """你是小说策划。基于已确定的项目设定,输出**逐章计划**。

要求:
- 正好 {count} 章,number 从 1 连续到 {count}
- title ≤14 字;goal(本章目标)≤25 字;events(核心事件,写清冲突与结果)≤50 字;cliffhanger(章末钩子)≤25 字
- 每章字数按 {words} 字安排,信息量与之匹配;不要为了凑章数复制情节
- 服从总纲与分卷战略,人名与世界观术语必须与设定一致
- **叙事人称(硬约束)**:{pov} —— 章节标题、目标、事件、钩子里的人物称谓必须与此人称一致,不得混用

输出 JSON:{{"chapters":[{{"number":1,"title":"","goal":"","events":"","cliffhanger":""}}]}}"""

SEGMENT_PLAN_PROMPT = """你是小说策划。{count} 章的长篇不适合逐章列细,改为**分段计划**。
叙事人称(硬约束):{pov} —— 标题与事件描述的称谓必须与此人称一致。
每段 20 章,共 {segments} 段。输出 JSON:
{{"segments":[{{"range":"1-20","title":"","goal":"","key_events":[""],"arc":""}}],
 "chapters":[{{"number":1,"title":"","goal":"","events":"","cliffhanger":""}}]}}
其中 chapters 只给每段前 3 章的示例细节(共 {samples} 条),用于校准颗粒度;每章字数 {words} 字。"""


def _plan_scale(drama_id: int, chapter_count: int | None, word_count: int | None) -> tuple[int, int]:
    nm = db.jload((db.q1("SELECT novel_meta,total_episodes FROM dramas WHERE id=?", (drama_id,))
                   or {"novel_meta": None, "total_episodes": None})["novel_meta"], {}) or {}
    # 章数单一来源 = dramas.total_episodes(「项目设置 → 集数」与「小说设定 → 全书章数」共用);
    # novel_meta.chapter_count 为历史遗留,不再参与取值,避免两处显示不一致
    n = int(chapter_count or db.q1(
        "SELECT total_episodes FROM dramas WHERE id=?", (drama_id,))["total_episodes"] or 60)
    words = int(word_count or nm.get("word_count") or 2500)
    return max(1, min(999, n)), words


def chapters_prompt(drama_id: int, chapter_count: int | None = None,
                    word_count: int | None = None) -> str:
    """构造章节计划提示词(与 persist_chapters 配对,便于流式边收边显示)。"""
    n, words = _plan_scale(drama_id, chapter_count, word_count)
    ctx = _novel_settings_ctx(drama_id)
    pov = pov_rule(get_novel_pov(drama_id))
    if n <= CHAPTER_PLAN_LIMIT:
        return f"{ctx}\n\n{CHAPTER_PLAN_PROMPT.format(count=n, words=words, pov=pov)}"
    segs = (n + 19) // 20
    return f"{ctx}\n\n" + SEGMENT_PLAN_PROMPT.format(count=n, segments=segs,
                                                          samples=segs * 3, words=words,
                                                          pov=pov)


# 长篇分批生成:一次请求只让模型写一批(单批 40 章,JSON 体积可控),
# 循环累积直到 n 章 —— 999 章单次请求会超出 token 预算,模型只能吐散文,解析全废。
CHAPTER_BATCH = 40
CHAPTER_BATCH_PROMPT = """你是小说策划。基于已确定的项目设定,输出**第 {start} 章到第 {end} 章**的逐章计划。

要求:
- 正好 {count} 章,number 从 {start} 连续到 {end}(全书共 {total} 章)
- title ≤14 字;goal(本章目标)≤25 字;events(核心事件,写清冲突与结果)≤50 字;cliffhanger(章末钩子)≤25 字
- 每章字数按 {words} 字安排;不要为了凑章数复制情节
- 承接前情:{prev} ;后续走向:{next}
- 服从总纲与分卷战略,人名与世界观术语必须与设定一致
- **叙事人称(硬约束)**:{pov} —— 章节标题与事件描述的称谓必须与此人称一致
- **只输出 JSON,不要任何解释文字**

输出 JSON:{{"chapters":[{{"number":{start},"title":"","goal":"","events":"","cliffhanger":""}}]}}"""


def chapters_batch_prompt(drama_id: int, start: int, count: int, total: int,
                          word_count: int, prev_hint: str = "", next_hint: str = "") -> str:
    """构造某一章区间的计划提示词(长篇分批生成用)。"""
    ctx = _novel_settings_ctx(drama_id)
    return CHAPTER_BATCH_PROMPT.format(
        start=start, end=start + count - 1, count=count, total=total,
        words=word_count, pov=pov_rule(get_novel_pov(drama_id)),
        prev=(prev_hint or "全书开篇(第 1 章)")[:200],
        next=(next_hint or "按总纲推进")[:200]) + "\n\n" + ctx


def generate_chapters_batched(drama_id: int, chapter_count: int | None = None,
                              word_count: int | None = None,
                              config_id: int | None = None,
                              progress=None) -> dict:
    """分批生成整本书的逐章计划并落库。progress(percent, done, total)。"""
    n, words = _plan_scale(drama_id, chapter_count, word_count)
    all_ch: list[dict] = []
    total_batches = (n + CHAPTER_BATCH - 1) // CHAPTER_BATCH
    for bi in range(total_batches):
        start = bi * CHAPTER_BATCH + 1
        cnt = min(CHAPTER_BATCH, n - start + 1)
        prev_hint = ""
        if all_ch:
            last = all_ch[-1]
            prev_hint = f"第{last['number']}章《{last.get('title','')}》钩子:{last.get('cliffhanger','')}"
        raw = runner.run_agent("novel_planner",
                               chapters_batch_prompt(drama_id, start, cnt, n, words,
                                                     prev_hint=prev_hint),
                               temperature=0.4, config_id=config_id,
                               # 输出预算取该服务配置的「最大输出 token」
                               max_tokens=None)
        data = runner.extract_json(raw) or {}
        batch = _clean_chapter_list(data.get("chapters"), n)
        if not batch:
            raise RuntimeError(f"第 {start}-{start + cnt - 1} 章生成失败"
                               f"(返回 {len(raw)} 字,疑似被截断)")
        all_ch += batch
        if progress:
            progress(int(len(all_ch) * 100 / n), len(all_ch), n)
    all_ch.sort(key=lambda c: c["number"])
    nm = db.jload((db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
                   or {"novel_meta": None})["novel_meta"], {}) or {}
    nm.pop("chapter_count", None)    # 真源统一为 total_episodes
    nm["word_count"] = words
    db.ex("UPDATE dramas SET novel_chapters=?, novel_meta=?, total_episodes=?, updated_at=? WHERE id=?",
          (json.dumps(all_ch, ensure_ascii=False), json.dumps(nm, ensure_ascii=False),
           n, db.now(), drama_id))
    return {"count": len(all_ch), "word_count": words, "chapters": all_ch}


def _parse_chapters_lenient(raw: str) -> list:
    """从可能**被截断**的 JSON 里救回已生成的章节。

    思考型模型把输出预算耗尽时,{"chapters":[{...},{... 结尾会断在半截。
    这里逐个对象回退解析:完整对象照收,最后那个残缺对象丢弃,
    宁可少几章也不要整批报废。
    """
    import re as _re
    out: list[dict] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(raw):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                frag = raw[start:i + 1]
                try:
                    obj = json.loads(frag)
                    if isinstance(obj, dict) and (obj.get("goal") or obj.get("events")):
                        out.append(obj)
                except Exception:  # noqa: BLE001
                    pass
                start = -1
    if not out:
        m = _re.search(r'"chapters"\s*:', raw)
        if m:
            return _parse_chapters_lenient(raw[m.end():])
    return out


def persist_chapters(drama_id: int, raw: str, chapter_count: int | None = None,
                     word_count: int | None = None) -> dict:
    """解析并落库章节计划;返回 {count, word_count}。"""
    n, words = _plan_scale(drama_id, chapter_count, word_count)
    raw = _strip_tool_calls(raw or "").strip()
    if not raw:
        raise RuntimeError("章节计划返回空内容")
    data = runner.extract_json(raw) or {}
    chapters = _clean_chapter_list(data.get("chapters"), n,
                                   allow_sparse=(n > CHAPTER_PLAN_LIMIT))
    if not chapters:
        # JSON 不完整(被输出预算截断)→ 逐对象抢救已生成的章节
        salvaged = _clean_chapter_list(_parse_chapters_lenient(raw), n, allow_sparse=True)
        if salvaged:
            chapters = salvaged
    if not chapters:
        raise RuntimeError(f"未解析出章节计划(前 120 字:{raw[:120]})")
    nm = db.jload((db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
                   or {"novel_meta": None})["novel_meta"], {}) or {}
    nm.pop("chapter_count", None)    # 真源统一为 total_episodes
    nm["word_count"] = words
    db.ex("UPDATE dramas SET novel_chapters=?, novel_meta=?, total_episodes=?, updated_at=? WHERE id=?",
          (json.dumps(chapters, ensure_ascii=False), json.dumps(nm, ensure_ascii=False),
           n, db.now(), drama_id))
    return {"count": len(chapters), "word_count": words, "chapters": chapters}


def plan_chapters(drama_id: int, chapter_count: int | None = None,
                  word_count: int | None = None, config_id: int | None = None) -> dict:
    """一次性生成并落库逐章计划(非流式路径;UI 走 chapters_prompt + persist_chapters)。"""
    raw = runner.run_agent("novel_planner", chapters_prompt(drama_id, chapter_count, word_count),
                           temperature=0.4, config_id=config_id,
                           system=_draft_system("章节计划"))
    out = persist_chapters(drama_id, raw, chapter_count, word_count)
    return {"chapters": out["chapters"], "count": out["count"], "word_count": out["word_count"]}


def _clean_chapter_list(raw, expected: int, allow_sparse: bool = False) -> list:
    """规整 AI 返回的章节数组:补 number、截断到 expected、丢弃缺字段项。"""
    out = []
    for i, c in enumerate(raw or []):
        if not isinstance(c, dict):
            continue
        goal = str(c.get("goal") or "").strip()
        events = str(c.get("events") or "").strip()
        if not goal and not events:
            continue
        out.append({"number": int(c.get("number") or i + 1),
                    "title": str(c.get("title") or "").strip()[:40],
                    "goal": goal[:200], "events": events[:500],
                    "cliffhanger": str(c.get("cliffhanger") or "").strip()[:200]})
    out.sort(key=lambda c: c["number"])
    if allow_sparse:
        return out
    return out[:expected] or out


CHARACTER_PROMPT = """你是小说策划。基于已确定的设定与章节计划,设计**主要角色**。

要求:
- 6-12 个:1 个主角 + 2-3 个核心对手/伙伴 + 若干关键配角
- role 写"主角"/"对手"/"同伴"/"配角" 之一
- motivation(动机)与章节计划中的实际行为对得上,不要空泛
- appearance(外形)要能直接转成文生图提示词(年龄段/性别/发型/体型/标志特征/典型穿着)
- styling(服装风格)同样给出可出图的具体描述

输出 JSON:{{"characters":[{{"name":"","role":"","identity":"","motivation":"",
"appearance":"","styling":""}}]}}只输出 JSON。"""


def plan_characters(drama_id: int, config_id: int | None = None) -> dict:
    """AI 生成主要角色。章节计划缺失时先在后台补章节计划(依赖先行)。"""
    d = db.q1("SELECT novel_chapters FROM dramas WHERE id=?", (drama_id,))
    chapters = db.jload(d["novel_chapters"], []) if d else []
    if not chapters:
        plan_chapters(drama_id, config_id=config_id)          # 章节计划是角色设计的前置
        d = db.q1("SELECT novel_chapters FROM dramas WHERE id=?", (drama_id,))
        chapters = db.jload(d["novel_chapters"], []) or []
    ctx = _novel_settings_ctx(drama_id)
    plan_txt = chapters_to_text(chapters)[:6000]
    raw = runner.run_agent("novel_planner",
                           f"{ctx}\n\n章节计划:\n{plan_txt}\n\n{CHARACTER_PROMPT}",
                           temperature=0.5, config_id=config_id)
    chars = _clean_characters((runner.extract_json(raw) or {}).get("characters"))
    if not chars:
        raise RuntimeError("AI 未返回角色,请重试或检查文本模型配置")
    meta = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))["novel_meta"], {}) or {}
    meta["main_characters"] = chars
    db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
    _sync_characters(drama_id, chars)
    return {"characters": chars, "count": len(chars)}


def _clean_characters(raw) -> list:
    out = []
    for c in raw or []:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        out.append({"name": name[:40], "role": str(c.get("role") or "配角")[:20],
                    "identity": str(c.get("identity") or "").strip()[:200],
                    "motivation": str(c.get("motivation") or "").strip()[:200],
                    "appearance": str(c.get("appearance") or "").strip()[:400],
                    "styling": str(c.get("styling") or "").strip()[:400]})
    return out[:12]


CHAPTER_LINE_RE = re.compile(r"^\s*第\s*([0-9零一二两三四五六七八九十百千]+)\s*[章集回节]?\s*(.*)$")
FIELD_ALIASES = {"目标": "goal", "事件": "events", "钩子": "cliffhanger",
                 "goal": "goal", "events": "events", "cliffhanger": "cliffhanger"}
_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def _chapter_num(raw: str) -> int:
    """章号:阿拉伯数字直接取;中文数字(含「十/百/千」)按位展开。"""
    s = (raw or "").strip()
    if s.isdigit():
        return int(s)
    if not s or any(c not in _CN_DIGITS and c not in "十百千" for c in s):
        return 0
    total, section, number = 0, 0, 0
    for c in s:
        if c in _CN_DIGITS:
            number = _CN_DIGITS[c]
        else:
            unit = {"十": 10, "百": 100, "千": 1000}[c]
            section += (number or 1) * unit
            number = 0
    return total + section + number


def chapters_to_text(chapters: list) -> str:
    """章节数组 → 可读可编辑的一行一章文本(面板展示与手工编辑用)。"""
    lines = []
    for c in chapters or []:
        title = (c.get("title") or "").strip()
        lines.append(
            f"第{c.get('number', '?')}章 {title} | 目标:{c.get('goal', '')}"
            f" | 事件:{c.get('events', '')} | 钩子:{c.get('cliffhanger', '')}")
    return "\n".join(lines)


def chapters_from_text(text: str) -> list:
    """可编辑文本 → 章节数组(容错:非「第N章」开头的续行并入上一章事件)。"""
    chapters = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = CHAPTER_LINE_RE.match(line)
        if m:
            rest = m.group(2).strip()
            title, _, tail = rest.partition("|")
            item = {"number": _chapter_num(m.group(1)), "title": title.strip()[:40],
                    "goal": "", "events": "", "cliffhanger": ""}
            chapters.append(item)
            for seg in tail.split("|"):
                if ":" in seg:
                    k, _, v = seg.partition(":")
                elif "：" in seg:
                    k, _, v = seg.partition("：")
                else:
                    continue
                key = FIELD_ALIASES.get(k.strip())
                if key:
                    item[key] = v.strip()[:500]
        elif chapters:                       # 续行并入上一章
            chapters[-1]["events"] = (chapters[-1]["events"] + "\n" + line)[:500]
    return [c for c in chapters if c.get("goal") or c.get("events") or c.get("title")]


def save_chapters(drama_id: int, chapters: list) -> int:
    meta = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))["novel_meta"], {}) or {}
    meta.pop("chapter_count", None)     # 真源统一为 total_episodes,不再留第二份
    db.ex("UPDATE dramas SET novel_chapters=?, novel_meta=?, total_episodes=?, updated_at=? WHERE id=?",
          (json.dumps(chapters, ensure_ascii=False), json.dumps(meta, ensure_ascii=False),
           len(chapters), db.now(), drama_id))
    return len(chapters)


def save_characters(drama_id: int, chars: list) -> int:
    chars = _clean_characters(chars)
    meta = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))["novel_meta"], {}) or {}
    meta["main_characters"] = chars
    db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
    _sync_characters(drama_id, chars)
    return len(chars)


def chapter_prompt(episode_id: int) -> str:
    """组装写章提示词(设定/本章计划/文风/台账/前情全部内联;流式路径与 write_chapter 共用)。"""
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("剧集(章)不存在")
    d = db.q1("SELECT * FROM dramas WHERE id=?", (ep["drama_id"],))
    chapters = db.jload(d["novel_chapters"], [])
    plan = next((c for c in chapters if int(c.get("number", 0)) == ep["episode_number"]), {})
    # 上一章 = 集数紧邻且正文非空的那一集(降序取第一行,修原版「升序取到第1集」的 bug)
    prev = db.q("""SELECT episode_number, content FROM episodes
                  WHERE drama_id=? AND episode_number<? AND content IS NOT NULL AND content!=''
                  ORDER BY episode_number DESC LIMIT 1""",
                (ep["drama_id"], ep["episode_number"]))
    prev_summary = (prev[0]["content"] or "")[-800:] if prev else "(本章为第一章)"
    prompt = f"""小说设定:
总纲: {(d['novel_outline'] or '')[:600]}
世界观: {(d['novel_world'] or '')[:600]}
故事合约: {(d['novel_contract'] or '')[:400]}
叙事人称(硬约束): {pov_rule(get_novel_pov(ep['drama_id']))} —— 全章严格遵守,不得中途切换人称;人物内心只能写该人称允许的范围。
本章计划: 第{ep['episode_number']}章 {plan.get('title','')} — 目标:{plan.get('goal','')} 事件:{plan.get('events','')} 钩子:{plan.get('cliffhanger','')}
文风: {get_novel_style(ep['drama_id'])}
人物状态台账(硬约束,不得无交代地跳变): {_ledger_ctx(ep['drama_id'])}
目标字数: {ep['target_words'] or 2500}
上一章结尾(衔接用): {prev_summary}

请输出本章正文。

正文硬约束(违反即不合格):
- 段落必须是完整自然段:每段 3-6 句,严禁一行一句的流水账写法;
- 每一段至少包含其一:心理描写(人物的念头/权衡/情绪暗涌)、环境细节(光线/气味/声音/温度/材质/周遭动静)、动作细节(带力度与身体反应);
- 心理与环境要交织推进叙事,不是独立成段的装饰;
- 对话后要有对方的动作/神态承接,不要只留一行引号;
- 禁止用「叶尘没有动。」这类一句话一段的记账式写法;

章节名优先沿用上面【本章计划】里的标题(原样使用,不要改写);
无计划标题时再自行起一个简短、有钩子的章节名(不超过 12 个汉字,不带「第N集」前缀)。
把章节名作为独立一行写在正文最前面,格式为 `# 章节名`。"""
    return prompt


def _write_chapter_text(prompt: str, config_id: int | None, lang: str | None,
                        max_tokens: int) -> tuple[str, str]:
    """流式写正文,返回 (正文, 思考全文)。

    为什么走流式:实测 MiniMax-M3 在非流式请求下把成稿放进 reasoning_content,
    content 通道只剩标题一行;流式通道 reasoning/content 分离稳定,空正文时
    还能从思考流里按 </think> 抢救。
    """
    from ..ai import text_stream
    from ..agents.prompts import load_prompt
    system = load_prompt("novel_writer", lang or db.get_setting("content_language", "zh"))
    parts: list[str] = []
    rparts: list[str] = []
    for kind, chunk in text_stream.chat_stream(prompt, system=system, config_id=config_id,
                                               temperature=0.6, max_tokens=max_tokens):
        (rparts if kind == "reasoning" else parts).append(chunk)
    content = _strip_think("".join(parts))
    if len(content) < 200:
        # M3 实测会把成稿整段写进思考通道(哪个通道拿到成稿是随机的):
        # 合并双通道,取最后一个「# 章节名」标记之后的部分 = 标题+全文;
        # 再滤掉英文规划行(中文字符占比过低的行)。
        combined = _strip_think("".join(rparts) + "\n" + "".join(parts))
        idx = combined.rfind("\n# ")
        cand = combined[idx:].strip() if idx >= 0 else ""

        def _cjk_line(ln: str) -> bool:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                return bool(ln)
            cjk = sum(1 for ch in ln if "\u4e00" <= ch <= "\u9fff")
            return cjk >= max(2, len(ln) * 0.3)

        cand = "\n".join(ln for ln in cand.split("\n") if _cjk_line(ln))
        if len(cand) >= 200:
            content = cand
    return content, "".join(rparts)


def write_chapter(episode_id: int, config_id: int | None = None,
                  lang: str | None = None) -> str:
    """按章节计划写当前章正文(自动带前情+设定),写回 episodes.content。

    lang: AI 产出语言(透传 run_agent;None=跟随文本提示词文件默认)。
    """
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("剧集(章)不存在")
    # 写作红线:小说项目设定未齐时,任何入口(按钮/批量/程序化)都写不了
    _enforce_novel_gate(ep["drama_id"])
    # 思考型模型(M3)行为有波动:偶发只输出标题一行。给三次机会(8k→32k→32k)。
    content = ""
    for budget in (8192, 32768, 32768):
        content, _reason = _write_chapter_text(chapter_prompt(episode_id), config_id, lang, budget)
        if len(content) >= 200:
            break
    return _save_with_title(episode_id, content)


def _strip_think(content: str) -> str:
    """剥掉模型把思考过程混进正文通道的片段:成对 <think> 块、未闭合的 <think> 尾巴,
    以及开头整段的英文元思考(Wait/Let me... —— 见 nov 综合征,实测出现过)。"""
    import re as _re
    text = (content or "")
    text = _re.sub(r"<tool_call>.*?(?:</tool_call>|$)", "", text, flags=_re.S)
    text = _re.sub(r"<think>.*?</think>", "", text, flags=_re.S)
    text = _re.sub(r"(?s)^.*?<think>", "", text) if "<think>" in text else text
    text = _re.sub(r"(?s)^(Wait|Actually|Let me|Hmm|Okay|So I)[^.]*\.(\s|(Wait|Actually|Let me|Hmm|Okay|So I)[^.]*\.)+", "", text)
    return text.strip()


def _save_with_title(episode_id: int, content: str) -> str:
    """保存正文;若首行是 `# 章节名`,顺带写回 episodes.title(对齐原版 save_episode_content.chapter_title)。"""
    import re as _re
    text = _strip_think(content)
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        return content
    m = _re.match(r"^#\s*(.+?)\s*$", text.splitlines()[0]) if text.splitlines() else None
    if m:
        name = _clean_chapter_name(m.group(1))
        if name:
            _apply_chapter_title(dict(ep), name, text)
            return db.q1("SELECT content FROM episodes WHERE id=?", (episode_id,))["content"] or ""
    db.ex("UPDATE episodes SET content=?, updated_at=? WHERE id=?", (text, db.now(), episode_id))
    return text


def write_chapter_with_review(episode_id: int, config_id: int | None = None,
                              task_id: int | None = None,
                              lang: str | None = None,
                              content: str | None = None) -> dict:
    """写章 → 写后校验 → 六维审校 → 有问题带清单重写一轮。

    对齐原版(101759d + 未提交批次):
    - 写后校验:以 episodes.content 为准,`len < 200` 视为模型没真写入 →
      抛错让上层重试一次,避免"界面显示完成但章节空着,极难排查"。
    - 阶段标记:writing → reviewing → repairing 写进 sys_task.params.stage,
      批量面板据此显示"当前在做什么"(正文生成要几十秒,只有阶段可见才不像卡死)。
    """
    from ..core import taskmgr as TM
    MIN_CHARS = 200

    def _stage(s: str):
        if task_id:
            TM.set_stage(task_id, s)

    _stage("writing" if not content else "reviewing")
    if content is not None:            # 流式路径:正文已生成,只落库后直接审校
        _save_with_title(episode_id, content)
    else:
        write_chapter(episode_id, config_id=config_id, lang=lang)
    row = db.q1("SELECT content, episode_number FROM episodes WHERE id=?", (episode_id,))
    content = (row["content"] if row else "") or ""
    if len(content.strip()) < MIN_CHARS:
        num = row["episode_number"] if row else "?"
        raise RuntimeError(f"第 {num} 集未写入正文(仅 {len(content.strip())} 字符),请重新生成")

    _stage("reviewing")
    try:
        review = review_chapter(episode_id, config_id=config_id, lang=lang)
    except Exception:  # noqa: BLE001
        return {"content": content, "review": None, "fixed": False}
    if isinstance(review, dict) and review.get("overall") == "fix":
        issues = []
        for dim, v in (review.get("dimensions") or {}).items():
            if isinstance(v, dict) and not v.get("pass", True):
                issues.append(f"[{dim}] " + "; ".join(v.get("issues", [])[:3]))
        if issues:
            _stage("repairing")
            fix_prompt = ("审校发现以下问题,请修复后输出完整修订正文:\n" + "\n".join(issues[:8])
                          + f"\n\n本项目叙事人称: {pov_rule(get_novel_pov(ep['drama_id']))}(修复时必须保持不变)"
                          + f"\n\n原正文:\n{content[:14000]}")
            fixed = _strip_think(runner.run_agent("novel_editor", fix_prompt, lang=lang, config_id=config_id))
            db.ex("UPDATE episodes SET content=?, updated_at=? WHERE id=?", (fixed, db.now(), episode_id))
            return {"content": fixed, "review": review, "fixed": True}
    return {"content": content, "review": review, "fixed": False}


def load_cover_asset_refs(drama_id: int, limit: int = 5) -> list[str]:
    """封面参考图:角色 3 + 场景 1 + 道具 1,去重后截断(对齐原版 loadCoverAssetRefs)。

    已有资产时喂给模型,保证封面人物/场景与正片一致;新建项目无资产则列表为空,
    退回纯文字生成。
    """
    refs: list[str] = []
    for sql in ("SELECT image_url FROM characters WHERE drama_id=? AND image_url IS NOT NULL ORDER BY id LIMIT 3",
                "SELECT image_url FROM scenes WHERE drama_id=? AND image_url IS NOT NULL ORDER BY id LIMIT 1",
                "SELECT image_url FROM props WHERE drama_id=? AND image_url IS NOT NULL ORDER BY id LIMIT 1"):
        for r in db.q(sql, (drama_id,)):
            u = (r["image_url"] or "").strip()
            if u and u not in refs:
                refs.append(u)
    return refs[:limit]


def _cover_style(drama_id: int) -> str:
    d = db.q1("SELECT comic_style, style FROM dramas WHERE id=?", (drama_id,))
    return db.style_prompt((d["comic_style"] or d["style"] or "3d") if d else "3d")


def generate_cover(drama_id: int, prompt: str = "", config_id: int | None = None,
                   size: str = "768x1024") -> str:
    """AI 生成项目封面(3:4 竖版),写 dramas.thumbnail;返回 /static URL。

    对齐原版 POST /novel/generate-cover:已有资产(角色/场景/道具)时作为参考图喂给模型,
    要求人物长相与场景设定与正片完全一致;关键内容与书名留居中安全区,
    七猫等 9:16 平台裁切也不伤主体。
    """
    from ..ai import image_client
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    if not d:
        raise RuntimeError("项目不存在")
    meta = db.jload(d["metadata"], {}) or {}
    asset_refs = load_cover_asset_refs(drama_id)
    text = (prompt or "").strip() or ", ".join(x for x in [
        f"Book cover art for the novel 《{d['title']}》",
        f"Genre: {meta.get('genre') or 'fiction'}",
        f"Synopsis: {(meta.get('intro') or '')[:220]}",
        "tall 3:4 portrait book cover, professional composition, dramatic cinematic lighting, high detail, no watermark",
        "title text area and main subject kept inside the central safe zone (critical elements away from edges), "
        "clean space reserved for title text",
        ("The characters and setting must match the reference images exactly "
         "(same faces, same outfits, same environment)") if asset_refs else "",
        _cover_style(drama_id),
    ] if x)
    out, _p = image_client.generate_image(text, out_name=f"cover_{drama_id}.png",
                                          config_id=config_id, size=size,
                                          reference_images=asset_refs)
    url = config.path_to_media_url(out)
    db.ex("UPDATE dramas SET thumbnail=?, updated_at=? WHERE id=?", (url, db.now(), drama_id))
    return url


def generate_episode_cover(episode_id: int, prompt: str = "", config_id: int | None = None) -> str:
    """AI 生成单章封面(3:4),写 episodes.thumbnail(不影响项目封面与正文)。"""
    from ..ai import image_client
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("章节不存在")
    d = db.q1("SELECT * FROM dramas WHERE id=?", (ep["drama_id"],))
    asset_refs = load_cover_asset_refs(ep["drama_id"])
    excerpt = " ".join((ep["content"] or "").split())[:200]
    text = (prompt or "").strip() or ", ".join(x for x in [
        f"Book cover art for chapter {ep['episode_number']} of the novel 《{(d or {}).get('title', '')}》",
        f"Chapter title: {ep['title'] or ''}",
        f"Chapter excerpt: {excerpt}" if excerpt else "",
        "tall 3:4 portrait book cover, single dramatic scene, professional composition, cinematic lighting, "
        "high detail, no text, no watermark",
        "main subject kept inside the central safe zone (critical elements away from edges)",
        ("The characters and setting must match the reference images exactly "
         "(same faces, same outfits, same environment)") if asset_refs else "",
        _cover_style(ep["drama_id"]),
    ] if x)
    out, _p = image_client.generate_image(text, out_name=f"epcover_{episode_id}.png",
                                          config_id=config_id, size="768x1024",
                                          reference_images=asset_refs)
    url = config.path_to_media_url(out)
    db.ex("UPDATE episodes SET thumbnail=?, updated_at=? WHERE id=?", (url, db.now(), episode_id))
    return url


def save_plan(drama_id: int, outline: str, world: str, contract: str, volume: str) -> None:
    """策划面板手动保存四件套(章节清单经 novel_planner 重新生成)。"""
    db.ex("""UPDATE dramas SET novel_outline=?, novel_world=?, novel_contract=?, novel_volume=?, updated_at=? WHERE id=?""",
          (outline, world, contract, volume, db.now(), drama_id))


def check_pov_violation(content: str, pov: str) -> list[str]:
    """规则化人称抽检:返回违规说明(空=通过)。

    只做高置信判断避免误伤:第一人称看是否出现成段第三人称叙述;
    第三人称看是否出现「我」作叙述者自称。
    """
    import re as _re
    body = _re.sub(r"^#.*$", "", content or "", flags=_re.M)
    issues: list[str] = []
    n_wo = body.count("我")
    if pov == "first":
        third = len(_re.findall(r"(他|她)(?!们)", body))
        if third >= 10 or n_wo == 0:
            issues.append(f"设定为第一人称,但正文「我」仅 {n_wo} 次、「他/她」{third} 次,疑似人称漂移")
    elif pov in ("third_limited", "third_omniscient") and n_wo > 5:
        issues.append(f"设定为第三人称,但正文出现第一人称「我」{n_wo} 次")
    return issues


def review_chapter(episode_id: int, config_id: int | None = None) -> dict:
    """六维审校,结果存 episodes.review_json。"""
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep or not (ep["content"] or "").strip():
        raise RuntimeError("本章还没有正文")
    pov = get_novel_pov(ep["drama_id"])
    prompt = (f"第 {ep['episode_number']} 章正文:\n{(ep['content'] or '')[:15000]}\n\n"
              f"【本项目叙事人称】{pov_rule(pov)}(硬约束,审校时必须核对是否被违反)")
    data = runner.run_agent_json("novel_reviewer", prompt, config_id=config_id)
    # 规则化人称抽检:模型漏检时兜底,不额外调用模型
    violations = check_pov_violation(ep["content"] or "", pov)
    if violations:
        pov_dim = (data.setdefault("dimensions", {})).setdefault("pov", {})
        if isinstance(pov_dim, dict):
            pov_dim["pass"] = False
            pov_dim.setdefault("issues", []).extend(violations)
        if data.get("overall") not in ("fix",):
            data["overall"] = "fix"
    db.ex("UPDATE episodes SET review_json=?, updated_at=? WHERE id=?",
          (json.dumps(data, ensure_ascii=False), db.now(), episode_id))
    return data


def edit_chapter(episode_id: int, instruction: str, config_id: int | None = None) -> str:
    """按指令改写本章正文。"""
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep or not (ep["content"] or "").strip():
        raise RuntimeError("本章还没有正文")
    prompt = (f"修改指令: {instruction}\n"
              f"本项目叙事人称(必须保持不变): {pov_rule(get_novel_pov(ep['drama_id']))}"
              f"\n\n正文:\n{ep['content'][:15000]}")
    content = runner.run_agent("novel_editor", prompt, config_id=config_id)
    db.ex("UPDATE episodes SET content=?, updated_at=? WHERE id=?", (content, db.now(), episode_id))
    return content


def export_book(drama_id: int, out_dir: str) -> str:
    """导出整本书目录结构(书名/第N章 标题.txt);返回根目录。"""
    from pathlib import Path
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    if not d:
        raise RuntimeError("项目不存在")
    root = Path(out_dir) / (d["title"].replace("/", "_")[:60])
    root.mkdir(parents=True, exist_ok=True)
    # 封面:有 thumbnail 就复制到导出根目录(缺失不阻断导出,同原版)
    if d["thumbnail"]:
        try:
            src = config.media_url_to_path(d["thumbnail"])
            if src.exists():
                (root / "封面.png").write_bytes(src.read_bytes())
        except Exception:  # noqa: BLE001
            pass
    (root / "设定.md").write_text(
        f"# {d['title']}\n\n## 总纲\n{d['novel_outline'] or ''}\n\n## 世界观\n{d['novel_world'] or ''}\n\n## 故事合约\n{d['novel_contract'] or ''}\n",
        encoding="utf-8")
    chapters = db.jload(d["novel_chapters"], [])
    titles = {int(c.get("number", 0)): c.get("title", "") for c in chapters}
    for ep in db.q("SELECT * FROM episodes WHERE drama_id=? ORDER BY episode_number", (drama_id,)):
        title = titles.get(ep["episode_number"], ep["title"] or "")
        name = f"第{ep['episode_number']}章 {title}".strip().replace("/", "_")[:70]
        (root / f"{name}.txt").write_text(ep["content"] or "", encoding="utf-8")
    return str(root)


def _clean_chapter_name(raw: str) -> str:
    """章节名清洗(三级,对齐原版):取首行 → 去「第N集」前缀 → 去引号/井号 → 截断 20 字。"""
    import re as _re
    lines = [l.strip() for l in (raw or "").splitlines() if l.strip()]
    if not lines:
        return ""
    name = _re.sub(r"^第\d+集[:：、\s]*", "", lines[0])
    name = _re.sub(r"^[#《「『\"'\s]+|[#》」』\"'\s]+$", "", name)
    return name[:20].strip()


def _apply_chapter_title(ep, name: str, text: str | None = None) -> str:
    """写回 episodes.title = 「第N集 <name>」,并同步正文首行 `# <name>`。

    text 必须传本次生成的新正文;不传(或传 None)才会回退 ep["content"] 旧快照 ——
    曾经只用旧快照,把刚生成的正文整段丢掉,落库只剩标题一行(实测 11 字符)。
    """
    import re as _re
    title = f"第{ep['episode_number']}集 {name}"
    text = (ep["content"] or "") if text is None else text
    if _re.match(r"^#\s+", text):
        new_text = _re.sub(r"^#\s+.*$", f"# {name}", text, count=1)
    else:
        new_text = f"# {name}\n\n{text}"
    db.ex("UPDATE episodes SET title=?, content=?, updated_at=? WHERE id=?",
          (title, new_text, db.now(), ep["id"]))
    return name


def extract_title_from_content(content: str) -> str:
    """从正文首行反向提取已存在的章节名(不调 AI,对齐原版 73b3339)。

    支持两种写法:`# 归乡的井`(markdown 标题)与 `第1集 县医院的消毒水味`;
    清洗书名号/引号/尾部标点;超过 30 字视为正文不当作标题。提取不到返回空串。
    """
    import re as _re
    first = next((l.strip() for l in (content or "").splitlines() if l.strip()), "")
    if not first:
        return ""
    if _re.match(r"^#{1,3}\s+", first):
        name = _re.sub(r"^#{1,3}\s+", "", first)
    elif _re.match(r"^第\d+集", first):
        name = _re.sub(r"^第\d+集\s*[:：、.\-—]?\s*", "", first)
    else:
        return ""
    name = _re.sub(r"^[#《「『\"'\s]+|[》」』\"'\s]+$", "", name)
    name = _re.sub(r"[。！？!?，,、；;]+$", "", name).strip()
    return name if name and len(name) <= 30 else ""


def gen_chapter_title(episode_id: int, config_id: int | None = None) -> tuple[str, str]:
    """一键章节名(对齐原版 POST /novel/chapter-title)。

    优先反向提取:正文首行已有 `# 名字` / 「第N集 名字」时直接取用,不调模型;
    提取不到才走 AI(上下文=总纲 400 字 + 前三章摘要各 200 字 + 本章节选 2000 字)。
    返回 (章节名, 来源 'content' | 'ai')。
    """
    import re as _re
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("剧集不存在")
    text = ep["content"] or ""
    if len(text.strip()) < 50:
        raise RuntimeError("本集正文太短,先粘贴或生成原文再起章节名")
    # 仅在标题为占位时提取,避免覆盖用户已改好的名字
    existing = (ep["title"] or "").strip()
    if (not existing) or _re.match(r"^第\d+集\s*$", existing):
        extracted = extract_title_from_content(text)
        if extracted:
            db.ex("UPDATE episodes SET title=?, updated_at=? WHERE id=?",
                  (f"第{ep['episode_number']}集 {extracted}", db.now(), episode_id))
            return extracted, "content"
    d = db.q1("SELECT * FROM dramas WHERE id=?", (ep["drama_id"],))
    parts: list[str] = []
    if d["novel_outline"]:
        parts.append("【总纲节选】\n" + (d["novel_outline"] or "")[:400])
    prev = db.q("SELECT episode_number, content FROM episodes WHERE drama_id=? AND episode_number<? "
                "ORDER BY episode_number DESC LIMIT 3", (ep["drama_id"], ep["episode_number"]))
    if prev:
        lines = [f"第{r['episode_number']}集摘要:" + " ".join((r["content"] or "").split())[:200]
                 for r in reversed(prev)]
        parts.append("【前文摘要】\n" + "\n".join(lines))
    else:
        parts.append("【前文摘要】(本章为第一章)")
    parts.append("【本章正文节选】\n" + " ".join(text.split())[:2000])
    parts.append(f"本项目叙事人称: {pov_rule(get_novel_pov(ep['drama_id']))}")
    parts.append("请为本章起一个简短、有钩子感的章节名:不超过 12 个汉字,不带「第N集」前缀,"
                 "标题里的称谓必须符合上述叙事人称。")
    parts.append("只输出章节名本身(一行纯文本,不要引号、书名号、前缀和任何解释)。")
    raw = runner.run_agent("novel_writer", "\n".join(parts), config_id=config_id)
    name = _clean_chapter_name(raw)
    if not name:
        raise RuntimeError("AI 未返回有效章节名,请重试")
    _apply_chapter_title(ep, name)
    return name, "ai"

# 写作红线(对齐原版 101759d):1 项目设定 / 2 总纲 / 3 世界观 / 4 故事合约 /
# 5 角色设定 / 7 章节规划 全部完成才能生成(6 卷战略是节拍层,保持可选)
NOVEL_REQUIRED_STEPS = [1, 2, 3, 4, 5, 7]
STEP_NAMES = {1: "项目设定", 2: "总纲", 3: "世界观", 4: "故事合约",
              5: "角色设定", 6: "卷战略", 7: "章节规划"}


def check_novel_redlines(drama_id: int) -> list[int]:
    """返回未完成的步骤号列表;空列表=设定齐全。"""
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    if not d:
        return NOVEL_REQUIRED_STEPS
    meta = db.jload(d["novel_meta"], {}) or {}
    # 简介 / 题材 由项目设置写进 dramas.metadata,不在 novel_meta 里
    proj = db.jload(d["metadata"], {}) or {}
    world = meta.get("world") or {}
    contract = meta.get("contract") or {}
    missing: list[int] = []
    # 1 项目设定:标题 + 简介
    if not (d["title"] or "").strip() or not (proj.get("intro") or "").strip():
        missing.append(1)
    # 2 总纲
    if not (d["novel_outline"] or "").strip():
        missing.append(2)
    # 3 世界观:era + location
    if not (str(world.get("era") or "").strip() and str(world.get("location") or "").strip()):
        missing.append(3)
    # 4 故事合约:pov + rules(非空)+ tones(非空)
    rules, tones = contract.get("rules") or [], contract.get("tones") or []
    if not (contract.get("pov") and any(str(r or "").strip() for r in rules) and len(tones) > 0):
        missing.append(4)
    # 5 角色设定
    if not db.q1("SELECT id FROM characters WHERE drama_id=? LIMIT 1", (drama_id,)):
        missing.append(5)
    # 7 章节规划
    if not (len(db.jload(d["novel_chapters"], []) or []) > 0):
        missing.append(7)
    return missing


def assert_novel_ready(drama_id: int) -> None:
    """写作红线守卫:未补齐设定时拒绝生成,提示缺哪几步。

    消息压缩到 40 字内(对齐原版 0114f24):只报步骤号,名称由 UI 侧翻译补全,
    避免长文本在错误提示里被截断。
    """
    missing = check_novel_redlines(drama_id)
    if missing:
        raise RuntimeError(f"小说设定未完成，请先补齐步骤 {'、'.join(str(s) for s in missing)}")


def _enforce_novel_gate(drama_id: int) -> None:
    """设定未齐时禁止写小说(非小说项目不受这条红线约束)。

    UI 侧虽然会把「AI 生成小说 / 批量写」置灰,但按钮禁用挡不住其它入口
    (键盘、批量面板、程序化调用),所以在 pipeline 层再拦一道。
    """
    d = db.q1("SELECT work_type FROM dramas WHERE id=?", (drama_id,))
    if not d or (d["work_type"] or "") != "novel":
        return
    assert_novel_ready(drama_id)


def missing_steps_text(drama_id: int) -> str:
    missing = check_novel_redlines(drama_id)
    if not missing:
        return ""
    return "、".join(f"{s}({STEP_NAMES.get(s, '')})" for s in missing)


SECTION_SPEC: dict[str, dict] = {
    "outline": {
        "field": "novel_outline", "name": "总纲", "fmt": "plain",
        "spec": ("800-1500 字全文总纲:一句话主题、核心冲突、主角目标与阻力、"
                 "三幕递进、结局走向。直接输出正文,不要 JSON、不要标题行、不要解释。"),
    },
    "world": {
        "field": "novel_world", "name": "世界观", "fmt": "json",
        "spec": ('JSON:{"text":"800-1500 字世界观全文","structured":{"era":"时代背景",'
                 '"location":"主要地点","power_system":"力量/能力体系",'
                 '"factions":[{"name":"势力名","desc":"一句话"}],"note":"补充"}}\n'
                 "text 是可直接阅读的全文;structured 是给写作红线门控用的结构化字段,两者都要填。"),
    },
    "contract": {
        "field": "novel_contract", "name": "故事合约", "fmt": "json",
        "spec": ('JSON:{"text":"600-1200 字故事合约全文","structured":{"pov":"first|second|'
                 'third_limited|third_omni","tones":["基调1","基调2"],'
                 '"rules":["硬约束1","硬约束2"],"word_range":[1800,2600],"note":"补充"}}\n'
                 "pov 只能取 first/second/third_limited/third_omni 之一;tones 与 rules 都不能是空数组。"),
    },
    "volume": {
        "field": "novel_volume", "name": "分卷战略", "fmt": "json",
        "spec": ('JSON:{"text":"分卷说明(markdown,可为空)","chapters":['
                 '{"title":"卷名","range":"1-30","goal":"本卷目标",'
                 '"key_events":["关键事件"],"cliffhanger":"卷末钩子"}]}'),
    },
}


def draft_prompt(drama_id: int, key: str) -> str:
    """构造起草提示词(与 persist_draft 配对,便于流式边收边显示)。"""
    spec = SECTION_SPEC.get(key)
    if not spec:
        raise RuntimeError(f"未知板块:{key}")
    ctx = _novel_settings_ctx(drama_id)
    d = db.q1("SELECT total_episodes, novel_chapters FROM dramas WHERE id=?", (drama_id,))
    chapters = db.jload(d["novel_chapters"], []) or []
    intended = len(chapters) or int(d["total_episodes"] or 0)
    return f"""请为下面这本书起草「{spec['name']}」。

【项目上下文】
{ctx}

计划章数:{intended or '未定'}

【输出格式】
{spec['spec']}

只输出这一份内容本身,不要任何前后说明。"""


# 模型有时把「我要怎么回答」这类元思考写进 content 通道,直接落库会变成一堆任务复述。
# 这些开头是特征词 —— 命中即判定为「没真出稿」,触发一次更严格的补发。
META_TALK = re.compile(
    r"^(我们需要|我需要|用户(要求|说|希望)|需要(直接|只|确保|先)|先(回答|分析|梳理)|"
    r"根据(用户|要求|输出格式)|输出格式(是|为)|只需输出|本次(只|要)|"
    r"(Let me|I need|We need|The user))")
META_TALK_ANY = re.compile(
    r"(只需要输出|请只输出|输出格式|user.*request|需要调用工具|必须先调用工具)")


def looks_like_meta_talk(text: str) -> bool:
    """判断内容是不是「在讲怎么回答」而不是「答案本身」。"""
    t = (text or "").strip()
    if not t:
        return True
    if len(t) < 80 and (META_TALK.match(t) or META_TALK_ANY.search(t)):
        return True
    if META_TALK.match(t):
        return True
    return False


def persist_draft(drama_id: int, key: str, raw: str) -> dict:
    """解析并落库一次起草结果;返回 {key, field, text, extra}。"""
    spec = SECTION_SPEC.get(key)
    if not spec:
        raise RuntimeError(f"未知板块:{key}")
    raw = _strip_tool_calls(raw or "").strip()
    if not raw:
        raise RuntimeError(f"{spec['name']}起草返回空内容")
    text, structured = _parse_draft(raw, spec)
    if not text:
        raise RuntimeError(f"{spec['name']}起草结果无法解析(原始输出前 120 字:{raw[:120]})")
    if looks_like_meta_talk(text):
        raise RuntimeError(f"{spec['name']}这次只返回了过程说明,没有实际内容(前 80 字:{text[:80]})")
    if key == "volume" and not structured:      # 分卷战略必须要卷/章结构,纯散文不算数
        raise RuntimeError(f"{spec['name']}没有返回分卷结构(前 80 字:{text[:80]})")
    ts = db.now()
    extra = ""
    if key == "volume" and structured:
        payload = [structured] if isinstance(structured, list) else (structured.get("chapters") or [])
        if payload:
            db.ex("UPDATE dramas SET novel_chapters=?, updated_at=? WHERE id=?",
                  (json.dumps(payload, ensure_ascii=False), ts, drama_id))
            extra = f",已重排 {len(payload)} 章计划"
    db.ex(f"UPDATE dramas SET {spec['field']}=?, updated_at=? WHERE id=?",
          (text, ts, drama_id))
    if isinstance(structured, dict) and key in ("world", "contract"):
        row = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
        meta = db.jload(row["novel_meta"], {}) if row else {}
        meta[key] = structured
        db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
              (json.dumps(meta, ensure_ascii=False), ts, drama_id))
        extra = ",已写入结构化字段(写作门控会读)"
    return {"key": key, "field": spec["field"], "text": text, "extra": extra}


def draft_section(drama_id: int, key: str, config_id: int | None = None) -> dict:
    """一次性起草并落库(非流式路径;UI 走 draft_prompt + persist_draft 以便流式显示)。

    与参考项目的差别:那边的 novel_planner 是带工具的 Mastra Agent,提示词写
    「完成后调用 save_novel_settings 保存」,工具会真的写库;本仓 runner 是单次调用、
    没有工具,照抄这句会让模型返回工具调用文本,什么都不会发生(实测总纲起草返回的就是它)。
    所以这里把两件事自己做掉:上下文**直接内联**进提示词(替代 read_novel_context),
    模型**直接返回内容**由本函数写库(替代 save_novel_settings)。
    """
    raw = runner.run_agent("novel_planner", draft_prompt(drama_id, key),
                           temperature=0.6, config_id=config_id,
                           system=_draft_system(SECTION_SPEC[key]["name"]))
    return persist_draft(drama_id, key, raw)


def _parse_draft(raw: str, spec: dict) -> tuple[str, object]:
    """按板块格式解析模型输出 → (可直接阅读的全文, 结构化部分)。"""
    if spec["fmt"] == "plain":
        return raw.strip(), None
    data = runner.extract_json(raw)
    if isinstance(data, dict):
        text = str(data.get("text") or "").strip()
        structured = data.get("structured")
        if structured is None:
            structured = {k: v for k, v in data.items() if k != "text"} or None
        return (text or json.dumps(data, ensure_ascii=False)), structured
    if isinstance(data, list):                       # volume 直接给数组
        lines = [f"### {c.get('title') or ''}(第 {c.get('range') or ''}章)" for c in data
                 if isinstance(c, dict)]
        return ("\n".join(lines) if lines else ""), data
    return raw.strip(), None

TOOL_CALL_RE = re.compile(r"<​?tool_call>.*?(?:</​?tool_call>|$)", re.S)


def _strip_tool_calls(raw: str) -> str:
    """剥掉模型把工具调用当文本吐出来的片段(兜底;真正的修法是换无工具系统提示)。"""
    cleaned = TOOL_CALL_RE.sub("", raw).strip()
    if cleaned and cleaned != raw.strip():
        return cleaned
    if "tool_call" in raw:
        # 修:原模式 [^"\] 的 \] 是转义符不闭合字符集,整个类"未闭合",
        # 模型输出含 tool_call 字样时必崩。正确写法:[^"\\](非引号非反斜杠) | \\. (转义对)
        m = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
        if m and len(m.group(1)) > 40:
            try:
                return m.group(1).encode().decode("unicode_escape")
            except Exception:  # noqa: BLE001
                return m.group(1)
    return raw.strip()


def _draft_system(section_name: str) -> str:
    """起草用的**无工具**系统提示词。

    不用 workspace/prompts/novel_planner.*.md:那套提示词假设 Agent 拥有
    read_novel_context / save_novel_settings 等工具,并明确要求「只输出工具调用,
    不要输出规划文本」。本仓 runner 是单次调用、没有工具,照用只会拿到一串
    tool_call 文本(实测「总纲」起草返回的就是这个)。
    """
    return (
        "你是资深网文主编,负责长篇的开书规划。\n\n"
        "本次只起草一个板块,并**直接输出内容本身**。\n"
        "你没有工具,也**绝不要**输出 tool_call 之类的东西;不要复述任务要求,不要解释。\n\n"
        "硬约束:\n"
        "- 内容必须与用户消息给出的题材/简介/文风/总纲一致,不凭空引入无关设定\n"
        "- 章节名、人物名、专有名词要具体可执行,不写「若干」「一些」这类空话\n"
        f"- 只输出「{section_name}」这一块的内容"
    )



# ── 批量建集(对齐原版 POST /episodes/bulk) ──
BULK_MAX = 999
RESOLUTIONS = ("480p", "720p", "1080p")


def bulk_create_episodes(drama_id: int, titles: list[str] | None = None, count: int | None = None,
                         target_words: int | None = None, resolution: str = "720p") -> dict:
    """一次插入批量建集(999 章量级下逐个建集会上千次串行请求)。

    titles 优先(按清单顺序),缺名补「第N集」;count 缺省取 len(titles);
    start_num = 已有最大集号 + 1。返回 {created, start_number, total, episodes}。
    """
    if not (1 <= int(count or len(titles or [])) <= BULK_MAX):
        raise RuntimeError(f"集数需在 1-{BULK_MAX} 之间")
    resolution = resolution if resolution in RESOLUTIONS else "720p"
    n = int(count if count is not None else len(titles or []))
    names = list(titles or [])
    start = (db.q1("SELECT MAX(episode_number) m FROM episodes WHERE drama_id=?", (drama_id,))["m"] or 0) + 1
    ts = db.now()
    words = int(target_words) if target_words and int(target_words) > 0 else None
    created = []
    for i in range(n):
        num = start + i
        title = (names[i].strip() if i < len(names) and names[i] else "") or f"第{num}集"
        eid = db.ex("""INSERT INTO episodes(drama_id,episode_number,title,status,resolution,target_words,created_at,updated_at)
                      VALUES(?,?,?,'pending',?,?,?,?)""",
                    (drama_id, num, title, resolution, words, ts, ts))
        created.append({"id": eid, "episode_number": num, "title": title})
    total = db.q1("SELECT COUNT(*) c FROM episodes WHERE drama_id=?", (drama_id,))["c"]
    return {"created": len(created), "start_number": start, "total": total, "episodes": created}


def check_prev_chapter(drama_id: int, episode_number: int) -> None:
    """续写红线(对齐原版 48f36da):前章无正文时拒绝续写。

    第 N 章开写前要读第 N-1 章结尾,前章是空的就会产出脱离前文的垃圾章节。
    第 1 章放行。
    """
    if int(episode_number) <= 1:
        return
    prev = db.q1("""SELECT episode_number, content FROM episodes
                    WHERE drama_id=? AND episode_number<?
                    ORDER BY episode_number DESC LIMIT 1""", (drama_id, episode_number))
    if prev and not (prev["content"] or "").strip():
        raise RuntimeError(f"上一章(第 {prev['episode_number']} 集)还没有正文,不能续写")


def batch_write_chapters(drama_id: int, episode_ids: list[int], force: bool = False,
                         config_id: int | None = None, lang: str | None = None,
                         on_progress=None, model: str | None = None) -> dict:
    """批量写章(**强制串行**,顺序按章节号升序,防标题写进A章正文写进B章)。

    对齐原版 48f36da:并发度硬编码为 1 —— 第 N 章开写前要读第 N-1 章结尾 +
    事实台账 + 未回收伏笔 + 卷段摘要,并行会让后章取不到前文、把同一情节整章重写。
    另有:默认已有正文的章节整批拒绝(force=True 才放行);续写红线(前章无正文拒写)。
    """
    _enforce_novel_gate(drama_id)
    rows = [r for r in (db.q1(f"SELECT id, episode_number, title, content FROM episodes WHERE id=?", (i,))
                        for i in episode_ids)]
    rows = [r for r in rows if r]
    if not rows:
        return {"total": 0, "ok": 0, "failed": 0}
    # 按章节号升序(调用方乱序也保证先写第 1 章)
    rows.sort(key=lambda r: r["episode_number"])
    # 续写红线:整批第一集的前一章必须有正文
    check_prev_chapter(drama_id, rows[0]["episode_number"])
    if not force:
        dup = [r["episode_number"] for r in rows if len((r["content"] or "").strip()) >= 200]
        if dup:
            raise RuntimeError(
                f"第 {'、'.join(map(str, dup))} 章已有正文,已跳过。重写请在批量面板点「重写已完成章节」。")
    ok = failed = 0
    for r in rows:
        try:
            # 生成前逐章再校验(双保险):前章失败则后续章自动被拦停,不接力产出垃圾
            check_prev_chapter(drama_id, r["episode_number"])
            write_chapter_with_review(r["id"], config_id=config_id, lang=lang)
            ok += 1
        except Exception:  # noqa: BLE001
            failed += 1
        # 状态台账:每章写完后更新「世界状态」事实层(提取 → 合并 → Jev 门控)。
        # 失败只记不抛 —— 台账是增强项,绝不阻断批量写作主流程。
        try:
            from . import state_ledger
            state_ledger.update_state_ledger(drama_id, r["id"], config_id=config_id, model=model)
        except Exception:  # noqa: BLE001
            pass
        if on_progress:
            on_progress(ok + failed, len(rows), r["episode_number"])
    return {"total": len(rows), "ok": ok, "failed": failed}


def update_state_ledger(episode_id: int, config_id: int | None = None,
                        model: str | None = None) -> dict | None:
    """手动重跑单章台账(修复/补历史用);对应参考项目 POST /novel/update-state-ledger。

    config_id / model 可选:跟随指定文本模型提取(缺省回退集锁定 / 全局默认)。
    """
    ep = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("章节不存在")
    from . import state_ledger
    out = state_ledger.update_state_ledger(ep["drama_id"], episode_id,
                                           config_id=config_id, model=model)
    if out is None:
        raise RuntimeError("台账提取失败(正文过短或模型输出异常)")
    return out


# ── 伏笔台账(对齐原版未提交批次: LCS 去重 + 封顶 + 可交互 toggle) ──
FORESHADOW_DEDUP_MIN_LCS = 5
OPEN_LEDGER_CAP = 40
LEDGER_INJECT_LIMIT = 8


def _normalize_foreshadow(s) -> str:
    """伏笔归一:去空白与中文标点,便于比较语义重合度。"""
    import re as _re
    return _re.sub(r"[\s　，。、；：？！「」『』\"'‘’（）()·…—\-]", "", str(s or ""))


def _lcs_len(a: str, b: str) -> int:
    """最长公共子串长度(DP)。伏笔多为「人物+行为」的改写句,bigram 区分度差,
    但核心短语会原样保留(如「苏晓晴对李安全变化的」稳定命中 10 字)。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def dedup_ledger(items: list[dict]) -> list[dict]:
    """判同规则:完全相同 || 互相包含 || LCS >= 5。"""
    out: list[dict] = []
    for it in items:
        txt = _normalize_foreshadow(it.get("text"))
        if not txt:
            continue
        dup = False
        for o in out:
            ot = _normalize_foreshadow(o.get("text"))
            if not ot:
                continue
            if ot == txt or ot in txt or txt in ot or _lcs_len(ot, txt) >= FORESHADOW_DEDUP_MIN_LCS:
                dup = True
                break
        if not dup:
            out.append(it)
    return out


def cap_ledger(items: list[dict]) -> list[dict]:
    """未回收且非 stale 超 40 条时,把最老的标 stale(不删除,界面仍可查)。"""
    opens = [it for it in items if not it.get("closed") and not it.get("stale")]
    if len(opens) > OPEN_LEDGER_CAP:
        for it in opens[: len(opens) - OPEN_LEDGER_CAP]:
            it["stale"] = True
    return items


def backfill_ledger_chapters(drama_id: int, items: list[dict]) -> list[dict]:
    """给历史伏笔补 open_chapter:归一文本前 4 字在该章正文中首次命中即取,找不到留空不臆造。"""
    for it in items:
        if it.get("open_chapter"):
            continue
        key = _normalize_foreshadow(it.get("text"))[:4]
        if len(key) < 4:
            continue
        for r in db.q("SELECT episode_number, content FROM episodes WHERE drama_id=? ORDER BY episode_number",
                      (drama_id,)):
            if key in _normalize_foreshadow(r["content"]):
                it["open_chapter"] = r["episode_number"]
                break
    return items


def get_ledger(drama_id: int) -> dict:
    """伏笔台账:未回收在前。index 为原始数组下标(toggle 依赖它定位)。"""
    d = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
    meta = db.jload(d["novel_meta"], {}) if d else {}
    raw = meta.get("ledger") or []
    items = []
    for i, it in enumerate(raw):
        if not (it or {}).get("text"):
            continue
        items.append({**it, "index": i})
    items.sort(key=lambda x: bool(x.get("closed")))
    return {"items": items, "open": sum(1 for i in items if not i.get("closed"))}


def toggle_ledger(drama_id: int, index: int, chapter: int | None = None) -> dict:
    """切换某条伏笔的回收状态(乐观更新的服务端半边)。"""
    d = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
    meta = db.jload(d["novel_meta"], {}) if d else {}
    ledger = meta.get("ledger") or []
    if not (0 <= int(index) < len(ledger)):
        raise RuntimeError("伏笔下标越界")
    item = ledger[index]
    item["closed"] = not item.get("closed")
    if item["closed"]:
        item["closed_chapter"] = chapter
        item.pop("stale", None)
    else:
        item.pop("closed_chapter", None)
    meta["ledger"] = cap_ledger(ledger)
    db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
    return get_ledger(drama_id)


def inject_recent_ledger(items: list[dict], limit: int = LEDGER_INJECT_LIMIT) -> list[dict]:
    """写作时注入的伏笔:按埋设章号倒序取最近 N 条(早期伏笔不再霸占前排)。"""
    opens = [it for it in items if not it.get("closed") and (it.get("text") or "").strip()]
    indexed = list(enumerate(opens))
    indexed.sort(key=lambda p: (-(p[1].get("open_chapter") or 0), -p[0]))
    return [it for _, it in indexed[:limit]]


# ── 审校摘要(对齐原版 GET /novel/review-summary) ──
def review_summary(drama_id: int) -> dict:
    """列出全书仍有审校问题的章节。"""
    items, total = [], 0
    for ep in db.q("SELECT * FROM episodes WHERE drama_id=? ORDER BY episode_number", (drama_id,)):
        rj = db.jload(ep["review_json"], {}) or {}
        issues = rj.get("issues") or []
        if not issues:
            continue
        def _txt(x):
            if isinstance(x, str):
                return x
            return str(x.get("description") or x.get("issue") or x)
        items.append({"episode_id": ep["id"], "episode_number": ep["episode_number"],
                      "title": ep["title"], "count": len(issues),
                      "issues": [_txt(x) for x in issues[:20]],
                      "reviewed_at": ep["updated_at"]})
        total += len(issues)
    return {"items": items, "total": len(items), "issues": total}


# ── 整章朗读(对齐原版 POST /novel/read-aloud) ──
def split_for_tts(text: str, limit: int = 600) -> list[str]:
    """按句切分(单句超限硬切),避免整章一次提交超长。"""
    import re as _re
    parts = _re.split(r"([^。！？!?…；;]+[。！？!?…；;]*\.?)", text or "")
    chunks, cur = [], ""
    for seg in parts:
        if not seg:
            continue
        while len(seg) > limit:                     # 超长单句硬切
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(seg[:limit])
            seg = seg[limit:]
        if len(cur) + len(seg) > limit:
            chunks.append(cur)
            cur = seg
        else:
            cur += seg
    if cur.strip():
        chunks.append(cur)
    return [c for c in chunks if c.strip()]


def read_aloud(episode_id: int, config_id: int | None = None) -> dict:
    """整章正文合成 MP3 供播放(MP3 帧自包含,顺序拼接可连续播放)。"""
    import uuid as _uuid
    from ..ai import tts_client
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("章节不存在")
    import re as _re
    text = _re.sub(r"^#\s+.*$", "", ep["content"] or "", count=1, flags=__import__("re").M)
    text = text.strip()
    if len(text) < 50:
        raise RuntimeError("本章正文太短,无法朗读")
    chunks = split_for_tts(text, 600)
    out_dir = config.STATIC_DIR / "narration" / "novel-read"
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, c in enumerate(chunks):
        p = tts_client.synthesize(c, config_id=config_id)
        parts.append(p.read_bytes())
        p.unlink(missing_ok=True)
    out = out_dir / f"ep-{episode_id}-{_uuid.uuid4().hex[:8]}.mp3"
    out.write_bytes(b"".join(parts))
    return {"audio_url": config.path_to_media_url(out), "chunks": len(chunks)}
