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


def save_lyrics_timed(drama_id: int, timed: list[dict]) -> dict:
    """保存逐行打轴结果 [{text, start, end}](秒,浮点)。

    打轴后 build_lyrics_ass 按 per-line 时间出字幕(不再平分),对口型镜头
    的音频切分与合成拼接也以这份时间轴为准。空文本行丢弃,浮点保留两位。
    """
    meta = _meta_of(drama_id)
    mtv = meta.get("mtv") or {}
    clean = []
    for x in (timed or []):
        text = str(x.get("text") or "").strip()
        if not text:
            continue
        try:
            start = round(max(0.0, float(x.get("start") or 0)), 2)
            end = round(max(0.0, float(x.get("end") or 0)), 2)
        except (TypeError, ValueError):
            continue
        if end <= start:
            end = start + 1.0
        clean.append({"text": text, "start": start, "end": end})
    mtv["lyrics_timed"] = clean
    meta["mtv"] = mtv
    db.ex("UPDATE dramas SET metadata=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
    return mtv


def timed_lines(mtv: dict) -> list[dict] | None:
    """打轴结果 → [{text, start, end}];未打轴/无有效行返回 None(调用方走平分)。"""
    timed = mtv.get("lyrics_timed")
    if isinstance(timed, list) and timed:
        return timed
    return None


def segment_song(song_path: str | Path, start: float, end: float,
                 out: str | Path) -> Path:
    """按打轴窗口切出该行歌词的音频段(对口型镜头的驱动音频)。

    -ss 放在 -i 前走快速定位;重编码为 aac 单声道,体积小且与视频合轨无碍。
    """
    ff = config.find_ffmpeg()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    dur = max(0.5, float(end) - float(start))
    subprocess.run([ff, "-y", "-ss", f"{float(start):.2f}", "-t", f"{dur:.2f}",
                    "-i", str(song_path), "-vn", "-ac", "1", "-c:a", "aac",
                    "-b:a", "128k", str(out)],
                   capture_output=True, timeout=120)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"音频切分失败({start:.1f}-{end:.1f}s)")
    return out


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
                     w: int = 1080, h: int = 1920,
                     timed: list[dict] | None = None) -> Path:
    """歌词 → ASS 字幕文件:底部居中,白字黑边。

    时间轴二选一:
    - **打轴优先**:timed = [{text, start, end}](歌词打轴器产出)→ 每行按
      打轴的起止出现,歌词与歌声逐行同步(用户痛点:平分模式歌词与唱到哪
      完全对不上);
    - 未打轴:每行**平分**歌曲时长(常规做法,空行/纯标记行跳过)。
    """
    lines = [ln.strip() for ln in (lyrics or "").splitlines()
             if ln.strip()]
    if not lines and not timed:
        raise RuntimeError("歌词为空,无法生成字幕")
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
    events = []
    if timed:
        for x in timed:
            st = max(0.0, float(x.get("start") or 0))
            en = max(st + 0.8, float(x.get("end") or 0))
            events.append(f"Dialogue: 0,{_ass_time(st)},{_ass_time(en)},"
                          f"MtvSub,,0,0,0,,{str(x.get('text') or '').strip()}")
    else:
        per = max(0.5, duration / max(1, len(lines)))
        t = 0.0
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
                                           silent.parent / "lyrics.ass", w=w, h=h,
                                           timed=timed_lines(mtv))
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


# ── 对口型(2026-11-04):打轴窗口 → 逐行音频段 → 音频驱动视频 → 拼接 ──────

