# -*- coding: utf-8 -*-
"""静态检查:函数体内使用的名字是否在作用域内可见(抓 NameError 类漏导入)。

背景:本项目连续踩了两次同类的坑 ——
  · video_clone.draft_volume_in_batches 用了 text_client 却没 import;
  · episode_page._after_split_chain 用了 R(storyboard_repair 的别名)没 import。
两者都是**运行时才炸**,而且异常发生在后台线程里会被静默吞掉,
表现为「点了没反应」。本脚本在提交前把它们拦下来。
"""
from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"


def _bound_names(node: ast.AST, extra: set[str] | None = None) -> set[str]:
    """收集一个作用域内可见的名字(参数/赋值/导入/全局/内建/父级)。"""
    names: set[str] = set(extra or ())
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.arg):
            names.add(n.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            names.add(n.name)
        elif isinstance(n, ast.Global) or isinstance(n, ast.Nonlocal):
            names.update(n.names)
    return names


def _module_globals(tree: ast.Module) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
    return out


def _unresolved(tree: ast.Module) -> list[tuple[str, int, str]]:
    g = _module_globals(tree)
    known = g | set(dir(builtins))
    problems: list[tuple[str, int, str]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # 收集本函数里(任意深度)导入的名字 —— 局部 import 也是合法来源
        local = _bound_names(fn) | known
        for n in ast.walk(fn):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    local.add((a.asname or a.name).split(".")[0])
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                nm = node.id
                if nm in local or nm == "self":
                    continue
                # 只报「大写开头的别名 / 含下划线的模块别名」这类导入型名字:
                # 普通局部变量漏定义由运行时自然暴露,而导入型漏掉最隐蔽
                # (异常发生在后台线程里会被吞掉,表现为「点了没反应」)。
                if nm[:1].isupper() or "_" in nm:
                    problems.append((getattr(fn, "lineno", 0), node.lineno, nm))
    # 去重(同名在多处报只报一次)
    seen, out = set(), []
    for fl, nl, name in sorted(problems):
        key = (fl, name)
        if key not in seen:
            seen.add(key)
            out.append((fl, nl, name))
    return out


def main() -> int:
    bad = 0
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT.parent)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            print(f"[语法错误] {rel}:{e.lineno} {e.msg}")
            bad += 1
            continue
        for fl, nl, name in _unresolved(tree):
            print(f"[可能未定义] {rel}:{nl} 函数在第 {fl} 行使用了 '{name}'")
            bad += 1
    print("—" * 46)
    print("未发现疑似漏导入" if not bad else f"共 {bad} 处待确认")
    return 0


if __name__ == "__main__":
    sys.exit(main())
