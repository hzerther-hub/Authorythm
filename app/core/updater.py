# -*- coding: utf-8 -*-
"""自动更新:检查 GitHub Releases → 下载新版本 → 替换文件 → 重启。

发布源(可覆盖,环境变量 PYDRAMA_UPDATE_FEED 或设置页):
  https://api.github.com/repos/hzerther-hub/PySide6_drama/releases/latest
Windows 采用「下载 zip → 备份旧文件 → 覆盖 → 启动新进程 → 退出」的安全更新流程。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import requests

from . import config

FEED_URL = (os.environ.get("PYDRAMA_UPDATE_FEED")
            or "https://api.github.com/repos/hzerther-hub/PySide6_drama/releases/latest")

# 更新包允许覆盖的后缀 —— **只允许源码/配置/文档**,不碰可执行文件。
# 这条白名单必须**独立于目标是否已存在**来判:早先写成
# `if dst.exists() and dst.suffix not in ALLOWED: continue`,
# 目标不存在时检查被短路,更新包里的 .exe/.bat/.pth 会直接落进程序根目录
# (可执行代码 = 远程代码执行)。更新包本身也没有完整性校验,feed 指向被改
# 就等于给所有用户发后门 —— 所以这里按「能跑起来的文件一律不覆盖」处理。
_ALLOWED_SUFFIX = {".py", ".json", ".txt", ".md", ".qss", ".spec", ".toml", ".cfg"}

STATE_KEY = "update_state"   # app_settings 里记录 last_check / last_version


def _ver(v: str) -> tuple:
    """'v1.2.3' -> (1,2,3);无法解析则返回 (0,)"""
    out = []
    for part in str(v or "").lstrip("vV").split("."):
        num = "".join(c for c in part if c.isdigit())
        out.append(int(num) if num else 0)
    return tuple(out) or (0,)


def current_version() -> str:
    return config.APP_VERSION


def read_state() -> dict:
    from . import db
    try:
        return db.jload(db.get_setting(STATE_KEY, "{}"), {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def write_state(**kw) -> None:
    from . import db
    st = read_state()
    st.update(kw)
    db.set_setting(STATE_KEY, json.dumps(st, ensure_ascii=False))


def check(timeout: int = 10) -> dict:
    """检查更新。返回 {has_update, latest, url, notes, current, error}。"""
    cur = current_version()
    result = {"has_update": False, "latest": cur, "current": cur, "url": "",
              "notes": "", "error": ""}
    try:
        r = requests.get(FEED_URL, timeout=timeout,
                         headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            result["error"] = f"检查失败:HTTP {r.status_code}"
            return result
        data = r.json()
        latest = (data.get("tag_name") or "").lstrip("vV")
        result["latest"] = latest or cur
        result["notes"] = (data.get("body") or "")[:800]
        for a in data.get("assets", []) or []:
            if a.get("name", "").lower().endswith((".zip", ".exe")):
                result["url"] = a.get("browser_download_url", "")
                break
        if not result["url"]:
            result["url"] = data.get("zipball_url") or ""
        result["has_update"] = bool(latest) and _ver(latest) > _ver(cur)
        write_state(last_check=db_now(), last_version=latest)
    except Exception as e:  # noqa: BLE001
        result["error"] = f"检查失败:{e}"
    return result


def db_now() -> str:
    from . import db
    return db.now()


def _launch_cmd() -> list[str]:
    """重启命令:python -m app.main(打包后为打包可执行文件自身)。"""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "app.main"]


def download_and_apply(url: str, progress=None) -> Path:
    """下载 zip 并覆盖程序文件(调用方负责重启)。返回解压目录。"""
    if not url:
        raise RuntimeError("没有可用的下载地址")
    tmp = Path(config.DATA_DIR) / "update"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    zip_path = tmp / "update.zip"
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with zip_path.open("wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    if not zipfile.is_zipfile(zip_path):
        raise RuntimeError("下载内容不是有效的更新包")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp / "pkg")
    # 若 zip 内只有一层目录,下钻
    pkg = tmp / "pkg"
    entries = list(pkg.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        pkg = entries[0]
    return pkg


def apply_update(pkg_dir: Path, progress=None) -> list[str]:
    """把更新包覆盖到程序根目录(先备份被覆盖的同名文件)。返回被更新文件列表。"""
    root = config.ROOT_DIR
    backup = config.DATA_DIR / "update_backup"
    updated: list[str] = []
    skip_dirs = {".git", "data", "workspace", "build", "dist", "__pycache__", "release", "vendor"}
    files = [p for p in pkg_dir.rglob("*") if p.is_file()]
    total = len(files)
    for i, f in enumerate(files, 1):
        rel = f.relative_to(pkg_dir)
        if rel.parts and rel.parts[0] in skip_dirs:
            continue
        # 后缀白名单**独立于目标是否已存在**。原来的写法是
        # `if dst.exists() and dst.suffix not in ALLOWED: continue`
        # —— 目标不存在时整条检查被短路,更新包里的 .exe/.bat/.pth 随便什么
        # 都能落进程序根目录(可执行代码 = RCE)。
        if f.suffix.lower() not in _ALLOWED_SUFFIX:
            continue
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, backup / rel)
        shutil.copy2(f, dst)
        updated.append(str(rel))
        if progress:
            progress(i, total)
    return updated


def do_update(url: str, progress=None) -> list[str]:
    """完整流程:下载 → 覆盖。返回更新文件列表(调用方重启)。"""
    pkg = download_and_apply(url, progress)
    return apply_update(pkg, progress)


def restart_app() -> None:  # pragma: no cover
    """拉起新进程后退出当前进程。"""
    subprocess.Popen(_launch_cmd(), cwd=str(config.ROOT_DIR))
    os._exit(0)
