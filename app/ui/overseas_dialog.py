"""「海外题材改写」弹窗。

把中文原文改成目标平台(GoodNovel / Dreame / Webnovel)的英文短篇网文,
四步都在这个弹窗里看得见:**诊断 → 术语表 → 改写 → 质检**。

三件必须做对的事:
1. **不覆盖中文原稿** —— 改写稿只显示在「改写结果」页,原稿一个字都不动。
2. **术语表可人工编辑** —— 这是防「同一人名前后不一致」的唯一有效手段
   (上下文窗口有限,模型自己记不住 200 万字的人名一致性)。
3. **线程纪律** —— worker 线程里绝不碰 Qt 控件:所有控件值在主线程先快照成
   普通变量再传进 worker;完成回调经 TASKMGR 的 queued 信号回到主线程,
   可以安全更新 UI。
"""
from __future__ import annotations

import contextlib

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core import db
from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from ..core.theme import SLATE_FORM_QSS
from . import widgets as W
from .braille import WaitingButton
from .toast import err, info, ok, warn

# 四档模式:全翻译(只译不改,用户手选) + 改写三档。标签走 i18n 的
# overseas_level_T / _A / _B / _C;诊断只建议 A/B/C,T 不接受诊断建议。
LEVELS = ("T", "A", "B", "C")
_DEFAULT_LEVEL_IDX = LEVELS.index("B")


