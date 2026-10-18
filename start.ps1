# -*- powershell -*-
# 易好短剧 · PySide6 版 启动脚本(PowerShell 版)
# 优先用仓库自带的 .venv:依赖是齐的(PySide6 6.12 + cryptography)。
# 没有 .venv 才回退 py 启动器 / python。
# 踩过的坑:本机全局是 Python 3.14 且**没装 cryptography**,回退到 python 时
# 会在 `app.core.secrets` 的 import 处直接崩 —— 表现为启动即退、没有任何 UI 提示,
# 光看窗口只会以为「双击没反应」。
# 用法:  powershell -ExecutionPolicy Bypass -File .\start.ps1
Set-Location $PSScriptRoot

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    # stderr 合并进 stdout:Qt 槽里的异常堆栈只走 stderr,丢掉它就永远
    # 查不到「点了没反应」类问题(实测批量视频静默失败就是这么盲的)
    & $venvPy -m app.main 2>&1
    exit $LASTEXITCODE
}
try {
    & py -3.13 -m app.main 2>&1
    if ($LASTEXITCODE -eq 0) { exit 0 }
} catch {}
python -m app.main 2>&1
