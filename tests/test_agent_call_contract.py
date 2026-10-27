# -*- coding: utf-8 -*-
"""Agent 调用契约守卫:全仓 run_agent_json 调用点只允许传真实签名里的参数。

背景(实测 2026-10-27):storyboard_repair.repair_storyboards 给
`run_agent_json` 传了不存在的 `temperature=0.4`,每次调用都 TypeError,
被 `except Exception` 吞进 errors 列表 ——「补全残缺分镜」整个功能静默失效,
而 mock 式测试(把 runner 整个换掉)永远发现不了这类坏调用。
静态扫源码里的关键字参数 vs 真实签名,新增调用点传错参数会直接红。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from app.agents import runner

APP = Path(__file__).resolve().parent.parent / "app"

# 这些调用点允许拿到 **kwargs 转发(自身就是包装器),无法静态核对,
# 但包装器的参数必须在转发时原样透传,漏一个同样会在运行时炸 —— 这里只放行,
# 由包装器自身的测试兜底。
_WRAPPER_ALLOWLIST: set[str] = set()


def _iter_agent_json_calls():
    for py in APP.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - 解析失败会被其它测试暴露
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and ((isinstance(node.func, ast.Attribute)
                          and node.func.attr == "run_agent_json")
                         or (isinstance(node.func, ast.Name)
                             and node.func.id == "run_agent_json"))):
                yield py, node


def test_run_agent_json_call_kwargs_match_signature():
    accepted = set(inspect.signature(runner.run_agent_json).parameters)
    bad = []
    for py, node in _iter_agent_json_calls():
        if str(py) in _WRAPPER_ALLOWLIST:
            continue
        for kw in node.keywords:
            # **kwargs 展开无法静态核对,跳过(真实参数由运行时把关)
            if kw.arg is not None and kw.arg not in accepted:
                bad.append(f"{py}:{node.lineno} 传了 run_agent_json 不存在的参数 {kw.arg!r}")
    assert not bad, "run_agent_json 调用契约被违反:\n" + "\n".join(bad)
