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
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QVBoxLayout, QWidget,
)

from ..ai.photocraft_bridge import ChatEditEngine, Step
from ..ai.photocraft_bridge import PHOTOCRAFT_URL
from ..core import db
from ..core.i18n import tr
from ..core import taskmgr as _TM
from . import widgets as W


# 聊天 vs 改图:用 JEV 给一句指令打分,按主流意图分流。
# JevClient.decide() 失败时返回 None(软建议器契约)—— fallback 直接走 edit。
_JEV_INTENT_QUESTIONS = {
    "intent": {
        "type": "choice",
        "instructions": "用户想让 chat-edit 助手做什么?",
        "criteria": {
            "edit": "用户想修改这张图片(改色/裁剪/滤镜/加水印/去字/扩图等)",
            "chat": "用户想聊天、要建议、问问题、解释概念或跟改图无关的请求",
        },
    },
}

# 路由结果常量
_INTENT_EDIT = "edit"
_INTENT_CHAT = "chat"


# ── /help 帮助文案 ──
# 按**实际实现**分类,不是拍脑袋写的:
#   ① 白名单:正则确定性命中,零延迟、结果稳定(photocraft_bridge._WL_RULES)
#   ② 文字编辑:走 TextReplaceSkill,需要多模态模型定位文字
#   ③ 加水印: PIL ImageDraw 画字 + alpha 叠加 PNG,不走 PhotoCraft
#   ④ 批分析: LLM 看图给 N 个单条 prompt,逐条执行
#   ⑤ 外部打开: 用 PhotoCraft 桌面端编辑,改完自动同步回来
#   ⑥ 兜底: 白名单没命中时交给 LLM 自由理解,措辞/命令不保证完全一致
_HELP_TEXT = """可以用下面这些说法改图(直接发文字即可,回车执行)。

【色彩 · 白名单,最稳】
改成黑白 / 改为黑白 / 黑白化 / 去色
亮度+30   亮度-20
对比+15   饱和度-40
曝光+10   鲜艳度-30
反色 / 反相 / 负片
去雾 / 除雾
加饱和 / 降饱和 / 鲜艳度+30
暖色调 / 冷色调 / 色温+30
胶片感 / 电影感 / 暗部提亮 / 亮部压暗

【几何 · 白名单】
顺时针旋转90 / 右转90
逆时针旋转90 / 左转90
水平翻转 / 水平镜像 / 左右翻转
垂直翻转 / 上下翻转
旋转180 / 转180 / 倒过来
裁掉透明边

【滤镜 · 白名单】
高斯模糊 5 / 模糊5 / 模糊一下
轻微模糊 / 轻度模糊 / 柔焦一下
运动模糊
锐化 / 清晰一些
强力锐化 / 更锐利
磨皮 / 皮肤柔化
中值去噪 / 加噪点 10
旋转扭曲 / 锐化30

【文字编辑 · 需要识图,稍慢】
把「影星传媒」改成「歌星」      ← 推荐加引号
把"CHAMPION"换成"TITLE"
将标题改为副标题
去掉图片上的文字 / 去除水印 / 删除字幕
加上文字 公司名 到左下              ← 字体/颜色/位置在「改图」面板里调

【加水印 · 当前图烙字 / 贴 PNG】
加水印 版权所有 到右下 / 宽 15% / 透 60%
加水印 草图 v1 到中下 黄字黑边
加 PNG 水印 → 选 PNG 文件 → 选位置 → 点「加水印」

【批分析 · 先分析再 N 个方案】
先分析这张图,再给 3 个改进方案分别执行
分析构图,然后给 2 个方案

【批改图 · 一键批量(资产页也能用)】
批量文绘 角色         ← 全角色全生图,3s 间隔,串行
批量重画 场景         ← 强制覆盖已有图,跑新风格
补图全部               ← 只生空白图(image_url IS NULL),不浪费 token
批量视频               ← 任务列表所有「无视频」分镜全跑

【外部打开 · PhotoCraft 桌面端】
✋ 我手动改             ← 启动 PhotoCraft,改完自动同步回来
🖥 PhotoCraft           ← 桌面端当前版本号 + 打开外部应用按钮

提示:数字是强度参数,可正可负(亮度+30 比 亮度30 更明确);加水印/批分析/
      批改图/外部打开用面板里的按钮,不是打字;
      「重抽」/「撤销」直接点气泡里的图片,弹「改图」面板裁剪/精调/水印/AI 修补;
      需要先选图 —— 没图时面板会明确报错。"""


# ── 气泡 ──

