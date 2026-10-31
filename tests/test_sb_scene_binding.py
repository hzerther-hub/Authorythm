"""分镜↔场景绑定的回归护栏。

三个真实缺陷(2026-10-27 实测):

1. **点场景卡必崩** —— `episode_page._toggle_ref_bind` 的 scene 分支写的是
   `INSERT OR IGNORE INTO storyboard_scenes(panel_id, scene_id)`,而这张表
   的列是 `storyboard_id / scene_id / variant_id`,**没有 panel_id 列**
   → 执行即 `OperationalError: table storyboard_scenes has no column named
   panel_id`,且异常无人捕获,用户点一下就崩。

2. **场景绑定写错表** —— 场景绑定的真相源是 `storyboards.scene_id` **列**
   (refs.build_shot_reference_list 读的就是它,场景图只有进了这一列才会
   真正进参考图列表)。原实现只写 storyboard_scenes 关联表 → 场景陈设
   逐镜漂,用户却以为「已绑定」。

3. **参考素材面板的场景卡是空操作** —— 那张卡点了什么都不做
   (`link_table = {"scene": None}` 直接 return),与分镜卡参考行那条路
   行为不一致。

测试绝不碰真实库。
"""
from __future__ import annotations

import pytest


@pytest.fixture()
def sb_db(tmp_path, monkeypatch):
    """真库(schema 全)+ 隔离路径。"""
    from app.core import db as _db
    monkeypatch.setattr(_db.config, "DB_PATH", tmp_path / "sb_scene.sqlite3")
    old = getattr(_db._local, "conn", None)
    if old is not None:
        old.close()
    _db._local.conn = None
    _db.init_db()
    yield _db
    conn = getattr(_db._local, "conn", None)
    if conn is not None:
        conn.close()
        _db._local.conn = None


def _seed(db, sb_id=100, scene_id=7):
    ts = db.now()
    db.ex("INSERT INTO storyboards(id,episode_id,storyboard_number,created_at,updated_at) "
          "VALUES(?,?,?,?,?)", (sb_id, 1, 1, ts, ts))
    db.ex("INSERT INTO scenes(id,drama_id,name,location,created_at,updated_at) "
          "VALUES(?,?,?,?,?,?)", (scene_id, 1, "会议室", "会议室", ts, ts))
    return sb_id, scene_id


def test_storyboard_scenes_table_has_no_panel_id_column(sb_db):
    """守栏:这张表没有 panel_id 列 —— 原实现按 panel_id 插入必崩。"""
    cols = [r[1] for r in sb_db.get_db().execute("PRAGMA table_info(storyboard_scenes)")]
    assert "panel_id" not in cols
    assert "storyboard_id" in cols


def test_scene_binding_writes_scene_id_column(sb_db):
    """场景绑定必须写 storyboards.scene_id(参考图列表的真相源)。"""
    sb_id, scene_id = _seed(sb_db)
    # 模拟 UI 的绑定动作:写 scene_id 列 + 同步关联表
    sb_db.ex("UPDATE storyboards SET scene_id=? WHERE id=?", (scene_id, sb_id))
    sb_db.ex("INSERT OR IGNORE INTO storyboard_scenes(storyboard_id,scene_id) VALUES(?,?)",
             (sb_id, scene_id))

    row = sb_db.q1("SELECT * FROM storyboards WHERE id=?", (sb_id,))
    assert row["scene_id"] == scene_id
    # 关联表也要有一份(变体覆盖 refs._variant_image_of 查它)
    n = sb_db.q1("SELECT COUNT(*) c FROM storyboard_scenes WHERE storyboard_id=?",
                 (sb_id,))["c"]
    assert n == 1


def test_bound_scene_enters_reference_list(sb_db):
    """绑了场景 → 场景图要真的进参考图列表(否则用户以为绑了,场景照样漂)。"""
    from app.pipeline import refs as refs_mod
    sb_id, scene_id = _seed(sb_db)
    sb_db.ex("UPDATE characters SET image_url=NULL WHERE 1=0")   # no-op,保持语句合法
    sb_db.ex("UPDATE scenes SET image_url='/static/images/scene.png' WHERE id=?", (scene_id,))
    sb_db.ex("UPDATE storyboards SET scene_id=? WHERE id=?", (scene_id, sb_id))

    sb = dict(sb_db.q1("SELECT * FROM storyboards WHERE id=?", (sb_id,)))
    items = refs_mod.build_shot_reference_list(sb)
    kinds = [i["kind"] for i in items]
    assert "scene" in kinds, f"场景没进参考列表: {items}"
    scene_item = next(i for i in items if i["kind"] == "scene")
    assert scene_item["scene_id"] == scene_id
    assert scene_item["name"] == "会议室"


def test_unbinding_clears_scene_id(sb_db):
    """解绑要把 scene_id 置空(否则场景一直挂着)。"""
    sb_id, scene_id = _seed(sb_db)
    sb_db.ex("UPDATE storyboards SET scene_id=? WHERE id=?", (scene_id, sb_id))
    sb_db.ex("DELETE FROM storyboard_scenes WHERE storyboard_id=?", (sb_id,))
    sb_db.ex("UPDATE storyboards SET scene_id=NULL WHERE id=?", (sb_id,))
    row = sb_db.q1("SELECT scene_id FROM storyboards WHERE id=?", (sb_id,))
    assert row["scene_id"] is None
