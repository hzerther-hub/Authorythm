# -*- coding: utf-8 -*-
"""主窗口:顶栏(Logo/导航/主题/语言)+ QStackedWidget(启动台/项目页/工作台/复刻页/合并工具)。"""
from __future__ import annotations

import json

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame,QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from ..core import config, db
from ..core.i18n import LANGS, on_change, set_language, tr
from .toast import err, ok
from ..core.taskmgr import TASKMGR
from ..core.theme import apply_theme
from .episode_page import EpisodePage
from .new_project_dialog import NewProjectDialog
from .project_page import ProjectPage
from .projects_page import ProjectsPage
from .settings_dialog import SettingsDialog
from .dashboard_widget import DashboardWidget
from . import widgets as W


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("app_title"))
        self.resize(1360, 860)
        # 锁定最小窗口大小 —— 否则打开抽屉时 splitter 会按子控件 minimumSizeHint
        # 把整个窗口撑大(实测 1360 → 1685),用户拖尺寸反而奇怪。
        self.setMinimumSize(1100, 720)
        from PySide6.QtGui import QIcon
        _logo = config.ROOT_DIR / "app" / "assets" / "logo.png"
        if _logo.exists():
            self.setWindowIcon(QIcon(str(_logo)))
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶栏
        top = QWidget()
        top.setObjectName("headerBar")          # 跟随主题,不再写死深色
        tlay = QHBoxLayout(top)
        tlay.setContentsMargins(20, 10, 20, 10)
        tlay.setSpacing(6)
        # 品牌块:圆角渐变方块 + 「易」,对齐原版 .brand-mark
        logo_lab = QLabel("易")
        logo_lab.setFixedSize(32, 32)
        logo_lab.setAlignment(Qt.AlignCenter)
        logo_lab.setObjectName("brandMark")
        tlay.addWidget(logo_lab)
        word = QWidget()
        wl = QVBoxLayout(word)
        wl.setContentsMargins(4, 0, 0, 0)
        wl.setSpacing(0)
        logo = QLabel(tr("易好网文短剧"))
        logo.setObjectName("brandName")
        wl.addWidget(logo)
        sub = QLabel("Yihao Shorts")
        sub.setObjectName("brandSub")
        wl.addWidget(sub)
        tlay.addWidget(word)
        tlay.addSpacing(10)
        tlay.addStretch(1)
        # 分段胶囊导航(对齐原版 layouts/default.vue 的 nav-segmented)
        # 与主题/设置/语言同组放右侧,统一 32px 高 —— 不再孤立在左侧
        nav_wrap = QFrame()
        nav_wrap.setObjectName("navSegWrap")
        nav_lay = QHBoxLayout(nav_wrap)
        nav_lay.setContentsMargins(3, 3, 3, 3)
        nav_lay.setSpacing(2)
        self.nav_btns: dict[str, QPushButton] = {}
        # 换脸/合并不再放顶部导航:换脸收进角色资产卡(图片处),合并收进制作台导出面板
        # 「图片处理」页已下线(commit 「图片处理功能全移到聊天改图」):它的批量能力
        # —— 多图/目录/URL 来源、指令批处理、本地超分与多规格导出、结果对照 ——
        # 整块搬进「聊天改图」页的批量折叠区(image_batch_panel.BatchImagePanel)。
        # 两边都是「对一张图下指令改它」,拆两页只会让用户在 A 页选图再点 💬 送到 B 页。
        self._nav_defs = [("dashboard", "◉", "nav_dashboard"),
                          ("projects", "▦", "nav_projects"),
                          ("chatedit", "💬", "chat_edit_nav")]
        # Director's Slate:Dashboard 用硬编码"仪表盘",不依赖 i18n key;
        # 其他 3 个有 key。后续如要本地化,在 app/core/i18n.py + ui_strings.py
        # 15 语言表里加 nav_dashboard 条目,这里再切回 tr(label_key)。
        LABEL_OVERRIDE = {"dashboard": "仪表盘"}
        for key, icon, label_key in self._nav_defs:
            label_text = LABEL_OVERRIDE.get(key) or tr(label_key)
            b = QPushButton(f"{icon}  {label_text}")
            b.setObjectName("navSeg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(32)
            b.clicked.connect(lambda _=False, k=key: self._goto(k))
            self.nav_btns[key] = b
            nav_lay.addWidget(b)
        # 主题/设置/语言与导航同装一个胶囊:等高 32、同字体同字号,风格一体
        icon_font = "font-family:'Segoe UI Symbol','Microsoft YaHei UI'; font-size:15px; padding:0;"
        theme_btn = QPushButton("◐")
        theme_btn.setObjectName("headerIconBtn")
        theme_btn.setFixedSize(32, 32)
        theme_btn.setStyleSheet(icon_font)
        theme_btn.setToolTip(tr("theme"))
        theme_btn.clicked.connect(self._toggle_theme)
        settings_btn = W.svg_icon_btn("settings", "", size=30)
        settings_btn.setObjectName("headerIconBtn")
        settings_btn.setFixedSize(32, 32)
        settings_btn.setStyleSheet(icon_font)
        settings_btn.setToolTip(tr("nav_settings"))
        settings_btn.clicked.connect(self._open_settings)
        # 地球图标:各语言用户都认识
        lang_btn = W.svg_icon_btn("globe", "", size=30)
        lang_btn.setObjectName("headerIconBtn")
        lang_btn.setFixedSize(32, 32)
        lang_btn.setStyleSheet(icon_font)
        lang_btn.setToolTip(tr("lang_short"))
        lang_btn.clicked.connect(self._switch_language)
        # 「?」服务依赖说明 —— 列出未就绪的核心服务(文本/图片/视频/配音/换脸/JEV/PhotoCraft)
        # 点开一个 dialog,每行可点跳到设置页;统一 i18n key,所有语言都对得上
        help_btn = QPushButton("?")
        help_btn.setObjectName("headerIconBtn")
        help_btn.setFixedSize(32, 32)
        help_btn.setStyleSheet("font-family:'Segoe UI Symbol','Microsoft YaHei UI';"
                                "font-size:18px; font-weight:700; padding:0;")
        help_btn.setToolTip(tr("install_help"))
        help_btn.setCursor(Qt.PointingHandCursor)
        help_btn.clicked.connect(self._show_install_help)
        for b in (theme_btn, settings_btn, lang_btn, help_btn):
            nav_lay.addWidget(b)
        tlay.addWidget(nav_wrap)
        from .braille import BrailleSpinner, BrailleBar
        self.busy_spin = BrailleSpinner(color="#8b909a", size=16)
        tlay.addWidget(self.busy_spin)
        self.busy_bar = BrailleBar(cells=14, parent=top)
        tlay.addWidget(self.busy_bar)
        tlay.addWidget(theme_btn)
        tlay.addWidget(settings_btn)
        tlay.addWidget(lang_btn)
        tlay.addWidget(help_btn)
        root.addWidget(top)

        # AI 服务未就绪横幅(缺 text/image/video 任一即显示,点此去设置)
        self.banner = QLabel()
        self.banner.setContentsMargins(20, 8, 20, 8)
        self.banner.setStyleSheet(
            "background:#fff7e6;color:#ad6800;border-bottom:1px solid #ffd591;"
            "font-weight:600;padding:6px 12px;")
        self.banner.setCursor(Qt.PointingHandCursor)
        self.banner.mousePressEvent = lambda _e: self._open_settings()
        self.banner.setVisible(False)
        root.addWidget(self.banner)
        self._refresh_ai_banner()

        # 页面栈(各页独立 tab,不再共用 splitter)
        self.stack = QStackedWidget()
        # Director's Slate:dashboard 作为 nav index 0 —— app 进首页不再直跳
        # 到启动台,而是看一屏总览(最近项目 / 任务池 / 服务 / 本周统计)
        self.dashboard = DashboardWidget()
        self.projects_page = ProjectsPage()
        self.project_page = ProjectPage()
        self.episode_page = EpisodePage()
        self.clone_page = ClonePage()
        from .face_swap_page import FaceSwapPage
        from .merger_tool_page import MergerToolPage
        self.face_swap_page = FaceSwapPage()
        self.merger_page = MergerToolPage()
        from .chat_edit_drawer import ChatEditDrawer
        # 独立 tab。原来的 ImageProcessPage(图片处理)已下线,批量改图现在是
        # 这个抽屉里的折叠区,见 chat_edit_drawer.ChatEditPanel.batch_panel。
        self.chat_edit_page = ChatEditDrawer(self)
        for p in (self.dashboard, self.projects_page, self.project_page, self.episode_page, self.clone_page,
                  self.face_swap_page, self.merger_page,
                  self.chat_edit_page):
            self.stack.addWidget(p)

        root.addWidget(self.stack, 1)         # 页面栈占中央,stretch=1 撑满

        # 状态栏
        self.status = self.statusBar()

        # 全局 toast(D 类)
        from .toast import ToastManager
        ToastManager.attach(central)
        # 登记为全局等待态宿主(任务开始/结束时自动切换盲文指示)
        from ..core.taskmgr import TASKMGR
        TASKMGR.attach_host(self)

        # 信号 —— 页面实例在语言切换时会被重建(_make_page),所以接线统一走
        # _wire_* 帮手,__init__ 与 _make_page 共用同一份,避免改一处漏一处
        # (settings_drama 就这么漏过:重建后的项目卡「⋯ → 项目设置」点了没反应)。
        self._wire_projects_page(self.projects_page)
        self.project_page.set_callbacks(self._back_to_projects, self._enter_episode, self._promo_dialog)
        self.episode_page.back_requested.connect(self._back_to_project)
        self._wire_clone_page(self.clone_page)
        # 聊天抽屉保存成品 → 落到同页批量区的结果行(原「图片处理」页没了)
        self._wire_chat_page(self.chat_edit_page)
        TASKMGR.updated.connect(lambda: self.status.showMessage(
            f"{tr('tasks')}: {TASKMGR.active_count()} {tr('in_progress')}"))
        # 任务抽屉是浮在 central 上的,切页时必须收掉,否则会跟着飘到别的页面
        self.stack.currentChanged.connect(self._on_page_changed)
        # 语言切换即时重建界面(机制同 comPySide),不再要求重启
        self._stale_pages: set[str] = set()
        on_change(self._on_lang_changed)

    def sync_task_drawer_geometry(self):
        """把任务抽屉铺满页面区(它是浮层,不是页面栈里的一页)。

        抽屉挂在 central 上按绝对坐标定位,窗口缩放后必须重新对齐,
        否则会漂移或遮住状态栏。
        """
        d = getattr(self, "_task_drawer", None)
        if d is None:
            return
        d.setGeometry(self.stack.geometry())

    def _on_page_changed(self, _idx: int):
        """切页即收起任务抽屉(抽屉只属于剧集页的当前界面)。"""
        d = getattr(self, "_task_drawer", None)
        if d is not None:
            d.closed.emit(d)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.sync_task_drawer_geometry()

    def set_busy(self, on: bool, message: str = ""):
        """全局盲文等待态(D 类):任何 AI 任务在跑时顶栏显示点字变化,避免"点了没反应"。"""
        from .braille import BrailleSpinner
        if on:
            self.busy_spin.start(message or tr("处理中…"))
            self.busy_bar.start()
            self.status.showMessage(f"⠿ {message or tr('处理中…')}")
        else:
            self.busy_spin.stop()
            self.busy_bar.stop()
            self.status.showMessage("")

    def _on_lang_changed(self, _code: str):
        """语言切换回调。

        必须延到下一个事件循环再重建:若在按钮 clicked 里同步重建,会把正在派发信号的
        那个按钮一起销毁,Qt 会卡在派发里出不来(comPySide 踩过这个坑)。
        """
        QTimer.singleShot(0, self._rebuild_ui)

    # 下标与 self.stack 的 addWidget 顺序严格一一对应 —— _rebuild_ui 靠它把
    # 「当前页」翻译回页面种类。「imageproc」下线后已从本表移除。
    # dashboard 必须在首位:它是栈里的第 0 页,漏了会让全表右移一位,
    # 切语言时把首页当成 projects 重建,直接把用户从 dashboard 弹到项目页。
    # _make_page("dashboard") 返回 None,_rebuild_ui 走「原地刷顶栏」分支,符合预期。
    _PAGE_KINDS = ["dashboard", "projects", "project", "episode", "clone",
                   "face_swap", "merger", "chatedit"]

    def _make_page(self, kind: str):
        """按页面种类新建一个页面实例(文案都是构造时 tr() 求值的)。

        **每一种页面都必须有分支** —— 语言切换的重建机制靠它,漏了哪种,
        哪种语言切换后就永远停在旧语言(而且不报错)。_PAGE_KINDS 里的每个键
        都要能在这里造出来,tests/test_lang_switch.py 守着这条。
        """
        from .project_page import ProjectPage
        from .projects_page import ProjectsPage
        from .episode_page import EpisodePage
        drama_id = getattr(self, "_cur_drama_id", 0)
        episode_id = getattr(self, "_cur_episode_id", 0)
        if kind == "dashboard":
            return DashboardWidget()
        if kind == "projects":
            p = ProjectsPage()
            self._wire_projects_page(p)
            return p
        if kind == "project" and drama_id:
            p = ProjectPage()
            p.enter_episode.connect(self._enter_episode)
            p.set_callbacks(self._back_to_projects, self._enter_episode, self._promo_dialog)
            p.load(drama_id)
            return p
        if kind == "episode" and drama_id:
            p = EpisodePage()
            p.back_requested.connect(self._back_to_project)
            p.load(drama_id, episode_id)
            return p
        if kind == "clone":
            p = ClonePage()
            self._wire_clone_page(p)
            # 复刻页是「按项目打开」的:当前项目是复刻类型就把上下文带回去,
            # 否则语言一切换用户就丢了正在看的复刻项目
            if drama_id:
                d = db.q1("SELECT work_type FROM dramas WHERE id=?", (drama_id,))
                if d and d["work_type"] == "video_clone":
                    p.load(drama_id)
            return p
        if kind == "face_swap":
            from .face_swap_page import FaceSwapPage
            return FaceSwapPage()
        if kind == "merger":
            from .merger_tool_page import MergerToolPage
            return MergerToolPage()
        if kind == "chatedit":
            from .chat_edit_drawer import ChatEditDrawer
            p = ChatEditDrawer(self)
            self._wire_chat_page(p)
            # 保留当前会话:语言切换不该把用户正进行中的对话视图清掉
            # (会话本体在 SQLite,load_session 恢复消息流与当前图)
            old = getattr(self, "chat_edit_page", None)
            sid = getattr(getattr(old, "panel", None), "_session_id", None)
            if sid:
                try:
                    p.panel.load_session(sid)
                except Exception:  # noqa: BLE001 —— 恢复失败就从头开始,不炸重建
                    pass
            return p
        return None

    def _wire_projects_page(self, p):
        p.open_drama.connect(self._open_drama)
        p.settings_drama.connect(self._open_project_settings)
        p.set_new_callback(self._new_project)

    def _wire_clone_page(self, p):
        p.back_requested.connect(self._back_to_projects)
        p.open_workbench_requested.connect(self._enter_episode)

    def _wire_chat_page(self, p):
        p.imageSaved.connect(self._on_chat_image_saved)
        p.needSettings.connect(self._open_settings)
        p.openDesktopApp.connect(self._open_photocraft_desktop)

    _PAGE_ATTR = {
        "dashboard": "dashboard",
        "projects": "projects_page", "project": "project_page", "episode": "episode_page",
        "clone": "clone_page",
        "face_swap": "face_swap_page", "merger": "merger_page",
        "chatedit": "chat_edit_page",
    }

    def _swap_page(self, kind: str, new) -> None:
        """把栈内某一页换成 new。

        旧页必须先 setParent(None) 再 deleteLater():deleteLater 是延迟删除,而 removeWidget
        只把它从栈的布局里摘下来、父子关系还在,删除事件被处理前它仍然按栈的几何参与绘制,
        结果新旧两页叠在一起,整个界面看起来是塌的(ep_grid 那次踩的是同一个坑)。
        """
        old = getattr(self, self._PAGE_ATTR[kind])
        idx = self.stack.indexOf(old)
        if idx < 0:
            idx = self.stack.currentIndex()
        self.stack.removeWidget(old)
        old.setParent(None)
        old.deleteLater()
        self.stack.insertWidget(idx, new)
        setattr(self, self._PAGE_ATTR[kind], new)
        self.stack.setCurrentIndex(idx)

    def _restore_geo(self, geo):
        """语言切换重建后恢复窗口原尺寸。

        新页面的最小尺寸提示可能比旧页大,布局会把窗口撑大且没人缩回去
        (实测切语言后窗口溢出屏幕、右侧按钮看不见)。延迟一拍等布局消化完再恢复。
        """
        if self.isMaximized() or geo is None:
            return
        from PySide6.QtWidgets import QApplication
        scr = QApplication.primaryScreen().availableGeometry()
        self.resize(min(geo.width(), int(scr.width() * 0.96)),
                    min(geo.height(), int(scr.height() * 0.96)))

    def _rebuild_ui(self):
        """按当前语言重建当前页面,并把其余数据页标记为待重建(下次进入时重建)。"""
        geo = self.geometry()          # 重建可能把窗口撑大,事后恢复
        idx = self.stack.currentIndex()
        kind = self._PAGE_KINDS[idx] if 0 <= idx < len(self._PAGE_KINDS) else "projects"
        try:
            new = self._make_page(kind)
        except Exception as exc:  # noqa: BLE001 —— 重建失败保留旧页,不把窗口搞没
            import traceback
            traceback.print_exc()
            err(tr('界面重建失败:{}').format(str(exc)[:120]))
            return
        # 全部页面种类都标记待重建(当前页马上重建,其余进入时重建)。
        # 之前只标 projects/project/episode —— dashboard / 聊天改图 / 复刻 /
        # 换脸 / 合并永远停在旧语言,「切语言大部分无效」的主因就是这个。
        self._stale_pages = {k for k in self._PAGE_KINDS if k != kind}
        if new is None:                     # 工具页/未加载的数据页,原地刷顶栏即可
            self.retranslate()
            return
        self._swap_page(kind, new)
        self.retranslate()
        QTimer.singleShot(0, lambda: self._restore_geo(geo))
        self.status.showMessage(tr("language_switched"))

    def _ensure_fresh(self, kind: str) -> None:
        """进入某页前:若它上次重建后语言又变过,先按当前语言重建。"""
        if kind not in self._PAGE_ATTR or kind not in getattr(self, "_stale_pages", ()):
            return
        geo = self.geometry()
        try:
            new = self._make_page(kind)
        except Exception:  # noqa: BLE001
            self._stale_pages.discard(kind)
            return
        if new is None:
            self._stale_pages.discard(kind)
            return
        self._swap_page(kind, new)
        self._stale_pages.discard(kind)
        self.retranslate()
        QTimer.singleShot(0, lambda: self._restore_geo(geo))

    def retranslate(self):
        """语言切换后即时刷新顶栏与标题(页面内容重启后完全生效)。"""
        self.setWindowTitle(tr("app_title"))
        for key, icon, label_key in self._nav_defs:
            self.nav_btns[key].setText(f"{icon}  {tr(label_key)}")
        cur = self.stack.currentWidget()
        for k, b in self.nav_btns.items():
            page = {"dashboard": self.dashboard,
                    "projects": self.projects_page, "face_swap": getattr(self, "face_swap_page", None),
                    "merger": getattr(self, "merger_page", None),
                    "chatedit": getattr(self, "chat_edit_page", None)}.get(k)
            if page is not None:
                b.setChecked(cur is page)
        # AI 就绪横幅也是 tr() 求值的,切语言后要跟着刷
        self._refresh_ai_banner()

    def _refresh_ai_banner(self):
        """AI 服务就绪横幅:缺失时明确列出缺哪几类,点击直达设置。"""
        try:
            from ..ai import registry
            miss = registry.missing_services()
        except Exception:  # noqa: BLE001
            return
        if miss:
            names = "、".join(registry.SVC_CN_LABEL.get(m, m) for m in miss)
            self.banner.setText(tr('⚠ AI 服务未配置完整(缺:{}) — 依赖模型的操作会无法执行,点击此处去「设置 → AI 服务」补全').format(names))
            self.banner.setVisible(True)
        else:
            self.banner.setVisible(False)

    def _goto(self, key: str):
        """切换:项目列表(导航胶囊)/ 换脸·合并工具(资产卡与导出面板的入口)。

        **新加导航项必须在这张表里登记** —— 漏了 page 就是 None,下面直接 return,
        表现是「按钮能点、点了什么都不发生」,没有任何报错。dashboard 就这么漏过
        一轮(导航胶囊里有按钮,_PAGE_KINDS 里也有,但这张表里没有)。
        """
        self._ensure_fresh(key)
        page = {"dashboard": self.dashboard,
                "projects": self.projects_page,
                # 聊天改图是独立 tab,必须在这张表里登记 —— 漏了会让 _goto 拿到 None
                # 直接 return,点按钮没反应。它同时是原「图片处理」页的新归宿。
                "chatedit": getattr(self, "chat_edit_page", None),
                "face_swap": getattr(self, "face_swap_page", None),
                "merger": getattr(self, "merger_page", None)}.get(key)
        if page is None:
            return
        for k, b in self.nav_btns.items():
            b.setChecked(k == key)
        self.stack.setCurrentWidget(page)
        if hasattr(page, "reload"):
            page.reload()

    def _new_project(self):
        dlg = NewProjectDialog(self)
        if dlg.exec() != NewProjectDialog.Accepted:
            return
        data = dlg.result_data()
        ts = db.now()
        drama_id = db.ex(
            "INSERT INTO dramas(title,style,aspect_ratio,work_type,ethnicity,metadata,"
            "creative_description,status,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?, 'pending', ?, ?)",
            (data["title"], data["style"], data["aspect_ratio"], data["work_type"],
             data["ethnicity"], data["metadata"],
             data.get("creative_description") or "", ts, ts))
        ep_id = db.ex(
            "INSERT INTO episodes(drama_id,episode_number,title,status,resolution,created_at,updated_at)"
            " VALUES(?,1,?,'pending','720p',?,?)",
            (drama_id, tr("episode_n").format(1), ts, ts))
        # 同款复刻:导入参考视频与素材
        if data["work_type"] == "video_clone":
            from ..pipeline import video_clone
            meta = db.jload(data["metadata"], {})
            src = meta.get("clone", {})
            if src.get("reference_src"):
                video_clone.import_reference(drama_id, src["reference_src"])
            if src.get("product_src"):
                video_clone.upload_material(drama_id, "product", src["product_src"])
            if src.get("presenter_src"):
                video_clone.upload_material(drama_id, "presenter", src["presenter_src"])
        # 首集自动生成(对齐 auto-generate.ts):建完就后台跑一次对应 Agent,
        # 用户不用手动点每一步;失败只记任务,不阻断建项目。clone 不生成(分镜来自参考视频拆解)。
        if data["work_type"] != "video_clone":
            try:
                from ..core.preflight import ensure_ready
                from ..pipeline import auto_generate
                if ensure_ready("text", None):
                    auto_generate.auto_generate_first_episode(drama_id, ep_id)
            except Exception:  # noqa: BLE001 —— 自动生成失败不影响项目本身
                pass
        self.projects_page.reload()
        self._open_drama(drama_id)

    def _open_project_settings(self, drama_id: int):
        """项目卡「⋯ → 项目设置」:按项目类型打开对应页面。

        复刻 → ClonePage(设置行就在顶部:模型下拉 / 画面风格 / 资产重建);
        其他类型 → 走原打开流程(顶部有模型下拉与风格选择)。
        """
        d = db.q1("SELECT work_type FROM dramas WHERE id=?", (drama_id,))
        self._open_drama(drama_id)
        if d and d["work_type"] == "video_clone":
            ok(tr("项目设置在页面上方:模型、风格与人物资产图"))

    def _open_drama(self, drama_id: int):
        d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
        if not d:
            return
        self._cur_drama_id = drama_id
        if d["work_type"] == "video_clone":
            self._ensure_fresh("clone")
            self.clone_page.load(drama_id)
            self.stack.setCurrentWidget(self.clone_page)
        else:
            self._ensure_fresh("project")
            self.project_page.load(drama_id)
            self.stack.setCurrentWidget(self.project_page)

    def _back_to_projects(self):
        self._ensure_fresh("projects")
        self.projects_page.reload()
        self.stack.setCurrentWidget(self.projects_page)

    def _back_to_project(self):
        self._ensure_fresh("project")
        self.project_page.load(self.episode_page.drama_id)
        self.stack.setCurrentWidget(self.project_page)

    def _enter_episode(self, drama_id: int, episode_id: int):
        self._cur_drama_id, self._cur_episode_id = drama_id, episode_id
        self._ensure_fresh("episode")
        self.episode_page.load(drama_id, episode_id)
        self.stack.setCurrentWidget(self.episode_page)

    def _promo_dialog(self, drama_id: int):
        # 宣传文案已内置到项目页(A5),这里保留兼容入口
        pass

    def _switch_language(self):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidget, QListWidgetItem
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ui_language"))
        dlg.resize(300, 420)
        lay = QVBoxLayout(dlg)
        lw = QListWidget()
        cur = db.get_setting("ui_language", "zh")
        for code, name in LANGS:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, code)
            if code == cur:
                item.setSelected(True)
            lw.addItem(item)
        lay.addWidget(lw)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        if dlg.exec() == QDialog.Accepted and lw.currentItem():
            lang = lw.currentItem().data(Qt.UserRole)
            db.set_setting("ui_language", lang)
            db.set_setting("content_language", lang)
            db.set_setting("ui_language_explicit", "1")   # 用户手选,此后不再跟随系统
            set_language(lang)          # 触发监听器 → 界面即时重建,不需要重启

    def _toggle_theme(self):
        cur = db.get_setting("theme", "light")
        new = "dark" if cur != "dark" else "light"
        db.set_setting("theme", new)
        from PySide6.QtWidgets import QApplication
        apply_theme(QApplication.instance(), new)

    # ── PhotoCraft 聊天改图页面(独立 tab) ──
    def toggle_chat_drawer(self):
        """旧名保留兼容:点 💬 头按钮 = 切到聊天改图 tab。"""
        self._goto("chatedit")

    def open_chat_with_image(self, path: str):
        """外部(资产卡等)送一张图进聊天改图:切 tab 并作为会话当前图。"""
        self._goto("chatedit")
        self.chat_edit_page.set_image(path)

    def _on_chat_image_saved(self, out_path: str):
        """抽屉里点「保存到结果区」:成品落到同页批量区的结果行。

        原先这条路径是写进独立的「图片处理」页;那个页下线后成品没地方可去,
        统一停在 ChatEditPanel 的批量区里,导出目录与批处理共用同一个。
        """
        self._goto("chatedit")
        self.chat_edit_page.add_external_result(out_path)

    def _open_photocraft_desktop(self):
        from ..ai.photocraft_bridge import resolve_app_path
        import os
        p = resolve_app_path()
        if not p:
            from .toast import err
            err(tr("chat_edit_cli_missing"))
            return
        try:
            os.startfile(p)  # noqa: Windows
        except Exception as exc:  # noqa: BLE001
            from .toast import err
            err(str(exc)[:200])

    def _open_settings(self):
        dlg = SettingsDialog(self, on_language_changed=self._on_language_changed,
                             on_theme_changed=self._apply_theme_cb)
        dlg.exec()
        self._refresh_ai_banner()

    def _show_install_help(self):
        """「?」按钮 → 列出所有需要安装/配置的服务,以及哪些没就绪。

        设计要点:
        - 7 类服务全覆盖(text/image/video/tts/faceswap/jev/photocraft),
          不止 AI 厂商配置 —— PhotoCraft 桌面端这种**本地工具**也列,
          因为它是聊天改图的核心依赖;
        - 已就绪的标 ✓(淡绿),未就绪标 ✗(红);
        - 每行可点 → 跳到设置页(未就绪行才跳转,避免对已配置项做无效跳转);
        - 标题/说明/按钮文案全部走 tr(),多语言同步。
        """
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
        from PySide6.QtCore import Qt
        from ..ai.registry import readiness, SVC_CN_LABEL

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("install_help_title"))
        dlg.resize(520, 420)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 12)
        lay.setSpacing(10)

        head = QLabel(tr("install_help_title"))
        head.setStyleSheet("font-size:15px; font-weight:700;")
        lay.addWidget(head)
        intro = QLabel(tr("install_help_intro"))
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#666;")
        lay.addWidget(intro)

        # 已就绪状态映射(从 readiness() 取)
        try:
            ready = {st: status == "ok" for st, status, _ in readiness()}
        except Exception:  # noqa: BLE001
            ready = {}

        # 所有服务行:逐项 → label + 状态 + 行可点跳转
        rows = [
            ("text",       "svc_text",       "set_text"),
            ("image",      "svc_image",      "set_image"),
            ("video",      "svc_video",      "set_video"),
            ("tts",        "svc_tts",        "set_tts"),
            ("faceswap",   "svc_faceswap",   "set_faceswap"),
            ("jev",        "svc_jev",        "set_jev"),
        ]
        for st, label_key, _tab in rows:
            row = QHBoxLayout()
            row.setSpacing(8)
            name = QLabel(f"● {tr(label_key)}")
            name.setStyleSheet("font-size:13px;")
            row.addWidget(name, 1)
            is_ready = ready.get(st, False)
            if is_ready:
                status = QLabel("✓")
                status.setStyleSheet("color:#16a34a; font-weight:700;")
            else:
                status = QLabel("✗ 未配置")
                status.setStyleSheet("color:#dc2626;")
            status.setFixedWidth(60)
            status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(status)
            if not is_ready:
                # 未就绪行可点 → 跳设置 tab
                btn = QPushButton(tr("open_settings"))
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _=False, s=st: (dlg.accept(), self._open_settings_for(s)))
                row.addWidget(btn)
            lay.addLayout(row)

        # PhotoCraft 桌面端单独一行 —— 检测逻辑跟 readiness() 不同(它不查表),
        # 直接读 db 的 photocraft_install_dir + photocraft_cli_path
        from ..core import db as _db
        from ..ai import photocraft_bridge as _pcb
        pc_ok = bool(_pcb.resolve_app_path() or _pcb.resolve_cli_path())
        row = QHBoxLayout()
        row.setSpacing(8)
        name = QLabel(f"● {tr('svc_photocraft')}")
        name.setStyleSheet("font-size:13px;")
        row.addWidget(name, 1)
        if pc_ok:
            status = QLabel("✓")
            status.setStyleSheet("color:#16a34a; font-weight:700;")
        else:
            status = QLabel("✗ 未安装")
            status.setStyleSheet("color:#dc2626;")
        status.setFixedWidth(60)
        status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(status)
        if not pc_ok:
            hint = QLabel(tr("svc_install_hint"))
            hint.setStyleSheet("color:#888; font-size:11px;")
            hint.setWordWrap(True)
            lay.addLayout(row)
            lay.addWidget(hint)
            btn = QPushButton(tr("open_settings"))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False: (dlg.accept(), self._open_settings()))
            lay.addWidget(btn)
        else:
            lay.addLayout(row)

        # 关闭按钮
        lay.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        close = QPushButton(tr("u_cancel"))
        close.clicked.connect(dlg.reject)
        btns.addWidget(close)
        lay.addLayout(btns)
        dlg.exec()

    def _open_settings_for(self, svc_type: str):
        """点某行「未就绪」按钮 → 跳到 SettingsDialog 的对应服务 tab。"""
        # SettingsDialog 用 tabWidget + tabsNav,索引顺序是固定的:
        # 0=AI 服务(总览) 1=文本 2=图片 3=视频 4=配音 5=换脸 6=PhotoCraft 7=Jev 8=通用 9=主题 10=关于
        tab_idx = {"text": 1, "image": 2, "video": 3, "tts": 4,
                   "faceswap": 5, "jev": 7}.get(svc_type, 0)
        try:
            self._open_settings_with_tab(tab_idx)
        except AttributeError:
            # 旧 SettingsDialog 没带 tab 跳转 → 退到普通打开
            self._open_settings()

    def _open_settings_with_tab(self, tab_idx: int):
        """开 SettingsDialog 并跳到指定 tab。"""
        from .settings_dialog import SettingsDialog
        dlg = SettingsDialog(self, on_language_changed=self._on_language_changed,
                             on_theme_changed=self._apply_theme_cb)
        try:
            dlg.tabs_nav.setCurrentRow(tab_idx)
        except Exception:  # noqa: BLE001
            pass
        dlg.exec()
        self._refresh_ai_banner()

    def _on_language_changed(self, lang: str):
        self.retranslate()

    def _apply_theme_cb(self, mode: str):
        from PySide6.QtWidgets import QApplication
        apply_theme(QApplication.instance(), "dark" if mode == "dark" else
                    ("dark" if mode == "system" and self._system_dark() else "light"))

    @staticmethod
    def _system_dark() -> bool:
        try:
            import darkdetect  # type: ignore
            return darkdetect.isDark()
        except Exception:  # noqa: BLE001
            return False


