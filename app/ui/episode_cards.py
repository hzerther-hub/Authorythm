# -*- coding: utf-8 -*-
"""制作面板的卡片与小组件(对齐原版 episode.vue 的 .asset-* / .video-* / .comic-*)。

只放「画出来」的可复用件,不含业务逻辑;回调由调用方(EpisodePage)以闭包传入。
配色一律走 theme.py 的 objectName QSS,不写死颜色。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from . import widgets as W
from ..core.i18n import tr

# ── 通用小件 ──
def section_title(text: str, add_label: str = "", on_add=None) -> QWidget:
    """区块标题 + 右侧虚线「新增」按钮(对齐 .asset-section-title + .asset-add-btn)。"""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 2, 0, 2)
    lab = QLabel(text)
    lab.setObjectName("sectionTitle")
    lay.addWidget(lab)
    lay.addStretch(1)
    if add_label:
        add = QPushButton(f"+  {add_label}")
        add.setObjectName("addBtn")
        add.setCursor(Qt.PointingHandCursor)
        if on_add:
            add.clicked.connect(on_add)
        lay.addWidget(add)
    return box


def mono_tag(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("monoTag")
    return lab


def status_pill(state: str, text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("statusDot")
    lab.setProperty("state", state)
    lab.setAlignment(Qt.AlignCenter)
    return lab


def role_tag(role_type: str, text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("roleTag")
    lab.setProperty("role", role_type or "extra")
    return lab


def link_label(text: str, on_click) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet("color:#f97316; font-size:11px; background:transparent; border:none;")
    lab.setCursor(Qt.PointingHandCursor)
    lab.mousePressEvent = lambda _e: on_click()
    return lab


def scroll_host(inner: QWidget) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setStyleSheet("QScrollArea{border:none;background:transparent;}")
    sc.setWidget(inner)
    return sc


class SaveOnBlurEdit(QPlainTextEdit):
    """失焦即存的文本框(QPlainTextEdit 没有 editingFinished,这里补一个)。"""

    editing_finished = Signal()

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.editing_finished.emit()


def empty_state(icon: str, title: str, desc: str = "") -> QWidget:
    box = QFrame()
    box.setObjectName("emptyState")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(16, 40, 16, 40)
    lay.setSpacing(6)
    ic = QLabel(icon)
    ic.setAlignment(Qt.AlignCenter)
    ic.setObjectName("placeholderIcon")
    ic.setStyleSheet("font-size:30px;")
    lay.addWidget(ic)
    t = QLabel(title)
    t.setAlignment(Qt.AlignCenter)
    t.setStyleSheet("font-weight:700; font-size:14px;")
    lay.addWidget(t)
    if desc:
        d = QLabel(desc)
        d.setAlignment(Qt.AlignCenter)
        d.setObjectName("muted")
        lay.addWidget(d)
    return box


class CoverBox(QFrame):
    """封面框:图或占位图标 + 左上状态角标 + 左下类型角标(对齐 .asset-cover / .character-portrait)。

    角标用 QGridLayout 同格叠放实现「浮在图上」,避免嵌套布局把图挤小。
    """

    def __init__(self, url: str | None, w: int, h: int, placeholder: str,
                 badge: str = "", badge_state: str = "todo", tag_text: str = "",
                 on_click=None):
        super().__init__()
        self.setFixedHeight(h)
        self.setMinimumWidth(min(w, 180))     # 不再撑破卡宽:小屏按 180,宽屏随布局铺满
        self._w = w
        self.setStyleSheet(
            "QFrame#coverBox{border:1px solid rgba(128,128,128,0.22); border-radius:8px;}"
            "QLabel#coverInner{border:none;}")
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(0)
        if url:
            img = QLabel()
            img.setObjectName("coverInner")
            img.setAlignment(Qt.AlignCenter)
            img.setPixmap(W.pixmap_from_media(url, w, h))
            if on_click:
                img.setCursor(Qt.PointingHandCursor)
                img.mousePressEvent = lambda _e: on_click()
            g.addWidget(img, 0, 0)
        else:
            ph = QLabel(placeholder)
            ph.setObjectName("coverInner")
            ph.setObjectName("placeholderIcon")
            ph.setAlignment(Qt.AlignCenter)
            g.addWidget(ph, 0, 0)
        if badge:
            b = QLabel(badge)
            b.setObjectName("coverBadge")
            b.setProperty("state", badge_state)
            g.addWidget(b, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        if tag_text:
            t = QLabel(tag_text)
            t.setObjectName("coverTag")
            g.addWidget(t, 1, 0, Qt.AlignLeft | Qt.AlignBottom)


def final_prompt_block(text: str, placeholder: str, on_edit=None) -> QFrame:
    """卡底「最终提示词」块:标签 + 两行截断 + 点击进入编辑(对齐 .asset-final-prompt)。"""
    box = QFrame()
    box.setObjectName("finalPrompt")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 5, 0, 0)
    lay.setSpacing(2)
    lab = QLabel(tr("最终提示词"))
    lab.setObjectName("finalLabel")
    lay.addWidget(lab)
    body = QLabel(text or placeholder)
    body.setObjectName("finalText")
    body.setWordWrap(True)
    if not text:
        body.setStyleSheet("color:#a8b0bb; font-size:11px;")
    if on_edit:
        box.setCursor(Qt.PointingHandCursor)
        box.mousePressEvent = lambda _e: on_edit()
    lay.addWidget(body)
    return box


# ── 资产卡 ──
class CharacterAssetCard(QFrame):
    """角色卡:16:9 立绘 + 角色角标 + 样貌/妆造 + 图绘/文绘/上传/换脸/变体 + 最终提示词。"""

    def __init__(self, row: dict, labels: dict, *, on_gen_image=None, on_gen_text=None,
                 on_upload=None, on_face_swap=None, on_variants=None, on_prompt=None,
                 on_open=None):
        super().__init__()
        self.setObjectName("assetCard")
        self.setFixedWidth(250)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(7)
        lay.addWidget(CoverBox(row.get("image_url"), 232, 132, "☺",
                               badge=labels["cover_todo"],
                               badge_state="ready" if row.get("image_url") else "todo",
                               tag_text=labels["cover_tag"],
                               on_click=on_open))
        # 名字块独占整行(此前与按钮同排,长名被挤到 ~30px 宽后省略;超长自动折行)
        name_wrap = QWidget()
        name_wrap.setStyleSheet("border:none; background:transparent;")
        name_row = QVBoxLayout(name_wrap)
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(3)
        name = QLabel(row.get("name") or "")
        f = name.font()
        f.setBold(True)
        name.setFont(f)
        name.setWordWrap(True)          # 折行而非截断
        name_row.addWidget(name)
        name_row.addWidget(role_tag(
            row.get("role_type") or "",
            {"lead": labels["lead"], "supporting": labels["supporting"]}.get(
                row.get("role_type") or "", labels["extra"])))
        lay.addWidget(name_wrap)
        summary = QHBoxLayout()
        for key, lab in (("appearance", tr("样貌")), ("styling", tr("妆造"))):
            v = (row.get(key) or "").strip()
            l = QLabel(f"{lab}:{v[:22]}{'…' if len(v) > 22 else ''}")
            l.setObjectName("muted")
            l.setToolTip(v)
            summary.addWidget(l)
        lay.addLayout(summary)
        btns = QHBoxLayout()
        btns.setSpacing(4)
        for text, tip, cb, enabled in (
            (labels["gen_image"], labels["gen_image_tip"], on_gen_image, bool(row.get("image_url"))),
            (labels["gen_text"], labels["gen_text_tip"], on_gen_text, True),
            (labels["upload"], labels["upload_tip"], on_upload, True),
            (labels["face_swap"], labels["face_swap_tip"], on_face_swap, True),
        ):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setEnabled(enabled)
            b.setCursor(Qt.PointingHandCursor)
            if cb:
                b.clicked.connect(lambda _=False, c=cb: c())
            btns.addWidget(b)
        lay.addLayout(btns)
        if on_variants:
            var = QPushButton(labels["variants"])
            var.setToolTip(labels["variants_tip"])
            var.setCursor(Qt.PointingHandCursor)
            var.clicked.connect(lambda _=False: on_variants())
            lay.addWidget(var)
        lay.addWidget(final_prompt_block(row.get("final_prompt") or "",
                                        labels["prompt_ph"], on_prompt))
        lay.addStretch(1)


class AssetCard(QFrame):
    """场景 / 道具卡:16:9 封面 + 名称 + 描述 + 光照 + 最终提示词 + 状态点/重绘/上传。"""

    def __init__(self, row: dict, labels: dict, kind: str, *,
                 on_gen=None, on_upload=None, on_prompt=None, on_open=None):
        super().__init__()
        self.setObjectName("assetCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(198)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        has = bool(row.get("image_url"))
        # 封面占满卡宽:此前固定两列(主图+漫画图),单封面只占左半
        lay.addWidget(CoverBox(row.get("image_url"), 260, 112,
                               "⌖" if kind == "scene" else "▣",
                               badge=labels["cover_done"] if has else labels["cover_todo"],
                               badge_state="ready" if has else "todo",
                               tag_text=labels["cover_tag"],
                               on_click=on_open))
        body = QWidget()
        body.setStyleSheet("border:none;")
        blay = QVBoxLayout(body)
        blay.setContentsMargins(9, 9, 9, 8)
        blay.setSpacing(3)
        name_row = QHBoxLayout()
        name = QLabel(row.get("location") or row.get("name") or "")
        f = name.font()
        f.setBold(True)
        name.setFont(f)
        name.setToolTip(name.text())
        name_row.addWidget(name, 1)
        if kind == "prop":
            name_row.addWidget(W.tag(row.get("type") or labels["prop"]))
        blay.addLayout(name_row)
        desc = (row.get("description") or "").strip()
        dl = QLabel(desc or labels["desc_empty"])
        dl.setObjectName("muted")
        dl.setWordWrap(True)
        blay.addWidget(dl)
        if kind == "scene" and (row.get("lighting") or "").strip():
            ll = QLabel(tr('光照 · {}').format(row['lighting'].strip()))
            ll.setObjectName("muted")
            ll.setWordWrap(True)
            blay.addWidget(ll)
        blay.addWidget(final_prompt_block(row.get("final_prompt") or "",
                                         labels["prompt_ph"], on_prompt))
        lay.addWidget(body)
        lay.addStretch(1)
        foot = QWidget()
        foot.setStyleSheet("border:none; border-top:1px solid rgba(128,128,128,0.18);")
        flay = QHBoxLayout(foot)
        flay.setContentsMargins(9, 7, 9, 8)
        flay.setSpacing(4)
        flay.addWidget(status_pill("ready" if has else "todo",
                                   labels["gen_done"] if has else labels["gen_todo"]))
        gen = QPushButton(labels["redraw"] if has else labels["generate"])
        gen.setCursor(Qt.PointingHandCursor)
        if on_gen:
            gen.clicked.connect(lambda _=False: on_gen())
        flay.addWidget(gen)
        flay.addStretch(1)
        up = QPushButton(labels["upload"])
        up.setToolTip(labels["upload_tip"])
        up.setCursor(Qt.PointingHandCursor)
        if on_upload:
            up.clicked.connect(lambda _=False: on_upload())
        flay.addWidget(up)
        lay.addWidget(foot)


class ComicAssetRow(QFrame):
    """漫画资产行:44px 缩略 + 名称 + 状态 + 生成漫画风按钮(对齐 .asset-comic-row)。"""

    def __init__(self, thumb_url: str, name: str, ready: bool, pending: bool,
                 button_tip: str, on_gen):
        super().__init__()
        self.setObjectName("assetCard")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)
        if thumb_url:
            th = QLabel()
            th.setFixedSize(44, 44)
            th.setPixmap(W.pixmap_from_media(thumb_url, 44, 44))
            th.setStyleSheet("border-radius:6px;")
        else:
            th = QLabel("⠋" if pending else "+")
            th.setFixedSize(44, 44)
            th.setAlignment(Qt.AlignCenter)
            th.setObjectName("placeholderIcon")
        lay.addWidget(th)
        nm = QLabel(name)
        nm.setObjectName("muted")
        nm.setToolTip(name)
        lay.addWidget(nm, 1)
        text = tr("生成中") if pending else (tr("已生成") if ready else tr("待生成"))
        lay.addWidget(status_pill("pending" if pending else ("ready" if ready else "todo"), text))
        btn = QPushButton("📕")
        btn.setToolTip(button_tip)
        btn.setFixedSize(26, 26)
        btn.setCursor(Qt.PointingHandCursor)
        if on_gen:
            btn.clicked.connect(lambda _=False: on_gen())
        lay.addWidget(btn)


# ── 分镜视频任务 ──
class MetricPill(QPushButton):
    """可点击筛选胶囊(生成中 / 完成 / 失败)。"""

    def __init__(self, state: str, text: str, on_click):
        super().__init__(text)
        self.setObjectName("metricPill")
        self.setProperty("state", state)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(lambda _=False: on_click(state))


class VideoTaskRow(QFrame):
    """视频任务行:56×32 预览 + #NN + 名称 + 状态/时长/场景 + 操作键(对齐 .video-task-row)。"""

    def __init__(self, index: int, name: str, meta: str, state: str, state_label: str,
                 action_tip: str, thumb_url: str | None, *, selected: bool = False,
                 on_click=None, on_action=None):
        super().__init__()
        self.setObjectName("taskRow")
        self.setProperty("state", "selected" if selected else state)
        self._name = name
        self._meta = meta
        self._state = state
        self._state_label = state_label
        self._index = index
        self._action_tip = action_tip
        self._thumb = thumb_url
        self._on_action = on_action
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)
        prev = QFrame()
        prev.setFixedSize(56, 32)
        prev.setObjectName("videoThumb")
        pl = QVBoxLayout(prev)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        if thumb_url:
            im = QLabel()
            im.setAlignment(Qt.AlignCenter)
            im.setPixmap(W.pixmap_from_media(thumb_url, 56, 32))
            pl.addWidget(im)
        else:
            ph = QLabel("🎬")
            ph.setAlignment(Qt.AlignCenter)
            ph.setObjectName("videoThumbIcon")
            pl.addWidget(ph)
        idx = QLabel(f"#{index:02d}")
        idx.setObjectName("taskIndex")
        pl.addWidget(idx, 0, Qt.AlignLeft)
        lay.addWidget(prev)
        main = QVBoxLayout()
        main.setSpacing(1)
        nm = QLabel(name)
        nm.setObjectName("taskName")
        nm.setToolTip(name)
        main.addWidget(nm)
        mt = QLabel(meta)
        mt.setObjectName("taskMeta")
        mt.setToolTip(meta)
        main.addWidget(mt)
        lay.addLayout(main, 1)
        act = QPushButton("🎬")
        act.setToolTip(action_tip)
        act.setFixedSize(24, 24)
        act.setEnabled(state != "pending")
        act.setCursor(Qt.PointingHandCursor)
        if on_action:
            act.clicked.connect(lambda _=False: on_action())
        lay.addWidget(act)
        self.setCursor(Qt.PointingHandCursor)
        if on_click:
            self.mousePressEvent = lambda _e: on_click()

    def refresh(self, thumb_url: str | None = None):
        """原地更新缩略图与状态,避免整列重建导致滚动位置跳回顶部。"""
        if thumb_url is not None and thumb_url != self._thumb:
            self._thumb = thumb_url
        self.setProperty("state", "selected" if False else self._state)
        self.style().unpolish(self)
        self.style().polish(self)


