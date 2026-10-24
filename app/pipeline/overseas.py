# -*- coding: utf-8 -*-
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
             target_lang: str = "en-US",
             text_config_id: int | None = None) -> dict:
    """诊断 + 术语表抽取(一次 LLM 调用一起出)。

    返回:
        {"level", "level_reason", "diagnosis", "issues", "opening",
         "glossary"(dict 中文→英文), "culture_mappings", "rules"}
    """
    text_config_id = text_config_id or _default_text_config()
    source = (source or "").strip()
    if not source:
        raise ValueError("中文原文为空")
    label = _lang_label(target_lang)
    rules = _rules(platform, category, target_lang=target_lang)
    prompt = (
        f"# 原文\n\n{source}\n\n"
        f"# 目标平台规格与品类套路\n\n{rules}\n\n"
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
    return {
        "level": str(data.get("level") or level or "B"),
        "level_reason": str(data.get("level_reason") or ""),
        "diagnosis": data.get("diagnosis") or {},
        "issues": data.get("issues") or [],
        "opening": data.get("opening") or {},
        "glossary": glossary,
        "culture_mappings": data.get("culture_mappings") or [],
        "rules": rules,
    }


# ---------------------------------------------------------------- 阶段 4

def rewrite(*, source: str, platform: str, category: str, level: str = "B",
            glossary: dict | None = None, issues: list | None = None,
            target_lang: str = "en-US",
            text_config_id: int | None = None) -> dict:
    """把一段中文改写成目标平台的英文稿。

    返回 {"content": 英文正文, "level": 实际级别}
    """
    text_config_id = text_config_id or _default_text_config()
    source = (source or "").strip()
    if not source:
        raise ValueError("中文原文为空")
    label = _lang_label(target_lang)
    rules = _rules(platform, category, level=level, target_lang=target_lang)
    glossary = _glossary_pairs(glossary)
    notes: list[str] = []
    for it in (issues or [])[:8]:
        if isinstance(it, dict):
            notes.append(f"- [{it.get('type', '')}] {it.get('quote', '')} → {it.get('fix', '')}")
    prompt = (
        f"# 原文(待改写)\n\n{source}\n\n"
        f"# 目标平台规格与品类套路\n\n{rules}\n\n"
        f"# 术语表(必须逐字照用,同一人名全篇一致)\n\n"
        f"{json.dumps(glossary, ensure_ascii=False, indent=2)}\n\n"
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


# ---------------------------------------------------------------- 阶段 5

def check(content: str, *, platform: str, category: str,
          glossary: dict | None = None, chapter_no: int | None = 1,
          target_lang: str = "en-US"):
    """跑静态校验器,返回问题清单(空=通过)。"""
    from . import overseas_check, overseas_rules
    try:
        plat = overseas_rules.get_platform(platform)
        cat = overseas_rules.get_category(category)
        lang = overseas_rules.get_language(target_lang)
    except Exception:  # noqa: BLE001
        return []
    return overseas_check.run_checks(content, chapter_no=chapter_no,
                                     glossary=_glossary_pairs(glossary),
                                     platform=plat, category=cat, language=lang)


# ---------------------------------------------------------------- 落库

def save_project(*, drama_id: int, episode_id: int | None, platform: str,
                 category: str, level: str, source_text: str,
                 target_lang: str = "en-US", glossary: dict | None = None,
                 diag: dict | None = None) -> int:
    ts = db.now()
    # db.ex 本身就返回 cursor.lastrowid。原实现丢掉返回值再
    # `SELECT id ... ORDER BY id DESC LIMIT 1` 查一次 —— 并发下两个诊断同时完成
    # 时会互相串号,把 A 的结果挂到 B 的 project 上。
    return db.ex(
        "INSERT INTO overseas_project(drama_id, episode_id, platform, category,"
        " target_lang, level, status, source_text, glossary_json, diag_json,"
        " created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (drama_id, episode_id, platform, category, target_lang, level,
         "diagnosed" if diag else "init", source_text,
         json.dumps(glossary or {}, ensure_ascii=False),
         json.dumps(diag or {}, ensure_ascii=False), ts, ts))


def update_project(project_id: int, **fields) -> None:
    if not project_id or not fields:
        return
    allowed = {"platform", "category", "target_lang", "level", "status",
               "source_text", "glossary_json", "diag_json", "plan_json"}
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
