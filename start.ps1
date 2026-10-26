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
# py 启动器存在就**只用它**:此前的写法是 py 失败(非 0 退出)就再落回
# `python -m app.main` —— 而"失败"也包括用户关窗/被杀/单实例闸门拦下,
# 于是每次退出都会**自动再起一个新实例**,和用户手动启动的实例撞单实例闸门,
# 弹「易好短剧已在运行」的警告(2026-10-26 实测:杀一个、弹两个,越杀越多)。
# 本机 py -3.13 依赖齐全(3.13.15 + cryptography),回落分支只留给没有 py
# 启动器的机器。
$pyCmd = Get-Command py -ErrorAction SilentlyContinue
if ($pyCmd) {
    & py -3.13 -m app.main 2>&1
    exit $LASTEXITCODE
}
python -m app.main 2>&1
