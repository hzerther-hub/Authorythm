# -*- coding: utf-8 -*-
"""整书导入 → 分析 → 仿写 三段式的对齐回归测试。

对齐基准:原版 E:\\xiaoshuo backend/src/routes/novel.ts(2df744b,此后上游未改)。
锁住的关键不变量:
- 切章:短书(≥3 个「第N章」)必须按标题切,不得掉进 2 万字窗口兜底
        (此前阈值写死 32,3-31 章的书全被窗口切碎);
- 切章:分隔线**下方**短标题(站点导出常见格式,原版唯一口径)能切出章;
- 分析:断点续跑跳过已成功组;失败率过高暂停并落盘 partial_chunks;
- 仿写:planned_chapters 缺失时兜底「原书章数 ‖ 100」,不再兜底 1;
- 仿写:总纲阶段也注入节拍时间线(否则写出来的是「同题材新书」不是「同骨架新书」)。

测试不碰真实库;LLM 一律 monkeypatch 打桩。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core import db
from app.pipeline import book_import as bi


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
    out = bi.import_book(drama_id, data=text.encode("gbk"))
    assert out["encoding"] == "gbk"
    assert out["chapters"] == 3
    n = db.q1("SELECT COUNT(*) c FROM episodes WHERE drama_id=?", (drama_id,))["c"]
    assert n == 3                                  # 旧章已替换
    meta = db.jload(db.q1("SELECT novel_meta FROM dramas WHERE id=?",
                          (drama_id,))["novel_meta"], {})
    assert meta["imported"]["chapters"] == 3


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

    monkeypatch.setattr(bi.runner, "run_agent", fake_run)
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

    monkeypatch.setattr(bi.runner, "run_agent", always_fail)
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

    monkeypatch.setattr(bi.runner, "run_agent", fake)
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
    assert "林晚,女主" in d
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
        if "设定" in prompt and "仿写档案" in prompt:
            return SETTINGS_JSON
        if "总纲" in prompt:
            return json.dumps({"outline": "总纲正文"}, ensure_ascii=False)
        return json.dumps({"volumes": "### 第1卷"}, ensure_ascii=False)

    monkeypatch.setattr(bi.runner, "run_agent", fake)
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
    monkeypatch.setattr(bi.runner, "run_agent", fake2)
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

    monkeypatch.setattr(bi.runner, "run_agent", fake)
    bi.generate_book_meta(drama_id)
    assert "MARK1" in got["prompt"]
    assert "MARK2" in got["prompt"] and "MARK3" in got["prompt"]
