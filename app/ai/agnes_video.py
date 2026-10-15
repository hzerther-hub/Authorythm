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
def _utf8_text(resp, limit: int = 400) -> str:
    """错误文案按 utf-8 显式解码。

    requests 在缺 Content-Type charset 时会走 apparent_encoding(charset_normalizer 猜),
    中文报错常被猜成 GBK/Big5 → 报错本身变乱码,排障时满屏鬼画符,看不出问题在哪。
    """
    try:
        return resp.content.decode("utf-8", errors="replace")[:limit]
    except Exception:  # noqa: BLE001
        return str(getattr(resp, "text", "") or "")[:limit]
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

# 项目「新建项目」对话框里的自适应画幅。官方明确 aspect_ratio="auto" 会 400,
# 所以它不能直接下发 —— 必须落到一个具体比例上。落哪个取决于首帧图的实际形状:
# 首帧就是这一镜的成片构图,它的宽高比就是这一镜该有的画幅。这比无条件回落 16:9
# 准确得多:竖屏项目的首帧是竖的,回落 16:9 会让竖屏项目出横屏片。
ADAPTIVE_TOKENS = {"adaptive", "auto", "", "0"}

# 参考素材上限:flash(图5/音3/不支持视频) 与 2.5(图8/音3/视频1,总数12)
FLASH_LIMITS = {"images": 5, "audios": 3}
FULL_LIMITS = {"images": 8, "audios": 3, "videos": 1, "total": 12}

# Agnes Video 的 `size` 只认这 4 个档位字符串(官方「Video Size and Aspect Ratio」),
# 传 1280x720 这类像素值直接 400;画幅由 aspect_ratio 决定,两者必须配套下发。
# 项目内部分辨率(episodes.resolution:480p/720p/1080p + 组合框里的 720P…2K)→ 官方档位。
# 480p 没有对应档位,就近升 720P(升而不是降:降档会白花钱且没有更便宜的档位)。
RESOLUTION_MAP = {"480p": "720P", "720p": "720P", "1080p": "1080P",
                  "1k": "1K", "2k": "2K"}
SIZE_TIERS_FULL = ("720P", "1080P", "1K", "2K")
SIZE_TIERS_FLASH = ("720P",)


def is_flash(model: str) -> bool:
    """Flash 型号(官方只支持 720P,多图≤5/音频≤3/不支持参考视频)。"""
    return bool(re.search(r"flash", model or "", re.I))


def size_tiers(model: str) -> tuple[str, ...]:
    """该型号实际可用的 size 档位。flash 锁死 720P,其它档位直接 HTTP 400。"""
    return SIZE_TIERS_FLASH if is_flash(model) else SIZE_TIERS_FULL


def effective_size(model: str, resolution: str | None) -> str:
    """项目分辨率 → 实际下发的 size。

    同一个返回值同时喂给请求体和参考图压缩档位(video_client._upload_profile):
    flash 选了 1080P 会被钳到 720P,此时首帧就不该再压到 1920 —— 压大只是白撑请求体。
    """
    tiers = size_tiers(model)
    tier = RESOLUTION_MAP.get((resolution or "").strip().lower(), "")
    if tier not in tiers:
        raw = (resolution or "").strip()
        tier = tiers[0]
        if raw:
            print(f"[agnes] size={raw!r} 对 {model} 不可用,按 {tier} 下发", flush=True)
    return tier

# 轮询需要 model_name,而创建响应只回 taskId —— 创建时把 model 编码进 taskId
TASK_ID_SEPARATOR = "::"


def normalize_seconds(duration) -> str:
    """时长 → Agnes seconds 字符串,合法区间 "4"~"12",默认 "5"。"""
    value = round(float(duration) if duration else 5) or 5
    return str(min(12, max(4, value)))


def adapt_seconds(duration) -> tuple[str, int | None]:
    """时长 → (下发值, 用户原始意图秒数);意图被钳制时第二项非 None。

    分开返回是为了让调用方能把「你要 25 秒,实际按 12 秒生成」讲给用户听 ——
    UI 的时长控件范围是 2–30s(见 episode_page 的 sb_duration),而 Agnes 只吃
    4–12s,原先 normalize_seconds 单向钳制,用户设 25s 会静默拿到 12s 的片子。
    """
    try:
        want = round(float(duration))
    except (TypeError, ValueError):
        want = 5
    if not want:
        want = 5
    got = min(12, max(4, want))
    return str(got), (None if got == want else want)


