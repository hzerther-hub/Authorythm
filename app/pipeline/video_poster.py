# -*- coding: utf-8 -*-
"""视频海报帧:抽首帧当缩略图(对齐参考项目 backend/src/utils/video-poster.ts)。

列表行原来直接把 **视频文件** 丢给 pixmap_from_media,而 Qt 无法把 mp4 渲染成
位图 —— 所以每一行永远落到「🎬」占位符,出片了也看不出成片长什么样。

参考项目的口径:
- 路径推导:x.mp4 → x_poster.jpg(与视频同目录);
- 取 **0.5s** 那一帧而不是真正的第 0 帧(首帧常是纯黑);
- 缩放到宽 640、等比;
- 失败返回 None,**不阻断主流程**。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..core import config

# 取 0.5s:视频首帧常常是纯黑,直接 -ss 0 会得到一张黑图
DEFAULT_AT_SECONDS = 0.5
POSTER_WIDTH = 640


def poster_path_for(video_path: str | Path) -> Path:
    """x.mp4 → x_poster.jpg(与参考项目 posterPathFor 同规则)。"""
    p = Path(video_path)
    return p.with_name(p.stem + "_poster.jpg")


def extract_video_poster(video_path: str | Path,
                         at_seconds: float = DEFAULT_AT_SECONDS) -> Path | None:
    """抽指定时间点画面存成海报帧;已存在则直接复用。失败返回 None。

    会**探测**:默认 0.5s 若是黑帧就往后试(见 _FALLBACK_SECONDS)。带片头
    黑底标题卡的成片,开头往往有 3~4 秒纯黑 —— 固定抽 0.5s 只会得到一张纯黑
    缩略图,等于没抽。
    """
    src = Path(video_path)
    if not src.exists():
        return None
    out = poster_path_for(src)
    # 已存在且不比视频旧 → 命中缓存(批量刷新列表时能省掉绝大多数 ffmpeg 调用)
    try:
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return out
    except OSError:
        pass
    exe = config.find_ffmpeg()
    if not exe:
        return None

    def _grab(sec: float) -> bool:
        try:
            proc = subprocess.run(
                [exe, "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", f"{max(0.0, sec):.3f}", "-i", str(src),
                 "-frames:v", "1", "-vf", f"scale={POSTER_WIDTH}:-1",
                 "-q:v", "3", str(out)],
                capture_output=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            return False
        if proc.returncode != 0 or not out.exists():
            out.unlink(missing_ok=True)      # 别留下半截文件
            return False
        return not _is_black_frame(out)

    for sec in (at_seconds, *_FALLBACK_SECONDS):
        if _grab(sec):
            return out
    out.unlink(missing_ok=True)
    return None


# 0.5s 抽到黑帧时依次尝试的时间点(带片头黑场的成片开头常有 3~4 秒纯黑)
_FALLBACK_SECONDS = (2.0, 4.0, 6.0, 10.0)
_BLACK_MEAN = 12.0        # 灰度均值低于此视为黑帧


def _is_black_frame(path: Path) -> bool:
    """判断抽到的帧是不是近乎全黑。"""
    try:
        from PIL import Image, ImageStat
        with Image.open(path) as im:
            mean = ImageStat.Stat(im.convert("L")).mean[0]
        return mean < _BLACK_MEAN
    except Exception:  # noqa: BLE001
        return False


def poster_url(video_url: str | None) -> str | None:
    """已生成好的海报帧的 /static 地址;没有则 None(不触发抽帧)。"""
    if not video_url:
        return None
    if str(video_url).startswith(("/", "static/")):
        p = config.media_url_to_path(video_url)
    else:
        p = Path(video_url)
    if not p.exists():
        return None
    poster = poster_path_for(p)
    if not poster.exists():
        return None
    return config.path_to_media_url(poster)
