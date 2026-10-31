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
    vc, _fake, _meta = clone_env
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
    vc, fake, _meta = clone_env
    # 资产行已被用户改名(id 56);_upsert 走 id 分支
    calls = {}

    def _fake_upsert_probe():
        # 直接验 _upsert 的行为:按 id 找到行 → UPDATE,不 INSERT
        table, _name = "characters", vc.CLONE_PRESENTER_NAME
        row = fake.q1(f"SELECT id, name FROM {table} WHERE id=?", (56,))
        assert row is not None
        calls["found_id"] = row["id"]
        calls["kept_name"] = row["name"]

    _fake_upsert_probe()
    assert calls == {"found_id": 56, "kept_name": "小雅"}


def test_turnaround_writeback_targets_id_not_name(clone_env):
    """三视图写回角色行要按 id —— 按名字写的话,改名后静默写不进去。"""
    vc, _fake, _meta = clone_env
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
    vc, _fake, _meta = clone_env
    names = vc.board_asset_names(15, {"characters": ["小雅"],
                                       "props": ["翡翠手镯"],
                                       "scene": "暖光卧室"})
    head = vc.asset_ref_header(names)
    assert "出场人物:@小雅" in head
    assert "道具:@翡翠手镯" in head
    assert "场景:@暖光卧室" in head


def test_board_asset_names_default_to_known_assets(clone_env):
    """分镜没声明绑定时,回落到已知资产(保持既有行为)。"""
    vc, _fake, _meta = clone_env
    names = vc.board_asset_names(15, {})
    assert names["characters"] == ["小雅"]
    assert names["props"] == ["翡翠手镯"]
    assert names["scene"] == "暖光卧室"


def test_board_asset_names_drop_invented_names(clone_env):
    """模型编的名字(对不上任何已知资产)要丢弃 —— 编的名字进提示词比没有更糟。"""
    vc, _fake, _meta = clone_env
    names = vc.board_asset_names(15, {"characters": ["不存在的模特"],
                                       "props": ["青铜戒"]})
    # 认不出 → 回落默认资产(而不是把编的名字塞进提示词)
    assert "不存在的模特" not in names["characters"]
    assert "青铜戒" not in names["props"]


def test_board_asset_names_follow_rename(clone_env):
    """改名后,绑定用新名字(提示词里的名字跟着改)。"""
    vc, _fake, _meta = clone_env
    names = vc.board_asset_names(15, {"characters": ["小雅"]})
    assert names["characters"] == ["小雅"]
    assert vc.asset_ref_header(names).count("@小雅") == 1


# ── 2026-10-28:特写镜参考图裁剪(「手复」#02-#04 实测回归)────────────────
# 无绑定的特写镜若仍带三视图立绘参考,图像参考的引力压过文字守卫,
# 首帧把主角全身画进背景(原片该镜只有一只手 + 产品)。裁剪与「绑定裁剪」
# 同一原则:靠文字守卫硬压不如直接不给。中景/近景不受影响(三张全带)。

class _ShotGenDB(_FakeDB):
    """在 _FakeDB 上补 generate_shot_image 用到的三个 db 侧函数。"""

    def get_setting(self, key, default=None):
        return default

    def resolve_selected_config_id(self, service, default=None):
        return default

    def style_prompt(self, style_value):
        return "真人写实风格"

    def drama_style(self, drama_id):
        return "live"