def _ratio_from_size(size: str | None) -> str:
    """像素形状推比例,取最接近的合法画幅。用于拿不到首帧时的兜底。"""
    return "16:9"


def normalize_aspect_ratio(aspect_ratio: str | None, size: str | None = None,
                           *, first_frame: str | None = None,
                           data_url_reader=None) -> tuple[str, str | None]:
    """项目画幅 → (下发值, 改写说明);未改写时说明为 None。

    三种来源按可靠性排序:
      1. 合法比例直接透传;
      2. `adaptive` → 读首帧图真实宽高比(首帧就是这一镜的构图,最可信);
      3. 都拿不到 → 回落 16:9(官方默认值)。

    1K 档官方是固定 1024x1024 方形,**与 aspect_ratio 无关**,此时非方形画幅
    一定拿不到(竖屏项目选 1K 会出方图),要如实回报而不是假装生效。
    """
    raw = (aspect_ratio or "").strip().lower()
    notes: list[str] = []

    if raw in VALID_RATIOS:
        if (size or "").strip().upper() == "1K" and raw != "1:1":
            return raw, (f"1K 档固定输出 1024x1024 方形(官方文档),"
                         f"画幅 {raw} 在该档位不生效,实际出方图")
        return raw, None

    if raw in ADAPTIVE_TOKENS:
        guess = None
        if first_frame and data_url_reader:
            try:
                guess = data_url_reader(first_frame)
            except Exception:  # noqa: BLE001
                guess = None
        if guess and guess in VALID_RATIOS:
            notes.append(f"自适应画幅按首帧图实际比例下发为 {guess}")
        else:
            guess = _ratio_from_size(size)
            notes.append(f"自适应画幅无法从首帧推断,回落 {guess}")
        if (size or "").strip().upper() == "1K" and guess != "1:1":
            return guess, ("; ".join(notes) +
                           ";1K 档固定输出 1024x1024 方形,画幅不生效")
        return guess, "; ".join(notes)

    # 完全不认识的值:显式记录,别让用户以为 21:9 真的生效了
    return "16:9", (f"画幅 {raw!r} 不被 Agnes 支持,已回退 16:9"
                    if raw else "未指定画幅,按官方默认 16:9 下发")


