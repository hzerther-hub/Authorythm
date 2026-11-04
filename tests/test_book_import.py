"""整书导入 → 分析 → 仿写 三段式的对齐回归测试。

对齐基准:原版 E:\\xiaoshuo backend/src/routes/novel.ts(2df744b,此后上游未改)。
锁住的关键不变量:
- 切章:短书(≥3 个「第N章」)必须按标题切,不得掉进 2 万字窗口兜底
        (此前阈值写死 32,3-31 章的书全被窗口切碎);
- 切章:分隔线**下方**短标题(站点导出常见格式,原版唯一口径)能切出章;
- 分析:断点续跑跳过已成功组;失败率过高暂停并落盘 partial_chunks;
- 仿写:planned_chapters 缺失时兜底「原书章数 ‖ 100」,不再兜底 1;
- 仿写:总纲阶段也注入节拍时间线(否则写出来的是「同题材新书」不是「同骨架新书」);
- 仿写:三阶段提示词必须按上游口径喂**标签化档案**并把总纲喂进分卷 ——
        这是「生成的新书与原书骨架像不像」的决定性因素(2026-11-02 用户实测:
        Vue 版生成的还是同一题材,Python 版改动过大);
- 导入:已有章节必须显式 confirm(上游 import-book 的 confirm:true 双保险);
- 分析:心跳落盘 + running 态(进程崩溃现场)可续跑;同一项目不许并发分析。

测试不碰真实库;LLM 一律 monkeypatch 打桩。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.agents import runner
from app.core import db
from app.pipeline import book_import as bi


def _as_json_runner(fake_raw):
    """把「回原始文本」的桩包装成 run_agent_json 的桩。

    run_agent_json 直接返回**已解析**的对象(它内部才是解析入口);老桩按 prompt
    内容回原始字符串,这里补上真函数的行为:解析不出来就抛 RuntimeError。
    """
    def wrapper(agent_type, prompt, **kw):
        raw = fake_raw(agent_type, prompt, **kw)
        if isinstance(raw, (dict, list)):
            return raw
        data = runner.extract_json(raw if isinstance(raw, str) else "")
        if data is None:
            raise RuntimeError(f"{agent_type} 输出无法解析为 JSON")
        return data
    return wrapper


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "book.sqlite3")
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


@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _mk_drama(work_type: str = "novel") -> int:
    db.ex("""INSERT INTO dramas(title,style,aspect_ratio,work_type,total_episodes,
             novel_meta,metadata,created_at,updated_at)
             VALUES('测试书','x','9:16',?,1,'{}','{}',?,?)""",
          (work_type, db.now(), db.now()))
    return db.get_db().execute(
        "SELECT id FROM dramas ORDER BY id DESC LIMIT 1").fetchone()["id"]


# ── 段① 切章 ───────────────────────────────────────────────────────

def test_short_book_splits_by_chapter_headings():
    """3-31 章的短书此前掉进兜底被 2 万字窗口切碎;原版阈值就是 3。"""
    text = "\n".join(
        f"第{'一二三四五'[i]}章 风起{i}\n" + "正文内容," * 30 for i in range(5))
    chapters = bi.split_book_into_chapters(text)
    assert len(chapters) == 5
    assert chapters[0][0].startswith("第一章")
    assert not chapters[0][0].startswith("片段")   # 没走窗口兜底


def test_separator_below_title_splits():
    """原版口径:「----」分隔线在标题**上方**(分隔线下方第一个非空短行是章名)。"""
    parts = []
    for i in range(4):
        parts.append("----")
        parts.append(f"魔尊在怀{i}·废柴翻身")
        parts.append("她攥紧了袖口,指节泛白。" * 20)
    chapters = bi.split_book_into_chapters("\n".join(parts))
    assert len(chapters) == 4
    assert chapters[1][0] == "魔尊在怀1·废柴翻身"


def test_separator_above_title_still_supported():
    """「标题在分隔线上方」的格式(本仓旧口径)仍能切出 —— 两方向都认,原版方向优先。"""
    parts = []
    for i in range(4):
        parts.append(f"无编号章名{i}")
        parts.append("====")
        parts.append("他把杯子放下,沉默良久。" * 20)
    chapters = bi.split_book_into_chapters("\n".join(parts))
    assert len(chapters) == 4
    assert chapters[2][0] == "无编号章名2"


def test_fallback_window_without_any_structure():
    text = "毫无结构的正文。" * 6000          # ~5 万字,无标题无分隔线
    chapters = bi.split_book_into_chapters(text)
    assert len(chapters) >= 2
    assert chapters[0][0] == "片段 1"


def test_import_book_reports_encoding_and_marks_meta(tmp_db):
    drama_id = _mk_drama()
    db.ex("""INSERT INTO episodes(drama_id,episode_number,title,content,status,
             resolution,created_at,updated_at) VALUES(?,1,'旧章','旧','draft','720p',?,?)""",
          (drama_id, db.now(), db.now()))
    text = "\n".join(f"第{i}章 章{i}\n" + "内容," * 400 for i in range(1, 4))
    out = bi.import_book(drama_id, data=text.encode("gbk"), confirm=True)
    assert out["encoding"] == "gbk"
    assert out["chapters"] == 3
    n = db.q1("SELECT COUNT(*) c FROM episodes WHERE drama_id=?", (drama_id,))["c"]
    assert n == 3                                  # 旧章已替换
    meta = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?",
                          (drama_id,))["novel_meta"], {})
    assert meta["imported"]["chapters"] == 3


def test_import_book_requires_confirm_when_chapters_exist(tmp_db):
    """已有章节时必须显式确认才导入(上游 import-book 的 confirm:true 双保险)。

    导入语义是「本项目改当源书」,会清掉既有章节与分镜 —— 本仓是硬删不可逆,
    所以护栏必须比上游更硬:没带 confirm 直接拒绝,一个旧章节都不能少。
    """
    drama_id = _mk_drama()
    db.ex("""INSERT INTO episodes(drama_id,episode_number,title,content,status,
             resolution,created_at,updated_at) VALUES(?,1,'旧章','旧','draft','720p',?,?)""",
          (drama_id, db.now(), db.now()))
    text = "\n".join(f"第{i}章 章{i}\n" + "内容," * 400 for i in range(1, 4))
    with pytest.raises(RuntimeError, match="已有 1 个章节"):
        bi.import_book(drama_id, data=text.encode("gbk"))
    n = db.q1("SELECT COUNT(*) c FROM episodes WHERE drama_id=?", (drama_id,))["c"]
    assert n == 1, "未确认时不得动既有章节"


# ── 段② 分析 ───────────────────────────────────────────────────────

MAP_JSON = json.dumps({
    "summary": "本段梗概", "beats": ["事件一", "事件二"],
    "characters": [{"name": "林晚", "identity": "女主", "personality": "坚韧"}],
    "settings": "都市", "hooks": "章末钩子"}, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """重试退避/错峰的 sleep 全部打掉,测试不真等。"""
    monkeypatch.setattr(bi.time, "sleep", lambda *_: None)


def _seed_chapters(drama_id: int, n: int) -> None:
    for i in range(1, n + 1):
        db.ex("""INSERT INTO episodes(drama_id,episode_number,title,content,status,
                 resolution,created_at,updated_at) VALUES(?,?,?,?, 'draft','720p',?,?)""",
              (drama_id, i, f"第{i}章", "正文" * 50, db.now(), db.now()))


def test_analysis_done_persists_profile(tmp_db, monkeypatch):
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 3)
    calls = []

    def fake_run(agent_type, prompt, **kw):
        calls.append(prompt)
        return MAP_JSON if "结构分析师" in prompt else json.dumps(
            {"genre": "都市", "main_characters": []}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake_run))
    out = bi.run_analysis(drama_id)
    assert out["status"] == "done"
    assert len(calls) == 2                          # 1 组 Map(3 章一组)+ 1 次 Reduce
    analysis = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?",
                              (drama_id,))["novel_meta"], {})["analysis"]
    assert analysis["status"] == "done"
    assert analysis["plot_timeline"][0]["beats"] == ["事件一", "事件二"]


def test_analysis_pause_valve_and_resume_skips_done(tmp_db, monkeypatch):
    """失败率过高 → paused + partial 落盘;resume 跳过已成功组只跑剩下的。"""
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 8)
    monkeypatch.setattr(bi, "GROUP", 2)             # 4 组
    monkeypatch.setattr(bi, "FAIL_MIN_SAMPLES", 2)

    def always_fail(agent_type, prompt, **kw):
        raise RuntimeError("429")

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(always_fail))
    out = bi.run_analysis(drama_id)
    assert out["status"] == "paused"
    analysis = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?",
                              (drama_id,))["novel_meta"], {})["analysis"]
    assert analysis["pause_count"] == 1
    assert analysis["paused_at"]
    # 冷却期内 resume 被拒(30s)
    with pytest.raises(RuntimeError, match="冷却中"):
        bi.run_analysis(drama_id, resume=True)
    # 把暂停时间拨回 60s 前 → 可恢复;1、2 组算已成功,只跑 3、4 组
    analysis["paused_at"] = (datetime.now(timezone.utc) - timedelta(seconds=60)
                             ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    analysis["partial_chunks"] = [
        {"_seg": 1, "_ok": True, "summary": "s1", "beats": [], "characters": [],
         "settings": "", "hooks": ""},
        {"_seg": 2, "_ok": True, "summary": "s2", "beats": [], "characters": [],
         "settings": "", "hooks": ""}]
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?",
          (json.dumps({"analysis": analysis}, ensure_ascii=False), drama_id))
    map_calls = []

    def fake(agent_type, prompt, **kw):
        if "结构分析师" in prompt:
            map_calls.append(prompt)
            return MAP_JSON
        return json.dumps({"genre": "g"}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    out = bi.run_analysis(drama_id, resume=True)
    assert out["status"] == "done"
    assert len(map_calls) == 2                      # 组 3、4;组 1、2 被跳过


def test_reduce_input_excludes_failed_and_uses_formatted_digest(
        tmp_db, monkeypatch):
    """Reduce 输入:格式化叙述 + 不含失败组空摘要(此前 json.dumps 截断还混失败组)。"""
    d = bi._reduce_digest([
        {"summary": "段一梗概", "characters": [{"name": "林晚", "identity": "女主",
                                             "personality": "坚韧"}],
         "settings": "都市", "hooks": "快节奏"},
        {"summary": "", "characters": [], "settings": "", "hooks": ""}])
    assert "【段1】段一梗概" in d
    # 人物行口径对齐上游:name(identity,personality) —— 此前只有「名字,身份」,
    # 性格(人物弧线的原料)被丢掉,Reduce 出来的 arc/personality 自然是空的。
    assert "林晚 (女主,坚韧)" in d
    assert "【段2】\n" in d                          # 空组也在(由调用方过滤)


# ── 段③ 仿写 ───────────────────────────────────────────────────────

SETTINGS_JSON = json.dumps({
    "title": "新书名", "genre": "玄幻", "description": "一句话",
    "world": {"era": "古代"}, "contract": {"pov": "third_limited"},
    "characters": [{"name": "阿禾", "identity": "村女",
                    "personality": "倔强", "arc": "觉醒"}],
    # 故意没有 planned_chapters —— 考兜底链
}, ensure_ascii=False)


def test_imitation_planned_falls_back_to_source_chapters(tmp_db, monkeypatch):
    """planned_chapters 缺失 → 用原书章数(原版口径);此前兜底 1 会建出 1 章的书。"""
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?", (
        json.dumps({"analysis": {"status": "done", "chapters": 37,
                                 "profile": {"genre": "都市"},
                                 "plot_timeline": [
                                     {"chapters": [1, 12], "summary": "s",
                                      "beats": ["b1", "b2"]}],
                                 "analyzed_at": db.now()}}, ensure_ascii=False),
        drama_id))
    prompts = []

    def fake(agent_type, prompt, **kw):
        prompts.append(prompt)
        # 分段标记必须唯一:分卷阶段也要吃「新书总纲」(上游同款结构),
        # 只认「总纲」二字会把分卷阶段误判成总纲阶段。
        if "书级设定" in prompt:
            return SETTINGS_JSON
        if "写新书的总纲" in prompt:
            return json.dumps({"outline": "总纲正文"}, ensure_ascii=False)
        return json.dumps({"volumes": "### 第1卷"}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    monkeypatch.setattr(bi.character_spec, "expand_many", lambda seed, lang=None: seed)
    out = bi.run_imitation(drama_id)
    assert out["planned_chapters"] == 37
    row = db.q1("SELECT total_episodes, novel_meta FROM dramas WHERE id=?",
                (out["drama_id"],))
    assert row["total_episodes"] == 37
    # outline 阶段也必须注入节拍时间线(此前只在 volumes 注入)
    outline_prompt = next(p for p in prompts if "总纲" in p)
    assert "情节节拍时间线" in outline_prompt
    assert "b1 → b2" in outline_prompt


def test_imitation_requires_done_analysis(tmp_db):
    drama_id = _mk_drama()
    with pytest.raises(RuntimeError, match="先完成章节分析"):
        bi.run_imitation(drama_id)


# ── 标志与互跳:导入书 / 仿写书 / 一原著仿 N 本 ────────────────────

def _imitation_payload(title: str) -> str:
    return json.dumps({"title": title, "genre": "玄幻", "description": "d",
                       "world": {}, "contract": {},
                       "characters": [{"name": "甲", "identity": "i",
                                       "personality": "p", "arc": "a"}]},
                      ensure_ascii=False)


def test_one_source_can_be_imitated_n_times(tmp_db, monkeypatch):
    """一篇原著可以反复仿成 N 本:每次新建独立项目,原著 novel_meta 不被占用。"""
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?", (
        json.dumps({"analysis": {"status": "done", "chapters": 30,
                                 "profile": {"genre": "都市"},
                                 "plot_timeline": [], "analyzed_at": db.now()}},
                   ensure_ascii=False), drama_id))
    seq = [_imitation_payload("仿本一"), _imitation_payload("仿本二"),
           json.dumps({"outline": "总纲"}, ensure_ascii=False),
           json.dumps({"volumes": "### 第1卷"}, ensure_ascii=False)]
    # 按调用次序轮转:每轮 settings→outline→volumes;settings 按轮次换书名
    state = {"i": 0}

    def fake2(agent_type, prompt, **kw):
        state["i"] += 1
        # 每轮 3 次调用:settings / outline / volumes;settings 按 title 切换
        pos = (state["i"] - 1) % 3
        if pos == 0:
            return seq[(state["i"] - 1) // 3]        # 第 1 轮「仿本一」第 2 轮「仿本二」
        return seq[1 + pos]                          # outline / volumes
    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake2))
    monkeypatch.setattr(bi.character_spec, "expand_many", lambda seed, lang=None: seed)

    out1 = bi.run_imitation(drama_id)
    out2 = bi.run_imitation(drama_id)
    assert out1["drama_id"] != out2["drama_id"]      # 两本各自独立
    titles = {r["title"] for r in db.q(
        "SELECT title FROM dramas WHERE id IN (?,?)", (out1["drama_id"], out2["drama_id"]))}
    assert titles == {"仿本一", "仿本二"}
    # 原著的 analysis 不被吃掉 —— 第 3 次照样能仿
    out3 = bi.run_imitation(drama_id)
    assert out3["drama_id"] not in (out1["drama_id"], out2["drama_id"])


def test_imitations_of_finds_all_children_in_order(tmp_db):
    """反查:原著能列出全部仿写本(按时间升序),自己与无关项目不算。"""
    src = _mk_drama()
    other = _mk_drama()                              # 无关项目
    ids = []
    for i, day in enumerate(("2026-10-01", "2026-10-02", "2026-10-03")):
        db.ex("""INSERT INTO dramas(title,style,aspect_ratio,work_type,total_episodes,
                 novel_meta,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)""",
              (f"仿本{i}", "x", "9:16", "novel", 1,
               json.dumps({"imitated_from": {"drama_id": src,
                                             "source_title": "原著"}},
                          ensure_ascii=False),
               f"{day}T00:00:0{i}Z", f"{day}T00:00:0{i}Z"))
        ids.append(db.get_db().execute(
            "SELECT id FROM dramas ORDER BY id DESC LIMIT 1").fetchone()["id"])
    # 其中一本的 imitated_from 指向别的项目 → 不该出现在 src 的列表里
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?", (
        json.dumps({"imitated_from": {"drama_id": other}}, ensure_ascii=False), ids[1]))
    found = bi.imitations_of(src)
    assert [c["drama_id"] for c in found] == [ids[0], ids[2]]
    assert found[0]["title"] == "仿本0"
    assert bi.imitations_of(other) == [{"drama_id": ids[1], "title": "仿本1",
                                        "at": "2026-10-02T00:00:01Z"}]
    assert bi.imitations_of(_mk_drama()) == []        # 没被仿过的书 → 空


# ── 段④ 项目信息提炼 ────────────────────────────────────────────────

def test_generate_book_meta_samples_first_three_chapters(tmp_db, monkeypatch):
    """采样前 3 章(原版口径) —— 题材铺垫常在第 2、3 章,只看第 1 章会漏。"""
    drama_id = _mk_drama()
    for i in range(1, 4):
        db.ex("""INSERT INTO episodes(drama_id,episode_number,title,content,status,
                 resolution,created_at,updated_at) VALUES(?,?,?,?, 'draft','720p',?,?)""",
              (drama_id, i, f"第{i}章",
               f"第{i}章的独有记号MARK{i}。" + "正文" * 60, db.now(), db.now()))
    got = {}

    def fake(agent_type, prompt, **kw):
        got["prompt"] = prompt
        return json.dumps({"genre": "都市", "description": "d",
                           "creative_description": "c"}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    bi.generate_book_meta(drama_id)
    assert "MARK1" in got["prompt"]
    assert "MARK2" in got["prompt"] and "MARK3" in got["prompt"]


# ── 导入书的设定补齐(照原书总结,与仿写是两条路)────────────────────────

_BOOK_SETTINGS_JSON = json.dumps({
    "genre": "都市重生",
    "description": "落魄主厨重生回灶台前,靠一手爆炒翻盘。",
    "world": {"text": "现代都市,餐饮江湖。",
              "structured": {"era": "当代", "location": "江城美食街",
                             "power_system": "厨艺",
                             "factions": [{"name": "鼎香楼", "desc": "老字号"}],
                             "note": ""}},
    "contract": {"text": "第三人称限知,每章 2000-2600 字。",
                 "structured": {"pov": "third_limited",
                                "tones": ["烟火气", "爽感"],
                                "rules": ["不写内心独白", "每章一个冲突"],
                                "word_range": [2000, 2600], "note": ""}},
    "characters": [{"name": "陈灶", "identity": "主厨",
                    "personality": "倔", "arc": "重开老店"}],
}, ensure_ascii=False)


def _done_analysis(drama_id: int) -> None:
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?", (
        json.dumps({"analysis": {"status": "done", "chapters": 40,
                                 "profile": {"genre": "都市"},
                                 "plot_timeline": [
                                     {"chapters": [1, 20], "summary": "前段",
                                      "beats": ["b1", "b2"]},
                                     {"chapters": [21, 40], "summary": "后段",
                                      "beats": ["b3"]}],
                                 "analyzed_at": db.now()}}, ensure_ascii=False),
        drama_id))


def test_book_settings_written_for_this_project(tmp_db, monkeypatch):
    """导入书的设定 = 照原书总结,写进**本项目**:四段设定 + 简介/题材 + 结构化镜像。

    与仿写的根本区别:仿写另开新项目;这里项目里躺着的就是这本书,
    novel_outline 等描述的必须是这本书本身(不改名、不改情节)。
    """
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 3)
    _done_analysis(drama_id)

    def fake(agent_type, prompt, **kw):
        assert agent_type == "novel_planner"
        if "提炼这本书本身的设定" in prompt:
            return _BOOK_SETTINGS_JSON
        if "这本书的全书总纲" in prompt:
            return json.dumps({"outline": "照原书总结的总纲正文"}, ensure_ascii=False)
        return json.dumps({"volumes": "### 第1卷 上半场(第1-20章)"}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    monkeypatch.setattr(bi.character_spec, "expand_many", lambda seed, lang=None: seed)
    out = bi.generate_book_settings(drama_id)
    assert out["outline"] > 0 and out["characters"] == 1
    row = db.q1("SELECT novel_outline, novel_world, novel_contract, novel_volume,"
                " novel_meta, metadata FROM dramas WHERE id=?", (drama_id,))
    assert "照原书总结的总纲正文" in (row["novel_outline"] or "")
    assert "现代都市,餐饮江湖" in (row["novel_world"] or "")
    assert "第三人称限知" in (row["novel_contract"] or "")
    assert "第1卷" in (row["novel_volume"] or "")
    # 结构化镜像进 novel_meta(写作门控/叙事人称读)
    nm = db.jload(row["novel_meta"], {})
    assert nm["world"]["power_system"] == "厨艺"
    assert nm["contract"]["pov"] == "third_limited"
    # 简介/题材写进 metadata(与「项目说明」共用槽位)
    md = db.jload(row["metadata"], {})
    assert md["genre"] == "都市重生"
    assert "爆炒" in md["intro"]
    # 主要角色入资产
    ch = db.q1("SELECT name, role_type FROM characters WHERE drama_id=?", (drama_id,))
    assert ch and ch["name"] == "陈灶" and ch["role_type"] == "lead"


def test_book_settings_requires_done_analysis(tmp_db):
    drama_id = _mk_drama()
    with pytest.raises(RuntimeError, match="先完成章节分析"):
        bi.generate_book_settings(drama_id)


def test_book_settings_never_duplicates_characters(tmp_db, monkeypatch):
    """重跑/重复导入不插重复角色行 —— 角色行是用户可编辑的资产,覆盖会毁掉
    用户改过的样貌/妆造。已有角色时直接跳过。"""
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    _done_analysis(drama_id)
    ts = db.now()
    db.ex("INSERT INTO characters(drama_id,name,role_type,created_at,updated_at)"
          " VALUES(?,?,?,?,?)", (drama_id, "用户手建", "lead", ts, ts))

    def fake(agent_type, prompt, **kw):
        if "提炼这本书本身的设定" in prompt:
            return _BOOK_SETTINGS_JSON
        if "这本书的全书总纲" in prompt:
            return json.dumps({"outline": "总纲"}, ensure_ascii=False)
        return json.dumps({"volumes": ""}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    out = bi.generate_book_settings(drama_id)
    assert out["characters"] == 0
    n = db.q1("SELECT COUNT(*) AS n FROM characters WHERE drama_id=?", (drama_id,))
    assert n["n"] == 1, "已有角色时不得再插"


def test_book_settings_retries_empty_outline_and_reports_missing(tmp_db, monkeypatch):
    """总纲阶段模型空转(回散文/解析不出)→ 重试 3 次;仍空则**明说缺什么**,
    绝不静默写空串 —— 此前任务报完成、总纲栏空白,用户以为整个设定没生成
    (2026-11-01 实测:重生之我是股神 总纲空,其余各段都写进去了)。"""
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    _done_analysis(drama_id)
    calls = {"outline": 0}

    def fake(agent_type, prompt, **kw):
        if "提炼这本书本身的设定" in prompt:
            return _BOOK_SETTINGS_JSON
        if "这本书的全书总纲" in prompt:
            calls["outline"] += 1
            return "模型吐了一段散文,没有 JSON 结构"       # 永远解析不出 outline
        return json.dumps({"volumes": "### 第1卷"}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    monkeypatch.setattr(bi.character_spec, "expand_many", lambda seed, lang=None: seed)
    out = bi.generate_book_settings(drama_id)
    assert calls["outline"] == 3, "总纲阶段应重试 3 次"
    assert out["missing"] == ["总纲"], "空板块必须上报 missing"
    row = db.q1("SELECT novel_outline, novel_volume FROM dramas WHERE id=?", (drama_id,))
    assert not (row["novel_outline"] or "").strip()
    assert "第1卷" in (row["novel_volume"] or ""), "其余板块照常写入"


def test_book_settings_reports_missing_volumes(tmp_db, monkeypatch):
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    _done_analysis(drama_id)

    def fake(agent_type, prompt, **kw):
        if "提炼这本书本身的设定" in prompt:
            return _BOOK_SETTINGS_JSON
        if "这本书的全书总纲" in prompt:
            return json.dumps({"outline": "总纲正文"}, ensure_ascii=False)
        return "又是一段没有结构的散文"

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    monkeypatch.setattr(bi.character_spec, "expand_many", lambda seed, lang=None: seed)
    out = bi.generate_book_settings(drama_id)
    assert out["missing"] == ["分卷"]
    assert out["outline"] > 0


def test_book_settings_prompts_describe_this_book(tmp_db, monkeypatch):
    """三段提示词必须是「总结这本书」,不得出现仿写的三条铁律(专名全换等)
    —— 那会把导入项目的设定写成另一本书。"""
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    _done_analysis(drama_id)
    prompts = []

    def fake(agent_type, prompt, **kw):
        prompts.append(prompt)
        if "提炼这本书本身的设定" in prompt:
            return _BOOK_SETTINGS_JSON
        if "这本书的全书总纲" in prompt:
            return json.dumps({"outline": "总纲"}, ensure_ascii=False)
        return json.dumps({"volumes": "### 第1卷"}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    monkeypatch.setattr(bi.character_spec, "expand_many", lambda seed, lang=None: seed)
    bi.generate_book_settings(drama_id)
    assert len(prompts) == 3
    for p in prompts:
        assert "专名全换" not in p, "混入了仿写铁律"
    # 设定与总纲阶段都要带节拍时间线(总结必须贴着原书情节)
    assert "情节节拍时间线" in prompts[1]
    assert "情节节拍时间线" in prompts[2]


def test_new_project_dialog_carries_book_src_only_for_novel(qapp):
    """「整书导入(可选)」只在写小说时出现、书路径只随 novel 传出 ——
    剧/漫/宣传/复刻不吃整本书正文。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from app.ui.new_project_dialog import NewProjectDialog
    dlg = NewProjectDialog()
    dlg._radios["novel"].setChecked(True)
    assert not dlg.book_row_host.isHidden(), "novel 应显示导入行"
    dlg.name_edit.setText("测试书")
    dlg._book_path = "C:/books/x.txt"
    assert dlg.result_data()["book_src"] == "C:/books/x.txt"
    dlg2 = NewProjectDialog()
    dlg2._radios["drama"].setChecked(True)
    assert dlg2.book_row_host.isHidden(), "drama 不应显示导入行"
    dlg2.name_edit.setText("测试剧")
    dlg2._book_path = "C:/books/x.txt"
    assert dlg2.result_data()["book_src"] == ""


