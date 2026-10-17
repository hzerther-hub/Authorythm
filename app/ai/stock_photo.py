# -*- coding: utf-8 -*-
"""免费图库检索(Unsplash / Pexels / Pixabay)—— 供「图片处理」「聊天改图」搜参考图。

实现参考 D:/webs/yijing/web/services/stock_photo_service.py 的做法,**按本仓约定重写**:
本仓用 `requests` 同步调用(那边是 httpx.AsyncClient),key 存 `ai_service_configs`
而不是远端 remote_config 表。

**三家鉴权方式各不相同,这是最容易踩的地方**:
    Pexels    Authorization: <key>
    Unsplash  Authorization: Client-ID <key>
    Pixabay   URL 参数 ?key=...(无鉴权头)

**软失败契约**(与 jev 一致):任何一家挂了都不影响其余两家,
全部失败时返回空结果列表,由调用方提示 —— 搜图是增强项,绝不能阻断改图主流程。

**尺寸分级**:图库同时给缩略图与原图两套 URL。检索一律返回缩略图(省流量),
真正下载入库时再取 download_url —— 直接拿原图做列表会烧配额。
"""
from __future__ import annotations

import requests

DEFAULT_TIMEOUT_S = 15.0
SOURCE_ORDER = ("pexels", "unsplash", "pixabay")

SOURCE_CN = {"pexels": "Pexels", "unsplash": "Unsplash", "pixabay": "Pixabay"}


def _cfg_rows() -> dict[str, dict]:
    """provider → 该图库的启用配置行。"""
    from ..core import db
    out: dict[str, dict] = {}
    for row in db.q("SELECT * FROM ai_service_configs "
                    "WHERE service_type='stockphoto' AND is_active=1 ORDER BY id"):
        p = (row["provider"] or "").strip().lower()
        if p in SOURCE_ORDER:
            out[p] = dict(row)
    return out


def configured_sources() -> list[str]:
    """已配置且启用的图库,按 SOURCE_ORDER 排。"""
    return [s for s in SOURCE_ORDER if s in _cfg_rows()]


def _photo(source: str, pid: str, preview: str, download: str,
           width: int = 0, height: int = 0, photographer: str = "",
           alt: str = "") -> dict:
    return {"id": f"{source}-{pid}", "source": source,
            "preview_url": preview, "download_url": download,
            "width": width, "height": height,
            "photographer": photographer, "alt": alt or photographer or "photo"}


def _search_pexels(key: str, query: str, page: int, per_page: int) -> list[dict]:
    r = requests.get("https://api.pexels.com/v1/search",
                     params={"query": query, "page": page, "per_page": per_page,
                             "orientation": "landscape"},
                     headers={"Authorization": key}, timeout=DEFAULT_TIMEOUT_S)
    r.raise_for_status()
    out = []
    for it in r.json().get("photos", []):
        s = it.get("src") or {}
        out.append(_photo(
            "pexels", str(it.get("id", "")),
            s.get("medium") or s.get("small") or s.get("large", ""),
            s.get("large") or s.get("large2x") or s.get("original", ""),
            int(it.get("width") or 0), int(it.get("height") or 0),
            str(it.get("photographer") or ""),
            str(it.get("alt") or it.get("photographer") or query)))
    return out


def _search_unsplash(key: str, query: str, page: int, per_page: int) -> list[dict]:
    r = requests.get("https://api.unsplash.com/search/photos",
                     params={"query": query, "page": page, "per_page": per_page,
                             "orientation": "landscape"},
                     # 注意:Unsplash 是 Client-ID 不是 Bearer —— 写成 Bearer 会 401
                     headers={"Authorization": f"Client-ID {key}"},
                     timeout=DEFAULT_TIMEOUT_S)
    r.raise_for_status()
    out = []
    for it in r.json().get("results", []):
        u = it.get("urls") or {}
        user = it.get("user") or {}
        out.append(_photo(
            "unsplash", str(it.get("id", "")),
            u.get("small") or u.get("thumb") or u.get("regular", ""),
            u.get("regular") or u.get("full") or u.get("raw", ""),
            int(it.get("width") or 0), int(it.get("height") or 0),
            str(user.get("name") or ""),
            str(it.get("alt_description") or it.get("description") or query)))
    return out


