# -*- coding: utf-8 -*-
"""阶段④:剧本 → 镜头级分镜(storyboard_breaker Agent)+ 批量视频提示词。"""
from __future__ import annotations

import json
import re

from ..agents import runner
from ..core import db

# 起始输出预算:整集分镜一次要吐 20-30 镜 × (description 3-6 句 + atmosphere 2-4 句 +
# video_prompt 每 3 秒一段),实测一集 26 镜 = 50,787 completion tokens / 115k 字符。
# 默认 8192 连一个 <think> 都装不下,按阶梯爬上去要连烧 4 次(≈16 分钟);
# 这里直接按实测值起步。供应商若不认这个上限,runner 会退回到低档阶梯重爬。
STORYBOARD_MAX_TOKENS = 65536


def split_storyboards(episode_id: int, aspect: str = "9:16", config_id: int | None = None,
                    lang: str | None = None) -> int:
    """整集重新拆分分镜;返回数量(对齐原版 save_storyboards:全量替换 + 资产绑定)。

    与原版对齐的关键点:
    - 落库 **全字段**(title/shot_type/angle/movement/location/time/description/result/
      atmosphere/image_prompt/video_prompt/bgm_prompt/sound_effect/scene_id/setting_tags/duration);
      setting_tags 为空时从场景继承 —— 缺这些字段时 `refs.build_shot_reference_list`
      拿不到绑定、reference injection 就是空的,生图只能每次现调 Agent。
    - 同步写 `storyboard_characters`(带 variant_id)与 `storyboard_props`;
    - 按 shot_number **幂等 upsert**(重拆不丢已生成的视频/首帧);
    - 重算 `episodes.duration = ceil(Σ分镜时长 / 60)`。
    """
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("剧集不存在")
    script = ep["script_content"] or ""
    if not script.strip():
        raise RuntimeError("请先完成剧本改写")
    chars = db.q("SELECT id, name, appearance, styling FROM characters WHERE drama_id=? AND deleted_at IS NULL",
                 (ep["drama_id"],))
    scenes = db.q("SELECT id, name, location, time, prompt, lighting, setting_tags FROM scenes "
                  "WHERE drama_id=? AND deleted_at IS NULL", (ep["drama_id"],))
    props = db.q("SELECT id, name, type, description FROM props WHERE drama_id=? AND deleted_at IS NULL",
                 (ep["drama_id"],))
    # 资产清单对齐参考项目 read_storyboard_context 的返回:角色带完整样貌/妆造(不截断),
    # 场景带 location/time/prompt(空间陈设年代质感)/lighting,道具带类型与外观描述。
    # atmosphere 的光线/色调/环境感受三层都要从这里取材:只喂 lighting 模型只能凭空编,
    # 这正是之前氛围比参考项目差一截的根因。
    char_lines = [f"- {r['name']}(样貌:{r['appearance'] or ''};妆造:{r['styling'] or ''})"
                  for r in chars] or ["- 无"]
    scene_lines = [f"- {r['name']} / 地点:{r['location']} / 时间:{r['time'] or ''} / "
                   f"环境:{r['prompt'] or ''} / 光影:{r['lighting'] or ''}"
                   for r in scenes] or ["- 无"]
    prop_lines = [f"- {r['name']}({r['type'] or ''}:{r['description'] or ''})"
                  for r in props] or ["- 无"]
    assets = ("角色(@角色名引用):\n" + "\n".join(char_lines)
              + "\n场景(@场景名引用,含光影供 atmosphere 取材):\n" + "\n".join(scene_lines)
              + "\n道具(@道具名引用):\n" + "\n".join(prop_lines))
    prompt = f"""剧本(第 {ep['episode_number']} 集,画面比例 {aspect}):
{script[:14000]}

可用资产:
{assets}"""
    # 输出格式规范(对齐参考项目 storyboard-breaker skill + video-prompt skill):
    # description 按【镜头N】子镜头(运镜在前/画面/台词);video_prompt 信息头 +
    # 按 3 秒分段带时间戳,段内 @场景/@角色/@道具 引用,切镜对齐【镜头N】结构
    prompt += ("""

【时长分配规范(硬规则)】
- 每镜 duration 按内容节奏在 8-15 秒内分配,且必须覆盖该镜全部台词的朗读时间
- 对话/过渡段偏短(8-10 秒),动作/高潮/多子镜头段偏长(11-15 秒)
- 各镜时长必须参差不齐、贴合叙事节奏,严禁全部输出同一数值

【description 规范(硬规则)】
- 按【镜头1】【镜头2】…逐子镜头描述观众实际看到和听到的内容
- 每个子镜头开头先写运镜(如"镜头从中景匀速缓推至特写"),再写画面(谁+具体动作+肢体细节+表情)
- 台词以「角色名说：「台词」」写进对应【镜头N】内;旁白写「旁白：内容」
- 运镜词库按段落类型选择:铺垫段→拉远揭示/升降俯瞰/横移跟随;对话段→过肩近景/缓推/固定微动(呼吸感起伏);情绪段→心跳脉冲式缓推/手持晃动/颤抖;动作段→疾速追尾/打斗穿梭/横移跟随;爆点段→子弹时间/急停定帧/凝视聚焦;悬疑惊悚→窥视视角/荷兰角/主观视角(点睛特技一集最多 1-2 处)
- 禁止一行一段的流水账;每段 3-6 句完整描述

【atmosphere 规范(硬规则,对齐参考项目 storyboard-breaker:光线+色调+声音+整体氛围)】
- 写 2-4 句完整短句,四层都要有,禁止关键词罗列:
  ① 光线:光源+方向+冷暖(如"日光灯冷白均匀照明");光线层必须从该镜匹配到的场景光影(lighting)延展,再叠加本镜时刻/情绪的增量
  ② 色调:整体色彩倾向与明暗关系
  ③ 声音:至少一层持续可听的环境音,写质感比喻(如"键盘声透过磨砂玻璃传来,喑哑如雨")
  ④ 整体氛围:把情绪落到具体物件或人的状态(如"整间屋子冷静、程序化、没有任何温度")
- 禁止"天气+感受"式短语(如"正午暴晒,热浪扭曲,恍惚")

【video_prompt 规范(硬规则)】
- 第一行是信息头:出场人物(@角色名)与场景(@场景名),独立一行,句号结尾;有道具出场可追加 道具：@道具名
- 之后按 3 秒为一段,每段单独一行:格式 = 时间范围[起-止秒] + @场景引用 + 景别/运镜 + @角色引用 + 主体动作·表情 + 对白/旁白 + 氛围光线
- description 的每个【镜头N】映射为 1-2 个连续的 3 秒段,顺序一致不遗漏;段数 = duration ÷ 3 向上取整
- 每段必须有镜头运动(位移/变焦/跟随/呼吸感起伏),禁止整段"固定镜头"静止画面;运镜写法="起始景别+运动方式+速度"
- 台词写「角色名说：「台词」」;情绪全部转为可见描写(动作/表情/肢体),不写抽象词
- 每段至少一个 @ 引用;名字必须与上面可用资产清单完全一致
- 每段末尾的氛围光线与环境音取自本镜 atmosphere,不要另造一套
""")

    prompt += ("\n\n请输出 JSON 对象:"
               '{"storyboards":[…]};每镜字段 '
               'number/title/content/shot_type/angle/movement/location/time/description/'
               'atmosphere/result/image_prompt/video_prompt/bgm_prompt/sound_effect/'
               'setting_tags(数组)/characters(角色名数组)/props(道具名数组)')
    data = runner.run_agent_json("storyboard_breaker", prompt, lang=lang, config_id=config_id,
                                 max_tokens=STORYBOARD_MAX_TOKENS)
    boards = _extract_boards(data)
    if not boards:
        raise RuntimeError("分镜结果为空")
    ts = db.now()
    name_to_id = {r["name"]: r["id"] for r in chars}
    scene_by_name = {r["name"]: dict(r) for r in scenes}
    prop_by_id = {r["id"]: r["name"] for r in props}
    prop_names = [r["name"] for r in props]
    _clear_episode_bindings(episode_id)
    total_dur = 0.0
    # 强制重编号 1..N:模型 number 只用于排序(幻觉出 14-30 起始编号时,
    # 任务列表会变成 #14 在前 #01 在后 —— 对齐参考项目按镜号顺序)
    boards.sort(key=lambda b: (int(b.get("number") or 10**6), ))
    for i, b in enumerate(boards, start=1):
        num = i
        scene_id = _match_scene(b, scene_by_name)
        inherit = (scene_by_name.get(b.get("location") or "", {}) or {}).get("setting_tags")
        tags = b.get("setting_tags") or inherit
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.replace("、", ",").split(",") if t.strip()]
        dur = _resolve_duration(b)
        total_dur += dur
        # 幂等 upsert:已存在的镜头保留生成物(视频/首帧/字幕),只更新描述类字段
        existing = db.q1("SELECT id FROM storyboards WHERE episode_id=? AND storyboard_number=?",
                         (episode_id, num))
        vals = (str(b.get("title") or b.get("content") or "")[:120],
                b.get("shot_type") or b.get("shot_size"), b.get("angle"), b.get("movement"),
                b.get("location"), b.get("time"), b.get("description"),
                b.get("result"), b.get("atmosphere"), b.get("image_prompt"),
                b.get("video_prompt"), b.get("bgm_prompt"), b.get("sound_effect"),
                scene_id, json.dumps(tags, ensure_ascii=False) if tags else None,
                b.get("content", ""), dur)
        if existing:
            db.ex("""UPDATE storyboards SET title=?, shot_type=?, angle=?, movement=?, location=?,
                      time=?, description=?, result=?, atmosphere=?, image_prompt=?, video_prompt=?,
                      bgm_prompt=?, sound_effect=?, scene_id=?, setting_tags=?, content=?, duration=?,
                      updated_at=? WHERE id=?""", vals + (ts, existing["id"]))
            sb_id = existing["id"]
        else:
            sb_id = db.ex(
                """INSERT INTO storyboards(episode_id,storyboard_number,title,shot_type,angle,
                   movement,location,time,description,result,atmosphere,image_prompt,video_prompt,
                   bgm_prompt,sound_effect,scene_id,setting_tags,content,duration,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?,?)""",
                (episode_id, num) + vals + (ts, ts))
        _bind_assets(sb_id, b, name_to_id, prop_by_id, prop_names, ts, episode_id)
        sid_row = db.q1("SELECT scene_id FROM storyboards WHERE id=?", (sb_id,))
        if sid_row and sid_row["scene_id"]:
            db.ex("INSERT OR IGNORE INTO episode_scenes(episode_id,scene_id) VALUES(?,?)",
                  (episode_id, sid_row["scene_id"]))
    db.ex("UPDATE episodes SET duration=?, updated_at=? WHERE id=?",
          (max(1, round(total_dur / 60)), ts, episode_id))
    db.touch("episodes", episode_id)
    # 自动建造型变体 + 情绪打标:扫描所有新分镜,发现外观/场景/道具变化就建一行;
    # 情绪变化只打标签写到 storyboards.emotion_tags(不建变体,脸没换)。
    # 不抢着生图(避免一次性烧光 token),用户进「造型变体」对话框手动点重生。
    try:
        from .variant_detector import (
            ensure_variants_for_storyboard,
            detect_emotions_in_storyboard,
        )
        drama_id = db.q1("SELECT drama_id FROM episodes WHERE id=?",
                          (episode_id,))["drama_id"]
        n_v = 0
        n_e = 0
        for sb in db.q("SELECT * FROM storyboards WHERE episode_id=? "
                       "AND deleted_at IS NULL", (episode_id,)):
            n_v += len(ensure_variants_for_storyboard(sb, drama_id))
            # 情绪打标(JSON 数组);合并旧的,不覆盖
            old = []
            try:
                old_row = db.q1("SELECT emotion_tags FROM storyboards WHERE id=?", (sb["id"],))
                if old_row and old_row.get("emotion_tags"):
                    import json as _json
                    try:
                        old = _json.loads(old_row["emotion_tags"])
                    except Exception:
                        old = []
            except Exception:
                pass
            new = detect_emotions_in_storyboard(sb)
            merged = sorted(set((old or []) + new))
            if merged != (old or []):
                import json as _json
                db.ex("UPDATE storyboards SET emotion_tags=?, updated_at=? WHERE id=?",
                      (_json.dumps(merged, ensure_ascii=False), ts, sb["id"]))
                n_e += 1
        if n_v or n_e:
            print(f"[variant_detector] EP{episode_id} 新建 {n_v} 变体 / "
                  f"{n_e} 镜打情绪标", flush=True)
    except Exception as e:                                # noqa: BLE001
        print(f"[variant_detector] 检测失败,忽略:{e}", flush=True)
    return len(boards)


