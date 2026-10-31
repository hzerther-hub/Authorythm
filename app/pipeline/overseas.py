"""海外题材改写 · 流水线(诊断 → 术语表 → 改写 → 质检)。

**不覆盖中文原稿** —— 改写稿独立落在 `overseas_chapter` 表,
`episodes.content` 一个字节都不动(AGENTS.md:不破坏用户数据)。

三层规矩,写在这里免得调用点漏:
1. **配置兜底必须在函数体内**:`text_config_id = text_config_id or _default_text_config()`。
   只写在 UI 层是不够的(调用点十几处,任一处漏掉就静默退回全局默认模型)。
2. **文本 config 的参数名不能叫 `config_id`**:同名的生图 config 传进文本调用会让
   `registry.check_ready("text", <生图id>)` 永不匹配 → 每格失败且被静默吞掉。
   本模块一律用 `text_config_id`。
3. **规则走数据文件,不走 Agent skill**:`prompts.load_skills()` 会把某 Agent 的全部 skill
   一次性拼进 instructions,3 平台 × 4 品类挂上去 prompt 会爆。
   规则由 `overseas_rules.assemble()` 按用户选择动态拼装。
"""
from __future__ import annotations

import json
import re

from ..agents import runner
from ..core import db
from ..core.logging_setup import get_logger

log = get_logger(__name__)

LEVELS = ("A", "B", "C")
# 全翻译(用户需求 2026-10-24):只译不改 —— 情节/结构/钩子/文化设定原样保留,
# 不做西化改写。诊断不会建议它(诊断的意义就是建议改多少),纯用户手选。
LEVEL_TRANSLATE = "T"
# 诊断的原文采样上限(头+尾):诊断要看的是开篇钩子/语言层/专名,单章正文
# (2-6 千字)远小于此;用户把多章或整本粘进来时截住,防 prompt 爆上下文/烧钱。
DIAG_HEAD_CHARS = 9000
DIAG_TAIL_CHARS = 3000


def _default_text_config() -> int | None:
    """全局默认文本模型 id。

    `registry.default_config` 可能返回 None —— 必须 `or {}` 兜底,
    否则 `.get("id")` 抛 AttributeError(设置页崩)。
    """
    from ..ai import registry
    cfg = registry.default_config("text", None) or {}
    return cfg.get("id")


def _strip_think(text: str) -> str:
    """剥推理型模型的 <think> 块。

    推理型模型(minimax-M3 / glm)会先吐思维链再给正文,不剥必然解析失败
    (AGENTS.md「LLM 输出的解析纪律」)。
    """
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    if "<think>" in text:
        text = text.rsplit("<think>", 1)[-1]
    return text.strip()


def _lang_label(target_lang: str) -> str:
    """目标语言的人类可读名,写进 prompt 当硬约束。

    不能只靠规则段里的「目标语言要点」那一节 —— 那是参考资料,不是命令。
    旧实现把「直接输出改写后的**英文**正文。」写死在最后一句,而系统提示词
    (overseas_rewriter.md)同样只说英文:两处都与规则段要求的语种矛盾,
    而且英文那句在最后、模型通常听最后的。切到法语就会「要求法语、得到英语」。
    """
    try:
        from ..core.i18n import LANG_OUTPUT_NAME
    except Exception:  # noqa: BLE001
        return target_lang
    base = target_lang.split("-")[0]
    return LANG_OUTPUT_NAME.get(target_lang) or LANG_OUTPUT_NAME.get(base) or target_lang


def _rules(platform: str, category: str, *, level: str | None = None,
           target_lang: str = "en-US") -> str:
    from . import overseas_rules
    return overseas_rules.assemble(platform, category, level=level,
                                   target_lang=target_lang)


def _glossary_pairs(glossary) -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(glossary, dict):
        for k, v in glossary.items():
            if k and v:
                out[str(k)] = str(v)
    elif isinstance(glossary, list):
        for it in glossary:
            if isinstance(it, dict):
                s = it.get("source") or it.get("zh")
                t = it.get("target") or it.get("en")
                if s and t:
                    out[str(s)] = str(t)
    return out


# ---------------------------------------------------------------- 阶段 1+2

