# -*- coding: utf-8 -*-
"""本地生图服务(ComfyUI / SD WebUI / Fooocus)—— 对齐参考项目 0117459(移植自 uu889-drama)。

三个零云额度、数据不出本机的图片 provider:

    comfyui   原生 HTTP API。
              上传: POST /upload/image (multipart: image, type=input, overwrite=true) → { name, subfolder }
              提交: POST /prompt { prompt: <API 格式工作流>, client_id } → { prompt_id, node_errors }
              轮询: GET /history/{prompt_id}(结束前为 {});空时再查 /queue,两处皆无=任务丢失
              取回: GET /view?filename=&subfolder=&type=output
              内置 SDXL/SD1.5 文生图模板(Checkpoint+KSampler+SaveImage),支持自定义工作流
              (settings.comfyui_workflow,{{prompt}}/{{seed}}/{{width}}… 占位符),
              参考图只在自定义工作流引用时上传;缺素材节点级联裁剪(/object_info 必填输入校验)
    sdwebui   AUTOMATIC1111 / Forge / reForge 兼容 /sdapi/v1/txt2img(--api 启动;
              Key 填「用户名:密码」走 Basic 鉴权),模型经 override_settings 临时切换。
              同步接口,无轮询。
    fooocus   Fooocus-API(默认端口 8888)。txt2img / IP-Adapter 参考图生图(≤4 张)。
              async_process → { job_id } → GET /v1/generation/query-job →
              { job_stage: WAITING|RUNNING|SUCCESS|ERROR, job_result: [{ base64, url, ... }] }

公共工具(对齐 local-image.ts):鉴权(Key 含冒号=Basic,否则 Bearer+X-API-KEY)、
尺寸换算(项目尺寸 → base_size² 保持比例对齐 64)、默认负向词。
"""
from __future__ import annotations

import io
import json
import math
import random
import re
import uuid
from pathlib import Path

import requests
from PIL import Image

from .text_client import AIError

COMFYUI_CLIENT_ID = "yihao-pyside"
COMFYUI_DEFAULT_MODEL = "sd_xl_base_1.0.safetensors"
SDWEBUI_DEFAULT_BASE = "http://127.0.0.1:7860"
FOOOCUS_DEFAULT_BASE = "http://127.0.0.1:8888"
MAX_REFERENCE_IMAGES = 6          # comfyui 参考图上限
FOOOCUS_MAX_IMAGE_PROMPTS = 4     # fooocus IP-Adapter 上限

IMAGE_EXT_RE = re.compile(r".*\.(png|jpe?g|webp)$", re.I)
IMAGE_PLACEHOLDER_RE = re.compile(r"^(image|first_frame|last_frame|reference_image_\d+)$", re.I)
PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}", re.I)
NUMERIC_PLACEHOLDERS = {"seed", "width", "height", "duration", "fps", "frames", "length", "steps", "cfg"}
TEXT_PLACEHOLDERS = {"prompt", "negative_prompt", "aspect_ratio", "resolution", "model"}

# 本地 ComfyUI 串行出图,批量提交排队久:轮询放宽 10s × 2160(6 小时)
COMFY_POLL_ROUNDS = 2160
COMFY_POLL_INTERVAL = 10

# 通用 SD 负向提示词(本地生图未配置负向词时使用)
LOCAL_DEFAULT_NEGATIVE_PROMPT = (
    "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, "
    "fewer digits, cropped, worst quality, low quality, jpeg artifacts, signature, "
    "watermark, username, blurry"
)


# ── 公共工具(对齐 local-image.ts)────────────────────────────────

