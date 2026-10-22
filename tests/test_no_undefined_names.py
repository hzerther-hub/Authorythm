# -*- coding: utf-8 -*-
"""钉死「未定义名」(F821)—— 这类错误在运行时才炸,几乎都是必崩。

实测(2026-10-21 审查):全项目 25 处未定义名,分布在 13 个文件:
  - `err` / `ok` 没导入(toast 函数)→ 回调自己 NameError,**失败被吞得干干净净**
  - `e_` 这种打错的变量名
  - `job` / `done` 孤儿语句(方法被重构后尾巴没删)
  - `QColorDialog` / `QMediaPlayer` / `Path` / `base64` 漏 import
  - `prop_by_id[name]` 这种方向搞反的映射
  - `TASKMGR.submit` 缩进错位写成 `run()` 外面 → 「AI 出整话」一点就炸

**ruff 静态就能全部查出来**,所以把它做成测试:以后谁再写出一个未定义名,
CI 立刻红,而不是等到用户点那个按钮。

ruff 不在环境里就跳过(不因此让整套测试挂掉)。
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _find_ruff() -> list[str] | None:
    """找一个能跑的 ruff。优先 `python -m ruff`(pip 装的),再找 PATH 上的可执行文件。"""
    try:
        subprocess.run([sys.executable, "-m", "ruff", "--version"],
                       capture_output=True, check=True)
        return [sys.executable, "-m", "ruff"]
    except (subprocess.SubprocessError, OSError):
        pass
    exe = shutil.which("ruff")
    if exe and pathlib.Path(exe).exists():
        return [exe]
    return None


RUFF = _find_ruff()


@pytest.mark.skipif(RUFF is None, reason="没装 ruff,跳过静态未定义名检查")
def test_no_undefined_names_in_app():
    """app/ 下不允许有 F821(未定义名)。"""
    cmd = [*RUFF, "check", "--output-format=concise",
           "--select", "F821", "--no-cache", "app/"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    # ruff 对「无违规」返回 0;有违规返回 1 并把清单打到 stdout
    out = [ln for ln in r.stdout.splitlines()
           if ln.strip() and "F821" in ln]
    assert not out, ("app/ 里出现未定义名(运行时会 NameError):\n  "
                     + "\n  ".join(out))


@pytest.mark.skipif(RUFF is None, reason="没装 ruff,跳过静态未定义名检查")
def test_no_f821_in_tests():
    """tests/ 同样不允许有未定义名(测试自己崩了等于没测)。"""
    cmd = [*RUFF, "check", "--output-format=concise",
           "--select", "F821", "--no-cache", "tests/"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    out = [ln for ln in r.stdout.splitlines()
           if ln.strip() and "F821" in ln]
    assert not out, ("tests/ 里出现未定义名:\n  " + "\n  ".join(out))