def diagnose(*, source: str, platform: str, category: str, level: str = "B",
             target_lang: str = "en-US", book_title: str = "",
             text_config_id: int | None = None) -> dict:
    """诊断 + 术语表抽取 + **西化书名**(一次 LLM 调用一起出)。

    book_title:中文书名(dramas.title)。给了才会要求书名 —— 不给就别让模型
    凭空造(它没看过全书,造出来的书名跟内容无关)。

    返回:
        {"level", "level_reason", "diagnosis", "issues", "opening",
         "glossary"(dict 中文→英文), "culture_mappings", "rules",
         "title_target"(主推西化书名,可能为空), "title_alts"(备选), "title_reason"}
    """
    text_config_id = text_config_id or _default_text_config()
    source = (source or "").strip()
    if not source:
        raise ValueError("中文原文为空")
    # 超长采样(头+尾):诊断要看开篇钩子/语言层/专名,尾段给章末钩子;
    # 多章/整本粘进来时截住,防爆上下文与烧钱(与 extract_new_terms 的上限同思路)
    if len(source) > DIAG_HEAD_CHARS + DIAG_TAIL_CHARS:
        source = (source[:DIAG_HEAD_CHARS]
                  + "\n……(中段略,以上为开头部分)……\n"
                  + source[-DIAG_TAIL_CHARS:])
    label = _lang_label(target_lang)
    rules = _rules(platform, category, target_lang=target_lang)
    title_block = ""
    if (book_title or "").strip():
        title_block = (f"# 中文书名\n\n{book_title.strip()}\n\n"
                       f"按输出格式里的 `title` 字段给出西化书名 —— "
                       f"**{label}**书写、遵循平台 title_style、不直译;\n\n")
    prompt = (
        f"# 原文\n\n{source}\n\n"
        f"# 目标平台规格与品类套路\n\n{rules}\n\n"
        + title_block +
        f"# 目标语言\n\n{label}\n\n"
        f"# 任务\n\n"
        f"对上面这段中文做诊断,按你规定的 JSON 格式返回。"
        f"术语表的 target 一律写成**{label}**里的译名 —— 不要一律写成英文,"
        f"那是最常见的失手点。"
    )
    # lang="zh" 是有意为之,不是漏传:原文恒为中文,分析结果(问题清单/文化映射/
    # 五维诊断)也用中文给用户看;`overseas_analyzer` 的 JSON schema 键是中文字面量
    # ("中文"/"English"),改 lang 会让术语表的方向键串语言。输出语言由上面
    # 「# 目标语言」一节约束,不是 system 语言。见 tests/test_content_lang_propagation.py
    raw = runner.run_agent("overseas_analyzer", prompt, lang="zh",
                           json_output=True, config_id=text_config_id)
    data = runner.extract_json(raw) or {}
    if not isinstance(data, dict):
        data = {}
    glossary = _glossary_pairs(data.get("glossary") or [])
    # 品类术语种子兜底:模型漏抽的常见专名用规则库补上
    try:
        from . import overseas_rules
        for k, v in overseas_rules.glossary_seed(category).items():
            glossary.setdefault(k, v)
    except Exception:  # noqa: BLE001
        pass
    # 西化书名(给了中文书名才可能有):main 为主推,alts 备选。老响应/没给书名时为空。
    title_obj = data.get("title") if isinstance(data.get("title"), dict) else {}
    title_alts = [str(a).strip() for a in (title_obj.get("alts") or [])
                  if str(a).strip()]
    return {
        "level": str(data.get("level") or level or "B"),
        "level_reason": str(data.get("level_reason") or ""),
        "diagnosis": data.get("diagnosis") or {},
        "issues": data.get("issues") or [],
        "opening": data.get("opening") or {},
        "glossary": glossary,
        "culture_mappings": data.get("culture_mappings") or [],
        "rules": rules,
        "title_target": str(title_obj.get("main") or "").strip(),
        "title_alts": title_alts[:2],
        "title_reason": str(title_obj.get("reason") or "").strip(),
    }


# ---------------------------------------------------------------- 阶段 4

