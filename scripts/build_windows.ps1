# Windows 打包脚本
#
# 用法(仓库根目录):
#     powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#
# 产物:dist\pydrama\pydrama.exe
#
# 前提:
#     Python 3.13 + 已 pip install -r requirements-dev.txt
#     app\assets\logo.ico 存在(没有就 python -m scripts.make_ico 生成)
param(
    [switch]$SkipDeps
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = "py"
if (-not (Get-Command py -ErrorAction SilentlyContinue)) { $py = "python" }

if (-not $SkipDeps) {
    Write-Host "==> 安装依赖"
    & $py -3.13 -m pip install --upgrade pip
    & $py -3.13 -m pip install -r requirements-dev.txt
}

Write-Host "==> 生成 Windows 图标"
& $py -3.13 -m scripts.make_ico

Write-Host "==> 清理旧产物"
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }

Write-Host "==> PyInstaller"
& $py -3.13 -m PyInstaller app.spec --noconfirm --clean

Write-Host ""
Write-Host "完成:dist\pydrama\pydrama.exe"
Write-Host "提醒:ffmpeg 不在包里 —— 请下载二进制放到 exe 同级的 vendor\ffmpeg\bin\,"
Write-Host "      或设环境变量 FFMPEG_BIN 指向 ffmpeg.exe。"
