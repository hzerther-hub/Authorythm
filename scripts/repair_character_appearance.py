# -*- coding: utf-8 -*-
"""一次性批量修复历史角色的 appearance / styling(按 character_spec 的规格)。

为什么需要:规格此前只写在 2/15 份提示词里,且落库前没有校验,实测整库角色
普遍只有 45~70 字的逗号串。character_spec 已把规格变成软件层可校验/可补写,
本脚本把历史数据补一遍,不必等下次出图才顺带修复。

行为:
   默认 --dry-run:只扫描 + 审计 + 打印,不调模型、不写库;
   真跑时按**项目分组**批量补写(一个项目一次模型调用),逐条回写;
   只回写"确实变长"的字段;仍不达标原样保留并报告;
   单个项目失败不影响其它项目,最后给汇总。

用法:
    python scripts/repair_character_appearance.py --dry-run
    python scripts/repair_character_appearance.py --dry-run --drama-id 13
    python scripts/repair_character_appearance.py --yes
    python scripts/repair_character_appearance.py --yes --config-id 7 --limit 20

 跑之前先关掉 app:SQLite 两边同时写会锁冲突(WAL 下通常只报 locked,不会坏库)。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:                       # pytest 的 capture 对象没有 reconfigure,导入本模块时不能炸
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:          # noqa: BLE001
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import config, db                      # noqa: E402
from app.pipeline import character_spec as cs        # noqa: E402

_COLS = "id, drama_id, name, role_type, appearance, styling"


def load_characters(drama_id: int | None = None) -> list[dict]:
    """读取未软删的角色。老库可能没有 deleted_at 列,回退为不过滤。"""
    if drama_id:
        sql = f"SELECT {_COLS} FROM characters WHERE drama_id=? AND deleted_at IS NULL ORDER BY id"
        args: tuple = (drama_id,)
    else:
        sql = f"SELECT {_COLS} FROM characters WHERE deleted_at IS NULL ORDER BY drama_id, id"
        args = ()
    try:
        rows = db.q(sql, args)
    except Exception as exc:  # noqa: BLE001  列不存在等老库兼容
        print(f"[warn] 带 deleted_at 过滤失败({str(exc)[:80]}),回退全量查询", flush=True)
        sql = sql.replace(" AND deleted_at IS NULL", "")
        rows = db.q(sql, args)
    return [dict(r) for r in rows]


def group_by_drama(rows: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(int(r["drama_id"]), []).append(r)
    return out


def _short(text: str | None, n: int = 28) -> str:
    t = (text or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[:n] + ""


def print_targets(grouped: dict[int, list[dict]]) -> int:
    total = 0
    print(f"\n{'#':>5}  {'drama':>5}  {'角色':<12} {'appearance':>10} {'styling':>7}  问题", flush=True)
    print("-" * 100, flush=True)
    for did, chars in sorted(grouped.items()):
        for c in chars:
            issues = cs.audit(c.get("appearance"), c.get("styling"), c.get("name") or "")
            if not issues:
                continue
            total += 1
            print(f"{total:>5}  {did:>5}  {str(c.get('name') or '')[:12]:<12} "
                  f"{len((c.get('appearance') or '').strip()):>10} "
                  f"{len((c.get('styling') or '').strip()):>7}  "
                  f"{'; '.join(issues)}", flush=True)
    return total


def repair_drama(drama_id: int, chars: list[dict], *, config_id: int | None,
                 lang: str | None, pause: float = 0.0) -> tuple[int, int, int]:
    """补写一个项目的角色并回写。返回 (尝试数, 已更新数, 仍不达标数)。"""
    before = {int(c["id"]): ((c.get("appearance") or "").strip(),
                             (c.get("styling") or "").strip()) for c in chars}
    try:
        fixed = cs.expand_many(chars, config_id=config_id, lang=lang)
    except Exception as exc:  # noqa: BLE001  expand_many 本身不抛,这里兜底防意外
        print(f"[drama {drama_id}] 补写异常: {str(exc)[:160]}", flush=True)
        return len(chars), 0, len(chars)

    ts = db.now()
    updated = still_bad = 0
    for c in fixed:
        cid = int(c["id"])
        ap = (c.get("appearance") or "").strip()
        st = (c.get("styling") or "").strip()
        old_ap, old_st = before[cid]
        if (ap, st) != (old_ap, old_st):
            try:
                db.ex("UPDATE characters SET appearance=?,styling=?,updated_at=? WHERE id=?",
                      (ap, st, ts, cid))
                updated += 1
            except Exception as exc:  # noqa: BLE001
                print(f"[drama {drama_id}] #{cid} 回写失败: {str(exc)[:120]}", flush=True)
        issues = cs.audit(ap, st, c.get("name") or "")
        if issues:
            still_bad += 1
            print(f"  [drama {drama_id}] {c.get('name')} 仍不达标: {'; '.join(issues)}",
                  flush=True)
    if pause:
        time.sleep(pause)
    return len(chars), updated, still_bad


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="按 character_spec 规格批量修复历史角色的 appearance / styling")
    p.add_argument("--dry-run", action="store_true",
                   help="只扫描并打印不达标的角色,不调用模型、不写库")
    p.add_argument("--yes", action="store_true",
                   help="确认执行(非 dry-run 时必须显式给出,或交互输入 y)")
    p.add_argument("--drama-id", type=int, default=None, help="只处理指定项目")
    p.add_argument("--limit", type=int, default=0,
                   help="最多处理多少个不达标角色(0=不限)")
    p.add_argument("--config-id", type=int, default=None,
                   help="指定文本模型配置 id;默认用项目默认文本模型")
    p.add_argument("--lang", default=None,
                   help="覆盖补写语言(zh/en/ja...);默认跟随项目内容语言")
    p.add_argument("--pause", type=float, default=0.5,
                   help="每个项目之间的间隔秒数(默认 0.5,给供应商留余量)")
    p.add_argument("--skip-empty", action="store_true",
                   help="跳过 appearance/styling 都为空的合成角色(无素材可补,补写等于凭空编人)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not config.DB_PATH.exists():
        print(f"[fatal] 数据库不存在: {config.DB_PATH}", flush=True)
        return 2
    print(f"数据库: {config.DB_PATH}", flush=True)
    print(f"规格: appearance >= {cs.MIN_APPEARANCE} 字 / styling >= {cs.MIN_STYLING} 字",
          flush=True)

    rows = load_characters(args.drama_id)
    if args.skip_empty:
        before_n = len(rows)
        rows = [r for r in rows
                if (r.get("appearance") or "").strip() or (r.get("styling") or "").strip()]
        if len(rows) != before_n:
            print(f"--skip-empty 跳过 {before_n - len(rows)} 个空角色", flush=True)
    grouped = group_by_drama(rows)
    target_grouped = {
        did: [c for c in chars
              if cs.audit(c.get("appearance"), c.get("styling"), c.get("name") or "")]
        for did, chars in grouped.items()
    }
    target_grouped = {did: chars for did, chars in target_grouped.items() if chars}

    print(f"扫描角色 {len(rows)} 个;不达标 {sum(len(v) for v in target_grouped.values())} 个,"
          f"分布在 {len(target_grouped)} 个项目", flush=True)
    print_targets(target_grouped)

    if not target_grouped:
        print("\n全部达标,无需修复。", flush=True)
        return 0

    if args.limit and args.limit > 0:
        left = args.limit
        limited: dict[int, list[dict]] = {}
        for did in sorted(target_grouped):
            chunk = target_grouped[did][:left]
            if chunk:
                limited[did] = chunk
            left -= len(chunk)
            if left <= 0:
                break
        target_grouped = limited
        print(f"\n--limit 生效:本次只处理 {args.limit} 个角色", flush=True)

    if args.dry_run:
        print("\n[DRY-RUN] 未调用模型、未写库。去掉 --dry-run(并加 --yes)执行修复。",
              flush=True)
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            print("\n[abort] 非交互环境必须显式加 --yes 才会写库。", flush=True)
            return 2
        ans = input(f"\n将调用模型补写 {len(target_grouped)} 个项目,确认执行? [y/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("已取消。", flush=True)
            return 0

    total = updated = still_bad = 0
    failed_dramas: list[int] = []
    for did in sorted(target_grouped):
        chars = target_grouped[did]
        lang = args.lang or config.resolve_content_language(did)
        print(f"\n[drama {did}] 补写 {len(chars)} 个角色 (lang={lang}) ", flush=True)
        try:
            n, u, bad = repair_drama(did, chars, config_id=args.config_id,
                                     lang=lang, pause=args.pause)
        except Exception as exc:  # noqa: BLE001  单项目失败不拖垮整批
            failed_dramas.append(did)
            print(f"[drama {did}] 失败: {str(exc)[:200]}", flush=True)
            continue
        total += n
        updated += u
        still_bad += bad
        print(f"[drama {did}] 已更新 {u}/{n},仍不达标 {bad}", flush=True)

    print("\n" + "=" * 60, flush=True)
    print(f"完成:尝试 {total} 个,已回写 {updated} 个,仍不达标 {still_bad} 个,"
          f"失败项目 {len(failed_dramas)} 个", flush=True)
    if failed_dramas:
        print(f"失败项目: {failed_dramas}", flush=True)
    if still_bad or failed_dramas:
        print("建议:检查文本模型配置后重跑(相同命令即可,已达标的会自动跳过)。", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
