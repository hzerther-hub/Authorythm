"""漫画长条图拼接(Pillow 竖向拼接,格间距白底,可加旁白条)。"""
from __future__ import annotations

import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..core import config, db


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("msyh.ttc", "simhei.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def stitch_panels(episode_id: int, gap: int = 16, side: int = 24,
                  with_narration: bool = True) -> Path:
    rows = db.q("SELECT * FROM comic_panels WHERE episode_id=? AND image_url IS NOT NULL ORDER BY panel_number", (episode_id,))
    imgs: list[tuple[Image.Image, str]] = []
    width = 0
    for r in rows:
        p = config.media_url_to_path(r["image_url"])
        if not p.exists():
            continue
        im = Image.open(p).convert("RGB")
        width = max(width, im.width)
        narration = (r["narration"] or "").strip() if with_narration else ""
        imgs.append((im, narration))
    if not imgs:
        raise RuntimeError("没有已出图的漫画格")

    target = min(width, 1080)
    font = _font(int(target * 0.032) + 8)
    narr_h = lambda t: (len(t) // 24 + 1) * int(target * 0.05) + 14  # noqa: E731
    pieces = []
    for im, narr in imgs:
        scale = target / im.width
        im2 = im.resize((target, int(im.height * scale)), Image.LANCZOS)
        nh = narr_h(narr) if narr else 0
        block = Image.new("RGB", (target, im2.height + nh), "white")
        block.paste(im2, (0, 0))
        if narr:
            draw = ImageDraw.Draw(block)
            for i in range(0, len(narr), 24):
                draw.text((12, im2.height + 6 + i * int(target * 0.05)),
                          narr[i:i + 24], fill="#333333", font=font)
        pieces.append(block)

    total_h = sum(p.height for p in pieces) + gap * (len(pieces) - 1) + side * 2
    canvas = Image.new("RGB", (target + side * 2, total_h), "white")
    y = side
    for p in pieces:
        canvas.paste(p, (side, y))
        y += p.height + gap
    out = config.STATIC_DIR / "comics" / f"stitch_{uuid.uuid4().hex[:12]}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=90)
    return out
