# -*- coding: utf-8 -*-
"""项目启动台:对齐原版 pages/index.vue 的 header / toolbar / 项目卡网格。"""
from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from .confirm import ask
from ..core import db
from ..core.i18n import tr
from . import widgets as W
from .toast import ok

# 模块级求值 tr() 会在 import 时定死语言,切语言后不跟着变 → 改成函数按需查
WT_KEYS = {"novel": "wt_novel", "drama": "wt_drama", "comic": "wt_comic",
           "promotion": "wt_promotion", "video_clone": "wt_clone"}


def wt_label(work_type: str) -> str:
    return tr(WT_KEYS.get(work_type, work_type))

# 状态色固定;标签走 i18n 词典(不能在导入时求值,否则切语言不生效)
STATUS_META = {"pending": "#86909c", "active": "#16a34a", "completed": "#f97316"}
STATUS_KEY = {"pending": "u_pending", "active": "u_running", "completed": "u_done"}


def status_label(status: str) -> str:
    return tr(STATUS_KEY.get(status, "u_pending"))


FILTER_KEYS = ["all", "draft", "active", "completed"]
FILTER_LABEL_KEY = {"all": "全部", "draft": "待开始", "active": "进行中", "completed": "已完成"}
FILTER_DB = {"all": None, "draft": "pending", "active": "active", "completed": "completed"}


def filter_label(key: str) -> str:
    """筛选项标签现取 —— 模块级写 tr() 会把语言定死在 import 那一刻,之后切不动。"""
    return tr(FILTER_LABEL_KEY.get(key, key))


def _fmt_ago(ts: str) -> str:
    """相对时间(对齐原版:刚刚 / N分钟前 / N小时前 / N天前 / M/D)。"""
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:  # noqa: BLE001
        return ts[:16]
    if secs < 60:
        return tr("刚刚")
    if secs < 3600:
        return f"{int(secs // 60)} 分钟前"
    if secs < 86400:
        return f"{int(secs // 3600)} 小时前"
    if secs < 86400 * 7:
        return f"{int(secs // 86400)} 天前"
    return f"{dt.month}/{dt.day}"


def _dot_icon(color: str):
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
    pm = QPixmap(12, 12)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(3, 3, 6, 6)
    p.end()
    return QIcon(pm)


def _pill(text: str, tone: str = "") -> QLabel:
    """统计胶囊(对齐 .hero-stats 里的 .tag)。"""
    lab = QLabel(text)
    style = "background:#f2f3f5; color:#4e5969;"
    if tone == "success":
        style = "background:#e6f6ee; color:#16a34a;"
    elif tone == "accent":
        style = "background:#fdf0e6; color:#f97316;"
    lab.setStyleSheet(style + " border-radius:999px; padding:3px 10px; font-size:11px;")
    return lab


