"""人物状态台账 —— 长篇写作的「世界状态数据库」(对齐参考项目 backend/src/services/state-ledger.ts)。

解决的问题:长篇跨章生成时,人物年纪/功法/性格/财产/关系无交代地跳变。靠前情摘要(叙事层)
接不住结构化状态,台账是「世界现在是什么状态」的事实层。

三段流程(`update_state_ledger` 编排):
  1. 提取:`novel_reviewer` 单次调用读本章正文,输出结构化变更 diff
  2. 合并:diff 应用到 `dramas.novel_meta.state_ledger`(写作侧由 `_novel_settings_ctx` 注入)
  3. 门控:Jev(TypeSafe AI System One)对「台账 + 变更」做矛盾置信度判定,
     高置信矛盾追加到该集审校 issues(界面上随审校问题自然展示)

**软失败语义(全链路)**:
  - Jev 未配置 → 门控跳过,台账照常
  - Jev 连不通 → 熔断冷却(连续 2 次失败停 10 分钟),期间跳过门控
  - 提取失败 → 跳过本章,不阻断批量写作主流程

存储:`dramas.novel_meta` JSON 内(与伏笔/事实台账同住,免加列):
    state_ledger: {characters: {名字: {年纪,功法,性格,财产,外貌,位置,relations:{}, updated_chapter}},
                   world: {时间线, 主线进度, updated_chapter}, updated_chapter}
    state_diffs:  [{chapter, changes:[...], jev: {...}}]   保留最近 100 章
"""
from __future__ import annotations

import json
import os

from ..agents import runner
from ..ai.jev_gate import JevBreaker, get_jev_gate
from ..core import config, db

DIFFS_CAP = 100
# 熔断:连续失败到该次数后冷却,期间门控直接跳过(配置了但连不通 → 不用)
MIN_BODY_CHARS = 200

CHARACTER_DIMENSIONS = ["年纪", "功法", "性格", "财产", "外貌", "位置"]
WORLD_DIMENSIONS = ["时间线", "主线进度"]

_breaker = JevBreaker("state-ledger")   # 按作用域独立熔断(对齐 jev-gate)

OPS_PROMPT = """你是长篇小说的**状态台账管理员**。读完本章正文后,按下面的**强制自查清单**逐项过一遍,
只对**确实发生**的变化输出操作(没有就输出 no_change),不要推测、不要凑数。

【强制自查清单】
① 角色设定变化 —— 性格/财产/位置/关系/外貌/年纪/功法 有没有变化?
② 世界/时间线 —— 故事时间推进了多少?主线进度走到哪了?
③ 新伏笔 —— 本章埋下了什么需要后文回收的钩子?
④ 旧伏笔回收 —— 本章回收了哪些之前埋下的伏笔(对照【未回收伏笔】清单)?
⑤ 全部没有 → 只输出一个 no_change 操作。

人物维度限定:{dims};世界维度限定:{wdims}。每条附一句原文依据 quote(≤40字)。

【当前状态台账】
{ledger}

【未回收伏笔】
{foreshadow}

【本章正文】
{text}

只输出 JSON(ops 数组,每项一种操作):
{{"ops":[
 {{"op":"update_character","character":"人名","dimension":"年纪|功法|性格|财产|外貌|位置|关系","from":"旧值(无则空串)","to":"新值","target":"关系对象(仅关系维度)","quote":"原文依据"}},
 {{"op":"update_world","dimension":"时间线|主线进度","from":"","to":"","quote":"原文依据"}},
 {{"op":"open_foreshadow","text":"伏笔内容一句话(≤40字)","quote":"原文依据"}},
 {{"op":"resolve_foreshadow","text":"要回收的伏笔内容(与【未回收伏笔】清单里的表述接近)","quote":"原文依据"}},
 {{"op":"no_change"}}
]}}"""

GATE_QUESTIONS = {
    "conflict": {
        "type": "noul",
        "instructions": ("state 中「本章变更」是否与「人物状态台账」矛盾"
                         "(无铺垫的跳级/性格突变/已消耗财产再现/死者再现等)。1=明显矛盾,0=无矛盾"),
    },
    "magnitude": {
        "type": "score",
        "instructions": "本章状态变化整体的幅度",
        "criteria": ["微小", "一般", "重大"],
    },
}


# ── 台账读 / 写 ──
def get_state_ledger(drama_id: int) -> dict:
    """返回 {ledger, diffs};diffs 只带最近 20 条(对齐参考项目 GET /novel/state-ledger)。"""
    meta = _meta(drama_id)
    ledger = meta.get("state_ledger") or {}
    diffs = meta.get("state_diffs")
    diffs = diffs[-20:] if isinstance(diffs, list) else []
    return {"ledger": ledger, "diffs": diffs}


