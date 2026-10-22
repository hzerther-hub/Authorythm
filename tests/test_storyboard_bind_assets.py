# -*- coding: utf-8 -*-
"""分镜资产绑定(_bind_assets)的回归护栏。

三个真实缺陷(2026-10-21 审查发现):
1. `prop_by_id` 实际是 **id → 名字** 映射,却被当 name→id 传给
   `_refs_to_names` → 模型给 `props: ["扇子"]`(名字形态)时永远查不到 id,
   **道具绑不上分镜**(id 形态 `prop_ids: [3]` 反而正常,更隐蔽)。
2. 「正文里出现 @名字 也算绑定」这段兜底被误挪进 `_refs_to_names` 的
   `return out` **之后** —— 永远不执行的死代码,兜底功能从来没生效过。
3. 逐条 `db.ex` 每条都 commit 一次,一集几十镜 = 几百次 fsync。

测试绝不碰真实库。
"""
from __future__ import annotations

import pytest


class _FakeDB:
    """记录所有写入,按 SQL 里的表名分类。"""

    def __init__(self, chars=None, props=None):
        # chars/props: [{"id": int, "name": str}]
        self.chars = chars or []
        self.props = props or []
        self.sb_char: list[tuple] = []      # (sb_id, cid, vid)
        self.sb_prop: list[tuple] = []      # (sb_id, pid)
        self.ep_char: list[tuple] = []
        self.ep_prop: list[tuple] = []
        self.commits = 0

    # ── 写 ──
    def ex(self, sql, args=()):
        self.commits += 1
        self._record(sql, args)
        return 1

    def exmany(self, sql, rows):
        self.commits += 1
        for r in rows:
            self._record(sql, r)

    def _record(self, sql, args):
        if "storyboard_characters" in sql:
            self.sb_char.append(tuple(args))
        elif "storyboard_props" in sql:
            self.sb_prop.append(tuple(args))
        elif "episode_characters" in sql:
            self.ep_char.append(tuple(args))
        elif "episode_props" in sql:
            self.ep_prop.append(tuple(args))

    # ── 读 ──
    def q(self, sql, args=()):
        if "FROM characters" in sql:
            ids = set(args or ())
            return [r for r in self.chars if r["id"] in ids]
        if "FROM props" in sql:
            ids = set(args or ())
            return [r for r in self.props if r["id"] in ids]
        return []

    def q1(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def now(self):
        return "2026-10-21T00:00:00Z"

    def jload(self, s, default=None):
        return default or {}


@pytest.fixture()
def sb_env(monkeypatch):
    from app.pipeline import storyboard as sb
    fake = _FakeDB(chars=[{"id": 1, "name": "叶尘"}, {"id": 2, "name": "苏九"}],
                   props=[{"id": 7, "name": "青铜戒"}, {"id": 8, "name": "长刀"}])
    monkeypatch.setattr(sb, "db", fake)
    return sb, fake


def _bind(sb, fake, panel, episode_id=42):
    """按真实调用方式调 _bind_assets。"""
    name_to_id = {r["name"]: r["id"] for r in fake.chars}
    prop_by_id = {r["id"]: r["name"] for r in fake.props}      # id → 名字(真实构造方式)
    prop_names = [r["name"] for r in fake.props]
    sb._bind_assets(100, panel, name_to_id, prop_by_id, prop_names,
                    "2026-10-21T00:00:00Z", episode_id)


def test_prop_by_name_binds_to_storyboard(sb_env):
    """模型给道具**名字**时必须绑上 —— 之前永远查不到 id(道具整批丢)。"""
    sb, fake = sb_env
    _bind(sb, fake, {"props": ["青铜戒"]})
    assert fake.sb_prop == [(100, 7)], f"道具没绑上: {fake.sb_prop}"
    assert fake.ep_prop == [(42, 7)], f"本集道具关联没补: {fake.ep_prop}"


def test_prop_by_id_still_binds(sb_env):
    """id 形态(prop_ids)不能被改坏。"""
    sb, fake = sb_env
    _bind(sb, fake, {"prop_ids": [8]})
    assert fake.sb_prop == [(100, 8)]


def test_character_by_name_and_id_both_bind(sb_env):
    """角色:名字形态与 id 形态都要绑上。"""
    sb, fake = sb_env
    _bind(sb, fake, {"characters": ["叶尘"], "char_ids": [2]})
    got = sorted(c[1] for c in fake.sb_char)
    assert got == [1, 2], f"角色绑定不全: {fake.sb_char}"
    # variant_id 保留在 3 列形态里
    assert all(len(c) == 3 for c in fake.sb_char)


def test_at_name_in_content_fallback_works(sb_env):
    """兜底:正文里出现 @名字 但模型没给数组时,也要绑上(这段曾是死代码)。"""
    sb, fake = sb_env
    _bind(sb, fake, {"content": "@叶尘 掏出 @青铜戒,@苏九 在旁看着"})
    char_ids = {c[1] for c in fake.sb_char}
    prop_ids = {p[1] for p in fake.sb_prop}
    assert char_ids == {1, 2}, f"正文里的 @角色 没绑上: {fake.sb_char}"
    assert prop_ids == {7}, f"正文里的 @青铜戒 没绑上: {fake.sb_prop}"


def test_fallback_does_not_bind_unmentioned_assets(sb_env):
    """兜底不能把没提到的资产也绑上(否则分镜挂满无关角色)。"""
    sb, fake = sb_env
    _bind(sb, fake, {"content": "@叶尘 独自赶路"})
    char_ids = {c[1] for c in fake.sb_char}
    prop_ids = {p[1] for p in fake.sb_prop}
    assert char_ids == {1}, f"绑了没提到的角色: {fake.sb_char}"
    assert prop_ids == set(), f"绑了没提到的道具: {fake.sb_prop}"


def test_fallback_needs_at_prefix(sb_env):
    """正文里只是提到名字(没有 @)不算引用 —— 不绑。"""
    sb, fake = sb_env
    _bind(sb, fake, {"content": "叶尘和苏九在青铜戒旁说话"})
    assert fake.sb_char == []
    assert fake.sb_prop == []


def test_batch_insert_uses_single_commit(sb_env):
    """多个角色/道具应该批量写(一次 commit),不是每条一次。"""
    sb, fake = sb_env
    _bind(sb, fake, {"characters": ["叶尘", "苏九"], "props": ["青铜戒", "长刀"]})
    # 2 角色 × (分镜 + 本集) + 2 道具 × (分镜 + 本集) = 4 次批量 + 兜底 0 次
    assert fake.commits <= 6, f"commit 次数过多({fake.commits}),批量写没生效"


def test_props_fallback_no_keyerror(sb_env):
    """兜底里按名字取 id 不能 KeyError(旧死代码用的是 prop_by_id[name])。"""
    sb, fake = sb_env
    # prop_names 里有名字,但 prop_by_id 反查不到 —— 不该炸
    name_to_id = {r["name"]: r["id"] for r in fake.chars}
    sb._bind_assets(100, {"content": "@青铜戒 在手"}, name_to_id,
                    {999: "青铜戒"}, ["青铜戒"], "ts", 42)
    assert fake.sb_prop == [(100, 999)]
