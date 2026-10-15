# -*- coding: utf-8 -*-
"""镜头级工具:首帧图生成 / 字幕烧录 / @角色参考图收集。

字幕/合成通过 ffmpeg 子进程完成(不向用户暴露技术细节)。
"""
from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

from ..ai import image_client, video_client
from ..core import config, db


def _ffmpeg() -> str:
    ff = config.find_ffmpeg()
    if not ff:
        raise RuntimeError("未找到 ffmpeg")
    return ff


def collect_reference_images(episode_id: int, storyboard_id: int, limit: int | None = None) -> list[str]:
    """该分镜的参考图本地路径列表(单一真相源,顺序=角色→场景→道具)。

    不再用正则猜 @名字,而是走 refs.build_shot_reference_list,与 @图片N 序号严格对齐
    (对齐原版 buildShotReferenceList,修复 @名字 与 reference_image_urls 序号错位 bug)。
    """
    from . import refs as refs_mod
    sb = db.q1("SELECT * FROM storyboards WHERE id=?", (storyboard_id,))
    if not sb:
        return []
    sb = dict(sb)
    out = []
    for item in refs_mod.build_shot_reference_list(sb, limit):
        p = config.media_url_to_path(item["image_url"])
        if p.exists():
            out.append(str(p))
    return out


def resolve_prompt(sb: dict, limit: int | None = None) -> str:
    """分镜提示词的 @名字 → @图片N名字 序号替换(名字按长度降序匹配,避免前缀误命中)。"""
    from . import refs as refs_mod
    return refs_mod.resolve_video_prompt_refs(sb.get("video_prompt") or sb.get("content") or "", sb, limit)


_ASPECT_SIZE = {"9:16": "1080x1920", "16:9": "1920x1080", "1:1": "1024x1024",
               "3:4": "1080x1440", "4:3": "1440x1080", "21:9": "2560x1080"}


def _aspect_to_size(aspect: str | None) -> str:
    """项目画幅 → 生图像素尺寸;未知画幅回退 16:9。"""
    return _ASPECT_SIZE.get((aspect or "16:9").strip(), _ASPECT_SIZE["16:9"])


def _drama_aspect_of(episode_id: int) -> str:
    row = db.q1("SELECT d.aspect_ratio FROM dramas d JOIN episodes e ON e.drama_id=d.id "
                "WHERE e.id=?", (episode_id,))
    return ((row or {}).get("aspect_ratio") or "16:9") if row else "16:9"