class ProjectCard(QFrame):
    open_requested = Signal(int)
    delete_requested = Signal(int, str)
    status_changed = Signal(int, str)

    def __init__(self, drama: dict):
        super().__init__()
        self.setObjectName("card")
        self.drama_id = drama["id"]
        self._title = drama["title"]
        self.setFixedSize(260, 244)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("click_open_project"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 封面块 2.1:1(对齐 .project-cover)
        cover = QFrame()
        cover.setFixedHeight(112)
        cover.setStyleSheet(
            "QFrame#cover{background:linear-gradient(135deg,#fdf0e6 0%,#f7f8fa 70%);"
            "border:none; border-bottom:1px solid #e4e7ec; border-top-left-radius:10px;"
            "border-top-right-radius:10px;}")
        cover.setObjectName("cover")
        cl = QVBoxLayout(cover)
        cl.setContentsMargins(10, 10, 10, 10)
        if drama.get("thumbnail"):
            img = QLabel()
            img.setAlignment(Qt.AlignCenter)
            img.setPixmap(W.pixmap_from_media(drama["thumbnail"], 240, 92))
            cl.addWidget(img)
        else:
            init = QLabel((drama["title"] or "?")[:1].upper())
            init.setAlignment(Qt.AlignCenter)
            init.setStyleSheet(
                "color:#f97316; opacity:0.55; font-size:30px; font-weight:700; border:none;")
            cl.addWidget(init)
        cover_ratios = QHBoxLayout()
        cover_ratios.addStretch(1)
        if drama.get("aspect_ratio") and drama["aspect_ratio"] != "adaptive":
            rc = QLabel(drama["aspect_ratio"])
            rc.setStyleSheet(
                "background:#ffffff; color:#86909c; border:1px solid #e4e7ec;"
                "border-radius:5px; padding:2px 7px; font-family:monospace; font-size:10px;")
            cover_ratios.addWidget(rc)
        cl.addLayout(cover_ratios)
        # 状态徽标(左上)+ 更多(右上,常显;QSS 做不到 hover 才显)
        marks = QHBoxLayout()
        self.status_btn = QPushButton()
        self.status_btn.setCursor(Qt.PointingHandCursor)
        self.status_btn.setFixedHeight(22)
        self._apply_status_style(drama.get("status") or "pending")
        self.status_btn.clicked.connect(self._status_menu)
        marks.addWidget(self.status_btn)
        marks.addStretch(1)
        more = QPushButton("⋯")
        more.setFixedSize(28, 22)
        more.setCursor(Qt.PointingHandCursor)
        more.setStyleSheet(
            "QPushButton{background:#ffffff;border:1px solid #e4e7ec;border-radius:6px;"
            "color:#4e5969;padding:0;}")
        more.clicked.connect(self._menu)
        marks.addWidget(more)
        cl.addLayout(marks)
        lay.addWidget(cover)

        # 主体
        body = QWidget()
        body.setStyleSheet("border:none;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 12, 14, 12)
        bl.setSpacing(0)
        title = W.h2(drama["title"])
        title.setStyleSheet("font-size:14px; font-weight:600;")
        title.setToolTip(drama["title"])
        bl.addWidget(title)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(W.tag(wt_label(drama["work_type"])))
        nm = db.jload(drama["novel_meta"], {}) or {}
        if (nm.get("imitated_from") or {}).get("drama_id"):
            imi = W.tag(tr("imitated"))
            imi.setStyleSheet(
                "background:rgba(168,85,247,0.08); color:#a855f7;"
                "border:1px solid rgba(168,85,247,0.45); border-radius:4px;"
                "padding:2px 8px; font-size:12px;")
            imi.setToolTip(tr("imitated_tip"))
            chips.addWidget(imi)
        style = db.q1("SELECT name FROM style_presets WHERE value=?", (drama["style"],))
        if style and drama["work_type"] != "novel":
            st = W.tag(style["name"])
            st.setStyleSheet("background:#fdf0e6; color:#f97316; border-radius:4px;"
                             "padding:2px 8px; font-size:12px;")
            chips.addWidget(st)
        chips.addStretch(1)
        bl.addLayout(chips)
        nc = db.q1("SELECT COUNT(*) c FROM characters WHERE drama_id=?", (drama["id"],))["c"]
        ns = db.q1("SELECT COUNT(*) c FROM scenes WHERE drama_id=?", (drama["id"],))["c"]
        ne = db.q1("SELECT COUNT(*) c FROM episodes WHERE drama_id=?", (drama["id"],))["c"]
        meta = QLabel(f"{nc} 角色 · {ns} 场景 · {ne} 集")
        meta.setObjectName("muted")
        bl.addWidget(meta)
        bl.addStretch(1)
        foot = QHBoxLayout()
        ago = QLabel(f"🕘 {_fmt_ago(drama['updated_at'])}")
        ago.setObjectName("muted")
        foot.addWidget(ago)
        foot.addStretch(1)
        bl.addLayout(foot)
        lay.addWidget(body, 1)

    def _apply_status_style(self, status: str):
        label, color = status_label(status), STATUS_META.get(status, STATUS_META["pending"])
        self.status_btn.setText(f"●  {label}")
        self.status_btn.setStyleSheet(
            f"QPushButton{{color:{color}; background:#ffffff; border:1px solid {color}44;"
            f"border-radius:12px; font-size:11px; padding:0 10px;}}")

    def _status_menu(self):
        m = QMenu(self)
        for key in STATUS_META:
            act = m.addAction(f"●  {status_label(key)}")
            act.setIcon(_dot_icon(STATUS_META[key]))
            act.triggered.connect(lambda _=False, k=key: self.status_changed.emit(self.drama_id, k))
        m.exec()

    def _menu(self):
        m = QMenu(self)
        a1 = m.addAction(tr("open_project"))
        a2 = m.addAction(tr("delete_project"))
        act = m.exec()
        if act == a1:
            self.open_requested.emit(self.drama_id)
        elif act == a2:
            self.delete_requested.emit(self.drama_id, self._title)

    def mousePressEvent(self, ev):
        if getattr(self, "_btn_clicked", False):
            self._btn_clicked = False
        else:
            self.open_requested.emit(self.drama_id)
        super().mousePressEvent(ev)


class ProjectsPage(QWidget):
    open_drama = Signal(int)

    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 20, 28, 24)
        root.setSpacing(16)

        # ── 头部:标题 + 副标题 + 三枚统计胶囊 + 新建项目 ──
        head = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(2)
        title = W.h1(tr("launcher_title"))
        title.setStyleSheet("font-size:20px; font-weight:650;")
        left.addWidget(title)
        sub = QLabel(tr("launcher_sub"))
        sub.setObjectName("muted")
        left.addWidget(sub)
        head.addLayout(left, 1)
        self.stats = QHBoxLayout()
        self.stats.setSpacing(8)
        self._stat_projects = _pill("")
        self._stat_running = _pill("", "success")
        self._stat_styles = _pill("", "accent")
        for w in (self._stat_projects, self._stat_running, self._stat_styles):
            self.stats.addWidget(w)
        head.addLayout(self.stats)
        new_btn = W.primary_btn("＋ " + tr("new_project"))
        new_btn.clicked.connect(self._new_project)
        head.addWidget(new_btn)
        root.addLayout(head)

        # ── 工具条:搜索 + 状态胶囊 + 排序 ──
        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("search"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(240)
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search)
        self._filter_btns: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for key in FILTER_KEYS:
            b = QPushButton(filter_label(key))
            b.setObjectName("filterChip")
            b.setCheckable(True)
            b.setChecked(key == "all")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            group.addButton(b)
            self._filter_btns[key] = b
            bar.addWidget(b)
        self._filter = "all"
        bar.addStretch(1)
        from PySide6.QtWidgets import QComboBox
        self.sort = QComboBox()
        self.sort.setFixedWidth(132)
        self.sort.addItem(tr("sort_recent"), "recent")
        self.sort.addItem(tr("sort_title"), "title")
        self.sort.currentIndexChanged.connect(self.reload)
        bar.addWidget(self.sort)
        root.addLayout(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.holder = QWidget()
        self.grid = QGridLayout(self.holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(16)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.holder)
        root.addWidget(self.scroll, 1)
        self._new_cb = None
        self.reload()

    def set_new_callback(self, cb) -> None:
        self._new_cb = cb

    def _new_project(self):
        if self._new_cb:
            self._new_cb()

    def _set_filter(self, key: str):
        self._filter = key
        self._filter_btns[key].setChecked(True)
        self.reload()

    def reload(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        kw = self.search.text().strip()
        want = FILTER_DB.get(self._filter)
        rows = [dict(r) for r in db.q("SELECT * FROM dramas")]
        shown = [d for d in rows
                 if (not kw or kw in d["title"])
                 and (want is None or (d.get("status") or "pending") == want)]
        if self.sort.currentData() == "title":
            shown.sort(key=lambda x: x["title"])
        else:
            shown.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
        cols = max(1, (self.scroll.viewport().width() or 1200) // 276)
        for i, d in enumerate(shown):
            card = ProjectCard(d)
            card.open_requested.connect(self.open_drama.emit)
            card.delete_requested.connect(self._delete)
            card.status_changed.connect(self._set_status)
            self.grid.addWidget(card, i // cols, i % cols)
        if not shown:
            self.grid.addWidget(self._empty_state(bool(rows)), 0, 0)
        running = sum(1 for d in rows if d.get("status") == "active")
        self._stat_projects.setText(tr("n_projects", len(rows)))
        self._stat_running.setText(tr("n_running", running))
        self._stat_styles.setText(tr("n_styles",
                                      len(db.q("SELECT id FROM style_presets WHERE is_active=1"))))

    def _empty_state(self, has_rows: bool) -> QWidget:
        from . import episode_cards as C
        box = QFrame()
        box.setObjectName("emptyState")
        box.setMinimumHeight(240)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 24, 16, 24)
        lay.setSpacing(10)
        icon = QLabel("⊞" if not has_rows else "🔍")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("font-size:30px; color:#f97316;")
        lay.addWidget(icon)
        title = QLabel(tr("empty_first_project") if not has_rows else tr("empty_no_match"))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight:600; font-size:14px;")
        lay.addWidget(title)
        desc = QLabel(tr("empty_first_desc") if not has_rows else tr("empty_no_match_desc"))
        desc.setAlignment(Qt.AlignCenter)
        desc.setObjectName("muted")
        lay.addWidget(desc)
        if not has_rows:
            btn = W.primary_btn(tr("new_project"))
            btn.clicked.connect(self._new_project)
            lay.addWidget(btn, 0, Qt.AlignCenter)
        return box

    def _set_status(self, drama_id: int, status: str):
        db.ex("UPDATE dramas SET status=?, updated_at=? WHERE id=?", (status, db.now(), drama_id))
        ok(f"{tr('status_marked')}: {status_label(status)}")
        self.reload()

    def _delete(self, drama_id: int, _title: str):
        from PySide6.QtWidgets import QMessageBox
        d = db.q1("SELECT title FROM dramas WHERE id=?", (drama_id,))
        if not d:
            return
        if not ask(self, tr("delete_project"), tr("confirm_delete_project", d["title"]),
                   danger=True):
            return
        for t in ("episode_characters", "episode_scenes", "episode_props"):
            db.ex(f"DELETE FROM {t} WHERE episode_id IN (SELECT id FROM episodes WHERE drama_id=?)", (drama_id,))
        for t in ("storyboard_characters", "storyboard_props"):
            db.ex(f"DELETE FROM {t} WHERE storyboard_id IN (SELECT id FROM storyboards WHERE episode_id IN (SELECT id FROM episodes WHERE drama_id=?))", (drama_id,))
        db.ex("DELETE FROM storyboards WHERE episode_id IN (SELECT id FROM episodes WHERE drama_id=?)", (drama_id,))
        db.ex("DELETE FROM comic_panel_characters WHERE panel_id IN (SELECT id FROM comic_panels WHERE episode_id IN (SELECT id FROM episodes WHERE drama_id=?))", (drama_id,))
        db.ex("DELETE FROM comic_panels WHERE episode_id IN (SELECT id FROM episodes WHERE drama_id=?)", (drama_id,))
        db.ex("DELETE FROM video_merges WHERE episode_id IN (SELECT id FROM episodes WHERE drama_id=?)", (drama_id,))
        db.ex("DELETE FROM episodes WHERE drama_id=?", (drama_id,))
        db.ex("DELETE FROM characters WHERE drama_id=?", (drama_id,))
        db.ex("DELETE FROM scenes WHERE drama_id=?", (drama_id,))
        db.ex("DELETE FROM props WHERE drama_id=?", (drama_id,))
        db.ex("DELETE FROM dramas WHERE id=?", (drama_id,))
        self.reload()