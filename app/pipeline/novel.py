# -*- coding: utf-8 -*-
"""小说线:策划(novel_planner)→ 逐章生成(novel_writer)→ 六维审校(novel_reviewer)→ 改稿(novel_editor)。"""
from __future__ import annotations

import json
import re

from ..agents import runner
from ..ai import text_client   # 分卷分批直接调 chat(非流式路径)
from ..core.i18n import tr       # 分批阶段提示文案(漏导入会让整批 NameError)
from ..ai import registry
from ..core import config, db

from . import character_spec
from . import script_quality


# 写法风格预设(逐字对齐原版 episode.vue 的 NOVEL_STYLES):选中值全文写入 dramas.novel_style
# 清单本体放在 core.db.NOVEL_STYLE_PRESETS —— 与 style_presets 表里 novel 类的种子
# 同源,避免「内置常量」和「库内种子」各写一份、改一处忘一处。
NOVEL_STYLES = [(name, prompt) for name, _value, _order, _wt, prompt, _desc
                in db.NOVEL_STYLE_PRESETS]
NOVEL_STYLE_CUSTOM = "__custom__"
DEFAULT_NOVEL_STYLE = NOVEL_STYLES[0][1]


def novel_style_options() -> list[tuple[str, str]]:
    """(显示名, prompt 全文) —— 内置 6 套 + 库内 style_type='novel' 的行。

    按 prompt 全文去重;value 一律是 prompt 全文(dramas.novel_style 存的就是全文)。
    """
    return db.style_options(db.STYLE_TYPE_NOVEL)


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
    config_id = config_id or plan_config_id()
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


