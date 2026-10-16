# -*- coding: utf-8 -*-
"""视频生成客户端:volcengine(Seedance) / minimax / aliyun(Wan) / agnes / runninghub / xiaoyunque(小云雀),提交+轮询+下载。"""
from __future__ import annotations

def _utf8_text(resp, limit: int = 400) -> str:
    """错误文案按 utf-8 显式解码。

    requests 在缺 Content-Type charset 时会走 apparent_encoding(charset_normalizer 猜),
    中文报错常被猜成 GBK/Big5 → 报错本身变乱码,排障时满屏鬼画符。
    """
    try:
        t = resp.content.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        t = str(getattr(resp, "text", "") or "")
    return t[:limit]

import re
import time
import uuid
from pathlib import Path

import threading

import requests

from ..core import config
from . import registry
from .text_client import AIError

RESOLUTION_TIERS: dict[str, list[str]] = {
    # 对齐原版 RESOLUTION_TIERS(按厂商分档)
    "volcengine": ["480p", "720p"],
    "minimax": ["768P", "2K"],
    "aliyun": ["480P", "720P", "1080P"],
    # agnes 的 size 只认 720P/1080P/1K/2K 四个档位字符串(传像素值直接 400)。
    # 完整档位表见 agnes_video.SIZE_TIERS_FULL;UI 侧还会按型号再收窄
    # (flash 锁死 720P,见 episode_page._sync_res_tiers)。
    "agnes": ["720P", "1080P", "1K", "2K"],
    "xiaoyunque": ["480p", "720p", "1080p"],
}


def _ext_for(url: str) -> str:
    low = (url.split("?")[0] or "").lower()
    return Path(low).suffix or ".mp4"


def _download(url: str) -> Path:
    """下载成片。

    成片地址是上游给的 CDN 直链(通常带签名),**不带任何鉴权头** —— 带上上游
    API 的 Authorization 会被 CDN 直接挡回 401。对齐参考项目 generation.ts:867
    的 `downloadFile(videoUrl, 'videos')`:第三个参数 headers 不传,内部裸下,
    也不做「401 再带鉴权重试」—— 重试只会用同样错误的凭据再失败一次,白白多耗
    一个 600 秒超时的连接。
    """
    out = config.STATIC_DIR / "videos" / f"{uuid.uuid4().hex}{_ext_for(url)}"
    resp = requests.get(url, timeout=600)
    if resp.status_code != 200:
        raise AIError(f"下载生成视频失败 HTTP {resp.status_code}")
    out.write_bytes(resp.content)
    return out


_IMAGE_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif"}

# 上传前参考图的长边上限。参考图原图是 1920×1080 的 PNG(实测中位 3.3MB),
# 8 张满配 base64 后请求体可达 36MB —— 上游极易撞体积上限,提交阶段也会慢到超时。
# 生图链路早按参考项目口径压到 768px(image_client._ref_data_url),视频链路此前漏了这一步。
_UPLOAD_MAX_SIDE = 768
_UPLOAD_QUALITY = 68

# agnes 例外:官方给参考图的额度很宽(单图 <15MB、整请求 <50MB、单边 256–5760px,
# 参考图本身不计费),沿用 768px 等于把画质上限白扔一半 —— 首帧只有 768px 时,出
# 1080P/2K 的画面必然发糊,而首帧细节基本决定整段成片的清晰度。这里按**实际下发
# 的 size 档位**给长边(官方 16:9 输出像素:720P=1280 / 1080P=1920 / 2K=2560,
# 1K 固定 1024x1024),质量提到 q82。
# 实测体积(1920x1080 源图,纯高频噪声 = JPEG 最坏情况,真实照片远小于此):
#   768/q68 → 79KB/张  |  1280/q82 → 483KB/张  |  1920/q82 → 1.35MB/张
# 8 张满配 base64 约 14MB,仍在 50MB 总额度内,且单张远低于 15MB 上限。
_UPLOAD_PROFILE_AGNES: dict[str, tuple[int, int]] = {
    "720P": (1280, 82), "1080P": (1920, 82), "1K": (1024, 82), "2K": (2560, 82)}
_data_url_cache: dict = {}


def _upload_profile(cfg: dict, resolution: str | None) -> tuple[int, int]:
    """参考图内联压缩档位 (长边上限, JPEG 质量)。agnes 按目标档位给足,其余厂商维持 768/q68。

    档位走 agnes_video.effective_size:flash 选了 1080P 会被钳到 720P,此时首帧
    压到 1280 就够,压到 1920 只是白撑请求体。
    """
    if (cfg.get("provider") or "").strip().lower() == "agnes":
        from .agnes_video import DEFAULT_MODEL, effective_size
        tier = effective_size(cfg.get("model") or DEFAULT_MODEL, resolution)
        return _UPLOAD_PROFILE_AGNES.get(tier, _UPLOAD_PROFILE_AGNES["720P"])
    return _UPLOAD_MAX_SIDE, _UPLOAD_QUALITY


