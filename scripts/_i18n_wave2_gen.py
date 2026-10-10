# -*- coding: utf-8 -*-
"""把 scripts/_i18n_translate.py 的机翻结果(docs/_i18n_wave2_raw.json)生成 i18n_wave2.py。"""
from __future__ import annotations

import json

RAW = "docs/_i18n_wave2_raw.json"
OUT = "app/core/i18n_wave2.py"

data = json.load(open(RAW, encoding="utf-8"))
# 丢空语言
data = {lang: kv for lang, kv in data.items() if kv}

lines = [
    '# -*- coding: utf-8 -*-',
    '"""第二波 UI 键补译(由 scripts/_i18n_translate.py 机翻生成,人工可校订)。',
    '',
    '覆盖首轮 i18n 清扫之后新增的键:这些键在主词典里是中文基线拷贝、',
    '在补充词典 ui_strings 里各语言槽位是英文占位,导致非英语界面直接显示英文。',
    '由 i18n.py 末尾 merge 进 T(主词典优先级高于补充词典)。',
    '"""',
    'from __future__ import annotations',
    '',
    'WAVE2: dict[str, dict[str, str]] = {',
]
for lang in sorted(data):
    lines.append(f'    "{lang}": {{')
    for k in sorted(data[lang]):
        v = str(data[lang][k]).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'        "{k}": "{v}",')
    lines.append('    },')
lines.append('}')
lines.append('')

open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines))
total = sum(len(v) for v in data.values())
print(f"written {OUT}: {len(data)} langs, {total} translations")