def outline_to_script(outline: str, episode_id: int,
                      *, config_id: int | None = None) -> str:
    r"""故事梗概 → 格式化剧本(可直接进 `comic.split_panels`)。

    给 `comic_outline_writer` Agent 提供 100-1000 字的梗概,扩成 600-1500 字
    的格式化剧本:4-8 个场景,每个带 `## S\d+\|内外景·地点\|时间` 头。
    **失败不落库**(原内容保持),只抛 RuntimeError。

    Args:
        outline:故事梗概(100-1000 字);太短会拒,太长会截。
        episode_id:剧集 id,用于取项目元信息(标题/语言/风格)与落库。
        config_id:文本模型 config_id;None 时回退到 prose_config_id()。

    Returns:
        落库后的剧本正文。

    Raises:
        RuntimeError:空梗概 / 空剧本 / 落库失败
    """
    outline = (outline or "").strip()
    if not outline:
        raise RuntimeError("请先输入故事梗概")
    if len(outline) < 30:
        raise RuntimeError("梗概太短(需 ≥30 字),请描述主要人物 / 事件 / 走向")
    config_id = config_id or prose_config_id()
    ep = db.q1("SELECT drama_id, episode_number FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("剧集不存在")
    drama = db.q1("SELECT title, language, novel_style FROM dramas WHERE id=?",
                  (int(ep["drama_id"]),))
    title = (drama or {}).get("title") or "未命名项目"
    style = (drama or {}).get("novel_style") or ""
    content_lang = (drama or {}).get("language") or None
    # 三段式 prompt:任务 + 上下文(标题/风格) + 输入(梗概)
    prompt = (
        f"项目: {title}\n"
        f"本集号: 第 {ep['episode_number']} 集\n"
        + (f"风格要求: {style}\n" if style else "")
        + f"\n故事梗概(用户输入,可能口语化):\n{outline[:2000]}\n\n"
        + "请把梗概扩写成 600-1500 字的格式化剧本,要求:\n"
        + "1. 输出 JSON:{\"script\": \"## S01|...\\n...\\n## S02|...\\n...\"}\n"
        + "2. 共 4-8 个场景,每个 ## S\\d+\\|内外景·地点\\|时间 头\n"
        + "3. 每个场景 1-3 句动作/对白,信息密度高,别注水\n"
        + "4. 严格遵循梗概的人物与主线,不要自创新角色或反转\n"
        + "5. 输出**只有 JSON**,无 <think> / 无解释 / 无 markdown 围栏"
    )
    data = runner.run_agent_json(
        "comic_outline_writer", prompt,
        config_id=config_id,
        lang=content_lang,
    )
    if not isinstance(data, dict):
        raise RuntimeError(f"梗概扩写失败:模型返回非 JSON({type(data).__name__})")
    script = (data.get("script") or "").strip()
    if not script:
        raise RuntimeError("梗概扩写失败:模型未返回 script 字段")
    # 校验剧本格式:至少 1 个 ## S 头
    if not re.search(r"^##\s*S\d+\s*\|", script, re.MULTILINE):
        raise RuntimeError("梗概扩写失败:剧本不含 ## S\\d+\\| 格式头")
    # 可拍性质量门:满篇画外音 / 单人独角戏的剧本打回重写,仍不合格不落库
    def _repair(prompt: str) -> str:
        d = runner.run_agent_json("comic_outline_writer", prompt,
                                  config_id=config_id, lang=content_lang)
        return (d.get("script") or "") if isinstance(d, dict) else ""

    script = script_quality.enforce(script, _repair)
    db.ex(
        "UPDATE episodes SET script_content=?, content=?, updated_at=? WHERE id=?",
        (script, script, db.now(), episode_id),
    )
    return script


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


# ── 规划 / 正文 双模型(实测见 git log 的提交说明)────────────────────────
# 规划侧(deepseek-v4-pro):结构化输出规整,分卷/合约的字段完整度高。
# 正文侧(minimax-M3):篇幅稳定,连续三章无衰减;deepseek 写正文逐章掉一半。
_PLAN_CFG_KEY = "yihao.novel.plan_cfg"
_PROSE_CFG_KEY = "yihao.novel.prose_cfg"


def plan_config_id() -> int | None:
    """规划用文本服务配置 id(未单独设置时回退全局默认)。

    ⚠️ `registry.default_config("text", None)` 在**没有可用文本配置**时返回
    None(不是空 dict)—— 直接 `.get("id")` 会 AttributeError,设置页初始化
    直接崩,用户看到的不是「请先配置文本服务」而是 Python 栈。
    参照 agents/runner.py 的写法:default_config(...) or {}。
    """
    v = db.get_setting(_PLAN_CFG_KEY, "")
    if v:
        try:
            return int(v)
        except (TypeError, ValueError):
            pass
    cfg = registry.default_config("text", None) or {}
    return cfg.get("id")


def prose_config_id() -> int | None:
    """正文写作用文本服务配置 id(未单独设置时回退全局默认)。

    同 plan_config_id:default_config 可能返回 None,必须兜底。
    """
    v = db.get_setting(_PROSE_CFG_KEY, "")
    if v:
        try:
            return int(v)
        except (TypeError, ValueError):
            pass
    cfg = registry.default_config("text", None) or {}
    return cfg.get("id")


def _plan_scale(drama_id: int, chapter_count: int | None, word_count: int | None) -> tuple[int, int]:
    nm = db.jload((db.q1("SELECT novel_meta,total_episodes FROM dramas WHERE id=?", (drama_id,))
                   or {"novel_meta": None, "total_episodes": None})["novel_meta"], {}) or {}
    # 章数单一来源 = dramas.total_episodes(「项目设置 → 集数」与「小说设定 → 全书章数」共用);
    # novel_meta.chapter_count 为历史遗留,不再参与取值,避免两处显示不一致
    # 章数取 novel_meta.chapter_count(**不再用 total_episodes**):
    # 那个字段同时表示「集数」,而 generate_chapters_batched 跑完会把它写成
    # 实际生成的章数 —— 用户在输入框设的 999 于是被自己的生成结果覆盖,
    # 下次打开对话框只剩 60(实测)。
    n = int(chapter_count or nm.get("chapter_count")
            or db.q1("SELECT total_episodes FROM dramas WHERE id=?",
                     (drama_id,))["total_episodes"] or 60)
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
# 章节计划的「升级预算」。实测(deepseek-v4-pro,40 章/批):默认 8192 全部
# 被 reasoning 吃掉,finish_reason=length、content=0 字,整批报废;同样提示词
# 给 32768 则一次返回 40 章(约 7k 字 JSON)。先按配置值跑,空了再升级 ——
# 一上来就塞 32768 会让输出上限较低的模型直接 400。
PLAN_RETRY_TOKENS = 32768
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


def _range_of(vol: dict) -> tuple[int, int]:
    """卷的 range("1-120"/"第1-120章")→ (起, 止)。解析不出返回 (0, 0)。"""
    nums = re.findall(r"\d+", str(vol.get("range") or ""))
    return (int(nums[0]), int(nums[1])) if len(nums) >= 2 else (0, 0)


def find_volume_of_chapter(drama_id: int, chapter_no: int) -> dict | None:
    """章号 → 所属卷。找不到返回 None。"""
    for v in load_volume_chapters(drama_id):
        a, b = _range_of(v)
        if a and a <= chapter_no <= b:
            return v
    return None


def volume_hint_for(drama_id: int, start: int) -> str:
    """这一批(从第 start 章起)所在卷的定位描述,拼进批次提示词。

    不给这段,模型只知道"服从分卷战略"却不知道眼前这批属于哪一卷,
    章节内容容易跑到别的卷的叙事区间里。
    """
    v = find_volume_of_chapter(drama_id, start)
    if not v:
        return ""
    a, b = _range_of(v)
    bits = [f"本批(第 {start} 章起)属于【{v.get('title') or ''}】(第 {a}-{b} 章)"]
    if v.get("goal"):
        bits.append(f"本卷目标:{v['goal']}")
    ev = [str(x).strip() for x in (v.get("key_events") or []) if str(x).strip()]
    if ev:
        bits.append("本卷关键事件:" + " / ".join(ev))
    if v.get("cliffhanger"):
        bits.append(f"本卷末钩子:{v['cliffhanger']}")
    return "\n".join(bits)


def chapters_batch_prompt(drama_id: int, start: int, count: int, total: int,
                          word_count: int, prev_hint: str = "", next_hint: str = "") -> str:
    """构造某一章区间的计划提示词(长篇分批生成用)。"""
    ctx = _novel_settings_ctx(drama_id)
    hint = volume_hint_for(drama_id, start)
    base = CHAPTER_BATCH_PROMPT.format(
        start=start, end=start + count - 1, count=count, total=total,
        words=word_count, pov=pov_rule(get_novel_pov(drama_id)),
        prev=(prev_hint or "全书开篇(第 1 章)")[:200],
        next=(next_hint or "按总纲推进")[:200])
    return base + ("\n\n【本卷定位】\n" + hint if hint else "") + "\n\n" + ctx


def _extract_characters_for_volume(drama_id: int, chapters: list[dict],
                                  vol: dict, config_id: int | None = None) -> list[dict]:
    """用某一卷的章节计划抽取该卷出场的主要角色,再**合并**进已有角色表。

    合并而不是覆盖:按卷滚动生成时前几卷角色已落库,重做一卷不该清掉它们。
    按 name 去重,同名以新结果为准(允许补全细节)。
    """
    if not chapters:
        return []
    a, b = _range_of(vol)
    title = vol.get("title") or ""
    ctx = _novel_settings_ctx(drama_id)
    plan_txt = chapters_to_text(chapters)[:6000]
    parts = [ctx, f"【当前只处理第 {a}-{b} 章(卷名:{title})】"]
    if vol.get("goal"):
        parts.append(f"本卷目标:{vol['goal']}")
    if vol.get("key_events"):
        parts.append("本卷关键事件:" + " / ".join(
            str(x) for x in vol["key_events"]))
    parts.append("本卷章节计划:\n" + plan_txt)
    parts.append(CHARACTER_PROMPT)
    parts.append("只列**本卷出场**的角色;前几卷已建立的可只保留姓名,不重复描述。")
    raw = runner.run_agent("novel_planner", "\n\n".join(parts),
                           temperature=0.5, config_id=config_id)
    chars = _clean_characters((runner.extract_json(raw) or {}).get("characters"))
    if not chars:
        return []
    meta = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?",
                          (drama_id,))["novel_meta"], {}) or {}
    by_name = {str(c.get("name") or "").strip(): c
               for c in (meta.get("main_characters") or []) if isinstance(c, dict)}
    for c in chars:
        by_name[str(c.get("name") or "").strip()] = c
    merged = list(by_name.values())
    meta["main_characters"] = merged
    db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
    _sync_characters(drama_id, merged)
    return chars


