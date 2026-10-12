# -*- coding: utf-8 -*-
"""片头(intro)系统 —— 对齐原版 3990bb8 / 56cd571 / 9ee15f4 / d262ac1。

两种模式(可同时开):
  intro_card    黑底标题卡前置到成片最前(默认开)
  intro_overlay 文字叠加在正片画面开头

三个 ffmpeg 坑(务必规避,原版踩过):
  1. fontfile 路径带中文 → 静默渲染为空(不报错)→ 合成时拷成 ASCII 临时文件
  2. 盘符冒号必须转义 + 正斜杠化 + 单引号包裹,否则被 filtergraph 选项切分器劈断
  3. 片头文字走 textfile=(UTF-8 临时文件),完全绕开 text= 的转义地狱
"""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from ..core import config, db

# 字体展示名(对齐原版 FONT_DISPLAY_NAMES)
FONT_DISPLAY_NAMES = {
    "SourceHanSansSC-Bold.otf": "思源黑体 · 粗(现代大气)",
    "LXGWWenKai-Regular.ttf": "霞鹜文楷(文艺书卷)",
    "MaShanZheng-Regular.ttf": "马善政毛笔楷书(古装爽剧)",
    "ZCOOLXiaoWei-Regular.ttf": "站酷小薇(细宋甜宠)",
    "ZCOOLKuaiLe-Regular.ttf": "站酷快乐体(欢乐综艺)",
    "ZCOOLQingKeHuangYou-Regular.ttf": "站酷庆科黄油体(厚重标题)",
    "LongCang-Regular.ttf": "龙藏行书(潇洒手写)",
    "LiuJianMaoCao-Regular.ttf": "柳建毛草(狂草泼墨)",
    "ZhiMangXing-Regular.ttf": "之芒行楷(利落行楷)",
    "msyh.ttc": "微软雅黑(系统)",
}
SYSTEM_FALLBACKS = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"]

FONT_EXTS = (".ttf", ".ttc", ".otf")
SIZE_PCT_RANGE = (0.02, 0.5)
POS_RANGE = (0.0, 1.0)
DUR_RANGE = (1.0, 10.0)


def font_dir() -> Path:
    return config.ROOT_DIR / "app" / "assets" / "fonts"


def list_fonts() -> list[dict]:
    """字体清单(按展示名排序,保证下拉稳定)。"""
    d = font_dir()
    items = []
    if d.is_dir():
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in FONT_EXTS:
                items.append({"file": f.name, "name": FONT_DISPLAY_NAMES.get(f.name, f.stem)})
    return sorted(items, key=lambda x: x["name"])


def resolve_font(name: str | None) -> Path | None:
    """指定字体 → 目录第一个 → 系统兜底;全无返回 None。"""
    d = font_dir()
    if name:
        cand = d / Path(str(name)).name          # 防目录穿越
        if cand.exists() and cand.suffix.lower() in FONT_EXTS:
            return cand
    if d.is_dir():
        files = sorted(f for f in d.iterdir() if f.suffix.lower() in FONT_EXTS)
        if files:
            return files[0]
    for fb in SYSTEM_FALLBACKS:
        c = d / fb
        if c.exists():
            return c
    return None


