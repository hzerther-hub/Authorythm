# -*- coding: utf-8 -*-
"""阶段②:小说原文 → 格式化剧本(script_rewriter Agent)。"""
from __future__ import annotations

from ..agents import runner
from ..core import db
from . import script_quality


def rewrite_prompt(episode_id: int, style_hint: str = "") -> str:
    """构造改写剧本的提示词(供流式路径复用,避免与 rewrite_script 的拼法漂移)。"""
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("剧集不存在")
    raw = ep["content"] or ""
    if not raw.strip():
        raise RuntimeError("请先在「原始内容」粘贴或生成小说文本")
    return f"""请把以下原始内容改写为短剧格式化剧本(第 {ep['episode_number']} 集)。
{('文风要求:' + style_hint) if style_hint else ''}

要求:保留原故事主线与人物,补齐场景标题、动作描写与台词;
**你没有工具,不要输出任何工具调用或思考过程,直接输出剧本正文**。

原始内容:
{raw}"""


def rewrite_script(episode_id: int, style_hint: str = "", config_id: int | None = None,
                  lang: str | None = None) -> str:
    """AI 改写当前集原文为格式化剧本,写回 episodes.script_content。

    落库前过一遍**可拍性质量门**(`script_quality`):满篇画外音/一个人在一间屋里
    自说自话的剧本会被返工重写,仍不合格直接 RuntimeError —— 坏剧本不进库,
    下游分镜/视频不会拿到没法拍的稿子。
    """
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError("剧集不存在")
    raw = ep["content"] or ""
    if not raw.strip():
        raise RuntimeError("请先在「原始内容」粘贴或生成小说文本")
    prompt = f"""请把以下原始内容改写为短剧格式化剧本(第 {ep['episode_number']} 集)。
{('文风要求:' + style_hint) if style_hint else ''}

原始内容:
{raw}"""
    result = runner.run_agent("script_rewriter", prompt, config_id=config_id, lang=lang)
    # run_agent 的返回类型是 str | tuple(只有 with_meta=True 才是 tuple),
    # 这里取纯文本再进质量门。
    script = result if isinstance(result, str) else result[0]
    script = script_quality.enforce(
        script,
        lambda p: runner.run_agent("script_rewriter", p, config_id=config_id, lang=lang),
    )
    db.ex("UPDATE episodes SET script_content=?, updated_at=? WHERE id=?", (script, db.now(), episode_id))
    return script
