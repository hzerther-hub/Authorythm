# -*- coding: utf-8 -*-
"""阶段⑤:剧本 → 漫画格(comic_board Agent)+ 旁白补齐 + 长条图拼接。"""
from __future__ import annotations

from ..agents import runner
from ..core import config, db


def split_panels(episode_id: int, config_id: int | None = None, lang: str | None = None) -> int:
    """整集重新生成漫画分镜格;返回格数。"""
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("剧集不存在")
    script = ep["script_content"] or ep["content"] or ""
    if not script.strip():
        raise RuntimeError("请先完成剧本")
    # 关键:comic_board 的系统提示词让模型「调用 read_drama_assets 取资产」,
    # 而 run_agent_json 是**单次无工具**调用 —— 模型照着提示词发工具调用,
    # 我们给不了,就永远吐不出 JSON(实测返回 <think>…</think> + [Tool: read_drama_assets];
    # 另一模型返回 {"name":…,"parameters":…} 函数信封)。这里把资产**直接内联**进提示词。
    d_id = ep["drama_id"]
    assets = ["【本集可用的视觉资产(已全部给出,不要再调用任何工具读取)】"]
    for label, table, cols in (
        ("角色", "characters", ("name", "appearance", "styling")),
        ("场景", "scenes", ("name", "prompt", "lighting")),
        ("道具", "props", ("name", "description")),
    ):
        rows = db.q(f"SELECT {','.join(cols)} FROM {table} WHERE drama_id=? LIMIT 12", (d_id,))
        if not rows:
            continue
        assets.append(f"— {label} —")
        for r in rows:
            bits = " / ".join(str(r[c] or "")[:90] for c in cols[1:])
            assets.append(f"  {r[cols[0]]}: {bits}")
    assets.append("以上即全部可用资产;某镜所需资产不在表中时,按剧本文字描述作画。")
    prompt = ("\n".join(assets) + "\n\n"
              + f"剧本(第 {ep['episode_number']} 集):\n{script[:14000]}\n\n"
              + "你现在**没有任何工具**,资产已在上方直接给全。禁止输出 <think>、"
                "[Tool: ...]、函数调用或任何解释,只输出一个 JSON 对象。")
    data = runner.run_agent_json("comic_board", prompt, lang=lang, config_id=config_id)
    # 兼容函数调用信封:部分模型会把内容包在 {"name":…,"parameters":{"panels":[…]}}
    if isinstance(data, dict) and not data.get("panels") and isinstance(data.get("parameters"), dict):
        data = data["parameters"]
    panels = data.get("panels") or (data if isinstance(data, list) else [])
    if not panels:
        raise RuntimeError("漫画分镜结果为空")
    ts = db.now()
    db.ex("DELETE FROM comic_panels WHERE episode_id=?", (episode_id,))
    for i, p in enumerate(panels, start=1):
        db.ex(
            "INSERT INTO comic_panels(episode_id,panel_number,description,dialogue,composition,narration,image_prompt,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (episode_id, int(p.get("number") or i), p.get("description", ""), p.get("dialogue", "无"),
             p.get("composition", ""), p.get("narration", ""), "", ts, ts))
    db.touch("episodes", episode_id)
    return len(panels)


def _style_for(drama_id: int, style_value: str = "") -> str:
    """项目风格串 + 人物面孔文化片段(角色级覆盖由 prompts_gen 处理)。"""
    d = db.q1("SELECT style, ethnicity, language FROM dramas WHERE id=?", (drama_id,))
    value = style_value or (d["style"] if d else "3d")
    return db.style_prompt(value or "3d",
                           ethnicity=(d["ethnicity"] if d else "") or "",
                           content_lang=(d["language"] if d else "") or "")


def panel_people_count(panel_id: int) -> int:
    """该格绑定的人物数(对齐原版 routes/comic.ts 的 peopleCount)。"""
    n = db.q1("SELECT COUNT(*) c FROM comic_panel_characters WHERE panel_id=?", (panel_id,))["c"]
    return max(1, int(n or 0))


