# -*- coding: utf-8 -*-
"""视频合并模块 —— 并入 golanse/easymerger 核心逻辑:

  能用无损合并就绝不用转码。

通道策略:
  A) 全部参数一致          → concat demuxer + `-c copy`(秒合,零损失)
  B) 视频参数一致、音频不一致 → 智能直通:视频流 copy,仅统一音频(aac 48k 立体声)
  C) 少数视频异类           → 一键对齐异类:只转码那几个到多数派参数,再走 A

参数检测(ffprobe):分辨率/编码/Profile/等级/帧率/像素格式/音频编码/音频Profile/采样率/声道。
容错回退:直通失败 → 换中间容器(.ts/.mov) → 重编码救回。
同时提供剧集拼接入口(镜头视频 + 旁白 MP3 amix 混音,对齐原版 ffmpeg-merge)。
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..core import config, db
from . import intro as _intro

VIDEO_KEYS = ["width", "height", "vcodec", "vprofile", "fps", "pix_fmt"]
AUDIO_KEYS = ["acodec", "aprofile", "sample_rate", "channels"]
ALL_KEYS = VIDEO_KEYS + AUDIO_KEYS


def _ffmpeg() -> str:
    ff = config.find_ffmpeg()
    if not ff:
        raise RuntimeError("未找到 ffmpeg,请安装或设置 FFMPEG_BIN 环境变量。")
    return ff


def _ffprobe() -> str:
    fp = config.find_ffprobe()
    if not fp:
        raise RuntimeError("未找到 ffprobe,请安装或设置 FFPROBE_BIN 环境变量。")
    return fp


def probe(path: str | Path) -> dict:
    """ffprobe 提取统一参数指纹。失败抛 RuntimeError。"""
    out = subprocess.run(
        [_ffprobe(), "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {out.stderr[:200]}")
    data = json.loads(out.stdout or "{}")
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    fps = "0"
    if v.get("avg_frame_rate") and v["avg_frame_rate"] != "0/0":
        num, _, den = v["avg_frame_rate"].partition("/")
        try:
            rate = int(num) / int(den or 1)
            fps = str(int(round(rate))) if abs(rate - round(rate)) < 0.05 else f"{rate:.3f}"
        except Exception:  # noqa: BLE001
            fps = v.get("r_frame_rate", "0")
    return {
        "path": str(path), "name": Path(path).name,
        "width": v.get("width"), "height": v.get("height"),
        "vcodec": v.get("codec_name"), "vprofile": v.get("profile"),
        "fps": fps, "pix_fmt": v.get("pix_fmt"),
        "acodec": a.get("codec_name"), "aprofile": a.get("profile"),
        "sample_rate": str(a.get("sample_rate") or ""), "channels": a.get("channels"),
        "duration": float(data.get("format", {}).get("duration") or 0) or None,
        "has_audio": bool(a),
    }


@dataclass
class AnalyzeResult:
    files: list[dict] = field(default_factory=list)
    majority: dict = field(default_factory=dict)   # 多数派参数
    diffs: list[str] = field(default_factory=list)  # 不一致的参数名
    outliers: list[str] = field(default_factory=list)  # 异类文件路径
    video_consistent: bool = True
    audio_consistent: bool = True

    @property
    def can_lossless(self) -> bool:
        return not self.diffs

    @property
    def can_smart_passthrough(self) -> bool:
        return self.video_consistent and not self.audio_consistent

    @property
    def need_align(self) -> bool:
        return not self.video_consistent

    def summary(self) -> str:
        if self.can_lossless:
            return "全部参数一致,可无损合并(-c copy)"
        if self.can_smart_passthrough:
            return f"视频参数一致,音频差异({','.join(k for k in self.diffs if k in AUDIO_KEYS)}) → 智能直通"
        return f"视频参数差异({','.join(k for k in self.diffs if k in VIDEO_KEYS)}),异类 {len(self.outliers)} 个 → 先一键对齐"


def _mode(values: list) -> object:
    return max(set(values), key=values.count) if values else None


def analyze(paths: list[str | Path]) -> AnalyzeResult:
    files = [probe(p) for p in paths]
    if len(files) < 2:
        raise RuntimeError("至少需要 2 个视频文件")
    res = AnalyzeResult(files=files)
    for key in ALL_KEYS:
        vals = [f[key] for f in files]
        maj = _mode(vals)
        res.majority[key] = maj
        if any(v != maj for v in vals):
            res.diffs.append(key)
    res.video_consistent = not any(k in res.diffs for k in VIDEO_KEYS)
    res.audio_consistent = not any(k in res.diffs for k in AUDIO_KEYS)
    res.outliers = [f["path"] for f in files
                    if any(f[k] != res.majority[k] for k in VIDEO_KEYS)]
    return res


def _run(cmd: list[str], timeout: int = 3600) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {proc.stderr[-400:]}")
    return proc


def lossless_merge(files: list[str], out: str | Path, stop_check=None) -> Path:
    """通道 A:concat demuxer + -c copy。失败自动走 _rescue。"""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in files:
            f.write(f"file '{Path(p).as_posix()}'\n")
        listfile = f.name
    try:
        try:
            _run([_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", listfile,
                  "-c", "copy", str(out)])
            return out
        except Exception:  # noqa: BLE001
            return _rescue(files, out)
    finally:
        os.unlink(listfile)


def _rescue(files: list[str], out: Path) -> Path:
    """容错回退:换中间容器(.ts)再 copy;仍失败则整批重编码。"""
    tmp = Path(tempfile.mkdtemp(prefix="merger_"))
    try:
        ts_files = []
        for i, p in enumerate(files):
            seg = tmp / f"{i:04d}.ts"
            _run([_ffmpeg(), "-y", "-i", p, "-c", "copy", "-bsf:v", "h264_mp4toannexb",
                  "-f", "mpegts", str(seg)])
            ts_files.append(str(seg))
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            for p in ts_files:
                f.write(f"file '{p}'\n")
            lst = f.name
        try:
            _run([_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", lst,
                  "-c", "copy", "-bsf:a", "aac_adtstoasc", str(out)])
            return out
        finally:
            os.unlink(lst)
    except Exception:  # noqa: BLE001
        return _reencode_merge(files, out)
    finally:
        for p in tmp.glob("*"):
            p.unlink(missing_ok=True)
        tmp.rmdir()


def smart_passthrough_merge(files: list[str], out: str | Path, stop_check=None) -> Path:
    """通道 B:视频流 copy,仅统一音频(48k 立体声 AAC)。"""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="passthrough_"))
    try:
        segs = []
        for i, p in enumerate(files):
            seg = tmp / f"{i:04d}.mp4"
            _run([_ffmpeg(), "-y", "-i", p,
                  "-map", "0:v:0", "-map", "0:a?",
                  "-c:v", "copy",
                  "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                  "-af", "apad", "-shortest",
                  str(seg)])
            segs.append(str(seg))
        return lossless_merge(segs, out)
    finally:
        for p in tmp.glob("*"):
            p.unlink(missing_ok=True)
        tmp.rmdir()


def _reencode_merge(files: list[str], out: Path, w: int = 1280, h: int = 720) -> Path:
    """通道 D(兜底):全部统一转码后 concat。"""
    tmp = Path(tempfile.mkdtemp(prefix="reencode_"))
    try:
        segs = []
        for i, p in enumerate(files):
            seg = tmp / f"{i:04d}.mp4"
            _run([_ffmpeg(), "-y", "-i", p,
                  "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                  "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                  str(seg)])
            segs.append(str(seg))
        return lossless_merge(segs, out)
    finally:
        for p in tmp.glob("*"):
            p.unlink(missing_ok=True)
        tmp.rmdir()


def align_one(src: str, target: dict, out_dir: Path | None = None) -> Path:
    """一键对齐单个异类文件到多数派参数(仅视频转码,音频统一 aac)。返回新文件。"""
    out_dir = out_dir or (config.STATIC_DIR / "aligned")
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"aligned_{Path(src).stem}_{uuid.uuid4().hex[:6]}.mp4"
    vf = (f"scale={target['width']}:{target['height']}:force_original_aspect_ratio=decrease,"
          f"pad={target['width']}:{target['height']}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={target['fps']}")
    _run([_ffmpeg(), "-y", "-i", src, "-vf", vf,
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
          "-pix_fmt", str(target.get("pix_fmt") or "yuv420p"),
          "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", str(dst)])
    # 对齐后校验
    check = probe(dst)
    for k in VIDEO_KEYS:
        if str(check[k]) != str(target[k]):
            raise RuntimeError(f"对齐校验失败:{k} {check[k]} != {target[k]}")
    return dst


def align_outliers(result: AnalyzeResult, progress=None, stop_check=None) -> list[str]:
    """把所有异类对齐到多数派;返回新的文件序列(原顺序)。"""
    aligned: dict[str, str] = {}
    outliers = set(result.outliers)
    done = 0
    for f in result.files:
        if stop_check and stop_check():
            raise RuntimeError("用户停止")
        if f["path"] in outliers:
            aligned[f["path"]] = str(align_one(f["path"], result.majority))
            done += 1
            if progress:
                progress(done, len(outliers), f["name"])
    return [aligned.get(f["path"], f["path"]) for f in result.files]


def auto_merge(files: list[str], out: str | Path, progress=None, stop_check=None) -> tuple[Path, str]:
    """全自动:检测 → 选通道 → 合并。返回 (输出路径, 通道说明)。"""
    result = analyze(files)
    if progress:
        progress(0, 1, result.summary())
    if result.can_lossless:
        return lossless_merge(files, out, stop_check), "无损合并(-c copy)"
    if result.can_smart_passthrough:
        return smart_passthrough_merge(files, out, stop_check), "智能直通(视频 copy,音频统一)"
    files2 = align_outliers(result, progress, stop_check)
    return lossless_merge(files2, out, stop_check), f"已对齐 {len(result.outliers)} 个异类后无损合并"


# ── 剧集拼接入口(镜头视频 + 旁白混音,对齐原版 ffmpeg-merge) ──

def episode_shot_files(episode_id: int, only_ids: list[int] | None = None) -> list[Path]:
    rows = db.q("SELECT * FROM storyboards WHERE episode_id=? ORDER BY storyboard_number", (episode_id,))
    files = []
    for r in rows:
        if only_ids and r["id"] not in only_ids:
            continue
        url = r["video_url"] or r["composed_video_url"]
        if not url:
            continue
        p = config.media_url_to_path(url)
        if p.exists():
            files.append(p)
    if not files:
        raise RuntimeError("没有已生成的镜头视频(先在「分镜」批量生成视频)")
    return files


def merge_episode(episode_id: int, only_ids: list[int] | None = None,
                  progress=None, stop_check=None,
                  intro_title: str | None = None, intro_card: bool | None = None,
                  intro_overlay: bool | None = None) -> Path:
    """拼接所选镜头;有旁白 MP3 时 amix 混音;分辨率统一到多数派;可选叠加片头。

    片头(对齐原版 3990bb8):黑底标题卡前置 + 文字叠加,两者可同时开。
    """
    shots = episode_shot_files(episode_id, only_ids)
    out = config.STATIC_DIR / "merged" / f"{episode_id}_{uuid.uuid4().hex[:8]}.mp4"
    ts = db.now()
    ep_row = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,))
    narrations = _episode_narrations(episode_id, only_ids, shots)
    # 片头字号/时长按真实画幅算:先探多数派分辨率再构造 spec(写死 1280x720 会让竖屏漫剧
    # 的字号错一档、黑底卡变横条)
    intro = None
    if ep_row:
        try:
            ref_w, ref_h = _majority_size(shots)
            intro = _intro.build_intro_spec(ep_row["drama_id"], title_override=intro_title,
                                            card=intro_card, overlay=intro_overlay,
                                            ref_w=ref_w, ref_h=ref_h)
        except Exception:  # noqa: BLE001
            intro = None      # 片头配置异常不阻断拼接
    model_name = "lossless-auto" + ("-intro" if intro else "")
    merge_id = db.ex(
        "INSERT INTO video_merges(episode_id,provider,model,scenes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        (episode_id, "ffmpeg", model_name, json.dumps([str(p) for p in shots], ensure_ascii=False),
         "processing", ts, ts))
    try:
        has_narr = any(narrations)
        if intro or has_narr:
            merged = _merge_filtered(shots, narrations, out, intro, stop_check)
            channel = ("统一参数拼接" if not has_narr else "统一参数拼接 + 旁白混音") \
                      + (" + 片头" if intro else "")
        else:
            path, channel = auto_merge([str(p) for p in shots], out, progress, stop_check)
            merged = path
        dur = probe(merged).get("duration") or 0
        db.ex("UPDATE video_merges SET merged_url=?, status='completed', duration=?, updated_at=? WHERE id=?",
              (config.path_to_media_url(merged), dur, db.now(), merge_id))
        db.ex("UPDATE episodes SET video_url=?, updated_at=? WHERE id=?",
              (config.path_to_media_url(merged), db.now(), episode_id))
        if progress:
            progress(1, 1, str(merged))
        return merged
    except Exception as e:  # noqa: BLE001
        db.ex("UPDATE video_merges SET status='failed', error_msg=?, updated_at=? WHERE id=?",
              (str(e)[:500], db.now(), merge_id))
        raise


def _episode_narrations(episode_id: int, only_ids: list[int] | None,
                        shots: list[Path]) -> list[Path | None]:
    """逐镜头对齐的旁白文件(按镜号顺序,与 shots 一一对应;缺失/文件丢失去 None)。"""
    rows = db.q("SELECT id, video_url, composed_video_url, narration_audio_url "
                "FROM storyboards WHERE episode_id=? ORDER BY storyboard_number", (episode_id,))
    keep = set(only_ids) if only_ids else {r["id"] for r in rows}
    shot_set = {str(p) for p in shots}
    out: list[Path | None] = []
    for r in rows:
        if r["id"] not in keep:
            continue
        url = r["video_url"] or r["composed_video_url"]
        if not url or str(config.media_url_to_path(url)) not in shot_set:
            continue
        n = r["narration_audio_url"]
        if n:
            np_ = config.media_url_to_path(n)
            out.append(np_ if np_.exists() else None)
        else:
            out.append(None)
    return out


def _majority_size(shots: list[Path]) -> tuple[int, int]:
    """多数派分辨率(对齐原版):个别异常片段(如横竖混杂)不绑架全集画幅。"""
    count: dict[tuple[int, int], int] = {}
    for p in shots:
        try:
            info = probe(p)
        except Exception:  # noqa: BLE001 —— 单个探测失败不拦拼接
            continue
        key = (info["width"] or 1280, info["height"] or 720)
        count[key] = count.get(key, 0) + 1
    best, n = (1280, 720), 0
    for key, c in count.items():
        if c > n:
            best, n = key, c
    return best


def _merge_filtered(shots: list[Path], narrations: list[Path | None] | None,
                    out: Path, intro: dict | None = None, stop_check=None) -> Path:
    """统一 filter_complex 拼接(对齐原版 doMergeInner 的单路径):

      视频:逐镜头 scale+pad 居中补边 + setsar + fps 归一到多数派画幅,片头黑底卡在前 concat
      音频:每镜头建「原声基准」(aformat 48k 立体声 + atrim + apad;无音轨的用 anullsrc 静音),
            有旁白再 amix(normalize=0 防音量减半),片头静音轨在前 concat
      叠加:片头文字在 concat 后的视频上 alpha 淡入淡出(只在尾部做一次)

    取代旧 _merge_with_narration/_merge_with_intro:旧版旁白输入加了却没在滤镜里引用、
    镜头输入下标被旁白挤错位、无叠加时 [aout] 未定义却要 map、画幅写死 1280x720。
    """
    narr = list(narrations or [])[:len(shots)]
    narr += [None] * (len(shots) - len(narr))
    infos = [probe(p) for p in shots]
    ref_w, ref_h = _majority_size(shots)

    # 输入顺序:镜头在前(按镜号),旁白文件在后(仅存在的)
    inputs: list[str] = []
    for s in shots:
        inputs += ["-i", str(s)]
    narr_input_of: dict[int, int] = {}
    j = len(shots)
    for i, n in enumerate(narr):
        if n and Path(n).exists():
            inputs += ["-i", str(n)]
            narr_input_of[i] = j
            j += 1

    iv, ia, i_overlay, temps = (_intro.build_intro_filters(intro) if intro else ([], [], None, []))

    chain: list[str] = []
    vlabels, alabels = [], []
    for i in range(len(shots)):
        chain.append(f"[{i}:v]scale={ref_w}:{ref_h}:force_original_aspect_ratio=decrease,"
                     f"pad={ref_w}:{ref_h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]")
        vlabels.append(f"[v{i}]")
        dur = infos[i].get("duration") or 5.0
        d = f"{dur:.3f}"
        if infos[i].get("has_audio"):
            chain.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                         f"atrim=0:{d},apad=whole_dur={d}[ab{i}]")
        else:
            chain.append(f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=0:{d}[ab{i}]")
        if i in narr_input_of:
            k = narr_input_of[i]
            # 旁白 MP3 常为 24kHz 单声道,同样先归一;duration=first 以原声长度为准
            chain.append(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                         f"atrim=0:{d},apad=whole_dur={d}[na{i}]")
            chain.append(f"[ab{i}][na{i}]amix=inputs=2:duration=first:dropout_transition=0:"
                         f"normalize=0[n{i}]")
            alabels.append(f"[n{i}]")
        else:
            alabels.append(f"[ab{i}]")

    # 片头片段插到最前(黑底卡 + 静音轨),再统一 concat
    n_seg = len(shots) + (1 if iv else 0)
    if iv:
        chain.insert(0, "".join(iv))
        chain.append("".join(ia))
    v_join = "".join((["[vIntro]"] if iv else []) + vlabels)
    a_join = "".join((["[aIntro]"] if iv else []) + alabels)
    chain.append(f"{v_join}concat=n={n_seg}:v=1:a=0[vcat]")
    chain.append(f"{a_join}concat=n={n_seg}:v=0:a=1[aout]")
    if i_overlay:                     # ★ 叠加只在尾部实现一次(原版 56cd571 的双重叠加坑)
        chain.append(f"[vcat]{i_overlay}[vout]")
    else:
        chain.append("[vcat]null[vout]")

    fc = ";".join(x.strip().rstrip(";") for x in chain if x.strip())
    try:
        _run([_ffmpeg(), "-y", *inputs, "-filter_complex", fc,
              "-map", "[vout]", "-map", "[aout]",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
              "-c:a", "aac", "-b:a", "192k", str(out)])
    finally:
        for f in temps:
            f.unlink(missing_ok=True)
    return out
