# -*- coding: utf-8 -*-
"""通用蒙版擦除/恢复(panel / character / scene / prop 全资产)—— 对齐参考 ecda917 + 9272acf。

前端 lightbox 画笔涂抹 → 导出「透明底 + 不透明白色笔迹」的 mask PNG(alpha 通道即形状);
后端按 类型+id+图版本(main=主图 / comic=漫画镜像)解析当前图,补丁式 inpaint 填充被涂区域,
首次擦除前把最初原图备份(资产在 erase-backup/<type>/<id>/,面板在原文件旁),可一键还原。
"""
from __future__ import annotations

import base64
import io
import re
import shutil
import uuid
from pathlib import Path

from PIL import Image

from ..core import config, db
from .inpaint import inpaint_masked

ERASE_TYPES = ("panel", "character", "scene", "prop")
_MIME_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class EraseError(RuntimeError):
    pass


def _panel_row(panel_id: int) -> dict:
    row = db.q1("SELECT * FROM comic_panels WHERE id=?", (panel_id,))
    if not row:
        raise EraseError("漫画分镜格不存在")
    if not row["image_url"]:
        raise EraseError("该分镜格还没出图,无法擦除")
    return dict(row)


def _asset_row(ertype: str, asset_id: int) -> dict:
    table = {"character": "characters", "scene": "scenes", "prop": "props"}[ertype]
    row = db.q1(f"SELECT * FROM {table} WHERE id=?", (asset_id,))
    if not row:
        raise EraseError({"character": "角色", "scene": "场景", "prop": "道具"}[ertype] + "不存在")
    return dict(row)


def _resolve_target(ertype: str, asset_id: int, kind: str = "main") -> dict:
    """定位当前图:返回 {abs_path, backup_path, set_image}。"""
    if ertype == "panel":
        row = _panel_row(asset_id)
        abs_path = config.media_url_to_path(row["image_url"])
        ext = abs_path.suffix or ".png"
        # 面板备份固定在 comic/panel/<id>/(历史方案位置)
        backup = abs_path.parent / f"_orig_backup{ext}"
        def set_image(p: str):
            db.ex("UPDATE comic_panels SET image_url=?, updated_at=? WHERE id=?",
                  (config.path_to_media_url(Path(p)), db.now(), asset_id))
        return {"abs_path": abs_path, "backup_path": backup, "set_image": set_image}

    label = {"character": "角色", "scene": "场景", "prop": "道具"}[ertype]
    row = _asset_row(ertype, asset_id)
    raw = (row.get("comic_image_url") if kind == "comic" else row.get("image_url")) or ""
    if not raw:
        raise EraseError(f"该{label}还没有{'漫画风格图' if kind == 'comic' else '出图'}")
    if re.match(r"^https?://", raw):
        raise EraseError("该图是外部链接,暂不支持在线擦除")
    abs_path = config.media_url_to_path(raw)
    ext = abs_path.suffix or ".png"
    backup_dir = config.STATIC_DIR / "erase-backup" / ertype
    backup = backup_dir / f"{asset_id}{'_comic' if kind == 'comic' else ''}{ext}"

    col = "comic_image_url" if kind == "comic" else "image_url"
    table = {"character": "characters", "scene": "scenes", "prop": "props"}[ertype]

    def set_image(p: str):
        db.ex(f"UPDATE {table} SET {col}=?, updated_at=? WHERE id=?",
              (config.path_to_media_url(Path(p)), db.now(), asset_id))
    return {"abs_path": abs_path, "backup_path": backup, "set_image": set_image}


def _find_backup(target: dict) -> Path | None:
    b = target["backup_path"]
    if b.exists():
        return b
    legacy = target["abs_path"].with_name(target["abs_path"].stem + "_orig" + target["abs_path"].suffix)
    return legacy if legacy.exists() else None


