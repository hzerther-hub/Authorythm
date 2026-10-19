# -*- coding: utf-8 -*-
"""一次性修复脚本的回归护栏:必须真回写、只在变长时回写、仍不达标时不动库。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.core import db
from app.pipeline import character_spec as cs

SCRIPT = (Path(__file__).resolve().parent.parent
          / "scripts" / "repair_character_appearance.py")


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("repair_character_appearance", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """与 test_stuck_task_watchdog 同一套隔离方式:改 DB_PATH + 清 thread-local。"""
    path = tmp_path / "t.sqlite3"
    monkeypatch.setattr(db.config, "DB_PATH", path)
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    yield path
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


SHORT = "33岁前呈现25岁面容，鹅蛋脸，眉眼锐利带倦意，黑直发常束低马尾"
LONG_AP = "她视觉年龄约二十五岁，实际三十三岁。鹅蛋脸轮廓清瘦而利落，下颌线收得干净。" * 5
LONG_ST = "上身穿一件洗得发软的白色棉质衬衫，袖口挽到小臂中段，肘弯处有细密褶痕。" * 3


def _seed(drama_id: int = 900001, name: str = "林岁晚") -> int:
    db.ex("INSERT OR IGNORE INTO dramas(id,title,created_at,updated_at) VALUES(?,?,?,?)",
          (drama_id, "T", db.now(), db.now()))
    cid = db.ex("INSERT INTO characters(drama_id,name,role_type,appearance,styling,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (drama_id, name, "lead", SHORT, "白衬衫黑西裤", db.now(), db.now()))
    return cid


def test_load_and_group_by_drama(script, tmp_db):
    _seed(900001, "甲")
    _seed(900002, "乙")
    rows = script.load_characters()
    grouped = script.group_by_drama(rows)
    assert {900001, 900002} <= set(grouped)
    assert all(len(grouped[d]) == 1 for d in (900001, 900002))


def test_repair_drama_writes_back(script, tmp_db, monkeypatch):
    cid = _seed()
    chars = [dict(db.q1("SELECT id,drama_id,name,appearance,styling FROM characters WHERE id=?",
                        (cid,)))]

    def fake_expand(chars, **kwargs):
        return [dict(chars[0], appearance=LONG_AP, styling=LONG_ST)]

    monkeypatch.setattr(cs, "expand_many", fake_expand)
    n, updated, still_bad = script.repair_drama(900001, chars, config_id=None, lang="zh", pause=0)

    assert (n, updated, still_bad) == (1, 1, 0)
    row = db.q1("SELECT appearance,styling FROM characters WHERE id=?", (cid,))
    assert row["appearance"] == LONG_AP
    assert row["styling"] == LONG_ST


def test_repair_drama_does_not_touch_db_when_still_short(script, tmp_db, monkeypatch):
    cid = _seed()
    chars = [dict(db.q1("SELECT id,drama_id,name,appearance,styling FROM characters WHERE id=?",
                        (cid,)))]

    monkeypatch.setattr(cs, "expand_many", lambda chars, **k: [dict(chars[0])])
    n, updated, still_bad = script.repair_drama(900001, chars, config_id=None, lang="zh", pause=0)

    assert (n, updated, still_bad) == (1, 0, 1)
    row = db.q1("SELECT appearance FROM characters WHERE id=?", (cid,))
    assert row["appearance"] == SHORT, "没有任何改进时不能写库"


def test_skip_empty_filters_synthetic_roles(script, tmp_db):
    _seed(900001, "有素材")
    db.ex("INSERT INTO characters(drama_id,name,role_type,appearance,styling,"
          "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
          (900001, "出镜人物", "lead", "", "", db.now(), db.now()))
    # init_db() 会种一个示例项目(含角色),这里只看自己造的那个项目
    rows = [r for r in script.load_characters() if r["drama_id"] == 900001]
    kept = [r for r in rows
            if (r.get("appearance") or "").strip() or (r.get("styling") or "").strip()]
    assert len(rows) == 2 and len(kept) == 1
