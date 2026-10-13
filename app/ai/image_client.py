# -*- coding: utf-8 -*-
"""图片生成客户端:openai / gemini / volcengine / agnes / qwen-image 适配(提交+轮询+落盘)。"""
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

import base64
import re
import time
import uuid
from pathlib import Path

import requests
from PIL import Image

from ..core import config
from . import registry
from .text_client import AIError


def _download(url: str, out: Path, headers: dict | None = None) -> Path:
    resp = requests.get(url, headers=headers or {}, timeout=180)
    if resp.status_code != 200:
        raise AIError(f"下载生成图片失败 HTTP {resp.status_code}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(resp.content)
    return out


def _b64_save(b64: str, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(b64))
    return out


def _ref_data_url(path: str | Path) -> str | None:
    """参考图本地路径 → 压缩 data URL(≤768px JPEG q68,对齐原版压缩口径);失败返回 None。"""
    try:
        import io
        p = Path(path)
        if not p.exists():
            return None
        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((768, 768))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=68)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return None


_NEG_UNSUPPORTED = ("negative_prompt is not supported",
                    "negative prompt is not supported",
                    "unsupported parameter: negative_prompt")


def _strip_negative(body: dict) -> bool:
    """从请求体剥离 negative_prompt(顶层 / extra_body / 深层扫描),返回是否剥掉了。"""
    removed = False
    if body.pop("negative_prompt", None) is not None:
        removed = True
    eb = body.get("extra_body")
    if isinstance(eb, dict) and eb.pop("negative_prompt", None) is not None:
        removed = True
    for v in list(body.values()):                      # 深层扫描(网关可能包一层)
        if isinstance(v, dict):
            if v.pop("negative_prompt", None) is not None:
                removed = True
    return removed


def _neg_unsupported(resp) -> bool:
    """上游是否以「不支持 negative_prompt」为由拒绝了请求。"""
    try:
        text = _utf8_text(resp, 500).lower()
    except Exception:  # noqa: BLE001
        return False
    return any(m in text for m in _NEG_UNSUPPORTED)


def _post_with_negative(url: str, body: dict, headers: dict, *, timeout: int,
                        prefix: str, **post_kw):
    """提交请求;上游不支持 negative_prompt 时**剥离后自动重试一次**。

    对齐原版 generation.ts 的「negative_prompt is not supported → 去掉重试」:
    平台质量守卫仍会下发负面词,但模型不吃这个字段时不能因此整次失败。
    """
    resp = requests.post(url, json=body, headers=headers, timeout=timeout, **post_kw)
    if resp.status_code >= 400 and _neg_unsupported(resp):
        if _strip_negative(body):
            resp = requests.post(url, json=body, headers=headers, timeout=timeout, **post_kw)
            if resp.status_code < 400:
                return resp
            text = _utf8_text(resp, 400)
            raise AIError(f"{prefix} HTTP {resp.status_code}(已去掉负面词仍失败): {text}")
        text = resp.text[:400]
        raise AIError(f"{prefix} HTTP {resp.status_code}: {text}")
    return resp


def _qwen_image_url(data: dict) -> str:
    """百炼生图响应里取图片 URL(output.choices[0].message.content[0].image,含 data: 直链)。"""
    choices = (data.get("output") or {}).get("choices") or []
    if choices:
        content = ((choices[0] or {}).get("message") or {}).get("content") or []
        if content:
            v = content[0].get("image") or content[0].get("url")
            if isinstance(v, str) and v:
                return v
    results = (data.get("output") or {}).get("results") or []
    if results and results[0].get("url"):
        return str(results[0]["url"])
    return data.get("image_url") or ""



# ── 平台级提示词守卫 + 尺寸映射(对齐参考项目 prompt-guards.ts / agnes-image.ts)──
# 守卫只有 prompt_guards 一份实现。这里转发而不是复制:之前这里另抄了一份,
# 且那份的 build_image_negative_guard 没处理 people=0(空镜/道具),
# people=0 会落回「禁额外人物」那一档,等于完全不禁人。
from .prompt_guards import (  # noqa: E402,F401  (re-export,保持既有调用点可用)
    IMAGE_NEGATIVE_GUARD, build_image_negative_guard, build_image_quality_guard)


_RATIO_CANDIDATES: list[tuple[int, int]] = [
    (1, 1), (3, 4), (4, 3), (16, 9), (9, 16), (2, 3), (3, 2), (21, 9)]