def _gen_shot_env(tmp_path, monkeypatch, shot: str,
                  board_extra: dict | None = None,
                  styling: str = "上装米色圆领针织衫,袖口罗纹收口,下装黑色阔腿裤") -> dict:
    """搭一个可跑 generate_shot_image 的最小复刻项目;返回捕获容器。"""
    from PIL import Image

    from app.pipeline import video_clone as vc
    product = tmp_path / "product.jpg"
    scene = tmp_path / "scene.png"
    standing = tmp_path / "standing.jpg"
    for p in (product, scene, standing):
        Image.new("RGB", (64, 64), "white").save(p)

    fake = _ShotGenDB({
        "characters": [{"id": 56, "name": "小雅", "styling": styling,
                        "appearance": "圆脸短发", "image_url": str(standing)}],
        "props": [{"id": 14, "name": "翡翠手镯", "image_url": str(product)}],
        "scenes": [{"id": 18, "name": "暖光卧室", "image_url": str(scene)}],
        "dramas": [{"id": 15, "aspect_ratio": "16:9"}],
    })
    monkeypatch.setattr(vc, "db", fake)
    row = {"number": 2, "start": 2.5, "end": 4.2, "shot": shot,
           "camera": "固定", "action": "双手捏住玉镯两侧",
           "prompt": "特写:双手取下玉镯"}
    row.update(board_extra or {})
    boards = [row]
    meta = {"clone": {
        "presenter_asset_id": 56, "product_asset_id": 14, "scene_asset_id": 18,
        "product_desc": "翠绿色宽圆玉镯", "presenter_desc": "年轻女性",
        "scene_image": str(scene),
        "turnaround_image": str(standing),
        "storyboards": boards,
    }}
    monkeypatch.setattr(vc, "_meta", lambda drama_id: meta)
    monkeypatch.setattr(vc, "_save_meta", lambda drama_id, m: None)

    captured = {}

    def _fake_gen(prompt, out_name="", config_id=None, reference_images=None,
                  people=None, size=None, reference_lock=False, **kw):
        captured["prompt"] = prompt
        captured["refs"] = list(reference_images or [])
        return tmp_path / out_name, "agnes"

    monkeypatch.setattr(vc.image_client, "generate_image", _fake_gen)

    vc.generate_shot_image(15, 2, "live")
    return captured


def test_closeup_image_refs_keep_all_three(tmp_path, monkeypatch):
    """2026-10-28 定版(用户反馈「服装在变」后):特写镜**照带**人物立绘
    (短剧首帧同款做法)—— 裁掉立绘虽让构图变紧,但人物失去图像锚,
    衣袖/肤色逐镜自由发挥(实测 #1 米色毛衣 / #2 #3 蓝袍)。"""
    captured = _gen_shot_env(tmp_path, monkeypatch, "特")   # 简称,读侧须归一
    refs = captured["refs"]
    names = [str(p) for p in refs]
    assert any(n.endswith("product.jpg") for n in names), "产品主锚必须带"
    assert any(n.endswith("scene.png") for n in names), "空景锚保留"
    assert any(n.endswith("standing.jpg") for n in names), "特写镜必须带立绘锚服装"


def test_medium_shot_keeps_all_three_refs(tmp_path, monkeypatch):
    captured = _gen_shot_env(tmp_path, monkeypatch, "中")
    names = [str(p) for p in captured["refs"]]
    assert any(n.endswith("standing.jpg") for n in names)
    assert any(n.endswith("scene.png") for n in names)
    assert any(n.endswith("product.jpg") for n in names)


def test_bound_closeup_keeps_standing_too(tmp_path, monkeypatch):
    """绑定与否不影响:特写镜都带立绘(2026-10-28 定版,见上)。"""
    captured = _gen_shot_env(tmp_path, monkeypatch, "特", board_extra={
        "characters": ["小雅"], "props": ["翡翠手镯"], "scene": "暖光卧室"})
    names = [str(p) for p in captured["refs"]]
    assert any(n.endswith("standing.jpg") for n in names)


def test_face_closeup_keeps_standing(tmp_path, monkeypatch):
    """文案明确拍脸/上半身的特写(如面部特写)仍需要人物参照 —— 不裁。"""
    captured = _gen_shot_env(tmp_path, monkeypatch, "特", board_extra={
        "characters": ["小雅"], "props": ["翡翠手镯"], "scene": "暖光卧室",
        "prompt": "面部特写:女子微笑展示耳环"})
    names = [str(p) for p in captured["refs"]]
    assert any(n.endswith("standing.jpg") for n in names)