def number_setting(value, fallback: float, lo: float, hi: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return fallback
    return n if lo <= n <= hi else fallback


def text_setting(value, fallback: str = "") -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def is_default_model(model) -> bool:
    """模型名为空 / default / current 表示沿用服务当前加载的模型。"""
    return not model or bool(re.match(r"^(default|current|默认)$", str(model).strip(), re.I))


def local_auth_headers(api_key: str | None) -> dict:
    """Key 含冒号=HTTP Basic(SD WebUI --api-auth);否则 Bearer + X-API-KEY(Fooocus)。未填不带。"""
    key = (api_key or "").strip()
    if not key:
        return {}
    if ":" in key:
        import base64
        return {"Authorization": "Basic " + base64.b64encode(key.encode()).decode()}
    return {"Authorization": f"Bearer {key}", "X-API-KEY": key}


def local_url(base_url: str, fallback_base: str, path: str) -> str:
    base = (base_url or fallback_base).rstrip("/")
    return base + (path if path.startswith("/") else "/" + path)


def local_image_dimensions(size: str | None, base_size: float = 1024) -> tuple[int, int]:
    """项目尺寸('1920x1080')→ SD 系适合的出图尺寸:保持比例、总像素≈base²、对齐 64。"""
    try:
        w, h = (int(x) for x in str(size or "").lower().split("x"))
    except ValueError:
        w = h = 0
    ratio = w / h if w > 0 and h > 0 else 1.0
    base = int(base_size) if base_size >= 256 else 1024
    area = base * base

    def align(v: float) -> int:
        return max(64, round(v / 64) * 64)
    return align(math.sqrt(area * ratio)), align(math.sqrt(area / ratio))


def strip_data_prefix(b64: str) -> str:
    return re.sub(r"^data:[^;]+;base64,", "", str(b64 or ""))


def _parse_refs(raw) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if isinstance(raw, (list, tuple)):
        return [str(u) for u in raw if u]
    return []


def _read_image_bytes(source: str | Path) -> tuple[bytes, str]:
    """参考图源(本地路径/data URL/http URL)→ (字节, 文件名)。对齐 media.ts loadReferenceFile。"""
    s = str(source)
    if s.startswith("data:"):
        b64 = strip_data_prefix(s)
        return __import__("base64").b64decode(b64), f"{uuid.uuid4().hex[:8]}.png"
    if s.startswith(("http://", "https://")):
        data = requests.get(s, timeout=60).content
        return data, f"{uuid.uuid4().hex[:8]}.png"
    p = Path(s)
    if not p.exists():
        raise AIError(f"参考图不存在: {s}")
    return p.read_bytes(), p.name


# ── ComfyUI(公共流程,对齐 comfyui-common.ts)─────────────────────

def parse_comfy_workflow(raw) -> dict | None:
    """解析配置工作流(字符串/对象)并校验 API 格式;空返回 None(用内置模板)。"""
    if raw is None or raw == "":
        return None
    parsed = raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except ValueError as e:
            raise AIError(f"ComfyUI 工作流不是合法 JSON: {e}")
    if not isinstance(parsed, dict):
        raise AIError("ComfyUI 工作流必须是 JSON 对象")
    if isinstance(parsed.get("nodes"), list):
        raise AIError("这是 ComfyUI 界面格式的工作流,请在 ComfyUI 中用「导出 (API)」重新导出")
    if isinstance(parsed.get("prompt"), dict):     # 兼容直接粘贴 /prompt 请求体
        parsed = parsed["prompt"]
    nodes = list(parsed.values())
    if not nodes or not all(isinstance(n, dict) and isinstance(n.get("class_type"), str) for n in nodes):
        raise AIError("ComfyUI 工作流格式不正确:每个节点都需要 class_type(请使用「导出 (API)」得到的 JSON)")
    return parsed


def _is_link(value) -> bool:
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and isinstance(value[1], int) and isinstance(value[0], (str, int)))


