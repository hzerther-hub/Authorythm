# -*- coding: utf-8 -*-
"""剧本可拍性质量门(`app.pipeline.script_quality`)的回归护栏。

背景:2026-10-20 某次短剧改写产出 11 场剧本,全部发生在同一间出租屋,每场只有
一个人的画外音 —— 这种剧本拆不成有对手戏的分镜,生成了视频也只是一个人对着
空气说话。本模块把「能不能拍」变成可执行指标,不合格的剧本打回重写,仍不合格
直接报错不落库。

覆盖:
- 坏剧本(满篇画外音/单人独角戏/同一间屋)→ 体检命中
- 项目标准样例(SAMPLE_SCRIPT)→ 体检通过
- 15 语言画外音标记(中英日韩德西…)→ 命中
- 地点高度重复 → 命中;场景数少时���判
- enforce:返工成功→返回新剧本;返工仍失败→RuntimeError
- 集成:rewrite_script / outline_to_script 遇到坏剧本 → RuntimeError 且**不落库**
"""
from __future__ import annotations

from unittest import mock

import pytest

from app.core import db
from app.core.db import SAMPLE_SCRIPT
from app.pipeline import novel, rewriter, script_quality

# 实测产出的坏剧本:一个人在一间屋里说了一整集画外音
BAD_SCRIPT = """## S01 | 内景 · 石榴巷出租屋 | 清晨

天花板上有一块缺口形的水渍，边缘泛黄，中心是一圈深棕色的霉斑。

林岁晚：（画外音，声音很轻）这件衣服……我认得。前年在地摊花三十五块钱买的。

## S02 | 内景 · 石榴巷出租屋 | 清晨

她撩起被角坐在床沿。石榴巷清晨的声音从窗户底下涌进来。

林岁晚：（画外音，缓慢）风很大。她的头发被吹得贴在脸颊上。

## S03 | 内景 · 出租屋 · 清晨

手机亮了一下。她侧头去看。2013年7月19日，星期五，凌晨5:12。

林岁晚：（画外音，声音微微发颤）2013年……7月19日……

## S04 | 内景 · 出租屋 · 清晨

她慢慢放下手机，重新坐回床沿。

林岁晚：（画外音，声音很轻）二十八。二十八岁那年的林岁晚住在这间屋子里。

## S05 | 内景 · 出租屋 · 清晨

她站起来，慢慢走到窗前。

林岁晚：（画外音，更轻）她不是要说大话。她是要重新做一个真人。

## S06 | 内景 · 出租屋 · 清晨

她走到那张瘸了一条腿的折叠桌前，把手机插上电。

林岁晚：（画外音，带着一点点苦涩）哪怕这意味着，她现在必须承认，自己连下个月的房租都交不起。
"""

# 合格剧本:有对手戏、台词说出口、场景不重复
GOOD_SCRIPT = """## S01 | 外景 · 石榴巷口 | 清晨

三轮车吱呀着推过去。林岁晚攥着手机站在巷口，屏幕还亮着。

房东老刘：（叼着烟）小林，你那房钱，到底什么时候给？

林岁晚：（把手机塞回兜里）今天我发工资。今天就给。

## S02 | 内景 · 城中村小公司 | 上午

传真机吐出一张纸。林岁晚接住，外联主管在门口敲了敲门框。

外联主管：（急促）隆达那边十点开会，材料你拷好没有？

林岁晚：（把文件塞进包里）拷好了，在地铁上给您。

## S03 | 内景 · 出租屋 | 午后

她把手机搁在折叠桌上，指尖在桌沿敲了两下，又收回来。

房东老刘：（电话里）你倒是回个话啊。

林岁晚：（按下静音键）我说了，今天。
"""


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """与 test_outline_to_script 同一套隔离方式:改 DB_PATH + 清 thread-local。"""
    static = tmp_path / "static"
    for sub in ("images", "videos", "narration", "merged", "comics", "uploads", "covers"):
        (static / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "t.sqlite3")
    monkeypatch.setattr(db.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db.config, "STATIC_DIR", static)
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    yield tmp_path
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


