#!/usr/bin/env bash
# macOS 打包脚本
#
# 用法(仓库根目录):
#     bash scripts/build_macos.sh
#
# 产物:dist/pydrama/pydrama.app
#
# 前提:
#     Python 3.13 + 已 pip install -r requirements-dev.txt
#     Xcode 命令行工具(xcode-select --install)
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3.13}"

if [ "${SKIP_DEPS:-0}" != "1" ]; then
    echo "==> 安装依赖"
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -r requirements-dev.txt
fi

echo "==> 清理旧产物"
rm -rf build dist

echo "==> PyInstaller"
"$PY" -m PyInstaller app.spec --noconfirm --clean

APP="dist/pydrama/pydrama.app"

if [ "${SIGN:-0}" = "1" ] && [ -n "${IDENTITY:-}" ]; then
    echo "==> 签名 $IDENTITY"
    codesign --force --deep --options runtime --sign "$IDENTITY" "$APP"
    codesign --verify --deep --strict --verbose=2 "$APP"
else
    echo "==> 未签名(开发机自用够了;分发给别人需 Apple Developer 证书)"
    echo "    分发时: SIGN=1 IDENTITY='Developer ID Application: XXX (TEAMID)' bash scripts/build_macos.sh"
fi

echo ""
echo "完成:$APP"
echo "提醒:ffmpeg 不在包里 —— 请下载二进制放到 .app 同级的 vendor/ffmpeg/bin/,"
echo "      或设环境变量 FFMPEG_BIN 指向 ffmpeg。"
echo "另外:未签名的 app 在别的 Mac 上打开会被 Gatekeeper 拦,"
echo "      需要右键打开 或 设 quarantine 属性清除。"
