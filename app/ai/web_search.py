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
    # lite 版备用布局:链接 class='result-link',摘要在 class='result-snippet'
    blocks = re.findall(
        r"<a[^>]*class='result-link'[^>]*href=\"([^\" )]+)\"[^>]*>(.*?)</a>",
        page, re.S)
    snips = re.findall(r"class='result-snippet'[^>]*>(.*?)</td>", page, re.S)
    for i, (url, title) in enumerate(blocks):
        m = re.search(r"[?&]uddg=([^&]+)", url)
        real = urllib.parse.unquote(m.group(1)) if m else url
        snip = _strip_tags(snips[i]) if i < len(snips) else ""
        results.append((_strip_tags(title), real, snip))
    return results


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

    q = urllib.parse.quote(query)
    engines: list[tuple[str, str, object]] = [
        ("Bing", f"https://www.bing.com/search?q={q}&setmkt=zh-CN&count=10",
         _parse_bing),
        ("DuckDuckGo", f"https://html.duckduckgo.com/html/?q={q}",
         _parse_duckduckgo),
        ("百度", f"https://www.baidu.com/s?wd={q}&rn=10", _parse_baidu),
    ]
    tried: list[str] = []
    results: list[Hit] = []
    for name, url, parse in engines:
        tried.append(name)
        page = _fetch_page(url)
        if not page:
            continue
        results = parse(page)
        if results:
            break

    if not results:
        return [], (f"已尝试 {'、'.join(tried)} 均无结果;稍后重试或换个问法")
    _cache[query] = (now + _CACHE_TTL_S, list(results))
    return results[:max_results], ""
