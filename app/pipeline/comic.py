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
    # 资产行同时记 id:模型读完上面这段要把每格用到的 character_ids / scene_id /
    # prop_ids 抄进 JSON,出图端 panel_image_prompt 会按这些 id 找参考图,跨格
    # 一致性才有锚点。下面建一份 name→id 的对照表,模型漏写 id 但写了 name 时
    # 也能兜底回查。
    name2id: dict[str, dict[str, int]] = {"character": {}, "scene": {}, "prop": {}}
    for label, key, table, cols in (
        ("角色", "character", "characters", ("name", "appearance", "styling")),
        ("场景", "scene", "scenes", ("name", "prompt", "lighting")),
        ("道具", "prop", "props", ("name", "description")),
    ):
        rows = db.q(f"SELECT id,{','.join(cols)} FROM {table} WHERE drama_id=? LIMIT 12", (d_id,))
        if not rows:
            continue
        assets.append(f"— {label} —")
        for r in rows:
            bits = " / ".join(str(r[c] or "")[:90] for c in cols[1:])
            assets.append(f"  [id={r['id']}] {r[cols[0]]}: {bits}")
            name2id[key][str(r[cols[0]]).strip()] = int(r["id"])
    assets.append("以上即全部可用资产;某镜所需资产不在表中时,按剧本文字描述作画,"
                  "character_ids / scene_id / prop_ids 留空即可。")
    prompt = ("\n".join(assets) + "\n\n"
              + f"剧本(第 {ep['episode_number']} 集):\n{script[:14000]}\n\n"
              + "你现在**没有任何工具**,资产已在上方直接给全。禁止输出 <think>、"
                "[Tool: ...]、函数调用或任何解释,只输出一个 JSON 对象。\n"
              + "每个 panel 必须额外带上 asset 引用(供出图端作参考图锚点):\n"
              + "  character_ids: [int,...]  本格出现角色的 id 列表(无人物则空数组)\n"
              + "  scene_id: int 或 null      本格主场景的 id(无明确场景则 null)\n"
              + "  prop_ids: [int,...]        本格出现的道具 id 列表(无道具则空数组)\n"
              + "没有的字段就当 null / 空数组,缺字段的格子仍会被保留(不会丢掉)。")
    data = runner.run_agent_json("comic_board", prompt, lang=lang, config_id=config_id)
    # 兼容三种返回形态:{"panels":[…]} / {"parameters":{"panels":[…]}} / 裸数组
    if isinstance(data, list):
        panels = data
    else:
        # 兼容函数调用信封:部分模型会把内容包在 {"name":…,"parameters":{"panels":[…]}}
        if not data.get("panels") and isinstance(data.get("parameters"), dict):
            data = data["parameters"]
        panels = data.get("panels") or []
    if not panels:
        raise RuntimeError("漫画分镜结果为空")
    ts = db.now()
    db.ex("DELETE FROM comic_panels WHERE episode_id=?", (episode_id,))
    # 先删旧绑定(整集替换语义),panel id 在 INSERT 后才能拿到 → 暂存到 list
    pending_links: list[tuple[int, list[int], int | None, list[int]]] = []
    for i, p in enumerate(panels, start=1):
        panel_id = db.ex(
            "INSERT INTO comic_panels(episode_id,panel_number,description,dialogue,composition,narration,image_prompt,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (episode_id, int(p.get("number") or i), p.get("description", ""), p.get("dialogue", "无"),
             p.get("composition", ""), p.get("narration", ""), "", ts, ts))
        if not panel_id:
            continue
        char_ids = _coerce_ids(p.get("character_ids") or p.get("characters") or [], int)
        scene_id = _coerce_one_id(p.get("scene_id"), int)
        prop_ids = _coerce_ids(p.get("prop_ids") or p.get("props") or [], int)
        # 兜底:模型只写了 name 时按 name2id 反查
        char_ids = [name2id["character"].get(_coerce_str(n), n) for n in (p.get("character_names") or [])] if not char_ids and p.get("character_names") else char_ids
        sn = _coerce_str(p.get("scene_name"))
        if scene_id is None and sn and sn in name2id["scene"]:
            scene_id = name2id["scene"][sn]
        prop_ids = [name2id["prop"].get(_coerce_str(n), n) for n in (p.get("prop_names") or [])] if not prop_ids and p.get("prop_names") else prop_ids
        pending_links.append((panel_id, char_ids, scene_id, prop_ids))
    # 统一入库链接表
    for panel_id, char_ids, scene_id, prop_ids in pending_links:
        for cid in char_ids:
            if cid:
                db.ex("INSERT OR IGNORE INTO comic_panel_characters(panel_id,character_id) VALUES(?,?)",
                      (panel_id, int(cid)))
        if scene_id:
            db.ex("INSERT OR IGNORE INTO comic_panel_scenes(panel_id,scene_id) VALUES(?,?)",
                  (panel_id, int(scene_id)))
        for pid in prop_ids:
            if pid:
                db.ex("INSERT OR IGNORE INTO comic_panel_props(panel_id,prop_id) VALUES(?,?)",
                      (panel_id, int(pid)))
    db.touch("episodes", episode_id)
    return len(panels)


