"""小说写作红线门控 + 正文内容体检。

用户反馈的原始描述:「你把 AI 生成的总纲的过程写到第一章了」
—— 写第 1 章时,模型返回的「在讲怎么写」被当正文存进了章节。

根因是三处叠加,本文件逐条钉死:
  1. 门控读的是 `novel_meta` 的结构化字段,而写作实际消费的是
     `novel_world` / `novel_contract` **文本列** → 用户填完了却说没填,
     永远写不了小说(实测 drama 4:列里 898/656 字全文,门控仍报「缺步骤 3、4」)。
  2. `plan_novel` 整块覆写 `novel_meta` → 重跑一次开书策划就把叙事人称、
     写作规则、结构化世界观全抹了。
  3. 写正文路径没有「这是过程说明不是正文」的守卫 ——
     `looks_like_meta_talk` 只用在总纲起草(persist_draft)。
"""
from __future__ import annotations

import json

import pytest

from app.core import db
from app.pipeline import novel as nv


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "novel.sqlite3")
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


def _make_drama(**kw) -> int:
    cols = dict(title="测试小说", work_type="novel", language="zh",
                novel_outline="", novel_world="", novel_contract="",
                novel_chapters="[]", novel_meta="{}", metadata="{}")
    cols.update(kw)
    keys = ",".join(cols)
    marks = ",".join("?" for _ in cols)
    db.ex(f"INSERT INTO dramas({keys},created_at,updated_at) VALUES({marks},?,?)",
          (*cols.values(), db.now(), db.now()))
    return int(db.q1("SELECT id FROM dramas ORDER BY id DESC LIMIT 1")["id"])


WORLD_TEXT = "青岚界以灵脉为根基,凡有灵脉处皆可开炉炼器,宗门以贡献点换算资源。"
CONTRACT_TEXT = "第三人称限知,只写主角林岚能感知到的范围,不写他人内心,每章三千字左右。"


# ---------------------------------------------------------------- 门控

def test_gate_accepts_settings_written_as_text_columns(tmp_db):
    """设定填在**文本列**里(向导/开书策划写的都是文本)也算完成。

    旧实现只认 novel_meta 的结构化字段 → 用户明明填了却永远写不了小说。
    """
    did = _make_drama(title="设定齐了", novel_outline="一句话主题:林岚修仙",
                      novel_world=WORLD_TEXT, novel_contract=CONTRACT_TEXT,
                      novel_chapters=json.dumps([{"number": 1}]),
                      metadata=json.dumps({"intro": "简介"}))
    db.ex("INSERT INTO characters(drama_id,name,role_type,created_at,updated_at)"
          " VALUES(?,?,?,?,?)", (did, "林岚", "lead", db.now(), db.now()))
    assert nv.check_novel_redlines(did) == [], "设定齐全却被门控拦住"


def test_gate_still_blocks_when_settings_are_missing(tmp_db):
    """只有总纲时必须拦住 —— 「设置不完整不能生成小说」。"""
    did = _make_drama(title="只有总纲", novel_outline="一句话主题:林岚修仙",
                      metadata=json.dumps({"intro": "简介"}))
    missing = nv.check_novel_redlines(did)
    assert 3 in missing, "缺世界观"
    assert 4 in missing, "缺故事合约"
    assert 5 in missing, "缺角色设定"
    assert 7 in missing, "缺章节规划"


def test_gate_rejects_placeholder_length_text(tmp_db):
    """文本列只有几个字不算填过 —— 不能因为放宽就形同虚设。"""
    did = _make_drama(novel_outline="总纲", novel_world="很短",
                      novel_contract="也短", metadata=json.dumps({"intro": "x"}))
    missing = nv.check_novel_redlines(did)
    assert 3 in missing, "占位长度的世界观不该放行"
    assert 4 in missing, "占位长度的合约不该放行"


def test_gate_accepts_structured_fields_in_novel_meta(tmp_db):
    """走「世界观/故事合约」向导时,结构化字段在 novel_meta 里 —— 也要认。"""
    did = _make_drama(title="向导填的", novel_outline="总纲",
                      novel_meta=json.dumps({
                          "world": {"era": "现代都市修仙", "location": "青岚界"},
                          "contract": {"pov": "third_limited",
                                       "rules": ["只写主角视角"],
                                       "tones": ["克制"]}}),
                      novel_chapters=json.dumps([{"number": 1}]),
                      metadata=json.dumps({"intro": "简介"}))
    db.ex("INSERT INTO characters(drama_id,name,role_type,created_at,updated_at)"
          " VALUES(?,?,?,?,?)", (did, "林岚", "lead", db.now(), db.now()))
    missing = nv.check_novel_redlines(did)
    assert 3 not in missing and 4 not in missing, missing