def generate_first_frame(episode_id: int, storyboard_id: int, config_id: int | None = None) -> str:
    """生成首帧图并写 storyboards.first_frame_image;返回 /static URL。

    首帧必须是一张「有景物、有人物」的开场定场画面(用户要求):
    - 取 video_prompt 的信息头 + 第一个 [0-3秒] 段(即开场镜头的景别/人物/动作),
      @名字 先解析成可读名字,不要把 @ 标记直接喂给出图模型;
    - 带上本镜参考图(角色形象/场景),人物相貌与场景陈设才能对上;
    - 明确要求出场人物全部入画、按描述站位,禁止空镜/背影/黑帧开场。

    people 数:**以 storyboard_characters 实际绑定为准**,不再从 @名字 正则猜
    (实测 sb 60 绑了 3 角色但头行只露 1 个名字 → 旧逻辑给 people=1 → 模型
    按 1 人生图,跟 3 张参考图打架,出 2 个「陈默」或者干脆空镜)。
    """
    sb = db.q1("SELECT * FROM storyboards WHERE id=?", (storyboard_id,))
    if not sb:
        raise RuntimeError("分镜不存在")
    ep = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))
    style = db.style_prompt(db.drama_style(ep["drama_id"]))
    resolved = resolve_prompt(dict(sb)) or (sb["content"] or "")[:300]
    # 开场段 = 信息头(出场人物/场景)+ 首个时间段;找不到分段标记就用整段前 400 字
    lines = [ln.strip() for ln in resolved.splitlines() if ln.strip()]
    head = lines[0] if lines else ""
    seg = next((ln for ln in lines[1:] if re.match(r"^\[\d", ln)), "")
    opening = "。".join(x for x in (head, seg) if x)[:600] or resolved[:400]
    # 实际绑定的角色数 —— 以这个为准
    n_chars = db.q1(
        "SELECT COUNT(*) c FROM storyboard_characters WHERE storyboard_id=?",
        (storyboard_id,))["c"]
    if n_chars:
        people = min(6, max(1, n_chars))
    else:
        # 没绑角色 → 退化到正则猜(空镜/纯场景/纯道具的情况)
        m = re.findall(r"[@、,，]\s*([^\s@、,，。]+)", head or "")
        people = max(1, min(6, len(m))) if m else 0  # 0 = 空镜

    # 关键:在 prompt 里把「图 N」和「角色真名」绑死 —— 这是底部 guard 文字约束
    # 拉不动的根本原因。ag 模型拿到的就是裸图列表,prompt 不告诉它「图 1 是谁」,
    # 它就按自己想象混 —— 实测陈默(平头中年)给出一个长发男,就是混了张雯的图。
    # 做法:在 prompt 开头显式列「人物 N(图 N)= 角色名」,模型既能在 prompt 里读到
    # 绑定关系,也更倾向于按 prompt 文字而非自己脑补。
    sb_dict = dict(sb)
    from . import refs as refs_mod
    ref_meta = refs_mod.build_shot_reference_list(sb_dict)
    char_bindings: list[str] = []
    for i, item in enumerate(ref_meta, start=1):
        if item.get("kind") == "character" and item.get("name"):
            char_bindings.append(f"人物图{i}={item['name']}")
    identity_lines = []
    for i, b in enumerate(char_bindings):
        identity_lines.append(
            f"- {b}: 严格按图 {i+1} 的五官、发型、体型、年龄、服装、配饰 —— 禁止模型自由改动。"
        )
    if char_bindings:
        identity_block = (
            "【人物身份锁定 / 严格按参考图外貌生成】\n"
            + "\n".join(identity_lines)
            + "\n(注意:图 1 是首位参考 = 主角本人,头发/服装/体型以它为准。)"
        )
    else:
        identity_block = ""
    # 去掉裸 @:让 prompt 用「图 1(陈默)」这种绑定写法,而不是只剩数字
    opening_with_names = opening
    if char_bindings:
        # 把 @图片1 → 图1(陈默),@图片2 → 图2(张雯)…
        # 用 build_shot_reference_list 顺序(和 reference_images 一一对应)
        for i, item in enumerate(ref_meta, start=1):
            if item.get("kind") == "character" and item.get("name"):
                opening_with_names = opening_with_names.replace(
                    f"@图片{i}", f"图{i}({item['name']})")
        # 残留的 @数字 兜底
        opening_with_names = opening_with_names.replace("@", "")
    # 横/竖屏指令:参数 size 在 agnes 那边会被翻译成 9:16 比例,
    # 但 prompt 里不写明模型常按横屏习惯构图(横构图人物居中、远处留天空)。
    # 这里再写一遍画幅 + 竖屏构图特征,让模型先想清楚再画。
    aspect = _drama_aspect_of(episode_id)
    is_vertical = aspect in ("9:16", "3:4")
    is_horizontal = aspect in ("16:9", "4:3", "21:9")
    if is_vertical:
        layout_hint = (
            f"【画幅】本图为竖屏构图({aspect}),主体人物居中或略偏下,上下方向留更多空间 —— "
            f"竖屏不要横构图:不要把人物放在画面两侧,不要让背景横向延展。"
        )
    elif is_horizontal:
        layout_hint = (
            f"【画幅】本图为横屏构图({aspect}),主体人物居中或略偏左,左右方向留更多空间。"
        )
    else:
        layout_hint = f"【画幅】本图为 {aspect} 构图。"
    prompt = (f"{style}。{identity_block}\n{layout_hint}\n"
              f"开场定场帧:按下面镜头描述生成视频第一帧画面,必须是包含出场人物与场景环境的"
              f"完整画面 —— 人物全部入画、按描述站位,景别与运镜起点一致,不许空镜、背影、剪影或黑帧。\n"
              f"{opening_with_names}\n电影质感,构图完整")
    ref_list = collect_reference_images(episode_id, storyboard_id)
    # 首帧必须按项目画幅出图 —— 这是竖屏能不能落地的**决定性一环**:
    # 视频侧只要带了 first_frame 就走 keyframe 模式(优先级高于 reference),
    # 而 Agnes 在 keyframe 模式下按首帧画幅出片,首帧是横的成片就一定是横的。
    # 之前这里从不传 size,用的是 provider 默认 16:9(实测首帧全是 2624x1472),
    # 于是 aspect_ratio=9:16 被完全架空,17 个分镜视频全成了 1280x704 横屏。
    size = _aspect_to_size(_drama_aspect_of(episode_id))
    out, _p = image_client.generate_image(prompt, out_name=f"ff_{storyboard_id}.png",
                                          config_id=config_id, reference_images=ref_list,
                                          people=people, size=size)
    url = config.path_to_media_url(out)
    db.ex("UPDATE storyboards SET first_frame_image=?, updated_at=? WHERE id=?", (url, db.now(), storyboard_id))
    return url


