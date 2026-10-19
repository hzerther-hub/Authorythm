# -*- coding: utf-8 -*-
"""端到端漫画生成:剧本 → 拆格 → 出图 → 拼长图(Layer 1)。

把现有的 4 个手动步骤(`comic.split_panels` / `panel_image_prompt` /
`image_client.generate_image` / `stitch.stitch_long_image`)串成一个可一键触发的
编排。**串行而非并发**:
  - 关键帧链式馈送(prev panel → next panel ref)必须按顺序,否则上下文锚点乱;
  - 多数生图 API 有 QPS 限流,并发会被拒;
  - 失败重试粒度按格,中间退出可恢复。

调用方:
- `app/ui/episode_cards.py` 加「✨ AI 出整话」按钮 → 调 `generate_full_comic`;
- `app/pipeline/novel.py` 的 `outline_to_script` 走完后再调它(梗概 → 整话)。

公开 API:
    generate_full_comic(episode_id, *, config_id=None, style_value="", force=False) -> int
"""
from __future__ import annotations

from ..ai import image_client
from ..core import config, db
from ..core.logging_setup import get_logger
from . import comic as _comic
from . import stitch


def panel_ids_in_order(episode_id: int) -> list[int]:
    """按 panel_number 升序返回 panel id 列表。"""
    rows = db.q(
        "SELECT id FROM comic_panels WHERE episode_id=? ORDER BY panel_number",
        (episode_id,),
    )
    return [int(r["id"]) for r in rows]


def panel_has_image(panel_id: int) -> bool:
    row = db.q1("SELECT image_url FROM comic_panels WHERE id=?", (panel_id,))
    return bool(row and row.get("image_url"))


def panel_image_url(panel_id: int) -> str:
    row = db.q1("SELECT image_url FROM comic_panels WHERE id=?", (panel_id,))
    return (row or {}).get("image_url") or ""


def generate_full_comic(
    episode_id: int,
    *,
    config_id: int | None = None,
    style_value: str = "",
    force: bool = False,
) -> dict:
    """端到端生成整话漫画:拆格 → 逐格出图 → 拼长图。

    Args:
        episode_id:剧集 id;必须已有 script_content(content 留空也能跑,优先用 script)。
        config_id:生图模型 config_id;None 时由 episode_page 顶栏的 image_config_id 决定。
        style_value:漫画风格 value;留空走项目级 comic_style。
        force:True 时把已有 image_url 的格也重新出图(默认跳过已出的)。

    Returns:
        {"panels": int, "generated": int, "skipped": int, "failed": int}
        —— 出图统计;调用方按这个 toast 报告。

    行为约束:
        - 拆格失败 → RuntimeError,后续不跑(无 panel 可出图)。
        - 单格出图失败 → 标 panel.status='failed',**不中断**继续下一格。
        - 全程 try/except 出图调用,任何异常归到 panel.status 不上抛。
        - 拼长图独立 try/except;失败也不回滚已出图(留作后续手动重试)。
    """
    log = get_logger("comic_pipeline")

    ep = db.q1("SELECT drama_id, script_content, content FROM episodes WHERE id=?",
              (episode_id,))
    if not ep:
        raise RuntimeError("剧集不存在")
    script = (ep["script_content"] or ep["content"] or "").strip()
    if not script:
        raise RuntimeError("剧本为空,请先在「原始内容」写入剧本或故事梗概")

    drama_id = int(ep["drama_id"])

    # 1) 拆格:有 force 时或当前集没有 panel 时才重拆
    existing = panel_ids_in_order(episode_id)
    if force or not existing:
        _comic.split_panels(episode_id, config_id=config_id)
    panel_ids = panel_ids_in_order(episode_id)
    if not panel_ids:
        raise RuntimeError("拆格后漫画分镜为空,可能剧本太短或模型未返回")

    # 2) 逐格出图(串行,关键帧链式)
    generated = skipped = failed = 0
    prev_url: str | None = None
    for pid in panel_ids:
        if not force and panel_has_image(pid):
            prev_url = panel_image_url(pid) or prev_url
            skipped += 1
            continue
        try:
            prompt = _comic.panel_image_prompt(
                pid, drama_id, config_id=config_id, style_value=style_value,
            )
            refs = _comic.panel_reference_images(pid, prev_image_url=prev_url)
            out, _provider = image_client.generate_image(
                prompt, config_id=config_id, size="1024x1024",
                reference_images=refs or None,
                # people 数喂给全局人数守卫;ghost 守卫防「同一角色一格出现多次」。
                # 两者此前只存在于 UI 的单格重绘链路,整话这里裸奔 ——
                # 实测 2026-10-19 ep79 前 3 格全部同一角色出现 3-4 次。
                people=_comic.panel_people_count(pid),
                extra_negative=_comic.PANEL_NEGATIVE_GUARD,
            )
            url = config.path_to_media_url(out)
            db.ex(
                "UPDATE comic_panels SET image_url=?, updated_at=? WHERE id=?",
                (url, db.now(), pid),
            )
            prev_url = url
            generated += 1
        except Exception as e:  # noqa: BLE001
            db.ex(
                "UPDATE comic_panels SET image_url=NULL, updated_at=? WHERE id=?",
                (db.now(), pid),
            )
            failed += 1
            # 单格失败不中断;最后一并入账
            # (用 log 不用 print —— 见 AGENTS.md 「日志 / 指标 / 密钥」)
            log.warning("panel %d image failed: %s", pid, e)

    # 3) 拼长图
    try:
        stitch.stitch_panels(episode_id)
    except Exception as e:  # noqa: BLE001
        log.warning("stitch_panels failed for episode %d: %s", episode_id, e)

    db.touch("episodes", episode_id)
    return {
        "panels": len(panel_ids),
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
    }
