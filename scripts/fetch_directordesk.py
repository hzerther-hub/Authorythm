# -*- coding: utf-8 -*-
"""获取导演台(DirectorDesk)web 构建产物到 data/vendor/directordesk/。

为什么这么做:预演模块(app/pipeline/previz.py + app/ui/previz_page.py)的渲染/
动画/视频编码**完全复用原版**,Python 不重写 —— 画质与原版逐位同源。原版是
TS+three.js,本机没有 node 没法 vite build,所以直接从上游 Release 的
Electron 免安装包里抽 `resources/app.asar`(内含同一份浏览器端构建产物,
源码里对 `window.directorDesktop` 全部做了可选链,浏览器环境可独立运行)。

用法:
    python scripts/fetch_directordesk.py                # 联网下载 Release → 解包
    python scripts/fetch_directordesk.py --zip xx.zip   # 用已下载的离线包

纯 Python 解析 asar(格式:[4][header_size][json_len][json...][文件数据]),
不依赖 node/npx asar。
"""
from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.logging_setup import get_logger  # noqa: E402

log = get_logger(__name__)

# 唯一真相源:上游 mangfufu/director-desk(MIT,410★)。
# 不用第三方 fork(如 hzerther-hub)—— 内核跑在用户机器上,供应链只认上游。
UPSTREAM_REPO = "mangfufu/director-desk"
# 固定版本保证可复现;要追新用 --latest(查 GitHub API 拿最新 Release 的 win-x64 ZIP)。
RELEASE_ZIP_URL = (f"https://github.com/{UPSTREAM_REPO}/releases/"
                   "download/v0.5.1/DirectorDesk-Portable-0.5.1-win-x64.zip")
VENDOR_DIR = ROOT / "data" / "vendor" / "directordesk"
APP_DIR = VENDOR_DIR / "app"


def _latest_release_zip_url() -> str:
    """查上游最新 Release 里名字带 Portable + win-x64 的 ZIP。"""
    api = f"https://api.github.com/repos/{UPSTREAM_REPO}/releases/latest"
    req = urllib.request.Request(api, headers={"User-Agent": "pydrama-fetch"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        rel = json.loads(resp.read().decode("utf-8"))
    for asset in rel.get("assets") or []:
        name = asset.get("name") or ""
        if "Portable" in name and "win-x64" in name and name.endswith(".zip"):
            log.info("上游最新:%s(%s)", rel.get("tag_name"), name)
            return asset["browser_download_url"]
    raise RuntimeError(f"上游最新 Release 里没有 Portable win-x64 ZIP:{rel.get('tag_name')}")


def _download(url: str, dest: Path) -> Path:
    log.info("下载 %s ...", url)
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "pydrama-fetch"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if total:
                log.info("  %d/%d MB (%.0f%%)", done >> 20, total >> 20, done * 100 / total)
    tmp.replace(dest)
    return dest


def extract_app_asar(zip_path: Path, dest_dir: Path) -> Path:
    """从免安装 ZIP 里只抽 resources/app.asar(Electron 运行时那 150MB 用不上)。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if n.endswith("app.asar")]
        if not names:
            raise RuntimeError(f"ZIP 里没有 resources/app.asar:{zip_path}")
        out = dest_dir / "app.asar"
        with zf.open(names[0]) as src, open(out, "wb") as fh:
            shutil.copyfileobj(src, fh)
        return out


def _asar_read(asar: Path) -> tuple[dict, int]:
    """返回 (文件树 JSON, 文件数据区起始偏移)。

    asar 布局(Chromium pickle,实测 v0.5.1 校准):
      [0:4]  uint32 = 4              (size pickle 的 payload 长度)
      [4:8]  uint32 = header pickle 总长 size
      [8:12] uint32 = header pickle payload 长度
      [12:16] uint32 = json 字节长度
      [16:16+json_len]  JSON 文件树
      [8+size:]  文件数据区,树内 offset 相对这里
    """
    with open(asar, "rb") as fh:
        head = fh.read(16)
        if len(head) < 16:
            raise RuntimeError(f"asar 文件过小:{asar}")
        size = struct.unpack_from("<I", head, 4)[0]
        json_len = struct.unpack_from("<I", head, 12)[0]
        fh.seek(16)
        raw = fh.read(json_len)
        try:
            header = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"asar 头解析失败(格式不符合预期):{exc}") from exc
        return header, 8 + size


def extract_asar(asar: Path, out_dir: Path) -> int:
    header, data_base = _asar_read(asar)
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    def walk(node: dict, rel: Path) -> None:
        nonlocal count
        for name, child in (node.get("files") or {}).items():
            target = rel / name
            if "files" in child:
                walk(child, target)
                continue
            if child.get("unpacked"):
                # unpacked 文件与 asar 同目录的 xxx.unpacked/ 下
                src = asar.parent / (asar.stem + ".unpacked") / target
                if src.exists():
                    dst = out_dir / target
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    count += 1
                continue
            offset = int(child["offset"])
            size = int(child["size"])
            dst = out_dir / target
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(asar, "rb") as fh:
                fh.seek(data_base + offset)
                remaining = size
                with open(dst, "wb") as out:
                    while remaining > 0:
                        chunk = fh.read(min(1 << 20, remaining))
                        if not chunk:
                            raise RuntimeError(f"asar 数据被截断:{target}")
                        out.write(chunk)
                        remaining -= len(chunk)
            count += 1

    walk(header, Path())
    return count


def find_web_entry(out_dir: Path) -> Path | None:
    """在解包树里找浏览器端入口(index.html)。"""
    candidates = sorted(out_dir.rglob("index.html"))
    # 渲染层入口一般带 assets/ 或 js 目录;package.json 旁边的多半是别的
    for c in candidates:
        if any(p.name in ("assets", "js", "static") for p in c.parent.iterdir()):
            return c
    return candidates[0] if candidates else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--zip", type=Path, default=None, help="已下载的免安装 ZIP 路径")
    ap.add_argument("--latest", action="store_true",
                    help=f"追新:自动取 {UPSTREAM_REPO} 最新 Release(默认固定 v0.5.1,可复现)")
    args = ap.parse_args()

    url = RELEASE_ZIP_URL
    if args.latest and not args.zip:
        url = _latest_release_zip_url()
    tag = "v" + url.rsplit("/v", 1)[-1].split("/", 1)[0] if "/v" in url else "unknown"

    tmp = Path(tempfile.mkdtemp(prefix="dd-fetch-"))
    try:
        if args.zip:
            zip_path = args.zip
        else:
            zip_path = tmp / "portable.zip"
            _download(url, zip_path)
        asar = extract_app_asar(zip_path, tmp)
        if APP_DIR.exists():
            shutil.rmtree(APP_DIR)
        n = extract_asar(asar, APP_DIR)
        entry = find_web_entry(APP_DIR)
        (VENDOR_DIR / "VERSION.json").write_text(json.dumps({
            "repo": UPSTREAM_REPO, "source": url, "version": tag.lstrip("v") if tag != "unknown" else tag,
            "files": n, "entry": entry.relative_to(APP_DIR).as_posix() if entry else None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK:解包 {n} 个文件 → {APP_DIR}")
        print(f"web 入口:{entry}")
        if not entry:
            print("警告:未找到 index.html,请检查解包结果")
            return 1
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
