# -*- coding: utf-8 -*-
"""修仓库里的 U+FFFD(替换字符)残留 —— 界面上会直接显示成「���」。

分两类,**不要误伤**:
- **故意的**:app/core/encoding.py 的 `_REPLACEMENT`、app/pipeline/book_import.py 的
  `text.count("\ufffd")` —— 这两处是**乱码检测器**本身,靠这个字符识别坏数据。
- **真乱码**:字面量/注释里残留的替换字符,多半是某次批量机翻或编码往返时被截断的字节。

用法:python scripts/i18n_fix_mojibake.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# (文件, 正则, 替换) —— 正则里的 \ufffd+ 匹配「一段替换字符」
FIXES: list[tuple[str, str, str]] = [
    # ── ui_strings.py:界面文案里的乱码(用户直接看得见)──
    ("app/core/ui_strings.py", r"三視\ufffd+", "三視図"),
    ("app/core/ui_strings.py", r"\ufffd+頭フレーム", "先頭フレーム"),
    ("app/core/ui_strings.py", r"表\ufffd+加字", "표지 텍스트"),
    ("app/core/ui_strings.py", r"就选几\ufffd+;", "就选几个;"),
    ("app/core/ui_strings.py", r"編集は文\ufffd+生成になり", "編集はテキスト生成になり"),
    ("app/core/ui_strings.py", r"편집이 문 생\ufffd+으로 바뀌고", "편집이 텍스트 생성으로 바뀌고"),
    # ── 注释 / 文档里的乱码 ──
    ("app/pipeline/novel.py", r"却一\ufffd+没进库", "却一条没进库"),
    ("docs/孤儿生成任务自愈-任务书.md", r"的\ufffd+频生成任务", "的视频生成任务"),
    ("docs/孤儿生成任务自愈-任务书.md", r"\ufffd+续数小时", "持续数小时"),
    ("tests/test_script_quality.py", r"场景数少时\ufffd+判", "场景数少时误判"),
]

# 这些文件里的 U+FFFD 是故意的,别碰
ALLOWED = {"app/core/encoding.py", "app/pipeline/book_import.py"}


def main() -> None:
    total = 0
    skipped = 0
    for rel, pattern, repl in FIXES:
        if rel in ALLOWED:
            print(f"!! {rel} 是乱码检测器所在文件,跳过")
            continue
        p = ROOT / rel
        src = p.read_text(encoding="utf-8")
        new, n = re.subn(pattern, repl, src)
        if n == 0:
            # 幂等:上一轮已经修过 → 替换文本已在文件里,不算失败。
            # 之前这里一律报「没匹配到」,导致脚本无法重复跑(它是一次性修表,
            # 但要留给人复核/新增条目时用,必须能反复执行)。
            if repl in src:
                skipped += 1
                print(f"  {rel}: 已修过({repl!r} 已在文件里),跳过")
            else:
                print(f"!! {rel}: {pattern!r} 没匹配到")
            continue
        p.write_text(new, encoding="utf-8")
        total += n
        print(f"  {rel}: 修 {n} 处")
    print(f"共修 {total} 处,跳过(已修过) {skipped} 处")

    # 收尾检查:不该再有残留(ALLOWED 里的两个文件是乱码检测器本身,故意留着 U+FFFD)
    left = []
    for rel in ("app/core/ui_strings.py", "app/pipeline/novel.py",
                "docs/孤儿生成任务自愈-任务书.md", "tests/test_script_quality.py"):
        p = ROOT / rel
        if p.exists() and "\ufffd" in p.read_text(encoding="utf-8"):
            left.append(rel)
    if left:
        raise SystemExit(f"仍有残留:{left}")
    print("收尾检查通过")


if __name__ == "__main__":
    main()
