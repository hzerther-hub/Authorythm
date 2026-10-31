"""按**槽位下标**改写 ui_strings.S 里的整行 —— i18n 修补专用。

## 为什么不能用 `line.replace(旧值, 新值)`

实测踩过:同一行的 15 个槽里,**en 槽和 ar 槽的值完全相同**(机翻没翻完,
两处都留着同一段英文)。这时 `line.replace(old, new, 1)` 替换的是**第一个**
出现位置(en 槽),而你本意是改 ar 槽 —— 结果 ar 槽没动、en 槽被写坏,
而且看起来「命令成功了」。改 3 个键就连锁串了 5 个槽。

## 本模块的做法

把整行当 Python 字面量解析(`ast.literal_eval` 出 15 个槽)→ 按下标改 →
重新序列化回源码。这样与「值是否重复」完全无关。

用法:
    from i18n_rowedit import set_rows
    set_rows({"键名": ["中文基准", "English", ... 15 个]})
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

UI_STRINGS_PY = ROOT / "app" / "core" / "ui_strings.py"
LANGS = ["zh", "en", "ja", "ko", "ar", "hi", "id", "th", "tr", "vi", "fr", "de", "es", "pt", "it"]


def _render(values: list[str]) -> str:
    """把 15 个值渲染成一行 list 字面量(风格贴近文件现状:默认单引号)。"""
    return "[" + ", ".join(repr(v) for v in values) + "]"


def _split_row(line: str) -> tuple[str, list[str], str] | None:
    """从一行里拆出 (键前缀, 15 个槽, 尾部)。不是 S 行则返回 None。"""
    m = re.match(r"^(    )('.*?'|\".*?\"): \[(.*)\],(\s*)$", line.rstrip("\n"))
    if not m:
        return None
    try:
        vals = ast.literal_eval("[" + m.group(3) + "]")
    except (SyntaxError, ValueError):
        return None
    if not isinstance(vals, list):
        return None
    return m.group(1) + m.group(2) + ": ", vals, m.group(4)


def _key_of(line: str) -> str | None:
    """取一行 S 条目的键。

    为什么不能靠 `repr(key)` 拼前缀:ui_strings.py 里同一个文件的键有**单引号和双引号
    两种写法**(含 `{a}`/`{b}` 这类片段的键当初是用双引号写的),
    `repr()` 只会给出单引号形式 → 拼出来的前缀命中 0 行,脚本报
    「找到 0 行以此键开头」而**实际键就在文件里**。实测踩过:
    '正在补第 {a}-{b} 卷的细节…'、'人物三视图已重建,重新生成首帧即可生效' 两个键都栽在这。
    所以改成解析出行首的键字面量再比对,两种引号写法都能命中。
    """
    m = re.match(r"^    (.+?): \[", line)
    if not m:
        return None
    try:
        k = ast.literal_eval(m.group(1))
    except (SyntaxError, ValueError):
        return None
    return k if isinstance(k, str) else None


def set_rows(patch: dict[str, list[str]], path: Path | None = None) -> int:
    """按 key → 15 语 list 改写 S 的行。返回改写的行数。"""
    p = path or UI_STRINGS_PY
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    changed = 0
    problems: list[str] = []

    # 先把每一行的键解析出来,建立 key → 行号 的索引(两种引号写法都认)
    index: dict[str, list[int]] = {}
    for i, ln in enumerate(lines):
        k = _key_of(ln)
        if k is not None:
            index.setdefault(k, []).append(i)

    for key, new_vals in patch.items():
        if len(new_vals) != 15:
            problems.append(f"{key!r}: 给了 {len(new_vals)} 个值,应为 15")
            continue
        hit = index.get(key, [])
        if len(hit) != 1:
            problems.append(f"{key!r}: 找到 {len(hit)} 行以此键开头,无法唯一定位")
            continue
        i = hit[0]
        parsed = _split_row(lines[i])
        if parsed is None:
            problems.append(f"{key!r}: 行解析失败")
            continue
        head, old_vals, tail = parsed
        if len(old_vals) != 15:
            problems.append(f"{key!r}: 该行有 {len(old_vals)} 个槽,不是 15")
            continue
        newline = "\n" if lines[i].endswith("\n") else ""
        lines[i] = f"{head}{_render(list(new_vals))},{tail}{newline}"
        changed += 1

    if problems:
        for x in problems:
            print("!!", x)
        raise SystemExit(f"{len(problems)} 处未处理")
    p.write_text("".join(lines), encoding="utf-8")
    return changed


def main() -> None:
    import json
    if len(sys.argv) < 2:
        raise SystemExit("用法:python scripts/i18n_rowedit.py <patch.json>")
    patch = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    n = set_rows(patch)
    print(f"改写 {n} 行")


if __name__ == "__main__":
    main()