# ── 分析空转防护(2026-11-01 实测:10 组节拍全空,假档案按 done 落库)──────

def test_analysis_empty_map_output_counts_as_failure(tmp_db, monkeypatch):
    """MAP 组模型空转(回空/不可解析)→ 重试后按**组失败**计数,绝不存空摘要。

    此前 extract_json 解析不出 → or {} → 空摘要当成功,Reduce 拿到全空输入。"""
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    attempts = {"n": 0}

    def fake_run(agent_type, prompt, **kw):
        if "结构分析师" in prompt:
            attempts["n"] += 1
            return "模型吐了一堆没有 JSON 的散文"     # 永远解析不出
        raise AssertionError("不应走到 Reduce")

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake_run))
    with pytest.raises(RuntimeError, match=r"全部.*组节拍抽取失败"):
        bi.run_analysis(drama_id)
    assert attempts["n"] == 3, "1 组 × 每组重试 3 次"


def test_analysis_reduces_garbage_issues_profile_to_error(tmp_db, monkeypatch):
    """Reduce 模型回 {issues:[…]} 的「礼貌拒绝」→ 不落库,报可读错误。

    此前这种假档案按 done 落库,仿写/设定基于空档案瞎编。"""
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)

    def fake_run(agent_type, prompt, **kw):
        if "结构分析师" in prompt:
            return MAP_JSON
        return json.dumps({"issues": ["段1至段10的节拍摘要均为空"],
                           "facts": []}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake_run))
    with pytest.raises(RuntimeError, match=r"分析没有产出可用档案.*节拍摘要均为空"):
        bi.run_analysis(drama_id)
    row = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
    assert "analysis" not in (db.jload(row["novel_meta"], {}) or {}), "假档案不得落库"


