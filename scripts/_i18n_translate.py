# -*- coding: utf-8 -*-
"""一次性脚本:补齐第二波 i18n 键(新增后未走首轮清扫,所有非英语语言都显示英文)。

用项目默认文本模型把 193 个键翻成 13 种语言,增量写 docs/_i18n_wave2_raw.json(可断点重跑)。
跑完后由 _i18n_wave2_gen.py 生成 app/core/i18n_wave2.py 补丁模块。
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "E:/pydrama")
from app.core import i18n          # noqa: E402
from app.ai import text_client     # noqa: E402
from app.core.ui_strings import S  # noqa: E402

zh = i18n.Z
lang_idx = {code: i for i, (code, _) in enumerate(i18n.LANGS)}
LANG_NAME = dict(i18n.LANGS)
OUT = "docs/_i18n_wave2_raw.json"


def en_of(key: str) -> str:
    v = i18n.T.get("en", {}).get(key)
    if v:
        return v
    row = S.get(key) or []
    return (row[1] if len(row) > 1 else None) or ""


def shows_english(lang: str, key: str) -> bool:
    """tr() 在该语言下最终是否落到英文值(= 未翻译)。"""
    zh_base = zh.get(key)
    en = en_of(key)
    val = i18n.T.get(lang, {}).get(key)
    if not val or (zh_base is not None and val == zh_base):
        row = S.get(key) or []
        i = lang_idx[lang]
        sup = row[i] if i < len(row) else None
        if sup and sup != zh_base:
            val = sup
    if not val:
        val = en or zh_base or key
    return bool(en) and val == en and en != zh_base


langs = [l for l in i18n.T if l not in ("zh", "en")]
keys, seen = [], set()
for lang in langs:
    for key in list(zh.keys()) + [k for k in S if k not in zh]:
        if key not in seen and shows_english(lang, key):
            seen.add(key)
            keys.append(key)
print("keys to translate:", len(keys), flush=True)

try:
    results = json.load(open(OUT, encoding="utf-8"))
except Exception:
    results = {}

CHUNK = 40
SYS = ("You are a localizer translating UI strings of a desktop AI short-drama studio app. "
       "Translate each entry into the target language, concise like real software UI text. "
       "ALWAYS preserve {} placeholders, and keep brand/tech words as-is (TikTok, RedNote, 720p, 3D, AI). "
       'Output strict JSON object: {"key": "translation", ...} covering every input key. No extra keys.')

for lang in langs:
    results.setdefault(lang, {})
    todo = [k for k in keys if not results[lang].get(k)]
    if not todo:
        continue
    tname = LANG_NAME[lang]
    for i in range(0, len(todo), CHUNK):
        batch = todo[i:i + CHUNK]
        lines = "\n".join(f"{k} | {en_of(k)} | {zh.get(k) or k}" for k in batch)
        prompt = (f"Target language: {tname} ({lang}). Translate each UI string to {tname}. "
                  f'Lines are "key | english source | chinese source".\n\n{lines}')
        for attempt in (1, 2, 3):
            try:
                raw = text_client.chat(prompt, system=SYS, temperature=0.2,
                                       max_tokens=8000, json_mode=True)
                s = raw.strip()
                data = json.loads(s if s.startswith("{") else s[s.find("{"):s.rfind("}") + 1])
                got = 0
                for k in batch:
                    v = data.get(k)
                    if isinstance(v, str) and v.strip():
                        results[lang][k] = v.strip()
                        got += 1
                print(lang, i // CHUNK + 1, f"{got}/{len(batch)}", flush=True)
                break
            except Exception as e:  # noqa: BLE001
                print(lang, "retry", attempt, str(e)[:100], flush=True)
                time.sleep(4)
        json.dump(results, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("DONE", flush=True)
