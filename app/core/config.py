"""路径与环境配置:数据目录 / SQLite / 媒体目录 / ffmpeg 定位。"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "PySide6Drama"
APP_VERSION = "1.1.0"

# PhotoCraft portable 默认安装位置(Windows 上无安装引导时指向这里)
DEFAULT_PHOTOCRAFT_DIR = r"E:\photocraft\photocraft-0.7.0-windows-x64-portable"


def _base_dir() -> Path:
    """程序根目录(放**用户数据**:data/ 与 workspace/)。

    打包后(PyInstaller)以 **exe 所在目录**为根 —— 这一点很关键:
    onefile 模式把程序解到临时目录 `sys._MEIPASS`,**进程退出即删**。
    若把 ROOT_DIR 指向那里,用户的数据库、生成的图片、编辑过的提示词会在
    每次退出/更新时全部蒸发。只读资源(字体/logo)走 `bundle_dir()`。

    源码运行时就是仓库根(app/ 的上一级)。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller:sys.executable 指向真的 exe/可执行文件
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    return root if root.exists() else Path.cwd()


def _bundle_dir() -> Path:
    """只读资源目录(app/assets/fonts、logo):打包后 = PyInstaller 解包目录。

    源码运行时 = 仓库根。打包后必须用 `sys._MEIPASS` —— 资源被打进包里,
    运行时从那里读;**不能**用 exe 同级目录(那里没有这些文件)。
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
    return _base_dir()


ROOT_DIR = _base_dir()
BUNDLE_DIR = _bundle_dir()
DATA_DIR = Path(os.environ.get("YIHAO_DATA_DIR") or (ROOT_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(os.environ.get("SQLITE_PATH") or (DATA_DIR / "yihao.sqlite3"))
STATIC_DIR = Path(os.environ.get("STORAGE_PATH") or (DATA_DIR / "static"))
STATIC_DIR.mkdir(parents=True, exist_ok=True)
for sub in ("images", "videos", "narration", "merged", "comics", "uploads", "covers"):
    (STATIC_DIR / sub).mkdir(parents=True, exist_ok=True)

# Agent 可编辑提示词工作区(对齐原版 workspace/prompts)
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_PATH") or (ROOT_DIR / "workspace"))
PROMPTS_DIR = WORKSPACE_DIR / "prompts"
PROMPTS_DIR.mkdir(parents=True, exist_ok=True)

# 打包进程序的**只读** workspace 副本(提示词 16 语言 + 技能 11 组)。
# 打包后 exe 同级没有 workspace/,而 load_prompt / load_skills 只读用户目录 ——
# 不把这份副本播种过去,16 语言提示词与技能会全部退化成中文内置版。
BUNDLED_WORKSPACE_DIR = BUNDLE_DIR / "workspace"


def assets_dir() -> Path:
    """打包进程序的只读资源目录(app/assets)。

    保持 `app/assets` 的层级不变 —— 打包 spec 里也按同一路径收进去,
    这样源码运行与打包运行用同一个解析函数,不必分支。
    """
    return BUNDLE_DIR / "app" / "assets"


def find_ffmpeg() -> str | None:
    """定位 ffmpeg:环境变量 FFMPEG_BIN > PATH > vendor 目录。"""
    env = os.environ.get("FFMPEG_BIN")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    vendor = ROOT_DIR / "vendor" / "ffmpeg" / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    return str(vendor) if vendor.exists() else None


def find_ffprobe() -> str | None:
    env = os.environ.get("FFPROBE_BIN")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffprobe")
    if found:
        return found
    vendor = ROOT_DIR / "vendor" / "ffmpeg" / "bin" / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    return str(vendor) if vendor.exists() else None


def media_url_to_path(url: str) -> Path:
    """把存储的 /static/xxx 相对地址转为本地绝对路径。"""
    rel = url.replace("\\", "/")
    if rel.startswith("/static/"):
        rel = rel[len("/static/"):]
    elif rel.startswith("static/"):
        rel = rel[len("static/"):]
    return (STATIC_DIR / rel).resolve()


def path_to_media_url(path: str | Path) -> str:
    p = Path(path).resolve()
    try:
        rel = p.relative_to(STATIC_DIR)
    except ValueError:
        return str(p)
    return "/static/" + rel.as_posix()


def resolve_content_language(drama_id: int | None = None) -> str:
    """项目级内容语言优先,回退全局 app_settings.content_language。

    对齐原版 a6a47dc:dramas.language='auto' 表示跟随全局,其他值固定该语言,
    各项目互不干扰。返回 15 语种之一。
    """
    from .i18n import LANGS
    valid = {c for c, _ in LANGS}
    if drama_id:
        try:
            from . import db
            row = db.q1("SELECT language FROM dramas WHERE id=?", (drama_id,))
            v = (row["language"] if row else None) or "auto"
            if v and v != "auto" and v in valid:
                return v
        except Exception:  # noqa: BLE001
            pass
        # 内存态回退(调用发生在 db 初始化前)
        try:
            from . import db
            g = db.get_setting("content_language", "zh")
            if g in valid:
                return g
        except Exception:  # noqa: BLE001
            pass
    return "zh"
