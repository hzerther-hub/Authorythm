# -*- coding: utf-8 -*-
"""端到端漫画生成编排(Layer 1)的回归护栏。

覆盖:
- 拆格 → 出图 → 拼长图 三步顺序正确
- 单格出图失败不中断,后续格继续
- `force=False` 时跳过已出图格,`force=True` 时全部重出
- 已出图格作为 prev_image_url 喂给下一格(关键帧链式)
- 空剧本抛 RuntimeError,不创建 panel
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from app.core import db
from app.pipeline import comic_pipeline


SCRIPT_VALID = (
    "## S01|内景·咖啡馆|白天\n"
    "李明端着咖啡望向窗外。\n\n"
    "## S02|内景·咖啡馆|白天\n"
    "门铃响了,王芳推门进来。\n"
)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    static = tmp_path / "static"
    for sub in ("images", "videos", "narration", "merged", "comics", "uploads", "covers"):
        (static / sub).mkdir(parents=True, exist_ok=True)

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


def _setup_episode(tmp_path, script=SCRIPT_VALID):
    did = db.ex(
        "INSERT INTO dramas(title,comic_style,created_at,updated_at) VALUES(?,?,?,?)",
        ("测试剧", "comic", db.now(), db.now()),
    )
    eid = db.ex(
        "INSERT INTO episodes(drama_id,episode_number,script_content,content,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?)",
        (did, 1, script, script, db.now(), db.now()),
    )
    return did, eid


def test_empty_script_raises_without_creating_panels(tmp_db):
    """空剧本 → RuntimeError,且不留任何 panel 记录。"""
    did, eid = _setup_episode(tmp_db, script="")
    with pytest.raises(RuntimeError, match="剧本为空"):
        comic_pipeline.generate_full_comic(eid)
    n = db.q1("SELECT COUNT(*) c FROM comic_panels WHERE episode_id=?", (eid,))["c"]
    assert n == 0


def test_end_to_end_runs_split_then_image_then_stitch(tmp_db):
    """拆格 → 出图 → 拼长图,三步按顺序执行。"""
    did, eid = _setup_episode(tmp_db)
    calls = {"split": 0, "image": 0, "stitch": 0}

    with mock.patch("app.pipeline.comic.split_panels",
                    side_effect=lambda *a, **kw: (_ for _ in ()).throw(
                        StopIteration)) as _:
        # StopIteration 不好用,改用 mock
        pass

    with mock.patch("app.pipeline.comic.split_panels") as m_split, \
         mock.patch("app.pipeline.comic.panel_image_prompt",
                    return_value="<test prompt>") as m_prompt, \
         mock.patch("app.pipeline.comic.panel_reference_images",
                    return_value=[]) as m_refs, \
         mock.patch("app.pipeline.comic_pipeline.image_client.generate_image",
                    return_value=("data/static/comics/panel_1.png", "test")) as m_img, \
         mock.patch("app.pipeline.comic_pipeline.stitch.stitch_panels") as m_stitch:

        # split 落 2 个 panel
        def fake_split(ep_id, text_config_id=None, lang=None):
            from app.core import db as _db
            for n in (1, 2):
                _db.ex(
                    "INSERT INTO comic_panels(episode_id,panel_number,description,created_at,updated_at)"
                    " VALUES(?,?,?,?,?)",
                    (ep_id, n, f"panel {n}", _db.now(), _db.now()),
                )
            calls["split"] += 1
            return 2
        m_split.side_effect = fake_split

        # image 返回 fake 本地路径(实际写到 static 目录)
        def fake_image(*a, **kw):
            calls["image"] += 1
            out = str(tmp_db / "static" / "comics" / f"p_{calls['image']}.png")
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"\x89PNG\r\n\x1a\n")
            return out, "fake"
        m_img.side_effect = fake_image

        m_stitch.side_effect = lambda *a, **kw: calls.__setitem__("stitch", calls["stitch"] + 1)

        result = comic_pipeline.generate_full_comic(eid)

    assert result["panels"] == 2
    assert result["generated"] == 2
    assert result["failed"] == 0
    assert calls == {"split": 1, "image": 2, "stitch": 1}
    # 所有 panel 都落了 image_url
    rows = db.q("SELECT image_url FROM comic_panels WHERE episode_id=? ORDER BY panel_number", (eid,))
    assert all(r["image_url"] for r in rows)


def test_per_panel_image_failure_does_not_abort(tmp_db):
    """第 1 格失败 → 标 panel.status / 不落图,第 2 格继续。"""
    did, eid = _setup_episode(tmp_db)

    with mock.patch("app.pipeline.comic.split_panels") as m_split, \
         mock.patch("app.pipeline.comic.panel_image_prompt",
                    return_value="<test>") as m_prompt, \
         mock.patch("app.pipeline.comic.panel_reference_images",
                    return_value=[]) as m_refs, \
         mock.patch("app.pipeline.comic_pipeline.image_client.generate_image") as m_img, \
         mock.patch("app.pipeline.comic_pipeline.stitch.stitch_panels"):

        def fake_split(ep_id, text_config_id=None, lang=None):
            for n in (1, 2):
                db.ex(
                    "INSERT INTO comic_panels(episode_id,panel_number,description,created_at,updated_at)"
                    " VALUES(?,?,?,?,?)",
                    (ep_id, n, f"p{n}", db.now(), db.now()),
                )
            return 2
        m_split.side_effect = fake_split

        # 第一次抛,第二次成功
        m_img.side_effect = [RuntimeError("provider down"), ("ok", "fake")]
        # 第二次出图需真实路径
        orig_generate = m_img
        def second_ok(*a, **kw):
            out = str(tmp_db / "static" / "comics" / "p_2.png")
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"\x89PNG\r\n\x1a\n")
            return out, "fake"
        m_img.side_effect = [RuntimeError("provider down"), second_ok()]

        result = comic_pipeline.generate_full_comic(eid)

    assert result["panels"] == 2
    assert result["generated"] == 1
    assert result["failed"] == 1


def test_skip_already_generated_panels(tmp_db):
    """默认不重出已有 image_url 的格;force=True 才全部重出。"""
    did, eid = _setup_episode(tmp_db)
    # 预置 2 个 panel,panel 1 已有图
    db.ex("INSERT INTO comic_panels(episode_id,panel_number,description,image_url,created_at,updated_at)"
          " VALUES(?,?,?,?,?,?)",
          (eid, 1, "p1", "/static/comics/p1.png", db.now(), db.now()))
    db.ex("INSERT INTO comic_panels(episode_id,panel_number,description,created_at,updated_at)"
          " VALUES(?,?,?,?,?)",
          (eid, 2, "p2", db.now(), db.now()))

    with mock.patch("app.pipeline.comic.split_panels") as m_split, \
         mock.patch("app.pipeline.comic.panel_image_prompt",
                    return_value="<test>") as m_prompt, \
         mock.patch("app.pipeline.comic.panel_reference_images",
                    return_value=[]) as m_refs, \
         mock.patch("app.pipeline.comic_pipeline.image_client.generate_image") as m_img, \
         mock.patch("app.pipeline.comic_pipeline.stitch.stitch_panels"):

        m_split.side_effect = lambda *a, **kw: None  # 不重拆
        m_img.return_value = (str(tmp_db / "static/comics/p2.png"), "fake")

        result = comic_pipeline.generate_full_comic(eid)

    assert result["panels"] == 2
    assert result["skipped"] == 1    # panel 1 已有图,跳过
    assert result["generated"] == 1  # panel 2 出图
    assert m_img.call_count == 1


def test_force_regenerates_existing_panels(tmp_db):
    """force=True 时已出图格也重出。"""
    did, eid = _setup_episode(tmp_db)
    db.ex("INSERT INTO comic_panels(episode_id,panel_number,description,image_url,created_at,updated_at)"
          " VALUES(?,?,?,?,?,?)",
          (eid, 1, "p1", "/static/comics/old.png", db.now(), db.now()))

    with mock.patch("app.pipeline.comic.split_panels") as m_split, \
         mock.patch("app.pipeline.comic.panel_image_prompt",
                    return_value="<test>") as m_prompt, \
         mock.patch("app.pipeline.comic.panel_reference_images",
                    return_value=[]) as m_refs, \
         mock.patch("app.pipeline.comic_pipeline.image_client.generate_image") as m_img, \
         mock.patch("app.pipeline.comic_pipeline.stitch.stitch_panels"):

        m_split.side_effect = lambda *a, **kw: None
        m_img.return_value = (str(tmp_db / "static/comics/p1_new.png"), "fake")

        result = comic_pipeline.generate_full_comic(eid, force=True)

    assert result["skipped"] == 0
    assert result["generated"] == 1
    assert m_img.call_count == 1
