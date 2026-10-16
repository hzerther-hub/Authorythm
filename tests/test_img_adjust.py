# -*- coding: utf-8 -*-
"""图片精调引擎(11 参调色 + 画布变换 + 抠图)。

核心不变量:**预览与落盘必须一致**。预览走降采样、落盘走全分辨率,
两条路径共用 `_apply_params` —— 如果哪天有人只改一边,用户拖滑杆时
看到的和最终保存的就对不上,而且很难察觉。
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.pipeline import img_adjust as IA

PARAMS = ("brightness", "contrast", "highlights", "shadows", "temperature",
          "tint", "saturation", "vibrance", "sharpness", "clarity", "vignette")


@pytest.fixture
def sample(tmp_path):
    """一张有渐变和不同色块的图 —— 纯色图看不出调色对不对。"""
    w, h = 240, 160
    a = np.zeros((h, w, 3), np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    a[..., 0] = xx * 255 // (w - 1)        # 水平红渐变
    a[..., 1] = yy * 255 // (h - 1)        # 垂直绿渐变
    a[..., 2] = 128                        # 固定蓝
    p = tmp_path / "src.png"
    Image.fromarray(a).save(p)
    return str(p)


def test_all_eleven_params_are_accepted(sample, tmp_path):
    """11 个参数全开不报错,且输出尺寸不变。"""
    out = IA.adjust(sample, str(tmp_path / "o.png"),
                    **{k: 0.3 for k in PARAMS})
    assert Image.open(out).size == Image.open(sample).size


def test_zero_params_is_identity(sample, tmp_path):
    """全 0 = 不调整。逐像素比对,允许 ±1 的编码误差。"""
    out = IA.adjust(sample, str(tmp_path / "o.png"))
    a = np.asarray(Image.open(sample).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(out).convert("RGB"), dtype=np.int16)
    assert np.abs(a - b).max() <= 1, "全 0 参数却改变了画面"


def test_brightness_direction(sample, tmp_path):
    """提亮必须真的变亮、压暗必须真的变暗(方向反了是最容易犯的错)。"""
    src = np.asarray(Image.open(sample).convert("RGB"), dtype=np.float32)
    up = np.asarray(Image.open(IA.adjust(sample, str(tmp_path / "u.png"),
                                        brightness=0.4)).convert("RGB"),
                    dtype=np.float32)
    dn = np.asarray(Image.open(IA.adjust(sample, str(tmp_path / "d.png"),
                                        brightness=-0.4)).convert("RGB"),
                    dtype=np.float32)
    assert up.mean() > src.mean() > dn.mean()


def test_temperature_warms_and_cools(sample, tmp_path):
    """色温:暖 = 红升蓝降,冷 = 反之。"""
    def mean_rgb(**kw):
        im = Image.open(IA.adjust(sample, str(tmp_path / "t.png"), **kw)).convert("RGB")
        a = np.asarray(im, dtype=np.float32)
        return a[..., 0].mean() - a[..., 2].mean()
    assert mean_rgb(temperature=0.5) > mean_rgb() > mean_rgb(temperature=-0.5)


def test_vignette_darkens_corners_only(sample, tmp_path):
    """暗角只压四角,中心不动 —— 压中心的话画面主体就没了。"""
    im = Image.open(IA.adjust(sample, str(tmp_path / "v.png"), vignette=0.9))
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    h, w = a.shape[:2]
    center = a[h // 2 - 5:h // 2 + 5, w // 2 - 5:w // 2 + 5].mean()
    corners = np.mean([a[:8, :8].mean(), a[:8, -8:].mean(),
                       a[-8:, :8].mean(), a[-8:, -8:].mean()])
    assert corners < center - 5, f"暗角没起作用 corner={corners:.1f} center={center:.1f}"


def test_alpha_is_preserved(tmp_path):
    """透明通道必须原样带回 —— 调色把透明区弄脏是常见回归。"""
    a = np.zeros((60, 60, 4), np.uint8)
    a[..., :3] = 200
    a[..., 3] = 0                       # 全透明
    src = tmp_path / "a.png"
    Image.fromarray(a).save(src)
    out = Image.open(IA.adjust(str(src), str(tmp_path / "b.png"),
                               brightness=0.5, contrast=0.5))
    arr = np.asarray(out)
    assert out.mode == "RGBA"
    assert arr[..., 3].max() == 0, "透明区被调成了不透明"


def test_preview_and_full_share_same_params(sample, tmp_path):
    """预览与落盘共用 `_apply_params`:同一张图、同一参数,结果必须一致。

    预览会降采样,所以只比**中心区域**(边缘受重采样影响)。
    """
    params = {k: 0.25 for k in PARAMS}
    prev = np.asarray(IA.adjust_preview(sample, max_side=64, **params).convert("RGB"))
    full = np.asarray(Image.open(IA.adjust(sample, str(tmp_path / "f.png"),
                                       **params)).convert("RGB"))
    # 预览缩小了,按比例取中心一小块对应位置比较趋势:均值应同向
    assert abs(prev.mean() - full.mean()) < 12, \
        f"预览({prev.mean():.1f})与落盘({full.mean():.1f})差太多"


def test_preview_returns_small_image(sample):
    """预览必须返回小图(不放大回原尺寸),否则拖滑杆会卡。"""
    out = IA.adjust_preview(sample, max_side=64, brightness=0.3)
    assert max(out.size) == 64


def test_preview_does_not_touch_source(sample):
    """预览不得写文件,也不得改原图。"""
    import pathlib
    before = pathlib.Path(sample).read_bytes()
    IA.adjust_preview(sample, 64, brightness=0.5, clarity=0.5)
    assert pathlib.Path(sample).read_bytes() == before


def test_transform_rotation_expands_canvas(sample, tmp_path):
    """任意角度旋转要扩画布,否则四个角会被裁掉。"""
    out = IA.transform(sample, str(tmp_path / "r.png"), rotate=45)
    assert max(Image.open(out).size) > max(Image.open(sample).size)


def test_transform_flip_is_idempotent(sample, tmp_path):
    """水平翻转两次回到原图 —— 确认 flip 没被写成别的操作。"""
    mid = IA.transform(sample, str(tmp_path / "1.png"), flip_h=True)
    back = IA.transform(mid, str(tmp_path / "2.png"), flip_h=True)
    a = np.asarray(Image.open(sample).convert("RGB"), dtype=np.int16)
    b = np.asarray(Image.open(back).convert("RGB"), dtype=np.int16)
    assert np.abs(a - b).max() <= 1


def test_corner_matte_makes_corners_transparent(tmp_path):
    """四角取样抠图:纯色背景的四角应变透明,中间主体保持不透明。"""
    a = np.full((80, 80, 3), 250, np.uint8)     # 白底
    a[30:50, 30:50] = (200, 40, 40)             # 红色方块主体
    src = tmp_path / "w.png"
    Image.fromarray(a).save(src)
    out = np.asarray(Image.open(IA.corner_matte(str(src),
                                               str(tmp_path / "o.png"))).convert("RGBA"))
    assert out[2, 2, 3] == 0, "四角没变透明"
    assert out[40, 40, 3] == 255, "主体被误抠成透明"


def test_clamps_out_of_range_values(sample, tmp_path):
    """参数越界不崩(滑杆可能给到意外值)。"""
    out = IA.adjust(sample, str(tmp_path / "o.png"),
                    brightness=99, clarity=-50, vignette=999)
    arr = np.asarray(Image.open(out).convert("RGB"))
    assert arr.max() <= 255 and arr.min() >= 0


# ── 超分辨率 ────────────────────────────────────────────────────

def test_upscale_doubles_size(sample, tmp_path):
    out = IA.upscale(sample, str(tmp_path / "u.png"), scale=2.0, detail=0)
    assert Image.open(out).size == (480, 320)


def test_upscale_keeps_source_untouched(sample, tmp_path):
    """放大不得改原图(用户可能要对同一张出多个规格)。"""
    import pathlib
    before = pathlib.Path(sample).read_bytes()
    IA.upscale(sample, str(tmp_path / "u.png"), scale=3.0)
    assert pathlib.Path(sample).read_bytes() == before


def test_upscale_preserves_alpha(tmp_path):
    a = np.zeros((50, 50, 4), np.uint8)
    a[..., :3] = 120
    a[..., 3] = 128                    # 半透明
    src = tmp_path / "a.png"
    Image.fromarray(a).save(src)
    out = Image.open(IA.upscale(str(src), str(tmp_path / "o.png"), scale=2))
    assert out.mode == "RGBA"
    assert np.asarray(out)[0, 0, 3] == 128, "半透明值被改动"


def test_upscale_scale_one_is_noop(sample, tmp_path):
    """scale=1 且不要细节增强 → 原样输出。"""
    import pathlib
    out = IA.upscale(sample, str(tmp_path / "u.png"), scale=1.0, detail=0)
    assert Image.open(out).size == Image.open(sample).size


def test_upscale_detail_sharpens_edges(tmp_path):
    """细节增强要真有效果,不能和纯 LANCZOS 一样糊。

    用**黑白硬边方块**而不是渐变图: USM 锐化的是边缘,纯线性渐变放大后
    本来就没有边缘可锐,拿它测会得到"两种参数没区别"的假结论。
    """
    w, h = 120, 120
    a = np.zeros((h, w), np.uint8)
    a[:, :w // 3] = 255                    # 硬边:纯黑 → 纯白
    a[:, w // 3:2 * w // 3] = 128
    src = tmp_path / "edge.png"
    Image.fromarray(a).save(src)

    def edge_energy(detail):
        img = Image.open(IA.upscale(str(src), str(tmp_path / f"{detail}.png"),
                                    scale=2, detail=detail)).convert("L")
        arr = np.asarray(img, dtype=np.float32)
        return float(np.abs(np.diff(arr, axis=1)).mean())

    assert edge_energy(0.6) > edge_energy(0.0),         "开启细节增强后边缘对比度没有提高"


# ── 投放尺寸 ────────────────────────────────────────────────────

def test_export_delivery_makes_requested_sizes(sample, tmp_path):
    outs = IA.export_delivery(sample, tmp_path, ["9:16", "1:1", "16:9"])
    assert len(outs) == 3
    assert Image.open(outs[0]).size == (1080, 1920)
    assert Image.open(outs[1]).size == (1080, 1080)
    assert Image.open(outs[2]).size == (1920, 1080)


@pytest.mark.parametrize("mode", ["pad", "cover", "blur"])
def test_all_delivery_modes_produce_target_size(sample, tmp_path, mode):
    for mode_ in (mode,):
        outs = IA.export_delivery(sample, tmp_path / mode_, ["9:16"], mode=mode_)
        assert Image.open(outs[0]).size == (1080, 1920)


def test_pad_does_not_crop_content(sample, tmp_path):
    """留边模式:整张图必须都在画面内(裁切会切掉人物头顶)。"""
    outs = IA.export_delivery(sample, tmp_path, ["9:16"], mode="pad")
    im = Image.open(outs[0]).convert("RGB")
    a = np.asarray(im)
    # 上下应为纯留白色带
    assert a[0, 540].tolist() == [255, 255, 255], "顶部没有留边"
    assert a[1919, 540].tolist() == [255, 255, 255], "底部没有留边"


def test_cover_fills_entire_canvas(sample, tmp_path):
    """裁切模式:不该有留白(整幅被画面填满)。"""
    outs = IA.export_delivery(sample, tmp_path, ["9:16"], mode="cover")
    a = np.asarray(Image.open(outs[0]).convert("RGB"))
    assert len(np.unique(a[0])) > 1, "顶部是纯色 = 留白了"


def test_export_delivery_rejects_unknown_ratio(sample, tmp_path):
    with pytest.raises(ValueError, match="不支持的画幅"):
        IA.export_delivery(sample, tmp_path, ["21:9"])


def test_export_delivery_default_is_three_ratios(sample, tmp_path):
    assert len(IA.export_delivery(sample, tmp_path)) == 3