def _coerce_ids(val, caster) -> list[int]:
    """从 list / 单值 / 字符串里抽出整数列表,丢弃空值与非数值。"""
    if val is None:
        return []
    if isinstance(val, (list, tuple)):
        out = []
        for v in val:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                continue
        return [x for x in out if x]
    try:
        return [int(val)]
    except (TypeError, ValueError):
        return []


def _coerce_one_id(val, caster):
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _coerce_str(val) -> str:
    return str(val).strip() if val is not None else ""


def comic_style_options() -> list[tuple[str, str]]:
    """(显示名, prompt 全文) —— 内置 6 套 + 库内 style_type='comic' 的行。

    按 prompt 全文去重;value 一律是 prompt 全文(dramas.comic_style 存的就是全文)。
    """
    return db.style_options(db.STYLE_TYPE_COMIC)


def _style_for(drama_id: int, style_value: str = "") -> str:
    """项目风格串 + 人物面孔文化片段(角色级覆盖由 prompts_gen 处理)。

    优先级:style_value > dramas.comic_style(项目级"温画画风")> dramas.style > "3d"。
    调用方传 style_value 时就以它为准;否则一律落回项目级 comic_style,
    不要再让 dramas.style 的常规视觉风格污染漫画格/漫画资产。
    """
    d = db.q1("SELECT style, comic_style, ethnicity, language FROM dramas WHERE id=?",
              (drama_id,))
    # comic_style 存的是 prompt 全文(存量项目里是 preset value)→ flex 解析两种都认
    return db.style_prompt_flex(
        _current_style_value(drama_id, style_value),
        ethnicity=(d["ethnicity"] if d else "") or "",
        content_lang=(d["language"] if d else "") or "")


def _current_style_value(drama_id: int, style_value: str = "") -> str:
    """当前实际生效的风格 value(与 _style_for 优先级一致),供自修复/对比用。

    与 _style_for 解耦:这里只返回 value 字符串,不取 style_prompt 全文。
    comic_asset_image 用它对比 row.final_prompt_style,不一致就自动重生成
    final_prompt —— 避免用旧 final_prompt + 当前 comic_style 拼出矛盾 prompt。
    """
    if style_value:
        return style_value
    d = db.q1("SELECT style, comic_style FROM dramas WHERE id=?", (drama_id,))
    if d and (d["comic_style"] or "").strip():
        return d["comic_style"]
    if d and (d["style"] or "").strip():
        return d["style"]
    return "3d"