def _merge_chapters(drama_id: int, new_ch: list[dict]) -> int:
    """按章号把新章节并进库里已有的计划,返回合并后的总章数。

    **绝不能整表覆盖** —— 分卷生成是增量补充,用户很可能已经生成过前面几卷。
    实测踩过:按卷生成时直接 `UPDATE novel_chapters=<本卷结果>`,
    把已有的 60 章(第 1-60 章)整体抹掉,而那一卷只覆盖第 1-120 章,
    看着「生成了 120 章」实则把第 61 章以后的计划清空了。
    同章号以新结果为准(重做本卷时覆盖),其余保留。
    """
    row = db.q1("SELECT novel_chapters FROM dramas WHERE id=?", (drama_id,))
    old = db.jload(row["novel_chapters"], []) if row else []
    merged: dict[int, dict] = {}
    for c in (old or []):
        num = int(c.get("number") or 0)
        if num:
            merged[num] = c
    for c in new_ch or []:
        num = int(c.get("number") or 0)
        if num:
            merged[num] = c
    out = [merged[k] for k in sorted(merged)]
    db.ex("UPDATE dramas SET novel_chapters=?, updated_at=? WHERE id=?",
          (json.dumps(out, ensure_ascii=False), db.now(), drama_id))
    return len(out)


