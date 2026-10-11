# -*- coding: utf-8 -*-
"""阶段③配套:角色/场景/道具最终出图提示词(prompt_generator Agent)。"""
from __future__ import annotations

from ..agents import runner
from ..core import db


def _style_prefix(drama_id: int) -> str:
    from .comic import _style_for
    return _style_for(drama_id)


def _robust_json(agent: str, prompt: str, lang=None, config_id=None) -> dict:
    """跑 prompt_generator 并解析 JSON。

    关键:**系统提示词用内置无工具版覆盖**,不用 workspace 文件 —— 后者(含 15 语言
    skill)教模型「调用 read_scenes / save_*_final_prompt」,而本仓 runner 是单次调用
    没有工具,模型照做只会吐出工具调用文本(实测反复失败)。上下文已内联进用户消息。
    再加固:剥 DSML/<tool_call>/<think> 残留,失败重试一次。
    """
    import re as _re
    from ..agents.prompts import DEFAULT_PROMPTS, LANG_OUTPUT_NAME, LANGUAGE_SUFFIX
    from ..core.db import get_setting
    if lang is None:
        lang = get_setting("content_language", "zh")
    system = DEFAULT_PROMPTS.get("prompt_generator", "") + (
        "\n\n你没有工具,绝不输出任何工具调用、invoke、DSML 或思考过程;"
        "\n只输出一个 JSON 对象:{\"final_prompt\": \"...\"},不要解释。")
    if lang != "zh" and lang in LANG_OUTPUT_NAME:
        system += LANGUAGE_SUFFIX.format(lang=LANG_OUTPUT_NAME[lang])
    last_raw = ""
    for attempt in (1, 2):
        raw = runner.run_agent(agent, prompt, lang=lang, config_id=config_id,
                               json_output=True, temperature=0.4, system=system)
        last_raw = raw or ""
        cleaned = last_raw
        # 自带安全清洗(不依赖 novel._strip_tool_calls —— 那里的正则曾损坏且
        # 会被并行会话的旧副本覆盖回去):
        cleaned = _re.sub(r"<tool_call>.*?(?:</tool_call>|$)", "", cleaned, flags=_re.S)
        # deepseek 会输出 DSML 格式工具调用(<｜｜DSML｜｜tool_calls> 等)
        cleaned = _re.sub(r"<[^>]*DSML[^>]*>[\s\S]*?(?:</[^>]*DSML[^>]*>|$)", "", cleaned, flags=_re.S)
        cleaned = _re.sub(r"<invoke[\s\S]*?(?:</invoke>|$)", "", cleaned, flags=_re.S)
        cleaned = _re.sub(r"<parameter[\s\S]*?(?:</parameter>|$)", "", cleaned, flags=_re.S)
        cleaned = _re.sub(r"<invoke[\s\S]*?(?:</invoke>|$)", "", cleaned, flags=_re.S)
        cleaned = _re.sub(r"<parameter[\s\S]*?(?:</parameter>|$)", "", cleaned, flags=_re.S)
        cleaned = _re.sub(r"<think>.*?</think>", "", cleaned, flags=_re.S)
        cleaned = _re.sub(r"(?s)^.*?<think>", "", cleaned) if "<think>" in cleaned else cleaned
        data = runner.extract_json(cleaned)
        if isinstance(data, dict) and str(data.get("final_prompt") or "").strip():
            return data
    return {}


def character_prompt(character_id: int, config_id: int | None = None, lang: str | None = None) -> str:
    c = db.q1("SELECT * FROM characters WHERE id=?", (character_id,))
    if not c:
        raise RuntimeError("角色不存在")
    prompt = f"""目标类型:character(角色三视图参考图)
视觉风格前缀: {_style_prefix(c['drama_id'])}

角色: {c['name']}({'主角' if c['role_type']=='lead' else '配角' if c['role_type']=='supporting' else '龙套'})
样貌: {c['appearance'] or '未提供'}
妆造: {c['styling'] or '未提供'}"""
    data = _robust_json("prompt_generator", prompt, lang=lang, config_id=config_id)
    fp = (data or {}).get("final_prompt", "")
    if not fp:
        raise RuntimeError("提示词生成失败(重试后仍为空,请检查文本服务)")
    # 只落库正向提示词。质量守卫与负向词由 app/ai/prompt_guards.py 在**生图时统一追加**
    # (positive 走 apply_image_quality_guard、负面走 negative_prompt),不再拼接进资产
    # 提示词正文 —— 否则每个角色的 final_prompt 都拖着一段重复的守卫文本,详情页难以编辑,
    # 且正负向混写会削弱模型对正向描述的注意力。旧数据里已有的守卫不影响生图(marker 幂等)。
    final = fp
    db.ex("UPDATE characters SET final_prompt=?, final_prompt_style=?, updated_at=? WHERE id=?",
          (final, db.drama_style(c["drama_id"]), db.now(), character_id))
    return final


def scene_prompt(scene_id: int, config_id: int | None = None, lang: str | None = None) -> str:
    s = db.q1("SELECT * FROM scenes WHERE id=?", (scene_id,))
    if not s:
        raise RuntimeError("场景不存在")
    prompt = f"""目标类型:scene(场景空镜建立图)
视觉风格前缀: {_style_prefix(s['drama_id'])}

场景: {s['name']}
位置: {s['location'] or ''}
时间: {s['time'] or ''}
环境: {s['prompt'] or ''}
光照: {s['lighting'] or ''}"""
    data = _robust_json("prompt_generator", prompt, lang=lang, config_id=config_id)
    fp = (data or {}).get("final_prompt", "")
    if not fp:
        raise RuntimeError("提示词生成失败(重试后仍为空,请检查文本服务)")
    final = fp          # 场景空镜:守卫在生图时按 people=0 统一追加
    db.ex("UPDATE scenes SET final_prompt=?, updated_at=? WHERE id=?", (final, db.now(), scene_id))
    return final


def prop_prompt(prop_id: int, config_id: int | None = None, lang: str | None = None) -> str:
    p = db.q1("SELECT * FROM props WHERE id=?", (prop_id,))
    if not p:
        raise RuntimeError("道具不存在")
    prompt = f"""目标类型:prop(道具单品产品图)
视觉风格前缀: {_style_prefix(p['drama_id'])}

道具: {p['name']}({p['type'] or 'prop'})
描述: {p['description'] or ''}"""
    data = _robust_json("prompt_generator", prompt, lang=lang, config_id=config_id)
    fp = (data or {}).get("final_prompt", "")
    if not fp:
        raise RuntimeError("提示词生成失败(重试后仍为空,请检查文本服务)")
    final = fp          # 道具特写:守卫在生图时按 people=0 统一追加
    db.ex("UPDATE props SET final_prompt=?, updated_at=? WHERE id=?", (final, db.now(), prop_id))
    return final