def render_comfy_workflow(template: dict, values: dict,
                          required_inputs: dict | None = None) -> dict:
    """替换 {{占位符}} + 级联裁剪缺素材的图片节点(对齐 renderComfyWorkflow)。

    字段值恰好是一个占位符时按类型替换(数字占位符写数字)。图片占位符无素材时,
    引用它的节点连同只依赖它的下游一起移除;被断开必填输入(/object_info)的节点也移除。
    """
    import copy
    workflow = copy.deepcopy(template)
    required_inputs = required_inputs or {}
    pruned: set[str] = set()
    unknown: set[str] = set()

    def substitute(value, node_id):
        if isinstance(value, str):
            exact = re.fullmatch(r"\{\{\s*([a-z0-9_]+)\s*\}\}", value, re.I)
            if exact:
                k = exact.group(1).lower()
                v = values.get(k)
                if v is None or v == "":
                    if IMAGE_PLACEHOLDER_RE.match(k):
                        pruned.add(node_id)
                    elif k in TEXT_PLACEHOLDERS:
                        return ""
                    else:
                        unknown.add(k)
                    return value
                return float(v) if k in NUMERIC_PLACEHOLDERS and str(v).replace(".", "", 1).lstrip("-").isdigit() else v
            def repl(m):
                k = m.group(1).lower()
                v = values.get(k)
                if v is None or v == "":
                    if IMAGE_PLACEHOLDER_RE.match(k):
                        pruned.add(node_id)
                    elif k in TEXT_PLACEHOLDERS:
                        return ""
                    else:
                        unknown.add(k)
                    return m.group(0)
                return str(v)
            return PLACEHOLDER_RE.sub(repl, value)
        if isinstance(value, list):
            return value if _is_link(value) else [substitute(x, node_id) for x in value]
        if isinstance(value, dict):
            for k in list(value.keys()):
                value[k] = substitute(value[k], node_id)
        return value

    for node_id, node in workflow.items():
        if isinstance(node, dict) and "inputs" in node:
            node["inputs"] = substitute(node["inputs"], node_id)
    if unknown:
        raise AIError("ComfyUI 工作流包含不支持的占位符: " + "、".join(f"{{{{{k}}}}}" for k in sorted(unknown)))

    # 级联移除:连线全断或断的是必填输入
    changed = bool(pruned)
    while changed:
        changed = False
        for node_id, node in workflow.items():
            if node_id in pruned or not isinstance(node, dict):
                continue
            inputs = node.get("inputs") or {}
            links = [(k, v) for k, v in inputs.items() if _is_link(v)]
            if not links:
                continue
            dangling = [(k, v) for k, v in links if str(v[0]) in pruned]
            if not dangling:
                continue
            required = required_inputs.get(node.get("class_type") or "", [])
            if len(dangling) == len(links) or any(k in required for k, _ in dangling):
                pruned.add(node_id)
                changed = True
    for node_id in pruned:
        workflow.pop(node_id, None)
    for node in workflow.values():
        inputs = node.get("inputs") or {}
        for k in [k for k, v in inputs.items() if _is_link(v) and str(v[0]) in pruned]:
            inputs.pop(k, None)
    if not workflow:
        raise AIError("ComfyUI 工作流裁剪后为空")
    return workflow


def comfy_url(cfg: dict, path: str) -> str:
    base = (cfg.get("base_url") or "http://127.0.0.1:8188").rstrip("/")
    return base + (path if path.startswith("/") else "/" + path)


def _comfy_headers(cfg: dict) -> dict:
    return {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}


def _comfy_upload_image(cfg: dict, source: str, base_name: str) -> str:
    data, filename = _read_image_bytes(source)
    resp = requests.post(comfy_url(cfg, "/upload/image"),
                         files={"image": (filename, data)},
                         data={"type": "input", "overwrite": "true"},
                         headers=_comfy_headers(cfg), timeout=120)
    if resp.status_code != 200:
        raise AIError(f"ComfyUI 上传参考图失败(HTTP {resp.status_code}): {resp.text[:200]}")
    d = resp.json()
    if not d.get("name"):
        raise AIError("ComfyUI 上传参考图未返回文件名")
    return f"{d['subfolder']}/{d['name']}" if d.get("subfolder") else d["name"]


def _comfy_fetch_json(cfg: dict, path: str):
    resp = requests.get(comfy_url(cfg, path), headers=_comfy_headers(cfg), timeout=60)
    if resp.status_code != 200:
        raise AIError(f"ComfyUI {path} HTTP {resp.status_code}")
    return resp.json()


def _comfy_required_inputs(cfg: dict, class_types: list[str]) -> dict:
    """查节点类型必填输入;失败返回空表(退回只按连线判断)。"""
    out: dict = {}
    for ct in class_types:
        try:
            resp = requests.get(comfy_url(cfg, f"/object_info/{ct}"),
                                headers=_comfy_headers(cfg), timeout=15)
            if resp.status_code != 200:
                continue
            info = resp.json().get(ct) or {}
            required = (info.get("input") or {}).get("required")
            if isinstance(required, dict):
                out[ct] = list(required.keys())
        except Exception:  # noqa: BLE001
            continue
    return out


