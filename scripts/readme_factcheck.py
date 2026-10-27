# -*- coding: utf-8 -*-
"""README 事实核对:把文档里写的数字与仓库实际状态对齐。

为什么要有这个脚本:README 里的「23 张表 / 13 个 Agent / 150 个提示词」这类数字
是手工写的,代码一改就漂。漂了没人发现,直到用户按文档找功能找不到。
"""
from __future__ import annotations

import collections
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def table_count() -> tuple[int, list[str]]:
    """按 CREATE TABLE 语句数统计,并(若存在)与真实库的表数对照。

    不去 executescript 整份 db.py —— 那是 Python 源码不是 SQL。
    """
    src = (ROOT / "app" / "core" / "db.py").read_text(encoding="utf-8")
    names = sorted(set(re.findall(r"CREATE TABLE IF NOT EXISTS\s+(\w+)", src)))
    real_db = ROOT / "data" / "yihao.sqlite3"
    if real_db.exists():
        con = sqlite3.connect(f"file:{real_db}?mode=ro", uri=True)
        live = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        con.close()
        print(f"[真实库 data/yihao.sqlite3] {len(live)} 张表")
    return len(names), names


def prompt_stats() -> tuple[int, dict[str, int]]:
    p = ROOT / "workspace" / "prompts"
    files = list(p.rglob("*.md")) if p.exists() else []
    agents = collections.Counter(f.stem.rsplit(".", 1)[0] for f in files)
    return len(files), dict(sorted(agents.items()))


def skill_stats() -> tuple[int, int]:
    s = ROOT / "workspace" / "skills"
    files = [f for f in s.rglob("*") if f.is_file()] if s.exists() else []
    return len(files), len({f.stem.rsplit(".", 1)[0] for f in files})


def ui_stats() -> tuple[int, list[tuple[str, int]]]:
    files = [f for f in (ROOT / "app" / "ui").rglob("*.py")]
    sizes = [(f.name, len(f.read_text(encoding="utf-8", errors="ignore").splitlines()))
             for f in files]
    sizes.sort(key=lambda x: -x[1])
    return len(files), sizes[:10]


def main() -> None:
    n, names = table_count()
    print(f"[表] {n} 张")
    print(f"     {', '.join(names)}")
    nf, agents = prompt_stats()
    print(f"\n[提示词] {nf} 个 md / {len(agents)} 类 Agent")
    for a, c in agents.items():
        print(f"     {a:30s} {c}")
    sk, skn = skill_stats()
    print(f"\n[技能] {sk} 个文件 / {skn} 类")
    ui, top = ui_stats()
    print(f"\n[UI] {ui} 个 py")
    for name, lines in top:
        print(f"     {name:34s} {lines:6d} 行")


if __name__ == "__main__":
    main()