def generate_last_frame(episode_id: int, storyboard_id: int,
                        config_id: int | None = None) -> str:
    """生成尾帧图并写 storyboards.last_frame_image;返回 /static URL。

    尾帧给 Agnes 的 keyframe 模式约束**结束构图与过渡**,短剧的转场/运镜由此可控。
    与 generate_first_frame 的差别只有一处关键:取**最后一个**时间段而不是开场段,
    且必须已经存在首帧 —— 尾帧是「首帧之后到达的状态」,没有首帧时无从对照。

    身份锁定块与画幅指令完全复用首帧的写法:keyframe 模式下 Agnes 会丢弃参考图
    (官方规则:keyframe 禁止同时带 images/audios/videos),所以人物相貌只能靠
    **提示词里锁死**,尾帧与首帧各生成一次,两次都必须锁同样的身份。
    """
    sb = db.q1("SELECT * FROM storyboards WHERE id=?", (storyboard_id,))
    if not sb:
        raise RuntimeError("分镜不存在")
    if not (sb["first_frame_image"] or "").strip():
        raise RuntimeError("请先生成首帧,再生成尾帧")
    ep = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))
    style = db.style_prompt(db.drama_style(ep["drama_id"]))
    resolved = resolve_prompt(dict(sb)) or (sb["content"] or "")[:300]

    # 尾段 = 最后一个 [n-m秒] 分段;没有分段标记就用整段描述
    lines = [ln.strip() for ln in resolved.splitlines() if ln.strip()]
    segs = [ln for ln in lines if re.match(r"^\[\d", ln)]
    head = lines[0] if lines else ""
    ending = segs[-1] if segs else resolved[-400:]

    n_chars = db.q1(
        "SELECT COUNT(*) c FROM storyboard_characters WHERE storyboard_id=?",
        (storyboard_id,))["c"]
    people = min(6, max(1, n_chars)) if n_chars else 0

    sb_dict = dict(sb)
    from . import refs as refs_mod
    ref_meta = refs_mod.build_shot_reference_list(sb_dict)
    char_bindings: list[str] = []
    for i, item in enumerate(ref_meta, start=1):
        if item.get("kind") == "character" and item.get("name"):
            char_bindings.append(f"人物图{i}={item['name']}")
    if char_bindings:
        identity_block = (
            "【人物身份锁定 / 严格按参考图外貌生成】\n"
            + "\n".join(
                f"- {b}: 严格按图 {i + 1} 的五官、发型、体型、年龄、服装、配饰 —— 禁止模型自由改动。"
                for i, b in enumerate(char_bindings))
            + "\n(注意:图 1 是首位参考 = 主角本人,头发/服装/体型以它为准。"
              "本图是视频的**最后一帧**,必须与首帧保持同一人物、同一场景、同一服装。)"
        )
    else:
        identity_block = ""

    ending_with_names = ending
    for i, item in enumerate(ref_meta, start=1):
        if item.get("kind") == "character" and item.get("name"):
            ending_with_names = ending_with_names.replace(
                f"@图片{i}", f"图{i}({item['name']})")
    ending_with_names = ending_with_names.replace("@", "")

    aspect = _drama_aspect_of(episode_id)
    if aspect in ("9:16", "3:4"):
        layout_hint = (f"【画幅】本图为竖屏构图({aspect}),主体人物居中或略偏下 —— "
                       f"竖屏不要横构图:不要把人物放在画面两侧。")
    elif aspect in ("16:9", "4:3", "21:9"):
        layout_hint = f"【画幅】本图为横屏构图({aspect}),主体人物居中或略偏左。"
    else:
        layout_hint = f"【画幅】本图为 {aspect} 构图。"

    prompt = (f"{style}。{identity_block}\n{layout_hint}\n"
              f"收场定帧:这是视频的**最后一帧**画面,动作已经走到末段、即将结束 —— "
              f"不是开场画面,不要画成起始状态。场景与人物必须与首帧完全一致,只推进到结束状态。\n"
              f"前情:{head}\n末段动作:{ending_with_names}\n电影质感,构图完整")
    ref_list = collect_reference_images(episode_id, storyboard_id)
    size = _aspect_to_size(aspect)
    out, _p = image_client.generate_image(prompt, out_name=f"lf_{storyboard_id}.png",
                                          config_id=config_id, reference_images=ref_list,
                                          people=people, size=size)
    url = config.path_to_media_url(out)
    db.ex("UPDATE storyboards SET last_frame_image=?, updated_at=? WHERE id=?",
          (url, db.now(), storyboard_id))
    return url


