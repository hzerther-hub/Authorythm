# -*- coding: utf-8 -*-
"""PhotoCraft 聊天修图侧栏:右侧抽屉 + 气泡 + 双引擎(白名单 + LLM)。

打开抽屉 → 加载图(本地图/远程 URL) → 输入中文 → 引擎命中 → 渲染产物。
会话存 SQLite(`chat_edit_sessions` / `chat_edit_messages`)以便恢复。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLayout, QLineEdit,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QToolButton,
    QVBoxLayout, QWidget,
)

from ..ai.photocraft_bridge import ChatEditEngine, Step
from ..core import db
from ..core.i18n import tr
from ..core import taskmgr as _TM
from . import widgets as W


# ── 气泡 ──

class ChatEditMessage(QFrame):
    """单条消息气泡 —— 用户/助手两种风格。"""

    def __init__(self, role: str, content: str, steps: list[Step] | None = None,
                 result_image: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.role = role
        self._steps = steps or []
        self._result_image = result_image
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        is_user = role == "user"

        # 头像
        avatar = W.avatar("你" if is_user else "P", size=28)
        lay.addWidget(avatar, 0, Qt.AlignTop)

        # 气泡内容
        body = QFrame()
        body.setObjectName("chatBubbleUser" if is_user else "chatBubbleAssistant")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(10, 8, 10, 8)
        bl.setSpacing(6)

        # 顶部标签
        tag_lab = W.muted(tr("chat_edit_msg_user") if is_user else tr("chat_edit_msg_assistant"))
        tag_lab.setStyleSheet("font-weight:600;")
        bl.addWidget(tag_lab)

        # 主文本
        text = QLabel(content or "")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text.setStyleSheet("font-size:13px; line-height:1.5;")
        bl.addWidget(text)

        # 助手:执行的命令
        if not is_user and self._steps:
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color:rgba(128,128,128,80);")
            sep.setFixedHeight(1)
            bl.addWidget(sep)
            lab = W.muted(tr("chat_edit_msg_steps"))
            bl.addWidget(lab)
            _step_labels = []
            for step in self._steps:
                line_lab = QLabel(f"• `{step.cmd}`" + (f"  {step.params}" if step.params else "")
                                  + (f"  — {step.reason}" if step.reason else ""))
                line_lab.setWordWrap(True)
                line_lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
                line_lab.setStyleSheet(
                    "font-family:Consolas,Menlo,monospace; font-size:11px;"
                    " background:rgba(0,0,0,28); padding:2px 6px; border-radius:3px;")
                bl.addWidget(line_lab)
                _step_labels.append(line_lab)

        # 助手:结果图
        if not is_user and self._result_image and Path(self._result_image).exists():
            bl.addSpacing(2)
            im = QLabel()
            im.setAlignment(Qt.AlignCenter)
            im.setStyleSheet(
                "border:1px solid rgba(128,128,128,160); border-radius:6px;"
                " background:#fafafa; padding:4px;")
            im.setPixmap(W.pixmap_from_media(self._result_image, 320, 320))
            im.setToolTip(self._result_image)
            im.setCursor(Qt.PointingHandCursor)
            im.mousePressEvent = lambda _e, p=self._result_image: self._view_large(p)
            bl.addWidget(im)

        # 气泡宽度按内容自适应(用户反馈「聊天长度要自动变宽,不要写死」):
        #   - 固定宽度会让短句拉成整行宽,右侧一大片空白
        #   - 自适应 + 上限 72% 是聊天常规做法:短句贴边,长句才折行
        #   - stretch=0 让 QLabel 走 sizeHint(文本自然宽度);MaximumWidth 在
        #     resizeEvent 里按父宽比例刷新,窗口缩放时上限跟着变
        # 注意:不要用 QLayout.SetMinAndMaxSize —— 它把气泡锁死在 QLabel 的
        # minimumWidth 上,中文逐字折行(「去掉图片」/「上的文字」各一行)。
        # 这里只给 MinimumSize,让 sizeHint(= 文本单行自然宽度)决定实际宽度。
        from PySide6.QtWidgets import QSizePolicy
        bl.setSizeConstraint(QLayout.SetMinimumSize)
        body.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self._body = body
        # (label, 原始文本) —— _apply_bubble_width 要用文本内容重新量自然宽
        pairs = [(text, content or "")]
        if not is_user and self._steps:
            for lab, step in zip(_step_labels, self._steps):
                pairs.append((lab, f"• `{step.cmd}`"
                                   + (f"  {step.params}" if step.params else "")
                                   + (f"  — {step.reason}" if step.reason else "")))
        self._wrap_labels = pairs
        for lab, _raw in pairs:
            lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            lab.setMinimumWidth(0)
            lab.setMaximumWidth(9999)     # 初始不限,resizeEvent 里按比例压
        self._img_label = None

        lay.addWidget(body, 0, Qt.AlignTop)
        # 用户消息右对齐:左边留 stretch;助手左对齐:右边留 stretch
        if is_user:
            lay.insertStretch(0, 1)
        else:
            lay.addStretch(1)

    def _bubble_max_w(self) -> int:
        """气泡最大宽度 = 聊天区可视宽的 72%。

        **不能**用 self.parentWidget().width():用户消息被包在一个 wrap QFrame 里
        (右对齐用),而 wrap 的宽度又由 msg 的 sizeHint 决定 —— 互相依赖,实测两边
        一起塌到最小值,气泡变成一条竖条、中文逐字折行(见 _append_message_widget)。
        这里向上找真正的聊天区容器(_hist_host)或退回 self.width()。
        """
        node = self
        while node is not None:
            if getattr(node, "objectName", lambda: "")() == "chatHistHost":
                w = node.width()
                if w > 0:
                    return max(240, int(w * 0.72))
            node = node.parentWidget()
        avail = self.width()
        return max(240, int(avail * 0.72)) if avail > 0 else 520

    def resizeEvent(self, e):
        """父宽变化时同步刷新气泡宽度上限。"""
        super().resizeEvent(e)
        self._apply_bubble_width()

    def _apply_bubble_width(self):
        """按当前聊天区宽度重算气泡尺寸。

        关键:文本 label 的自然宽**不能用 sizeHint()** —— QLabel 开了 wordWrap 后,
        sizeHint 返回的是「在当前宽度约束下需要多少高」的推算值,会随布局逐轮收窄,
        实测最后塌成一个字宽(中文逐字折行)。这里用 QFontMetrics.horizontalAdvance
        直接量文本单行像素宽,这是稳定的。
        """
        from PySide6.QtGui import QFontMetrics
        cap = self._bubble_max_w()
        b = getattr(self, "_body", None)
        if b is not None:
            b.setMaximumWidth(cap + 24)   # +内边距(10×2)+边框(1×2)
        for lab, raw in getattr(self, "_wrap_labels", []):
            lab.setMaximumWidth(cap)
            fm = QFontMetrics(lab.font())
            # 逐行量,取最长那行(命令列表可能多行);上限 cap,超出就折行
            natural = max((fm.horizontalAdvance(ln) for ln in raw.splitlines()),
                          default=0)
            lab.setMinimumWidth(min(natural + 2, cap))   # +2 抗字形右缘截断

    def showEvent(self, e):
        """首次显示时也要刷一次 —— 此时父容器才刚拿到真实宽度。"""
        super().showEvent(e)
        self._apply_bubble_width()

    def _view_large(self, path: str):
        from .asset_dialogs import ImageViewerDialog
        ImageViewerDialog(self, path, Path(path).name).exec()


# ── 面板 ──

class ChatEditPanel(QWidget):
    """聊天面板主体。

    Signals:
        imageSaved(str) — 用户点「保存到结果区」时 emit,带新产物路径
        needSettings() — 需要跳到设置时 emit
        openDesktopApp() — 用户点「打开桌面端」emit
    """

    imageSaved = Signal(str)
    needSettings = Signal()
    openDesktopApp = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine = ChatEditEngine()
        self._session_id: int | None = None
        self._source_image: str | None = None      # 用户原图(撤回终点)
        self._current_image: str | None = None     # 当前产物(下一轮的输入)
        self._history: list[dict] = []
        self._busy = False
        self._pc_watcher = None                    # PhotoCraftWatcher,首次启动时建
        self._build()
        self._refresh_status()
        self._reload_sessions()

    # ── UI ──
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)

        # 顶部:标题 + 引擎状态 + 桌面端按钮
        top = QHBoxLayout()
        top.setSpacing(6)
        title = W.h2(tr("chat_edit_panel"))
        top.addWidget(title)
        top.addStretch(1)
        manual_btn = QPushButton("✋ " + tr("chat_edit_manual"))
        manual_btn.setObjectName("primary")
        manual_btn.setCursor(Qt.PointingHandCursor)
        manual_btn.setToolTip(tr("chat_edit_manual_tip"))
        manual_btn.clicked.connect(self._start_manual_edit)
        self.manual_btn = manual_btn
        top.addWidget(manual_btn)
        desktop_btn = W.svg_icon_btn("open_external", "打开 PhotoCraft 桌面端", size=26)
        desktop_btn.clicked.connect(self._open_desktop)
        top.addWidget(desktop_btn)
        settings_btn = W.svg_icon_btn("settings", tr("chat_edit_to_settings"), size=26)
        settings_btn.clicked.connect(self.needSettings.emit)
        top.addWidget(settings_btn)
        root.addLayout(top)

        self.status_lab = W.muted("")
        self.status_lab.setStyleSheet("font-size:11px;")
        root.addWidget(self.status_lab)

        # 未配置时的内嵌配置入口(替代下面整张工作台 —— 抽屉本身就是稀缺空间,
        # 让 ta 先配通 CLI 才能继续聊)
        self.config_card = W.make_card()
        cc_lay = QVBoxLayout(self.config_card)
        cc_lay.setContentsMargins(12, 10, 12, 10)
        cc_lay.setSpacing(6)
        cc_title = W.h2(tr("chat_edit_setup_title"))
        cc_lay.addWidget(cc_title)
        cc_lay.addWidget(W.muted(tr("chat_edit_cli_missing")))
        cc_dir_row = QHBoxLayout()
        cc_dir_row.setSpacing(4)
        self.cc_dir_edit = QLineEdit()
        from ..core import db as _db
        from ..core import config as _cfg
        self.cc_dir_edit.setText(_db.get_setting("photocraft_install_dir", "") or _cfg.DEFAULT_PHOTOCRAFT_DIR)
        self.cc_dir_edit.setPlaceholderText("例如 E:\\photocraft\\photocraft-0.7.0-windows-x64-portable")
        cc_dir_row.addWidget(self.cc_dir_edit, 1)
        b_pick = QPushButton("…")
        b_pick.setFixedWidth(28)
        b_pick.setCursor(Qt.PointingHandCursor)
        b_pick.clicked.connect(self._cc_pick_dir)
        cc_dir_row.addWidget(b_pick)
        cc_lay.addLayout(cc_dir_row)
        cc_btn_row = QHBoxLayout()
        cc_btn_row.setSpacing(6)
        cc_btn_row.addStretch(1)
        b_open_dir = QPushButton(tr("chat_edit_open_install_dir"))
        b_open_dir.setCursor(Qt.PointingHandCursor)
        b_open_dir.clicked.connect(self._cc_open_dir)
        cc_btn_row.addWidget(b_open_dir)
        b_test = W.primary_btn(tr("chat_edit_test_cli"))
        b_test.clicked.connect(self._cc_test_cli)
        cc_btn_row.addWidget(b_test)
        cc_lay.addLayout(cc_btn_row)
        self.cc_status = W.muted("")
        cc_lay.addWidget(self.cc_status)
        root.addWidget(self.config_card)

        # 当前图像 + 加载/重置
        cur_row = QHBoxLayout()
        cur_row.setSpacing(8)
        self.thumb = QLabel()
        self.thumb.setFixedSize(96, 72)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet(
            "border:1px dashed rgba(128,128,128,160); border-radius:6px;"
            " background:#f7f8fa; color:#94a3b8; font-size:11px;")
        self.thumb.setText(tr("chat_edit_no_image"))
        # 点击缩略图放大查看(同 ChatEditMessage 的图片气泡)
        self.thumb.setCursor(Qt.PointingHandCursor)
        self.thumb.setToolTip("点击查看大图")
        self.thumb.mousePressEvent = lambda _e: self._view_thumb()
        cur_row.addWidget(self.thumb)
        cur_row.addSpacing(4)
        col = QVBoxLayout()
        col.setSpacing(4)
        path_lab_row = QHBoxLayout()
        path_lab_row.setSpacing(4)
        path_lab_row.addWidget(W.muted(tr("chat_edit_install_dir") + ":"))
        self.path_lab = W.muted("")
        self.path_lab.setStyleSheet("font-size:10px; color:#64748b;")
        path_lab_row.addWidget(self.path_lab, 1)
        col.addLayout(path_lab_row)
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        b_pick = QPushButton(tr("u_add"))
        b_pick.setObjectName("primary")
        b_pick.setCursor(Qt.PointingHandCursor)
        b_pick.clicked.connect(self._pick_image)
        row2.addWidget(b_pick)
        b_reset = QPushButton(tr("chat_edit_reset"))
        b_reset.setCursor(Qt.PointingHandCursor)
        b_reset.clicked.connect(self._reset_current)
        self.reset_btn = b_reset
        row2.addWidget(b_reset)
        col.addLayout(row2)
        col.addStretch(1)
        cur_row.addLayout(col, 1)
        root.addLayout(cur_row)

        # 会话切换
        sess_row = QHBoxLayout()
        sess_row.setSpacing(6)
        sess_row.addWidget(W.muted(tr("chat_edit_session_list") + ":"))
        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(140)
        self.session_combo.currentIndexChanged.connect(self._on_session_changed)
        sess_row.addWidget(self.session_combo, 1)
        b_new = QPushButton(tr("chat_edit_session_new"))
        b_new.setCursor(Qt.PointingHandCursor)
        b_new.clicked.connect(self._new_session)
        sess_row.addWidget(b_new)
        b_del = QPushButton(tr("u_delete"))
        b_del.setCursor(Qt.PointingHandCursor)
        b_del.setObjectName("danger")
        b_del.clicked.connect(self._delete_session)
        sess_row.addWidget(b_del)
        root.addLayout(sess_row)

        # 历史滚动区
        self.hist_host = QWidget()
        self.hist_host.setObjectName("chatHistHost")   # 气泡靠它算宽度上限
        self.hist_lay = QVBoxLayout(self.hist_host)
        self.hist_lay.setContentsMargins(0, 0, 0, 0)
        self.hist_lay.setSpacing(8)
        self.hist_lay.addStretch(1)
        self.empty_lab = W.muted(tr("chat_edit_no_image"))
        self.hist_lay.insertWidget(0, self.empty_lab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(self.hist_host)
        scroll.setStyleSheet("QScrollArea{background:transparent;} QWidget{background:transparent;}")
        root.addWidget(scroll, 1)
        self._scroll = scroll

        # 底部:输入框 + 发送 + 保存
        bot = QHBoxLayout()
        bot.setSpacing(6)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("例如:改成黑白 / 亮度+30 / 高斯模糊 5")
        self.input.setFixedHeight(64)
        self.input.setStyleSheet("font-size:13px;")
        bot.addWidget(self.input, 1)
        send_col = QVBoxLayout()
        send_col.setSpacing(4)
        self.send_btn = QPushButton(tr("chat_edit_send"))
        self.send_btn.setObjectName("primary")
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setFixedHeight(32)
        self.send_btn.clicked.connect(self._send)
        send_col.addWidget(self.send_btn)
        self.save_btn = QPushButton(tr("chat_edit_save_to_main"))
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setFixedHeight(28)
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_to_main)
        send_col.addWidget(self.save_btn)
        bot.addLayout(send_col)
        root.addLayout(bot)

        self.input.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Ctrl+Enter 直接发送(Enter 只换行,贴近聊天惯例)。"""
        if obj is self.input and event.type() == event.Type.KeyPress:
            from PySide6.QtGui import QKeyEvent
            if isinstance(event, QKeyEvent) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ControlModifier:
                    self._send()
                    return True
        return super().eventFilter(obj, event)

    # ── 状态 ──
    def _refresh_status(self):
        ok, txt = self._engine.status_text()
        self.status_lab.setText(txt)
        from ..ai.photocraft_bridge import resolve_cli_path
        path = resolve_cli_path()
        self.path_lab.setText(path or "(未配置)")
        self.send_btn.setEnabled(ok and self._current_image is not None and not self._busy)
        # 未配 → 只显示内嵌配置卡;配了 → 正常图像工作台
        self.config_card.setVisible(not ok)
        # 未配时把手动 / 桌面端 / 输入区都禁用,避免用户点空炮
        self.manual_btn.setEnabled(ok)
        for w in (self.input, self.save_btn):
            w.setEnabled(ok and self._current_image is not None)

    def set_engine_mode(self, mode: str):
        """更新引擎模式(由设置对话框写入后回调)。"""
        # 不存 state,每次取最新
        pass

    # ── 会话 ──
    def _reload_sessions(self):
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItem("(当前会话)", None)
        for s in db.list_chat_sessions(50):
            label = Path(s["source_image"]).name or "image"
            self.session_combo.addItem(f"#{s['id']} · {label}", s["id"])
        self.session_combo.blockSignals(False)

    def _on_session_changed(self, _idx):
        sid = self.session_combo.currentData()
        if sid is None:
            return
        self.load_session(sid)

    def load_session(self, sid: int):
        sess = db.get_chat_session(sid)
        if not sess:
            return
        self._session_id = sid
        self._source_image = sess["source_image"]
        self._current_image = sess["current_image"]
        self._render_thumb()
        self._history = []
        # 渲染历史
        self._clear_messages()
        for m in db.load_chat_messages(sid):
            steps_raw = m.get("command_json") or ""
            steps: list[Step] = []
            if steps_raw:
                try:
                    arr = json.loads(steps_raw)
                    steps = [Step(**s) for s in arr if isinstance(s, dict) and s.get("cmd")]
                except Exception:  # noqa: BLE001
                    pass
            self._append_message_widget(m["role"], m["content"], steps, m.get("result_image"),
                                       scroll=False)
        self._refresh_status()

    def _new_session(self):
        # 当前图变成新会话的原图
        src = self._current_image or self._source_image
        if not src:
            self.status_lab.setText(tr("chat_edit_no_image"))
            return
        sid = db.create_chat_session(src, engine_mode="")
        self._reload_sessions()
        # 选中新会话
        for i in range(self.session_combo.count()):
            if self.session_combo.itemData(i) == sid:
                self.session_combo.setCurrentIndex(i)
                break
        self._session_id = sid
        self._source_image = src
        self._current_image = src
        self._history = []
        self._clear_messages()
        self._render_thumb()

    def _delete_session(self):
        sid = self._session_id or self.session_combo.currentData()
        if not sid:
            return
        db.delete_chat_session(sid)
        self._reload_sessions()
        if self._session_id == sid:
            self._session_id = None
            self._clear_messages()

    # ── 图片 ──
    def _pick_image(self):
        from .image_process_page import IMG_EXTS  # 复用常量
        path, _ = QFileDialog.getOpenFileName(
            self, tr("chat_edit_install_dir"), "",
            f"Images ({' '.join('*' + e for e in IMG_EXTS)})")
        if not path:
            return
        self.set_image(path)

    def set_image(self, path: str, auto_new_session: bool = True):
        """外部入口(图片处理页传入)。auto_new_session=True 时若无会话就建一个。"""
        if auto_new_session and not self._session_id:
            sid = db.create_chat_session(path, engine_mode="")
            self._session_id = sid
            self._reload_sessions()
            for i in range(self.session_combo.count()):
                if self.session_combo.itemData(i) == sid:
                    self.session_combo.setCurrentIndex(i)
                    break
        elif self._session_id:
            # 已存在会话:把这张图作为新分支起点
            db.touch_chat_session(self._session_id, current_image=path)
        if not self._session_id:
            self._source_image = path
        self._current_image = path
        self._render_thumb()
        self._refresh_status()

    def _reset_current(self):
        if not self._source_image:
            return
        self._current_image = self._source_image
        if self._session_id:
            db.touch_chat_session(self._session_id, current_image=self._source_image)
            # 也清掉当前会话里「撤回」之后的历史(简化:删从 source 之后的助手消息)
            msgs = db.load_chat_messages(self._session_id)
            keep_id = 0
            for m in msgs:
                if m["role"] == "user":
                    keep_id = m["id"]
            db.delete_chat_messages_after(self._session_id, keep_id)
        self._history = []
        self._clear_messages()
        self._render_thumb()
        self._save_btn_refresh()

    def _render_thumb(self):
        if not self._current_image or not Path(self._current_image).exists():
            self.thumb.setText(tr("chat_edit_no_image"))
            self.thumb.setPixmap(QPixmap())
            self.save_btn.setEnabled(False)
            return
        pm = W.pixmap_from_media(self._current_image, 96, 72)
        self.thumb.setPixmap(pm)
        self.thumb.setText("")
        # 保存到结果区按钮:仅当「当前图 != 原图」时启用
        self._save_btn_refresh()

    def _view_thumb(self):
        """点击顶部缩略图 → 弹出大图查看器(复用 ImageViewerDialog)。

        与 ChatEditMessage 气泡里的图片点击同套机制,行为一致。
        """
        if not self._current_image or not Path(self._current_image).exists():
            return
        from .asset_dialogs import ImageViewerDialog
        ImageViewerDialog(self, self._current_image,
                          Path(self._current_image).name).exec()

    def _save_btn_refresh(self):
        enable = (self._current_image is not None
                  and self._current_image != self._source_image
                  and Path(self._current_image).exists())
        self.save_btn.setEnabled(bool(enable))

    # ── 消息历史渲染 ──
    def _clear_messages(self):
        while self.hist_lay.count():
            it = self.hist_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.hist_lay.addStretch(1)

    def _append_message_widget(self, role: str, content: str,
                              steps: list[Step] | None,
                              result_image: Optional[str],
                              scroll: bool = True):
        # 去掉底部 stretch 再插,插完再加回
        stretch = self.hist_lay.takeAt(self.hist_lay.count() - 1).widget()
        msg = ChatEditMessage(role, content, steps=steps, result_image=result_image, parent=self.hist_host)
        if role == "user":
            # 右对齐:用 spacer 推右
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addStretch(1)
            row.addWidget(msg)
            wrap = QFrame()
            wrap.setLayout(row)
            self.hist_lay.addWidget(wrap)
        else:
            self.hist_lay.addWidget(msg)
        self.hist_lay.addStretch(1)
        if stretch:
            stretch.deleteLater()
        if scroll:
            QTimer.singleShot(0, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ── 发送 ──
    def _send(self):
        if self._busy:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        if not self._current_image or not Path(self._current_image).exists():
            self.status_lab.setText(tr("chat_edit_msg_image_missing"))
            return
        if not self._engine.ready:
            self.status_lab.setText(tr("chat_edit_cli_missing"))
            return

        # 显示用户气泡
        self._append_message_widget("user", text, None, None)
        self.input.clear()
        self._set_busy(True)

        # 决定引擎模式
        from ..core import db as _db
        mode = _db.get_setting("chat_edit_engine_mode", "smart") or "smart"
        llm_id_raw = _db.get_setting("chat_edit_llm_config_id", "")
        llm_id = int(llm_id_raw) if llm_id_raw.isdigit() else None

        # 在线程里跑:解释 → 应用 → 保存 → 渲染
        in_path = self._current_image
        sess_id = self._session_id

        def job(tid):
            # ── 批量:分析 → N 个方案 → 逐个执行 ──
            # 用户说「先分析...再 N 个方案分别执行」时走这里:LLM 看图给 N 个
            # 单条可执行 prompt,然后每个 prompt 都当独立 user_text 跑一遍单步
            # 逻辑(复用 _execute_single)。结果以 {"kind": "batch", "results":[...]}
            # 回给 done 回调,UI 拆成多个气泡显示。
            from ..ai.photocraft_bridge import (_wants_batch_analysis,
                                                 _wants_batch_n, analyze_and_plan)
            if _wants_batch_analysis(text):
                n = _wants_batch_n(text)
                analysis, plans, err = analyze_and_plan(
                    str(in_path), text, n=n, config_id=llm_id)
                if err:
                    return {"error": err, "user_text": text,
                            "engine_label": "planner"}
                if not plans:
                    return {"empty": True,
                            "note": "LLM 没规划出可执行方案,试试换个说法。",
                            "user_text": text}
                results: list[dict] = []
                # 1) 构图分析(独立气泡)
                results.append({
                    "kind": "analysis",
                    "content": (f"📊 **构图分析**\n\n{analysis}"
                                if analysis else "📊 **构图分析**(空)"),
                    "image": str(in_path),
                })
                # 2) 每个方案:复用单步执行
                for plan in plans:
                    single = self._execute_single(
                        plan["prompt"], str(in_path), sess_id,
                        llm_id, mode, tid)
                    single["plan"] = plan
                    results.append(single)
                return {"kind": "batch", "results": results,
                        "user_text": text}

            # ── 单步(文字编辑 / PhotoCraft CLI) ──
            return self._execute_single(
                text, str(in_path), sess_id, llm_id, mode, tid)

        def done(tid, result, error):
            """job 跑完的统一回调(单步 / 批量都走这里)。"""
            self._set_busy(False)
            if error:
                self._append_message_widget(
                    "assistant", tr("chat_edit_msg_error").format(str(error)[:240]),
                    None, None)
                return
            r = result or {}
            if r.get("empty"):
                note = r.get("note") or tr("chat_edit_msg_no_steps")
                self._append_message_widget("assistant", note, None, None)
                return

            # ── 批量结果:分析气泡 + 每个方案分别气泡 ──
            if r.get("kind") == "batch":
                for sub in r.get("results", []):
                    self._render_batch_sub(sub)
                # 批量模式不切换 current_image —— 用户还要继续聊,原图留着
                self.status_lab.setText(f"已生成 {len(r.get('results', []))} 个气泡")
                return
            steps_data = r.get("steps") or []
            steps = [Step(**s) for s in steps_data if isinstance(s, dict) and s.get("cmd")]
            user_text = r.get("user_text", "")
            result_image = r.get("result_image")
            engine_label = r.get("engine_label", "")
            note = r.get("note", "")

            # 显示助手气泡
            # 「已按…修图」只在**结果图确实存在**时说 —— 之前无条件宣告成功,
            # CLI 对不支持的命令返回原图时,界面照样报"已修图",用户对着
            # 一模一样的图完全不知道发生了什么(实测「去掉图片上的文字」)。
            has_result = bool(result_image and Path(result_image).exists())
            content_lines = []
            if has_result:
                content_lines.append(f"已按「{user_text}」修图。")
            else:
                content_lines.append(f"未能执行「{user_text}」—— 没有产出新图。")
            if engine_label == "inpaint":
                pass          # inpaint 通道没有 PhotoCraft 命令,不显示命中标签
            elif steps:
                content_lines.append(
                    f"({tr('chat_edit_msg_whitelist_hit') if engine_label == 'whitelist' else tr('chat_edit_msg_llm_hit')})")
            if note:
                content_lines.append(note)
            self._append_message_widget(
                "assistant", "\n".join([x for x in content_lines if x]).strip(),
                steps, result_image)

            # 持久化
            if self._session_id:
                db.add_chat_message(self._session_id, "user", user_text)
                db.add_chat_message(
                    self._session_id, "assistant", json.dumps(steps_data, ensure_ascii=False),
                    command_json=json.dumps(steps_data, ensure_ascii=False),
                    result_image=result_image,
                    engine_label=engine_label)
                if result_image and Path(result_image).exists():
                    self._current_image = result_image
                    db.touch_chat_session(self._session_id, current_image=result_image)
                    self._render_thumb()
                    self.status_lab.setText(
                        f"{tr('chat_edit_thinking').rstrip('…') or '已生成'} "
                        f"· {Path(result_image).name}")

        _TM.TASKMGR.submit("chat_edit", job, done, detail=tr("chat_edit_panel"))

    def _execute_single(self, prompt: str, in_path: str, sess_id,
                        llm_id, mode: str, tid) -> dict:
        """执行单条 prompt 的完整逻辑,返回统一格式结果 dict。

        被 _send 单步路径直接调用,也被批量路径对每个 plan 复用。
        """
        # ── 文字编辑(替换 / 抹除)走 TextReplaceSkill ──
        # PhotoCraft CLI 的 run 模式下 select.rect 选区不传递,contentAwareFill
        # 完全对不上字。技能改走:MiniMax-M3 定位 → OpenCV cv2.inpaint(快、本地)
        # 抹字 → PIL ImageDraw 渲染新字;inpaint_masked 当兜底。
        from ..ai.text_replace_skill import TextReplaceSkill, parse_intent
        intent = parse_intent(prompt)
        if intent is not None:
            action, arg1, arg2 = intent
            import time as _t3
            from ..core import config as _cfg
            od = _cfg.STATIC_DIR / "photocraft_sessions" / f"s{sess_id or 0}"
            od.mkdir(parents=True, exist_ok=True)
            outp = od / f"r_{_t3.strftime('%H%M%S')}_{tid}.png"
            skill = TextReplaceSkill(llm_config_id=llm_id)
            if action == "replace":
                res = skill.replace(in_path, arg1, arg2, str(outp))
            else:
                res = skill.remove_all_text(in_path, str(outp))
            if not res.ok:
                if "没检测到文字" in res.error or "没找到" in res.error:
                    return {"empty": True, "note": res.error,
                            "user_text": prompt}
                return {"error": res.error, "user_text": prompt,
                        "engine_label": res.engine or "text_skill"}
            if action == "replace":
                found = res.regions[0].get("text") if res.regions else arg1
                note = (f"已把「{found}」替换为「{arg2}」(用 {res.engine} "
                        f"抹旧字,PIL 渲新字)。")
                steps_data = [{"cmd": "text.replace",
                               "params": {"find": arg1, "replace": arg2},
                               "reason": f"「{found}」→「{arg2}」"}]
            else:
                sample = "、".join(f"「{r.get('text') or '?'}」"
                                   for r in res.regions[:5]) or f"{len(res.regions)} 处"
                note = f"已定位并抹掉 {len(res.regions)} 处文字:{sample}。"
                steps_data = []
            return {
                "user_text": prompt,
                "steps": steps_data,
                "engine_label": res.engine or "text_skill",
                "note": note,
                "result_image": res.output_path,
                "session_id": sess_id,
            }

        # ── PhotoCraft 白名单 + LLM ──
        steps, engine_label, err_or_note = self._engine.interpret(
            prompt, image_url=in_path, mode=mode, llm_config_id=llm_id)
        if err_or_note:
            return {"error": err_or_note, "user_text": prompt,
                    "engine_label": engine_label}
        if not steps:
            note = engine_label if engine_label else "未匹配到可执行的改图命令"
            return {"empty": True, "note": note, "user_text": prompt}
        # 应用
        import time as _t2
        from ..core import config
        out_dir = config.STATIC_DIR / "photocraft_sessions" / f"s{sess_id or 0}"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = _t2.strftime("%H%M%S")
        out_path = out_dir / f"r_{ts}_{tid}.png"
        src_copied = out_dir / f"src_{ts}.png"
        try:
            shutil.copy2(in_path, src_copied)
            result = self._engine.apply(str(src_copied), steps, str(out_path))
        finally:
            try:
                src_copied.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
        return {
            "user_text": prompt,
            "steps": [s.to_dict() for s in steps],
            "engine_label": engine_label,
            "note": err_or_note,
            "result_image": str(out_path),
            "session_id": sess_id,
        }

    def _render_batch_sub(self, sub: dict):
        """渲染一个批量子项(分析气泡 / 方案成功 / 方案失败 / 方案空)。"""
        kind = sub.get("kind")
        plan = sub.get("plan", {}) or {}
        title = plan.get("title") or "?"
        desc = plan.get("description") or ""
        prompt = plan.get("prompt") or ""

        # 1) 构图分析气泡
        if kind == "analysis":
            content = sub.get("content", "")
            self._append_message_widget("assistant", content, None, sub.get("image"))
            if self._session_id:
                db.add_chat_message(self._session_id, "assistant", content,
                                    result_image=sub.get("image"),
                                    engine_label="analysis")
            return

        # 2) 失败
        if sub.get("error"):
            content = f"**{title}**\n{desc}\n指令:{prompt}\n\n❌ {sub['error']}"
            self._append_message_widget("assistant", content, None, None)
            if self._session_id:
                db.add_chat_message(self._session_id, "assistant", content,
                                    engine_label="batch_error")
            return

        # 3) 空(LLM 没规划出可执行命令)
        if sub.get("empty"):
            note = sub.get("note") or "未匹配到可执行命令"
            content = f"**{title}**\n{desc}\n指令:{prompt}\n\n⚠ {note}"
            self._append_message_widget("assistant", content, None, None)
            if self._session_id:
                db.add_chat_message(self._session_id, "assistant", content,
                                    engine_label="batch_empty")
            return

        # 4) 成功
        steps = sub.get("steps") or []
        engine_label = sub.get("engine_label") or ""
        note = sub.get("note") or ""
        result_image = sub.get("result_image") or ""
        lines = [f"**{title}**", desc, f"指令:{prompt}", ""]
        if steps:
            lines.append("执行步骤:")
            for s in steps:
                if not isinstance(s, dict):
                    continue
                cmd = s.get("cmd") or "?"
                params = s.get("params") or {}
                reason = s.get("reason") or ""
                p_str = json.dumps(params, ensure_ascii=False) if params else ""
                lines.append(f"  • `{cmd}` {p_str}{(' — ' + reason) if reason else ''}")
            lines.append("")
        if note:
            lines.append(note)
        content = "\n".join(x for x in lines if x is not None).rstrip()

        step_objs: list[Step] = []
        for s in steps:
            if isinstance(s, dict) and s.get("cmd"):
                try:
                    step_objs.append(Step(**s))
                except Exception:  # noqa: BLE001
                    pass
        self._append_message_widget("assistant", content, step_objs, result_image)
        if self._session_id:
            db.add_chat_message(self._session_id, "assistant", content,
                                command_json=json.dumps(steps, ensure_ascii=False),
                                result_image=result_image,
                                engine_label=engine_label)

    def _set_busy(self, on: bool):
        self._busy = on
        self.send_btn.setEnabled(not on and self._engine.ready and self._current_image is not None)
        self.input.setReadOnly(on)
        if on:
            self.send_btn.setText(tr("chat_edit_thinking"))
        else:
            self.send_btn.setText(tr("chat_edit_send"))

    # ── 跳转 / 桌面端 ──
    def _save_to_main(self):
        if not self._current_image or not Path(self._current_image).exists():
            return
        self.imageSaved.emit(self._current_image)

    def _open_desktop(self):
        from ..ai.photocraft_bridge import resolve_app_path
        import os
        path = resolve_app_path()
        if path:
            try:
                os.startfile(path)  # noqa: Windows
            except Exception as exc:  # noqa: BLE001
                self.status_lab.setText(str(exc)[:200])
        else:
            self.status_lab.setText(tr("chat_edit_cli_missing"))

    # ── 内嵌配置卡(未配 PhotoCraft 时显示) ──

    def _cc_pick_dir(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(
            self, tr("chat_edit_install_dir"), self.cc_dir_edit.text())
        if d:
            self.cc_dir_edit.setText(d)

    def _cc_open_dir(self):
        import os
        d = self.cc_dir_edit.text().strip()
        if d and os.path.isdir(d):
            try:
                os.startfile(d)  # noqa: Windows
            except Exception as exc:  # noqa: BLE001
                self.cc_status.setText(str(exc)[:160])

    def _cc_test_cli(self):
        from ..core import db as _db
        d = self.cc_dir_edit.text().strip()
        if d:
            _db.set_setting("photocraft_install_dir", d)
            from ..ai.photocraft_bridge import PhotocraftCLI as _PC
            _PC._cmds_cache = {}
            _PC._cmds_cache_ts = 0.0
        from ..ai.photocraft_bridge import ChatEditEngine
        eng = ChatEditEngine()
        ok, txt = eng.status_text()
        if ok:
            self.cc_status.setText(tr("chat_edit_cli_ok").format(txt))
            self._refresh_status()
        else:
            self.cc_status.setText(tr("chat_edit_cli_bad").format(txt))

    # ── 手动接力:在 PhotoCraft 桌面端打开当前图,改完自动同步回对话 ──
    # 复用 app.ui.photocraft_watcher.PhotoCraftWatcher(三路监听 +
    # mtime+size 双检),不在这里重复实现。

    def _start_manual_edit(self):
        """✋ 我手动改:启动 photocraft.exe <当前图>,watcher 自动同步回来。"""
        if not self._current_image or not Path(self._current_image).exists():
            self.status_lab.setText(tr("chat_edit_manual_no_img"))
            return
        from .photocraft_watcher import PhotoCraftWatcher
        # 复用同一个 watcher 实例 —— 多次点击不会泄漏进程/线程
        if not hasattr(self, "_pc_watcher") or self._pc_watcher is None:
            self._pc_watcher = PhotoCraftWatcher(self)
            self._pc_watcher.changed.connect(self._handle_manual_change)
        # 终止上一次(若用户连点),重新 watch
        self._pc_watcher.stop()
        ok, err = self._pc_watcher.watch(self._current_image)
        if not ok:
            self.status_lab.setText(err[:200])
            return
        # 写一条"接力"消息,让对话流清楚
        self._append_message_widget("assistant",
                           f"🖐 接力给手动模式 —— PhotoCraft 已打开当前图。你保存后会同步回来。",
                           None, self._current_image)
        if self._session_id:
            db.add_chat_message(self._session_id, "assistant",
                                f"🖐 接力给手动模式",
                                command_json=None,
                                result_image=self._current_image,
                                engine_label="manual")
        self.status_lab.setText(tr("chat_edit_manual_watching"))
        self.manual_btn.setText("🖐 改完会自动同步")

    def _stop_manual_edit(self):
        """停监听(不杀 PhotoCraft 进程:用户可能自己启动的)。"""
        if getattr(self, "_pc_watcher", None):
            self._pc_watcher.stop()

    def _handle_manual_change(self, path: str):
        """把"手动修改"作为一次 assistant 轮加入对话与持久化(PhotoCraftWatcher 回调)。"""
        note = f"📝 {tr('chat_edit_manual_done')} · {Path(path).name}"
        self._append_message_widget("assistant", note, None, str(path))
        if self._session_id:
            db.add_chat_message(self._session_id, "assistant", note,
                                command_json=None, result_image=str(path),
                                engine_label="manual")
        if self._session_id and self._current_image and Path(self._current_image).exists():
            db.touch_chat_session(self._session_id, current_image=str(path))
        # 让 thumb / save-to-main 按钮刷新
        self._render_thumb()
        self.status_lab.setText(tr("chat_edit_manual_done"))
        from .toast import ok
        ok(tr("chat_edit_manual_done"))


# ── 抽屉(顶部 + 面板容器) ──

class ChatEditDrawer(QWidget):
    """侧栏抽屉:顶栏(折叠)+ 内容(ChatEditPanel)。"""

    imageSaved = Signal(str)              # 转发给主窗口
    needSettings = Signal()                # 转发给主窗口去跳转
    openDesktopApp = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        # 转发内部信号
        self.panel.imageSaved.connect(self.imageSaved)
        self.panel.needSettings.connect(self.needSettings)
        self.panel.openDesktopApp.connect(self.openDesktopApp)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("chatDrawerHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 6, 10, 6)
        hl.setSpacing(6)
        ic = W.icon_label("message", size=18)
        hl.addWidget(ic, 0, Qt.AlignVCenter)
        title = QLabel(tr("chat_edit_panel"))
        title.setStyleSheet("font-weight:600; font-size:13px;")
        hl.addWidget(title)
        hl.addStretch(1)
        self.fold_btn = QToolButton()
        self.fold_btn.setText("▶")
        self.fold_btn.setCursor(Qt.PointingHandCursor)
        self.fold_btn.setToolTip("折叠")
        self.fold_btn.clicked.connect(self.fold_requested)
        hl.addWidget(self.fold_btn)
        root.addWidget(head)

        self.panel = ChatEditPanel(self)
        root.addWidget(self.panel, 1)

    def set_image(self, path: str):
        self.panel.set_image(path)

    def fold_requested(self):
        # 留作外部 hook(主窗口收到后收起抽屉)
        pass