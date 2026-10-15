# -*- coding: utf-8 -*-
"""资产图去重影:白底单人立绘的确定性后处理。

**为什么需要它(实测)**:Agnes Image 在「参考图 + 要求单主体」这个组合下有稳定的
重影倾向 —— 生成出来的全身像两侧会各带一个半透明人影,而且这些重影会**原样**被
带进每一张分镜成品(只传 1 张参考图也一样,证明是照抄参考图而非多图融合)。

**为什么负面词压不住**:负面词压制的是「凭空生成」,而重影是从参考图**继承**的
构图惯性。用户上传的原照背景是大面积红橙暖色光晕,模型读成「旁边还有发光的东西」。
已验证:补齐短剧侧那条张嘴/极端表情负面词(open mouth, screaming…)后重影不减反增。

所以走像素后处理:白底单人立绘的连通域非常干净,主体面积远大于重影,
保留最大连通域即可。不花额度、不依赖模型表现、结果确定。
"""
from __future__ import annotations

from pathlib import Path


def _foreground_mask(im, thresh: int = 34):
    """二值化:与「近白背景」差异足够大的像素算前景。"""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype("int16")
    # 背景取四角中位色,比写死纯白更稳(资产图常有轻微灰底/渐变)
    corners = np.concatenate([a[:6, :6].reshape(-1, 3), a[:6, -6:].reshape(-1, 3),
                              a[-6:, :6].reshape(-1, 3), a[-6:, -6:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)
    diff = np.abs(a - bg).max(axis=2)
    return diff > thresh, bg


def _largest_component(mask):
    """最大连通域(PIL 无 scipy 时的纯 numpy BFS,资产图尺寸下够快)。"""
    import numpy as np
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    best, best_size = None, 0
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or seen[sy, sx]:
                continue
            stack = [(sy, sx)]
            seen[sy, sx] = True
            comp = []
            while stack:
                y, x = stack.pop()
                comp.append((y, x))
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if len(comp) > best_size:
                best_size, best = len(comp), comp
    return best, best_size


def strip_ghosting(src: str | Path, dst: str | Path | None = None,
                   pad_ratio: float = 0.06) -> tuple[Path, dict]:
    """按**列前景剖面**裁掉白底单人立绘两侧的重影,返回 (输出路径, 统计信息)。

    **为什么不用连通域**:重影是半透明渐变,边缘与主体区域**粘连**,像素级连通
    判定会把三者当成一个连通域(实测裁完重影原封不动)。列投影法更合适 ——
    主体占据画面中部一段连续的宽列,重影是两侧较窄的列带。

    pad_ratio 是主体两侧留白比例。找不到主体或前景占比异常(不是白底单人立绘)时
    原样返回,不做破坏性处理。
    """
    import numpy as np
    from PIL import Image, ImageDraw
    src = Path(str(src))
    dst = Path(str(dst)) if dst else src
    info = {"applied": False, "reason": ""}
    try:
        im = Image.open(src).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        info["reason"] = f"读图失败: {exc}"
        return src, info
    w, h = im.size
    mask, bg = _foreground_mask(im)
    total = int(mask.sum())
    if total < w * h * 0.005:
        info["reason"] = "前景太少,不像白底立绘"
        return src, info
    cols = mask.sum(axis=0)
    peak = int(cols.max())
    if peak <= 0:
        info["reason"] = "无前景列"
        return src, info
    # 主体列:前景数 ≥ 峰值 35% 的连续区段(人体躯干那段最宽)
    strong = cols >= peak * 0.35
    segs, start = [], None
    for i, v in enumerate(list(strong) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            segs.append((start, i - 1))
            start = None
    if not segs:
        info["reason"] = "找不到主体列区段"
        return src, info
    # 取最宽的一段为主体;若有多段宽度接近(>60%),说明是并排多人,别乱裁
    segs.sort(key=lambda s: s[1] - s[0], reverse=True)
    sx0, sx1 = segs[0]
    if len(segs) > 1 and (segs[1][1] - segs[1][0]) > (sx1 - sx0) * 0.6:
        info["reason"] = f"检出 {len(segs)} 段等宽主体,疑似并排多人"
        return src, info
    rows = np.where(mask[:, sx0:sx1 + 1].any(axis=1))[0]
    y0, y1 = (int(rows[0]), int(rows[-1])) if len(rows) else (0, h - 1)
    pad = int(max(sx1 - sx0, y1 - y0) * pad_ratio)
    box = (max(0, sx0 - pad), max(0, y0 - pad),
           min(w, sx1 + pad + 1), min(h, y1 + pad + 1))
    # 主体两侧(左界外 / 右界外)整片涂背景色;主体区内只保留与主体列相连的部分
    clean = im.copy()
    draw = ImageDraw.Draw(clean)
    bgc = tuple(int(v) for v in bg)
    draw.rectangle((0, 0, w - 1, h - 1), fill=bgc)
    clean.paste(im.crop((sx0, y0, sx1 + 1, y1 + 1)), (sx0, y0))
    clean.crop(box).save(dst)
    info.update(applied=True, box=box, segs=len(segs), fg=total)
    return dst, info
