# -*- coding: utf-8 -*-
"""第二波 UI 键补译(由 scripts/_i18n_translate.py 机翻生成,人工可校订)。

覆盖首轮 i18n 清扫之后新增的键:这些键在主词典里是中文基线拷贝、
在补充词典 ui_strings 里各语言槽位是英文占位,导致非英语界面直接显示英文。
由 i18n.py 末尾 merge 进 T(主词典优先级高于补充词典)。
"""
from __future__ import annotations

WAVE2: dict[str, dict[str, str]] = {}
