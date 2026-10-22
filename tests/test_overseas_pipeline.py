# -*- coding: utf-8 -*-
"""海外题材改写 · 流水线与落库。

**测试不许碰真实库**:`data/yihao.sqlite3` 是用户数据,落库路径全部走临时库。
LLM 一律 monkeypatch 打桩,不真调模型。
"""
from __future__ import annotations

import json

import pytest

from app.core import db
from app.pipeline import overseas


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "oversea.sqlite3")
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


DIAG_JSON = {
    "level": "B",
    "level_reason": "主线可留,文化专名要换",
    "diagnosis": {"setting": {"score": 2, "notes": "货币单位要改"},
                   "structure": {"score": 1, "notes": "开篇没钩子"},
                   "pacing": {"score": 2, "notes": "章末弱"},
                   "language": {"score": 2, "notes": "自指观察"},
                   "compliance": {"score": 2, "notes": "全角标点"}},
    "issues": [{"type": "自指观察", "quote": "我的脸红了", "fix": "改成手指发白"}],
    "opening": {"hook": "电话", "payoff_chapter": 2, "notes": "以电话开场"},
    "glossary": [{"source": "林晚", "target": "Lin Wan", "type": "人名", "note": "女主"}],
    "culture_mappings": [{"source": "总裁", "target": "the CEO", "note": "职位"}],
}


def _fake_run_agent(payload):
    def _run(agent_type, user_prompt, **kwargs):
        _run.calls.append((agent_type, user_prompt, kwargs))
        return payload
    _run.calls = []
    return _run


# ---------------------------------------------------------------- 诊断

def test_diagnose_returns_level_and_glossary(monkeypatch):
    fake = _fake_run_agent(json.dumps(DIAG_JSON, ensure_ascii=False))
    monkeypatch.setattr(overseas.runner, "run_agent", fake)
    monkeypatch.setattr(overseas.runner, "extract_json",
                        lambda t: json.loads(t))
    res = overseas.diagnose(source="我的脸红了。", platform="goodnovel",
                            category="billionaire")
    assert res["level"] == "B"
    assert res["glossary"]["林晚"] == "Lin Wan"
    # 品类术语种子要兜底补上(模型漏抽的专名)
    assert res["glossary"].get("霸总") == "the CEO"
    assert res["culture_mappings"][0]["target"] == "the CEO"
    # 规则片段要进 prompt
    assert "GoodNovel" in fake.calls[0][1]


def test_diagnose_raises_on_empty_source():
    with pytest.raises(ValueError):
        overseas.diagnose(source="   ", platform="goodnovel", category="billionaire")


def test_diagnose_uses_config_fallback(monkeypatch):
    """config_id 传 None 时要回落到全局默认文本模型,不能静默传 None 出去。"""
    from app.ai import registry
    fake = _fake_run_agent(json.dumps(DIAG_JSON, ensure_ascii=False))
    monkeypatch.setattr(overseas.runner, "run_agent", fake)
    monkeypatch.setattr(overseas.runner, "extract_json", lambda t: json.loads(t))
    monkeypatch.setattr(registry, "default_config",
                        lambda st, cid=None: {"id": 4242})
    overseas.diagnose(source="一段中文。", platform="goodnovel",
                      category="billionaire")
    assert fake.calls[0][2]["config_id"] == 4242


def test_default_text_config_survives_none(monkeypatch):
    """default_config 返回 None 时不能 AttributeError(设置页崩的老坑)。"""
    from app.ai import registry
    monkeypatch.setattr(registry, "default_config", lambda st, cid=None: None)
    assert overseas._default_text_config() is None


# ---------------------------------------------------------------- 改写

def test_rewrite_strips_think_and_fence(monkeypatch):
    payload = ("<think>先想一下</think>\n\n```\nAt midnight she waited.\n```")
    fake = _fake_run_agent(payload)
    monkeypatch.setattr(overseas.runner, "run_agent", fake)
    res = overseas.rewrite(source="午夜,她在等。", platform="goodnovel",
                           category="billionaire", level="B",
                           glossary={"林晚": "Lin Wan"})
    assert "<think>" not in res["content"]
    assert "```" not in res["content"]
    assert res["content"].startswith("At midnight")
    # 术语表要进 prompt
    assert "Lin Wan" in fake.calls[0][1]


def test_rewrite_raises_on_empty_source():
    with pytest.raises(ValueError):
        overseas.rewrite(source="", platform="goodnovel", category="billionaire")


# ---------------------------------------------------------------- 质检

def test_check_returns_issues_for_bad_draft():
    issues = overseas.check("我的脸红了。", platform="goodnovel",
                            category="billionaire")
    assert any(i.rule == "R1" for i in issues)


def test_check_quiet_for_clean_draft():
    issues = overseas.check(
        "She opened the door. Her phone lit up. Before she could answer, "
        "a car door slammed outside.", platform="goodnovel", category="billionaire")
    assert not any(i.rule in ("R1", "R4") for i in issues)


def test_check_survives_unknown_platform():
    """规则 id 不存在时不能抛异常,应安静返回空。"""
    assert overseas.check("hi", platform="nope", category="nope") == []


# ---------------------------------------------------------------- 落库

def test_save_project_and_chapter_roundtrip(tmp_db):
    pid = overseas.save_project(drama_id=900001, episode_id=900002,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="中文原稿",
                                glossary={"林晚": "Lin Wan"},
                                diag=DIAG_JSON)
    assert pid > 0
    row = db.q1("SELECT * FROM overseas_project WHERE id=?", (pid,))
    assert row["platform"] == "goodnovel"
    assert row["status"] == "diagnosed"
    assert json.loads(row["glossary_json"])["林晚"] == "Lin Wan"

    cid = overseas.save_chapter(project_id=pid, episode_id=900002,
                                chapter_no=1, content="At midnight she waited.",
                                title="Ch1", notes="n", qc=[])
    assert cid > 0
    rows = overseas.list_chapters(pid)
    assert len(rows) == 1
    assert rows[0]["status"] == "done"
    assert rows[0]["words"] > 0


def test_update_project_only_touches_allowed_fields(tmp_db):
    pid = overseas.save_project(drama_id=900003, episode_id=None,
                                platform="dreame", category="werewolf",
                                level="A", source_text="x")
    overseas.update_project(pid, level="C", status="done", bogus_field="x")
    row = db.q1("SELECT * FROM overseas_project WHERE id=?", (pid,))
    assert row["level"] == "C"
    assert row["status"] == "done"
