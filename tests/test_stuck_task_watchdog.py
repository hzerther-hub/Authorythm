# -*- coding: utf-8 -*-
"""僵尸任务看门狗的回归护栏(对应 docs/孤儿生成任务自愈-任务书.md §五)。

任务书建议补一个 pytest「锁住巡检间隔 ≥30 分钟」。**那条断言是无效的** ——
出错值 45 分钟照样 > 30,测试会绿着放行这个 bug。真正要锁的是:

    巡检间隔 > 单个任务可能停留在 processing 的最长时间

而这个上界必须从 video_client 的实际常量推导,不能写成魔数,否则改轮询参数时
又会悄悄失配(这正是 45 分钟定错的成因:那个 30 分钟是参考项目的数,不是本仓库的)。
"""
from __future__ import annotations

import sqlite3
import threading

import pytest

from app.ai import video_client
from app.core import db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """把 db 指向临时库,并清掉 get_db 的 thread-local 连接缓存。

    清连接是必须的:get_db 把连接缓存在 threading.local 上,同一个 pytest 进程里
    一旦建过就一直复用,后续 monkeypatch 改 DB_PATH 对**已存在的连接无效**。不这样
    隔离的话,第二个测试起会静默读写上一个测试的库 —— 实测踩过一次:一个断言因此
    在错误的库上假绿。
    """
    path = tmp_path / "t.sqlite3"
    monkeypatch.setattr(db.config, "DB_PATH", path)
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None          # 让下一次 get_db() 按新路径重建
    db.init_db()
    yield path
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


def _read_fresh(path) -> sqlite3.Connection:
    """独立连接读库,绕开被测连接自己的事务视图。"""
    c = sqlite3.connect(str(path))
    c.row_factory = sqlite3.Row
    return c


def test_reap_interval_exceeds_real_generation_ceiling():
    """巡检间隔必须高于真实生成上界。"""
    ceiling = video_client.max_task_processing_s()
    assert db.REAP_INTERVAL_S > ceiling, (
        f"REAP_INTERVAL_S={db.REAP_INTERVAL_S}s 低于单任务最坏耗时 {ceiling:.0f}s "
        f"({ceiling / 60:.0f}min):会把正在正常生成的任务判成僵尸。"
        f"改之前先看 video_client.max_task_processing_s() 的推导。"
    )


def test_reap_interval_has_margin_not_just_clears():
    """要求留出余量:等于上界时,一次慢轮询就会顶穿。

    tick 只要落在任务寿命末尾的窗口内就会误杀,余量至少给到 1.5 倍让边界不敏感。
    """
    assert db.REAP_INTERVAL_S >= video_client.max_task_processing_s() * 1.5


def test_poll_ceiling_matches_actual_poll_sites():
    """POLL_* 常量必须和真实轮询上限对得上,否则 max_task_processing_s 会悄悄失真。"""
    assert video_client.POLL_INTERVAL_S * video_client.POLL_MAX_ROUNDS == 50 * 60


def test_wall_clock_gate_is_set():
    """总墙钟闸门必须存在且是有限值。"""
    assert 0 < video_client.CREATE_TOTAL_WALL_CLOCK_S <= 6 * 3600


def test_reap_only_touches_tasks_older_than_interval(tmp_db):
    """巡检只收尾「静默至少一个间隔」的任务 —— 不误杀正在生成的任务。"""
    conn = db.get_db()
    old = "2020-01-01T00:00:00.000Z"
    conn.execute("INSERT INTO sys_task(type,status,created_at,updated_at) "
                 "VALUES('image','processing',?,?)", (old, db.now()))
    conn.execute("INSERT INTO sys_task(type,status,created_at,updated_at) "
                 "VALUES('image','processing',?,?)", (db.now(), db.now()))
    conn.commit()

    rows, done, failed = db.settle_interrupted_tasks(
        conn, db.now(), reason="单测", min_age_s=3600)

    assert (rows, done, failed) == (1, 0, 1), "只应收走那条 2020 年的僵尸任务"
    check = _read_fresh(tmp_db)
    left = check.execute("SELECT COUNT(*) c FROM sys_task "
                         "WHERE status='processing'").fetchone()["c"]
    check.close()
    assert left == 1, "刚建立的任务必须原样保留"


def test_reap_actually_commits(tmp_db):
    """收尾必须真正落盘。

    对应真实踩过的坑:settle_interrupted_tasks 全程没有 commit,启动路径靠
    init_db 末尾兜住,运行期巡检没有调用方 —— UPDATE 只活在本连接事务里,日志照打
    「已收尾 N 个」,界面上的「生成中」纹丝不动。
    """
    conn = db.get_db()
    conn.execute("INSERT INTO sys_task(type,status,created_at,updated_at) "
                 "VALUES('image','processing','2020-01-01T00:00:00.000Z',?)",
                 (db.now(),))
    conn.commit()

    db.settle_interrupted_tasks(conn, db.now(), reason="单测", min_age_s=3600)

    check = _read_fresh(tmp_db)          # 另一条连接:能读到才算真提交
    row = check.execute("SELECT status FROM sys_task ORDER BY id DESC LIMIT 1").fetchone()
    check.close()
    assert row["status"] == "failed"


def test_watchdog_runs_on_its_own_thread_local_connection(tmp_db):
    """巡检必须真跑起来,而不是在 tick 里抛异常被 except 吞掉。

    连接是 thread-local 的(get_db),sqlite3 默认 check_same_thread=True;若把主线程
    的连接借给巡检线程,首次 tick 会抛 ProgrammingError —— 而 _tick 外面的
    except Exception 只 print,看门狗于是每 45 分钟静默死一次,界面看不出任何异常。

    断言的是**收尾真的生效**,不是"函数被调用过":spy 的 finally 无论成功失败都会
    set 事件,只断言调用等于放行失败路径。
    """
    conn = db.get_db()
    conn.execute("INSERT INTO sys_task(type,status,created_at,updated_at) "
                 "VALUES('image','processing','2020-01-01T00:00:00.000Z',?)",
                 (db.now(),))
    conn.commit()

    timer = db.start_stuck_task_watchdog(interval_s=0.3)
    try:
        deadline = threading.Event()
        ok = False
        for _ in range(100):                       # 最多等 ~15s
            check = _read_fresh(tmp_db)
            row = check.execute("SELECT status FROM sys_task ORDER BY id DESC LIMIT 1").fetchone()
            check.close()
            if row and row["status"] == "failed":
                ok = True
                break
            deadline.wait(0.15)
        assert ok, "巡检 15 秒内没有把僵尸任务收走:tick 很可能在跨线程用连接时炸了"
    finally:
        timer.cancel()