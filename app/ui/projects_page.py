# -*- coding: utf-8 -*-
"""项目启动台:对齐原版 pages/index.vue 的 header / toolbar / 项目卡网格。

视觉重写:Director's Slate —— 把每个项目卡上方加一条拍板条(SlateStrip:黑底 +
斜白条 + mono 生产码),卡片四角回到 4px 圆角、1px 细灰边;整体脱离 SaaS 常见的
橙色胶囊,统一回纸白底 + 拍板黑主色。详见 app/core/theme.py 里的 SLATE_* token。
"""
from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtGui import QCursor, QPainter, QPolygon, QFont
from PySide6.QtCore import Qt, Signal, QPoint, QRect
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from .confirm import ask
from ..core import db
from ..core.i18n import tr
from ..core.theme import (SLATE_BAR, SLATE_BAR_INK, SLATE_BAR_DIM, SLATE_BG, SLATE_PAPER,
                          SLATE_MUTED, SLATE_HAIR, SLATE_HAIR_HV, SLATE_META, SLATE_STRIPE,
                          SLATE_TRACK, SLATE_ST_DONE, SLATE_ST_PROG, SLATE_ST_PEND,
                          SLATE_ST_FAIL, SLATE_CARD_QSS, MONO_STACK)
from . import widgets as W
from .toast import ok

# 模块级求值 tr() 会在 import 时定死语言,切语言后不跟着变 → 改成函数按需查
WT_KEYS = {"novel": "wt_novel", "drama": "wt_drama", "comic": "wt_comic",
           "promotion": "wt_promotion", "video_clone": "wt_clone"}


def wt_label(work_type: str) -> str:
    return tr(WT_KEYS.get(work_type, work_type))


