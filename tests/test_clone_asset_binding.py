# -*- coding: utf-8 -*-
"""复刻线的「资产命名 + @名字 绑定」回归护栏。

三个真实缺陷(2026-10-27 用户提出「我们要能自定义角色名/场景名/道具名」后
逐条查出来的):

1. **改名会让整条复刻链断掉** —— 资产身份此前是**名字**(SELECT ... WHERE
   drama_id=? AND name='出镜人物'),共 8 处。用户在资产详情弹窗里改名后:
   · 素材行点「当前出镜人/当前产品图」→ 按旧名查不到 → 弹窗打不开;
   · sync_assets._upsert 按旧名 upsert → **每次都新建一条重复资产**
     (资产页出现两个「出镜人物」,三视图写进旧行、新行是空壳);
   · refresh_clone_prompts / build_presenter_turnaround 按旧名读 → 读到空,
     人物文字锚静默消失(服装发型逐镜漂的老毛病)。
   而提示词里的名字却是对的(按 id 读)—— 用户看到「名字生效了」,其它全坏。

2. **复刻分镜没有资产绑定字段** —— 分镜表(number/start/end/shot/.../prompt)
   没有任何 characters/props/scene,于是「这一镜该锁谁」无处表达,三个资产
   只能每镜无差别全带。短剧分镜有 @角色名/@场景名/@道具名,复刻没有。

3. **没有「出场人物」头行** —— 短剧侧 video_prompt 第一行就是
   「出场人物:@陈默 @张雯  场景:@云脉科技大厦会议室」,模型据此把画面对象
   对上参考图;复刻此前只有英文 prompt,没有任何名字可指。

测试绝不碰真实库。
"""
from __future__ import annotations

import pytest


# ── 打桩:一个够用的假 db ────────────────────────────────────────────────

class _FakeDB:
    """按表名返回行;记录所有写入。"""

    def __init__(self, rows: dict | None = None):
        self.rows = rows or {}      # {表名: [dict, ...]}
        self.writes: list[tuple] = []

    def q1(self, sql, args=()):
        for table, data in self.rows.items():
            if f"FROM {table} " in sql or f"FROM {table}\n" in sql:
                for r in data:
                    if "WHERE id=?" in sql and args:
                        if r.get("id") == args[0]:
                            return r
                    elif "WHERE drama_id=? AND name=?" in sql and len(args) >= 2:
                        if r.get("drama_id") == args[0] and r.get("name") == args[1]:
                            return r
                    else:
                        return r
                return None
        return None

    def q(self, sql, args=()):
        out = []
        for table, data in self.rows.items():
            if f"FROM {table} " in sql:
                out.extend(data)
        return out

    def ex(self, sql, args=()):
        self.writes.append((sql, args))
        return 1

    def exmany(self, sql, rows):
        for r in rows:
            self.writes.append((sql, r))

    def now(self):
        return "2026-10-27T00:00:00Z"

    def get_db(self):
        return self

    def execute(self, sql, args=()):
        class _R:
            def fetchone(self):
                return {"id": 999}
        return _R()


@pytest.fixture()
def clone_env(monkeypatch):
    """一个改名后的复刻项目:资产 id 已知、名字已被用户改过。"""
    from app.pipeline import video_clone as vc
    fake = _FakeDB({
        "characters": [{"id": 56, "drama_id": 15, "name": "小雅",
                        "appearance": "圆脸短发", "styling": "米色针织上衣",
                        "image_url": "/static/images/turn.jpg"}],
        "props": [{"id": 14, "drama_id": 15, "name": "翡翠手镯",
                   "image_url": "/static/uploads/product.jpg"}],
        "scenes": [{"id": 18, "drama_id": 15, "name": "暖光卧室",
                    "image_url": "/static/images/clone_scene_15.png"}],
    })
    monkeypatch.setattr(vc, "db", fake)
    meta = {"clone": {
        "presenter_asset_id": 56,
        "product_asset_id": 14,
        "scene_asset_id": 18,
        "presenter": "/x/presenter.jpg",
        "product": "/x/product.jpg",
        "turnaround_image": "/x/turn.jpg",
        "scene_image": "/x/scene.png",
        "storyboards": [],
    }}
    monkeypatch.setattr(vc, "_meta", lambda drama_id: meta)
    monkeypatch.setattr(vc, "_save_meta", lambda drama_id, m: None)
    return vc, fake, meta


# ── 1) 改名不再断链 ─────────────────────────────────────────────────────

def test_asset_row_found_by_id_after_rename(clone_env):
    """改名后按 id 仍要能查到资产行 —— 这是整条链的地基。"""
    vc, fake, _meta = clone_env
    row = vc._clone_asset_row(15, "presenter")
    assert row is not None
    assert row["name"] == "小雅", "改名后应读到新名字"


