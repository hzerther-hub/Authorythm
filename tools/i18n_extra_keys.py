# -*- coding: utf-8 -*-
"""把「不在 app/ui 里、但会显示给用户看」的中文登记进语言包。

sweep 只扫 app/ui,像 NOVEL_STYLES 这种住在 pipeline/ 里、直接当标签显示的预设名会漏掉。
这里把它们补进 i18n.Z(中文基准),之后跑一次 autofill 就有了。

    py -3.13 -X utf8 tools/i18n_extra_keys.py
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline.novel import NOVEL_STYLES  # noqa: E402

# pipeline 里的常量:值是显示名,后面跟的提示词是发给模型的指令,不登记
EXTRA = [name for name, _prompt in NOVEL_STYLES]


def main() -> int:
    ipath = ROOT / "app" / "core" / "i18n.py"
    src = ipath.read_text(encoding="utf-8")
    todo = [k for k in EXTRA if f"{k!r}:" not in src]
    if not todo:
        print(f"无需新增,{len(EXTRA)} 个键都在 i18n.Z 里")
        return 0
    idx = src.index("\n}\n\ndef _t(")
    block = "".join(f" {k!r}: {k!r},\n" for k in todo)
    ipath.write_text(src[:idx] + block + src[idx:], encoding="utf-8")
    print(f"新增 {len(todo)} 个中文基准键:{todo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