COMFY_MISSING_ERROR = "ComfyUI 的队列和历史里都找不到该任务(ComfyUI 可能已重启或任务被删除),请重新生成"


def _comfy_fetch_poll_result(cfg: dict, task_id: str):
    """history 为空时查 /queue,两处皆无 → __comfyMissing(立即判失败不空等)。"""
    history = _comfy_fetch_json(cfg, f"/history/{task_id}")
    if isinstance(history, dict) and history:
        return history
    queue = _comfy_fetch_json(cfg, "/queue")
    in_queue = any(isinstance(item, list) and str(item[1]) == task_id
                   for item in list(queue.get("queue_running") or []) + list(queue.get("queue_pending") or []))
    if in_queue:
        return {}
    again = _comfy_fetch_json(cfg, f"/history/{task_id}")
    if isinstance(again, dict) and again:
        return again
    return {"__comfyMissing": True}


def _comfy_read_history(result) -> dict:
    """history 记录状态: missing / running / error / finished。"""
    if result.get("__comfyMissing"):
        return {"state": "missing"}
    entry = next(iter(result.values()), None) if isinstance(result, dict) and result else None
    if not isinstance(entry, dict):
        return {"state": "running"}
    status = entry.get("status") or {}
    if status.get("status_str") == "error":
        msgs = status.get("messages") or []
        failure = next((m[1] for m in msgs if isinstance(m, list) and m and m[0] == "execution_error"), None)
        interrupted = any(isinstance(m, list) and m and m[0] == "execution_interrupted" for m in msgs)
        err = (f"ComfyUI 执行失败: {(failure or {}).get('node_type', '')} {(failure or {}).get('exception_message', '')}".strip()
               if failure else ("ComfyUI 任务被中断" if interrupted else "ComfyUI 执行失败"))
        return {"state": "error", "error": err}
    if status.get("completed") or status.get("status_str") == "success" or entry.get("outputs"):
        return {"state": "finished", "entry": entry}
    return {"state": "running"}


def _comfy_find_image_output(outputs) -> str | None:
    """在 history 节点输出里按扩展名找图片文件(/view 相对路径)。"""
    best = None
    for output in (outputs or {}).values():
        if not isinstance(output, dict):
            continue
        for lst in output.values():
            if not isinstance(lst, list):
                continue
            for item in lst:
                if (isinstance(item, dict) and isinstance(item.get("filename"), str)
                        and IMAGE_EXT_RE.match(item["filename"])):
                    score = 4 if item.get("type") == "output" else 0
                    if best is None or score > best[0]:
                        best = (score, item)
    if not best:
        return None
    from urllib.parse import urlencode
    it = best[1]
    return "/view?" + urlencode({"filename": it["filename"],
                                 "subfolder": it.get("subfolder", ""),
                                 "type": it.get("type", "output")})


# 内置模板:ComfyUI 默认文生图工作流(SDXL/SD1.5 通用)
COMFYUI_DEFAULT_IMAGE_WORKFLOW = {
    "3": {"class_type": "KSampler", "inputs": {"seed": "{{seed}}", "steps": "{{steps}}", "cfg": "{{cfg}}",
                                               "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1,
                                               "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                                               "latent_image": ["5", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "{{model}}"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": "{{width}}", "height": "{{height}}", "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{negative_prompt}}", "clip": ["4", 1]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "yihao-drama", "images": ["8", 0]}},
}


# ── Fooocus 内置 SDXL 比例档 ─────────────────────────────────────

FOOOCUS_ASPECT_RATIOS = [
    "704*1408", "704*1344", "768*1344", "768*1280", "832*1216", "832*1152", "896*1152",
    "896*1088", "960*1088", "960*1024", "1024*1024", "1024*960", "1088*960", "1088*896",
    "1152*896", "1152*832", "1216*832", "1280*768", "1344*768", "1344*704", "1408*704",
    "1472*704", "1536*640", "1600*640", "1664*576", "1728*576",
]


def fooocus_aspect_ratio(size: str | None) -> str:
    try:
        w, h = (int(x) for x in str(size or "").lower().split("x"))
    except ValueError:
        return "1024*1024"
    if not w or not h:
        return "1024*1024"
    target = math.log(w / h)

    def diff(cand: str) -> float:
        cw, ch = (int(x) for x in cand.split("*"))
        return abs(math.log(cw / ch) - target)
    return min(FOOOCUS_ASPECT_RATIOS, key=diff)