def QApplication_instance():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance()


def _playable_video(src: str) -> str:
    """返回一个保证能在 Qt Multimedia 里播的本地路径(必要时转码)。

    Qt Multimedia 在 Windows 上走 WMF/FFmpeg 后端,**对 AV1 支持很不完整** ——
    实测 B 站下的 av01 参考视频直接播是黑屏/无响应。AV1 转 H.264 后一律可播,
    15 秒片子转码不到 1 秒。其他编码原样返回,不白折腾一次转码。
    """
    import subprocess
    from ..core import config
    # Path("") 会变成 "."(当前目录)且 exists() 为真 —— 直接拿去 ffmpeg 会白跑一次,
    # 空串必须在这里挡掉。
    if not str(src or "").strip():
        return str(src)
    p = Path(str(src))
    if not p.is_file():
        return str(src)
    try:
        ff = config.find_ffmpeg()
        probe = subprocess.run([ff, "-i", str(p)], capture_output=True, timeout=60)
        if "av01" not in probe.stderr.decode("utf-8", "replace"):
            return str(p)                     # 非 AV1,直接用原文件
        out_dir = config.STATIC_DIR / "temp"
        out_dir.mkdir(parents=True, exist_ok=True)
        dst = out_dir / f"play-{p.stem}.mp4"
        subprocess.run([ff, "-y", "-i", str(p), "-c:v", "libx264", "-preset",
                        "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", str(dst)],
                       capture_output=True, timeout=600)
        return str(dst) if dst.exists() and dst.stat().st_size > 0 else str(p)
    except Exception:  # noqa: BLE001
        return str(p)                        # 转码失败就用原文件,让播放器自己报错