class OverseasDialog(QDialog):
    """海外题材改写。"""

    # worker 线程汇报阶段进度 → 状态行(红框处)。直连 setText 会跨线程碰控件,
    # 走信号经 queued connection 回主线程才是安全路径(线程纪律)。
    stage_sig = Signal(str)

    def __init__(self, parent=None, *, drama_id: int = 0,
                 episode_id: int | None = None,
                 text_config_id: int | None = None,
                 project_id: int = 0):
        super().__init__(parent)
        self.setWindowTitle(tr("overseas_dialog_title"))
        self.setStyleSheet(SLATE_FORM_QSS)
        self.resize(1120, 820)
        self._drama_id = drama_id
        self._episode_id = episode_id
        self._config_id = text_config_id
        # 从启动台「海外改写书」卡片进入:定位到该 project,
        # 打开即落「已保存章节」页(查看/导出的主场景)
        self._open_to_saved = bool(project_id)
        self._glossary: dict[str, str] = {}
        self._issues: list = []
        self._level = "B"
        self._zh_source = ""
        self._project_id = project_id or 0

        root = QVBoxLayout(self)

        # ── 头部 ──
        # **不要在这里加自定义关闭按钮**:本对话框走原生标题栏(Windows 自带 X),
        # 头部再加一个 X 就是右上角两个关闭按钮 —— 实测被用户当成「多了一个按钮」。
        head = QHBoxLayout()
        head.addWidget(W.icon_label("globe", 20))
        head.addWidget(W.h2(tr("overseas_dialog_title")))
        head.addStretch(1)
        root.addLayout(head)
        root.addWidget(W.muted(tr("overseas_dialog_desc")))

        # ── 中文原文 ──
        root.addWidget(QLabel(tr("overseas_source")))
        self.source_edit = QPlainTextEdit()
        self.source_edit.setPlaceholderText(tr("overseas_source_ph"))
        self.source_edit.setMinimumHeight(120)
        root.addWidget(self.source_edit)

        # ── 西化书名 ──
        # 诊断按平台 title_style 起的目标语言书名(不直译);用户改过就不再覆盖
        # (重诊断也不许把用户定的书名顶掉),改写时随 project 落库。
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel(tr("overseas_title")))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText(tr("overseas_title_ph"))
        self.title_edit.setMinimumWidth(280)
        title_row.addWidget(self.title_edit, 1)
        root.addLayout(title_row)
        self._title_dirty = False
        self._title_filling = False

        def _mark_title_dirty():
            if not self._title_filling:
                self._title_dirty = True

        self.title_edit.textChanged.connect(_mark_title_dirty)

        # ── 章节行:第几章 + 目标语言章名 ──
        # 章号自动按「重改本集沿用 / 新章 max+1」预填,可手改(粘贴流自己编号);
        # 章名留空 = 改写完按**改写稿**内容自动起(目标语言),填了就以用户的为准。
        ch_row = QHBoxLayout()
        ch_row.addWidget(QLabel(tr("overseas_chapter_no")))
        self.ch_no_edit = QLineEdit()
        self.ch_no_edit.setFixedWidth(56)
        self.ch_no_edit.setToolTip(tr("overseas_chapter_no_tip"))
        ch_row.addWidget(self.ch_no_edit)
        ch_row.addWidget(QLabel(tr("overseas_chapter_name")))
        self.ch_name_edit = QLineEdit()
        self.ch_name_edit.setPlaceholderText(tr("overseas_chapter_name_ph"))
        ch_row.addWidget(self.ch_name_edit, 1)
        root.addLayout(ch_row)
        self._ch_name_filling = False
        # 「将关联到」指示(用户问:第二章翻译要关联到哪一篇?)—— 关联键 =
        # 源书 + 平台 + 品类 + 语言,此前全在幕后,界面上看不到第二章会挂到哪本
        self.link_lab = W.muted("")
        root.addWidget(self.link_lab)
        # 章号预填延到 __init__ 尾部:platform/lang 下拉建在参数行(本章节行之后),
        # 这里就刷新会撞「控件不存在」(同 lang_note 的老坑)
        self._auto_ch_no = ""

        # ── 参数行 ──
        row = QHBoxLayout()
        row.setSpacing(10)
        self.use_ep_btn = QPushButton(tr("overseas_use_episode"))
        W.set_icon(self.use_ep_btn, "doc")
        # 与「开始改写」的关系(用户疑问 2026-10-24):本按钮只管装填输入,
        # 改写只看原文框当前内容 —— 从集工作台打开时本集正文已自动填入。
        self.use_ep_btn.setToolTip(tr("overseas_use_episode_tip"))
        self.use_ep_btn.clicked.connect(self._use_episode)
        row.addWidget(self.use_ep_btn)

        row.addWidget(QLabel(tr("overseas_platform")))
        self.platform_combo = QComboBox()
        self._fill_combo(self.platform_combo, self._platform_items())
        row.addWidget(self.platform_combo)

        row.addWidget(QLabel(tr("overseas_category")))
        self.category_combo = QComboBox()
        self._fill_combo(self.category_combo, self._category_items())
        row.addWidget(self.category_combo)

        row.addWidget(QLabel(tr("overseas_level")))
        self.level_combo = QComboBox()
        for lv in LEVELS:
            self.level_combo.addItem(f"{lv} · {tr('overseas_level_' + lv)}", lv)
        self.level_combo.setCurrentIndex(_DEFAULT_LEVEL_IDX)
        row.addWidget(self.level_combo)

        # 目标语言。**默认取项目设置里的「内容语言」** —— 正文语言和目标语言
        # 本来就不该是两个独立选择,绝大多数情况是同一个值;下拉只是允许本次覆盖。
        #
        # lang_note 必须先建好:setCurrentIndex 会立刻触发 currentIndexChanged,
        # 顺序颠倒就是「setVisible 之前 widget 还不存在」的 AttributeError。
        self.lang_note = W.muted("")
        self.lang_note.setVisible(False)
        row.addWidget(QLabel(tr("overseas_target_lang")))
        self.lang_combo = QComboBox()
        self._fill_combo(self.lang_combo, self._language_items())
        self.lang_combo.currentIndexChanged.connect(lambda _i: self._sync_lang_note())
        self.lang_combo.setToolTip(tr("overseas_lang_hint"))
        row.addWidget(self.lang_combo)
        row.addStretch(1)
        root.addLayout(row)
        root.addWidget(self.lang_note)

        # ── 操作行 ──
        act = QHBoxLayout()
        self.diag_btn = WaitingButton(tr("overseas_diagnose"))
        W.set_icon(self.diag_btn, "search")
        self.diag_btn.clicked.connect(self._on_diagnose)
        act.addWidget(self.diag_btn)
        self.rw_btn = WaitingButton(tr("overseas_rewrite"), primary=True)
        W.set_icon(self.rw_btn, "globe")
        self.rw_btn.clicked.connect(self._on_rewrite)
        act.addWidget(self.rw_btn)
        # 整书生成(用户工作流:书写完 → 一次定好书级设定 → 逐章自动改写)
        self.batch_btn = WaitingButton(tr("overseas_batch"), primary=True)
        W.set_icon(self.batch_btn, "book")
        self.batch_btn.setToolTip(tr("overseas_batch_tip"))
        self.batch_btn.clicked.connect(self._on_batch)
        act.addWidget(self.batch_btn)
        self.status_lab = QLabel("")
        self.status_lab.setStyleSheet("color:#8a9099;")
        self.stage_sig.connect(self._on_stage)
        act.addWidget(self.status_lab)
        # 已用时长:推理型模型(如 MiniMax-M3)一次大 JSON 可能跑 5-10 分钟,
        # 不显示流逝时间的话用户只能对着静态「诊断中…」干等(实测 9 分半完成
        # 的一次诊断,期间界面零反馈)。秒级刷新,worker 侧 stage 经信号更新基文案。
        self._stage_base = ""
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._elapsed_start = 0.0
        act.addStretch(1)
        root.addLayout(act)

        # ── 结果页 ──
        self.tabs = QTabWidget()
        self.diag_view = QTextEdit()
        self.diag_view.setReadOnly(True)
        self.tabs.addTab(self.diag_view, tr("overseas_tab_diag"))

        self.glossary_table = QTableWidget(0, 2)
        self.glossary_table.setHorizontalHeaderLabels(["中文", "English"])
        self.glossary_table.horizontalHeader().setStretchLastSection(True)
        self.glossary_table.verticalHeader().setVisible(False)
        self.glossary_table.setToolTip(tr("overseas_glossary_hint"))
        self.tabs.addTab(self.glossary_table, tr("overseas_tab_glossary"))

        self.zh_view = QTextEdit()
        self.zh_view.setReadOnly(True)
        self.en_view = QTextEdit()
        self.en_view.setReadOnly(True)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.zh_view)
        split.addWidget(self.en_view)
        self.tabs.addTab(split, tr("overseas_tab_result"))

        self.qc_table = QTableWidget(0, 3)
        self.qc_table.setHorizontalHeaderLabels(["规则", "级别", "说明"])
        self.qc_table.horizontalHeader().setStretchLastSection(True)
        self.qc_table.verticalHeader().setVisible(False)
        self.qc_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabs.addTab(self.qc_table, tr("overseas_tab_qc"))

        # ── 已保存章节:关窗后译文的「再入口」+ 整书导出 ──
        # 译文一直落 overseas_chapter 表,但此前没有任何界面能看到它 ——
        # 用户改完关窗就"找不到译文了"(2026-10-25 「翻译的保存了吗」的由来)。
        saved_host = QWidget()
        sv = QVBoxLayout(saved_host)
        sv.setContentsMargins(0, 6, 0, 0)
        self.saved_table = QTableWidget(0, 4)
        self.saved_table.setHorizontalHeaderLabels(
            [tr("overseas_chapter_no"), tr("overseas_chapter_name"),
             "Words", tr("saved_at_label")])
        self.saved_table.horizontalHeader().setStretchLastSection(True)
        self.saved_table.verticalHeader().setVisible(False)
        self.saved_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.saved_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.saved_table.doubleClicked.connect(lambda _i: self._load_saved_chapter())
        sv.addWidget(self.saved_table, 1)
        sv_row = QHBoxLayout()
        self.load_saved_btn = QPushButton(tr("overseas_saved_load"))
        self.load_saved_btn.clicked.connect(self._load_saved_chapter)
        sv_row.addWidget(self.load_saved_btn)
        self.regen_btn = QPushButton("⟳ " + tr("overseas_saved_regen"))
        self.regen_btn.setToolTip(tr("overseas_saved_regen_tip"))
        self.regen_btn.clicked.connect(self._regen_saved)
        sv_row.addWidget(self.regen_btn)
        self.del_btn = QPushButton("✕ " + tr("overseas_saved_delete"))
        self.del_btn.setToolTip(tr("overseas_saved_delete_tip"))
        self.del_btn.clicked.connect(self._delete_saved)
        sv_row.addWidget(self.del_btn)
        self.export_btn = QPushButton("↓ " + tr("overseas_saved_export"))
        self.export_btn.setToolTip(tr("overseas_saved_export_tip"))
        self.export_btn.clicked.connect(self._export_saved)
        sv_row.addWidget(self.export_btn)
        sv_row.addStretch(1)
        sv.addLayout(sv_row)
        self.tabs.addTab(saved_host, tr("overseas_tab_saved"))
        root.addWidget(self.tabs, 1)

        root.addWidget(W.muted(tr("overseas_rules_note")))

        # 所有控件建完之后再定目标语言默认值:`_sync_lang_note` 会连带刷新
        # 术语表表头,而 glossary_table / lang_note 都排在参数行之后 ——
        # 提前调用就是「widget 还不存在」的 AttributeError。
        self._select_project_language()
        # 参数变化(平台/品类/语言)会换关联链:关联指示/章号/已保存页都要跟着重算
        for combo in (self.platform_combo, self.category_combo, self.lang_combo):
            combo.currentIndexChanged.connect(
                lambda _i: (self._refresh_link(), self._load_stored_title(),
                            self._load_stored_diag(),
                            self._refresh_chapter_no(), self._refresh_saved()))
        self._refresh_link()
        self._load_stored_title()
        self._load_stored_diag()
        self._refresh_chapter_no()
        self._refresh_saved()
        if self._open_to_saved:
            self.tabs.setCurrentIndex(self.tabs.count() - 1)   # 已保存章节页

    def _refresh_chapter_no(self) -> None:
        """预填章号:重改本集沿用原号、新章 = project max+1(没有 project 就是 1)。
        只在用户没手改过时刷新 —— 手改的章号是用户拍板,不许顶掉。"""
        if (self.ch_no_edit.text().strip() and self.ch_no_edit.text() != self._auto_ch_no):
            return
        from ..pipeline import overseas
        pid = (self._project_id or overseas.find_project(
            self._drama_id, *self._platform_category_lang()))
        no = overseas.next_chapter_no(pid, self._episode_id) if pid else 1
        self._auto_ch_no = str(no)
        self.ch_no_edit.setText(self._auto_ch_no)

    def _on_stage(self, msg: str) -> None:
        """worker 阶段上报:记基文案 + 启动已用计时(有文案就在计时)。"""
        self._stage_base = msg
        self.status_lab.setText(msg)
        import time as _time
        if not self._elapsed_start:
            self._elapsed_start = _time.monotonic()
            self._elapsed_timer.start()

    def _tick_elapsed(self) -> None:
        if not self._elapsed_start:
            return
        import time as _time
        secs = int(_time.monotonic() - self._elapsed_start)
        self.status_lab.setText(f"{self._stage_base}({secs // 60}分{secs % 60:02d}秒)")

    def _stop_elapsed(self) -> None:
        self._elapsed_timer.stop()
        self._elapsed_start = 0.0

    def _refresh_saved(self) -> None:
        """「已保存章节」页:列当前 project(同平台/品类/语言)的全部改写稿。

        刷新前先自愈坏行(空章/同集重复)—— 软件自动修,坏章所在集按未完成
        对待,下次生成自动补,不需要人工清理(用户要求 2026-10-25)。"""
        from ..pipeline import overseas
        self.saved_table.setRowCount(0)
        pid = (self._project_id or overseas.find_project(
            self._drama_id, *self._platform_category_lang()))
        if not pid:
            return
        with contextlib.suppress(Exception):
            overseas.cleanup_empty_chapters(pid)
        self._saved_pid = pid
        for ch in overseas.list_chapters(pid):
            r = self.saved_table.rowCount()
            self.saved_table.insertRow(r)
            self.saved_table.setItem(r, 0, QTableWidgetItem(str(ch["chapter_no"])))
            self.saved_table.setItem(r, 1, QTableWidgetItem(ch["title"] or ""))
            self.saved_table.setItem(r, 2, QTableWidgetItem(str(ch["words"] or 0)))
            self.saved_table.setItem(r, 3, QTableWidgetItem(str(ch["created_at"] or "")[:16]))
            # 行数据带 chapter 内容,载入时不用回库
            self.saved_table.item(r, 0).setData(Qt.UserRole, dict(ch))

    def _load_saved_chapter(self) -> None:
        """双击/按钮:把选中的已保存章节回显到「改写结果」页(中英对照)。"""
        row = self.saved_table.currentRow()
        if row < 0:
            info(tr("overseas_saved_pick_first"))
            return
        ch = self.saved_table.item(row, 0).data(Qt.UserRole) or {}
        en = ch.get("content") or ""
        zh = ""
        ep_id = ch.get("episode_id")
        if ep_id:
            ep = db.q1("SELECT content FROM episodes WHERE id=?", (ep_id,))
            zh = (ep["content"] if ep else "") or ""
        self.zh_view.setPlainText(zh)
        self.en_view.setPlainText(en)
        self.tabs.setCurrentWidget(self.tabs.widget(2))     # 改写结果页

    def _selected_saved(self) -> dict | None:
        row = self.saved_table.currentRow()
        if row < 0:
            info(tr("overseas_saved_pick_first"))
            return None
        return self.saved_table.item(row, 0).data(Qt.UserRole) or None

    def _delete_saved(self) -> None:
        """删除所选章:中链删除会断链 —— 后续章被锁(先补洞才能再生成)。"""
        from ..pipeline import overseas
        from .confirm import ask
        ch = self._selected_saved()
        if not ch:
            return
        if not ask(self, tr("overseas_saved_delete"),
                   tr("overseas_saved_delete_confirm").format(
                       ch.get("chapter_no"), ch.get("title") or ""),
                   danger=True):
            return
        overseas.delete_chapter(int(ch["id"]))
        ok(tr("overseas_saved_deleted"))
        self._refresh_link()
        self._refresh_chapter_no()
        self._refresh_saved()

    def _regen_saved(self) -> None:
        """重新生成所选章:沿用原章号,链上更前的章必须连续(洞则拒绝)。"""
        from ..pipeline import overseas
        ch = self._selected_saved()
        if not ch:
            return
        ep_id = ch.get("episode_id")
        if not ep_id:
            err(tr("overseas_saved_regen_noep"))
            return
        snap = self._snapshot()
        self.regen_btn.busy(tr("overseas_saved_regen"))
        self._stop_elapsed()
        self._on_stage(tr("overseas_stage_read"))

        def job(tid):
            return overseas.regenerate_chapter(
                project_id=int(ch["project_id"]), episode_id=int(ep_id),
                chapter_no=int(ch["chapter_no"]),
                platform=snap["platform"], category=snap["category"],
                level=snap["level"], target_lang=snap["target_lang"],
                title="", text_config_id=snap["config_id"])

        def done(tid, result, error):
            self.regen_btn.idle()
            self._stop_elapsed()
            if error:
                err(str(error)[:250])
                return
            r = result or {}
            self.zh_view.setPlainText("")
            self.en_view.setPlainText(r.get("content") or "")
            self.tabs.setCurrentIndex(2)
            ok(tr("overseas_saved_regen_done").format(r.get("chapter_no")))
            self._refresh_link()
            self._refresh_saved()

        TASKMGR.submit("overseas_rewrite", job, done, episode_id=ep_id)

    def _export_saved(self) -> None:
        """整书导出 TXT:西化书名 + 逐章(章名 + 正文),UTF-8。"""
        from ..pipeline import overseas
        pid = getattr(self, "_saved_pid", 0) or (
            self._project_id or overseas.find_project(
                self._drama_id, *self._platform_category_lang()))
        chapters = overseas.list_chapters(pid) if pid else []
        if not chapters:
            info(tr("overseas_saved_pick_first"))
            return
        proj = db.q1("SELECT title_target FROM overseas_project WHERE id=?", (pid,))
        book = (proj["title_target"] if proj else "") or "Rewritten Book"
        default = book.replace("/", "_")[:60] + ".txt"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("overseas_saved_export"), default, "Text files (*.txt);;All files (*)")
        if not path:
            return
        out = [f"# {book}", ""]
        for ch in chapters:
            out.append(f"## Chapter {ch['chapter_no']}: {ch['title'] or ''}")
            out.append("")
            out.append((ch["content"] or "").strip())
            out.append("")
        try:
            from pathlib import Path as _P
            _P(path).write_text("\n".join(out), encoding="utf-8")
            ok(tr("overseas_saved_exported").format(
                n=len(chapters), path=path))
        except OSError as exc:
            err(f"写入失败:{exc}")

    def _load_stored_title(self) -> None:
        """打开对话框/切换关联链时回读**已定书名**(用户没手改过才填)。

        第二章进来书名行此前是空的 —— 看不到已定书名不说,重诊断一次
        还会被新建议顶掉(书改到一半换名)。书名是书级资产:定了就不动,
        想换就手改(手改后任何自动填充都不再覆盖)。
        """
        if self._title_dirty and self.title_edit.text().strip():
            return
        from ..pipeline import overseas
        pid = (self._project_id or overseas.find_project(
            self._drama_id, *self._platform_category_lang()))
        if not pid:
            return
        row = db.q1("SELECT title_target FROM overseas_project WHERE id=?", (pid,))
        stored = (row["title_target"] if row else "") or ""
        self._title_filling = True
        self.title_edit.setText(stored)
        self._title_filling = False
        if stored:
            self.title_edit.setToolTip(tr("overseas_title_locked_tip"))

    def _load_stored_diag(self) -> None:
        """回读已存诊断(第 2 章起不再白跑一次 45s~10min 的诊断)。

        诊断结果本就落库(diag_json)—— 五维/问题清单/建议级别都是**书级资产**;
        但此前只在诊断当次会话里用(内存变量),重开对话框「诊断发现」就没了,
        第 2 章改写丢失硬约束。本会话跑过新诊断则不动(内存优先)。
        """
        if self._issues:
            return
        from ..pipeline import overseas
        pid = (self._project_id or overseas.find_project(
            self._drama_id, *self._platform_category_lang()))
        if not pid:
            return
        d = db.q1("SELECT diag_json FROM overseas_project WHERE id=?", (pid,))
        diag = db.jload(d["diag_json"], {}) if d else {}
        if not isinstance(diag, dict) or not (diag.get("issues") or diag.get("diagnosis")):
            return
        self._issues = diag.get("issues") or []
        self._level = diag.get("level") or self._level
        self._fill_diag(diag)             # 诊断报告页同时回显,看得到存了什么

    def _refresh_link(self) -> None:
        """「将关联到」:按当前四键(源书+平台+品类+语言)显示本次改写会挂到哪本
        改写书 —— 已有则报书名与章数(第二章就是接它),没有则明示将新建。"""
        from ..pipeline import overseas
        pid = (self._project_id or overseas.find_project(
            self._drama_id, *self._platform_category_lang()))
        if pid:
            row = db.q1(
                "SELECT p.title_target, COUNT(c.id) n FROM overseas_project p"
                " LEFT JOIN overseas_chapter c ON c.project_id = p.id"
                " WHERE p.id=? GROUP BY p.id", (pid,))
            n = int(row["n"] or 0) if row else 0
            self.link_lab.setText(tr("overseas_link_to").format(
                book=(row["title_target"] if row else "") or tr("overseas_untitled_book"),
                n=n))
        else:
            self.link_lab.setText(tr("overseas_link_new"))

    def _platform_category_lang(self) -> tuple:
        """当前选中的 (platform, category, target_lang) —— find_project 的键。"""
        return (self.platform_combo.currentData() or "",
                self.category_combo.currentData() or "",
                self.lang_combo.currentData() or "en-US")

    # ------------------------------------------------------------ 组合框

    @staticmethod
    def _fill_combo(combo: QComboBox, items: list[tuple[str, str]]) -> None:
        for label, data in items:
            combo.addItem(label, data)

    def _platform_items(self) -> list[tuple[str, str]]:
        try:
            from ..pipeline import overseas_rules
            return [(f"{p.get('name', p['id'])}", p["id"])
                    for p in overseas_rules.list_platforms()]
        except Exception:  # noqa: BLE001
            return []

    def _category_items(self) -> list[tuple[str, str]]:
        try:
            from ..pipeline import overseas_rules
            return [(f"{c.get('name_zh') or c.get('name', c['id'])}", c["id"])
                    for c in overseas_rules.list_categories()]
        except Exception:  # noqa: BLE001
            return []

    def _language_items(self) -> list[tuple[str, str]]:
        """目标语言下拉。骨架包**带角标如实标注**,不让用户以为质检跑全了。"""
        try:
            from ..pipeline import overseas_rules
            items = []
            for l in overseas_rules.list_languages():
                name = f"{l.get('name_zh') or l.get('name', l['id'])} ({l['id']})"
                if l.get("depth") == "skeleton":
                    name += " · " + tr("overseas_lang_skeleton")
                items.append((name, l["id"]))
            return items
        except Exception:  # noqa: BLE001
            return []

    def _select_project_language(self) -> None:
        """默认选项目内容语言。

        项目语言不在语言包列表里时(中文/日文项目 —— 它们的语言本身就不是
        「出海目标语言」)必须回退到 **en-US 而不是下拉的第一项**:列表是按 id
        字母序排的,第一项是 ar-SA,让一个中文项目默认选中阿拉伯语毫无道理。
        """
        lang = ""
        try:
            from ..core import config
            lang = config.resolve_content_language(self._drama_id) or ""
        except Exception:  # noqa: BLE001
            pass
        idx = self.lang_combo.findData(lang)
        if idx < 0:
            try:
                from ..pipeline import overseas_rules
                idx = self.lang_combo.findData(overseas_rules.DEFAULT_LANG)
            except Exception:  # noqa: BLE001
                idx = -1
        self.lang_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._sync_lang_note()

    def _sync_lang_note(self) -> None:
        """把规则包深度写在界面上 —— 骨架包只跑语言无关的质检项。"""
        lid = self.lang_combo.currentData() or ""
        try:
            from ..pipeline import overseas_rules
            depth = next((l.get("depth") for l in overseas_rules.list_languages()
                          if l.get("id") == lid), None)
        except Exception:  # noqa: BLE001
            depth = None
        if depth == "skeleton":
            self.lang_note.setText(tr("overseas_lang_skeleton_note"))
            self.lang_note.setVisible(True)
        else:
            self.lang_note.setVisible(False)
        self._sync_glossary_header()

    def _sync_glossary_header(self) -> None:
        """术语表表头跟着目标语言走 —— 写死「中文 / English」时法语项目会误导用户。"""
        lid = self.lang_combo.currentData() or "en-US"
        try:
            from ..pipeline import overseas_rules
            name = overseas_rules.get_language(lid).get("name", lid)
        except Exception:  # noqa: BLE001
            name = lid
        self.glossary_table.setHorizontalHeaderLabels([tr("overseas_source"), str(name)])

    # ------------------------------------------------------------ 输入

    def set_source(self, text: str) -> None:
        self.source_edit.setPlainText(text or "")
        self._zh_source = text or ""

    def _use_episode(self) -> None:
        """从库里取本集正文/剧本填进原文框(用户在编辑框里改过的内容不覆盖,
        只在原文框为空时填)。"""
        if self.source_edit.toPlainText().strip():
            warn(tr("overseas_reload_blocked"))
            return
        if not self._episode_id:
            warn(tr("overseas_no_project"))
            return
        from ..core import db
        row = db.q1("SELECT content, script_content FROM episodes WHERE id=?",
                    (self._episode_id,))
        if not row:
            warn(tr("overseas_no_project"))
            return
        text = (row.get("content") or "").strip() or (row.get("script_content") or "").strip()
        if not text:
            warn(tr("overseas_no_source"))
            return
        self.set_source(text)
        self._refresh_chapter_no()

    # ------------------------------------------------------------ 参数快照

    def _snapshot(self) -> dict:
        """**主线程**里把控件值快照成普通变量 —— worker 线程绝不能碰控件。"""
        return {
            "source": self.source_edit.toPlainText().strip(),
            "platform": self.platform_combo.currentData() or "",
            "category": self.category_combo.currentData() or "",
            "level": self.level_combo.currentData() or "B",
            "target_lang": self.lang_combo.currentData() or "en-US",
            "config_id": self._config_id,
        }

    # ------------------------------------------------------------ 诊断

    def _on_diagnose(self) -> None:
        from ..pipeline import overseas
        snap = self._snapshot()
        if not snap["source"]:
            warn(tr("overseas_no_source"))
            return
        if not snap["platform"] or not snap["category"]:
            warn(tr("overseas_rules_note"))
            return
        self.diag_btn.busy(tr("overseas_diag_running"))
        self._stop_elapsed()
        # 基文案在主线程就设**详细阶段文案**:此前首段依赖 worker 的跨线程
        # stage_sig 送达,实测生产环境偶发丢失(状态行只剩「诊断中(N分N秒)」,
        # 用户看不到进行到哪)。worker 的 emit 仍保留(后续阶段用它细化)。
        self._on_stage(tr("overseas_stage_diag"))
        # 书名快照(主线程取,worker 不碰控件):给了书名诊断才会出西化书名;
        # 用户改过书名就不采纳本次模型建议(重诊断不许顶掉用户定的)
        title_dirty = self._title_dirty
        title_now = self.title_edit.text().strip()   # 快照:worker 不碰 Qt 控件
        book_title = ""
        if self._drama_id:
            d = db.q1("SELECT title FROM dramas WHERE id=?", (self._drama_id,))
            book_title = (d["title"] if d else "") or ""

        def job(tid):
            self.stage_sig.emit(tr("overseas_stage_diag"))
            res = overseas.diagnose(
                source=snap["source"], platform=snap["platform"],
                category=snap["category"], level=snap["level"],
                target_lang=snap["target_lang"], book_title=book_title,
                text_config_id=snap["config_id"])
            # 诊断完就落库:以前诊断结果只存在内存里,关窗即丢,
            # overseas_project 表的 target_lang 列也从来没被写过。
            # **复用同书同参数的 project**(逐章诊断不再各开一个):术语表/章序
            # 的跨章连续性全挂在同一个 project 上,新建就把链断了。
            pid = overseas.find_project(self._drama_id, snap["platform"],
                                        snap["category"], snap["target_lang"])
            if pid:
                stored = db.jload(db.q1(
                    "SELECT glossary_json FROM overseas_project WHERE id=?",
                    (pid,))["glossary_json"], {}) or {}
                # 已落库的旧术语优先:它们锁的是前面章节的译名,本章诊断的新抽
                # 不能覆盖(只能补充) —— 否则重诊断一次前几章的译名全变。
                merged = {**{k: v for k, v in (res.get("glossary") or {}).items()
                             if k and v}, **{k: v for k, v in stored.items()
                                             if k and v}}
                res["glossary"] = merged
                # 书名是**书级资产,定了就不换**(第二章重诊断不得给书改名):
                # 用户手改 > 已定书名 > 本次建议(前两者都空才采纳新建议)
                stored_title = db.q1(
                    "SELECT title_target FROM overseas_project WHERE id=?",
                    (pid,))["title_target"] or ""
                res["title_target"] = (title_now if title_dirty and title_now
                                       else stored_title
                                       or res.get("title_target") or "")
                res["_title_kept"] = bool(stored_title) and not (title_dirty and title_now)
                overseas.update_project(
                    pid, level=res.get("level") or snap["level"],
                    source_text=snap["source"],
                    glossary=merged, diag=res,
                    title_target=res["title_target"])
                res["project_id"] = pid
            else:
                res["project_id"] = overseas.save_project(
                    drama_id=self._drama_id, episode_id=self._episode_id,
                    platform=snap["platform"], category=snap["category"],
                    level=res.get("level") or snap["level"],
                    source_text=snap["source"], target_lang=snap["target_lang"],
                    glossary=res.get("glossary"), diag=res,
                    title_target=(title_now if title_dirty and title_now
                                  else res.get("title_target") or ""))
            return res

        def done(tid, result, error):
            self.diag_btn.idle()
            self._stop_elapsed()
            if error:
                self.status_lab.setText("")
                err(f"{tr('overseas_diagnose')}: {str(error)[:200]}")
                return
            res = result or {}
            self._level = res.get("level") or snap["level"]
            self._issues = res.get("issues") or []
            self._glossary = res.get("glossary") or {}
            self._project_id = res.get("project_id") or 0
            self._refresh_link()
            self._fill_diag(res)
            self._fill_glossary(self._glossary)
            # 西化书名回填:用户没改过才填;沿用已定书名(res._title_kept)时
            # 不展示备选/理由 —— 那是**上一章诊断时**的建议,对本书已不适用
            if not title_dirty and res.get("title_target"):
                self._title_filling = True
                self.title_edit.setText(res["title_target"])
                self._title_filling = False
                if not res.get("_title_kept"):
                    alts = res.get("title_alts") or []
                    tip = res.get("title_reason") or ""
                    if alts:
                        tip = (tr("overseas_title_alts") + ":" + " / ".join(alts)
                               + ("\n" + tip if tip else ""))
                    if tip:
                        self.title_edit.setToolTip(tip)
            self.tabs.setCurrentIndex(0)
            n = len(self._issues)
            self.status_lab.setText(
                tr("overseas_diag_done").format(level=self._level, n=n))
            ok(tr("overseas_diag_done").format(level=self._level, n=n))

        TASKMGR.submit("overseas_diag", job, done, episode_id=self._episode_id)

    def _fill_diag(self, res: dict) -> None:
        rows = ["<h3>改写级别建议</h3>"]
        rows.append(f"<p><b>{res.get('level', 'B')}</b> — "
                    f"{res.get('level_reason', '')}</p>")
        rows.append("<h3>五维诊断</h3><table cellpadding='4' cellspacing='0' "
                    "border='1' width='100%'>")
        for key, label in (("setting", "设定"), ("structure", "结构"),
                            ("pacing", "节奏"), ("language", "语言"),
                            ("compliance", "合规")):
            item = (res.get("diagnosis") or {}).get(key) or {}
            score = item.get("score", 0)
            rows.append(f"<tr><td width='60'><b>{label}</b></td>"
                        f"<td width='40'>{score}/5</td>"
                        f"<td>{item.get('notes', '')}</td></tr>")
        rows.append("</table>")
        issues = res.get("issues") or []
        if issues:
            rows.append("<h3>问题清单</h3><table cellpadding='4' cellspacing='0' "
                        "border='1' width='100%'>"
                        "<tr><th>类型</th><th>原文</th><th>怎么改</th></tr>")
            for it in issues:
                if not isinstance(it, dict):
                    continue
                rows.append(f"<tr><td>{it.get('type', '')}</td>"
                            f"<td>{it.get('quote', '')}</td>"
                            f"<td>{it.get('fix', '')}</td></tr>")
            rows.append("</table>")
        maps = res.get("culture_mappings") or []
        if maps:
            rows.append("<h3>文化映射</h3><table cellpadding='4' cellspacing='0' "
                        "border='1' width='100%'>"
                        "<tr><th>中式设定</th><th>目标设定</th><th>理由</th></tr>")
            for m in maps:
                if not isinstance(m, dict):
                    continue
                rows.append(f"<tr><td>{m.get('source', '')}</td>"
                            f"<td>{m.get('target', '')}</td>"
                            f"<td>{m.get('note', '')}</td></tr>")
            rows.append("</table>")
        self.diag_view.setHtml("".join(rows))

    def _fill_glossary(self, glossary: dict) -> None:
        self.glossary_table.setRowCount(0)
        for k, v in (glossary or {}).items():
            r = self.glossary_table.rowCount()
            self.glossary_table.insertRow(r)
            self.glossary_table.setItem(r, 0, QTableWidgetItem(str(k)))
            self.glossary_table.setItem(r, 1, QTableWidgetItem(str(v)))

    def _glossary_from_table(self) -> dict:
        out: dict[str, str] = {}
        for r in range(self.glossary_table.rowCount()):
            a = self.glossary_table.item(r, 0)
            b = self.glossary_table.item(r, 1)
            if a and b and a.text().strip() and b.text().strip():
                out[a.text().strip()] = b.text().strip()
        return out

    # ------------------------------------------------------------ 改写

    # ------------------------------------------------------------ 整书生成

    def _on_batch(self) -> None:
        from ..pipeline import overseas
        if not self._drama_id:
            warn(tr("overseas_batch_need_drama"))
            return
        if not db.q1("SELECT id FROM dramas WHERE id=?", (self._drama_id,)):
            warn(tr("overseas_batch_need_drama"))
            return
        snap = self._snapshot()
        # 书级设定一次定死:当前 书名/平台/品类/级别/语言 即本书的整书设定
        title_now = self.title_edit.text().strip()
        self.batch_btn.busy(tr("overseas_batch"))
        self._stop_elapsed()
        self._on_stage(tr("overseas_batch_running").format("0/?"))

        def job(tid):
            return overseas.batch_rewrite(
                drama_id=self._drama_id, platform=snap["platform"],
                category=snap["category"], level=snap["level"],
                target_lang=snap["target_lang"], title=title_now,
                text_config_id=snap["config_id"],
                on_stage=lambda pos: self.stage_sig.emit(
                    tr("overseas_batch_running").format(pos)))

        def done(tid, result, error):
            self.batch_btn.idle()
            self._stop_elapsed()
            if error:
                self.status_lab.setText("")
                err(f"{tr('overseas_batch')}: {str(error)[:200]}")
                return
            r = result or {}
            if r.get("failed_at"):
                msg = tr("overseas_batch_stopped").format(
                    r["failed_at"], str(r.get("error") or "")[:150])
                err(msg)
            else:
                msg = tr("overseas_batch_done").format(
                    done=r.get("done", 0), skipped=r.get("skipped", 0),
                    total=r.get("total", 0))
                ok(msg)
            self.status_lab.setText("")
            self._refresh_link()
            self._load_stored_title()
            self._refresh_chapter_no()
            self._refresh_saved()

        TASKMGR.submit("overseas_batch", job, done, drama_id=self._drama_id)

    def _on_rewrite(self) -> None:
        from ..pipeline import overseas
        snap = self._snapshot()
        if not snap["source"]:
            warn(tr("overseas_no_source"))
            return
        glossary = self._glossary_from_table() or self._glossary
        if not glossary:
            warn(tr("overseas_no_glossary"))
            return
        # 顺序红线(主线程先查,秒回错,不进 LLM 等待):上一章没改写,本章不许改 ——
        # 衔接锚是上一章改写稿,跳章必然断链。按 project 生效:西语链没走到这章,
        # 英文链改完了也不放行。
        pid = (self._project_id or overseas.find_project(
            self._drama_id, snap["platform"], snap["category"],
            snap["target_lang"]))
        try:
            overseas.assert_previous_rewritten(pid, self._episode_id)
        except RuntimeError as exc:
            err(str(exc))
            self.status_lab.setText("")
            return
        # 书名快照(主线程):改写时把界面书名随 project 落库,关窗重开不丢
        title_now = self.title_edit.text().strip()
        # 章号/章名快照:章号填了数字就以用户的为准(粘贴流自编号),
        # 否则走自动「重改沿用 / max+1」;章名留空 = 改写完按改写稿自动起
        ch_no_raw = self.ch_no_edit.text().strip()
        ch_no_user = int(ch_no_raw) if ch_no_raw.isdigit() and int(ch_no_raw) > 0 else None
        ch_name_now = self.ch_name_edit.text().strip()
        self.rw_btn.busy(tr("overseas_rewrite_running"))
        self._stop_elapsed()
        # 同诊断:首段基文案主线程直设,不赌跨线程信号
        self._on_stage(tr("overseas_stage_read"))

        def job(tid):
            # ── 跨章一致性三件事(逐章改写的「情节一致」全靠这里)──
            # 1) 复用同书同参数 project,把前面章节锁定的术语表读回来
            #    (术语表是 project 级资产,不是对话框实例变量 —— 关窗重开不能丢)
            self.stage_sig.emit(tr("overseas_stage_read"))
            pid = (self._project_id or overseas.find_project(
                self._drama_id, snap["platform"], snap["category"],
                snap["target_lang"]))
            had_project = bool(pid)
            if not pid:
                pid = overseas.save_project(
                    drama_id=self._drama_id, episode_id=self._episode_id,
                    platform=snap["platform"], category=snap["category"],
                    level=snap["level"], source_text=snap["source"],
                    target_lang=snap["target_lang"], glossary=glossary,
                    title_target=title_now)
                stored_title = title_now
            else:
                stored = db.jload(db.q1(
                    "SELECT glossary_json FROM overseas_project WHERE id=?",
                    (pid,))["glossary_json"], {}) or {}
                # 界面表值优先(用户改过表就是想让本次按改后的来),
                # 表里没有的旧词由落库值补上
                glossary_merged = {**stored, **glossary}
                glossary.clear()
                glossary.update(glossary_merged)
                # 2) 增量术语抽取:本章新出场专名当场锁译名(轻量调用,失败不阻塞)
                self.stage_sig.emit(tr("overseas_stage_terms"))
                new_terms = overseas.extract_new_terms(
                    snap["source"], glossary, target_lang=snap["target_lang"],
                    text_config_id=snap["config_id"])
                if new_terms:
                    glossary.update(new_terms)
                # 书名随改写落库:界面值优先(用户可能直接改了没诊断),
                # 界面空则保持库里的不动(关窗重开的连续性)
                fields = {"glossary": glossary}
                if title_now:
                    fields["title_target"] = title_now
                overseas.update_project(pid, **fields)
                stored_title = db.q1(
                    "SELECT title_target FROM overseas_project WHERE id=?",
                    (pid,))["title_target"] or ""
            # 3) 真实章号(重改本集沿用原号;新集 = max+1 —— 此前硬编码 1,
            #    多章全落「第 1 章」),再按「章号严格更小」取上一章改写稿结尾
            #    作衔接锚。重改第 1 章时没有上一章,锚为空(不能把后面的章当前章)。
            chapter_no = ch_no_user or overseas.next_chapter_no(pid, self._episode_id)
            # 单章改写前自愈:该集若残留空章/重复行,先清再落(否则会插出第二行)
            if had_project:
                overseas.cleanup_empty_chapters(pid)
                chapter_no = ch_no_user or overseas.next_chapter_no(pid, self._episode_id)
            prev_tail = overseas.chapter_tail(pid, chapter_no) if had_project else ""
            self.stage_sig.emit(tr("overseas_stage_writing").format(chapter_no))
            res = overseas.rewrite(
                source=snap["source"], platform=snap["platform"],
                category=snap["category"], level=snap["level"],
                glossary=glossary, issues=self._issues,
                target_lang=snap["target_lang"], prev_tail=prev_tail,
                text_config_id=snap["config_id"])
            self.stage_sig.emit(tr("overseas_stage_qc"))
            issues = overseas.check(
                res["content"], platform=snap["platform"],
                category=snap["category"], glossary=glossary,
                target_lang=snap["target_lang"], level=snap["level"])
            res["qc"] = issues
            res["project_id"] = pid
            res["chapter_no"] = chapter_no
            # 章名:用户填了就用;留空按改写稿自动起(目标语言,失败为空不阻塞)
            ch_title = ch_name_now
            if not ch_title:
                self.stage_sig.emit(tr("overseas_stage_title"))
                ch_title = overseas.generate_chapter_title(
                    res["content"], target_lang=snap["target_lang"],
                    text_config_id=snap["config_id"])
            res["chapter_title"] = ch_title
            self.stage_sig.emit(tr("overseas_stage_save"))
            res["chapter_id"] = overseas.save_chapter(
                project_id=pid, episode_id=self._episode_id,
                chapter_no=chapter_no, title=ch_title,
                content=res["content"], qc=[str(i) for i in issues])
            res["title_back"] = stored_title
            return res

        def done(tid, result, error):
            self.rw_btn.idle()
            self._stop_elapsed()
            if error:
                self.status_lab.setText("")
                err(f"{tr('overseas_rewrite')}: {str(error)[:200]}")
                return
            res = result or {}
            en = res.get("content") or ""
            self.zh_view.setPlainText(snap["source"])
            self.en_view.setPlainText(en)
            self.tabs.setCurrentIndex(2)
            self._fill_qc(res.get("qc") or [])
            self._project_id = res.get("project_id") or self._project_id
            self._refresh_link()
            # 术语表可能有增量新词,回填表格让用户看得见、可再改
            if res.get("glossary"):
                self._glossary = res["glossary"]
                self._fill_glossary(self._glossary)
            # 书名回填:界面原本空着(用户没诊断直接改写)且库里有 → 补显
            if not title_now and res.get("title_back"):
                self._title_filling = True
                self.title_edit.setText(res["title_back"])
                self._title_filling = False
            # 章名回填(用户留空才填自动起的);章号刷新到下一章(自动逻辑)
            if not ch_name_now and res.get("chapter_title"):
                self._ch_name_filling = True
                self.ch_name_edit.setText(res["chapter_title"])
                self._ch_name_filling = False
            if not ch_no_user:
                self._auto_ch_no = ""            # 清掉旧自动值,允许刷新
                self.ch_no_edit.setText("")
                self._refresh_chapter_no()
            self._refresh_saved()                # 新章落库,已保存页同步
            warns = sum(1 for i in (res.get("qc") or [])
                        if getattr(i, "severity", "") == "warn")
            msg = tr("overseas_rewrite_done").format(
                chapters=res.get("chapter_no") or 1, warns=warns)
            self.status_lab.setText(msg)
            ok(msg)

        # glossary 是可变 dict,worker 里就地 merge;done 里回填要看 worker 改后的值
        # —— 所以把最终术语表从 job 带回来(书名回读值 job 已放进 res.title_back)
        def job_with_glossary(tid):
            out = job(tid)
            out["glossary"] = dict(glossary)
            return out

        TASKMGR.submit("overseas_rewrite", job_with_glossary, done,
                       episode_id=self._episode_id)

    def _fill_qc(self, issues) -> None:
        self.qc_table.setRowCount(0)
        for it in issues:
            r = self.qc_table.rowCount()
            self.qc_table.insertRow(r)
            self.qc_table.setItem(r, 0, QTableWidgetItem(str(getattr(it, "rule", ""))))
            sev = getattr(it, "severity", "")
            self.qc_table.setItem(r, 1, QTableWidgetItem(
                "错误" if sev == "error" else "警告"))
            self.qc_table.setItem(r, 2, QTableWidgetItem(
                str(getattr(it, "message", ""))))