# 漫画格专项负向词(叠加全局守卫)。**所有出漫画格的链路都必须带上它**——
# 单格重绘 / 批量出图 / 整话 pipeline 三处共用这一个常量,不许各写各的
# (此前只有单格重绘带守卫,批量与整话裸奔,实测 2026-10-19 ep79 整话 10 格里
#  前3格全部「同一角色出现 3-4 次」:床上躺一个+站着一个+镜子里一个+窗外一个)。
# 力道对齐视频守卫:之前默认守卫词太软,模型常出「主体+半透明副本」
# 「参考图三视图当成画面背景」(实测会议室场景多出 2 个透明人物)。
PANEL_NEGATIVE_GUARD = (
    "ghost figure, ghost copy, ghost in background, transparent body, "
    "translucent figure, semi-transparent person, faded silhouette, "
    "second copy of same character, mirror image of character, "
    "character lined up in row, character turnaround sheet in background, "
    "same person appearing twice, duplicate person in scene, one character only, "
    "no faces turned away, no profile shot, no 3/4 angle, "
    "no standing figure in background, no extra body silhouette behind subject, "
    "no faded body in mist, no echo figure, "
    "no reflection of same person in mirror, second person in mirror, "
    "no figure outside the window, no person seen through window, "
    "no reflection in window glass"
)


def panel_people_count(panel_id: int) -> int:
    """该格绑定的人物数(对齐原版 routes/comic.ts 的 peopleCount)。"""
    n = db.q1("SELECT COUNT(*) c FROM comic_panel_characters WHERE panel_id=?", (panel_id,))["c"]
    return max(1, int(n or 0))


def _character_best_ref(character_id: int) -> str:
    """角色参考图优先级:character_variants.comic_image_url(多角度,任意一张)
    > character_variants.image_url > characters.comic_image_url > characters.image_url。

    variants 表是多角度图(front/side/3-4/back),用其任何一张作 ref 都比单张主图
    更稳;取 sort_order 最小且有图的那张。多角度图本身由 comic_pipeline._ensure_char_variants
    之类的钩子生成,落库后这里直接用。

    **保留为单 ref 接口**给轻量场景(角色卡 / 头像);跨格一致性需要多 ref 时
    走 `character_all_refs()`。
    """
    v = db.q1(
        "SELECT comic_image_url, image_url FROM character_variants "
        "WHERE character_id=? AND COALESCE(comic_image_url, image_url)!='' "
        "ORDER BY sort_order, id LIMIT 1", (character_id,))
    if v and (v.get("comic_image_url") or v.get("image_url")):
        return v.get("comic_image_url") or v.get("image_url")
    c = db.q1("SELECT comic_image_url, image_url FROM characters WHERE id=?", (character_id,))
    if c:
        return (c.get("comic_image_url") or c.get("image_url") or "")
    return ""


# 同一角色在出图端的 ref 上限。**3 张实测是「参考图够锁定外观」与
# 「payload 不撑爆」的最佳折中**(Wan 3.0 上限 10 留给场景/道具/关键帧;
# Agnes 上限 6 留 3 槽位)。超过这个数,生图端会丢图(实测 qwen-image / volcengine
# 传满 6 张就开始静默丢,见 AGENTS.md 「供应商能力差异」)。
_MAX_REFS_PER_CHARACTER = 3


def _sheet_view_boxes(path: str) -> list[tuple[int, int]]:
    """检测设定图里各「人物立绘」的列范围 [(x0,x1),...];单姿势图返回 []。

    原理:设定图的立绘之间是**空白背景列**(亮且均匀),按列统计灰度,
    均值高且方差低的连续段是背景,其余聚成前景簇。≥2 个簇 = 多立绘设定图。
    不依赖「恰好四格」的假设 —— 特写/正面/侧面/背面、三视图都能处理。
    """
    import numpy as np
    from PIL import Image
    try:
        im = Image.open(path).convert("L")
    except Exception:  # noqa: BLE001 —— 打不开就当单姿势处理
        return []
    w, h = im.size
    a = np.asarray(im.resize((min(w, 512), min(h, 512))), dtype=np.float32)
    col_std = a.std(axis=0)
    col_mean = a.mean(axis=0)
    fg = ~((col_mean > 175.0) & (col_std < 22.0))     # 前景列 = 不够「亮且均匀」
    min_w = max(4, int(len(fg) * 0.04))               # 簇最小宽度 4%,滤掉噪点
    clusters: list[tuple[int, int]] = []
    start = None
    for i, f in enumerate(fg):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if i - start >= min_w:
                clusters.append((start, i))
            start = None
    if start is not None and len(fg) - start >= min_w:
        clusters.append((start, len(fg)))
    return clusters if len(clusters) >= 2 else []