def ratio_from_image_bytes(data: bytes | None) -> str | None:
    """图片字节 → 最接近的合法画幅;解不出返回 None。

    刻意只认 6 个官方白名单值:宁可返回 None 走 16:9 兜底,也不要下发
    「4.5:2」这种上游会 400 的比例。
    """
    if not data:
        return None
    try:
        import io

        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception:  # noqa: BLE001
        return None
    if not w or not h:
        return None
    want = w / h
    best, best_gap = None, None
    for r in VALID_RATIOS:
        a, b = r.split(":")
        gap = abs((int(a) / int(b)) - want)
        if best_gap is None or gap < best_gap:
            best, best_gap = r, gap
    return best


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
    flash = is_flash(model)

    prompt = (prompt or "").strip()
    if not prompt:
        raise AIError("Agnes 视频生成要求必须提供提示词")

    first_frame = (first_frame or "").strip()
    last_frame = (last_frame or "").strip()
    ref_images = [u for u in ref_images if u]
    ref_audios = [u for u in (ref_audios or []) if u]
    ref_videos = [u for u in (ref_videos or []) if u]

    if flash and ref_videos:
        raise AIError("Agnes Video Flash 不支持参考视频,请改用 agnes-video-2.5")

    # 模式互斥(官方规则:keyframe 禁带 images/audios/videos):帧 > 参考 > 纯文生
    if first_frame or last_frame:
        project_mode = "keyframe"
    elif ref_images or ref_audios or ref_videos:
        project_mode = "reference"
    else:
        project_mode = "text"

    # 限额只对**真正会进请求体**的素材生效:keyframe 模式下 build_generate_body
    # 根本不读 images/audios/videos,若在这里一并计数,带首帧的镜头会凭空报
    # 「超限」而整镜失败 —— 那些图压根没被用过。
    if project_mode == "keyframe":
        ref_images, ref_audios, ref_videos = [], [], []

    # 超限**截断而非报错**,对齐参考项目 normalizeReferenceImages 的 `.slice(0, 6)`:
    # 参考图多绑几个应该少带几张,不该让整条视频任务直接失败。
    limits = FLASH_LIMITS if flash else FULL_LIMITS
    if len(ref_images) > limits["images"]:
        ref_images = ref_images[:limits["images"]]
    if len(ref_audios) > limits["audios"]:
        ref_audios = ref_audios[:limits["audios"]]
    if not flash:
        total = len(ref_images) + len(ref_audios) + len(ref_videos)
        if total > FULL_LIMITS["total"]:
            room = FULL_LIMITS["total"] - len(ref_audios) - len(ref_videos)
            ref_images = ref_images[:max(0, room)]

    final_mode = map_mode(model, project_mode)

    # size 只算一次:effective_size 对 flash 会打日志,调两次会重复打印同一行
    size = effective_size(model, resolution)
    body: dict = {
        "model": model,
        "prompt": prompt,
        "seconds": normalize_seconds(duration),
        # flash 仅 720P,传其它值直接 400 → 统一走 effective_size 钳制
        "size": size,
        "aspect_ratio": normalize_aspect_ratio(aspect_ratio, size)[0],
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


def parse_poll_response(st: dict) -> tuple[str, str | None, str | None, int | None, int | None]:
    """轮询响应 → (status, video_url, error, duration, progress)。

    status ∈ {"running", "failed", "completed"};completed 但拿不到地址按失败处理
    (与参考版一致:任务完成却无 URL 不能当成功落库)。

    progress 取官方文档的 0–100 字段。**不能看 internal_progress** —— 官方明说
    内部字段在 completed 时仍可能是 pending/0,只有 status+progress 可信。
    """
    progress = None
    raw_progress = st.get("progress")
    if raw_progress is not None:
        try:
            progress = max(0, min(100, int(float(raw_progress))))
        except (TypeError, ValueError):
            progress = None

    status = str(st.get("status") or "")
    if status == "completed":
        metadata = st.get("metadata") if isinstance(st.get("metadata"), dict) else {}
        video_url = st.get("url") or metadata.get("url")
        if not video_url:
            return "failed", None, "Agnes 任务完成但未返回视频地址", None, 100
        seconds = st.get("seconds")
        dur = None
        try:
            dur = int(seconds) if seconds is not None and float(seconds) == float(seconds) else None
        except (TypeError, ValueError):
            dur = None
        return "completed", video_url, None, dur, 100
    if status == "failed":
        err = st.get("error")
        msg = err.get("message") if isinstance(err, dict) else str(err or "")
        return "failed", None, (msg or "Agnes 视频生成失败"), None, progress
    # queued / in_progress / 未知状态一律继续等待
    return "running", None, None, None, progress


def generate_agnes(cfg: dict, base: str, headers: dict, *, prompt: str,
                   resolution: str = "720p", duration=None,
                   first_frame: str | None = None, last_frame: str | None = None,
                   reference_images: list[str] | None = None,
                   reference_audios: list[str] | None = None,
                   reference_videos: list[str] | None = None,
                   aspect_ratio: str | None = None, seed=None,
                   ref_side: int | None = None, ref_quality: int | None = None,
                   on_progress=None,
                   poll_seconds: int = 10, poll_rounds: int = 300):
    """提交 + 轮询,返回成片 URL。由 video_client 负责下载落盘与重试包装。

    ref_side / ref_quality:首帧/参考图的内联压缩档位(video_client._upload_profile
    按目标 size 档位算好后传进来)。留空则沿用 video_client 的 768px/q68 默认口径。

    on_progress:每轮轮询收到官方 progress(0-100)时调用一次。**回调发生在 worker
    线程里**,调用方只能更新数据/发信号,绝不能碰 Qt 控件。传 None 则不回调。

    本地路径转 data URL 在这里统一做(与参考版 normalizeVideoReferenceUrl 同位)。
    """
    from .video_client import _fetch_remote_as_data_url, _local_to_data_url
    from ..core import config

    def _inline(u: str) -> str:
        """本地图片 → data URL;公网 http(s) 先下载再压缩(对齐参考项目
        fetchImageAsCompressedDataUrl);已是 data URL 的原样透传。

        /static/xxx 这类库里存的相对地址要先换算回磁盘绝对路径,否则
        Path(u).exists() 恒为 False,相对地址会被原样发给上游,同样吃 400。
        """
        if not u:
            return u
        u = str(u)                    # 调用方可能传 Path 对象(首帧取自 _local_to_data_url 前的路径)
        if u.startswith("data:"):
            return u
        if u.startswith(("http://", "https://")):
            # 下载压缩失败时原样透传:对 Agnes 来说公网 URL 本身就是合法媒体,
            # 宁可发大一点也不要悄悄丢掉用户绑定的参考图
            return _fetch_remote_as_data_url(u, ref_side, ref_quality) or u
        if u.startswith(("/static/", "static/")):
            p = config.media_url_to_path(u)
            return _local_to_data_url(p, ref_side, ref_quality) if p.exists() else u
        if Path(u).exists():
            return _local_to_data_url(u, ref_side, ref_quality)
        return u

    inline_first = _inline(first_frame) if first_frame else None

    # 自适应画幅要先看首帧图的实际比例,所以走一遍 _inline 拿到可读的字节。
    # data URL 的 base64 部分解开就是原图字节,直接喂 ratio_from_image_bytes。
    def _ratio_reader(u: str) -> str | None:
        import base64 as _b64
        text = str(u or "")
        if not text.startswith("data:"):
            return None
        try:
            return ratio_from_image_bytes(_b64.b64decode(text.split(",", 1)[1]))
        except Exception:  # noqa: BLE001
            return None

    size = effective_size(cfg.get("model") or DEFAULT_MODEL, resolution)
    ratio, ratio_note = normalize_aspect_ratio(
        aspect_ratio, size, first_frame=inline_first, data_url_reader=_ratio_reader)
    if ratio_note:
        print(f"[agnes] {ratio_note}", flush=True)

    body = build_generate_body(
        cfg, prompt=prompt, resolution=resolution, duration=duration,
        first_frame=inline_first,
        last_frame=_inline(last_frame) if last_frame else None,
        ref_images=[_inline(u) for u in _parse_url_array(reference_images)],
        ref_audios=reference_audios, ref_videos=reference_videos,
        aspect_ratio=ratio, seed=seed)

    resp = requests.post(create_endpoint(base), json=body, headers=headers, timeout=120)
    if resp.status_code not in (200, 201):
        raise AIError(f"Agnes 提交失败 HTTP {resp.status_code}: {_utf8_text(resp)[:300]}")
    task_id = parse_create_response(resp.json())
    video_id, _, poll_model = task_id.partition(TASK_ID_SEPARATOR)
    poll_url = poll_endpoint(base, cfg.get("api_key") or "", video_id, poll_model or None)

    import time
    last_pct = -1
    for _ in range(poll_rounds):
        time.sleep(poll_seconds)
        try:
            pr = requests.get(poll_url, headers={"Authorization": headers.get("Authorization", "")},
                              timeout=60)
        except requests.RequestException:
            # 单次轮询网络抖动(读超时/断连)不终局,继续等下一轮(对齐参考版 pollTask;
            # 此前 30s ReadTimeout 直接炸掉整个任务,是 agnes 成片率低的主因之一)
            continue
        if pr.status_code != 200:
            continue          # 与参考版 pollTask 相同:单次轮询失败不终局,继续等
        status, url_v, err, _dur, pct = parse_poll_response(pr.json())
        # 只在百分比真的变了才回调:进度条重绘有成本,而多数轮次上游根本不推进
        if on_progress and pct is not None and pct != last_pct:
            last_pct = pct
            try:
                on_progress(pct)
            except Exception:  # noqa: BLE001
                pass          # UI 回调出问题不该带崩正在跑的任务
        if url_v:
            return url_v
        if status == "failed":
            raise AIError(f"Agnes 视频生成失败: {err}")
    raise AIError("Agnes 视频任务轮询超时")
