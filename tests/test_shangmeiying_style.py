# -*- coding: utf-8 -*-
"""上美影五风格预设(对标 liangdabiao/smy-seedance-storyboard 风格指南)回归。

锁住的不变量:
- 五条种子(value/排序/适用 work_type)齐且幂等;
- prompt 走源仓库 **v3 视频行配方**为基底 —— 本项目同一份 style 前缀既进生图
  又进视频提示词,源仓库明确警告图片块(§2.1 咆哮体「绝对不要阴影渐变」)与
  视频行配方互相套用会翻车:绝对化「无阴影无渐变」在视频端连手绘肌理一起杀掉。
  所以五个 prompt **不得出现**「绝对不要阴影」「NO SHADING」「NO GRADIENTS」
  这类绝对化禁令;平涂靠正向词「水粉平涂上色」锚定,否定词只打真敌
  (3D/写实/体积光);
- 色盘主四色(青瓷绿/朱砂红/鎏金/墨黑)逐字进前缀 —— 防跨镜跑色的主抓手;
- 子风格只换媒介质感短语,共享骨架逐字一致;
- MTV 项目(新项目弹窗的下拉)能选到它们(work_type 含 mtv)。
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.core import db, config

SMY_VALUES = ("shangmeiying", "smy_dunhuang", "smy_ink_wash", "smy_paper_cut",
              "smy_blue_ink")

# 源仓库 §2.3 子风格表:媒介质感短语(其余骨架逐字保留)
MEDIA_PHRASES = {
    "shangmeiying": "手绘墨线轮廓，水粉平涂上色、保留颜料笔触与手工感",
    "smy_dunhuang": "陈年壁画矿物重彩，斑驳壁画肌理与轻微颜料过渡",
    "smy_ink_wash": "墨色浓淡晕染与淡彩过渡",
    "smy_paper_cut": "分层剪纸剪影，对称装饰纹样，实色平涂刻线边缘",
    "smy_blue_ink": "淡雅磨砂平涂，强线条感，小面积怪色点缀",
}


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "smy.sqlite3")
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


def test_five_shangmeiying_presets_seeded(tmp_db):
    for i, value in enumerate(SMY_VALUES):
        r = db.q1("SELECT * FROM style_presets WHERE value=?", (value,))
        assert r is not None, f"缺种子 {value}"
        assert r["style_type"] == "visual"
        assert r["work_type"] == "drama,novel,comic,mtv"
        assert r["sort_order"] == 10 + i
        assert r["is_active"] == 1
    assert db.q1("SELECT name FROM style_presets WHERE value='shangmeiying'")["name"] \
        == "上美影手绘"


def test_seed_idempotent(tmp_db):
    db.init_db()
    db.init_db()
    n = db.q1("SELECT COUNT(*) AS n FROM style_presets WHERE value IN "
              "('shangmeiying','smy_dunhuang','smy_ink_wash','smy_paper_cut','smy_blue_ink')")["n"]
    assert n == 5


def test_prompts_follow_v3_recipe_not_absolute_bans(tmp_db):
    """配方纪律:正向锚平涂、否定词只打真敌,严禁绝对化禁令(见模块 docstring)。"""
    # 每个风格的「平涂/重彩正向锚」—— 敦煌与水墨淡彩的媒介短语按源仓库子风格表
    # 本就不含「平涂」二字(重彩/淡彩即锚),按各自的媒介词断言。
    flat_anchors = {
        "shangmeiying": "水粉平涂上色",
        "smy_dunhuang": "陈年壁画矿物重彩",
        "smy_ink_wash": "墨色浓淡晕染与淡彩过渡",
        "smy_paper_cut": "实色平涂刻线边缘",
        "smy_blue_ink": "淡雅磨砂平涂",
    }
    for value in SMY_VALUES:
        p = db.q1("SELECT prompt FROM style_presets WHERE value=?", (value,))["prompt"]
        assert "上海美术电影制片厂经典手绘动画风格" in p, "品牌全称锚定(源仓库 v3 要点)"
        assert flat_anchors[value] in p, f"{value} 缺平涂/媒介正向锚"
        assert "不要3D渲染、不要写实感、不要体积光" in p, "否定词只打真敌(v3)"
        # 绝对化禁令会连手绘肌理一起杀掉(源仓库 §2.3 v3 修订原因),一个都不许有
        for banned in ("绝对不要阴影", "绝对不要渐变", "NO SHADING", "NO GRADIENTS",
                       "不要阴影、不要渐变"):
            assert banned not in p, f"{value} 混入了绝对化禁令:{banned}"
        # 色盘主四色逐字进前缀(防跨镜跑色的主抓手)
        for color in ("青瓷绿", "朱砂红", "鎏金", "墨黑"):
            assert color in p, f"{value} 缺主色 {color}"
        # 跨镜一致性句与其余预设同款
        assert "consistent character design across shots" in p


def test_substyles_differ_only_in_media_phrase(tmp_db):
    """子风格只换媒介质感短语,共享骨架逐字一致(源仓库子风格表)。"""
    prompts = {v: db.q1("SELECT prompt FROM style_presets WHERE value=?", (v,))["prompt"]
               for v in SMY_VALUES}
    for value, media in MEDIA_PHRASES.items():
        assert media in prompts[value], f"{value} 缺媒介短语:{media}"
    # 五条 prompt 的媒介短语互不相同(否则子风格没意义)
    assert len(set(prompts.values())) == 5


def test_shangmeiying_selectable_for_mtv_projects(tmp_db):
    """新项目弹窗的风格下拉按 work_type 过滤 —— MTV 项目要能选到上美影
    (源仓库的示例本就是故事 MV 形态)。"""
    from app.ui.new_project_dialog import style_choices
    values = [v for v, _name in style_choices("mtv")]
    for value in SMY_VALUES:
        assert value in values, f"MTV 风格下拉缺 {value}"


def test_style_prompt_passthrough(tmp_db):
    """db.style_prompt 按值取到上美影前缀(生图/出视频共用的那个入口)。"""
    p = db.style_prompt("shangmeiying", content_lang="zh")
    assert p.startswith("上海美术电影制片厂经典手绘动画风格")
    assert "青瓷绿" in p
