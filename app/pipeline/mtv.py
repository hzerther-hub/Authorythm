# -*- coding: utf-8 -*-
"""MTV/MV 项目线:歌曲管理 + 全静音合并 + 铺歌成片。

对齐参考项目(E:\\xiaoshuo)的 MTV 流水线,交接要点(MV生成交换文档):
  · MTV 项目成片**全静音**:镜头原声与旁白音轨一律不要,歌曲是唯一声音;
  · 铺歌 = 无声画面 + MP3:`ffmpeg -i 无声成片 -i 歌曲 -map 0:v -map 1:a
    -c:v copy -c:a aac -shortest`;
  · 分镜总时长 ≈ 歌曲时长(每镜 8-12 秒),画幅默认 9:16。

数据落 dramas.metadata.mtv:{lyrics, song_duration, song_url}(不新增表列,
与 clone 的 metadata.clone 同一套路)。
"""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from ..core import config, db
from ..core.logging_setup import get_logger
from . import merge as merge_mod

log = get_logger(__name__)


def mtv_meta(drama_id: int) -> dict:
    """读 MTV 元数据(歌词/时长/歌曲);非 MTV 项目返回空 dict。"""
    d = db.q1("SELECT work_type, metadata FROM dramas WHERE id=?", (drama_id,))
    if not d or d["work_type"] != "mtv":
        return {}
    meta = db.jload(d["metadata"], {}) or {}
    m = meta.get("mtv") or {}
    return m if isinstance(m, dict) else {}