def _upload_bytes(path: Path, mime: str,
                  max_side: int | None = None, quality: int | None = None) -> bytes:
    """上传用字节:图片等比缩进 max_side 的框内、**统一转 JPEG**。

    对齐参考项目 backend/src/utils/storage.ts 的 compressImageAsDataUrl:
      sharp(...).resize({width:768,height:768,fit:'inside',withoutEnlargement:true})
      有 alpha → flatten 白底 → .jpeg({quality:68})
    即参考项目没有 PNG 这个选项,一律 image/jpeg。我们此前直接塞 1920×1080
    原图(中位 3.3MB),8 张满配 base64 可达 36MB。

    缩不动 / 非图片 / 解码失败时回退原文件字节,绝不因压缩失败而丢图。

    max_side / quality 缺省走全局 768/q68;agnes 由 _upload_profile 按目标 size 档位
    传入更大的框(见该函数上方注释)。
    """
    side = max_side or _UPLOAD_MAX_SIDE
    q = quality or _UPLOAD_QUALITY
    if not mime.startswith("image/"):
        return path.read_bytes()
    try:
        import io
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im.load()
            im = ImageOps.exif_transpose(im)      # 对齐 .rotate():按 EXIF 自动摆正
            if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            elif im.mode != "RGB":
                im = im.convert("RGB")
            im.thumbnail((side, side), Image.LANCZOS)  # inside + 不放大
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q, optimize=True)
            return buf.getvalue()
    except Exception:  # noqa: BLE001
        return path.read_bytes()


def _has_alpha(im) -> bool:
    try:
        return im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
    except Exception:  # noqa: BLE001
        return False


def _fetch_remote_as_data_url(url: str, max_side: int | None = None,
                              quality: int | None = None) -> str | None:
    """远程参考图 → 下载后压缩成 data URL(对齐参考项目 fetchImageAsCompressedDataUrl)。

    只在下载确实失败时返回 None,由调用方决定丢弃或原样透传 —— 对 Agnes 来说
    公网 URL 本身就是合法媒体,所以宁可透传也不要悄悄把用户绑定的参考图弄丢。
    """
    import tempfile
    try:
        import requests
        from PIL import Image
        resp = requests.get(url, timeout=60)
        if resp.status_code != 200 or not resp.content:
            return None
        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tf:
            tf.write(resp.content)
            tmp = Path(tf.name)
        try:
            with Image.open(tmp) as probe:
                probe.load()
                fmt = (probe.format or "PNG").upper()
            mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp",
                    "GIF": "image/gif", "BMP": "image/bmp"}.get(fmt, "image/png")
            return (f"data:{mime};base64," + base64.b64encode(
                _upload_bytes(tmp, mime, max_side, quality)).decode())
        finally:
            tmp.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        return None


def _local_to_data_url(path: str | Path, max_side: int | None = None,
                       quality: int | None = None) -> str:
    """本地图片 → 压缩 data URL(默认缩进 768 框内,统一 JPEG q68,见 _upload_bytes)。

    已是 data: / http(s): 的原样透传 —— 前者不重复编码,后者交给调用方决定
    (Agnes 接受公网 URL 作为合法媒体)。非图片文件(音视频)退回 octet-stream。
    """
    import base64
    text = str(path or "")
    if not text:
        return text
    if text.startswith(("data:", "http://", "https://")):
        return text
    p = Path(text)
    if not p.exists():
        return text
    st = p.stat()
    # 压缩档位进缓存 key:同一张图按 720P 与按 2K 下发是两段不同的 data URL,
    # 漏掉会导致先小后大被小的那份命中缓存,画质白提。
    key = (str(p), st.st_mtime_ns, st.st_size, max_side or 0, quality or 0)
    hit = _data_url_cache.get(key)
    if hit is not None:
        return hit
    mime = _IMAGE_MIME.get(p.suffix.lower(), "application/octet-stream")
    if mime.startswith("image/"):
        url = "data:image/jpeg;base64," + base64.b64encode(
            _upload_bytes(p, mime, max_side, quality)).decode()
    else:
        url = f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
    if len(_data_url_cache) >= 32:      # 批量逐镜会反复用同一批图,小缓存即可命中
        _data_url_cache.clear()
    _data_url_cache[key] = url
    return url


def _poll(fetch_status, interval: int, rounds: int) -> str:
    """轮询直至返回最终视频 URL;失败抛 AIError。对齐原版 video 10s×300。"""
    for _ in range(rounds):
        time.sleep(interval)
        status, url, err = fetch_status()
        if url:
            return url
        if status == "failed":
            raise AIError(f"视频任务失败: {err}")
    raise AIError("视频任务轮询超时")


def suggest_video_config(visual_need: str) -> tuple[int, dict, bool] | None:
    """按画面需求建议视频配置,返回 (config_id, 分布, 低置信)。不可用 → None。

    **只建议,不自动改写用户的选择** —— 换供应商等于换钱,必须由用户拍板。
    调用方拿 None 时什么都不用做(继续用当前所选配置),这就是「jev 没开也能正常跑」。

    第三个返回值 low=True 表示 jev 自己也不确定(前二名分布差距 <0.15),
    UI 应据此如实说明,别把它包装成明确建议。
    """
    try:
        from .jev_ask import pick_video_config_advisory
        return pick_video_config_advisory(visual_need)
    except Exception:  # noqa: BLE001 —— 软建议器契约
        return None


