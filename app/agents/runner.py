# -*- coding: utf-8 -*-
"""Agent 执行器:组装 system + user,调用文本模型,解析 JSON 输出。"""
from __future__ import annotations

import json

import requests
import re

from ..ai import text_client
from ..ai import registry
from ..ai.text_client import AI_LLM_TIMEOUT_S
from ..core import db
from . import prompts


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
              max_tokens: int | None = None) -> str:
    """system=None 时用 workspace/prompts/<type>.<lang>.md。

    传入 system 可整体覆盖:workspace 里的提示词是给**带工具的 Mastra Agent** 写的
    (例如 novel_planner.md 里写着「只输出工具调用,不要输出规划文本」),
    本仓 runner 是单次调用、没有工具,不覆盖就会拿到一串 <tool_call> 文本。
    """
    if lang is None:
        lang = db.get_setting("content_language", "zh")
    system = system if system is not None else prompts.load_prompt(agent_type, lang)
    return text_client.chat(
        user_prompt, system=system, temperature=temperature,
        json_mode=json_output, config_id=config_id, image_urls=image_urls,
        max_tokens=max_tokens)


JSON_HINT = "请只输出 JSON,不要任何解释文字、不要 Markdown 代码块标记。"


def run_agent_json(agent_type: str, user_prompt: str, *, lang: str | None = None,
                   config_id: int | None = None,
                   image_urls: list[str] | None = None) -> dict | list:
    """跑 Agent 并解析 JSON;解析失败时抛 RuntimeError(带原始输出片段)。

    **总是把「只输出 JSON」写进用户消息**:部分网关要求 messages 里出现 json 字样才肯用
    response_format=json_object,而 workspace/prompts/*.md 里的系统提示不一定含该词
    (实测 storyboard_breaker 的 md 就没有),否则整个 Agent 调用 400。
    """
    prompt = user_prompt if JSON_HINT in user_prompt else user_prompt + "\n\n" + JSON_HINT
    raw = run_agent(agent_type, prompt, lang=lang, json_output=True,
                    temperature=0.4, config_id=config_id, image_urls=image_urls)
    data = extract_json(raw)
    if data is None:
        raise RuntimeError(f"{agent_type} 输出无法解析为 JSON:{raw[:300]}")
    return data