# ---------------------------------------------------------------- plan_novel

def test_plan_novel_preserves_novel_meta(tmp_db, monkeypatch):
    """开书策划不能抹掉 novel_meta 里的结构化字段与人称。"""
    did = _make_drama(title="旧设定", novel_meta=json.dumps({
        "world": {"era": "现代都市", "location": "青岚界"},
        "contract": {"pov": "first_person", "rules": ["只写主角"], "tones": ["克制"]},
        "imported": {"at": "2026-01-01"}}))
    fake = {"outline": "新总纲", "world": "新世界观", "contract": "新合约",
            "volume": "{}",
            "chapters": [{"number": 1, "title": "第一章"}],
            "main_characters": [{"name": "林岚", "role": "lead"}]}
    monkeypatch.setattr(nv.runner, "run_agent_json", lambda *a, **k: fake)
    monkeypatch.setattr(nv, "plan_config_id", lambda: 4242)
    monkeypatch.setattr(nv, "_sync_characters", lambda *a, **k: None)

    nv.plan_novel(did, "一个修仙创意")

    meta = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?", (did,))["novel_meta"], {})
    assert meta["world"]["era"] == "现代都市", "开书策划把世界观结构化字段抹了"
    assert meta["contract"]["pov"] == "first_person", "开书策划把叙事人称抹了"
    assert meta["imported"], "开书策划把其它 novel_meta 键也抹了"
    assert meta["main_characters"], "主要角色没写进去"


def test_plan_novel_writes_structured_settings_when_planner_returns_them(tmp_db, monkeypatch):
    """策划若给了结构化的世界观/合约,一并落进 novel_meta(门控认这个)。"""
    did = _make_drama(title="策划带结构")
    fake = {"outline": "总纲", "world": "文本", "contract": "文本", "volume": "{}",
            "chapters": [], "main_characters": [],
            "structured_world": {"era": "x"}}
    # 策划返回的 world/contract 是结构化 dict 时才落 meta
    fake["world"] = {"text": "世界观全文", "era": "现代都市", "location": "青岚界"}
    fake["contract"] = {"text": "合约全文", "pov": "third_limited",
                        "rules": ["只写主角"], "tones": ["克制"]}
    monkeypatch.setattr(nv.runner, "run_agent_json", lambda *a, **k: fake)
    monkeypatch.setattr(nv, "plan_config_id", lambda: 4242)
    monkeypatch.setattr(nv, "_sync_characters", lambda *a, **k: None)

    nv.plan_novel(did, "创意")

    meta = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?", (did,))["novel_meta"], {})
    assert meta.get("world", {}).get("era") == "现代都市"
    assert meta.get("contract", {}).get("pov") == "third_limited"


# ---------------------------------------------------------------- 正文体检

def test_check_chapter_content_flags_settings_digest(tmp_db):
    """正文里照抄了总纲原文 → 判定为「在复述设定」,不是正文。"""
    outline = ("本书一句话主题是:一个被房贷和裁员逼到中年尽头的程序员,"
               "用开源思维把修仙界改造成可持续产业。")
    did = _make_drama(novel_outline=outline)
    leaked = ("好的,我们先梳理一下总纲的核心。\n\n" + outline +
              "\n\n接下来开始写正文。\n\n" + "林岚把门关上,雨声就远了。" * 20)
    problem = nv.check_chapter_content(leaked, did)
    assert problem, "照抄总纲没被检出"
    assert "总纲" in problem


def test_check_chapter_content_passes_normal_prose(tmp_db):
    """正常正文不该被误伤 —— 正文里引用设定里的专名/短句是允许的。"""
    outline = ("本书一句话主题是:一个被房贷和裁员逼到中年尽头的程序员,"
               "用开源思维把修仙界改造成可持续产业。")
    did = _make_drama(novel_outline=outline)
    prose = ("林岚把辞职信放在桌上,窗外的雨下得很密。她想起父亲说过的那句话,"
             "有些门推开就关不上了。合同上的字她一个都没看,只是把笔帽按得咔哒响。"
             "楼下有人在按喇叭,她没有抬头。") * 8
    assert nv.check_chapter_content(prose, did) == ""


