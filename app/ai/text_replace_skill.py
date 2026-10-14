# -*- coding: utf-8 -*-
"""文字编辑技能:替换图中指定文字 / 抹掉所有文字。

设计原则
========
- 一个技能 = 一个独立可测的能力单元。输入图片 + 意图,返回产物。
- 工具链按"各取所长"组合,失败有兜底:

  | 步骤           | 首选                | 兜底            | 原因                    |
  |----------------|--------------------|-----------------|------------------------|
  | 意图解析       | 本地正则             | MiniMax-M3 NLU  | 大多数用户句子正则能命中 |
  | 文字定位       | MiniMax-M3 多模态    | —               | CLI 858 命令里无 OCR   |
  | 抹字 inpaint   | OpenCV cv2.inpaint   | PhotoCraft CLI  | CLI select.rect 不传   |
  | 渲染新字       | PIL/Pillow ImageDraw | —               | 简单、可控、不依赖 CLI  |

为什么不用 PhotoCraft 的 select.rect + contentAwareFill(实测):
  photocraft-cli 的 `run` 模式下选区状态不在命令间传递 —— select.rect
  返回 null,后续 contentAwareFill 完全对不上字(选 y=430,填充 window
  是 y=289),文字纹丝不动。这是 CLI 侧限制,换调用姿势无效。

用法
----
    from app.ai.text_replace_skill import TextReplaceSkill, TextEditResult

    skill = TextReplaceSkill()
    result = skill.replace("input.png", "影星", "歌星", "output.png")
    if result.ok:
        print(result.output_path)
    else:
        print(result.error)

    # 抹掉所有字
    result = skill.remove_all_text("input.png")

    # 自动解析意图
    action = skill.parse_intent("把'89'改成'2025'")
    # action = ("replace", "89", "2025")
"""
from __future__ import annotations

import io
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .photocraft_bridge import (
    PhotocraftCLI,
    _opencv_available,
    inpaint_regions_opencv,
    locate_text_regions,
    remove_text_by_inpaint,
)


# ── 意图识别 ──

# 把X改成Y / 把X换成Y / 把X替换为Y / 将X改为Y / X变Y
# 注意:引号(中英全角半角「"'『')和非引号两种都允许;非引号版本会贪婪,
#       所以先匹配引号版本。
_REPLACE_PATTERNS = [
    re.compile(r"""把\s*[「"'『""](.+?)[」"'』""]\s*改成\s*[「"'『""](.+?)[」"'』""]"""),
    re.compile(r"""把\s*[「"'『""](.+?)[」"'』""]\s*换成\s*[「"'『""](.+?)[」"'』""]"""),
    re.compile(r"""把\s*[「"'『""](.+?)[」"'』""]\s*替换为\s*[「"'『""](.+?)[」"'』""]"""),
    re.compile(r"""把\s*['"](.+?)['"]\s*改成\s*['"]?(.+?)['"]?$"""),
    re.compile(r"""把\s*(.+?)\s*改成\s*['"](.+?)['"]$"""),
    re.compile(r"""把\s*(.+?)\s*换成\s*(.+?)$"""),
    re.compile(r"""把\s*(.+?)\s*替换为\s*(.+?)$"""),
    re.compile(r"""将\s*(.+?)\s*改为\s*(.+?)$"""),
    re.compile(r"""(.+?)\s*变(?:成|为)\s*(.+?)$"""),
]

# 抹掉所有字(老路径已存在,这里仅复用正则)
_REMOVE_PATTERNS = [
    re.compile(r"去掉|去除|删除|抹掉|清除|消除|擦掉|擦除|遮掉|去请|除掉|移除|消掉|remove|erase|clean"),
]


def parse_intent(text: str) -> tuple[str, str, str] | None:
    """把用户一句中文解析成 (action, arg1, arg2)。

    - ("replace", find, replace):把 find 替换为 replace
    - ("remove", "", ""):抹掉所有文字
    - None:不是文字编辑意图
    """
    t = (text or "").strip()
    if not t:
        return None
    # 1. 替换意图(更具体,先匹配)
    for pat in _REPLACE_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        find = m.group(1).strip()
        replace = m.group(2).strip()
        # 去掉残留引号(像 '把"X"改成"Y"' 误匹配时)
        find = find.strip("「」'\"『』""''")
        replace = replace.strip("「」'\"『』""''")
        if find and replace and find != replace:
            return ("replace", find, replace)
    # 2. 抹除意图(去掉所有文字)
    low = t.lower()
    if any(rw.search(t) or rw.search(low) for rw in _REMOVE_PATTERNS):
        # 必须指向图上的文字
        has_dedicated = any(w in t for w in
                            ("文字", "文本", "文案", "字幕", "水印", "签名", "logo"))
        has_ctx = "字" in t and any(c in t for c in
                                   ("图", "图片", "画面", "照片", "海报", "封面", "背景", "上", "里", "中"))
        if has_dedicated or has_ctx:
            return ("remove", "", "")
    return None


