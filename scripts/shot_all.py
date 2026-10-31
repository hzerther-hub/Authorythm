"""离屏截图:批量抓取各页面(项目列表 / 项目详情 / 制作台各步骤 / 任务抽屉)。

用法:py -3.13 -X utf8 scripts/shot_all.py <out_dir> [dark]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.core import db, theme

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/shots")
MODE = sys.argv[2] if len(sys.argv) > 2 else "light"
OUT.mkdir(parents=True, exist_ok=True)
SUFFIX = "" if MODE == "light" else "_dark"

app = QApplication(sys.argv)
theme.apply_theme(app, MODE)

from app.ui.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.resize(1500, 940)
win.show()

did = db.q1("SELECT id FROM dramas WHERE work_type!='novel' ORDER BY id LIMIT 1")["id"]
eid = db.q1("SELECT id FROM episodes WHERE drama_id=? ORDER BY episode_number LIMIT 1",
            (did,))["id"]

STEPS = [("raw", "step_raw"), ("rewrite", "step_rewrite"), ("assets", "step_assets"),
         ("storyboard", "step_storyboard"), ("comic", "step_comic"), ("export", "step_export")]


def shoot():
    jobs = []
    jobs.append(("projects", lambda: win._goto("projects")))
    jobs.append(("project_detail", lambda: (win._goto("projects"), win._open_drama(did))))
    for step, name in STEPS:
        jobs.append((name, (lambda s=step: (win._enter_episode(did, eid), win.episode_page._goto_step(s)))))
    jobs.append(("task_drawer", lambda: (win._enter_episode(did, eid),
                                         win.episode_page._open_tasks())))
    for name, action in jobs:
        try:
            action()
        except Exception as exc:  # noqa: BLE001
            print("skip", name, exc)
            continue
        app.processEvents()
        path = OUT / f"{name}{SUFFIX}.png"
        win.grab().save(str(path))
        print("saved", path)
    win._task_drawer = None
    app.quit()


QTimer.singleShot(1600, shoot)
app.exec()
