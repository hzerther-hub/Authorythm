"""离屏截图:打开某一集制作页并保存 PNG(用于对齐原版界面的目视检查)。

用法:py -3.13 -X utf8 scripts/shot_episode.py <drama_id> <episode_id> <out.png> [dark]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.core import db, theme

OUT = sys.argv[3] if len(sys.argv) > 3 else "shot.png"
MODE = sys.argv[4] if len(sys.argv) > 4 else "light"
did = int(sys.argv[1]) if len(sys.argv) > 1 else 0
eid = int(sys.argv[2]) if len(sys.argv) > 2 else 0

app = QApplication(sys.argv)
theme.apply_theme(app, MODE)

if not did:
    row = db.q1("SELECT id FROM dramas ORDER BY id LIMIT 1")
    did = row["id"] if row else 0
if not eid and did:
    row = db.q1("SELECT id FROM episodes WHERE drama_id=? ORDER BY episode_number LIMIT 1", (did,))
    eid = row["id"] if row else 0

from app.ui.main_window import MainWindow  # noqa: E402

win = MainWindow()
win.resize(1500, 940)
win.show()
if did and eid:
    win._enter_episode(did, eid)
    win.episode_page._goto_step(sys.argv[5] if len(sys.argv) > 5 else "assets")


def shot():
    win.grab().save(OUT)
    print("saved", OUT)
    app.quit()


QTimer.singleShot(1800, shot)
app.exec()