def _extract_dialogue(text: str) -> str:
    lines = re.findall(r"「([^」]+)」|「([^」]+)」", text or "")
    merged = " / ".join(a or b for a, b in lines)[:220]
    return merged or (text or "")[:120]


def burn_subtitle(storyboard_id: int) -> str:
    """把旁白/台词作为字幕烧录进镜头视频,写 composed_video_url;返回 URL。"""
    sb = db.q1("SELECT * FROM storyboards WHERE id=?", (storyboard_id,))
    if not sb:
        raise RuntimeError("分镜不存在")
    src_url = sb["video_url"] or sb["composed_video_url"]
    if not src_url:
        raise RuntimeError("该镜头还没有视频")
    src = config.media_url_to_path(src_url)
    if not src.exists():
        raise RuntimeError("镜头视频文件不存在")
    sub_text = (sb["narration"] or "").strip() or _extract_dialogue(sb["content"])
    if not sub_text:
        raise RuntimeError("没有可用于字幕的文本(旁白/台词)")
    srt = config.STATIC_DIR / "videos" / f"srt_{uuid.uuid4().hex[:8]}.srt"
    srt.write_text(f"1\n00:00:00,200 --> 00:00:08,000\n{sub_text}\n", encoding="utf-8")
    out = config.STATIC_DIR / "videos" / f"sub_{uuid.uuid4().hex[:10]}.mp4"
    try:
        proc = subprocess.run(
            [_ffmpeg(), "-y", "-i", str(src),
             "-vf", f"subtitles={srt.as_posix()}:force_style='FontSize=14,Outline=1,MarginV=24'",
             "-c:a", "copy", str(out)],
            capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"字幕烧录失败: {proc.stderr[-300:]}")
    finally:
        srt.unlink(missing_ok=True)
    url = config.path_to_media_url(out)
    db.ex("UPDATE storyboards SET composed_video_url=?, updated_at=? WHERE id=?", (url, db.now(), storyboard_id))
    return url


def compose_from_image(episode_id: int, storyboard_id: int, resolution: str = "720p",
                       config_id: int | None = None,
                       on_progress=None) -> str:
    """图生视频:用首帧图生成镜头视频(无首帧则先生成),写 video_url。

    尾帧与 seed 都从 storyboards 行上读,不额外加参数 —— 调用点(按钮/批量)本来就
    只传 shot_id,让 DB 成为这两个可选参数的真相源,免得两条路径各记一份。
    """
    sb = db.q1("SELECT * FROM storyboards WHERE id=?", (storyboard_id,))
    if not sb:
        raise RuntimeError("分镜不存在")
    first = sb["first_frame_image"]
    if not first:
        generate_first_frame(episode_id, storyboard_id, config_id=config_id)
        sb = db.q1("SELECT * FROM storyboards WHERE id=?", (storyboard_id,))
        first = sb["first_frame_image"]
    ref_list = collect_reference_images(episode_id, storyboard_id)
    # 视频提示词必须拼风格前缀 —— 与 generate_first_frame 同源。video_prompt
    # 表里只存「0-3 秒:...」的镜头描述,不带画风,直接喂给视频模型会被它默认成
    # 通用动画/二次元风(用户反馈:选了 3D 漫剧,视频却全是动画风 —— 根因)。
    ep = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))
    style = db.style_prompt(db.drama_style(ep["drama_id"]))
    prompt = resolve_prompt(dict(sb))
    prompt = f"{style}。{prompt}" if prompt else style
    # 项目画幅透传(对齐参考 record.aspectRatio):不传 seedance 默认 1:1,竖屏项目全变方图
    d_row = db.q1("""SELECT d.aspect_ratio FROM dramas d JOIN episodes e ON e.drama_id=d.id
                     WHERE e.id=?""", (episode_id,))
    last = (sb["last_frame_image"] or "").strip()
    path, _provider = video_client.generate_video(
        prompt[:1500], resolution=resolution,
        duration=int(sb["duration"] or 8),
        first_frame=config.media_url_to_path(first), reference_images=ref_list,
        config_id=config_id,
        aspect_ratio=(d_row["aspect_ratio"] if d_row else None) or None,
        last_frame=config.media_url_to_path(last) if last else None,
        seed=(sb["video_seed"] if "video_seed" in sb.keys() else None) or None,
        on_progress=on_progress)
    db.ex("UPDATE storyboards SET video_url=?, status='completed', updated_at=? WHERE id=?",
          (config.path_to_media_url(path), db.now(), storyboard_id))
    return config.path_to_media_url(path)
