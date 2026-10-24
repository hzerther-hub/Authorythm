# -*- coding: utf-8 -*-
"""章节名生成 gen_chapter_title —— 此前**零测试覆盖**,且它直接写 episodes.title。

为什么必须补:
1. 它有「仅当标题是占位符时才覆盖用户已改好的名字」这条守卫。这条守卫一旦失效,
   用户手打的章节名会被 AI 结果静默覆盖,而且**不可撤销**(没有历史版本)。
   `tests/test_no_db_pollution.py` 的 autouse 守卫只查 dramas 表,
   拦不住 episodes.title 被测试覆盖。
2. 它直写用户数据,所以本文件所有落库路径都走临时库,一个字节都不碰 data/yihao.sqlite3。
3. 它是「项目内容语言」落地到标题的唯一点,语言错了用户一眼就能看见。
"""
from __future__ import annotations

import pytest

from app.core import db
from app.pipeline import novel as nv


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "title.sqlite3")
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


def _make_episode(drama_id: int, *, title: str = "", content: str = "",
                  episode_number: int = 1, language: str = "auto") -> int:
    db.ex("INSERT INTO dramas(title,language,created_at,updated_at) VALUES(?,?,?,?)",
          ("测试项目", language, db.now(), db.now()))
    got = db.q1("SELECT id FROM dramas ORDER BY id DESC LIMIT 1")
    did = int(got["id"])
    db.ex("""INSERT INTO episodes(drama_id,episode_number,title,content,
                created_at,updated_at) VALUES(?,?,?,?,?,?)""",
          (did, episode_number, title, content or "正文" * 60, db.now(), db.now()))
    return int(db.q1("SELECT id FROM episodes ORDER BY id DESC LIMIT 1")["id"])


def _fake_agent(payload, calls=None):
    def _run(agent_type, user_prompt, **kwargs):
        if calls is not None:
            calls.append((agent_type, user_prompt, kwargs))
        return payload
    return _run


# ---------------------------------------------------------------- 占位符守卫

def test_reverse_extraction_wins_and_skips_llm(tmp_db, monkeypatch):
    """标题为空/占位,且正文首行已有 `# 名字` → 直接反向提取,不调模型。

    这才是「避免覆盖用户已改好的名字」那道守卫的真实语义:守卫的是**反向提取
    的写入**,不是 AI 分支。AI 分支(`_apply_chapter_title`)按设计就是「用户主动
    点生成 → 覆盖」,它在 UI 上不可达于已命名剧集 —— 按钮的显隐由
    `project_page._chapter_name_missing` 判定,只有占位标题才显示。
    """
    ep_id = _make_episode(1, title="第 1 集", content="# 龙啸九天\n\n" + "正文" * 60)
    calls = []
    monkeypatch.setattr(nv.runner, "run_agent", _fake_agent("AI 新标题", calls))

    name, src = nv.gen_chapter_title(ep_id)

    assert (name, src) == ("龙啸九天", "content")
    assert calls == [], "有可用标题时不该白跑一次模型"
    assert db.q1("SELECT title FROM episodes WHERE id=?", (ep_id,))["title"] == "龙啸九天"


def test_ai_branch_overwrites_placeholder(tmp_db, monkeypatch):
    """标题是占位符时,AI 结果才允许写入。"""
    ep_id = _make_episode(1, title="第 1 集", content="正文" * 60)
    calls = []
    monkeypatch.setattr(nv.runner, "run_agent", _fake_agent("龙啸九天", calls))
    monkeypatch.setattr(nv, "prose_config_id", lambda: 4242)

    name, src = nv.gen_chapter_title(ep_id)

    assert (name, src) == ("龙啸九天", "ai")
    assert db.q1("SELECT title FROM episodes WHERE id=?", (ep_id,))["title"] == "龙啸九天"


def test_title_written_without_episode_prefix(tmp_db, monkeypatch):
    """落库存**纯标题**,不带「第N集」—— 集号是 episode_number 的职责。"""
    ep_id = _make_episode(1, title="第 1 集", content="正文" * 60, episode_number=3)
    monkeypatch.setattr(nv.runner, "run_agent", _fake_agent("龙啸九天"))
    monkeypatch.setattr(nv, "prose_config_id", lambda: 4242)

    nv.gen_chapter_title(ep_id)

    stored = db.q1("SELECT title FROM episodes WHERE id=?", (ep_id,))["title"]
    assert stored == "龙啸九天", f"落库标题不该带集号前缀: {stored!r}"