def test_imitation_rejects_garbage_profile(tmp_db, monkeypatch):
    """库里存着 {issues:…} 假档案(旧版落库的)→ 仿写/设定必须拒绝并指引重跑。"""
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?", (
        json.dumps({"analysis": {"status": "done", "chapters": 2,
                                 "profile": {"issues": ["空"], "facts": []}}},
                   ensure_ascii=False), drama_id))
    with pytest.raises(RuntimeError, match="仿写档案为空或不可用"):
        bi.run_imitation(drama_id)
    with pytest.raises(RuntimeError, match="仿写档案为空或不可用"):
        bi.generate_book_settings(drama_id)


# ── 保真度:提示词结构决定「生成的新书像不像原书」 ──────────────────

def test_imitation_prompts_keep_skeleton_fidelity(tmp_db, monkeypatch):
    """仿写三阶段必须把原书骨架喂足 —— 「生成的新书与原书差太多」的根因就在这。

    2026-11-02 用户实测:同一本书,Vue 版生成的新书还是同一题材同一骨架,
    Python 版改动过大。三条不变量锁死(均来自与上游 novel.ts 逐段比对):
      ① 设定阶段用**标签化**档案(原书题材/结构/世界观/冲突线/节奏模式/文风),
         不是 json 整坨 —— 整坨 JSON 在模型眼里是「待转换的数据」,
         标签化逐行才是「要照着写的骨架」;
      ② 分卷阶段带上**新书总纲**(上游同款),否则卷与卷的承接关系散掉;
      ③ 铁律第 3 条必须点名「人物配置与弧线、冲突线、爽点周期与文风」——
         此前只写「分卷节奏/章节密度/爽点间隔」,人物弧线与文风没被点名,
         模型就当自由发挥,骨架自然漂。
    """
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?", (
        json.dumps({"analysis": {"status": "done", "chapters": 30,
                                 "profile": {"genre": "都市",
                                             "book_structure": "开篇钩子→压制→爆发",
                                             "worldview": "现代都市",
                                             "conflict_lines": ["复仇线"],
                                             "rhythm_patterns": "每3章一爽点",
                                             "style_features": "短句快节奏",
                                             "main_characters": [{"name": "林晚"}]},
                                 "plot_timeline": [
                                     {"chapters": [1, 12], "summary": "前段",
                                      "beats": ["b1", "b2"]}],
                                 "analyzed_at": db.now()}}, ensure_ascii=False),
        drama_id))
    prompts = []

    def fake(agent_type, prompt, **kw):
        prompts.append(prompt)
        if "书级设定" in prompt:
            return SETTINGS_JSON
        if "写新书的总纲" in prompt:
            return json.dumps({"outline": "总纲正文XYZ"}, ensure_ascii=False)
        return json.dumps({"volumes": "### 第1卷"}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    monkeypatch.setattr(bi.character_spec, "expand_many", lambda seed, lang=None: seed)
    bi.run_imitation(drama_id)

    settings_prompt = next(p for p in prompts if "书级设定" in p)
    volumes_prompt = next(p for p in prompts if "分卷战略" in p)
    # ① 标签化档案
    assert "原书题材:都市" in settings_prompt
    assert "结构:开篇钩子→压制→爆发" in settings_prompt
    assert "节奏模式:每3章一爽点" in settings_prompt
    assert "文风:短句快节奏" in settings_prompt
    # ② 分卷带总纲 + 节拍时间线
    assert "总纲正文XYZ" in volumes_prompt
    assert "情节节拍时间线" in volumes_prompt
    assert "b1 → b2" in volumes_prompt
    # ③ 铁律点名要沿用的骨架维度
    assert "人物配置与弧线" in settings_prompt
    assert "冲突线" in settings_prompt
    assert "文风" in settings_prompt


def test_imitation_fails_when_outline_empty(tmp_db, monkeypatch):
    """总纲空 → 明确失败,不建空壳书(上游同款:仿写总纲输出缺少 outline 即抛错)。

    静默建出一本没总纲的新书,用户在向导里看不出哪里出了问题。
    """
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?", (
        json.dumps({"analysis": {"status": "done", "chapters": 30,
                                 "profile": {"genre": "都市"},
                                 "plot_timeline": [], "analyzed_at": db.now()}},
                   ensure_ascii=False), drama_id))

    def fake(agent_type, prompt, **kw):
        if "书级设定" in prompt:
            return SETTINGS_JSON
        return json.dumps({"foo": 1}, ensure_ascii=False)   # 合法 JSON,但没有 outline

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    before = db.q1("SELECT COUNT(*) c FROM dramas")["c"]
    with pytest.raises(RuntimeError, match="仿写总纲输出为空"):
        bi.run_imitation(drama_id)
    after = db.q1("SELECT COUNT(*) c FROM dramas")["c"]
    assert after == before, "总纲为空时不得建出新项目"


