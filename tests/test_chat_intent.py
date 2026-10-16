# -*- coding: utf-8 -*-
"""回归:聊天改图的意图路由 —— 问图内容必须进问答,不是进改图引擎。

实测 bug(用户报告「为什么系统认为我们要处理图片」):

  用户问「这张图片是什么内容?」,界面回「未能执行 —— 没有产出新图」。
  查证:JEV **判得完全正确**(本机实测 decide() 返回 choice=chat、置信度 1.0),
  但解析代码写的是 `str(answer) == "chat"`,而 `answers.intent` 是个**对象**
  `{"type": "choice", "choice": "chat", "confidence": 1.0, "probabilities": {...}}`
  —— dict 转字符串永远不等于 "chat",于是**每条消息都被判成 edit**,
  聊天分支从上线起就是死代码。与 AGENTS.md 记过的视频路由同款坑
  (choice 的答案在 `choice` 字段,不在外层)。
"""
from __future__ import annotations

# 本机 Jev 对「这张图片是什么内容?\n当前图: xxx.png」的真实响应(2026-10 实测)
_REAL_DECIDE_RES = {
    "model": "jev-1.13.0",
    "answers": {
        "intent": {
            "type": "choice",
            "choice": "chat",
            "confidence": 1.0,
            "probabilities": {"edit": 0.0, "chat": 1.0},
        }
    },
    "elapsed_ms": 953,
}


def test_parse_jev_intent_reads_choice_field_from_real_shape():
    from app.ui.chat_edit_drawer import _INTENT_CHAT, _parse_jev_intent

    assert _parse_jev_intent(_REAL_DECIDE_RES) == _INTENT_CHAT, (
        "真实 JEV 响应(answers.intent 是对象)必须解析出 chat —— "
        "str(dict) 永远不等于 'chat',这就是聊天分支成死代码的根因")


def test_parse_jev_intent_edit_and_fallbacks():
    from app.ui.chat_edit_drawer import _INTENT_EDIT, _INTENT_CHAT, _parse_jev_intent

    edit_res = {"answers": {"intent": {"type": "choice", "choice": "edit",
                                       "confidence": 0.9}}}
    assert _parse_jev_intent(edit_res) == _INTENT_EDIT
    # 兼容裸字符串形态(万一上游改成直接给值)
    assert _parse_jev_intent({"answers": {"intent": "chat"}}) == _INTENT_CHAT
    # 软建议器契约:None / 空对象 / 缺字段 一律 edit,不抛异常
    assert _parse_jev_intent(None) == _INTENT_EDIT
    assert _parse_jev_intent({}) == _INTENT_EDIT
    assert _parse_jev_intent({"answers": {}}) == _INTENT_EDIT


def test_question_messages_route_to_analysis():
    from app.ui.chat_edit_drawer import _looks_like_analysis

    assert _looks_like_analysis("这张图片是什么内容?")
    assert _looks_like_analysis("这是什么图")
    assert _looks_like_analysis("这个构图怎么样")
    assert _looks_like_analysis("描述一下画面里的人物")
    assert not _looks_like_analysis("改成黑白")
    assert not _looks_like_analysis("亮度+30")
    assert not _looks_like_analysis("去掉图片上的文字")
    assert not _looks_like_analysis("")
    # 编辑动词优先于疑问特征:「怎么改成黑白」是要改图,不是问问题
    assert not _looks_like_analysis("怎么把背景改成纯黑?")


def test_batch_analysis_command_not_captured_by_question_rule():
    """「分析…方案」是改图流程,问句规则不得抢走 —— job 里在规则前用
    _wants_batch_analysis 截走;这里守住两者的分工边界。"""
    from app.ai.photocraft_bridge import _wants_batch_analysis
    from app.ui.chat_edit_drawer import _looks_like_analysis

    for cmd in ("先分析这张图,再给 2 个方案", "分析构图,然后给 2 个方案"):
        assert _wants_batch_analysis(cmd), f"批分析命令没被识别:{cmd}"
        # 正因为问句规则对它们也可能为 True,job 里必须先截走
        if _looks_like_analysis(cmd):
            assert _wants_batch_analysis(cmd), (
                f"「{cmd}」会被问句规则抢进聊天,批分析保护失效")
