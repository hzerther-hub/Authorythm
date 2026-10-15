# -*- coding: utf-8 -*-
"""本地 InsightFace 换脸服务客户端(127.0.0.1:5678)。

对齐原版 face-swap-service/app.py 接口:
  POST /swap  body: {source_url, template_url, source_index, template_index,
                     swap_all_faces, face_enhance, save_local_path}
              resp: {ok, image_base64, saved_path, elapsed_ms, source_face_count, template_face_count}
  GET  /health → {status, model, providers, data_root}
source = 脸来源照片;template = 被换脸的目标图。
"""
from __future__ import annotations

import base64
import mimetypes
import uuid
from pathlib import Path

import requests

from ..core import config
from . import registry


def _utf8_text(resp, limit: int = 400) -> str:
    """错误文案按 utf-8 显式解码(requests 无 charset 时会猜,中文常被猜错成乱码)。"""
    try:
        return resp.content.decode("utf-8", errors="replace")[:limit]
    except Exception:  # noqa: BLE001
        return str(getattr(resp, "text", "") or "")[:limit]


DEFAULT_BASE = "http://127.0.0.1:5678"


def _to_data_url(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        return str(path)  # 允许直接传 URL / /static 相对地址
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def _resolve_base(config_id: int | None = None, base: str | None = None) -> str:
    """换脸服务地址优先级:显式 base > 指定配置 > faceswap 类默认配置 > 本地默认。"""
    if base:
        return base.rstrip("/")
    from . import registry
    cfg = registry.default_config("faceswap", config_id)
    if cfg and cfg.get("base_url"):
        return str(cfg["base_url"]).rstrip("/")
    return DEFAULT_BASE


def health(base: str | None = None, config_id: int | None = None) -> tuple[bool, str]:
    _base = _resolve_base(config_id, base)
    try:
        resp = requests.get(f"{_base}/health", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            # 新版返回 {local:{ok}, remote:{ok}};旧版扁平 {ok}(对齐原版 09e76b8 修复)
            ok_flag = data.get("local", {}).get("ok") if isinstance(data.get("local"), dict) else None
            if ok_flag is None:
                ok_flag = data.get("ok")
            if ok_flag is None:
                # 新版边车只回 {"status":"ok","model":...},没有 ok 字段(旧两种格式已不适用)
                ok_flag = str(data.get("status", "")).lower() == "ok"
            model = (data.get("model") or (data.get("local") or {}).get("model") or "")
            return bool(ok_flag), f"{data.get('status', 'ok')} · {model}"
        return False, _utf8_text(resp, 200)
    except Exception as e:  # noqa: BLE001
        # 本地服务没起是最常见的报错,直接把"怎么装/怎么启"指给用户,
        # 免得只看到一句 Connection refused 不知道去哪下手。
        hint = ""
        if "127.0.0.1" in _base or "localhost" in _base:
            hint = (" —— 本地换脸服务未启动。安装与启动步骤见 "
                    "docs/换脸服务-安装与本地启动.md;"
                    "或改用远程换脸(provider=remote-faceswap)")
        return False, f"服务不可达({_base}):{e}{hint}"


def swap_one(template_path: str | Path, source_path: str | Path,
             swap_all_faces: bool = True, face_enhance: bool = False,
             source_index: int = 0, base: str | None = None,
             config_id: int | None = None) -> Path:
    """单图换脸:template=被换图,source=脸来源。返回输出图片路径。

    config_id/base 可指向本地(127.0.0.1:5678)或远程换脸服务,接口协议一致。
    """
    _base = _resolve_base(config_id, base)
    # 输出格式按模板扩展名判定(对齐原版:png 保留透明通道,否则 jpg)
    out_fmt = "png" if str(template_path).lower().endswith(".png") else "jpg"
    payload = {
        "source_url": _to_data_url(source_path),
        "template_url": _to_data_url(template_path),
        "source_index": source_index,
        "template_index": 0,
        "swap_all_faces": swap_all_faces,
        "face_enhance": face_enhance,
        "output_format": out_fmt,
    }
    resp = requests.post(f"{_base}/swap", json=payload, timeout=300)
    if resp.status_code != 200:
        raise RuntimeError(f"换脸服务返回 HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if not data.get("ok") or not data.get("image_base64"):
        raise RuntimeError(f"换脸失败: {str(data)[:200]}")
    out = config.STATIC_DIR / "images" / f"faceswap_{uuid.uuid4().hex[:12]}.png"
    out.write_bytes(base64.b64decode(data["image_base64"]))
    return out


def test_config(cfg: dict) -> tuple[bool, str]:
    return health(cfg.get("base_url"))


# ── 远程换脸(对齐原版 4c6d1de / 25131f7)──
REMOTE_BACKOFF_S = [3, 6, 12]          # 503 退避表,优先用 Retry-After
REMOTE_TIMEOUT_S = 300                  # 纯 CPU 推理,大图一两分钟
NO_RETRY_STATUS = {400, 401, 413, 422, 502}


def _inline_image(url: str) -> str:
    """把图转 data URL(远程 URL 也下载后内联,避免远程拉不到我们给的地址触发 502)。"""
    import mimetypes
    from ..core import config as _cfg
    if str(url).startswith("data:"):
        return url
    p = (_cfg.media_url_to_path(url) if str(url).startswith(("/static/", "static/"))
         else Path(url))
    if not p.exists():
        raise RuntimeError(f"图片不存在:{p}")
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def health_remote(config_id: int | None = None) -> tuple[bool, str]:
    """远程换脸健康检查(按 provider=remote-faceswap 的 faceswap 配置)。"""
    cfg = registry.default_config("faceswap", config_id)
    if not cfg or cfg.get("provider") != "remote-faceswap":
        return False, "远程换脸未配置(设置页添加换脸服务:provider=remote-faceswap)"
    key = (cfg.get("api_key") or "").strip()
    if not key:
        return False, "远程换脸配置缺少 API Key"
    base = (cfg.get("base_url") or "https://face.mei.biz").rstrip("/")
    try:
        r = requests.get(f"{base}/health", headers={"X-API-Key": key}, timeout=20)
        ok_flag = r.json().get("ok", r.status_code == 200)
        return bool(ok_flag), (r.json().get("model") or "remote")
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:120]


def swap_remote(source_path: str | Path, template_path: str | Path,
                output_format: str = "jpg", config_id: int | None = None):
    """远程换脸:X-API-Key 鉴权,两张图内联,503 退避重试,结构化错误码透传。"""
    cfg = registry.default_config("faceswap", config_id)
    if not cfg or cfg.get("provider") != "remote-faceswap":
        raise RuntimeError("远程换脸未配置(设置页需存在 provider=remote-faceswap 的换脸服务)")
    key = (cfg.get("api_key") or "").strip()
    if not key:
        raise RuntimeError("远程换脸配置缺少 API Key,请到设置页补全")
    base = (cfg.get("base_url") or "https://face.mei.biz").rstrip("/")
    try:
        src_in = _inline_image(str(source_path))
        tpl_in = _inline_image(str(template_path))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"读取换脸图片失败:{e}") from e
    payload = {"source_url": src_in, "template_url": tpl_in,
                "source_index": 0, "template_index": 0,
                "swap_all_faces": True, "output_format": output_format}
    headers = {"Content-Type": "application/json", "X-API-Key": key}
    last = ""
    for attempt in range(len(REMOTE_BACKOFF_S) + 1):
        try:
            r = requests.post(f"{base}/swap", json=payload, headers=headers,
                              timeout=REMOTE_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"远程换脸调用失败:{e}") from e
        data = r.json() if r.content else {}
        if r.status_code == 200 and data.get("ok"):
            b64 = data.get("image_base64")
            if not b64:
                raise RuntimeError("远程换脸响应缺少 image_base64")
            out = config.STATIC_DIR / "images" / f"rswap_{uuid.uuid4().hex[:12]}.{output_format}"
            out.write_bytes(base64.b64decode(b64))
            return out
        # 结构化错误透传(远程中文 detail + error_code + hint)
        detail = data.get("detail") or data.get("message") or r.text[:200]
        last = f"{detail}" + (f"({data.get('error_code')})" if data.get("error_code") else "")
        if r.status_code in NO_RETRY_STATUS:
            raise RuntimeError(f"远程换脸失败:{last}")
        if r.status_code == 503:      # 模型未加载,可退避重试
            import time as _t
            ra = r.headers.get("Retry-After")
            wait = float(ra) if ra and ra.isdigit() else REMOTE_BACKOFF_S[min(attempt, len(REMOTE_BACKOFF_S) - 1)]
            if attempt < len(REMOTE_BACKOFF_S):
                _t.sleep(wait)
                continue
        break
    raise RuntimeError(f"远程换脸失败:{last}")


def swap_one_by_provider(source_path: str | Path, template_path: str | Path,
                         provider: str | None = None, config_id: int | None = None,
                         output_format: str = "jpg",
                         swap_all_faces: bool = True, face_enhance: bool = False) -> Path:
    """按所选引擎分发单图重绘(原版 bug:重绘写死本地引擎,选远程也失败)。"""
    if provider == "remote-faceswap":
        return swap_remote(source_path, template_path, output_format, config_id=config_id)
    return swap_one(template_path, source_path, swap_all_faces=swap_all_faces,
                    face_enhance=face_enhance, config_id=config_id)
