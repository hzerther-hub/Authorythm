"""批量生成面板:三段式进度条 + 阶段显示 + 伏笔台账 + 审校明细。

对齐原版 episode.vue 未提交批次的批量面板:
  - 三段进度条(成功绿 / 失败红 / 进行中条纹动画)
  - 图例:百分比 / 进行中 n / 成功 n / 失败 n
  - 每章阶段(写正文/审校中/修复问题/卷段压缩)
  - 伏笔台账可交互勾选(乐观更新+失败回滚)
  - 审校问题明细(本地标记)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.i18n import tr
from . import widgets as W

STAGE_CN = {"writing": "写正文", "reviewing": "审校中", "repairing": "修复问题",
            "compressing": "卷段压缩", "splitting": "拆分分镜",
            "ledger": "状态台账", "jev_gate": "Jev 门控", "prose": "小说体改造"}


class _SegmentBar(QWidget):
    """三段式进度条:成功 / 失败 / 进行中。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self._ok = self._fail = self._run = 0
        self._total = 1

    def set_counts(self, ok: int, fail: int, running: int, total: int):
        self._ok, self._fail, self._run = ok, fail, running
        self._total = max(1, total)
        self.update()

    def paintEvent(self, ev):
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        h = self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e8eaf0"))
        p.drawRoundedRect(0, 0, w, h, 6, 6)
        x = 0.0
        for cnt, color in ((self._ok, "#16a34a"), (self._fail, "#dc2626")):
            seg = w * cnt / self._total
            if seg <= 0:
                continue
            p.setBrush(QColor(color))
            p.drawRoundedRect(int(x), 0, max(int(seg), 1), h, 6, 6)
            x += seg
        if self._run:
            seg = w * self._run / self._total
            p.setBrush(QColor("#f97316"))
            p.drawRoundedRect(int(x), 0, max(int(seg), 1), h, 6, 6)
        p.end()