def panel_image_prompt(panel_id: int, drama_id: int, config_id: int | None = None) -> str:
    """单格出图提示词:画面+构图+对白气泡说明,注入项目风格前缀 + 人数硬前缀。"""
    p = db.q1("SELECT * FROM comic_panels WHERE id=?", (panel_id,))
    if not p:
        raise RuntimeError("漫画格不存在")
    style = _style_for(drama_id)
    prompt = f"""目标类型:comic_panel(条漫单格画面,画幅竖版)
视觉风格前缀: {style}

画面: {p['description']}
构图: {p['composition']}
台词(画面内以对话气泡呈现): {p['dialogue']}"""
    data = runner.run_agent_json("prompt_generator", prompt, config_id=config_id)
    fp = _pick_prompt_text(data)
    if not fp:
        # 模型没给出可用字段(键名随模型自由发挥,见过 final_prompt / panel_prompt / prompt)
        # 就地兜底用原文拼,绝不能把空串送去生图接口 —— 那边只会回 prompt is required
        fp = prompt
    # 人数硬前缀放在最前:模型先读到「恰好 N 人」,比只在末尾写约束更稳
    from ..ai.prompt_guards import comic_people_prefix
    fp = comic_people_prefix(panel_people_count(panel_id)) + "\n" + fp
    db.ex("UPDATE comic_panels SET image_prompt=?, updated_at=? WHERE id=?", (fp, db.now(), panel_id))
    return fp


def _pick_prompt_text(data: object) -> str:
    """从 agent 返回里取出提示词正文。

    prompt_generator 模板没有钉死输出键名,同一模板在不同模型上出现过
    final_prompt / panel_prompt / prompt / image_prompt 各种写法,只认一个键
    就会静默取到空串。这里按优先级逐个找,兼容嵌套一层。
    """
    if isinstance(data, str):
        return data.strip()
    if not isinstance(data, dict):
        return ""
    for key in ("final_prompt", "panel_prompt", "comic_prompt", "image_prompt", "prompt"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    for v in data.values():          # 嵌一层,例如 {"panel": {"prompt": ...}}
        if isinstance(v, dict):
            got = _pick_prompt_text(v)
            if got:
                return got
        elif isinstance(v, str) and len(v.strip()) > 40:
            return v.strip()
    return ""


def comic_asset_image(drama_id: int, kind: str, row_id: int, config_id: int | None = None) -> str:
    """资产行的漫画风格镜像图(角色/场景/道具),写 comic_image_url;返回 URL。"""
    from ..ai import image_client
    # 调用方有的传单数("character"),有的直接传表名("characters"),统一归一,
    # 否则单张「重画」会 KeyError: 'characters'
    kind = {"characters": "character", "scenes": "scene",
            "props": "prop"}.get(kind, kind)
    table = {"character": "characters", "scene": "scenes", "prop": "props"}[kind]
    row = db.q1(f"SELECT * FROM {table} WHERE id=?", (row_id,))
    if not row:
        raise RuntimeError("资产不存在")
    d = db.q1("SELECT comic_style, style FROM dramas WHERE id=?", (drama_id,))
    style = _style_for(drama_id, style_value=d["comic_style"] or d["style"] or "3d")
    if kind == "character":
        spec = f"角色三视图参考图(左正脸特写+正/侧/背三张全身), 角色: {row['name']}, 样貌: {row['appearance'] or ''}, 服装: {row['styling'] or ''}"
    elif kind == "scene":
        spec = f"场景空镜建立图(三层构图,无人物), 场景: {row['name']}, 环境: {row['prompt'] or ''}, 光照: {row['lighting'] or ''}"
    else:
        spec = f"道具单品图(纯白背景), 道具: {row['name']}, 描述: {row['description'] or ''}"
    prompt = f"{style}, {spec}, 电影质感"
    # 对齐参考项目 comic.ts:尺寸按类型区分(角色 1024x1024 / 场景道具 1280x720),
    # 主形象图作为参考图传入(否则 AI 看 appearance 文字自己想象,镜像不像主形象),
    # 负面守卫:场景/道具禁止出现人物
    size = "1024x1024" if kind == "character" else "1280x720"
    refs = []
    cur = (row["image_url"] or "").strip()
    if cur:
        lp = (config.media_url_to_path(cur) if cur.startswith(("/static/", "static/"))
              else Path(cur))
        if lp.exists():
            refs = [str(lp)]
    negative = (image_client.build_image_negative_guard(1) if kind == "character"
                else image_client.build_image_negative_guard(0))
    out, _p = image_client.generate_image(prompt, config_id=config_id, size=size,
                                         reference_images=refs or None,
                                         people=(1 if kind == "character" else 0))
    url = config.path_to_media_url(out)
    db.ex(f"UPDATE {table} SET comic_image_url=?, updated_at=? WHERE id=?", (url, db.now(), row_id))
    return url