_TIER_THRESHOLDS: list[tuple[int, str]] = [
    (1280, '1K'), (2560, '2K'), (3840, '3K'), (5248, '4K')]


def map_size_to_tier_ratio(size: str | None) -> tuple[str, str]:
    """项目内尺寸(1920x1080)→ Agnes 档位+比例('2K','16:9');非法/缺省→2K 16:9。"""
    import re as _re
    m = _re.match(r'^\s*(\d+)x(\d+)\s*$', (size or '').strip())
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if w > 0 and h > 0:
            target = w / h
            best = _RATIO_CANDIDATES[0]
            diff_best = 1e9
            for cand in _RATIO_CANDIDATES:
                d = abs(target - cand[0] / cand[1])
                if d < diff_best:
                    diff_best, best = d, cand
            tier = next((t for th, t in _TIER_THRESHOLDS if max(w, h) <= th), '4K')
            return tier, f'{best[0]}:{best[1]}'
    raw = (size or '').strip().upper()
    if raw in ('1K', '2K', '3K', '4K'):
        return raw, '1:1'
    return '2K', '16:9'


# 哪些 provider 真正支持"参考图"入参。
# agnes 走 extra_body.image[] 注入;qwen-image / volcengine 的请求体里根本没有
# 图像字段,传了也被丢弃 —— 表现为「按参考图重绘」实际变成纯文生图,画面与原图
# 完全无关。调用改图类功能前必须先过这个检查,否则会白花钱。
REFERENCE_CAPABLE_PROVIDERS = {"agnes", "local", "comfyui", "sdwebui", "fooocus"}


def supports_reference_images(provider: str | None) -> bool:
    """该 provider 是否真的会把参考图发给模型。"""
    return (provider or "").strip().lower() in REFERENCE_CAPABLE_PROVIDERS


