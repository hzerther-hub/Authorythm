# -*- coding: utf-8 -*-
"""i18n 覆盖度守卫:新增的界面文案不许露键名、不许漏中文、不许丢占位符。

起因是实测踩到的两个 bug:
  · `nav_dashboard` 键在词典里**根本不存在**,但构造时用 `LABEL_OVERRIDE`
    硬编码了「仪表盘」,第一次进来看着正常;一切换语言,`retranslate()`
    直接 `tr(label_key)` → 按钮上写着 `nav_dashboard`。
  · `chat_edit_nav` 只在中文基准表里有值,没有任何译文 → 15 个语种全漏中文。

这类问题的共同点是**不会抛异常**,只会静默显示错的东西。所以必须用测试盯住。

## 为什么要基线快照

本仓存量缺口不小(147 个键露键名、170 个键漏译、合计 2192 处),一次补完
需要数千条译文。本测试改为比对 `tests/_i18n_gaps.json` 基线:
  · **新增**缺口 → 测试红,并告诉你补哪里;
  · 修好的键 → 从基线删一行(跑 `python scripts/i18n_gap_baseline.py --write`),
    债务只减不增,且随时能报出还剩多少。
手写白名单做不到这点:300 多条手维护的条目必然腐烂。

## 一个容易写错的判据

判断「界面是不是漏了中文」**不能**用「字符串含不含汉字」。日语大量用汉字
当词素(`設定`/`保存`/`チャット編集`/`三人称限定`),按字符集判断会把正确
的日语译文全误报成漏译。本文件一律用「与中文基准逐字相同」做判据。
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from app.core import i18n
from app.core import ui_strings as U

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
BASELINE = Path(__file__).resolve().parent / "_i18n_gaps.json"

PATTERNS = ("ui/**/*.py", "pipeline/**/*.py", "agents/**/*.py", "core/*.py")
SKIP_FILES = {"i18n.py", "ui_strings.py"}

PLACEHOLDER = re.compile(r"\{[0-9a-zA-Z_]*\}")
# 「含汉字」判据只看**表意文字**(U+4E00–U+9FFF),不含 CJK 标点与全角符号。
# 原因:「、」是中文顿号,各语言通用同一个字形 —— 拿它当「漏译」是误报。
# 单位/符号(如 total_dur 的 '{}s')同理。
_CJK = re.compile(r"[一-鿿]")

# 中日共用汉字:这些词日语本来就那么写,ja 槽 == zh 槽不是漏译。
# 与 scripts/i18n_gap_baseline.py 保持一致。
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
    "女", "男",                # 性别下拉项:日语就是「女/男」这两个字(克隆表单)
}

# 拉丁字母语种(不用汉字)。这些语种渲染出**汉字**就是中文漏出来了。
# ja/ko 合法使用汉字(词素),ar/hi/th 另有一条守卫(见 NON_HAN_LANGS)。
_LATIN_SCRIPT_LANGS = {"en", "fr", "de", "es", "pt", "it", "vi", "tr", "id"}
# 例外:这些键的值里**故意**含中文 —— 说明文字举的例子本身就是中文词
# (功能就是「把『他』批量替换成『她』」),不是漏译。
HAN_IN_QUOTES_OK = {"kbd_r_desc"}

# 不用汉字、也不用本族文字的语种:ar(阿拉伯文)/ hi(天城文)/ th(泰文)。
# 它们的槽里出现汉字 = 中文漏出来了(2026-10-26 实测 ar 槽整段是中文)。
NON_HAN_LANGS = ("ar", "hi", "th")


def _baseline() -> dict:
    if not BASELINE.exists():  # pragma: no cover
        pytest_fail("基线快照不存在,先跑 python scripts/i18n_gap_baseline.py --write")
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def pytest_fail(msg: str):  # pragma: no cover —— 只是让上面那句能读
    raise AssertionError(msg)


def _used_tr_keys() -> set[str]:
    """所有 `tr("字面量")` 的键。

    只认字面量参数 —— `tr(some_var)` 运行期才知道,静态扫不到,不在本测试覆盖内。
    """
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


def _zh_baseline(key: str) -> str | None:
    """取该键的中文基准。

    为什么不能只看 `i18n.Z`:Z 是**中文基准表**,而补充词典 S 里有 324 个 S-only 键
    (其中 72 个还是中文名)根本不在 Z 里 → `Z.get(key)` 返回 None,
    漏译判据直接 `continue` 跳过,**这 324 个键从来没被漏译判据看过**。
    S 的第 0 槽就是中文基准,拿它兜底。
    """
    base = i18n.Z.get(key)
    if base is not None:
        return base
    row = U.S.get(key)
    if isinstance(row, list) and len(row) == 15:
        return row[0]
    return None


def _leaks() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for lang in U.LANGS:
        if lang == "zh":
            continue
        table = i18n.T.get(lang, {})
        for key in set(i18n.Z) | set(U.S):
            val = U.ui_lookup(lang, key)
            if val is None:
                val = table.get(key)
            zh = _zh_baseline(key)
            if val is None:
                out.setdefault(key, []).append(lang)
                continue
            # 拉丁字母语种渲染出**汉字** → 中文漏出来了。
            # 为什么不能只靠「与中文基准逐字相同」:差一个字就逃逸。
            # 实测(2026-10-26):ar 槽整段是中文原文,只把「妆造」写成「妆容」,
            # 就同时躲过了漏译判据和运行时体检(后者对非拉丁语种的判据是
            # 「没有本族文字却有拉丁字母」,而中文**没有拉丁字母**)。
            if (lang in _LATIN_SCRIPT_LANGS and _CJK.search(val)
                    and key not in HAN_IN_QUOTES_OK):
                out.setdefault(key, []).append(lang)
                continue
            if zh is None or val != zh:
                continue
            # 槽位与中文基准逐字相同才算「漏中文」。两个例外:
            # ① 基准本身不含汉字(单位/符号,如 total_dur 的 '{}s'),
            #    别语言原样复用是正确的,谈不上漏中文;
            # ② ja 且值在中日共用汉字表里(保存/停止/生成中…) —— 日语本来就那么写。
            if _CJK.search(zh) and not (lang == "ja" and zh in JA_EQUIVOKENT):
                out.setdefault(key, []).append(lang)
    return {k: sorted(set(v)) for k, v in out.items()}


def _han_in_non_han_languages() -> list[tuple[str, str]]:
    """ar/hi/th 渲染值里出现汉字(这三个语种不用汉字)。"""
    out: list[tuple[str, str]] = []
    old = i18n.current_language()
    try:
        for lang in NON_HAN_LANGS:
            i18n.set_language(lang)
            for key in set(i18n.Z) | set(U.S):
                if key in HAN_IN_QUOTES_OK:
                    continue
                v = i18n.tr(key)
                if v and _CJK.search(v):
                    out.append((key, lang))
    finally:
        i18n.set_language(old)
    return sorted(out)


def _ja_equals_zh() -> list[str]:
    iz, ija = 0, U.LANGS.index("ja")
    # 与 leak 判据同口径:基准不含汉字的(标点「、」、破折号「—」、品牌字样),
    # ja 槽逐字相同是**应该**的,不算「日语未译」。
    return sorted(k for k, v in U.S.items()
                  if len(v) == 15 and v[ija] == v[iz]
                  and v[iz] not in JA_EQUIVOKENT and _CJK.search(v[iz]))


def _placeholder_loss() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
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
                out.setdefault(key, []).append(lang)
    return {k: sorted(set(v)) for k, v in out.items()}


# 葡萄牙语专有词:这些词/词形在**西班牙语里不存在,或拼法不同**。
# 为什么单独盯西语槽:葡语和西语都是拉丁字母,「露中文」判据(汉字)抓不到,
# 「回落英文」判据(与英文槽逐字相同)也抓不到 —— 2026-10-26 那轮合并
# 把 5 条葡语译文原样塞进了西语槽,西班牙语用户看到的是葡萄牙语,
# 而所有既有判据**一个都没报**。
PT_ONLY_TOKENS = (
    "você", "não", "pela ", "nesta ", "neste ", "ao clicar", "a escolhida",
    "oito acima", "são calculados", "envie pela", "suporta imagens",
    "Pesquise imagens", "de imagem do chat", "edição de imagem",
    "Função", "funções", "bem sucedido", "confirme que o ponto",
    "o corpo existente", "Papéis", "classificado como duplicado",
)


def _truncated_slots() -> list[tuple[str, str]]:
    """译文只剩占位符(正文/量词被吞)→ 界面上是个孤零零的数字。

    判据要收紧到「中文基准**同时**含占位符和实词」,否则碎片键会误报:
    '请先生成「' 这种碎片键的正确译法就是半个引号(没有实词),
    ' 字)' 同理 —— 它们的中文基准本来就不含实词。
    """
    out: list[tuple[str, str]] = []
    for key, vals in U.S.items():
        if len(vals) != 15:
            continue
        zh = vals[0]
        if not PLACEHOLDER.search(zh):
            continue
        if not any(c.isalpha() for c in zh):
            continue
        for idx, lang in enumerate(U.LANGS):
            if lang == "zh":
                continue
            if not any(c.isalpha() for c in vals[idx]):
                out.append((key, lang))
    return sorted(out)


def _spanish_with_portuguese() -> list[tuple[str, str]]:
    """西语槽里出现葡萄牙语专有词。"""
    out: list[tuple[str, str]] = []
    ies = U.LANGS.index("es")
    for key, vals in U.S.items():
        if len(vals) != 15:
            continue
        es = vals[ies]
        low = es.lower()
        for tok in PT_ONLY_TOKENS:
            if tok.lower() in low:
                out.append((key, tok))
                break
    return sorted(out)


def _zh_hant_problems() -> tuple[list[str], list[str], list[str]]:
    """繁中表(ZH-HANT)的三类问题:缺值 / 值不对 / 显英文。

    为什么单列:漏译判据 `_leaks()` 走的是 U.LANGS(15 语言,**不含 zh-Hant**),
    繁中这条线长期没人看 —— 实测就是靠这个盲区,繁中界面整体显示英文/简体
    烂了很久没人发现。所以这里单独用精确判据查,不走基线。
    """
    from app.core.zh_convert import to_traditional

    i18n.ensure_zh_hant()
    zht = i18n.T["zh-Hant"]
    missing: list[str] = []
    wrong: list[str] = []
    english: list[str] = []

    for key in set(i18n.Z) | set(U.S):
        val = zht.get(key)
        if val is None:
            missing.append(key)
            continue
        if key in i18n.Z:
            base = i18n.Z[key]
        else:
            row = U.S[key]
            base = row[0] if isinstance(row, list) and len(row) == 15 else None
        if base is None:
            continue
        # 期望值 = OpenCC 自动转换,人工校订表优先
        expect = to_traditional(base)
        if val != expect and val != i18n.ZH_HANT_MANUAL.get(key):
            wrong.append(key)
        # 显英文:值等于英文表的值,说明又从 T["en"] 继承了
        en_val = i18n.T["en"].get(key)
        if en_val is not None and val == en_val and val != base:
            english.append(key)

    return sorted(missing), sorted(wrong), sorted(english)


def _assert_no_new_gaps(kind, current, base, hint):
    if isinstance(base, dict):
        new = {k: v for k, v in current.items() if set(v) - set(base.get(k, []))}
    else:
        new = [k for k in current if k not in set(base)]
    if not new:
        remaining = len(current) if not isinstance(current, dict) else len(current)
        print(f"[i18n] {kind}:无新增(存量 {remaining})")
        return
    detail = "\n".join(f"    {k}: {v}" if isinstance(v, list) else f"    {k!r}"
                       for k, v in (new.items() if isinstance(new, dict)
                                    else ((k, None) for k in new)))
    raise AssertionError(
        f"i18n {kind} 新增 {len(new)} 个(基线 {BASELINE.name} 未收录):\n"
        f"{detail}\n\n{hint}")


# ---------------------------------------------------------------- 守卫

def test_no_new_undefined_tr_keys():
    """露键名:被 tr() 调用但词典里没有 → 按钮上直接显示 `batch_capped` 这种标识符。"""
    base = _baseline()
    cur = sorted(k for k in _used_tr_keys() if k not in i18n.Z and k not in U.S)
    _assert_no_new_gaps(
        "露键名", cur, base.get("undefined", []),
        "修法:app/core/i18n.py 的 Z 加中文基准 + app/core/ui_strings.py 补 15 语言。")


def test_no_new_translation_leaks():
    """漏译:切到非中文语种时直接显示中文基准。"""
    base = _baseline()
    cur = _leaks()
    _assert_no_new_gaps(
        "漏译", cur, base.get("leak", {}),
        "修法:app/core/ui_strings.py 补 15 语言条目(每个 list 必须是 15 个元素)。")


def test_no_new_japanese_equal_chinese():
    """日语槽与中文逐字相同,且不属于中日通用词。"""
    base = _baseline()
    cur = _ja_equals_zh()
    _assert_no_new_gaps(
        "日语未译", cur, base.get("no_ja", []),
        "修法:补真正的日语;确实与中文同形的,加进本文件与 "
        "scripts/i18n_gap_baseline.py 的 JA_EQUIVOKENT。")


def test_no_new_placeholder_loss():
    """译文丢了模板占位符 → 渲染少数字/参数(「0 segments」而不是「12 segments」)。"""
    base = _baseline()
    cur = _placeholder_loss()
    _assert_no_new_gaps(
        "占位符丢失", cur, base.get("no_placeholder", {}),
        "修法:译文里保留与中文基准相同的 {}/ {name} 占位符。")


# ---------------------------------------------------------------- 定点守卫

def test_no_truncated_translation():
    """译文只剩占位符 —— 量词/正文被吞。

    实测(2026-10-26):'items_n'(中文基准 '{0} 个')有 7 个语种只剩 '{0}',
    界面上显示成孤零零的数字;'＋ 添加{}' 的西语槽、'确定删除「{}」?…'
    的韩语/印地语槽同样被清空。

    这条是**硬约束不走基线** —— 译文只剩占位符永远是 bug,不存在「合理」情形。
    """
    bad = _truncated_slots()
    assert not bad, (
        f"有 {len(bad)} 个译文只剩占位符(量词/正文被吞):{bad[:10]}\n"
        f"修法:app/core/ui_strings.py 里补齐该语种的名词/量词,别只留 {{}}。")


def test_no_spanish_slot_contains_portuguese():
    """西语槽不能出现葡萄牙语专有词。

    实测(2026-10-26):合并译员把 5 条葡语译文原样塞进西语槽,
    因为葡西都是拉丁字母,「露中文」「回落英文」两条判据**一个都没报**。
    """
    bad = _spanish_with_portuguese()
    assert not bad, (
        f"有 {len(bad)} 个西语槽含葡萄牙语专有词:{bad[:10]}\n"
        f"修法:app/core/ui_strings.py 里把 es 槽重译成西班牙语。")


def test_no_han_chars_in_non_han_languages():
    """ar/hi/th 的槽里不能出现汉字。

    实测(2026-10-26):ar 槽整段是中文原文(只差一个字就躲过了逐字比较的漏译判据),
    ar 槽里塞了个汉字「切换」,hi 槽开头留了个「第」,th 槽结尾留了个「生效」。
    """
    bad = _han_in_non_han_languages()
    assert not bad, (
        f"有 {len(bad)} 个非汉字语种的槽里含汉字:{bad[:10]}\n"
        f"修法:app/core/ui_strings.py 里把该语种重译成自己语言。")


def test_zh_hant_table_is_complete():
    """繁中表必须每个键都有值、值是对的、且不能显英文。

    这条是**硬约束不走基线** —— 繁中表由「简体基准 → OpenCC → 人工表」生成,
    本来就不该有缺口;有了缺口就是代码坏了(不是「存量债」)。

    修之前的实测:繁中表从 T["en"] 派生,1554 个基准键里只有 107 键是真繁体,
    1251 键显示简体、1446 键显示英文,1446 个键里没有任何一个语种检查会发现
    —— 因为漏译判据只扫 U.LANGS(15 语言),zh-Hant 不在里面。
    """
    from app.core import zh_convert

    if not zh_convert.available():
        pytest.skip("opencc 未安装,繁中表退化为简体,本项无法校验")

    missing, wrong, english = _zh_hant_problems()
    assert not missing, (
        f"繁中表缺 {len(missing)} 个键(会回退成英文):{missing[:10]}\n"
        f"修法:确认 app/core/i18n.py 的 _build_zh_hant() 覆盖了 Z 与 ui_strings.S。")
    assert not wrong, (
        f"繁中表有 {len(wrong)} 个键与 OpenCC 基准/人工表都不符:{wrong[:10]}\n"
        f"修法:改 app/core/i18n.py 的 ZH_HANT_MANUAL,或检查 _build_zh_hant() 的合并顺序。")
    assert not english, (
        f"繁中表有 {len(english)} 个键显英文(又从 T['en'] 继承了):{english[:10]}\n"
        f"修法:检查 _build_zh_hant() 是否真的用 OpenCC 基准覆盖了 T['zh-Hant']。")


def test_zh_hant_renders_chinese_not_english():
    """抽几个顶栏/导航键,确认繁中模式下真的出繁体而不是英文或简体。"""
    from app.core import zh_convert

    if not zh_convert.available():
        pytest.skip("opencc 未安装,本项无法校验")

    old = i18n.current_language()
    try:
        i18n.set_language("zh-Hant")
        for key in ("nav_projects", "nav_dashboard", "new_project", "settings",
                    "episodes", "raw_content", "storyboard"):
            v = i18n.tr(key)
            assert v and v != key, f"zh-Hant 下 {key} 渲染成键名/空串"
            assert v != i18n.T["en"].get(key), f"zh-Hant 下 {key} 显示英文:{v!r}"
    finally:
        i18n.set_language(old)


def test_navigation_labels_never_fall_back():
    """顶栏三个导航键必须有真译文 —— 这条单列,因为它已经真炸过。

    `nav_dashboard` 曾经键都不存在,靠硬编码中文蒙混过关,一切换语言就露馅。
    """
    old = i18n.current_language()
    try:
        for lang in ("zh", "en", "ja", "fr", "de", "es", "pt"):
            i18n.set_language(lang)
            for key in ("nav_dashboard", "nav_projects", "chat_edit_nav"):
                v = i18n.tr(key)
                assert v and v != key, f"{lang} 下 {key} 渲染成键名/空串"
                if lang != "zh":
                    assert v != i18n.Z[key], f"{lang} 下 {key} 回退成中文: {v!r}"
    finally:
        i18n.set_language(old)


def test_baseline_has_no_stale_entries():
    """基线里不该再有「已经修好」的条目 —— 否则债务统计会失真。"""
    base = _baseline()
    stale_undef = set(base.get("undefined", [])) & (set(i18n.Z) | set(U.S))
    assert not stale_undef, (
        f"基线里这些键已经有定义了,请删掉:{sorted(stale_undef)[:10]}\n"
        f"或跑 python scripts/i18n_gap_baseline.py --write 刷新基线。")

    live_leak = set(_leaks())
    stale_leak = set(base.get("leak", {})) - live_leak
    assert not stale_leak, (
        f"基线里这些漏译已修复,请删掉:{sorted(stale_leak)[:10]}\n"
        f"或跑 python scripts/i18n_gap_baseline.py --write 刷新基线。")
