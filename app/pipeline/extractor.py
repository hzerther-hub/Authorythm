# -*- coding: utf-8 -*-
"""阶段③:从剧本提取角色/场景/道具并去重(extractor Agent),写库+关联本集。"""
from __future__ import annotations

import json

from ..agents import prompts, runner
from ..core import db

ROLE_MAP = {"lead": "lead", "supporting": "supporting", "extra": "extra",
            "主角": "lead", "配角": "supporting", "龙套": "extra"}

# extractor.md 是给**带工具的 Mastra Agent** 写的(读剧本/写库都靠工具调用)。
# 本仓 runner 只是单次 chat,没有工具:不覆盖 system 时模型会返回
# {"name": "read_script_for_extraction", "arguments": {...}} —— 合法 JSON,
# 但调用方拿不到 characters/scenes/props,表现为「提取 0 条」或解析失败。
# 预算给 32768:MiniMax-M3 这类推理模型在 8192 下会把预算全烧在 <think> 上,
# 正文 JSON 根本没开始写(实测两次 extract 任务都是 reasoning-only)。
EXTRACT_MAX_TOKENS = 32768
_EXTRACT_JSON_SUFFIX = """

【本次运行环境没有工具】不要调用 read_script_for_extraction / read_existing_* /
save_dedup_* 等任何工具,也不要输出 {"name": "...", "arguments": {...}} 形式的
工具调用。直接输出最终结果的 JSON 对象,结构:
{"characters":[{"name":"","role_type":"lead|supporting|extra","appearance":"","styling":"","ethnicity_override":null,"variants":[{"label":"","tags":[],"costume_desc":""}]}],
 "scenes":[{"location":"","time":"","prompt":"","lighting":"","setting_tags":[]}],
 "props":[{"name":"","type":"","description":""}]}
只输出这个 JSON,不要解释、不要 Markdown 代码块。"""


def _save_variants(character_id: int, raw, ts: str) -> int:
    """落库角色造型变体草稿(extractor 只给 label/tags/costume_desc,不含图)。

    此前模型按模板产出的 variants 被整包丢弃 —— character_variants 永远为空,
    分镜侧的「造型变体」下拉也就永远没有选项。同名 label 已存在时跳过,保证
    重跑提取不会灌出重复变体(角色去重本身已在主循环里跳过了已存在的角色,
    这里只需防同一次返回内的重名)。
    """
    if not isinstance(raw, list):
        return 0
    have = {r["label"] for r in db.q(
        "SELECT label FROM character_variants WHERE character_id=?", (character_id,))}
    n = 0
    for i, v in enumerate(raw):
        if not isinstance(v, dict):
            continue
        label = (v.get("label") or "").strip()
        if not label or label in have:
            continue
        have.add(label)
        tags = v.get("tags")
        db.ex("INSERT INTO character_variants(character_id,label,tags,costume_desc,"
              "is_default,sort_order,created_at) VALUES(?,?,?,?,0,?,?)",
              (character_id, label,
               json.dumps(tags if isinstance(tags, list) else [], ensure_ascii=False),
               (v.get("costume_desc") or "").strip(), i, ts))
        n += 1
    return n


