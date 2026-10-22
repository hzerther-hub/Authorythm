# -*- coding: utf-8 -*-
"""手动换画风:把一张已有的资产图转成项目画风(或另一个指定画风)。

**为什么做成"手动"而不是自动**:实测模型在图生图时会持续往画面里加东西 ——
真人照片转漫画,连着四次分别加了 8 / 12 / 2 个人和一个骷髅骷髅场景;
场景图转漫画也会凭空加一个店小二。这些都是画风词汇本身带的倾向
(美式漫画 → 戏剧化场面),提示词压不住。所以这里**只提供能力,不做流水线**:
用户点一下、看结果、满意才替换,不满意原图还在。

**必须用能发参考图的 provider**:`image_client.REFERENCE_CAPABLE_PROVIDERS`
之外的(qwen-image / volcengine)请求体里没有图像字段,传了也被网关丢掉,
结果是凭空生成一张无关的图 —— 看起来"成功了",实际和原图没关系。
"""
from __future__ import annotations

import pathlib
import uuid

from pathlib import Path

from ..core import config, db

# 画风里的 "dramatic" 系词汇在**图生图**场景会被模型当成"把场面戏剧化"的指令,
# 实测是凭空加人的主因。转换时剥掉,渲染技法部分保留。
_DRAMA_WORDS = ("dramatic spotlight lighting", "dynamic cinematic composition",
                "dramatic contrast", "dynamic saturated colors")

_TABLES = {"characters": "角色", "scenes": "场景", "props": "道具"}


def tame_style_prompt(style: str) -> str:
    """剥掉诱导加戏的戏剧性词汇。"""
    import re as _re
    s = style or ""
    for w in _DRAMA_WORDS:
        s = s.replace(w + ",", "").replace(w, "")
    return _re.sub(r"\s+", " ", s).strip()


def build_prompt(kind: str, style: str) -> str:
    """按资产类型构造转换提示词。

    人物要锁五官(崩了就认不出是谁);场景/道具没有"身份"要保,
    锁的是布局与物件 —— 但两者都要防加戏。
    """
    who_lock = ("【必须保持】人物身份、性别与年龄、五官与脸型、发型发色、妆容、"
                "姿态神情、服装款式与材质类别、首饰配饰。\n"
                ) if kind == "characters" else (
        "【必须保持】空间布局、视角与景别、家具与器物的位置和数量、墙面地面材质、"
        "悬挂物位置、光源方向。\n")
    no_people = "" if kind == "characters" else \
        "不得出现人物、人体、剪影、倒影中的人;不得添加参考图中不存在的家具、器物、装饰或文字。\n"
    return (
        f"把参考图转换为 {style}\n"
        "这是**风格替换**,不是重新创作。画面必须与参考图一一对应:同样的构图、"
        "同样的取景范围、同样的主体位置与姿态。\n"
        "【只允许改变】渲染技法与笔触、材质表现方式、光影模型、色彩处理。\n"
        "【绝对禁止】不得增加参考图中不存在的任何元素;不得移动或删除已有物件;"
        "不得改变构图与取景范围。\n"
        f"{no_people}"
        "不得替换或重设计主体;不得改变性别、年龄、五官与服装款式。\n"
        f"{who_lock}"
        "输出:同一张画面,仅换成上述画风。"
    )


