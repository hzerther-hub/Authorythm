"""运行时体检:切到每个语种,看界面**真正渲染**出来的是什么。

为什么必须查运行时而不是查表:各语种主表是从英文表继承的
(`T["ja"] = _t(T["en"], ...)`),所以原始表里 ja 槽写着 'Settings' 是**正常**的 ——
tr() 会用补充词典(ui_strings.S)里该语种的译文顶掉。
查原始表会把这 1700 个键全报成「日语显示英文」,全是假警报。

这里直接调 tr(),测的是用户真正看到的东西。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import i18n  # noqa: E402
from app.core import ui_strings as U  # noqa: E402

# 该语种「用自己书写系统」的判据:槽里出现拉丁文且不含本族文字 → 可疑
SCRIPT = {
    "ar": r"[؀-ۿ]",
    "hi": r"[ऀ-ॿ]",
    "th": r"[฀-๿]",
    "ja": r"[぀-ヿ一-鿿]",
    "ko": r"[가-힯]",
}
COMPILED = {k: re.compile(v) for k, v in SCRIPT.items()}
LATIN = re.compile(r"[A-Za-z]")
CJK = re.compile(r"[一-鿿]")

old = i18n.current_language()
rows = {}
eng_rows = {}
try:
    for lang, _name in i18n.LANGS:
        if lang in ("zh", "zh-Hant"):
            continue
        i18n.set_language(lang)
        for key in set(i18n.Z) | set(U.S):
            rendered = i18n.tr(key)
            if not rendered.strip():
                continue
            pat = COMPILED.get(lang)
            if pat:
                # 非拉丁书写系统:渲染结果里没有本族文字、却有拉丁字母 → 疑似回落英文
                if not pat.search(rendered) and LATIN.search(rendered):
                    rows.setdefault(key, {})[lang] = rendered
            else:
                # 拉丁书写系统的语种:渲染结果**含汉字** → 漏译(中文漏出来了)
                if CJK.search(rendered):
                    rows.setdefault(key, {})[lang] = rendered
            # 与英文槽**逐字相同** → 机翻没翻,直接留了英文。
            # 拉丁书写系统的语种漏成英文时,上面的汉字判据抓不到,靠这条兜。
            #
            # 英文基准要取「**有效英文值**」而不是 T["en"]:T 是从 Z(中文基准表)派生的,
            # 只含 Z 里的键;而 S(补充词典)里有 324 个键是 S-only(其中 72 个还是中文名),
            # 这些键在 T["en"] 里根本没有 → en_val 为 None → 这条判据对它们**从未生效**。
            # 实测就漏掉了 ',{} 章失败'(vi/fr/de/es/pt/it 六个语种全是英文原文)。
            en_val = i18n.T["en"].get(key)
            if en_val is None:
                row = U.S.get(key)
                if row is not None:
                    en_val = row[U.LANGS.index("en")]
            if en_val and rendered == en_val and en_val.strip():
                eng_rows.setdefault(key, {})[lang] = rendered
finally:
    i18n.set_language(old)

print(f"运行时仍显示错语言的键:{len(rows)}")
total = 0
for key, langs in sorted(rows.items()):
    total += len(langs)
    print(f"\n== {key[:66]!r}")
    for lang, val in langs.items():
        print(f"   {lang}: {val[:100]!r}")
print(f"\n合计槽位:{total}")

print(f"\n\n{'=' * 60}\n运行时直接显示英文(与英文槽逐字相同)的键:{len(eng_rows)}")
etotal = 0
for key, langs in sorted(eng_rows.items()):
    etotal += len(langs)
    print(f"\n== {key[:66]!r}")
    for lang, val in langs.items():
        print(f"   {lang}: {val[:100]!r}")
print(f"\n合计槽位:{etotal}")
