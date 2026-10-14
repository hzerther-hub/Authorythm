# -*- coding: utf-8 -*-
"""制作面板的卡片与小组件(对齐原版 episode.vue 的 .asset-* / .video-* / .comic-*)。

只放「画出来」的可复用件,不含业务逻辑;回调由调用方(EpisodePage)以闭包传入。
配色一律走 theme.py 的 objectName QSS,不写死颜色。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap, QPolygonF
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


# 三类资产卡统一尺寸(对齐参考项目 character-asset-grid 的 230-260px 卡片)
ASSET_CARD_W = 250


def _snug_card(card: QFrame):
    """卡片贴内容高:宽固定对齐网格,高按 sizeHint 收口。

    之前三类卡统一 setFixedSize(250, 360),内容不足 360 时底部留一大块空白
    (用户红框标的就是它)。高度改由内容决定,网格行高自动取本行最高的卡。
    """
    card.setFixedWidth(ASSET_CARD_W)
    card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    card.adjustSize()
    card.setFixedHeight(max(card.height(), 120))


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
    # 参考项目(web)只有纵向滚动;横向滚动条多为长文本撑宽内层所致,直接关掉
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    sc.setWidget(inner)
    return sc


def chapter_editor(cls=None):
    """整章页(原始内容 / AI 改写)的正文编辑器 —— 与资产页 #assetCard 同款外观。

    资产页的内容是「白卡浮在 #f5f6f8 页底上」,整章页原先是一整块 #f2f3f5 的
    平铺区,两个页面并排看就是"一个做了卡片、一个没做"。

    卡片画在编辑器**自己**身上而不是外面再套一层框:编辑器本就带 1px 边框和
    圆角(见 theme.py 的 QPlainTextEdit 规则),外套框会变成"白卡里嵌一个灰块",
    多一圈描边还多 2px 内缩。

    cls 默认在调用时才解析 —— SaveOnBlurEdit 定义在本文件 scroll_host 之后,
    写成默认参数会在模块导入时就 NameError。
    """
    if cls is None:
        cls = SaveOnBlurEdit
    ed = cls()
    ed.setObjectName("chapterEdit")
    return ed


def video_camera_icon(color, size: int = 15) -> QIcon:
    """单色「摄像机」图标:🎬 emoji 在 Windows 部分字体下渲染为空框,改用 QPainter 画。

    颜色传调色板 ButtonText,亮暗主题各自成立;禁用态 Qt 自动生成灰化图标。
    """
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    w = float(size)
    # 机身圆角矩形 + 右侧探出的镜头梯形(标准 videocam 轮廓)
    p.drawRoundedRect(QRectF(0.0, w * 0.24, w * 0.62, w * 0.52), 2.0, 2.0)
    p.drawPolygon(QPolygonF([QPointF(w * 0.68, w * 0.40), QPointF(w * 0.98, w * 0.20),
                             QPointF(w * 0.98, w * 0.80), QPointF(w * 0.68, w * 0.60)]))
    p.end()
    return QIcon(pm)


class SaveOnBlurEdit(QPlainTextEdit):
    """失焦即存的文本框(QPlainTextEdit 没有 editingFinished,这里补一个)。

    默认就是 QPlainTextEdit,内容长短不一(尤其是视频提示词 + 氛围/描述段)
    时,固定高度让短文空、长文塞不下。所以**按文档行数自适应**,留一个上限免得
    把整个分镜工作台撑爆。
    """

    editing_finished = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 撑满模式开关:默认关,行为与以前完全一致(按内容自适应 + 封顶)。
        self._fill = False
        # 关键:sizePolicy 垂直是 Preferred(默认是 Expanding)—— Expanding 会让父
        # 布局把所有剩余空间塞给它,无视 maxHeight,文本框看上去一样高。
        # Preferred 让 widget 按 min/max = 内容高走,父布局给多少就是多少。
        from PySide6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setAutoResizeRange(80, 480)
        self.textChanged.connect(self._auto_resize)

    def setAutoResizeRange(self, min_h: int, max_h: int) -> None:
        """设上下限(像素)。此后每次 textChanged / showEvent / resizeEvent 都
        会按需重设 setMinimumHeight / setMaximumHeight 到 [min_h, max_h]。"""
        self._ar_min = int(min_h)
        self._ar_max = int(max_h)

    def setFillHeight(self, on: bool = True) -> None:
        """撑满模式:不吃 autoResizeRange 的高度封顶,始终吃掉父布局给的全部剩余
        高度;文本更长时用编辑器自身的滚动条,而不是把页面撑长。

        为什么整章页需要它:raw / rewrite 的编辑器原来按内容自适应、最多 480px。
        窗口比这高时剩余空间没处去,QVBoxLayout 会把它**均摊到内容块的上下**
        —— 工具条被顶下 41px、底部条下面又压一条 41px 空带(实测工具条 y=49,
        资产页同一位置 y=8)。资产页内容是撑满的,所以整章页看着比资产页
        "缩进去一截",上下各留一条空白带。
        """
        from PySide6.QtWidgets import QSizePolicy
        self._fill = bool(on)
        if self._fill:
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            self.updateGeometry()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._schedule_resize()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # 用户反馈:输入框在不停地抖动(红框闪烁)—— 根因是 resizeEvent 频繁
        # 触发 _auto_resize,而 _auto_resize 的 updateGeometry 又触发下一次
        # resizeEvent,死循环刷新导致 focus 描边跳。
        # 修:1) 加 _resizing 防重入;2) 只在宽度变了 ≥2px 才计算(像素 jitter 跳过)
        if getattr(self, "_resizing", False):
            return
        new_w = ev.size().width()
        prev_w = getattr(self, "_last_resize_w", None)
        if prev_w is not None and abs(new_w - prev_w) < 2:
            return
        self._last_resize_w = new_w
        self._resizing = True
        try:
            self._auto_resize()
        finally:
            self._resizing = False

    def _schedule_resize(self) -> None:
        from PySide6.QtCore import QTimer
        if getattr(self, "_fill", False):
            return          # 撑满模式高度由父布局给,再自适应会把它按回内容高
        QTimer.singleShot(0, self._auto_resize)

    def _auto_resize(self) -> None:
        # QPlainTextEdit 高度自适应的唯一稳定做法:用 QFontMetrics 自算
        # —— 用 vp 宽折算每段占几行,总行数 × lineSpacing + padding。
        # 关键:同时设 setMin/setMax = h,让容器尊重真实高度而不是被拉伸
        if getattr(self, "_resizing", False) or getattr(self, "_fill", False):
            return
        vp_w = self.viewport().width()
        if vp_w <= 0:
            self._schedule_resize()
            return
        fm = self.fontMetrics()
        line_h = fm.lineSpacing()
        avg_w = max(7, fm.horizontalAdvance("中"))
        margins = self.contentsMargins().left() + self.contentsMargins().right() \
                  + self.frameWidth() * 2
        usable_w = max(1, vp_w - margins - 4)
        chars_per_line = max(1, usable_w // avg_w)

        total_lines = 0
        text = self.toPlainText()
        if not text:
            total_lines = 1
        else:
            for line in text.split("\n"):
                n = len(line)
                if n <= chars_per_line:
                    total_lines += 1
                else:
                    total_lines += (n + chars_per_line - 1) // chars_per_line
        h = int(total_lines * line_h) + 12
        h = max(self._ar_min, min(self._ar_max, h))
        if self.minimumHeight() != h:
            self.setMinimumHeight(h)
        if self.maximumHeight() != h:
            self.setMaximumHeight(h)
        self.updateGeometry()

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
                 on_click=None, pending: bool = False, on_download=None):
        super().__init__()
        self.setFixedHeight(h)
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
            img.setPixmap(W.pixmap_cover_media(url, w, h))   # 铺满裁切,与参考一致
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
        # 预览图右上角下载钮(对齐参考项目 asset-cover 的 ⬇)。
        # 原先用 '⬇' 字符 + 24×24:该码位没字形,且撞上全局 padding,渲染成纯空白
        # (实测颜色数=1)。改用 Qt 原生下箭头,跨字体稳定。
        from PySide6.QtWidgets import QStyle
        self._dl_btn = W.icon_btn(QStyle.StandardPixmap.SP_ArrowDown,
                                  tr("download"), size=24, fallback="⬇")
        if on_download:
            self._dl_btn.clicked.connect(on_download)
        g.addWidget(self._dl_btn, 0, 0, Qt.AlignRight | Qt.AlignTop)
        self._dl_btn.setVisible(bool(url))
        # 生成中遮罩:半透明黑底 + 盲文转圈(对齐参考项目 Loader2 animate-spin)
        from .braille import BrailleSpinner
        self._overlay = QFrame(self)
        self._overlay.setObjectName("coverOverlay")
        self._overlay.setStyleSheet(
            "QFrame#coverOverlay{background:rgba(0,0,0,0.45);border-radius:8px;}")
        ol = QVBoxLayout(self._overlay)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setAlignment(Qt.AlignCenter)
        spin = BrailleSpinner(color="#ffffff", size=22, parent=self._overlay)
        ol.addWidget(spin, 0, Qt.AlignCenter)
        spin.start(tr("生成中"))
        g.addWidget(self._overlay, 0, 0)
        self._overlay.setVisible(pending)
        if badge:
            b = QLabel(badge)
            b.setObjectName("coverBadge")
            b.setProperty("state", badge_state)
            g.addWidget(b, 0, 0, Qt.AlignLeft | Qt.AlignTop)
        if tag_text:
            t = QLabel(tag_text)
            t.setObjectName("coverTag")
            g.addWidget(t, 1, 0, Qt.AlignLeft | Qt.AlignBottom)

    def set_pending(self, on: bool):
        """显示/隐藏生成中遮罩(生成期间封面盖转圈,按钮禁用)。"""
        self._overlay.setVisible(on)


def final_prompt_block(text: str, placeholder: str, on_edit=None) -> QFrame:
    """卡底「最终提示词」块:标签 + 两行截断 + 点击进入编辑(对齐 .asset-final-prompt)。"""
    box = QFrame()
    box.setObjectName("finalPrompt")
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 5, 0, 0)
    lay.setSpacing(2)
    lab = QLabel(tr("最终提示词"))
    lab.setObjectName("finalLabel")
    body_lab = QLabel((text or "")[:300] or placeholder)   # 正文节选(对齐参考,不再是「有/无」)
    body_lab.setToolTip(text or "")
    if not text:
        body_lab.setStyleSheet("color:#a8b0bb; font-size:11px;")
    lab_row = QHBoxLayout()
    lab_row.setContentsMargins(0, 0, 0, 0)
    lab_row.setSpacing(4)
    lab_row.addWidget(lab)
    lab_row.addWidget(body_lab)
    lab_row.addStretch(1)
    lay.addLayout(lab_row)
    body = body_lab
    body.setObjectName("finalText")
    body.setWordWrap(False)
    if on_edit:
        box.setCursor(Qt.PointingHandCursor)
        box.mousePressEvent = lambda _e: on_edit()
    lay.addWidget(body)
    return box


# ── 资产卡 ──
def apply_asset_busy(card, cover, gen_btns: list, busy: bool):
    """资产卡生成中状态:封面盖半透明遮罩+盲文转圈,**所有**按钮禁用并变旋转字。

    gen_btns 为 [(按钮, 原文字)] —— 通常只指 gen 按钮(文绘/图绘);
    但 busy=True 时仍要禁用其它按钮(上传/换脸/删除/造型变体 等),
    防止用户在生成途中再点造成并发任务或状态错乱。

    卡片 busy=False 时:原按钮文字 + 启用;True 时:全卡按钮禁用 + 旋转字。
    """
    if cover is not None:
        cover.set_pending(busy)
    # 收集卡上**所有** QPushButton(上传/换脸/删除/变体/文绘/图绘 都算)
    all_btns = list(card.findChildren(QPushButton))
    # 把 gen_btns 里没有的按钮也补进去(它们的原文字直接读 button.text())
    known_ids = {id(b) for b, _ in gen_btns}
    extra = [(b, b.text()) for b in all_btns if id(b) not in known_ids]
    full_btns = list(gen_btns) + extra
    if not busy:
        for b, orig in full_btns:
            b.setEnabled(True)
            b.setText(orig)
        return
    from PySide6.QtCore import QTimer
    from .braille import BRAILLE_FRAMES
    for b, _orig in full_btns:
        b.setEnabled(False)
        b.setText(BRAILLE_FRAMES[0])
    state = {"i": 0}

    def tick():
        state["i"] = (state["i"] + 1) % len(BRAILLE_FRAMES)
        for b, _orig in full_btns:
            b.setText(BRAILLE_FRAMES[state["i"]])
    t = QTimer(card)
    t.timeout.connect(tick)
    t.start(90)
    card._busy_timer = t


class CharacterAssetCard(QFrame):
    """角色卡:16:9 立绘 + 角色角标 + 样貌/妆造 + 图绘/文绘/上传/换脸/变体 + 最终提示词。

    封面图:优先 comic_image_url(漫画风格镜像,与项目 comic_style 一致),
    没漫画镜像时回退到 image_url(常规 3D)。这样卡片预览永远展示与
    用户在「项目设定 → 画风」选的同一种风格,不会因为先常规后漫画导致观感错位。
    """

    def __init__(self, row: dict, labels: dict, *, on_delete=None, on_gen_image=None, on_gen_text=None,
                 on_upload=None, on_face_swap=None, on_variants=None, on_prompt=None,
                 on_open=None, busy: bool = False):
        super().__init__()
        self.setObjectName("assetCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(7)
        # 封面图:image_url(常规 / 3D)优先,漫画镜像 comic_image_url 作 fallback。
        # 两个字段独立 —— 常规资产走 image_url,漫画资产走 comic_image_url;
        # 卡片默认展示常规版,因为常规版是给视频生成当 first_frame 用的(用户主要需求)。
        # 用户要看漫画版时切换到「漫画资产」tab 即可。
        cover_url = (row.get("image_url") or "").strip() or (row.get("comic_image_url") or "").strip()
        cover = CoverBox(cover_url, 320, 180, "☺",
                         badge=(labels["cover_done"] if cover_url
                                else labels["cover_todo"]),
                         badge_state="ready" if cover_url else "todo",
                         tag_text=labels["cover_tag"],
                         on_click=on_open, pending=busy)
        lay.addWidget(cover)
        # 名字块独占整行(此前与按钮同排,长名被挤到 ~30px 宽后省略;超长自动折行)
        name_wrap = QWidget()
        name_wrap.setStyleSheet("border:none; background:transparent;")
        name_row = QHBoxLayout(name_wrap)      # 角色名与定位标签同一行
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(6)
        name = QLabel(row.get("name") or "")
        f = name.font()
        f.setBold(True)
        name.setFont(f)
        name.setWordWrap(True)          # 折行而非截断
        # 角色名与「主角/配角」标签同一行(此前是上下两行,卡片显得松散)
        name_row.addWidget(name)
        r_tag = role_tag(
            row.get("role_type") or "",
            {"lead": labels["lead"], "supporting": labels["supporting"]}.get(
                row.get("role_type") or "", labels["extra"]))
        name_row.addWidget(r_tag, 0, Qt.AlignTop)
        name_row.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        lay.addWidget(name_wrap)
        summary = QHBoxLayout()
        for key, lab in (("appearance", tr("样貌")), ("styling", tr("妆造"))):
            v = (row.get(key) or "").strip()
            l = QLabel(f"{lab}:{v[:22]}{'…' if len(v) > 22 else ''}")
            l.setObjectName("muted")
            l.setToolTip(v)
            summary.addWidget(l)
        lay.addLayout(summary)
        # 按钮排成一行(用户要求):图绘/文绘/上传/换脸 + 删除 横向排布,
        # 用 QHBoxLayout 而不是 QGridLayout —— 网格在窄卡片里会被压成竖排单字。
        # 风格统一:橙色 outline(品牌色 #f97316),hover 浅橙填充,与项目主调一致;
        # 删除按钮浅红 outline 与其它按钮同款但颜色区别。
        btns = QHBoxLayout()
        btns.setSpacing(4)
        btns.setContentsMargins(0, 0, 0, 0)
        gen_btns = []      # 文绘/图绘两键:生成中变盲文旋转字(apply_asset_busy)
        # 5 个按钮一行横排:统一高度 26px,等宽 1 份 (共 5 份 + 1 份删除 = 6 份)
        for text, tip, cb, enabled, is_gen in (
            (labels["gen_image"], labels["gen_image_tip"], on_gen_image, True, True),
            (labels["gen_text"], labels["gen_text_tip"], on_gen_text, True, True),
            (labels["upload"], labels["upload_tip"], on_upload, True, False),
            (labels["face_swap"], labels["face_swap_tip"], on_face_swap, True, False),
        ):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setEnabled(enabled)
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setMinimumWidth(0)
            b.setStyleSheet(
                "QPushButton{font-size:11px;padding:3px 4px;"
                "border:1px solid #fed7aa;border-radius:6px;background:#fff8f1;color:#9a3412;}"
                "QPushButton:hover{background:#fff0e1;border-color:#f97316;}"
                "QPushButton:disabled{color:#c9cdd4;background:#f7f8fa;border-color:#e8eaef;}")
            if cb:
                b.clicked.connect(lambda _=False, c=cb: c())
            if is_gen:
                gen_btns.append((b, text))
            btns.addWidget(b, 1)
        if on_delete:                      # 删除按钮同款 outline 但红色,与生成按钮区分
            db = QPushButton(tr("delete"))
            db.setToolTip(tr("删除该资产"))
            db.setCursor(Qt.PointingHandCursor)
            db.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            db.setMinimumWidth(0)
            db.setStyleSheet(
                "QPushButton{font-size:11px;padding:3px 4px;"
                "border:1px solid #fecaca;border-radius:6px;background:#fff5f5;color:#b91c1c;}"
                "QPushButton:hover{background:#fee2e2;border-color:#ef4444;}")
            db.clicked.connect(lambda _=False: on_delete())
            btns.addWidget(db, 1)
        lay.addLayout(btns)
        if on_variants:
            var = QPushButton(labels["variants"])
            var.setToolTip(labels["variants_tip"])
            var.setCursor(Qt.PointingHandCursor)
            var.clicked.connect(lambda _=False: on_variants())
            lay.addWidget(var)
        lay.addWidget(final_prompt_block(row.get("final_prompt") or "",
                                        labels["prompt_ph"], on_prompt))
        _snug_card(self)
        apply_asset_busy(self, cover, gen_btns, busy)


class AssetCard(QFrame):
    """场景 / 道具卡:16:9 封面 + 名称 + 描述 + 光照 + 最终提示词 + 状态点/重绘/上传。"""

    def __init__(self, row: dict, labels: dict, kind: str, *,
                 on_gen=None, on_upload=None, on_prompt=None, on_open=None,
                 on_delete=None, on_gen_text=None, on_gen_vary=None, busy: bool = False):
        super().__init__()
        self.setObjectName("assetCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        has = bool(row.get("image_url"))
        # 封面占满卡宽:image_url(常规 / 3D)优先,漫画镜像 fallback。
        cover_url = (row.get("image_url") or "").strip() or (row.get("comic_image_url") or "").strip()
        cover = CoverBox(cover_url, 320, (180 if kind == "scene" else 240),
                         "⌖" if kind == "scene" else "▣",
                         badge=labels["cover_done"] if cover_url else labels["cover_todo"],
                         badge_state="ready" if cover_url else "todo",
                         tag_text=labels["cover_tag"],
                         on_click=on_open, pending=busy)
        lay.addWidget(cover)
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
        foot = QWidget()
        foot.setStyleSheet("border:none; border-top:1px solid rgba(128,128,128,0.18);")
        flay = QHBoxLayout(foot)
        flay.setContentsMargins(9, 7, 9, 8)
        flay.setSpacing(4)
        flay.addWidget(status_pill("ready" if has else "todo",
                                   labels["gen_done"] if has else labels["gen_todo"]))
        # 统一橙色 outline(品牌色 #f97316),hover 浅橙填充,与角色卡按钮同款。
        BTN_QSS = ("QPushButton{font-size:11px;padding:3px 4px;"
                   "border:1px solid #fed7aa;border-radius:6px;background:#fff8f1;color:#9a3412;}"
                   "QPushButton:hover{background:#fff0e1;border-color:#f97316;}"
                   "QPushButton:disabled{color:#c9cdd4;background:#f7f8fa;border-color:#e8eaef;}")
        gen_btns = []
        for text, tip, cb, enabled in (
            (labels["gen_text"], labels["gen_text_tip"], on_gen_text, True),
            (labels["gen_image"], labels["gen_image_tip"], on_gen_vary, True),
        ):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setMinimumWidth(0)
            b.setStyleSheet(BTN_QSS)
            b.setEnabled(enabled)
            if cb:
                b.clicked.connect(lambda _=False, c=cb: c())
            gen_btns.append((b, text))
            flay.addWidget(b, 1)
        up = QPushButton(labels["upload"])
        up.setToolTip(labels["upload_tip"])
        up.setCursor(Qt.PointingHandCursor)
        up.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        up.setMinimumWidth(0)
        up.setStyleSheet(BTN_QSS)
        if on_upload:
            up.clicked.connect(lambda _=False: on_upload())
        flay.addWidget(up, 1)
        if on_delete:
            # 浅红 outline,与生成按钮同款形但色不同(操作意图区分)
            dp = QPushButton(tr("delete"))
            dp.setToolTip(tr("删除该资产"))
            dp.setCursor(Qt.PointingHandCursor)
            dp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            dp.setMinimumWidth(0)
            dp.setStyleSheet(
                "QPushButton{font-size:11px;padding:3px 4px;"
                "border:1px solid #fecaca;border-radius:6px;background:#fff5f5;color:#b91c1c;}"
                "QPushButton:hover{background:#fee2e2;border-color:#ef4444;}")
            dp.clicked.connect(lambda _=False: on_delete())
            flay.addWidget(dp, 1)
        lay.addWidget(foot)
        _snug_card(self)
        apply_asset_busy(self, cover, gen_btns, busy)


def _click_to(widget, fn):
    """给 QLabel 挂左键点击(QLabel 默认不收鼠标事件)。"""
    orig = widget.mousePressEvent

    def handler(event):
        if event.button() == Qt.LeftButton:
            fn()
            return
        orig(event)
    return handler


class ComicAssetRow(QFrame):
    """漫画资产行:60px 缩略 + 名称 + 状态 + 生成漫画风按钮(对齐 .asset-comic-row)。

    pending=True 时缩略图位置用真 BrailleSpinner 旋转(替代之前静态字符 "⠋"
    看上去不变),与 CharacterAssetCard 保持一致;按钮全部用橙色 outline 文字
    按钮,与项目品牌色统一。
    """

    def __init__(self, thumb_url: str, name: str, ready: bool, pending: bool,
                 button_tip: str, on_gen, on_open=None, on_redo=None):
        super().__init__()
        self.setObjectName("assetCard")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(10)
        # 缩略图 60×44(原 44×44 太小);pending 显 BrailleSpinner
        if thumb_url:
            th = QLabel()
            th.setFixedSize(60, 44)
            th.setPixmap(W.pixmap_from_media(thumb_url, 60, 44))
            th.setStyleSheet("border-radius:6px;")
            if on_open:
                th.setCursor(Qt.PointingHandCursor)
                th.setToolTip(tr("preview"))
                th.mousePressEvent = _click_to(th, lambda: on_open(thumb_url))
        else:
            th = QWidget()
            th.setFixedSize(60, 44)
            th_v = QVBoxLayout(th)
            th_v.setContentsMargins(0, 0, 0, 0)
            th_v.setAlignment(Qt.AlignCenter)
            if pending:
                from .braille import BrailleSpinner
                self._sp = BrailleSpinner(color="#f97316", size=14, parent=th)
                th_v.addWidget(self._sp, 0, Qt.AlignCenter)
                self._sp.start("")
            else:
                ph = QLabel("+")
                ph.setAlignment(Qt.AlignCenter)
                ph.setObjectName("placeholderIcon")
                th_v.addWidget(ph)
        lay.addWidget(th)
        nm = QLabel(name)
        nm.setObjectName("muted")
        nm.setToolTip(name)
        lay.addWidget(nm, 1)
        text = tr("生成中") if pending else (tr("已生成") if ready else tr("待生成"))
        lay.addWidget(status_pill("pending" if pending else ("ready" if ready else "todo"), text))
        # 按钮横排:重画(已生成时显)+ 生成/重生(始终)
        # 用文字 + 橙色 outline,与其他资产卡同款风格
        BTN = ("QPushButton{font-size:11px;padding:3px 8px;"
               "border:1px solid #fed7aa;border-radius:6px;background:#fff8f1;color:#9a3412;}"
               "QPushButton:hover{background:#fff0e1;border-color:#f97316;}"
               "QPushButton:disabled{color:#c9cdd4;background:#f7f8fa;border-color:#e8eaef;}")
        if ready and on_redo:
            redo = QPushButton("⟳ " + tr("redraw"))
            redo.setToolTip(tr("redraw_tip") if tr("redraw_tip") else tr("redraw"))
            redo.setCursor(Qt.PointingHandCursor)
            redo.setStyleSheet(BTN)
            redo.clicked.connect(lambda _=False: on_redo())
            lay.addWidget(redo)
        if on_gen:
            if ready:
                label = tr("redraw")
            else:
                label = tr("gen_comic")
            gen_btn = QPushButton(label)
            gen_btn.setToolTip(button_tip)
            gen_btn.setCursor(Qt.PointingHandCursor)
            gen_btn.setStyleSheet(BTN)
            gen_btn.setEnabled(not pending)        # 生成中禁用防止重复点
            gen_btn.clicked.connect(lambda _=False: on_gen())
            lay.addWidget(gen_btn)


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
                 on_click=None, on_action=None, on_regen=None, on_approve=None,
                 image_status: str = "none"):
        super().__init__()
        self.setObjectName("taskRow")
        self._selected = selected
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
            self._thumb_label = im
        else:
            ph = W.icon_label("video", size=22)
            ph.setObjectName("videoThumbIcon")
            pl.addWidget(ph)
            self._thumb_label = ph
        idx = QLabel(f"#{index:02d}")
        idx.setObjectName("taskIndex")
        pl.addWidget(idx, 0, Qt.AlignLeft)
        lay.addWidget(prev)
        main = QVBoxLayout()
        main.setSpacing(1)
        # 名称/元信息超宽时截断(对齐参考 .video-task-name/.truncate),
        # 不把横向 minimum 撑给 236px 任务列,否则列表底部会顶出横向滚动条
        nm = QLabel(name)
        nm.setObjectName("taskName")
        nm.setToolTip(name)
        nm.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        main.addWidget(nm)
        mt = QLabel(meta)
        mt.setObjectName("taskMeta")
        mt.setToolTip(meta)
        mt.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        main.addWidget(mt)
        lay.addLayout(main, 1)
        # 操作区:图标键与旋转子两个宿主常驻,按状态切换可见性(set_state 可原地换态,
        # 批量进行中不重建整列也能让当前镜转起来)
        act_host = QWidget()
        act_host.setFixedSize(24, 24)
        al = QHBoxLayout(act_host)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(0)
        act = QPushButton()
        act.setToolTip(action_tip)
        act.setFixedSize(24, 24)
        act.setIcon(video_camera_icon(self.palette().color(QPalette.ButtonText)))
        act.setIconSize(QSize(15, 15))
        act.setEnabled(True)
        act.setCursor(Qt.PointingHandCursor)
        if on_action:
            # 点击瞬间:禁用按钮 + 切旋转图标,防止重复点击。
            # 后台 task 跑完由 set_state('done'/'ready') 重新启用。
            def _act_with_busy():
                act.setEnabled(False)
                self._spin.start("")
                self._spin.parentWidget().setVisible(True)
                self.act_btn.setVisible(False)
                on_action()
            act.clicked.connect(lambda _=False: _act_with_busy())
        spin_host = QWidget()
        spin_host.setFixedSize(24, 24)
        from .braille import BrailleSpinner
        _sl = QVBoxLayout(spin_host)
        _sl.setContentsMargins(0, 0, 0, 0)
        _spin = BrailleSpinner(color="#f97316", size=9, parent=spin_host)
        _sl.addWidget(_spin)
        al.addWidget(act)
        al.addWidget(spin_host)
        # 首帧预审:pending_review 时显示 ✓ 确认出视频;always 显示 ⟳ 重生首帧
        if on_regen:
            rg = QPushButton("⟳")
            rg.setFixedSize(22, 22)
            rg.setToolTip(tr("重新生成首帧"))
            rg.setCursor(Qt.PointingHandCursor)
            rg.setStyleSheet("QPushButton{font-size:11px;padding:0;}")
            # 重生首帧:点击后禁用,等 set_state 回来恢复
            def _rg_with_busy():
                rg.setEnabled(False)
                on_regen()
            rg.clicked.connect(lambda _=False: _rg_with_busy())
            lay.addWidget(rg)
            self._rg_btn = rg  # 留给 _apply_state 在非 pending 时启用
        if on_approve and image_status == "pending_review":
            ap = W.svg_icon_btn("check", tr("确认出视频"), size=22)
            ap.setStyleSheet(
                "QPushButton{background:#16a34a;color:#fff;border:none;"
                "border-radius:5px;font-weight:700;font-size:12px;padding:0;}")
            # 确认出视频:点击后禁用,等 set_state 回来恢复
            def _ap_with_busy():
                ap.setEnabled(False)
                on_approve()
            ap.clicked.connect(lambda _=False: _ap_with_busy())
            lay.addWidget(ap)
            self._ap_btn = ap  # 留给 _apply_state 在非 pending 时启用
        lay.addWidget(act_host)
        self.act_btn = act
        self._spin = _spin
        self._apply_state(state)
        self.setCursor(Qt.PointingHandCursor)
        if on_click:
            self.mousePressEvent = lambda _e: on_click()

    def _apply_state(self, state: str):
        pending = state == "pending"
        self.act_btn.setVisible(not pending)
        self.act_btn.setEnabled(not pending)
        # 点击瞬间已被禁用,任务跑完 set_state 来恢复 + 重启按钮
        if hasattr(self, "_rg_btn"):
            self._rg_btn.setEnabled(not pending)
        if hasattr(self, "_ap_btn"):
            self._ap_btn.setEnabled(not pending)
        if pending:
            self._spin.start("")
        else:
            self._spin.stop()
        self._spin.parentWidget().setVisible(pending)
        self.setProperty("state", "selected" if self._selected else state)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_state(self, state: str, state_label: str, meta: str | None = None,
                  thumb_url: str | None = None):
        """批量进行中原地换态:pending↔图标键 + 状态样式 + 元信息行,不重建列表。"""
        self._state = state
        self._state_label = state_label
        if meta is not None:
            self._meta = meta
            for lab in self.findChildren(QLabel):
                if lab.objectName() == "taskMeta":
                    lab.setText(meta)
                    lab.setToolTip(meta)
        if thumb_url and thumb_url != self._thumb:
            self._thumb = thumb_url
        self._apply_state(state)

    def refresh_thumb(self, thumb_url: str | None):
        """海报帧补抽完成后原地换缩略图,不用重建整列(保住滚动位置)。"""
        lab = getattr(self, "_thumb_label", None)
        if lab is None or not thumb_url or thumb_url == self._thumb:
            return
        self._thumb = thumb_url
        lab.setObjectName("")           # 从 🎬 占位切成图片
        lab.setPixmap(W.pixmap_from_media(thumb_url, 56, 32))
        lab.setToolTip(thumb_url)

    def refresh(self, thumb_url: str | None = None):
        """原地更新缩略图与状态,避免整列重建导致滚动位置跳回顶部。"""
        if thumb_url is not None and thumb_url != self._thumb:
            self._thumb = thumb_url
        self.setProperty("state", "selected" if False else self._state)
        self.style().unpolish(self)
        self.style().polish(self)


class RefCard(QFrame):
    """参考素材卡:缩略(或「角/景/具」占位)+ 名称 + 类型/变体 + 绑定状态。

    整卡点击切换绑定(star prop 风格)—— 已绑定态用橙色 2px 描边
    (用户要求「选中的资产用橙框」,对齐参考项目已绑/未绑的视觉区分)。
    """

    def __init__(self, url: str | None, placeholder: str, name: str, meta: str,
                 state: str, on_click=None, on_generate=None, on_toggle=None):
        super().__init__()
        self.setObjectName("refCard")
        if on_toggle:
            self.setCursor(Qt.PointingHandCursor)
            self.mousePressEvent = lambda _e: on_toggle()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(3)
        if url:
            im = QLabel()
            im.setMinimumHeight(110)
            im.setAlignment(Qt.AlignCenter)
            # 按卡片显示宽度的富余分辨率加载(参考素材卡 ~300px 宽)
            im.setPixmap(W.pixmap_from_media(url, 480, 360))
            im.setScaledContents(True)
            # 高度必须跟随宽度按图片纵横比联动(heightForWidth),否则卡片被拉宽时
            # setScaledContents 只横向拉伸 → 道具等宽图变形(参考项目为瀑布流自然比例)
            sp = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            sp.setHeightForWidth(True)
            im.setSizePolicy(sp)
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


class VideoHistoryCard(QFrame):
    """历史视频卡:96×54 抽帧缩略 + 时间 + 当前/预览角标 + 下载/删除键
    (对齐参考项目 .video-history-item)。"""

    def __init__(self, thumb_path: str | None, time_label: str, *, current: bool = False,
                 previewing: bool = False, on_preview=None, on_download=None, on_delete=None):
        super().__init__()
        self.setObjectName("videoHistoryCard")
        self.setProperty("current", "1" if current else "0")
        self.setProperty("previewing", "1" if previewing else "0")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(3)
        im = QLabel()
        im.setFixedSize(96, 54)
        im.setAlignment(Qt.AlignCenter)
        if thumb_path and Path(thumb_path).exists():
            im.setPixmap(W.pixmap_cover_media(thumb_path, 96, 54))
        else:
            _ic = W.svg_icon("video", size=22)
            if not _ic.isNull():
                im.setPixmap(_ic.pixmap(22, 22))
            im.setObjectName("videoThumbIcon")
        lay.addWidget(im)
        foot = QHBoxLayout()
        foot.setSpacing(2)
        badge = QLabel(time_label)
        badge.setObjectName("historyTime"
                            if not (current or previewing) else "historyBadge")
        if current:
            badge.setText(f"{time_label} · ✓")
        elif previewing:
            badge.setText(f"{time_label} · ◉")
        foot.addWidget(badge)
        foot.addStretch(1)
        # 纯图标(文字挪 tooltip):原先用 '↓' / '×' 字符,16×16 固定尺寸撞上全局
        # QPushButton 的 padding:6px 14px,内容区被挤没,按钮渲染成一片空白
        # (实测改前只有 1 种颜色=纯背景)。改用 Qt 原生图标,同 main_window 任务键。
        from PySide6.QtWidgets import QStyle
        dl = W.icon_btn(QStyle.StandardPixmap.SP_ArrowDown, tr("download"),
                        fallback="↓")
        if on_download:
            dl.clicked.connect(lambda _=False: on_download())
        foot.addWidget(dl)
        de = W.icon_btn(QStyle.StandardPixmap.SP_TrashIcon, tr("delete"),
                        fallback="×")
        if on_delete:
            de.clicked.connect(lambda _=False: on_delete())
        foot.addWidget(de)
        lay.addLayout(foot)
        if on_preview:
            self.mousePressEvent = lambda _e: on_preview()


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
    """漫画格卡:3:4 缩略 + 序号 + 描述/台词/构图 + 旁白说明框 + 错误 + 出图提示词 + 绑定资产缩略。"""

    def __init__(self, row: dict, labels: dict, *, busy: bool = False, failed: str = "",
                 on_draw=None, on_open=None, on_narration_save=None, on_erase=None,
                 on_bind=None, on_jump=None, bound_assets: list[dict] | None = None,
                 similar_to: list[dict] | None = None):
        super().__init__()
        self.setObjectName("comicCard")
        self._panel_id = int(row.get("id") or 0)
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
            if busy:
                # 动态旋转的盲文 spinner(替代之前只渲染静态 "⠋" 字符,
                # 那样看上去永远不变,用户误以为批量卡住)。start() 启动 90ms
                # 一次的帧循环,busy=True 进来直接转,reload_comic 重渲染时
                # 也会跟着 busy_ids 集合重新激活。
                from .braille import BrailleSpinner
                spin_host = QWidget()
                spin_host.setFixedSize(36, 36)
                _sl = QVBoxLayout(spin_host)
                _sl.setContentsMargins(0, 0, 0, 0)
                self._busy_spin = BrailleSpinner(color="#f97316", size=18, parent=spin_host)
                self._busy_spin.start("")
                _sl.addWidget(self._busy_spin)
                cl2.addWidget(spin_host, 0, Qt.AlignCenter)
            else:
                ph = QLabel("▣")
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
            # 右上双角标:⟳ 重绘 / 🩹 擦除(局部重绘,对齐参考 ecda917)
            corner = QHBoxLayout()
            corner.setSpacing(4)
            from PySide6.QtWidgets import QStyle
            redo = W.icon_btn(QStyle.StandardPixmap.SP_BrowserReload, labels["redraw"],
                            size=24, fallback="⟳")
            redo.clicked.connect(lambda _=False: on_draw() if on_draw else None)
            corner.addWidget(redo)
            if on_erase:
                er = W.icon_btn(QStyle.StandardPixmap.SP_DialogResetButton,
                                tr("擦除漫画格"), size=24, fallback="🩹")
                er.clicked.connect(lambda _=False: on_erase())
                corner.addWidget(er)
            corner_wrap = QWidget()
            corner_wrap.setLayout(corner)
            tg.addWidget(corner_wrap, 0, 0, Qt.AlignRight | Qt.AlignTop)
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
        # 绑定资产缩略 + 「+资产」按钮(便于用户手动改自动绑定的结果)
        if on_bind:
            br = QHBoxLayout()
            br.setSpacing(4)
            br.setContentsMargins(0, 0, 0, 0)
            for a in (bound_assets or []):
                chip = QLabel()
                chip.setFixedSize(28, 28)
                chip.setToolTip(f"{a.get('kind','?')} · {a.get('name') or ''}")
                u = (a.get("comic_image_url") or a.get("image_url") or "").strip()
                if u:
                    chip.setPixmap(W.pixmap_from_media(u, 56, 56))
                chip.setStyleSheet("border:1px solid #d4d2cb; border-radius:4px; background:#fff;")
                br.addWidget(chip)
            br.addStretch(1)
            bb = QPushButton("+ " + tr("bind_panel_assets"))
            bb.setObjectName("bindBtn")
            bb.setCursor(Qt.PointingHandCursor)
            bb.clicked.connect(lambda _=False: on_bind())
            br.addWidget(bb)
            bl.addLayout(br)
        # 描述雷同警告:和前序某格相似度 ≥ 阈值时,出图容易撞脸,提示用户
        # 处理。可点 chip 跳过去比对,或者点 ↻ 重抽只这一格。
        if similar_to:
            for s in similar_to:
                wr = QHBoxLayout()
                wr.setSpacing(4)
                wr.setContentsMargins(0, 0, 0, 0)
                warn = QLabel(f"⚠ 与 #{int(s['other_number']):02d} 描述相似度 {int(round(float(s['score']) * 100))}%")
                warn.setObjectName("dupWarn")
                warn.setStyleSheet(
                    "color:#b45309; background:#fef3c7; border:1px solid #fcd34d;"
                    "border-radius:3px; padding:3px 6px; font-size:11px;")
                warn.setToolTip("画面/构图高度雷同,直接出图会撞。点下面跳转对比,或重抽只这一格。")
                wr.addWidget(warn, 1)
                if on_jump:
                    jb = QPushButton("↗ 跳转")
                    jb.setObjectName("dupJump")
                    jb.setStyleSheet("color:#b45309; background:transparent; border:none; font-size:11px;")
                    jb.setCursor(Qt.PointingHandCursor)
                    jb.clicked.connect(lambda _=False, oid=s["other_id"]: on_jump(oid))
                    wr.addWidget(jb)
                if on_draw:
                    reroll = QPushButton("↻ 重抽")
                    reroll.setObjectName("dupReroll")
                    reroll.setStyleSheet("color:#b45309; background:transparent; border:none; font-size:11px;")
                    reroll.setCursor(Qt.PointingHandCursor)
                    reroll.clicked.connect(lambda _=False: on_draw())
                    wr.addWidget(reroll)
                bl.addLayout(wr)
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