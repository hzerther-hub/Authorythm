# -*- coding: utf-8 -*-
"""单实例闸门回归。

背景(2026-10-24 实测):`_acquire_db_lock` 一直存在,但 init_db 拿不到锁只是
跳过孤儿回收,第二个实例照样起窗 → 双实例同写一个 SQLite。main() 现在在
init_db **之前**先 `claim_single_instance()`,拿不到锁提示并退出。
"""
from __future__ import annotations

import io
import pathlib

from app.core import db


def test_claim_on_fresh_db_succeeds(tmp_path, monkeypatch):
    """空库首次认领 → True,并留下锁文件(锁文件残留无害,内核退出自动释放)。"""
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "single.sqlite3")
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db._lock_fd = None                     # 换库前放掉上一测的锁
    try:
        assert db.claim_single_instance() is True
        assert (tmp_path / "single.sqlite3.lock").exists()
        # 同进程内重复认领(重入)= 已持有 → True
        assert db.claim_single_instance() is True
    finally:
        if db._lock_fd is not None:
            import os
            os.close(db._lock_fd[1])
            db._lock_fd = None
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
            db._local.conn = None


def test_main_guards_before_init_db():
    """main() 必须在 init_db 之前过闸门,且带 PYDRAMA_ALLOW_MULTI 豁免 ——
    防止将来重构把闸门挪到 init_db 之后(那时第二个进程已经摸到库了)。"""
    src = io.open(pathlib.Path("app/main.py"), encoding="utf-8").read()
    guard = src.find("claim_single_instance")
    init = src.find("db.init_db()")
    assert guard != -1 and init != -1 and guard < init
    assert "PYDRAMA_ALLOW_MULTI" in src


def test_lock_held_by_other_process_reports_false(tmp_path, monkeypatch):
    """锁被占(模拟另一实例持有)→ claim 返回 False,main 侧据此退出。"""
    monkeypatch.setattr(db, "_acquire_db_lock", lambda: False)
    assert db.claim_single_instance() is False
