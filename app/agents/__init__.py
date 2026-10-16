# -*- coding: utf-8 -*-
"""Agents 入口:单步 LLM 调用 + 多步 state machine 编排。

两个层次并存 —— 老 caller 走单步,新 caller 可选 state machine:

1. **prompt_runner 风格(单步 LLM 调用 —— 老接口)**
     `from app.agents.runner import run_agent_json, run_agent`
     - 适用:单条指令、prompt 模板 + JSON 抽取;
     - 用法:被 `app/pipeline/novel.py` / `app/pipeline/storyboard.py` 等内部调用。

2. **state machine(多步编排 —— C.1+ 可选启用)**
     `from app.agents.novel_review_flow import build_novel_review_flow, run_novel_review_loop`
     - 适用:写小说 → 六维审校 → JEV 门控 → 修复 / 重写 / giveup 路由决策;
     - 用法:被 `app/pipeline/novel.py:write_chapter_with_review` 内部调用;
     - LangGraph 没装 → 自动 fall back 到 cycle loop(零破坏);装了 → 真 StateGraph 调度 + LangSmith 可观察。

新增 state machine 模块时,在下方 _EXPORT 里加导出即可。
"""
from __future__ import annotations

# ── prompt_runner 风格(单步)──
from .runner import run_agent_json, run_agent  # noqa: F401

# ── state machine 风格(多步)──
from .novel_review_flow import (  # noqa: F401
    NovelReviewState,
    build_novel_review_flow,
    run_novel_review_loop,
    writer_node,
    critic_node,
    repair_node,
    jev_gate_node,
    compressor_node,
    route_after_criticique,
    route_after_jev,
    interrupt_demo_one_step,
)

__all__ = [
    # 单步
    "run_agent_json",
    "run_agent",
    # 多步 state machine
    "NovelReviewState",
    "build_novel_review_flow",
    "run_novel_review_loop",
    "writer_node",
    "critic_node",
    "repair_node",
    "jev_gate_node",
    "compressor_node",
    "route_after_criticique",
    "route_after_jev",
    "interrupt_demo_one_step",
]