def generate_chapters_for_volume(drama_id: int, volume_no: int,
                                 word_count: int | None = None,
                                 config_id: int | None = None,
                                 progress=None, on_partial=None, on_stage=None,
                                 with_characters: bool = True) -> dict:
    """只生成**第 volume_no 卷**的章节计划(A 方案)。

    全书一次生成对 999 章这种体量不现实(20 分钟以上、中途看不到产出、
    质量不稳)。分卷已经把叙事切成若干段,按卷生成既快又能保证章节与
    分卷对齐 —— 每次约 120 章、3 分钟左右,不满意只重做这一卷。

    on_stage(文本) 在**每批开始前**回调一次,让界面能显示「正在生成第 N 批…」——
    实测一批要 82 秒(deepseek-v4-pro),这段时间里进度回调一次都不触发,
    没有它界面完全静止,用户看到的就是"点了没反应"。

    返回 {"count","word_count","chapters","start","end"}。
    """
    vols = load_volume_chapters(drama_id)
    if not vols:
        raise RuntimeError("还没有分卷战略,先在「分卷战略」页签生成")
    if not 1 <= volume_no <= len(vols):
        raise RuntimeError(f"卷号超出范围(共 {len(vols)} 卷)")
    vol = vols[volume_no - 1]
    a, b = _range_of(vol)
    if not a or not b:
        raise RuntimeError(f"第 {volume_no} 卷缺少章号范围({vol.get('range')!r})")
    total = _plan_scale(drama_id, None, None)[0]
    config_id = config_id or plan_config_id()
    n = b - a + 1
    all_ch: list[dict] = []
    total_batches = (n + CHAPTER_BATCH - 1) // CHAPTER_BATCH
    if on_stage:
        on_stage(tr("第 {no} 卷【{t}】第 {a}-{b} 章,共 {n} 章,分 {k} 批生成。\n"
                    "每批约 1 分钟,完成后会立即显示在下方。").format(
                        no=volume_no, t=vol.get("title") or "", a=a, b=b,
                        n=n, k=total_batches))
    for bi in range(total_batches):
        start = a + bi * CHAPTER_BATCH
        cnt = min(CHAPTER_BATCH, b - start + 1)
        if on_stage and bi:
            on_stage(tr("第 {bi}/{all} 批 · 第 {a}-{b} 章…").format(
                bi=bi + 1, all=total_batches, a=start, b=start + cnt - 1))
        prev_hint = ""
        if all_ch:
            last = all_ch[-1]
            prev_hint = f"第{last['number']}章《{last.get('title','')}》钩子:{last.get('cliffhanger','')}"
        raw = ""
        batch: list[dict] = []
        budgets = _plan_budgets(config_id)
        for attempt, budget in enumerate(budgets):
            try:
                raw = runner.run_agent(
                    "novel_planner",
                    chapters_batch_prompt(drama_id, start, cnt, total, word_count or 2500,
                                          prev_hint=prev_hint),
                    temperature=0.4, config_id=config_id, max_tokens=budget)
            except Exception as exc:  # noqa: BLE001
                if attempt == len(budgets) - 1:
                    raise
                print(f"[novel] 第 {start}-{start + cnt - 1} 章请求失败({exc}),"
                      f"升到 {budgets[attempt + 1]} 预算重试", flush=True)
                continue
            data = runner.extract_json(raw) or {}
            batch = _clean_chapter_list(data.get("chapters"), cnt)
            if batch:
                break
            print(f"[novel] 第 {start}-{start + cnt - 1} 章返回 {len(raw)} 字符"
                  f"(预算 {budget},解析 0 章),"
                  + (f"升到 {budgets[attempt + 1]} 重试" if attempt < len(budgets) - 1
                     else "放弃"), flush=True)
        if not batch:
            # 空批次直接报错:继续往下跑只会让用户等完才看到「什么都没有」。
            # 已产出的批次已经在下面逐批落库,不会丢。
            raise RuntimeError(f"第 {start}-{start + cnt - 1} 章生成失败"
                               f"(返回 {len(raw)} 字,疑似被截断)")
        all_ch.extend(batch)
        # 逐批落库(合并,不覆盖):三批跑几分钟,中途断网/超时已生成的批次不能丢
        _merge_chapters(drama_id, all_ch)
        if progress:
            progress(int(len(all_ch) * 100 / n), len(all_ch), n)
        if on_partial:
            on_partial(all_ch)
    all_ch.sort(key=lambda c: c["number"])
    if on_stage:
        on_stage(tr("正在抽取本卷主要角色…"))
    chars: list[dict] = []
    if with_characters:
        try:
            chars = _extract_characters_for_volume(
                drama_id, all_ch, vol, config_id)
        except Exception as exc:  # noqa: BLE001
            # 角色抽取失败不该让已生成的章节计划前功尽弃
            print(f"[novel] 第 {volume_no} 卷角色抽取失败({exc}),章节计划已保留", flush=True)
    return {"count": len(all_ch), "word_count": word_count or 2500,
            "chapters": all_ch, "start": a, "end": b, "characters": chars}


def generate_chapters_batched(drama_id: int, chapter_count: int | None = None,
                              word_count: int | None = None,
                              config_id: int | None = None,
                              progress=None, on_partial=None) -> dict:
    """分批生成整本书的逐章计划并落库。

    progress(percent, done, total)  —— 进度数字
    on_partial(已生成章节列表)      —— 每批产出后回调,用于把内容实时写进界面
    """
    n, words = _plan_scale(drama_id, chapter_count, word_count)
    config_id = config_id or plan_config_id()
    all_ch: list[dict] = []
    total_batches = (n + CHAPTER_BATCH - 1) // CHAPTER_BATCH
    for bi in range(total_batches):
        start = bi * CHAPTER_BATCH + 1
        cnt = min(CHAPTER_BATCH, n - start + 1)
        prev_hint = ""
        if all_ch:
            last = all_ch[-1]
            prev_hint = f"第{last['number']}章《{last.get('title','')}》钩子:{last.get('cliffhanger','')}"
        raw = ""
        batch: list[dict] = []
        budgets = _plan_budgets(config_id)
        for attempt, budget in enumerate(budgets):
            try:
                raw = runner.run_agent("novel_planner",
                                       chapters_batch_prompt(drama_id, start, cnt, n, words,
                                                             prev_hint=prev_hint),
                                       temperature=0.4, config_id=config_id,
                                       max_tokens=budget)
            except Exception as exc:  # noqa: BLE001
                if attempt == len(budgets) - 1:
                    raise
                print(f"[novel] 第 {start}-{start + cnt - 1} 章请求失败({exc}),"
                      f"升到 {budgets[attempt + 1]} 预算重试", flush=True)
                continue
            data = runner.extract_json(raw) or {}
            batch = _clean_chapter_list(data.get("chapters"), n)
            if batch:
                break
            print(f"[novel] 第 {start}-{start + cnt - 1} 章返回 {len(raw)} 字符"
                  f"(预算 {budget},解析 0 章),"
                  + (f"升到 {budgets[attempt + 1]} 重试" if attempt < len(budgets) - 1
                     else "放弃"), flush=True)
        if not batch:
            raise RuntimeError(f"第 {start}-{start + cnt - 1} 章生成失败"
                               f"(返回 {len(raw)} 字,疑似被截断)")
        all_ch += batch
        if progress:
            progress(int(len(all_ch) * 100 / n), len(all_ch), n)
        if on_partial:
            # 每批生成完就把已产出的章节文本抛给 UI 追加 —— 否则长篇分批
            # 全程编辑器空白,只能等 25 批跑完才一次性出现(实测「看不到过程」)。
            on_partial(all_ch)
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
    # 落库前的乱码闸门(章节计划也是模型产出,流式路径没有 text_client._guarded 兜底)
    _chapters_json = _gate_content(json.dumps(chapters, ensure_ascii=False), "章节计划")
    db.ex("UPDATE dramas SET novel_chapters=?, novel_meta=?, total_episodes=?, updated_at=? WHERE id=?",
          (_chapters_json, json.dumps(nm, ensure_ascii=False),
           n, db.now(), drama_id))
    return {"count": len(chapters), "word_count": words, "chapters": chapters}