def save_song(drama_id: int, lyrics: str = "", duration: float | None = None,
              song_path: str | Path | None = None) -> dict:
    """保存/更新 MTV 元数据;song_path 存在时拷入 uploads 并探时长。

    时长优先级:真实探测的 MP3 时长 > 调用方给的值(用户手填只是没传歌时的
    估计,传了歌就以歌为准)。
    """
    meta = _meta_of(drama_id)
    mtv = meta.get("mtv") or {}
    if lyrics:
        mtv["lyrics"] = lyrics
    if song_path:
        src = Path(song_path)
        dst = config.STATIC_DIR / "uploads" / f"song_{uuid.uuid4().hex[:10]}{src.suffix or '.mp3'}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
        mtv["song_url"] = config.path_to_media_url(dst)
        probed = probe_audio_duration(dst)
        if probed > 0:
            mtv["song_duration"] = round(probed)
    if duration and not mtv.get("song_duration"):
        mtv["song_duration"] = int(duration)
    meta["mtv"] = mtv
    db.ex("UPDATE dramas SET metadata=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
    return mtv


def set_song_subtitle(drama_id: int, on: bool) -> None:
    """歌词字幕开关落库(合并铺歌时把歌词按行烧进画面)。"""
    meta = _meta_of(drama_id)
    mtv = meta.get("mtv") or {}
    mtv["subtitle"] = bool(on)
    meta["mtv"] = mtv
    db.ex("UPDATE dramas SET metadata=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))


def probe_audio_duration(path: str | Path) -> float:
    """ffprobe 探音频时长(秒);失败返回 0(调用方按「未探测到」处理)。"""
    ff = config.find_ffprobe()
    if not ff or not Path(path).exists():
        return 0.0
    try:
        r = subprocess.run([ff, "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=30)
        return float((r.stdout or "0").strip() or 0)
    except (ValueError, subprocess.SubprocessError):
        return 0.0


def _meta_of(drama_id: int) -> dict:
    d = db.q1("SELECT metadata FROM dramas WHERE id=?", (drama_id,))
    return db.jload(d["metadata"], {}) if d else {}


def _silent_concat_cmd(shots: list[Path], out: Path, w: int, h: int) -> list[str]:
    """多镜头 → 单条无声视频的 ffmpeg 参数(统一到多数派画幅 + 30fps)。

    与 merge._merge_filtered 的视频链同规格(scale+pad 居中补边 + setsar + fps),
    但**不建任何音频链**(concat v=1:a=0 + -an)—— MTV 的镜头原声一律丢弃。
    """
    ff = config.find_ffmpeg()
    parts: list[str] = [ff, "-y"]
    for s in shots:
        parts += ["-i", str(s)]
    chain = ";".join(
        f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]"
        for i in range(len(shots)))
    labels = "".join(f"[v{i}]" for i in range(len(shots)))
    filt = f"{chain};{labels}concat=n={len(shots)}:v=1:a=0[vout]"
    parts += ["-filter_complex", filt, "-map", "[vout]", "-an",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
              "-movflags", "+faststart", str(out)]
    return parts


def _mux_song_cmd(silent: Path, song: Path, out: Path) -> list[str]:
    """无声画面 + 歌曲 → 成品 MV(画面流 copy 不重压,音频转 aac,-shortest 对齐)。"""
    ff = config.find_ffmpeg()
    return [ff, "-y", "-i", str(silent), "-i", str(song),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(out)]


def _mux_song_cmd_subtitled(silent: Path, song: Path, ass: Path, out: Path) -> list[str]:
    """铺歌 + **烧歌词字幕**(画面要重压:字幕是滤镜,不能用 copy)。

    ass 与 silent 同目录,用相对文件名喂 subtitles 滤镜 —— Windows 绝对路径
    里的 `C:` 冒号在滤镜转义里是个坑,相对名彻底绕开。
    """
    ff = config.find_ffmpeg()
    return [ff, "-y", "-i", str(silent), "-i", str(song),
            "-map", "0:v", "-map", "1:a",
            "-vf", f"subtitles={ass.name}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", "-movflags", "+faststart", str(out)]


def _ass_time(sec: float) -> str:
    """ASS 时间戳:H:MM:SS.CS(厘秒)。"""
    sec = max(0.0, sec)
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_lyrics_ass(lyrics: str, duration: float, path: str | Path,
                     w: int = 1080, h: int = 1920) -> Path:
    """歌词 → ASS 字幕文件:每行**平分**歌曲时长,底部居中,白字黑边。

    没有逐行时间数据(卡拉OK级对轴需要人工打点),按行数等分是 MV 工具的
    常规做法 —— 歌词行数与歌曲段落天然接近等间隔。空行/纯标记行跳过。
    """
    lines = [ln.strip() for ln in (lyrics or "").splitlines()
             if ln.strip()]
    if not lines:
        raise RuntimeError("歌词为空,无法生成字幕")
    per = max(0.5, duration / len(lines))
    fontsize = max(28, int(h * 0.032))          # 1080x1920 → ~61
    margin_v = int(h * 0.06)
    style = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\n"
        "WrapStyle: 2\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: MtvSub,Microsoft YaHei,{fs},&H00FFFFFF,&H00FFFFFF,"
        "&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,{mv},1\n"
        "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n").format(w=w, h=h, fs=fontsize, mv=margin_v)
    t = 0.0
    events = []
    for ln in lines:
        events.append(f"Dialogue: 0,{_ass_time(t)},{_ass_time(t + per)},"
                      f"MtvSub,,0,0,0,,{ln}")
        t += per
    p = Path(path)
    p.write_text(style + "\n".join(events), encoding="utf-8")
    return p


def merge_mtv(episode_id: int, only_ids: list[int] | None = None,
              progress=None, stop_check=None) -> Path:
    """MTV 成片:全静音合并所选镜头,再铺上歌曲;返回成片路径。

    与 merge_episode 同款落 video_merges(任务面板/成片卡直接复用),
    区别只有两点:音频链整条不建(镜头原声/旁白都不要)、成片混入歌曲。
    没传歌曲 → 只出无声画面(提示在调用方,model 名带 silent 便于分辨)。
    """
    shots = merge_mod.episode_shot_files(episode_id, only_ids)
    if not shots:
        raise RuntimeError("没有可合并的镜头视频,请先生成镜头视频")
    ep = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))
    drama_id = ep["drama_id"] if ep else 0
    mtv = mtv_meta(drama_id)
    song = _resolve_song(mtv.get("song_url"))
    out_dir = config.STATIC_DIR / "merged"
    out_dir.mkdir(parents=True, exist_ok=True)
    silent = out_dir / f"mtv_{episode_id}_{uuid.uuid4().hex[:8]}_silent.mp4"
    out = out_dir / f"mtv_{episode_id}_{uuid.uuid4().hex[:8]}.mp4"

    ts = db.now()
    model = "mtv-song" if song else "mtv-silent"
    merge_id = db.ex(
        "INSERT INTO video_merges(episode_id,provider,model,scenes,status,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (episode_id, "ffmpeg", model,
         json.dumps([str(p) for p in shots], ensure_ascii=False),
         "processing", ts, ts))
    try:
        if progress:
            progress(0, 2, "拼接镜头(静音)")
        w, h = merge_mod._majority_size(shots)
        r = subprocess.run(_silent_concat_cmd(shots, silent, w, h),
                           capture_output=True, timeout=1800)
        if r.returncode != 0 or not silent.exists():
            raise RuntimeError(f"静音合并失败:{(r.stderr or b'')[-400:]!r}")
        if song:
            if progress:
                progress(1, 2, "铺歌")
            # 歌词字幕:开关存 metadata.mtv.subtitle;开着且有歌词 → 生成 ASS
            # 并在铺歌时烧进画面(画面重压;相对路径喂 subtitles 滤镜避 Windows 冒号坑)
            # 字幕对轴用的是**歌曲时长**(歌词跟歌走,不跟画面走);探不到就跳过
            song_dur = float(mtv.get("song_duration") or 0)
            use_sub = bool(mtv.get("subtitle")) and bool(mtv.get("lyrics")) \
                and song_dur > 0
            if use_sub:
                try:
                    ass = build_lyrics_ass(str(mtv.get("lyrics")), song_dur,
                                           silent.parent / "lyrics.ass", w=w, h=h)
                except RuntimeError as exc:
                    log.warning("mtv.ass.skip episode=%s err=%s", episode_id, exc)
                    ass = None
            else:
                ass = None
            cmd = (_mux_song_cmd_subtitled(silent, song, ass, out) if ass
                   else _mux_song_cmd(silent, song, out))
            r = subprocess.run(cmd, cwd=str(silent.parent),
                               capture_output=True, timeout=1800)
            if r.returncode != 0 or not out.exists():
                raise RuntimeError(f"铺歌失败:{(r.stderr or b'')[-400:]!r}")
            silent.unlink(missing_ok=True)      # 中间产物不留磁盘
        else:
            out = silent
        dur = merge_mod.probe(out).get("duration") or 0
        db.ex("UPDATE video_merges SET merged_url=?, status='completed', duration=?, updated_at=? WHERE id=?",
              (config.path_to_media_url(out), dur, db.now(), merge_id))
        db.ex("UPDATE episodes SET video_url=?, updated_at=? WHERE id=?",
              (config.path_to_media_url(out), db.now(), episode_id))
        if progress:
            progress(2, 2, str(out))
        log.info("mtv.merge.done episode=%s shots=%d song=%s dur=%.1fs",
                 episode_id, len(shots), bool(song), dur)
        return out
    except Exception as e:
        db.ex("UPDATE video_merges SET status='failed', error_msg=?, updated_at=? WHERE id=?",
              (str(e)[:500], db.now(), merge_id))
        raise


def _resolve_song(url) -> Path | None:
    """song_url(/static/ 媒体地址或本地路径)→ 本地路径;不存在返回 None。"""
    if not url:
        return None
    s = str(url).replace("\\", "/")
    p = config.media_url_to_path(s) if s.startswith(("/static/", "static/")) else Path(s)
    return p if p.exists() else None