# ---------------------------------------------------------------- 语言

def test_project_language_is_forwarded(tmp_db, monkeypatch):
    """项目内容语言=fr → 传给 run_agent,且提示词里明确点名法语。"""
    ep_id = _make_episode(1, title="第 1 集", content="Il est une fois une histoire." * 8,
                          language="fr")
    calls = []
    monkeypatch.setattr(nv.runner, "run_agent", _fake_agent("Le dragon", calls))
    monkeypatch.setattr(nv, "prose_config_id", lambda: 4242)

    nv.gen_chapter_title(ep_id)

    assert calls, "AI 分支应调一次模型"
    _, user_prompt, kwargs = calls[0]
    assert kwargs.get("lang") == "fr", f"lang 没透传: {kwargs.get('lang')!r}"
    assert "French" in user_prompt, "提示词里应显式点名目标语言"


def test_lang_is_optional_and_falls_back_inside_function(tmp_db, monkeypatch):
    """调用点不传 lang 也要按项目语言走(兜底写在函数体内,AGENTS.md 的纪律)。"""
    ep_id = _make_episode(1, title="第 1 集", content="正文" * 60, language="ja")
    calls = []
    monkeypatch.setattr(nv.runner, "run_agent", _fake_agent("竜", calls))
    monkeypatch.setattr(nv, "prose_config_id", lambda: 4242)

    nv.gen_chapter_title(ep_id)          # 不传 lang

    assert calls[0][2].get("lang") == "ja"


@pytest.mark.parametrize("sample,expect", [
    ("这是一段纯中文的正文内容用来判断书写系统。", "12 个汉字"),
    ("Ceci est une histoire en français pour le test.", "6 个词"),
    ("これは日本語のテスト用の本文です。", "12 个汉字"),
])
def test_length_rule_follows_writing_system(sample, expect):
    """长度约束按书写系统分档,不再一刀切「12 个汉字」。

    12 个拉丁字母连一个像样的法语标题都装不下,照搬会让模型给出缩写到看不懂的词。
    """
    rule = nv._chapter_title_length_rule("fr", sample)
    assert expect in rule, f"样本 {sample[:20]!r} 的约束应是 {expect},实得 {rule!r}"


# ---------------------------------------------------------------- 前缀剥除

@pytest.mark.parametrize("title,num,expect", [
    ("第 1 集 夜谈", 1, "夜谈"),
    ("第1集 夜谈", 1, "夜谈"),
    ("第  1  集  夜谈", 1, "夜谈"),
    ("夜谈", 1, "夜谈"),
    ("", 1, ""),
    ("第 2 集 倒叙", 5, "第 2 集 倒叙"),      # 集号对不上,不剥
    ("第1章 裁员后我打开了青岚界", 1, "第1章 裁员后我打开了青岚界"),  # 「章」不是集号
])
def test_strip_episode_prefix(title, num, expect):
    assert nv.strip_episode_prefix(title, num) == expect


def test_placeholder_detection():
    assert nv.is_placeholder_episode_title("", 1)
    assert nv.is_placeholder_episode_title("第 1 集", 1)
    assert nv.is_placeholder_episode_title("第 3 集", 5)      # 集号对不上也算占位
    assert not nv.is_placeholder_episode_title("龙啸九天", 1)


def test_extract_title_handles_localized_episode_prefix():
    """非中文正文首行也要能反向提取,否则白跑一次 AI 调用。"""
    assert nv.extract_title_from_content("# Le retour du dragon\n\n正文...") == "Le retour du dragon"
    assert nv.extract_title_from_content("Épisode 3 · Le retour\n\n正文...") == "Le retour"
    assert nv.extract_title_from_content("第3集 归乡的井\n\n正文...") == "归乡的井"
    assert nv.extract_title_from_content("这是一段正文,没有标题行。") == ""
