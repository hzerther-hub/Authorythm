# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置(三个平台共用一个 spec)。

用法:
    pyinstaller app.spec --noconfirm

产物:
    dist/pydrama/pydrama.exe        (Windows)
    dist/pydrama/pydrama             (Linux)
    dist/pydrama/pydrama.app         (macOS)

**关键设计**(改之前先读 app/core/config.py 的 _base_dir / _bundle_dir):

1. **用户数据与只读资源分开**:
   - `app/assets/`(字体/logo)与 `workspace/`(提示词+技能)打进包里,运行时从
     `sys._MEIPASS` 读 → `config.BUNDLE_DIR`;
   - `data/`(数据库、生成的图片)与用户可编辑的 `workspace/` 落在** exe 同级目录**
     → `config.ROOT_DIR`。
   - 绝不能让数据目录指向 `sys._MEIPASS`:onefile 模式退出即删那个临时目录,
     用户的库和提示词会在每次退出时一起蒸发。

2. **workspace 首次启动会被播种**:exe 同级没有 workspace/ 时,
   `prompts.seed_prompt_files()` 把包内那份只读副本复制过去(只补缺失),
   否则 16 语言提示词与技能会退化成中文内置版。

3. **ffmpeg 不打包**:几十 MB 且三平台二进制不同 → 用 `FFMPEG_BIN` 环境变量
   或 `vendor/ffmpeg/bin/` 目录(见 docs 里的安装指南)。
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()
APP_NAME = "pydrama"
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# ── 只读资源:原样保留 app/ 与 workspace/ 的层级 ──────────────────────────
# 源码运行时资源在 <repo>/app/assets,打包后从 sys._MEIPASS/app/assets 读 ——
# 两边路径一致,`config.assets_dir()` 就不必分支。
datas = [
    (str(ROOT / "app" / "assets"), "app/assets"),
]
# workspace:16 语言提示词(168 个 md)+ 11 组技能(165 个 md)
for sub in ("prompts", "skills"):
    d = ROOT / "workspace" / sub
    if d.is_dir():
        datas.append((str(d), f"workspace/{sub}"))

# ── 隐藏导入 ─────────────────────────────────────────────────────────────
hiddenimports = [
    # PySide6 的部分模块是动态导入的,PyInstaller 静态分析看不到
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtNetwork",
    "PySide6.QtSvg", "PySide6.QtPrintSupport",
    # cryptography 的 Rust 扩展(静态加密层必需)
    "cryptography.hazmat.bindings._rust",
    # 音频/图像的可选依赖:缺了会静默退化,显式声明避免打包期报错
    "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont",
]
# cryptography / opencc 的子模块自动收集
for pkg in ("cryptography", "opencc"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:  # noqa: BLE001
        pass

# ── Windows 图标(需要 .ico;没有就用默认)────────────────────────────────
icon_path = ""
ico = ROOT / "app" / "assets" / "logo.ico"
if IS_WIN and ico.is_file():
    icon_path = str(ico)

block_cipher = None
a = Analysis(
    # 入口用包级启动器 run_pydrama.py —— 直接用 app/main.py 会因为它是
    # `__main__` 而没有包上下文,包内相对导入全部失效
    # (ImportError: attempted relative import with no known parent package)。
    [str(ROOT / "run_pydrama.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 明确排除:这些包本项目用不到,排除能显著减小体积
        "tkinter", "matplotlib", "numpy.f2py", "pytest", "PyQt5", "PyQt6",
        "IPython", "jupyter", "notebook",
        # PySide6 的 QML/Quick 组件本项目完全不用,排除能省几百 MB
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D",
        "PySide6.QtQuickWidgets", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
        "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus",
        "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtDesigner",
        "PySide6.QtHelp", "PySide6.QtUiTools", "PySide6.QtTest",
        "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSql",
        "PySide6.QtDataVisualization", "PySide6.QtCharts",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX 压缩常被杀软误报,不用
    console=False,       # GUI 程序:不要黑窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,    # 用构建机的架构
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

# ── macOS:打成 .app bundle ───────────────────────────────────────────────
if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="com.yihao.pydrama",
        version="1.1.0",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [],
            "NSPhotoLibraryUsageDescription": "保存与读取生成的图片素材",
        },
    )
