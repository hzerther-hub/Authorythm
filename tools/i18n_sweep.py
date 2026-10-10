# -*- coding: utf-8 -*-
"""扫出 app/ui/*.py 里没走 tr() 的中文字面量。

背景:ui_strings.S 的语言包本身已经 15 语言全了,但这些文案压根没被 tr() 包过 ——
它们是写死在源码里的中文字面量,所以永远不随语言切换而变。

用法:
    py -3.13 -X utf8 tools/i18n_sweep.py --list          # 只列出来人工过一遍
    py -3.13 -X utf8 tools/i18n_sweep.py --apply         # 改源码 + 写 zh 基准
    py -3.13 -X utf8 tools/i18n_sweep.py --apply --skip-prompts
"""
from __future__ import annotations

import argparse
import ast
import io
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
UI = ROOT / "app" / "ui"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 这些是发给模型的指令,不是界面文案 —— 翻了反而让提示词语义跑偏(与参考项目一致)
PROMPT_HINTS = (
    "你是一个", "请你", "请按", "请严格", "以下是", "输出格式", "不要输出",
    "输出 JSON", "输出json", "必须包含", "字数", "段落", "如下格式", "例如：",
    "例如:", "claude", "Claude", "You are",
)

# 只统计长度在这个区间内的短串:超过的是长提示词/说明段落,单独人工判断
MAX_LEN = 60

# 正则:翻了就匹配不上(剧集标题模式 \d \s ^ $),一概不动
REGEX_CHARS = ("\\d", "\\s", "\\w", "\\b", "^", "$", "(?", "[", "|")


def _is_regex(text: str, prefix: str = "") -> bool:
    if prefix.lower() == "r":
        return True
    return any(c in text for c in REGEX_CHARS)


def _is_prompt(text: str) -> bool:
    if any(h in text for h in PROMPT_HINTS):
        return True
    return len(text) > MAX_LEN


