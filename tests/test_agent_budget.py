# -*- coding: utf-8 -*-
"""输出预算自适应(agent runner)的回归测试。

背景见 docs/分镜拆分失败-根因与修复交接.md:
分镜拆分从上线起从未成功过 —— 推理型模型(minimax-M3 / deepseek-v4-pro)把默认
8192 的输出预算全烧在 <think> 上,正文 JSON 一个字没写就被截断,
extract_json 返回 None;而此前的重试用的是同一个预算,等于拿同样的截断结果再赌一次。

修复的关键约束是「模型无关」:升不升预算由 `_looks_truncated` 这个客观信号决定,
不靠为某个供应商调参。本用例守住这个契约。
"""
import pytest

from app.agents import runner
from app.ai.text_client import AIError

TRUNC_THINK = "<think>Let me analyze this carefully and think about the structure"  # 未闭合
TRUNC_JSON = '{"storyboards": [{"number": 1, "title": "第一镜"'  # 括号不配平
TOOL_CALL = '{"name": "read_script", "arguments": {"path": "x.md"}}'  # 合法但没用的工具调用
PROSE = "好的,我已经完成分析了,以下是分镜表"  # 散文,不是截断
GOOD = '{"storyboards": [{"number": 1}]}'


@pytest.fixture
def budgets(monkeypatch):
    """打桩 run_agent,记录每次调用的 max_tokens;返回该记录列表。"""
    seen = []
    script = []

    def fake(agent_type, user_prompt, *, lang=None, json_output=False, temperature=0.7,
             config_id=None, image_urls=None, system=None, max_tokens=None):
        seen.append(max_tokens)
        item = script.pop(0) if script else GOOD
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(runner, "run_agent", fake)
    return seen, script


def _run(agent="storyboard_breaker"):
    return runner.run_agent_json(agent, "拆一下")


# ------------------------------------------------------------------ 信号判定

@pytest.mark.parametrize("raw,truncated", [
    (None, True),                       # 空响应:预算被烧光
    ("", True),
    ("   ", True),
    (TRUNC_THINK, True),                # think 未闭合
    (TRUNC_JSON, True),                 # JSON 写到一半
    (GOOD, False),                      # 完整 JSON
    (PROSE, False),                     # 散文不是截断
    (TOOL_CALL, False),                 # 工具调用不是截断
])
def test_looks_truncated_signals(raw, truncated):
    assert runner._looks_truncated(raw) is truncated


def test_budget_ladder_doubles_until_ceiling():
    assert runner._budget_ladder(8192, 65536) == [8192, 16384, 32768, 65536]
    # 已经到顶就不该再生成更高档
    assert runner._budget_ladder(65536, 65536) == [65536]
    assert runner._budget_ladder(4096, 8192) == [4096, 8192]


# ------------------------------------------------------------------ 主路径

def test_escalates_until_success_when_truncated(budgets):
    seen, script = budgets
    script.extend([TRUNC_THINK, TRUNC_THINK, GOOD])
    assert _run() == {"storyboards": [{"number": 1}]}
    assert seen == [8192, 16384, 32768], "被截断应按 2 倍阶梯升预算"


def test_does_not_escalate_when_not_truncated(budgets):
    """JSON 写坏 / 回了工具调用 → 升预算是浪费 token,应直接走禁工具重试。"""
    seen, script = budgets
    script.extend([PROSE, '{"a": 1}'])
    assert _run("extractor") == {"a": 1}
    assert seen == [8192, 8192], "非截断失败不应抬高预算"


def test_tool_call_triggers_no_tool_retry_without_escalation(budgets):
    seen, script = budgets
    script.extend([TOOL_CALL, '{"a": 1}'])
    assert _run("extractor") == {"a": 1}
    assert seen == [8192, 8192], "工具调用同样不该抬预算"


def test_success_first_call_makes_no_retry(budgets):
    seen, script = budgets
    script.append(GOOD)
    _run()
    assert seen == [8192], "一次成功就不该有第二次调用"


def test_explicit_max_tokens_is_the_starting_point(budgets):
    """契约:max_tokens 是**起始**预算而非上限。

    刻意允许升级 —— 否则调用方就得自己知道「这个模型需要多少」,那就退回到
    为每个供应商调参的老路上了。本仓调用方(extractor 显式 32768)传的是
    「至少要这么多」,不是「最多花这么多」,升级不会踩到它的意图。
    """
    seen, script = budgets
    script.extend([TRUNC_THINK, TRUNC_JSON, '{"a": 1}'])
    runner.run_agent_json("extractor", "x", max_tokens=4096)
    assert seen[0] == 4096, "调用方显式值必须作为第一次的预算"
    assert seen == [4096, 8192, 16384], "从显式值继续阶梯升级"


# ------------------------------------------------------------------ 供应商上限

def test_provider_rejects_budget_ceiling_is_discovered_from_error(budgets):
    """天花板由供应商自己告诉我们(400),而不是代码里写死某家的上限。"""
    seen, script = budgets
    script.extend([TRUNC_THINK, AIError("400 max_tokens too large"), '{"a": 1}'])
    assert _run() == {"a": 1}
    assert seen == [8192, 16384, 8192], "被拒档应回退到上一档继续试"


def test_first_call_ai_error_propagates(budgets):
    """起始档就 400 = 鉴权/配置这类硬错误,照常抛出,不能被兜底吞掉。"""
    seen, script = budgets
    script.append(AIError("401 unauthorized"))
    with pytest.raises(AIError):
        _run()


def test_gives_up_at_ceiling_instead_of_looping_forever(budgets):
    seen, script = budgets
    script.extend([TRUNC_JSON] * 10)
    with pytest.raises(RuntimeError, match="无法解析为 JSON"):
        _run()
    assert max(seen) == runner.BUDGET_CEILING, "升到天花板就停,不能无限升级"


def test_real_failure_reason_is_not_masked_by_prompt_loading_error(budgets):
    """阶梯失败后的禁工具兜底里,load_prompt 抛错不能顶掉真正的诊断信息。"""
    seen, script = budgets
    script.extend([TRUNC_JSON] * 10)
    # agent 名不存在 → prompts.load_prompt 抛 ValueError
    with pytest.raises(RuntimeError, match="无法解析为 JSON"):
        runner.run_agent_json("no_such_agent_xyz", "x")