def _singing_anchor_image(episode_id: int) -> str | None:
    """对口型镜头的主角形象图:首选该集第一个已出首帧的分镜图(场景/形象都已
    定),回落剧集主角资产的立绘。都没有返回 None(调用方报错指路)。"""
    for col in ("first_frame", "image_url"):
        r = db.q1(f"SELECT {col} AS u FROM storyboards WHERE episode_id=? "
                  "AND deleted_at IS NULL AND COALESCE(" + col + ",'')!='' "
                  "ORDER BY storyboard_number LIMIT 1", (episode_id,))
        if r and r["u"]:
            s = str(r["u"]).replace("\\", "/")
            p = config.media_url_to_path(s) if s.startswith(("/static/", "static/")) else Path(s)
            if Path(p).exists():
                return str(p)
    d = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))
    ch = db.q1("SELECT COALESCE(NULLIF(comic_image_url,''),NULLIF(image_url,'')) AS u "
               "FROM characters WHERE drama_id=? ORDER BY id LIMIT 1",
               (d["drama_id"] if d else 0,))
    if ch and ch["u"]:
        s = str(ch["u"]).replace("\\", "/")
        p = config.media_url_to_path(s) if s.startswith(("/static/", "static/")) else Path(s)
        if Path(p).exists():
            return str(p)
    return None


def singing_clips(drama_id: int) -> list[dict]:
    """已生成的对口型镜头(按歌词行序);每项 {idx, start, end, text, video_url}。"""
    m = mtv_meta(drama_id)
    clips = m.get("singing") or []
    return sorted((c for c in clips if isinstance(c, dict) and c.get("video_url")),
                  key=lambda x: float(x.get("start") or 0))