def ledger_for_context(drama_id: int) -> dict | None:
    """写作上下文里的台账注入:只取最近更新的 10 个角色,防上下文膨胀。"""
    ledger = (_meta(drama_id).get("state_ledger") or None)
    if not isinstance(ledger, dict):
        return None
    chars = ledger.get("characters") or {}
    ranked = sorted(chars.items(),
                    key=lambda kv: int((kv[1] or {}).get("updated_chapter") or 0),
                    reverse=True)[:10]
    return {"characters": dict(ranked), "world": ledger.get("world") or None,
            "updated_chapter": ledger.get("updated_chapter")}


def _meta(drama_id: int) -> dict:
    row = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
    return db.jload(row["novel_meta"], {}) if row else {}


def _save_meta(drama_id: int, meta: dict) -> None:
    db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))


def _compact_ledger(ledger: dict, names: list) -> str:
    """只保留本章涉及的角色 + world,作为 Jev 门控的 state 输入。"""
    out: dict = {"characters": {}, "world": ledger.get("world") or None}
    chars = ledger.get("characters") or {}
    for name in names:
        if name in chars:
            out["characters"][name] = chars[name]
    return json.dumps(out, ensure_ascii=False)


def merge_ledger(ledger: dict, changes: list, chapter: int) -> bool:
    """把变更合并进台账(白名单维度外的丢弃;关系维度走 relations 子对象)。"""
    if not changes:
        return False
    ledger.setdefault("characters", {})
    changed = False
    for c in changes:
        name, dim, to = c.get("character"), c.get("dimension"), c.get("to")
        if not name or not to:
            continue
        if dim == "关系" and c.get("target"):
            ch = ledger["characters"].setdefault(name, {"relations": {}})
            ch.setdefault("relations", {})[c["target"]] = str(to)[:80]
            ch["updated_chapter"] = chapter
            changed = True
            continue
        if dim not in CHARACTER_DIMENSIONS:
            continue
        ch = ledger["characters"].setdefault(name, {})
        ch[dim] = str(to)[:80]
        ch["updated_chapter"] = chapter
        changed = True
    return changed


# ── Jev 门控 ──
def jev_gate_state_diff(ledger: dict, changes: list) -> dict:
    """台账+变更是否矛盾。任何失败都返回 skipped —— 门控绝不阻断写作主流程。"""
    at = db.now()
    def skip(reason):
        return {"enabled": True, "verdict": "skipped", "reason": reason, "at": at}
    if not changes:
        return {"enabled": True, "verdict": "ok", "reason": "no-changes", "at": at}
    if _breaker.in_cooldown():
        return skip(_breaker.skip_reason())
    gate = get_jev_gate()
    if not gate.usable:
        return {"enabled": not gate.disabled, "verdict": "skipped",
                "reason": gate.reason or "unconfigured", "at": at}
    client = gate.client
    names = sorted({c["character"] for c in changes if c.get("character")})
    state = _compact_ledger(ledger, names) + "\n本章变更:" + json.dumps(changes, ensure_ascii=False)
    result = client.decide(state, GATE_QUESTIONS)
    if not result or not result.get("answers"):
        _breaker.note_fail()
        return skip("jev-unreachable")
    _breaker.note_ok()
    conflict = _num((result["answers"].get("conflict") or {}).get("noul"))
    magnitude = _num((result["answers"].get("magnitude") or {}).get("score"))
    threshold = _num(os.environ.get("JEV_LEDGER_MIN_CONFLICT"), 0.7)
    conflicted = conflict is not None and conflict >= threshold
    return {"enabled": True, "conflict": conflict, "magnitude": magnitude,
            "verdict": "conflict" if conflicted else "ok", "at": at}


def _num(value, default=None):
    try:
        f = float(value)
        return f
    except (TypeError, ValueError):
        return default


# ── 编排入口 ──
def resolve_text_config_id_for_model(model: str | None) -> int | None:
    """按模型名反查承载它的活跃文本配置 id。

    同名模型可挂在多个 provider 下(如 deepseek-v4-pro 同时出现在 OpenAI 兼容网关 / 官方),
    只传模型名不传 config_id 时会用「当前启用配置」的 provider/base_url 去请求该模型名 → 配错网关
    (原版实测报 2013 unknown model)。在活跃 text 配置里找 model 含该名字的那条,
    让「选什么模型就跟什么配置配合」对任意新增模型自动成立。
    """
    if not model:
        return None
    from ..ai import registry
    for r in registry.list_configs("text"):
        if not r["is_active"]:
            continue
        names = db.jload(r["models"], []) if r.get("models") else []
        if isinstance(names, str):
            names = [names]
        if any(str(m).lower() == model.lower() for m in names or []):
            return r["id"]
    return None