def generate_image(prompt: str, out_name: str | None = None,
                   config_id: int | None = None, size: str | None = None,
                   reference_images: list[str] | None = None,
                   people: int = 1, skip_guard: bool = False,
                   extra_negative: str | None = None) -> tuple[Path, str]:
    """生图:返回 (本地路径, provider)。reference_images 为本地路径列表(图生图参考)。

    仅 agnes 注入(extra_body.image[],≤6 张压缩 data URI);qwen-image / volcengine 等
    **忽略**参考图(见 supports_reference_images)。改图类功能务必先检查。

    **平台级质量守卫**:prompt 统一追加画面质量要求(幂等),negative_prompt 统一下发禁用词。
    people = 画面应有的人物数(漫画格=绑定角色数),>1 时守卫措辞切到「恰好 N 人」,
    否则双人格子会收到「只许一个人」的自相矛盾指令、模型可能随机删掉第二个角色。
    """
    from .prompt_guards import apply_image_quality_guard, build_image_negative_guard
    prompt = prompt if skip_guard else apply_image_quality_guard(prompt, people)
    negative = build_image_negative_guard(people) if not skip_guard else None
    if extra_negative:
        # 追加而非替换:改图场景要额外压制"凭空多出来的人",但不能把全局守卫
        # 里对正常人物生成有用的约束丢掉。opt-in,不影响其它调用方。
        negative = f"{negative}, {extra_negative}" if negative else extra_negative
    cfg = registry.check_ready("image", config_id)  # 未配置/缺 Key 直接拦下
    provider = cfg["provider"]
    # 本地生图扩展设置(comfyui_workflow/image_base_size/steps/cfg/sampler…,JSON 列)
    import json as _json
    try:
        cfg["settings"] = _json.loads(cfg["settings"]) if cfg.get("settings") else None
    except (ValueError, TypeError):
        cfg["settings"] = None
    out_name = out_name or f"{uuid.uuid4().hex}.png"
    out = config.STATIC_DIR / "images" / out_name
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"

    if provider == "qwen-image":
        # 阿里云百炼专用端点(不在 OpenAI 兼容 /images/generations 下,走那个会 404):
        #   POST {base}/api/v1/services/aigc/multimodal-generation/generation(同步)
        #   GET  {base}/api/v1/tasks/{taskId}(部分模型异步)
        # size 用「宽*高」星号分隔;响应图在 output.choices[0].message.content[0].image
        base = cfg["base_url"].rstrip("/")

        def _bail_size(sz: str | None) -> str:
            """项目内尺寸 → 百炼档位(对齐 qwen-image.ts normalizeSize):
            qwen-image 总像素须在 512²~2048² 之间,1920*1080 超上限被服务端
            归一到 1024*1024(实测三视图变方形);等比缩到上限内才保得住比例。"""
            if not sz:
                return "1024*1024"
            m = re.match(r"^(\d+)\s*[xX*]\s*(\d+)$", sz.strip())
            if not m:
                return "1024*1024"
            w, h = int(m.group(1)), int(m.group(2))
            if w <= 0 or h <= 0:
                return "1024*1024"
            total = w * h
            if total < 512 * 512:
                return f"{max(512, w)}*{max(512, h)}"
            if total > 2048 * 2048:
                scale = (2048 * 2048 / total) ** 0.5
                w = max(512, round(w * scale))
                h = max(512, round(h * scale))
                # 凑整后可能仍略超上限(1920x1080 → 2731*1536 = 4194816 > 4194304)
                while w * h > 2048 * 2048:
                    w = max(512, int(w * 0.98))
                    h = max(512, int(h * 0.98))
            return f"{w}*{h}"

        url = f"{base}/api/v1/services/aigc/multimodal-generation/generation"
        body: dict = {"model": cfg["model"],
                      "input": {"messages": [{"role": "user",
                                              "content": [{"text": prompt}]}]},
                      "parameters": {"size": _bail_size(size), "n": 1,
                                     "prompt_extend": True, "watermark": False}}
        if negative:
            body["parameters"]["negative_prompt"] = negative[:500]
        resp = _post_with_negative(url, body, headers, timeout=300, prefix="百炼生图失败")
        if resp.status_code != 200:
            raise AIError(f"百炼生图失败 HTTP {resp.status_code}: {_utf8_text(resp)[:300]}")
        data = resp.json()
        img = _qwen_image_url(data)
        if not img:
            task_id = ((data.get("output") or {}).get("task_id")) or data.get("task_id")
            if not task_id:
                raise AIError(f"百炼生图响应无图片: {str(data)[:300]}")
            img = None
            for _ in range(120):          # 5s × 120,异步模式
                time.sleep(5)
                st = requests.get(f"{base}/api/v1/tasks/{task_id}", headers=headers, timeout=30)
                if st.status_code != 200:
                    continue
                payload = st.json()
                s_ = str((payload.get("output") or {}).get("task_status")
                         or payload.get("task_status") or payload.get("status") or "").lower()
                if s_ in ("succeeded", "success", "completed"):
                    img = _qwen_image_url(payload)
                    if not img:
                        raise AIError(f"百炼任务完成但无图片: {str(payload)[:200]}")
                    break
                if s_ in ("failed", "error"):
                    raise AIError(f"百炼生图任务失败: {str(payload)[:200]}")
            if not img:
                raise AIError("百炼生图任务轮询超时(10 分钟)")
        if img.startswith("data:"):
            import base64 as _b64
            head, _, b = img.partition(",")
            _b64_save(b, out)
        else:
            _download(img, out)
        return out, provider

    if provider in ("openai", "gemini"):
        # OpenAI 兼容 images/generations
        url = cfg["base_url"].rstrip("/") + "/images/generations"
        body: dict = {"model": cfg["model"], "prompt": prompt, "n": 1}
        if size:
            body["size"] = size
        if negative:
            body["negative_prompt"] = negative
        resp = _post_with_negative(url, body, headers, timeout=300, prefix="生图失败")
        if resp.status_code != 200:
            raise AIError(f"生图失败 HTTP {resp.status_code}: {_utf8_text(resp)[:300]}")
        data = resp.json()["data"][0]
        if data.get("b64_json"):
            _b64_save(data["b64_json"], out)
        else:
            _download(data["url"], out)
        return out, provider

    if provider == "volcengine":
        # 火山方舟 Seedream:images/generations 兼容(支持 b64 返回)
        url = cfg["base_url"].rstrip("/") + "/images/generations"
        body = {"model": cfg["model"], "prompt": prompt, "response_format": "url",
                "size": size or "2K", "watermark": False}
        if negative:
            body["negative_prompt"] = negative
        resp = _post_with_negative(url, body, headers, timeout=300, prefix="生图失败")
        if resp.status_code != 200:
            raise AIError(f"生图失败 HTTP {resp.status_code}: {_utf8_text(resp)[:300]}")
        data = resp.json()["data"][0]
        if data.get("b64_json"):
            _b64_save(data["b64_json"], out)
        else:
            _download(data["url"], out)
        return out, provider

    if provider == "agnes":
        # Agnes:提交任务 → 轮询 → 下载
        submit = cfg["base_url"].rstrip("/") + "/v1/images/generations"
        tier, ratio = map_size_to_tier_ratio(size)
        # 对齐参考 agnes-image adapter:response_format=url + 平台级负面守卫
        # (禁围观者/复制人/畸形);negative 未传时用默认守卫
        extra: dict = {"response_format": "url",
                       "negative_prompt": negative or IMAGE_NEGATIVE_GUARD}
        refs = [r for r in (_ref_data_url(x) for x in (reference_images or [])[:6]) if r]
        if refs:
            extra["image"] = refs
        body = {"model": cfg["model"], "prompt": prompt, "n": 1,
                "size": tier, "ratio": ratio, "extra_body": extra}
        resp = _post_with_negative(submit, body, headers, timeout=120, prefix="Agnes 提交失败")
        if resp.status_code not in (200, 201):
            raise AIError(f"Agnes 提交失败 HTTP {resp.status_code}: {_utf8_text(resp)[:300]}")
        data = resp.json()
        # 兼容同步返回与异步任务两种形态
        if isinstance(data.get("data"), list) and data["data"] and (data["data"][0].get("url") or data["data"][0].get("b64_json")):
            item = data["data"][0]
            if item.get("b64_json"):
                _b64_save(item["b64_json"], out)
            else:
                _download(item["url"], out)
            return out, provider
        task_id = data.get("id") or data.get("task_id") or data.get("data", {}).get("task_id")
        if not task_id:
            raise AIError(f"Agnes 响应缺少任务 id: {str(data)[:300]}")
        for _ in range(120):  # 5s × 120 上限 10 分钟(对齐原版)
            time.sleep(5)
            st = requests.get(f"{cfg['base_url'].rstrip('/')}/v1/images/generations/{task_id}",
                              headers=headers, timeout=30)
            payload = st.json()
            status = str(payload.get("status") or payload.get("data", {}).get("status", "")).lower()
            if status in ("succeeded", "success", "completed"):
                item = (payload.get("data") or {}).get("images") or payload.get("images") or [{}]
                url_i = item[0].get("url") or item[0].get("image_url")
                if url_i:
                    _download(url_i, out)
                    return out, provider
                b64 = item[0].get("b64_json")
                if b64:
                    _b64_save(b64, out)
                    return out, provider
                raise AIError(f"Agnes 任务完成但无图片: {str(payload)[:300]}")
            if status in ("failed", "error", "cancelled"):
                raise AIError(f"Agnes 生图任务失败: {str(payload)[:300]}")
        raise AIError("Agnes 生图任务轮询超时(10 分钟)")

    if provider == "comfyui":
        # 本地 ComfyUI:渲染工作流(内置 SDXL/SD1.5 模板或自定义)→ /prompt → history 轮询
        from .local_image import gen_comfyui
        url_v = gen_comfyui(cfg, prompt, negative, size, reference_images)
        _download(url_v, out, headers=_download_headers(cfg))
        return out, provider

    if provider == "sdwebui":
        # 本地 SD WebUI(A1111/Forge,--api 启动):同步 txt2img
        from .local_image import gen_sdwebui
        out.write_bytes(gen_sdwebui(cfg, prompt, negative, size))
        return out, provider

    if provider == "fooocus":
        # 本地 Fooocus-API:txt2img / IP-Adapter 参考图生图
        from .local_image import gen_fooocus
        out.write_bytes(gen_fooocus(cfg, prompt, negative, size, reference_images))
        return out, provider

    raise AIError(f"不支持的图片 provider: {provider}")


def _download_headers(cfg: dict) -> dict | None:
    """ComfyUI /view 下载可能要鉴权(Bearer)。"""
    return {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else None


def test_config(cfg: dict | None = None, config_id: int | None = None) -> tuple[bool, str]:
    """设置页「测试」。本地三 provider(comfyui/sdwebui/fooocus)走轻量探针(不真出图),
    云端 provider 真实生成一张测试图。"""
    if cfg is None and config_id is not None:
        import sqlite3
        from ..core import db as _db
        cfg = _db.q1("SELECT * FROM ai_configs WHERE id=?", (config_id,))
    cfg = dict(cfg or {})
    if cfg.get("provider") in ("comfyui", "sdwebui", "fooocus"):
        from .local_image import probe_local
        return probe_local(cfg["provider"], cfg)
    try:
        out, _ = generate_image("a red apple on white background, product photo",
                                out_name=f"_test_{uuid.uuid4().hex[:8]}.png",
                                config_id=cfg.get("id"))
        out.unlink(missing_ok=True)
        return True, "OK"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]
