# -*- coding: utf-8 -*-
"""翻译服务:三级引擎依次降级,供 i18n 自动补翻与将来的运行时翻译使用。

    1. baidu-forward —— fortuneteller.top 转发(百度翻译),主力;需本机配 API Key
    2. google-gtx    —— translate.googleapis.com gtx 免费端点,免 key(限流按 IP)
    3. mymemory      —— MyMemory 免费端点(5000 词/天/IP),兜底

统一入口 `translate(text, target, source="zh")`;全部失败抛 TranslateError。
目标语言码与我们的一致(zh/en/ja/ko/ar/hi/id/th/tr/vi/fr/de/es/pt/it),
各引擎的差异在内部映射。
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

BAIDU_FORWARD_URL = "https://fortuneteller.top/api/translate"


def _baidu_forward_key() -> str:
    """取转发服务的 API Key —— 只从本机读,**代码里不内置**。

    这里曾经硬编码过一把真 key,并随仓库推到了 GitHub;而本仓库是 public,
    那把 key 等同于公开泄露过,已在 fortuneteller.top 后台作废。
    现在只认两处本机来源,优先级 环境变量 > 设置表:
      - 环境变量 `YIHAO_BAIDU_FORWARD_KEY`
      - 设置表键 `baidu_forward_key`(与 photocraft_install_dir 同一套机制,
        在 data/yihao.sqlite3 里,不进版本库)

    取不到返回空 → `_via_baidu` 抛 TranslateError → 自动降级到免 key 的
    google-gtx / mymemory。翻译不会因此不可用,只是慢一点、额度少一点。

    **别再把任何 key 写回这个文件**:光删代码不等于安全,git 历史里还在。
    仓库是 public,任何进过版本库的 key 都必须当作已泄露、去服务端作废重发。
    """
    from . import db
    return (os.environ.get("YIHAO_BAIDU_FORWARD_KEY", "")
            or db.get_setting("baidu_forward_key", "") or "").strip()


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
    key = _baidu_forward_key()
    if not key:
        # 不是异常,是「这台机器没配这把 key」—— 走降级链即可,别打断调用方
        raise TranslateError(
            "baidu-forward 未配置 API Key(设环境变量 YIHAO_BAIDU_FORWARD_KEY "
            "或设置表 baidu_forward_key)")
    req = urllib.request.Request(
        BAIDU_FORWARD_URL,
        data=json.dumps({"text": text, "from": source, "to": target}).encode(),
        headers={"Content-Type": "application/json",
                 "X-API-Key": key})
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

# 与中文同形、翻过去基本不变的词(品牌/技术名词),别拿它们当"没翻"的证据
_OK_IDENTITY = {"jev", "api key", "base url", "system prompt", "profile", "prompt",
                "id", "url", "token", "json", "sse", "csv", "png", "jpg", "mp4",
                "ai", "llm", "h264", "720p", "1080p"}


def _is_identity(text: str, out: str, target: str, source: str = "zh") -> bool:
    """判断引擎是不是把原文原样吐回来了。

    百度转发遇到拿不准的短词会直接透传,不报错也不换语言 —— 日文那档最明显,
    「生成封面」原样返回。拿这种结果去填语言包,等于把中文写进日文槽,比空着还糟。

    判据:目标语≠源语、结果与原文完全相同、且原文**含汉字**。
    含汉字才可疑;纯拉丁串(Jev/Base URL)本来就同形,不算透传。
    注意不能拿「含 U+2000 以上字符」当外文证据 —— 中文标点(。…、「」◇)全在那个区间,
    之前就是这么误判的。
    """
    if target == source or out != text:
        return False
    if text.strip().lower() in _OK_IDENTITY:
        return False
    return any(0x4E00 <= ord(c) <= 0x9FFF for c in text)


def translate(text: str, target: str, source: str = "zh") -> str:
    """三级降级翻译;全部失败抛 TranslateError(带最后一次的错误摘要)。"""
    text = (text or "").strip()
    if not text:
        return ""
    last = ""
    identity = ""
    for name, fn in ENGINES:
        try:
            out = fn(text, target, source)
            if out and _is_identity(text, out, target, source):
                identity = out
                last = f"{name}: 原文透传(未翻译)"
                continue
            if out:
                return out
            last = f"{name}: 空响应"
        except Exception as exc:  # noqa: BLE001
            last = f"{name}: {str(exc)[:110]}"
    if identity:
        # 全程只有透传:与其报错让调用方留空,不如把原文交回去,至少界面显示得出来
        return identity
    raise TranslateError(f"全部翻译引擎失败 —— {last}")


def translate_batch(items: list[tuple[str, str]], target: str, source: str = "zh",
                    interval: float = 0.15) -> list[str]:
    """批量翻译;保持顺序。单条内部已在 translate 里做三级降级。"""
    out = []
    for text in items:
        out.append(translate(text, target, source))
        time.sleep(interval)
    return out

