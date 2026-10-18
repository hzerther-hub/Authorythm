# -*- coding: utf-8 -*-
"""Agent 执行器:组装 system + user,调用文本模型,解析 JSON 输出。"""
from __future__ import annotations

import json
import time

import requests
import re

from ..ai import text_client
from ..ai import registry
from ..ai.text_client import AI_LLM_TIMEOUT_S
from ..ai.text_client import AIError
from ..core import db
from ..core.logging_setup import get_logger
from . import prompts

log = get_logger(__name__)


def extract_json(text: str) -> dict | list | None:
    """从模型输出中稳健提取 JSON(容忍 ```json 围栏、<think> 推理块与前后杂文)。

    **必须先剥 <think> 再找 JSON**:推理型模型(glm-5.3 / MiniMax-M3 等)会先吐一整段
    带花括号的思维链,「首个 { 到最后一个 }」会把推理连同正文一起框进来,必然解析失败。
    实测 comic_board 正是栽在这里。
    """
    if not text:
        return None
    # 1) 先剥成对 <think>...</think>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    # 2) 未闭合的尾巴:正文在思考之后,取最后一个 <think> 之后的全部内容
    if "<think>" in text:
        text = text.rsplit("<think>", 1)[-1]
    text = text.strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidates = []
    if fence:
        candidates.append(fence.group(1).strip())
    # 直接整体
    candidates.append(text.strip())
    # 首个 { 到最后一个 }
    s, e = text.find("{"), text.rfind("}")
    if s >= 0 and e > s:
        candidates.append(text[s:e + 1])
    s2, e2 = text.find("["), text.rfind("]")
    if s2 >= 0 and e2 > s2:
        candidates.append(text[s2:e2 + 1])
    # 尾逗号修复候选:LLM 常写 {"a": 1,} / [1,2,] —— json.loads 必炸,去尾逗号就能救
    for cand in list(candidates):
        fixed = re.sub(r",\s*([}\]])", r"\1", cand)
        if fixed != cand:
            candidates.append(fixed)
    for cand in candidates:
        try:
            return json.loads(cand)
        except Exception:  # noqa: BLE001
            continue
    return None


def run_agent(agent_type: str, user_prompt: str, *, lang: str | None = None,
              json_output: bool = False, temperature: float = 0.7,
              config_id: int | None = None,
              image_urls: list[str] | None = None,
              system: str | None = None,
              max_tokens: int | None = None,
              timeout: int | None = None,
              with_meta: bool = False) -> str | tuple[str, dict]:
    """system=None 时用 workspace/prompts/<type>.<lang>.md。

    传入 system 可整体覆盖:workspace 里的提示词是给**带工具的 Mastra Agent** 写的
    (例如 novel_planner.md 里写着「只输出工具调用,不要输出规划文本」),
    本仓 runner 是单次调用、没有工具,不覆盖就会拿到一串 <tool_call> 文本。

    with_meta=True 时返回 (content, meta),meta 含 finish_reason / usage ——
    预算自适应要靠 finish_reason=="length" 判断截断,不能只靠括号配平去猜。
    """
    if lang is None:
        lang = db.get_setting("content_language", "zh")
    system = system if system is not None else prompts.load_prompt(agent_type, lang)
    kwargs: dict = {}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return text_client.chat(
        user_prompt, system=system, temperature=temperature,
        json_mode=json_output, config_id=config_id, image_urls=image_urls,
        max_tokens=max_tokens, with_meta=with_meta, **kwargs)


JSON_HINT = "请只输出 JSON,不要任何解释文字、不要 Markdown 代码块标记。"

# workspace/prompts/*.md 是给带工具的 Mastra Agent 写的(「调用 read_xxx / save_xxx」),
# 本仓 runner 没有工具。不加这句时,模型会老老实实回一个
# {"name": "read_script_for_extraction", "arguments": {...}} —— 它是合法 JSON,
# extract_json 会解析成功,但调用方拿到的是工具调用而不是结果,资产提取 0 条。
_NO_TOOL_HINT = (
    "\n\n【本次运行环境没有工具】不要调用任何工具,也不要输出 "
    '{"name": "...", "arguments": {...}} 形式的工具调用;直接输出最终 JSON。'
)


def _looks_like_tool_call(data) -> bool:
    """识别 {"name": "...", "arguments": {...}} 这种工具调用 JSON。"""
    return (isinstance(data, dict) and set(data) == {"name", "arguments"}
            and isinstance(data.get("name"), str))


