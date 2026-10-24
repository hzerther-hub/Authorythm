# -*- coding: utf-8 -*-
"""分镜 → 预演工程生成器:全程打桩,绝不碰真实数据库(用户数据是红线)。"""
from __future__ import annotations

import pytest

from app.pipeline import previz, previz_gen


def _install_fake_db(monkeypatch, *, ep, shots, chars, props, sb_chars):
    """打桩 previz_gen 里的 db.q / db.q1。sb_chars: {storyboard_id: character_id}。"""

    def fake_q(sql, params=()):
        if "FROM storyboards" in sql:
            return shots
        if "FROM characters c" in sql:
            return chars
        if "FROM props p" in sql:
            return props
        return []

    def fake_q1(sql, params=()):
        if "FROM episodes" in sql:
            return ep
        if "FROM storyboard_characters" in sql:
            cid = sb_chars.get(params[0])
            return {"character_id": cid} if cid else None
        return None

    monkeypatch.setattr(previz_gen.db, "q", fake_q)
    monkeypatch.setattr(previz_gen.db, "q1", fake_q1)


def _shot(sid, num, **kw):
    base = {"id": sid, "storyboard_number": num, "duration": 2.0, "shot_type": "中景",
            "angle": "平拍", "movement": "固定", "description": f"描述{num}",
            "title": f"标题{num}", "content": f"对白{num}", "atmosphere": "紧张",
            "location": "卧室"}
    base.update(kw)
    return base


@pytest.fixture
def env(tmp_path, monkeypatch):
    ep = {"id": 7, "title": "雨夜追凶", "episode_number": 3}
    shots = [_shot(1, 1, shot_type="特写", movement="推"),
             _shot(2, 2, shot_type="全景", movement="摇"),
             _shot(3, 3, movement="固定", duration=4.0)]
    chars = [{"id": 11, "name": "林小雨", "appearance": "年轻女性", "image_url": None},
             {"id": 12, "name": "张探长", "appearance": "中年男性", "image_url": None}]
    props = [{"name": "餐桌"}, {"name": "双人床"}, {"name": "水晶球"}]
    _install_fake_db(monkeypatch, ep=ep, shots=shots, chars=chars, props=props,
                     sb_chars={1: 11, 2: 12})
    return tmp_path / "proj.directordesk.json"


def test_generate_basic(env):
    result = previz_gen.generate_from_episode(7, out_path=env)
    assert result["shots"] == 3
    assert result["actors"] == 2
    assert result["duration"] == pytest.approx(8.0)  # 2+2+4
    data = previz.load_project(env)  # 能通过校验、能读回
    cams = [e for e in data["entities"] if e["kind"] == "camera"]
    assert len(cams) == 3  # 每镜一台摄影机
    assert data["cuts"][0]["time"] == 0
    times = [c["time"] for c in data["cuts"]]
    assert times == sorted(set(times))  # 严格递增
    assert data["duration"] == pytest.approx(8.0)


def test_generate_notes_mapping(env):
    previz_gen.generate_from_episode(7, out_path=env)
    data = previz.load_project(env)
    notes = data["production"]["notes"]
    assert len(notes) == 3
    assert notes[0]["dialogue"] == "对白1"
    assert notes[0]["story"] == "描述1"
    assert notes[0]["emotion"] == "紧张"
    actor_ids = {e["id"] for e in data["entities"] if e["kind"] == "actor"}
    assert notes[0]["actorId"] in actor_ids  # 镜1 绑定角色11 → 某 actor


def test_generate_actor_gender_guess(env):
    previz_gen.generate_from_episode(7, out_path=env)
    data = previz.load_project(env)
    actors = {e["name"]: e for e in data["entities"] if e["kind"] == "actor"}
    assert actors["林小雨"]["asset"] == "woman"
    assert actors["张探长"]["asset"] == "person"
    assert actors["林小雨"]["height"] == 1.65


def test_generate_prop_keyword_mapping(env):
    previz_gen.generate_from_episode(7, out_path=env)
    data = previz.load_project(env)
    by_name = {e["name"]: e for e in data["entities"] if e["kind"] == "prop"}
    assert by_name["双人床"]["asset"] == "bed"
    assert by_name["餐桌"]["asset"] == "table"  # specific 优先于「桌」
    assert "水晶球" not in by_name  # 映射不上的不硬造


def test_generate_camera_distance_by_shot_type(env):
    previz_gen.generate_from_episode(7, out_path=env)
    data = previz.load_project(env)
    cams = {c["name"]: c for c in data["entities"] if c["kind"] == "camera"}
    close = cams["镜1"]  # 特写 → 近距 + 长焦
    wide = cams["镜2"]   # 全景 → 远距 + 广角
    assert close["camera"]["focal"] == 50 and wide["camera"]["focal"] == 20
    assert abs(close["position"][0]) < abs(wide["position"][0])
    assert close["path"] is not None   # 推 → 摄影机路径
    assert wide["path"] is not None    # 摇 → 摄影机路径
    assert cams["镜3"]["path"] is None  # 固定 → 无路径


def test_generate_missing_episode(monkeypatch, tmp_path):
    _install_fake_db(monkeypatch, ep=None, shots=[], chars=[], props=[], sb_chars={})
    with pytest.raises(RuntimeError, match="剧集不存在"):
        previz_gen.generate_from_episode(999, out_path=tmp_path / "x.json")


def test_generate_no_storyboards(monkeypatch, tmp_path):
    _install_fake_db(monkeypatch, ep={"id": 1, "title": "t", "episode_number": 1},
                     shots=[], chars=[], props=[], sb_chars={})
    with pytest.raises(RuntimeError, match="分镜"):
        previz_gen.generate_from_episode(1, out_path=tmp_path / "x.json")


def test_generate_without_characters(monkeypatch, tmp_path):
    ep = {"id": 2, "title": "空城", "episode_number": 1}
    _install_fake_db(monkeypatch, ep=ep, shots=[_shot(9, 1)], chars=[], props=[],
                     sb_chars={})
    out = tmp_path / "x.json"
    result = previz_gen.generate_from_episode(2, out_path=out)
    assert result["actors"] == 0
    data = previz.load_project(out)
    cams = [e for e in data["entities"] if e["kind"] == "camera"]
    assert cams[0]["camera"]["mode"] == "free"  # 无主体 → 自由机位