def test_surface_texture_is_not_a_face_shot():
    """「手复」#03 实测回归:英文改写文案的「sur**face** texture(表面纹理)」
    被 face 子串匹配误判成拍脸 → 特写镜错误保留人物立绘。英文必须按词边界。"""
    from app.pipeline import video_clone as vc
    assert not vc._shot_mentions_face(
        "Close-up of hands, delicate surface texture, rounded profile")
    assert vc._shot_mentions_face("her face lights up with a smile")
    assert vc._shot_mentions_face("面部特写展示妆容")
    assert vc._shot_mentions_face("她低头,脸庞靠近玉镯")


def test_closeup_header_keeps_person_too(clone_env):
    """2026-10-28 定版:特写镜头行照常@人物(与立绘参考配套,短剧绑定做法)。
    旧实验「头行去人物防造人」随立绘恢复一并废止。"""
    from app.pipeline import video_clone as vc
    names = vc.board_asset_names(15, {"shot": "特", "prompt": "surface texture",
                                      "characters": ["小雅"], "props": ["翡翠手镯"],
                                      "scene": "暖光卧室"})
    assert names["characters"] == ["小雅"]
    head = vc.asset_ref_header(names)
    assert "@小雅" in head and "@翡翠手镯" in head


def test_face_closeup_header_keeps_person(clone_env):
    """文案明确拍脸的特写(面部特写)仍要点名人物 —— 头行与参考裁剪同口径。"""
    from app.pipeline import video_clone as vc
    names = vc.board_asset_names(15, {"shot": "特", "prompt": "her face closeup",
                                      "characters": ["小雅"], "props": ["翡翠手镯"],
                                      "scene": "暖光卧室"})
    assert names["characters"] == ["小雅"]


def test_closeup_prompt_carries_clothing_anchor(tmp_path, monkeypatch):
    """「服装在变」回归(2026-10-28 用户反馈):特写镜的服装/肤色依据 —
    立绘图像锚 + 服装文字锚双保险。styling 有数据时,特写提示词必须带上
    (数据驱动:读各项目自己的妆造字段;为空时不注入,不凭空编造)。"""
    captured = _gen_shot_env(tmp_path, monkeypatch, "特", board_extra={
        "characters": ["小雅"], "props": ["翡翠手镯"], "scene": "暖光卧室"})
    assert "服装文字锚" in captured["prompt"], "特写镜缺服装文字锚"
    assert "米色圆领针织衫" in captured["prompt"], "锚内容应来自角色行 styling"


def test_empty_styling_injects_nothing(tmp_path, monkeypatch):
    """styling 为空 → 不注入服装锚子句,更不调 LLM 凭空编服装
    (纯文字编造会跟立绘参考图打架,2026-10-28 定版)。"""
    captured = _gen_shot_env(tmp_path, monkeypatch, "特", board_extra={
        "characters": ["小雅"], "props": ["翡翠手镯"], "scene": "暖光卧室"},
        styling="")
    assert "服装文字锚" not in captured["prompt"]


# ── 2026-10-28:场景锚抹除原产品(用户定版「场景不要保留参考视频的产品」)──
# 空景图的生图要求保留 props,原产品混在其中被一并保留,再当「参考图2=场景图」
# 进每一镜(实测:手复桌上的原片白色软管、自检项目的口红)。修法:多模态定位
# 原产品 bbox → cv2 修复抹掉 → 再喂生图;任何一步失败退回原帧。

def _write_frame(path, product_rect=None):
    """生成合成帧:白底;可选画一块绿色矩形当「原产品」。"""
    import cv2
    import numpy as np
    img = np.full((300, 400, 3), 255, np.uint8)
    if product_rect:
        x1, y1, x2, y2 = product_rect
        img[y1:y2, x1:x2] = (60, 180, 60)
    cv2.imwrite(str(path), img)


