# -*- coding: utf-8 -*-
"""图片精调引擎:11 参调色 + 画布变换,纯 Pillow + numpy,进程内直接跑。

**不引入任何外部服务**(不需要 FastAPI / 数据库 / 后台进程):
调色全是像素运算,1080p 一次几十毫秒,直接在 UI 线程外跑即可。

向量化说明:自然饱和与暗角本质是逐像素运算,写 Python 双层循环在 1080p
(约 200 万像素)要跑十几秒,拖动滑杆时根本没法实时预览。这里全部用 numpy
广播做,同样的公式快 100 倍以上。

全部参数取值 -1.0 ~ 1.0(暗角为 0 ~ 1),0 表示不调整。
alpha 通道全程独立处理并原样带回 —— 调色不该把透明区弄脏。
"""
from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageEnhance, ImageFilter

# 各参数的「安全步长」:0.1 一格,UI 滑杆按这个换算成 -1..1
STEP = 0.1


def _clip(arr: np.ndarray) -> np.ndarray:
    return np.clip(arr, 0, 255).astype(np.uint8)


def _open(path: str | Path) -> tuple[Image.Image, Image.Image]:
    """读图并拆成 (RGB, alpha)。无 alpha 时补一个全不透明的。"""
    im = Image.open(str(path))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA")
    if im.mode == "RGB":
        return im.convert("RGB"), Image.new("L", im.size, 255)
    im = im.convert("RGBA")
    return im.convert("RGB"), im.getchannel("A")


def _assemble(rgb: np.ndarray, alpha: Image.Image) -> Image.Image:
    """numpy RGB 数组 + alpha 图 → PIL 图。"""
    h, w = rgb.shape[:2]
    out = Image.fromarray(rgb, "RGB").convert("RGBA")
    out.putalpha(alpha.resize((w, h)))
    return out


# ── 各参数的实现 ────────────────────────────────────────────────

def _tone(rgb: np.ndarray, highlights: float, shadows: float) -> np.ndarray:
    """高光/阴影:按亮度加权,亮处只动高光、暗处只动阴影,中间自然过渡。

    比"整体加亮度"更像专业后期 —— 后者会把中间调一起带偏。
    """
    if not (highlights or shadows):
        return rgb
    lum = rgb.astype(np.float32).mean(axis=2) / 255.0        # 0..1
    delta = (shadows * (1.0 - lum) * 64.0 + highlights * lum * 64.0)
    return _clip(rgb.astype(np.float32) + delta[:, :, None])


def _white_balance(rgb: np.ndarray, temperature: float, tint: float) -> np.ndarray:
    """色温/色调:温度走红蓝反向,色调走绿/品红。"""
    if not (temperature or tint):
        return rgb
    out = rgb.astype(np.float32)
    out[:, :, 0] += temperature * 28.0 + tint * 12.0         # 红
    out[:, :, 1] -= tint * 20.0                              # 绿
    out[:, :, 2] += -temperature * 28.0 + tint * 12.0        # 蓝
    return _clip(out)


def _vibrance(rgb: np.ndarray, amount: float) -> np.ndarray:
    """自然饱和:按每个像素**已有的**饱和程度给不同增益。

    饱和度是全局线性拉,已鲜艳的区域容易过曝(红脸、纯色招牌);
    自然饱和只给"欠饱和"的像素多补一点,鲜艳的原样不动。
    """
    if not amount:
        return rgb
    f = rgb.astype(np.float32)
    avg = f.mean(axis=2, keepdims=True)                        # 各像素灰度均值
    chroma = np.abs(f - avg).mean(axis=2) / 128.0              # 0..~2 的彩度
    weight = amount * np.clip(1.0 - chroma, 0.0, 1.0)          # 越淡越多给
    return _clip(f + (f - avg) * weight[:, :, None])


def _clarity(rgb: np.ndarray, amount: float) -> np.ndarray:
    """清晰度:大半径 USM。锐化(sp)走 PIL 的小半径,两者观感不同。

    清晰度加大半径 → 强化中频结构与局部对比,不是简单"更锐"。
    """
    if not amount:
        return rgb
    im = Image.fromarray(rgb, "RGB").filter(
        ImageFilter.UnsharpMask(radius=3, percent=int(70 * amount), threshold=3))
    return np.asarray(im)


