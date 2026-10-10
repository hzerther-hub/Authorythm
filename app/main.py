# -*- coding: utf-8 -*-
"""易好短剧 · PySide6 版 入口。

运行:python app/main.py(Python 3.10+)
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .agents.prompts import seed_prompt_files
from .core import db
from .core.i18n import detect_system_language, set_language
from .core.theme import apply_theme, load_bundled_fonts


def _apply_drama_font(app) -> None:
    """字体策略对齐原版 drama(body 栈:SF Pro → PingFang SC → Microsoft YaHei):
    1. assets/fonts/ 打包字体(本仓库内置 msyh.ttc,跨环境一致);
    2. macOS 回落 PingFang SC;Windows 回落 Microsoft YaHei UI。"""
    from PySide6.QtGui import QFont
    families = load_bundled_fonts(app)
    if families:
        app.setFont(QFont(families[0], 10))
        return
    if sys.platform == "darwin":
        f = QFont("PingFang SC", 10)
    else:
        f = QFont("Microsoft YaHei UI", 10)
        f.setStyleHint(QFont.SansSerif)
    f.setPointSize(10)
    app.setFont(f)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PySide6Drama")

    db.init_db()
    seed_prompt_files()
    from .ai.registry import seed_tts_default, seed_faceswap_default, seed_jev_default
    seed_tts_default()
    seed_faceswap_default()
    seed_jev_default()      # 仅当环境变量给了 JEV_API_KEY 才落一条启用配置

    # 界面语言:用户明确选过的(ui_language_explicit=1)尊重所存值;
    # 从没选过的跟随系统语言,系统不在 15 语种内/判断失败回退英文。
    lang = db.get_setting("ui_language", "zh")
    if db.get_setting("ui_language_explicit", "0") != "1":
        lang = detect_system_language()
    set_language(lang)
    _apply_drama_font(app)
    apply_theme(app, db.get_setting("theme", "light"))

    from .ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    _schedule_update_check(win)
    return app.exec()


_UP_THREADS: list = []


def _schedule_update_check(win) -> None:
    """启动后静默检查更新:有新版才 toast 提示(可在「关于更新」关闭)。"""
    from PySide6.QtCore import QTimer, QThread
    from .core import updater
    from .ui.toast import ToastManager

    def _check():
        """静默检查;有新版才提示,任何异常都不影响启动。"""
        if not updater.read_state().get("auto_check", True):
            return
        res: dict = {}

        def done():
            r = res.get("r") or {}
            if r.get("has_update"):
                ToastManager.toast(
                    f"发现新版本 v{r['latest']},可在「设置 → 关于更新」升级", "info", 6000)

        class _T(QThread):
            def run(self):
                try:
                    res["r"] = updater.check()
                except Exception:  # noqa: BLE001
                    res["r"] = {"error": "check failed"}

        th = _T()
        th.finished.connect(done)
        _UP_THREADS.append(th)   # 保持引用,避免 QThread 被回收导致进程退出
        th.start()

    QTimer.singleShot(3000, _check)


if __name__ == "__main__":
    raise SystemExit(main())