def test_check_chapter_content_flags_short_output(tmp_db):
    """过短的输出也要拦 —— 模型思考吃满预算时正文可能只有一行。"""
    did = _make_drama()
    assert nv.check_chapter_content("只有一行。", did)


def test_check_chapter_content_tolerates_incomplete_row(tmp_db, monkeypatch):
    """拿不到设定列时不能崩(判不出复述 ≠ 有复述)。"""
    did = _make_drama()
    monkeypatch.setattr(nv.db, "q1", lambda *a, **k: {"novel_outline": ""})
    assert nv.check_chapter_content("正文" * 200, did) == ""


# ---------------------------------------------------------------- 落库

def test_write_chapter_with_review_persists_ok_draft(tmp_db, monkeypatch):
    """审校第一轮就判 ok 时,正文必须真的落库。

    `compressor_node` 的注释说「调用方自行入库」,但没有任何调用方入库 ——
    旧实现下这条路径生成完的正文会凭空消失,界面上照样弹「本章已生成」。
    """
    did = _make_drama()
    db.ex("INSERT INTO episodes(drama_id,episode_number,title,content,created_at,updated_at)"
          " VALUES(?,?,?,?,?,?)", (did, 1, "第1章", "", db.now(), db.now()))
    ep_id = int(db.q1("SELECT id FROM episodes ORDER BY id DESC LIMIT 1")["id"])
    text = "# 第一章\n\n" + "林岚推开门,雨声灌了进来。" * 30

    monkeypatch.setattr("app.agents.novel_review_flow.run_novel_review_loop",
                        lambda **kw: {"decision": "ok", "final": [text], "cycles": 1})
    monkeypatch.setattr(nv, "prose_config_id", lambda: 4242)

    out = nv.write_chapter_with_review(ep_id)
    assert out["content"] == text
    stored = db.q1("SELECT content FROM episodes WHERE id=?", (ep_id,))["content"]
    assert stored == text, "判 ok 的正文没有落库"


def test_write_chapter_with_review_does_not_persist_giveup(tmp_db, monkeypatch):
    """审校没通过(giveup)的稿子不该落库。"""
    did = _make_drama()
    db.ex("INSERT INTO episodes(drama_id,episode_number,title,content,created_at,updated_at)"
          " VALUES(?,?,?,?,?,?)", (did, 1, "第1章", "", db.now(), db.now()))
    ep_id = int(db.q1("SELECT id FROM episodes ORDER BY id DESC LIMIT 1")["id"])

    monkeypatch.setattr("app.agents.novel_review_flow.run_novel_review_loop",
                        lambda **kw: {"decision": "giveup", "final": [], "cycles": 3})
    monkeypatch.setattr(nv, "prose_config_id", lambda: 4242)

    nv.write_chapter_with_review(ep_id)
    stored = db.q1("SELECT content FROM episodes WHERE id=?", (ep_id,))["content"]
    assert not stored, "giveup 的稿子不该落库"


# ---------------------------------------------------------------- 主要角色

def test_load_main_characters_falls_back_to_asset_library(tmp_db):
    """角色只在资产库里时也必须读得到。

    写作门控查的是资产库(chars 表),而向导的「主要角色」框只读
    novel_meta.main_characters —— 两边不同源时,用户看到一片空白,
    但角色其实在库里(实测 drama 4:库里 10 个角色,向导显示空)。
    """
    did = _make_drama(title="只有资产库有角色")
    db.ex("""INSERT INTO characters(drama_id,name,role_type,appearance,styling,
                created_at,updated_at) VALUES(?,?,?,?,?,?,?)""",
          (did, "叶尘", "lead", "18岁男性,瘦削结实", "灰黑破旧道袍",
           db.now(), db.now()))
    chars = nv.load_main_characters(did)
    assert len(chars) == 1
    assert chars[0]["name"] == "叶尘"
    assert chars[0]["role"] == "主角"
    assert chars[0]["appearance"] == "18岁男性,瘦削结实"