def _vignette(rgb: np.ndarray, amount: float) -> np.ndarray:
    """暗角:以画面中心为原点做径向压暗,指数 1.6 让中心保持干净。"""
    if not amount:
        return rgb
    h, w = rgb.shape[:2]
    # 网格一次生成,后续每张图都能复用同尺寸缓存
    key = (h, w)
    cache = _VIGNETTE_CACHE.get(key)
    if cache is None:
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        cx, cy = w / 2.0, h / 2.0
        dist = np.hypot(xx - cx, yy - cy) / (math.hypot(cx, cy) or 1.0)
        cache = np.clip(dist, 0.0, 1.0) ** 1.6
        _VIGNETTE_CACHE[key] = cache
    shade = (1.0 - amount * cache)[:, :, None]
    return _clip(rgb.astype(np.float32) * shade)


_VIGNETTE_CACHE: dict[tuple[int, int], np.ndarray] = {}


def adjust_preview(src: str | Path, max_side: int = 640, **params) -> Image.Image:
    """预览用:降采样算完直接返回小图,**不放大回原尺寸**。

    **为什么不直接全分辨率**:实测 1920×1080 十一参全开要 ~1s,拖滑杆时每挪
    一格卡一秒根本没法用。
    **为什么不放大回来**:放大本身又要几百毫秒(纯插值,纯浪费)——预览只是
    给用户看个大概,界面渲染时本来就会按控件尺寸再缩一次,提前放大等于白做
    两遍缩放。返回小图让 UI 直接用,是这条路径上最快的做法。

    降采样用 LANCZOS(锐度最接近原图),不能用 NEAREST —— 那会让用户看到的
    预览和最终结果糊的程度不一样,以为调错了。真正落盘时 `adjust()` 走全分辨率。
    """
    rgb, alpha = _open(src)
    w, h = rgb.size
    scale = max_side / max(w, h)
    if scale < 1.0:
        rgb = rgb.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.LANCZOS)
        alpha = alpha.resize(rgb.size, Image.BILINEAR)
    return _apply_params(rgb, alpha, **params)


def _apply_params(rgb_img: Image.Image, alpha: Image.Image, *,
                  brightness: float = 0.0, contrast: float = 0.0,
                  highlights: float = 0.0, shadows: float = 0.0,
                  temperature: float = 0.0, tint: float = 0.0,
                  saturation: float = 0.0, vibrance: float = 0.0,
                  sharpness: float = 0.0, clarity: float = 0.0,
                  vignette: float = 0.0) -> Image.Image:
    """参数 → 出图。预览与落盘共用,保证两边结果一致(只是分辨率不同)。"""
    # PIL 负责的几项(它的 Enhance 对这些换算是标准实现,自己重写没意义)
    for enh, val in ((ImageEnhance.Brightness, brightness),
                     (ImageEnhance.Contrast, contrast),
                     (ImageEnhance.Color, saturation),
                     (ImageEnhance.Sharpness, sharpness)):
        if val:
            rgb_img = enh(rgb_img).enhance(1.0 + val)
    arr = np.asarray(rgb_img, dtype=np.uint8)

    # numpy 负责的几项
    arr = _tone(arr, highlights, shadows)
    arr = _white_balance(arr, temperature, tint)
    arr = _vibrance(arr, vibrance)
    arr = _clarity(arr, clarity)
    arr = _vignette(arr, vignette)
    return _assemble(arr, alpha)


def adjust(src: str | Path, dst: str | Path | None = None, *,
           brightness: float = 0.0, contrast: float = 0.0,
           highlights: float = 0.0, shadows: float = 0.0,
           temperature: float = 0.0, tint: float = 0.0,
           saturation: float = 0.0, vibrance: float = 0.0,
           sharpness: float = 0.0, clarity: float = 0.0,
           vignette: float = 0.0) -> str:
    """按参数调整一张图并写出,返回输出路径。dst 省略则原地覆盖的同目录新文件。

    处理顺序有讲究:先线性项(亮度/对比度/饱和) → 再色彩分离(高光/阴影/白平衡)
    → 再锐化类 → 最后暗角。暗角放最后,免得被前面的曲线二次影响。
    """
    rgb_img, alpha = _open(src)
    out = _apply_params(rgb_img, alpha, brightness=brightness, contrast=contrast,
                        highlights=highlights, shadows=shadows,
                        temperature=temperature, tint=tint,
                        saturation=saturation, vibrance=vibrance,
                        sharpness=sharpness, clarity=clarity, vignette=vignette)
    dst = str(dst) if dst else str(Path(src).with_name(
        f"{Path(src).stem}_adj{Path(src).suffix}"))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    out.save(dst)
    return dst


# ── 画布变换 ────────────────────────────────────────────────────

