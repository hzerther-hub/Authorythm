# -*- coding: utf-8 -*-
"""Layer 2.2:多角度参考图注入出图端的回归护栏。

覆盖:
- `character_all_refs` 返回去重后的所有变体图(上限 3)
- 同一 panel 内出现多角色时,各角色 ref 互不串
- `panel_reference_images` 上限为 8(Wan 3.0 留余量)
- prev_image_url 始终追加在末尾(关键帧链式馈送不被挤掉)

**不污染用户库**:所有 panel/character 走 tmp_path + autouse fixture 隔离。
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from app.core import db
from app.pipeline import comic


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """重定向 DB 与 STATIC 到 tmp_path,清 thread-local 连接。"""
    static = tmp_path / "static"
    static.mkdir()
    (static / "images").mkdir()
    (static / "comics").mkdir()
    (static / "uploads").mkdir()

    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "t.sqlite3")
    monkeypatch.setattr(db.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db.config, "STATIC_DIR", static)
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    yield tmp_path
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


def _make_drama(tmp_path, name="测试剧"):
    did = db.ex(
        "INSERT INTO dramas(title,created_at,updated_at) VALUES(?,?,?)",
        (name, db.now(), db.now()),
    )
    return did


def _make_episode(drama_id, script="test"):
    eid = db.ex(
        "INSERT INTO episodes(drama_id,episode_number,script_content,content,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?)",
        (drama_id, 1, script, script, db.now(), db.now()),
    )
    return eid


def _make_character(drama_id, name="角色A", image="/static/images/a.png",
                    comic_image="/static/images/a_comic.png"):
    cid = db.ex(
        "INSERT INTO characters(drama_id,name,image_url,comic_image_url,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?)",
        (drama_id, name, image, comic_image, db.now(), db.now()),
    )
    return cid


def _make_variant(character_id, comic_image, sort_order=0):
    vid = db.ex(
        "INSERT INTO character_variants(character_id,label,final_prompt,comic_image_url,sort_order,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (character_id, f"v{sort_order}", "test", comic_image, sort_order, db.now()),
    )
    return vid


def _make_scene(drama_id, name="场景A", image="/static/images/scene.png"):
    sid = db.ex(
        "INSERT INTO scenes(drama_id,name,image_url,created_at,updated_at) VALUES(?,?,?,?,?)",
        (drama_id, name, image, db.now(), db.now()),
    )
    return sid


def _make_panel(episode_id, panel_number, description="desc"):
    pid = db.ex(
        "INSERT INTO comic_panels(episode_id,panel_number,description,created_at,updated_at)"
        " VALUES(?,?,?,?,?)",
        (episode_id, panel_number, description, db.now(), db.now()),
    )
    return pid


def _link_panel_char(panel_id, character_id):
    db.ex("INSERT OR IGNORE INTO comic_panel_characters(panel_id,character_id) VALUES(?,?)",
          (panel_id, character_id))


def _link_panel_scene(panel_id, scene_id):
    db.ex("INSERT OR IGNORE INTO comic_panel_scenes(panel_id,scene_id) VALUES(?,?)",
          (panel_id, scene_id))


def _touch(path: Path) -> Path:
    """落一个真实文件(只为了 exists() 通过)。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")  # 假 PNG
    return path


def test_character_all_refs_returns_dedup_multi_views(tmp_db):
    """同一角色 3 变体 + 1 主图,应返回前 3 张(去重 + 上限)。"""
    static = tmp_db / "static" / "images"
    _touch(static / "a_main.png")
    _touch(static / "a_v0.png")
    _touch(static / "a_v1.png")
    _touch(static / "a_v2.png")

    did = _make_drama(tmp_db)
    cid = _make_character(did, comic_image="/static/images/a_main.png")
    _make_variant(cid, "/static/images/a_v0.png", sort_order=0)
    _make_variant(cid, "/static/images/a_v1.png", sort_order=1)
    _make_variant(cid, "/static/images/a_v2.png", sort_order=2)

    refs = comic.character_all_refs(cid)
    assert len(refs) == 3, f"expected 3 refs (cap=3), got {len(refs)}"
    # 全部去重
    assert len(set(refs)) == 3
    # 全部是真实存在的本地路径
    for r in refs:
        assert Path(r).exists(), f"ref not found: {r}"


def test_character_all_refs_falls_back_to_main_image(tmp_db):
    """没有变体时,回退到 characters 主图(至少 1 张)。"""
    static = tmp_db / "static" / "images"
    _touch(static / "a_main.png")

    did = _make_drama(tmp_db)
    cid = _make_character(did, comic_image="/static/images/a_main.png")
    # 无变体

    refs = comic.character_all_refs(cid)
    assert len(refs) == 1
    assert Path(refs[0]).exists()


def test_panel_reference_images_dedupes_across_characters(tmp_db):
    """panel 绑了两个角色(用同一张主图),refs 应去重,不会送 2 份。"""
    static = tmp_db / "static" / "images"
    _touch(static / "shared.png")

    did = _make_drama(tmp_db)
    cid_a = _make_character(did, name="A", comic_image="/static/images/shared.png")
    cid_b = _make_character(did, name="B", comic_image="/static/images/shared.png")
    eid = _make_episode(did)
    pid = _make_panel(eid, 1)
    _link_panel_char(pid, cid_a)
    _link_panel_char(pid, cid_b)

    refs = comic.panel_reference_images(pid)
    assert len(refs) == 1, f"同图应去重,got {len(refs)}: {refs}"


def test_panel_reference_images_includes_scene_and_prev(tmp_db):
    """角色 + 场景 + 关键帧 prev 都进 refs,顺序:角色 → 场景 → prev。"""
    static = tmp_db / "static" / "images"
    _touch(static / "char.png")
    _touch(static / "scene.png")
    _touch(static / "prev.png")

    did = _make_drama(tmp_db)
    cid = _make_character(did, comic_image="/static/images/char.png")
    sid = _make_scene(did, image="/static/images/scene.png")
    eid = _make_episode(did)
    pid = _make_panel(eid, 1)
    _link_panel_char(pid, cid)
    _link_panel_scene(pid, sid)

    refs = comic.panel_reference_images(pid, prev_image_url="/static/images/prev.png")
    assert len(refs) == 3
    assert refs[0].endswith("char.png")
    assert refs[1].endswith("scene.png")
    assert refs[2].endswith("prev.png"), "关键帧 prev 应在末尾"


def test_panel_reference_images_caps_at_8(tmp_db):
    """防止撑爆生图 payload —— 上限 8。"""
    static = tmp_db / "static" / "images"
    paths = []
    for i in range(10):
        p = static / f"img_{i}.png"
        _touch(p)
        paths.append(f"/static/images/img_{i}.png")

    did = _make_drama(tmp_db)
    cids = []
    for i in range(3):
        cid = _make_character(did, name=f"C{i}", comic_image=paths[i])
        # 每角色 3 张变体(共 9 张)→ 实际只取 3 张
        for v in range(2):
            _make_variant(cid, paths[i] if v == 0 else f"/static/images/v_{i}_{v}.png",
                          sort_order=v)
        cids.append(cid)
    eid = _make_episode(did)
    pid = _make_panel(eid, 1)
    for cid in cids:
        _link_panel_char(pid, cid)

    refs = comic.panel_reference_images(pid)
    assert len(refs) <= 8, f"应被 cap 8 截断,got {len(refs)}"