def _clamp(v, lo, hi, default=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f or f in (float("inf"), float("-inf")):   # NaN / inf
        return default
    return max(lo, min(hi, f))


def sanitize_intro(payload: dict) -> dict:
    """按原版校验规则清洗 8 个字段(越界/非有限 → None=自动)。"""
    name = payload.get("intro_font")
    if name:
        name = Path(str(name)).name
        if not re.search(r"\.(ttf|ttc|otf)$", name, re.I):
            name = None
    return {
        "intro_title": (str(payload.get("intro_title") or "").strip()[:60] or None),
        "intro_font": name,
        "intro_font_size": _clamp(payload.get("intro_font_size"), *SIZE_PCT_RANGE),
        "intro_pos_x": _clamp(payload.get("intro_pos_x"), *POS_RANGE),
        "intro_pos_y": _clamp(payload.get("intro_pos_y"), *POS_RANGE),
        "intro_duration": _clamp(payload.get("intro_duration"), *DUR_RANGE),
        "intro_card": 1 if payload.get("intro_card") else 0,
        "intro_overlay": 1 if payload.get("intro_overlay") else 0,
    }


def intro_card_metrics(title: str, ref_w: int, ref_h: int) -> dict:
    """自适应默认:CJK 算 1 倍字号宽,其它 0.6。"""
    units = sum(1.0 if ord(c) > 0x2E80 else 0.6 for c in title or "")
    units = max(1.0, units)
    fs = max(28, min(round(ref_h * 0.09), int(ref_w * 0.86 / units)))
    dur = min(4.0, max(2.6, 2.0 + 0.12 * units))
    return {"font_size": fs, "duration": round(dur, 2)}


def esc_path(p) -> str:
    """ffmpeg 路径转义:正斜杠 + 冒号转义(盘符)。"""
    return str(p).replace("\\", "/").replace(":", r"\:")


def _make_temp_font(font: Path) -> Path:
    """拷成 ASCII 临时文件(ffmpeg 对中文路径静默渲染为空)。"""
    tmp_dir = config.STATIC_DIR / "merged"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dst = tmp_dir / f"intro-font-{uuid.uuid4().hex}{font.suffix}"
    shutil.copy2(font, dst)
    return dst


def _make_temp_text(title: str) -> Path:
    tmp_dir = config.STATIC_DIR / "merged"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dst = tmp_dir / f"intro-txt-{uuid.uuid4().hex}.txt"
    dst.write_text(title or "", encoding="utf-8")   # UTF-8 无 BOM
    return dst


def build_intro_spec(drama_id: int, title_override: str | None = None,
                     card: bool | None = None, overlay: bool | None = None,
                     ref_w: int = 1280, ref_h: int = 720) -> dict | None:
    """从 dramas 读片头配置构造 IntroSpec;未启用返回 None。"""
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    if not d:
        return None
    title = (title_override or d["intro_title"] or d["title"] or "").strip()[:60]
    if not title:
        return None
    c = (d["intro_card"] if card is None else (1 if card else 0))
    o = (d["intro_overlay"] if overlay is None else (1 if overlay else 0))
    if not c and not o:
        return None
    font = resolve_font(d["intro_font"])
    if not font:
        raise RuntimeError("未找到可用字体(片头需要字体文件),请把 .ttf/.otf 放入 app/assets/fonts/")
    auto = intro_card_metrics(title, ref_w, ref_h)
    fs = d["intro_font_size"]
    font_size = max(12, min(round(ref_h * float(fs)), ref_h)) if fs else auto["font_size"]
    dur = float(d["intro_duration"]) if d["intro_duration"] else auto["duration"]
    dur = max(DUR_RANGE[0], min(DUR_RANGE[1], dur))
    return {
        "title": title, "card": bool(c), "overlay": bool(o),
        "font_path": str(font), "font_size": int(font_size),
        "pos_x": d["intro_pos_x"], "pos_y": d["intro_pos_y"],
        "duration": round(dur, 2), "ref_w": ref_w, "ref_h": ref_h,
    }


def render_intro_clip(spec: dict, fps_hint: float = 30.0) -> Path:
    """把标题卡渲染成独立视频片段(h264+aac),供**无损 concat** 前置到成片。

    此前片头一律走 filter_complex 整段重编码(正片跟着再压一遍,有损)。改为:
    标题卡单独按 ref_w/ref_h 渲染成 mp4,与正片一起过 auto_merge 的 concat demuxer
    (-c copy,正片零转码);若片段指纹与正片不一致,auto_merge 只对齐这一个异类片段。
    片头名取 spec['title'](行内输入 → 项目片头名 → 剧名 的链路在 build_intro_spec)。
    """
    import subprocess
    ff = config.find_ffmpeg()
    if not ff:
        raise RuntimeError("未找到 ffmpeg,请安装或设置 FFMPEG_BIN 环境变量。")
    font_tmp = _make_temp_font(Path(spec["font_path"]))
    txt_tmp = _make_temp_text(spec["title"])
    f, t = esc_path(font_tmp), esc_path(txt_tmp)
    fs, dur = spec["font_size"], spec["duration"]
    fade = min(0.4, dur / 3)
    px, py = spec.get("pos_x"), spec.get("pos_y")
    x_expr = f"w*{px}-text_w/2" if px is not None else "(w-text_w)/2"
    y_expr = f"h*{py}-text_h/2" if py is not None else "(h-text_h)/2"
    fps_s = f"{max(1.0, float(fps_hint or 30.0)):.3f}".rstrip("0").rstrip(".")
    out = config.STATIC_DIR / "merged" / f"intro_{uuid.uuid4().hex[:8]}.mp4"
    vf = (f"drawtext=fontfile='{f}':textfile='{t}':fontcolor=white:fontsize={fs}"
          f":x={x_expr}:y={y_expr}"
          f",fade=t=in:st=0:d={fade},fade=t=out:st={dur - fade}:d={fade}"
          f",format=yuv420p,setsar=1")
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i",
           f"color=c=black:s={spec['ref_w']}x{spec['ref_h']}:r={fps_s}:d={dur}",
           "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
           "-t", f"{dur}",
           "-vf", vf,
           "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
           "-shortest", "-movflags", "+faststart", str(out)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"片头片段渲染失败:{proc.stderr[-300:]}")
    finally:
        font_tmp.unlink(missing_ok=True)
        txt_tmp.unlink(missing_ok=True)
    return out


