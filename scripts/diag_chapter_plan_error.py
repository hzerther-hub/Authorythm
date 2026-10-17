# -*- coding: utf-8 -*-
"""诊断脚本:列出最近失败的「章节计划」任务并打印完整 error_msg。

用法:
    python -m scripts.diag_chapter_plan_error
    python -m scripts.diag_chapter_plan_error --tail 50     # 多打几行
    python -m scripts.diag_chapter_plan_error --drama-id 7  # 只看某个项目
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DB = Path("data/yihao.sqlite3")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tail", type=int, default=10, help="显示最近多少条失败任务")
    p.add_argument("--drama-id", type=int, default=None, help="只看某个项目")
    p.add_argument("--db", type=str, default=str(DB), help="SQLite 路径")
    args = p.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"[ERR] 数据库不存在:{db_path.resolve()}")
        return 1

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    where = ["status='failed'", "type='prompt'"]
    params: list = []
    if args.drama_id is not None:
        where.append("drama_id=?")
        params.append(args.drama_id)
    sql = f"""SELECT id, drama_id, type, status, error_msg, created_at, updated_at
              FROM sys_task
              WHERE {' AND '.join(where)}
              ORDER BY id DESC LIMIT ?"""
    params.append(args.tail)
    rows = con.execute(sql, params).fetchall()

    if not rows:
        print("[OK] 没有失败的 prompt 任务(sys_task 里 status='failed' 且 type='prompt')")
        return 0

    for r in rows:
        print("=" * 78)
        print(f"task#{r['id']}  drama_id={r['drama_id']}  type={r['type']}  "
              f"status={r['status']}")
        print(f"created={r['created_at']}  updated={r['updated_at']}")
        print("-" * 78)
        # 全文输出,不再截断
        print(r["error_msg"] or "(error_msg 为空)")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
