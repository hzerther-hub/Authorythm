# -*- coding: utf-8 -*-
"""i18n 自动补翻(并发版):三级引擎降级 + ThreadPool 8 线程。

用法:
    py -3.13 -X utf8 tools/i18n_autofill.py            # 补翻全部缺口
    py -3.13 -X utf8 tools/i18n_autofill.py --workers 16
    py -3.13 -X utf8 tools/i18n_autofill.py --dry-run

引擎(app/core/translate.py):baidu-forward → google-gtx → mymemory 依次降级。
失败不写入,保留 EN fallback,记 stderr;每 24 条完成即写盘,中断重跑可续。
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import translate as TR
from app.core import ui_strings as U

_lock = Lock()
_done = 0
_failed = 0


def to_translate(row: list[str], lang_idx: int) -> bool:
    lang = U.LANGS[lang_idx]
    if lang == "zh":                       # 中文是基准,不用翻
        return False
    cur = row[lang_idx]
    if not cur or not cur.strip():
        return True
    if cur.strip() == row[0].strip():
        return True
    if lang not in ("zh", "ja") and any("一" <= c <= "鿿" for c in cur):
        return True
    return False


def seed_missing() -> int:
    """把主词典 i18n.T 里「值==中文原文」且未进 S 的键追加进 S。"""
    from app.core import i18n as _i18n

    def _zh(t):
        return any("一" <= c <= "鿿" for c in str(t))

    _i18n.set_language("en")
    added = 0
    for key in sorted(_i18n.Z):
        if key in U.S:
            continue
        if _zh(_i18n.tr(key)):
            row = [""] * len(U.LANGS)
            row[0] = _i18n.Z[key]
            U.S[key] = row
            added += 1
    _i18n.set_language("zh")
    return added


def main() -> int:
    args = sys.argv[1:]
    workers, dry = 8, False
    if "--workers" in args:
        i = args.index("--workers"); workers = int(args[i + 1]); del args[i:i + 2]
    if "--dry-run" in args:
        dry = True

    added = seed_missing()
    jobs = []
    for key, row in U.S.items():
        for li, lang in enumerate(U.LANGS):
            if to_translate(row, li):
                jobs.append((key, li, lang))
    print(f"seed 新增 {added} 键 · 待补 {len(jobs)} 个语言位 · {workers} 线程"
          + ("(dry-run)" if dry else ""), flush=True)
    if dry:
        return 0

    path = Path(__file__).resolve().parent.parent / "app/core/ui_strings.py"
    t0 = time.time()

    def one(job):
        global _done, _failed
        key, li, lang = job
        row = U.S[key]
        try:
            out = TR.translate(row[0], lang, source="zh")
            row[li] = (out or "").strip()
            with _lock:
                _done += 1
                # 每 10 条报一条在翻什么,每 100 条落一次盘 —— 跑到一半被 Ctrl+C 也不丢
                if _done % 10 == 0 or _done == len(jobs):
                    src = row[0].replace("\n", "⏎")[:34]
                    dst = (row[li] or "…").replace("\n", "⏎")[:34]
                    print(f"  {_done:>5}/{len(jobs)}  {lang}  {src}  →  {dst}", flush=True)
                if _done % 100 == 0:
                    _write(U, path)
                    el = time.time() - t0
                    rate = _done / max(1e-9, el)
                    left = (len(jobs) - _done) / max(1e-9, rate)
                    print(f"[save] {_done}/{len(jobs)} · {rate:.1f}/s · 剩余约 {left/60:.0f} 分"
                          f" · 失败 {_failed}", flush=True)
            return True
        except Exception as exc:  # noqa: BLE001
            with _lock:
                _failed += 1
                if _failed <= 20:
                    print(f"[fail] {key[:24]}/{lang}: {str(exc)[:80]}", flush=True)
            return False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, j) for j in jobs]
        for _ in as_completed(futures):
            pass

    _write(U, path)
    print(f"完成:{_done} 成功 / {_failed} 失败 · 用时 {time.time() - t0:.0f}s", flush=True)
    return 0


def _write(mod, path: Path) -> None:
    lines = [f'    "{k}": [' + ", ".join(repr(x) for x in row) + "]," for k, row in mod.S.items()]
    body = (
        '# -*- coding: utf-8 -*-\n'
        '"""UI 文案补充词典(第二层)。i18n.tr() 先查主词典,再查本表。\n\n'
        "15 种语言全覆盖;新增条目按 langs 顺序给出 15 个值:\n"
        "    zh en ja ko ar hi id th tr vi fr de es pt it\n"
        '"""\nfrom __future__ import annotations\n\n\n'
        "LANGS = " + repr(mod.LANGS) + "\n\n"
        "# key: [zh, en, ja, ko, ar, hi, id, th, tr, vi, fr, de, es, pt, it]\n"
        "S: dict[str, list[str]] = {\n" + "\n".join(lines) + "\n}\n\n\n"
        "def ui_lookup(lang: str, key: str) -> str | None:\n"
        '    """查 UI 补充词典;未命中返回 None(交由主词典/回退处理)。"""\n'
        "    row = S.get(key)\n    if not row:\n        return None\n"
        "    try:\n        return row[LANGS.index(lang)]\n"
        "    except (ValueError, IndexError):\n        return row[0]\n"
    )
    path.write_text(body, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    sys.exit(main())