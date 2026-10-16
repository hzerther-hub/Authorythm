# -*- coding: utf-8 -*-
"""模型下拉必须列出配置里的**每一个**模型,并标注多模态能力。

起因:设置页的模型标签里明明列着 deepseek-v4-pro / deepseek-flash、
agnes-image 三个型号、minimax 五个型号,但顶栏下拉一条配置只显示默认模型
(`addItem(cfg["model"], cfg["id"])`),其余全选不到 —— 用户看得见却用不了。
"""
from __future__ import annotations

import json

from app.ai import registry
from app.core import db


def _make_cfg(cid: int, provider: str, default: str, models: list[str]) -> None:
    db.ex("INSERT OR REPLACE INTO ai_service_configs "
          "(id, service_type, provider, model, models, base_url, api_key, "
          " is_active, priority, created_at, updated_at) "
          "VALUES (?,?,?,?,?,?,?,1,0,?,?)",
          (cid, "text", provider, default, json.dumps(models),
           "https://example.invalid/v1", "k", db.now(), db.now()))


def test_every_model_gets_its_own_entry():
    """一条配置的每个模型各出一项,不是只出默认那个。"""
    _make_cfg(95001, "testprov", "testprov-a", ["testprov-a", "testprov-b", "testprov-c"])
    ents = registry.model_entries("text")
    mine = [e for e in ents if e["config_id"] == 95001]
    assert len(mine) == 3, f"只列出了 {len(mine)} 项,应为 3"
    assert [e["model"] for e in mine] == ["testprov-a", "testprov-b", "testprov-c"]
    assert sum(1 for e in mine if e["is_default"]) == 1, "默认标记必须只有一个"
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (95001,))


def test_entries_share_config_id():
    """同一条配置的多个模型共用 config_id —— 调用链只认 config_id。"""
    _make_cfg(95002, "testprov", "testprov-a", ["testprov-a", "testprov-b"])
    mine = [e for e in registry.model_entries("text") if e["config_id"] == 95002]
    assert {e["config_id"] for e in mine} == {95002}
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (95002,))


def test_label_disambiguates_provider_when_multiple():
    """同配置多模型时 label 带 provider 前缀,免得看不出是哪家的名字。"""
    _make_cfg(95003, "testprov", "shared-name", ["shared-name", "shared-name-2"])
    mine = [e for e in registry.model_entries("text") if e["config_id"] == 95003]
    assert all("testprov" in e["label"] for e in mine), \
        f"多模型时 label 未加 provider 前缀:{[e['label'] for e in mine]}"
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (95003,))


def test_single_model_label_has_no_prefix():
    """只有一个模型时不加前缀,保持顶栏紧凑。"""
    _make_cfg(95004, "solo", "solo-model", ["solo-model"])
    mine = [e for e in registry.model_entries("text") if e["config_id"] == 95004]
    assert mine[0]["label"] == "solo-model"
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (95004,))


def test_default_inserted_when_missing_from_models():
    """models 列表漏了默认模型时以 model 列为准补进去。"""
    _make_cfg(95005, "testprov", "the-default", ["other-1"])
    mine = [e for e in registry.model_entries("text") if e["config_id"] == 95005]
    models = [e["model"] for e in mine]
    assert "the-default" in models, "默认模型没出现在下拉里"
    assert models.index("the-default") == 0
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (95005,))


def test_broken_models_json_does_not_crash():
    """models 列是坏 JSON 时退回只显示默认模型,不抛异常。"""
    db.ex("INSERT OR REPLACE INTO ai_service_configs "
          "(id, service_type, provider, model, models, base_url, api_key, "
          " is_active, priority, created_at, updated_at) "
          "VALUES (?,?,?,?,?,?,?,1,0,?,?)",
          (95006, "text", "badprov", "bad-model", "{not json", "https://x/v1", "k",
           db.now(), db.now()))
    mine = [e for e in registry.model_entries("text") if e["config_id"] == 95006]
    assert len(mine) == 1 and mine[0]["model"] == "bad-model"
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (95006,))


# ── select_model:把选择写回配置的 model 列 ────────────────────────

def test_select_model_switches_within_list():
    _make_cfg(95007, "testprov", "testprov-a", ["testprov-a", "testprov-b"])
    assert registry.select_model(95007, "testprov-b") is True
    row = db.q1("SELECT model FROM ai_service_configs WHERE id=?", (95007,))
    assert row["model"] == "testprov-b"
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (95007,))


def test_select_model_rejects_outside_list():
    """不允许借此把配置改成 models 列表外的模型。"""
    _make_cfg(95008, "testprov", "testprov-a", ["testprov-a", "testprov-b"])
    assert registry.select_model(95008, "some-other-model") is False
    row = db.q1("SELECT model FROM ai_service_configs WHERE id=?", (95008,))
    assert row["model"] == "testprov-a", "被改成了列表外的模型"
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (95008,))


def test_select_model_noop_returns_false():
    _make_cfg(95009, "testprov", "testprov-a", ["testprov-a"])
    assert registry.select_model(95009, "testprov-a") is False
    assert registry.select_model(99999, "whatever") is False
    assert registry.select_model(95009, "") is False
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (95009,))


# ── 多模态标注 ────────────────────────────────────────────────────

def test_minimax_is_vision_model():
    """MiniMax-M 系列实测能读图 —— video_clone 的读图调用一直发它。

    漏标的后果:本该读图的功能静默拿到凭空编的描述,一路走到生图才暴露。
    """
    assert registry.is_vision_model("MiniMax-M3")
    assert registry.is_vision_model("MiniMax-M2.7")
    assert registry.is_vision_model("minimax-m2")


def test_deepseek_flash_is_text_only():
    assert not registry.is_vision_model("deepseek-flash")
    assert not registry.is_vision_model("deepseek-v4-pro")


def test_empty_model_is_not_vision():
    assert not registry.is_vision_model("")
    assert not registry.is_vision_model(None)


def test_vision_marker_not_emoji():
    """多模态标记必须是文字 —— Windows 应用字体没有 emoji 字形,会渲染成空白。

    见 AGENTS.md:实测 emoji 图标在这个项目里颜色数=1(纯空白)。
    """
    _make_cfg(95010, "minimax", "MiniMax-M3", ["MiniMax-M3"])
    ent = next(e for e in registry.model_entries("text") if e["config_id"] == 95010)
    assert ent["vision"] is True
    assert "多模态" in ent["label"]
    assert not any(ord(ch) > 0x1F000 for ch in ent["label"]), \
        f"label 里混进了 emoji:{ent['label']!r}"
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (95010,))
