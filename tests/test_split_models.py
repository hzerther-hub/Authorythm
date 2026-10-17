# -*- coding: utf-8 -*-
"""规划模型 / 正文模型 必须走各自的配置,不能串。

依据实测(同批章节计划,两模型各写第 1-3 章):
  · minimax-M3      6538 字 / 1988·2638·1912 —— 篇幅稳定
  · deepseek-v4-pro 5332 字 / 2513·1640·1179 —— 逐章衰减 53%
  · 规划侧相反:deepseek 的结构化输出(分卷/合约)更规整
所以必须分设,且 write_chapter 不能拿规划模型去写正文。
"""
from __future__ import annotations

import inspect
import json

from app.core import db
from app.pipeline import novel as nv


def test_plan_and_prose_are_separate_settings():
    """两个 key 各自独立,不共用一个全局默认。"""
    assert nv._PLAN_CFG_KEY != nv._PROSE_CFG_KEY
    assert nv._PLAN_CFG_KEY.startswith("yihao.novel.")
    assert nv._PROSE_CFG_KEY.startswith("yihao.novel.")


def test_prose_falls_back_to_prose_model(monkeypatch):
    """write_chapter 未显式指定 config_id 时取「正文模型」,不是规划模型。"""
    src = inspect.getsource(nv.write_chapter)
    assert "prose_config_id()" in src, "写正文未回退到正文模型配置"

    called = {}

    def fake_text(prompt, config_id=None, lang=None, budget=None):
        called["cid"] = config_id
        return ("正文" * 200, "")

    # 两个都要在 write_chapter 被调用**之前**打好:兜底函数在函数体里被引用,
    # 若调用后才 patch, 会撞 UnboundLocalError(测试本身的顺序问题)。
    #
    # 门控/落库/回读全部打桩:**绝不能让测试往真实 yihao.sqlite3 里写正文**。
    # 之前这版直接对库里 drama 13 的真剧集跑 write_chapter,测试跑一次就
    # 覆盖掉用户一章正文,排查成本远高于写这几行桩。
    monkeypatch.setattr(nv, "prose_config_id", lambda: 4242)
    monkeypatch.setattr(nv, "_write_chapter_text", fake_text)
    monkeypatch.setattr(nv, "_enforce_novel_gate", lambda drama_id: None)
    monkeypatch.setattr(nv, "_save_with_title",
                        lambda eid, text: None, raising=False)
    ep = db.q1("SELECT id FROM episodes WHERE drama_id=13 LIMIT 1")
    if not ep:
        import pytest
        pytest.skip("库里没有小说剧集")
    saved = {}
    _ = saved

    def fake_q1(sql, args=()):
        if "FROM dramas" in sql:
            return {"novel_chapters": "[]", "novel_outline": "", "novel_meta": "{}"}
        if "FROM episodes" in sql:
            return {"content": "正文" * 200, "episode_number": 1,
                    "drama_id": 13}
        return None

    monkeypatch.setattr(nv.db, "q1", fake_q1)
    monkeypatch.setattr(nv, "chapter_prompt", lambda eid: "P")
    nv.write_chapter(ep["id"])
    assert called["cid"] == 4242, "写正文用错了模型配置"


def test_draft_section_uses_plan_model(monkeypatch):
    """draft_section(总纲/世界观/合约/分卷)必须取「规划模型」。"""
    src = inspect.getsource(nv.draft_section)
    assert "plan_config_id()" in src, "规划类未走规划模型配置"

    called = {}

    def fake_agent(agent_type, prompt, **kw):
        called["cid"] = kw.get("config_id")
        return '{"storyboards":[]}'

    # 提示词拼装与落库都要读 dramas/settings,和「传了哪个 config_id」无关。
    # 这里替掉它们,测试才不会依赖库里有没有 id=13 的小说项目 ——
    # 依赖库的那版会在建表前抛异常,被 except 吞掉后 called 一直是空,
    # 断言报「用错了模型配置」,真实原因(异常)根本看不见。
    monkeypatch.setattr(nv, "plan_config_id", lambda: 777)
    monkeypatch.setattr(nv, "draft_prompt", lambda *a, **k: "P")
    monkeypatch.setattr(nv, "_draft_system", lambda name: "S")
    monkeypatch.setattr(nv, "persist_draft",
                        lambda drama_id, key, raw: {"key": key, "text": raw})
    monkeypatch.setattr(nv.runner, "run_agent", fake_agent)
    nv.draft_section(1, "world", config_id=None)
    assert called.get("cid") == 777, "规划类用错了模型配置"


def test_first_chapter_budget_comes_from_config(monkeypatch):
    """write_chapter 第一次请求的 max_tokens 取配置值,不是硬编码。

    依据用户规则「max_tokens 要从设置里获取,没有再用程序兜底」:
    原来固定 8192 起跳,用户把配置调成 32768 也得先白跑一次短预算。
    """
    budgets = []

    def fake_text(prompt, config_id=None, lang=None, max_tokens=None):
        budgets.append(max_tokens)
        return ("正文" * 200, "")

    monkeypatch.setattr(nv, "_write_chapter_text", fake_text)
    monkeypatch.setattr(nv, "_configured_max_tokens", lambda cid: 32768)
    monkeypatch.setattr(nv, "_enforce_novel_gate", lambda drama_id: None)
    monkeypatch.setattr(nv, "_save_with_title", lambda eid, text: "", raising=False)
    monkeypatch.setattr(nv, "chapter_prompt", lambda eid: "P")
    # 不依赖真实库里有 episode id=1(本机库只有 id=2):测试读的是 max_tokens,
    # 不是数据,替掉这次查询即可 —— AGENTS 明确要求测试不许碰真实库。
    monkeypatch.setattr(nv.db, "q1",
                        lambda sql, args=(): {"id": 1, "drama_id": 1, "content": ""})
    nv.write_chapter(1, config_id=4)
    assert budgets and budgets[0] == 32768, f"首次预算没取配置值:{budgets}"