def plan_chapters(drama_id: int, chapter_count: int | None = None,
                  word_count: int | None = None, config_id: int | None = None) -> dict:
    """一次性生成并落库逐章计划(非流式路径;UI 走 chapters_prompt + persist_chapters)。"""
    config_id = config_id or plan_config_id()
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

# 规格块由软件层统一注入(不再依赖某个语言变体的提示词文件)。小说策划这条
# 链路原先只有一句「要能直接转成文生图提示词」,实测产出 45~70 字,远低于
# extractor 要求的 150 字  同一个字段,两条链路两套标准,出图质量自然分层。
# 具体注入发生在 plan_characters() 里(按项目内容语言选中/英文规格块)。


def plan_characters(drama_id: int, config_id: int | None = None) -> dict:
    """AI 生成主要角色。章节计划缺失时先在后台补章节计划(依赖先行)。"""
    config_id = config_id or plan_config_id()
    d = db.q1("SELECT novel_chapters FROM dramas WHERE id=?", (drama_id,))
    chapters = db.jload(d["novel_chapters"], []) if d else []
    if not chapters:
        plan_chapters(drama_id, config_id=config_id)          # 章节计划是角色设计的前置
        d = db.q1("SELECT novel_chapters FROM dramas WHERE id=?", (drama_id,))
        chapters = db.jload(d["novel_chapters"], []) or []
    ctx = _novel_settings_ctx(drama_id)
    plan_txt = chapters_to_text(chapters)[:6000]
    # 规格块按内容语言注入(软件层单一来源,不再依赖提示词文件手工维护)
    lang = config.resolve_content_language(drama_id)
    raw = runner.run_agent("novel_planner",
                           f"{ctx}\n\n章节计划:\n{plan_txt}\n\n{CHARACTER_PROMPT}"
                           f"\n\n{character_spec.rules_for(lang)}",
                           temperature=0.5, config_id=config_id)
    chars = _clean_characters((runner.extract_json(raw) or {}).get("characters"))
    if not chars:
        raise RuntimeError("AI 未返回角色,请重试或检查文本模型配置")
    # 与 extractor 同一条软件层规格:不达标先定向补写,再进 novel_meta / characters。
    # 失败原样返回,不阻断策划流程。
    chars = character_spec.expand_many(chars, config_id=config_id, lang=lang)
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


def _configured_max_tokens(config_id: int | None) -> int | None:
    """读该模型配置里手填的 max_tokens;留空/非法值返回 None,交给调用方兜底。

    与 `ai/text_client._build_body` 同一优先级:配置值优先,程序兜底在后。
    这里单独读一次是因为 write_chapter 要用这个值决定**第一次**请求的预算,
    不能先发一个 8192 的短预算再靠重试顶上去。
    """
    if not config_id:
        return None
    row = db.q1("SELECT max_tokens FROM ai_service_configs WHERE id=?", (config_id,))
    if not row:
        return None
    try:
        return int(row["max_tokens"] or 0) or None
    except (TypeError, ValueError):
        return None


def _plan_budgets(config_id: int | None) -> list[int]:
    """章节计划每批的输出预算序列:先配置值(留空=8192),空了再升到 32768。

    不再一上来就硬传大值:输出上限低的供应商(reject max_tokens)会直接 400。
    详见 PLAN_RETRY_TOKENS 的实测记录。
    """
    first = _configured_max_tokens(config_id) or 8192
    return [first] if first >= PLAN_RETRY_TOKENS else [first, PLAN_RETRY_TOKENS]


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
    # 正文模型与规划模型分设:调用方没显式指定时走「正文模型」
    # (实测 minimax-M3 写正文篇幅稳定三章无衰减;deepseek 逐章掉一半)
    if config_id is None:
        config_id = prose_config_id()
    # 写作红线:小说项目设定未齐时,任何入口(按钮/批量/程序化)都写不了
    _enforce_novel_gate(ep["drama_id"])
    # 思考型模型(M3)行为有波动:偶发只输出标题一行,或思考吃满预算导致正文为空。
    # 给三次机会,但**第一次用配置里填的 max_tokens**,不是硬编码值 ——
    # 用户把 32768 调大就是想让第一次就够用,固定 8192 会白跑一次短预算。
    # 配置留空才退到 _chapter_budget 兜底,后两次才升到 32768。
    budgets = (_configured_max_tokens(config_id) or 32768, 32768, 32768)
    content = ""
    for budget in budgets:
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


def _gate_content(text: str, where: str) -> str:
    """AI 产出的正文落库前的乱码闸门(能还原就还原,还原不了抛错中止)。"""
    from ..core.encoding import ensure_text
    return ensure_text(_strip_think(text or ""), where=where)


