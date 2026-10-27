# -*- coding: utf-8 -*-
"""状态台账的解析韧性回归。

背景(实测 2026-10-27):update_state_ledger 里 `extract_json(raw) or {}` 只挡
None 挡不住「模型直接回了 JSON 数组」—— 数组是真值,后面 `parsed.get(...)`
直接 AttributeError,而且那几行已在 try 块之外,手动重跑入口会把内部错误
原样抛给 UI。守卫:数组响应必须被压成空 dict,走「无变更」的安静路径。

**不碰真实库**:db.q1 / _meta / _save_meta 全部打桩。
"""
from __future__ import annotations

from app.pipeline import state_ledger as sl


def test_array_model_response_does_not_crash(monkeypatch):
    """模型回了 JSON 数组(而不是对象)→ 不抛 AttributeError,按无变更返回。"""
    ep_row = {"content": "字" * sl.MIN_BODY_CHARS, "episode_number": 3}
    monkeypatch.setattr(sl.db, "q1", lambda *a, **k: ep_row)
    monkeypatch.setattr(sl, "_meta", lambda *a, **k: {})
    monkeypatch.setattr(sl, "_save_meta", lambda *a, **k: None)
    monkeypatch.setattr(sl, "jev_gate_state_diff", lambda *a, **k: {})
    monkeypatch.setattr(sl.config, "resolve_content_language", lambda *a, **k: "zh")
    monkeypatch.setattr(sl.runner, "run_agent", lambda *a, **k: "[1,2,3]")

    out = sl.update_state_ledger(1, 9)

    assert out == {"changes": 0, "jev": {}}


def test_dict_response_still_parsed(monkeypatch):
    """正常对象响应不受影响:changes 仍被提取、计入返回值。"""
    ep_row = {"content": "字" * sl.MIN_BODY_CHARS, "episode_number": 3}
    monkeypatch.setattr(sl.db, "q1", lambda *a, **k: ep_row)
    saved = {}
    monkeypatch.setattr(sl, "_meta", lambda *a, **k: {})
    monkeypatch.setattr(sl, "_save_meta", lambda _did, meta: saved.update(meta))
    monkeypatch.setattr(sl, "jev_gate_state_diff", lambda *a, **k: {})
    monkeypatch.setattr(sl.config, "resolve_content_language", lambda *a, **k: "zh")

    def fake_run(*a, **k):
        return ('{"changes": [{"character": "林岁晚", "dimension": "位置",'
                '"from": "旅店", "to": "码头", "target": "", "quote": "走出旅店"}]}')

    monkeypatch.setattr(sl.runner, "run_agent", fake_run)

    out = sl.update_state_ledger(1, 9)

    assert out["changes"] == 1
    assert saved["state_ledger"]["updated_chapter"] == 3
