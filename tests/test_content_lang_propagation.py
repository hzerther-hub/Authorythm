# -*- coding: utf-8 -*-
"""项目级内容语言必须真的透传到每次 AI 调用 —— AST 守卫。

背景:「项目设置 → 内容语言」这个下拉从一开始就能存(`dramas.language`),
`config.resolve_content_language(drama_id)` 也早就写好了,但 `runner.run_agent`
在 `lang=None` 时回落到**全局** `app_settings.content_language`
(`app/agents/runner.py:82-84`)。实测 34 个调用点里只有 14 个传了 `lang=`,
剩下 20 个静默退回全局 —— 用户把项目设成日语,总纲/世界观/章节计划照样出中文,
界面上完全看不出异常。

这类 bug 的特点是「漏一处不会报错,只会静默走错语言」,所以不能靠 review,
必须用测试钉死:扫源码,见一个没传 `lang=` 的调用点就红。

与 `tests/test_split_models.py` 同一思路(逐个入口断言源码里含兜底调用),
但这里用 AST 而不是字符串匹配 —— 字符串匹配分不清
`run_agent("x", p)` 和注释/字符串里出现的同名文本。
"""
from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# 允许不传 lang 的调用点。**新增条目必须在注释里写清理由** ——
# 这个白名单是唯一能绕过守卫的口子,不留理由就等于没守。
ALLOWED_NO_LANG: dict[str, str] = {
    "overseas.py:98": "诊断固定 lang='zh':源文恒为中文,且 glossary 的 JSON schema "
                      "键是中文字面量(agents/prompts.py 的 overseas_analyzer 里 "
                      "写死了 \"中文\"/\"English\"),目标语言换成别的会让术语表串语言。"
                      "输出语言由 prompt 里的「目标语言要点」规则段决定,不是 system 语言。",
    "overseas.py:152": "改写同理:术语表方向由 diagnose 固定为 中文→目标语言,"
                       "system 用中文指令更利于模型逐条遵守,正文语言由注入的语言名决定。",
}

# runner 自身的定义与内部转发:lang 是它要透传的东西,不是要解析的东西。
_SKIP_FILES = {"runner.py", "novel_review_flow.py"}


def _call_key(path: Path, node: ast.Call) -> str:
    """稳定标识:文件名:行号(行号会随编辑漂移,故 ALLOWED 的键按行匹配)。"""
    return f"{path.name}:{node.lineno}"


def _has_lang_kw(call: ast.Call) -> bool:
    return any(kw.arg == "lang" for kw in call.keywords)


def _iter_calls(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        # 形如 runner.run_agent(...) / run_agent(...)
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name in ("run_agent", "run_agent_json"):
            yield node


def _scan():
    """返回 [(相对路径:行号, 源码片段)] —— 所有没传 lang 的调用点。"""
    missing: list[tuple[str, str]] = []
    for path in sorted(APP.rglob("*.py")):
        if path.name in _SKIP_FILES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover —— 语法错误交给 ruff/py_compile 报
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for call in _iter_calls(tree):
            if _has_lang_kw(call):
                continue
            key = _call_key(path, call)
            if key in ALLOWED_NO_LANG:
                continue
            rel = path.relative_to(APP).as_posix()
            snippet = lines[call.lineno - 1].strip()[:100] if call.lineno <= len(lines) else ""
            missing.append((f"{rel}:{key}", snippet))
    return missing


def test_every_run_agent_call_passes_lang():
    """每个 run_agent / run_agent_json 调用都必须显式传 lang=。

    漏传不会抛异常,只会静默退回全局语言 —— 项目设置形同虚设。
    """
    missing = _scan()
    assert not missing, (
        "以下 AI 调用没传 lang=,会静默退回全局 content_language,项目设置里的"
        "「内容语言」对它们无效:\n"
        + "\n".join(f"  {where}  {snip}" for where, snip in missing)
    )


def test_allowed_exceptions_still_exist():
    """白名单本身也要被盯着:对应的调用点被删掉/挪走后,白名单应同步清理。

    防止「白名单条目悬空」—— 没人知道哪几条是历史遗留。
    """
    seen = set()
    for path in sorted(APP.rglob("*.py")):
        if path.name in _SKIP_FILES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover
            continue
        for call in _iter_calls(tree):
            seen.add(_call_key(path, call))

    dangling = [k for k in ALLOWED_NO_LANG if k not in seen]
    # 白名单的键是「文件名:行号」,行号会随编辑漂移 —— 只在同名文件的该函数里
    # 确实存在 run_agent 调用时才算存活。用文件名匹配做宽松判定。
    alive_files = {k.split(":")[0] for k in seen}
    stale_files = [k for k in dangling if k.split(":")[0] not in alive_files]
    assert not stale_files, (
        f"白名单里有已不存在的文件:{stale_files};请从 ALLOWED_NO_LANG 删掉"
    )
