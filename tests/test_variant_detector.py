# -*- coding: utf-8 -*-
"""`variant_detector.ensure_variants_for_storyboard` 的关联表兜底路径回归。

bug 背景:`storyboard_characters` / `storyboard_scenes` / `storyboard_props` 这三张
「本镜关联」表没绑上东西时,代码兜底去读集级关联表
(`episode_characters` / `episode_scenes` / `episode_props`),但那三张表是**纯关联表,
只有 (episode_id, xxx_id) 两列、没有 `id` 列**,原实现却读 `r["id"]` → IndexError
("No item with that key")。

为什么一直没被发现:兜底路径只在「该镜没绑上角色/场景/道具」时才走。实测多数分镜
能按 location/name 匹配到场景并写进 storyboard_scenes,于是这条分支几乎踩不到;
一旦踩到,异常一路冒到 `split_storyboards` 包住整集的 try 里,后果是**整集**的
变体检测与情绪打标被静默跳过(用户只看到标签没打上,没有任何报错)。

**测试不许碰真实库**:这里只打桩 `db.q`,返回与真实关联表列名一致的 dict,
读错列名会直接 KeyError —— 正是这个 bug 的形态。
"""
from __future__ import annotations

from app.pipeline import variant_detector as vd


def _stub_junction_tables(monkeypatch, *, bound: bool) -> list[str]:
    """打桩 db.q:本镜关联表按 bound 决定有无行,集级关联表始终有行。

    返回一个记录被查过的表名的列表,供断言用。
    行数据刻意用 dict 且**只含关联表真实存在的列**(没有 "id"),
    于是「查了 xxx_id 却读 r["id"]」会当场 KeyError。
    """
    seen: list[str] = []
    rows = {
        "storyboard_characters": ([{"storyboard_id": 1, "character_id": 7}] if bound else []),
        "episode_characters": [{"episode_id": 56, "character_id": 7}],
        "storyboard_scenes": ([{"storyboard_id": 1, "scene_id": 13}] if bound else []),
        "episode_scenes": [{"episode_id": 56, "scene_id": 13}],
        "storyboard_props": ([{"storyboard_id": 1, "prop_id": 3}] if bound else []),
        "episode_props": [{"episode_id": 56, "prop_id": 3}],
    }

    def fake_q(sql, args=()):
        for table, data in rows.items():
            if f"FROM {table} " in sql:
                seen.append(table)
                return [dict(r) for r in data]
        return []

    monkeypatch.setattr(vd.db, "q", fake_q)
    # 变化检测与建变体都要读库/写库,这里与被测路径无关,全部打桩掉
    monkeypatch.setattr(vd, "detect_in_storyboard", lambda s: [])
    monkeypatch.setattr(vd, "detect_scene_changes", lambda s: [])
    monkeypatch.setattr(vd, "detect_prop_changes", lambda s: [])
    return seen


SB = {"id": 1, "episode_id": 56, "storyboard_number": 1,
      "content": "", "description": "", "video_prompt": ""}


def test_episode_level_fallback_reads_junction_key(monkeypatch):
    """该镜没绑角色/场景/道具 → 走集级兜底,读 xxx_id 而不是不存在的 id 列。"""
    seen = _stub_junction_tables(monkeypatch, bound=False)
    assert vd.ensure_variants_for_storyboard(dict(SB), drama_id=1) == []
    for table in ("episode_characters", "episode_scenes", "episode_props"):
        assert table in seen, f"该镜无绑定时应回退到 {table}"


def test_bound_rows_short_circuit_the_fallback(monkeypatch):
    """该镜已绑定时不该再去查集级关联表(多一次无用查询)。"""
    seen = _stub_junction_tables(monkeypatch, bound=True)
    assert vd.ensure_variants_for_storyboard(dict(SB), drama_id=1) == []
    assert not any(t.startswith("episode_") for t in seen), \
        f"已有本镜关联就不该回退,却查了: {[t for t in seen if t.startswith('episode_')]}"


def test_missing_episode_id_is_a_noop(monkeypatch):
    """没有 episode_id 的分镜直接返回,不查库。"""
    seen = _stub_junction_tables(monkeypatch, bound=False)
    assert vd.ensure_variants_for_storyboard({"id": 1}, drama_id=1) == []
    assert seen == []
