# -*- coding: utf-8 -*-
"""守住「换台机器/换个 Python 版本就崩」的三类隐患。

背景(2026-10-21 实测):
1. `app/ui/ai_edit_dialog.py` 用了 f-string 表达式里的反斜杠转义
   (`f"{'\\n\\n' if cond else ''}"`)—— 这是 **PEP 701,Python 3.12 才有**的语法。
   而 pyproject 声明 `requires-python = ">=3.10"` → 在 3.10/3.11 上这个文件
   直接 SyntaxError,import 失败 → **应用起不来**。本机是 3.13,本地测不出来。
2. `tests/test_outline_to_script.py` 的 docstring 里有未转义的 `\\d`
   → Python 3.14 起(PEP 758)invalid escape sequence 变成 **SyntaxError**,
   那个测试文件直接收集不了。本机装了 3.14,实测报 `SyntaxError: "\\d" is an
   invalid escape sequence`。
3. 4 个文件带 UTF-8 BOM → 运行时 Python 会跳过,但任何用 ast.parse(把源码读成
   str)的工具链会直接 `SyntaxError: invalid non-printable character U+FEFF`。

这三个都不是「风格问题」,是**换环境就炸**。用测试钉住,别再复发。
"""
from __future__ import annotations

import ast
import pathlib
import warnings

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_DIRS = ("app", "tests", "scripts")


def _py_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if "__pycache__" in p.parts or ".venv" in p.parts:
                continue
            yield p


def _fstring_backslash(path: pathlib.Path, tree: ast.AST) -> list[int]:
    """返回「f-string 表达式部分含反斜杠」的节点行号(Python 3.12+ 才合法)。"""
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for v in node.values:
            if not isinstance(v, ast.FormattedValue):
                continue
            for sub in ast.walk(v.value):
                if (isinstance(sub, ast.Constant) and isinstance(sub.value, str)
                        and "\\" in sub.value):
                    hits.append(node.lineno)
                    break
    return hits


def test_no_fstring_backslash_in_expression():
    """f-string 表达式里不能有反斜杠 —— 3.12+ 才支持,项目声明支持 3.10。"""
    bad: list[str] = []
    for p in _py_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        except SyntaxError:
            continue          # 语法本身坏了,另一个测试会报
        for line in _fstring_backslash(p, tree):
            bad.append(f"{p.relative_to(ROOT)}:{line}")
    assert not bad, ("f-string 表达式里出现反斜杠(Python 3.12+ 才有,项目声明 >=3.10): "
                     + ", ".join(bad))


def test_no_invalid_escape_sequence():
    """非法转义序列在 Python 3.14 是 SyntaxError(PEP 758)。"""
    bad: list[str] = []
    for p in _py_files():
        src = p.read_text(encoding="utf-8-sig")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                compile(src, str(p), "exec")
            except SyntaxError as e:
                bad.append(f"{p.relative_to(ROOT)}:{e.lineno} {e.msg}")
                continue
            for x in w:
                if "escape sequence" in str(x.message):
                    bad.append(f"{p.relative_to(ROOT)}:{x.lineno} {x.message}")
    assert not bad, ("非法转义序列(Python 3.14 会变成 SyntaxError): "
                     + "; ".join(bad))


def test_no_utf8_bom():
    """文件头不要带 BOM —— ast.parse 类工具链会直接 SyntaxError。"""
    bad = [str(p.relative_to(ROOT)) for p in _py_files()
           if p.read_bytes()[:3] == b"\xef\xbb\xbf"]
    assert not bad, f"这些文件带 UTF-8 BOM: {bad}"


@pytest.mark.parametrize("mod", ["app.ui.ai_edit_dialog", "app.pipeline.video_clone",
                                  "app.ui.episode_page", "app.core.db"])
def test_key_modules_importable(mod):
    """关键模块必须能 import(名字写错/语法错会在这里炸)。"""
    import importlib
    importlib.import_module(mod)