def generate_video(prompt: str, resolution: str = "720p", duration: int | None = None,
                   first_frame: str | None = None, config_id: int | None = None,
                   reference_images: list[str] | None = None,
                   aspect_ratio: str | None = None,
                   last_frame: str | None = None, seed=None,
                   on_progress=None) -> tuple[Path, str]:
    """文生视频 / 图生视频(first_frame 本地路径)。

    reference_images:@角色 形象参考图本地路径列表(角色一致性)。
    aspect_ratio:项目画幅(如 9:16)。对齐参考项目 `ratio: record.aspectRatio || 'adaptive'`
    —— 不传时 seedance 默认出 1:1 方图,竖屏项目全变方块,必须显式下发。
    agnes 走多模态参考注入;volcengine 以 reference_image 角色注入;minimax/aliyun 忽略。
    返回 (本地路径, provider)。

    last_frame / seed / on_progress 是为 agnes 官方文档能力加的**全可选**参数:
    只有 agnes 会真正用它们,其余 provider 忽略(其余分支照旧)。不传 = 行为与
    加这些参数之前完全一致,现有 3 个调用点无需改动。

    last_frame 有一处**必须知道的行为**:agnes 官方规定 keyframe 模式禁止同时带
    images/audios/videos。所以一旦下发尾帧,整镜就进 keyframe 模式,参考图不再下发,
    角色一致性只能靠首帧/尾帧本身(首帧是身份锁定的,见 shot_tools.generate_first_frame)。
    seed 同 seed 可复现,便于对比调参。

    **平台级质量守卫**:prompt 统一追加视频质量要求 + 表演克制 + 节奏三层守卫(各自 marker 幂等)。
    视频模型对肢体畸形与强情绪词(尖叫/嘶吼/痛哭)都天生放大,需在平台层压住;
    确需爆发表情的镜头,在分镜 video_prompt 里显式写「情绪爆发」覆盖表演守卫。

    视频供应商路由走 `suggest_video_config`,**不在这里自动改写 config_id**:
    生成主体路径保持「用户选什么就用什么」,路由建议是旁路能力,详见该函数 docstring。
    """
    from .prompt_guards import apply_video_guards
    prompt = apply_video_guards(prompt)
    cfg = registry.check_ready("video", config_id)  # 未配置/缺 Key 直接拦下
    provider = cfg["provider"]
    # 契约校验:请求发出去之前就拒,让上游不明的 400 变成可读的本地原因(对齐 routes/tasks.ts)
    from .video_contract import check_request
    check_request(prompt, first_frame, reference_images, provider)
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    base = cfg["base_url"].rstrip("/")
    # 参考图/首帧的内联压缩档位:agnes 按目标 size 档位给足长边,其余厂商维持 768/q68
    max_side, quality = _upload_profile(cfg, resolution)
    refs = [_local_to_data_url(r, max_side, quality) for r in (reference_images or [])][:4]

    # 提交 + 轮询整体走重试包装:永久错误立即失败,限流/队列满按长预算退避,
    # 上游给了 retry_at 时间戳就睡到那一刻(最多跟 2 次)。
    # 限流预算 30 分钟对齐参考 RATE_LIMIT_CREATE_BUDGET_MS(实测 Agnes 拥塞可持续
    # 20 分钟+),所有 provider 的限流路径同待遇。
    return _generate_with_retry(
        lambda: _dispatch_once(cfg, base, headers, prompt, resolution, duration,
                               first_frame, refs, config_id, reference_images or [],
                               aspect_ratio, max_side, quality,
                               last_frame, seed, on_progress))


