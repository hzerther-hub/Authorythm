# -*- coding: utf-8 -*-
"""生成文本的乱码检测与修复(mojibake guard)。

现象:章节正文整段变成 ``æ□®e□³□`` 这种鬼样子。成因是**UTF-8 字节被按别的编码
解读**一次(或多次),典型于某些中转网关/代理在转发时按 latin-1 或 GBK 解了一遍。

实测结论(本模块的 _repair 的依据):
- **latin-1 / cp1252 误读可 100% 还原** —— 按当初误读的编码重新编码回去、再用
  utf-8 解即可严格往返;
- **GBK 误读救不回来** —— UTF-8 字节流里存在 GBK 非法序列,解码器必须开
  errors="replace",丢掉的字节变成 U+FFFD,永久损毁。所以 GBK 这类只能在**源头**
  防(响应一律显式 utf-8 解码),事后无法救。

因此本模块的策略是:
1. 检测(looks_mojibake)——不靠单点阈值,靠「往返后是否明显变好」自证;
2. 修复(repair)——按候选编码逐一试往返,用质量分挑出最优;
3. 闸门(ensure_text)——修不好就抛错,**绝不让脏数据静默落库**。
   静默存坏数据比直接失败难查得多:界面上看不出任何异常,用户只会以为模型不好用。
"""
from __future__ import annotations

import re

__all__ = ["looks_mojibake", "repair", "ensure_text", "MojibakeError"]

# 候选误读编码,按还原成功率排序:latin-1 无损(能映射全部 256 字节)排最前
_CANDIDATES = ("latin-1", "cp1252", "gbk", "gb18030", "big5")

# UTF-8 被按单字节编码解读后必然出现的字符(latin-1 补充区 + 部分 CJK 兼容区)
_MOJIBAKE_CHARS = set(
    "ÃÂÐÑÞß"          # latin-1 补充里 UTF-8 序列的常见首字节
    "¡¢£¤¥¦§¨©ª«¬"  # 0xA1-0xBF 段
    "®¯°±²³´µ¶·¸¹º»¼½¾¿"  # 0xAE-0xBF 段
    "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ"  # 0xC0-0xD6
    "æçèéêëìíîïðñòóôõöøùúûüýþÿ"  # 小写同段
)

_REPLACEMENT = "�"


class MojibakeError(RuntimeError):
    """文本损坏且无法还原 —— 调用方应当让这次生成失败,而不是把脏数据存下去。"""


def _sample(text: str, n: int = 1200) -> str:
    """只取前 n 个字符做判据,避免长文本上做无谓的全量统计。"""
    return text[:n]


def _quality(text: str) -> float:
    """文本「像不像正常中文」的质量分,越高越好。

    = CJK 字符占比 + 1 - 乱码特征字符占比 - 替换字符占比
    """
    s = _sample(text)
    if not s:
        return 1.0
    cjk = sum(1 for c in s if "一" <= c <= "鿿" or "㐀" <= c <= "䶿")
    bad = sum(1 for c in s if c in _MOJIBAKE_CHARS)
    repl = s.count(_REPLACEMENT)
    n = len(s)
    return (cjk / n) - (bad / n) * 1.5 - (repl / n) * 3.0


def looks_mojibake(text: str) -> bool:
    """这段文本是不是乱码。

    判定不靠单一阈值,而是问「能不能往返出一段明显更好的文本」——能,就是乱码。
    这样正常中文不会被误伤,也不用去调那个很容易过期的密度阈值。
    """
    if not text or len(text) < 8:
        return False
    s = _sample(text)
    # 替换字符是铁证:解码失败过,信息已丢失
    if _REPLACEMENT in s:
        return True
    bad_ratio = sum(1 for c in s if c in _MOJIBAKE_CHARS) / len(s)
    if bad_ratio < 0.02:
        return False
    return _repair(text) is not None


def _repair(text: str) -> str | None:
    """逐一试往返编码,返回质量提升最明显的结果;都不行返回 None。"""
    base = _quality(text)
    best, best_gain = None, 0.0
    for enc in _CANDIDATES:
        try:
            cand = text.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue                      # 这条编码路径解不通,换下一条
        if _REPLACEMENT in cand:
            continue                      # 修完还有替换字符 = 丢过信息,不算修好
        gain = _quality(cand) - base
        if gain > best_gain:
            best, best_gain = cand, gain
    # 要求明显提升才算数,避免把正常文本"修"成别的样子
    return best if best_gain >= 0.15 else None


def repair(text: str) -> str | None:
    """尝试还原乱码;本来就不是乱码则原样返回;无法还原返回 None。"""
    if not text:
        return text
    if not looks_mojibake(text):
        return text
    return _repair(text)


def ensure_text(text: str, *, where: str = "生成结果") -> str:
    """落库前的闸门:能修就修,修不了就抛 MojibakeError。

    where 只用于报错文案,让失败时能直接看出是哪一步出的问题。
    """
    if not text:
        return text
    if not looks_mojibake(text):
        return text
    fixed = _repair(text)
    if fixed is not None:
        return fixed
    s = _sample(text, 40)
    raise MojibakeError(
        f"{where}解码异常且无法还原(疑似上游按非 UTF-8 编码返回),"
        f"已中止以免存下乱码。样本:{s!r}"
    )