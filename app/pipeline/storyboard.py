# -*- coding: utf-8 -*-
"""阶段④:剧本 → 镜头级分镜(storyboard_breaker Agent)+ 批量视频提示词。"""
from __future__ import annotations

import json
import re

from ..agents import prompts, runner
from ..core import db
from ..core.logging_setup import get_logger
from . import media_files

log = get_logger(__name__)

# 单次调用的输出预算:整集分镜一次要吐 20-30 镜 × (description 3-6 句 + atmosphere
# 2-4 句 + video_prompt 每 3 秒一段),实测一集 26 镜 = 50,787 completion tokens /
# 115k 字符,且**波动极大** —— 同一条 prompt 换一次跑就顶满 65,536 被 length 截断
# (128,980 字符全是半截 JSON)。所以除了把预算抬到 65536,更要按场景分批。
STORYBOARD_MAX_TOKENS = 65536
# 每批剧本的字数上限:一集 8 场 ≈ 3000 字拆 3-4 批,单批 ≈ 6-8 镜 ≈ 20-30k 输出 tokens。
# 1400 字那档实测单批就吐了 42,984 tokens / 453s,太接近上限,所以收紧到 900。
STORYBOARD_CHUNK_CHARS = 900


def _script_batches(script: str, limit: int = STORYBOARD_CHUNK_CHARS) -> list[tuple[str, str]]:
    """把剧本按场景切成若干批,每批一次 LLM 调用。

    为什么必须切:整集一次调用实测 50,787+ completion tokens 且波动极大,
    65536 档仍被 finish_reason=length 截断。切批后单次只要 1/3 输出,
    既不会顶到供应商上限,也能把批间进度反馈到任务面板。
    """
    blocks = [b for b in re.split(r"(?m)^(?=##\s*S\d+\s*\|)", script) if b.strip()]
    if len(blocks) <= 1:
        # 没有场景头的老剧本:按空行切段再合并,避免整集塞进一次调用
        blocks = [b for b in re.split(r"\n\s*\n", script) if b.strip()]
    batches: list[tuple[str, str]] = []
    cur: list[str] = []
    cur_len = 0
    for b in blocks:
        if cur and cur_len + len(b) > limit:
            batches.append((_batch_label(cur), "".join(cur)))
            cur, cur_len = [], 0
        cur.append(b if b.endswith("\n") else b + "\n")
        cur_len += len(b)
    if cur:
        batches.append((_batch_label(cur), "".join(cur)))
    # 收尾合并:最后一个场景常常很短(实测 S06 只有 189 字,单独一次调用
    # 要多花一整轮 prompt 与思维链),把它并进相邻批;允许略微超过 limit。
    merged: list[tuple[str, str]] = []
    for label, part in batches:
        if (merged and len(part) < limit / 3
                and len(merged[-1][1]) + len(part) <= limit * 1.6):
            prev_part = merged.pop()[1]
            merged.append((_batch_label([prev_part, part]), prev_part + part))
        else:
            merged.append((label, part))
    return merged or [("全剧", script)]


def _batch_label(parts: list[str]) -> str:
    nums = re.findall(r"(?m)^##\s*S(\d+)\s*\|", "".join(parts))
    if not nums:
        return "本批"
    return f"第 {nums[0]}-{nums[-1]} 场" if nums[0] != nums[-1] else f"第 {nums[0]} 场"


def _scene_blocks(text: str) -> list[str]:
    blocks = [b for b in re.split(r"(?m)^(?=##\s*S\d+\s*\|)", text) if b.strip()]
    return blocks or [text]


