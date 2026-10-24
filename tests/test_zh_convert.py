# -*- coding: utf-8 -*-
"""简体→繁体转换(app/core/zh_convert.py)+ runner 出口挂钩。

这里的用例刻意挑**逐字替换会做错**的字:
  头发→頭髮(不是頭發)、里面→裡面、后来→後來、干杯→乾杯、
  软件→軟體(台湾用词,不是軟件)。
如果哪天有人把 OpenCC 换成一张单字表,这几个用例会立刻红。
"""
from __future__ import annotations

import pytest

from app.core import zh_convert


def test_ambiguous_chars_use_phrase_level_rules():
    """词组级消歧:同一句里的 發/髮、乾/幹、裡/里 必须分对。"""
    src = "他的头发很长,在里面开发软件,后来说:出发后干杯。"
    out = zh_convert.to_traditional(src)
    assert "頭髮" in out, f"头发→頭髮 错了: {out}"
    assert "頭發" not in out, f"出现了错误的 頭發: {out}"
    assert "裡面" in out, f"里面→裡面 错了: {out}"
    assert "軟體" in out, f"软件→軟體(台湾用词)错了: {out}"
    assert "後來" in out, f"后来→後來 错了: {out}"
    assert "乾杯" in out, f"干杯→乾杯 错了: {out}"


@pytest.mark.skipif(not zh_convert.available(), reason="未安装 opencc")
def test_conversion_preserves_non_chinese_and_punctuation():
    """ASCII / 数字 / 标点不能被动过 —— 稿子里混排很常见。"""
    src = "Chapter 3: 他掏出了 2,000 dollars, 然后说 \"Deal.\""
    out = zh_convert.to_traditional(src)
    assert "Chapter 3:" in out and "2,000 dollars" in out and '"Deal."' in out
    assert "他掏出了" in out


def test_pure_ascii_passthrough_is_cheap():
    """没有汉字时直接返回,不做无谓转换(每次 AI 调用都会走这里)。"""
    src = "# Episode 3 — nothing to convert here"
    assert zh_convert.to_traditional(src) is src or \
        zh_convert.to_traditional(src) == src


def test_empty_and_none_safe():
    assert zh_convert.to_traditional("") == ""
    assert zh_convert.to_traditional(None) == ""


def test_apply_output_language_only_touches_zh_hant():
    """只有 zh-Hant 才转;其余语种必须原样返回。"""
    src = "他的头发很长"
    for lang in ("zh", "en", "ja", "fr", None, "zh_CN"):
        assert zh_convert.apply_output_language(src, lang) == src, \
            f"lang={lang} 不该触发转换"


@pytest.mark.skipif(not zh_convert.available(), reason="未安装 opencc")
def test_apply_output_language_converts_for_zh_hant():
    out = zh_convert.apply_output_language("他的头发很长", "zh-Hant")
    assert "頭髮" in out


def test_missing_dependency_degrades_instead_of_crashing(monkeypatch):
    """缺依赖时退化成原样返回 —— 这跟 cryptography 的教训是同一类风险:
    顶层 import 缺失会让 `python -m app.main` 直接起不来,界面只闪一下就没了。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "opencc":
            raise ImportError("模拟未安装 opencc")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(zh_convert, "_cc", None)
    monkeypatch.setattr(zh_convert, "_failed", False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert zh_convert.available() is False
    assert zh_convert.to_traditional("他的头发很长") == "他的头发很长"


def test_runner_converts_only_for_zh_hant(monkeypatch):
    """runner 出口挂钩:zh-Hant 走转换,zh 走原样,with_meta 时只转 content。"""
    from app.agents import runner

    def fake_chat(*a, **kw):
        if kw.get("with_meta"):
            return "他的头发很长", {"finish_reason": "stop"}
        return "他的头发很长"

    monkeypatch.setattr(runner.text_client, "chat", fake_chat)

    assert "頭髮" in runner.run_agent("novel_writer", "x", lang="zh-Hant",
                                     system="s")
    assert runner.run_agent("novel_writer", "x", lang="zh", system="s") == "他的头发很长"

    content, meta = runner.run_agent("novel_writer", "x", lang="zh-Hant",
                                     system="s", with_meta=True)
    assert "頭髮" in content
    assert isinstance(meta, dict)


def test_json_output_stays_parseable_after_conversion(monkeypatch):
    """JSON 值转繁体后仍能被 json.loads 解析(键名是 ASCII,不受影响)。"""
    import json

    from app.agents import runner

    monkeypatch.setattr(runner.text_client, "chat",
                        lambda *a, **kw: '{"title": "他的头发很长", "n": 3}')
    raw = runner.run_agent("novel_writer", "x", lang="zh-Hant",
                           system="s", json_output=True)
    data = json.loads(raw)
    assert data["n"] == 3
    assert "頭髮" in data["title"]
