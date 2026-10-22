# -*- coding: utf-8 -*-
"""以后台独立进程启动 GUI(不挂控制台),让应用**脱离调用方 shell 的生命周期**存活。

为什么不用 `python.exe`:
    `python.exe` 是控制台程序。哪怕用 Start-Process 拉起来,它的控制台仍可能
    在父 shell 退出时被一起拆掉 —— 实测应用被连带杀死:窗口消失、进程无痕,
    而 Windows 事件日志无 python/Qt 崩溃记录、应用日志也无 ERROR。
    典型的「后台任务超时被中止 → 子进程陪葬」。

为什么不用 `-WindowStyle Hidden`:
    会把 GUI 窗口藏起来,用户看不到应用。

pythonw.exe 的坑:`sys.stdout` / `sys.stderr` 是 **None**,任何 print() 会炸
(AttributeError: 'NoneType' object has no attribute 'write')。
所以先把它们接到文件上 —— 既不依赖控制台,又保留崩溃现场。

用法(推荐走 pythonw.exe,这样父 shell 退出也不影响):
    py -3.13 -c "import subprocess,sys; subprocess.Popen([sys.executable.replace('python.exe','pythonw.exe'), 'scripts/launch_app.py'])"

或直接:
    scripts\\launch_app.py

    stdout/stderr 落在 data/logs/app_stdout.log / app_stderr.log。

注意:别开两个实例。会话内重复启动时,后一个的 db 锁拿不到,
init_db 会跳过「僵尸任务回收」(见 app/core/db.py:_acquire_db_lock),
不会误杀前一个实例正在跑的任务。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "logs"


def _attach_streams() -> None:
    """pythonw.exe 下 stdout/stderr 是 None —— 接到文件上,否则 print() 会炸。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None:
        sys.stdout = open(LOG_DIR / "app_stdout.log", "a", encoding="utf-8", buffering=1)
    if sys.stderr is None:
        sys.stderr = open(LOG_DIR / "app_stderr.log", "a", encoding="utf-8", buffering=1)


def main() -> int:
    _attach_streams()
    sys.path.insert(0, str(ROOT))
    try:
        from app.main import main as app_main
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return 1
    try:
        return app_main()
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
