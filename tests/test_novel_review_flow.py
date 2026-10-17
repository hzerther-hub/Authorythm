# -*- coding: utf-8 -*-
"""novel_review_flow 路径测试:不依赖 LangGraph 真包,验证 routing + fallback 路径。
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def no_real_jev(monkeypatch):
    """审校 fallback 用例只测 routing,禁止打真实 Jev 接口。

    实测踩过:本机库里残留一条 Jev 配置(id 落在 95000 测试段),审校 fallback
    会真的发 POST /v1/systemone;模型答「不连续」时 decision 变 rewrite,
    final 从 repaired-once 变成 d-2 —— 用例随真实接口时绿时红。
    Jev 自身的用例(test_jev_gate_*)不用这个 fixture。
    """
    from app.agents import novel_review_flow as nrf
    monkeypatch.setattr(nrf, "jev_gate_node", lambda s: {"jev_decision": None})


def test_build_returns_none_or_graph():
    from app.agents.novel_review_flow import build_novel_review_flow
    g = build_novel_review_flow()
    assert g is None or hasattr(g, "invoke")


def test_route_after_criticique_all_branches():
    from app.agents.novel_review_flow import route_after_criticique

    assert route_after_criticique({"decision": "ok"}) == "compressor"
    assert route_after_criticique({"decision": "revise"}) == "repair"
    assert route_after_criticique({"decision": "rewrite"}) == "writer"
    assert route_after_criticique({"decision": "giveup"}) == "__end__"
    assert route_after_criticique({}) == "writer"


def test_run_loop_fallback_when_langgraph_missing(monkeypatch):
    """LangGraph 不可用 → build 返回 None,fallback 可跑。"""
    from app.agents import novel_review_flow as nrf
    monkeypatch.setattr(nrf, "_try_langgraph", lambda: (None, None))
    g = nrf.build_novel_review_flow()
    assert g is None


def test_run_loop_fallback_ok_path(no_real_jev):
    """fallback 跑通 ok 直接终止。"""
    from app.agents import novel_review_flow as nrf
    nrf.writer_node = lambda s: {"cycle": 1, "draft": "happy"}
    nrf.critic_node = lambda s: {"critique": {"overall": "pass"}, "decision": "ok"}
    nrf.repair_node = lambda s: {"draft": "unused"}
    try:
        out = nrf.run_novel_review_loop(episode_id=999, max_cycles=3)
        assert out["decision"] == "ok"
        assert out["cycles"] == 1
        assert out["final"] == ["happy"]
    finally:
        importlib.reload(nrf)


def test_run_loop_fallback_revise_then_ok(no_real_jev):
    """fallback 1 次 revise + 修复,第二轮 ok。"""
    from app.agents import novel_review_flow as nrf
    nrf.writer_node = lambda s: {
        "cycle": s.get("cycle", 0) + 1,
        "draft": f"d-{s.get('cycle', 0) + 1}",
    }
    nrf.critic_node = lambda s: {
        "critique": {"overall": "fix" if s["draft"] == "d-1" else "pass"},
        "decision": "revise" if s["draft"] == "d-1" else "ok",
    }
    nrf.repair_node = lambda s: {"draft": "repaired-once"}
    try:
        out = nrf.run_novel_review_loop(episode_id=999, max_cycles=3)
        assert out["decision"] == "ok"
        assert out["cycles"] == 2
        assert out["final"] == ["repaired-once"]
    finally:
        importlib.reload(nrf)


def test_run_loop_fallback_max_cycles_triggers_giveup(no_real_jev):
    """max_cycles=2 时,两个 revise 后自动 giveup。"""
    from app.agents import novel_review_flow as nrf
    nrf.writer_node = lambda s: {
        "cycle": s.get("cycle", 0) + 1,
        "draft": f"d-{s.get('cycle', 0) + 1}",
    }
    nrf.critic_node = lambda s: {"critique": {"overall": "fix"}, "decision": "revise"}
    nrf.repair_node = lambda s: {"draft": "repaired"}
    try:
        out = nrf.run_novel_review_loop(episode_id=999, max_cycles=2)
        assert out["decision"] == "giveup"
    finally:
        importlib.reload(nrf)


def test_route_after_jev_all_branches():
    """JEV 门控后的路由。"""
    from app.agents.novel_review_flow import route_after_jev
    assert route_after_jev({"jev_decision": "rewrite"}) == "writer"
    assert route_after_jev({"jev_decision": "pass"}) == "critic"
    assert route_after_jev({"jev_decision": None}) == "critic"
    assert route_after_jev({}) == "critic"


def test_jev_gate_node_returns_none_when_unavailable(monkeypatch):
    """JEV 未配/未装 → jev_gate_node 透传 None(走 critic)。"""
    from app.agents import novel_review_flow as nrf

    class _FakeGate:
        usable = False

    # nrf 内的 `from app.ai.jev_gate import get_jev_gate` 每次都重 lookup,
    # 所以 monkeypatch 在 module attr 上 set,后续 from 都会拿到 fake。
    import app.ai.jev_gate as _jev_mod
    monkeypatch.setattr(_jev_mod, "get_jev_gate", lambda: _FakeGate())
    out = nrf.jev_gate_node({"episode_id": 999, "draft": "x", "outline": "y"})
    assert out["jev_decision"] is None


def test_jev_gate_node_rewrite_on_low_score(monkeypatch):
    """JEV 返回 0(不连续)→ decision=rewrite。"""
    from app.agents import novel_review_flow as nrf

    class _FakeGate:
        usable = True
        client = type(
            "C", (), {"decide": staticmethod(
                lambda *a, **k: {"answers": {"continuity": {"noul": "0.2"}}})}
        )()

    import app.ai.jev_gate as _jev_mod
    monkeypatch.setattr(_jev_mod, "get_jev_gate", lambda: _FakeGate())
    out = nrf.jev_gate_node({"episode_id": 999, "draft": "x", "outline": "y"})
    assert out["jev_decision"] == "rewrite"


def test_jev_gate_node_pass_on_high_score(monkeypatch):
    """JEV 返回 ≥ 0.5 → decision=pass。"""
    from app.agents import novel_review_flow as nrf

    class _FakeGate:
        usable = True
        client = type(
            "C", (), {"decide": staticmethod(
                lambda *a, **k: {"answers": {"continuity": {"noul": "0.95"}}})}
        )()

    import app.ai.jev_gate as _jev_mod
    monkeypatch.setattr(_jev_mod, "get_jev_gate", lambda: _FakeGate())
    out = nrf.jev_gate_node({"episode_id": 999, "draft": "x", "outline": "y"})
    assert out["jev_decision"] == "pass"


def test_interrupt_demo_returns_none_when_no_langgraph(monkeypatch):
    """没 LangGraph 时 interrupt_demo_one_step 返回 None。"""
    from app.agents import novel_review_flow as nrf
    monkeypatch.setattr(nrf, "_try_langgraph", lambda: (None, None))
    out = nrf.interrupt_demo_one_step(episode_id=42)
    assert out is None