def _dispatch_once(cfg, base, headers, prompt, resolution, duration,
                   first_frame, refs, config_id, reference_images, aspect_ratio=None,
                   max_side=None, quality=None,
                   last_frame=None, seed=None, on_progress=None):
    """按 provider 分发一次(不含重试)。"""
    provider = cfg["provider"]
    if provider == "volcengine":
        body: dict = {"model": cfg["model"], "content": [
            {"type": "text", "text": prompt + f" --resolution {resolution}" +
             (f" --duration {duration}" if duration else "") +
             (f" --ratio {aspect_ratio}" if aspect_ratio else "")}]}
        for ref in refs:
            body["content"].append({"type": "image_url", "image_url": {"url": ref},
                                    "role": "reference_image"})
        if first_frame:
            # 首帧**必须带 role** —— Seedance 报 `role must be specified for image
            # contents`(HTTP 400)。参考图那条带了 role 所以一直没事,首帧这条漏了,
            # 只要分镜有首帧就 400。
            body["content"].append({
                "type": "image_url", "role": "first_frame",
                "image_url": {"url": _local_to_data_url(first_frame, max_side, quality)}})
        resp = requests.post(_ark_url(base, "/contents/generations/tasks"), json=body, headers=headers, timeout=120)
        if resp.status_code not in (200, 201):
            raise AIError(f"Seedance 提交失败 HTTP {resp.status_code}: {_utf8_text(resp)[:300]}")
        task_id = resp.json().get("id")
        if not task_id:
            raise AIError(f"Seedance 响应缺少 id: {_utf8_text(resp)[:300]}")

        def check():
            st = requests.get(_ark_url(base, f"/contents/generations/tasks/{task_id}"),
                              headers=headers, timeout=60).json()
            status = st.get("status", "")
            video = (st.get("content") or {}).get("video_url") if isinstance(st.get("content"), dict) else None
            return ("failed" if status == "failed" else "running"), video, st.get("error")

        url = _poll(check, POLL_INTERVAL_S, POLL_MAX_ROUNDS)
        return _download(url), provider

    if provider == "minimax":
        body = {"model": cfg["model"], "prompt": prompt}
        if first_frame:
            body["first_frame_image"] = _local_to_data_url(first_frame, max_side, quality)
        resp = requests.post(f"{base}/video_generation", json=body, headers=headers, timeout=120)

        def check2():
            st = requests.get(f"{base}/query/video_generation?task_id={task_id}", headers=headers, timeout=30).json()
            status = st.get("status", "")
            file = (st.get("file") or {}) if isinstance(st.get("file"), dict) else {}
            return ("failed" if status == "Fail" else "running"), file.get("download_url"), st.get("message")

        url = _poll(check2, POLL_INTERVAL_S, POLL_MAX_ROUNDS)
        return _download(url), provider

    if provider == "aliyun":
        body = {"model": cfg["model"], "input": {"prompt": prompt},
                "parameters": {"size": "1280*720" if "720" in resolution.upper() else "960*480"}}
        resp = requests.post(f"{base}/api/v1/services/aigc/video-generation/video-synthesis",
                             json=body, headers=headers, timeout=120)
        if resp.status_code not in (200, 201):
            raise AIError(f"Wan 提交失败 HTTP {resp.status_code}: {_utf8_text(resp)[:300]}")
        task_id = resp.json().get("output", {}).get("task_id")

        def check3():
            st = requests.get(f"{base}/api/v1/tasks/{task_id}", headers=headers, timeout=30).json()
            out = st.get("output", {})
            status = out.get("task_status", "")
            url_v = out.get("video_url")
            if status == "SUCCEEDED" and url_v:
                return "running", url_v + ("?Expires=" + str(int(time.time()) + 86400)), None
            return ("failed" if status in ("FAILED", "CANCELED") else "running"), None, out.get("message")

        url = _poll(check3, POLL_INTERVAL_S, POLL_MAX_ROUNDS)
        return _download(url), provider

    if provider == "agnes":
        # 对齐参考项目 agnes-video.ts + 官方文档:POST /v1/videos、mode 按 model 版本映射
        # (v2.0→ti2vid,素材进 first_frame/image_url/images)、素材上限、size 只认
        # 720P/1080P/1K/2K 档位(flash 锁死 720P,由 effective_size 钳制)、
        # 轮询走 {origin}/agnesapi?video_id=&model_name=(不在 /v1 下)、成片地址取顶层 url
        from .agnes_video import generate_agnes
        url_v = generate_agnes(cfg, base, headers, prompt=prompt, resolution=resolution,
                               duration=duration, first_frame=first_frame,
                               last_frame=last_frame,
                               reference_images=reference_images,
                               aspect_ratio=aspect_ratio, seed=seed,
                               ref_side=max_side, ref_quality=quality,
                               on_progress=on_progress)
        return _download(url_v), provider

    if provider == "runninghub":
        return _generate_runninghub(cfg, base, headers, prompt, resolution, duration,
                                    first_frame, refs, config_id, max_side, quality)

    if provider == "xiaoyunque":
        # 小云雀要原始本地路径(上传换 asset_id),不能传 data URL,故传 reference_images 原列表
        return _generate_xiaoyunque(cfg, base, headers, prompt, resolution, duration,
                                    first_frame, reference_images or [])

    raise AIError(f"不支持的视频 provider: {provider}")


# ── RunningHub(对齐原版 b78f9bf:openapi v2,Seedance 2.5 + Wan 3.0 参考生视频)──
RUNNINGHUB_MODELS = {
    "seedance-2.5": {"endpoint": "/bydedance/seedance-2.5-token/multimodal-video",
                      "img": 30, "vid": 10, "aud": 10},
    "wan3.0-video": {"endpoint": "/alibaba/wan-3.0/reference-to-video",
                     "img": 10, "vid": 5, "aud": 5},
    "wan3.0-video-prime": {"endpoint": "/alibaba/wan-3.0/reference-to-video",
                           "img": 10, "vid": 5, "aud": 5},
}


def _rh_normalize_duration(d) -> int:
    try:
        n = int(float(d))
    except (TypeError, ValueError):
        n = 5
    return min(30, max(2, n))


def _rh_normalize_resolution(res: str, is_wan: bool) -> str:
    r = (res or "").strip()
    if r.upper() == "2K":
        return "1080P" if is_wan else "2K"
    if r.upper() in ("480P", "1080P"):
        return r.upper()
    return "720P"


