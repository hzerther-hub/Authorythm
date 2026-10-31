"""从原版(xiaoshuo)迁移 AI 服务配置到 PySide6 重写版。

原版 `ai_service_configs` 字段 → 本版映射:
    name        → remark(配置名)
    model       → JSON 数组字符串 → models(JSON) + model(取第一个)
    settings    → 原样(厂商私有开关,如 tts 的 voice_type / 视频的 realPersonMode)

用法:
    py -3.13 -m scripts.migrate_ai_configs            # 迁移
    py -3.13 -m scripts.migrate_ai_configs --dry-run  # 只看不动
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai import registry
from app.core import db

SOURCE_DB = Path(r"E:\xiaoshuo\data\yihao.sqlite3")


def read_source() -> list[dict]:
    conn = sqlite3.connect(f"file:{SOURCE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM ai_service_configs").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        # model 可能是 JSON 数组字符串、单值或 None
        raw = (d.get("model") or "").strip()
        models: list[str] = []
        if raw.startswith("["):
            try:
                models = [str(x) for x in json.loads(raw) if str(x).strip()]
            except Exception:  # noqa: BLE001
                models = []
        elif raw:
            models = [raw]
        if not models:
            continue
        out.append({
            "service_type": d["service_type"],
            "provider": d["provider"],
            "remark": d.get("name") or f"{d['provider']}-{d['service_type']}",
            "base_url": (d.get("base_url") or "").rstrip("/"),
            "api_key": d.get("api_key") or "",
            "model": models[0],
            "models": models,
            "priority": int(d.get("priority") or 0),
            "is_default": 1 if d.get("is_default") else 0,
            "is_active": 1 if d.get("is_active") else 0,
            "settings": d.get("settings") or "",
        })
    return out


def main() -> int:
    dry = "--dry-run" in sys.argv
    if not SOURCE_DB.exists():
        print(f"❌ 找不到原版数据库:{SOURCE_DB}")
        return 1
    db.init_db()
    src = read_source()
    print(f"原版配置 {len(src)} 条{'(dry-run 不会写入)' if dry else ''}\n")
    for c in src:
        key = "有Key" if c["api_key"].strip() else "缺Key"
        print(f"  {c['service_type']:9s} | {c['remark'][:28]:28s} | P{c['priority']:3d} | {key} | {len(c['models'])} 模型")
    if dry:
        return 0

    migrated = skipped = 0
    for c in src:
        # 同类型同 provider 同 base_url 视为同一条,覆盖更新
        row = db.q1("""SELECT id FROM ai_service_configs
                       WHERE service_type=? AND provider=? AND base_url=?""",
                    (c["service_type"], c["provider"], c["base_url"]))
        if row:
            registry.update_config(row["id"], provider=c["provider"], base_url=c["base_url"],
                                   api_key=c["api_key"], model=c["model"],
                                   remark=c["remark"], priority=c["priority"],
                                   is_active=bool(c["is_active"]))
            db.ex("UPDATE ai_service_configs SET models=?, settings=?, is_default=? WHERE id=?",
                  (json.dumps(c["models"], ensure_ascii=False), c["settings"],
                   c["is_default"], row["id"]))
            skipped += 1
        else:
            cid = registry.add_config(c["service_type"], c["provider"], c["base_url"],
                                      c["model"], api_key=c["api_key"],
                                      is_default=bool(c["is_default"]),
                                      remark=c["remark"], priority=c["priority"],
                                      models=c["models"])
            db.ex("UPDATE ai_service_configs SET is_active=?, settings=? WHERE id=?",
                  (c["is_active"], c["settings"], cid))
            migrated += 1
    print(f"\n✅ 新增 {migrated} 条,更新 {skipped} 条\n")
    print("=== 迁移后就绪状态 ===")
    for st, status, reason in registry.readiness():
        print(f"  {'✅' if status == 'ok' else '❌'} {registry.SVC_CN.get(st, st):4s} — {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