def _setup_episode(content=""):
    db.ex(
        "INSERT INTO ai_service_configs(service_type,provider,base_url,api_key,model,is_active,created_at,updated_at)"
        " VALUES('text','openai','https://api.openai.com/v1','sk-test','gpt-test',1,?,?)",
        (db.now(), db.now()),
    )
    did = db.ex("INSERT INTO dramas(title,language,created_at,updated_at) VALUES(?,?,?,?)",
                ("测试剧", "zh", db.now(), db.now()))
    eid = db.ex("INSERT INTO episodes(drama_id,episode_number,script_content,content,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?)", (did, 1, "", content, db.now(), db.now()))
    return did, eid


# ---------------------------------------------------------------- 检测

def test_bad_script_is_rejected():
    """满篇画外音 + 单人独角戏 + 同一间屋 → 体检命中。"""
    problems = script_quality.check(BAD_SCRIPT)
    assert problems, "坏剧本必须被拦下"
    joined = " ".join(problems)
    assert "画外音" in joined
    assert "独白" in joined or "对手戏" in joined
    assert "地点" in joined


def test_sample_script_passes():
    """项目标准样例必须通过体检(否则会误杀正常剧本)。"""
    assert script_quality.check(SAMPLE_SCRIPT) == []


def test_good_script_passes():
    assert script_quality.check(GOOD_SCRIPT) == []


def test_stats_of_bad_script():
    st = script_quality.analyze(BAD_SCRIPT)
    assert st.scenes == 6
    assert st.vo_lines == 6
    assert st.speakers == ["林岁晚"]
    assert st.monologue_scenes == 6
    assert st.vo_ratio == 1.0


@pytest.mark.parametrize("line,marker", [
    ("林岁晚：（画外音）我回来了。", "zh"),
    ("ANNA: (voice-over) I came back.", "en"),
    ("アンナ：（ボイスオーバー）帰ってきた。", "ja"),
    ("안나：(화면 밖 목소리) 돌아왔다.", "ko"),
    ("ANNA: (Stimme) Ich bin zurück.", "de"),
    ("ANA: (en off) He regresado.", "es"),
    ("ANA: (voz off) Voltou.", "pt"),
    ("Анна: (за кадром) Я вернулась.", "ru"),
])
def test_vo_markers_detected_multilingual(line, marker):
    """多语言画外音标记都要能认出来(项目支持 15 种语言)。"""
    script = f"## S01 | 内景 · 房间 | 白天\n\n{line}\n"
    st = script_quality.analyze(script)
    assert st.vo_lines == 1, f"{marker} 没被识别成画外音"


def test_dialogue_without_vo_is_not_flagged():
    """正常台词里出现「内心」等词但不带画外音标记 → 不算画外音。"""
    script = ("## S01 | 内景 · 办公室 | 白天\n\n"
              "老王：（皱眉）你这内心倒是挺强。\n")
    assert script_quality.analyze(script).vo_lines == 0


def test_location_repetition_flagged():
    """6 场全在同一地点 → 命中地点重复。"""
    blocks = []
    for i in range(1, 7):
        blocks.append(f"## S{i:02d} | 内景 · 出租屋 | 白天\n\n她坐在床沿{i}。\n\n"
                      "老刘：（电话里）你倒是回话。\n")
    problems = script_quality.check("".join(blocks))
    assert any("地点" in p for p in problems)


def test_few_scenes_skip_location_check():
    """场景数太少时不判地点重复(3 场 1 地点也正常,只要有对手戏)。"""
    blocks = []
    for i in range(1, 4):
        blocks.append(f"## S{i:02d} | 内景 · 出租屋 | 白天\n\n她坐在床沿{i}。\n\n"
                      "老刘：（电话里）你倒是回话。\n\n"
                      "林岁晚：（低声）我知道了。\n")
    assert script_quality.check("".join(blocks)) == []


