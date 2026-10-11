# -*- coding: utf-8 -*-
"""测试:非流式写章 + 审校 + 修复(批量写章节的构建块),真实落库。"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, "E:/pydrama")

from app.pipeline import novel as novel_pipe  # noqa: E402

t0 = time.time()
out = novel_pipe.write_chapter_with_review(8)
print(f"elapsed={round(time.time() - t0)}s")
print("content_len:", len(out["content"]), "| fixed:", out["fixed"],
      "| review overall:", (out.get("review") or {}).get("overall"))

from app.core import db  # noqa: E402

row = db.q1("SELECT content, title FROM episodes WHERE id=8")
c = row["content"] or ""
print("DB content_len:", len(c), "| DB title:", row["title"])
print("残留检查 | <think>:", "<think>" in c, "| <tool_call>:", "<tool_call>" in c)
print("head:", c[:150].replace("\n", " "))
print("TEST-B-DONE")