def generate_singing_shots(episode_id: int, config_id: int | None = None,
                           progress=None, stop_check=None) -> dict:
    """逐行生成对口型镜头(批量,串行;已生成的行自动跳过 = 断点续作)。

    每行:打轴窗口切音频段 → agnes 参考模式(主角形象图 + 音频段)音视频
    同步生成,人物口型贴该行歌词。结果写 metadata.mtv.singing,供
    merge_singing 拼接成对口型 MV。
    """
    ep = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))
    drama_id = ep["drama_id"] if ep else 0
    mtv = mtv_meta(drama_id)
    timed = timed_lines(mtv)
    if not timed:
        raise RuntimeError("请先完成歌词打轴(歌曲条 → 歌词打轴)")
    song = _resolve_song(mtv.get("song_url"))
    if not song:
        raise RuntimeError("请先上传歌曲 MP3(歌曲条 → 换歌)")
    anchor = _singing_anchor_image(episode_id)
    if not anchor:
        raise RuntimeError("没有主角形象图:先生成任意一镜首帧,或出镜人物资产图")
    _srow = db.q1("SELECT style FROM dramas WHERE id=?", (drama_id,))
    style = db.style_prompt((_srow["style"] if _srow else "") or "")
    out_dir = config.STATIC_DIR / "mtv_singing"
    out_dir.mkdir(parents=True, exist_ok=True)

    prev = {int(x.get("idx")): x for x in (mtv.get("singing") or [])
            if x.get("video_url")}
    from ..ai import video_client
    total = len(timed)
    done_n = 0
    singing = list(mtv.get("singing") or [])
    for idx, x in enumerate(timed):
        if stop_check and stop_check():
            break
        if idx in prev:
            done_n += 1
            if progress:
                progress(idx + 1, total, f"第{idx + 1}/{total} 行(已有,跳过)")
            continue
        start, end = float(x["start"]), float(x["end"])
        if progress:
            progress(idx, total, f"第{idx + 1}/{total} 行:{str(x['text'])[:18]}")
        seg = segment_song(song, start, end,
                           out_dir / f"ep{episode_id}_line{idx}.m4a")
        prompt = ((f"{style}。" if style else "")
                  + f"主角面对镜头演唱这句歌词,口型与歌词逐字精确同步:「{x['text']}」。"
                  "半身近景居中,手持麦克风或清唱姿态,情绪贴合歌词,背景轻微虚化,"
                  "镜头缓慢推近,人物始终在画面中心")
        dur = max(4, min(12, int(round(end - start)) or 4))
        out, _prov = video_client.generate_video(
            prompt, resolution="720p", duration=dur, config_id=config_id,
            reference_images=[anchor], audios=[str(seg)])
        url = config.path_to_media_url(out)
        entry = next((e for e in singing if int(e.get("idx")) == idx), None)
        payload = {"idx": idx, "start": start, "end": end,
                   "text": str(x.get("text") or ""), "video_url": url}
        if entry:
            entry.update(payload)
        else:
            singing.append(payload)
        singing.sort(key=lambda e: int(e.get("idx")))
        meta = _meta_of(drama_id)
        mtv_data = meta.setdefault("mtv", {})
        mtv_data["singing"] = singing
        meta["mtv"] = mtv_data
        db.ex("UPDATE dramas SET metadata=?, updated_at=? WHERE id=?",
              (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
        done_n += 1
        if progress:
            progress(idx + 1, total, f"第{idx + 1}/{total} 行完成")
    return {"done": done_n, "total": total}


def merge_singing(episode_id: int, progress=None, stop_check=None) -> Path:
    """对口型 MV 成片:按歌词行序拼接对口型镜头,铺原歌。

    与 merge_mtv(画面叙事版)并列的第二种成片:每一镜都是主角在唱那行
    歌词的镜头,歌与口型天然同步。镜头时长按打轴窗口裁齐(ffmpeg -t)。
    """
    ep = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))
    drama_id = ep["drama_id"] if ep else 0
    mtv = mtv_meta(drama_id)

    def _local(url):
        if not url:
            return None
        s = str(url).replace("\\", "/")
        p = config.media_url_to_path(s) if s.startswith(("/static/", "static/")) else Path(s)
        return p if Path(p).exists() else None

    clips = [c for c in singing_clips(drama_id) if _local(c.get("video_url"))]
    if not clips:
        raise RuntimeError("还没有对口型镜头:先点「对口型镜头」逐行生成")
    song = _resolve_song(mtv.get("song_url"))
    out_dir = config.STATIC_DIR / "merged"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    silent = out_dir / f"mtvsing_{episode_id}_{tag}_silent.mp4"
    out = out_dir / f"mtvsing_{episode_id}_{tag}.mp4"
    ts = db.now()
    paths = [_local(c["video_url"]) for c in clips]
    merge_id = db.ex(
        "INSERT INTO video_merges(episode_id,provider,model,scenes,status,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (episode_id, "ffmpeg", "mtv-lipsync",
         json.dumps([str(p) for p in paths], ensure_ascii=False),
         "processing", ts, ts))
    try:
        if progress:
            progress(0, 2, f"拼接对口型镜头({len(paths)} 行)")
        w, h = merge_mod._majority_size(paths)
        r = subprocess.run(_silent_concat_cmd(paths, silent, w, h),
                           capture_output=True, timeout=1800)
        if r.returncode != 0 or not silent.exists():
            raise RuntimeError(f"对口型镜头拼接失败:{(r.stderr or b'')[-400:]!r}")
        if song:
            if progress:
                progress(1, 2, "铺歌")
            r = subprocess.run(_mux_song_cmd(silent, song, out),
                               capture_output=True, timeout=1800)
            if r.returncode != 0 or not out.exists():
                raise RuntimeError(f"铺歌失败:{(r.stderr or b'')[-400:]!r}")
            silent.unlink(missing_ok=True)
        else:
            out = silent
        dur = merge_mod.probe(out).get("duration") or 0
        db.ex("UPDATE video_merges SET merged_url=?, status='completed', duration=?, updated_at=? WHERE id=?",
              (config.path_to_media_url(out), dur, db.now(), merge_id))
        db.ex("UPDATE episodes SET video_url=?, updated_at=? WHERE id=?",
              (config.path_to_media_url(out), db.now(), episode_id))
        if progress:
            progress(2, 2, str(out))
        log.info("mtv.lipsync.done episode=%s lines=%d song=%s dur=%.1fs",
                 episode_id, len(paths), bool(song), dur)
        return out
    except Exception as e:
        db.ex("UPDATE video_merges SET status='failed', error_msg=?, updated_at=? WHERE id=?",
              (str(e)[:500], db.now(), merge_id))
        raise
