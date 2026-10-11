# -*- coding: utf-8 -*-
"""测试:流式写章(按钮路径)——真实 StreamWorker,离屏 Qt。"""
from __future__ import annotations

import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, "E:/pydrama")

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

from app.ui.streaming import StreamWorker  # noqa: E402
from app.agents.prompts import load_prompt  # noqa: E402
from app.core import db  # noqa: E402
from app.pipeline import novel as novel_pipe  # noqa: E402

EP = 8
prompt = novel_pipe.chapter_prompt(EP)
system = load_prompt("novel_writer", db.get_setting("content_language", "zh"))
w = StreamWorker(prompt, system=system, config_id=None, temperature=0.6, max_tokens=32768)
state = {"r": 0, "c": 0, "done": False, "err": None, "text": ""}


def on_delta(kind, chunk):
    if kind == "reasoning":
        state["r"] += len(chunk)
    else:
        state["c"] += len(chunk)


def on_finish(text):
    state["done"] = True
    state["text"] = text


def on_failed(m):
    state["done"] = True
    state["err"] = m


w.delta.connect(on_delta)
w.finished.connect(on_finish)
w.failed.connect(on_failed)
w.start()

t0 = time.time()
while not state["done"] and time.time() - t0 < 540:
    app.processEvents()
    time.sleep(0.1)

print(f"elapsed={round(time.time() - t0)}s reasoning={state['r']}字 content={state['c']}字")
text = state.get("text", "")
print("content_len:", len(text.strip()))
print("head:", text.strip()[:150].replace("\n", " "))
print("残留检查 | <think>:", "<think>" in text, "| <tool_call>:", "<tool_call>" in text)
if state["err"]:
    print("ERROR:", state["err"][:200])
print("TEST-A-DONE")
