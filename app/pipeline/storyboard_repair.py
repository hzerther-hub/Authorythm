"""残缺分镜自动补全(对齐原版 daa17d0 / storyboard-repair.ts)。

storyboard_breaker 拆分整集时中途失败(超时/限流/重启)会留下"半成品分镜":
description / video_prompt 已写入,但 image_prompt 为空、storyboard_characters 为空
—— 无法出图、也不带参考图(UI 表现为「绑定参考图 0」)。

判定「残缺」:
  1. image_prompt 为空/纯空白                → 缺 image_prompt
  2. storyboard_characters 零行 且 description 含 @角色名 → 缺 character_links

修复:逐个调 prompt_generator,补 image_prompt + character_ids + prop_ids + scene_id。
成败以落库为准(不信 agent 自述):要求 image_prompt 非空且关联行数 > 0。
"""
from __future__ import annotations

import re

from ..agents import runner
from ..core import db

# @引用提取(对齐原版 referencedNames):@王德厚（王父）→ 王德厚
_AT_RE = re.compile(r"@([^\s@，。；：、!！?？)）]{1,20})")


def referenced_names(text: str) -> set[str]:
    names = set()
    for m in _AT_RE.finditer(text or ""):
        raw = m.group(1)
        raw = re.sub(r"[（(【\[].*", "", raw)  # 剥掉括号注释
        if raw:
            names.add(raw)
    return names


def is_incomplete(sb: dict) -> list[str]:
    """返回缺失项列表:['image_prompt'] / ['character_links'];完整则返回 []。"""
    missing: list[str] = []
    if not (sb.get("image_prompt") or "").strip():
        missing.append("image_prompt")
    n_links = db.q1("SELECT COUNT(*) c FROM storyboard_characters WHERE storyboard_id=?",
                     (sb["id"],))["c"]
    desc = sb.get("description") or sb.get("content") or ""
    if n_links == 0 and referenced_names(desc):
        missing.append("character_links")
    return missing


def list_incomplete(episode_id: int) -> list[dict]:
    out = []
    for sb in db.q("SELECT * FROM storyboards WHERE episode_id=? ORDER BY storyboard_number", (episode_id,)):
        sb = dict(sb)
        missing = is_incomplete(sb)
        if missing:
            out.append({"id": sb["id"], "storyboard_number": sb["storyboard_number"], "missing": missing})
    return out


REPAIR_PROMPT = """请补齐分镜 #{num}(ID:{sid})缺失的出图信息。

该分镜的画面描述:{desc}

请输出 JSON(只输出 JSON,不要解释):
1. image_prompt —— 出图提示词。基于画面描述写成可直接生图的英文提示词,
   描述本镜的景别、主体、光线、色调、氛围;不要出现 @ 标记。
2. character_names —— 本镜出场角色名数组(description 里用 @姓名 提到的都算)。
3. prop_names —— 本镜出现的道具名数组(没有就给空数组)。
4. scene_name —— 本镜所在场景名(根据描述匹配,匹配不到就给 null)。

不要重新拆分整集,不要改写画面描述与视频提示词。"""


def repair_storyboards(episode_id: int, storyboard_ids: list[int] | None = None,
                       config_id: int | None = None, lang: str | None = None,
                       progress=None) -> dict:
    """补全残缺分镜。storyboard_ids 传了就只处理所选(强制重跑)。返回统计。"""
    rows = db.q("SELECT * FROM storyboards WHERE episode_id=? ORDER BY storyboard_number", (episode_id,))
    targets = []
    for sb in rows:
        sb = dict(sb)
        if storyboard_ids:
            if sb["id"] in storyboard_ids:
                targets.append(sb)
        elif is_incomplete(sb):
            targets.append(sb)
    if not targets:
        return {"status": "idle", "total": 0, "completed": 0, "failed": 0}

    # 可选名 → 真实 id 映射
    chars = {r["name"]: r["id"] for r in db.q(
        "SELECT c.id, c.name FROM characters c JOIN episode_characters ec ON ec.character_id=c.id "
        "WHERE ec.episode_id=?", (episode_id,))}
    props = {r["name"]: r["id"] for r in db.q(
        "SELECT p.id, p.name FROM props p JOIN episode_props ep ON ep.prop_id=p.id "
        "WHERE ep.episode_id=?", (episode_id,))}
    scenes = {r["name"]: r["id"] for r in db.q(
        "SELECT s.id, s.name FROM scenes s JOIN episode_scenes es ON es.scene_id=s.id "
        "WHERE es.episode_id=?", (episode_id,))}

    total = len(targets)
    completed = failed = 0
    errors: list[str] = []
    for sb in targets:
        if progress:
            progress(completed + failed, total, f"#{sb['storyboard_number']}")
        prompt = REPAIR_PROMPT.format(
            num=sb["storyboard_number"], sid=sb["id"],
            desc=(sb.get("description") or sb.get("content") or "")[:1200])
        try:
            # 注意:run_agent_json 没有 temperature 形参(内部 _call_budgeted
            # 已固定 0.4)。这里曾误传 temperature=0.4,每次调用都 TypeError,
            # 被 except 吞掉后「补全残缺分镜」整个功能静默失效。
            data = runner.run_agent_json("prompt_generator", prompt, lang=lang,
                                         config_id=config_id)
            data = data if isinstance(data, dict) else {}
            ip = (data.get("image_prompt") or "").strip()
            if ip:
                db.ex("UPDATE storyboards SET image_prompt=?, updated_at=? WHERE id=?",
                      (ip, db.now(), sb["id"]))
            # 绑定(先清后建,保证幂等)
            db.ex("DELETE FROM storyboard_characters WHERE storyboard_id=?", (sb["id"],))
            for nm in (data.get("character_names") or []):
                cid = chars.get(nm)
                if cid:
                    db.ex("INSERT OR IGNORE INTO storyboard_characters(storyboard_id, character_id) VALUES(?,?)",
                          (sb["id"], cid))
            db.ex("DELETE FROM storyboard_props WHERE storyboard_id=?", (sb["id"],))
            for nm in (data.get("prop_names") or []):
                pid = props.get(nm)
                if pid:
                    db.ex("INSERT OR IGNORE INTO storyboard_props(storyboard_id, prop_id) VALUES(?,?)",
                          (sb["id"], pid))
            sn = data.get("scene_name")
            if sn and scenes.get(sn):
                db.ex("UPDATE storyboards SET scene_id=?, updated_at=? WHERE id=?",
                      (scenes[sn], db.now(), sb["id"]))
        except Exception as e:  # noqa: BLE001
            errors.append(f"#{sb['storyboard_number']}: {e}")
        # 成败以落库为准
        chk = db.q1("SELECT image_prompt FROM storyboards WHERE id=?", (sb["id"],))
        n_links = db.q1("SELECT COUNT(*) c FROM storyboard_characters WHERE storyboard_id=?",
                        (sb["id"],))["c"]
        if (chk and (chk["image_prompt"] or "").strip()) and n_links > 0:
            completed += 1
        else:
            failed += 1
    if progress:
        progress(total, total, "完成")
    return {"status": "done", "total": total, "completed": completed, "failed": failed,
            "errors": errors[:5]}
