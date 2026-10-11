# -*- coding: utf-8 -*-
"""把参考项目(E:\\xiaoshuo)的所有 AI 模型配置迁到 pydrama。

策略(幂等,可重跑):
  - 以 (service_type, provider) 为键 upsert 参考项目的每一条配置
  - base_url / api_key / model / endpoint / query_endpoint / api_format 全部取参考值
  - pydrama 独有的配置(火山 Seedream 生图、本地换脸等)不动
  - is_default 保留 pydrama 现状(默认项是这边刻意选过的),只迁移 is_active
"""
from __future__ import annotations

import json
import sqlite3

REF = r"E:\xiaoshuo\data\yihao.sqlite3"
PYD = r"E:\pydrama\data\yihao.sqlite3"

FIELDS = ("service_type", "provider", "base_url", "api_key", "model",
          "priority", "is_active", "api_format")


def load_ref():
    conn = sqlite3.connect("file:" + REF + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute("SELECT * FROM ai_service_configs")]


def main() -> None:
    ref_rows = load_ref()
    conn = sqlite3.connect(PYD)
    conn.row_factory = sqlite3.Row
    ts = "2026-10-11T00:00:00.000Z"
    added, updated = [], []

    for r in ref_rows:
        st, pv = r["service_type"], r["provider"]
        models = r.get("model") or ""
        # 参考项目 model 是 JSON 数组时,同时写进 pydrama 的 models 列
        models_list = None
        try:
            parsed = json.loads(models)
            if isinstance(parsed, list):
                models_list = models
                models = parsed[0]
        except Exception:
            parsed = None

        old = conn.execute(
            "SELECT id FROM ai_service_configs WHERE service_type=? AND provider=?",
            (st, pv)).fetchone()
        if old:
            sets = ["base_url=?", "api_key=?", "model=?", "updated_at=?"]
            vals = [r["base_url"], r["api_key"], models, ts]
            if models_list:
                sets.append("models=?")
                vals.append(models_list)
            if r.get("priority"):
                sets.append("priority=?")
                vals.append(r["priority"])
            sets.append("is_active=?")
            vals.append(r["is_active"])
            if r.get("api_format"):
                sets.append("api_format=?")
                vals.append(r["api_format"])
            vals.append(old["id"])
            conn.execute(
                "UPDATE ai_service_configs SET " + ",".join(sets) + " WHERE id=?",
                tuple(vals))
            updated.append(f"{st}/{pv}")
        else:
            conn.execute(
                "INSERT INTO ai_service_configs"
                "(service_type,provider,base_url,api_key,model,models,priority,"
                " is_default,is_active,remark,api_format,created_at,updated_at)"
                " VALUES(?,?,?,?,?,?,?,0,?,?,?,?,?)",
                (st, pv, r["base_url"], r["api_key"], models, models_list,
                 r["priority"] or 0, r["is_active"],
                 (r.get("name") or "") + "(取自参考项目)", r.get("api_format"),
                 ts, ts))
            added.append(f"{st}/{pv}:{models}")

    conn.commit()
    print(f"更新 {len(updated)} 条: {', '.join(updated) or '-'}")
    print(f"新增 {len(added)} 条:")
    for a in added:
        print("   +", a)
    print("--- pydrama 现状 ---")
    for row in conn.execute(
            "SELECT service_type,provider,model,is_active,is_default FROM "
            "ai_service_configs ORDER BY service_type, id"):
        print("   %-9s | %-14s | %-40s | active=%s def=%s"
              % (row["service_type"], row["provider"], str(row["model"])[:40],
                 row["is_active"], row["is_default"]))
    conn.close()


if __name__ == "__main__":
    main()