def collect() -> dict[pathlib.Path, list[tuple[int, str]]]:
    """返回 {文件: [(行号, 中文串)]},排除 tr() 内部与注释。"""
    out: dict[pathlib.Path, list[tuple[int, str]]] = {}
    cjk = re.compile(r"[一-鿿]")
    for f in sorted(UI.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        tree = ast.parse(src)
        parent = {}
        for node in ast.walk(tree):
            for ch in ast.iter_child_nodes(node):
                parent[id(ch)] = node
        # 已经被 tr(...) 包住的字面量
        in_tr: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr":
                for a in node.args:
                    if isinstance(a, ast.Constant):
                        in_tr.add(id(a))
        hits: list[tuple[int, str]] = []
        lines = src.split("\n")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            v = node.value
            if not cjk.search(v) or len(v) < 2:
                continue
            if id(node) in in_tr or "\n" in v:
                continue
            ln = getattr(node, "lineno", 0)
            # raw 前缀(r"^第\d+集$")ast 里拿不到,从源码行里找 —— col_offset 是字节偏移,
            # 得先换成字符数,否则前面的中文会把位置带偏
            src_line = lines[ln - 1] if 0 < ln <= len(lines) else ""
            col = len(src_line.encode("utf-8")[:node.col_offset].decode("utf-8", "ignore"))
            if _is_regex(v, "r" if re.search(r"\br[\"']$", src_line[:col]) else ""):
                continue
            par = parent.get(id(node))
            # setObjectName / setProperty 是选择器不是文案;dict 键参与比较,包 tr() 会改语义
            if isinstance(par, ast.Call) and isinstance(par.func, ast.Attribute) \
                    and par.func.attr in ("setObjectName", "setProperty"):
                continue
            if isinstance(par, ast.Dict):
                continue
            st = src_line.strip()
            if st.startswith("#") or st.startswith('"""') or st.startswith("'''"):
                continue
            hits.append((ln, v))
        if hits:
            out[f] = sorted(set(hits))
    return out


def _rewrite(path: pathlib.Path, targets: set[str]) -> int:
    """把文件里等于 targets 的字符串字面量包上 tr()。

    两个坑:
    1. ast 的 col_offset 是 UTF-8 **字节**偏移,直接当字符下标用,一行里只要有中文就整行错位。
    2. 隐式拼接("a"\\n"b")在 AST 里是**一个**跨行 Constant,值是拼好的;按行改会把它拆散。
       所以这里统一切整段源码,替换从后往前做,前面的偏移量才不会被带偏。
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    parent: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            parent[id(ch)] = node
    in_tr: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr":
            for a in node.args:
                if isinstance(a, ast.Constant):
                    in_tr.add(id(a))

    # 全程在**字节**空间里做偏移:ast 的 col_offset 是 UTF-8 字节偏移,
    # 而 starts 若按字符数累加,遇到中文行就会整行错位(踩过一次)。
    blob = src.encode("utf-8")
    starts, acc = [], 0
    for ln in blob.splitlines(keepends=True):
        starts.append(acc)
        acc += len(ln)

    def off(lineno: int, col: int) -> int:
        return starts[lineno - 1] + col

    edits: list[tuple[int, int, bytes]] = []
    seen: set[tuple[int, int]] = set()

    def add_span(node) -> None:
        # 原样保留字面量自带的引号:跨行的隐式拼接("a"\n"b")塞进一对新引号会直接语法错,
        # 而 tr(原样) 对单行、多行、raw 串、f 串都成立。
        s, e = off(node.lineno, node.col_offset), off(node.end_lineno, node.end_col_offset)
        if (s, e) in seen:
            return
        seen.add((s, e))
        edits.append((s, e, b"tr(" + blob[s:e] + b")"))

    # f-string:f"生成封面 {n}" 里那一段是**字面文本**,不能塞 tr(),否则 f 串会把 tr(...) 原样打印出来。
    # 只有整个 f 串没有插值时才能整体包起来。
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr) or id(node) in in_tr:
            continue
        if any(isinstance(c, ast.FormattedValue) for c in node.values):
            continue
        v = "".join(c.value for c in node.values if isinstance(c, ast.Constant))
        if v in targets and "\n" not in v:
            add_span(node)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        v = node.value
        if v not in targets or id(node) in in_tr or "\n" in v:
            continue
        if isinstance(parent.get(id(node)), ast.JoinedStr):   # 上面已按整段处理
            continue
        add_span(node)

    for s, e, repl in sorted(edits, key=lambda t: -t[0]):
        blob = blob[:s] + repl + blob[e:]
    if not edits:
        return 0
    src = blob.decode("utf-8")
    src = _ensure_tr_import(src, path)
    path.write_text(src, encoding="utf-8")
    return len(edits)


_TR_IMPORT = re.compile(r"^from\s+\.{1,2}[\w.]*i18n\s+import\s+[^\n]*\btr\b", re.M)


def _ensure_tr_import(src: str, path: pathlib.Path) -> str:
    """文件里用到 tr() 就必须能 import 到它。

    两个坑:
    1. 锚点不能只找 `from ..`:braille.py 一个相对导入都没有,全都走 PySide6 绝对导入,
       照原样插不进去,模块一 import 就 NameError。
    2. 插入点不能是"最后一条匹配行":多行括号导入(from x import (a,\\n b))的续行也匹配
       `^(from|import)`,插在续行后会把括号列表劈成两半(toast.py 踩过)。
       所以只在 ast 的顶层 ImportFrom/Import 节点(带准确的 end_lineno)之后插。
    """
    if _TR_IMPORT.search(src):
        return src
    line = "from ..core.i18n import tr"
    tree = ast.parse(src)
    last_end = None
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_end = node.end_lineno
    if last_end:
        lines = src.split("\n")
        lines.insert(last_end, line)
        return "\n".join(lines)
    return line + "\n\n" + src


def apply(data) -> tuple[int, dict[str, str]]:
    keys: dict[str, str] = {}
    n = 0
    for path, hits in data.items():
        targets = {v for _l, v in hits if not _is_prompt(v)}
        if targets:
            n += _rewrite(path, targets)
        for _l, v in hits:
            if not _is_prompt(v):
                keys[v] = v
    return n, keys


def seed(keys: dict[str, str]) -> int:
    """把新键写进 i18n.Z(中文基准)和 ui_strings.S(先只填中文,其余留给机翻)。

    中文原文直接做键:自解释、天然去重,而且译文缺失时 tr() 会回退到中文而不是显示键名。
    """
    from app.core import ui_strings as U
    from app.core import i18n as I
    old_z, old_s = set(I.Z), set(U.S)
    new = [k for k in keys if k not in old_s]
    for k in new:
        U.S[k] = [k] + [""] * (len(U.LANGS) - 1)
    if not new:
        return 0

    ipath = ROOT / "app" / "core" / "i18n.py"
    isrc = ipath.read_text(encoding="utf-8")
    idx = isrc.index("\n}\n\ndef _t(")
    block = "".join(f" {k!r}: {k!r},\n" for k in new if k not in old_z)
    if block:
        ipath.write_text(isrc[:idx] + block + isrc[idx:], encoding="utf-8")

    upath = ROOT / "app" / "core" / "ui_strings.py"
    usrc = upath.read_text(encoding="utf-8")
    tail = usrc.rindex("}\n\n\ndef ui_lookup")
    ublock = "".join(
        "    " + repr(k) + ": [" + ", ".join(repr(x) for x in U.S[k]) + "],\n" for k in new)
    upath.write_text(usrc[:tail] + ublock + usrc[tail:], encoding="utf-8")
    return len(new)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "tools" / "sweep_keys.json"))
    a = ap.parse_args()

    data = collect()
    if a.list:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        total = prompts = 0
        for f, hits in data.items():
            rows = [(l, v, _is_prompt(v)) for l, v in hits]
            ui = [r for r in rows if not r[2]]
            total += len(ui)
            prompts += len(r for r in rows if r[2])
            print(f"\n=== {f.name}  界面 {len(ui)} / 提示词跳过 {prompts if False else len([r for r in rows if r[2]])}")
            for l, v, _ in ui:
                print(f"  {l:5} {v}")
        print(f"\n合计界面文案 {total} 条,跳过提示词 {prompts} 条")
        return 0

    if not a.apply:
        ap.error("给 --list 或 --apply")

    n, keys = apply(data)
    added = seed(keys)
    print(f"改写 {n} 处,新键 {added} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
