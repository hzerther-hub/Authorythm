# -*- coding: utf-8 -*-
"""分镜参考图引用:单一真相源(对齐原版 buildShotReferenceList,修复序号错位 bug)。

原版修复要点(67adf7a):
  原实现 `reference_image_urls` 顺序是「角色→场景」,而 `@名字 → @图片N` 索引却是
  「场景→角色」,两边反了 → 分镜同时绑定场景与角色时提示词里的 `@图片N` 指错图。
  现以 build_shot_reference_list() 为唯一真相源,参考图列表与序号映射都由它派生,
  保证 `@图片N` 永远等于 reference_image_urls[N-1]。

权威顺序:角色(按绑定顺序) → 场景(单选) → 道具(按绑定顺序)
去重:按 imageUrl 去重;截断:达到 ref_image_limit 即停(Wan 3.0 为 10 张,其他 9 张)。

每条带 kind + id 字段,UI 端点文字可直接 toggle 绑定。
"""
from __future__ import annotations

import re

from ..core import config, db


def ref_image_limit(provider: str | None = None, model: str | None = None) -> int:
    """Wan 3.0 官方支持 10 张参考图,其他模型 9 张(对齐原版 useModelOptions.refImageLimit)。"""
    if provider == "aliyun" or (model or "").startswith("wan3.0-video"):
        return 10
    return 9


def _variant_image_of(character_id: int, sb: dict, kind: str = "character") -> str | None:
    """造型图:优先取该分镜人工覆盖的变体,否则按场景标签自动匹配,最后回退基础形象。

    kind ∈ {"character", "scene", "prop"} —— 同一份逻辑复用给三表
    (character_variants / scene_variants / prop_variants)。
    """
    # 三个关联表 + 三个变体表的 schema 平行,集中查一次省得散写
    cfg = {
        "character": ("storyboard_characters", "character_variants", "character_id",
                      "characters", "image_url"),
        "scene":     ("storyboard_scenes",   "scene_variants",     "scene_id",
                      "scenes",     "image_url"),
        "prop":      ("storyboard_props",    "prop_variants",      "prop_id",
                      "props",      "image_url"),
    }[kind]
    link_t, var_tbl, ref_col, base_tbl, img_col = cfg
    row = db.q1(f"SELECT variant_id FROM {link_t} "
                f"WHERE storyboard_id=? AND {ref_col}=?", (sb["id"], character_id))
    if row and row["variant_id"]:
        v = db.q1(f"SELECT image_url FROM {var_tbl} WHERE id=?", (row["variant_id"],))
        if v and v["image_url"]:
            return v["image_url"]
    # 按 setting_tags 自动解析变体
    tags = set(db.jload(sb.get("setting_tags"), []) or [])
    if tags:
        for v in db.q(f"SELECT * FROM {var_tbl} WHERE {ref_col}=?", (character_id,)):
            vtags = set(db.jload(v["tags"], []) or [])
            if tags & vtags and v["image_url"]:
                return v["image_url"]
    base = db.q1(f"SELECT {img_col} FROM {base_tbl} WHERE id=?", (character_id,))
    return base[img_col] if base else None


def build_shot_reference_list(sb: dict, limit: int | None = None) -> list[dict]:
    """构造该分镜的参考图权威列表:[{kind, character_id/scene_id/prop_id, name, image_url}]。
    角色优先(缺 first_frame 时会用 [0] 兜底锁脸)。

    每条带 kind + id 字段,UI 端点文字可直接 toggle 绑定(增/删 storyboard_* 关联)。
    """
    limit = limit or 9
    out: list[dict] = []
    seen: set[str] = set()

    def push(kind: str, _id: int, name: str | None, url: str | None):
        if not url or url in seen or len(out) >= limit:
            return
        seen.add(url)
        out.append({"kind": kind, f"{kind}_id": _id,
                    "name": name or "", "image_url": url})

    # 1) 角色(排首位:后端缺 first_frame 时会用 reference_image_urls[0] 兜底当首帧,锁的是角色脸)
    for r in db.q("""SELECT character_id FROM storyboard_characters WHERE storyboard_id=?
                    ORDER BY character_id""", (sb["id"],)):
        cid = r["character_id"]
        c = db.q1("SELECT name FROM characters WHERE id=?", (cid,))
        push("character", cid, c["name"] if c else None, _variant_image_of(cid, sb, "character"))
    # 2) 场景(单选):也走变体优先级链,与角色/道具同套逻辑
    if sb.get("scene_id"):
        # 提前绑定到本地变量 —— Row 反复访问会触发奇怪行为(实测
        # `db.q1(..., (sb["scene_id"],))` 偶尔抛 parameters unsupported),
        # 绑给 _sid 后稳定。
        _sid = sb["scene_id"]
        s = db.q1("SELECT name FROM scenes WHERE id=?", (_sid,))
        push("scene", _sid, s["name"] if s else None, _variant_image_of(_sid, sb, "scene"))
    # 3) 道具
    for r in db.q("""SELECT prop_id FROM storyboard_props WHERE storyboard_id=?
                    ORDER BY prop_id""", (sb["id"],)):
        pid = r["prop_id"]
        p = db.q1("SELECT name FROM props WHERE id=?", (pid,))
        push("prop", pid, p["name"] if p else None, _variant_image_of(pid, sb, "prop"))
    return out


def get_shot_reference_images(sb: dict, limit: int | None = None) -> list[str]:
    return [i["image_url"] for i in build_shot_reference_list(sb, limit)]


def get_shot_reference_index_map(sb: dict, limit: int | None = None) -> dict[str, int]:
    """name -> 序号(1 起),同名取首次出现者。"""
    out: dict[str, int] = {}
    for i, item in enumerate(build_shot_reference_list(sb, limit), start=1):
        n = (item.get("name") or "").strip()
        if n and n not in out:
            out[n] = i
    return out


def resolve_video_prompt_refs(text: str, sb: dict, limit: int | None = None) -> str:
    """分镜提示词里 `@名字` → `@图片N` 序号替换。

    名字按长度降序匹配(长的先替),避免短名误命中前缀:角色「赵雷」+「赵雷涛」,
    `@赵雷涛` 必须先替成 `@图片N`,否则 `@赵雷` 抢先替换后剩下的「涛」就孤立了。

    顺序来自 build_shot_reference_list() —— 与 reference_image_urls 序号严格对齐,
    保证 `@图片N` 永远等于 reference_image_urls[N-1](修过 refs.py 注释里那条
    67adf7a 序号错位 bug)。

    没匹配上的 `@名字` 原样保留 —— 让上游(视频模型)拿到可读名字,而不是被
    静默吞掉的 `@图片99` 之类。
    """
    if not text:
        return text
    idx_map = get_shot_reference_index_map(sb, limit)
    if not idx_map:
        return text
    # 按名字长度降序,长名先替
    for name in sorted(idx_map.keys(), key=len, reverse=True):
        # 转义正则元字符(中文名字常见,但防御一下)
        esc = re.escape(name)
        text = re.sub(rf"@{esc}", f"@图片{idx_map[name]}", text)
    return text