def rewrite(*, source: str, platform: str, category: str, level: str = "B",
            glossary: dict | None = None, issues: list | None = None,
            target_lang: str = "en-US",
            prev_tail: str = "", prev_summary: str = "",
            text_config_id: int | None = None) -> dict:
    """把一段中文改写成目标平台的英文稿。

    prev_tail = **上一章改写稿**的结尾片段(不是中文原文!)—— B/C 级改写是再创作,
    桥段/钩子都会被改,逐章改写时的事实源是上一章**改写稿**而不是上一章原文。
    prev_summary = 前情提要(可选,有就一并注入)。两者都空 = 第一章/孤立改写。

    返回 {"content": 英文正文, "level": 实际级别}
    """
    text_config_id = text_config_id or _default_text_config()
    source = (source or "").strip()
    if not source:
        raise ValueError("中文原文为空")
    label = _lang_label(target_lang)
    glossary = _glossary_pairs(glossary)
    # ── 全翻译(T):只译不改 —— 不拼平台规则(那是给改写定的套路,翻译遵循原文),
    #    也不注入上一章衔接硬约束(它授权模型改开头承接,与「忠实翻译」矛盾;
    #    术语表仍生效,译名链不能断)。
    if level == LEVEL_TRANSLATE:
        prompt = (
            f"# 原文(待翻译)\n\n{source}\n\n"
            f"# 术语表(必须逐字照用,同一人名全篇一致)\n\n"
            f"{json.dumps(glossary, ensure_ascii=False, indent=2)}\n\n"
            f"# 翻译模式:全翻译(只译不改)\n\n"
            f"- 逐段忠实翻译,情节/结构/段落顺序/钩子/文化设定**一概保持原样**;\n"
            f"- 不做任何西化改写:不替换文化设定、不增删段落、不调整开篇与卡点;\n"
            f"- 人名/地名/专名一律按术语表的译名,表里没有的按全篇统一的译法;\n"
            f"- 译文要自然流畅,但「自然」只到语言层 —— 内容层零改动。\n\n"
            f"# 输出语言\n\n"
            f"译文必须用 **{label}** 书写,不要保留中文。\n\n"
            f"直接输出译文。"
        )
        raw = runner.run_agent("overseas_rewriter", prompt, lang="zh",
                               config_id=text_config_id)
        content = _strip_think(raw)
        content = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", content).strip()
        return {"content": content, "level": level}
    rules = _rules(platform, category, level=level, target_lang=target_lang)
    notes: list[str] = []
    for it in (issues or [])[:8]:
        if isinstance(it, dict):
            notes.append(f"- [{it.get('type', '')}] {it.get('quote', '')} → {it.get('fix', '')}")
    prev_block = ""
    if (prev_tail or "").strip() or (prev_summary or "").strip():
        parts = []
        if (prev_summary or "").strip():
            parts.append(f"前情提要:{prev_summary.strip()}")
        if (prev_tail or "").strip():
            parts.append(f"上一章结尾(改写稿原文,开头必须自然承接,不得重启场景):\n"
                         f"……{prev_tail.strip()}")
        prev_block = (
            "# 上一章衔接(硬约束)\n\n"
            + "\n\n".join(parts) + "\n\n"
            "- 本章开头必须自然承接上面这个结尾(同场景/同时间线,或原文明确切换场景);\n"
            "- 人物状态(受伤/关系/立场/谁知道什么秘密)必须与上一章结束时一致,\n"
            "  不得凭空恢复、不得遗忘;\n"
            "- 上一章埋的钩子/悬念,除非本章原文回收,不得当作不存在;\n"
            "- 已下线的人物不得无中生有地出场(除非本章原文有)。\n\n")
    prompt = (
        f"# 原文(待改写)\n\n{source}\n\n"
        f"# 目标平台规格与品类套路\n\n{rules}\n\n"
        f"# 术语表(必须逐字照用,同一人名全篇一致)\n\n"
        f"{json.dumps(glossary, ensure_ascii=False, indent=2)}\n\n"
        + prev_block +
        f"# 改写级别\n\n{level}\n\n"
        "# 诊断发现(改写时必须修掉)\n\n" + ("\n".join(notes) or "- 无") + "\n\n"
        f"# 输出语言\n\n"
        f"改写后的正文必须用 **{label}** 书写。不要用英文,不要用任何其它语言,"
        f"也不要保留中文。\n\n"
        f"直接输出改写后的{label}正文。"
    )
    raw = runner.run_agent("overseas_rewriter", prompt, lang="zh",
                           config_id=text_config_id)
    content = _strip_think(raw)
    # 模型偶尔会加围栏或前后解释,去掉
    content = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", content).strip()
    return {"content": content, "level": level}


# ---------------------------------------------------------------- 跨章一致性

PREV_TAIL_CHARS = 800


def find_project(drama_id: int, platform: str, category: str,
                 target_lang: str = "en-US") -> int:
    """找同书同参数的最近 project(逐章改写复用同一个,术语表/衔接才有连续性)。

    匹配键 = drama_id + platform + category + target_lang(级别不参与 ——
    逐章微调级别不该把术语表和章序切断)。返回 project_id,没有返回 0。
    """
    row = db.q1(
        "SELECT id FROM overseas_project WHERE drama_id=? AND platform=?"
        " AND category=? AND target_lang=? ORDER BY id DESC LIMIT 1",
        (drama_id, platform, category, target_lang))
    return row["id"] if row else 0