def _extract_boards(data) -> list:
    '''兼容三种返回形态:{"storyboards":[…]} / {"boards":[…]} / 裸数组。'''
    if isinstance(data, list):
        return [b for b in data if isinstance(b, dict)]
    if isinstance(data, dict):
        for key in ("storyboards", "boards", "shots", "items"):
            v = data.get(key)
            if isinstance(v, list) and v:
                return [b for b in v if isinstance(b, dict)]
        # 兜底:形如 {"1": {...}, "2": {...}} 的字典
        vals = [v for v in data.values() if isinstance(v, dict)]
        if vals and all("content" in v or "video_prompt" in v for v in vals):
            return vals
    return []


def _clear_episode_bindings(episode_id: int) -> None:
    """重拆前清掉本集分镜的资产绑定(分镜本身由 upsert 处理,不删以免丢生成物)。"""
    db.ex("DELETE FROM storyboard_characters WHERE storyboard_id IN "
          "(SELECT id FROM storyboards WHERE episode_id=?)", (episode_id,))
    db.ex("DELETE FROM storyboard_props WHERE storyboard_id IN "
          "(SELECT id FROM storyboards WHERE episode_id=?)", (episode_id,))


def _match_scene(b: dict, scene_by_name: dict) -> int | None:
    """按 location / scene 字段匹配场景;匹配不到留空(原版同样允许 unbound)。"""
    for key in ("scene", "location"):
        v = (b.get(key) or "").strip()
        if v and v in scene_by_name:
            return scene_by_name[v]["id"]
    for name in scene_by_name:
        if name and name in (b.get("content") or ""):
            return scene_by_name[name]["id"]
    return None


