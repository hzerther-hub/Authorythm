# -*- coding: utf-8 -*-
"""宣传线:按平台+格式生成宣传文案(promo_writer Agent)。"""
from __future__ import annotations

import json

from ..agents import runner
from ..core import config, db

PLATFORMS = [
    ("douyin", "抖音"), ("xiaohongshu", "小红书"), ("wechat_channels", "视频号"),
    ("wechat_mp", "公众号"), ("bilibili", "B站"), ("zhihu", "知乎"),
]
FORMATS = [
    ("video", "短视频"), ("image_set", "图文集"), ("card_burst", "卡点"),
    ("mixed_clip", "混剪"), ("voiceover", "口播"), ("article", "长图文"),
]


def generate_promo(drama_id: int, platform: str, fmt: str,
                   extra: str = "", config_id: int | None = None) -> dict:
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    if not d:
        raise RuntimeError("项目不存在")
    meta = db.jload(d["metadata"], {})
    platform_name = dict(PLATFORMS).get(platform, platform)
    fmt_name = dict(FORMATS).get(fmt, fmt)
    first_ep = db.q1("SELECT content FROM episodes WHERE drama_id=? ORDER BY episode_number LIMIT 1", (drama_id,))
    source = ((first_ep or {"content": ""})["content"] or (d["novel_outline"] or ""))[:4000]
    prompt = f"""目标平台: {platform_name}
输出格式: {fmt_name}
产品/作品: {d['title']}
{( '补充要求: ' + extra) if extra else ''}

素材(作品内容/大纲):
{source}"""
    data = runner.run_agent_json("promo_writer", prompt, config_id=config_id,
                                 lang=config.resolve_content_language(drama_id))
    if not isinstance(data, dict):
        data = {"title": "", "body": str(data)}
    db.ex("UPDATE dramas SET metadata=?, updated_at=? WHERE id=?",
          (json.dumps({**meta, "last_promo": data}, ensure_ascii=False), db.now(), drama_id))
    return data