def _single_pose_ref(path_str: str) -> str:
    """角色参考图若为多立绘设定图,裁出**单姿势**那一格再用;否则原样返回。

    为什么必须裁:角色设定图 = 1 特写 + 3 全身,同一角色出现 4 次。原样喂给
    生图模型当参考,模型照着「参考图里有多个人」画,漫画格必然复制人
    (实测 ep79:前 3 格全部 3-4 个复制人,负向词压不住 —— 视觉证据强于提示词)。
    裁完参考里只有 1 个人,复制人问题从源头消失。

    选格:四格规格([特写|正面|侧面|背面])取第 2 簇 = 正面全身;
    三视图([正面|侧面|背面])取第 1 簇;两簇取更宽的(特写窄、全身宽)。
    缓存到同目录 <stem>_single<k>.png:stem 是出图时的 uuid,角色重绘换图后
    文件名变化,缓存自然失效,不需要额外失效逻辑。
    """
    from pathlib import Path
    from PIL import Image
    p = Path(path_str)
    try:
        clusters = _sheet_view_boxes(path_str)
        if not clusters:
            return path_str
        w, _h = Image.open(path_str).size
        scale = w / 512 if w > 512 else 1.0     # 检测时缩过宽,坐标按比例还原
        if len(clusters) >= 4:
            x0, x1 = clusters[1]                # [特写|正面|...] → 正面全身
        elif len(clusters) == 3:
            x0, x1 = clusters[1]                # 取中间:不会是特写(特写总在最左),
            # [正面|侧面|背面] 的中簇是侧面全身;[特写|正面|侧面+背面粘连] 的
            # 中簇是正面全身 —— 两种布局都拿到单姿势全身(实测漫画设定图
            # 特写带彩色背景与正面粘连成 1 簇,首簇裁出来是特写,只有脸没有身)
        else:
            x0, x1 = max(clusters, key=lambda c: c[1] - c[0])
        cache = p.with_name(f"{p.stem}_single{x0}.png")
        if cache.exists():
            return str(cache)
        im = Image.open(path_str).convert("RGB")
        box = (int(x0 * scale), 0, int(x1 * scale), im.size[1])
        im.crop(box).save(cache)
        return str(cache)
    except Exception:  # noqa: BLE001 —— 裁剪失败就退回原图,别挡出图
        return path_str


def character_all_refs(character_id: int) -> list[str]:
    """返回该角色所有可用参考图(去重 + 限长 + 存在性检查)。

    用于漫画出图时把**多角度**参考图全部喂给生图模型(StoryDiffusion / MangaNinja
    风格的「参考库」),比单 ref 跨格一致性显著提升(实测)。

    顺序:variants 表多张 comic_image_url 优先(每张是不同视角的同角色),
    然后是 characters 主图兜底;去重;只取本地文件存在的;最多 3 张。

    每张 ref 出口统一过 `_single_pose_ref`:多立绘设定图裁成单姿势再用。
    此前把四格设定图整张喂给模型,「参考里有 4 个人」直接导致漫画格复制人
    (实测 ep79 前 3 格每格 3-4 个复制人,负向词压不住视觉证据)。

    **同一来源漫画版与写实版只取其一**:comic_image_url 优先,没有才退
    image_url。两版是同一个人的不同画风重绘,五官/脸型差异明显 —— 一起喂
    会被模型当成**两个角色**,实测 ep79 第 2 格在单姿势参考下仍出 2 人,
    去掉写实版后单人格才稳定。
    """
    seen: set[str] = set()
    out: list[str] = []

    def _add_pair(comic_url: str | None, plain_url: str | None) -> None:
        for u in (comic_url, plain_url):          # 漫画版优先,取到即止
            if not u or u in seen:
                continue
            try:
                if config.media_url_to_path(u).exists():
                    out.append(_single_pose_ref(str(config.media_url_to_path(u))))
                    seen.add(u)
                    return
            except Exception:  # noqa: BLE001
                continue

    for r in db.q(
        "SELECT comic_image_url, image_url FROM character_variants "
        "WHERE character_id=? AND COALESCE(comic_image_url, image_url)!='' "
        "ORDER BY sort_order, id",
        (character_id,),
    ):
        _add_pair(r["comic_image_url"], r["image_url"])
        if len(out) >= _MAX_REFS_PER_CHARACTER:
            return out
    if len(out) < _MAX_REFS_PER_CHARACTER:
        c = db.q1("SELECT comic_image_url, image_url FROM characters WHERE id=?",
                  (character_id,))
        if c:
            _add_pair(c["comic_image_url"], c["image_url"])
    return out