def test_load_main_characters_prefers_novel_meta(tmp_db):
    """novel_meta 里有完整字段时优先用它(带 identity/motivation)。"""
    did = _make_drama(title="meta 有角色", novel_meta=json.dumps({
        "main_characters": [{"name": "林岚", "role": "主角",
                             "identity": "青岚界工坊主", "motivation": "活下去"}]}))
    db.ex("""INSERT INTO characters(drama_id,name,role_type,created_at,updated_at)
             VALUES(?,?,?,?,?)""", (did, "另一个", "supporting", db.now(), db.now()))
    chars = nv.load_main_characters(did)
    assert len(chars) == 1
    assert chars[0]["name"] == "林岚"
    assert chars[0]["identity"] == "青岚界工坊主"


def test_wizard_has_ai_generate_characters_button():
    """向导里必须有「AI 生成主要角色」按钮 + 章节计划后自动串联。

    之前**没有**:角色只能靠「开书策划」顺带产出,或者手写 JSON。
    而角色设定是写作红线的第 5 步 —— 没有它,一章也写不了。

    用源码断言而不是实例化对话框:本仓其它 UI 测试(test_split_models.py)
    也是这个路子 —— 构造 QWidget 需要 QApplication,单测里起一个会拖慢全量。
    """
    import inspect

    from app.ui import novel_dialogs
    src = inspect.getsource(novel_dialogs)
    assert "chars_btn" in src, "向导里没有 chars_btn"
    assert "_ai_characters" in src, "没有「AI 生成主要角色」的处理函数"
    assert "_chain_characters" in src, "章节计划生成后没有自动串联角色"
    # 按钮必须接上点击信号,否则是个死按钮
    assert "self.chars_btn.clicked.connect(self._ai_characters)" in src,         "「AI 生成主要角色」按钮没接点击信号"
    # 章节计划的两个完成回调(分批路径 / 流式路径)都要串联
    assert src.count("self._chain_characters()") >= 2,         "章节计划的完成回调没有全部接上角色串联"


# ---------------------------------------------------------------- 角色解析

def test_character_payload_accepts_chinese_keys():
    """模型用中文键回角色时也必须解析出来(实测 drama 4 上就是这么失败的)。

    提示词整体是中文(总纲/世界观/合约/角色外观规格块),模型就跟着给中文键:
    {"角色":[{"姓名":…,"角色":…,"外形":…,"服装风格":…}]}。
    旧实现只认 name/role/appearance → 名字取不到 → 每个角色被跳过 →
    「AI 未返回角色」(sys_task 1548 就是这条)。
    """
    payload = {"角色": [{
        "姓名": "叶尘", "角色": "主角", "身份": "被逐弟子", "动机": "查清灭门真相",
        "外形": "约二十二岁的青年男子,中等身高一米七八,体型偏瘦但骨架结实。",
        "服装风格": "贴身的粗麻深灰短打,领口开成斜襟,领缘被磨得发白起毛。",
    }]}
    got = nv._extract_characters_payload(payload)
    assert len(got) == 1, "中文键没解析出来"
    assert got[0]["name"] == "叶尘"
    assert got[0]["role"] == "主角"
    assert got[0]["identity"] == "被逐弟子"
    assert "青年男子" in got[0]["appearance"]
    assert "粗麻" in got[0]["styling"]


@pytest.mark.parametrize("payload", [
    {"characters": [{"name": "A", "role": "主角"}]},
    {"main_characters": [{"name": "A", "role": "主角"}]},
    {"角色": [{"姓名": "A", "角色": "主角"}]},
    [{"name": "A", "role": "主角"}],
])
def test_character_payload_shapes(payload):
    """容器形态:characters / main_characters / 角色 / 裸数组 —— 全都认。"""
    assert len(nv._extract_characters_payload(payload)) == 1


def test_character_payload_empty_is_empty():
    assert nv._extract_characters_payload({}) == []
    assert nv._extract_characters_payload(None) == []


def test_normalize_character_fields_keeps_standard_shape():
    """已经是标准形态的 dict 不该被改写。"""
    c = {"name": "A", "role": "主角", "appearance": "x", "styling": "y"}
    out = nv._normalize_character_fields(c)
    assert out == c


# ------------------------------------------------- 「生成角色」只管角色

