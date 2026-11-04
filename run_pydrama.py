"""PyInstaller 打包入口。

**为什么需要这个文件**:打包不能直接用 `app/main.py` —— 那个文件用的是
包内相对导入(`from .agents.prompts import ...`),而 PyInstaller 把入口脚本
当 `__main__` 执行,没有包上下文 → 运行时抛
`ImportError: attempted relative import with no known parent package`。
用这个包级启动器包一层,导入就变成 `app.main` 这个正规包路径。

源码运行仍然用 `python -m app.main`;本文件只给打包用。
"""
from __future__ import annotations

import multiprocessing


def main() -> int:
    # 打包后的多进程:Windows 用 spawn,子进程会重新执行入口脚本。
    # 不设 freeze_support 的话,子进程会再次进入这里造成无限递归。
    multiprocessing.freeze_support()
    from app.main import main as app_main
    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