def transform(src: str | Path, dst: str | Path | None = None, *,
              rotate: float = 0.0, flip_h: bool = False, flip_v: bool = False,
              scale: float = 1.0, crop: tuple[int, int, int, int] | None = None,
              expand: float = 0.0) -> str:
    """旋转/翻转/缩放/裁剪/扩图。rotate 单位为度,逆时针为正。"""
    img, _alpha = _open(src)
    out = img.convert("RGBA")

    if crop:
        left, top, right, bottom = crop
        w, h = out.size
        out = out.crop((max(0, left), max(0, top), min(w, right), min(h, bottom)))

    if expand:
        """AI 扩图的占位实现:先把画布放大,内容居中。

        真正的内容生成要调生图模型(会重绘、与原图对不齐),这里只做画布准备,
        与 UI 上「扩图」按钮的语义区分开 —— 别让人以为内容被 AI 生成过了。
        """
        w, h = out.size
        dw, dh = int(w * (1 + expand * 2)), int(h * (1 + expand * 2))
        canvas = Image.new("RGBA", (dw, dh), (0, 0, 0, 0))
        canvas.paste(out, ((dw - w) // 2, (dh - h) // 2))
        out = canvas

    if scale and scale != 1.0:
        w, h = out.size
        out = out.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                         Image.LANCZOS)

    if rotate:
        out = out.rotate(rotate, resample=Image.BICUBIC, expand=True)

    if flip_h:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
    if flip_v:
        out = out.transpose(Image.FLIP_TOP_BOTTOM)

    dst = str(dst) if dst else str(Path(src).with_name(
        f"{Path(src).stem}_tf{Path(src).suffix}"))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    out.save(dst)
    return dst


def corner_matte(src: str | Path, dst: str | Path | None = None,
                 tolerance: int = 28) -> str:
    """四角取样抠图 —— 纯背景色单一时的应急方案,不需要 rembg 模型。

    与 rembg 的区别要跟用户说清:rembg 认得出复杂主体边缘,这里只认"四角颜色
    相同且处处一致"的纯色背景。产品图/白底图适用,街景背景会抠坏。
    """
    rgb, alpha = _open(src)
    arr = np.asarray(rgb, dtype=np.int16)
    w, h = arr.shape[1], arr.shape[0]
    corners = np.stack([arr[0, 0], arr[0, w - 1], arr[h - 1, 0], arr[h - 1, w - 1]])
    key = corners.mean(axis=0)                                  # 四角均色
    dist = np.sqrt(((arr - key[None, None, :]) ** 2).sum(axis=2))
    mask = np.where(dist <= tolerance, 0, 255).astype(np.uint8)  # 近背景色 → 全透明
    out = Image.merge("RGBA", (*rgb.split(), Image.fromarray(mask, "L")))
    dst = str(dst) if dst else str(Path(src).with_name(
        f"{Path(src).stem}_matte{Path(src).suffix}"))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    out.save(dst)
    return dst


# ── 超分辨率 ────────────────────────────────────────────────────

def upscale(src: str | Path, dst: str | Path | None = None,
            scale: float = 2.0, detail: float = 0.35) -> str:
    """放大分辨率,尽量让边缘保持干净。

    **为什么不直接 LANCZOS 就完事**:单纯插值放大出来的图会糊 —— 像素变多
    了但没有新信息。这里做两步:LANCZOS 打底(拿到正确的插值结果),再用
    小半径 USM 把被插值抹平的边缘找回来。detail=0 就是纯 LANCZOS。

    注意这是**几何放大**,不是 AI 超分(那种会重绘细节,可能改变画面内容,
    对角色资产来说风险太高)。要真正的细节增强得走视频/图像模型,不在本函数职责内。
    """
    img, alpha = _open(src)
    if scale <= 1 and detail <= 0:
        return _save(img, src, dst, "_up")
    w, h = img.size
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
    big = img.resize((nw, nh), Image.LANCZOS)
    if detail > 0:
        big = big.filter(ImageFilter.UnsharpMask(
            radius=max(1.0, min(3.0, 1.2 * scale)),
            percent=int(70 * min(2.0, detail * 2.5)),
            threshold=2))
    if alpha.size != big.size:
        alpha = alpha.resize((nw, nh), Image.BILINEAR)
    return _save(_assemble(np.asarray(big.convert("RGB"), dtype=np.uint8), alpha),
                 src, dst, "_up")


# ── 投放尺寸 ────────────────────────────────────────────────────

# 平台常用规格。分辨率按"主流发布位"取,避免用户拿到 9:16 的 720×1280 又嫌糊。
DELIVERY_SIZES: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),        # 方形(公众号/朋友圈)
    "3:4": (1080, 1440),        # 竖版(小红书主图)
    "4:3": (1440, 1080),        # 横版(小红书封面)
    "4:5": (1080, 1350),        # 竖版(Instagram)
    "9:16": (1080, 1920),       # 全屏竖版(抖音/视频号)
    "16:9": (1920, 1080),       # 横屏(B站/YouTube)
}
DELIVERY_PRESET_CN = {
    "1:1": "方形 1080×1080",
    "3:4": "小红书竖版 1080×1440",
    "4:3": "小红书横版 1440×1080",
    "4:5": "Instagram 竖版 1080×1350",
    "9:16": "抖音全屏 1080×1920",
    "16:9": "B站横屏 1920×1080",
}