def _drawtext(font: str, text: str, fs: int, x_expr: str, y_expr: str,
              alpha_expr: str | None = None, enable: str | None = None) -> str:
    s = (f"drawtext=fontfile='{font}':textfile='{text}':fontcolor=white:fontsize={fs}"
         f":x={x_expr}:y={y_expr}")
    if alpha_expr:
        s += f":alpha='{alpha_expr}'"
    if enable:
        s += f":enable='{enable}'"
    return s


def build_intro_filters(intro: dict) -> tuple[list[str], list[str], str | None, list[Path]]:
    """生成片头 filter 片段。

    返回 (视频前置片段, 音频前置片段, 尾部叠加片段, 临时文件列表)。
    ★ 叠加只在尾部实现一次(原版 56cd571 修的双重叠加黑场坑)。
    """
    font_tmp = _make_temp_font(Path(intro["font_path"]))
    txt_tmp = _make_temp_text(intro["title"])
    temps = [font_tmp, txt_tmp]
    f, t = esc_path(font_tmp), esc_path(txt_tmp)
    fs = intro["font_size"]
    dur = intro["duration"]
    fade = min(0.4, dur / 3)
    px, py = intro["pos_x"], intro["pos_y"]
    x_expr = (f"w*{px}-text_w/2" if px is not None else "(w-text_w)/2")
    y_expr = (f"h*{py}-text_h/2" if py is not None else "(h-text_h)/2")

    v_parts: list[str] = []
    a_parts: list[str] = []
    if intro["card"]:
        v_parts.append(
            f"color=c=black:s={intro['ref_w']}x{intro['ref_h']}:r=30:d={dur},"
            + _drawtext(f, t, fs, x_expr, y_expr)
            + f",setsar=1,fade=t=in:st=0:d={fade},fade=t=out:st={dur - fade}:d={fade},"
              f"format=yuv420p[vIntro]")
        a_parts.append(
            f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration={dur}[aIntro]")

    overlay: str | None = None
    if intro["overlay"]:
        t0 = dur if intro["card"] else 0.0        # 有卡片时整体顺延
        t1 = t0 + dur
        alpha = (f"if(lt(t,{t0}),0,"
                 f"if(lt(t,{t0 + fade}),(t-{t0})/{fade},"
                 f"if(lt(t,{t1 - fade}),1,max(0,({t1}-t)/{fade}))))")
        overlay = _drawtext(f, t, fs, x_expr, y_expr,
                           alpha_expr=alpha, enable=f"lte(t,{t1})")
    return v_parts, a_parts, overlay, temps