def extract_new_terms(source: str, glossary: dict, *, target_lang: str = "en-US",
                      text_config_id: int | None = None) -> dict:
    """增量术语抽取:本章原文里**术语表还没有**的专名,按现有译名风格补译。

    为什么需要:术语表只在第一次诊断的原文上抽取,第 5 章新出场的人物不在表里,
    译名就会逐章漂移(「林晚」这章 Lin Wan、下章 Lin Wan'er)。每章改写前补一次
    轻量调用,新词当场锁死并随 project 落库。

    失败/无新词返回空 dict(调用方原样继续,不阻塞改写)。
    """
    text_config_id = text_config_id or _default_text_config()
    source = (source or "").strip()
    if not source:
        return {}
    glossary = _glossary_pairs(glossary)
    prompt = (
        "# 术语表(已定译名,不要重复输出)\n\n"
        f"{json.dumps(glossary, ensure_ascii=False, indent=1)}\n\n"
        f"# 中文原文\n\n{source[:6000]}\n\n"
        f"# 任务\n\n"
        f"找出原文里会**反复出现**的专有名词(人名/地名/组织/称号/功法/物品),"
        f"但**只输出术语表里还没有的**。译名风格必须与术语表一致"
        f"(音译/意译口径、长短)。目标语言:{_lang_label(target_lang)}。\n"
        f'只输出 JSON:{{"new_terms": {{"中文": "译名", ...}}}},没有新词输出空对象。'
    )
    try:
        raw = runner.run_agent("overseas_analyzer", prompt, lang="zh",
                               json_output=True, config_id=text_config_id)
        data = runner.extract_json(raw) or {}
        out = _glossary_pairs(data.get("new_terms") or data)
        # 已在表里的剔除;空值剔除 —— 只留真正的新词
        return {k: v for k, v in out.items() if k and v and k not in glossary}
    except Exception as exc:  # noqa: BLE001 —— 增量抽取是增强,不阻塞改写
        log.warning("overseas.extract_new_terms_failed error=%s", exc)
        return {}


def next_chapter_no(project_id: int, episode_id: int | None) -> int:
    """本章落库章号:该集改写过 → 沿用原章号(视为重改,不占新章);
    否则 → **链上最小空洞**(删过中间章时先补洞,用户规则 2026-10-25
    「删掉中间时不能再生成除非补上」),没有洞才是 max+1。"""
    if episode_id:
        row = db.q1(
            "SELECT chapter_no FROM overseas_chapter WHERE project_id=?"
            " AND episode_id=? ORDER BY id DESC LIMIT 1", (project_id, episode_id))
        if row:
            return int(row["chapter_no"])
    rows = {int(r["chapter_no"]) for r in db.q(
        "SELECT chapter_no FROM overseas_chapter WHERE project_id=?", (project_id,))}
    m = max(rows) if rows else 0
    for n in range(1, m + 1):
        if n not in rows:
            return n                     # 最小空洞:删掉的中间章,先生成它
    return m + 1


def missing_chapter_before(project_id: int, chapter_no: int) -> int:
    """链上 1..chapter_no-1 缺的第一个章号(链不连续);连续返回 0。
    删过中间章后,比它大的章不许重生成 —— 衔接锚断在洞里。"""
    rows = {int(r["chapter_no"]) for r in db.q(
        "SELECT chapter_no FROM overseas_chapter WHERE project_id=? AND chapter_no<?",
        (project_id, chapter_no))}
    for n in range(1, chapter_no):
        if n not in rows:
            return n
    return 0


def generate_chapter_title(content: str, *, target_lang: str = "en-US",
                           text_config_id: int | None = None) -> str:
    """按**改写稿**内容起目标语言的章名(用户需求 2026-10-24:章名用相关语言)。

    只按改写稿起、不按中文原文起 —— 章名要贴合成品内容(B/C 级改写后内容
    已与原文不同)。轻量单调用;失败返回空串,不阻塞改写主流程。
    """
    text_config_id = text_config_id or _default_text_config()
    content = (content or "").strip()
    if not content:
        return ""
    label = _lang_label(target_lang)
    prompt = (
        f"# 章节正文\n\n{content[:3000]}\n\n"
        f"# 任务\n\n"
        f"为这一章起一个章名:**{label}**书写,4-10 个词,短句有钩子感,"
        f"贴合海外短篇网文的章节命名习惯。\n"
        f"只输出章名本身 —— 不要引号、不要章节号、不要任何解释。"
    )
    try:
        raw = runner.run_agent("overseas_rewriter", prompt, lang="zh",
                               config_id=text_config_id)
        t = _strip_think(raw)
        t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t).strip()
        t = t.strip('"“”‘’').strip()
        return t.split("\n")[0].strip()[:80]
    except Exception as exc:  # noqa: BLE001 —— 章名是增强,失败不阻塞
        log.warning("overseas.generate_chapter_title_failed error=%s", exc)
        return ""