def test_imitation_fails_when_volumes_empty(tmp_db, monkeypatch):
    """分卷空 → 明确失败,不建空壳书(上游同款)。"""
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?", (
        json.dumps({"analysis": {"status": "done", "chapters": 30,
                                 "profile": {"genre": "都市"},
                                 "plot_timeline": [], "analyzed_at": db.now()}},
                   ensure_ascii=False), drama_id))

    def fake(agent_type, prompt, **kw):
        if "书级设定" in prompt:
            return SETTINGS_JSON
        if "写新书的总纲" in prompt:
            return json.dumps({"outline": "总纲正文"}, ensure_ascii=False)
        return json.dumps({"bar": 2}, ensure_ascii=False)   # 合法 JSON,但没有 volumes

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    before = db.q1("SELECT COUNT(*) c FROM dramas")["c"]
    with pytest.raises(RuntimeError, match="仿写分卷输出为空"):
        bi.run_imitation(drama_id)
    after = db.q1("SELECT COUNT(*) c FROM dramas")["c"]
    assert after == before, "分卷为空时不得建出新项目"


# ── 中断可续跑:心跳落盘 + running 态续跑 ───────────────────────────

def test_analysis_heartbeat_persists_progress(tmp_db, monkeypatch):
    """分析运行中把已成功组落盘(上游 persistAnalyzeJob 同款)。

    进程中途被杀/机器休眠时,断点不丢,可续跑 —— 此前只在暂停/完成时落盘,
    中途崩溃 = 从头再来,上游配额白烧一遍。
    """
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)                  # GROUP=2 → 1 组
    monkeypatch.setattr(bi, "GROUP", 2)
    monkeypatch.setattr(bi, "HEARTBEAT_S", 0.0)  # 每组都落盘
    metas = []
    real_ex = bi.db.ex

    def spy_ex(sql, args=()):
        if "UPDATE dramas SET novel_meta" in sql:
            metas.append(args[0])
        return real_ex(sql, args)

    monkeypatch.setattr(bi.db, "ex", spy_ex)

    def fake_run(agent_type, prompt, **kw):
        return MAP_JSON if "结构分析师" in prompt else json.dumps(
            {"genre": "都市", "main_characters": []}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake_run))
    bi.run_analysis(drama_id)

    running = [json.loads(m)["analysis"] for m in metas
               if json.loads(m).get("analysis", {}).get("status") == "running"]
    assert running, "心跳必须写过 running 态的 analysis"
    assert len(running[0]["partial_chunks"]) == 1, "已成功组必须落盘"
    assert running[0]["done"] == 1