def _panel_bound_assets(panel_id: int) -> tuple[list[dict], list[dict], list[dict]]:
    """读出该 panel 绑定的角色/场景/道具(各自全集,不去重;后续按出现次序拼)。

    返回 [(chars...), (scenes...), (props...)]。每条记录至少有 id/name。
    角色参考图字段 _ref_url 优先用 character_variants 多角度图,没有时回退到
    characters 主图(漫画风格或原图)。
    """
    chars_raw = [dict(r) for r in db.q(
        "SELECT c.id, c.name, c.appearance, c.styling, c.comic_image_url, c.image_url "
        "FROM comic_panel_characters pc JOIN characters c ON c.id = pc.character_id "
        "WHERE pc.panel_id=? ORDER BY c.id", (panel_id,))]
    chars = []
    for c in chars_raw:
        c["_ref_url"] = _character_best_ref(c["id"])
        chars.append(c)
    scenes = [dict(r) for r in db.q(
        "SELECT s.id, s.name, s.prompt, s.lighting, s.comic_image_url, s.image_url "
        "FROM comic_panel_scenes ps JOIN scenes s ON s.id = ps.scene_id "
        "WHERE ps.panel_id=? ORDER BY s.id", (panel_id,))]
    props = [dict(r) for r in db.q(
        "SELECT p.id, p.name, p.description, p.comic_image_url, p.image_url "
        "FROM comic_panel_props pp JOIN props p ON p.id = pp.prop_id "
        "WHERE pp.panel_id=? ORDER BY p.id", (panel_id,))]
    return chars, scenes, props


def panel_reference_images(panel_id: int, *, prev_image_url: str | None = None) -> list[str]:
    """把绑定资产的参考图转成本地路径,作为生图端的 reference_images。

    角色参考图走 `character_all_refs()`(多角度,StoryDiffusion 风格「参考库」),
    单角色最多 3 张;场景/道具只用主图。

    prev_image_url (跨 panel 一致性,Step 1「keyframe 链式馈送」):
      同一集**相邻的上一张 panel** 出图后,会把这个 url 加到参考图集**末尾**,
      提示模型「保持上一镜头的构图/光影/人物站位」。跨组(切镜)不传。

    没绑定任何资产 / 资产都没图时返回空列表(出图端会直接走纯文生图)。
    上限 8 张(Wan 3.0 上限 10 留余量,Agnes 6 → 我们的 8 会触发静默丢,见
    AGENTS.md「参考图白名单」)。prev_image_url 始终保留,资产参考按顺序裁。
    """
    chars, scenes, props = _panel_bound_assets(panel_id)
    out: list[str] = []
    seen: set[str] = set()
    for c in chars:
        # 多角度 ref 集(同一角色多张图)
        for ref in character_all_refs(c["id"]):
            if ref in seen:
                continue
            out.append(ref)
            seen.add(ref)
    # 场景/道具:单 ref,避免与角色抢槽位
    for r in scenes + props:
        url = r.get("comic_image_url") or r.get("image_url") or ""
        if not url:
            continue
        if url.startswith(("/static/", "static/")):
            lp = config.media_url_to_path(url)
        elif url.startswith(("file://", "/", "\\")):
            from pathlib import Path
            lp = Path(url.replace("file:///", "").replace("file://", ""))
        else:
            from pathlib import Path
            lp = Path(url)
        if lp.exists():
            sp = str(lp)
            if sp not in seen:
                out.append(sp)
                seen.add(sp)
    # keyframe 链式馈送:始终追加到末尾,这样若资产参考图很多时 prev 不会被挤掉。
    if prev_image_url:
        from pathlib import Path
        if prev_image_url.startswith(("/static/", "static/")):
            plp = config.media_url_to_path(prev_image_url)
        else:
            plp = Path(prev_image_url)
        if plp.exists():
            sp = str(plp)
            if sp not in seen:
                out.append(sp)
                seen.add(sp)
    # 参考图上限:防止绑定过多撑爆生图 payload。
    return out[:8]


