"""i18n 完整度审计(16 语言全覆盖,含 zh-Hant)。

为什么单独写一个:tests/test_i18n_coverage.py 是**回归守卫**(只看「有没有比基线
更差」),回答不了「现在还差多少」。这个脚本回答后者,用来定期体检。

覆盖 scripts/i18n_gap_baseline.py 漏掉的一格:**zh-Hant**。
基线脚本只扫 ui_strings.LANGS(15 语言,不含 zh-Hant),所以繁中这条线
长期没人看 —— 实测就是靠这个盲区,繁中界面整体显示英文/简体烂了很久。

用法:
    python scripts/i18n_audit.py            # 人读报告
    python scripts/i18n_audit.py --json     # 机读(便于接 CI)
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import i18n  # noqa: E402
from app.core import ui_strings as U  # noqa: E402
from app.core.zh_convert import to_traditional  # noqa: E402

APP = ROOT / "app"
PATTERNS = ("ui/**/*.py", "pipeline/**/*.py", "agents/**/*.py", "core/*.py")
SKIP_FILES = {"i18n.py", "ui_strings.py"}
PLACEHOLDER = re.compile(r"\{[0-9a-zA-Z_]*\}")
# 「含汉字」只看表意文字(U+4E00–U+9FFF),不含 CJK 标点与全角符号 ——
# 「、」是中文顿号,各语言通用同一字形,当「漏译」判是误报。
_CJK = re.compile(r"[一-鿿]")

# 中日共用汉字:这些词日语本来就那么写,ja 槽 == zh 槽不是漏译。
# 与 tests/test_i18n_coverage.py、scripts/i18n_gap_baseline.py 保持一致。
JA_EQUIVOKENT = {
    "AI", "⤢", "生成中", "生成中…", "生成中 {}", "停止", "保存", "位置", "文字",
    "人", "成功", "生成", "水彩", "失败", "确定", "取消", "名称", "标题",
    # 「◑ 生成中…」:前缀是状态图标,「生成中…」本身日语照抄。
    "◑ 生成中…",
    # 以下几组日语与中文同形,是**正确**的日文写法,不是漏译:
    "合成中…",                 # 合成中…(朗读合成中)
    "LLM 解析",                # LLM 解析(技术标签)
    "生成中 {done}/{total}",   # 生成中 {done}/{total}
    "生成中 {}%",              # 生成中 {}%
    "{0}/{1} 成功",            # {0}/{1} 成功
}

# 拉丁字母语种(不用汉字)。这些语种渲染出汉字 = 中文漏出来了。
# ja/ko 合法使用汉字;ar/hi/th 由 tests 的独立硬守卫覆盖。
LATIN_SCRIPT_LANGS = {"en", "fr", "de", "es", "pt", "it", "vi", "tr", "id"}
# 例外:值里**故意**含中文(说明文字举的例子本身就是中文词)。
HAN_IN_QUOTES_OK = {"kbd_r_desc"}


def used_tr_keys() -> dict[str, list[str]]:
    """所有 tr("字面量") 的键 → 调用处。只认字面量参数(tr(some_var) 静态扫不到)。"""
    out: dict[str, list[str]] = defaultdict(list)
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
                    out[first.value].append(f"{path.as_posix()}:{node.lineno}")
    return out


def audit() -> dict:
    used = used_tr_keys()
    i18n.ensure_zh_hant()
    zht = i18n.T["zh-Hant"]
    all_langs = [lang for lang, _ in i18n.LANGS]
    non_zh = [lang for lang in all_langs if lang != "zh"]

    # ── 1. 露键名:tr() 调了但词典里没有 ──
    undefined = sorted(k for k in used if k not in i18n.Z and k not in U.S)
    keyname = [k for k in undefined if not _CJK.search(k)]

    # ── 2. 漏译:键在 Z(有中文基准),某语种却显示中文 ──
    # zh-Hant 不在这轮里扫:它的「正确值」是 OpenCC 转出来的繁体,和简体基准
    # 逐字相同是正常的(「全部」繁简同形),拿简体去判它必然全误报。
    # 繁中单独在第 3 步用精确判据查。
    leak: dict[str, list[str]] = {}
    for lang in non_zh:
        if lang == "zh-Hant":
            continue
        for key in set(i18n.Z) | set(U.S):
            val = U.ui_lookup(lang, key)
            if val is None:
                val = i18n.T.get(lang, {}).get(key)
            # 中文基准:优先 Z;Z 里没有的(324 个 S-only 键)用补充词典第 0 槽兜底,
            # 否则这批键的基准为 None → 直接跳过,从来没被漏译判据看过。
            zh = i18n.Z.get(key)
            if zh is None:
                row = U.S.get(key)
                zh = row[0] if isinstance(row, list) and len(row) == 15 else None
            if val is None:
                leak.setdefault(key, []).append(lang)
                continue
            # 拉丁字母语种渲染出汉字 → 中文漏出来了(逐字相同会漏掉差一个字的)。
            if (lang in LATIN_SCRIPT_LANGS and _CJK.search(val)
                    and key not in HAN_IN_QUOTES_OK):
                leak.setdefault(key, []).append(lang)
                continue
            if zh is None or val != zh:
                continue
            if not _CJK.search(zh):
                continue
            # 日语大量汉字词素与中文同形(保存/停止/生成中…),不是漏译。
            if lang == "ja" and zh in JA_EQUIVOKENT:
                continue
            leak.setdefault(key, []).append(lang)
    leak = {k: sorted(set(v)) for k, v in leak.items()}

    # ── 3. zh-Hant:缺值 / 显英文 / 与 OpenCC 基准不符 ──
    zht_missing: list[str] = []
    zht_english: list[str] = []
    zht_wrong: list[str] = []
    for key in set(i18n.Z) | set(U.S):
        val = zht.get(key)
        if val is None:
            zht_missing.append(key)
            continue
        en_val = i18n.T["en"].get(key)
        if en_val is not None and val == en_val and val != i18n.Z.get(key):
            zht_english.append(key)
        if key in i18n.Z:
            expect = to_traditional(i18n.Z[key])
            if val != expect and val != i18n.ZH_HANT_MANUAL.get(key):
                zht_wrong.append(key)
        elif key in U.S and isinstance(U.S[key], list) and len(U.S[key]) == 15:
            expect = to_traditional(U.S[key][0])
            if val != expect:
                zht_wrong.append(key)

    # ── 4. 日语槽与中文逐字相同 ──
    iz, ija = 0, U.LANGS.index("ja")
    ja_same = sorted(k for k, v in U.S.items()
                     if len(v) == 15 and v[ija] == v[iz]
                     and v[iz] not in JA_EQUIVOKENT and _CJK.search(v[iz]))

    # ── 5. 占位符丢失 ──
    ph_loss: dict[str, list[str]] = {}
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
                ph_loss.setdefault(key, []).append(lang)
    ph_loss = {k: sorted(set(v)) for k, v in ph_loss.items()}

    # ── 6. 结构性统计 ──
    z_only = sorted(k for k in i18n.Z if k not in U.S)      # 有中文基准、零译文
    s_only = sorted(k for k in U.S if k not in i18n.Z)      # 有译文、没中文基准

    return {
        "undefined": undefined,
        "undefined_keyname": keyname,
        "leak": leak,
        "zht_missing": sorted(zht_missing),
        "zht_english": sorted(zht_english),
        "zht_wrong": sorted(zht_wrong),
        "ja_same_zh": ja_same,
        "placeholder_loss": ph_loss,
        "z_only": z_only,
        "s_only": s_only,
        "counts": {
            "langs": len(all_langs),
            "Z": len(i18n.Z),
            "S": len(U.S),
            "zh_Hant": len(zht),
            "undefined": len(undefined),
            "undefined_keyname": len(keyname),
            "leak_keys": len(leak),
            "leak_places": sum(len(v) for v in leak.values()),
            "zht_missing": len(zht_missing),
            "zht_english": len(zht_english),
            "zht_wrong": len(zht_wrong),
            "ja_same_zh": len(ja_same),
            "placeholder_loss_keys": len(ph_loss),
            "z_only": len(z_only),
            "s_only": len(s_only),
        },
    }


def report(res: dict) -> None:
    c = res["counts"]
    print(f"语言 {c['langs']} 种 · 中文基准 {c['Z']} 键 · 补充词典 {c['S']} 条 · "
          f"繁中表 {c['zh_Hant']} 键")
    print()
    print(f"  露键名(界面显示原始标识符)      {c['undefined_keyname']}")
    print(f"  露中文(tr 调用了但词典里没有)    {c['undefined'] - c['undefined_keyname']}")
    print(f"  漏译(有中文基准,某语种显示中文)  {c['leak_keys']} 键 / {c['leak_places']} 处")
    print(f"  繁中缺值                        {c['zht_missing']}")
    print(f"  繁中显英文                      {c['zht_english']}")
    print(f"  繁中值与 OpenCC 基准不符        {c['zht_wrong']}")
    print(f"  日语槽 == 中文                   {c['ja_same_zh']}")
    print(f"  占位符丢失                      {c['placeholder_loss_keys']} 键")
    print(f"  有中文基准但零译文              {c['z_only']}")
    print(f"  有译文但没中文基准              {c['s_only']}")
    if res["undefined_keyname"]:
        print("\n露键名明细:")
        for k in res["undefined_keyname"]:
            print(f"    {k!r}")
    if res["zht_english"]:
        print("\n繁中显英文明细(前 20):")
        for k in res["zht_english"][:20]:
            print(f"    {k!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    res = audit()
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        report(res)


if __name__ == "__main__":
    main()
