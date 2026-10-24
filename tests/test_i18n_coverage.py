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

from app.core import i18n
from app.core import ui_strings as U

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
BASELINE = Path(__file__).resolve().parent / "_i18n_gaps.json"

PATTERNS = ("ui/**/*.py", "pipeline/**/*.py", "agents/**/*.py", "core/*.py")
SKIP_FILES = {"i18n.py", "ui_strings.py"}

PLACEHOLDER = re.compile(r"\{[0-9a-zA-Z_]*\}")

# 中日共用汉字:这些词日语本来就那么写,ja 槽 == zh 槽不是漏译。
# 与 scripts/i18n_gap_baseline.py 保持一致。
JA_EQUIVOKENT = {
    "AI", "⤢", "生成中", "生成中…", "生成中 {}", "停止", "保存", "位置", "文字",
    "人", "成功", "生成", "水彩", "失败", "确定", "取消", "名称", "标题",
}


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
            zh = i18n.Z.get(key)
            if val is None or (zh is not None and val == zh):
                out.setdefault(key, []).append(lang)
    return {k: sorted(set(v)) for k, v in out.items()}


def _ja_equals_zh() -> list[str]:
    iz, ija = 0, U.LANGS.index("ja")
    return sorted(k for k, v in U.S.items()
                  if len(v) == 15 and v[ija] == v[iz] and v[iz] not in JA_EQUIVOKENT)


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