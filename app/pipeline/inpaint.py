# -*- coding: utf-8 -*-
"""程序化擦除的填充核心(两级流水线)—— 对齐参考项目 utils/inpaint.ts(ecda917)。

1) 补丁式结构填充(主体):把图与蒙版降到低分辨率(洞 ≤96px),从洞边缘向内逐层
   「洋葱填充」——每个待填像素以其邻域已知像素为上下文,在周围全有效区域搜索 SSD
   最小的 5×5 补丁并拷贝其中心像素。线条、墙面、地面等结构会自然延续,
   而不是金字塔平均色的"平滑抹痕"。
2) Push-Pull 金字塔(兜底):补丁填充覆盖不到的极端情况由多尺度加权平均补齐。

合成:低清结构结果放大回原尺寸,仅在蒙版内生效;按洞外环的高频能量自适应补颗粒
(平滑渲染图几乎不加噪,纹理画面则回填颗粒感);蒙版羽化区轻模糊过渡,
羽化区外像素与原图逐字节一致。

pydrama 侧用 Pillow 逐像素实现(参考版是 sharp+手写循环),无 numpy 依赖。
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageFilter


# ── Push-Pull 金字塔 ─────────────────────────────────────────────

def _pyramid_fill(rgb: list, mask: list, w: int, h: int) -> list:
    """金字塔填充:返回与原图同尺寸的 [r,g,b] 列表(蒙版外保持原色)。"""
    levels_w = [w]
    levels_h = [h]
    # 预乘色与权重
    c0 = [0.0] * (w * h * 3)
    a0 = [0.0] * (w * h)
    for i in range(w * h):
        w1 = 1.0 - mask[i] / 255.0
        a0[i] = w1
        if w1 > 0:
            c0[i * 3] = rgb[i * 3] * w1
            c0[i * 3 + 1] = rgb[i * 3 + 1] * w1
            c0[i * 3 + 2] = rgb[i * 3 + 2] * w1
    cs = [c0]
    as_ = [a0]
    while levels_w[-1] > 4 and levels_h[-1] > 4:
        pw, ph = levels_w[-1], levels_h[-1]
        nw, nh = max(1, pw >> 1), max(1, ph >> 1)
        nc = [0.0] * (nw * nh * 3)
        na = [0.0] * (nw * nh)
        pc, pa = cs[-1], as_[-1]
        for y in range(ph):
            ty = min(nh - 1, y >> 1)
            for x in range(pw):
                si = y * pw + x
                wgt = pa[si]
                if wgt <= 0:
                    continue
                di = ty * nw + min(nw - 1, x >> 1)
                nc[di * 3] += pc[si * 3]
                nc[di * 3 + 1] += pc[si * 3 + 1]
                nc[di * 3 + 2] += pc[si * 3 + 2]
                na[di] += wgt
        cs.append(nc)
        as_.append(na)
        levels_w.append(nw)
        levels_h.append(nh)

    # pull:从最粗层往下,洞像素取粗层双线性采样
    for li in range(len(cs) - 2, -1, -1):
        lv_w, lv_h = levels_w[li], levels_h[li]
        lv_c, lv_a = cs[li], as_[li]
        co_c, co_w, co_h = cs[li + 1], levels_w[li + 1], levels_h[li + 1]
        for y in range(lv_h):
            for x in range(lv_w):
                i = y * lv_w + x
                av = lv_a[i]
                if av >= 0.999:
                    lv_c[i * 3] /= av
                    lv_c[i * 3 + 1] /= av
                    lv_c[i * 3 + 2] /= av
                    continue
                fx = min(co_w - 1.0, max(0.0, (x + 0.5) / 2 - 0.5))
                fy = min(co_h - 1.0, max(0.0, (y + 0.5) / 2 - 0.5))
                x0, y0 = int(fx), int(fy)
                x1, y1 = min(co_w - 1, x0 + 1), min(co_h - 1, y0 + 1)
                tx, ty = fx - x0, fy - y0
                for k in range(3):
                    c00 = co_c[(y0 * co_w + x0) * 3 + k]
                    c10 = co_c[(y0 * co_w + x1) * 3 + k]
                    c01 = co_c[(y1 * co_w + x0) * 3 + k]
                    c11 = co_c[(y1 * co_w + x1) * 3 + k]
                    v = (c00 * (1 - tx) * (1 - ty) + c10 * tx * (1 - ty)
                         + c01 * (1 - tx) * ty + c11 * tx * ty)
                    if av <= 0.001:
                        lv_c[i * 3 + k] = v
                    else:
                        lv_c[i * 3 + k] = v * (1 - av) + lv_c[i * 3 + k]
                lv_a[i] = 1.0
    return cs[0]


# ── 补丁式结构填充(低分辨率) ─────────────────────────────────────

def _hole_bbox(mask: list, w: int, h: int, thr: int = 96):
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        base = y * w
        for x in range(w):
            if mask[base + x] >= thr:
                if x < x0:
                    x0 = x
                if x > x1:
                    x1 = x
                if y < y0:
                    y0 = y
                if y > y1:
                    y1 = y
    return None if x1 < 0 else (x0, y0, x1, y1)


def _patch_fill(rgb: list, hole: list, w: int, h: int) -> list:
    """洋葱式补丁填充:就地改写 rgb 中洞内像素,返回 done 标记列表。"""
    r = 2            # 补丁半径(5×5)
    min_ctx = 3      # 最少已知上下文像素
    R = 20           # 搜索窗口半径
    stride = 2       # 搜索步长
    done = [0] * (w * h)

    def known(i: int) -> int:
        return 1 if (hole[i] == 0 or done[i]) else 0

    remaining = sum(1 for v in hole if v)
    guard = 0
    while remaining > 0 and guard < 600:
        guard += 1
        targets = []
        for y in range(h):
            for x in range(w):
                i = y * w + x
                if not hole[i] or done[i]:
                    continue
                ctx = 0
                for dy in (-1, 0, 1):
                    if ctx >= 8:
                        break
                    for dx in (-1, 0, 1):
                        if not dx and not dy:
                            continue
                        nx, ny = x + dx, y + dy
                        if nx < 0 or ny < 0 or nx >= w or ny >= h or known(ny * w + nx):
                            ctx += 1
                if ctx >= min_ctx:
                    targets.append(i)
        if not targets:
            break
        for i in targets:
            if done[i]:
                continue
            x, y = i % w, i // w
            best, best_ssd = -1, float("inf")
            for qy in range(max(0, y - R), min(h - 1, y + R) + 1, stride):
                for qx in range(max(0, x - R), min(w - 1, x + R) + 1, stride):
                    if qy == y and qx == x:
                        continue
                    # 候选补丁必须整体有效(远离洞)
                    valid = True
                    for dy in range(-r, r + 1):
                        ny = qy + dy
                        if ny < 0 or ny >= h:
                            valid = False
                            break
                        row = ny * w
                        for dx in range(-r, r + 1):
                            nx = qx + dx
                            if nx < 0 or nx >= w or hole[row + nx]:
                                valid = False
                                break
                        if not valid:
                            break
                    if not valid:
                        continue
                    # 上下文 SSD(目标补丁内已知/已填位置)
                    ssd = 0.0
                    cnt = 0
                    for dy in range(-r, r + 1):
                        ny = y + dy
                        if ny < 0 or ny >= h:
                            continue
                        for dx in range(-r, r + 1):
                            nx = x + dx
                            if nx < 0 or nx >= w:
                                continue
                            ni = ny * w + nx
                            if not known(ni):
                                continue
                            qi = (qy + dy) * w + (qx + dx)
                            d0 = rgb[ni * 3] - rgb[qi * 3]
                            d1 = rgb[ni * 3 + 1] - rgb[qi * 3 + 1]
                            d2 = rgb[ni * 3 + 2] - rgb[qi * 3 + 2]
                            ssd += d0 * d0 + d1 * d1 + d2 * d2
                            cnt += 1
                    if cnt >= min_ctx and ssd < best_ssd:
                        best_ssd = ssd
                        best = qy * w + qx
            if best >= 0:
                rgb[i * 3] = rgb[best * 3]
                rgb[i * 3 + 1] = rgb[best * 3 + 1]
                rgb[i * 3 + 2] = rgb[best * 3 + 2]
                done[i] = 1
                remaining -= 1
    return done


# ── 主入口 ───────────────────────────────────────────────────────

def _to_rgb_lists(img: Image.Image, mask_img: Image.Image):
    w, h = img.size
    rgb = list(img.convert("RGB").getdata())
    rgb = [v for px in rgb for v in px]
    mask = list(mask_img.convert("RGBA").getChannel if False else mask_img.getchannel("A").getdata())
    return rgb, mask, w, h


def inpaint_masked(orig: bytes | str | Path, mask_png: bytes) -> bytes:
    """对原图中被蒙版(alpha=擦除强度)覆盖的区域做填充,返回 PNG 字节。

    蒙版形状必须在 alpha 通道(参考版同一契约);无 alpha 的灰度蒙版由调用方归一化。
    """
    base = Image.open(io.BytesIO(orig if isinstance(orig, bytes) else Path(orig).read_bytes()))
    W, H = base.size
    if not W or not H:
        raise ValueError("inpaint: 原图尺寸无效")
    mask_img = Image.open(io.BytesIO(mask_png)).convert("RGBA")
    if mask_img.size != (W, H):
        mask_img = mask_img.resize((W, H), Image.NEAREST)
    rgb_flat, m, _, _ = _rgb_lists_from(base, mask_img)

    # ── 1) 低分辨率补丁式结构填充 ──
    textured = None
    bbox = _hole_bbox(m, W, H)
    if bbox:
        hole_w, hole_h = bbox[2] - bbox[0] + 1, bbox[3] - bbox[1] + 1
        scale = max(1, -(-max(hole_w, hole_h) // 96))
        lw, lh = max(8, round(W / scale)), max(8, round(H / scale))
        low_rgb_img = base.convert("RGB").resize((lw, lh), Image.BICUBIC)
        low_mask_img = mask_img.getchannel("A").resize((lw, lh), Image.NEAREST)
        rgb_l = [v for px in low_rgb_img.getdata() for v in px]
        hole_l = [1 if a >= 96 else 0 for a in low_mask_img.getdata()]
        done = _patch_fill(rgb_l, hole_l, lw, lh)
        if any(done):
            # 未被补丁覆盖的洞内像素用同层有效像素平均兜底
            sr = sg = sb = sc = 0
            for i in range(lw * lh):
                if not hole_l[i]:
                    sr += rgb_l[i * 3]
                    sg += rgb_l[i * 3 + 1]
                    sb += rgb_l[i * 3 + 2]
                    sc += 1
            if sc:
                sr, sg, sb = sr / sc, sg / sc, sb / sc
            for i in range(lw * lh):
                if hole_l[i] and not done[i]:
                    rgb_l[i * 3], rgb_l[i * 3 + 1], rgb_l[i * 3 + 2] = sr, sg, sb
            low_full = Image.merge("RGB", [Image.new("L", (lw, lh))] * 0 or _imgs_from_flat(rgb_l, lw, lh))
            textured = [v for px in low_full.resize((W, H), Image.BICUBIC).getdata() for v in px]

    # ── 2) 金字塔兜底 + 合成 ──
    lv0c = _pyramid_fill(rgb_flat, m, W, H)

    # 洞外环的高频能量(平均 |laplacian|)→ 自适应颗粒强度
    lap_sum = lap_n = 0
    for y in range(1, H - 1):
        for x in range(1, W - 1):
            i = y * W + x
            if m[i] >= 200:
                continue
            near = False
            for d in range(-24, 25, 8):
                j = i + d + (W if d > 0 else 0)
                if 0 <= j < W * H and m[j] >= 200:
                    near = True
                    break
            if not near:
                continue
            g = (rgb_flat[i * 3] + rgb_flat[i * 3 + 1] + rgb_flat[i * 3 + 2]) / 3
            gx = (rgb_flat[(i + 1) * 3] + rgb_flat[(i + 1) * 3 + 1] + rgb_flat[(i + 1) * 3 + 2]) / 3
            gy = (rgb_flat[(i + W) * 3] + rgb_flat[(i + W) * 3 + 1] + rgb_flat[(i + W) * 3 + 2]) / 3
            lap_sum += abs(2 * g - gx - gy)
            lap_n += 1
    grain = min(6.0, (lap_sum / lap_n) * 0.3) if lap_n else 0.0

    out = Image.new("RGB", (W, H))
    out_px = out.load()
    # 可复现轻量伪随机(mulberry32)
    state = 0x9e3779b9

    def rand():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = state
        x = ((t ^ (t >> 15)) * (1 | t)) & 0xFFFFFFFF
        x = (x ^ (x + ((x ^ (x >> 7)) * (61 | x)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((x ^ (x >> 14)) & 0xFFFFFFFF) / 4294967296

    for y in range(H):
        for x in range(W):
            i = y * W + x
            if m[i] > 0 and textured:
                r, g, b = textured[i * 3], textured[i * 3 + 1], textured[i * 3 + 2]
                if m[i] >= 200 and grain > 0.05:
                    n = (rand() + rand() + rand()) / 1.5 - 1
                    r, g, b = r + n * grain, g + n * grain, b + n * grain
            else:
                r, g, b = lv0c[i * 3], lv0c[i * 3 + 1], lv0c[i * 3 + 2]
            out_px[x, y] = (max(0, min(255, round(r))), max(0, min(255, round(g))), max(0, min(255, round(b))))

    # 覆盖层:alpha 编码蒙版形状,轻模糊过渡后 over 混合贴回
    overlay = Image.merge("RGBA", (*out.split(), mask_img.getchannel("A"))).filter(ImageFilter.GaussianBlur(2))
    result = base.convert("RGB").convert("RGBA")
    result.alpha_composite(overlay)
    buf = io.BytesIO()
    result.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def _rgb_lists_from(base_img: Image.Image, mask_img: Image.Image):
    rgb = [v for px in base_img.convert("RGB").getdata() for v in px]
    mask = list(mask_img.getchannel("A").getdata())
    return rgb, mask, base_img.size[0], base_img.size[1]


def _imgs_from_flat(flat: list, w: int, h: int) -> list:
    """扁平 [r,g,b,...] → 3 个 L 通道图(RGB merge 用)。"""
    px = [(flat[i * 3], flat[i * 3 + 1], flat[i * 3 + 2]) for i in range(w * h)]
    img = Image.new("RGB", (w, h))
    img.putdata(px)
    return [img.getchannel("R"), img.getchannel("G"), img.getchannel("B")]