def _normalize_mask(mask_b64: str, w: int, h: int) -> bytes:
    """mask base64 → 归一化 PNG 字节(形状必须在 alpha 通道;灰度蒙版转 alpha)。"""
    raw = base64.b64decode(re.sub(r"^data:image/\w+;base64,", "", mask_b64))
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    alpha = img.getchannel("A")
    # 全不透明的灰度笔迹图(很多画板导出白色笔迹+不透明底)→ 用亮度当 alpha
    if alpha.getextrema() == (255, 255):
        lum = img.convert("L")
        alpha = lum.point(lambda v: 255 if v >= 128 else 0)
    alpha = alpha.resize((w, h), Image.NEAREST).filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(2))
    out = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    out.putalpha(alpha)
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def erase_region(ertype: str, asset_id: int, mask_b64: str, kind: str = "main") -> Path:
    """擦除:备份最初原图 → mask 归一化 → inpaint → 落盘回写。返回新图本地路径。"""
    if ertype not in ERASE_TYPES:
        raise EraseError(f"类型不支持: {ertype}")
    target = _resolve_target(ertype, asset_id, kind)
    abs_path: Path = target["abs_path"]
    if not abs_path.exists():
        raise EraseError("图片文件已丢失,无法擦除")
    base = Image.open(abs_path)
    W, H = base.size
    # 首次擦除前备份最初原图(已存在则不动 —— 永远保住最早版本)
    backup: Path = target["backup_path"]
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        shutil.copy2(abs_path, backup)
    mask_fit = _normalize_mask(mask_b64, W, H)
    result = inpaint_masked(abs_path.read_bytes(), mask_fit)
    out_dir = config.STATIC_DIR / ("comic/panel" if ertype == "panel" else "images")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"erase_{uuid.uuid4().hex[:10]}.png"
    out.write_bytes(result)
    target["set_image"](str(out))
    return out


def restore_original(ertype: str, asset_id: int, kind: str = "main") -> Path:
    """一键还原到最初原图(备份存在时)。返回还原后的本地路径。"""
    target = _resolve_target(ertype, asset_id, kind)
    backup = _find_backup(target)
    if not backup:
        raise EraseError("没有可还原的备份(未擦除过)")
    # 还原也落新文件,擦除链路可继续 undo 到本备份
    out_dir = config.STATIC_DIR / ("comic/panel" if ertype == "panel" else "images")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"restore_{uuid.uuid4().hex[:10]}{backup.suffix or '.png'}"
    shutil.copy2(backup, out)
    target["set_image"](str(out))
    return out


# ── 去背景(rembg,换脸边车 /remove;对齐参考 9272acf)──────────────

def bg_remove_health(cfg: dict) -> tuple[bool, str]:
    """探针:/health 的 bg_ready 字段决定「去背景」按钮可用性。"""
    import requests
    base = (cfg.get("base_url") or "http://127.0.0.1:5678").rstrip("/")
    headers = {"X-API-Key": cfg["api_key"]} if cfg.get("api_key") else {}
    try:
        r = requests.get(f"{base}/health", headers=headers, timeout=4)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        body = r.json()
        if body.get("bg_ready") is True:
            return True, body.get("bg_model") or "rembg"
        return False, ("远程服务未启用去背景(需部署 face-swap-service/app.py 且安装 rembg)"
                       if cfg.get("provider") == "remote-faceswap"
                       else "换脸服务未安装 rembg: pip install \"rembg[cpu]\" 后重启服务")
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:120]


def bg_remove(cfg: dict, image_path: str | Path, alpha_matting: bool = False,
              model: str | None = None) -> Path:
    """去背景:本地路径/URL → 边车 /remove → 保存带 alpha 的 PNG 到 static/bg-remove/。

    不就地覆盖原图(jpg 目标会丢透明通道);首次调用会下载权重(u2net ~176MB)。
    """
    import requests
    base = (cfg.get("base_url") or "http://127.0.0.1:5678").rstrip("/")
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["X-API-Key"] = cfg["api_key"]
    p = Path(image_path)
    if p.exists():
        import base64 as _b64
        src = "data:image/png;base64," + _b64.b64encode(p.read_bytes()).decode()
    else:
        src = str(image_path)
    body: dict = {"image_url": src, "alpha_matting": alpha_matting}
    if model:
        body["model"] = model
    r = requests.post(f"{base}/remove", json=body, headers=headers, timeout=600)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or not data.get("ok"):
        hint = f"({data['hint']})" if data.get("hint") else ""
        raise EraseError(f"去背景失败(HTTP {r.status_code}): {data.get('detail') or '未知错误'}{hint}")
    b64 = data.get("image_base64") or ""
    if not b64:
        raise EraseError("去背景未返回 image_base64")
    out_dir = config.STATIC_DIR / "bg-remove"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{uuid.uuid4().hex[:10]}.png"
    out.write_bytes(base64.b64decode(b64))
    return out