def _boards_for_part(ep, aspect: str, assets: str, part: str, label: str, *,
                     lang, config_id, depth: int = 0) -> list:
    """跑一批分镜;整批没拿到 JSON 就按场景对半拆开重试,而不是让整集失败。

    实测 minimax-M3 偶发「只吐 <think> 就 finish=stop」(S07-08 那批 39,704 字符
    全是思维链,正文 0 字),重试同一批也未必好;但拆成单场后模型负担减半,
    并且失败的代价从「整集重来」降到「重跑一场」。
    """
    blocks = _scene_blocks(part)
    prompt = _storyboard_prompt(ep, aspect, assets, part, label,
                                total=2 if len(blocks) > 1 else 1)
    reason = ""
    try:
        data = runner.run_agent_json("storyboard_breaker", prompt, lang=lang,
                                     config_id=config_id,
                                     max_tokens=STORYBOARD_MAX_TOKENS)
        got = _extract_boards(data)
        if got:
            return got
        reason = "模型返回了空分镜列表"
    except RuntimeError as e:
        reason = str(e)[:200]
    except Exception as e:  # noqa: BLE001
        # **网络异常也必须走「这一批失败」的路径**,不能直接冒上去。
        # 原来只捕 RuntimeError,而 requests 的 ProxyError / ConnectionError /
        # ReadTimeout / IncompleteRead 都不是 RuntimeError —— 本机代理掐断长连接时
        # (实测 2026-10-19 ep79 第 4 批)一个批次失败会**整集任务死掉**,
        # 前面几批已经落库的分镜也跟着白拆。这与本函数「整批没拿到就拆半重试、
        # 而不是让整集失败」的设计意图正好相反。降级成 RuntimeError 后,
        # 多场景的批次还能拆成单场再试一次。
        reason = f"{type(e).__name__}: {str(e)[:160]}"
    if len(blocks) <= 1 or depth >= 2:
        raise RuntimeError(f"分镜结果为空({label}):{reason}")
    mid = len(blocks) // 2
    log.warning("storyboard.chunk.split_retry label=%s scenes=%d reason=%s",
                label, len(blocks), reason)
    return (_boards_for_part(ep, aspect, assets, "".join(blocks[:mid]),
                             _batch_label(blocks[:mid]), lang=lang, config_id=config_id,
                             depth=depth + 1)
            + _boards_for_part(ep, aspect, assets, "".join(blocks[mid:]),
                               _batch_label(blocks[mid:]), lang=lang, config_id=config_id,
                               depth=depth + 1))


def _storyboard_prompt(ep, aspect: str, assets: str, script_part: str,
                       label: str = "", total: int = 1) -> str:
    prompt = f"""剧本(第 {ep['episode_number']} 集,画面比例 {aspect}):
{script_part}

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

【video_prompt】本步不生成:video_prompt 由拆分完成后的「逐镜补写」步骤负责
(那里会拿到这一镜的 description/atmosphere 再写 3 秒分段)。这里输出 null,
不要自己编 —— 一次性写它会把单镜输出翻倍,实测就是这一步把 65,536 预算吐满的。
""")

    prompt += ("\n\n请输出 JSON 对象:"
               '{"storyboards":[…]};每镜字段 '
               'number/title/content/shot_type/angle/movement/location/time/description/'
               'atmosphere/result/image_prompt/bgm_prompt/sound_effect/'
               'setting_tags(数组)/characters(角色名数组)/props(道具名数组)/duration')
    if total > 1:
        # 分批时镜号必须每批从 1 起(落库前统一重编号);否则模型会接着上一批
        # 编出 20、21… 而我们按批追加,排序就会把批次顺序打乱
        prompt += (f"\n\n【分批说明】本次只输出 {label} 的分镜,不要输出其它场次;"
                   "镜号从 1 开始连续编号(落库时会统一重编号),"
                   "不要重复前面批次已经写过的镜头。")
    return prompt