def panel_image_prompt(panel_id: int, drama_id: int, config_id: int | None = None,
                       style_value: str = "") -> str:
    """单格出图提示词:画面+构图+对白气泡说明,注入项目风格前缀 + 人数硬前缀。

    style_value 不为空时,优先于 dramas.comic_style 和 dramas.style —— 让界面上
    的「画风」下拉框真正影响图像;否则一律落回 _style_for 的默认拼装。

    绑定的角色/场景/道具会拼成「参考资产视觉」段落进提示词,出图端另由
    panel_reference_images() 把它们的镜像作为 reference_images 传入,跨格
    一致性靠这两层锚点同时锁。
    """
    from pathlib import Path
    p = db.q1("SELECT * FROM comic_panels WHERE id=?", (panel_id,))
    if not p:
        # 调试:把收到的 id 与此刻所有 panel id 范围打出来
        try:
            r = db.q1("SELECT MIN(id) lo, MAX(id) hi, COUNT(*) c FROM comic_panels")
            print(f"[comic] panel_id={panel_id!r} not found; table has {r['c']} rows, ids {r['lo']}..{r['hi']}", flush=True)
        except Exception as e:
            print(f"[comic] panel_id={panel_id!r} not found; re-probe failed: {e}", flush=True)
        raise RuntimeError("漫画格不存在")
    style = _style_for(drama_id, style_value=style_value)
    chars, scenes, props = _panel_bound_assets(panel_id)
    bound_block = ""
    if chars or scenes or props:
        parts = []
        for c in chars:
            bits = " / ".join(s for s in (c.get("appearance"), c.get("styling")) if s)[:200]
            parts.append(f"角色[{c['name']}]: {bits}")
        for s in scenes:
            bits = " / ".join(v for v in (s.get("prompt"), s.get("lighting")) if v)[:200]
            parts.append(f"场景[{s['name']}]: {bits}")
        for p2 in props:
            parts.append(f"道具[{p2['name']}]: {p2.get('description') or ''}"[:200])
        bound_block = "\n\n参考资产视觉(必须与下方参考图保持一致):\n" + "\n".join(parts)
    prompt = f"""目标类型:comic_panel(条漫单格画面,画幅竖版)
视觉风格前缀: {style}
{bound_block}
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
    # 单实例硬规则拼在末尾:负向词与 people 前缀都压不住「链式关键帧把上一格
    # 的成图(躺着)当参考、本格描述是另一状态(站着)」的组合 —— 实测 ep79 重出后
    # 第 2/3 格仍画出「躺着+站着」两个状态并存。正面明确写出「只画此刻」,比
    # 侧面禁止更有效。镜像/玻璃/窗外人影也是本次实测的复制形态,一并点名。
    fp += ("\n\n【单实例硬规则】画面中每个角色只出现一次,只画剧情此刻的状态与位置;"
           "禁止同时画出同一角色的其它状态(如既躺着又站着、既有背影又有正面);"
           "镜面、玻璃、窗外、水面不得出现任何人影或倒影。")
    db.ex("UPDATE comic_panels SET image_prompt=?, updated_at=? WHERE id=?", (fp, db.now(), panel_id))
    return fp


# 描述雷同阈值:SequenceMatcher.ratio() ≥ 此值即视为高重复,UI 挂警告。
# 0.7 是经验值 —— 中文短描述里允许少量同义改写,但「同镜换人名/换站位」这种
# 模型偷懒改写会稳定触发。低于 0.5 基本是不同画面。
_PANEL_SIMILAR_THRESHOLD = 0.7


def panel_similar_pairs(episode_id: int, threshold: float = _PANEL_SIMILAR_THRESHOLD
                        ) -> dict[int, list[dict]]:
    """检测同集内漫画格描述的雷同对。

    返回 {panel_id: [{"other_id": int, "other_number": int, "score": float}, ...]}
    ——「我与谁雷同」的反向索引。每个 panel 只列出比它 panel_number 小的对端,
    避免 A↔B 重复两次。空字典表示该集无雷同。

    计算量:difflib SequenceMatcher O(N²) 但 description < 200 字符,N 通常 12-20,
    单集耗时 < 50ms,可放 UI reload 路径里无负担。
    """
    import difflib
    rows = db.q("SELECT id, panel_number, description, dialogue, composition "
                "FROM comic_panels WHERE episode_id=? ORDER BY panel_number",
                (episode_id,))
    if len(rows) < 2:
        return {}
    # 把 description + composition 一起算,跳过纯对白(对白可以重复但不重复画面)
    sigs: list[tuple[int, int, str]] = []
    for r in rows:
        text = " ".join(filter(None, [r["description"] or "", r["composition"] or ""])).strip()
        sigs.append((int(r["id"]), int(r["panel_number"]), text))
    out: dict[int, list[dict]] = {}
    for i in range(len(sigs)):
        id_i, num_i, txt_i = sigs[i]
        if not txt_i:
            continue
        for j in range(i + 1, len(sigs)):
            id_j, num_j, txt_j = sigs[j]
            if not txt_j:
                continue
            score = difflib.SequenceMatcher(None, txt_i, txt_j).ratio()
            if score >= threshold:
                # i < j:把这条记在 j 头上(它的「问题」:和前面的 i 太像)
                out.setdefault(id_j, []).append({
                    "other_id": id_i,
                    "other_number": num_i,
                    "score": round(score, 2),
                })
    return out


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


_TURNAROUND_BLOCK = (
    "Character turnaround sheet / character reference sheet / multi-view concept art "
    "layout, orthographic views, no perspective distortion: "
    "左侧为该角色的正脸特写,右侧为正面、90度侧面、背面三张等高全身视图水平并排,"
    "evenly spaced panels(等距分栏),头顶与脚底严格对齐,全身入镜,中性A字站姿(A-pose),"
    "双手自然下垂。四个视图必须是同一位角色实例,脸型、发型、服装、配色、比例完全一致,"
    "只允许视角不同;角色实例总数恰为 4 个(1 个特写 + 3 个全身),禁止更多。")

# 空镜硬约束:中英双语都要,英文 token 权重更高
_EMPTY_SCENE_BLOCK = (
    "场景空镜,画面里只有场景本身。Empty scene, no human figures, no silhouettes, "
    "no reflections of people, no crowd in background, no hands, no body parts, "
    "just the location itself, atmospheric and undisturbed")


def comic_asset_image(drama_id: int, kind: str, row_id: int, config_id: int | None = None,
                      style_value: str = "") -> str:
    """资产行的漫画风格镜像图(角色/场景/道具),写 comic_image_url;返回 URL。

    style_value 留空时一律走项目级"温画画风」(dramas.comic_style),由 _style_for 收口,
    避免上游 UI 再重复提供下拉。

    **自动校验 + 自修复**:生成前比对 row.final_prompt_style 与当前 _style_for
    的实际生效 value,不一致说明 final_prompt 是旧风格(prompts_gen 之前按
    dramas.style='3d' 跑出的),此时自动调 prompts_gen 重新跑一遍,让 final_prompt
    跟当前 comic_style 对齐 —— 整个过程不需用户操作数据库。
    """
    from ..ai import image_client
    # 调用方有的传单数("character"),有的直接传表名("characters"),统一归一,
    # 否则单张「重画」会 KeyError: 'characters'
    kind = {"characters": "character", "scenes": "scene",
            "props": "prop"}.get(kind, kind)
    table = {"character": "characters", "scene": "scenes", "prop": "props"}[kind]
    row = db.q1(f"SELECT * FROM {table} WHERE id=?", (row_id,))
    if not row:
        raise RuntimeError("资产不存在")

    # ── 自修复逻辑已废弃 ──
    # 历史:曾经 prompts_gen 用 _style_for()(comic_style 优先),导致 final_prompt 跟
    # dramas.style 不一致,需要自修复重写。现在 prompts_gen 已改为严格走 dramas.style,
    # final_prompt 与 final_prompt_style 天然一致(comic_asset_image 自己拼 spec,不读
    # final_prompt),自修复就只是**白烧一次 LLM**——直接跳过。
    # 旧行里若 final_prompt 还是漫画前缀(commit 之前生成的),用户点"AI 起草最终提示词"
    # 会重写为 3D 前缀,这里不动它们。

    style = _style_for(drama_id, style_value=style_value)
    # **不再复用 row['final_prompt']** —— 它是「常规资产」流程在 dramas.style 下
    # 生成的(可能是 3d 写实风格),与 comic_style 设的「美式漫画/日漫赛璐璐」完全无关;
    # 复用会让 comic_image_url 永远被钉死在当初生成时那个风格上(实测用 dramas.style
    # ='3d' 时生成的 final_prompt,后续切到 comic_style='comic' 也救不回来)。
    # 改为每次按 row 字段拼最简 spec,让 prompt 头部的 _style_for 风格前缀独立生效。
    if kind == "character":
        # 三视图版式沿用现成 TURNAROUND_BLOCK 规范(英文 token 让模型严格遵守布局),
        # 角色信息只用 appearance/styling 关键描述,不被 final_prompt 旧值带偏。
        spec = (f"角色: {row['name']}, "
                f"样貌: {row['appearance'] or ''}, "
                f"服装: {row['styling'] or ''}。" + _TURNAROUND_BLOCK +
                " 所有视图表情平静自然、双唇闭合、眼神放松,不做任何夸张情绪。"
                "纯白无缝背景,柔和均匀漫射光线")
    elif kind == "scene":
        # 场景:空镜,直接描述名字+环境+光照,people=0 走纯文生图 + 负向守卫禁一切人。
        spec = (f"场景: {row['name']}, "
                f"环境: {row['prompt'] or ''}, "
                f"光照: {row['lighting'] or ''}。" + _EMPTY_SCENE_BLOCK)
    else:
        spec = (f"道具: {row['name']}, "
                f"描述: {row['description'] or ''}。纯白无缝背景单品图")
    prompt = f"{style}, {spec}"
    # 对齐参考项目 comic.ts:尺寸按类型区分(角色 1024x1024 / 场景道具 1280x720)。
    # **不再把 image_url(常规 3D 写实图)当作 reference_images 喂进生图模型** ——
    # 模型会"参考"那张写实人像,导致无论 prompt 写"美式漫画/日漫赛璐璐"等
    # 风格前缀,输出都被钉在写实人像的视觉上。改为纯文生图,让 prompt 头部
    # 的 comic_style 风格前缀真正生效。
    # (场景/道具从一开始就**不**传参考图,见下面原注释。)
    size = "1024x1024" if kind == "character" else "1280x720"
    refs = []
    # 三视图的"特写格"是模型最爱加戏的位置:默认给一张张嘴嘶吼的脸。
    # 通用守卫里只有一句 no wide-open screaming mouth,权重不够,这里再加一层。
    extra_neg = ("open mouth, screaming, shouting, yelling, gasp, aghast, terrified expression, "
                 "horror face, exaggerated emotion, background figures, faded silhouettes, "
                 "reflections of people") if kind == "character" else None
    out, _p = image_client.generate_image(prompt, config_id=config_id, size=size,
                                         reference_images=refs or None,
                                         people=(1 if kind == "character" else 0),
                                         extra_negative=extra_neg)
    url = config.path_to_media_url(out)
    db.ex(f"UPDATE {table} SET comic_image_url=?, updated_at=? WHERE id=?", (url, db.now(), row_id))
    return url