def _resolve_duration(b: dict) -> float:
    """分镜时长:模型给了就用(夹取 2-30);没给则按子镜头数与台词字数分配 8-15 秒。

    模型常省略 duration,固定兜底值会让全片时长一模一样(实测 17 镜全是 5s),
    这里按【镜头N】数量(每镜头约 3 秒)+ 台词字数推算,保证参差不齐且贴合内容。
    """
    import re as _re
    raw = b.get("duration")
    try:
        if raw is not None and float(raw) > 0:
            return min(30.0, max(2.0, float(raw)))
    except (TypeError, ValueError):
        pass
    text = (b.get("description") or b.get("content") or "")
    shots = max(1, len(_re.findall(r"【镜头\d+】", text)))
    dialogue = len(_re.findall(r"说：「[^」]*」", text))
    sec = shots * 3.0 + min(4.0, dialogue * 0.12)      # 每子镜头约 3s + 台词补量
    sec += (int(b.get("number") or 1) % 3) * 0.5          # 相邻镜不撞同一值
    return min(15.0, max(8.0, round(sec)))


def _bind_assets(sb_id: int, b: dict, name_to_id: dict, prop_by_id: dict,
                 prop_names: list, ts: str, episode_id: int | None = None) -> None:
    """把本镜出现的 @角色 / @道具 绑定到分镜(对齐 syncStoryboardCharacters/Props)。

    兼容两种形态:`characters: ["叶尘"]` 与 `char_ids: [3]`(模型有时直接给 id)。
    绑定的角色/道具若尚未关联本集,自动补 episode_characters/episode_props/episode_scenes
    关联(对齐参考项目 save_storyboards 工具的自愈逻辑)——否则参考素材面板按本集
    关联过滤,这些资产根本不显示。
    """
    names = _refs_to_names(b, "characters", name_to_id, prop_by_id)
    for name, cid, vid in names:
        db.ex("INSERT OR IGNORE INTO storyboard_characters(storyboard_id,character_id,variant_id) "
              "VALUES(?,?,?)", (sb_id, cid, vid))
        if episode_id:
            db.ex("INSERT OR IGNORE INTO episode_characters(episode_id,character_id) VALUES(?,?)",
                  (episode_id, cid))
    for _name, pid, _vid in _refs_to_names(b, "props", prop_by_id, prop_by_id):
        db.ex("INSERT OR IGNORE INTO storyboard_props(storyboard_id,prop_id) VALUES(?,?)",
              (sb_id, pid))
        if episode_id:
            db.ex("INSERT OR IGNORE INTO episode_props(episode_id,prop_id) VALUES(?,?)",
                  (episode_id, pid))