def _save_board(b: dict, num: int, episode_id: int, ts: str, name_to_id: dict,
                scene_by_name: dict, prop_by_id: dict, prop_names: list) -> float:
    """落库一镜(幂等 upsert),返回该镜时长。

    拆出来是为了**分批增量落库**:前面批次成功就先写进库,失败批次只影响自己,
    用户不至于因为最后一场失败而看到「0 个分镜」。
    """
    scene_id = _match_scene(b, scene_by_name)
    inherit = (scene_by_name.get(b.get("location") or "", {}) or {}).get("setting_tags")
    tags = b.get("setting_tags") or inherit
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace("、", ",").split(",") if t.strip()]
    dur = _resolve_duration(b)
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
    return dur


def split_storyboards(episode_id: int, aspect: str = "9:16", config_id: int | None = None,
                      lang: str | None = None, on_progress=None,
                      on_chunk_failed=None, on_purged=None) -> int:
    """整集重新拆分分镜;返回数量(对齐原版 save_storyboards:全量替换 + 资产绑定)。

    与原版对齐的关键点:
    - 落库 **全字段**(title/shot_type/angle/movement/location/time/description/result/
      atmosphere/image_prompt/video_prompt/bgm_prompt/sound_effect/scene_id/setting_tags/duration);
      setting_tags 为空时从场景继承 —— 缺这些字段时 `refs.build_shot_reference_list`
      拿不到绑定、reference injection 就是空的,生图只能每次现调 Agent。
    - 同步写 `storyboard_characters`(带 variant_id)与 `storyboard_props`;
    - **清空本集旧分镜与已生成的视频文件**(purge_episode_storyboards)再从零拆
      —— 用户要求「重新拆分」= 彻底重来(2026-10-20);删除推迟到**第一批
      LLM 成功之后**,失败时旧内容原样留着(见下面 _purge_old 的注释);
    - 重算 `episodes.duration = ceil(Σ分镜时长 / 60)`。
    """
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("剧集不存在")
    script = ep["script_content"] or ""
    if not script.strip():
        raise RuntimeError("请先完成剧本改写")
    # ── 从零重来:清掉本集旧分镜 + 已生成的视频/首帧文件 ──
    # 以前是「按镜号幂等 upsert」,旧镜号没被覆盖就残留:新描述配旧视频,
    # 还白占着列表和合片(用户反馈「重新拆分,以前生成的怎么办」)。
    # UI 侧已先弹二次确认告知会删什么,这里才真删。
    #
    # ⚠️ 删除时机:推迟到**第一批 LLM 成功之后**。
    # 原来在任何 LLM 调用之前就 purge —— 鉴权失败 / 额度耗尽 / 网络全断 /
    # 模型连续返回不可解析内容时,旧分镜与**已付费生成的视频文件**已经被删光,
    # 用户最后只拿到一个空集(两头空)。漫画链路(comic.split_panels)早就是
    # 「LLM 成功之后才 purge」,这里跟上同一约定:失败时旧内容原样留着。
    def _purge_old() -> None:
        stats = purge_episode_storyboards(episode_id)
        if stats.get("shots"):
            log.info("storyboard.resplit.purged episode=%s shots=%d files=%d bytes=%d merges=%d",
                     episode_id, stats["shots"], stats["files"],
                     stats["bytes"], stats["merges"])
        if on_purged:
            on_purged(stats)
        _clear_episode_bindings(episode_id)

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
    ts = db.now()
    name_to_id = {r["name"]: r["id"] for r in chars}
    scene_by_name = {r["name"]: dict(r) for r in scenes}
    prop_by_id = {r["id"]: r["name"] for r in props}
    prop_names = [r["name"] for r in props]
    batches = _script_batches(script)
    total_dur = 0.0
    saved = 0
    failed: list[str] = []
    purged = False
    for bi, (label, part) in enumerate(batches, start=1):
        try:
            got = _boards_for_part(ep, aspect, assets, part, label,
                                   lang=lang, config_id=config_id)
        except RuntimeError as e:
            # 没给回调 = 老行为(整集失败);给了就记下来继续跑其它批,
            # 已经成功的前几批照常落库,用户至少能拿到那部分
            if on_chunk_failed is None:
                raise
            reason = str(e)[:200]
            log.warning("storyboard.chunk.failed episode=%s label=%s err=%s",
                        episode_id, label, reason)
            failed.append(label)
            on_chunk_failed(label, reason)
            if on_progress:
                on_progress(min(90, int(bi / len(batches) * 90)))
            continue
        # 第一批拿到内容了 → 这时才清旧分镜(从零重来)。
        # 全批失败时旧分镜与已生成的视频原样保留,不至于两头空。
        if not purged:
            _purge_old()
            purged = True
        # 批次内先按模型给的号排(它可能从 3 开始),再统一编成连续号
        got.sort(key=lambda b: (int(b.get("number") or 10 ** 6),))
        for b in got:
            saved += 1
            b["number"] = saved
            total_dur += _save_board(b, saved, episode_id, ts, name_to_id,
                                     scene_by_name, prop_by_id, prop_names)
        log.info("storyboard.chunk.done episode=%s chunk=%d/%d label=%s boards=%d total=%d",
                 episode_id, bi, len(batches), label, len(got), saved)
        if on_progress:
            on_progress(min(90, int(bi / len(batches) * 90)))
    if not saved:
        raise RuntimeError(f"分镜结果为空({len(failed)} 批全部失败:{'、'.join(failed)})")
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
    return saved


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


