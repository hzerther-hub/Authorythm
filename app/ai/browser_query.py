# -*- coding: utf-8 -*-
"""浏览器 Agent 实时查询(jev-ultrafast):网页搜索拿不到的**实时数据**走这里。

分工对齐 jev-ultrafast 的设计(参考 Browser Use 官方文章):Jev 决策「点哪里/
填什么框」,文本模型只在需要往输入框打字时生成内容,程序执行真实点击。
典型场景:查火车车次要上 12306 真查 —— 网页搜索只能给出 12306 的**链接**,
拿不到实时余票。

软失败契约(全项目统一):包没装 / Chrome 没连上 / key 缺失 / 超时 / 任何异常
一律返回 None,调用方落到普通网页搜索。浏览器查询是增强项,不能因为它
把「查一下」变成不可用。

凭据全部从本机配置读(不落代码):TYPESAFE_API_KEY = 设置里 Jev 服务的
api_key(用户确认就是 TypeSafe 官方申请的那把);TEXT_MODEL_* = 默认文本
服务(OpenAI 兼容端点)。
"""
from __future__ import annotations

import os
import threading
import time

# jev-ultrafast 的 model.py 直接读进程环境变量;Agent 跑在 worker 线程里,
# 改 env 是进程级操作,加锁避免与其它线程的 LLM 调用互相踩
_ENV_LOCK = threading.Lock()

# 关键词 → 起始网址。Agent 自己会在站内导航/填表,这里只负责「上对车」。
# 没命中的话题返回 None(→ 调用方走普通网页搜索)。
_SITE_ROUTES: list[tuple[tuple[str, ...], str]] = [
    (("火车", "车次", "高铁", "动车", "12306", "火车票"), "https://www.12306.cn/index/"),
    (("航班", "机票", "飞机"), "https://www.fliggy.com/"),
    (("天气", "气温", "下雨"), "https://www.weather.com.cn/"),
    (("快递", "物流", "包裹"), "https://www.kuaidi100.com/"),
]

# 一次浏览器查询的预算。12306 这类站从打开到出结果实测十几步,90s 足够;
# 卡住就返回半程结果(页面文本可能已有有用信息),绝不无限等。
_MAX_SECONDS = 120


def pick_site(query: str) -> str | None:
    """按关键词选起始站点;不适合浏览器直查的话题返回 None。"""
    t = (query or "").strip()
    for keys, url in _SITE_ROUTES:
        if any(k in t for k in keys):
            return url
    return None


def available() -> tuple[bool, str]:
    """(可用, 不可用原因)。只查包与凭据,Chrome 连通性要在真跑时才知道。"""
    try:
        import jev_ultrafast  # noqa: F401
    except ImportError:
        return False, "jev-ultrafast 未安装"
    from . import registry
    jev = registry.list_configs("jev")
    if not jev or not ((jev[0].get("api_key") or "").strip()):
        return False, "未配置 Jev 服务(TypeSafe API Key)"
    txt = registry.list_configs("text")
    if not txt or not ((txt[0].get("api_key") or "").strip()):
        return False, "未配置文本模型(填表单时要用)"
    return True, ""


def _setup_env() -> tuple[str, str]:
    """把本机凭据注进 jev-ultrafast 读的环境变量,返回 (文本模型标注, 站点)。"""
    from . import registry
    jev = registry.list_configs("jev")[0]
    os.environ["TYPESAFE_API_KEY"] = (jev.get("api_key") or "").strip()
    os.environ.setdefault("TYPESAFE_MODEL", "jev-latest")
    # 文本模型优先 DeepSeek(OpenAI 兼容、便宜、非推理档填表快),没有再取默认
    txt = registry.list_configs("text")
    pick = next((c for c in txt if "deepseek" in (c.get("base_url") or "").lower()
                 or "deepseek" in (c.get("model") or "").lower()), txt[0])
    base = (pick.get("base_url") or "").strip().rstrip("/")
    os.environ["TEXT_MODEL_API_KEY"] = (pick.get("api_key") or "").strip()
    os.environ["TEXT_MODEL_BASE_URL"] = base if base.endswith("/v1") else base + "/v1"
    os.environ["TEXT_MODEL"] = pick.get("model") or "deepseek-chat"
    os.environ["TEXT_MODEL_REASONING"] = "none"   # 填表单要快,不要推理档
    return pick.get("model") or "", base


