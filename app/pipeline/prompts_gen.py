# -*- coding: utf-8 -*-
"""阶段③配套:角色/场景/道具最终出图提示词(prompt_generator Agent)。

⚠️ 关键:这里生成的是**常规资产**的 final_prompt(写进 image_url 走 3D/写实路径),
不是漫画资产。必须用 dramas.style(项目设置里的视觉风格,如 3D),而**不是**
dramas.comic_style(项目级"温画画风",那是给 comic_image_url/漫画格用的)。

历史坑:此函数曾用 comic._style_for(),它优先级 comic_style > style > "3d" —
结果是用户选了 3D,出来的常规资产图全是漫画风。comic_asset_image() 里
"自修复"逻辑也因为 final_prompt 已经被漫画前缀污染、每次都判定不一致而反复重跑。
"""
from __future__ import annotations

from ..agents import runner
from ..core import db


def _style_prefix(drama_id: int) -> str:
    """常规资产风格前缀:严格用 dramas.style(3D/写实/...)。"""
    return db.style_prompt(db.drama_style(drama_id))


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
    # 三视图规范校验(对齐参考 ensureCharacterPrompt + prompt_generator 硬性约束):
    # ①必须含英文构图 token(character turnaround sheet 等 —— 模型对英文 token 权重最高,
    #   实测只写中文「三视图布局」会被无视,出单人立绘);②内容比风格前缀长不出 80 字的
    # 判为模型偷懒只回了前缀。不合格一律拦下重试
    prefix = _style_prefix(c["drama_id"])
    if len(fp) <= len(prefix) + 80:
        raise RuntimeError("提示词不合格:内容与风格前缀几乎等长,模型偷懒,请重试")
    # 三视图布局保证:英文 token 权重最高,但 glm 等模型常只写中文甚至漏写布局。
    # 中文等价词(三视图/正脸特写/三张全身)也算数;仍缺就**确定性补上**标准英文
    # 布局块 —— 此前直接 raise,任务失败、final_prompt 留空,生图只能走兜底
    # 单行提示词,出的全是单人立绘(灰袍散修实测)。补块幂等,不重复添加。
    # 判据只看**英文 token 在不在**,不能因为写了中文「三视图」就放过 ——
    # 图像模型不认中文布局词(实测中文三视图照样出单人立绘),放过等于没补。
    if not any(k in fp for k in ("turnaround", "reference sheet", "multi-view", "orthographic")):
        fp += (", character turnaround sheet, front-face close-up on the left, "
               "three equal-height full-body views on the right (front / 90-degree side / back), "
               "orthographic views, no perspective distortion")
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