def assert_previous_rewritten(project_id: int, episode_id: int | None) -> None:
    """顺序红线:上一章没改写,本章不许改(用户规则,2026-10-24)。

    为什么必须顺序:跨章一致性的衔接锚是上一章**改写稿**(B/C 级是再创作,
    原文不是事实源)—— 跳章改写时锚不存在,本章开头/人物状态必然与前文脱节,
    事后无法补(第 N-1 章后补的改写稿接不回已写好的第 N 章)。

    口径:
    - **按集判**:本章 = episode_number>1 时,取本书里 episode_number 更小的
      最近一集,它必须在**同一 project**(同语言同平台)下已有改写稿;
      英文链改完不影响西语链 —— 各语言各有各的链。
    - 集号不连续(删过集)不算跳章:比它小的最近一集改了就行。
    - 手动粘贴流(episode_id=None)不设卡:章号走 max+1,天然顺序,跳不了。
    - 第 1 章无前置,恒放行。
    """
    if not episode_id:
        return
    ep = db.q1("SELECT drama_id, episode_number, title FROM episodes WHERE id=?",
               (episode_id,))
    if not ep:
        return
    n = int(ep["episode_number"] or 1)
    if n <= 1:
        return
    prev = db.q1(
        "SELECT id, episode_number, title FROM episodes"
        " WHERE drama_id=? AND episode_number<?"
        " ORDER BY episode_number DESC LIMIT 1",
        (ep["drama_id"], n))
    if not prev:
        return                       # 书里没有更早的集 → 本章事实上的第 1 章
    row = db.q1(
        "SELECT id FROM overseas_chapter WHERE project_id=? AND episode_id=?",
        (project_id, prev["id"])) if project_id else None
    if not row:
        raise RuntimeError(
            f"上一章(第{prev['episode_number']}章《{prev['title'] or '无题'}》)"
            "还没有改写。跨章情节一致依赖上一章的**改写稿**做衔接锚 —— "
            "请先改写上一章,再回来改本章。")


def chapter_tail(project_id: int, current_chapter_no: int = 0,
                 chars: int = PREV_TAIL_CHARS) -> str:
    """取**上一章改写稿**的结尾片段 = 章号严格小于当前章的最大那章。

    这是逐章改写的衔接锚:改写是再创作,事实源是改写稿不是原文。
    按**章号**而不是 episode_id 判「上一章」:重改第 1 章时,比它小的章号不存在,
    锚为空(正确 —— 第 1 章本来就没有上一章);若按「跳过自己取最大」,
    会把**后面的**第 2 章当成上一章,倒序污染。
    """
    row = db.q1(
        "SELECT content FROM overseas_chapter WHERE project_id=?"
        " AND chapter_no<? ORDER BY chapter_no DESC LIMIT 1",
        (project_id, current_chapter_no))
    if not row or not (row["content"] or "").strip():
        return ""
    return row["content"].strip()[-chars:]


# ---------------------------------------------------------------- 阶段 5

def check(content: str, *, platform: str, category: str,
          glossary: dict | None = None, chapter_no: int | None = 1,
          target_lang: str = "en-US", level: str = "B"):
    """跑静态校验器,返回问题清单(空=通过)。

    全翻译(T)只跑语言层检查(中文残留/术语一致/翻译腔):钩子/卡点/爽点这些
    平台结构规则是给「改写」定的套路 —— 忠实翻译保留原文结构,被它们打回
    全是误报。
    """
    from . import overseas_check, overseas_rules
    try:
        lang = overseas_rules.get_language(target_lang)
        if level == LEVEL_TRANSLATE:
            plat, cat = {}, {}          # 空 dict = 平台/品类规则全部不适用
        else:
            plat = overseas_rules.get_platform(platform)
            cat = overseas_rules.get_category(category)
    except Exception:  # noqa: BLE001
        return []
    return overseas_check.run_checks(content, chapter_no=chapter_no,
                                     glossary=_glossary_pairs(glossary),
                                     platform=plat, category=cat, language=lang)


