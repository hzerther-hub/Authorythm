"""批量重画一个项目的所有常规资产(image_url,走 dramas.style)。

脱离 app 直接跑:不依赖 Qt event loop,每条同步等出图,
逐条打印 OK / FAIL,失败不影响后面的。

⚠️ 跑之前先关掉 app —— SQLite + Python 线程,两边同时写会锁冲突。

用法:
    PYTHONPATH=. python scripts/bulk_regen.py <drama_id> [--image-cfg 9]

默认:
    drama_id = 1
    image_cfg_id = 9 (qwen-image / wan2.7-image-pro)
"""
from __future__ import annotations

import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

import argparse

from app.core import db
from app.pipeline import prompts_gen
from app.ai import image_client
from app.core import config


def regen_one(kind: str, table: str, row_id: int, image_cfg: int) -> tuple[bool, str]:
    """单个资产重画,返回 (ok, msg)。"""
    try:
        # 1. 重新起草 final_prompt(走新代码 → 严格 dramas.style 前缀)
        if kind == "character":
            fp = prompts_gen.character_prompt(row_id)
        elif kind == "scene":
            fp = prompts_gen.scene_prompt(row_id)
        else:
            fp = prompts_gen.prop_prompt(row_id)
        prefix = fp[:60]
        # 2. 出图
        size = "1024x1024" if kind == "character" else "1280x720"
        people = 1 if kind == "character" else 0
        out, provider = image_client.generate_image(
            fp,
            out_name=f"{table}_{row_id}_3d.png",
            config_id=image_cfg, size=size, people=people)
        url = config.path_to_media_url(out)
        # 3. 落库
        db.ex(f"UPDATE {table} SET image_url=?, updated_at=? WHERE id=?",
              (url, db.now(), row_id))
        return True, f"[{provider}] {url} | prefix: {prefix}"
    except Exception as e:                                # noqa: BLE001
        return False, str(e)[:200]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("drama_id", nargs="?", type=int, default=1)
    ap.add_argument("--image-cfg", type=int, default=9,
                    help="image 服务 config_id(9=qwen-image, 3=agnes, 7=volcengine)")
    args = ap.parse_args()

    db.init_db()
    print(f"=== drama {args.drama_id} 批量重画 image_url,config_id={args.image_cfg} ===")
    print(f"(确保 app 已关闭,避免 SQLite 锁冲突)\n")

    ok = fail = 0
    for kind, table in (("character", "characters"),
                        ("scene", "scenes"),
                        ("prop", "props")):
        rows = db.q(f"SELECT id FROM {table} WHERE drama_id=? ORDER BY id",
                    (args.drama_id,))
        if not rows:
            continue
        print(f"--- {kind} ({len(rows)} 个) ---")
        for r in rows:
            rid = r["id"]
            success, msg = regen_one(kind, table, rid, args.image_cfg)
            mark = "OK  " if success else "FAIL"
            print(f"  [{mark}] {kind}#{rid:>3}: {msg[:160]}")
            if success:
                ok += 1
            else:
                fail += 1

    print(f"\n完成:OK={ok}  FAIL={fail}")


if __name__ == "__main__":
    main()