def _refs_to_names(b: dict, key: str, id_by_name: dict, prop_by_id: dict) -> list:
    """把 characters/props 引用统一成 (名字, id, variant_id);兼容名字数组与 id 数组。"""
    out: list = []
    id_key = "char_ids" if key == "characters" else "prop_ids"
    for cid in b.get(id_key) or []:
        try:
            row = db.q1("SELECT id, name FROM characters WHERE id=?" if key == "characters"
                        else "SELECT id, name FROM props WHERE id=?", (int(cid),))
        except (TypeError, ValueError):
            row = None
        if row:
            out.append((row["name"], row["id"], None))
    for ref in b.get(key) or []:
        name = (ref.get("name") if isinstance(ref, dict) else str(ref)) or ""
        name = name.lstrip("@").strip()
        cid = id_by_name.get(name)
        if cid:
            vid = (ref.get("variant_id") if isinstance(ref, dict) else None)
            out.append((name, cid, vid))
    return out
    # 兜底:正文里出现的资产名也算绑定(Agent 漏给 characters 数组时)
    text = b.get("content") or ""
    for name, cid in name_to_id.items():
        if cid and name in text and "@" + name in text:
            db.ex("INSERT OR IGNORE INTO storyboard_characters(storyboard_id,character_id) "
                  "VALUES(?,?)", (sb_id, cid))
    for i, name in enumerate(prop_names):
        if name and "@" + name in text:
            db.ex("INSERT OR IGNORE INTO storyboard_props(storyboard_id,prop_id) VALUES(?,?)",
                  (sb_id, prop_by_id[name]))