class _CoverLabel(QLabel):
    """可点击的封面图:点左键弹大图预览,并拦下卡片"整卡点击进项目"的默认行为。"""
    clicked = Signal()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
            ev.accept()
            return
        super().mousePressEvent(ev)

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
        return tr('{} 分钟前').format(int(secs // 60))
    if secs < 86400:
        return tr('{} 小时前').format(int(secs // 3600))
    if secs < 86400 * 7:
        return tr('{} 天前').format(int(secs // 86400))
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


def _one_line(text: str | None, max_len: int = 200) -> str:
    """把多行文本压成单行摘要(去换行 + 折叠空白)。

    项目级 TXT 导出的字段摘要用 —— 一行一个字段看起来像清单,
    比起多行堆叠更适合「快速浏览 + 复制粘贴到其它工具」。
    """
    if not text:
        return "(空)"
    s = " ".join(text.split())
    return s if len(s) <= max_len else s[:max_len] + "…"


class SlateStrip(QFrame):
    """拍板顶条 —— 每张项目卡的视觉签名。

    视觉原理(对应 board 上的 clapper):
        ┌───════════════════════════════════════───┐
        │ ▓▓  PROJECT N°0003  ·  EP02  ·  TAKE 04/12 │   ← 30px 高
        └───════════════════════════════════════───┘

    黑色背景 + 左侧 ~60px 内斜白条;QSS/QPalette 都做不出标准的 45° 斜条,所以用
    paintEvent 画一组并行四边形。斜白条只占左侧 STRIPE_W,右侧整块黑底铺生产码。

    故意脱离 SaaS 常见橙色 / 渐变胶囊,回到片场视觉 —— 这是这块 UI 的"签名元素",
    其它面板不必引入,见 theme.py 注释。
    """
    STRIPE_W = 60        # 斜条带宽度
    SLASH_W = 11         # 单根斜条宽
    SLASH_GAP = 8        # 斜条间距
    HEIGHT = 30          # 整条高度

    def __init__(self, project_no: str, ep_label: str, take_label: str,
                 *, status: str = "pending", scene_meta: str = ""):
        super().__init__()
        self.setFixedHeight(self.HEIGHT)
        self.setStyleSheet("background:transparent; border:none;")
        self._left_meta = f"{project_no}  ·  {ep_label}  ·  {take_label}"
        self._right_meta = scene_meta
        # 状态点的小圆用 paintEvent 直接画(右下角),不走额外 widget
        self._status = status

    def paintEvent(self, ev):
        from PySide6.QtGui import QColor
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        # 1. 黑底
        p.fillRect(0, 0, w, h, QColor(SLATE_BAR))
        # 2. 左侧斜白条(限制在 STRIPE_W 范围内 —— 用 clipRect 物理裁剪)
        p.save()
        p.setClipRect(0, 0, self.STRIPE_W, h)
        step = self.SLASH_W + self.SLASH_GAP
        # 让第一根斜条从画面外左侧斜入,一直铺到 STRIPE_W 右侧外
        start = -h
        end = self.STRIPE_W + h
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(SLATE_STRIPE))
        x = start
        while x < end:
            poly = QPolygon([
                QPoint(x, h),
                QPoint(x + self.SLASH_W, h),
                QPoint(x + self.SLASH_W - h, 0),
                QPoint(x - h, 0),
            ])
            p.drawPolygon(poly)
            x += step
        p.restore()
        # 3. 主文字(左侧 meta):跳过斜白条,从 STRIPE_W 起
        from PySide6.QtGui import QFont
        f = QFont()
        f.setFamilies(["JetBrains Mono", "SFMono-Regular", "Menlo",
                       "Consolas", "Courier New", "monospace"])
        f.setPixelSize(11)
        f.setBold(True)
        f.setLetterSpacing(QFont.PercentageSpacing, 110)
        p.setFont(f)
        p.setPen(QColor(SLATE_BAR_INK))
        p.drawText(QRect(self.STRIPE_W + 12, 0, w - self.STRIPE_W - 130, h),
                   Qt.AlignVCenter | Qt.AlignLeft, self._left_meta)
        # 4. 右侧 scene meta(灰白),与状态点
        f2 = QFont(f)
        f2.setBold(False)
        f2.setPixelSize(10)
        f2.setLetterSpacing(QFont.PercentageSpacing, 80)
        p.setFont(f2)
        p.setPen(QColor(SLATE_BAR_DIM))
        p.drawText(QRect(0, 0, w - 14, h),
                   Qt.AlignVCenter | Qt.AlignRight, self._right_meta)
        # 5. 状态小圆点(右侧贴 6px,直径 8px)
        color = {"completed": SLATE_ST_DONE, "active": SLATE_ST_PROG,
                 "failed": SLATE_ST_FAIL}.get(self._status, SLATE_BAR_DIM)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        r = 4
        p.drawEllipse(QPoint(w - 14 - r - 4 - p.fontMetrics().horizontalAdvance(
            self._right_meta) if self._right_meta else w - 18, h // 2), r, r)


class ProjectCard(QFrame):
    open_requested = Signal(int)
    delete_requested = Signal(int, str)
    status_changed = Signal(int, str)

    # 视觉骨架:4px 圆角卡片,顶 30px 拍板条,封面 2:1,底约 142px 三段
    # 早期版 410 太长,封面下到状态行之间 80~100px 净空白 → 缩到 348
    CARD_W = 280
    CARD_H = 348
    STRIP_H = 30
    COVER_H = 148  # 280×148 ≈ 16:8.5,接近 2:1 电影画幅

    def __init__(self, drama: dict):
        super().__init__()
        self.setObjectName("slateCard")
        self.drama_id = drama["id"]
        self._title = drama["title"]
        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("click_open_project"))

        # 临时尝试把 QSS 局部应用,失败也无所谓 —— paintEvent 才是关键
        try:
            self.setStyleSheet(SLATE_CARD_QSS)
        except Exception:  # noqa: BLE001
            pass

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ─── 拍板顶条 ───
        # 取 ID/episode 数/拍摄进度(视作"take")。每张卡的拍板码都是这一张独立的——
        # 启动台化身"今日拍摄计划"的可视化,而非通用项目网格。
        ne = db.q1("SELECT COUNT(*) c FROM episodes WHERE drama_id=?", (drama["id"],))["c"]
        # 完成度当作"take":打板数 / 计划数(全部任务中已完成比例)
        try:
            tot = db.q1(
                "SELECT (SELECT COUNT(*) FROM storyboards sb "
                "JOIN episodes e ON sb.episode_id=e.id WHERE e.drama_id=?) AS shots",
                (drama["id"],))["shots"] or 0
            done = db.q1(
                "SELECT COUNT(*) c FROM storyboards sb "
                "JOIN episodes e ON sb.episode_id=e.id "
                "WHERE e.drama_id=? AND sb.video_url IS NOT NULL",
                (drama["id"],))["c"]
            take_done = int(done)
            take_total = int(tot)
        except Exception:  # noqa: BLE001
            take_done, take_total = 0, 0
        status = (drama.get("status") or "pending").lower()
        self._status = status
        self._take_done = take_done
        self._take_total = take_total
        self._ep_count = ne
        # PROJECT N° 是创建时分配的整数 ID,4 位宽跟场记板真实 pad 一致
        project_no = f"PROJECT N°{int(drama['id']):04d}"
        ep_label = f"EP{ne:02d}" if ne else "EP --"
        take_label = f"TAKE {take_done:02d}/{take_total:02d}" if take_total else "TAKE --/--"
        self.strip = SlateStrip(project_no, ep_label, take_label,
                                status=status, scene_meta=_fmt_ago(drama["updated_at"]))
        root.addWidget(self.strip)

        # ─── 封面 ───
        cover = QFrame()
        cover.setObjectName("slateCover")
        cover.setFixedHeight(self.COVER_H)
        # 此前是 KeepAspectRatioByExpanding:竖屏原图(9:16)横铺到 280×148 时只露顶 28%,
        # 用户看不到完整人物/场景。改 KeepAspectRatio 整图缩进 + 米白底 letterbox,
        # 视觉上像「片场取景框」看完整构图,而不是「海报裁切」。
        cover.setStyleSheet(
            "QFrame#slateCover{background:" + SLATE_BG + ";border:none;"
            "border-bottom:1px solid " + SLATE_HAIR + ";}")
        cl = QVBoxLayout(cover)
        cl.setContentsMargins(8, 8, 8, 8)
        self._thumb = drama.get("thumbnail") or ""
        if self._thumb:
            img = _CoverLabel()
            img.setAlignment(Qt.AlignCenter)
            # KeepAspectRatio:整图可见,缩到 (CARD_W-16, COVER_H-16) 合约束之内。
            # 竖屏图会在左右留出米白 letterbox,横屏图在上下留;背景被 #slateCover 的
            # 米色盖住,整体视觉一致。
            img.setStyleSheet("background:transparent; border:none;")
            img.setPixmap(W.pixmap_from_media(self._thumb, self.CARD_W - 16, self.COVER_H - 16))
            img.setCursor(Qt.PointingHandCursor)
            img.clicked.connect(self._preview_cover)
            cl.addWidget(img)
        else:
            # 无封面时仍走米白底 + 拍板黑大字首字母
            init = QLabel((drama["title"] or "?")[:1].upper())
            init.setAlignment(Qt.AlignCenter)
            init.setStyleSheet(
                f"color:{SLATE_BAR}; font-family:'Inter','Helvetica Neue',sans-serif;"
                f"font-size:54px; font-weight:800; border:none; background:transparent;")
            cl.addWidget(init)
        # 比例 mono 标签(右上角,不抢戏)
        if drama.get("aspect_ratio") and drama["aspect_ratio"] != "adaptive":
            row = QHBoxLayout()
            row.addStretch(1)
            rc = QLabel(drama["aspect_ratio"])
            rc.setObjectName("slateChip")
            row.addWidget(rc)
            cl.addLayout(row)
        cover.mousePressEvent = lambda _e: self._preview_cover()
        root.addWidget(cover)

        # ─── 主体 ───
        body = QWidget()
        body.setStyleSheet("background:transparent; border:none;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(14, 9, 14, 10)
        bl.setSpacing(4)
        # 标题(标题行也用 Inter,故意不用 mono——保持层级)
        title = QLabel(drama["title"])
        title.setObjectName("slateTitle")
        title.setWordWrap(True)
        title.setToolTip(drama["title"])
        title.setMaximumHeight(38)
        bl.addWidget(title)
        # chip 行:type (mono) + 可选 imitated + 可选 风格名
        chips = QHBoxLayout()
        chips.setSpacing(5)
        chips.setContentsMargins(0, 0, 0, 0)
        c1 = QLabel(wt_label(drama["work_type"]).upper())
        c1.setObjectName("slateChip")
        chips.addWidget(c1)
        nm = db.jload(drama["novel_meta"], {}) or {}
        if (nm.get("imitated_from") or {}).get("drama_id"):
            c2 = QLabel(tr("imitated").upper())
            c2.setObjectName("slateChip")
            c2.setToolTip(tr("imitated_tip"))
            chips.addWidget(c2)
        style = db.q1("SELECT name FROM style_presets WHERE value=?", (drama["style"],))
        if style and drama["work_type"] != "novel":
            c3 = QLabel(tr(style["name"]).upper())
            c3.setObjectName("slateChip")
            chips.addWidget(c3)
        chips.addStretch(1)
        bl.addLayout(chips)
        # meta 行(纯 mono)
        nc = db.q1("SELECT COUNT(*) c FROM characters WHERE drama_id=?",
                   (drama["id"],))["c"]
        ns = db.q1("SELECT COUNT(*) c FROM scenes WHERE drama_id=?",
                   (drama["id"],))["c"]
        meta = QLabel(f"{int(nc):02d} CHARACTERS  ·  {int(ns):02d} SCENES  ·  {int(ne):02d} EPS")
        meta.setObjectName("slateMeta")
        bl.addWidget(meta)
        # 进度条:status-state 属性切换颜色
        track = QFrame()
        track.setObjectName("slateTrack")
        track.setFixedHeight(4)
        tlay = QHBoxLayout(track)
        tlay.setContentsMargins(0, 0, 0, 0)
        tlay.setSpacing(0)
        self._progress = QFrame()
        self._progress.setObjectName("slateFill")
        if take_total:
            pct = min(100, int(round(100 * take_done / take_total)))
        else:
            pct = 0 if status != "completed" else 100
        self._progress.setMinimumWidth(int(pct))
        self._apply_progress_state(status, pct)
        tlay.addWidget(self._progress)
        tlay.addStretch(1)
        bl.addWidget(track)
        # ★ 关键:此前的 bl.addStretch(1) 把 footer 顶到卡片底部,中间留 80+px 净空白。
        # 删掉后 body 自然贴合,卡片整体缩到 348 也还能放得下。
        # 底部一行:左状态时间 mono,右 2 个 mini icon(用 SlateIconBtn)
        foot = QHBoxLayout()
        foot.setSpacing(6)
        foot.setContentsMargins(0, 2, 0, 0)
        self.status_btn = QPushButton(f"●  {status_label(status)}")
        self.status_btn.setObjectName("slateIconBtn")
        self.status_btn.setCursor(Qt.PointingHandCursor)
        self._apply_status_style(status)
        self.status_btn.clicked.connect(self._status_menu)
        foot.addWidget(self.status_btn)
        foot.addStretch(1)
        more = QPushButton("⋯")
        more.setObjectName("slateIconBtn")
        more.setCursor(Qt.PointingHandCursor)
        more.clicked.connect(self._menu)
        foot.addWidget(more)
        bl.addLayout(foot)
        root.addWidget(body, 1)

    def _apply_progress_state(self, status: str, pct: int):
        """进度条颜色按状态语义染;百分比仅负责宽度。"""
        # 三档语义:done/prog/fail.pend 不上色
        if status == "completed":
            self._progress.setProperty("done", "1")
        elif status == "active":
            self._progress.setProperty("prog", "1")
        elif status == "failed":
            self._progress.setProperty("fail", "1")
        # 默认黑(不写 done/prog/fail 即可)
        self._progress.style().unpolish(self._progress)
        self._progress.style().polish(self._progress)

    def _preview_cover(self):
        """点击封面:弹出大图预览(完整比例,不随卡片裁切)。"""
        d = QDialog(self)
        d.setWindowTitle(self._title)
        d.resize(480, 720)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(16, 16, 16, 16)
        img = QLabel()
        img.setAlignment(Qt.AlignCenter)
        img.setPixmap(W.pixmap_from_media(self._thumb, 448, 688))
        lay.addWidget(img)
        d.exec()

    def _apply_status_style(self, status: str):
        """mini 状态钮文本已经在构造时塞了字,这里只补颜色(走 objectName + property 切换)"""
        prop = {"pending": "pend", "active": "prog", "completed": "done"}.get(status)
        for k in ("done", "prog", "fail", "pend"):
            self.status_btn.setProperty(k, None)
        if prop:
            self.status_btn.setProperty(prop, "1")
        self.status_btn.style().unpolish(self.status_btn)
        self.status_btn.style().polish(self.status_btn)

    def _status_menu(self):
        m = QMenu(self)
        for key in STATUS_META:
            act = m.addAction(f"●  {status_label(key)}")
            act.setIcon(_dot_icon(STATUS_META[key]))
            act.triggered.connect(lambda _=False, k=key: self.status_changed.emit(self.drama_id, k))
        m.exec(QCursor.pos())

    def _menu(self):
        m = QMenu(self)
        a1 = m.addAction(tr("open_project"))
        a2 = m.addAction(tr("delete_project"))
        act = m.exec(QCursor.pos())
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
        # 局部挂 SLATE_CARD_QSS —— search/filter/sort/new 都只在本页生效,不影响其它面板
        try:
            existing = self.styleSheet()
            self.setStyleSheet((existing + "\n" + SLATE_CARD_QSS) if existing else SLATE_CARD_QSS)
        except Exception:  # noqa: BLE001
            pass
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 24)
        root.setSpacing(14)

        # ── 头部:大写 tracking 标题(mono)+ 副标 + mono inline 统计 + 拍板黑 NEW ──
        head = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(4)
        title = QLabel(tr("launcher_title").upper())
        title.setObjectName("slatePageTitle")
        left.addWidget(title)
        sub = QLabel(tr("launcher_sub"))
        sub.setObjectName("slatePageSub")
        left.addWidget(sub)
        head.addLayout(left, 1)
        # inline 统计(mono,齐腰一行)
        self.stats = QHBoxLayout()
        self.stats.setSpacing(0)
        self._stat_projects = QLabel("")
        self._stat_projects.setObjectName("slateStatBig")
        self._stat_running = QLabel("")
        self._stat_running.setObjectName("slateStatBig")
        self._stat_styles = QLabel("")
        self._stat_styles.setObjectName("slateStatBig")
        self.stats.addWidget(self._stat_projects)
        self.stats.addSpacing(20)
        self.stats.addWidget(self._stat_running)
        self.stats.addSpacing(20)
        self.stats.addWidget(self._stat_styles)
        head.addLayout(self.stats)
        new_btn = QPushButton("＋  " + tr("new_project").upper())
        new_btn.setObjectName("slateNew")
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self._new_project)
        head.addWidget(new_btn)
        root.addLayout(head)

        # ── 工具条:搜索 + filterChip(slate 方形)+ 排序(slate 方形) ──
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("search"))
        self.search.setClearButtonEnabled(True)
        self.search.setObjectName("slateSearch")
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search)
        self._filter_btns: dict[str, QPushButton] = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        # 给每个 filter 加个两位数字前缀(00/01/02/03)呼应场记板
        for i, key in enumerate(FILTER_KEYS):
            b = QPushButton(f"{i:02d}  {filter_label(key).upper()}")
            b.setObjectName("slateFilter")
            b.setCheckable(True)
            b.setChecked(key == "all")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            group.addButton(b)
            self._filter_btns[key] = b
            bar.addWidget(b)
        self._filter = "all"
        # ↓ 下载项目全部提示词:把所有剧集的分镜提示词打成一个大 TXT(每集一节)。
        # 用户场景:复制整套提示词到 Notion / 喂给其它 AI / 项目归档备份。
        self._download_all_btn = QPushButton(tr("download_project_prompts"))
        self._download_all_btn.setObjectName("slateSort")
        self._download_all_btn.setToolTip(tr("download_project_prompts_tip"))
        self._download_all_btn.setCursor(Qt.PointingHandCursor)
        self._download_all_btn.clicked.connect(self._download_all_prompts_txt)
        bar.addWidget(self._download_all_btn)
        bar.addStretch(1)
        from PySide6.QtWidgets import QComboBox
        self.sort = QComboBox()
        self.sort.setObjectName("slateSort")
        self.sort.setFixedWidth(150)
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
        # slate mono inline 统计:b 是大数字(粗)+ 后面是单位描述,中间留一个 nbsp
        styles_n = len(db.q("SELECT id FROM style_presets WHERE is_active=1"))
        self._stat_projects.setText(
            f"<b>{int(len(rows)):02d}</b>&nbsp; {tr('n_projects', len(rows))}")
        self._stat_running.setText(
            f"<b>{int(running):02d}</b>&nbsp; {tr('n_running', running)}")
        self._stat_styles.setText(
            f"<b>{int(styles_n):02d}</b>&nbsp; {tr('n_styles', styles_n)}")

    def _empty_state(self, has_rows: bool) -> QWidget:
        box = QFrame()
        box.setObjectName("slateCard")
        box.setMinimumHeight(240)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 24, 16, 24)
        lay.setSpacing(10)
        icon = QLabel("▢" if not has_rows else "○")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"font-size:30px; color:{SLATE_BAR}; font-weight:300;")
        lay.addWidget(icon)
        title = QLabel(tr("empty_first_project") if not has_rows else tr("empty_no_match"))
        title.setAlignment(Qt.AlignCenter)
        title.setObjectName("slateTitle")
        title.setStyleSheet(f"color:{SLATE_META}; font-weight:600; font-size:14px;")
        lay.addWidget(title)
        desc = QLabel(tr("empty_first_desc") if not has_rows else tr("empty_no_match_desc"))
        desc.setAlignment(Qt.AlignCenter)
        desc.setObjectName("slatePageSub")
        lay.addWidget(desc)
        if not has_rows:
            btn = QPushButton("＋  " + tr("new_project").upper())
            btn.setObjectName("slateNew")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self._new_project)
            lay.addWidget(btn, 0, Qt.AlignCenter)
        return box

    def _set_status(self, drama_id: int, status: str):
        db.ex("UPDATE dramas SET status=?, updated_at=? WHERE id=?", (status, db.now(), drama_id))
        ok(f"{tr('status_marked')}: {status_label(status)}")
        self.reload()

    def _download_all_prompts_txt(self):
        """项目级批量导出:把当前筛选下的所有剧集的分镜提示词打成一个大 TXT。

        每集一节(EP01 / EP02...),集内每个镜头一子节,字段统一:
        分镜描述 / 视频提示词 / 氛围 / 旁白。
        """
        from PySide6.QtWidgets import QFileDialog
        from pathlib import Path
        # 取当前筛选下的项目(尊重搜索/筛选/排序)
        kw = self.search.text().strip()
        want = FILTER_DB.get(self._filter)
        rows = [dict(r) for r in db.q("SELECT * FROM dramas")]
        shown = [d for d in rows
                 if (not kw or kw in d["title"])
                 and (want is None or (d.get("status") or "pending") == want)]
        if not shown:
            err("当前筛选下没有项目")
            return
        # 默认文件名
        default_name = f"项目提示词合集_{db.now()[:10]}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("download_project_prompts"), default_name,
            "Text files (*.txt);;All files (*)")
        if not path:
            return
        out = []
        out.append(f"【项目提示词合集 · {len(shown)} 个项目】")
        out.append(f"导出时间:{db.now()}")
        out.append("")
        grand_eps = grand_sbs = 0
        line = "═" * 60
        sep = "─" * 60
        for d in shown:
            eps = db.q("SELECT id, episode_number, title FROM episodes "
                       "WHERE drama_id=? ORDER BY episode_number", (d["id"],))
            if not eps:
                continue
            out.append(line)
            out.append(f"项目:{d['title']}  (drama_id={d['id']})")
            out.append(line)
            for ep in eps:
                ep_no = ep["episode_number"]
                ep_title = ep["title"] or f"EP{ep_no:02d}"
                out.append("")
                out.append(f"EP{ep_no:02d} · {ep_title}")
                out.append(sep)
                sbs = db.q("SELECT * FROM storyboards WHERE episode_id=? "
                           "AND deleted_at IS NULL ORDER BY storyboard_number",
                           (ep["id"],))
                grand_eps += 1
                grand_sbs += len(sbs)
                if not sbs:
                    out.append("  (无分镜)")
                    continue
                for r in sbs:
                    n = r["storyboard_number"]
                    out.append(f"  · 镜头 #{n:02d}")
                    out.append(f"    分镜描述:{_one_line(r['description'] or r['content'])}")
                    out.append(f"    视频提示词:{_one_line(r['video_prompt'])}")
                    out.append(f"    氛围:{_one_line(r['atmosphere'])}")
                    out.append(f"    旁白:{_one_line(r['narration'])}")
                out.append(sep)
            out.append("")
        out.append(line)
        out.append(f"EOF · 共 {grand_eps} 集 / {grand_sbs} 个分镜")
        out.append(line)
        try:
            Path(path).write_text("\n".join(out), encoding="utf-8")
            ok(f"已导出 {grand_eps} 集 / {grand_sbs} 个分镜到:\n{path}")
        except Exception as e:                              # noqa: BLE001
            err(f"写入失败:{e}")

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