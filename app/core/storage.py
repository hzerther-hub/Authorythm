"""存储用量统计(对齐参考项目 backend/src/routes/storage.ts + utils/dirsize.ts)。

分桶统计 static/ 下的 db / images / videos / merged / uploads / comics / temp / other,
数据库文件(含 -wal / -shm)单独计数(不在目录遍历里),另报剩余可用空间。
结果缓存 60s,过期后先返回旧值再后台重算(stale-while-revalidate)。
"""
from __future__ import annotations

import contextlib
import os
import threading
import time

from . import config

CACHE_TTL_S = 60
BUCKETS = ("db", "images", "videos", "merged", "comics", "uploads", "temp", "other")
_DIR_BUCKETS = {"images", "videos", "merged", "comics", "uploads", "temp"}
_cache: dict = {"data": None, "at": 0.0}
_lock = threading.Lock()


def _db_files_bytes() -> int:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = config.DB_PATH.with_name(config.DB_PATH.name + suffix) if suffix else config.DB_PATH
        with contextlib.suppress(OSError):
            total += p.stat().st_size
    return total


def _dir_bytes(path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                continue
    return total


def compute_usage() -> dict:
    """全量重算一次分桶用量(约 100ms 级,别在 UI 线程里高频调)。"""
    out = {b: 0 for b in BUCKETS}
    out["db"] = _db_files_bytes()
    base = config.STATIC_DIR
    try:
        for entry in os.scandir(base):
            if not entry.is_dir():
                continue
            name = entry.name
            bucket = name if name in _DIR_BUCKETS else "other"
            out[bucket] += _dir_bytes(entry.path)
    except OSError:
        pass
    used = sum(out.values())
    try:
        import shutil
        free = shutil.disk_usage(base).free      # Windows 无 statvfs,用 shutil
    except Exception:  # noqa: BLE001
        free = 0
    return {"buckets": out, "used": used, "free": free,
            "path": str(base), "computed_at": time.time()}


def get_usage(force: bool = False) -> dict:
    """带 60s 缓存的用量查询;过期时先返回旧值,再触发后台重算。"""
    with _lock:
        fresh = _cache["data"] and (time.time() - _cache["at"]) < CACHE_TTL_S
        if _cache["data"] and (fresh or not force):
            if not fresh:
                threading.Thread(target=_refresh, daemon=True).start()
            return _cache["data"]
    _refresh()
    return _cache["data"] or {"buckets": {b: 0 for b in BUCKETS}, "used": 0, "free": 0,
                              "path": str(config.STATIC_DIR), "computed_at": 0.0}


def _refresh() -> None:
    data = compute_usage()
    with _lock:
        _cache["data"] = data
        _cache["at"] = time.time()


def human_size(num: int) -> str:
    """人类可读体积。"""
    n = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


BUCKET_CN = {"db": "数据库", "images": "图片", "videos": "视频", "merged": "成片",
             "comics": "漫画长图", "uploads": "上传", "temp": "临时", "other": "其他"}