def _save_with_title(episode_id: int, content: str) -> str:
    """保存正文;若首行是 `# 章节名`,顺带写回 episodes.title(对齐原版 save_episode_content.chapter_title)。

    落库前过一道乱码闸门:能还原就还原,还原不了**中止这次生成**。
    这是最后一道防线 —— 上游网关把 UTF-8 按 latin-1/GBK 解一遍就会产出
    ``æ□®e□³□`` 这种正文,一旦静默存下去,界面上看不出任何异常,用户只会
    反复重抽浪费配额,而且**已经落库的数据不会被自动修回来**。
    """
    import re as _re
    from ..core.encoding import MojibakeError, ensure_text
    text = _strip_think(content)
    try:
        text = ensure_text(text, where="章节正文")
    except MojibakeError:
        raise
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
    """写章 → 写后校验 → 六维审校 → JEV 门控 → 必要时带清单修复 → loop。

    C.1:内部走 LangGraph StateGraph(装了的话) 或 fallback cycle loop;
    与原版行为一致 — 真装 LangGraph 时自动启用真图,fail-safe fallback 保底。

    对齐原版(101759d + 未提交批次):
    - 写后校验:以 episodes.content 为准,`len < 200` 视为模型没真写入 →
      抛错让上层重试一次,避免"界面显示完成但章节空着,极难排查"。
    - 阶段标记:writing → reviewing → repairing → jev_gate 写进 sys_task.params.stage。
    """
    from ..agents.novel_review_flow import run_novel_review_loop
    config_id = config_id or prose_config_id()

    out = run_novel_review_loop(
        episode_id=episode_id,
        config_id=config_id,
        lang=lang,
        task_id=task_id,
        content=content,
        max_cycles=3,
    )
    # 兼容老 caller 返回形状(content/review/fixed):
    final = (out.get("final") or [None])[0]
    return {
        "content": final or content or "",
        "review": None,                      # StateGraph 内部跑过 caller 拿不到详情,如需可见再扩
        "fixed": out.get("decision") == "ok",
    }


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
    # comic_style 现在存的是 prompt 全文(也可能是存量的 preset value)→ 用 flex 解析
    return db.style_prompt_flex((d["comic_style"] or d["style"] or "3d") if d else "3d")


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
    config_id = config_id or prose_config_id()
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
    config_id = config_id or prose_config_id()
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep or not (ep["content"] or "").strip():
        raise RuntimeError("本章还没有正文")
    prompt = (f"修改指令: {instruction}\n"
              f"本项目叙事人称(必须保持不变): {pov_rule(get_novel_pov(ep['drama_id']))}"
              f"\n\n正文:\n{ep['content'][:15000]}")
    content = _gate_content(runner.run_agent("novel_editor", prompt, config_id=config_id), "改稿正文")
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
    raw = runner.run_agent("novel_writer", "\n".join(parts),
                           config_id=config_id or prose_config_id())
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
        "spec": ("完整全文总纲(内容充分即可,按需展开,不设字数上限):一句话主题、核心冲突、主角目标与阻力、"
                 "三幕递进、结局走向。直接输出正文,不要 JSON、不要标题行、不要解释。"),
    },
    "world": {
        "field": "novel_world", "name": "世界观", "fmt": "json",
        "spec": ('JSON:{"text":"完整世界观全文(内容充分即可,不设字数上限)","structured":{"era":"时代背景",'
                 '"location":"主要地点","power_system":"力量/能力体系",'
                 '"factions":[{"name":"势力名","desc":"一句话"}],"note":"补充"}}\n'
                 "text 是可直接阅读的全文;structured 是给写作红线门控用的结构化字段,两者都要填。"),
    },
    "contract": {
        "field": "novel_contract", "name": "故事合约", "fmt": "json",
        "spec": ('JSON:{"text":"完整故事合约全文(内容充分即可,不设字数上限)","structured":{"pov":"first|second|'
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


# 分卷分批阈值:计划章数超过它就改成「先出卷骨架、再逐卷展开」,
# 否则一次性输出会被 max_tokens 截断(实测 999 章 → 34 卷 ≈ 8800 字,
# 而默认 8192 tokens 只够约 6300 字,必然中途截断、JSON 括号都不闭合)。
VOLUME_BATCH_THRESHOLD = 60
VOLUME_CHAPTERS_PER_VOL = 30
# 单次调用的输出预算:骨架与每批细节都用它,远小于默认 8192,
# 但足够一批(默认 6 卷)的细节 —— 分批的意义就在这里。
# 输出预算一律**读模型配置表**(设置页「最大输出 token」),不写死。
#
# 写死过 4096/8192,踩了两种坑:
#   · 4096 对 34 卷骨架太小 → 模型思考完就吐空(返回 0 字符),表现为
#     "点了没反应、十分钟不出结果";
#   · 而用户在设置里把该服务配成了 384000 —— 写死值让配置形同虚设,
#     改设置不生效。
# 所以这里只保留**下限兜底**(配置留空时用),有配置一律听配置的。
VOLUME_BATCH_SIZE = 6


def volume_plan_size(drama_id: int) -> int:
    """该书的计划章数。**统一走 _plan_scale**,不要自己另算。

    此前这里另写了一套取值(读 novel_chapters 长度 / total_episodes),与
    _plan_scale 的规则不一致 —— 后者已改为读 novel_meta.chapter_count,而这里
    还在读 total_episodes,于是同一本书两处算出 999 与 60:分批以为只有 60 章
    (不超阈值直接 raise),界面却显示 999。
    """
    return _plan_scale(drama_id, None, None)[0]


def _volume_brief(drama_id: int, outline_chars: int = 300) -> str:
    """分卷骨架用的**精简**上下文:书名 + 简介 + 总纲开头。

    完整 _novel_settings_ctx() 有 3200+ 字符,推理型模型读完就没预算输出正文了
    (实测 48s 后返回 0 字符)。骨架只需要"分几个卷、各卷叫什么",
    总纲读个开头足够 —— 细节留到阶段二逐批展开时再给。
    """
    d = db.q1("SELECT title, novel_outline, metadata FROM dramas WHERE id=?", (drama_id,))
    if not d:
        return ""
    meta = db.jload(d["metadata"], {}) or {}
    parts = [f"书名:{d['title']}"]
    intro = (meta.get("intro") or "").strip()
    if intro:
        parts.append(f"简介:{intro[:150]}")
    outline = (d["novel_outline"] or "").strip()
    if outline:
        parts.append(f"总纲摘要:{outline[:outline_chars]}")
    return "\n".join(parts)


def draft_volume_in_batches(drama_id: int, config_id: int | None = None,
                            on_progress=None, on_stage=None) -> list[dict]:
    """分批起草分卷战略:骨架先行,再逐卷补细节,拼成完整的 chapters 数组。

    一次性出全书分卷在章数大时不可行(输出量随章数线性增长,必然撞 max_tokens)。
    这里拆成两阶段:
      1. **骨架**:只要 卷名 + 章号范围,输出极短,一次就能出完;
      2. **展开**:按批(每批 N 卷)补 goal / key_events / cliffhanger,
         骨架已定,模型每批只看得到自己的那几卷,不会跑偏、也不会重复。

    on_progress(done, total) 供 UI 显示进度;失败的单批不阻断整体,缺字段留空。
    """
    total_ch = volume_plan_size(drama_id)
    if total_ch <= VOLUME_BATCH_THRESHOLD:
        raise RuntimeError(f"章数({total_ch})未超过阈值,应走单次起草")
    config_id = config_id or plan_config_id()
    ctx = _novel_settings_ctx(drama_id)

    # ── 阶段 1:骨架 ──
    # 骨架只给**书名 + 总纲摘要**:完整 ctx 有 3200+ 字符,实测带上去后模型
    # 花 48s 思考、思考完预算耗尽返回**空**(0 字符)。骨架只需要"分几个卷、
    # 各卷叫什么",总纲读个开头就够。
    brief = _volume_brief(drama_id)
    skel_prompt = f"""请为下面这本书规划分卷骨架。

{brief}

全书共 {total_ch} 章。请**按故事的叙事结构**(幕、转折、情绪阶段、主角成长弧)
来决定分几卷,每一卷是一个完整的叙事单元,**不要机械地按固定章数均分**。
若内容体量确实只够写几十章,就按实际篇幅规划,并在 text 里写清实到多少章。

只输出 JSON,不要任何解释:
{{"text":"分卷说明(markdown:分几卷、每卷叙事定位、整体节奏)","chapters":[{{"title":"卷名","range":"起-止"}}]}}
chapters 的 range 必须**连续覆盖第 1 章到第 {total_ch} 章**,不重不漏。"""
    if on_stage:
        # 骨架这一步实测要 ~22s(deepseek-v4-pro 出 34 项 JSON),
        # 不发通知的话这段就是"点了没反应" —— 用户根本不知道在跑。
        on_stage(tr('正在规划分卷(按叙事结构决定卷数)…'))
    # 推理型模型偶尔返回空 content(<think> 吃满预算 / 网关抖动),重试一次;
    # 两次都空才报错,并把响应长度带出来 —— 否则排查时只看到"生成失败"无从下手。
    data, raw = None, ""
    for attempt in range(2):
        # 后台线程里的异常若不打印,界面只表现为"没反应",排查完全无从下手
        # (实测连续三轮分卷失败,控制台一行输出都没有)
        # **不传 max_tokens**:text_client 会自己读配置表(32768)。
        # 此前这里显式传 _max_tokens(config_id),而 GUI 路径 config_id=None
        # → 兜底 4096 → 覆盖了配置的大预算 → MiniMax-M3 思考完预算耗尽,
        # 返回 0 字符(实测连续两次)。显式传小值比不传更糟。
        raw = text_client.chat(skel_prompt, temperature=0.3,
                               json_mode=True, config_id=config_id)
        data = runner.extract_json(raw) or {}
        skel = [c for c in (data.get("chapters") or []) if isinstance(c, dict) and c.get("range")]
        if skel:
            break
        print(f"[novel] 分卷骨架第 {attempt + 1} 次返回 {len(raw or '')} 字符,重试", flush=True)
    if not skel:
        raise RuntimeError(
            f"分卷骨架生成失败(重试 2 次,末次响应 {len(raw or '')} 字符,"
            f"前 120 字:{raw[:120]!r})")

    if on_stage:
        on_stage(tr('卷骨架完成,共 {n} 卷,开始逐批补细节…').format(n=len(skel)))
    # ── 阶段 2:逐批展开 ──
    batch = VOLUME_BATCH_SIZE
    done = 0
    for i in range(0, len(skel), batch):
        group = skel[i:i + batch]
        listing = "\n".join(f"{n}. 卷名「{c.get('title')}」 覆盖第 {c.get('range')} 章"
                            for n, c in enumerate(group, i + 1))
        if on_stage:
            on_stage(tr('正在补第 {a}-{b} 卷的细节…')
                     .format(a=i + 1, b=min(i + batch, len(skel))))
        exp_prompt = f"""为下面这几卷补写分卷细节(其余卷不用管)。全书共 {total_ch} 章。

{ctx}

{listing}

只输出 JSON,不要解释:
{{"chapters":[{{"title":"卷名","range":"章号范围","goal":"本卷目标(60字内)","
"key_events":["关键事件1","关键事件2"],"cliffhanger":"卷末钩子"}}]}}
必须正好 {len(group)} 项,title 与 range 与上面给的完全一致。"""
        try:
            r2 = text_client.chat(exp_prompt, temperature=0.4,
                                  json_mode=True, config_id=config_id)
            d2 = runner.extract_json(r2) or {}
            got = [c for c in (d2.get("chapters") or []) if isinstance(c, dict)]

            def _norm_range(v) -> str:
                """「第 1-120 章」「1-120」「1~120」统一成「1-120」。

                模型写 range 的格式极不统一(带"第…章"、空格、全角横线都见过),
                精确字符串匹配必然频繁落空 —— 实测 6 卷细节因此全部被丢弃,
                界面只标红「缺细节」。
                """
                nums = re.findall(r"\d+", str(v or ""))
                return "-".join(nums) if len(nums) >= 2 else str(v or "").strip()

            by_range = {_norm_range(c.get("range")): c for c in got if c.get("range")}
            by_title = {str(c.get("title") or "").strip(): c for c in got if c.get("title")}
            for idx, c in enumerate(group):
                hit = (by_range.get(_norm_range(c.get("range")))
                       or by_title.get(str(c.get("title") or "").strip())
                       or (got[idx] if idx < len(got) else None))   # 顺序兜底
                if hit:
                    c.update({k: v for k, v in hit.items() if v})
        except Exception as exc:  # noqa: BLE001
            print(f"[novel] 分卷第 {i + 1}-{i + len(group)} 卷细节失败({exc}),保留骨架", flush=True)
        done += len(group)
        if on_progress:
            on_progress(done, len(skel))
    return skel



_VOLUME_META_KEY = "volume_chapters"      # 分卷结构(metadata 内,与 novel_chapters 分开)


def load_volume_chapters(drama_id: int) -> list[dict]:
    """读分卷结构。与「章节计划」(novel_chapters)是两个东西,不共用。"""
    row = db.q1("SELECT metadata FROM dramas WHERE id=?", (drama_id,))
    meta = db.jload((row or {}).get("metadata"), {}) or {}
    return meta.get(_VOLUME_META_KEY) or []


def save_volume_chapters(drama_id: int, chapters: list[dict]) -> None:
    """写分卷结构到 metadata,不碰 novel_chapters。"""
    row = db.q1("SELECT metadata FROM dramas WHERE id=?", (drama_id,))
    meta = db.jload((row or {}).get("metadata"), {}) or {}
    meta[_VOLUME_META_KEY] = chapters
    db.ex("UPDATE dramas SET metadata=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))


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
    # 落库前的乱码闸门:流式路径的文本没经过 text_client._guarded,
    # 网关少带一个 charset 就能把整段中文按 latin-1 解开糊进库(乱码不可逆)。
    text = _gate_content(text, f"{spec['name']}起草结果")
    ts = db.now()
    extra = ""
    if key == "volume" and structured:
        payload = [structured] if isinstance(structured, list) else (structured.get("chapters") or [])
        if payload:
            # 写 metadata 而不是 novel_chapters —— 后者是「章节计划」的字段,
            # 共用会导致生成分卷后一点章节计划就把分卷清空(实测)。
            save_volume_chapters(drama_id, payload)
            extra = f",已写入 {len(payload)} 卷结构"
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
    # 规划侧走「规划模型」(实测 deepseek-v4-pro 的结构化输出更规整:
    # 分卷 7 卷的目标/关键事件/钩子字段完整;minimax 偶有只吐散文)
    config_id = config_id or plan_config_id()
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
    """整章正文合成 MP3 供播放(MP3 帧自包含,顺序拼接可连续播放)。

    朗读音色取本剧项目设置:ProjectSettingsDialog 里的「朗读音色」女/男单选 →
    dramas.metadata.tts_gender。文本语言变化时,Edge TTS 自动挑 16 语种 × 男女 = 32
    个预设 voice 中的对应项(无需 API Key 与语言包,云端微软神经)。
    """
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
    # 项目级朗读音色:ProjectSettingsDialog 写入 dramas.metadata.tts_gender
    drama = db.q1("SELECT metadata FROM dramas WHERE id=?", (ep["drama_id"],))
    meta = db.jload(drama["metadata"] if drama else "", {}) or {}
    gender = meta.get("tts_gender") or "female"
    chunks = split_for_tts(text, 600)
    out_dir = config.STATIC_DIR / "narration" / "novel-read"
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, c in enumerate(chunks):
        # 把 voice 选定权下放到 synthesize():tts_client 检测 Edge voice / volc engine 自动降级
        p = tts_client.synthesize(c, config_id=config_id, gender=gender)
        parts.append(p.read_bytes())
        p.unlink(missing_ok=True)
    out = out_dir / f"ep-{episode_id}-{_uuid.uuid4().hex[:8]}.mp3"
    out.write_bytes(b"".join(parts))
    # 取出本次合成真正使用的 voice(Edge 32 预设 或 volcengine BV001 之类),
    # 弹播放器时让用户看到「这次朗读用的是哪个具体声音」。
    used_voice = tts_client.last_voice()
    return {"audio_url": config.path_to_media_url(out),
            "chunks": len(chunks),
            "voice": used_voice,
            "gender": gender}
