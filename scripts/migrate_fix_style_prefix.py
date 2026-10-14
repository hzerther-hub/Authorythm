"""一次性迁移:把现有 final_prompt 头部换成 dramas.style 对应的前缀。

历史背景:prompts_gen 之前误用 comic._style_for()(优先级 comic_style > style > "3d"),
会把 comic_style 写进 final_prompt 头部。drama.style 设的视觉风格(如 3D)就被无视。

本脚本不调 LLM,只就地替换头部,数秒跑完,无 token 消耗。

跑过一次后即可删;之后所有新生成的 final_prompt 都走修正后的 prompts_gen,
前缀自动跟 dramas.style 对齐,不再需要此迁移。

用法:python scripts/migrate_fix_style_prefix.py
"""
from __future__ import annotations

from app.core import db


def _all_known_prefixes() -> list[str]:
    """所有合法风格预设的前缀全文。"""
    rows = db.q("SELECT prompt FROM style_presets WHERE is_active=1")
    out = [(r["prompt"] or "").strip() for r in rows if (r["prompt"] or "").strip()]
    # "live" 是兜底风格(不在 style_presets 里),单独加进来
    out.append("ultra-realistic cinematic live-action look, professional film photography, "
               "natural skin texture, real human actors")
    return out


def _detect_prefix(fp: str, all_pfx: list[str]) -> str | None:
    """返回 final_prompt 头部那段当前前缀(若能匹配上某个已知预设)。"""
    if not fp:
        return None
    head = fp[:300]
    for p in all_pfx:
        if head.startswith(p):
            return p
    return None


def main() -> None:
    db.init_db()
    all_pfx = _all_known_prefixes()
    print(f"已知风格前缀: {len(all_pfx)} 种")

    counts = {"characters": 0, "scenes": 0, "props": 0}
    for table in ("characters", "scenes", "props"):
        # 只有 characters 表有 final_prompt_style 列(scenes/props 没有)
        has_style_col = (table == "characters")
        rows = db.q(f"SELECT id, drama_id, final_prompt FROM {table} "
                    f"WHERE final_prompt IS NOT NULL AND final_prompt != ''")
        for r in rows:
            cid, drama_id, fp = r["id"], r["drama_id"], r["final_prompt"]
            if not drama_id:
                continue
            d = db.q1("SELECT style FROM dramas WHERE id=?", (drama_id,))
            if not d:
                continue
            style_val = (d["style"] or "3d").strip()
            cur_pfx = _detect_prefix(fp, all_pfx)
            new_pfx = db.style_prompt(style_val)
            if cur_pfx == new_pfx:
                continue                              # 已经匹配,不浪费 IO
            body = fp[len(cur_pfx):].lstrip(" ,。. ") if cur_pfx else fp
            new_fp = f"{new_pfx}, {body}" if body else new_pfx
            if has_style_col:
                db.ex(f"UPDATE {table} SET final_prompt=?, final_prompt_style=?, "
                      f"updated_at=? WHERE id=?",
                      (new_fp, style_val, db.now(), cid))
            else:
                db.ex(f"UPDATE {table} SET final_prompt=?, updated_at=? WHERE id=?",
                      (new_fp, db.now(), cid))
            counts[table] += 1

    print(f"迁移完成:角色 {counts['characters']} / 场景 {counts['scenes']} / "
          f"道具 {counts['props']}")


if __name__ == "__main__":
    main()