def gen_video_prompts(episode_id: int, config_id: int | None = None, lang: str | None = None) -> int:
    """批量补齐缺失的每镜 video_prompt(prompt_generator Agent);返回处理数。

    对齐原版:只处理 `video_prompt` 为空的镜头(已有的不覆盖),按镜头号顺序逐条生成。
    """
    rows = db.q("""SELECT * FROM storyboards WHERE episode_id=?
                   AND (video_prompt IS NULL OR video_prompt='') ORDER BY storyboard_number""",
                (episode_id,))
    if not rows:
        rows = db.q("SELECT * FROM storyboards WHERE episode_id=? ORDER BY storyboard_number",
                    (episode_id,))
        if not rows:
            raise RuntimeError("请先「重新拆分」生成分镜")
    from .comic import _style_for
    drama_id = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))["drama_id"]
    style = _style_for(drama_id)
    done = 0
    for r in rows:
        prompt = f"""目标类型:storyboard(镜头视频提示词)
视觉风格前缀: {style}

分镜 #{r['storyboard_number']}:
{(r['description'] or r['content'] or '')[:1500]}"""
        try:
            data = runner.run_agent_json("prompt_generator", prompt, lang=lang, config_id=config_id)
            vp = data.get("video_prompt") if isinstance(data, dict) else None
            if vp:
                db.ex("UPDATE storyboards SET video_prompt=?, updated_at=? WHERE id=?", (vp, db.now(), r["id"]))
                done += 1
                # video_prompt 也可能命中外观变化 → 给关联角色建一条变体
                try:
                    from .variant_detector import ensure_variants_for_storyboard
                    sb_now = db.q1("SELECT * FROM storyboards WHERE id=?", (r["id"],))
                    if sb_now:
                        ensure_variants_for_storyboard(sb_now, drama_id)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            continue
    return done


def gen_atmospheres(episode_id: int, config_id: int | None = None, lang: str | None = None) -> int:
    """按四层规范(光线+色调+声音+整体氛围)整集重写 atmosphere;返回成功数。

    与拆分共用同一条规范(见 split_storyboards 里的【atmosphere 规范】),
    光线层从该镜匹配到的场景 lighting 延展 —— 给旧规则拆出来的分镜补一条
    不用整集重拆的升级路径。返回纯文本,不走 JSON 解析。
    """
    rows = db.q("SELECT * FROM storyboards WHERE episode_id=? ORDER BY storyboard_number",
                (episode_id,))
    if not rows:
        raise RuntimeError("请先「重新拆分」生成分镜")
    scenes = db.q("SELECT id, name, location, time, lighting FROM scenes "
                  "WHERE drama_id=(SELECT drama_id FROM episodes WHERE id=?)", (episode_id,))
    scene_by_id = {r["id"]: dict(r) for r in scenes}
    scene_by_loc = {r["location"]: dict(r) for r in scenes if r["location"]}
    system = ("你是影视美术指导。只输出氛围描述本身,不要任何前言、解释或引号。"
              "氛围 = 光线 + 色调 + 声音 + 整体氛围,写 2-4 句完整短句:"
              "光线从给定场景光影延展(光源+方向+冷暖);色调写色彩倾向与明暗;"
              "声音至少一层持续可听的环境音并带质感比喻;整体氛围把情绪落到具体物件或人的状态。"
              "禁止\"天气+感受\"式关键词罗列。")
    done = 0
    for r in rows:
        sc = scene_by_id.get(r["scene_id"]) or scene_by_loc.get(r["location"] or "") or {}
        prompt = f"""镜头 #{r['storyboard_number']} 《{r['title'] or ''}》
场景: {r['location'] or sc.get('location') or ''} {r['time'] or sc.get('time') or ''}
场景光影: {sc.get('lighting') or '(未记录,按场景与时段推断)'}
画面描述:
{(r['description'] or r['content'] or '')[:1000]}
当前氛围(需要按规范重写):
{r['atmosphere'] or '(空)'}

请输出这个镜头的氛围描述。"""
        try:
            text = runner.run_agent("prompt_generator", prompt, lang=lang,
                                    config_id=config_id, system=system).strip()
            text = text.strip('"“”').strip()
            if text and 10 < len(text) < 500:
                db.ex("UPDATE storyboards SET atmosphere=?, updated_at=? WHERE id=?",
                      (text, db.now(), r["id"]))
                done += 1
        except Exception:  # noqa: BLE001 —— 单镜失败不阻断整批
            continue
    return done


