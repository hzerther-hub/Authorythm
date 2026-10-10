# -*- coding: utf-8 -*-
"""Agnes AI 视频生成(https://apihub.agnes-ai.com,OpenAI 兼容网关)。

对照参考项目 xiaoshuo backend/src/services/adapters/agnes-video.ts 一比一对齐
(2026-10 当前版,含 v2.0→ti2vid 映射/素材上限/画幅校验/轮询端点):

    创建: POST {base}/v1/videos → { id, task_id, video_id, status: "queued" }
    轮询: GET {origin}/agnesapi?video_id=<video_id>&model_name=<model>
          (注意不在 /v1 下,需去掉 baseUrl 的 /v1 前缀)
    完成: status="completed" 且顶层 url(文档写的 metadata.url 实测不返回,两者都兼容)
    失败: status="failed" + error.message

    生成模式(互斥,按素材优先级): keyframe 帧 > reference 参考 > text 纯文生
    - v2.5/2.5-flash: text / keyframe / reference
    - v2.0: 统一映射 ti2vid(multi_reference 实测恒 400;ti2vid 接受
      first_frame/image_url/images 任意一种,audios/videos 无语义 → 忽略)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse

import requests

from .text_client import AIError

MODEL_PREFIX = "agnes-video"
DEFAULT_MODEL = "agnes-video-2.5-flash"

# mode 字段映射:项目内统一用 v2.5 schema(text/keyframe/reference),按 model 版本翻成实际值
_V2_0 = re.compile(r"v2\.0$", re.I)


def map_mode(model: str, project_mode: str) -> str:
    """v2.0 一律 ti2vid(实测 v2.0 唯一能跑的 mode);其它原样(v2.5 schema)。"""
    m = (model or "").lower()
    if "v2.0" in m or m.endswith("-v2.0"):
        return "ti2vid"
    return project_mode


# Agnes 支持的画幅比;不认识的回 16:9(乱传 HTTP 400)
VALID_RATIOS = {"21:9", "16:9", "4:3", "1:1", "3:4", "9:16"}

# 参考素材上限:flash(图5/音3/不支持视频) 与 2.5(图8/音3/视频1,总数12)
FLASH_LIMITS = {"images": 5, "audios": 3}
FULL_LIMITS = {"images": 8, "audios": 3, "videos": 1, "total": 12}

# 项目内部分辨率 → Agnes 档位(480p 无对应档位,就近升 720P)
RESOLUTION_MAP = {"480p": "720P", "720p": "720P", "1080p": "1080P", "2k": "2K"}

# 轮询需要 model_name,而创建响应只回 taskId —— 创建时把 model 编码进 taskId
TASK_ID_SEPARATOR = "::"


def normalize_seconds(duration) -> str:
    """时长 → Agnes seconds 字符串,合法区间 "4"~"12",默认 "5"。"""
    value = round(float(duration) if duration else 5) or 5
    return str(min(12, max(4, value)))


def _parse_url_array(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if isinstance(raw, (list, tuple)):
        return [str(u).strip() for u in raw if isinstance(u, str) and u.strip()]
    return []


def build_generate_body(cfg: dict, *, prompt: str, resolution: str, duration,
                        first_frame: str | None, last_frame: str | None,
                        ref_images: list[str], ref_audios: list[str] | None = None,
                        ref_videos: list[str] | None = None,
                        aspect_ratio: str | None = None, seed=None) -> dict:
    """构造创建请求体。pydrama 现有链路只产 first_frame + reference_images,
    但字段与参考版一一同构,将来接尾帧/参考音视频不用改协议。"""
    model = (cfg.get("model") or DEFAULT_MODEL).strip()
    if not model.lower().startswith(MODEL_PREFIX):
        raise AIError(f"仅支持 Agnes Video 系列模型({MODEL_PREFIX}-*),当前: {model}")
    is_flash = bool(re.search(r"flash", model, re.I))

    prompt = (prompt or "").strip()
    if not prompt:
        raise AIError("Agnes 视频生成要求必须提供提示词")

    first_frame = (first_frame or "").strip()
    last_frame = (last_frame or "").strip()
    ref_images = [u for u in ref_images if u]
    ref_audios = [u for u in (ref_audios or []) if u]
    ref_videos = [u for u in (ref_videos or []) if u]

    if is_flash and ref_videos:
        raise AIError("Agnes Video Flash 不支持参考视频,请改用 agnes-video-2.5")
    limits = FLASH_LIMITS if is_flash else FULL_LIMITS
    if len(ref_images) > limits["images"] or len(ref_audios) > limits["audios"]:
        raise AIError(f"参考素材超限:图片≤{limits['images']}、音频≤{limits['audios']}")
    if not is_flash and len(ref_images) + len(ref_audios) + len(ref_videos) > FULL_LIMITS["total"]:
        raise AIError(f"参考素材总数超限:≤{FULL_LIMITS['total']}")

    # 模式互斥(官方规则:keyframe 禁带 images/audios/videos):帧 > 参考 > 纯文生
    if first_frame or last_frame:
        project_mode = "keyframe"
    elif ref_images or ref_audios or ref_videos:
        project_mode = "reference"
    else:
        project_mode = "text"
    final_mode = map_mode(model, project_mode)

    body: dict = {
        "model": model,
        "prompt": prompt,
        "seconds": normalize_seconds(duration),
        # flash 仅 720P,传其它值直接 400
        "size": "720P" if is_flash else RESOLUTION_MAP.get((resolution or "").lower(), "720P"),
        "aspect_ratio": aspect_ratio if aspect_ratio in VALID_RATIOS else "16:9",
        "n": 1,
    }
    if seed is not None and seed != "":
        try:
            body["seed"] = float(seed) if not float(seed).is_integer() else int(seed)
        except (TypeError, ValueError):
            pass
    body["mode"] = final_mode

    if final_mode == "ti2vid":
        # v2.0 优先级:有 first_frame → first_frame;单张参考图 → image_url;多张 → images[]
        # v2.0 没有 audios/videos 字段语义 → 忽略
        if first_frame:
            body["first_frame"] = first_frame
        elif len(ref_images) == 1:
            body["image_url"] = ref_images[0]
        elif len(ref_images) > 1:
            body["images"] = ref_images[:4]
    elif final_mode == "keyframe":
        # v2.5+ keyframe(帧图保留为真实首尾帧)
        if first_frame:
            body["first_frame"] = first_frame
        if last_frame:
            body["last_frame"] = last_frame
    elif final_mode == "reference":
        # v2.5+ reference(参考图仅作风格/主体参考,不占首尾帧)
        if ref_images:
            body["images"] = ref_images
        if ref_audios:
            body["audios"] = ref_audios
        if ref_videos:
            body["videos"] = [{"url": u, "require_audio": False} for u in ref_videos]
    return body


def create_endpoint(base: str) -> str:
    """POST {base}/v1/videos;baseUrl 已带 /v1 时不重复拼(参考 joinProviderUrl 语义)。"""
    base = (base or "").rstrip("/")
    if base.endswith("/v1"):
        return base + "/videos"
    return base + "/v1/videos"


def poll_endpoint(base: str, api_key: str, video_id: str, model: str | None) -> str:
    """轮询端点在域名根 /agnesapi,不在 /v1 下;从 baseUrl 取 origin 拼接。"""
    parsed = urlparse((base or "").rstrip("/"))
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else base
    params = {"video_id": video_id}
    if model:
        params["model_name"] = model
    sep = "&" if "?" in origin else "?"
    return f"{origin}/agnesapi{sep}{urlencode(params)}"


def parse_create_response(data: dict) -> str:
    """创建响应 → 轮询用 taskId(video_id::model)。"""
    video_id = data.get("video_id") or data.get("id") or data.get("task_id")
    if isinstance(video_id, str) and video_id:
        model = data.get("model") if isinstance(data.get("model"), str) else ""
        return f"{video_id}{TASK_ID_SEPARATOR}{model}" if model else video_id
    raise AIError(f"No video_id in Agnes create response: {str(data)[:200]}")


def parse_poll_response(st: dict) -> tuple[str, str | None, str | None, int | None]:
    """轮询响应 → (status, video_url, error, duration)。

    status ∈ {"running", "failed", "completed"};completed 但拿不到地址按失败处理
    (与参考版一致:任务完成却无 URL 不能当成功落库)。
    """
    status = str(st.get("status") or "")
    if status == "completed":
        metadata = st.get("metadata") if isinstance(st.get("metadata"), dict) else {}
        video_url = st.get("url") or metadata.get("url")
        if not video_url:
            return "failed", None, "Agnes 任务完成但未返回视频地址", None
        seconds = st.get("seconds")
        dur = None
        try:
            dur = int(seconds) if seconds is not None and float(seconds) == float(seconds) else None
        except (TypeError, ValueError):
            dur = None
        return "completed", video_url, None, dur
    if status == "failed":
        err = st.get("error")
        msg = err.get("message") if isinstance(err, dict) else str(err or "")
        return "failed", None, (msg or "Agnes 视频生成失败"), None
    # queued / in_progress / 未知状态一律继续等待
    return "running", None, None, None


def generate_agnes(cfg: dict, base: str, headers: dict, *, prompt: str,
                   resolution: str = "720p", duration=None,
                   first_frame: str | None = None, last_frame: str | None = None,
                   reference_images: list[str] | None = None,
                   reference_audios: list[str] | None = None,
                   reference_videos: list[str] | None = None,
                   aspect_ratio: str | None = None, seed=None,
                   poll_seconds: int = 10, poll_rounds: int = 300):
    """提交 + 轮询,返回成片 URL。由 video_client 负责下载落盘与重试包装。

    本地路径转 data URL 在这里统一做(与参考版 normalizeVideoReferenceUrl 同位)。
    """
    from .video_client import _local_to_data_url

    def _inline(u: str) -> str:
        # 参考/帧图走同一归一:本地路径内联成 data URL,http(s)/static 保持原样
        if u and not u.startswith(("http://", "https://", "data:")) and Path(u).exists():
            return _local_to_data_url(u)
        return u

    body = build_generate_body(
        cfg, prompt=prompt, resolution=resolution, duration=duration,
        first_frame=_inline(first_frame) if first_frame else None,
        last_frame=_inline(last_frame) if last_frame else None,
        ref_images=[_inline(u) for u in _parse_url_array(reference_images)],
        ref_audios=reference_audios, ref_videos=reference_videos,
        aspect_ratio=aspect_ratio, seed=seed)

    resp = requests.post(create_endpoint(base), json=body, headers=headers, timeout=120)
    if resp.status_code not in (200, 201):
        raise AIError(f"Agnes 提交失败 HTTP {resp.status_code}: {resp.text[:300]}")
    task_id = parse_create_response(resp.json())
    video_id, _, poll_model = task_id.partition(TASK_ID_SEPARATOR)
    poll_url = poll_endpoint(base, cfg.get("api_key") or "", video_id, poll_model or None)

    import time
    for _ in range(poll_rounds):
        time.sleep(poll_seconds)
        pr = requests.get(poll_url, headers={"Authorization": headers.get("Authorization", "")},
                          timeout=30)
        if pr.status_code != 200:
            continue          # 与参考版 pollTask 相同:单次轮询失败不终局,继续等
        status, url_v, err, _dur = parse_poll_response(pr.json())
        if url_v:
            return url_v
        if status == "failed":
            raise AIError(f"Agnes 视频生成失败: {err}")
    raise AIError("Agnes 视频任务轮询超时")
