# -*- coding: utf-8 -*-
"""文本模型客户端:OpenAI 兼容 chat completions(覆盖 OpenAI/MiniMax/DeepSeek/Gemini-OpenAI 端点)。"""
from __future__ import annotations

import os

import requests

from . import registry

# LLM 挂起超时(对齐原版 AI_LLM_TIMEOUT_MS,默认 5 分钟):
# 服务商偶发"接受连接但永不响应",没有超时会让任务永远卡在 processing。
AI_LLM_TIMEOUT_S = int(int(os.environ.get("AI_LLM_TIMEOUT_MS", 300_000)) / 1000)


class AIError(RuntimeError):
    pass


def _needs_json_word(err_text: str) -> bool:
    """网关以「messages 必须含 json 字样」为由拒绝 response_format=json_object 时判 True。"""
    t = (err_text or "").lower()
    return "response_format" in t and "json" in t and ("must contain" in t or "invalid_parameter" in t)


def _build_body(cfg: dict, prompt: str, system: str | None, temperature: float,
                max_tokens: int, json_mode: bool, image_urls: list[str] | None) -> dict:
    """组装请求体(chat 与 chat_stream 共用,避免两处参数漂移)。"""
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    if image_urls:
        # OpenAI 兼容多模态格式(MiniMax-M3 / Gemini-OpenAI 端点均按此收图/收视频)
        parts: list[dict] = [{"type": "text", "text": prompt}]
        for u in image_urls:
            if u.startswith("data:video") or str(u).lower().endswith((".mp4", ".mov", ".webm")):
                parts.append({"type": "video_url", "video_url": {"url": u}})
            else:
                parts.append({"type": "image_url", "image_url": {"url": u}})
        msgs.append({"role": "user", "content": parts})
    else:
        msgs.append({"role": "user", "content": prompt})
    body: dict = {"model": cfg["model"], "messages": msgs, "temperature": temperature}
    # 输出预算:调用方显式传值优先,否则用该服务配置里手填的 max_tokens,再兜底默认
    mt = max_tokens
    if mt is None:
        try:
            mt = int(cfg.get("max_tokens") or 0) or None
        except (TypeError, ValueError):
            mt = None
    body["max_tokens"] = mt or 8192
    # 配置级 Temperature(对齐原版:留空跟随服务默认;填写则强制覆盖,应对强制温度模型)
    cfg_temp = cfg.get("temperature")
    if cfg_temp is not None and cfg_temp != "":
        try:
            body["temperature"] = float(cfg_temp)
        except (TypeError, ValueError):
            pass
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def _err_text(resp) -> str:
    """错误文案一律按 utf-8 显式解码。

    原来用 resp.text —— requests 在没有 Content-Type charset 时会走
    apparent_encoding(charset_normalizer 猜),中文报错常被猜成 GBK/Big5,
    于是**报错本身就是乱码**,排障时看到的全是鬼画符,反而看不出问题在哪。
    """
    try:
        return resp.content.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return str(resp.text or "")


def _guarded(text: str) -> str:
    """模型产出过乱码闸门:能还原就还原,还原不了直接抛 —— 绝不把乱码传下去。"""
    from ..core.encoding import MojibakeError, ensure_text
    try:
        return ensure_text(text, where="文本模型返回内容")
    except MojibakeError as e:
        raise AIError(str(e)) from e


def chat(prompt: str, system: str | None = None, config_id: int | None = None,
         temperature: float = 0.7, max_tokens: int | None = None,
         json_mode: bool = False, timeout: int = 300,
         image_urls: list[str] | None = None) -> str:
    cfg = registry.check_ready("text", config_id)  # 未配置/缺 Key 直接拦下,不发空请求
    # 传了图但模型不是多模态 → 先说清楚再发:纯文本模型收下 image_url 后
    # 通常不会报错,而是回一句凭空编的描述(实测复刻的产品描述/人物外貌全是
    # 胡话,却一路走到生图才暴露)。这里只提示不拦 —— 名字判定只是启发式,
    # 万一标错了不该把用户的活儿挡下来。
    if image_urls and not registry.is_vision_model(cfg.get("model")):
        print(f"[text] ⚠ 模型 {cfg.get('model')!r} 不是多模态,却收到 "
              f"{len(image_urls)} 个媒体文件;返回内容很可能与素材无关。"
              f"在「设置 → AI 服务」里换一个带「多模态」标记的模型。", flush=True)
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    body = _build_body(cfg, prompt, system, temperature, max_tokens, json_mode, image_urls)
    # 网关要求 messages 里出现 json 字样才肯用 json_object;被拒就摘掉该参数重发
    # (runner.run_agent_json 已保证用户消息含该词,这里是兜底)。
    resp = requests.post(url, json=body, headers=headers, timeout=timeout)
    if resp.status_code != 200 and json_mode and _needs_json_word(resp.text):
        body.pop("response_format", None)
        resp = requests.post(url, json=body, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise AIError(f"文本模型请求失败 HTTP {resp.status_code}: {_err_text(resp)[:400]}")
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise AIError(f"文本模型响应格式异常: {data}") from e
    # 兼容部分中转站返回 reasoning + content 结构
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return _guarded(content or "")


def test_config(cfg: dict) -> tuple[bool, str]:
    try:
        url = cfg["base_url"].rstrip("/") + "/chat/completions"
        headers = {"Content-Type": "application/json"}
        if cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        resp = requests.post(url, json={
            "model": cfg["model"], "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8, "temperature": 0,
        }, headers=headers, timeout=30)
        if resp.status_code == 200:
            return True, "OK"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)
