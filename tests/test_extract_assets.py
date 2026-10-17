# -*- coding: utf-8 -*-
"""资产提取:已存在资产也必须关联到本集。

现场:分卷规划先建好了 9 个角色,提取运行时模型返回的 5 个角色全在
`existing` 里,原实现遇到同名直接 `continue` —— 提取任务显示成功,
但 `episode_characters` 仍是 0,本集资产列表一片空白。
用户看到的「周铁城已经存在」只是模型思考里的原话,真正的问题是
已存在角色没有被 episode_* 关联。
"""
from __future__ import annotations

import pytest

from app.core import db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "extract.sqlite3")
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    yield
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


def test_existing_assets_are_linked_to_episode(tmp_db, monkeypatch):
    ts = db.now()
    did, eid, cid = 990011, 990012, 990013
    db.ex("INSERT INTO dramas(id,title,work_type,status,created_at,updated_at) "
          "VALUES(?,?,?,?,?,?)", (did, "extract-test", "novel", "pending", ts, ts))
    db.ex("INSERT INTO episodes(id,drama_id,episode_number,title,status,script_content,"
          "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
          (eid, did, 1, "e1", "pending", "周铁城在车间里检查水压机。", ts, ts))
    db.ex("INSERT INTO characters(id,drama_id,name,created_at,updated_at) "
          "VALUES(?,?,?,?,?)", (cid, did, "周铁城", ts, ts))

    from app.pipeline import extractor
    monkeypatch.setattr(extractor.runner, "run_agent_json", lambda *a, **k: {
        "characters": [
            {"name": "周铁城", "role_type": "lead"},
            {"name": "新角色", "role_type": "supporting",
             "appearance": "a", "styling": "s"},
        ],
        "scenes": [{"location": "车间", "time": "夜", "prompt": "p"}],
        "props": [{"name": "扳手", "type": "工具", "description": "d"}],
    })

    st = extractor.extract_assets(eid, config_id=None, lang="zh")

    assert st["characters"] == 1, "已有角色不应重复插入,只应新增 1 个"
    assert st["scenes"] == 1 and st["props"] == 1
    assert db.q1("SELECT COUNT(*) c FROM episode_characters WHERE episode_id=?",
                 (eid,))["c"] == 2, "已有角色 + 新角色都必须关联到本集"
    assert db.q1("SELECT COUNT(*) c FROM episode_scenes WHERE episode_id=?",
                 (eid,))["c"] == 1
    assert db.q1("SELECT COUNT(*) c FROM episode_props WHERE episode_id=?",
                 (eid,))["c"] == 1