def _rh_find_video_url(node, depth: int = 0):
    """递归找第一个 .mp4 URL;优先按字段名顺序,避免封面图抢先命中。"""
    if depth > 8:
        return None
    if isinstance(node, str):
        return node if re.match(r"^https?://\S+\.mp4(\?\S*)?$", node, re.I) else None
    if isinstance(node, dict):
        for key in ("video_url", "videoUrl", "video", "url", "result_url", "resultUrl"):
            if key in node:
                hit = _rh_find_video_url(node[key], depth + 1)
                if hit:
                    return hit
        for v in node.values():
            hit = _rh_find_video_url(v, depth + 1)
            if hit:
                return hit
    elif isinstance(node, list):
        for v in node:
            hit = _rh_find_video_url(v, depth + 1)
            if hit:
                return hit
    return None


def _generate_runninghub(cfg, base, headers, prompt, resolution, duration,
                         first_frame, refs, config_id, max_side=None, quality=None):
    import json as _json
    model_key = (cfg["model"] or "").strip()
    spec = RUNNINGHUB_MODELS.get(model_key)
    if not spec:
        raise AIError("RunningHub 视频仅支持 seedance-2.5 / wan3.0-video(-prime),当前: " + model_key)
    is_wan = model_key.startswith("wan3")
    imgs = list(refs)
    if len(imgs) > spec["img"]:
        raise AIError(f"RunningHub 参考素材超限:图片≤{spec['img']}")
    # 首帧图 unshift 到首位,保持「第一张参考图锁脸」语义
    if first_frame:
        d_url = _local_to_data_url(first_frame, max_side, quality)
        if d_url not in imgs:
            imgs.insert(0, d_url)
    if not imgs and not prompt.strip():
        raise AIError("RunningHub 生成需要至少一个参考图/视频或 prompt")
    dur = _rh_normalize_duration(duration)
    res = _rh_normalize_resolution(resolution, is_wan)
    # 厂商私有开关:settings.realPersonMode 显式为 false 才关(默认 true)
    settings = {}
    try:
        s = _json.loads(cfg.get("settings") or "")
        if isinstance(s, dict):
            settings = s
    except Exception:  # noqa: BLE001
        pass
    body: dict = {"prompt": prompt.replace("@图片(\\d+)", r"图\1"),
                  "imageUrls": imgs, "resolution": res, "duration": dur}
    if is_wan:
        body["aspectRatio"] = "自适应"
        body["audio"] = True
    else:
        body["ratio"] = "自适应"
        body["generateAudio"] = True
        body["watermark"] = False
        body["realPersonMode"] = settings.get("realPersonMode") is not False
    submit = requests.post(f"{base}/openapi/v2{spec['endpoint']}", json=body,
                           headers=headers, timeout=120)
    if submit.status_code not in (200, 201):
        raise AIError(f"RunningHub 提交失败 HTTP {submit.status_code}: {submit.text[:300]}")
    r = submit.json()
    task_id = (r.get("taskId") or r.get("task_id") or (r.get("data") or {}).get("taskId")
               or (r.get("data") or {}).get("task_id") or r.get("id"))
    if not task_id:
        raise AIError(f"[RunningHub] {r.get('msg') or r.get('message') or '响应中缺少 taskId'}")

    def check():
        st = requests.post(f"{base}/openapi/v2/query", json={"taskId": task_id},
                           headers=headers, timeout=30).json()
        payload = st.get("data") or st
        s = str(payload.get("status") or payload.get("state") or "").lower()
        if s in ("success", "succeeded", "completed", "complete"):
            return "running", _rh_find_video_url(payload), None
        if s in ("failed", "failure", "error", "cancelled", "canceled"):
            return "failed", None, (payload.get("msg") or payload.get("message")
                                    or payload.get("failMsg") or payload.get("fail_msg"))
        return "running", None, None

    url = _poll(check, POLL_INTERVAL_S, POLL_MAX_ROUNDS)
    return _download(url), "runninghub"


# ── 小云雀(剪映 xyq.jianying.com):沉浸式短片 API,计费走小云雀积分(会员折扣价)──
# 文档:https://bytedance.larkoffice.com/docx/CQOYdJNLioLz6fxRzKXcCsKLnJh
XIAOYUNQUE_AGENT = "pippit_video_part_agent"  # 文档要求 agent_name 固定传此值


def xiaoyunque_credit_balance(cfg: dict) -> str:
    """查询小云雀积分余额(api_key 即官网【CLI/API】申请的 Access Key)。失败抛 AIError。"""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    try:
        resp = requests.post(f"{cfg['base_url'].rstrip('/')}/api/biz/v1/skill/get_credit_balance",
                             json={}, headers=headers, timeout=30)
    except requests.RequestException as e:
        raise AIError(f"小云雀积分查询失败: {e}") from e
    if resp.status_code != 200:
        raise AIError(f"小云雀积分查询失败 HTTP {resp.status_code}: {_utf8_text(resp)[:200]}")
    r = resp.json()
    if str(r.get("ret")) != "0":
        raise AIError(f"小云雀积分查询失败: {r.get('errmsg') or str(r)[:200]}")
    return str((r.get("data") or {}).get("total_remain_amount") or "0")


