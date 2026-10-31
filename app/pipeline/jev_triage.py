"""审校问题降噪(Jev score 复核)—— 修复循环只修值得修的。

对齐参考项目 backend/src/services/jev-triage.ts。

痛点:审校(novel_reviewer)输出的 issues 真假混杂 —— 硬性矛盾、OOC、设定冲突值得修;
风格意见、主观偏好、误报不值得为它们跑一轮修复重写(整次 agent 调用)。

做法:审校解析出 issues 后,一次性把全部问题发给 Jev 评分(问题编号做动态 question key,
单次 decide 调用给所有问题打分),0=可忽略 / 1=应修复 / 2=必须修复。修复循环只修 ≥1 的;
全部为 0 时跳过修复轮。

软失败:`JEV_TRIAGE=0` 显式关 / Jev 未配置 / 连不通(熔断)/ 解析失败 → 返回 None,
调用方按「全部应修复」处理(与接入前行为完全一致,零风险)。
"""
from __future__ import annotations

import os

from ..ai.jev_gate import JevBreaker, get_jev_gate

MAX_TRIAGE_ISSUES = 10
SEVERITY_CN = {0: "可忽略", 1: "应修复", 2: "必须修复"}

_breaker = JevBreaker("review-triage")


def jev_triage_issues(issues: list[str], context_text: str) -> list[int] | None:
    """给审校问题列表打严重度分。

    返回与 issues 等长的分数数组(0/1/2);Jev 不可用或失败返回 None(调用方全修)。
    """
    if not issues:
        return None
    if os.environ.get("JEV_TRIAGE") == "0":
        return None
    gate = get_jev_gate()
    if not gate.usable:
        return None
    if _breaker.in_cooldown():
        return None

    # 单次 decide 给全部问题打分:sev_0..sev_n 作动态 question key
    capped = issues[:MAX_TRIAGE_ISSUES]
    list_text = "\n".join(f"{i}. {it}" for i, it in enumerate(capped))
    questions = {
        f"sev_{i}": {
            "type": "score",
            "instructions": (f"第 {i} 号审校问题的严重度。"
                             "0=可忽略(风格意见/主观偏好/误报,不值得为它重写);"
                             "1=应修复(轻度矛盾或表达问题);"
                             "2=必须修复(硬性矛盾/OOC/设定冲突/物件连续性错误)"),
            "criteria": list(SEVERITY_CN.values()),
        }
        for i in range(len(capped))
    }
    state = ("请对照本章正文,逐条评估下列审校问题的真实严重度(审校模型偶尔会产出误报或风格意见)。\n"
             f"【本章正文节选】\n{context_text}\n"
             f"【审校问题列表】\n{list_text}")
    result = gate.client.decide(state, questions)
    if not result or not result.get("answers"):
        _breaker.note_fail()
        return None
    _breaker.note_ok()

    scores = []
    for i in range(len(capped)):
        try:
            v = float((result["answers"].get(f"sev_{i}") or {}).get("score"))
            scores.append(max(0, min(2, round(v))))
        except (TypeError, ValueError):
            scores.append(1)
    # 超出评分上限的问题不评分:按 1(应修复)处理,保持保守
    scores.extend([1] * (len(issues) - len(scores)))
    return scores


def filter_fixable(issues: list[str], severity: list[int] | None) -> list[str]:
    """只保留 severity ≥1 的问题;无评分(未配置/失败)时全部保留 —— 与接入前行为一致。"""
    if not severity:
        return list(issues)
    return [it for i, it in enumerate(issues) if (severity[i] if i < len(severity) else 1) >= 1]