def _stub_llm(monkeypatch, payload):
    """把角色生成链路上的两次 LLM 调用打桩。"""
    monkeypatch.setattr(nv.runner, "run_agent_json",
                        lambda *a, **k: payload)
    monkeypatch.setattr(nv.character_spec, "expand_many",
                        lambda chars, **k: chars)


def test_plan_characters_never_generates_chapter_plan(tmp_db, monkeypatch):
    """点「AI 生成主要角色」**不许顺带生成章节计划**。

    旧实现在章节计划缺失时先跑 `plan_chapters()`,而章节计划是按全书章数
    生成的(drama 4 是 500 章)—— 于是「生成角色」= 「生成 500 章计划」:
    几十次 LLM 调用、十几分钟,最后才轮到角色;中途失败则角色一个都没有。
    按钮该干什么就干什么。
    """
    did = _make_drama(title="没有章节计划", novel_chapters="[]")

    def _boom(*a, **k):  # pragma: no cover —— 被调用就是 bug
        raise AssertionError("生成角色时不该去生成章节计划")

    monkeypatch.setattr(nv, "plan_chapters", _boom)
    _stub_llm(monkeypatch, {"characters": [
        {"name": "林岚", "role": "主角", "appearance": "青衣少年",
         "styling": "粗布长衫"}]})

    out = nv.plan_characters(did)
    assert out["count"] == 1
    assert out["plan_missing"] is True, "章节计划缺失要如实标出来"
    # 角色照常落库(资产库 + novel_meta)
    rows = db.q("SELECT name FROM characters WHERE drama_id=?", (did,))
    assert [r["name"] for r in rows] == ["林岚"]
    meta = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?", (did,))["novel_meta"], {})
    assert meta["main_characters"][0]["name"] == "林岚"


def test_plan_characters_uses_existing_plan_and_flags_present(tmp_db, monkeypatch):
    """章节计划在库里时直接用它,并把 plan_missing 标成 False。"""
    did = _make_drama(title="有章节计划", novel_chapters=json.dumps([
        {"number": 1, "title": "逐出青云", "goal": "起势", "events": "叶尘被逐",
         "cliffhanger": "钩子"}]))
    seen = {}

    def _capture(agent, prompt, **k):
        seen["prompt"] = prompt
        return {"characters": [{"name": "林岚", "role": "主角"}]}

    monkeypatch.setattr(nv.runner, "run_agent_json", _capture)
    monkeypatch.setattr(nv.character_spec, "expand_many", lambda chars, **k: chars)

    out = nv.plan_characters(did)
    assert out["plan_missing"] is False
    assert "叶尘被逐" in seen["prompt"], "章节计划没进提示词"
    assert "章节计划" in seen["prompt"]


def test_character_plan_context_keeps_volume_key_events():
    """分卷形态的 key_events **不能丢**。

    `novel_chapters` 存分卷结构时(开书策划原样落库,实测 drama 4 是 3 卷/500 章),
    `chapters_to_text` 只认 events → key_events 整段丢失 → 渲染出
    「第?章 第一卷:… | 事件:(空)」,人物的关键行为一个都没进上下文。
    而角色提示词要求「动机与章节计划里的实际行为对得上」。
    """
    txt = nv._character_plan_context([
        {"title": "第一卷：黑水边城", "range": "1-3", "goal": "起势",
         "key_events": ["叶尘被逐出师门", "青灯残页现世"], "cliffhanger": "钩子"}])
    assert "第一卷：黑水边城" in txt
    assert "1-3" in txt
    assert "叶尘被逐出师门" in txt, "key_events 被丢了"
    assert "钩子" in txt


def test_character_plan_context_supports_chapter_shape():
    """逐章形态照旧(第 N 章 / 目标 / 事件 / 钩子)。"""
    txt = nv._character_plan_context([
        {"number": 7, "title": "断水式", "goal": "g", "events": "e", "cliffhanger": "h"}])
    assert "第7章 断水式" in txt
    assert "事件:e" in txt


def test_character_prompt_basis_switches_without_plan():
    """没有章节计划时,提示词不能还在要求「与章节计划对得上」。"""
    with_plan = nv._character_prompt("章节计划")
    without_plan = nv._character_prompt("总纲与故事合约")
    assert "章节计划" in with_plan
    assert "总纲与故事合约" in without_plan
    assert "{plan_basis}" not in without_plan
    # JSON 形状不能被 replace 吃掉花括号
    assert '{"characters":[' in without_plan