# ── 「重新拆分」= 彻底清空重来 ──
# 「重新拆分」时会被删掉的生成物字段(本集分镜行自己引用的媒体文件)
_PURGE_FILE_FIELDS = ("video_url", "composed_video_url", "first_frame_image",
                      "last_frame_image", "composed_image",
                      "narration_audio_url", "subtitle_url")
# 合片里只有这些扩展名算「视频」;漫画拼接长图(jpg/png)留着 —— 它跟漫画格绑定,
# 不在这次重拆的范围内,删了等于白丢一次拼接。
_VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v")


def _purge_media_files(urls: list[str]) -> tuple[int, int]:
    """删掉 media url 指向的本地文件;返回(删掉几个文件, 释放多少字节)。

    实现在 `pipeline.media_files` —— 漫画链路(`comic.purge_episode_comic_panels`)
    要用同一套边界检查,而 comic.py 不能 import 本模块(反向复用会成环)。
    """
    return media_files.purge_media_files(urls)


def purge_episode_storyboards(episode_id: int, delete_files: bool = True) -> dict:
    """彻底清空本集分镜:DB 行 + 磁盘上的生成物文件。返回清掉的统计。

    「重新拆分」按用户要求是**从零重来**(2026-10-20):旧分镜行、已生成的
    视频/首帧/尾帧/合图/配音/字幕文件全部清掉,拆完就是干干净净的新一集。

    为什么以前会错位:旧实现是「按 storyboard_number 幂等 upsert」—— 重拆出
    6 镜时只覆盖 1..6,原来第 7..10 镜的行**根本没人碰**。而绑定已经被
    `_clear_episode_bindings` 全清(新拆分只重建 1..6 的绑定),于是 7..10
    变成「描述还是旧的、绑定是空的、视频还在」的半残状态,还继续占着镜号
    出现在分镜列表和合片里(用户反馈:「重新拆分,以前生成的怎么办」)。

    只删**本集分镜行自己引用**的文件:
    - 角色/场景/道具资产图不在列 —— 它们跨集共用,删了别的集就废了;
    - 同一文件被多行引用时只删一次;
    - 路径必须落在 static 目录内,否则跳过(防越界删到别处)。
    """
    rows = db.q("SELECT * FROM storyboards WHERE episode_id=?", (episode_id,))
    urls: list[str] = []
    for r in rows:
        for f in _PURGE_FILE_FIELDS:
            v = (r[f] or "").strip()
            if v:
                urls.append(v)
    # 合片:只收视频文件(漫画拼接长图保留)
    merge_ids: list[int] = []
    for r in db.q("SELECT id, merged_url FROM video_merges WHERE episode_id=?", (episode_id,)):
        v = (r["merged_url"] or "").strip()
        if v and v.lower().endswith(_VIDEO_SUFFIXES):
            merge_ids.append(r["id"])
            urls.append(v)
    removed_files = 0
    freed = 0
    if delete_files:
        removed_files, freed = _purge_media_files(urls)
    # 子表先删,再删本体
    db.ex("DELETE FROM storyboard_characters WHERE storyboard_id IN "
          "(SELECT id FROM storyboards WHERE episode_id=?)", (episode_id,))
    db.ex("DELETE FROM storyboard_props WHERE storyboard_id IN "
          "(SELECT id FROM storyboards WHERE episode_id=?)", (episode_id,))
    db.ex("DELETE FROM storyboards WHERE episode_id=?", (episode_id,))
    for mid in merge_ids:
        db.ex("DELETE FROM video_merges WHERE id=?", (mid,))
    return {"shots": len(rows), "files": removed_files, "bytes": freed,
            "merges": len(merge_ids)}


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
    if names:
        # 一次 executemany = 一次 commit。原来每个角色一次 db.ex(每个 ex 都
        # commit 一次),一集几十镜就是几百次 fsync。
        db.exmany("INSERT OR IGNORE INTO storyboard_characters(storyboard_id,character_id,variant_id) "
                  "VALUES(?,?,?)", [(sb_id, cid, vid) for _n, cid, vid in names])
        if episode_id:
            db.exmany("INSERT OR IGNORE INTO episode_characters(episode_id,character_id) VALUES(?,?)",
                      [(episode_id, cid) for _n, cid, _v in names])
    # prop_by_id 是 **id → 名字** 映射(见 _save_board 的构造),按名字反查 id
    # 得转一下 —— 之前直接把 id→name 当 name→id 用,于是「模型给道具名字
    # (props: ["扇子"])」这条路永远查不到 id,道具绑不上分镜。
    prop_name_to_id = {name: pid for pid, name in prop_by_id.items()}
    props = _refs_to_names(b, "props", prop_name_to_id, prop_by_id)
    if props:
        db.exmany("INSERT OR IGNORE INTO storyboard_props(storyboard_id,prop_id) VALUES(?,?)",
                  [(sb_id, pid) for _n, pid, _v in props])
        if episode_id:
            db.exmany("INSERT OR IGNORE INTO episode_props(episode_id,prop_id) VALUES(?,?)",
                      [(episode_id, pid) for _n, pid, _v in props])

    # 兜底:正文里出现 @名字 也算绑定(模型漏给 characters/props 数组时)。
    # 这段曾经被误挪进 _refs_to_names 的 `return out` **之后** —— 变成永远
    # 不执行的死代码,兜底等于从来没生效过(且 mypy 报 4 个未定义名)。
    text = b.get("content") or ""
    if text:
        for name, cid in name_to_id.items():
            if cid and ("@" + name) in text:
                db.ex("INSERT OR IGNORE INTO storyboard_characters(storyboard_id,character_id) "
                      "VALUES(?,?)", (sb_id, cid))
        for name in prop_names:
            pid = prop_name_to_id.get(name)
            if pid and ("@" + name) in text:
                db.ex("INSERT OR IGNORE INTO storyboard_props(storyboard_id,prop_id) "
                      "VALUES(?,?)", (sb_id, pid))