class _BatchProgressDialog(QDialog):
    """批量生成进度面板(模态浮窗)。"""

    def __init__(self, parent, total: int, page=None):
        super().__init__(parent)
        self.page = page
        self.total = max(1, total)
        self.setWindowTitle(tr("批量生成小说"))
        self.resize(560, 480)
        # Director's Slate:批次进度 dialog 容器 + 标签统一 slate 字(mono caps),
        # 嵌入 _SegmentBar 的三段颜色(成功绿/失败红/进行中暗琥珀)
        self.setObjectName("batchDialog")
        self.setStyleSheet(
            "QDialog#batchDialog{background:#F5F4EF;}"
            "QPushButton{background:transparent; border:1px solid #DCDAD3;"
            "border-radius:3px; color:#6B727A;"
            "font-family:ui-monospace,Menlo,Consolas,monospace; font-size:10px;"
            "letter-spacing:0.5px; padding:0 12px; min-height:26px;}"
            "QPushButton:hover{border-color:#0E0F12; color:#0E0F12;}"
        )
        root = QVBoxLayout(self)

        self.bar = _SegmentBar()
        root.addWidget(self.bar)
        self.legend = W.muted("")
        root.addWidget(self.legend)
        self.stage_lab = W.muted("")
        root.addWidget(self.stage_lab)

        self.rows = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:1px solid rgba(128,128,128,40);border-radius:8px;}")
        inner = QWidget()
        inner.setLayout(self.rows)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        # 伏笔台账
        self.ledger_btn = QPushButton(tr("▾ 伏笔台账"))
        self.ledger_btn.setCheckable(True)
        self.ledger_btn.toggled.connect(self._toggle_ledger)
        root.addWidget(self.ledger_btn)
        self.ledger_box = QWidget()
        self.ledger_list = QVBoxLayout()
        self.ledger_box.setLayout(self.ledger_list)
        self.ledger_box.setVisible(False)
        root.addWidget(self.ledger_box)

        btns = QHBoxLayout()
        self.rewrite_btn = QPushButton(tr("↻ 重写已完成章节"))
        self.rewrite_btn.clicked.connect(lambda: page and page._rewrite_done_chapters())
        close = QPushButton(tr("close"))
        close.clicked.connect(self.accept)
        btns.addWidget(self.rewrite_btn)
        btns.addStretch(1)
        btns.addWidget(close)
        root.addLayout(btns)
        self._render_ledger()
        # on_progress 在工作线程里只改共享变量(跨线程碰 UI 会炸),这里用 1s 心跳把
        # page._batch_done 反映到进度条/阶段(对齐成片「拼接中」卡的心跳模式)
        import time as _time
        self._t0 = _time.time()          # 批量开始时刻
        self._chap_t0 = _time.time()     # 当前章开始时刻(done 变化时重置)
        self._last_done = -1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_progress)
        self._timer.start(1000)

    def _poll_progress(self):
        if not self.page:
            return
        import time as _time
        done = getattr(self.page, "_batch_done", 0)
        if done != getattr(self, "_last_done", done):
            self._chap_t0 = _time.time()     # 换章:本章计时重置
            self._last_done = done
        # 原来只在 done 非 0 时才刷新 → 第 1 章还没写完的那几分钟里
        # 窗内进度条/阶段/章节列表全是初始空值,看着像卡死。
        # 现在无条件刷新,并渲染章节列表(逐章一行:进行中 / 已完成 / 待写)。
        self.update_progress(done, self.total)
        self._refresh_chapter_rows()

    def _refresh_chapter_rows(self):
        """按当前进度重画章节行:每章一行,标注「已完成 / 进行中 / 待写」。

        之前 self.rows 建好后**没有任何代码往里填**,中间那块滚动区永远是
        空白(用户反馈"批量生成没有内容")。
        """
        if not self.page:
            return
        ids = list(getattr(self.page, "_batch_ids", []) or [])
        if not ids:
            return
        done = int(getattr(self.page, "_batch_done", 0) or 0)
        # 运行中章的实时阶段/轮次来自批量任务的 params(writing/reviewing/
        # repairing/jev_gate/ledger + stage_cycle),写章内部会持续更新。
        cur_stage, cur_cycle = "", 0
        try:
            import json as _json

            from ..core import db as _db2
            _row = _db2.q1("SELECT params FROM sys_task WHERE type='novel_batch' "
                           "AND status='processing' ORDER BY id DESC LIMIT 1")
            if _row:
                _pr = (_json.loads(_row["params"] or "{}")
                       if isinstance(_row["params"], str) else (_row["params"] or {}))
                cur_stage = str(_pr.get("stage") or "")
                cur_cycle = int(_pr.get("stage_cycle") or 0)
        except Exception:  # noqa: BLE001
            pass
        # 签名含阶段/轮次/节拍(÷3):阶段切换或轮播换词时才重建行,
        # 既让红框区显示**动态过程文字**,又不至于每秒闪烁。
        self._run_tick = getattr(self, "_run_tick", 0) + 1
        sig = (tuple(ids), done, cur_stage, cur_cycle, self._run_tick % 3)
        if getattr(self, "_rows_sig", None) == sig:
            return
        self._rows_sig = sig
        from ..core import db as _db
        while self.rows.count():
            it = self.rows.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        for i, ep_id in enumerate(ids):
            ep = _db.q1("SELECT episode_number, title, length(coalesce(content,'')) L FROM episodes WHERE id=?", (ep_id,))
            if not ep:
                continue
            no, title, L = ep["episode_number"], (ep["title"] or ""), ep["L"]
            # done 是"已完成章数",前面 done 章已过;当前正在写的是第 done+1 章
            if i < done:
                mark, color = "✓ 已完成", "#16a34a"
            elif i == done:
                color = "#f97316"
                # 红框区动态过程文字:按真实阶段显示(用户要求「显示动态思考
                # 或生成过程的文字」);写作阶段轮播三连语,其余按阶段+轮次。
                if cur_stage == "reviewing":
                    mark = ("🔍 审校中" + (f"(第 {cur_cycle}/3 轮)" if cur_cycle else "")
                            + " · 连贯性/人设/设定…")
                elif cur_stage == "repairing":
                    mark = ("🔧 按审校清单修复问题"
                            + (f"(第 {cur_cycle} 轮)" if cur_cycle else "") + "…")
                elif cur_stage == "jev_gate":
                    mark = "⚖ 一致性门控校验…"
                elif cur_stage == "prose":
                    mark = "📖 小说体改造(脚本体→叙述正文)…"
                elif cur_stage == "ledger":
                    mark = "📒 更新状态台账(事实层)…"
                elif cur_stage == "writing":
                    mark = "✍️ " + ("正在构思情节…", "正在撰写正文…",
                                     "正在润色语言…")[self._run_tick % 3]
                else:
                    stage = self.page._chapter_running_stage(ep_id) or ""
                    mark = "✍️ 进行中"
                    if stage:
                        mark = mark + "  ·  " + tr(STAGE_CN.get(stage, stage))
            else:
                mark, color = "待写", "#a8b0bb"
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(8, 4, 8, 4)
            hl.setSpacing(8)
            num = W.muted(f"第 {no} 章")
            num.setFixedWidth(64)
            hl.addWidget(num)
            t = QLabel(title or "")
            t.setStyleSheet(f"font-size:12px; color:{color};")
            t.setToolTip(title or "")
            hl.addWidget(t, 1)
            st = W.muted(mark)
            st.setStyleSheet(f"font-size:11px; color:{color};")
            hl.addWidget(st)
            hl.addWidget(W.muted(f"{L} 字"))
            self.rows.addWidget(row)

    # 进度
    def update_progress(self, done: int, total: int):
        running = 1 if done < total else 0
        fail = getattr(self, "_fail", 0)
        self.bar.set_counts(done - fail, fail, running, self.total)
        self.legend.setText(tr('{}%  ·  进行中 {}  ·  成功 {}  ·  失败 {}').format(int((done / self.total) * 100), running, done - fail, fail))
        self._refresh_stage()

    def finish(self, ok: int, fail: int):
        self._fail = fail
        self.bar.set_counts(ok, fail, 0, self.total)
        self.legend.setText(tr('100%  ·  成功 {}  ·  失败 {}').format(ok, fail))
        self.stage_lab.setText(tr("完成"))
        self._render_ledger()

    def _refresh_stage(self):
        if not self.page:
            return
        ids = getattr(self.page, "_batch_ids", []) or []
        cur = next((i for i in ids if self.page._chapter_running_stage(i)), None)
        if cur:
            # cur 是**集 id**;显示集号(id≠集号,EP4 的 id 可能是 94)+
            # 这一集的当前阶段。之前错把 id 当阶段/集号格式化(实测截图)。
            from ..core import db as _db
            num = _db.q1("SELECT episode_number FROM episodes WHERE id=?", (cur,))
            _num = (num["episode_number"] if num else cur)
            stage = self.page._chapter_running_stage(cur) or ""
            import time as _time
            _now = _time.time()
            _el = max(1, int((_now - getattr(self, "_t0", _now)) // 60))
            _cs = max(1, int((_now - getattr(self, "_chap_t0", _now)) // 60))
            _done = int(getattr(self.page, "_batch_done", 0) or 0)
            _rest = ""
            if _done:
                _avg = (_now - getattr(self, "_t0", _now)) / _done
                _rest = tr(' · 剩余约 {} 分').format(
                    max(1, int(_avg * (self.total - _done) // 60)))
            self.stage_lab.setText(
                tr('当前阶段:{}').format(
                    f"第 {_num} 集 · " + tr(STAGE_CN.get(stage, stage)))
                + tr(' · 已用时 {} 分 · 本章 {} 分').format(_el, _cs) + _rest)
            return
        # 没有 processing 任务时不留白:给出明确的下一步,否则「空标签」和
        # 「卡住了」在界面上长得一模一样
        done = int(getattr(self.page, "_batch_done", 0) or 0)
        if done >= self.total:
            self.stage_lab.setText(tr("完成"))
        elif done == 0 and ids:
            self.stage_lab.setText(tr("准备中… 正在启动模型"))

    # 伏笔台账
    def _toggle_ledger(self, on: bool):
        self.ledger_box.setVisible(on)
        self.ledger_btn.setText(tr("▾ 伏笔台账") if on else tr("▸ 伏笔台账"))

    def _render_ledger(self):
        if not self.page:
            return
        from ..pipeline import novel as N
        while self.ledger_list.count():
            it = self.ledger_list.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        data = N.get_ledger(self.page.drama_id)
        if not data["items"]:
            lab = W.muted(tr("(台账为空)"))
            self.ledger_list.addWidget(lab)
            return
        for item in data["items"]:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 1, 2, 1)
            cb = QCheckBox()
            cb.setChecked(bool(item.get("closed")))
            cb.toggled.connect(lambda _v, it=item: self._toggle_ledger_item(it))
            rl.addWidget(cb)
            ch = item.get("open_chapter")
            rl.addWidget(W.tag(tr('第{}章').format(ch) if ch else "—"))
            txt = QLabel(item.get("text", "")[:60])
            txt.setObjectName("muted")
            txt.setWordWrap(True)
            if item.get("closed") or item.get("stale"):
                txt.setStyleSheet("color:#c0c6cf;text-decoration:line-through;")
            rl.addWidget(txt, 1)
            self.ledger_list.addWidget(row)

    def _toggle_ledger_item(self, item: dict):
        from ..pipeline import novel as N
        from .toast import err
        if not self.page:
            return
        was = bool(item.get("closed"))
        item["closed"] = not was          # 乐观更新
        self._render_ledger()
        try:
            N.toggle_ledger(self.page.drama_id, item.get("index", 0),
                            self.page._ep["episode_number"])
        except Exception as e:  # noqa: BLE001
            item["closed"] = was           # 失败回滚
            self._render_ledger()
            err(e)


class ReviewPanelDialog(QDialog):
    """审校问题明细(勾选标记已处理,仅本地不改正文)。"""

    def __init__(self, parent, issues: list, chapter: int = 0, title: str = ""):
        super().__init__(parent)
        self.setWindowTitle(tr("审校问题明细"))
        self.resize(560, 460)
        root = QVBoxLayout(self)
        root.addWidget(W.h2(tr('第 {} 章 · {}').format(chapter, title) if title else tr('第 {} 章').format(chapter)))
        self.resolved: set[int] = set()
        self.boxes: dict[int, QCheckBox] = {}
        for i, iss in enumerate(issues or []):
            txt = iss if isinstance(iss, str) else str(iss.get("description") or iss.get("issue") or iss)
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(2, 2, 2, 2)
            cb = QCheckBox()
            cb.toggled.connect(lambda v, i=i: self._mark(i, v))
            rl.addWidget(cb)
            lab = QLabel(txt)
            lab.setWordWrap(True)
            rl.addWidget(lab, 1)
            self.boxes[i] = cb
            root.addWidget(row)
        root.addWidget(W.muted(tr("勾选表示你已处理该项(仅本地标记,不修改正文)")))
        close = W.primary_btn(tr("close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

    def _mark(self, i: int, v: bool):
        if v:
            self.resolved.add(i)
        else:
            self.resolved.discard(i)


class ReviewSummaryDialog(QDialog):
    """全书审校清单:逐章列出问题,可跳转。"""

    def __init__(self, parent, data: dict, on_goto=None):
        super().__init__(parent)
        self.setWindowTitle(tr("全书审校清单"))
        self.resize(680, 560)
        self._on_goto = on_goto
        root = QVBoxLayout(self)
        root.addWidget(W.h2(tr('{} 章有问题 · 共 {} 项').format(data.get('total', 0), data.get('issues', 0))))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        items = data.get("items") or []
        if not items:
            lay.addWidget(W.muted(tr("全书没有审校问题")))
        for it in items:
            box = W.make_card()
            bl = QVBoxLayout(box)
            head = QHBoxLayout()
            head.addWidget(W.tag(tr('第{}章').format(it.get('episode_number'))))
            head.addWidget(QLabel(it.get("title") or ""))
            head.addWidget(W.tag(tr('{} 项').format(it.get('count', 0))))
            head.addStretch(1)
            go = QPushButton(tr("去这章"))
            go.clicked.connect(lambda _=False, e=it.get("episode_id"): self._goto(e))
            head.addWidget(go)
            bl.addLayout(head)
            for s in (it.get("issues") or [])[:20]:
                lab = QLabel("· " + str(s))
                lab.setObjectName("muted")
                lab.setWordWrap(True)
                bl.addWidget(lab)
            lay.addWidget(box)
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)
        close = W.primary_btn(tr("close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

    def _goto(self, episode_id):
        if self._on_goto:
            self._on_goto(episode_id)
        self.accept()