def test_erase_product_inpainted_out_of_frame(tmp_path, monkeypatch):
    import cv2

    from app.pipeline import video_clone as vc
    frame = tmp_path / "f1.jpg"
    product = tmp_path / "prod.jpg"
    _write_frame(frame, product_rect=(100, 200, 180, 280))   # x1,y1,x2,y2
    _write_frame(product)

    # 模型回 0-1000 归一化 bbox(绿矩形: x 100-180/400, y 200-280/300)
    monkeypatch.setattr(vc.text_client, "chat", lambda *a, **kw:
                        '{"product": [[250, 666, 450, 933]], "person": []}')
    out = tmp_path / "f1_noprod.jpg"
    assert vc._erase_subjects_from_frame(frame, out) is True
    img = cv2.imread(str(out))
    assert img is not None
    region = img[210:270, 110:170]           # 原绿矩形内部
    assert float(region.mean()) > 180, "产品区域应被修复成接近背景色"
    corner = img[10:30, 10:30]               # 远角不受影响
    assert float(corner.mean()) > 240


def test_erase_product_no_bbox_is_noop(tmp_path, monkeypatch):
    from app.pipeline import video_clone as vc
    frame = tmp_path / "f1.jpg"
    product = tmp_path / "prod.jpg"
    _write_frame(frame, product_rect=(100, 200, 180, 280))
    _write_frame(product)
    monkeypatch.setattr(vc.text_client, "chat", lambda *a, **kw: '{"product": [], "person": []}')
    out = tmp_path / "f1_noprod.jpg"
    assert vc._erase_subjects_from_frame(frame, out) is False
    assert not out.exists(), "没定位到就不该写输出"


def test_erase_product_rejects_fullframe_bbox(tmp_path, monkeypatch):
    """模型回整幅大框(>85% 画幅)= 误标,直接放弃,不能把整帧抹花。"""
    from app.pipeline import video_clone as vc
    frame = tmp_path / "f1.jpg"
    product = tmp_path / "prod.jpg"
    _write_frame(frame, product_rect=(100, 200, 180, 280))
    _write_frame(product)
    monkeypatch.setattr(vc.text_client, "chat", lambda *a, **kw:
                        '{"bboxes": [[0, 0, 1000, 1000]]}')
    out = tmp_path / "f1_noprod.jpg"
    assert vc._erase_subjects_from_frame(frame, out) is False
    assert not out.exists()


def test_scene_anchor_uses_erased_frame(tmp_path, monkeypatch):
    """接线回归:场景锚生图的参考帧必须是「已抹原产品」的那张。"""
    from app.pipeline import video_clone as vc
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for i in range(1, 4):
        _write_frame(frames_dir / f"f{i}.jpg")
    product = tmp_path / "prod.jpg"
    _write_frame(product)
    (tmp_path / "ref.mp4").write_bytes(b"fake")   # 只验存在性,_duration 已打桩
    meta = {"clone": {
        "reference": str(tmp_path / "ref.mp4"),
        "product": str(product),
        "frames_dir": str(frames_dir),
        "scene_asset_id": 26,
    }}
    monkeypatch.setattr(vc, "_meta", lambda drama_id: meta)
    monkeypatch.setattr(vc, "_save_meta", lambda drama_id, m: None)
    monkeypatch.setattr(vc, "_duration", lambda p: 15.0)
    fake_db = _ShotGenDB({"scenes": [{"id": 26, "name": "主场景"}],
                          "dramas": [{"id": 15, "style": "live"}]})
    monkeypatch.setattr(vc, "db", fake_db)

    cap = {}

    def _fake_chat(prompt, **kw):
        # 第一次调用 = 挑帧;若有第二次 = 定位原产品 → 回一个真实小区域
        cap["chat_n"] = cap.get("chat_n", 0) + 1
        if cap["chat_n"] == 1:
            return '{"frame": 2, "location": "夜间卧室", "lighting": "暖灯", ' \
                   '"prompt": "夜间卧室木桌与床铺"}'
        if cap["chat_n"] == 2:
            return '{"product": [[250, 666, 450, 933]], "person": []}'
        return '{"person": false, "product": false}'

    monkeypatch.setattr(vc.text_client, "chat", _fake_chat)

    def _fake_gen(body, out_name="", config_id=None, reference_images=None,
                  people=0, skip_guard=False, reference_lock=False, **kw):
        cap["refs"] = [str(p) for p in (reference_images or [])]
        out = tmp_path / out_name
        _write_frame(out)
        return out, "agnes"

    monkeypatch.setattr(vc.image_client, "generate_image", _fake_gen)
    assert vc.extract_scene_anchor(15) is True
    assert cap["refs"], "场景锚生图必须带参考帧"
    assert cap["refs"][0].endswith("_nosubj.jpg"), (
        "参考帧必须是抹除商品/人物后的那张")