class _RefVideoDialog(QDialog):
    """参考视频播放弹窗(Qt Multimedia,无额外依赖)。

    独立弹窗而不是内嵌:复刻页有一排操作按钮 + 一列分镜卡片,再塞一个 480×270
    的播放器会把列表挤到要滚动才能看完。弹窗也天然支持「边看原片边对照分镜」——
    窗口可以拖到一边,分镜列表还在另一边的屏幕上。
    """

    def __init__(self, parent, path):
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoWidget
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout
        self.setWindowTitle(tr("参考视频") + " · " + Path(str(path)).name)
        self.resize(760, 520)
        root = QVBoxLayout(self)
        self._video = QVideoWidget(self)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setVideoOutput(self._video)
        self._player.setSource(QUrl.fromLocalFile(_playable_video(path)))
        root.addWidget(self._video, 1)
        row = QHBoxLayout()
        play = QPushButton(tr("播放") + " / " + tr("暂停"))
        play.clicked.connect(self._toggle_play)
        close = W.primary_btn(tr("close"))
        close.clicked.connect(self._close_and_stop)
        row.addWidget(play)
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)
        self._player.play()

    def _toggle_play(self):
        # QMediaPlayer 只在 __init__ 里局部 import 过,这里要用必须再导一次
        from PySide6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _close_and_stop(self):
        # 必须先 stop 再关:QMediaPlayer 还在播的话,窗口销毁后音频线程可能残留
        self._player.stop()
        self.accept()


