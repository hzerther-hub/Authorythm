# -*- powershell -*-
# 易好短剧 · PySide6 版 启动脚本(PowerShell 版)
# 优先用 py 启动器(会自动选 .pythonbrew 注册的 3.13),失败回退 python。
# 用法:  powershell -ExecutionPolicy Bypass -File .\start.ps1
Set-Location $PSScriptRoot
try {
    & py -3.13 -m app.main 2>$null
    if ($LASTEXITCODE -eq 0) { exit 0 }
} catch {}
python -m app.main
