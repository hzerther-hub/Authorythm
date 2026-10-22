# -*- coding: utf-8 -*-
"""海外题材改写 · 领域规则库(平台规格 / 品类套路 / 语言层 / 叙事层)。

规则外置为 `data/overseas/` 下的 JSON(用户可编辑),首次启动从
`app/pipeline/overseas_templates/` 播种,**只补缺失、不覆盖用户改动**。

为什么不用 Agent skill 承载规则:
  `app/agents/prompts.py:load_skills()` 会把某 Agent 的全部 skill(含子目录)
  一次性拼进 instructions,**没有按需加载机制** —— 3 平台 × 4 品类全挂上去,
  每次调用的 prompt 会膨胀到不可用。这里改成由 pipeline 按用户选择动态拼装
  片段(只拼选中的平台 + 品类),等价于竞品的「按品类加载文档」而没有那个坑。

规则数据的可信度:平台规格来自**二手来源**(自媒体/报告摘要),两组数字互相
矛盾且会变 —— 所以每条平台规则都带 `source` 字段,UI 必须提示用户复核。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..core import config
from ..core.logging_setup import get_logger

log = get_logger(__name__)

OVERSEAS_DIR = config.DATA_DIR / "overseas"
TEMPLATES_DIR = Path(__file__).parent / "overseas_templates"

PLATFORM_DIR = "platforms"
CATEGORY_DIR = "categories"
LANGUAGE_DIR = "language"
NARRATIVE_NAME = "narrative.json"

DEFAULT_LANG = "en-US"

# 改写级别(对齐 SoloEnt「海外短篇网文本地化」插件的 A/B/C 分级)
LEVELS = ("A", "B", "C")


class RuleError(ValueError):
    """规则库读取/校验失败(缺文件、JSON 坏、字段缺失)。"""


# ---------------------------------------------------------------- 读取

def _read_json(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuleError(f"规则文件读取失败:{path} — {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuleError(f"规则文件不是合法 JSON:{path} — 第 {exc.lineno} 行 {exc.msg}") from exc
    if not isinstance(data, dict):
        raise RuleError(f"规则文件顶层必须是对象:{path}")
    return data


def _list_json(sub: str) -> list[Path]:
    d = OVERSEAS_DIR / sub
    if not d.is_dir():
        return []
    return sorted(d.glob("*.json"))


def _load_all(sub: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in _list_json(sub):
        data = _read_json(p)
        rid = str(data.get("id") or p.stem)
        out[rid] = data
    return out


def seed_templates(force: bool = False) -> list[str]:
    """把内置规则模板播种到 `data/overseas/`。**只补缺失,不覆盖用户改动。**

    `force=True` 时用模板覆盖已有文件 —— 供「恢复默认规则库」用,
    也供模板升级时刷新那些**还没被用户改过**的副本。
    返回本次实际写入的相对路径列表(空=无需改动)。
    """
    if not TEMPLATES_DIR.is_dir():
        return []
    seeded: list[str] = []
    for src in sorted(TEMPLATES_DIR.rglob("*.json")):
        rel = src.relative_to(TEMPLATES_DIR)
        dst = OVERSEAS_DIR / rel
        if dst.exists() and not force:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        seeded.append(rel.as_posix())
    if seeded:
        log.info("overseas 规则库%s:%s",
                 "已重置为默认" if force else "已播种", ", ".join(seeded))
    return seeded


# ---------------------------------------------------------------- 查询

def list_platforms() -> list[dict]:
    """可选平台列表(给 UI 下拉用)。"""
    return [
        {
            "id": rid,
            "name": d.get("name", rid),
            "name_zh": d.get("name_zh", rid),
            "source_verified": bool(d.get("source_verified", False)),
        }
        for rid, d in _load_all(PLATFORM_DIR).items()
    ]


def list_categories() -> list[dict]:
    """可选品类列表(给 UI 下拉用)。"""
    return [
        {
            "id": rid,
            "name": d.get("name", rid),
            "name_zh": d.get("name_zh", rid),
            "pov_hint": d.get("pov_hint", ""),
        }
        for rid, d in _load_all(CATEGORY_DIR).items()
    ]


def _require(data: dict[str, dict], key: str, kind: str) -> dict:
    if key not in data:
        avail = "、".join(sorted(data)) or "(空)"
        raise RuleError(f"未知的{kind}:{key}。可用:{avail}")
    return data[key]


def get_platform(platform_id: str) -> dict:
    return _require(_load_all(PLATFORM_DIR), platform_id, "目标平台")


def get_category(category_id: str) -> dict:
    return _require(_load_all(CATEGORY_DIR), category_id, "品类")


def get_language(lang: str = DEFAULT_LANG) -> dict:
    path = OVERSEAS_DIR / LANGUAGE_DIR / f"{lang}.json"
    if not path.exists():
        avail = "、".join(p.stem for p in _list_json(LANGUAGE_DIR)) or "(空)"
        raise RuleError(f"未知的语言规则:{lang}。可用:{avail}")
    return _read_json(path)


def get_narrative() -> dict:
    path = OVERSEAS_DIR / NARRATIVE_NAME
    if not path.exists():
        raise RuleError(f"缺少叙事层规则:{path}")
    return _read_json(path)


def glossary_seed(category_id: str) -> dict[str, str]:
    """该品类的术语种子(中文 → 固定英文译名),用于初始化术语表。"""
    cat = get_category(category_id)
    seed = cat.get("glossary_seed") or {}
    return {str(k): str(v) for k, v in seed.items()}


def chapter_bounds(platform_id: str) -> tuple[int, int] | None:
    """平台允许的章节字数区间;没有就给 None。"""
    ch = (get_platform(platform_id).get("chapter") or {})
    lo, hi = ch.get("min_words"), ch.get("max_words")
    if isinstance(lo, int) and isinstance(hi, int):
        return lo, hi
    return None


def paywall_range(platform_id: str) -> tuple[int, int] | None:
    """平台允许的付费卡点章节区间;没有就给 None(此时不做该检查)。"""
    pay = (get_platform(platform_id).get("paywall") or {})
    rng = pay.get("paywall_chapter_range")
    if isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, int) for x in rng):
        return rng[0], rng[1]
    return None


# ---------------------------------------------------------------- 体检

def validate() -> list[str]:
    """结构体检:返回问题清单(空=通过)。不抛异常,供 UI 提示与测试用。"""
    problems: list[str] = []
    try:
        platforms = _load_all(PLATFORM_DIR)
    except RuleError as exc:
        return [str(exc)]
    if not platforms:
        problems.append("缺少平台规则(platforms/ 为空)")
    for rid, d in platforms.items():
        if not d.get("name"):
            problems.append(f"平台 {rid} 缺字段 name")
        pay = d.get("paywall") or {}
        rng = pay.get("paywall_chapter_range")
        if rng is not None and (not isinstance(rng, list) or len(rng) != 2
                                or not all(isinstance(x, int) for x in rng)
                                or rng[0] > rng[1]):
            problems.append(f"平台 {rid} 的 paywall_chapter_range 非法:{rng!r}")
        ch = d.get("chapter") or {}
        lo, hi = ch.get("min_words"), ch.get("max_words")
        if isinstance(lo, int) and isinstance(hi, int) and lo > hi:
            problems.append(f"平台 {rid} 章节字数区间反了:{lo} > {hi}")
    try:
        cats = _load_all(CATEGORY_DIR)
    except RuleError as exc:
        problems.append(str(exc))
        cats = {}
    if not cats:
        problems.append("缺少品类规则(categories/ 为空)")
    for rid, d in cats.items():
        if not d.get("name"):
            problems.append(f"品类 {rid} 缺字段 name")
        if not d.get("glossary_seed"):
            problems.append(f"品类 {rid} 没有 glossary_seed(术语表无从初始化)")
    try:
        get_language(DEFAULT_LANG)
    except RuleError as exc:
        problems.append(str(exc))
    try:
        get_narrative()
    except RuleError as exc:
        problems.append(str(exc))
    return problems


# ---------------------------------------------------------------- 拼装

def _bullets(items) -> list[str]:
    return [f"- {it}" for it in items if it]


def assemble(platform_id: str, category_id: str, *,
             target_lang: str = DEFAULT_LANG,
             level: str | None = None) -> str:
    """把选中的平台/品类/语言/叙事规则拼成一段可直接进 prompt 的文本。

    只拼选中的那一份 —— 这就是「按需加载」的落点。
    `level` 传 "A"/"B"/"C" 时只附带该级别的改造范围。
    """
    p = get_platform(platform_id)
    c = get_category(category_id)
    lang = get_language(target_lang)
    nar = get_narrative()

    lines: list[str] = []

    # ---- 平台规格
    sign = p.get("signing") or {}
    upd = p.get("updates") or {}
    pay = p.get("paywall") or {}
    opening = p.get("opening") or {}
    ch = p.get("chapter") or {}
    bits: list[str] = []
    if sign.get("min_words_for_signing"):
        bits.append(f"签约门槛:{sign['min_words_for_signing']} 字({sign.get('mode', '')})")
    if upd.get("daily_words"):
        bits.append(f"更新要求:日更 {upd['daily_words']} 字")
    if upd.get("monthly_words"):
        bits.append(f"更新要求:月更 {upd['monthly_words']} 字(满 {upd.get('min_days_per_month', '?')} 天)")
    if ch.get("min_words") and ch.get("max_words"):
        bits.append(f"章节字数:{ch['min_words']}-{ch['max_words']} 词")
    rng = pay.get("paywall_chapter_range")
    if rng:
        bits.append(f"付费卡点:第 {rng[0]}-{rng[1]} 章")
    if opening.get("payoff_within_chapters"):
        bits.append(f"开篇:{opening['payoff_within_chapters']} 章内必须释放核心爽点")
    lines.append(f"## 目标平台规格:{p.get('name', platform_id)}")
    lines += _bullets(bits)
    if p.get("title_style"):
        lines.append("- 标题风格:" + "、".join(str(x) for x in p["title_style"]))
    if p.get("banned"):
        lines.append("- 平台禁止项:")
        lines += [f"  - {x}" for x in p["banned"]]
    if p.get("source"):
        lines.append(f"> 平台规格来源(二手数据,需官方页复核):{p['source']}")

    # ---- 平台文风与读者口味(换平台真正变的是这一段)
    style = p.get("style_notes") or {}
    if style:
        lines.append("")
        lines.append("## 平台文风与读者口味")
        if style.get("readers"):
            lines.append(f"- 读者画像:{style['readers']}")
        for it in style.get("prose") or []:
            lines.append(f"- {it}")
        if style.get("pacing"):
            lines.append(f"- 节奏:{style['pacing']}")
        if style.get("review_tolerance"):
            lines.append(f"- 审核尺度:{style['review_tolerance']}")

    # ---- 品类套路
    lines.append("")
    lines.append(f"## 品类套路:{c.get('name_zh') or c.get('name', category_id)}")
    # 平台读者画像里会提到该平台收的其它品类;必须显式钉死「本篇只走这一个品类」,
    # 否则模型会把别的品类桥段(狼人的 mate mark、霸总的 black card)混进来。
    lines.append(f"> **本篇只采用「{c.get('name_zh') or c.get('name', category_id)}」这一个品类的套路**;"
                 "平台读者画像里提到的其它品类一律不采用,也不要混用它们的桥段与术语。")
    if c.get("required_elements"):
        lines.append("- 必备元素:" + "、".join(str(x) for x in c["required_elements"]))
    if c.get("tropes"):
        lines.append("- 常见桥段:" + "、".join(str(x) for x in c["tropes"]))
    seed = c.get("glossary_seed") or {}
    if seed:
        pairs = "、".join(f"{k}→{v}" for k, v in seed.items())
        lines.append(f"- 术语固定译名(必须逐字照用,不得换译法):{pairs}")
    if c.get("banned"):
        lines.append("- 品类禁止项:")
        lines += [f"  - {x}" for x in c["banned"]]
    if c.get("craft_notes"):
        lines.append("- 写法要求:")
        lines += [f"  - {x}" for x in c["craft_notes"]]

    # ---- 语言层 / 叙事层 / 套路层
    lines.append("")
    lines.append("## 本土化三层(语言层 ≠ 叙事层 ≠ 套路层)")
    for sec in nar.get("localization_layers") or []:
        lines.append(f"### {sec.get('title', sec.get('id', ''))}")
        if sec.get("note"):
            lines.append(f"> {sec['note']}")
        lines += _bullets(sec.get("items") or [])

    # ---- 第一视角硬约束
    fp = nar.get("first_person") or {}
    if fp:
        lines.append("")
        lines.append("## 第一视角硬约束")
        lines.append(f"- 被动链(错):{fp.get('passive_chain_bad')}")
        lines.append(f"- 主动链(对):{fp.get('passive_chain_good')}")
        beats = fp.get("per_chapter_beats")
        if beats:
            lines.append("- 每章必须给到:" + "、".join(str(x) for x in beats))
        allow = fp.get("self_observation_allowed")
        if allow:
            lines.append("- 可写(有感觉依据):" + "、".join(str(x) for x in allow))
        forbid = fp.get("self_observation_forbidden")
        if forbid:
            lines.append("- 禁写(第一视角看不见自己):" + "、".join(str(x) for x in forbid))
        if fp.get("note"):
            lines.append(f"> {fp['note']}")

    # ---- 付费卡点
    pw = nar.get("paywall") or {}
    if pw:
        lines.append("")
        lines.append("## 付费卡点设计")
        if pw.get("principle"):
            lines.append(f"> {pw['principle']}")
        hooks = pw.get("hook_types")
        if hooks:
            lines.append("- 可用断点:")
            lines += [f"  - {h.get('label', h.get('id'))}" for h in hooks]
        steps = pw.get("reverse_steps")
        if steps:
            lines.append("- 倒推步骤:")
            lines += [f"  {i}. {s}" for i, s in enumerate(steps, 1)]
        fails = pw.get("failures")
        if fails:
            lines.append("- 常见失败 → 修正:")
            lines += [f"  - {f.get('failure')} → {f.get('fix')}" for f in fails]

    # ---- 目标语言要点
    lines.append("")
    lines.append(f"## 目标语言要点({lang.get('name', target_lang)})")
    if lang.get("localization_goal"):
        lines.append(f"> {lang['localization_goal']}")
    addr = lang.get("address") or {}
    if addr.get("note"):
        lines.append(f"- 称呼:{addr['note']}")
    mis = lang.get("common_mistranslations") or []
    if mis:
        lines.append("- 常见误译(必须替换):")
        lines += [f"  - {m.get('cn')} → {m.get('en')}" + (f"({m['note']})" if m.get("note") else "")
                  for m in mis]
    punct = lang.get("punctuation") or {}
    if punct.get("note"):
        lines.append(f"- 标点:{punct['note']}")

    # ---- 改写级别
    levels = nar.get("rewrite_levels") or []
    if levels:
        lines.append("")
        lines.append("## 改写级别")
        for lv in levels:
            mark = " ←当前级别" if level and lv.get("id") == level else ""
            scope = "、".join(str(x) for x in lv.get("scope") or [])
            lines.append(f"- {lv.get('id')} {lv.get('name_zh')}(改动约 {lv.get('ratio')}):"
                         f"{lv.get('desc')}" + (f" —— 范围:{scope}" if scope else "") + mark)

    return "\n".join(lines)