# ---------------------------------------------------------------- 输出预算自适应
#
# 为什么要有这一层:推理型模型(minimax-M3 / deepseek-v4-pro / glm 等)会先吐一整段
# <think>,默认 8192 的输出预算会被这段思维链吃光 —— finish_reason=length、
# 正文 0 字符,extract_json 必然返回 None。实测后果是分镜拆分从上线起一次都没成功过
# (storyboards 表 0 行、storyboard_split 任务恒 failed)。
#
# **刻意不针对任何具体模型**:过去 extractor 硬写 32768、novel 硬写 32768、
# 分镜干脆没写,换一家供应商就得重新试一遍。这里改成「看输出是否被截断」来决定
# 升不升预算 —— 非推理模型不会触发(输出本来就不是截断的),推理模型无论需要多少
# 都能自己爬到够用为止,不需要为它单独调参。
#
# 三个信号合起来判定「这次是被预算截断了」:
#   1. finish_reason == "length" —— 供应商自己说的,唯一可靠信号
#   2. 空响应                  —— 预算全烧在 <think> 上,正文一个字没写
#   3. <think> 未闭合 / 括号不配平 —— 供应商不给 finish_reason 时的退化判断
# **只看括号配平会漏**(实测 minimax-M3 分镜 8192 档):切在 JSON 字符串中间时
# `{` 与 `}` 数量仍然相等,于是被判成「不是截断」,预算永远不升。
# 只有命中这些信号才升预算;否则(JSON 写坏 / 模型回了工具调用 / 输出散文)升预算
# 纯属浪费 token,那种情况走既有的禁工具重试。
BUDGET_START = 8192        # 与 text_client._build_body 的兜底值保持一致
BUDGET_CEILING = 65536     # 自适应天花板:到顶还截断就是提示词本身太长,交给人看
BUDGET_FACTOR = 2


def _configured_budget(config_id: int | None, explicit: int | None) -> int:
    """起始预算 = 调用方显式值 > 服务配置里手填的值 > BUDGET_START。

    与 `novel._configured_max_tokens`、`ai/text_client._build_body` 同一优先级,
    三处口径必须一致,否则会出现「配置里填的大预算被程序兜底盖掉」。

    **走 `registry.default_config` 而不是按 id 直查**:调用点绝大多数传
    `config_id=None`(让 text_client 自己挑默认配置),此时按 id 直查是
    `WHERE id=NULL`,永远查不到行 → 一律退到 8192。而 text_client._build_body
    在同一种情况下会用默认配置里手填的值(本机是 32768)。两处口径一分裂,
    第一次请求就白发一个短预算,多烧一次往返还得靠阶梯爬回来。
    """
    if explicit:
        return int(explicit)
    try:
        cfg = registry.default_config("text", config_id) or {}
        v = int(cfg.get("max_tokens") or 0)
        if v:
            return v
    except Exception:  # noqa: BLE001 —— 读不到就按兜底走,不能因此中断业务
        pass
    return BUDGET_START


def _looks_truncated(raw: str | None, finish_reason: str | None = None) -> bool:
    """输出是否像是被输出预算截断(见上方注释的信号)。"""
    # 信号 0:供应商明确说 length —— 优先信它,不要再靠文本猜
    if finish_reason == "length":
        return True
    if not raw or not raw.strip():
        return True  # 信号 1:空响应
    t = raw.strip()
    if "<think>" in t and "</think>" not in t:
        return True  # 信号 2:思考块没闭合
    # 信号 3:括号不配平(正文写到一半被切断)
    return t.count("{") > t.count("}") or t.count("[") > t.count("]")