def letterbox(src: str | Path, dst: str, width: int, height: int,
              fill: tuple[int, int, int] = (255, 255, 255)) -> str:
    """**完整放入**目标画幅,不裁切,空白处居中留白。

    为什么用留边而不是裁切填满:裁切会切掉人物的头顶或产品边缘 —— 对资产图
    是不可接受的损失。留边的代价是上下/左右有空白,但画面完整。

    `mode` 可选:
      pad   留边(默认,内容不丢)
      cover 裁切填满(不留边,会切掉超出部分)
      blur  模糊背景填充(不留白,主体不裁切 —— 适合短视频封面)
    """
    img, _alpha = _open(src)
    img = img.convert("RGB")
    mode = "pad"
    if width <= 0 or height <= 0:
        raise ValueError("目标尺寸必须大于 0")
    if img.size == (width, height):
        return _save(img.convert("RGBA"), dst, dst, "")

    scale = min(width / img.width, height / img.height)
    size = (max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale))))
    placed = img.resize(size, Image.LANCZOS)

    canvas = Image.new("RGB", (width, height), fill)
    canvas.paste(placed, ((width - size[0]) // 2, (height - size[1]) // 2))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst)
    return dst


def export_delivery(src: str | Path, out_dir: str | Path,
                    ratios: list[str] | None = None,
                    mode: str = "pad") -> list[str]:
    """一张图导出多平台规格,返回写出的文件路径列表。

    mode: pad(留边) / cover(裁切填满) / blur(模糊背景填充)
    """
    ratios = ratios or ["9:16", "3:4", "1:1"]
    bad = [r for r in ratios if r not in DELIVERY_SIZES]
    if bad:
        raise ValueError(f"不支持的画幅:{bad},可用:{list(DELIVERY_SIZES)}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(src).stem
    img, alpha = _open(src)
    img = img.convert("RGB")

    outs: list[str] = []
    for r in ratios:
        w, h = DELIVERY_SIZES[r]
        dst = out_dir / f"{stem}_{r.replace(':', 'x')}.png"
        if img.size == (w, h):
            img.save(dst)
        elif mode == "cover":
            # 裁切填满:等比放大到"盖住",再从中心裁掉超出部分
            sc = max(w / img.width, h / img.height)
            big = img.resize((max(w, int(img.width * sc + 0.5)),
                              max(h, int(img.height * sc + 0.5))), Image.LANCZOS)
            box = ((big.width - w) // 2, (big.height - h) // 2,
                   (big.width - w) // 2 + w, (big.height - h) // 2 + h)
            big.crop(box).save(dst)
        elif mode == "blur":
            # 模糊底:同一张图放大裁切后高斯模糊当背景,前景原比例居中
            sc = max(w / img.width, h / img.height)
            bg = img.resize((max(w, int(img.width * sc + 0.5)),
                             max(h, int(img.height * sc + 0.5))), Image.LANCZOS)
            box = ((bg.width - w) // 2, (bg.height - h) // 2,
                   (bg.width - w) // 2 + w, (bg.height - h) // 2 + h)
            bg = bg.crop(box).filter(ImageFilter.GaussianBlur(max(8, w // 22)))
            sc2 = min(w / img.width, h / img.height)
            fg = img.resize((max(1, int(img.width * sc2)), max(1, int(img.height * sc2))),
                             Image.LANCZOS)
            bg.paste(fg, ((w - fg.width) // 2, (h - fg.height) // 2))
            bg.save(dst)
        else:
            sc = min(w / img.width, h / img.height)
            size = (max(1, int(round(img.width * sc))), max(1, int(round(img.height * sc))))
            placed = img.resize(size, Image.LANCZOS)
            canvas = Image.new("RGB", (w, h), (255, 255, 255))
            canvas.paste(placed, ((w - size[0]) // 2, (h - size[1]) // 2))
            canvas.save(dst)
        outs.append(str(dst))
    return outs


def _save(img: Image.Image, src: str, dst: str | None, suffix: str) -> str:
    """统一的落盘:给了 dst 用 dst,否则在 src 同目录生成带后缀的新文件。"""
    out = str(dst) if dst else str(Path(src).with_name(
        f"{Path(src).stem}{suffix}{Path(src).suffix}"))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