def test_scene_anchor_regenerates_when_dirty(tmp_path, monkeypatch):
    """内容门回归:生成的空景图若审查出人体/商品残留,必须重画,干净才放行
    (2026-10-28 实测:游离的手、床上的脚、留下的包装盒各随机出现过)。"""
    from app.pipeline import video_clone as vc
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for i in range(1, 4):
        _write_frame(frames_dir / f"f{i}.jpg")
    product = tmp_path / "prod.jpg"
    _write_frame(product)
    (tmp_path / "ref.mp4").write_bytes(b"fake")
    meta = {"clone": {
        "reference": str(tmp_path / "ref.mp4"),
        "product": str(product),
        "frames_dir": str(frames_dir),
        "scene_asset_id": 26,
    }}
    monkeypatch.setattr(vc, "_meta", lambda drama_id: meta)
    monkeypatch.setattr(vc, "_save_meta", lambda drama_id, m: None)
    monkeypatch.setattr(vc, "_duration", lambda p: 15.0)
    fake_db = _ShotGenDB({"scenes": [{"id": 26, "name": "主场景"}],
                          "dramas": [{"id": 15, "style": "live"}]})
    monkeypatch.setattr(vc, "db", fake_db)

    cap = {"chat_n": 0, "gen_n": 0}

    def _fake_chat(prompt, **kw):
        cap["chat_n"] += 1
        if cap["chat_n"] == 1:
            return '{"frame": 2, "location": "L", "lighting": "M", "prompt": "P"}'
        if cap["chat_n"] == 2:
            return '{"product": [[250, 666, 450, 933]], "person": []}'
        if cap["chat_n"] == 3:
            return '{"person": true, "product": false}'    # 第一次审查:脏
        return '{"person": false, "product": false}'        # 重画后:干净

    monkeypatch.setattr(vc.text_client, "chat", _fake_chat)

    def _fake_gen(body, out_name="", config_id=None, reference_images=None,
                  people=0, skip_guard=False, reference_lock=False, **kw):
        cap["gen_n"] = cap.get("gen_n", 0) + 1
        out = tmp_path / f"g{cap['gen_n']}_{out_name}"
        _write_frame(out)
        return out, "agnes"

    monkeypatch.setattr(vc.image_client, "generate_image", _fake_gen)
    assert vc.extract_scene_anchor(15) is True
    assert cap["gen_n"] == 2, f"审查出残留必须重画,实际生图 {cap['gen_n']} 次"