class ChatEditMessage(QFrame):
    """单条消息气泡 —— 用户/助手两种风格。"""

    def __init__(self, role: str, content: str, steps: list[Step] | None = None,
                 result_image: Optional[str] = None, parent=None,
                 on_image_edit=None):
        super().__init__(parent)
        self.role = role
        self._steps = steps or []
        self._result_image = result_image
        # 帮助气泡(/help):内容长,宽度上限单独放宽,见 _bubble_max_w
        self._is_help = bool(content) and content.startswith("可以用下面这些说法")
        # 点结果图 → 弹「改图」对话框。回调由 ChatEditPanel 注入(气泡自己
        # 拿不到面板的"保存后同步当前图"逻辑)。None 时退回只看不改。
        self._on_image_edit = on_image_edit
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
        # 帮助气泡用等宽字体,命令清单的冒号/缩进才能对齐,方便照着抄
        text.setStyleSheet(
            "font-size:12px; line-height:1.55; font-family:Consolas,Menlo,monospace;"
            if self._is_help else "font-size:13px; line-height:1.5;")
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
        """气泡最大宽度 = 聊天区可视宽的 72%(帮助气泡放宽到 94%)。

        **不能**用 self.parentWidget().width():用户消息被包在一个 wrap QFrame 里
        (右对齐用),而 wrap 的宽度又由 msg 的 sizeHint 决定 —— 互相依赖,实测两边
        一起塌到最小值,气泡变成一条竖条、中文逐字折行(见 _append_message_widget)。
        这里向上找真正的聊天区容器(_hist_host)或退回 self.width()。

        帮助气泡内容很长(几十行命令清单),按 72% 排会拉出屏幕外;识别到 help
        气泡就放宽,让它接近整行宽、命令清单一屏能看完。
        """
        ratio = 0.94 if self._is_help else 0.72
        node = self
        while node is not None:
            if getattr(node, "objectName", lambda: "")() == "chatHistHost":
                w = node.width()
                if w > 0:
                    return max(240, int(w * ratio))
            node = node.parentWidget()
        avail = self.width()
        return max(240, int(avail * ratio)) if avail > 0 else 520

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
        """点气泡里的结果图 → 弹「改图」对话框(裁剪/旋转/精调/滤镜/水印/尺寸/AI 修补)。

        原先是 ImageViewerDialog(只能看不能改)。聊天改图里的图是**会话产物**,
        不属于任何角色/场景/道具资产,所以 target=None —— 改完保存即下载,
        不写回资产表。改完的结果由面板的回调同步成"当前图",可以接着继续改。

        回调未注入(理论上不会发生)时退回只看不改,不让点击无响应。
        """
        if self._on_image_edit is not None:
            self._on_image_edit(path)
            return
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
        # 「打开 PhotoCraft 桌面端」。
        # 原先用 svg_icon_btn("open_external"),但 icons.ALIAS 里**没有这一项**,
        # icon() 找不到 SVG 返回空 QIcon → 渲染成一个纯白方块(用户截图里
        # 「我手动改」右边那个白框)。改用已有的 image 图标 + 「PhotoCraft」文字。
        desktop_btn = QPushButton(" PhotoCraft")
        desktop_btn.setIcon(W.svg_icon("image", size=14))
        desktop_btn.setToolTip("打开 PhotoCraft 桌面端")
        desktop_btn.setCursor(Qt.PointingHandCursor)
        desktop_btn.setStyleSheet(
            "QPushButton{border:1px solid #e4e7ec;border-radius:6px;"
            "background:#fff;color:#4e5969;padding:4px 10px;font-size:12px;}"
            "QPushButton:hover{background:#fef3e8;border-color:#f3c9a4;color:#1f2329;}")
        desktop_btn.clicked.connect(self._open_desktop)
        top.addWidget(desktop_btn)
        # 调色板图标(原是齿轮):PhotoCraft 本身就是图像编辑工具,用「palette」图标
        # 比齿轮更贴合本面板属性 —— 齿轮总让人想到系统设置,跟这里跳到
        # PhotoCraft 配置入口的语义对不上。
        settings_btn = W.svg_icon_btn("palette", tr("chat_edit_to_settings"), size=26)
        settings_btn.clicked.connect(self.needSettings.emit)
        top.addWidget(settings_btn)
        root.addLayout(top)

        self.status_lab = W.muted("")
        self.status_lab.setStyleSheet("font-size:11px;")
        # 未就绪时(PhotoCraft 没装)把状态栏变成可点击链接,直接跳 GitHub 下载页 ——
        # 只显示「未配置」的话用户不知道去哪装
        self.status_lab.setOpenExternalLinks(True)
        self.status_lab.setTextInteractionFlags(Qt.TextBrowserInteraction)
        root.addWidget(self.status_lab)

        # 未配置时的内嵌配置入口(替代下面整张工作台 —— 抽屉本身就是稀缺空间,
        # 让 ta 先配通 CLI 才能继续聊)
        self.config_card = W.make_card()
        cc_lay = QVBoxLayout(self.config_card)
        cc_lay.setContentsMargins(12, 10, 12, 10)
        cc_lay.setSpacing(6)
        cc_title = W.h2(tr("chat_edit_setup_title"))
        cc_lay.addWidget(cc_title)
        # 未装 PhotoCraft 时,除了"去设置配目录",再给一个官方下载链接
        cc_dl = QLabel(
            f'没装?到 <a href="{PHOTOCRAFT_URL}">GitHub 官方仓库</a> 下载,'
            f'解压后把目录填到下面。')
        cc_dl.setOpenExternalLinks(True)
        cc_dl.setTextInteractionFlags(Qt.TextBrowserInteraction)
        cc_dl.setObjectName("muted")
        cc_lay.addWidget(cc_dl)
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

        # 水印行:模式(文字/PNG) + 输入控件(随模式切换) + 9 宫格位置 + 加水印按钮
        # 用法:选文字 → 输字 → 选位置 → 点加水印
        #      选 PNG  → 选文件 → 选位置 → 点加水印(PNG 透明通道会保留)
        wm_row = QHBoxLayout()
        wm_row.setSpacing(4)
        # 模式:文字 / PNG 图片
        self.wm_mode = QComboBox()
        self.wm_mode.addItem("📝 " + tr("chat_watermark_text"), "text")
        self.wm_mode.addItem("🖼  PNG", "image")
        self.wm_mode.currentIndexChanged.connect(self._on_wm_mode_changed)
        wm_row.addWidget(self.wm_mode)
        # 文字模式输入 + 图片模式输入(QStackedWidget 互斥显示)
        from PySide6.QtWidgets import QStackedWidget, QColorDialog
        from PySide6.QtGui import QColor
        self.wm_stack = QStackedWidget()
        # 文字页(双行:输入行 + 样式行[预设/描边宽/描边色/主色])
        text_page = QWidget()
        text_vlay = QVBoxLayout(text_page)
        text_vlay.setContentsMargins(0, 0, 0, 0)
        text_vlay.setSpacing(2)
        text_input_row = QHBoxLayout()
        text_input_row.setSpacing(0)
        self.wm_input = QLineEdit()
        self.wm_input.setPlaceholderText(tr("chat_watermark_text"))
        self.wm_input.setMaxLength(40)
        self.wm_input.setClearButtonEnabled(True)
        text_input_row.addWidget(self.wm_input)
        text_vlay.addLayout(text_input_row)
        # 样式行:预设 + 描边宽 + 描边色 + 主色
        # 选预设会自动套用「描边宽/描边色/主色」三件套,后续用户手动调会覆盖预设
        text_style_row = QHBoxLayout()
        text_style_row.setSpacing(4)
        # 预设:默认值(None=中心像素反相)、Logo 白/Logo 黑/印章红/高亮黄
        self.wm_preset = QComboBox()
        self._wm_presets = [
            ("默认（中心反相）", None),
            ("Logo 白（白字黑边）",
             {"main": (255, 255, 255, 230), "stroke": (0, 0, 0, 200), "width": 1}),
            ("Logo 黑（黑字白边）",
             {"main": (20, 20, 20, 220), "stroke": (255, 255, 255, 180), "width": 1}),
            ("印章红（红字白边）",
             {"main": (220, 30, 30, 235), "stroke": (255, 255, 255, 200), "width": 2}),
            ("高亮黄（黄字黑边）",
             {"main": (255, 220, 0, 240), "stroke": (0, 0, 0, 200), "width": 1}),
        ]
        for label, _val in self._wm_presets:
            self.wm_preset.addItem(label)
        self.wm_preset.currentIndexChanged.connect(self._apply_wm_preset)
        text_style_row.addWidget(self.wm_preset)
        # 字体:从 intro.list_fonts() 列系统字体(去掉 .ttc/.otf 后缀的可读名)
        # 默认选第一项;用户改了之后,加水印时优先用用户选的中文字体(否则退到硬编码链)
        from ..pipeline import intro as _intro
        self.wm_font = QComboBox()
        self._wm_fonts = _intro.list_fonts()
        for f in self._wm_fonts:
            self.wm_font.addItem(f["name"], f["file"])
        if self._wm_fonts:
            self.wm_font.setCurrentIndex(0)
        self.wm_font.setToolTip("文字字体(取系统能扫到的 .ttf/.otf/.ttc)")
        self.wm_font.setMinimumWidth(96)
        text_style_row.addWidget(self.wm_font)
        # 描边宽(像素)—— 加显式「宽 N」标签,跟 QSpinBox 一起看才不歧义
        stroke_lbl = QLabel("宽")
        stroke_lbl.setStyleSheet("color:#64748b; font-size:11px;")
        text_style_row.addWidget(stroke_lbl)
        self.wm_stroke_w = QSpinBox()
        self.wm_stroke_w.setRange(0, 6)
        self.wm_stroke_w.setValue(1)
        self.wm_stroke_w.setSuffix("px")
        self.wm_stroke_w.setFixedWidth(58)
        self.wm_stroke_w.setToolTip("描边宽度(0=无描边)")
        text_style_row.addWidget(self.wm_stroke_w)
        # 透明度(0-100%,默认 100 = 不透明;PNG 模式缩放 RGBA alpha,
        # 文字模式按比例缩放主色/描边色的 alpha)
        opa_lbl = QLabel("透")
        opa_lbl.setStyleSheet("color:#64748b; font-size:11px;")
        text_style_row.addWidget(opa_lbl)
        self.wm_opacity = QSpinBox()
        self.wm_opacity.setRange(10, 100)
        self.wm_opacity.setValue(100)
        self.wm_opacity.setSuffix("%")
        self.wm_opacity.setFixedWidth(72)
        self.wm_opacity.setToolTip("水印透明度(10~100,数字越小越透)")
        text_style_row.addWidget(self.wm_opacity)
        # 描边色 + 主色按钮:之前 28x22 太窄,用户点不上;改成 36x24 + 文字「色」
        # 让点击区够大,按钮底色就是当前色,鼠标移上去 tooltip 显完整说明
        for color_attr, label, pick_method, default_name in (
                ("wm_stroke_color", "描", "_pick_wm_stroke_color", "#000000"),
                ("wm_main_color",   "字", "_pick_wm_main_color",   "#ffffff"),
        ):
            btn = QPushButton(label)
            btn.setFixedSize(36, 24)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"background:{default_name}; border:1px solid rgba(128,128,128,160);"
                f"border-radius:3px; font-size:10px; color:#1f2329; padding:0;")
            btn.clicked.connect(getattr(self, pick_method))
            setattr(self, color_attr, btn)
            text_style_row.addWidget(btn)
        text_vlay.addLayout(text_style_row)
        self.wm_stack.addWidget(text_page)
        # 初始化颜色按钮的填色:默认预设(中心反相)不给具体色,先给一个默认色
        self._wm_stroke_qc = QColor(0, 0, 0, 200)
        self._wm_main_qc = QColor(255, 255, 255, 230)
        self._sync_wm_color_btns()
        # 给两个颜色按钮加 tooltip 完整说明(按钮小,只能显示短文字)
        self.wm_stroke_color.setToolTip(tr("watermark_stroke_color") + " — 点击弹颜色选择器")
        self.wm_main_color.setToolTip(tr("watermark_main_color") + " — 点击弹颜色选择器")
        # 图片页
        img_page = QWidget()
        img_lay = QHBoxLayout(img_page)
        img_lay.setContentsMargins(0, 0, 0, 0)
        img_lay.setSpacing(4)
        self.wm_file_btn = QPushButton("📁 " + tr("chat_watermark_pick"))
        self.wm_file_btn.setCursor(Qt.PointingHandCursor)
        self.wm_file_btn.clicked.connect(self._pick_wm_image)
        img_lay.addWidget(self.wm_file_btn)
        self.wm_file_lab = QLabel(tr("chat_watermark_no_file"))
        self.wm_file_lab.setStyleSheet("color:#94a3b8; font-size:11px;")
        self.wm_file_lab.setToolTip("")
        img_lay.addWidget(self.wm_file_lab, 1)
        img_lay.addStretch(1)
        self.wm_stack.addWidget(img_page)
        wm_row.addWidget(self.wm_stack, 1)
        # 宽度(两模式共用):
        #   文字模式 = 字号占图短边的百分比(40% / 100 = 图短边 0.4 倍字号)
        #   图片模式 = 水印图宽度占图短边的百分比(20% / 100 = 图短边 0.2 倍宽)
        # 默认 12% —— 用户实测反馈「20% 看起来占了图的一半」,小点更不抢戏
        width_lbl = QLabel("宽")
        width_lbl.setStyleSheet("color:#64748b; font-size:11px;")
        wm_row.addWidget(width_lbl)
        self.wm_scale = QSpinBox()
        self.wm_scale.setRange(3, 80)
        self.wm_scale.setValue(12)
        self.wm_scale.setSuffix("%")
        self.wm_scale.setFixedWidth(64)            # 加宽 6px,「N%」更完整可见
        self.wm_scale.setToolTip("水印占图短边的百分比(文字=字号;PNG=宽度)")
        wm_row.addWidget(self.wm_scale)
        # 9 宫格位置(与文字/图片共用)
        self.wm_pos = QComboBox()
        for label, x, y in (
                ("左上", 0.08, 0.10), ("中上", 0.5, 0.06), ("右上", 0.92, 0.10),
                ("左中", 0.06, 0.5),  ("正中", 0.5, 0.5),  ("右中", 0.94, 0.5),
                ("左下", 0.08, 0.92), ("中下", 0.5, 0.94), ("右下", 0.92, 0.92),
        ):
            self.wm_pos.addItem(label, (x, y))
        self.wm_pos.setCurrentIndex(8)
        wm_row.addWidget(self.wm_pos)
        root.addLayout(wm_row)

        # 加水印按钮单独一行 —— 设置项(模式/文字/PNG/宽度/位置)挤一行,
        # 按钮独占下一行,按下后「模式+文字/PNG+宽度+位置」整体生效;视觉上更清楚
        # 这是个主操作,不该跟下拉挤一起。
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.wm_btn = QPushButton("💧 " + tr("chat_watermark_apply"))
        self.wm_btn.setCursor(Qt.PointingHandCursor)
        self.wm_btn.setFixedHeight(28)
        self.wm_btn.setObjectName("primary")
        self.wm_btn.clicked.connect(self._add_watermark)
        btn_row.addWidget(self.wm_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)
        # 记录当前 PNG 路径(QStackedWidget 内 file_lab 显示)
        self._wm_image_path: str | None = None

        # 底部:输入框 + 发送 + 保存
        bot = QHBoxLayout()
        bot.setSpacing(6)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("例如:改成黑白 / 亮度+30 / 高斯模糊 5(或输入 /help 看全部写法)")
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
        # 未就绪 → 文案里带可点击的 GitHub 下载链接
        if not ok:
            txt = (f'PhotoCraft 未就绪 —— '
                   f'<a href="{PHOTOCRAFT_URL}">点击前往 GitHub 下载</a>')
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
        """点击顶部缩略图 → 弹「改图」对话框。

        与气泡里的图片点击走同一个入口(_open_image_edit),行为一致:
        裁剪/旋转/精调/滤镜/水印/尺寸/AI 修补,改完应用回会话当前图。
        """
        if not self._current_image or not Path(self._current_image).exists():
            return
        self._open_image_edit(self._current_image)

    def _open_image_edit(self, path: str):
        """弹「改图」对话框处理一张会话图。

        target={"type": "session"}:会话里的图是**工作副本**,用户要的是
        「改完接着用」,不是存到磁盘 —— 所以点「应用」直接回写当前图,
        不弹下载框。也**不写回任何资产表**(聊天产物不属于角色/场景/道具,
        写进去会污染资产库)。
        """
        from .image_edit_dialog import open_image_edit
        open_image_edit(self, path, target={"type": "session"},
                        title=f"{tr('改图')} · {Path(path).name}",
                        on_saved=self._on_image_edited)

    def _on_image_edited(self, saved_url: str):
        """改图保存后:同步成"当前图",刷新缩略图与保存按钮。

        只更新 _current_image 而不追加消息气泡 —— 用户是在已有图上微调,
        再插一条"已按…修图"会让对话流被编辑记录刷屏。
        """
        if not saved_url:
            return
        self._current_image = saved_url
        self._render_thumb()
        self._save_btn_refresh()
        if self._session_id:
            from ..core import db as _db
            _db.touch_chat_session(self._session_id, current_image=saved_url)
        from .toast import ok
        ok(tr("改图已保存,可继续在会话里修改"))

    def _append_help(self):
        """往对话流里追加一条「可用写法」帮助气泡。

        内容按**实际实现**列,不是拍脑袋写的:白名单那批是零延迟确定性命中,
        文字编辑那批走 TextReplaceSkill,其余交给 LLM 自由理解(标注为「兜底」,
        措辞不保证完全一致)。用等宽字体块排版,方便直接复制。
        """
        self._append_message_widget("user", "/help", None, None)
        self._append_message_widget("assistant", _HELP_TEXT, None, None)
        self.status_lab.setText(tr("chat_edit_help_tip"))

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
        msg = ChatEditMessage(role, content, steps=steps, result_image=result_image,
                              parent=self.hist_host,
                              on_image_edit=self._open_image_edit)
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
    def _chat_reply(self, user_text: str, in_path: str, llm_id, mode: str) -> dict:
        """JEV 判定为 chat 意图 → 调文本 LLM 给建议/解释,不调 PhotoCraft。

        系统提示把当前图像文件名 + 用户原句打包,让 LLM 知道是「看着哪张图聊天」。
        失败/异常都按 error 返回(done 回调统一兜底)。
        """
        from ..ai import text_client as _tc
        from ..ai.image_client import _ref_data_url
        sys_p = (
            "你是 chat-edit 助手的聊天分支。当前用户的图片已经在会话里,"
            "他们只想问建议、解释概念、或者跟改图无关的问题 —— "
            "【不要】调用任何工具、不要再尝试修改图片,"
            "【不要】给出修改命令(step/cmd/参数)。用 1-3 句中文直接回答。"
        )
        user_prompt = f"用户消息: {user_text}"
        image_urls = None
        try:
            if in_path and Path(in_path).exists():
                d = _ref_data_url(in_path)
                if d:
                    image_urls = [d]
        except Exception:  # noqa: BLE001
            image_urls = None
        try:
            content = _tc.chat(user_prompt, system=sys_p, config_id=llm_id,
                              temperature=0.6, max_tokens=600, timeout=60,
                              image_urls=image_urls)
            return {
                "kind": "chat",
                "user_text": user_text,
                "content": (content or "").strip() or "(空回复)",
                "engine_label": "chat",
            }
        except _tc.AIError as exc:
            return {"error": str(exc)[:240], "user_text": user_text,
                    "engine_label": "chat"}

    def _send(self):
        if self._busy:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        # /help(以及 ?/help/help)→ 直接把支持的写法列出来,不走改图引擎。
        # 放在最前面是因为它不需要当前图 —— 用户往往就是「不知道能写什么」
        # 才问的,此时可能还没加载图。
        if text.lstrip().strip("/").lower() in ("help", "?", "帮助", "h"):
            self.input.clear()
            self._append_help()
            return
        # chat-edit 整面板就是围着当前图转的,不管聊天还是改图都要先选图 —— 用户实测
        # 反馈「聊天还是要有图片」(没图发任何指令都不知拿啥说/改啥)。worker 里 JEV
        # 路由前先在主线程拦掉,无图直接报 chat_edit_msg_image_missing。
        if not self._current_image or not Path(self._current_image).exists():
            self.status_lab.setText(tr("chat_edit_msg_image_missing"))
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
            # ── JEV 意图路由:先问一句「用户想聊天还是改图」 ──
            # edit → 走原本 Whitelist + LLM IntentParser + PhotoCraft CLI
            # chat → 走文本 LLM 纯聊天回复(给建议/解释/问答),不动图
            # JEV 未配/挂了 → fallback edit(沿用旧行为,0 回归)
            from ..ai.jev_client import JevClient
            intent = _INTENT_EDIT   # 默认 edit
            try:
                client = JevClient()
                if client.is_configured():
                    # 把用户文本 + 当前图(若有)拼成 state,再喂判定问题
                    state = f"用户消息: {text}"
                    if self._current_image:
                        state += f"\n当前图: {Path(self._current_image).name}"
                    res = client.decide(state, _JEV_INTENT_QUESTIONS) or {}
                    answer = (res.get("answers") or {}).get("intent", _INTENT_EDIT)
                    intent = _INTENT_CHAT if str(answer).strip().lower() == _INTENT_CHAT else _INTENT_EDIT
            except Exception:  # noqa: BLE001
                intent = _INTENT_EDIT

            # chat 路径:不动图,直接调文本 LLM 给建议(不检查图存在)
            if intent == _INTENT_CHAT:
                return self._chat_reply(text, str(in_path), llm_id, mode)

            # edit 路径:必须有图。JEV 已判定为改图,若用户没选图就明确报错
            if not in_path or not Path(in_path).exists():
                return {"empty": True,
                        "note": tr("chat_edit_msg_image_missing"),
                        "user_text": text}

            # edit 路径:走原本逻辑(批量 / 单步)
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
            """job 跑完的统一回调(单步 / 批量 / chat 都走这里)。"""
            self._set_busy(False)
            if error:
                self._append_message_widget(
                    "assistant", tr("chat_edit_msg_error").format(str(error)[:240]),
                    None, None)
                return
            r = result or {}
            # JEV chat 路径:不动图,只追加一条文字建议气泡
            if r.get("kind") == "chat":
                content = r.get("content") or "(空回复)"
                self._append_message_widget("assistant", content, None, None)
                self.status_lab.setText("💬 chat · " + tr(r.get("engine_label") or "ready"))
                return
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

    # ── 水印 ──
    def _add_watermark(self):
        """用 PIL 给当前图加水印(文字或 PNG),产物就地替换 current_image + 弹助手气泡。

        模式路由:
          - 文字:取 wm_input 文字 → 按 wm_scale% 算字号(图短边 × scale%) → 烙字
          - PNG :取 _wm_image_path 图 → 按 wm_scale% 算宽(图短边 × scale%) → alpha 叠加
        设置项共用 wm_scale,模式切换不影响;两个模式的尺寸语义不同:
          - 文字 → 字号(图短边的 X% 倍字号,例如 20% 就是图短边的 0.2 倍字号)
          - PNG  → 水印图显示宽(图短边的 X% 倍像素)
        """
        if not self._current_image or not Path(self._current_image).exists():
            self.status_lab.setText(tr("chat_edit_msg_image_missing"))
            return
        mode = self.wm_mode.currentData() or "text"
        scale_pct = max(self.wm_scale.value(), 3)
        fx, fy = self.wm_pos.currentData()
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            self.status_lab.setText("Pillow 未安装")
            return
        try:
            im = Image.open(self._current_image).convert("RGB")
        except Exception as exc:
            self.status_lab.setText(str(exc)[:160])
            return
        Wd, Hd = im.size
        short = min(Wd, Hd)
        # 主 overlay 同主图大小(图片模式还要在下面粘水印图)
        overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))

        if mode == "image":
            # PNG 水印:按 wm_scale% 缩放,保持 PNG 透明通道
            if not self._wm_image_path or not Path(self._wm_image_path).exists():
                self.status_lab.setText(tr("chat_watermark_no_file"))
                return
            wm_pil = Image.open(self._wm_image_path)
            if wm_pil.mode != "RGBA":
                wm_pil = wm_pil.convert("RGBA")
            target_w = max(8, int(short * scale_pct / 100))
            ratio = target_w / max(1, wm_pil.width)
            target_h = max(8, int(wm_pil.height * ratio))
            wm_pil = wm_pil.resize((target_w, target_h), Image.LANCZOS)
            # 透明度:把 RGBA 的 alpha 通道按 wm_opacity% 缩放
            opa_pct = self.wm_opacity.value()
            if opa_pct < 100 and wm_pil.mode == "RGBA":
                # alpha_composite 会保留 alpha;此处直接乘系数
                r, g, b, a = wm_pil.split()
                a = a.point(lambda v: int(v * opa_pct / 100))
                wm_pil = Image.merge("RGBA", (r, g, b, a))
            # 按 9 宫格锚点对齐(以 wm_pil 实际宽高对齐 fx,fy)
            x = max(0, int((Wd - wm_pil.width) * fx))
            y = max(0, int((Hd - wm_pil.height) * fy))
            overlay.alpha_composite(wm_pil, dest=(x, y))
        else:
            # 文字水印:与 image_edit_dialog._add_watermark_item 一致
            text = self.wm_input.text().strip()
            if not text:
                self.status_lab.setText(tr("chat_watermark_no_text"))
                return
            # 字号 = 图短边 × scale%(用户统一控制 width 即可,无需另设字号)
            size = max(10, min(int(short * scale_pct / 100), 256))
            # 字体优先级:用户选 > 硬编码链 > default
            font = None
            user_font = self.wm_font.currentData()
            if user_font:
                try:
                    font = ImageFont.truetype(str(user_font), size)
                except (OSError, ValueError):
                    font = None
            if font is None:
                for cand in ("msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc",
                             "PingFang.ttc", "NotoSansCJK-Regular.ttc",
                             "arial.ttf", "DejaVuSans.ttf"):
                    try:
                        font = ImageFont.truetype(cand, size)
                        break
                    except OSError:
                        continue
            if font is None:
                font = ImageFont.load_default()
            d = ImageDraw.Draw(overlay)
            try:
                tb = d.textbbox((0, 0), text, font=font)
                tw, th = tb[2] - tb[0], tb[3] - tb[1]
            except Exception:  # noqa: BLE001
                tw, th = int(size * len(text) * 0.6), int(size * 1.2)
            x = max(0, int((Wd - tw) * fx))
            y = max(0, int((Hd - th) * fy))
            # 描边宽:用户控件优先;预设或默认 1px
            # 描边宽 = 字号 × 比例(跟 Photoshop 习惯一致:大字号描边粗)
            sw = max(1, size // 14) if self.wm_preset.currentData() is None else self.wm_stroke_w.value()
            sw = max(sw, 0)
            # 主色 + 描边色:选「默认(中心反相)」时按图中心像素算,
            # 选预设时按预设给的 RGBA,手动调主/描边色按钮时按按钮色
            preset_data = self._wm_presets[self.wm_preset.currentIndex()][1]
            if preset_data is None:
                # 默认:中心像素反相
                try:
                    center = im.getpixel((Wd // 2, Hd // 2))
                    if isinstance(center, tuple):
                        center = center[:3]
                except Exception:  # noqa: BLE001
                    center = (255, 255, 255)
                lum = 0.299 * center[0] + 0.587 * center[1] + 0.114 * center[2]
                main = (255, 255, 255, 230) if lum < 128 else (20, 20, 20, 220)
                stroke = (0, 0, 0, 200) if lum >= 128 else (255, 255, 255, 180)
            else:
                # 预设或手动:用按钮当前色(预设应用时已同步按钮色)
                # alpha 按 wm_opacity% 缩放(100%=全不透明,越小越透)
                opa_pct = self.wm_opacity.value()
                ma = int(self._wm_main_qc.alpha() * opa_pct / 100)
                sa = int(self._wm_stroke_qc.alpha() * opa_pct / 100)
                main = (self._wm_main_qc.red(), self._wm_main_qc.green(),
                        self._wm_main_qc.blue(), ma)
                stroke = (self._wm_stroke_qc.red(), self._wm_stroke_qc.green(),
                          self._wm_stroke_qc.blue(), sa)
            if sw > 0:
                for dx in range(-sw, sw + 1):
                    for dy in range(-sw, sw + 1):
                        if dx == 0 and dy == 0:
                            continue
                        d.text((x + dx, y + dy), text, font=font, fill=stroke)
            d.text((x, y), text, font=font, fill=main)

        # 合成 → 保存到 static/processed/wm_<uuid>.png → 写库 current_image
        from ..core import config as _cfg
        import uuid
        out_dir = _cfg.STATIC_DIR / "processed"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"wm_{uuid.uuid4().hex[:8]}.png"
        Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB").save(out)
        url = _cfg.path_to_media_url(out)
        # 更新会话:current_image 替换 + 写库
        self._current_image = str(out)
        if self._session_id:
            db.touch_chat_session(self._session_id, current_image=url)
        self._render_thumb()
        self._save_btn_refresh()
        # 弹助手气泡
        if mode == "image":
            tag_text = f"💧 PNG 水印:{Path(self._wm_image_path).name}"
        else:
            tag_text = f"💧 加水印:{text}"
        self._append_message_widget("user", tag_text, None, None)
        self._append_message_widget(
            "assistant",
            f"{tr('chat_watermark_done')} ({self.wm_pos.currentText()})",
            None, str(out))
        if mode == "text":
            self.wm_input.clear()
        from .toast import ok
        ok(tr("chat_watermark_done"))

    def _pick_wm_image(self):
        """选 PNG 水印文件,支持透明 PNG 优先(RGBA 通道保留)。"""
        path, _ = QFileDialog.getOpenFileName(
            self, tr("chat_watermark_pick"), "",
            "PNG (*.png);;所有图片 (*.png *.jpg *.jpeg *.webp)")
        if not path:
            return
        self._wm_image_path = path
        self.wm_file_lab.setText(Path(path).name)
        self.wm_file_lab.setToolTip(path)

    def _apply_wm_preset(self, _idx: int):
        """选预设 → 同步描边宽 + 主色 + 描边色三个手动控件(用户后续可调覆盖)。"""
        preset = self._wm_presets[_idx][1] if 0 <= _idx < len(self._wm_presets) else None
        if preset is None:
            # 「默认」:不动手动控件,保留用户上次调的值;_add_watermark 走中心反相
            return
        # 描边宽
        self.wm_stroke_w.setValue(int(preset.get("width", 1)))
        # 主色 + 描边色 → 同步 QColor 内部态 + 按钮底色
        mr, mg, mb, ma = preset.get("main", (255, 255, 255, 230))
        self._wm_main_qc = self._wm_main_qc.__class__(mr, mg, mb, ma)
        sr, sg, sb, sa = preset.get("stroke", (0, 0, 0, 200))
        self._wm_stroke_qc = self._wm_stroke_qc.__class__(sr, sg, sb, sa)
        self._sync_wm_color_btns()

    def _sync_wm_color_btns(self):
        """把 _wm_main_qc / _wm_stroke_qc 同步到两个按钮的 background,做色块。"""
        self.wm_main_color.setStyleSheet(
            f"background:{self._wm_main_qc.name()}; border:1px solid rgba(128,128,128,120);"
            f"border-radius:3px;")
        self.wm_stroke_color.setStyleSheet(
            f"background:{self._wm_stroke_qc.name()}; border:1px solid rgba(128,128,128,120);"
            f"border-radius:3px;")

    def _pick_wm_main_color(self):
        c = QColorDialog.getColor(self._wm_main_qc, self, tr("watermark_main_color"))
        if c.isValid():
            self._wm_main_qc = c
            self._sync_wm_color_btns()

    def _pick_wm_stroke_color(self):
        c = QColorDialog.getColor(self._wm_stroke_qc, self, tr("watermark_stroke_color"))
        if c.isValid():
            self._wm_stroke_qc = c
            self._sync_wm_color_btns()

    def _on_wm_mode_changed(self, _idx: int):
        """模式切换:文字 ↔ PNG,同步 QStackedWidget 当前页 + 按钮状态。"""
        self.wm_stack.setCurrentIndex(_idx)

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
            self.status_lab.setText(
                f'PhotoCraft 未就绪 —— <a href="{PHOTOCRAFT_URL}">点击前往 GitHub 下载</a>')

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
        # 原先这里有个「▶ 折叠」按钮,但 fold_requested 是空实现、外部也没有任何
        # 连接(全仓库仅此一处定义),点了没反应 —— 纯装饰,已移除。
        root.addWidget(head)

        self.panel = ChatEditPanel(self)
        root.addWidget(self.panel, 1)

    def set_image(self, path: str):
        self.panel.set_image(path)