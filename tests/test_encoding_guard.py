# -*- coding: utf-8 -*-
"""生成文本乱码防护的回归测试。

真实故障:章节正文整段变成 ``æ□®e□³□``。成因是 UTF-8 字节被按 latin-1/GBK 解了
一遍 —— 常见于中转网关转发时。

关键取舍(改代码前请先读):
- **latin-1 / cp1252 误读可 100% 还原** —— 按误读编码编回、再用 utf-8 解;
- **GBK 误读救不回来** —— UTF-8 字节流含 GBK 非法序列,解码器必须 errors="replace",
  丢的字节变 U+FFFD,永久损毁。所以 GBK 这类只能靠「发现就中止」保住数据,
  不能事后修。

对应地,策略是:能修就修,修不了**抛错中止**,绝不静默把脏数据落库。
"""
from __future__ import annotations

import pytest

from app.core.encoding import (MojibakeError, ensure_text, looks_mojibake,
                               repair)

GOOD = "陈默摘下工牌的时候，指尖在塑料卡套边缘停了一下。会议室里的中央空调嗡嗡响。" * 10
LATIN1 = GOOD.encode("utf-8").decode("latin-1")
GBK_LOSSY = GOOD.encode("utf-8").decode("gbk", errors="replace")


# ── 正常文本绝不能被误判 ──
@pytest.mark.parametrize("text", [
    GOOD,
    "第 1 集 · 原始内容 —— 原始内容字数 3603/4000 字\n换行\n" * 10,
    "The quick brown fox jumps over the lazy dog. " * 20,
    "模型 MiniMax-M3 分辨率 720P ratio=16:9 " * 10,
    "café naïve résumé " * 15,
    "a" * 200,
])
def test_normal_text_not_flagged(text):
    assert not looks_mojibake(text)
    assert ensure_text(text) == text, "正常文本被改写了 —— 这是最严重的误伤"


def test_short_text_ignored():
    """短文本(标题、单字)不做判定,避免边界抖动。"""
    for t in ("", "好", "OK", "æ"):
        assert not looks_mojibake(t)
        assert ensure_text(t) == t


# ── 可还原的:必须能修回来 ──
def test_latin1_mojibake_detected_and_repaired():
    assert looks_mojibake(LATIN1)
    assert repair(LATIN1) == GOOD
    assert ensure_text(LATIN1) == GOOD


def test_repair_returns_none_when_unrepairable():
    """修不了时要老实返回 None,而不是把原文原样吐回去假装修好了。"""
    # (曾经的"双重 latin-1"用例删掉了:latin-1→utf-8→latin-1 是恒等变换,
    #  根本构造不出二次乱码,那个用例是错的。)
    assert repair(GBK_LOSSY) is None


# ── 不可还原的:必须抛错而不是静默落库 ──
@pytest.mark.parametrize("text", [
    GBK_LOSSY,
    GOOD.encode("utf-8").decode("cp1252", errors="replace"),
])
def test_lossy_mojibake_raises_instead_of_storing(text):
    assert looks_mojibake(text), "有损乱码也必须被识别出来"
    with pytest.raises(MojibakeError):
        ensure_text(text, where="章节正文")


def test_error_message_carries_context():
    """报错要能指出是哪一步崩的,否则排障时无从下手。"""
    with pytest.raises(MojibakeError) as ei:
        ensure_text(GBK_LOSSY, where="审校修复正文")
    assert "审校修复正文" in str(ei.value)


# ── 闸门真的接在生成链路上 ──
def test_novel_gate_repairs_and_blocks():
    from app.pipeline.novel import _gate_content
    assert _gate_content(GOOD, "章节正文") == GOOD
    assert _gate_content(LATIN1, "章节正文") == GOOD      # 能修
    with pytest.raises(MojibakeError):
        _gate_content(GBK_LOSSY, "章节正文")              # 修不了 → 中止


def test_text_client_gate():
    from app.ai.text_client import _guarded
    assert _guarded(GOOD) == GOOD
    assert _guarded(LATIN1) == GOOD
    with pytest.raises(Exception):
        _guarded(GBK_LOSSY)


def test_error_text_decoder_does_not_use_guessed_encoding():
    """错误文案必须显式 utf-8 解,不能走 requests 的 apparent_encoding。

    缺 charset 时 charset_normalizer 常把中文猜成 GBK/Big5,报错本身就变乱码,
    排障时满屏鬼画符反而看不出问题在哪。
    """
    from app.ai.text_client import _err_text

    class FakeResp:
        # 模拟 requests 无 charset 时猜错:resp.text 是乱码,content 是正确 UTF-8
        content = "生成失败:上游返回非 UTF-8 内容".encode("utf-8")
        text = "ç¡æµŽè¯·ä¸ªæµŽæ­¤"

    out = _err_text(FakeResp())
    assert "上游返回非 UTF-8" in out
    assert "ç¡æµŽ" not in out, "仍在用 guessed 的 resp.text"