def _open_foreshadow_ctx(drama_id: int) -> str:
    """未回收伏笔清单(给台账模型的自查对照)。空返回占位文案。"""
    try:
        meta = _meta(drama_id)
        items = meta.get("ledger") or []
        open_items = [f"- {it.get('text', '')}" for it in items
                      if isinstance(it, dict) and not it.get("closed") and it.get("text")]
        return "\n".join(open_items[:12]) if open_items else "(无未回收伏笔)"
    except Exception:  # noqa: BLE001
        return "(无未回收伏笔)"


def _apply_foreshadow_ops(drama_id: int, ops: list, chapter_hint: int | None = None) -> int:
    """把 open_foreshadow / resolve_foreshadow 操作落到伏笔台账。

    伏笔数据在 novel_meta.ledger(novel.py 管理);这里惰性导入它的去重/封顶
    逻辑避免循环导入。返回应用的条数。
    """
    if not ops:
        return 0
    try:
        from . import novel as _novel
    except Exception:  # noqa: BLE001
        return 0
    meta = _meta(drama_id)
    items = meta.get("ledger") or []
    applied = 0
    chapter = chapter_hint or 0
    for kind, txt, _quote in ops:
        if kind == "open_foreshadow":
            items.append({"text": txt, "open_chapter": chapter,
                          "closed": False, "closed_chapter": None, "stale": False})
            applied += 1
        elif kind == "resolve_foreshadow":
            # 按文本相似匹配未回收项(与 dedup 同款 LCS 判同思路,这里宽松包含匹配)
            hit = next((it for it in items
                        if isinstance(it, dict) and not it.get("closed")
                        and (txt[:10] in str(it.get("text", ""))
                             or str(it.get("text", ""))[:10] in txt)), None)
            if hit is not None:
                hit["closed"] = True
                hit["closed_chapter"] = chapter or hit.get("open_chapter")
                hit["stale"] = False
                applied += 1
    if applied:
        items = _novel.dedup_ledger(items)
        items = _novel.cap_ledger(items)
        meta["ledger"] = items
        _save_meta(drama_id, meta)
    return applied


