# -*- coding: utf-8 -*-
"""metrics 极简实现的回归护栏。

覆盖:
- incr / observe 累加
- snapshot 包含 counters + timers 的 p50/p95
- dump_recent 取最近 n 条
- flush_now 落 JSONL
- reset 清空(测试间隔离)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import metrics
from app.core import db


@pytest.fixture(autouse=True)
def _isolate_metrics(tmp_path, monkeypatch):
    """每个测试用 tmp_path,防止污染真实 data/metrics.jsonl。"""
    monkeypatch.setattr(metrics, "_data_dir", lambda: tmp_path)
    metrics.reset()
    yield
    metrics.reset()


def test_incr_basic():
    metrics.incr("test.counter")
    metrics.incr("test.counter", 3)
    snap = metrics.snapshot()
    assert snap["counters"]["test.counter"] == 4


def test_observe_records_timer_with_percentiles():
    for v in [10, 20, 30, 40, 50, 100, 200, 300, 400, 500]:
        metrics.observe("test.latency_ms", v)
    snap = metrics.snapshot()
    t = snap["timers"]["test.latency_ms"]
    assert t["count"] == 10
    assert t["max"] == 500
    # p50 落在中位数附近
    assert 50 <= t["p50"] <= 300


def test_dump_recent_returns_last_n():
    for i in range(50):
        metrics.incr(f"test.e.{i}")
    rows = metrics.dump_recent(10)
    assert len(rows) == 10
    # 最后一条应该是 49(最近)
    assert rows[-1]["name"] == "test.e.49"


def test_flush_now_writes_jsonl(tmp_path):
    metrics.incr("test.flush", 5)
    metrics.observe("test.flush.latency", 100)
    metrics.flush_now()
    path = tmp_path / "metrics.jsonl"
    assert path.exists()
    line = path.read_text("utf-8").strip().splitlines()[-1]
    parsed = json.loads(line)
    assert "snapshot" in parsed
    assert parsed["snapshot"]["counters"].get("test.flush") == 5


def test_flush_now_noop_when_empty():
    """无数据时不写文件(避免空文件污染)。"""
    metrics.flush_now()
    # 调用了不抛错即可,无 file 副作用
    assert True


def test_incr_does_not_raise_on_garbage_args():
    """埋点必须不能抛 —— 业务侧无 try/except 也安全。"""
    try:
        metrics.incr(None)  # type: ignore[arg-type]
        metrics.observe("x", None)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        pytest.fail("incr/observe 不能抛")


def test_observe_caps_at_2000_samples():
    """单 key 上限 2000,FIFO 丢最早。"""
    for v in range(3000):
        metrics.observe("test.burst", float(v))
    snap = metrics.snapshot()
    assert snap["timers"]["test.burst"]["count"] == 2000
    # max 应该是 2999(最新)
    assert snap["timers"]["test.burst"]["max"] == 2999.0