# ---------------------------------------------------------------- 落库

def save_project(*, drama_id: int, episode_id: int | None, platform: str,
                 category: str, level: str, source_text: str,
                 target_lang: str = "en-US", glossary: dict | None = None,
                 diag: dict | None = None, title_target: str = "") -> int:
    ts = db.now()
    # db.ex 本身就返回 cursor.lastrowid。原实现丢掉返回值再
    # `SELECT id ... ORDER BY id DESC LIMIT 1` 查一次 —— 并发下两个诊断同时完成
    # 时会互相串号,把 A 的结果挂到 B 的 project 上。
    return db.ex(
        "INSERT INTO overseas_project(drama_id, episode_id, platform, category,"
        " target_lang, level, status, source_text, glossary_json, diag_json,"
        " title_target, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (drama_id, episode_id, platform, category, target_lang, level,
         "diagnosed" if diag else "init", source_text,
         json.dumps(glossary or {}, ensure_ascii=False),
         json.dumps(diag or {}, ensure_ascii=False),
         title_target or "", ts, ts))


def update_project(project_id: int, **fields) -> None:
    if not project_id or not fields:
        return
    allowed = {"platform", "category", "target_lang", "level", "status",
               "source_text", "glossary_json", "diag_json", "plan_json",
               "title_target"}
    sets, vals = [], []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k in ("glossary_json", "diag_json", "plan_json") and not isinstance(v, str):
            v = json.dumps(v or {}, ensure_ascii=False)
        sets.append(f"{k}=?")
        vals.append(v)
    if not sets:
        return
    vals.append(db.now())
    vals.append(project_id)
    db.ex(f"UPDATE overseas_project SET {', '.join(sets)}, updated_at=? WHERE id=?",
          tuple(vals))


def save_chapter(*, project_id: int, episode_id: int | None, chapter_no: int,
                 content: str, title: str = "", notes: str = "",
                 qc: list | None = None) -> int:
    # 空正文不落库(实测整书生成第 8 章存过 0 词空章:模型偶发返回空串,
    # 存了还会被断点续跑当「已完成」跳过,永远补不上)
    if not (content or "").strip():
        raise RuntimeError(f"第 {chapter_no} 章改写返回了空正文,不落库(请重试本章)")
    ts = db.now()
    words = len(content.split())
    # 同一个 lastrowid 问题(见 save_project):这里原来按 `ORDER BY id DESC` 取 id,
    # 同一 project 并发写两章就会串。
    return db.ex(
        "INSERT INTO overseas_chapter(project_id, episode_id, chapter_no, title,"
        " content, notes, words, qc_json, status, created_at, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (project_id, episode_id, chapter_no, title, content, notes, words,
         json.dumps([str(i) for i in (qc or [])], ensure_ascii=False),
         "done", ts, ts))


def list_chapters(project_id: int) -> list:
    return db.q("SELECT * FROM overseas_chapter WHERE project_id=? "
                "ORDER BY chapter_no", (project_id,))


def delete_chapter(chapter_id: int) -> bool:
    """删除一条已保存章(用户可删可重生成,2026-10-25)。返回是否删到。"""
    if not chapter_id:
        return False
    return bool(db.ex("DELETE FROM overseas_chapter WHERE id=?", (chapter_id,)))


