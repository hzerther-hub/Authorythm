# -*- coding: utf-8 -*-
"""文本模型调用的网络韧性 + 分批拆分的失败隔离回归。

背景(实测 2026-10-19,episodes#79 分镜拆分):
本机系统代理是 Clash `127.0.0.1:56561`,会**掐长连接** —— 短请求 1 秒就过,
动辄几分钟的生成会被 RemoteDisconnected / IncompleteRead 掐掉。那一次拆分的
第 4 批就死在 ProxyError 上,前 3 批已落库的 23 条分镜也跟着白拆。

两个缺陷:
1. `text_client.chat` 单次 `requests.post`,任何瞬时网络抖动直接冒给业务层,
   一次都不重试(而业务层会把它当成「模型不会写 JSON」,方向完全错了)。
2. `storyboard._boards_for_part` 只捕 RuntimeError;requests 的 ProxyError /
   ConnectionError / ReadTimeout / IncompleteRead 都不是 RuntimeError,
   于是一个批次失败 = 整集任务失败,与「整批没拿到就拆半重试」的设计相反。

**测试不许碰真实库/真实网络**:requests.post 与 db 全部打桩。
"""
from __future__ import annotations

import pytest
import requests

from app.ai import text_client
from app.pipeline import storyboard as sb


# ------------------------------------------------------------------ 网络重试

def test_retries_transient_network_error(monkeypatch):
    """第一次 ProxyError、第二次成功 → 不该把异常抛出去。"""
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(timeout)
        if len(calls) == 1:
            raise requests.exceptions.ProxyError("Unable to connect to proxy")
        class _R:
            status_code = 200
            text = "{}"
            content = b"{}"

            def json(self):
                return {"choices": [{"message": {"content": '{"ok":1}'}}]}
        return _R()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    assert text_client.chat("hi", system="s") == '{"ok":1}'
    assert len(calls) == 2


def test_gives_up_after_max_attempts(monkeypatch):
    """连挂到底 → 抛最后一次异常(不能无限重试)。"""
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(1)
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(requests.exceptions.ConnectionError):
        text_client._post_with_retry("u", {}, {}, 10)
    assert len(calls) == text_client.NET_RETRY_ATTEMPTS


def test_does_not_retry_http_errors(monkeypatch):
    """HTTP 4xx 是业务错误(鉴权/参数),不是瞬时故障 —— 只发一次。

    传回响应本身就算成功返回,重试逻辑在 `_post_with_retry` 里只在抛异常时触发,
    这条断言守住「别把 401 当网络抖动重试 3 次」。
    """
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(1)
        class _R:
            status_code = 401
            text = "unauthorized"
            content = b"unauthorized"
        return _R()

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(text_client.AIError):
        text_client.chat("hi", system="s")
    assert len(calls) == 1


# ------------------------------------------------------------------ 分批失败隔离

def test_network_error_degrades_to_batch_failure(monkeypatch):
    """网络异常必须降级成「这一批失败」,不能整集死掉。"""
    monkeypatch.setattr(sb.runner, "run_agent_json",
                        lambda *a, **k: (_ for _ in ()).throw(
                            requests.exceptions.ProxyError("Remote end closed connection")))
    ep = {"id": 79, "episode_number": 1}
    part = "## S01 | 甲 | 夜\n内容\n\n## S02 | 乙 | 夜\n内容\n"
    with pytest.raises(RuntimeError, match="分镜结果为空"):
        sb._boards_for_part(ep, "9:16", "", part, "第 01-02 场", lang=None, config_id=None)


def test_network_error_triggers_scene_split_retry(monkeypatch):
    """多场景批次遇网络异常,应拆成单场再试(而不是整集失败)。"""
    seen = []

    def fake_run(*a, **k):
        label = k.get("label") or ""
        seen.append(len(k.get("part", "")))
        if len(seen) == 1:
            raise requests.exceptions.ReadTimeout("timed out")
        return {"storyboards": [{"number": 1, "title": "x", "duration": 8}]}

    monkeypatch.setattr(sb.runner, "run_agent_json", fake_run)
    monkeypatch.setattr(sb, "_storyboard_prompt", lambda *a, **k: "p")
    got = sb._boards_for_part(
        {"id": 79, "episode_number": 1}, "9:16", "",
        "## S01 | 甲 | 夜\n内容\n\n## S02 | 乙 | 夜\n内容\n",
        "第 01-02 场", lang=None, config_id=None)
    assert got, "拆半后应该拿到分镜"
    assert len(seen) >= 2, "第一趟网络失败后应拆成单场重试"