def test_chain_characters_skips_when_library_already_has_characters():
    """章节计划后的角色串联:资产库里已有角色就不该再生成一批。

    以前只看 novel_meta.main_characters,而角色也可能从资产提取/整书导入进库
    (实测 drama 4:库里 10 个角色、meta 是空的)→ 判成「没有」→ 白白再生成一批。
    """
    import inspect

    from app.ui import novel_dialogs
    src = inspect.getsource(novel_dialogs)
    assert "load_main_characters" in src, "串联角色没按资产库+meta 一起判"
    assert 'nm.get("main_characters")' not in src, "还在只看 novel_meta"


# ---------------------------------------------------------------- UI 静态守卫

def test_ui_classes_do_not_read_undefined_self_attributes():
    """UI 类不得读取自己没赋值过的 self 属性。

    实测踩过:给 `AiEditDialog.job()` 加 `lang=resolve_content_language(self.drama_id)`,
    而 `AiEditDialog` 只有 `episode_id`(`drama_id` 是 `QaDialog` 才有的)——
    一按「应用」就 AttributeError 崩在按钮上,用户看到的是「AI 修改一点反应没有」。
    静态扫一遍比等用户踩到便宜。

    判据:类里**读到**的 self.X 必须满足其一
      · 在本类里被赋值过(self.X = ...)
      · 本类里定义过同名方法(self.X 是方法,不是属性)
    只查我们自己的命名前缀(drama/_drama/lang/_lang)—— Qt 的属性太多,查不过来。
    """
    import ast
    from pathlib import Path

    ui = Path(__file__).resolve().parents[1] / "app" / "ui"
    PREFIX = ("drama", "_drama", "lang", "_lang")
    problems: list[str] = []
    for path in sorted(ui.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover
            continue
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            assigned: set[str] = set()
            methods: set[str] = set()
            read: set[str] = set()
            for n in ast.walk(cls):
                if isinstance(n, ast.FunctionDef):
                    methods.add(n.name)
                if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                        and n.value.id == "self"):
                    if isinstance(n.ctx, ast.Store):
                        assigned.add(n.attr)
                    else:
                        read.add(n.attr)
            missing = {a for a in read - assigned - methods if a.startswith(PREFIX)}
            if missing:
                problems.append(f"{path.name}:{cls.name} → {sorted(missing)}")
    assert not problems, (
        "以下类读到了自己没定义过的属性(一用就 AttributeError):\n  "
        + "\n  ".join(problems))


def test_ui_gate_agrees_with_pipeline_gate(tmp_db):
    """UI 的 wizard_step_done 与 pipeline 的 check_novel_redlines 必须同一把尺子。

    这是两份独立实现,曾经 UI 侧只认 novel_meta 结构化字段、pipeline 侧认文本列
    —— pipeline 放行、按钮锁死,「共享修仙」第 3 集就是这么灰掉的。
    用同一个项目断言两边判定一致(世界观/合约写的是**文本列**)。
    """
    from app.ui.novel_dialogs import missing_steps
    did = _make_drama(title="双门控一致", novel_outline="一句话主题:测试",
                      novel_world="青岚界以灵脉为根基,凡有灵脉处皆可开炉炼器,宗门以贡献点换算资源。",
                      novel_contract="第三人称限知,只写主角林岚能感知到的范围,不写他人内心,每章三千字左右。",
                      novel_chapters=json.dumps([{"number": 1}]),
                      metadata=json.dumps({"intro": "简介"}))
    db.ex("INSERT INTO characters(drama_id,name,role_type,created_at,updated_at)"
          " VALUES(?,?,?,?,?)", (did, "林岚", "lead", db.now(), db.now()))
    # 两边都必须说「无缺失」
    assert nv.check_novel_redlines(did) == [], "pipeline 门控误拦"
    assert missing_steps(did) == [], "UI 门控误拦(按钮会锁死)"

    # 再断言:两边对「只有总纲」的项目也一致地拦
    did2 = _make_drama(title="只有总纲", novel_outline="一句话主题:测试",
                       metadata=json.dumps({"intro": "简介"}))
    assert 3 in nv.check_novel_redlines(did2)
    assert 3 in missing_steps(did2)
