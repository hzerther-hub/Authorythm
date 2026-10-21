# -*- coding: utf-8 -*-
"""生成物文件的删除(分镜 / 漫画两条「重拆」链路共用)。

为什么单独一个模块:`storyboard.py` 反向复用了 `comic.py:_style_for`
(AGENTS.md「依赖方向单向」里明说的那个有意例外),所以 `comic.py` 再
import `storyboard.py` 就成环 —— 共享的文件删除逻辑只能落在第三方模块里。

边界检查在这里做一次,两条链路共用同一套规则:
    - 只删 static 目录内的文件(url 存在库里,理论上可被外部写入,
      不做边界检查就可能删到项目外的文件);
    - 同一文件被多行引用时只删一次。
"""
from __future__ import annotations

from ..core import config


def purge_media_files(urls) -> tuple[int, int]:
    """删掉 media url 指向的本地文件;返回(删掉几个文件, 释放多少字节)。"""
    root = config.STATIC_DIR.resolve()
    removed = 0
    freed = 0
    seen: set[str] = set()
    for u in urls:
        u = (u or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        try:
            p = config.media_url_to_path(u).resolve()
            p.relative_to(root)          # 越界 → ValueError → 跳过
        except (ValueError, OSError):
            continue
        try:
            if p.is_file():
                freed += p.stat().st_size
                p.unlink()
                removed += 1
        except OSError:
            continue
    return removed, freed