# ── 三个 provider 的生图主流程 ────────────────────────────────────

def gen_comfyui(cfg: dict, prompt: str, negative: str | None, size: str | None,
                reference_images: list[str] | None) -> str:
    """ComfyUI:渲染工作流 → 提交 /prompt → 轮询 history → 返回图片 URL(可能相对路径)。"""
    settings = cfg.get("settings") or {}
    template = parse_comfy_workflow(settings.get("comfyui_workflow")) or COMFYUI_DEFAULT_IMAGE_WORKFLOW
    width, height = local_image_dimensions(size, number_setting(settings.get("image_base_size"), 1024, 256, 2048))
    refs = _parse_refs(reference_images)[:MAX_REFERENCE_IMAGES]
    values: dict = {
        "prompt": (prompt or "").strip(),
        "negative_prompt": text_setting(settings.get("comfyui_negative_prompt"), LOCAL_DEFAULT_NEGATIVE_PROMPT) if not negative else negative,
        "seed": random.randrange(2 ** 32),
        "width": width, "height": height,
        "steps": round(number_setting(settings.get("image_steps"), 25, 1, 150)),
        "cfg": number_setting(settings.get("image_cfg_scale"), 7, 0, 30),
        "model": cfg.get("model") or COMFYUI_DEFAULT_MODEL,
        "aspect_ratio": f"{width}:{height}",
        "image": refs[0] if refs else None,
    }
    for i, ref in enumerate(refs):
        values[f"reference_image_{i + 1}"] = ref

    # 只上传工作流实际引用到的图片
    template_text = json.dumps(template)
    uploaded: dict = {}
    for key, src in list(values.items()):
        if not src or not re.search(rf"\{{\{{\s*{key}\s*\}}\}}", template_text, re.I):
            continue
        if src not in uploaded:
            uploaded[src] = _comfy_upload_image(cfg, src, f"yihao-img-{key}")
        values[key] = uploaded[src]

    workflow = render_comfy_workflow(template, values)
    # 被断开连线的节点类型 → 查必填输入 → 重新渲染
    affected = {n.get("class_type") for n in template.values()
                if any(_is_link(v) and str(v[0]) not in workflow for v in (n.get("inputs") or {}).values())}
    affected.discard(None)
    if affected:
        required = _comfy_required_inputs(cfg, list(affected))
        if required:
            values.update({k: v for k, v in values.items()})     # values 已含上传后的名字
            workflow = render_comfy_workflow(template, values, required)

    resp = requests.post(comfy_url(cfg, "/prompt"),
                         json={"prompt": workflow, "client_id": COMFYUI_CLIENT_ID},
                         headers={**_comfy_headers(cfg), "Content-Type": "application/json"},
                         timeout=120)
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = "; ".join(
                f"#{nid} {e.get('class_type', '')} " + "; ".join(
                    filter(None, (x.get("message"), x.get("details"))) for x in (e.get("errors") or []))
                for nid, e in (body.get("node_errors") or {}).items())
            msg = (body.get("error") or {}).get("message", "") if isinstance(body.get("error"), dict) else body.get("error", "")
            text = " — ".join(x for x in (msg, detail) if x)
            if text:
                raise AIError(f"ComfyUI 工作流校验失败(HTTP {resp.status_code}): {text}"[:600])
        except (ValueError, KeyError):
            pass
        raise AIError(f"ComfyUI 提交失败 HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    task_id = data.get("prompt_id")
    if not task_id:
        raise AIError(f"ComfyUI 未返回 prompt_id: {str(data)[:300]}")

    import time
    for _ in range(COMFY_POLL_ROUNDS):
        time.sleep(COMFY_POLL_INTERVAL)
        try:
            result = _comfy_fetch_poll_result(cfg, task_id)
        except AIError:
            continue                      # 单次轮询失败不终局
        state = _comfy_read_history(result)
        if state["state"] == "missing":
            raise AIError(COMFY_MISSING_ERROR)
        if state["state"] == "error":
            raise AIError(state["error"])
        if state["state"] == "finished":
            rel = _comfy_find_image_output(state["entry"].get("outputs"))
            if not rel:
                raise AIError("ComfyUI 工作流已完成但没有图片输出(请确认含 SaveImage 节点)")
            return comfy_url(cfg, rel)
    raise AIError("ComfyUI 生图轮询超时(6 小时)")


def gen_sdwebui(cfg: dict, prompt: str, negative: str | None, size: str | None) -> bytes:
    """SD WebUI(同步):POST /sdapi/v1/txt2img → PNG 字节。参考图不使用(ControlNet 参数各异)。"""
    settings = cfg.get("settings") or {}
    width, height = local_image_dimensions(size, number_setting(settings.get("image_base_size"), 1024, 256, 2048))
    body: dict = {
        "prompt": (prompt or "").strip(),
        "negative_prompt": negative or text_setting(settings.get("image_negative_prompt"), LOCAL_DEFAULT_NEGATIVE_PROMPT),
        "width": width, "height": height,
        "steps": round(number_setting(settings.get("image_steps"), 25, 1, 150)),
        "cfg_scale": number_setting(settings.get("image_cfg_scale"), 7, 0, 30),
        "seed": -1, "batch_size": 1, "n_iter": 1,
        "send_images": True, "save_images": False,
    }
    sampler = text_setting(settings.get("image_sampler"))
    if sampler:
        body["sampler_name"] = sampler
    model = cfg.get("model")
    if not is_default_model(model):
        body["override_settings"] = {"sd_model_checkpoint": model}
    url = local_url(cfg.get("base_url"), SDWEBUI_DEFAULT_BASE, "/sdapi/v1/txt2img")
    resp = requests.post(url, json=body, timeout=600,
                         headers={**local_auth_headers(cfg.get("api_key")), "Content-Type": "application/json"})
    if resp.status_code != 200:
        if resp.status_code == 404:
            raise AIError("Stable Diffusion WebUI 没有开启 API: 请用 --api 参数启动 WebUI")
        try:
            b = resp.json()
            detail = " — ".join(x for x in (b.get("error"), b.get("detail") if isinstance(b.get("detail"), str) else "") if x)
            raise AIError(f"Stable Diffusion WebUI 报错(HTTP {resp.status_code}): {detail}"[:500])
        except ValueError:
            raise AIError(f"SD WebUI 生图失败 HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    images = data.get("images") or []
    if not images:
        raise AIError("Stable Diffusion WebUI 未返回图片" +
                      (f": {data.get('error')} {data.get('detail') or ''}".rstrip() if data.get("error") else ""))
    import base64 as _b64
    return _b64.b64decode(strip_data_prefix(images[0]))


def gen_fooocus(cfg: dict, prompt: str, negative: str | None, size: str | None,
                reference_images: list[str] | None) -> bytes:
    """Fooocus-API:txt2img / IP-Adapter(参考图 ≤4)→ job 轮询 → PNG 字节。"""
    settings = cfg.get("settings") or {}
    refs = [r for r in (_read_image_bytes_src(x) for x in _parse_refs(reference_images)[:FOOOCUS_MAX_IMAGE_PROMPTS]) if r]
    body: dict = {
        "prompt": (prompt or "").strip(),
        "negative_prompt": negative or text_setting(settings.get("image_negative_prompt"), LOCAL_DEFAULT_NEGATIVE_PROMPT),
        "aspect_ratios_selection": fooocus_aspect_ratio(size),
        "performance_selection": text_setting(settings.get("fooocus_performance"), "Speed"),
        "image_number": 1, "image_seed": -1,
        "require_base64": True, "async_process": True,
    }
    styles = [x.strip() for x in text_setting(settings.get("fooocus_styles")).replace("，", ",").split(",") if x.strip()]
    if styles:
        body["style_selections"] = styles
    model = cfg.get("model")
    if not is_default_model(model):
        body["base_model_name"] = model
    if refs:
        body["image_prompts"] = [{"cn_img": r, "cn_stop": 0.5, "cn_weight": 1.0, "cn_type": "ImagePrompt"} for r in refs]
    path = "/v2/generation/text-to-image-with-ip" if refs else "/v1/generation/text-to-image"
    url = local_url(cfg.get("base_url"), FOOOCUS_DEFAULT_BASE, path)
    resp = requests.post(url, json=body, timeout=300,
                         headers={**local_auth_headers(cfg.get("api_key")), "Content-Type": "application/json"})
    if resp.status_code != 200:
        try:
            detail = resp.json().get("detail")
            detail = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
            raise AIError(f"Fooocus-API 报错(HTTP {resp.status_code}): {detail}"[:500])
        except ValueError:
            raise AIError(f"Fooocus 提交失败 HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()

    def first_result(d):
        if isinstance(d, list) and d:
            return d[0]
        if isinstance(d, dict) and isinstance(d.get("job_result"), list) and d["job_result"]:
            return d["job_result"][0]
        if isinstance(d, dict) and (d.get("base64") or d.get("url")):
            return d
        return None

    first = first_result(data)
    if first:
        if first.get("finish_reason") and first["finish_reason"] != "SUCCESS":
            raise AIError(f"Fooocus 生成失败: {first['finish_reason']}")
        if first.get("base64"):
            import base64 as _b64
            return _b64.b64decode(strip_data_prefix(first["base64"]))
        if first.get("url"):
            return requests.get(first["url"], timeout=300).content
    job_id = data.get("job_id")
    if not job_id:
        raise AIError(f"Fooocus 未返回任务 ID: {json.dumps(data.get('detail') or data, ensure_ascii=False)[:200]}")

    import time
    poll_url = local_url(cfg.get("base_url"), FOOOCUS_DEFAULT_BASE,
                         f"/v1/generation/query-job?job_id={job_id}&require_step_preview=false")
    for _ in range(720):                      # 本地 GPU 排队:5s × 720 上限 1 小时
        time.sleep(5)
        pr = requests.get(poll_url, headers=local_auth_headers(cfg.get("api_key")), timeout=60)
        if pr.status_code != 200:
            continue
        d = pr.json()
        stage = str(d.get("job_stage") or "").upper()
        if stage == "ERROR":
            raise AIError(f"Fooocus 生成失败: {d.get('job_error') or d.get('job_status') or 'ERROR'}")
        if stage == "SUCCESS":
            f2 = first_result(d)
            if not f2:
                raise AIError("Fooocus 任务完成但没有返回图片")
            if f2.get("finish_reason") and f2["finish_reason"] != "SUCCESS":
                raise AIError(f"Fooocus 生成失败: {f2['finish_reason']}")
            if f2.get("base64"):
                import base64 as _b64
                return _b64.b64decode(strip_data_prefix(f2["base64"]))
            if f2.get("url"):
                return requests.get(f2["url"], timeout=300).content
        # WAITING / RUNNING 继续
    raise AIError("Fooocus 生图轮询超时(1 小时)")


def _read_image_bytes_src(source: str) -> str | None:
    """Fooocus IP-Adapter 的 cn_img:本地路径 → 纯 base64(data 前缀剥掉);http 原样。"""
    try:
        s = str(source)
        if s.startswith("data:"):
            return strip_data_prefix(s)
        if s.startswith(("http://", "https://")):
            return s
        p = Path(s)
        if p.exists():
            import base64 as _b64
            return _b64.b64encode(p.read_bytes()).decode()
    except Exception:  # noqa: BLE001
        return None
    return None


# ── 探针(设置页「测试」按钮;对齐 buildProbe 的本地三分支)──────────

def probe_local(provider: str, cfg: dict) -> tuple[bool, str]:
    """本地服务探活:ComfyUI /system_stats;SD WebUI /sdapi/v1/options;Fooocus 根路径。"""
    auth = local_auth_headers(cfg.get("api_key"))
    try:
        if provider == "comfyui":
            r = requests.get(comfy_url(cfg, "/system_stats"), headers=auth, timeout=8)
        elif provider == "sdwebui":
            r = requests.get(local_url(cfg.get("base_url"), SDWEBUI_DEFAULT_BASE, "/sdapi/v1/options"),
                             headers=auth, timeout=8)
        else:
            r = requests.get(local_url(cfg.get("base_url"), FOOOCUS_DEFAULT_BASE, "/"), headers=auth, timeout=8)
        return (r.status_code == 200, f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:120]
