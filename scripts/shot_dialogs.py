"""离屏截图:抓小说策划面板 / 项目设置 / 整书导入对话框。

用法:py -3.13 -X utf8 scripts/shot_dialogs.py <out_dir> [drama_id]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.core import db, theme

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/shots")
OUT.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
theme.apply_theme(app, "light")

did = int(sys.argv[2]) if len(sys.argv) > 2 else None
if not did:
    row = db.q1("SELECT id FROM dramas WHERE work_type='novel' ORDER BY id DESC LIMIT 1")
    did = row["id"]

from app.ui.asset_dialogs import ProjectSettingsDialog  # noqa: E402
from app.ui.book_import_dialog import BookImportDialog  # noqa: E402
from app.ui.novel_dialogs import NovelPlanDialog  # noqa: E402

shots = [("settings", ProjectSettingsDialog(None, did), (520, 780)),
         ("novel_plan", NovelPlanDialog(None, did), (860, 720)),
         ("book_import", BookImportDialog(None, did), (760, 640))]

windows = [(n, w) for n, w, s in shots]
for n, w, s in shots:
    w.resize(*s)
    w.show()
for n, w in windows:
    if n == "novel_plan":
        w.tabs.setCurrentIndex(w.tabs.count() - 1)      # 章节计划(主要角色已并入)


def shot():
    for n, w in windows:
        w.grab().save(str(OUT / f"{n}.png"))
        print("saved", OUT / f"{n}.png")
    app.quit()


QTimer.singleShot(1500, shot)
app.exec()
