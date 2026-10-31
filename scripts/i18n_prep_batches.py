"""为补译任务生成「带上下文」的批次输入文件。

为什么要这一步:光给一个键名,译者只能猜语义(「批量补齐提示词完成:{}」到底是
「批量补齐提示词完成」还是「批量补齐提示词已完成」?)。把**调用处的源码行**
一起给出去,译文才准。

产出(默认写到 .tmp_i18n/):每个批次一个 JSON,形如
    [{"key": ..., "zh": ..., "file": ..., "line": ..., "ctx": "<源码行>"}, ...]
补译代理读 JSON → 写同名的 .translated.json(15 语 list)。
"""
from __future__ import annotations

import ast
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import i18n  # noqa: E402
from app.core import ui_strings as U  # noqa: E402

APP = ROOT / "app"
PATTERNS = ("ui/**/*.py", "pipeline/**/*.py", "agents/**/*.py", "core/*.py")
SKIP_FILES = {"i18n.py", "ui_strings.py"}
OUT = ROOT / ".tmp_i18n"

# undefined(界面显示原始中文/键名)按来源文件分组;Z-only(有中文基准但无译文)另开批。
BATCHES: dict[str, list[str]] = {
    "A_episode": ["episode_page.py", "image_batch_panel.py", "mask_erase_dialog.py"],
    "B_settings": ["settings_dialog.py", "task_panel.py"],
    "C_novel": ["novel_dialogs.py", "novel.py"],
    "D_main": ["main_window.py", "project_page.py", "new_project_dialog.py",
               "project_concept_dialog.py"],
    "E_asset": ["asset_dialogs.py", "add_asset_dialog.py", "variants_dialog.py"],
    "F_misc": ["stock_photo_dialog.py", "image_edit_dialog.py", "chat_edit_drawer.py",
               "cover_text_dialog.py", "style_convert_dialog.py", "ai_edit_dialog.py",
               "batch_dialogs.py", "dashboard_widget.py"],
}


def collect_used() -> dict[str, list[tuple[str, int, str]]]:
    """key -> [(文件, 行号, 源码行)],按调用处收集。"""
    out: collections.defaultdict[str, list[tuple[str, int, str]]] = collections.defaultdict(list)
    for pat in PATTERNS:
        for path in sorted(APP.glob(pat)):
            if path.name in SKIP_FILES or "__pycache__" in path.parts:
                continue
            src = path.read_text(encoding="utf-8")
            lines = src.splitlines()
            tree = ast.parse(src, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                fn = node.func
                nm = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if nm != "tr":
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    ctx = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
                    out[first.value].append((path.name, node.lineno, ctx))
    return out


def main() -> None:
    used = collect_used()
    undefined = sorted(k for k in used if k not in i18n.Z and k not in U.S)
    z_only = sorted(k for k in i18n.Z if k not in U.S)

    OUT.mkdir(exist_ok=True)
    assigned: set[str] = set()
    for name, files in BATCHES.items():
        items = []
        for k in undefined:
            if k in assigned:
                continue          # 同一个键可能出现在多个文件(如公共文案),只归第一批
            hit = next((u for u in used[k] if u[0] in files), None)
            if hit is None:
                continue
            items.append({"key": k, "zh": k, "file": hit[0], "line": hit[1], "ctx": hit[2]})
        assigned |= {i["key"] for i in items}
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{name}: {len(items)} 键 -> {path.name}")

    leftover = [k for k in undefined if k not in assigned]
    if leftover:
        print(f"!! 未分配 {len(leftover)}: {leftover}", file=sys.stderr)

    # Z-only 批次:语义只能从「中文基准 + 键名」推,没有调用点上下文。
    items = [{"key": k, "zh": i18n.Z[k], "file": "", "line": 0, "ctx": ""} for k in z_only]
    path = OUT / "G_zonly.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"G_zonly: {len(items)} 键 -> {path.name}")


if __name__ == "__main__":
    main()