# ── 垃圾分镜清理(对齐原版 StoryboardSplit junk-removed) ──
JUNK_DESC_MIN = 50
JUNK_IMAGE_MIN = 30
JUNK_VIDEO_MIN = 60


def clean_junk_storyboards(episode_id: int) -> int:
    """清理拆分中断留下的空壳分镜。

    模型偶发先写「占位清理A/B…」占位行再填充,中途截断就留下
    description<50 且 image_prompt<30 且 video_prompt<60 的空壳行(实测一次 6 行)。
    以**产物长度**判定,不匹配标题关键词。级联清 storyboard_characters/props。
    """
    removed = 0
    for sb in db.q("SELECT * FROM storyboards WHERE episode_id=?", (episode_id,)):
        desc = (sb["description"] or sb["content"] or "").strip()
        img = (sb["image_prompt"] or "").strip()
        vid = (sb["video_prompt"] or "").strip()
        if len(desc) < JUNK_DESC_MIN and len(img) < JUNK_IMAGE_MIN and len(vid) < JUNK_VIDEO_MIN:
            db.ex("DELETE FROM storyboard_characters WHERE storyboard_id=?", (sb["id"],))
            db.ex("DELETE FROM storyboard_props WHERE storyboard_id=?", (sb["id"],))
            db.ex("DELETE FROM storyboards WHERE id=?", (sb["id"],))
            removed += 1
    return removed


def split_storyboards_bg(episode_id: int, aspect: str = "9:16", config_id: int | None = None,
                         lang: str | None = None):
    """后台分镜拆解(对齐原版 POST /storyboards/split-async)。

    拆解是 5-10 分钟的多步 Agent 调用,同步等待会被代理掐断;这里丢进任务队列,
    由 TaskManager 线程执行,UI 轮询 sys_task 状态。
    """
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("章节不存在")
    if not (ep["script_content"] or "").strip():
        raise RuntimeError("本集还没有剧本,请先完成「AI 改写」")
    # 防重入:同集已有拆分任务在跑
    running = db.q1("""SELECT id FROM sys_task WHERE episode_id=? AND type='storyboard_split'
                       AND status='processing'""", (episode_id,))
    if running:
        raise RuntimeError("本集拆分已在进行中,请等它完成或在任务面板查看进度")

    from ..core import taskmgr as TM
    from ..core.taskmgr import TASKMGR

    def job(tid: int):
        TM.set_stage(tid, "splitting")
        try:
            n = split_storyboards(episode_id, aspect, config_id=config_id, lang=lang)
            removed = clean_junk_storyboards(episode_id)
            n = db.q1("SELECT COUNT(*) c FROM storyboards WHERE episode_id=?", (episode_id,))["c"]
            if n == 0:
                raise RuntimeError("拆分结束但没有写入任何分镜,请重试")
            msg = f"拆出 {n} 个分镜"
            if removed:
                msg += f"(已清理 {removed} 个残缺行)"
            TM.finish_task(tid, "completed", result_url=str(n), local_path=msg)
            return n
        except Exception as e:  # noqa: BLE001
            TM.finish_task(tid, "failed", error=str(e)[:500])
            raise

    return TASKMGR.submit("storyboard_split", job, episode_id=episode_id,
                          drama_id=ep["drama_id"])
