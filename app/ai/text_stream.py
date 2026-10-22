# -*- coding: utf-8 -*-
"""文本模型流式输出(OpenAI 兼容 SSE)。

与 `text_client.chat` 的区别只在「内容怎么回来」:这里逐块 yield 增量文本,
调用方可以边收边显示。端点不支持流式时自动回落到一次性请求,调用方无需分支。
"""
from __future__ import annotations

import json

import requests

from . import registry
from .text_client import AIError, _build_body


def chat_stream(prompt: str, system: str | None = None, config_id: int | None = None,
                temperature: float = 0.7, max_tokens: int | None = None,
                json_mode: bool = False, timeout: int = 300,
                image_urls: list[str] | None = None):
    """逐块 yield `(kind, text)`,kind ∈ {"reasoning", "content"}。

    **思考过程与最终结果分开给**:reasoning 只用于界面实时显示,content 才是要落库的内容
    (直接拼接两者会把「用户要求用一句话…必须先调用工具…」这类思考也存进正文)。
    失败抛 AIError;端点不支持流式则整体回落为一次性返回。
    """
    cfg = registry.check_ready("text", config_id)
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = _build_body(cfg, prompt, system, temperature, max_tokens, json_mode, image_urls)
    body["stream"] = True
    body.setdefault("stream_options", {"include_usage": False})

    try:
        resp = requests.post(url, json=body, headers=headers, timeout=timeout, stream=True)
    except requests.RequestException as exc:
        raise AIError(f"流式请求失败:{exc}") from exc
    if resp.status_code != 200:
        # 端点不接受 stream / 网关不支持 → 摘掉 stream 重发一次,拿整段返回
        text = resp.text[:200]
        if "stream" in text.lower() or resp.status_code in (400, 404, 422, 501):
            return _fallback_once(url, body, headers, timeout, json_mode)
        raise AIError(f"文本模型请求失败 HTTP {resp.status_code}: {text}")

    # ⚠️ 编码闸门(根因修复):SSE 规范规定 UTF-8,但 requests 对 `text/*` 且
    # **响应头没带 charset** 的响应一律按 ISO-8859-1 解码
    # (requests.utils.get_encoding_from_headers)。OpenAI 兼容网关最常见的形态
    # 就是 `Content-Type: text/event-stream`(不带 charset)→ 整段中文被当
    # latin-1 解开 → "你好" 变成 "ä½ å¥½"。
    # 非流式路径有 text_client._guarded 兜底能修回来,流式路径没有这一层,
    # 乱码一路流到 novel.persist_draft 直接落库(AGENTS.md:GBK 误读不可逆)。
    # 这里显式钉死 utf-8;响应头真带了 charset 就尊重它。
    if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "latin-1"):
        resp.encoding = "utf-8"

    got_any = False
    try:
        for raw in resp.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue                      # 心跳/注释行,跳过
            delta = _delta_text(data)
            if delta:
                got_any = True
                yield delta           # delta 已是 (kind, text)
    except requests.RequestException as exc:
        if got_any:
            return                         # 已经收到一部分,不再抛
        raise AIError(f"流式读取中断:{exc}") from exc
    finally:
        resp.close()
    if not got_any:
        # 返回 200 但没有任何增量(某些网关会把整段放在最后一帧之外)
        whole = _fallback_once(url, {k: v for k, v in body.items()
                                    if k not in ("stream", "stream_options")},
                              headers, timeout, json_mode)
        if whole:
            yield ("content", whole)


def _fallback_once(url: str, body: dict, headers: dict, timeout: int, json_mode: bool) -> str:
    """不支持流式时的回落:摘掉 stream 重新发一次,返回完整文本。"""
    body = {k: v for k, v in body.items() if k not in ("stream", "stream_options")}
    resp = requests.post(url, json=body, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise AIError(f"文本模型请求失败 HTTP {resp.status_code}: {resp.content.decode('utf-8', 'replace')[:300]}")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise AIError(f"文本模型响应格式异常: {resp.content.decode('utf-8', 'replace')[:200]}") from exc
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    from ..core.encoding import MojibakeError, ensure_text
    try:
        return ensure_text(content or "", where="文本模型返回内容")
    except MojibakeError as e:
        raise AIError(str(e)) from e


def _delta_text(data: dict) -> tuple[str, str] | None:
    """从一帧 SSE 里取出 `(kind, 文本)`;这一帧没有可显示内容时返回 None。

    优先取 reasoning_content(思考),其次 content/text(正式输出)——
    两者分开标记,调用方据此决定「显示但只存 content」。
    """
    try:
        choice = (data.get("choices") or [{}])[0]
    except (IndexError, TypeError):
        return None
    payload = choice.get("delta") or choice.get("message") or {}
    if not isinstance(payload, dict):
        return None
    for key, kind in (("reasoning_content", "reasoning"), ("reasoning", "reasoning"),
                      ("content", "content"), ("text", "content")):
        v = payload.get(key)
        if isinstance(v, str) and v:
            return kind, v
        if isinstance(v, list):             # 兼容多模态 content 数组
            joined = "".join(p.get("text", "") for p in v if isinstance(p, dict))
            if joined:
                return kind, joined
    return None