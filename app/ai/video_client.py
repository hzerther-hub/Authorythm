# -*- coding: utf-8 -*-
"""视频生成客户端:volcengine(Seedance) / minimax / aliyun(Wan) / agnes / runninghub / xiaoyunque(小云雀),提交+轮询+下载。"""
from __future__ import annotations

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
    "agnes": ["720P", "1080P"],
    "xiaoyunque": ["480p", "720p", "1080p"],
}


def _ext_for(url: str) -> str:
    low = (url.split("?")[0] or "").lower()
    return Path(low).suffix or ".mp4"


def _download(url: str, headers: dict | None = None) -> Path:
    out = config.STATIC_DIR / "videos" / f"{uuid.uuid4().hex}{_ext_for(url)}"
    resp = requests.get(url, headers=headers or {}, timeout=600)
    if resp.status_code != 200:
        raise AIError(f"下载生成视频失败 HTTP {resp.status_code}")
    out.write_bytes(resp.content)
    return out


def _local_to_data_url(path: str | Path) -> str:
    import base64
    p = Path(path)
    if p.exists():
        return "data:application/octet-stream;base64," + base64.b64encode(p.read_bytes()).decode()
    return str(path)


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


def generate_video(prompt: str, resolution: str = "720p", duration: int | None = None,
                   first_frame: str | None = None, config_id: int | None = None,
                   reference_images: list[str] | None = None) -> tuple[Path, str]:
    """文生视频 / 图生视频(first_frame 本地路径)。

    reference_images:@角色 形象参考图本地路径列表(角色一致性)。
    agnes 走多模态参考注入;volcengine 以 reference_image 角色注入;minimax/aliyun 忽略。
    返回 (本地路径, provider)。

    **平台级质量守卫**:prompt 统一追加视频质量要求 + 表演克制 + 节奏三层守卫(各自 marker 幂等)。
    视频模型对肢体畸形与强情绪词(尖叫/嘶吼/痛哭)都天生放大,需在平台层压住;
    确需爆发表情的镜头,在分镜 video_prompt 里显式写「情绪爆发」覆盖表演守卫。
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
    refs = [_local_to_data_url(r) for r in (reference_images or [])][:4]

    # 提交 + 轮询整体走重试包装:永久错误立即失败,限流/队列满按长预算退避,
    # 上游给了 retry_at 时间戳就睡到那一刻(最多跟 2 次)。
    return _generate_with_retry(
        lambda: _dispatch_once(cfg, base, headers, prompt, resolution, duration,
                               first_frame, refs, config_id, reference_images or []))


def _dispatch_once(cfg, base, headers, prompt, resolution, duration,
                   first_frame, refs, config_id, reference_images):
    """按 provider 分发一次(不含重试)。"""
    provider = cfg["provider"]
    if provider == "volcengine":
        body: dict = {"model": cfg["model"], "content": [
            {"type": "text", "text": prompt + f" --resolution {resolution}" +
             (f" --duration {duration}" if duration else "") +
             (" --ratio 16:9" if resolution.lower() not in ("720p", "1080p", "480p") else "")}]}
        for ref in refs:
            body["content"].append({"type": "image_url", "image_url": {"url": ref},
                                    "role": "reference_image"})
        if first_frame:
            body["content"].append({"type": "image_url", "image_url": {"url": _local_to_data_url(first_frame)}})
        resp = requests.post(f"{base}/contents/generations/tasks", json=body, headers=headers, timeout=120)
        if resp.status_code not in (200, 201):
            raise AIError(f"Seedance 提交失败 HTTP {resp.status_code}: {resp.text[:300]}")
        task_id = resp.json().get("id")
        if not task_id:
            raise AIError(f"Seedance 响应缺少 id: {resp.text[:300]}")

        def check():
            st = requests.get(f"{base}/contents/generations/tasks/{task_id}", headers=headers, timeout=30).json()
            status = st.get("status", "")
            video = (st.get("content") or {}).get("video_url") if isinstance(st.get("content"), dict) else None
            return ("failed" if status == "failed" else "running"), video, st.get("error")

        url = _poll(check, 10, 300)
        return _download(url, headers), provider

    if provider == "minimax":
        body = {"model": cfg["model"], "prompt": prompt}
        if first_frame:
            body["first_frame_image"] = _local_to_data_url(first_frame)
        resp = requests.post(f"{base}/video_generation", json=body, headers=headers, timeout=120)

        def check2():
            st = requests.get(f"{base}/query/video_generation?task_id={task_id}", headers=headers, timeout=30).json()
            status = st.get("status", "")
            file = (st.get("file") or {}) if isinstance(st.get("file"), dict) else {}
            return ("failed" if status == "Fail" else "running"), file.get("download_url"), st.get("message")

        url = _poll(check2, 10, 300)
        return _download(url, headers), provider

    if provider == "aliyun":
        body = {"model": cfg["model"], "input": {"prompt": prompt},
                "parameters": {"size": "1280*720" if "720" in resolution.upper() else "960*480"}}
        resp = requests.post(f"{base}/api/v1/services/aigc/video-generation/video-synthesis",
                             json=body, headers=headers, timeout=120)
        if resp.status_code not in (200, 201):
            raise AIError(f"Wan 提交失败 HTTP {resp.status_code}: {resp.text[:300]}")
        task_id = resp.json().get("output", {}).get("task_id")

        def check3():
            st = requests.get(f"{base}/api/v1/tasks/{task_id}", headers=headers, timeout=30).json()
            out = st.get("output", {})
            status = out.get("task_status", "")
            url_v = out.get("video_url")
            if status == "SUCCEEDED" and url_v:
                return "running", url_v + ("?Expires=" + str(int(time.time()) + 86400)), None
            return ("failed" if status in ("FAILED", "CANCELED") else "running"), None, out.get("message")

        url = _poll(check3, 10, 300)
        return _download(url, headers), provider

    if provider == "agnes":
        # 对齐参考项目 agnes-video.ts(当前版):POST /v1/videos、mode 按 model 版本映射
        # (v2.0→ti2vid,素材进 first_frame/image_url/images)、素材上限、flash 仅 720P、
        # 轮询走 {origin}/agnesapi?video_id=&model_name=(不在 /v1 下)、成片地址取顶层 url
        from .agnes_video import generate_agnes
        url_v = generate_agnes(cfg, base, headers, prompt=prompt, resolution=resolution,
                               duration=duration, first_frame=first_frame,
                               reference_images=reference_images)
        return _download(url_v, headers), provider

    if provider == "runninghub":
        return _generate_runninghub(cfg, base, headers, prompt, resolution, duration,
                                    first_frame, refs, config_id)

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
                         first_frame, refs, config_id):
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
        d_url = _local_to_data_url(first_frame)
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

    url = _poll(check, 10, 300)
    return _download(url, headers), "runninghub"


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
        raise AIError(f"小云雀积分查询失败 HTTP {resp.status_code}: {resp.text[:200]}")
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
        raise AIError(f"小云雀上传失败 HTTP {resp.status_code}: {resp.text[:300]}")
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
        raise AIError(f"小云雀提交失败 HTTP {resp.status_code}: {resp.text[:300]}")
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

    url = _poll(check, 10, 300)
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
            return ok, "OK" if ok else f"HTTP {resp.status_code}: {resp.text[:200]}"
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


def _is_rate_limited(exc) -> bool:
    """429/503 或响应体含限流关键词 → 触发长预算退避。"""
    s = str(exc).lower()
    return ("429" in s or "503" in s or "queue_full" in s
            or "too many requests" in s or "rate limit" in s)


def _generate_with_retry(fn, *, max_attempts: int = 6,
                         rate_limit_budget_s: float = 900.0,
                         create_budget_s: float = 180.0) -> tuple[Path, str]:
    """提交 + 轮询的重试包装。

    - **永久错误立即失败**:4xx(缺 Key / 参数错 / 模型下线)退避再试也没用,只是烧配额;
    - **限流 / 队列满**:长预算(默认 15 分钟,实测 Agnes 拥塞会持续 20 分钟+)按 30s→45s→… 退避,封顶 2 分钟;
    - **retry_at 时间戳**:上游明确给了「X 之后再试」就直接睡到那一刻,最多跟 2 次、单次 ≤24h;
    - **串行门全程持锁**:重试期间不放开,两个任务不会同时踩上游。
    """
    import time as _t
    from .video_contract import is_permanent_error, retry_at_wait_seconds
    gate = threading.Lock()
    last_err = None
    started = _t.time()
    retry_at_follows = 0
    for attempt in range(max_attempts):
        with gate:
            acquire_video_create_gate()          # 距上次提交不足 15s 就排队等
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        if is_permanent_error(last_err):
            raise last_err                       # 4xx 快速失败,不进退避
        elapsed = _t.time() - started
        budget = rate_limit_budget_s if _is_rate_limited(last_err) else create_budget_s
        wait = retry_at_wait_seconds(str(last_err), retry_at_follows)
        if wait is not None:
            retry_at_follows += 1
        else:
            wait = backoff_seconds(attempt)
        if elapsed + wait > budget or attempt == max_attempts - 1:
            raise last_err                       # 预算耗尽或次数用尽,按最后一次错误上报
        _t.sleep(wait)
    raise last_err  # pragma: no cover


def backoff_seconds(attempt: int, retry_after: float | None = None) -> float:
    """退避计算:优先 Retry-After,否则 30s × 1.5^n,封顶 120s。"""
    if retry_after:
        return min(float(retry_after), RATE_LIMIT_BACKOFF_CAP_S)
    return min(RATE_LIMIT_BACKOFF_BASE_S * (1.5 ** min(attempt, 6)), RATE_LIMIT_BACKOFF_CAP_S)


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


def _generate_with_retry(fn, *, max_attempts: int = 6,
                         rate_limit_budget_s: float = 900.0,
                         create_budget_s: float = 180.0) -> tuple[Path, str]:
    """提交 + 轮询的重试包装。

    - **永久错误立即失败**:4xx(缺 Key / 参数错 / 模型下线)退避再试也没用,只是烧配额;
    - **限流 / 队列满**:长预算(默认 15 分钟,实测 Agnes 拥塞会持续 20 分钟+)按 30s→45s→… 退避,封顶 2 分钟;
    - **retry_at 时间戳**:上游明确给了「X 之后再试」就直接睡到那一刻,最多跟 2 次、单次 ≤24h;
    - **串行门全程持锁**:重试期间不放开,两个任务不会同时踩上游。
    """
    import time as _t
    from .video_contract import is_permanent_error, retry_at_wait_seconds
    gate = threading.Lock()
    last_err = None
    started = _t.time()
    retry_at_follows = 0
    for attempt in range(max_attempts):
        with gate:
            acquire_video_create_gate()          # 距上次提交不足 15s 就排队等
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        if is_permanent_error(last_err):
            raise last_err                       # 4xx 快速失败,不进退避
        elapsed = _t.time() - started
        budget = rate_limit_budget_s if _is_rate_limited(last_err) else create_budget_s
        wait = retry_at_wait_seconds(str(last_err), retry_at_follows)
        if wait is not None:
            retry_at_follows += 1
        else:
            wait = backoff_seconds(attempt)
        if elapsed + wait > budget or attempt == max_attempts - 1:
            raise last_err                       # 预算耗尽或次数用尽,按最后一次错误上报
        _t.sleep(wait)
    raise last_err  # pragma: no cover


def backoff_seconds(attempt: int, retry_after: float | None = None) -> float:
    """退避计算:优先 Retry-After,否则 30s × 1.5^n,封顶 120s。"""
    if retry_after:
        return min(float(retry_after), RATE_LIMIT_BACKOFF_CAP_S)
    return min(RATE_LIMIT_BACKOFF_BASE_S * (1.5 ** min(attempt, 6)), RATE_LIMIT_BACKOFF_CAP_S)
