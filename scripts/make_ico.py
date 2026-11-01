# -*- coding: utf-8 -*-
"""从 app/assets/logo-512.png 生成 Windows 用的 .ico(多尺寸)。

用法:python -m scripts.make_ico
输出:app/assets/logo.ico

为什么需要:.ico 是 Windows exe 图标的唯一格式,spec 里要引用它。
仓库只存 png(图标编辑/网页 favicon 用),.ico 由脚本生成 —— 但生成后
**要提交进仓库**(CI 的 Windows 构建 job 需要它,且仓库本就是 public,
16KB 的图标没有保密问题)。
"""
from __future__ import annotations

from pathlib import Path

SRC = Path("app/assets/logo-512.png")
DST = Path("app/assets/logo.ico")
# Windows exe 图标常用尺寸:16(任务栏)/24/32(列表)/48(资源管理器)/64/128/256
SIZES = [16, 24, 32, 48, 64, 128, 256]


def main() -> int:
    if not SRC.is_file():
        print(f"!! 找不到 {SRC}")
        return 1
    from PIL import Image

    img = Image.open(SRC).convert("RGBA")
    # ico 需要正方形:非正方形时居中裁剪(logo-512 本身是正方形)
    w, h = img.size
    if w != h:
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2,
                        (w - side) // 2 + side, (h - side) // 2 + side))
    img.save(DST, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"已生成 {DST} ({DST.stat().st_size} 字节),尺寸 {SIZES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
