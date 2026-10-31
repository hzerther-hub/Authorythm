"""把补译代理产出的 15 语译文合并进主词典(Z)与补充词典(ui_strings.S)。

为什么不直接手改两个大文件:i18n.py 140KB、ui_strings.py 950KB,手改 291 个条目
既慢又容易漏校验。这里把校验(长度 15 / zh 基准逐字相等 / 占位符对齐)写成代码,
不合规直接抛错,不让半成品进库。

顺带把「只在 tr() 里当字面量用、但词典里根本没有」的键补进 Z ——
项目约定是「Z 放中文基准、S 放 15 语」,只补 S 不补 Z 的话,
tests/test_i18n_coverage 的漏译判据(靠 Z 知道谁是中文)就看不见这些键。

用法:
    python scripts/i18n_merge_translations.py            # 合并 + 自检
    python scripts/i18n_merge_translations.py --dry-run  # 只校验不落盘
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import i18n  # noqa: E402
from app.core import ui_strings as U  # noqa: E402

TMP = ROOT / ".tmp_i18n"
I18N_PY = ROOT / "app" / "core" / "i18n.py"
UI_STRINGS_PY = ROOT / "app" / "core" / "ui_strings.py"

PLACEHOLDER = re.compile(r"\{[0-9a-zA-Z_]*\}")


def load_batches() -> tuple[dict[str, list[str]], dict[str, str]]:
    """返回 (key -> 15 语 list, key -> 中文基准)。

    `H_manual.json` 是人工定稿的覆盖表:那 8 个「ASCII 键名直接露在界面上」的键
    不能用自动补译 —— 键名本身不是中文(如 batch_capped),而调用点还带
    `.format(MAX_BATCH)`,自动补译会把占位符吞掉、数字消失。
    所以它们的**中文基准要重写**(如 batch_capped → "单批最多 {0} 张,其余已忽略"),
    覆盖表里同时给出基准和 15 语译文。
    """
    out: dict[str, list[str]] = {}
    zh_base: dict[str, str] = {}
    for path in sorted(TMP.glob("*.translated.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, vals in data.items():
            if key in out:
                raise SystemExit(f"重复键 {key!r}({path.name})")
            out[key] = list(vals)
    for path in sorted(TMP.glob("*.json")):
        if path.name.endswith(".translated.json"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue          # 不是批次输入(如人工覆盖表),跳过
        for item in payload:
            if not isinstance(item, dict) or "key" not in item:
                continue
            zh_base[item["key"]] = item["zh"]
    # 人工覆盖表最后生效(仓库内常驻,不在临时目录里)
    manual_path = ROOT / "scripts" / "i18n_manual_overrides.json"
    if manual_path.exists():
        for key, item in json.loads(manual_path.read_text(encoding="utf-8")).items():
            if key.startswith("_"):
                continue
            out[key] = list(item["vals"])
            zh_base[key] = item["zh"]
    return out, zh_base


def validate(vals: dict[str, list[str]], zh_base: dict[str, str]) -> list[str]:
    """返回问题列表(空 = 全过)。"""
    problems: list[str] = []
    for key, v in vals.items():
        if len(v) != 15:
            problems.append(f"{key!r}: 长度 {len(v)} != 15")
            continue
        if any(not isinstance(x, str) or not x.strip() for x in v):
            problems.append(f"{key!r}: 有空串槽位")
            continue
        base = zh_base.get(key)
        if base is not None and v[0] != base:
            problems.append(f"{key!r}: zh 槽与基准不等\n    基准={base!r}\n    槽位={v[0]!r}")
        src = sorted(PLACEHOLDER.findall(base or v[0]))
        for idx, lang in enumerate(U.LANGS):
            if lang == "zh":
                continue
            if src != sorted(PLACEHOLDER.findall(v[idx])):
                problems.append(f"{key!r}: {lang} 占位符不对齐 {src} vs "
                                f"{sorted(PLACEHOLDER.findall(v[idx]))}")
    return problems


def insert_into_z(entries: dict[str, str]) -> int:
    """把新键插进 i18n.py 的 Z 字面量(闭合大括号之前)。"""
    src = I18N_PY.read_text(encoding="utf-8")
    anchor = "\n}\n\ndef _t(src: dict, **over) -> dict:"
    if anchor not in src:
        raise SystemExit("i18n.py 里找不到 Z 的闭合位置,手工确认后再跑")
    block = "\n" + "\n".join(
        f" {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)},"
        for k, v in entries.items()
    ) + "\n"
    I18N_PY.write_text(src.replace(anchor, block + anchor, 1), encoding="utf-8")
    return len(entries)


def insert_into_s(entries: dict[str, list[str]]) -> int:
    """把新条目插进 ui_strings.py 的 S 字面量(闭合大括号之前)。"""
    src = UI_STRINGS_PY.read_text(encoding="utf-8")
    marker = "\n}\n\n\ndef ui_lookup("
    if marker not in src:
        raise SystemExit("ui_strings.py 里找不到 S 的闭合位置,手工确认后再跑")
    lines = []
    for k, v in entries.items():
        lines.append(f"    {k!r}: {v!r},")
    block = "\n" + "\n".join(lines) + "\n"
    UI_STRINGS_PY.write_text(src.replace(marker, block + marker, 1), encoding="utf-8")
    return len(entries)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    vals, zh_base = load_batches()
    if not vals:
        raise SystemExit(f"{TMP} 下没有 *.translated.json")
    print(f"待合并 {len(vals)} 键")

    problems = validate(vals, zh_base)
    if problems:
        print(f"!! 校验不通过 {len(problems)} 项:")
        for p in problems[:40]:
            print("   ", p)
        raise SystemExit(1)
    print("校验通过:长度全 15 / zh 全等基准 / 占位符全对齐")

    # 已经存在的键跳过(补译代理可能覆盖了已有条目)。
    new_vals = {k: v for k, v in vals.items() if k not in U.S}
    skipped = len(vals) - len(new_vals)
    if skipped:
        print(f"跳过 {skipped} 个已存在的键")

    # 需要补进 Z 的:只在 tr() 当字面量用、词典里没有的。
    new_z = {k: zh_base[k] for k in new_vals
             if k not in i18n.Z and k in zh_base}
    if args.dry_run:
        print(f"[dry-run] 将新增 Z 键 {len(new_z)} 个,S 条目 {len(new_vals)} 个")
        return

    if new_z:
        n = insert_into_z(new_z)
        print(f"i18n.Z 新增 {n} 键")
    n = insert_into_s(new_vals)
    print(f"ui_strings.S 新增 {n} 条目")

    # 自检:开**子进程**重载模块确认真的生效了。
    # 不能在本进程里 reload —— `from app.core import i18n` 拿到的是包属性上的旧引用,
    # sys.modules.pop 也不会刷新包属性,自检会假阴性。
    code = "\n".join([
        "import sys; sys.path.insert(0, " + json.dumps(str(ROOT)) + ")",
        "from app.core import i18n as i2",
        "from app.core import ui_strings as u2",
        "need = " + json.dumps(sorted(new_vals), ensure_ascii=False),
        "miss = [k for k in need if k not in u2.S]",
        "zmiss = [k for k in need if k not in i2.Z]",
        "assert not miss, ('S missing: ' + repr(miss[:5]))",
        "assert not zmiss, ('Z missing: ' + repr(zmiss[:5]))",
        "print('OK Z=' + str(len(i2.Z)) + ' S=' + str(len(u2.S)))",
    ])
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit("合并后自检失败")
    print(f"自检通过:{len(new_vals)} 键已进 Z 与 S")


if __name__ == "__main__":
    main()
