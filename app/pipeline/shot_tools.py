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
    opening = opening.replace("@", "")
    people = 1
    for ln in (head,):
        m = re.findall(r"[@、,，]\s*([^\s@、,，。]+)", ln or "")
        people = max(1, min(6, len(m))) if m else 1
    prompt = (f"{style}。开场定场帧:按下面镜头描述生成视频第一帧画面,必须是包含出场人物与场景环境的"
              f"完整画面 —— 人物全部入画、按描述站位,景别与运镜起点一致,不许空镜、背影、剪影或黑帧。\n"
              f"{opening}\n电影质感,构图完整")
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
                       config_id: int | None = None) -> str:
    """图生视频:用首帧图生成镜头视频(无首帧则先生成),写 video_url。"""
    sb = db.q1("SELECT * FROM storyboards WHERE id=?", (storyboard_id,))
    if not sb:
        raise RuntimeError("分镜不存在")
    first = sb["first_frame_image"]
    if not first:
        generate_first_frame(episode_id, storyboard_id, config_id=config_id)
        sb = db.q1("SELECT * FROM storyboards WHERE id=?", (storyboard_id,))
        first = sb["first_frame_image"]
    ref_list = collect_reference_images(episode_id, storyboard_id)
    prompt = resolve_prompt(dict(sb))
    # 项目画幅透传(对齐参考 record.aspectRatio):不传 seedance 默认 1:1,竖屏项目全变方图
    d_row = db.q1("""SELECT d.aspect_ratio FROM dramas d JOIN episodes e ON e.drama_id=d.id
                     WHERE e.id=?""", (episode_id,))
    path, _provider = video_client.generate_video(
        prompt[:1500], resolution=resolution,
        duration=int(sb["duration"] or 8),
        first_frame=config.media_url_to_path(first), reference_images=ref_list,
        config_id=config_id,
        aspect_ratio=(d_row["aspect_ratio"] if d_row else None) or None)
    db.ex("UPDATE storyboards SET video_url=?, status='completed', updated_at=? WHERE id=?",
          (config.path_to_media_url(path), db.now(), storyboard_id))
    return config.path_to_media_url(path)