def _refs_to_names(b: dict, key: str, id_by_name: dict, prop_by_id: dict) -> list:
    """把 characters/props 引用统一成 (名字, id, variant_id);兼容名字数组与 id 数组。

    id_by_name:**名字 → id** 映射(角色传 name_to_id,道具传 prop_name_to_id)。
    prop_by_id:**id → 名字** 映射(给 id 数组分支查名字用)。
    """
    out: list = []
    id_key = "char_ids" if key == "characters" else "prop_ids"
    table = "characters" if key == "characters" else "props"
    # id 数组:一次 IN 查完,别一个 id 一次 db.q1(N+1)
    raw_ids: list[int] = []
    for cid in b.get(id_key) or []:
        try:
            raw_ids.append(int(cid))
        except (TypeError, ValueError):
            continue
    if raw_ids:
        marks = ",".join("?" * len(raw_ids))
        for r in db.q(f"SELECT id, name FROM {table} WHERE id IN ({marks})", tuple(raw_ids)):
            out.append((r["name"], r["id"], None))
    for ref in b.get(key) or []:
        name = (ref.get("name") if isinstance(ref, dict) else str(ref)) or ""
        name = name.lstrip("@").strip()
        cid = id_by_name.get(name)
        if cid:
            vid = (ref.get("variant_id") if isinstance(ref, dict) else None)
            out.append((name, cid, vid))
    return out

