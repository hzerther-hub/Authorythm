# -*- coding: utf-8 -*-
"""导演台预演工程数据模型:校验、读写、示例工程。

previz 模块不碰数据库,测试无需打桩;关键是守住「与原版 model.ts 的约束一致」
—— 校验比原版松会放进坏工程,比原版严会拒绝原版接受的合法工程。
"""
from __future__ import annotations

import json

import pytest

from app.pipeline import previz

# ---------------------------------------------------------------- 构建辅助

def test_new_entity_actor_default_color():
    a = previz.new_entity("actor", "person", "甲")
    assert a.color == previz.COLORS[0]
    assert a.camera is None
    assert previz._COLOR_RE.match(a.color)


def test_new_camera_entity_has_camera_config():
    c = previz.new_entity("camera", "camera", "机位 A")
    assert c.camera is not None
    assert c.camera.focal == 28
    assert c.camera.mode == "free"


def test_new_entity_bad_kind():
    with pytest.raises(previz.PrevizError):
        previz.new_entity("dragon", "person", "龙")


def test_new_clip_unknown_action():
    with pytest.raises(previz.PrevizError):
        previz.new_clip("fly", 0, 1)
    clip = previz.new_clip("walk", 0, 2)
    assert clip.speed == 1.0 and clip.id


def test_add_path_ordered_points():
    e = previz.new_entity("actor", "person", "甲")
    path = previz.add_path(e, [(1, (0, 0, 0)), (3, (1, 0, 1))])
    assert [w.time for w in path.points] == [1, 3]
    assert e.path is path


# ---------------------------------------------------------------- 数值

def test_aspect_and_frames():
    assert previz.aspect_number("9:16") == 9 / 16
    assert previz.get_frame_count(0, 15, 24) == 360
    assert previz.get_frame_count(5, 5, 24) == 0


# ---------------------------------------------------------------- 校验

def _demo_dict():
    return json.loads(previz.project_to_json(previz.demo_project()))


def test_demo_project_validates_and_serializes():
    data = _demo_dict()
    previz.validate_project(data)
    assert data["format"] == "director-desk"
    assert data["cuts"][0]["time"] == 0
    cams = [e for e in data["entities"] if e["kind"] == "camera"]
    assert len(cams) >= 1
    assert {c["cameraId"] for c in data["cuts"]} <= {e["id"] for e in cams}


def test_validate_rejects_wrong_format():
    data = _demo_dict()
    data["format"] = "other"
    with pytest.raises(previz.PrevizError, match="格式或版本"):
        previz.validate_project(data)


def test_validate_rejects_bad_fps_and_aspect():
    data = _demo_dict()
    data["fps"] = 25
    with pytest.raises(previz.PrevizError, match="帧率"):
        previz.validate_project(data)
    data = _demo_dict()
    data["aspect"] = "7:5"
    with pytest.raises(previz.PrevizError, match="画幅"):
        previz.validate_project(data)


def test_validate_rejects_room_out_of_range():
    data = _demo_dict()
    data["room"]["width"] = 1.0
    with pytest.raises(previz.PrevizError, match="房间尺寸"):
        previz.validate_project(data)


def test_validate_rejects_duplicate_entity_id():
    data = _demo_dict()
    data["entities"][1]["id"] = data["entities"][0]["id"]
    with pytest.raises(previz.PrevizError, match="标识"):
        previz.validate_project(data)


def test_validate_rejects_no_camera():
    data = _demo_dict()
    data["entities"] = [e for e in data["entities"] if e["kind"] != "camera"]
    with pytest.raises(previz.PrevizError, match="摄影机"):
        previz.validate_project(data)


def test_validate_rejects_camera_config_on_actor():
    data = _demo_dict()
    next(e for e in data["entities"] if e["kind"] == "actor")["camera"] = {
        "aim": "target", "focal": 28, "target": [0, 1, 0], "targetId": "",
        "targetHeight": 1.2, "mode": "free", "offset": [0, 1.6, -1.8],
        "inheritRotation": True, "hideWalls": []}
    with pytest.raises(previz.PrevizError, match="摄影机配置"):
        previz.validate_project(data)


def test_validate_rejects_focal_out_of_range():
    data = _demo_dict()
    next(e for e in data["entities"] if e["kind"] == "camera")["camera"]["focal"] = 500
    with pytest.raises(previz.PrevizError, match="焦距"):
        previz.validate_project(data)


def test_validate_rejects_descending_path_times():
    data = _demo_dict()
    path = next(e for e in data["entities"] if e.get("path"))
    path["path"]["points"] = list(reversed(path["path"]["points"]))
    with pytest.raises(previz.PrevizError, match="递增"):
        previz.validate_project(data)


def test_validate_rejects_overlapping_clips():
    data = _demo_dict()
    actor = next(e for e in data["entities"] if e["kind"] == "actor" and len(e["clips"]) >= 2)
    actor["clips"][1]["start"] = actor["clips"][0]["end"] - 0.5
    with pytest.raises(previz.PrevizError, match="重叠"):
        previz.validate_project(data)


def test_validate_rejects_cuts_not_from_zero():
    data = _demo_dict()
    data["cuts"][0]["time"] = 1
    with pytest.raises(previz.PrevizError, match="从零秒"):
        previz.validate_project(data)


def test_validate_rejects_cut_dangling_camera():
    data = _demo_dict()
    data["cuts"][1]["cameraId"] = "no-such-camera"
    with pytest.raises(previz.PrevizError, match="机位"):
        previz.validate_project(data)


def test_validate_rejects_bad_reference_image():
    data = _demo_dict()
    data["references"] = [{"id": "r1", "name": "参考", "data": "http://example.com/a.png"}]
    with pytest.raises(previz.PrevizError, match="参考图"):
        previz.validate_project(data)


def test_validate_rejects_note_with_unknown_actor():
    data = _demo_dict()
    data["production"] = {"fixedPrompt": "", "sceneReferenceIds": [],
                          "notes": [{"id": "n1", "start": 0, "end": 1, "actorId": "ghost",
                                     "story": "", "emotion": "", "dialogue": "", "action": ""}]}
    with pytest.raises(previz.PrevizError, match="角色不存在"):
        previz.validate_project(data)


# ---------------------------------------------------------------- 读写

def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "proj" / "demo.directordesk.json"
    project = previz.demo_project()
    previz.save_project(project, p)
    loaded = previz.load_project(p)
    assert loaded["name"] == project.name
    assert len(loaded["entities"]) == len(project.entities)
    # 保留中文可读,不转 \uXXXX
    assert "人物 A" in p.read_text(encoding="utf-8")


def test_load_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{oops", encoding="utf-8")
    with pytest.raises(previz.PrevizError, match="JSON"):
        previz.load_project(p)


def test_load_rejects_invalid_project(tmp_path):
    p = tmp_path / "bad2.json"
    p.write_text(json.dumps({"format": "director-desk"}), encoding="utf-8")
    with pytest.raises(previz.PrevizError):
        previz.load_project(p)