def _timeout_for(budget: int) -> int:
    """预算越大,供应商吐字时间越长:按 60 tokens/s 估,再加 120s 余量。

    实测 minimax-M3 出 50,787 completion tokens 用了 401s(≈127 tok/s),
    固定 300s 超时会让 65536 档必然 Timeout —— 而 Timeout 不是 AIError,
    会直接冒到任务里,看起来和「模型不会写 JSON」完全无关。
    """
    return max(AI_LLM_TIMEOUT_S, budget // 60 + 120)


def _budget_rejected(err: AIError) -> bool:
    """供应商是不是「单纯不认这个 max_tokens」,而不是配置/鉴权坏了。

    只有前者才值得退回低档重试;401/404 之类退回低档也没意义,白白拖时间。
    """
    msg = str(err).lower()
    if any(k in msg for k in ("401", "403", "404", "unauthorized", "invalid api key")):
        return False
    return any(k in msg for k in ("max_tokens", "max tokens", "too large", "exceeds",
                                  "invalid_parameter", "context length"))


def _budget_ladder(start: int, ceiling: int) -> list[int]:
    """start, start*2, start*4 ... 直到 ceiling。已到顶就只给一档。"""
    out, b = [start], start
    while b < ceiling:
        b = min(b * BUDGET_FACTOR, ceiling)
        out.append(b)
    return out


def _call_budgeted(agent_type: str, prompt: str, *, lang, config_id, image_urls,
                   system, start_budget: int, parse, accept):
    """按预算阶梯调用模型,直到 parse() 拿到 accept() 认可的结果。

    阶梯中途遇到 AIError(供应商拒绝该预算,通常 400)就把天花板压到这一档 ——
    **天花板由供应商自己告诉我们**,而不是代码里写死某个模型的上限。
    若调用方传的起始预算就被拒,退回到 BUDGET_START 重新爬(而不是直接失败:
    调用方按「这个 Agent 输出大」填的高预算,供应商不认不代表配置坏了)。
    返回 (data, last_raw):data 为 None 表示全阶梯都没拿到可用结果。
    """
    ladder = _budget_ladder(start_budget, BUDGET_CEILING)
    last_raw = ""
    i = 0
    while i < len(ladder):
        budget = ladder[i]
        t0 = time.perf_counter()
        try:
            raw, meta = run_agent(agent_type, prompt, lang=lang, json_output=True,
                                  temperature=0.4, config_id=config_id,
                                  image_urls=image_urls, system=system,
                                  max_tokens=budget, timeout=_timeout_for(budget),
                                  with_meta=True)
        except AIError as e:
            log.warning("agent.budget.rejected agent=%s budget=%d err=%s",
                        agent_type, budget, str(e)[:200])
            if i == 0 and _budget_rejected(e) and start_budget > BUDGET_START:
                ladder = _budget_ladder(BUDGET_START, BUDGET_CEILING)
                i = 0
                continue
            # 起始档就炸 = 供应商侧硬错误(配置错/鉴权失败),照常抛出。
            if i == 0:
                raise
            # 更高档被拒 = 到顶了,用上一档再试一次就收手。
            ladder = ladder[:i]
            break
        last_raw = raw or ""
        truncated = _looks_truncated(raw, meta.get("finish_reason"))
        usage = meta.get("usage") or {}
        log.info("agent.budget.attempt agent=%s budget=%d finish=%s out_tokens=%s "
                 "chars=%d truncated=%s elapsed=%.1fs",
                 agent_type, budget, meta.get("finish_reason"),
                 usage.get("completion_tokens"), len(last_raw), truncated,
                 time.perf_counter() - t0)
        data = parse(raw)
        if data is not None and accept(data):
            return data, last_raw
        # 不是被截断 → 升预算也救不回来,别再烧 token。
        if not truncated:
            break
        i += 1
    return None, last_raw


def run_agent_json(agent_type: str, user_prompt: str, *, lang: str | None = None,
                   config_id: int | None = None,
                   image_urls: list[str] | None = None,
                   system: str | None = None,
                   max_tokens: int | None = None) -> dict | list:
    """跑 Agent 并解析 JSON;解析失败时抛 RuntimeError(带原始输出片段)。

    **总是把「只输出 JSON」写进用户消息**:部分网关要求 messages 里出现 json 字样才肯用
    response_format=json_object,而 workspace/prompts/*.md 里的系统提示不一定含该词
    (实测 storyboard_breaker 的 md 就没有),否则整个 Agent 调用 400。

    system:整体覆盖系统提示(同 run_agent)。extractor 这类提示词写死了
    「调用工具保存」的 Agent 必须用 JSON 专用 system,否则拿到的是工具调用。
    max_tokens:起始输出预算(**不是上限**,被截断时仍会往上自适应升)。
    不传则读该服务配置里手填的值,留空用 8192。

    失败时按「输出是否被截断」自适应升预算重试(见 _looks_truncated / _budget_ladder),
    对推理型与非推理型模型一视同仁,不需要为单个供应商调参。
    """
    prompt = user_prompt if JSON_HINT in user_prompt else user_prompt + "\n\n" + JSON_HINT
    start = _configured_budget(config_id, max_tokens)
    data, raw = _call_budgeted(
        agent_type, prompt, lang=lang, config_id=config_id, image_urls=image_urls,
        system=system, start_budget=start,
        parse=extract_json,
        accept=lambda d: not _looks_like_tool_call(d),
    )
    if data is None:
        # 不是预算问题(模型照着带工具的 prompt 回了工具调用 / JSON 写坏):
        # 明确禁工具再试一次,沿用既有模式。
        # load_prompt 本身也可能抛(Agent 名拼错/提示词文件缺失)——那种情况下
        # 必须让下面那句「输出无法解析为 JSON」照常抛出去,否则真正的失败原因
        # 会被一个无关的 ValueError 顶掉,排查时看到的是错的东西。
        try:
            base_system = system if system is not None else prompts.load_prompt(agent_type, lang)
            raw2 = run_agent(agent_type, prompt, lang=lang, json_output=True,
                             temperature=0.4, config_id=config_id, image_urls=image_urls,
                             system=base_system + _NO_TOOL_HINT, max_tokens=start)
        except (AIError, ValueError, OSError):
            raw2 = None
        d2 = extract_json(raw2) if raw2 else None
        if d2 is not None and not _looks_like_tool_call(d2):
            return d2
    if data is None:
        raise RuntimeError(f"{agent_type} 输出无法解析为 JSON:{raw[:300]}")
    return data
