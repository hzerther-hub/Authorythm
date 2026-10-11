# -*- coding: utf-8 -*-
"""诊断:录制 write_chapter 实际收到的流帧统计。"""
from __future__ import annotations

import sys

sys.path.insert(0, "E:/pydrama")

from app.ai import text_stream  # noqa: E402

_orig = text_stream.chat_stream
ATTEMPT = {"n": 0}


def recorder(prompt, **kw):
    ATTEMPT["n"] += 1
    n = ATTEMPT["n"]
    stats = {"r": 0, "c": 0, "frames": 0, "r_head": "", "c_head": "", "c_tail": ""}
    for kind, chunk in _orig(prompt, **kw):
        stats["frames"] += 1
        if kind == "reasoning":
            stats["r"] += len(chunk)
            if not stats["r_head"]:
                stats["r_head"] = chunk[:70]
        else:
            stats["c"] += len(chunk)
            if not stats["c_head"]:
                stats["c_head"] = chunk[:70]
            stats["c_tail"] = (stats["c_tail"] + chunk)[-70:]
        yield kind, chunk
    print(f"[attempt {n}] frames={stats['frames']} reasoning={stats['r']}字 "
          f"content={stats['c']}字", flush=True)
    print(f"  r_head={stats['r_head']!r}", flush=True)
    print(f"  c_head={stats['c_head']!r}", flush=True)
    print(f"  c_tail={stats['c_tail']!r}", flush=True)


text_stream.chat_stream = recorder

from app.pipeline import novel as novel_pipe  # noqa: E402

try:
    out = novel_pipe.write_chapter_with_review(8)
    print("OK content_len:", len(out["content"]), "fixed:", out["fixed"])
except Exception as e:
    print("FAIL:", str(e)[:200])
print("DIAG-DONE")