def test_analysis_resume_accepts_interrupted_running_state(tmp_db, monkeypatch):
    """落盘是 running(上次跑着跑着进程没了)时也能续跑(上游 analyze-resume 同款)。

    此前只认 paused —— 进程一崩,断点就死在库里,用户只能从头再烧一遍配额。
    """
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 4)
    monkeypatch.setattr(bi, "GROUP", 2)          # 2 组
    ran = {"n": 0}

    def fake_run(agent_type, prompt, **kw):
        if "结构分析师" in prompt:
            ran["n"] += 1
            return MAP_JSON
        return json.dumps({"genre": "都市", "main_characters": []}, ensure_ascii=False)

    # 落盘成「running」态(崩溃现场):第 1 组已成功
    stale = (datetime.now(timezone.utc) - timedelta(seconds=60)
             ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?", (
        json.dumps({"analysis": {
            "status": "running", "chapters": 4, "done": 1, "failed": 0,
            "total": 1, "pause_count": 0, "updated_at": stale,
            "partial_chunks": [
                {"_seg": 1, "_ok": True, "summary": "s1", "beats": ["b1"],
                 "characters": [], "settings": "", "hooks": ""}]}},
            ensure_ascii=False), drama_id))
    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake_run))
    out = bi.run_analysis(drama_id, resume=True)
    assert out["status"] == "done"
    assert ran["n"] == 1, "已成功的那组不该重跑"


