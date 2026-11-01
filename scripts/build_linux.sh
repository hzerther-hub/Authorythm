#!/usr/bin/env bash
# Linux 打包脚本
#
# 用法(仓库根目录):
#     bash scripts/build_linux.sh
#
# 产物:dist/pydrama/pydrama
#
# 前提:
#     Python 3.13 + 已 pip install -r requirements-dev.txt
#     系统装了 libxcb / libxkbcommon 等 Qt 运行库
#       (Debian/Ubuntu: libxcb-cursor0 libxkbcommon-x11-0 libegl1 libgl1)
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

echo ""
echo "完成:dist/pydrama/pydrama"
echo "提醒:ffmpeg 不在包里 —— 请下载二进制放到 exe 同级的 vendor/ffmpeg/bin/,"
echo "      或设环境变量 FFMPEG_BIN 指向 ffmpeg。"
