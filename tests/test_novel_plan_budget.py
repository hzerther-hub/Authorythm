# -*- coding: utf-8 -*-
"""章节计划的输出预算:推理吃空 8192 时必须自动升到 32768 重试。

实测(deepseek-v4-pro,40 章/批,2026-10-17):
默认 8192 全部用在 reasoning 上 → finish_reason=length、content=0 字,
`extract_json` 拿不到任何章节,整批失败;同一提示词给 32768 则一次返回
40 章(约 7k 字 JSON)。这两个用例守住「先配置值、空了再升级」的行为。
"""
from __future__ import annotations

import json

from app.pipeline import novel as nv


def test_plan_budgets_escalates_when_config_empty(monkeypatch):
    monkeypatch.setattr(nv, "_configured_max_tokens", lambda cid: None)
    assert nv._plan_budgets(None) == [8192, nv.PLAN_RETRY_TOKENS]


def test_plan_budgets_respects_large_config(monkeypatch):
    """用户把「最大输出 token」调得比 32768 更大时,不应再降回来重试。"""
    monkeypatch.setattr(nv, "_configured_max_tokens", lambda cid: 65536)
    assert nv._plan_budgets(None) == [65536]


def test_volume_batch_retries_with_bigger_budget(monkeypatch):
    """第一批空返回 → 用 32768 重试,最终 80 章全部产出。"""
    monkeypatch.setattr(nv, "load_volume_chapters",
                        lambda did: [{"title": "第一卷", "range": "1-80"}])
    monkeypatch.setattr(nv, "_plan_scale", lambda *a: (80, 2500))
    monkeypatch.setattr(nv, "plan_config_id", lambda: 3)
    monkeypatch.setattr(nv, "chapters_batch_prompt", lambda *a, **k: "prompt")
    monkeypatch.setattr(nv, "_merge_chapters", lambda did, ch: len(ch))
    monkeypatch.setattr(nv, "_configured_max_tokens", lambda cid: None)

    budgets: list[int | None] = []
    attempts = 0

    def fake_run_agent(agent, prompt, **kw):
        nonlocal attempts
        attempts += 1
        budgets.append(kw.get("max_tokens"))
        if attempts == 1:          # 推理吃空预算:content 为空
            return ""
        base = 1 if attempts == 2 else 41
        return json.dumps({"chapters": [
            {"number": i, "title": f"第{i}章", "goal": "g",
             "events": "e", "cliffhanger": "c"}
            for i in range(base, base + 40)]}, ensure_ascii=False)

    monkeypatch.setattr(nv.runner, "run_agent", fake_run_agent)

    out = nv.generate_chapters_for_volume(2, 1, word_count=2500,
                                          with_characters=False)
    assert budgets[:2] == [8192, nv.PLAN_RETRY_TOKENS]
    assert out["count"] == 80
    assert [c["number"] for c in out["chapters"]] == list(range(1, 81))
