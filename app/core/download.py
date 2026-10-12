# -*- coding: utf-8 -*-
"""资产下载:把生成的图片/视频/成片复制到用户下载目录,文件名用资产名。

对齐原版(72736af)文件名规则:
  图片  = <资产名>[_变体].png
  分镜视频 = 第NN镜[_标题][_历史时间].mp4
  成片  = <项目名>_第N集.mp4
原版走 Content-Disposition 响应头(浏览器约束),桌面端直接落盘更自然。
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from ..core import config, db

MAX_BYTES = 400 * 1024 * 1024  # 与原版一致:超过 400MB 不走下载


def sanitize_filename(name: str, fallback: str = "asset") -> str:
    """去掉路径分隔符与非法字符,截断 80 字(对齐原版 sanitizeFilename)。"""
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(name or "")).strip()[:80]
    return cleaned or fallback


def _ext_from(url_or_path: str, fallback: str = ".jpg") -> str:
    m = re.search(r"\.([a-zA-Z0-9]{2,5})(?:\?|$|#)", str(url_or_path or ""))
    return f".{m.group(1).lower()}" if m else fallback


def default_download_dir() -> Path:
    from pathlib import Path as _P
    return _P.home() / "Downloads"


def download_media(url: str | None, filename: str, dest_dir: Path | None = None) -> Path:
    """把 /static/... 对应的本地文件复制到下载目录;返回落地路径。"""
    src = _validated_src(url)
    dest_dir = dest_dir or default_download_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / sanitize_filename(filename)
    i = 1
    while dst.exists():
        dst = dest_dir / sanitize_filename(f"{Path(filename).stem}_{i}{Path(filename).suffix}")
        i += 1
    shutil.copy2(src, dst)
    return dst


def download_media_ask(parent, url: str | None, filename: str) -> Path | None:
    """弹「另存为」对话框选择位置后复制(对齐图片下载的体验);取消返回 None。

    默认目录仍指向 Downloads,文件名可改;覆盖已有文件由对话框自身确认。
    """
    from PySide6.QtWidgets import QFileDialog
    src = _validated_src(url)
    default = default_download_dir() / sanitize_filename(filename)
    ext = default.suffix or ".mp4"
    caption = "Save"
    try:
        from ..core.i18n import tr
        caption = tr("download")
    except Exception:  # noqa: BLE001
        pass
    path, _ = QFileDialog.getSaveFileName(parent, caption, str(default), f"*{ext};;All (*)")
    if not path:
        return None
    dst = Path(path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def _validated_src(url: str | None) -> Path:
    """下载源校验:地址为空/文件缺失/空文件给可读错误。"""
    if not url:
        raise RuntimeError("该素材还没有生成文件,无法下载")
    src = config.media_url_to_path(url)
    if not src.exists():
        raise RuntimeError("文件不存在,可能已被清理")
    size = src.stat().st_size
    if size == 0:
        raise RuntimeError("下载失败:文件内容为空,请重新生成后再试")
    if size > MAX_BYTES:
        raise RuntimeError(f"文件超过 400MB({size/1048576:.0f}MB),请直接访问数据目录 {config.STATIC_DIR}")
    return src


def download_asset_image(row: dict, kind: str, variant_label: str = "") -> Path:
    """资产图下载(角色/场景/道具)。"""
    url = row.get("image_url") or row.get("comic_image_url")
    name = row.get("name") or row.get("location") or "asset"
    ext = _ext_from(url)
    fn = f"{name}{('_' + variant_label) if variant_label else ''}{ext}"
    return download_media(url, fn)


def download_storyboard_video(sb: dict, suffix: str = "") -> Path:
    """分镜视频下载。"""
    n = int(sb.get("storyboard_number") or 0)
    title = (sb.get("title") or "").strip()
    fn = f"第{n:02d}镜{('_' + title) if title else ''}{suffix}.mp4"
    return download_media(sb.get("video_url") or sb.get("composed_video_url"), fn)


def download_storyboard_video_ask(parent, sb: dict, suffix: str = "") -> Path | None:
    """分镜视频下载(弹「另存为」选位置;取消返回 None)。"""
    n = int(sb.get("storyboard_number") or 0)
    title = (sb.get("title") or "").strip()
    fn = f"第{n:02d}镜{('_' + title) if title else ''}{suffix}.mp4"
    return download_media_ask(parent, sb.get("video_url") or sb.get("composed_video_url"), fn)


def download_merge_ask(parent, merge: dict) -> Path | None:
    """成片下载(弹「另存为」选位置;取消返回 None):<项目名>_第N集.mp4。"""
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (merge["episode_id"],))
    d = db.q1("SELECT title FROM dramas WHERE id=?", (ep["drama_id"],)) if ep else None
    title = sanitize_filename((d["title"] if d else "短剧"), "短剧")
    fn = f"{title}_第{ep['episode_number'] if ep else 1}集.mp4"
    return download_media_ask(parent, merge.get("merged_url"), fn)


def download_merge(merge: dict) -> Path:
    """成片下载:<项目名>_第N集.mp4。"""
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (merge["episode_id"],))
    d = db.q1("SELECT title FROM dramas WHERE id=?", (ep["drama_id"],)) if ep else None
    title = sanitize_filename((d["title"] if d else "短剧"), "短剧")
    fn = f"{title}_第{ep['episode_number'] if ep else 1}集.mp4"
    return download_media(merge.get("merged_url"), fn)