def regenerate_chapter(*, project_id: int, episode_id: int, chapter_no: int,
                       platform: str, category: str, level: str,
                       target_lang: str = "en-US", title: str = "",
                       text_config_id: int | None = None) -> dict:
    """重新生成一章:删旧行、**沿用原章号**(中链位置不变),按同一套改写程序重出。

    与直接再改写的差别:next_chapter_no 会把该集排到**队尾**(max+1),中链重生成
    就乱序了;这里显式用原章号,衔接锚取「章号严格更小」的最新章 —— 在哪断的
    就从哪重接。旧行先删(连同该集可能的历史重复行),不会并存两行。
    """
    text_config_id = text_config_id or _default_text_config()
    # 链断检查(用户规则:删掉中间章后,后续章不能再生成,除非先补上)——
    # 重生成第 N 章要求 1..N-1 连续,洞在哪就先补哪
    miss = missing_chapter_before(project_id, chapter_no)
    if miss:
        raise RuntimeError(
            f"第 {miss} 章缺失(被删除),链断在此 —— 先补上第 {miss} 章,"
            f"才能重生成第 {chapter_no} 章")
    cleanup_empty_chapters(project_id)
    # 该集旧行全删(防重复),但章号记的是调用方传的原号
    db.ex("DELETE FROM overseas_chapter WHERE project_id=? AND episode_id=?",
          (project_id, episode_id))
    ep = db.q1("SELECT content FROM episodes WHERE id=?", (episode_id,))
    source = ((ep["content"] if ep else "") or "").strip()
    if not source:
        raise RuntimeError("该集没有正文可重新生成")
    glossary = _glossary_pairs(db.jload(db.q1(
        "SELECT glossary_json FROM overseas_project WHERE id=?",
        (project_id,))["glossary_json"], {}) or {})
    new_terms = extract_new_terms(source, glossary, target_lang=target_lang,
                                  text_config_id=text_config_id)
    if new_terms:
        glossary.update(new_terms)
        update_project(project_id, glossary=glossary)
    diag = db.jload(db.q1("SELECT diag_json FROM overseas_project WHERE id=?",
                          (project_id,))["diag_json"], {}) or {}
    prev_tail = chapter_tail(project_id, chapter_no)
    res = rewrite(source=source, platform=platform, category=category,
                  level=level, glossary=glossary,
                  issues=(diag.get("issues") or []) if isinstance(diag, dict) else [],
                  target_lang=target_lang, prev_tail=prev_tail,
                  text_config_id=text_config_id)
    if not (res.get("content") or "").strip():
        raise RuntimeError("重新生成返回了空正文,原章保持删除状态(可再试)")
    ch_title = title or generate_chapter_title(
        res["content"], target_lang=target_lang, text_config_id=text_config_id)
    issues = check(res["content"], platform=platform, category=category,
                   glossary=glossary, target_lang=target_lang, level=level)
    cid = save_chapter(project_id=project_id, episode_id=episode_id,
                       chapter_no=chapter_no, title=ch_title,
                       content=res["content"], qc=[str(i) for i in issues])
    res.update({"chapter_id": cid, "chapter_no": chapter_no,
                "chapter_title": ch_title, "qc": issues,
                "project_id": project_id})
    return res


def cleanup_empty_chapters(project_id: int) -> None:
    """自愈空章/重复章(软件自动修,不靠人工删库 —— 用户要求 2026-10-25)。

    两类坏行:① 空正文行(模型偶发返回空串时落过);② 同一集的多行
    (空行未清时再改写该集会插入第二行,新旧并存)。
    处理:删空行;同集多行时只留**最新的一条非空行**。
    调用点:整书生成启动 / 对话框刷新已保存页 / 单章改写落库前 ——
    任何入口碰到坏行都当场清,坏章所在集按未完成对待、下次生成自动补。
    """
    if not project_id:
        return
    db.ex("DELETE FROM overseas_chapter WHERE project_id=?"
          " AND (content IS NULL OR TRIM(content)='')", (project_id,))
    for d in db.q("SELECT episode_id FROM overseas_chapter"
                  " WHERE project_id=? AND episode_id IS NOT NULL"
                  " GROUP BY episode_id HAVING COUNT(*)>1", (project_id,)):
        keep = db.q1(
            "SELECT id FROM overseas_chapter WHERE project_id=? AND episode_id=?"
            " AND TRIM(content)!='' ORDER BY id DESC LIMIT 1",
            (project_id, d["episode_id"]))
        if keep:
            db.ex("DELETE FROM overseas_chapter WHERE project_id=?"
                  " AND episode_id=? AND id<>?",
                  (project_id, d["episode_id"], keep["id"]))
        else:
            db.ex("DELETE FROM overseas_chapter WHERE project_id=?"
                  " AND episode_id=?", (project_id, d["episode_id"]))


