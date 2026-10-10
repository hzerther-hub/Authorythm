# -*- coding: utf-8 -*-
"""一次性脚本:给 E:/comPySide 的 i18n_data.json 补 29 个缺失键 × 13 语言。

用 pydrama 配置的文本模型机翻;输出 docs/_composer_i18n_raw.json 供合并。
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "E:/pydrama")
from app.ai import text_client  # noqa: E402

OUT = "docs/_composer_i18n_raw.json"
DATA = "E:/comPySide/src/compositor/i18n_data.json"

KEYS = [
    "Layers",
    "Blur", "Heal", "Brush", "Eraser", "Crop", "Eyedropper", "Type", "Move",
    "Clone Stamp", "Gradient", "Shape", "Marquee Rect", "Marquee Ellipse",
    "Lasso", "Polygon Lasso", "Wand", "Object Select",
    "&Bloom…", "&Dither…", "&Lens Correction…", "&Vignette…",
    "(no preview)", "Choose folder for imported project",
    "Everything in this file was imported.", "Import report",
    "Imported {count} layers — {w}×{h}", "PSD import failed",
    "{name} — {message}",
]

LANGS = {
    "ja": "日本語", "ko": "한국어", "fr": "Français", "de": "Deutsch",
    "it": "Italiano", "pt": "Português", "es": "Español", "vi": "Tiếng Việt",
    "tr": "Türkçe", "ar": "العربية", "hi": "हिन्दी", "id": "Bahasa Indonesia",
    "th": "ภาษาไทย",
}

en_table = json.load(open(DATA, encoding="utf-8"))["en"]
SYS = ("You are a localizer for a desktop image-editor app (Photoshop-like). "
       "Translate UI strings into the target language, concise like real software UI. "
       "Rules: keep leading '&' mnemonic prefix if present; keep trailing '…'; "
       "ALWAYS preserve {count}/{w}/{h}/{name}/{message} placeholders exactly; "
       "keep brand/tech words (PSD, PSD import). "
       'Output strict JSON: {"key": "translation"} covering every input key.')

try:
    results = json.load(open(OUT, encoding="utf-8"))
except Exception:
    results = {}

for lang, tname in LANGS.items():
    results.setdefault(lang, {})
    todo = [k for k in KEYS if not results[lang].get(k)]
    if not todo:
        continue
    lines = "\n".join(f"{k} => {en_table.get(k, k)}" for k in todo)
    prompt = (f"Target language: {tname} ({lang}). Translate each image-editor UI string to {tname}.\n\n{lines}")
    for attempt in (1, 2, 3):
        try:
            raw = text_client.chat(prompt, system=SYS, temperature=0.2,
                                   max_tokens=4000, json_mode=True)
            s = raw.strip()
            data = json.loads(s if s.startswith("{") else s[s.find("{"):s.rfind("}") + 1])
            got = 0
            for k in todo:
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    results[lang][k] = v.strip()
                    got += 1
            print(lang, f"{got}/{len(todo)}", flush=True)
            break
        except Exception as e:  # noqa: BLE001
            print(lang, "retry", attempt, str(e)[:100], flush=True)
            time.sleep(4)
    json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("DONE", flush=True)