class RefCard(QFrame):
    """参考素材卡:缩略(或「角/景/具」占位)+ 名称 + 类型/变体 + 可参考状态。"""

    def __init__(self, url: str | None, placeholder: str, name: str, meta: str,
                 state: str, on_click=None, on_generate=None):
        super().__init__()
        self.setObjectName("refCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(3)
        if url:
            im = QLabel()
            im.setMinimumHeight(120)
            im.setAlignment(Qt.AlignCenter)
            im.setPixmap(W.pixmap_from_media(url, 170, 130))
            if on_click:
                im.setCursor(Qt.PointingHandCursor)
                im.mousePressEvent = lambda _e: on_click()
            lay.addWidget(im)
        else:
            ph = QLabel(placeholder)
            ph.setAlignment(Qt.AlignCenter)
            ph.setFixedHeight(120)
            ph.setObjectName("refThumb")
            lay.addWidget(ph)
        nm = QLabel(name)
        f = nm.font()
        f.setBold(True)
        nm.setFont(f)
        nm.setToolTip(name)
        lay.addWidget(nm)
        if meta:
            m = QLabel(meta)
            m.setObjectName("muted")
            lay.addWidget(m)
        st = QLabel(state)
        st.setObjectName("refState")
        # state 传进来已经是 tr("ref_ok") 之类翻好的文案,拿原键比会永远不相等
        st.setProperty("ok", "1" if state == tr("ref_ok") else "0")
        lay.addWidget(st)
        if on_generate:
            lay.addWidget(link_label(tr("去生成 →"), on_generate))


# ── 漫画格 ──
class NarrationBox(QFrame):
    """旁白说明框:标题 + 可编辑旁白 + 提示,草稿与已存值不同时出现「还原 / 保存」。"""

    def __init__(self, saved: str, labels: dict, on_save=None):
        super().__init__()
        self.setObjectName("narrationBox")
        self._saved = saved or ""
        self._on_save = on_save
        lay = QVBoxLayout(self)
        lay.setContentsMargins(7, 6, 7, 6)
        lay.setSpacing(3)
        head = QHBoxLayout()
        hl = QLabel(labels["narration_label"])
        hl.setObjectName("narrationHead")
        head.addWidget(hl)
        head.addStretch(1)
        self._reset_btn = QPushButton(tr("还原"))
        self._reset_btn.setFixedHeight(20)
        self._reset_btn.setVisible(False)
        self._reset_btn.clicked.connect(self._reset)
        self._save_btn = W.primary_btn(tr("保存"))
        self._save_btn.setFixedHeight(20)
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._commit)
        head.addWidget(self._reset_btn)
        head.addWidget(self._save_btn)
        lay.addLayout(head)
        self.edit = QPlainTextEdit(self._saved)
        self.edit.setPlaceholderText(labels["narration_ph"])
        self.edit.setFixedHeight(56)
        lay.addWidget(self.edit)
        self.hint = QLabel("")
        self.hint.setObjectName("narrationHint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.edit.textChanged.connect(self._sync)
        self._sync()

    def _sync(self):
        text = self.edit.toPlainText()
        dirty = text != self._saved
        self._reset_btn.setVisible(dirty)
        self._save_btn.setVisible(dirty)
        if dirty:
            self.hint.setText("")
        elif text:
            self.hint.setText(f"{len(text)}/200")
        else:
            self.hint.setText(self.labels_hint if hasattr(self, "labels_hint") else "")
        return dirty

    def set_hint(self, text: str):
        self.labels_hint = text
        if self.edit.toPlainText() == self._saved:
            self.hint.setText(text if not self._saved else f"{len(self._saved)}/200")

    def _reset(self):
        self.edit.setPlainText(self._saved)

    def _commit(self):
        text = self.edit.toPlainText()
        self._saved = text
        self._sync()
        if self._on_save:
            self._on_save(text)


class ComicPanelCard(QFrame):
    """漫画格卡:3:4 缩略 + 序号 + 描述/台词/构图 + 旁白说明框 + 错误 + 出图提示词。"""

    def __init__(self, row: dict, labels: dict, *, busy: bool = False, failed: str = "",
                 on_draw=None, on_open=None, on_narration_save=None):
        super().__init__()
        self.setObjectName("comicCard")
        self.setProperty("state", "failed" if failed else "")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 缩略:3:4 竖版,角标浮在图上(对齐 .comic-panel-thumb)
        thumb = QFrame()
        thumb.setObjectName("comicThumbBox")
        thumb.setFixedHeight(196)
        tg = QGridLayout(thumb)
        tg.setContentsMargins(0, 0, 0, 0)
        tg.setSpacing(0)
        url = row.get("image_url")
        if url:
            im = QLabel()
            im.setAlignment(Qt.AlignCenter)
            im.setPixmap(W.pixmap_from_media(url, 250, 196))
            if on_open:
                im.setCursor(Qt.PointingHandCursor)
                im.mousePressEvent = lambda _e: on_open()
            tg.addWidget(im, 0, 0)
        else:
            cell = QWidget()
            cl2 = QVBoxLayout(cell)
            cl2.setContentsMargins(0, 0, 0, 0)
            cl2.setAlignment(Qt.AlignCenter)
            ph = QLabel("⠋" if busy else "▣")
            ph.setAlignment(Qt.AlignCenter)
            ph.setObjectName("comicThumb")
            cl2.addWidget(ph)
            if not busy and on_draw:
                draw = QPushButton(labels["draw"])
                draw.setFixedSize(64, 26)
                draw.setCursor(Qt.PointingHandCursor)
                draw.clicked.connect(lambda _=False: on_draw())
                cl2.addWidget(draw, 0, Qt.AlignCenter)
            tg.addWidget(cell, 0, 0)
        idx = QLabel(f"#{int(row.get('panel_number') or 0):02d}")
        idx.setObjectName("comicIndex")
        tg.addWidget(idx, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        if url:
            redo = QPushButton("⟳")
            redo.setFixedSize(24, 24)
            redo.setToolTip(labels["redraw"])
            redo.setCursor(Qt.PointingHandCursor)
            redo.clicked.connect(lambda _=False: on_draw() if on_draw else None)
            tg.addWidget(redo, 0, 0, Qt.AlignRight | Qt.AlignTop)
        lay.addWidget(thumb)

        body = QWidget()
        body.setStyleSheet("border:none;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(9, 8, 9, 10)
        bl.setSpacing(5)
        desc = (row.get("description") or "").strip()
        dl = QLabel(desc or "—")
        dl.setStyleSheet("font-weight:700; font-size:12px;")
        dl.setToolTip(desc)
        dl.setWordWrap(True)
        bl.addWidget(dl)
        if (row.get("dialogue") or "").strip():
            dq = QLabel(row["dialogue"].strip())
            dq.setObjectName("comicDialogue")
            dq.setWordWrap(True)
            bl.addWidget(dq)
        if (row.get("composition") or "").strip():
            cp = QLabel(tr('构图:{}').format(row['composition'].strip()))
            cp.setObjectName("muted")
            cp.setWordWrap(True)
            bl.addWidget(cp)
        self.narration = NarrationBox(row.get("narration") or "", labels, on_narration_save)
        self.narration.set_hint(labels["narration_hint"])
        bl.addWidget(self.narration)
        if failed:
            er = QHBoxLayout()
            e = QLabel(failed)
            e.setObjectName("comicError")
            e.setToolTip(failed)
            er.addWidget(e, 1)
            if on_draw:
                retry = QPushButton(labels["draw"])
                retry.clicked.connect(lambda _=False: on_draw())
                er.addWidget(retry)
            bl.addLayout(er)
        if (row.get("image_prompt") or "").strip():
            pr = QLabel(labels["prompt_label"])
            pr.setObjectName("finalLabel")
            bl.addWidget(pr)
            pv = QLabel(row["image_prompt"].strip()[:300])
            pv.setObjectName("finalText")
            pv.setWordWrap(True)
            pv.setToolTip(row["image_prompt"])
            bl.addWidget(pv)
        lay.addWidget(body)
        lay.addStretch(1)