def _ensure_cdp() -> None:
    """确保有可连的 Chrome CDP,失败抛异常(调用方兜成 None)。

    browser-harness 默认找**日常 Chrome** 的调试口,日常 Chrome 没带调试启动
    时直接 fatal(实测:DevToolsActivePort not found)。所以这里自己拉一个
    **独立 profile** 的专用实例 —— 不碰用户正在用的浏览器窗口 —— 再把
    BU_CDP_WS 指给它。实例常驻,下次查询直接复用。
    """
    if os.environ.get("BU_CDP_WS"):
        return
    import json as _json
    import subprocess
    import urllib.request

    def _probe(port: int) -> str | None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version",
                                        timeout=2) as r:
                return _json.load(r).get("webSocketDebuggerUrl")
        except Exception:  # noqa: BLE001
            return None

    port = 9223
    ws = _probe(port)
    if not ws:
        from ..core import config
        exe = None
        for cand in (
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ):
            if os.path.exists(cand):
                exe = cand
                break
        if not exe:
            raise RuntimeError("本机没找到 Chrome/Edge")
        profile = config.STATIC_DIR / "chrome-agent"
        profile.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
             "--no-first-run", "--no-default-browser-check",
             "--window-size=1180,820", "about:blank"],
            cwd=str(profile))
        for _ in range(30):          # 最多等 30s 让 DevTools 口就绪
            ws = _probe(port)
            if ws:
                break
            time.sleep(1)
        if not ws:
            raise RuntimeError("Chrome 调试口未能启动")
    os.environ["BU_CDP_WS"] = ws


def _run_once(goal: str, url: str, max_seconds: int) -> dict | None:
    from jev_ultrafast import Agent
    import jev_ultrafast.agent as _ja
    # 官方 demo 预算 60 步,对 12306 这类重站不够(关弹窗/填两城/选日期就要
    # 几十步)。agent.py 是 `from .questions import MAX_STEPS` 拿的**值**,要改
    # 它自己命名空间里的那份才生效。
    _ja.MAX_STEPS = 120
    started = time.monotonic()
    steps = 0
    status = "unknown"
    with Agent(url, goal) as agent:
        for snap in agent.run():
            steps += 1
            status = snap.get("status") or status
            if time.monotonic() - started > max_seconds:
                print(f"[browser_query] 超时({max_seconds}s),取半程结果", flush=True)
                break
        final_url = ""
        try:
            final_url = agent.browser.evaluate("location.href") or ""
        except Exception:  # noqa: BLE001
            pass
        try:
            page_text = agent.browser.evaluate(
                "document.body ? document.body.innerText : ''") or ""
        except Exception:  # noqa: BLE001
            page_text = ""
    page_text = (page_text or "").strip()[:6000]
    if not page_text:
        return None
    return {"status": status, "steps": steps,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "page_text": page_text, "url": final_url}


def query(goal: str, url: str, max_seconds: int = _MAX_SECONDS) -> dict | None:
    """跑一次浏览器 Agent,返回 {status, steps, elapsed_ms, page_text, url}。

    goal 写**人话目标**(如「查宁波到淄博的火车车次」),Agent 自己读控件、
    填表、点查询。任何失败返回 None —— 调用方必须落回网页搜索,不许抛。

    **默认关闭**(设置表 browser_query_enabled=1 才启用):实测 12306 这类
    重站一次查询要烧 200+ 次 Jev 决策调用还可能走不完(官网 demo 是给
    Google Flights 调的),默认路径交给「网页搜索 + 抓结果页正文」,
    浏览器留给愿意花配额换实时性的人。

    Agent 打开的 Chrome 窗口是查询的工作窗口,查询期间关掉它会让 CDP
    断连(实测 "no close frame")—— 失败后重拉一次 Chrome 再试,两次都挂
    才放弃。
    """
    from ..core import db
    if (db.get_setting("browser_query_enabled", "0") or "0") != "1":
        return None
    ok, reason = available()
    if not ok:
        print(f"[browser_query] 不可用:{reason}", flush=True)
        return None
    with _ENV_LOCK:
        last_exc = None
        for attempt in (1, 2):
            try:
                from jev_ultrafast import Agent  # noqa: F401
                _setup_env()
                _ensure_cdp()
                return _run_once(goal, url, max_seconds)
            except Exception as exc:  # noqa: BLE001 —— Chrome 没连/harness 挂/网络,全兜
                last_exc = exc
                print(f"[browser_query] 第 {attempt} 次失败:{str(exc)[:160]}",
                      flush=True)
                os.environ.pop("BU_CDP_WS", None)   # 强制下一轮重拉 Chrome
        print(f"[browser_query] 两次均失败,落回网页搜索:{str(last_exc)[:120]}",
              flush=True)
        return None