def test_configured_max_tokens_reads_db_and_tolerates_bad_values(monkeypatch):
    """配置留空 / 非法 / 查无此行都返回 None,由调用方兜底。"""
    def fake_q1(sql, args=()):
        return {"max_tokens": "16384"}
    monkeypatch.setattr(nv.db, "q1", fake_q1)
    assert nv._configured_max_tokens(4) == 16384

    monkeypatch.setattr(nv.db, "q1", lambda sql, args=(): {"max_tokens": None})
    assert nv._configured_max_tokens(4) is None
    monkeypatch.setattr(nv.db, "q1", lambda sql, args=(): {"max_tokens": "abc"})
    assert nv._configured_max_tokens(4) is None
    monkeypatch.setattr(nv.db, "q1", lambda sql, args=(): None)
    assert nv._configured_max_tokens(4) is None
    assert nv._configured_max_tokens(None) is None


# 规划侧 / 正文侧的入口清单。UI 的两个下拉只存 id,真正决定"谁在用"的是
# 这些函数内部有没有兜底 —— 漏一个,那个入口就静默回到全局默认模型。
PLAN_ENTRIES = ["plan_novel", "plan_chapters", "plan_characters",
                "draft_section", "draft_volume_in_batches",
                "generate_chapters_for_volume", "generate_chapters_batched"]
PROSE_ENTRIES = ["write_chapter", "write_chapter_with_review",
                 "review_chapter", "edit_chapter"]


def test_every_planning_entry_falls_back_to_plan_model():
    """每个规划入口在 config_id=None 时都要自己取规划模型。"""
    for name in PLAN_ENTRIES:
        src = inspect.getsource(getattr(nv, name))
        assert "plan_config_id()" in src, f"{name} 未回退到规划模型"


def test_every_prose_entry_falls_back_to_prose_model():
    """每个正文入口在 config_id=None 时都要自己取正文模型。"""
    for name in PROSE_ENTRIES:
        src = inspect.getsource(getattr(nv, name))
        assert "prose_config_id()" in src, f"{name} 未回退到正文模型"


# ── 分卷生成不能覆盖已有章节计划 ────────────────────────────────────

def test_merge_chapters_keeps_existing_volumes(monkeypatch):
    """按卷生成只做增量合并,**绝不整表覆盖**。

    实测踩过:`UPDATE dramas SET novel_chapters=<本卷结果>` 会把用户已生成的
    其它卷整体抹掉 —— 生成第一卷(第 1-120 章)时,已存在的第 61 章以后的
    计划被清空,而界面只显示「生成了 120 章」,看着一切正常。
    """
    import time as _t
    did = int(_t.time() * 1000) % 900000 + 700000
    db.ex("INSERT INTO dramas (id, title, created_at, updated_at) VALUES (?,?,?,?)",
          (did, "合并测试", db.now(), db.now()))

    def set_chapters(nums):
        rows = [{"number": i, "title": f"T{i}", "goal": "g", "events": "e",
                 "cliffhanger": "c"} for i in nums]
        db.ex("UPDATE dramas SET novel_chapters=? WHERE id=?",
              (json.dumps(rows, ensure_ascii=False), did))

    def get_chapters():
        row = db.q1("SELECT novel_chapters FROM dramas WHERE id=?", (did,))
        return [int(c["number"]) for c in db.jload(row["novel_chapters"], []) or []]

    try:
        set_chapters(range(1, 61))                # 已有第 1-60 章(其它卷的)
        nv._merge_chapters(did, [{"number": i, "title": f"N{i}", "goal": "g",
                                  "events": "e", "cliffhanger": "c"}
                                 for i in range(1, 41)])  # 再生成第 1-40 章
        got = get_chapters()
        assert len(got) == 60, f"原有 60 章被覆盖了,现在只有 {len(got)} 章"
        assert got == list(range(1, 61)), f"章号不对:{got[:5]}…"
    finally:
        # 清理必须放 finally:放断言之后的话,断言一失败这条测试项目就永远
        # 留在用户真实库里了(表现为「删掉的项目又出现」)。
        db.ex("DELETE FROM dramas WHERE id=?", (did,))


def test_merge_chapters_same_number_overwrites(monkeypatch):
    """同章号以新结果为准(重做本卷时能覆盖旧的)。"""
    import time as _t
    did = (int(_t.time() * 1000) % 900000 + 700001)
    db.ex("INSERT INTO dramas (id, title, created_at, updated_at) VALUES (?,?,?,?)",
          (did, "覆盖测试", db.now(), db.now()))
    try:
        db.ex("UPDATE dramas SET novel_chapters=? WHERE id=?",
              (json.dumps([{"number": 1, "title": "旧", "goal": "g", "events": "e",
                            "cliffhanger": "c"}], ensure_ascii=False), did))
        nv._merge_chapters(did, [{"number": 1, "title": "新", "goal": "g",
                                  "events": "e", "cliffhanger": "c"}])
        row = db.q1("SELECT novel_chapters FROM dramas WHERE id=?", (did,))
        got = db.jload(row["novel_chapters"], []) or []
        assert len(got) == 1 and got[0]["title"] == "新", "同章号没被新结果覆盖"
    finally:
        db.ex("DELETE FROM dramas WHERE id=?", (did,))   # 同上:必须 finally
