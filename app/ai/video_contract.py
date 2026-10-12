# -*- coding: utf-8 -*-
"""视频请求契约:入参归一化 + 上限校验 + 错误分类 + retry_at 跟随。

对齐参考项目 `backend/src/routes/tasks.ts` 的 normalizeVideoRequest / validateVideoRequest
与 `backend/src/services/generation.ts` 的 isFallbackableError / retry_at 跟随。

放在独立模块的原因:校验规则是**纯函数**,不碰网络,可以用构造请求逐条断言;
`video_client` 只在入口调一次,避免把网关相关的分支堆进本来就很大的生成函数里。
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

# 官方 Wan 3.0 input.media 支持的 type
WAN_MEDIA_TYPES = {"first_frame", "last_frame", "reference_image",
                   "reference_video", "reference_audio", "file", "link"}

# 各上限(对齐原版)
ALIYUN_LIMITS = {"image": 10, "video": 5, "audio": 5, "total": 20}
GENERIC_LIMITS = {"image": 9, "video": 3, "audio": 3}

# retry_at 跟随
UPSTREAM_RETRY_AT_MAX_FOLLOWS = 2      # 最多跟随 2 次
UPSTREAM_RETRY_AT_MAX_WAIT_S = 24 * 3600   # 单次最多睡 24h
UPSTREAM_RETRY_AT_BUFFER_S = 5         # 额外 5s 余量

RETRY_AT_RE = re.compile(
    r"try again after\s*(?P<ts>[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9:]{5,8}(?:\s*(?:UTC|Z))?)",
    re.IGNORECASE)


def normalize_video_request(body: dict) -> dict:
    """兼容两种入参形态:本仓扁平参数,与官方 Wan 3.0 的 `input.media[] / parameters{}`。

    扁平形态的字段全部保留;官方形态按 type 分流到对应字段,原始 media 放进 `official_media`。
    """
    inp = body.get("input") if isinstance(body.get("input"), dict) else {}
    params = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
    media = inp.get("media") if isinstance(inp.get("media"), list) else []

    def urls(kind: str) -> list[str]:
        return [str(m.get("url")) for m in media
                if isinstance(m, dict) and m.get("type") == kind and m.get("url")]

    out = dict(body)
    out["prompt"] = body.get("prompt") or inp.get("prompt") or ""
    out["reference_image_urls"] = body.get("reference_image_urls") or urls("reference_image")
    out["reference_video_urls"] = body.get("reference_video_urls") or urls("reference_video")
    out["reference_audio_urls"] = body.get("reference_audio_urls") or urls("reference_audio")
    out["first_frame_url"] = body.get("first_frame_url") or (urls("first_frame") or [None])[0]
    out["last_frame_url"] = body.get("last_frame_url") or (urls("last_frame") or [None])[0]
    out["file_url"] = body.get("file_url") or (urls("file") or [None])[0]
    out["link_url"] = body.get("link_url") or (urls("link") or [None])[0]
    out["generate_audio"] = body.get("generate_audio", params.get("audio"))
    out["duration"] = body.get("duration", params.get("duration"))
    out["aspect_ratio"] = body.get("aspect_ratio", params.get("ratio"))
    out["resolution"] = body.get("resolution", params.get("resolution"))
    out["official_media"] = media
    return out


def validate_video_request(body: dict, provider: str | None = None) -> str | None:
    """返回错误说明(None = 通过)。规则逐条对齐原版 validateVideoRequest。"""
    for key in ("reference_image_urls", "reference_video_urls", "reference_audio_urls"):
        v = body.get(key)
        if v is not None and not isinstance(v, list):
            return f"{key} 必须为数组"
        if isinstance(v, list) and any(not isinstance(u, str) or not u.strip() for u in v):
            return f"{key} 中的每个 URL 都必须为非空字符串"

    media = body.get("official_media") or []
    if media:
        for item in media:
            if (not isinstance(item, dict) or item.get("type") not in WAN_MEDIA_TYPES
                    or not isinstance(item.get("url"), str) or not item["url"].strip()):
                return "input.media 中的每项都必须包含官方支持的 type 和非空 url"
        for kind in ("first_frame", "last_frame", "file", "link"):
            if sum(1 for m in media if m.get("type") == kind) > 1:
                return f"Wan 3.0 input.media 中 {kind} 最多 1 项"

    imgs = len(body.get("reference_image_urls") or [])
    vids = len(body.get("reference_video_urls") or [])
    auds = len(body.get("reference_audio_urls") or [])
    first = bool(body.get("first_frame_url"))
    last = bool(body.get("last_frame_url"))
    file = bool(body.get("file_url"))
    link = bool(body.get("link_url"))

    if (provider or "").lower() == "aliyun":
        lim = ALIYUN_LIMITS
        if imgs > lim["image"] or vids > lim["video"] or auds > lim["audio"]:
            return "Wan 3.0 参考素材超限:图片≤10、视频≤5、音频≤5"
        if last and not first:
            return "Wan 3.0 尾帧必须与首帧同时传入"
        if file and link:
            return "Wan 3.0 file 与 link 不能同时传入"
        if (first or last) and (imgs + vids + auds > 0 or file or link):
            return ("Wan 3.0 的 first_frame/last_frame 不能与 "
                    "reference_image/reference_video/reference_audio/file/link 混用")
        total = imgs + vids + auds + int(first) + int(last) + int(file) + int(link)
        if total > lim["total"]:
            return "Wan 3.0 input.media 最多 20 项"
    else:
        lim = GENERIC_LIMITS
        if imgs > lim["image"] or vids > lim["video"] or auds > lim["audio"]:
            return "参考素材超限:图片≤9、视频≤3、音频≤3"
        if auds > 0 and imgs + vids == 0:
            return "参考音频需要至少 1 个参考图片或视频"

    if not str(body.get("prompt") or "").strip() and imgs + vids + auds == 0 and not (first or last or file or link):
        return "视频生成需要至少一个参考素材或 prompt"
    return None


def check_request(prompt: str, first_frame: str | None, reference_images: list[str] | None,
                  provider: str | None) -> None:
    """把本仓的扁平调用参数拼成请求体后校验;不通过直接抛错(请求根本不发出)。"""
    body = {"prompt": prompt, "first_frame_url": first_frame,
            "reference_image_urls": list(reference_images or [])}
    err = validate_video_request(normalize_video_request(body), provider)
    if err:
        raise ValueError(err)


def is_fallbackable_error(err) -> bool:
    """是否值得「换个渠道再试」。

    上游临时性限流 / 队列满 / 网关抖动 → True;
    4xx 客户端错误(缺 Key、参数错、模型下线)→ False —— 回退只会浪费配额并掩盖真问题。
    """
    if not err:
        return False
    msg = str(getattr(err, "message", "") or err).lower()
    return any(k in msg for k in (
        "queue_full", "video_queue_full", "rate limit", "too many requests",
        "service unavailable", "gateway timeout", "bad gateway",
        "api error 502", "api error 503", "api error 504", "api error 429",
        "try again after"))


def is_permanent_error(err) -> bool:
    """是否立即失败、不再退避重试。

    - 带 HTTP 状态的协议错误:4xx 客户端错 → 永久(408/409/425/429 除外);
    - requests 网络层异常(连接reset/超时)→ 可重试;
    - **其余一律永久**:没有 HTTP 语义又非网络抖动的,基本是本地代码 bug
      (AttributeError/TypeError/KeyError…)。之前这类也被当可重试,实测
      WindowsPath.startswith 崩溃被白白退避重试 4 次(30s/45s/68s),
      既浪费时间又把真错误埋进重试链末尾。
    """
    msg = str(getattr(err, "message", "") or err)
    m = re.search(r"HTTP (\d{3})", msg)
    if m:
        code = int(m.group(1))
        if 400 <= code < 500:
            # 408/429 是请求超时与限流,仍属可恢复
            return code not in (408, 409, 425, 429)
        return False
    try:
        import requests
        if isinstance(err, requests.exceptions.RequestException):
            return False
    except ImportError:  # pragma: no cover
        pass
    return True


def parse_retry_at(text: str) -> datetime | None:
    """从上游文案里解析 `Please try again after <datetime>`;解析不出返回 None。

    接受 `2026-10-09 15:30:00 UTC` / `...Z` / 无时区后缀等写法,一律按 UTC 解释
    (与参考项目 generation.ts 的 new Date(t) 一致)。
    """
    m = RETRY_AT_RE.search(text or "")
    if not m:
        return None
    raw = m.group("ts").strip()
    raw = re.sub(r"\s*(UTC|GMT|Z)$", "", raw, flags=re.IGNORECASE).strip()
    raw = raw.replace(" ", "T")
    for length, fmt in ((19, "%Y-%m-%dT%H:%M:%S"), (16, "%Y-%m-%dT%H:%M")):
        if len(raw) >= length:
            try:
                return datetime.strptime(raw[:length], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


def retry_at_wait_seconds(text: str, follows_used: int) -> float | None:
    """算出「该睡多久」;不该跟随时返回 None。

    最多跟随 2 次;单次超过 24h 直接放弃(上游时间戳不可信时不能把任务挂死)。
    """
    if follows_used >= UPSTREAM_RETRY_AT_MAX_FOLLOWS:
        return None
    dt = parse_retry_at(text)
    if dt is None:
        return None
    wait = (dt - datetime.now(timezone.utc)).total_seconds() + UPSTREAM_RETRY_AT_BUFFER_S
    if wait <= 0:
        return 0.0
    if wait > UPSTREAM_RETRY_AT_MAX_WAIT_S:
        return None
    return wait


def fallback_enabled() -> bool:
    """跨 provider 回退是否开启(默认关,与参考项目当前策略一致)。

    参考项目已被用户策略压成单点模型:失败就直接报,不悄悄切到别的模型掩盖真问题。
    需要兜底时用 `YIHAO_VIDEO_FALLBACK=1` 打开。
    """
    return (os.environ.get("YIHAO_VIDEO_FALLBACK") or "").strip().lower() in ("1", "true", "yes", "on")