def extract_assets(episode_id: int, config_id: int | None = None, lang: str | None = None) -> dict:
    """提取并入库;返回统计。与项目已有资产按名字去重(同名更新描述,否则新增)。"""
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("剧集不存在")
    drama_id = ep["drama_id"]
    script = ep["script_content"] or ep["content"] or ""
    if not script.strip():
        raise RuntimeError("请先完成剧本(原始内容 / AI 改写)")

    existing = {
        "characters": [r["name"] for r in db.q("SELECT name FROM characters WHERE drama_id=?", (drama_id,))],
        "scenes": [r["name"] for r in db.q("SELECT name FROM scenes WHERE drama_id=?", (drama_id,))],
        "props": [r["name"] for r in db.q("SELECT name FROM props WHERE drama_id=?", (drama_id,))],
    }
    d = db.q1("SELECT title, novel_style, style, metadata FROM dramas WHERE id=?", (drama_id,))
    meta = db.jload(d["metadata"], {}) or {} if d else {}
    ctx = ""
    if d:
        parts = [f"题材:{meta.get('genre', '') or '未定'}", f"简介:{meta.get('intro', '') or '未定'}"]
        if (d["novel_style"] or "").strip():
            parts.append(f"写法文风:{d['novel_style'].strip()}")
        ctx = "作品设定(据此匹配场景年代/道具质感/语言风格,不要脱离):\n" + "\n".join(parts) + "\n\n"
    prompt = f"""{ctx}剧本(第 {ep['episode_number']} 集):
{script[:12000]}

项目已有资产(不要重复提取):
角色: {', '.join(existing['characters']) or '无'}
场景: {', '.join(existing['scenes']) or '无'}
道具: {', '.join(existing['props']) or '无'}"""
    system = prompts.load_prompt("extractor", lang) + _EXTRACT_JSON_SUFFIX
    data = runner.run_agent_json("extractor", prompt, lang=lang, config_id=config_id,
                                 system=system, max_tokens=EXTRACT_MAX_TOKENS)
    ts = db.now()
    stat = {"characters": 0, "scenes": 0, "props": 0, "variants": 0}
    # 已存在资产也必须关联到本集:原实现遇到同名直接 continue,于是「分卷规划
    # 已建好 9 个角色」时提取跑完、本集资产列表却仍然是空的(实测 episode_characters=0)。
    char_ids = {r["name"]: r["id"] for r in db.q(
        "SELECT id,name FROM characters WHERE drama_id=?", (drama_id,))}
    scene_ids = {r["name"]: r["id"] for r in db.q(
        "SELECT id,name FROM scenes WHERE drama_id=?", (drama_id,))}
    prop_ids = {r["name"]: r["id"] for r in db.q(
        "SELECT id,name FROM props WHERE drama_id=?", (drama_id,))}

    for c in data.get("characters", []) or []:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        cid = char_ids.get(name)
        if cid:
            db.ex("INSERT OR IGNORE INTO episode_characters(episode_id,character_id) VALUES(?,?)",
                  (episode_id, cid))
            continue
        # 关键:新插入的名字要回写 existing,否则同一次返回里出现两次同名
        # 会被当成两个不同角色各插一条(实测 张雯/赵刚/王经理 各重复 3-4 条)
        existing["characters"].append(name)
        cid = db.ex(
            "INSERT INTO characters(drama_id,name,role_type,appearance,styling,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (drama_id, name, ROLE_MAP.get(c.get("role_type", "supporting"), "supporting"),
             c.get("appearance", ""), c.get("styling", ""), ts, ts))
        char_ids[name] = cid
        db.ex("INSERT OR IGNORE INTO episode_characters(episode_id,character_id) VALUES(?,?)", (episode_id, cid))
        stat["characters"] += 1
        # 造型变体草稿:与角色同批落库,否则模型算完就丢
        stat["variants"] += _save_variants(cid, c.get("variants"), ts)

    for s in data.get("scenes", []) or []:
        # 场景主字段是 location(对齐参考项目 save_dedup_scenes 的 schema:
        # {location, time, prompt, lighting}),模型不会给场景起 "name";
        # 曾只读 name 导致场景条目全部判空被跳过 —— "重提场景"永远 0 个
        name = (s.get("location") or s.get("name") or "").strip()
        if not name:
            continue
        sid = scene_ids.get(name)
        if sid:
            db.ex("INSERT OR IGNORE INTO episode_scenes(episode_id,scene_id) VALUES(?,?)",
                  (episode_id, sid))
            continue
        existing["scenes"].append(name)          # 同上:回写,防同批重复插入
        sid = db.ex(
            "INSERT INTO scenes(drama_id,episode_id,name,location,time,prompt,lighting,setting_tags,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (drama_id, episode_id, name, s.get("location", ""), s.get("time", ""),
             s.get("prompt", ""), s.get("lighting", ""),
             json.dumps(s.get("setting_tags", []), ensure_ascii=False), ts, ts))
        scene_ids[name] = sid
        db.ex("INSERT OR IGNORE INTO episode_scenes(episode_id,scene_id) VALUES(?,?)", (episode_id, sid))
        stat["scenes"] += 1

    for p in data.get("props", []) or []:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        pid = prop_ids.get(name)
        if pid:
            db.ex("INSERT OR IGNORE INTO episode_props(episode_id,prop_id) VALUES(?,?)",
                  (episode_id, pid))
            continue
        existing["props"].append(name)           # 同上
        pid = db.ex(
            "INSERT INTO props(drama_id,name,type,description,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (drama_id, name, p.get("type", "prop"), p.get("description", ""), ts, ts))
        prop_ids[name] = pid
        db.ex("INSERT OR IGNORE INTO episode_props(episode_id,prop_id) VALUES(?,?)", (episode_id, pid))
        stat["props"] += 1

    db.touch("episodes", episode_id)
    return stat
