# -*- coding: utf-8 -*-
"""审校过程上报到界面红框状态栏的回归。

背景:写章完成后的审校是多轮循环(critic → repair → JEV 门控,最多 3 轮),
全程可能好几分钟。以前 UI 只显示一句静态的「写完,审校中…」,用户分不清
是在干活还是卡死了(实测反馈:「审校中的过程出现在红色框中」)。

链路:review flow 各节点把 stage + 轮次写进 sys_task.params
(`taskmgr.set_stage(task_id, stage, cycle)`),UI 起定时器轮询该字段,
翻译成「第 N/3 轮 · 六维审校中…」这类文案刷进状态栏。

**测试不许碰真实库**:涉及 DB 的用例都按本仓约定 monkeypatch config.DB_PATH。
"""
from __future__ import annotations

import json

import pytest

from app.ui import episode_page as EP


# ------------------------------------------------------------------ 文案映射

def test_stage_text_with_cycle():
    raw = json.dumps({"stage": "reviewing", "stage_cycle": 2})
    assert EP.EpisodePage._review_stage_text(raw) == "🔍 第2/3轮 · 六维审校中…"


def test_stage_text_without_cycle_keeps_placeholder():
    raw = json.dumps({"stage": "repairing"})
    assert EP.EpisodePage._review_stage_text(raw) == "🛠 第?轮 · 审校发现问题,修复中…"


def test_stage_text_unknown_stage_is_empty():
    """未知阶段返回空,调用方保留原有提示(如「写完,审校中…」)。"""
    assert EP.EpisodePage._review_stage_text(json.dumps({"stage": "whatever"})) == ""
    assert EP.EpisodePage._review_stage_text("{}") == ""
    assert EP.EpisodePage._review_stage_text(None) == ""


def test_stage_text_survives_bad_json():
    assert EP.EpisodePage._review_stage_text("not-json{") == ""
    # stage_cycle 非数字也不能炸
    raw = json.dumps({"stage": "reviewing", "stage_cycle": "x"})
    assert EP.EpisodePage._review_stage_text(raw) == "🔍 第?轮 · 六维审校中…"


# ------------------------------------------------------------------ set_stage 落库

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """按本仓约定隔离:改 config.DB_PATH(导 config 时环境变量已失效,别用它)。"""
    from app.core import config as cfg, db as db_mod
    monkeypatch.setattr(cfg, "DB_PATH", tmp_path / "t.sqlite3")
    db_mod.init_db()
    return db_mod


def test_set_stage_writes_cycle(tmp_db):
    from app.core import db, taskmgr
    tid = taskmgr.create_task("novel", episode_id=1, drama_id=1)
    taskmgr.set_stage(tid, "reviewing", 2)
    params = json.loads(db.q1("SELECT params FROM sys_task WHERE id=?", (tid,))["params"])
    assert params["stage"] == "reviewing"
    assert params["stage_cycle"] == 2


def test_set_stage_without_cycle_keeps_old_value(tmp_db):
    """不传 cycle 时保留旧轮次:repair 之后的 jev_gate 同轮,不该把轮次抹掉。"""
    from app.core import db, taskmgr
    tid = taskmgr.create_task("novel", episode_id=1, drama_id=1)
    taskmgr.set_stage(tid, "repairing", 3)
    taskmgr.set_stage(tid, "jev_gate")
    params = json.loads(db.q1("SELECT params FROM sys_task WHERE id=?", (tid,))["params"])
    assert params["stage"] == "jev_gate"
    assert params["stage_cycle"] == 3


# ------------------------------------------------------------------ 节点上报

def _capture_stages(monkeypatch):
    import app.core.taskmgr as TM
    seen = []
    monkeypatch.setattr(TM, "set_stage",
                        lambda tid, stage, cycle=None: seen.append((stage, cycle)))
    return seen


def test_critic_node_reports_reviewing_with_cycle(monkeypatch):
    """critic_node 在函数体内局部导入 review_chapter → 打桩要打在源模块上。"""
    from app.agents import novel_review_flow as nrf
    from app.pipeline import novel as novel_pipe
    seen = _capture_stages(monkeypatch)
    monkeypatch.setattr(novel_pipe, "review_chapter",
                        lambda *a, **k: {"overall": "pass", "dimensions": {}})
    out = nrf.critic_node({"cycle": 2, "episode_id": 1, "task_id": 9})
    assert out["decision"] == "ok"
    assert ("reviewing", 2) in seen


def test_repair_node_reports_repairing_with_cycle(monkeypatch):
    from app.agents import novel_review_flow as nrf
    from app.agents import runner as runner_mod
    from app.pipeline import novel as novel_pipe
    from app.core import db as db_mod
    seen = _capture_stages(monkeypatch)
    monkeypatch.setattr(runner_mod, "run_agent", lambda *a, **k: "修复后的正文")
    monkeypatch.setattr(novel_pipe, "_gate_content", lambda t, w: t)
    # repair_node 内部还会经 get_novel_pov 查 dramas.novel_meta —— 桩要一并喂饱
    monkeypatch.setattr(db_mod, "q1",
                        lambda *a, **k: {"drama_id": 1, "novel_meta": None, "novel_contract": None})
    monkeypatch.setattr(db_mod, "ex", lambda *a, **k: 1)
    nrf.repair_node({"cycle": 1, "episode_id": 1, "task_id": 9, "draft": "正文",
                     "critique": {"dimensions": {"pacing": {"pass": False, "issues": ["节奏拖"]}}}})
    assert ("repairing", 1) in seen


def test_jev_gate_node_reports_stage_even_when_unconfigured(monkeypatch):
    """JEV 未配置时瞬间返回 None,但阶段上报照发 —— 界面至少能看到这一步发生过。"""
    from app.agents import novel_review_flow as nrf
    seen = _capture_stages(monkeypatch)

    class _FakeGate:
        usable = False

    import app.ai.jev_gate as jg
    monkeypatch.setattr(jg, "get_jev_gate", lambda: _FakeGate())
    out = nrf.jev_gate_node({"episode_id": 1, "draft": "x", "outline": "y",
                             "task_id": 9, "cycle": 1})
    assert out["jev_decision"] is None
    assert ("jev_gate", 1) in seen


# ------------------------------------------------------------------ UI 接线

def test_ui_starts_stage_poll_after_submit():
    """守住「提交审校后必须启动阶段轮询」的接线(源码检查,不起 Qt 事件循环)。"""
    import inspect
    src = inspect.getsource(EP.EpisodePage)
    assert "self._poll_review_stage(tid)" in src, \
        "提交审校任务后必须启动阶段轮询,否则红框里永远是静态的「写完,审校中…」"
    assert "_REVIEW_STAGE_CN" in src