def _xy_resolve_path(path: str | Path) -> Path | None:
    """首帧/参考图可能存的是 /static/ 媒体地址,统一转本地路径;不存在返回 None。"""
    s = str(path).replace("\\", "/")
    p = config.media_url_to_path(s) if s.startswith(("/static/", "static/")) else Path(path)
    return p if p.exists() else None


def _xy_upload_asset(base: str, headers: dict, path: str | Path) -> str:
    """上传单个素材换 pippit_asset_id(multipart 单文件,认证在请求头)。"""
    p = _xy_resolve_path(path)
    if not p:
        raise AIError(f"小云雀参考素材不存在: {path}")
    up = {k: v for k, v in headers.items() if k.lower() != "content-type"}
    with open(p, "rb") as f:
        resp = requests.post(f"{base}/api/biz/v1/skill/upload_file", headers=up,
                             files={"file": (p.name, f)}, timeout=120)
    if resp.status_code not in (200, 201):
        raise AIError(f"小云雀上传失败 HTTP {resp.status_code}: {_utf8_text(resp)[:300]}")
    r = resp.json()
    if str(r.get("ret")) != "0":
        raise AIError(f"小云雀上传失败: {r.get('errmsg') or str(r)[:200]}")
    asset_id = (r.get("data") or {}).get("pippit_asset_id")
    if not asset_id:
        raise AIError(f"小云雀上传响应缺少 pippit_asset_id: {str(r)[:300]}")
    return asset_id


def _xy_norm_duration(d) -> int:
    try:
        n = int(float(d))
    except (TypeError, ValueError):
        n = 8
    return min(30, max(2, n))


def _generate_xiaoyunque(cfg, base, headers, prompt, resolution, duration,
                         first_frame, ref_images):
    """沉浸式短片 API(submit_run):自然语言指令 + 精确时长/分辨率,适配短剧镜头。"""
    import json as _json
    model = (cfg.get("model") or "").strip()
    if not model:
        raise AIError("小云雀需要在配置中选择模型(如 Seedance_2.5)")
    res = (resolution or "720p").strip().lower()
    if res not in ("480p", "720p", "1080p"):
        res = "720p"
    if res == "1080p" and model.lower() != "seedance2.0_vision":
        raise AIError("小云雀 1080p 目前仅支持 seedance2.0_vision 模型,请调整分辨率或模型")
    # 积分预检:0 余额直接报错;查询失败不阻塞(服务端提交时也会校验)
    try:
        balance = xiaoyunque_credit_balance(cfg)
    except AIError:
        balance = None
    if balance == "0":
        raise AIError("小云雀积分余额为 0,请到官网充值或领取每日积分后再生成")
    # 画幅可由配置 settings JSON 覆盖(如 {"ratio": "9:16"} 竖屏)
    ratio = "16:9"
    try:
        s = _json.loads(cfg.get("settings") or "")
        if isinstance(s, dict) and s.get("ratio"):
            ratio = str(s["ratio"])
    except Exception:  # noqa: BLE001
        pass
    # 首帧图排首位(锁角色),参考图随后;统一上传换 asset_id(接口无 data URL 通道)
    imgs = ([first_frame] if first_frame else []) + list(ref_images)
    asset_ids = [_xy_upload_asset(base, headers, p) for p in imgs[:4]]
    body: dict = {
        "message": prompt,
        "agent_name": XIAOYUNQUE_AGENT,
        "video_part_tool_param": {
            "prompt": prompt, "model": model, "ratio": ratio,
            "duration_sec": _xy_norm_duration(duration), "resolution": res,
            "images": [{"pippit_asset_id": a} for a in asset_ids]},
    }
    if asset_ids:
        body["asset_ids"] = asset_ids
    resp = requests.post(f"{base}/api/biz/v1/skill/submit_run", json=body, headers=headers, timeout=120)
    if resp.status_code not in (200, 201):
        raise AIError(f"小云雀提交失败 HTTP {resp.status_code}: {_utf8_text(resp)[:300]}")
    r = resp.json()
    if str(r.get("ret")) != "0":
        raise AIError(f"小云雀提交失败: {r.get('errmsg') or str(r)[:200]}")
    run = (r.get("data") or {}).get("run") or {}
    run_id, thread_id = run.get("run_id"), run.get("thread_id")
    if not run_id or not thread_id:
        raise AIError(f"小云雀提交响应缺少 run_id/thread_id: {str(r)[:300]}")

    def check():
        st = requests.post(f"{base}/api/biz/v1/agent/query_generate_video_result",
                           json={"thread_id": thread_id, "run_id": run_id},
                           headers=headers, timeout=30).json()
        if str(st.get("ret")) != "0":
            return "failed", None, str(st.get("errmsg") or st)[:200]
        data = st.get("data") or {}
        state = str(data.get("run_state") or (data.get("run") or {}).get("state") or "")
        urls = data.get("video_urls") or []
        if state == "3":
            if urls:
                return "running", urls[0], None
            return "failed", None, "任务成功但未返回视频链接"
        if state in ("4", "5"):
            fr = data.get("fail_reason")
            msg = fr.get("message") if isinstance(fr, dict) else fr
            return "failed", None, str(msg or "任务失败")[:200]
        return "running", None, None

    url = _poll(check, POLL_INTERVAL_S, POLL_MAX_ROUNDS)
    # video_urls 是服务端解析好的可直接下载链接,不带鉴权头下载,避免泄露 Access Key
    return _download(url), "xiaoyunque"