def test_no_scene_header_returns_no_problems():
    """没有场景头 → 本模块不报(格式问题交给格式校验)。"""
    assert script_quality.check("就是一段没有场景头的文字") == []


# ---------------------------------------------------------------- 返工

def test_enforce_returns_repaired_script():
    calls = []

    def repair(prompt):
        calls.append(prompt)
        return GOOD_SCRIPT

    out = script_quality.enforce(BAD_SCRIPT, repair)
    assert out == GOOD_SCRIPT
    assert len(calls) == 1
    assert "画外音" in calls[0], "返工指令要点明问题"


def test_enforce_raises_when_repair_still_bad():
    def repair(prompt):
        return BAD_SCRIPT

    with pytest.raises(RuntimeError, match="剧本质量不合格"):
        script_quality.enforce(BAD_SCRIPT, repair)


def test_enforce_passes_through_good_script_without_calling_model():
    called = []

    def repair(prompt):
        called.append(prompt)
        return ""

    assert script_quality.enforce(GOOD_SCRIPT, repair) == GOOD_SCRIPT
    assert called == []


def test_try_repair_reports_remaining_problems():
    ok, problems = script_quality.try_repair(BAD_SCRIPT, lambda p: BAD_SCRIPT)
    assert ok == ""
    assert problems


# ---------------------------------------------------------------- 集成

def test_rewrite_script_rejects_monologue_and_keeps_db_clean(tmp_db):
    """rewrite_script 拿到坏剧本 → RuntimeError,且**不落库**。"""
    _did, eid = _setup_episode("原始小说内容,足够长,这里随便写点内容凑够长度用于改写。")
    with (mock.patch("app.pipeline.rewriter.runner.run_agent", return_value=BAD_SCRIPT),
          pytest.raises(RuntimeError, match="剧本质量不合格")):
        rewriter.rewrite_script(eid, config_id=None)
    row = db.q1("SELECT script_content FROM episodes WHERE id=?", (eid,))
    assert row["script_content"] == "", "坏剧本不能落库"


def test_rewrite_script_writes_repaired_script(tmp_db):
    """坏剧本 → 返工后的好剧本 → 落库。"""
    _did, eid = _setup_episode("原始小说内容,足够长,这里随便写点内容凑够长度用于改写。")
    with mock.patch("app.pipeline.rewriter.runner.run_agent",
                    side_effect=[BAD_SCRIPT, GOOD_SCRIPT]):
        out = rewriter.rewrite_script(eid, config_id=None)
    assert out == GOOD_SCRIPT
    row = db.q1("SELECT script_content FROM episodes WHERE id=?", (eid,))
    assert row["script_content"] == GOOD_SCRIPT


def test_outline_to_script_rejects_monologue(tmp_db):
    """梗概扩写产出坏剧本 → RuntimeError,不落库。"""
    _did, eid = _setup_episode()
    with (mock.patch("app.pipeline.novel.runner.run_agent_json",
                     return_value={"script": BAD_SCRIPT}),
          pytest.raises(RuntimeError, match="剧本质量不合格")):
        novel.outline_to_script("这是一个足够长的故事梗概,讲了一个人重生之后的故事,"
                                 "包含人物、冲突和走向,长度超过三十个字。", episode_id=eid)
    row = db.q1("SELECT script_content FROM episodes WHERE id=?", (eid,))
    assert row["script_content"] == ""


def test_outline_to_script_accepts_good_script(tmp_db):
    _did, eid = _setup_episode()
    with mock.patch("app.pipeline.novel.runner.run_agent_json",
                    return_value={"script": GOOD_SCRIPT}):
        out = novel.outline_to_script("这是一个足够长的故事梗概,讲了一个人重生之后的故事,"
                                      "包含人物、冲突和走向,长度超过三十个字。", episode_id=eid)
    assert out == GOOD_SCRIPT.strip()
