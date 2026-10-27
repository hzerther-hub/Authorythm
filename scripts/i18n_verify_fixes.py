# -*- coding: utf-8 -*-
"""校验 i18n 修复表里的每一条都落在**正确的槽位下标**上。

为什么单独校验:修补脚本早期用 `line.replace(旧值, 新值, 1)` 改行,
而同一行的 en 槽与 ar 槽**值完全相同**(机翻没翻完,两处都留着同一段英文),
replace 打到了第一个(en 槽) —— 改 3 个键连锁串了 5 个槽,命令却报「成功」。
所以「改了」不等于「改对位置了」,必须按下标逐条核对。

用法:python scripts/i18n_verify_fixes.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import ui_strings as U  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))

from i18n_fix_mirror import FIXES as MIRROR_FIXES  # noqa: E402
from i18n_fix_mixed_lang import FIXES as MIXED_FIXES  # noqa: E402


def check(name: str, fixes: dict[str, dict[str, str]]) -> list[str]:
    bad: list[str] = []
    for key, langs in fixes.items():
        row = U.S.get(key)
        if row is None:
            bad.append(f"{name}: 键不在补充词典里:{key!r}")
            continue
        for lang, want in langs.items():
            idx = U.LANGS.index(lang)
            got = row[idx]
            if got != want:
                bad.append(
                    f"{name}: {key[:32]!r} / {lang} 槽位不符\n"
                    f"      期望: {want[:110]!r}\n"
                    f"      实际: {got[:110]!r}")
    return bad


def main() -> None:
    problems = check("mirror", MIRROR_FIXES) + check("mixed", MIXED_FIXES)
    total = sum(len(v) for v in MIRROR_FIXES.values()) + sum(len(v) for v in MIXED_FIXES.values())
    if problems:
        print(f"!! {len(problems)} 处不符:")
        for p in problems:
            print("   ", p)
        raise SystemExit(1)
    print(f"校验通过:{total} 个槽位全部落在正确位置")


if __name__ == "__main__":
    main()