def test_book_meta_requires_fields_and_reports(tmp_db, monkeypatch):
    """AI 起草简介/题材:字段不齐必须报错,不能静默返回空(上游 askConceptJson 同款)。"""
    drama_id = _mk_drama()
    db.ex("""INSERT INTO episodes(drama_id,episode_number,title,content,status,
             resolution,created_at,updated_at) VALUES(?,1,'第1章',?,'draft','720p',?,?)""",
          (drama_id, "正文" * 300, db.now(), db.now()))
    monkeypatch.setattr(bi.runner, "run_agent_json",
                        _as_json_runner(lambda *a, **k: "模型只吐了一段散文,没有 JSON"))

    # 散文输出:既解析不出 JSON,也抠不出字段 —— 两种都要明确报错,不能静默返回空
    with pytest.raises(RuntimeError, match=r"无法解析为 JSON|缺少字段"):
        bi.generate_book_meta(drama_id)


def test_analysis_refuses_concurrent_run_same_project(tmp_db, monkeypatch):
    """同一个项目的分析不许并发跑(上游 analyze-book「分析已在进行中」同款)。

    心跳落盘把「running」写进 novel_meta 后,UI 的「恢复分析」在分析跑着时也是亮
    的 —— 没这道闸,用户一点就起第二个分析,两批 worker 抢同一份 partial_chunks。
    """
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    monkeypatch.setattr(bi, "GROUP", 2)

    def fake_run(agent_type, prompt, **kw):
        # 在分析**进行中**再起一个 → 必须被拒
        with pytest.raises(RuntimeError, match="分析正在进行中"):
            bi.run_analysis(drama_id)
        return MAP_JSON if "结构分析师" in prompt else json.dumps(
            {"genre": "都市", "main_characters": []}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake_run))
    out = bi.run_analysis(drama_id)
    assert out["status"] == "done"
    # 跑完之后名额已释放,再跑一次不再被拒
    out2 = bi.run_analysis(drama_id)
    assert out2["status"] == "done"


