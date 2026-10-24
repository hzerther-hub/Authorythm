# -*- coding: utf-8 -*-
"""生成 i18n 缺口基线快照(tests/_i18n_gaps.json)。

用法:
    python scripts/i18n_gap_baseline.py            # 只报告,不写
    python scripts/i18n_gap_baseline.py --write    # 写基线(修完一批就跑一次)

为什么用快照而不是手维护白名单:
手写的 ALLOW_MISSING 有 300 多条,每修一个键就要记得删一行,漏删就失去意义;
更糟的是它无法区分「已修」和「忘了记」。基线快照让测试只对**新增**缺口报错,
修掉的键自然从快照里消失 —— 债务可见、可递减、不会腐烂。

基线里的键分三类:
  undefined  被 tr() 调用但词典里没有 → 渲染成键名本身
  leak       Z 里有中文基准但部分语种无译文 → 非中文界面显示中文
  no_ja      日语槽 == 中文槽且不属于中日通用词
  no_ph      译文丢了模板占位符
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import i18n          # noqa: E402
from app.core import ui_strings as U  # noqa: E402

APP = ROOT / "app"
OUT = ROOT / "tests" / "_i18n_gaps.json"
PATTERNS = ("ui/**/*.py", "pipeline/**/*.py", "agents/**/*.py", "core/*.py")
SKIP_FILES = {"i18n.py", "ui_strings.py"}

# 中日共用汉字:这些词日语本来就那么写,ja 槽 == zh 槽不是漏译
JA_EQUIVOKENT = {
    "AI", "⤢", "生成中", "生成中…", "生成中 {}", "停止", "保存", "位置", "文字",
    "人", "成功", "生成", "水彩", "失败", "确定", "取消", "名称", "标题",
}

import re  # noqa: E402
PLACEHOLDER = re.compile(r"\{[0-9a-zA-Z_]*\}")


def used_keys() -> set[str]:
    out: set[str] = set()
    for pat in PATTERNS:
        for path in sorted(APP.glob(pat)):
            if path.name in SKIP_FILES or "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                fn = node.func
                nm = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if nm != "tr":
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    out.add(first.value)
    return out


def collect() -> dict:
    used = used_keys()
    undefined = sorted(k for k in used if k not in i18n.Z and k not in U.S)

    leak: dict[str, list[str]] = {}
    for lang in U.LANGS:
        if lang == "zh":
            continue
        for key in set(i18n.Z) | set(U.S):
            val = U.ui_lookup(lang, key)
            if val is None:
                val = i18n.T.get(lang, {}).get(key)
            zh = i18n.Z.get(key)
            if val is None or (zh is not None and val == zh):
                leak.setdefault(key, []).append(lang)

    iz, ija = 0, U.LANGS.index("ja")
    no_ja = sorted(k for k, v in U.S.items()
                   if len(v) == 15 and v[ija] == v[iz] and v[iz] not in JA_EQUIVOKENT)

    no_ph: dict[str, list[str]] = {}
    for key, vals in U.S.items():
        if len(vals) != 15:
            continue
        src = set(PLACEHOLDER.findall(vals[0]))
        if not src:
            continue
        for idx, lang in enumerate(U.LANGS):
            if lang == "zh":
                continue
            if src - set(PLACEHOLDER.findall(vals[idx])):
                no_ph.setdefault(key, []).append(lang)

    return {
        "_note": ("i18n 已知缺口基线。由 scripts/i18n_gap_baseline.py 生成,"
                  "tests/test_i18n_coverage.py 用它挡住**新增**缺口。"
                  "修好一个键就从这里删掉一行,债务只会递减。"),
        "undefined": undefined,
        "leak": {k: sorted(set(v)) for k, v in sorted(leak.items())},
        "no_ja": no_ja,
        "no_placeholder": {k: sorted(set(v)) for k, v in sorted(no_ph.items())},
    }


def main() -> int:
    gaps = collect()
    print(f"undefined(露键名) {len(gaps['undefined'])}")
    print(f"leak(漏译)       {len(gaps['leak'])} 键 / "
          f"{sum(len(v) for v in gaps['leak'].values())} 处")
    print(f"no_ja(日语同中文) {len(gaps['no_ja'])}")
    print(f"no_placeholder    {len(gaps['no_placeholder'])} 键 / "
          f"{sum(len(v) for v in gaps['no_placeholder'].values())} 处")
    if "--write" in sys.argv:
        OUT.write_text(json.dumps(gaps, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        print(f"\n已写入 {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())