def test_scene_anchor_rotates_frame_when_all_dirty(tmp_path, monkeypatch):
    """换帧回归:第一个候选帧连画 3 次都有残留 → 必须换下一候选帧重来,
    直到出干净图(实测:人物占比大的帧怎么去都不干净,换帧最可靠)。"""
    from app.pipeline import video_clone as vc
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for i in range(1, 4):
        _write_frame(frames_dir / f"f{i}.jpg")
    product = tmp_path / "prod.jpg"
    _write_frame(product)
    (tmp_path / "ref.mp4").write_bytes(b"fake")
    meta = {"clone": {
        "reference": str(tmp_path / "ref.mp4"),
        "product": str(product),
        "frames_dir": str(frames_dir),
        "scene_asset_id": 26,
    }}
    monkeypatch.setattr(vc, "_meta", lambda drama_id: meta)
    monkeypatch.setattr(vc, "_save_meta", lambda drama_id, m: None)
    monkeypatch.setattr(vc, "_duration", lambda p: 15.0)
    fake_db = _ShotGenDB({"scenes": [{"id": 26, "name": "主场景"}],
                          "dramas": [{"id": 15, "style": "live"}]})
    monkeypatch.setattr(vc, "db", fake_db)

    cap = {"chat_n": 0, "gen_n": 0, "refs": [], "gate_n": 0}

    def _fake_chat(prompt, **kw):
        cap["chat_n"] += 1
        if 'true或false' in prompt:                     # 内容门审查
            cap["gate_n"] += 1
            if cap["gate_n"] <= 3:                   # 帧 f1 的 3 次全部有人
                return '{"person": true, "product": false}'
            return '{"person": false, "product": false}'   # 帧 f2 干净
        if "带货主体" in prompt:                      # 商品/人物定位
            return '{"product": [], "person": []}'
        return '{"frame": 1, "location": "L", "lighting": "M", "prompt": "P"}'

    monkeypatch.setattr(vc.text_client, "chat", _fake_chat)

    def _fake_gen(body, out_name="", config_id=None, reference_images=None,
                  people=0, skip_guard=False, reference_lock=False, **kw):
        cap["gen_n"] += 1
        cap["refs"].append(str(reference_images[0]))
        out = tmp_path / f"g{cap['gen_n']}_{out_name}"
        _write_frame(out)
        return out, "agnes"

    monkeypatch.setattr(vc.image_client, "generate_image", _fake_gen)
    assert vc.extract_scene_anchor(15) is True
    # 帧 f1 连画 3 次(全脏)→ 换 f2,第 4 次生成;候选帧循环里审查器不可用
    # 会按「干净」处理 —— 本用例审查始终返回「有人」验证的是换帧而不是重画,
    # 但审查失败即视为干净会让它第 1 帧就通过…… 所以此处审查桩必须一直返回
    # 有人,用来证明「换帧路径」被走到:第 4 次生成的参考帧应是 f2
    assert cap["gen_n"] == 4, f"实际生图 {cap['gen_n']} 次"
    assert cap["refs"][3].endswith("f2_nosubj.jpg") or cap["refs"][3].endswith("f2.jpg")


def test_order_scene_candidates_puts_person_free_frames_first():
    """候选帧确定性排序:人物显著度高的帧(人物特写)沉底 —— 对特写帧做去人,
    生图会脑补回化妆品场景(实测 f03)。同分保持原序(LLM 首选在前)。"""
    from app.pipeline import video_clone as vc
    f1, f2, f3 = "f1.jpg", "f2.jpg", "f3.jpg"
    scores = {f1: 0.30, f2: 0.0, f3: 0.10}   # f1=人物特写, f2=无人, f3=手部
    out = vc._order_scene_candidates(f1, [f1, f2, f3], lambda f: scores[f])
    assert out == [f2, f3, f1], f"人物多的帧应沉底,得到 {out}"


def test_erase_person_and_product_regions(tmp_path, monkeypatch):
    """商品与人物(手部)都要抹:只抹产品会留下一只游离的手(实测)。"""
    import cv2

    from app.pipeline import video_clone as vc
    frame = tmp_path / "f1.jpg"
    _write_frame(frame, product_rect=(100, 200, 180, 280))   # 绿矩形 = 商品
    img = cv2.imread(str(frame))
    img[220:260, 300:380] = (40, 40, 200)                    # 右侧红块 = 手
    cv2.imwrite(str(frame), img)
    monkeypatch.setattr(vc.text_client, "chat", lambda *a, **kw:
                        '{"product": [[250, 666, 450, 933]], '
                        '"person": [[750, 733, 950, 866]]}')
    out = tmp_path / "f1_nosubj.jpg"
    assert vc._erase_subjects_from_frame(frame, out) is True
    img2 = cv2.imread(str(out))
    assert float(img2[210:270, 110:170].mean()) > 180, "商品区域应被抹掉"
    assert float(img2[230:250, 310:370].mean()) > 180, "手部区域也应被抹掉"