def batch_rewrite(*, drama_id: int, platform: str, category: str, level: str,
                  target_lang: str = "en-US", title: str = "",
                  force: bool = False,
                  text_config_id: int | None = None,
                  on_stage=None, stop_check=None) -> dict:
    """整书逐章批量生成(用户工作流:书写完 → 一次定好 书名/平台/西化程度/语言
    → 一键生成,而不是每章手动改一遍)。

    - 按 episode_number 顺序处理有正文的集 —— 顺序由构造保证,天然满足
      顺序红线;每章与**对应原章**关联(overseas_chapter.episode_id),
      走与单章完全相同的改写程序(增量抽词 → 上一章衔接 → 改写 →
      目标语言章名 → 质检 → 落库)。
    - **断点续跑**:已改写过的集默认跳过(再次点整书生成只补剩余章);
      force=True 才整书重出。
    - 单章失败即停(跳章会断衔接链),已完成章保留 —— 修好问题再点一次,
      从断点继续。
    - 返回 {"done": 本次完成, "skipped": 已有跳过, "total": 总章数,
            "failed_at": 失败章号或 0, "error": 失败原因或 ""}
    """
    text_config_id = text_config_id or _default_text_config()
    eps = db.q("SELECT id, episode_number FROM episodes WHERE drama_id=?"
               " AND content IS NOT NULL AND TRIM(content)!=''"
               " ORDER BY episode_number", (drama_id,))
    chapters = [(r["id"], int(r["episode_number"] or 0)) for r in eps]
    if not chapters:
        raise RuntimeError("这本书没有任何带正文的章节,先写完/导入再整书生成")

    # 书级设定一次定死:复用(或新建)链,书名有值则更新(空则不动已定书名)
    pid = find_project(drama_id, platform, category, target_lang)
    if not pid:
        pid = save_project(drama_id=drama_id, episode_id=None, platform=platform,
                           category=category, level=level, source_text="",
                           target_lang=target_lang,
                           title_target=title, diag={})
    elif title:
        update_project(pid, title_target=title)
    update_project(pid, platform=platform, category=category,
                   target_lang=target_lang, level=level)
    # 已存诊断的「发现」是书级硬约束(语言层/文化专名类问题跨章通用),
    # 整书生成同样要带着修 —— 与单章改写同口径
    diag = db.jload(db.q1("SELECT diag_json FROM overseas_project WHERE id=?",
                          (pid,))["diag_json"], {}) or {}
    diag_issues = diag.get("issues") or [] if isinstance(diag, dict) else []

    done = skipped = 0
    # 自愈:清掉本链历史空章/重复章(见 cleanup_empty_chapters),坏章按未完成重出
    cleanup_empty_chapters(pid)
    for ep_id, ep_no in chapters:
        if stop_check and stop_check():
            break
        if not force and db.q1(
                "SELECT id FROM overseas_chapter WHERE project_id=? AND episode_id=?"
                " AND content IS NOT NULL AND TRIM(content)!=''",
                (pid, ep_id)):
            skipped += 1
            if on_stage:
                on_stage(f"{skipped + done}/{len(chapters)}")
            continue
        row = db.q1("SELECT content FROM episodes WHERE id=?", (ep_id,))
        source = (row["content"] or "").strip()
        if not source:
            continue
        try:
            if on_stage:
                on_stage(f"{skipped + done + 1}/{len(chapters)}")
            # 每章走与单章改写**同一套程序**(术语累积/衔接锚/章名/质检/真实章号)
            glossary = _glossary_pairs(db.jload(db.q1(
                "SELECT glossary_json FROM overseas_project WHERE id=?",
                (pid,))["glossary_json"], {}) or {})
            new_terms = extract_new_terms(source, glossary,
                                          target_lang=target_lang,
                                          text_config_id=text_config_id)
            if new_terms:
                glossary.update(new_terms)
                update_project(pid, glossary=glossary)
            chapter_no = next_chapter_no(pid, ep_id)
            prev_tail = chapter_tail(pid, chapter_no)
            res = rewrite(source=source, platform=platform, category=category,
                          level=level, glossary=glossary, issues=diag_issues,
                          target_lang=target_lang, prev_tail=prev_tail,
                          text_config_id=text_config_id)
            if not (res.get("content") or "").strip():
                # 空正文按失败处理:停在断点保住已完成,绝不能落 0 词空章
                raise RuntimeError(f"第 {ep_no} 章改写返回了空正文(模型抖动,重试通常可解)")
            ch_title = generate_chapter_title(
                res["content"], target_lang=target_lang,
                text_config_id=text_config_id)
            issues = check(res["content"], platform=platform, category=category,
                           glossary=glossary, target_lang=target_lang,
                           level=level)
            save_chapter(project_id=pid, episode_id=ep_id, chapter_no=chapter_no,
                         title=ch_title, content=res["content"],
                         qc=[str(i) for i in issues])
            done += 1
        except Exception as exc:  # noqa: BLE001 —— 单章失败即停,保住已完成
            return {"done": done, "skipped": skipped, "total": len(chapters),
                    "failed_at": ep_no, "error": str(exc)[:300]}
    return {"done": done, "skipped": skipped, "total": len(chapters),
            "failed_at": 0, "error": ""}