# ── 统一返回值 ──

@dataclass
class TextEditResult:
    """技能返回的产物 + 元信息。

    设计:所有方法(成功/失败/无文字)都返回这个 dataclass,不抛异常。
    调用方只需看 ok 字段,详情走 info / error / regions。
    """
    ok: bool
    output_path: str = ""
    error: str = ""
    info: str = ""                  # 给用户的说明
    engine: str = ""                # 实际跑了哪个 inpaint:opencv / photocraft / inpaint_masked
    regions: list[dict] = field(default_factory=list)   # 识别到的文字框


# ── 技能本体 ──

class TextReplaceSkill:
    """文字编辑技能:把图中的 X 替换为 Y / 抹掉所有字。

    工具链:
      - 意图解析:parse_intent() —— 正则匹配,零成本
      - 文字定位:locate_text_regions() —— MiniMax-M3 多模态
      - 抹字:inpaint_regions_opencv() / PhotocraftCLI / inpaint_masked
      - 渲染新字:PIL/Pillow ImageDraw + 中文字体
    """

    # 默认字体候选(中英常见)
    _FONT_CANDIDATES = (
        "msyh.ttc",       # 微软雅黑(Win)
        "msyh.ttf",
        "simhei.ttf",     # 黑体(Win)
        "simsun.ttc",     # 宋体(Win)
        "PingFang.ttc",   # 苹方(macOS)
        "STHeiti Medium.ttc",
        "NotoSansCJK-Regular.ttc",  # Linux
        "DejaVuSans.ttf",
        "arial.ttf",
    )

    def __init__(self, llm_config_id: int | None = None,
                 cli: PhotocraftCLI | None = None):
        self.llm_config_id = llm_config_id
        self.cli = cli or PhotocraftCLI()

    # ── 对外入口 ──

    def replace(self, image_path: str, find_text: str, replace_text: str,
                out_path: str | None = None) -> TextEditResult:
        """把图中的 find_text 替换为 replace_text。

        流程:定位 → 匹配 find → 抹旧字 → 渲新字 → 保存。
        """
        regions, rerr = self._locate(image_path)
        if rerr:
            return TextEditResult(ok=False, error=rerr)
        if not regions:
            return TextEditResult(ok=False,
                                  error="这张图里没检测到文字,无法替换。")

        matched = self._match_region(find_text, regions)
        if not matched:
            sample = "、".join(f"「{r.get('text') or '?'}」" for r in regions[:5])
            return TextEditResult(
                ok=False,
                regions=regions,
                error=f"图里没找到「{find_text}」(检测到:{sample}...)。")

        return self._replace_one_region(
            image_path, [matched], replace_text, out_path)

    def remove_all_text(self, image_path: str,
                        out_path: str | None = None) -> TextEditResult:
        """抹掉图中所有文字。

        复用 replace 的底层:只是不渲染新字。
        """
        regions, rerr = self._locate(image_path)
        if rerr:
            return TextEditResult(ok=False, error=rerr)
        if not regions:
            return TextEditResult(ok=False,
                                  error="这张图里没检测到文字,无需抹除。")
        return self._replace_one_region(image_path, regions, "", out_path,
                                        render_new=False)

    def parse_intent(self, text: str):
        """对外暴露意图解析(模块级 parse_intent 的实例版)。"""
        return parse_intent(text)

    # ── 内部步骤 ──

    def _locate(self, image_path: str) -> tuple[list[dict], str]:
        """调 LLM 定位图中所有文字 + 坐标。"""
        return locate_text_regions(image_path, config_id=self.llm_config_id)

    def _match_region(self, find: str, regions: list[dict]) -> dict | None:
        """把 find 跟 regions 里的 text 字段匹配,挑最像的。

        匹配顺序:精确 → 包含 → 模糊相似度(≥0.5)。
        """
        from difflib import SequenceMatcher
        if not regions:
            return None
        # 精确
        for r in regions:
            if r.get("text") == find:
                return r
        # 包含
        for r in regions:
            rt = r.get("text", "")
            if find in rt or rt in find:
                return r
        # 相似度
        best, best_score = None, 0.0
        for r in regions:
            score = SequenceMatcher(None, find, r.get("text", "")).ratio()
            if score > best_score:
                best, best_score = r, score
        return best if best_score >= 0.5 else None

    def _replace_one_region(self, image_path: str, regions: list[dict],
                            new_text: str, out_path: str | None,
                            render_new: bool = True) -> TextEditResult:
        """核心:对 regions 做抹字(+可选渲染新字),保存到 out_path。"""
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return TextEditResult(ok=False, error="Pillow 未安装")

        p = Path(image_path)
        if not p.exists():
            return TextEditResult(ok=False, error=f"图片不存在:{image_path}")

        # 1) 抹字:inpaint(优先 OpenCV,退到 inpaint_masked)
        try:
            from . import config as _cfg
            out = Path(out_path) if out_path else (
                _cfg.STATIC_DIR / "processed" /
                f"textedit_{int(time.time())}_{uuid.uuid4().hex[:6]}.png")
            out.parent.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            out = Path(out_path) if out_path else p.with_name(
                f"{p.stem}_textedit{p.suffix}")

        engine = "opencv"
        err_msg = ""
        if _opencv_available():
            ok, err = inpaint_regions_opencv(image_path, regions, str(out))
            if ok:
                engine = "opencv"
            else:
                err_msg = err
        else:
            err_msg = "未安装 opencv-python"

        if err_msg:
            # 退到 inpaint_masked(走项目 AI inpaint 服务)
            ok2, err2 = remove_text_by_inpaint(image_path, regions, out_file=str(out))
            if not ok2:
                return TextEditResult(ok=False, error=err2 or err_msg)
            engine = "inpaint_masked"

        # 2) 渲染新字(仅当 render_new=True)
        if render_new and new_text:
            try:
                self._render_new_text(str(out), regions, new_text, str(out))
            except Exception as exc:  # noqa: BLE001
                # 渲染失败 ≠ 整体失败,产物图(已抹字)仍可用
                return TextEditResult(
                    ok=True, output_path=str(out),
                    info=f"已抹掉原字,但渲染新字失败:{exc}",
                    engine=engine, regions=regions)

        info = ""
        if render_new and new_text:
            info = (f"已识别 {len(regions)} 处文字,把其中 "
                    f"「{regions[0].get('text') or '?'}」"
                    f"替换为「{new_text}」(用 {engine} 抹旧字,PIL 渲新字)。")
        else:
            info = f"已抹掉 {len(regions)} 处文字(用 {engine})。"

        return TextEditResult(ok=True, output_path=str(out),
                              info=info, engine=engine, regions=regions)

    def _render_new_text(self, image_path: str, regions: list[dict],
                         new_text: str, out_path: str) -> None:
        """在 regions[0] 的位置上画 new_text,字体大小按 region 高度估算。

        颜色取 region 中心像素(常见杂志/海报字色),描 1px 黑边以贴合"原字是
        描边字"的常见样式。
        """
        from PIL import Image, ImageDraw, ImageFont
        try:
            import cv2
            import numpy as np
        except ImportError:
            # 没有 OpenCV 就纯 PIL:不能拿中心像素颜色,默认黑色
            cv2 = None  # type: ignore[assignment]

        r = regions[0]
        x1, y1 = int(r["x1"]), int(r["y1"])
        x2, y2 = int(r["x2"]), int(r["y2"])
        rw = max(1, x2 - x1)
        rh = max(1, y2 - y1)

        img = Image.open(image_path).convert("RGB")
        draw = ImageDraw.Draw(img)

        # 估算字号:区域高度的 1.1 倍;若新文字较长,按比例缩小
        char_count = max(1, len(new_text))
        font_size = max(10, min(int(rh * 1.05),
                                int(rw / char_count * 1.7)))
        font = self._load_font(font_size)

        # textbbox 算实际像素宽高(不同字体/字符差异大)
        try:
            tb = draw.textbbox((0, 0), new_text, font=font)
            tw, th = tb[2] - tb[0], tb[3] - tb[1]
        except Exception:  # noqa: BLE001
            tw, th = font_size * char_count, font_size
        # 居中放在 region 内
        tx = x1 + (rw - tw) // 2
        ty = y1 + (rh - th) // 2

        # 取 region 中心像素作主色(常见杂志字色 = 区域中心背景色)
        if cv2 is not None:
            arr = cv2.imread(image_path, cv2.IMREAD_COLOR)
            if arr is not None:
                h, w = arr.shape[:2]
                cx = max(0, min(w - 1, (x1 + x2) // 2))
                cy = max(0, min(h - 1, (y1 + y2) // 2))
                bgr = arr[cy, cx]
                text_color = (int(bgr[2]), int(bgr[1]), int(bgr[0]))
            else:
                text_color = (20, 20, 20)
        else:
            text_color = (20, 20, 20)

        # 描边(细一些;太粗会糊)
        stroke_w = max(1, font_size // 14)
        for dx in range(-stroke_w, stroke_w + 1):
            for dy in range(-stroke_w, stroke_w + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text((tx + dx, ty + dy), new_text, fill=(0, 0, 0), font=font)
        draw.text((tx, ty), new_text, fill=text_color, font=font)

        img.save(out_path)

    def _load_font(self, size: int):
        """挑一个可用的中文字体;都不可用就退化到 PIL 默认字体。"""
        from PIL import ImageFont
        for name in self._FONT_CANDIDATES:
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()