def test_config(cfg: dict) -> tuple[bool, str]:
    # 视频不做真实生成测试,只做提交连通性(避免消耗配额):用极短 prompt 提交后立即查询一次
    try:
        headers = {"Content-Type": "application/json"}
        if cfg.get("api_key"):
            headers["Authorization"] = f"Bearer {cfg['api_key']}"
        base = cfg["base_url"].rstrip("/")
        if cfg["provider"] == "volcengine":
            resp = requests.post(f"{base}/contents/generations/tasks", json={
                "model": cfg["model"], "content": [{"type": "text", "text": "ping --resolution 480p"}]},
                headers=headers, timeout=30)
            ok = resp.status_code in (200, 201)
            return ok, "OK" if ok else f"HTTP {resp.status_code}: {_utf8_text(resp)[:200]}"
        if cfg["provider"] == "xiaoyunque":
            # 积分余额接口免费,正好用作真实连通性测试
            return True, f"OK,积分余额 {xiaoyunque_credit_balance(cfg)}"
        return True, "OK(跳过真实提交)"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]

# ── 视频限流治理(对齐原版 4790a54)──
RATE_LIMIT_BACKOFF_CAP_S = 120        # 退避封顶 2 分钟
RATE_LIMIT_BACKOFF_BASE_S = 30        # 退避基数 30 秒
VIDEO_CREATE_SPACING_S = 15           # 视频提交全局串行门:两次提交最小间隔 15 秒
_last_video_create_at: list = [0.0]
_video_gate_lock = threading.Lock()


def _ark_url(base: str, path: str) -> str:
    """火山方舟端点拼接(对齐参考项目 joinProviderUrl):路径固定带 /api/v3 前缀。

    base 配了 https://ark.cn-beijing.volces.com/api/v3 或裸域名的都能出正确地址
    —— 此前裸域名直接拼 /contents/generations/tasks,上游 404 且响应体为空。
    """
    b = (base or "").rstrip("/")
    if "/api/v3" not in b:
        b += "/api/v3"
    return f"{b}{path}"


def _is_rate_limited(exc) -> bool:
    """429/503 或响应体含限流关键词 → 触发长预算退避。"""
    s = str(exc).lower()
    return ("429" in s or "503" in s or "queue_full" in s
            or "too many requests" in s or "rate limit" in s)



def acquire_video_create_gate() -> None:
    """视频提交全局串行门:阻塞到距上次提交满 15 秒后放行,并更新时刻。

    对齐原版 passVideoCreateGate —— 多任务并发时按最小间隔排队,避免同时踩上游限流。
    原实现返回线程让调用方 join,但线程从未 start,等于门形同虚设;改为直接阻塞获取。
    """
    with _video_gate_lock:
        wait = _last_video_create_at[0] + VIDEO_CREATE_SPACING_S - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_video_create_at[0] = time.time()


class VideoRetryExhausted(RuntimeError):
    """重试预算耗尽(或撞上永久错误)——携带**每一次**尝试的原因。

    此前实现只有一个 `last_err = exc` 反复覆盖:中间失败的信息全丢,落库的
    error_msg 只剩最后一个异常,排查时看不到「先发生了什么、中间变没变」。
    这里把整条尝试链拼进消息,并把原始异常挂到 __cause__,traceback 里两条都在。
    """

    def __init__(self, attempts: list, last: BaseException | None):
        self.attempts = list(attempts)
        self.last = last
        head = last if isinstance(last, BaseException) else RuntimeError(str(last))
        chain = " | ".join(f"#{i} @{t:.0f}s {k}: {m}" for i, t, k, m in self.attempts)
        super().__init__(f"{head}  [共 {len(self.attempts)} 次尝试] {chain}")
        self.__cause__ = head


# 创建请求的总墙钟上限:无论单轮预算怎么升档、Retry-After 跟几次,从首次尝试
# 起算的总时长不得超过它。max_attempts 只约束**次数**不约束**时长**,上游每次都
# 返回一个未来的 Retry-After,20 次尝试就能累积出数小时(参考项目实测挂过 6h20m)。
# 取 2 小时:覆盖限流长预算(30min)之外的所有正常情况。
CREATE_TOTAL_WALL_CLOCK_S = 2 * 60 * 60

