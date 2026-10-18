# -*- coding: utf-8 -*-
"""进程内 metrics 极简实现:Counter / Timer / 注册表 / JSONL 持久化。

设计取舍:
- 不引入 prometheus_client / opentelemetry —— 单机桌面应用,只需本地观测。
- 命名约定:`subsystem.event.unit`(如 `task.image.completed` / `ai.text.latency_ms`)。
- 进程内 dict + threading.Lock,线程安全。
- 持久化:`data/metrics.jsonl`,每 60s 或进程退出前 flush 一次。
- 不抛异常:埋点调用用 try/except 包住,失败仅静默。

使用:
    from app.core import metrics
    metrics.incr("task.image.completed")
    metrics.observe("ai.text.latency_ms", 234)
    metrics.flush_now()                       # 立即刷盘
    rows = metrics.dump_recent(200)            # 给设置页「最近指标」弹窗用
"""
from __future__ import annotations

import atexit
import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()
_COUNTERS: dict[str, int] = {}
_TIMERS_MS: dict[str, list[float]] = {}    # 全量保留(去重),dump 时算分位数
_EVENTS: deque[dict[str, Any]] = deque(maxlen=5000)   # 最近事件
_FLUSH_INTERVAL = 60.0
_LAST_FLUSH = time.time()
_CONFIGURED = False


def _data_dir() -> Path:
    try:
        from . import config
        base = config.DATA_DIR
    except Exception:  # noqa: BLE001
        base = Path.cwd() / "data"
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _metrics_path() -> Path:
    return _data_dir() / "metrics.jsonl"


def incr(name: str, value: int = 1, **ctx: Any) -> None:
    """自增计数器。"""
    try:
        with _LOCK:
            _COUNTERS[name] = _COUNTERS.get(name, 0) + value
            _EVENTS.append({
                "ts": time.time(),
                "kind": "counter",
                "name": name,
                "value": _COUNTERS[name],
                **ctx,
            })
    except Exception:  # noqa: BLE001
        pass


def observe(name: str, value: float, **ctx: Any) -> None:
    """记录一个观测值(毫秒、字节、任意数值)。"""
    try:
        with _LOCK:
            arr = _TIMERS_MS.setdefault(name, [])
            arr.append(float(value))
            # 防止单 key 涨爆:每 key 上限 2000 个采样,FIFO 丢最早
            if len(arr) > 2000:
                del arr[: len(arr) - 2000]
            _EVENTS.append({
                "ts": time.time(),
                "kind": "observe",
                "name": name,
                "value": float(value),
                **ctx,
            })
    except Exception:  # noqa: BLE001
        pass


def _percentile(arr: list[float], p: float) -> float:
    if not arr:
        return 0.0
    s = sorted(arr)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return s[k]


def snapshot() -> dict[str, Any]:
    """当前所有计数 / 观测的快照(dict 形式,UI 直接用)。

    自动取锁。**已持锁的调用方**应直接用 `_snapshot_locked()` 以避免死锁。
    """
    with _LOCK:
        return _snapshot_locked()


def _snapshot_locked() -> dict[str, Any]:
    """snapshot 的「持锁态」版本 —— 调用方必须已经持有 _LOCK。"""
    out_counters = dict(_COUNTERS)
    out_timers: dict[str, dict[str, float]] = {}
    for k, arr in _TIMERS_MS.items():
        if not arr:
            continue
        out_timers[k] = {
            "count": len(arr),
            "avg": sum(arr) / len(arr),
            "p50": _percentile(arr, 50),
            "p95": _percentile(arr, 95),
            "p99": _percentile(arr, 99),
            "max": max(arr),
        }
    return {"counters": out_counters, "timers": out_timers}


def dump_recent(n: int = 200) -> list[dict[str, Any]]:
    """最近 n 条事件(供 UI 显示)。"""
    with _LOCK:
        return list(_EVENTS)[-n:]


def reset() -> None:
    """清空所有计数/观测(测试用)。"""
    with _LOCK:
        _COUNTERS.clear()
        _TIMERS_MS.clear()
        _EVENTS.clear()


def flush_now() -> None:
    """把当前 snapshot 追加到 data/metrics.jsonl,然后清空 events 缓冲。

    文件不存在则创建,存在则 append;每次一行 JSON。
    """
    global _LAST_FLUSH
    with _LOCK:
        snap = _snapshot_locked()
        events = list(_EVENTS)
        _EVENTS.clear()
        _LAST_FLUSH = time.time()
    if not snap["counters"] and not snap["timers"] and not events:
        return
    try:
        path = _metrics_path()
        ts = time.time()
        line = json.dumps({"ts": ts, "snapshot": snap}, ensure_ascii=False, default=str)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def setup_periodic_flush(interval_sec: float = _FLUSH_INTERVAL) -> None:
    """启动后台定时刷盘的线程(只在主进程入口调一次)。

    退出时 atexit 兜底再刷一次。
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    stop = threading.Event()
    _CONFIGURED = True

    def _loop():
        while not stop.wait(interval_sec):
            flush_now()

    th = threading.Thread(target=_loop, name="metrics-flush", daemon=True)
    th.start()
    atexit.register(flush_now)

    # 进程退出信号
    def _signal_handler(signum, frame):  # noqa: ARG001
        flush_now()
        os._exit(0)

    try:
        import signal
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _signal_handler)
            except (ValueError, OSError):
                pass
    except Exception:  # noqa: BLE001
        pass


def maybe_flush() -> None:
    """低频轮询调用:距上次 flush 超过 _FLUSH_INTERVAL 就刷一次。

    适合塞在 taskmgr 任务完成回调里,不必每任务都刷。
    """
    global _LAST_FLUSH
    if time.time() - _LAST_FLUSH < _FLUSH_INTERVAL:
        return
    flush_now()


# 命名建议(供 AGENTS.md 引用):
NAMING_HINT = {
    "taskmgr": "task.{type}.{status} / task.{type}.duration_ms",
    "ai": "ai.{type}.{provider}.{status} / ai.{type}.latency_ms",
    "novel": "novel.chapter.{event} / novel.review.{event}",
    "video_clone": "video_clone.shot.{event} / video_clone.merge.{event}",
}