def convert(row_id: int, table: str, style_value: str = "",
            config_id: int | None = None) -> str:
    """转换一张资产图,返回**新图的本地路径**(不落库,由调用方决定要不要替换)。

    不直接写回 image_url —— 用户要先看到效果再决定,手动流程不该替他做主。
    """
    from ..ai import image_client

    if table not in _TABLES:
        raise RuntimeError(f"不支持的资产表:{table}")
    row = db.q1(f"SELECT * FROM {table} WHERE id=?", (row_id,))
    if not row:
        raise RuntimeError(f"{_TABLES[table]}不存在")
    cur = (row["image_url"] or "").strip()
    if not cur:
        raise RuntimeError(f"该{_TABLES[table]}还没有形象图,先「上传」或「文绘」出一张")

    src = (config.media_url_to_path(cur) if cur.startswith(("/static/", "static/"))
           else pathlib.Path(cur))
    if not pathlib.Path(src).exists():
        raise RuntimeError("形象图文件已丢失,重新上传或重绘一张")

    # 必须走能发参考图的 provider,否则等于凭空生成
    cfg = image_client.registry.check_ready("image", config_id)
    if not image_client.supports_reference_images(cfg["provider"]):
        raise RuntimeError(
            f"当前图像服务「{cfg['provider']}」不接收参考图,换风格会生成一张"
            f"与原图无关的新图。请在顶栏把图像模型切成 agnes / local / comfyui "
            f"/ sdwebui / fooocus 之一再试。")

    # 显式按原图尺寸出图:不传 size 模型会自己定画幅,构图必然被重排
    from PIL import Image
    try:
        with Image.open(src) as im:
            w, h = im.size
        size = f"{w}x{h}" if w and h else None
    except Exception:  # noqa: BLE001
        size = None

    style = tame_style_prompt(db.style_prompt(style_value or "3d"))
    out_name = f"styleconv_{table}_{row_id}_{uuid.uuid4().hex[:8]}.png"
    out, _prov = image_client.generate_image(
        build_prompt(table, style), out_name=out_name, config_id=cfg["id"],
        reference_images=[str(src)],
        people=1 if table == "characters" else 0,   # 场景/道具 people=0 → 守卫措辞切到"无人物"
        size=size)
    return str(out)


def convert_path(src: str | Path, style_value: str,
                 config_id: int | None = None, kind: str = "scenes") -> str:
    """把一张任意本地图转成指定画风,返回新图路径。**不落库**。

    与 `convert()` 的区别:那个针对资产表的一行(id + table),这个只看路径。
    搜图弹窗里的「换画风」用它 —— 搜来的图还不是资产,先转再说。

    kind 只影响提示词里的锁项(人物锁五官/场景道具锁布局),默认按场景处理。
    """
    from ..ai import image_client

    src = pathlib.Path(src)
    if not src.exists():
        raise RuntimeError("原图文件不存在")

    cfg = image_client.registry.check_ready("image", config_id)
    if not image_client.supports_reference_images(cfg["provider"]):
        raise RuntimeError(
            f"当前图像服务「{cfg['provider']}」不接收参考图,换画风会生成一张"
            f"与原图无关的新图。请切到 agnes / local / comfyui / sdwebui / fooocus。")

    # 显式按原图尺寸出图:不传 size 模型自定画幅,构图必然被重排
    size = None
    try:
        from PIL import Image
        with Image.open(src) as im:
            w, h = im.size
        size = f"{w}x{h}" if w and h else None
    except Exception:  # noqa: BLE001
        pass

    style = tame_style_prompt(db.style_prompt(style_value or "3d"))
    out, _prov = image_client.generate_image(
        build_prompt(kind, style), out_name=f"stockconv_{uuid.uuid4().hex[:8]}.png",
        config_id=cfg["id"], reference_images=[str(src)],
        people=1 if kind == "characters" else 0, size=size)
    return str(out)


def apply_result(row_id: int, table: str, new_path: str) -> str:
    """把转换结果写回 image_url,返回新的 media url。"""
    if table not in _TABLES:
        raise RuntimeError(f"不支持的资产表:{table}")
    new_url = f"/static/images/{pathlib.Path(new_path).name}"
    db.ex(f"UPDATE {table} SET image_url=?, updated_at=? WHERE id=?",
          (new_url, db.now(), row_id))
    return new_url


def available_styles() -> list[tuple[str, str]]:
    """(value, 中文名) — 供 UI 下拉(只列视觉风格 style_type='visual')。"""
    return [(r["value"], db.style_display_name(r["value"], r["name"])) for r in
            db.q("SELECT value, name FROM style_presets WHERE is_active=1 "
                 "AND style_type='visual' ORDER BY id")]
