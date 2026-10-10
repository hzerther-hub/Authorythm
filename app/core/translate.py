# -*- coding: utf-8 -*-
"""翻译服务:三级引擎依次降级,供 i18n 自动补翻与将来的运行时翻译使用。

    1. baidu-forward —— fortuneteller.top 转发(百度翻译),主力;API_KEY 常量内置
    2. google-gtx    —— translate.googleapis.com gtx 免费端点,免 key(限流按 IP)
    3. mymemory      —— MyMemory 免费端点(5000 词/天/IP),兜底

统一入口 `translate(text, target, source="zh")`;全部失败抛 TranslateError。
目标语言码与我们的一致(zh/en/ja/ko/ar/hi/id/th/tr/vi/fr/de/es/pt/it),
各引擎的差异在内部映射。
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

BAIDU_FORWARD_URL = "https://fortuneteller.top/api/translate"
BAIDU_FORWARD_KEY = "***REMOVED-LEAKED-KEY***"


class TranslateError(RuntimeError):
    pass


def _post_json(url: str, payload: dict | None = None, timeout: int = 20) -> dict:
    if payload is not None:
        data = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json", "User-Agent": UA}
    else:
        data = None
        headers = {"User-Agent": UA}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _via_baidu(text: str, target: str, source: str) -> str:
    req = urllib.request.Request(
        BAIDU_FORWARD_URL,
        data=json.dumps({"text": text, "from": source, "to": target}).encode(),
        headers={"Content-Type": "application/json",
                 "X-API-Key": BAIDU_FORWARD_KEY})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = (data.get("text") or "").strip()
    if not out:
        raise TranslateError(f"baidu-forward 空响应: {str(data)[:120]}")
    return out


def _via_google(text: str, target: str, source: str) -> str:
    q = urllib.parse.quote(text)
    sl = "zh-CN" if source == "zh" else source
    url = (f"https://translate.googleapis.com/translate_a/single"
           f"?client=gtx&sl={sl}&tl={target}&dt=t&q={q}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = "".join(seg[0] for seg in data[0] if seg and seg[0]).strip()
    if not out:
        raise TranslateError("google-gtx 空响应")
    return out


def _via_mymemory(text: str, target: str, source: str) -> str:
    q = urllib.parse.quote(text[:500])
    sl = "zh-CN" if source == "zh" else source
    url = f"https://api.mymemory.translated.net/get?q={q}&langpair={sl}|{target}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = ((data.get("responseData") or {}).get("translatedText") or "").strip()
    if not out:
        raise TranslateError("mymemory 空响应")
    return out


# 顺序即优先级
ENGINES = [("baidu", _via_baidu), ("google", _via_google), ("mymemory", _via_mymemory)]


def translate(text: str, target: str, source: str = "zh") -> str:
    """三级降级翻译;全部失败抛 TranslateError(带最后一次的错误摘要)。"""
    text = (text or "").strip()
    if not text:
        return ""
    last = ""
    for name, fn in ENGINES:
        try:
            out = fn(text, target, source)
            if out:
                return out
            last = f"{name}: 空响应"
        except Exception as exc:  # noqa: BLE001
            last = f"{name}: {str(exc)[:110]}"
    raise TranslateError(f"全部翻译引擎失败 —— {last}")


def translate_batch(items: list[tuple[str, str]], target: str, source: str = "zh",
                    interval: float = 0.15) -> list[str]:
    """批量翻译;保持顺序。单条内部已在 translate 里做三级降级。"""
    out = []
    for text in items:
        out.append(translate(text, target, source))
        time.sleep(interval)
    return out