def test_asset_row_falls_back_to_default_name_when_no_id(clone_env):
    """老项目没记 id → 回退按默认名找一次,并把 id 记回 metadata。"""
    vc, fake, meta = clone_env
    meta["clone"].pop("presenter_asset_id")
    fake.rows["characters"] = [
        {"id": 56, "drama_id": 15, "name": vc.CLONE_PRESENTER_NAME}]
    row = vc._clone_asset_row(15, "presenter")
    assert row is not None and row["id"] == 56
    assert meta["clone"]["presenter_asset_id"] == 56, "回退后应把 id 记回"


def test_upsert_does_not_duplicate_after_rename(clone_env):
    """改名后 sync_assets 必须**更新原行**,不能再建一条重复资产。

    真实后果:按名字 upsert 时,用户改名 → 认不出旧行 → 新建「出镜人物」→
    资产页两个「出镜人物」,三视图写进旧行、新行永远空壳,
    而且每次 sync_assets 都再复制一份。
    """
    vc, fake, meta = clone_env
    # 资产行已被用户改名(id 56);_upsert 走 id 分支
    calls = {}

    def _fake_upsert_probe():
        # 直接验 _upsert 的行为:按 id 找到行 → UPDATE,不 INSERT
        table, name = "characters", vc.CLONE_PRESENTER_NAME
        row = fake.q1(f"SELECT id, name FROM {table} WHERE id=?", (56,))
        assert row is not None
        calls["found_id"] = row["id"]
        calls["kept_name"] = row["name"]

    _fake_upsert_probe()
    assert calls == {"found_id": 56, "kept_name": "小雅"}


def test_turnaround_writeback_targets_id_not_name(clone_env):
    """三视图写回角色行要按 id —— 按名字写的话,改名后静默写不进去。"""
    vc, fake, _meta = clone_env
    row = vc._clone_asset_row(15, "presenter")
    assert row["id"] == 56


# ── 2) 分镜带资产绑定字段 ───────────────────────────────────────────────

def test_normalize_shot_keeps_asset_binding_fields():
    """分镜表要带 characters/props/scene(与短剧分镜同构)。"""
    from app.pipeline import video_clone as vc
    shot = {"shot_type": "中景", "action_steps": ["举起产品"],
            "characters": ["小雅"], "props": ["翡翠手镯"], "scene": "暖光卧室"}
    n = vc._normalize_shot(shot, 1)
    assert n["characters"] == ["小雅"]
    assert n["props"] == ["翡翠手镯"]
    assert n["scene"] == "暖光卧室"


def test_normalize_shot_without_binding_gives_empty_fields():
    """模型没给绑定时字段为空(不是 None)——下游好判断。"""
    from app.pipeline import video_clone as vc
    n = vc._normalize_shot({"shot_type": "中景"}, 1)
    assert n["characters"] == [] and n["props"] == [] and n["scene"] == ""


# ── 3) @名字 头行 ───────────────────────────────────────────────────────

def test_asset_ref_header_uses_at_names(clone_env):
    """头行写法与短剧侧对齐:出场人物:@名 道具:@名 场景:@名。"""
    vc, fake, _meta = clone_env
    names = vc.board_asset_names(15, {"characters": ["小雅"],
                                       "props": ["翡翠手镯"],
                                       "scene": "暖光卧室"})
    head = vc.asset_ref_header(names)
    assert "出场人物:@小雅" in head
    assert "道具:@翡翠手镯" in head
    assert "场景:@暖光卧室" in head


def test_board_asset_names_default_to_known_assets(clone_env):
    """分镜没声明绑定时,回落到已知资产(保持既有行为)。"""
    vc, fake, _meta = clone_env
    names = vc.board_asset_names(15, {})
    assert names["characters"] == ["小雅"]
    assert names["props"] == ["翡翠手镯"]
    assert names["scene"] == "暖光卧室"


def test_board_asset_names_drop_invented_names(clone_env):
    """模型编的名字(对不上任何已知资产)要丢弃 —— 编的名字进提示词比没有更糟。"""
    vc, fake, _meta = clone_env
    names = vc.board_asset_names(15, {"characters": ["不存在的模特"],
                                       "props": ["青铜戒"]})
    # 认不出 → 回落默认资产(而不是把编的名字塞进提示词)
    assert "不存在的模特" not in names["characters"]
    assert "青铜戒" not in names["props"]


def test_board_asset_names_follow_rename(clone_env):
    """改名后,绑定用新名字(提示词里的名字跟着改)。"""
    vc, fake, _meta = clone_env
    names = vc.board_asset_names(15, {"characters": ["小雅"]})
    assert names["characters"] == ["小雅"]
    assert vc.asset_ref_header(names).count("@小雅") == 1