def update_state_ledger(drama_id: int, episode_id: int, config_id: int | None = None,
                        model: str | None = None) -> dict | None:
    """章节正文完成后调用(批量流水线每章一次;也可手动重跑)。返回 {changes, jev} 或 None。"""
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    text = (ep["content"] or "") if ep else ""
    if len(text.strip()) < MIN_BODY_CHARS:
        return None
    meta = _meta(drama_id)
    ledger = meta.get("state_ledger") or {"characters": {}, "world": {}}

    # 1) 提取(工具化:模型按自查清单决定输出哪种台账操作)
    foreshadow_ctx = _open_foreshadow_ctx(drama_id)
    prompt = OPS_PROMPT.format(
        dims="/".join(CHARACTER_DIMENSIONS), wdims="/".join(WORLD_DIMENSIONS),
        ledger=json.dumps(ledger, ensure_ascii=False)[:2500],
        foreshadow=foreshadow_ctx, text=text[:6000])
    # 提取模型跟随本次写作选中的文本模型(顶栏下拉),与正文同一模型保持判断口径一致;
    # 只给了模型名时反查承载它的配置,防配错网关。
    if config_id is None and model:
        config_id = resolve_text_config_id_for_model(model)
    try:
        raw = runner.run_agent("novel_reviewer", prompt, temperature=0.2, config_id=config_id,
                            lang=config.resolve_content_language(drama_id))
        # `or {}` 只挡得住 None,挡不住「模型直接回了 JSON 数组」——数组是真值,
        # 后面 parsed.get 会 AttributeError,而且 222 行起已在 try 之外,
        # 手动重跑入口会把这个内部错误原样抛给 UI。统一压成 dict。
        parsed = runner.extract_json(raw)
        parsed = parsed if isinstance(parsed, dict) else {}
    except Exception:  # noqa: BLE001 —— 提取失败不阻断批量写作
        return None

    changes_raw = []
    world_ops = []               # update_world 操作(旧格式从 parsed["world"] 取)
    foreshadow_ops = []          # open/resolve 交给伏笔台账
    ops = parsed.get("ops")
    if isinstance(ops, list):
        # 工具化输出:模型按自查清单自己决定调哪种操作
        for op in ops[:24]:
            if not isinstance(op, dict):
                continue
            kind = str(op.get("op") or "").strip()
            if kind == "update_character":
                changes_raw.append({
                    "character": str(op.get("character") or "").strip(),
                    "dimension": str(op.get("dimension") or "").strip(),
                    "from": str(op.get("from") or ""),
                    "to": str(op.get("to") or ""),
                    "target": str(op.get("target") or "").strip() or None,
                    "quote": str(op.get("quote") or "")[:60],
                })
            elif kind == "update_world":
                world_ops.append({
                    "character": "世界",
                    "dimension": str(op.get("dimension") or "").strip(),
                    "from": str(op.get("from") or ""),
                    "to": str(op.get("to") or ""),
                    "quote": str(op.get("quote") or "")[:60],
                })
            elif kind in ("open_foreshadow", "resolve_foreshadow"):
                txt = str(op.get("text") or "").strip()
                if txt:
                    foreshadow_ops.append((kind, txt,
                                           str(op.get("quote") or "")[:60]))
            elif kind == "no_change":
                pass
    else:
        # 旧格式兼容:模型没按 ops 输出时仍认 {"changes":[...]}
        for c in (parsed.get("changes") or [])[:20]:
            if not isinstance(c, dict):
                continue
            changes_raw.append({
                "character": str(c.get("character") or "").strip(),
                "dimension": str(c.get("dimension") or "").strip(),
                "from": str(c.get("from") or ""),
                "to": str(c.get("to") or ""),
                "target": str(c.get("target") or "").strip() or None,
                "quote": str(c.get("quote") or "")[:60],
            })
    # 无效变更过滤:from == to(模型偶尔把「未变化」也报上来,如 位置:旅店→旅店)
    changes = [c for c in changes_raw if not (c["from"] and c["to"] and c["from"] == c["to"])]
    # 伏笔操作:借道 novel.py 的伏笔台账(去重/封顶都在那边),惰性导入防循环
    foreshadow_applied = _apply_foreshadow_ops(drama_id, chapter_hint=None,
                                               ops=foreshadow_ops) if foreshadow_ops else 0
    world = []
    for w in ([*world_ops, *(parsed.get("world") or [])][:6]):
        if not isinstance(w, dict):
            continue
        dim = str(w.get("dimension") or "").strip()
        to = str(w.get("to") or "")
        if to and dim in WORLD_DIMENSIONS:
            world.append({"character": "世界", "dimension": dim, "from": str(w.get("from") or ""),
                          "to": to, "quote": str(w.get("quote") or "")[:60]})

    # 2) 合并
    chapter = int(ep["episode_number"] or 0)
    merge_ledger(ledger, changes, chapter)
    if world:
        ledger["world"] = ledger.get("world") or {}
        for w in world:
            ledger["world"][w["dimension"]] = w["to"][:80]
        ledger["world"]["updated_chapter"] = chapter
    ledger["updated_chapter"] = chapter
    meta["state_ledger"] = ledger

    # 3) 门控
    all_changes = changes + world
    jev = jev_gate_state_diff(ledger, all_changes)

    # 4) 持久化 + 高置信矛盾写回该集审校 issues
    diffs = meta.get("state_diffs")
    diffs = diffs if isinstance(diffs, list) else []
    meta["state_diffs"] = ([*diffs, {"chapter": chapter, "changes": all_changes, "jev": jev}])[-DIFFS_CAP:]
    _save_meta(drama_id, meta)
    if jev.get("verdict") == "conflict":
        _write_back_conflict(episode_id, all_changes, jev)
    return {"changes": len(all_changes), "jev": jev,
            "foreshadow": foreshadow_applied}


def _write_back_conflict(episode_id: int, changes: list, jev: dict):
    """矛盾写进该集审校 issues —— 界面上随审校问题自然展示,不另开入口。"""
    row = db.q1("SELECT review_json FROM episodes WHERE id=?", (episode_id,))
    review = db.jload(row["review_json"], {}) if row else {}
    if not isinstance(review, dict):
        review = {}
    top = changes[0] if changes else {}
    desc = f"{top.get('character', '')}{top.get('dimension', '')}:{top.get('from') or '∅'}→{top.get('to', '')}" if top else ""
    pct = round((jev.get("conflict") or 0) * 100)
    msg = f"状态台账疑似矛盾(置信度 {pct}%):{desc}"[:160]
    issues = review.get("issues")
    issues = issues if isinstance(issues, list) else []
    review["issues"] = ([*issues, msg])[-12:]
    db.ex("UPDATE episodes SET review_json=?, updated_at=? WHERE id=?",
          (json.dumps(review, ensure_ascii=False), db.now(), episode_id))
