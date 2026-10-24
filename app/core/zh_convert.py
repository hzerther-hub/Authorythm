# -*- coding: utf-8 -*-
"""简体 ↔ 繁体转换(内容语言 = zh-Hant 时使用,不走 AI)。

为什么用 OpenCC 而不是自带字表:
逐字替换会错在语义上。「干」要变幹/乾/干、「发」要变發/髮、「后」要变後/后、
「里」要变裡/里、「面」要变麵/面 —— 单字映射表挑不出唯一正确答案,实测错误率
2-5%,而这些字在短剧稿里全是高频(「头发」「里面」「后来」「干杯」)。
OpenCC 带词组级消歧表,同一句实测:

    s2twp: 他的头发很长,在里面开发软件,后来说:出发后干杯。
       → 他的頭髮很長,在裡面開發軟體,後來說:出發後乾杯。
                  ^頭髮  ^裡面        ^軟體(台湾用词,不是軟件)  ^乾杯

选 `s2twp` 而不是 `s2t`:s2t 只换字形,「软件」会留成「軟件」;香港台湾读者
看到的是「軟體」。`s2twp` 还带台湾惯用词转换。

**依赖缺失不许崩**:本模块在 import 期就可能失败(用户没装
opencc-python-reimplemented)。这跟 `app/core/secrets.py` 顶层 import cryptography
是同一类风险 —— 漏装会让 `python -m app.main` 直接 ModuleNotFoundError 起不来,
界面上只是一闪而过,像是「双击没反应」。所以这里退化成「原样返回」+ 记一次
warning,用户顶多拿到简体中文,而不是整个 App 打不开。
"""
from __future__ import annotations

import threading

from .logging_setup import get_logger

log = get_logger(__name__)

# s2twp = 简体 → 台湾正字 + 台湾惯用词
_CONVERTER = "s2twp"

_lock = threading.Lock()
_cc = None          # OpenCC 实例
_failed = False     # 依赖缺失只警告一次,避免每次调用刷一行日志


def _get():
    """惰性拿转换器;缺依赖时返回 None(只警告一次)。"""
    global _cc, _failed
    if _cc is not None or _failed:
        return _cc
    with _lock:
        if _cc is not None or _failed:
            return _cc
        try:
            from opencc import OpenCC
            _cc = OpenCC(_CONVERTER)
        except Exception as exc:  # noqa: BLE001 —— 缺依赖/词典损坏都不能崩
            _failed = True
            log.warning("zh_convert: OpenCC 不可用(%s),zh-Hant 内容将保持简体。"
                        "装依赖:pip install opencc-python-reimplemented", exc)
    return _cc


def available() -> bool:
    """转换器是否可用(UI 用来给「内容语言 = 繁体中文」加提示角标)。"""
    return _get() is not None


def to_traditional(text: str) -> str:
    """简体 → 繁体(台湾正字+用词)。转换器不可用时原样返回。"""
    if not text or not any("一" <= ch <= "鿿" for ch in text):
        return text or ""
    cc = _get()
    if cc is None:
        return text
    try:
        return cc.convert(text)
    except Exception as exc:  # noqa: BLE001 —— 单条内容转换失败不该拖垮整次调用
        log.warning("zh_convert: 转换失败(%s),原样返回", exc)
        return text


def apply_output_language(text: str, lang: str | None) -> str:
    """按内容语言决定是否转繁体。**只有 zh-Hant 会转换**,其余语种原样返回。

    在 `runner.run_agent` 出口统一调用 —— 一处覆盖全部 34 个调用点(含未来新增的)。
    JSON 输出也安全:键名是 ASCII,`json.loads` 不受影响,只有中文值被转换。
    """
    if lang != "zh-Hant":
        return text
    return to_traditional(text)