def _search_pixabay(key: str, query: str, page: int, per_page: int) -> list[dict]:
    # Pixabay 的 per_page 最小值是 3,传 1 会被拒
    r = requests.get("https://pixabay.com/api/",
                     params={"key": key, "q": query, "page": page,
                             "per_page": max(3, per_page),
                             "image_type": "photo", "orientation": "horizontal",
                             "safesearch": "true"},
                     timeout=DEFAULT_TIMEOUT_S)
    r.raise_for_status()
    out = []
    for it in r.json().get("hits", []):
        out.append(_photo(
            "pixabay", str(it.get("id", "")),
            it.get("previewURL") or it.get("webformatURL", ""),
            it.get("largeImageURL") or it.get("webformatURL", ""),
            int(it.get("imageWidth") or 0), int(it.get("imageHeight") or 0),
            str(it.get("user") or ""), str(it.get("tags") or query)))
    return out


def _searcher_for(source: str):
    """按名字从模块全局取搜索函数,**不要**在导入时把函数对象存进 dict。

    存对象会让 `monkeypatch.setattr(stock_photo, "_search_unsplash", ...)` 失效 ——
    dict 里还握着旧引用,测试怎么换都换不掉,整轮搜索结果全错还很难查。
    """
    return globals().get(f"_search_{source}")


def search(query: str, source: str = "all", page: int = 1,
           per_page: int = 12) -> tuple[list[dict], list[str]]:
    """搜图库。返回 (结果列表, 错误信息列表)。

    source: all | pexels | unsplash | pixabay
    单家失败只进 errors,不影响其余 —— 搜图是增强项,不该阻断改图。
    """
    query = (query or "").strip()
    if not query:
        return [], ["请输入搜索关键词"]
    rows = _cfg_rows()
    if not rows:
        return [], ["未配置图库 API Key,到「设置 → AI 服务」添加(类型选「图库」)"]
    if source != "all" and source not in rows:
        avail = "、".join(SOURCE_CN[s] for s in rows)
        return [], [f"图库 {SOURCE_CN.get(source, source)} 未配置,已配置:{avail}"]

    targets = ([source] if source != "all"
               else [s for s in SOURCE_ORDER if s in rows])
    photos: list[dict] = []
    errors: list[str] = []
    for src in targets:
        cfg = rows[src]
        key = (cfg.get("api_key") or "").strip()
        if not key:
            errors.append(f"{SOURCE_CN[src]}: 未填 API Key")
            continue
        try:
            fn = _searcher_for(src)
            if fn is None:
                errors.append(f"{SOURCE_CN[src]}: 未实现的适配器")
                continue
            photos.extend(fn(key, query, page, per_page))
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            # 401/403 = key 失效,这是最常见的一种,值得单独说清楚
            hint = "(API Key 无效或已失效,请到设置里更新)" if code in (401, 403) else ""
            errors.append(f"{SOURCE_CN[src]}: HTTP {code} {hint}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{SOURCE_CN[src]}: {type(exc).__name__} {str(exc)[:80]}")
    return photos, errors


def download(url: str, out_path) -> bool:
    """下载原图到本地。失败返回 False(调用方跳过该张)。

    url 也可以是**本地图库/换画风结果的本地路径** —— 直接复制,不走网络
    (换画风的「使用这张」传的就是本地转换结果,此前 requests.get 一个
    Windows 路径必然失败,表现为「换完画风却选不上」)。
    """
    if not url:
        return False
    if os.path.exists(url):                      # 本地路径:直接复制
        try:
            shutil.copyfile(url, out_path)
            return True
        except Exception:  # noqa: BLE001
            return False
    try:
        r = requests.get(url, timeout=30, stream=True)
        if r.status_code != 200:
            return False
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(64 * 1024):
                f.write(chunk)
        return True
    except Exception:  # noqa: BLE001
        return False


def test_source(source: str) -> tuple[bool, str]:
    """设置页「连接测试」:真发一次搜索请求验鉴权/可达性。"""
    rows = _cfg_rows()
    cfg = rows.get(source)
    if not cfg:
        return False, "未配置或已停用"
    key = (cfg.get("api_key") or "").strip()
    if not key:
        return False, "未填 API Key"
    try:
        fn = _searcher_for(source)
        if fn is None:
            return False, "未实现的适配器"
        got = fn(key, "test", 1, 3)
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        if code in (401, 403):
            return False, f"API Key 无效或已失效(HTTP {code})"
        return False, f"HTTP {code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"
    return True, f"可用 · 命中 {len(got)} 张"
