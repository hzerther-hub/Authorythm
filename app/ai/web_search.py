# -*- coding: utf-8 -*-
"""联网搜索(Bing → DuckDuckGo → 百度 三引擎自动回退),零第三方依赖。

移植自参考项目 D:\\drama\\tools.py 的 web_search 工具(实测可用),供聊天改图的
「知识问句」意图使用:用户问图片处理知识(「什么是高斯模糊?」「锐化和磨皮
有什么区别?」)时先搜再答,LLM 只负责基于搜索结果组织语言,不裸编。

软失败契约(与 stock_photo 同款):任何引擎全部失败返回 ([], 错误文案),
绝不抛异常打断业务 —— 搜不到就降级为纯 LLM 回答(调用方注明未经联网核实)。

结果带 10 分钟 TTL 缓存:知识问句常被反复问,同一个问题没必要反复打搜索引擎
(搜索引擎对高频抓取会弹验证码,那是三引擎集体失效的最常见原因)。
"""
from __future__ import annotations

import html
import re
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

DEFAULT_TIMEOUT_S = 12

# (title, url, snippet) 三元组列表
Hit = tuple[str, str, str]

_cache: dict[str, tuple[float, list[Hit]]] = {}
_CACHE_TTL_S = 600


def _strip_tags(s: str) -> str:
    """去掉 HTML 标签并还原实体,用于解析搜索结果页。"""
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _fetch_page(url: str) -> str:
    """抓取页面,失败返回空字符串(网络问题由调用方换引擎重试)。"""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": UA,
                          "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_S) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _parse_bing(page: str) -> list[Hit]:
    """解析 Bing 结果页:<h2><a href> 标题 + <p> 摘要。"""
    results: list[Hit] = []
    # 每个结果块 <li class="b_algo"> … <h2><a href="URL">标题</a></h2> … <p>摘要</p>
    for block in re.findall(r'<li class="b_algo".*?</li>', page, re.S):
        m = re.search(r'<h2[^>]*><a[^>]+href="([^"]+)"[^>]*>(.*?)</a></h2>',
                      block, re.S)
        if not m:
            continue
        url, title = m.group(1), _strip_tags(m.group(2))
        if not url.startswith("http"):
            continue
        snip_m = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
        snip = _strip_tags(snip_m.group(1)) if snip_m else ""
        results.append((title, url, snip))
    return results


def _parse_baidu(page: str) -> list[Hit]:
    """解析百度结果页:<h3> 标题链接 + c-abstract 摘要。"""
    results: list[Hit] = []
    for block in re.findall(r'<div class="result[^"]*"[^>]*>.*?</div>\s*</div>',
                            page, re.S):
        m = re.search(r'<h3[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                      block, re.S)
        if not m:
            continue
        url, title = m.group(1), _strip_tags(m.group(2))
        snip_m = re.search(
            r'class="c-abstract[^"]*"[^>]*>(.*?)(?:</span>|</div>)', block, re.S)
        snip = _strip_tags(snip_m.group(1)) if snip_m else ""
        results.append((title, url, snip))
        if len(results) >= 10:
            break
    return results


def _fetch_ddg_lite(query: str) -> str:
    """DuckDuckGo lite 版用 POST 表单查询,单独取页(GET html 版实测会给
    无关内容/异常页)。"""
    data = urllib.parse.urlencode({"q": query}).encode()
    try:
        req = urllib.request.Request(
            "https://lite.duckduckgo.com/lite/", data=data,
            headers={"User-Agent": UA,
                     "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                     "Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_S) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""


def _parse_duckduckgo(page: str) -> list[Hit]:
    """解析 DuckDuckGo HTML/Lite 版结果页。"""
    results: list[Hit] = []
    # html 版:结果链接 class="result__a",真实地址在 href 的 uddg= 参数里
    blocks = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        page, re.S)
    snips = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
    for i, (href, title) in enumerate(blocks):
        m = re.search(r"[?&]uddg=([^&]+)", href)
        url = urllib.parse.unquote(m.group(1)) if m else href
        snip = _strip_tags(snips[i]) if i < len(snips) else ""
        results.append((_strip_tags(title), url, snip))
    if results:
        return results
    # lite 版备用布局:链接 class='result-link',摘要在 class='result-snippet'。
    # 注意 href 可能在 class **前面**(实测 <a rel="nofollow" href="…" class='result-link'>),
    # 所以抓整个 <a> 标签再从属性串里提 href,别假定属性顺序。
    results = []
    for m in re.finditer(r"<a([^>]*?)class='result-link'([^>]*?)>(.*?)</a>",
                         page, re.S):
        attrs = m.group(1) + m.group(2)
        hm = re.search(r'href="([^"]+)"', attrs)
        if not hm:
            continue
        url = hm.group(1)
        m2 = re.search(r"[?&]uddg=([^&]+)", url)
        if m2:
            url = urllib.parse.unquote(m2.group(1))
        results.append((_strip_tags(m.group(3)), url, ""))
    snips = re.findall(r"class='result-snippet'[^>]*>(.*?)</td>", page, re.S)
    out: list[Hit] = []
    for i, (title, url, _s) in enumerate(results):
        snip = _strip_tags(snips[i]) if i < len(snips) else ""
        out.append((title, url, snip))
    return out


def search(query: str, max_results: int = 6,
           use_cache: bool = True) -> tuple[list[Hit], str]:
    """联网搜索,返回 (hits, 错误文案)。hits 为空时错误文案说明原因。

    顺序即优先级:Bing(对中文技术内容质量最稳)→ DuckDuckGo(不墙)→ 百度。
    """
    query = (query or "").strip()
    if not query:
        return [], "搜索词为空"
    now = time.time()
    if use_cache:
        hit = _cache.get(query)
        if hit and hit[0] > now:
            return hit[1][:max_results], ""

    q = query
    # 顺序即优先级。**DuckDuckGo lite 第一**:对无 cookie 的程序化请求最宽容、
    # 结果相关(实测「宁波到淄博的火车」返回 12306/携程/去哪儿);Bing 对
    # 这类客户端会**假装答了** —— 页面标题是对的,organic 结果却是无关内容
    # (实测返回塑料协会/翻译,比"没结果"更坑),降为第二引擎。
    engines: list[tuple[str, object, object]] = [
        ("DuckDuckGo", lambda: _fetch_ddg_lite(q), _parse_duckduckgo),
        ("Bing", lambda: _fetch_page(
            f"https://www.bing.com/search?q={urllib.parse.quote(q)}&setmkt=zh-CN&count=10"),
         _parse_bing),
        ("百度", lambda: _fetch_page(
            f"https://www.baidu.com/s?wd={urllib.parse.quote(q)}&rn=10"),
         _parse_baidu),
    ]
    tried: list[str] = []
    results: list[Hit] = []
    for name, fetch, parse in engines:
        tried.append(name)
        page = fetch()
        if not page:
            continue
        results = parse(page)
        if results:
            break

    if not results:
        return [], (f"已尝试 {'、'.join(tried)} 均无结果;稍后重试或换个问法")
    _cache[query] = (now + _CACHE_TTL_S, list(results))
    return results[:max_results], ""