# 单次 _dispatch_once 内部的轮询上限。原先 5 处调用点各写死字面量 _poll(..., 10, 300),
# 想确认「一个视频任务最多能 processing 多久」只能靠人肉数 —— 而这正是巡检间隔被
# 定成 45 分钟(小于真实上界 50 分钟)的根因。提成常量后上界可由 max_task_processing_s()
# 推导,tests/test_stuck_task_watchdog.py 会拿它跟 db.REAP_INTERVAL_S 对质。
POLL_INTERVAL_S = 10
POLL_MAX_ROUNDS = 300

# 限流档的尝试间预算(秒)。同样从函数签名默认值提成常量,理由同上。
CREATE_RATE_LIMIT_BUDGET_S = 1800.0


def max_task_processing_s() -> float:
    """一个视频任务从提交到落定,**最长**可能停留在 processing 的秒数 —— 巡检间隔
    必须大于它,否则会把正在正常生成的任务判成僵尸。

    推导:重试循环的尝试间预算用 `elapsed + wait > budget` 卡,而 elapsed 从循环外
    的 `started` 起算、**从不重置**,所以最后一次尝试最晚在累计 30 分钟时进入;
    而单次尝试内部还要跑满整轮轮询(10s × 300 = 50 分钟)。两者相加得 ~80 分钟。
    """
    return CREATE_RATE_LIMIT_BUDGET_S + POLL_INTERVAL_S * POLL_MAX_ROUNDS


def _generate_with_retry(fn, *, max_attempts: int = 20,
                         rate_limit_budget_s: float = CREATE_RATE_LIMIT_BUDGET_S,
                         create_budget_s: float = 180.0) -> tuple[Path, str]:
    """提交 + 轮询的重试包装。

    - **永久错误立即失败**:4xx(缺 Key / 参数错 / 模型下线)退避再试也没用,只是烧配额;
    - **限流 / 队列满**:长预算按 30s→45s→… 退避,封顶 2 分钟,把拥塞「等过去」
      而不是快速失败。对齐参考项目 CREATE_RETRY_MAX_ATTEMPTS=20 / 30 分钟预算
      (此前这里只试 6 次 ≈ 6 分钟,Agnes 实测 video_queue_full 拥塞 20 分钟+,
      6 次必然成批早死 —— 今天整批失败全是这个);
    - **retry_at 时间戳**:上游明确给了「X 之后再试」就直接睡到那一刻,最多跟 2 次、单次 ≤24h;
    - **串行门全程持锁**:重试期间不放开,两个任务不会同时踩上游;
    - **失败上报整条尝试链**:抛 VideoRetryExhausted,不再只报最后一次。
    """
    import time as _t
    from .video_contract import is_permanent_error, retry_at_wait_seconds
    gate = threading.Lock()
    last_err = None
    attempts: list = []          # (轮次, 距开始秒数, 异常类名, 摘要)
    started = _t.time()
    # 总墙钟起点用**独立变量**,不复用 started —— started 的语义是「当前预算轮
    # 起点」,将来若引入预算重置会被污染
    first_attempt_at = _t.time()
    retry_at_follows = 0
    rate_limited_mode = False
    for attempt in range(max_attempts):
        if _t.time() - first_attempt_at >= CREATE_TOTAL_WALL_CLOCK_S:
            # 用真除法而不是 //:常量被调小做验证时(比如压到 1s),
            # `1 // 60` 会显示成「累计超过 0 分钟」
            mins = CREATE_TOTAL_WALL_CLOCK_S / 60
            shown = int(mins) if mins >= 1 else round(mins, 1)
            raise VideoRetryExhausted(attempts, RuntimeError(
                f"创建请求累计超过 {shown} 分钟仍未成功,已按总时长上限失败"))
        with gate:
            acquire_video_create_gate()          # 距上次提交不足 15s 就排队等
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                attempts.append((attempt + 1, _t.time() - started,
                                 type(exc).__name__, str(exc)[:160]))
        if is_permanent_error(last_err):
            raise VideoRetryExhausted(attempts, last_err)   # 4xx 快速失败,不进退避
        if _is_rate_limited(last_err):
            rate_limited_mode = True             # 一旦命中限流,预算升到长档且不再回落
        budget = rate_limit_budget_s if rate_limited_mode else create_budget_s
        elapsed = _t.time() - started
        wait = retry_at_wait_seconds(str(last_err), retry_at_follows)
        if wait is not None:
            retry_at_follows += 1
        else:
            wait = backoff_seconds(attempt)
        if elapsed + wait > budget or attempt == max_attempts - 1:
            raise VideoRetryExhausted(attempts, last_err)   # 预算耗尽或次数用尽
        _t.sleep(wait)
    raise VideoRetryExhausted(attempts, last_err)  # pragma: no cover


def backoff_seconds(attempt: int, retry_after: float | None = None) -> float:
    """退避计算:优先 Retry-After,否则 30s × 1.5^n,封顶 120s。"""
    if retry_after:
        return min(float(retry_after), RATE_LIMIT_BACKOFF_CAP_S)
    return min(RATE_LIMIT_BACKOFF_BASE_S * (1.5 ** min(attempt, 6)), RATE_LIMIT_BACKOFF_CAP_S)