def gen_video_prompts(episode_id: int, config_id: int | None = None, lang: str | None = None,
                      on_progress=None) -> int:
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
    for idx, r in enumerate(rows, start=1):
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
        finally:
            if on_progress:
                on_progress(int(idx / len(rows) * 100))
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
                                    config_id=config_id,
                                    system=prompts.with_language_suffix(system, lang)).strip()
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
        failed_batches: list[tuple[str, str]] = []
        purged: dict = {}
        try:
            # 第一阶段:拆分(0-90%)。每批成功即落库,失败批次只影响自己 ——
            # 不会再出现「最后一场失败 → 整集 0 个分镜」。
            n = split_storyboards(
                episode_id, aspect, config_id=config_id, lang=lang,
                on_progress=lambda p: TM.set_task_progress(tid, min(90, int(p * 0.9))),
                on_chunk_failed=lambda label, reason: failed_batches.append((label, reason)),
                on_purged=purged.update,
            )
            removed = clean_junk_storyboards(episode_id)
            n = db.q1("SELECT COUNT(*) c FROM storyboards WHERE episode_id=?", (episode_id,))["c"]
            if n == 0:
                raise RuntimeError("拆分结束但没有写入任何分镜,请重试")
            # 第二阶段:逐镜补 video_prompt(90-100%)。失败不回滚拆分结果 ——
            # 分镜本身已经可用,提示词还能从「批量视频提示词」按钮单独补。
            vp = 0
            try:
                TM.set_stage(tid, "video_prompts")
                vp = gen_video_prompts(
                    episode_id, config_id=config_id, lang=lang,
                    on_progress=lambda p: TM.set_task_progress(tid, 90 + int(p * 0.1)),
                )
            except Exception as e:  # noqa: BLE001
                log.warning("storyboard.video_prompts.failed episode=%s err=%s",
                            episode_id, str(e)[:200])
            msg = f"拆出 {n} 个分镜,补齐 {vp} 条视频提示词"
            if purged.get("shots"):
                msg += (f";已清空旧分镜 {purged['shots']} 个"
                        f"(删除生成文件 {purged.get('files', 0)} 个)")
            if vp < n:
                msg += f"({n - vp} 条待补,可用「批量视频提示词」重试)"
            if failed_batches:
                # 已落库的部分照常可用;失败场次在消息里点名,方便只补那几场
                msg += ";未完成:" + "、".join(lbl for lbl, _ in failed_batches)
                msg += "(已保留其余分镜,可再次拆分补齐)"
            if removed:
                msg += f";已清理 {removed} 个残缺行"
            TM.finish_task(tid, "completed", result_url=str(n), local_path=msg)
            return n
        except Exception as e:  # noqa: BLE001
            TM.finish_task(tid, "failed", error=str(e)[:500])
            raise

    return TASKMGR.submit("storyboard_split", job, episode_id=episode_id,
                          drama_id=ep["drama_id"])