# ── 系统提示覆盖:workspace 的 md 是「别的 agent」的契约 ────────────────

def test_pipeline_overrides_workspace_system_prompt(tmp_db, monkeypatch):
    """book_import 必须覆盖 workspace 的系统提示 —— 那两份 md 是**别的任务**的契约。

    两处坑(2026-11-02 端到端实跑踩出来):
      · novel_planner.md 末尾写「**只输出工具调用,不要输出规划文本**」→ 模型回
        {"name":"save_novel_settings","arguments":{...}};它解析得出来(合法 JSON),
        却一个设定字段都没有 → 仿写建出一本空壳书,新书与原书毫无关系;
      · novel_reviewer.md 规定的是**章节审校** schema {"issues":[…],"facts":[…]} →
        分析阶段拿到合法审校 JSON,没有 summary/beats → 「节拍摘要为空」。
    两者都表现为「模型明明回了东西,程序却说没有内容」。
    """
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    _done_analysis(drama_id)
    systems = []

    def fake(agent_type, prompt, **kw):
        systems.append((agent_type, kw.get("system") or ""))
        if "书级设定" in prompt:
            return SETTINGS_JSON
        if "写新书的总纲" in prompt:
            return json.dumps({"outline": "总纲正文"}, ensure_ascii=False)
        return json.dumps({"volumes": "### 第1卷"}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    monkeypatch.setattr(bi.character_spec, "expand_many", lambda seed, lang=None: seed)
    bi.run_imitation(drama_id)

    assert systems, "至少要调到一次模型"
    for agent_type, system in systems:
        assert system, f"{agent_type} 没覆盖系统提示 —— 会按 workspace md 的 schema 回"
        # 覆盖后的提示必须声明「无工具」,且不得带 workspace md 的特征串
        assert "没有工具" in system
        assert "只输出工具调用" not in system, "不能带 planner md 的「只输出工具调用」"
        assert '"issues"' not in system, "不能带审校 md 的 issues schema"


def test_imitation_rejects_tool_call_payload(tmp_db, monkeypatch):
    """模型回工具调用 JSON → 必须报错,不能当成设定建出空壳书。

    {"name":"save_novel_settings","arguments":{...}} 是**合法 JSON**,解析得出来,
    但里面没有书名/人物/世界观 —— 拿它当设定,建出来的新书与原书毫无关系。
    """
    drama_id = _mk_drama()
    _seed_chapters(drama_id, 2)
    db.ex("UPDATE dramas SET novel_meta=? WHERE id=?", (
        json.dumps({"analysis": {"status": "done", "chapters": 30,
                                 "profile": {"genre": "都市"},
                                 "plot_timeline": [], "analyzed_at": db.now()}},
                   ensure_ascii=False), drama_id))

    def fake(agent_type, prompt, **kw):
        return json.dumps({"name": "save_novel_settings",
                           "arguments": {"section": "outline", "content": "总纲"}},
                          ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent_json", _as_json_runner(fake))
    before = db.q1("SELECT COUNT(*) c FROM dramas")["c"]
    with pytest.raises(RuntimeError, match="工具调用"):
        bi.run_imitation(drama_id)
    after = db.q1("SELECT COUNT(*) c FROM dramas")["c"]
    assert after == before, "工具调用不得被当成设定建出新项目"