class _RefVideoWidget(QWidget):
    """参考视频入口(按钮 + 文件名);点开弹播放器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.toggle = QPushButton(tr("看原视频"))
        self.toggle.setObjectName("ffAction")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.clicked.connect(self._open)
        lay.addWidget(self.toggle)
        self.hint = QLabel("")
        self.hint.setObjectName("inspectorLabel")
        lay.addWidget(self.hint)
        lay.addStretch(1)
        self._path = ""

    def set_source(self, path):
        p = str(path or "")
        self._path = p
        self.hint.setText(Path(p).name if p else tr("尚未导入参考视频"))
        self.toggle.setEnabled(bool(p))

    def _open(self):
        if not self._path:
            err(tr("尚未导入参考视频"))
            return
        try:
            _RefVideoDialog(self.window(), self._path).exec()
        except Exception as exc:  # noqa: BLE001
            err(tr("无法播放参考视频:") + str(exc)[:200])


class ClonePage(QWidget):
    """同款复刻工作台:参考视频分析 → 素材 → 逐镜重拍 → 拼接。"""
    back_requested = Signal()
    # 整段直传拆解的产物落在 storyboards 表(分镜工作台那套),不像抽帧分析写
    # metadata —— 需要跳到工作台时用这个信号,请 MainWindow 接 _enter_episode。
    open_workbench_requested = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.drama_id = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)
        head = QHBoxLayout()
        back = QPushButton("← " + tr("back"))
        back.clicked.connect(self.back_requested.emit)
        self.title = W.h1("")
        head.addWidget(back)
        head.addWidget(self.title)
        head.addStretch(1)
        root.addLayout(head)
        self.intro = W.muted(tr("wt_clone_desc"))
        root.addWidget(self.intro)

        bar = QHBoxLayout()
        analyze_btn = W.primary_btn("1️⃣ " + tr("detect") + " · AI " + tr("storyboard"))
        analyze_btn.clicked.connect(lambda: self._analyze(direct=False))
        # 直传曾是一个独立按钮(1️⃣'),产物却写进 storyboards 表 —— 于是同一项目
        # 会并存两套分镜(metadata 抽帧版 + 表直传版),而只有抽帧版支持换产品。
        # 合并成模式开关:两条路现在产出同构、落同一处,下游无感。
        self.clone_direct_mode = False
        direct_btn = QPushButton(tr("整段直传模式"))
        direct_btn.setCheckable(True)
        direct_btn.setCursor(Qt.PointingHandCursor)
        direct_btn.setToolTip(
            tr("整段视频直接交给多模态模型拆解(不抽帧,能看到连续运动,更准但更慢更贵)。\n"
               "默认抽 8 帧分析:快、便宜,适合静态为主的开箱/特写类带货片。"))
        def _toggle_direct(on: bool):
            self.clone_direct_mode = on
            direct_btn.setProperty("primary", "1" if on else "0")
            direct_btn.style().unpolish(direct_btn)
            direct_btn.style().polish(direct_btn)
            analyze_btn.setText(("1️⃣ " + tr("整段直传拆解")) if on
                                else ("1️⃣ " + tr("detect") + " · AI " + tr("storyboard")))
        direct_btn.toggled.connect(_toggle_direct)
        bar.addWidget(direct_btn)
        # 一键重绘:换完素材后逐镜点「重绘」太碎,尤其分镜多的时候
        redraw_all_btn = W.primary_btn("3️⃣ " + tr("一键重绘首帧"))
        redraw_all_btn.setToolTip(tr("把所有缺首帧的分镜逐张生成(串行,逐镜消耗生图额度)"))
        redraw_all_btn.clicked.connect(self._redraw_all_shots)
        self.redraw_all_btn = redraw_all_btn
        self._shot_busy: set = set()      # 正在生成的镜号,渲染时占位
        bar.addWidget(redraw_all_btn)
        presenter_btn = QPushButton("2️⃣ AI " + tr("生成出镜模特"))
        presenter_btn.clicked.connect(self._presenter)
        # 换素材:后端 upload_material 一直在,但此前建完项目就没有入口了 ——
        # 想换人物/产品只能删项目重建,而重建会重跑视频拆解、丢掉已生成的首帧。
        product_btn = QPushButton("2️⃣' " + tr("替换产品图"))
        product_btn.setToolTip(tr("换成新的产品照片,并自动重新识别产品描述"))
        product_btn.clicked.connect(lambda: self._replace_material("product"))
        presenter_img_btn = QPushButton("2️⃣'' " + tr("替换出镜照"))
        presenter_img_btn.setToolTip(tr("换成新的出镜人照片,用于锁定人物长相"))
        presenter_img_btn.clicked.connect(lambda: self._replace_material("presenter"))
        merge_btn = W.primary_btn("4️⃣ " + tr("merge_now"))
        merge_btn.clicked.connect(self._merge)
        bar.addWidget(analyze_btn)
        bar.addWidget(presenter_btn)
        bar.addWidget(product_btn)
        bar.addWidget(presenter_img_btn)
        bar.addWidget(merge_btn)
        bar.addStretch(1)
        root.addLayout(bar)
        # 生图/文本模型下拉:「用我选的就是我用的」——之前批量重绘偷用
        # registry.default_config 去猜,结果挑中了额度耗尽的百炼,而用户顶栏
        # 明明选的是 Agnes。文本模型同理:拆解与分镜改写都走它,不同厂商的
        # max_tokens/上下文能力差异很大(见设置页的两个输入框),必须可选。
        mrow = QHBoxLayout()
        mlab = QLabel(tr("生图模型"))
        mlab.setObjectName("inspectorLabel")
        mrow.addWidget(mlab)
        self.clone_image_combo = QComboBox()
        self.clone_image_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.clone_image_combo.setMinimumWidth(120)
        self.clone_image_combo.setMaximumWidth(240)
        mrow.addWidget(self.clone_image_combo)
        tlab = QLabel(tr("文本模型"))
        tlab.setObjectName("inspectorLabel")
        mrow.addWidget(tlab)
        self.clone_text_combo = QComboBox()
        self.clone_text_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.clone_text_combo.setMinimumWidth(120)
        self.clone_text_combo.setMaximumWidth(240)
        mrow.addWidget(self.clone_text_combo)
        mrow.addStretch(1)
        root.addLayout(mrow)
        self._reload_clone_image_models()
        self._reload_clone_text_models()
        # 项目设置:画面风格 + 人物参照图重建。
        srow = QHBoxLayout()
        slab = QLabel(tr("画面风格"))
        slab.setObjectName("inspectorLabel")
        srow.addWidget(slab)
        self.clone_style_combo = QComboBox()
        self.clone_style_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.clone_style_combo.setMinimumWidth(140)
        self.clone_style_combo.setMaximumWidth(260)
        srow.addWidget(self.clone_style_combo)
        # 全身像 = 分镜参考主图(锁脸 + 锁服装);三视图仅供人工核对
        self.clone_fs_btn = QPushButton(tr("重建人物全身像"))
        self.clone_fs_btn.setObjectName("ffAction")
        self.clone_fs_btn.setCursor(Qt.PointingHandCursor)
        self.clone_fs_btn.setToolTip(
            tr("用「替换出镜照」里的人物照重新生成单人全身像,"
               "作为跨镜锁人物长相与服装的参考图"))
        self.clone_fs_btn.clicked.connect(self._rebuild_fullshot)
        srow.addWidget(self.clone_fs_btn)
        self.clone_ta_btn = QPushButton(tr("重建人物三视图"))
        self.clone_ta_btn.setObjectName("ffAction")
        self.clone_ta_btn.setCursor(Qt.PointingHandCursor)
        self.clone_ta_btn.setToolTip(
            tr("重新生成三视图(正脸特写 + 正面/侧面/背面),仅供人工核对,不用于分镜"))
        self.clone_ta_btn.clicked.connect(self._rebuild_turnaround)
        srow.addWidget(self.clone_ta_btn)
        srow.addStretch(1)
        root.addLayout(srow)
        # 控件建好之后再填数据/接信号 —— 顺序反了会 AttributeError
        self._reload_clone_styles()
        self.clone_style_combo.currentIndexChanged.connect(self._apply_clone_style)
        # 参考视频播放器:判断「分镜拆得对不对」的唯一依据就是原片 ——
        # 没有它,用户只能盯着生成的首帧猜原片是什么样,拆解跑偏了也无从发现。
        # 放在按钮条正下方,随时可对着原片核对每一镜。
        self.ref_player = _RefVideoWidget()
        root.addWidget(self.ref_player)
        # 配置总览:把「当前实际生效的配置」列出来 —— 上面的下拉只显示模型名,
        # 看不到底层的关键参数(生图档位/视频模型/换脸引擎),出问题无从查起。
        self.settings_note = W.muted("")
        self.settings_note.setWordWrap(True)
        self.settings_note.setObjectName("inspectorLabel")
        root.addWidget(self.settings_note)
        # 素材缩略图:换完之后要能一眼确认换成功了,不必点重绘才知道
        self.material_row = QHBoxLayout()
        self.material_row.setSpacing(6)
        self.mat_product_lab = QLabel()
        self.mat_product_lab.setFixedSize(110, 110)
        self.mat_product_lab.setAlignment(Qt.AlignCenter)
        self.mat_product_lab.setToolTip(tr("当前产品图"))
        self.mat_presenter_lab = QLabel()
        self.mat_presenter_lab.setFixedSize(110, 110)
        self.mat_presenter_lab.setAlignment(Qt.AlignCenter)
        self.mat_presenter_lab.setToolTip(tr("当前出镜人"))
        # 派生资产缩略图:全身像 / 三视图 / 场景图 —— 此前只存在磁盘上,界面看不到
        self.mat_fullshot_lab = QLabel()
        self.mat_fullshot_lab.setFixedSize(110, 110)
        self.mat_fullshot_lab.setAlignment(Qt.AlignCenter)
        self.mat_turn_lab = QLabel()
        self.mat_turn_lab.setFixedSize(110, 110)
        self.mat_turn_lab.setAlignment(Qt.AlignCenter)
        self.mat_scene_lab = QLabel()
        self.mat_scene_lab.setFixedSize(110, 110)
        self.mat_scene_lab.setAlignment(Qt.AlignCenter)
        self.material_row.addWidget(self.mat_product_lab)
        self.material_row.addWidget(self.mat_presenter_lab)
        self.material_row.addWidget(self.mat_fullshot_lab)
        self.material_row.addWidget(self.mat_turn_lab)
        self.material_row.addWidget(self.mat_scene_lab)
        self.material_row.addStretch(1)
        root.addLayout(self.material_row)
        # 直传产物落在 storyboards 表,本页列表(读 metadata)看不到它 —— 单独一行
        # 显示条数并给跳转入口,否则用户点了按钮像什么都没发生。
        self.board_note = W.muted("")
        self.board_note.setVisible(False)
        root.addWidget(self.board_note)
        self.board_clear_btn = QPushButton(tr("清掉旧分镜"))
        self.board_clear_btn.setObjectName("ffAction")
        self.board_clear_btn.setCursor(Qt.PointingHandCursor)
        self.board_clear_btn.clicked.connect(self._clear_legacy_boards)
        self.board_clear_btn.setVisible(False)
        root.addWidget(self.board_clear_btn)
        self.board_list = QVBoxLayout()
        root.addLayout(self.board_list)
        root.addStretch(1)
        # 首帧缩略图索引:镜号 → QLabel。批量重绘时单镜出图就能只换那一张,
        # 不必整表 reload(整表会把已出的图闪掉重来)。
        self._shot_thumbs = []

    def load(self, drama_id: int):
        self.drama_id = drama_id
        d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
        self.title.setText(f"▷ {d['title']}")
        from ..pipeline import video_clone as _vc
        ref = _vc._resolve_local((_vc._meta(drama_id).get("clone") or {}).get("reference"))
        self.ref_player.set_source(ref or "")
        self.reload()

    def reload(self):
        while self.board_list.count():
            item = self.board_list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        # 旧卡片已销毁,索引必须一起清,否则会攒下一堆悬空控件,
        # 后面「生成一张显示一张」按索引找缩略图会刷到已 deleteLater 的对象。
        self._shot_thumbs = []
        from ..pipeline import video_clone
        boards = video_clone._clone_storyboards(self.drama_id)
        self._refresh_board_note()
        self._refresh_materials()
        self._refresh_settings_note()
        for b in boards:
            box = W.make_card()
            lay = QHBoxLayout(box)
            lay.setContentsMargins(12, 8, 12, 8)
            # 首帧缩略图:此前每张卡片只画了文字与按钮,generate_shot_image 写进
            # b["first_frame"] 的图**没有任何渲染分支**(b["video"] 有,首帧没有),
            # 于是首帧生成成功了界面也看不见,用户只能反复点重绘去磁盘里翻。
            # 加了之后「素材换没换成功」点一次重绘就能当场确认。
            ff = b.get("first_frame")
            thumb = QLabel()
            thumb.setFixedSize(190, 150)
            thumb.setAlignment(Qt.AlignCenter)
            # 登记到索引:批量重绘「生成一张显示一张」靠它定位到具体那一张
            thumb.setProperty("shotNumber", int(b.get("number", 0)))
            self._shot_thumbs.append(thumb)
            if ff:
                thumb.setPixmap(W.pixmap_from_media(ff, 190, 150))
                thumb.setCursor(Qt.PointingHandCursor)
                full = str(ff)
                thumb.mousePressEvent = lambda _e, u=full: self._view_image_big(u)
            elif int(b.get("number", 0)) in getattr(self, "_shot_busy", set()):
                # 正在生成:给明确的等待态,而不是笼统的空态 ——
                # 批量重绘时用户要能看出「跑到第几镜、这镜还在跑」
                thumb.setText("⠋ " + tr("生成中…"))
            else:
                # 这里显示的是**首帧**,不是尾帧。此前误用了 no_last_frame 这个键,
                # 界面上 4 张卡片全写「暂无尾帧」,与旁边的「重绘·首帧图」按钮自相矛盾
                thumb.setText(tr("no_first_frame"))
            lay.addWidget(thumb)
            info = QVBoxLayout()
            head = QHBoxLayout()
            head.addWidget(W.h2(f"#{int(b.get('number', 0)):02d}"))
            head.addWidget(W.tag(f"{b.get('start','?')}-{b.get('end','?')}s"))
            if b.get("video"):
                head.addWidget(W.tag(tr("done")))
            head.addStretch(1)
            info.addLayout(head)
            steps = [str(s).strip() for s in (b.get("action_steps") or []) if str(s).strip()]
            action_txt = "；".join(f"{i}.{s}" for i, s in enumerate(steps, 1)) if steps else b.get("action", "")
            head_bits = " · ".join(x for x in (b.get("shot", ""), b.get("camera", "")) if x)
            desc = QLabel(f"{head_bits}  {action_txt}  {(tr('产品:') + b.get('product_use','')) if b.get('product_use') else ''}")
            desc.setWordWrap(True)
            info.addWidget(desc)
            if b.get("line"):
                line = QLabel(b["line"])
                line.setObjectName("muted")
                info.addWidget(line)
            lay.addLayout(info, 1)
            btns = QVBoxLayout()
            img_btn = QPushButton("3️⃣ " + tr("redraw") + tr(" · 首帧图"))
            img_btn.clicked.connect(lambda _=False, n=int(b.get("number", 0)): self._shot_image(n))
            vid_btn = W.primary_btn("▷ " + tr("batch_video"))
            vid_btn.clicked.connect(lambda _=False, n=int(b.get("number", 0)): self._shot_video(n))
            btns.addWidget(img_btn)
            btns.addWidget(vid_btn)
            lay.addLayout(btns)
            self.board_list.addWidget(box)

    def _analyze(self, direct: bool = False):
        from ..pipeline import video_clone
        def job(tid):
            return video_clone.analyze_reference(self.drama_id, direct=direct,
                                                 config_id=self._clone_text_cfg())
        def done(tid, result, error):
            if error:
                err(str(error)[:280])
            self.reload()
        TASKMGR.submit("clone_analyze", job, done, drama_id=self.drama_id,
                       episode_id=self._clone_episode_id())

    def _refresh_board_note(self):
        """提示「本集分镜表里还有旧版直传拆解的产物」——那些分镜本页看不到。

        直传拆分并入 analyze 的模式开关后,新拆解不再写 storyboards 表,
        但**旧项目**的表里可能还留着当初直传写进去的分镜。用户会困惑
        「本页 4 个,表里 6 个,重拍哪套?」——这里点明来源并给清理入口。
        """
        ep_id = self._clone_episode_id()
        n = 0 if not ep_id else len(
            db.q("SELECT id FROM storyboards WHERE episode_id=?", (ep_id,)))
        self.board_note.setVisible(bool(n))
        if n:
            self.board_note.setText(
                tr("本集分镜表还留着 {n} 个旧版直传拆解的分镜(本页重拍读的是 clone 分镜表,"
                   "两套不通用)。删掉可避免混淆:").format(n=n))
            btn = getattr(self, "board_clear_btn", None)
            if btn is not None:
                btn.setVisible(True)

    def _clone_episode_id(self) -> int:
        """同款复刻项目在新建时就会建第 1 集当分镜挂载点(对齐参考项目
        「各类型都建首集容器,clone 也需要」),直传拆解写入的就是它。"""
        row = db.q1("SELECT id FROM episodes WHERE drama_id=? "
                    "ORDER BY episode_number LIMIT 1", (self.drama_id,))
        return row["id"] if row else 0

    def _clear_legacy_boards(self):
        """删掉本集 storyboards 表里的旧版直传分镜。

        直传拆分并入 analyze 的「整段直传模式」后,新拆解统一落 clone.storyboards,
        表里这份是旧版留下的、且**不支持产品替换**。两套并存只会让人搞不清
        「重拍哪一套」,而且它们互不同步。删掉以本项目为准。
        """
        from .confirm import ask
        ep_id = self._clone_episode_id()
        if not ep_id:
            return
        n = len(db.q("SELECT id FROM storyboards WHERE episode_id=?", (ep_id,)))
        if not n:
            return
        if not ask(self, tr("清掉旧分镜"),
                   tr("将删除本集分镜表里的 {n} 个旧分镜(旧版整段直传拆解的产物,"
                      "本页重拍用的是 clone 分镜表,不在这 {n} 个里)。\n\n确定删除?").format(n=n),
                   danger=True):
            return
        for o in db.q("SELECT id FROM storyboards WHERE episode_id=?", (ep_id,)):
            db.ex("DELETE FROM storyboard_characters WHERE storyboard_id=?", (o["id"],))
            db.ex("DELETE FROM storyboard_props WHERE storyboard_id=?", (o["id"],))
        db.ex("DELETE FROM storyboards WHERE episode_id=?", (ep_id,))
        self.reload()
        ok(tr("已删除 {n} 个旧分镜").format(n=n))

    def _presenter(self):
        from ..pipeline import video_clone
        d = db.q1("SELECT style FROM dramas WHERE id=?", (self.drama_id,))
        def job(tid):
            return video_clone.prepare_presenter(self.drama_id, d["style"],
                                                  config_id=self._clone_image_cfg())
        def done(tid, result, error):
            if error:
                err("AI")
        TASKMGR.submit("clone_presenter", job, done, drama_id=self.drama_id,
                       episode_id=self._clone_episode_id())

    def _reload_clone_image_models(self):
        """填充生图模型下拉,默认值与分镜工作台共用 yihao.model.image 全局记忆。"""
        from ..ai import registry
        self.clone_image_combo.blockSignals(True)
        self.clone_image_combo.clear()
        self.clone_image_combo.addItem(tr("configured"), None)
        for r in registry.list_configs("image"):
            self.clone_image_combo.addItem((r["model"] or "").split("/")[-1] or r["model"], r["id"])
        saved = db.resolve_selected_config_id("image")
        if saved:
            i = self.clone_image_combo.findData(saved)
            if i >= 0:
                self.clone_image_combo.setCurrentIndex(i)
        self.clone_image_combo.blockSignals(False)
        self.clone_image_combo.currentIndexChanged.connect(self._remember_clone_image_model)

    def _remember_clone_image_model(self):
        """与 episode_page._remember_model 同一套全局记忆键,两边联动。"""
        v = self.clone_image_combo.currentData()
        if v:
            db.set_setting("yihao.model.image", str(v))

    def _reload_clone_text_models(self):
        """填充文本模型下拉(拆解 + 分镜改写都用它)。"""
        from ..ai import registry
        self.clone_text_combo.blockSignals(True)
        self.clone_text_combo.clear()
        self.clone_text_combo.addItem(tr("configured"), None)
        for r in registry.list_configs("text"):
            self.clone_text_combo.addItem((r["model"] or "").split("/")[-1] or r["model"], r["id"])
        saved = db.resolve_selected_config_id("text")
        if saved:
            i = self.clone_text_combo.findData(saved)
            if i >= 0:
                self.clone_text_combo.setCurrentIndex(i)
        self.clone_text_combo.blockSignals(False)
        self.clone_text_combo.currentIndexChanged.connect(self._remember_clone_text_model)

    def _remember_clone_text_model(self):
        v = self.clone_text_combo.currentData()
        if v:
            db.set_setting("yihao.model.text", str(v))

    def _reload_clone_styles(self):
        """填充画面风格下拉:与短剧/小说侧共用 style_presets,并默认带上当前项目的风格。"""
        try:
            self.clone_style_combo.blockSignals(True)
            self.clone_style_combo.clear()
            for r in db.q("SELECT value, name FROM style_presets "
                          "WHERE is_active=1 AND style_type='visual' ORDER BY sort_order, id"):
                self.clone_style_combo.addItem(db.style_display_name(r["value"], r["name"]), r["value"])
            cur = ""
            if self.drama_id:
                d = db.q1("SELECT style FROM dramas WHERE id=?", (self.drama_id,))
                cur = (d["style"] if d else "") or ""
            i = self.clone_style_combo.findData(cur)
            if i >= 0:
                self.clone_style_combo.setCurrentIndex(i)
            self.clone_style_combo.blockSignals(False)
        except Exception:  # noqa: BLE001
            pass

    def _apply_clone_style(self):
        """把下拉里的风格写回项目。成品镜头按它出图。"""
        v = self.clone_style_combo.currentData()
        if v and self.drama_id:
            db.ex("UPDATE dramas SET style=?, updated_at=? WHERE id=?",
                  (v, db.now(), self.drama_id))
            ok(tr("画面风格已更新"))

    def _rebuild_fullshot(self):
        """重建单人全身像 —— 分镜真正使用的参考主图(锁脸 + 锁服装)。"""
        from ..pipeline import video_clone
        from .confirm import ask
        clone = (video_clone._meta(self.drama_id).get("clone") or {})
        src = video_clone._resolve_local(clone.get("presenter"))
        if not src:
            err(tr("请先上传出镜人照片"))
            return
        if not ask(self, tr("重建人物全身像"),
                   tr("将用当前上传的人物照生成单人全身像(消耗一次生图额度)。\n\n继续?")):
            return
        btn = getattr(self, "clone_fs_btn", None)
        if btn is not None:
            btn.setEnabled(False)

        def job(tid):
            return str(video_clone.build_presenter_fullshot(
                src, config_id=self._clone_image_cfg(),
                text_cfg_id=video_clone._selected_text_cfg(),
                swap_cfg_id=video_clone._selected_swap_cfg()))

        def done(tid, result, error):
            if btn is not None:
                btn.setEnabled(True)
            if error:
                err(str(error)[:280])
                return
            c = video_clone._meta(self.drama_id)
            c.setdefault("clone", {})["presenter_fullshot"] = result
            video_clone._save_meta(self.drama_id, c)
            db.ex("UPDATE characters SET image_url=?, updated_at=? "
                  "WHERE drama_id=? AND name=?",
                  (config.path_to_media_url(result), db.now(),
                   self.drama_id, video_clone.CLONE_PRESENTER_NAME))
            self.reload()
            ok(tr("人物全身像已重建,重新生成首帧即可生效"))

        TASKMGR.submit("clone_fullshot", job, done, drama_id=self.drama_id,
                       episode_id=self._clone_episode_id())

    def _rebuild_turnaround(self):
        """用当前上传的人物照重建三视图(换模型/换风格/换素材后都要重来)。"""
        from ..pipeline import video_clone
        from .confirm import ask
        clone = (video_clone._meta(self.drama_id).get("clone") or {})
        src = video_clone._resolve_local(clone.get("presenter"))
        if not src:
            err(tr("请先上传出镜人照片"))
            return
        if not ask(self, tr("重建人物三视图"),
                   tr("将用当前上传的人物照重新生成三视图(消耗一次生图额度)。\n\n继续?")):
            return
        btn = getattr(self, "clone_ta_btn", None)
        if btn is not None:
            btn.setEnabled(False)

        def job(tid):
            return str(video_clone.build_presenter_turnaround(
                src, config_id=self._clone_image_cfg()))

        def done(tid, result, error):
            if btn is not None:
                btn.setEnabled(True)
            if error:
                err(str(error)[:280])
                return
            from ..core import db as _db
            c = video_clone._meta(self.drama_id)
            cc = c.setdefault("clone", {})
            cc["turnaround_image"] = result          # 三视图:仅供人工核对
            video_clone._save_meta(self.drama_id, c)
            # 分镜用的是**全身像**,重建三视图不该改动分镜参考图
            ok(tr("人物三视图已重建(仅供核对),重新生成首帧即可生效"))
            self.reload()
            ok(tr("人物三视图已重建,重新生成首帧即可生效"))

        TASKMGR.submit("clone_turnaround", job, done, drama_id=self.drama_id,
                       episode_id=self._clone_episode_id())

    def _clone_text_cfg(self):
        return getattr(self, "clone_text_combo", None) and self.clone_text_combo.currentData()

    def _clone_image_cfg(self):
        """当前选中的生图配置 id;未选(None)时返回 None 让 image_client 走默认。"""
        return getattr(self, "clone_image_combo", None) and self.clone_image_combo.currentData()

    def _refresh_settings_note(self):
        """列出当前实际生效的配置:光看模型名看不出底层的档位/引擎/价格档。"""
        from ..ai import registry
        from ..pipeline import video_clone
        parts = []
        def _name(cid, kind):
            try:
                r = db.q1("SELECT model FROM ai_service_configs WHERE id=?", (cid,))
                return (r["model"] if r else None) or tr("默认")
            except Exception:  # noqa: BLE001
                return tr("默认")
        img = self._clone_image_cfg()
        txt = video_clone._selected_text_cfg()
        swp = video_clone._selected_swap_cfg()
        vid = None
        try:
            v = registry.default_config("video", None)
            vid = (v or {}).get("model")
        except Exception:  # noqa: BLE001
            pass
        parts.append(tr("生图") + ": " + _name(img, "image"))
        parts.append(tr("文本/改写") + ": " + _name(txt, "text"))
        parts.append(tr("换脸") + ": " + _name(swp, "faceswap"))
        parts.append(tr("视频") + ": " + str(vid or tr("未配置")))
        style = self.clone_style_combo.currentText() if hasattr(self, "clone_style_combo") else ""
        if style:
            parts.append(tr("画面风格") + ": " + style)
        clone = (video_clone._meta(self.drama_id).get("clone") or {})
        bs = len(clone.get("storyboards") or [])
        if bs:
            parts.append(tr("分镜") + f": {bs} " + tr("镜"))
        have = sum(1 for b in (clone.get("storyboards") or []) if b.get("first_frame"))
        if bs:
            parts.append(tr("已出首帧") + f": {have}/{bs}")
        self.settings_note.setText("   |   ".join(parts))

    def _refresh_materials(self):
        """素材与派生资产缩略图:换完素材当场能看到换没换成功。

        除了用户上传的产品图/出镜照,还显示**系统派生出来的资产图**:
          · 人物全身像 —— 分镜真正使用的参考主图(纯文字生成 + 换脸)
          · 人物三视图 —— 仅供人工核对长相/体型/服装
          · 场景图     —— 首镜出图后固化,后续镜锁同一场景
        这三张此前只躺在磁盘上,用户完全看不到,只能靠猜。
        """
        from ..pipeline import video_clone
        clone = (video_clone._meta(self.drama_id).get("clone") or {})
        items = (("product", self.mat_product_lab, tr("当前产品图")),
                 ("presenter", self.mat_presenter_lab, tr("当前出镜人")))
        for kind, lab, tip in items:
            path = video_clone._resolve_local(clone.get(kind))
            if path:
                lab.setPixmap(W.pixmap_from_media(str(path), 110, 110))
                lab.setToolTip(tip)
            else:
                lab.setPixmap(QPixmap())
                lab.setText(tr("none"))
                lab.setToolTip(tip)
        # 派生资产:全身像 / 三视图 / 场景
        derived = (("presenter_fullshot", self.mat_fullshot_lab, tr("人物全身像(分镜参考)")),
                   ("turnaround_image", self.mat_turn_lab, tr("人物三视图(仅核对)")),
                   ("scene_image", self.mat_scene_lab, tr("场景图(首镜固化)")))
        for key, lab, tip in derived:
            lab.setToolTip(tip)
            path = video_clone._resolve_local(clone.get(key))
            if path:
                lab.setPixmap(W.pixmap_from_media(str(path), 110, 110))
                lab.setCursor(Qt.PointingHandCursor)
                full = str(path)
                lab.mousePressEvent = lambda _e, u=full: self._view_image_big(u)
            else:
                lab.setPixmap(QPixmap())
                lab.setText(tr("none"))

    def _replace_material(self, kind: str):
        """换产品图 / 出镜人照片。换产品图会多跑一次多模态读图刷新描述。"""
        from ..pipeline import video_clone
        p, _ = QFileDialog.getOpenFileName(
            self, tr("替换产品图") if kind == "product" else tr("替换出镜照"),
            "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not p:
            return
        cfg_id = None
        try:
            from ..core import db as _db
            cfg_id = _db.get_setting("yihao.clone_image_cfg", "") or None
            cfg_id = int(cfg_id) if cfg_id else None
        except (TypeError, ValueError):
            cfg_id = None

        def job(tid):
            return video_clone.replace_material(self.drama_id, kind, p, config_id=cfg_id)

        def done(tid, result, error):
            if error:
                err(str(error)[:280])
                return
            self.reload()
            ok(tr("素材已替换,请点各分镜的「重绘 · 首帧图」刷新画面"))

        TASKMGR.submit("clone_replace_material", job, done, drama_id=self.drama_id,
                       episode_id=self._clone_episode_id())

    def _view_image_big(self, url: str):
        if not url:
            return
        try:
            from .asset_dialogs import ImageViewerDialog
            ImageViewerDialog(self, url).exec()
        except Exception:  # noqa: BLE001
            pass

    def _shot_image(self, n: int):
        from ..pipeline import video_clone
        d = db.q1("SELECT style FROM dramas WHERE id=?", (self.drama_id,))
        cfg_id = self._clone_image_cfg()
        def job(tid):
            return str(video_clone.generate_shot_image(self.drama_id, n, d["style"],
                                                      config_id=cfg_id))
        def done(tid, result, error):
            if error:
                err(str(error)[:280])
            self.reload()
        TASKMGR.submit("clone_image", job, done, drama_id=self.drama_id,
                       episode_id=self._clone_episode_id())

    def _redraw_all_shots(self):
        """一键重绘:串行跑完所有缺首帧的分镜。

        必须**串行**:生图是外部付费接口,并发提交会互相踩限流,且 QThreadPool
        上限 6 个线程,批量 6 镜同时打过去大概率触发上游 429(实测 Agnes 拥塞
        可持续 20 分钟+)。逐镜串行 + 每镜完成即刷新列表,用户能看着图一张张出来,
        而不是全部结束才看到(全表重建 6 行要 1.5s+,之前用户反馈「按了没反应」)。

        默认只补缺首帧的;若全部都有,则问用户「是否强制全部重绘」——换素材/改提示词后
        旧首帧全部作废,却因为「都有图」而一键重绘直接拒绝,用户只能逐镜点(实测踩到)。
        """
        from ..pipeline import video_clone
        from .confirm import ask
        boards = video_clone._clone_storyboards(self.drama_id)
        if not boards:
            err(tr("还没有分镜,请先运行 AI 分镜"))
            return
        todo = [b for b in boards if not (b.get("first_frame") or "").strip()]
        if not todo:
            # 全都有首帧:换素材或改分镜后它们已经过时,给一个强制重绘的出口
            if not ask(self, tr("一键重绘"),
                       tr("所有 {n} 个分镜都已有首帧。\n\n"
                          "若你刚换了产品/人物素材或重跑了 AI 分镜,旧首帧已过时,"
                          "是否全部重绘?\n\n(每镜都会消耗一次生图额度)").format(n=len(boards)),
                       danger=True):
                return
            todo = list(boards)
        elif not ask(self, tr("一键重绘"),
                     tr("将为 {n} 个缺少首帧的分镜逐张生成(逐镜消耗生图额度)。\n\n开始?")
                     .format(n=len(todo))):
            return
        d = db.q1("SELECT style FROM dramas WHERE id=?", (self.drama_id,))
        # 用界面上选的那个模型,不去猜 default_config —— 曾因此挑中额度耗尽的
        # 百炼,用户顶栏明明选的是 Agnes,6 镜里 5 镜吃 429。
        cfg_id = self._clone_image_cfg()
        # 等待态:按钮变「生成中 i/N」并禁用,逐镜卡片占位显示「生成中…」。
        # 此前只有底部状态栏一句「正在处理」,用户不知道跑到第几镜、还要多久。
        btn = getattr(self, "redraw_all_btn", None)
        total = len(todo)

        def _set_busy(done_n: int, running: bool):
            from ..core.taskmgr import on_main

            def _ui():
                if btn is None:
                    return
                btn.setEnabled(not running)
                if running:
                    btn.setText(tr("生成首帧中 {done}/{total}")
                               .format(done=done_n, total=total))
                else:
                    btn.setText("3️⃣ " + tr("一键重绘首帧"))
                self._shot_busy.clear()
                self.reload()
            on_main(_ui)

        self._shot_busy = {int(b.get("number", 0)) for b in todo}
        _set_busy(0, True)
        self.reload()          # 让「生成中」占位立刻出现

        def _on_shot_ready(board_number: int):
            """单镜出图后回主线程刷新**那一张**缩略图(不整表 reload)。

            worker 线程里绝不能碰 Qt 控件 —— 用 taskmgr.on_main 调度回主线程。
            只换对应卡片里的 QLabel pixmap,已出的其他图保持不动(整表 reload
            会把正在显示的图全销毁重建,视觉上等于闪一下)。
            """
            from ..core.taskmgr import on_main

            def _patch():
                from ..pipeline import video_clone as _vc
                row = next((x for x in _vc._clone_storyboards(self.drama_id)
                            if int(x.get("number", 0)) == board_number), None)
                url = (row or {}).get("first_frame")
                if not url:
                    return
                for lab in self._shot_thumbs:
                    if lab.property("shotNumber") == board_number:
                        lab.setPixmap(W.pixmap_from_media(url, 190, 150))
                        return
            on_main(_patch)

        def job(tid):
            done_n = 0
            for b in todo:
                n = int(b.get("number", 0))
                # 每镜独立 try:单镜失败(额度/超时/内容审核)不该让整批停摆,
                # 剩下的继续跑,最后汇总失败数交给用户
                try:
                    video_clone.generate_shot_image(
                        self.drama_id, n, d["style"], config_id=cfg_id)
                    done_n += 1
                except Exception as exc:  # noqa: BLE001
                    print(f"[clone] 分镜#{n} 首帧失败: {exc}", flush=True)
                # 无论成败都要清「生成中」并推进进度,否则失败的镜会永远卡在等待态
                _set_busy(done_n, True)
                # **生成一张显示一张**:回主线程只刷这一张缩略图。
                # 不这么做的话 6 张要等全部跑完才出现(用户反馈「按了没反应」),
                # 整表 reload 又会把已出的图闪掉重来。
                _on_shot_ready(n)
            return {"done": done_n, "total": total}

        def done_cb(tid, result, error):
            _set_busy((result or {}).get("done", 0), False)   # 先解除等待态
            if error:
                err(str(error)[:280])
                return
            st = result or {}
            if st.get("done", 0) >= st.get("total", 1):
                ok(tr("首帧生成完成 {n} 张").format(n=st.get("done", 0)))
            else:
                err(tr("首帧完成 {ok}/{total},失败的可在对应分镜单独重绘")
                    .format(ok=st.get("done", 0), total=st.get("total", 0)))

        TASKMGR.submit("clone_redraw_all", job, done_cb, drama_id=self.drama_id,
                       episode_id=self._clone_episode_id())

    def _shot_video(self, n: int):
        from ..pipeline import video_clone
        def job(tid):
            return str(video_clone.generate_shot_video(self.drama_id, n, "720p"))
        def done(tid, result, error):
            if error:
                err("AI")
            self.reload()
        TASKMGR.submit("clone_video", job, done, drama_id=self.drama_id,
                       episode_id=self._clone_episode_id())

    def _merge(self):
        from ..pipeline import video_clone
        def job(tid):
            return str(video_clone.merge_clone(self.drama_id))
        def done(tid, result, error):
            if error:
                err(tr("merge_now"))
            else:
                import os
                os.startfile(result)  # noqa
        TASKMGR.submit("clone_merge", job, done, drama_id=self.drama_id,
                       episode_id=self._clone_episode_id())
