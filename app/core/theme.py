# -*- coding: utf-8 -*-
"""浅色 / 深色 QSS 主题。

字体策略对齐原版 drama(frontend/app/assets/studio.css):
  body/display: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', sans-serif
  mono:         ui-monospace, 'SF Mono', Menlo, 'Fira Code', Consolas, monospace
Windows 上实际回落到 Microsoft YaHei;macOS 回落 PingFang SC。
"""
from __future__ import annotations

FONT_STACK = "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', 'Hiragino Sans GB', 'Heiti SC', sans-serif"
MONO_STACK = "ui-monospace, 'SF Mono', 'SFMono-Regular', Menlo, 'Fira Code', Consolas, monospace"

_QSS_BODY = None  # 字体栈直接内联进两套 QSS

# 制作面板:资产卡 / 分镜工作台 / 漫画格(对齐原版 episode.vue 的 .asset-* .video-* .comic-*)
ASSET_QSS_LIGHT = """
QWidget#prodBar { background: transparent; }
QWidget#prodContent { background: transparent; }
QLabel#sectionTitle { font-size: 12px; font-weight: 800; letter-spacing: 1px; color: #1f2329; }
QPushButton#addBtn { border: 1px dashed #f97316; color: #f97316; background: transparent;
  border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 600; }
QPushButton#addBtn:hover { background: #fdf0e6; }
QPushButton#segTab { background: transparent; border: none; border-radius: 999px;
  padding: 4px 12px; font-size: 12px; font-weight: 600; color: #4e5969; }
QPushButton#segTab:checked { background: #ffffff; color: #1f2329; font-weight: 700; }
QFrame#segWrap { background: #f2f3f5; border-radius: 999px; }
QLabel#monoTag { background: #f2f3f5; border-radius: 4px; padding: 1px 7px;
  color: #4e5969; font-family: monospace; font-size: 11px; }
# 卡片间距已归零(grid.setSpacing(0)),圆角从 10px 降到 4px —— 否则相邻卡的
# 圆角互相咬合,网格线上出现锯齿状白缝,反而比留 10px 间距更乱
QFrame#assetCard { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 4px; }
QFrame#assetCard:hover { border-color: #f97316; }
QPlainTextEdit#chapterEdit { background: #ffffff; border: 1px solid #e4e7ec;
  border-radius: 10px; }
QPlainTextEdit#chapterEdit:focus { border-color: #f97316; }
QLabel#coverBadge { background: rgba(0,0,0,0.55); color: #ffffff; border-radius: 4px;
  padding: 1px 6px; font-size: 10px; }
QLabel#coverBadge[state="ready"] { background: #16a34acc; }
QLabel#coverBadge[state="pending"] { background: #e0794bcc; }
QLabel#coverTag { background: rgba(0,0,0,0.62); color: #ffffff; border-radius: 4px;
  padding: 0 5px; font-size: 9px; }
QLabel#placeholderIcon { color: #c0c6cf; font-size: 22px; }
QLabel#roleTag { border-radius: 4px; padding: 1px 7px; font-size: 11px;
  background: #fdf0e6; color: #f97316; }
QLabel#roleTag[role="lead"] { background: #fdecec; color: #dc2626; }
QLabel#roleTag[role="supporting"] { background: #eaf1fe; color: #2563eb; }
QLabel#roleTag[role="extra"] { background: #f2f3f5; color: #6b7280; }
QFrame#finalPrompt { border-top: 1px solid #eef0f3; }
QLabel#finalLabel { font-size: 10px; color: #86909c; letter-spacing: 1px; }
QLabel#finalText { font-size: 11px; color: #4e5969; }
QLabel#statusDot { border-radius: 4px; padding: 0 6px; font-size: 11px;
  background: #f2f3f5; color: #86909c; }
QLabel#statusDot[state="ready"] { background: #e6f6ee; color: #16a34a; }
QLabel#statusDot[state="pending"] { background: #fdf1e7; color: #e0794b; }
QLabel#statusDot[state="failed"] { background: #fdecec; color: #dc2626; }
QFrame#propsEmpty { border: 1px dashed #d5d9e0; border-radius: 10px; }
QFrame#svcCard { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 10px; }
QFrame#svcCard:hover { border-color: #f97316; }
/* 启用开关勾选态用绿色(「开」的语义),不再沿用全局的拍板黑 */
QFrame#svcCard QCheckBox::indicator:checked {
  background: #16a34a; border-color: #16a34a; }
QFrame#emptyState { background: transparent; border: none; }
/* ── 分镜工作台 ── */
QFrame#taskList { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 10px; }
QFrame#taskHead { background: transparent; border: none; border-bottom: 1px solid #e4e7ec; }
QLabel#taskTitle { font-size: 13px; font-weight: 800; }
QPushButton#metricPill { background: #f2f3f5; border: none; border-radius: 999px;
  padding: 2px 9px; font-size: 11px; font-weight: 700; color: #4e5969; }
QPushButton#metricPill[state="pending"] { background: #fdf0e6; color: #f97316; }
QPushButton#metricPill[state="done"] { background: #e6f6ee; color: #16a34a; }
QPushButton#metricPill[state="failed"] { background: #fdecec; color: #dc2626; }
QPushButton#metricPill[state="all"] { background: #e9eaee; color: #1f2329; }
QPushButton#metricPill:checked { border: 2px solid #f97316; }
QFrame#taskRow { background: transparent; border: none; border-top: 1px solid #f2f3f5; }
QFrame#taskRow:hover { background: #f7f8fa; }
QFrame#taskRow[state="selected"] { background: #fdf0e6; }
QFrame#taskRow[state="done"] { background: #f7fdf9; }
QFrame#taskRow[state="failed"] { background: #fdf6f6; }
QLabel#taskIndex { background: rgba(0,0,0,0.56); color: #ffffff; border-radius: 3px;
  padding: 0 4px; font-family: monospace; font-size: 9px; }
QLabel#taskName { font-size: 12px; font-weight: 700; }
QLabel#taskMeta { font-size: 11px; color: #86909c; }
QLabel#taskError { font-size: 11px; color: #dc2626; }
QFrame#inspector { background: #f7f8fa; border: 1px solid #e4e7ec; border-radius: 10px; }
QFrame#playerPanel { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 10px; }
QLabel#playerStage { background: #14161a; color: #b8bcc4; border-radius: 8px; }
QLabel#inspectorLabel { font-size: 12px; font-weight: 700; }
QLabel#heroLabel { font-size: 13px; font-weight: 700; color: #f97316; border-left: 3px solid #f97316; }
QFrame#paramCard { background: #fdf0e6; border: 1px solid #f3c9a4; border-radius: 8px; }
QLabel#effective { background: #ffffff; border: 1px solid #f97316; border-radius: 6px;
  padding: 3px 8px; font-family: monospace; font-size: 11px; color: #f97316; }
QPushButton#refTab { background: transparent; border: none; border-bottom: 2px solid transparent;
  padding: 5px 10px 7px; font-size: 12px; font-weight: 600; color: #86909c; }
QPushButton#refTab:checked { color: #1f2329; border-bottom-color: #f97316; }
QPushButton#ffAction { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 4px;
  padding: 3px 10px; font-size: 11px; font-weight: 600; color: #4e5969; min-height: 22px; }
QPushButton#ffAction:hover { background: #fef3e8; border-color: #f3c9a4; color: #1f2329; }
QPushButton#ffAction:disabled { color: #c0c6cf; background: #f7f8fa; }
QPushButton#ffAction[primary="1"] { background: #f97316; border-color: #f97316; color: #ffffff; }
QPushButton#ffAction[primary="1"]:hover { background: #ea580c; border-color: #ea580c; }
QPushButton#ffAction[primary="1"]:disabled { background: #fde0c8; border-color: #fde0c8; color: #ffffff; }
QFrame#refCard { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 8px; }
QFrame#refCard[bound="1"] { border-color: #f97316; }
QFrame#videoHistoryCard { background: #ffffff; border: 1.5px solid #e4e7ec; border-radius: 6px; }
QFrame#videoHistoryCard:hover { border-color: #f97316; }
QFrame#videoHistoryCard[current="1"] { border-color: #16a34a; }
QFrame#videoHistoryCard[previewing="1"] { border-color: #2563eb; }
QLabel#historyTime { color: #86909c; font-size: 10px; }
QLabel#historyBadge { color: #16a34a; font-size: 10px; font-weight: 700; }
QLabel#refState { font-size: 11px; color: #86909c; }
QLabel#refState[ok="1"] { color: #16a34a; }
QLabel#chip { background: #fdf0e6; color: #f97316; border-radius: 999px; padding: 1px 8px; font-size: 11px; }
QFrame#historyStrip { background: transparent; border: none; border-bottom: 1px solid #e4e7ec; }
/* ── 漫画格 ── */
QFrame#comicCard { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 10px; }
QFrame#comicCard[state="failed"] { border-color: #dc2626; }
QLabel#comicIndex { background: rgba(0,0,0,0.5); color: #ffffff; border-radius: 3px;
  padding: 0 5px; font-family: monospace; font-size: 10px; }
QLabel#comicThumb { background: #f2f3f5; color: #c0c6cf; border-radius: 8px; font-size: 18px; }
QLabel#comicDialogue { background: #fdf0e6; border-left: 2px solid #f97316; border-radius: 4px;
  padding: 3px 7px; font-size: 11px; color: #1f2329; }
QFrame#narrationBox { background: rgba(244,241,236,0.5); border: 1px dashed #d5d9e0; border-radius: 6px; }
QLabel#narrationHead { font-size: 11px; color: #86909c; letter-spacing: 1px; }
QLabel#narrationHint { font-size: 10px; color: #a8b0bb; }
QLabel#comicError { font-size: 11px; color: #dc2626; }
QFrame#stitchBox { background: #f7f8fa; border: 1px solid #e4e7ec; border-radius: 10px; }
QWidget#mergePending { background: transparent; border: none; }
QLabel#mergingWait { color: #86909c; background: transparent; border: none; opacity: 1; }
QLabel#mergingWait[pulse="1"] { opacity: 0.35; }
QLabel#monoTag[mergeElapsed] { color: #e0794b; }
QLabel#refThumb { font-size:22px; background:#f2f3f5; color:#c0c6cf; border-radius:6px; }
QFrame#comicThumbBox { background:#f2f3f5; border:none; border-top-left-radius:10px;
  border-top-right-radius:10px; }
QFrame#videoThumb { background:#f2f3f5; border-radius:4px; }
QLabel#videoThumbIcon { color:#86909c; background:transparent; }
"""

ASSET_QSS_DARK = """
QWidget#prodBar { background: transparent; }
QWidget#prodContent { background: transparent; }
QLabel#sectionTitle { font-size: 12px; font-weight: 800; letter-spacing: 1px; color: #e8eaed; }
QPushButton#addBtn { border: 1px dashed #fb923c; color: #fdba74; background: transparent;
  border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 600; }
QPushButton#addBtn:hover { background: #2e2119; }
QPushButton#segTab { background: transparent; border: none; border-radius: 999px;
  padding: 4px 12px; font-size: 12px; font-weight: 600; color: #8b909a; }
QPushButton#segTab:checked { background: #202126; color: #f2f3f5; font-weight: 700; }
QFrame#segWrap { background: #202126; border-radius: 999px; }
QLabel#monoTag { background: #2a2c33; border-radius: 4px; padding: 1px 7px;
  color: #b8bcc4; font-family: monospace; font-size: 11px; }
QFrame#assetCard { background: #202126; border: 1px solid #2c2e35; border-radius: 4px; }
QFrame#assetCard:hover { border-color: #fb923c; }
QPlainTextEdit#chapterEdit { background: #202126; border: 1px solid #2c2e35;
  border-radius: 10px; }
QPlainTextEdit#chapterEdit:focus { border-color: #fb923c; }
QLabel#coverBadge { background: rgba(0,0,0,0.55); color: #ffffff; border-radius: 4px;
  padding: 1px 6px; font-size: 10px; }
QLabel#coverBadge[state="ready"] { background: #16a34acc; }
QLabel#coverBadge[state="pending"] { background: #e0794bcc; }
QLabel#coverTag { background: rgba(0,0,0,0.62); color: #ffffff; border-radius: 4px;
  padding: 0 5px; font-size: 9px; }
QLabel#placeholderIcon { color: #5a5d66; font-size: 22px; }
QLabel#roleTag { border-radius: 4px; padding: 1px 7px; font-size: 11px;
  background: #2e2119; color: #fdba74; }
QLabel#roleTag[role="lead"] { background: #4a2226; color: #ff8b8f; }
QLabel#roleTag[role="supporting"] { background: #22304d; color: #7aa2f7; }
QLabel#roleTag[role="extra"] { background: #2a2c33; color: #8b909a; }
QFrame#finalPrompt { border-top: 1px solid #2c2e35; }
QLabel#finalLabel { font-size: 10px; color: #5a5d66; letter-spacing: 1px; }
QLabel#finalText { font-size: 11px; color: #b8bcc4; }
QLabel#statusDot { border-radius: 4px; padding: 0 6px; font-size: 11px;
  background: #2a2c33; color: #8b909a; }
QLabel#statusDot[state="ready"] { background: #16321f; color: #4ade80; }
QLabel#statusDot[state="pending"] { background: #3a2a1c; color: #fbbf24; }
QLabel#statusDot[state="failed"] { background: #3d1f22; color: #ff8b8f; }
QFrame#propsEmpty { border: 1px dashed #3a3d46; border-radius: 10px; }
QFrame#svcCard { background: #202126; border: 1px solid #2c2e35; border-radius: 10px; }
QFrame#svcCard QCheckBox::indicator:checked {
  background: #16a34a; border-color: #16a34a; }
QFrame#svcCard:hover { border-color: #fb923c; }
QFrame#emptyState { background: transparent; border: none; }
QFrame#taskList { background: #202126; border: 1px solid #2c2e35; border-radius: 10px; }
QFrame#taskHead { background: transparent; border: none; border-bottom: 1px solid #2c2e35; }
QLabel#taskTitle { font-size: 13px; font-weight: 800; }
QPushButton#metricPill { background: #2a2c33; border: none; border-radius: 999px;
  padding: 2px 9px; font-size: 11px; font-weight: 700; color: #b8bcc4; }
QPushButton#metricPill[state="pending"] { background: #2e2119; color: #fdba74; }
QPushButton#metricPill[state="done"] { background: #16321f; color: #4ade80; }
QPushButton#metricPill[state="failed"] { background: #3d1f22; color: #ff8b8f; }
QPushButton#metricPill[state="all"] { background: #33363e; color: #e8eaed; }
QPushButton#metricPill:checked { border: 2px solid #fb923c; }
QFrame#taskRow { background: transparent; border: none; border-top: 1px solid #26282e; }
QFrame#taskRow:hover { background: #26282e; }
QFrame#taskRow[state="selected"] { background: #2e2119; }
QFrame#taskRow[state="done"] { background: #182018; }
QFrame#taskRow[state="failed"] { background: #241b1d; }
QLabel#taskIndex { background: rgba(0,0,0,0.56); color: #ffffff; border-radius: 3px;
  padding: 0 4px; font-family: monospace; font-size: 9px; }
QLabel#taskName { font-size: 12px; font-weight: 700; }
QLabel#taskMeta { font-size: 11px; color: #8b909a; }
QLabel#taskError { font-size: 11px; color: #ff8b8f; }
QFrame#inspector { background: #1a1c20; border: 1px solid #2c2e35; border-radius: 10px; }
QFrame#playerPanel { background: #202126; border: 1px solid #2c2e35; border-radius: 10px; }
QLabel#playerStage { background: #0e0f12; color: #8b909a; border-radius: 8px; }
QLabel#inspectorLabel { font-size: 12px; font-weight: 700; }
QLabel#heroLabel { font-size: 13px; font-weight: 700; color: #fdba74; border-left: 3px solid #fb923c; }
QFrame#paramCard { background: #1e2338; border: 1px solid #2f3a5e; border-radius: 8px; }
QLabel#effective { background: #202126; border: 1px solid #fb923c; border-radius: 6px;
  padding: 3px 8px; font-family: monospace; font-size: 11px; color: #fdba74; }
QPushButton#refTab { background: transparent; border: none; border-bottom: 2px solid transparent;
  padding: 5px 10px 7px; font-size: 12px; font-weight: 600; color: #8b909a; }
QPushButton#refTab:checked { color: #f2f3f5; border-bottom-color: #fb923c; }
QPushButton#ffAction { background: #202126; border: 1px solid #2c2e35; border-radius: 4px;
  padding: 3px 10px; font-size: 11px; font-weight: 600; color: #b8bcc4; min-height: 22px; }
QPushButton#ffAction:hover { background: #2a2c33; border-color: #fb923c; color: #f2f3f5; }
QPushButton#ffAction:disabled { color: #4e5969; background: #1a1c1f; }
QPushButton#ffAction[primary="1"] { background: #fb923c; border-color: #fb923c; color: #14161a; }
QPushButton#ffAction[primary="1"]:hover { background: #f97316; border-color: #f97316; }
QPushButton#ffAction[primary="1"]:disabled { background: #4a2f1a; border-color: #4a2f1a; color: #8b909a; }
QFrame#refCard { background: #202126; border: 1px solid #2c2e35; border-radius: 8px; }
QFrame#refCard[bound="1"] { border-color: #fb923c; }
QFrame#videoHistoryCard { background: #202126; border: 1.5px solid #2c2e35; border-radius: 6px; }
QFrame#videoHistoryCard:hover { border-color: #fb923c; }
QFrame#videoHistoryCard[current="1"] { border-color: #4ade80; }
QFrame#videoHistoryCard[previewing="1"] { border-color: #7aa2f7; }
QLabel#historyTime { color: #8b909a; font-size: 10px; }
QLabel#historyBadge { color: #4ade80; font-size: 10px; font-weight: 700; }
QLabel#refState { font-size: 11px; color: #8b909a; }
QLabel#refState[ok="1"] { color: #4ade80; }
QLabel#chip { background: #2e2119; color: #fdba74; border-radius: 999px; padding: 1px 8px; font-size: 11px; }
QFrame#historyStrip { background: transparent; border: none; border-bottom: 1px solid #2c2e35; }
QFrame#comicCard { background: #202126; border: 1px solid #2c2e35; border-radius: 10px; }
QFrame#comicCard[state="failed"] { border-color: #ff8b8f; }
QLabel#comicIndex { background: rgba(0,0,0,0.5); color: #ffffff; border-radius: 3px;
  padding: 0 5px; font-family: monospace; font-size: 10px; }
QLabel#comicThumb { background: #1a1c20; color: #5a5d66; border-radius: 8px; font-size: 18px; }
QLabel#comicDialogue { background: #232740; border-left: 2px solid #fb923c; border-radius: 4px;
  padding: 3px 7px; font-size: 11px; color: #e8eaed; }
QFrame#narrationBox { background: rgba(244,241,236,0.04); border: 1px dashed #3a3d46; border-radius: 6px; }
QLabel#narrationHead { font-size: 11px; color: #8b909a; letter-spacing: 1px; }
QLabel#narrationHint { font-size: 10px; color: #6b7280; }
QLabel#comicError { font-size: 11px; color: #ff8b8f; }
QFrame#stitchBox { background: #1a1c20; border: 1px solid #2c2e35; border-radius: 10px; }
QWidget#mergePending { background: transparent; border: none; }
QLabel#mergingWait { color: #8b909a; background: transparent; border: none; opacity: 1; }
QLabel#mergingWait[pulse="1"] { opacity: 0.35; }
QLabel#monoTag[mergeElapsed] { color: #fbbf24; }
QLabel#refThumb { font-size:22px; background:#1a1c20; color:#5a5d66; border-radius:6px; }
QFrame#comicThumbBox { background:#1a1c20; border:none; border-top-left-radius:10px;
  border-top-right-radius:10px; }
QFrame#videoThumb { background:#1a1c20; border-radius:4px; }
QLabel#videoThumbIcon { color:#8b909a; background:transparent; }
"""

# 制作流水线侧栏(对齐原版 episode.vue 的 .sidebar / .pipe-section / .pipe-item /
# .sidebar-progress)。用 objectName 承载,亮暗两套各一份,避免组件里写死颜色。
SIDEBAR_QSS_LIGHT = """
QWidget#sidebar { background: #f7f8fa; border-right: 1px solid #e4e7ec; }
QLabel#pipeSection { color: #4e5969; font-size: 11px; font-weight: 700; letter-spacing: 1px; padding: 10px 4px 2px 4px; }
QLabel#pipeTag { background: #fdf0e6; color: #f97316; border-radius: 4px; padding: 1px 6px; font-size: 11px; font-weight: 600; }
QLabel#pipeState { color: #c0c6cf; font-size: 12px; }
QLabel#pipeState[done="1"] { color: #f97316; }
QPushButton#pipeItem { background: transparent; border: none; border-radius: 6px; padding: 6px 8px; text-align: left; color: #1f2329; }
QPushButton#pipeItem:hover { background: #fdf0e6; color: #f97316; }
QPushButton#pipeItem:checked { background: #fdf0e6; color: #f97316; font-weight: 700; }
QPushButton#pipeItem:disabled { background: transparent; color: #c0c6cf; }
QPushButton#pipeToggle { background: transparent; border: none; color: #86909c; padding: 5px 8px; text-align: left; }
QPushButton#pipeToggle:hover { color: #f97316; }
QPushButton#pipeSeg { background: #e4e7ec; border: none; border-radius: 3px; height: 6px; }
QPushButton#pipeSeg:hover { background: #c0c6cf; }
QPushButton#pipeSeg[state="done"] { background: #f97316; }
QPushButton#pipeSeg[state="current"] { background: #fdba74; }
QLabel#pipeProgLabel { color: #86909c; font-size: 11px; }
QLabel#pipeProgLabel[on="1"] { color: #f97316; font-weight: 700; }
QLabel#pipeProgLabel[done="1"] { color: #4e5969; }
"""

SIDEBAR_QSS_DARK = """
QWidget#sidebar { background: #1a1c20; border-right: 1px solid #2c2e35; }
QLabel#pipeSection { color: #8b909a; font-size: 11px; font-weight: 700; letter-spacing: 1px; padding: 10px 4px 2px 4px; }
QLabel#pipeTag { background: #2e2119; color: #fdba74; border-radius: 4px; padding: 1px 6px; font-size: 11px; font-weight: 600; }
QLabel#pipeState { color: #5a5d66; font-size: 12px; }
QLabel#pipeState[done="1"] { color: #fb923c; }
QPushButton#pipeItem { background: transparent; border: none; border-radius: 6px; padding: 6px 8px; text-align: left; color: #e8eaed; }
QPushButton#pipeItem:hover { background: #26282e; color: #fdba74; }
QPushButton#pipeItem:checked { background: #2e2119; color: #fdba74; font-weight: 700; }
QPushButton#pipeItem:disabled { background: transparent; color: #5a5d66; }
QPushButton#pipeToggle { background: transparent; border: none; color: #8b909a; padding: 5px 8px; text-align: left; }
QPushButton#pipeToggle:hover { color: #fdba74; }
QPushButton#pipeSeg { background: #31343d; border: none; border-radius: 3px; height: 6px; }
QPushButton#pipeSeg:hover { background: #454953; }
QPushButton#pipeSeg[state="done"] { background: #f97316; }
QPushButton#pipeSeg[state="current"] { background: #3d4570; }
QLabel#pipeProgLabel { color: #5a5d66; font-size: 11px; }
QLabel#pipeProgLabel[on="1"] { color: #fdba74; font-weight: 700; }
QLabel#pipeProgLabel[done="1"] { color: #8b909a; }
"""


# 片头标题卡字体(楷书 / 毛笔 / 行书等)。它们**只供 ffmpeg drawtext 与片头预览使用**,
# 不该参与界面正文字体回退 —— 否则 QSS 里的 -apple-system 在 Windows 上解析不到时,
# Qt 会挑中这些花体,把整段正文变成手写体。
TITLE_CARD_FONTS = {
    "SourceHanSansSC-Bold.otf", "LXGWWenKai-Regular.ttf", "MaShanZheng-Regular.ttf",
    "ZCOOLXiaoWei-Regular.ttf", "ZCOOLKuaiLe-Regular.ttf", "ZCOOLQingKeHuangYou-Regular.ttf",
    "LongCang-Regular.ttf", "LiuJianMaoCao-Regular.ttf", "ZhiMangXing-Regular.ttf",
}

# 界面正文字体候选(按优先级;都是系统自带,不依赖打包字体)
UI_FONT_CANDIDATES = [
    "Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC",
    "Source Han Sans SC", "WenQuanYi Micro Hei", "SimHei", "Segoe UI",
]


def load_bundled_fonts(app) -> list[str]:
    """注册 assets/fonts/ 下的打包字体(片头标题卡用);返回已注册 family。"""
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase
    fonts_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    families: list[str] = []
    if fonts_dir.exists():
        for f in sorted(fonts_dir.glob("*")):
            if f.suffix.lower() in (".ttf", ".otf", ".ttc"):
                fid = QFontDatabase.addApplicationFont(str(f))
                fams = QFontDatabase.applicationFontFamilies(fid)
                families += fams
    return families


def resolve_ui_family(preferred: str = "") -> str:
    """挑一个**确实装在系统里**的界面字体族。

    QSS 里的 '-apple-system' 在 Windows 上不存在,Qt 会继续回退;若此时片头花体也在字体库里,
    就会把正文渲染成手写/楷体。这里先按用户偏好、再按候选列表解析成一个真实族名,
    由 apply_theme 显式设成应用默认字体,QSS 的 `*` 规则也用这个具体族名。
    """
    from PySide6.QtGui import QFontDatabase
    installed = set(QFontDatabase.families())
    if preferred:
        # 允许用户直接填族名,也允许从下拉里选「跟随系统」这类空值
        for name in (preferred, *UI_FONT_CANDIDATES):
            if name and name in installed:
                return name
    for name in UI_FONT_CANDIDATES:
        if name in installed:
            return name
    return ""


LIGHT_QSS = """
* { font-family: """ + FONT_STACK + """; font-size: 13px; }
QMainWindow, QDialog { background: #f5f6f8; }
QWidget#card { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 10px; }
QLabel#h1 { font-size: 22px; font-weight: 700; color: #1f2329; }
QLabel#h2 { font-size: 16px; font-weight: 700; color: #1f2329; }
QLabel#muted { color: #86909c; font-size: 12px; }
QLabel#tag { background: #f2f3f5; border-radius: 4px; padding: 2px 8px; color: #4e5969; font-size: 12px; }
QPushButton { background: #f2f3f5; border: none; border-radius: 6px; padding: 6px 14px; color: #1f2329; }
QPushButton:hover { background: #e9ebee; }
QPushButton:pressed { background: #dfe2e7; }
QPushButton:disabled { color: #c0c6cf; background: #f7f8fa; }
QLabel#taskBadge { background: #f97316; color: #ffffff; border-radius: 8px;
  padding: 1px 6px; font-size: 10px; font-weight: 700; }
QPushButton#primary { background: #f97316; border: none; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #ea580c; }
QPushButton#primary:disabled { background: #f6c9a3; color: #f0f1f5; }
QPushButton#blackAction { background: #17181c; border: none; color: #ffffff; font-weight: 600; }
QPushButton#blackAction:hover { background: #2e2f36; }
QPushButton#blackAction:disabled { background: #c9cdd4; color: #f5f6f8; }
QPushButton#danger { color: #dc2626; border: none;
  background: rgba(220,38,38,0.10); font-weight: 600; }
QPushButton#danger:hover { color: #b91c1c; background: rgba(220,38,38,0.16); }
/* 纯图标小按钮:padding 必须压到 0 —— 继承 QPushButton 的 6px 14px 会把 16~20px
   的按钮内容区挤没,图标一个字都画不出来(历史视频卡的下载/删除键就是空白的)。*/
QPushButton#iconBtn { padding: 0; background: transparent; border: 1px solid #e4e7ec;
  border-radius: 4px; }
QPushButton#iconBtn:hover { background: #eef0f3; border-color: #c0c6cf; }
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {
  background: #f2f3f5; border: 1px solid transparent; border-radius: 6px; padding: 5px 8px; color: #1f2329; selection-background-color: #f97316;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #f97316; background: #ffffff; }
QComboBox::drop-down { border: none; background: transparent; width: 20px; }
QSpinBox::up-button, QSpinBox::down-button { background: transparent; border: none; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #e9ebee; border-radius: 4px; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid #e4e7ec; selection-background-color: #fdf0e6; selection-color: #1f2329; }
QListWidget, QTreeWidget, QTableWidget { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 8px; }
QListWidget::item { padding: 6px 8px; border-radius: 6px; }
QListWidget::item:selected { background: #fdf0e6; color: #1f2329; }
QTreeWidget::item, QTableWidget::item { padding: 4px; }
QHeaderView::section { background: #f7f8fa; border: none; border-bottom: 1px solid #e4e7ec; padding: 6px; font-weight: 600; }
QTabWidget::pane { border: 1px solid #e4e7ec; border-radius: 8px; top: -1px; }
QTabBar::tab { padding: 7px 16px; color: #4e5969; border: none; }
QTabBar::tab:selected { color: #f97316; border-bottom: 2px solid #f97316; }
QProgressBar { border: 1px solid #e4e7ec; border-radius: 5px; text-align: center; height: 16px; background: #ffffff; }
QProgressBar::chunk { background: #f97316; border-radius: 4px; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #d5d9e0; border-radius: 5px; min-height: 30px; }
QScrollBar::horizontal { background: transparent; height: 10px; }
QScrollBar::handle:horizontal { background: #d5d9e0; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QMenu { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 6px; }
QMenu::item:selected { background: #fdf0e6; }
QStatusBar { background: #f5f6f8; color: #86909c; }
QSplitter::handle { background: #e4e7ec; }
QToolTip { background: #ffffff; color: #1f2329; border: 1px solid #d5d9e0; padding: 4px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
/* ── 顶栏与分段导航(对齐原版 layouts/default.vue)── */
QWidget#headerBar { background: #f7f8fa; border-bottom: 1px solid #e7e9ee; }
QLabel#brandMark { background: #f97316; color: #ffffff; border-radius: 9px;
  font-size: 17px; font-weight: 800; }
QLabel#brandName { color: #17181a; font-size: 15px; font-weight: 700; background: transparent; }
QLabel#brandSub { color: #9aa1ad; font-size: 10px; background: transparent; }
QFrame#navSegWrap { background: #eef0f3; border-radius: 999px; }
QPushButton#navSeg { background: transparent; border: none; border-radius: 999px;
  padding: 6px 14px; font-size: 13px; font-weight: 600; color: #5c6370; }
QPushButton#navSeg:hover { color: #17181a; }
QPushButton#navSeg:checked { background: #ffffff; color: #17181a; font-weight: 700; }
QPushButton#headerIconBtn { background: transparent; border: none; border-radius: 16px;
  color: #5c6370; font-size: 16px; padding: 6px; min-width: 32px; min-height: 32px; }
QPushButton#headerIconBtn:hover { background: #e9ebef; color: #17181a; }
QPushButton#filterChip { background: #f2f3f5; border: none; border-radius: 999px;
  padding: 6px 14px; font-size: 12px; font-weight: 600; color: #4e5969; }
QPushButton#filterChip:hover { background: #e9ebef; color: #1f2329; }
QPushButton#filterChip:checked { background: #1f2329; color: #ffffff; }
""" + ASSET_QSS_LIGHT + SIDEBAR_QSS_LIGHT

DARK_QSS = """
* { font-family: """ + FONT_STACK + """; font-size: 13px; color: #e8eaed; }
QMainWindow, QDialog { background: #17181c; }
QWidget#card { background: #202126; border: 1px solid #2c2e35; border-radius: 10px; }
QLabel#h1 { font-size: 22px; font-weight: 700; color: #f2f3f5; }
QLabel#h2 { font-size: 16px; font-weight: 700; color: #f2f3f5; }
QLabel#muted { color: #8b909a; font-size: 12px; }
QLabel#tag { background: #2a2c33; border-radius: 4px; padding: 2px 8px; color: #b8bcc4; font-size: 12px; }
QPushButton { background: #2a2c33; border: none; border-radius: 6px; padding: 6px 14px; color: #e8eaed; }
QPushButton:hover { background: #33363f; }
QPushButton:pressed { background: #3a3d46; }
QPushButton:disabled { color: #5a5d66; background: #232529; }
QLabel#taskBadge { background: #f97316; color: #ffffff; border-radius: 8px;
  padding: 1px 6px; font-size: 10px; font-weight: 700; }
QPushButton#primary { background: #f97316; border: none; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #ea580c; }
QPushButton#primary:disabled { background: #31343d; color: #6a6d76; }
QPushButton#blackAction { background: #0d0e11; border: 1px solid #3a3d46; color: #ffffff; font-weight: 600; }
QPushButton#blackAction:hover { background: #1f2126; }
QPushButton#blackAction:disabled { background: #17181c; color: #6a6d76; }
QPushButton#danger { color: #dc2626; border: none; background: rgba(220,38,38,0.16); }
QPushButton#danger:hover { background: rgba(220,38,38,0.26); }
QPushButton#iconBtn { padding: 0; background: transparent; border: 1px solid #2c2e35;
  border-radius: 4px; }
QPushButton#iconBtn:hover { background: #2a2c33; border-color: #3d4048; }
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {
  background: #26282e; border: 1px solid transparent; border-radius: 6px; padding: 5px 8px; color: #e8eaed; selection-background-color: #f97316;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #f97316; }
QComboBox::drop-down { border: none; background: transparent; width: 20px; }
QSpinBox::up-button, QSpinBox::down-button { background: transparent; border: none; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #33363f; border-radius: 4px; }
QComboBox QAbstractItemView { background: #202126; border: 1px solid #3a3d46; selection-background-color: #33364a; }
QListWidget, QTreeWidget, QTableWidget { background: #202126; border: 1px solid #2c2e35; border-radius: 8px; }
QListWidget::item { padding: 6px 8px; border-radius: 6px; }
QListWidget::item:selected { background: #33364a; color: #f2f3f5; }
QHeaderView::section { background: #1d1f24; border: none; border-bottom: 1px solid #2c2e35; padding: 6px; font-weight: 600; }
QTabWidget::pane { border: 1px solid #2c2e35; border-radius: 8px; top: -1px; }
QTabBar::tab { padding: 7px 16px; color: #9aa0aa; border: none; }
QTabBar::tab:selected { color: #fdba74; border-bottom: 2px solid #f97316; }
QProgressBar { border: 1px solid #2c2e35; border-radius: 5px; text-align: center; height: 16px; background: #1d1f24; color: #e8eaed; }
QProgressBar::chunk { background: #f97316; border-radius: 4px; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #3a3d46; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:horizontal { background: #3a3d46; border-radius: 5px; min-width: 30px; }
QMenu { background: #202126; border: 1px solid #3a3d46; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 22px; border-radius: 6px; }
QMenu::item:selected { background: #33364a; }
QStatusBar { background: #17181c; color: #8b909a; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
/* ── 顶栏与分段导航(对齐原版 layouts/default.vue)── */
QWidget#headerBar { background: #f7f8fa; border-bottom: 1px solid #e7e9ee; }
QLabel#brandMark { background: #f97316; color: #ffffff; border-radius: 9px;
  font-size: 17px; font-weight: 800; }
QLabel#brandName { color: #17181a; font-size: 15px; font-weight: 700; background: transparent; }
QLabel#brandSub { color: #9aa1ad; font-size: 10px; background: transparent; }
QFrame#navSegWrap { background: #eef0f3; border-radius: 999px; }
QPushButton#navSeg { background: transparent; border: none; border-radius: 999px;
  padding: 6px 14px; font-size: 13px; font-weight: 600; color: #5c6370; }
QPushButton#navSeg:hover { color: #17181a; }
QPushButton#navSeg:checked { background: #ffffff; color: #17181a; font-weight: 700; }
QPushButton#headerIconBtn { background: transparent; border: none; border-radius: 16px;
  color: #5c6370; font-size: 16px; padding: 6px; min-width: 32px; min-height: 32px; }
QPushButton#headerIconBtn:hover { background: #e9ebef; color: #17181a; }
QPushButton#filterChip { background: #2a2c33; border: none; border-radius: 999px;
  padding: 6px 14px; font-size: 12px; font-weight: 600; color: #b8bcc4; }
QPushButton#filterChip:hover { background: #33364a; color: #f2f3f5; }
QPushButton#filterChip:checked { background: #f97316; color: #ffffff; }
QToolTip { background: #26282e; color: #e8eaed; border: 1px solid #3a3d46; padding: 4px; }
""" + ASSET_QSS_DARK + SIDEBAR_QSS_DARK


def db_get_setting(key: str, default: str = "") -> str:
    """取全局设置(theme 不反向依赖 db 模块,延迟导入避免循环)。"""
    try:
        from .db import get_setting
        return get_setting(key, default)
    except Exception:  # noqa: BLE001
        return default


# ── Director's Slate:启动台项目卡的视觉 token(QSS 之外的硬编码,只为这块专属) ──
#
#  命名约定取自真实场记板的视觉语汇,所有"美化"只在启动台这一面落地,其余页面继续走
#  ASSET_QSS / LIGHT_QSS 不受影响。这样不会把所有页面带跑偏,场记板的差异点是**单一页面
#  的标志性元素**,满足"精力花在一个地方"的设计原则。
SLATE_BG       = "#F5F4EF"   # 米白纸底
SLATE_PAPER    = "#FFFFFF"   # 卡片白
SLATE_BAR      = "#0E0F12"   # 拍板黑(主签名色)
SLATE_MUTED    = "#6B727A"   # 副信息
SLATE_HAIR     = "#DCDAD3"   # 卡边 1px 细灰
SLATE_HAIR_HV  = "#0E0F12"   # hover 强化成拍板黑
SLATE_META     = "#1F2329"   # 标题墨
SLATE_STRIPE   = "#F5F4EF"   # 斜条白(在黑底上)
SLATE_GHOST    = "#A8A6A1"   # 灰白(拍板右侧 meta 字色)
SLATE_TRACK    = "#E4E1D7"   # 进度条空轨(带轻微米色,避免 #FFF 过冷)
SLATE_BAR_INK  = "#F5F4EF"   # 黑条上的主字色
SLATE_BAR_DIM  = "#9a9c9f"   # 黑条上的副字色

# 状态色:刻意脱离 SaaS 惯用的"绿/橙/灰"扁平调,改成更有片场感的低饱和度
SLATE_ST_DONE  = "#6E8C5E"   # 已完成 —— 暗橄榄(像收工打了卡)
SLATE_ST_PROG  = "#C28F4C"   # 进行中 —— 暗琥珀(像卷片)
SLATE_ST_PEND  = "#6B727A"   # 待开始 —— 与 SLATE_MUTED 同
SLATE_ST_FAIL  = "#A14844"   # 失败 —— 砖红

SLATE_CARD_QSS = """
QFrame#slateCard { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 4px; }
QFrame#slateCard:hover { border-color: """ + SLATE_HAIR_HV + """; border-width: 1px; }
QFrame#slateCover { background: """ + SLATE_BG + """; border: none; border-bottom: 1px solid """ + SLATE_HAIR + """; }
QLabel#slateTitle { color: """ + SLATE_META + """; font-size: 14px; font-weight: 600;
  letter-spacing: 0.2px; }
QLabel#slateMeta { color: """ + SLATE_MUTED + """; font-family: """ + MONO_STACK + """;
  font-size: 11px; letter-spacing: 0.3px; }
QLabel#slateMetaDim { color: """ + SLATE_MUTED + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; letter-spacing: 0.3px; opacity: 0.72; }
QLabel#slateStat { color: """ + SLATE_META + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; font-weight: 600; padding: 0 7px; }
QLabel#slateStat[done="1"] { color: """ + SLATE_ST_DONE + """; }
QLabel#slateStat[prog="1"] { color: """ + SLATE_ST_PROG + """; }
QLabel#slateStat[fail="1"] { color: """ + SLATE_ST_FAIL + """; }
QLabel#slateStat[pend="1"] { color: """ + SLATE_MUTED + """; }
QLabel#slateChip { color: """ + SLATE_MUTED + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; padding: 1px 6px; font-family: """ + MONO_STACK + """;
  font-size: 10px; background: transparent; }
QFrame#slateTrack { background: """ + SLATE_TRACK + """; border: none; border-radius: 1px; }
QFrame#slateFill { background: """ + SLATE_BAR + """; border: none; border-radius: 1px; }
QFrame#slateFill[done="1"] { background: """ + SLATE_ST_DONE + """; }
QFrame#slateFill[prog="1"] { background: """ + SLATE_ST_PROG + """; }
QFrame#slateFill[fail="1"] { background: """ + SLATE_ST_FAIL + """; }
QPushButton#slateIconBtn { background: transparent; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; color: """ + SLATE_MUTED + """; font-size: 11px; min-width: 26px;
  min-height: 24px; padding: 0 6px; }
QPushButton#slateIconBtn:hover { border-color: """ + SLATE_BAR + """; color: """ + SLATE_BAR + """; }
/* 启动台顶栏:大字标题走 tracking 风格,不靠 orange 加成撑场面 */
QLabel#slatePageTitle { color: """ + SLATE_BAR + """; font-family: """ + MONO_STACK + """;
  font-size: 13px; font-weight: 700; letter-spacing: 4px; }
QLabel#slatePageSub { color: """ + SLATE_MUTED + """; font-size: 12px; }
QLabel#slateStatBig { color: """ + SLATE_META + """; font-family: """ + MONO_STACK + """;
  font-size: 11px; letter-spacing: 1px; }
QLabel#slateStatBig b { color: """ + SLATE_BAR + """; font-weight: 700; font-size: 13px; }
/* 工具条:filterChip 改方形 4px,segment 上加 mono 序号 */
QPushButton#slateFilter { background: transparent; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; padding: 5px 12px; font-size: 12px; color: """ + SLATE_MUTED + """;
  font-family: """ + MONO_STACK + """; }
QPushButton#slateFilter:hover { border-color: """ + SLATE_BAR + """; color: """ + SLATE_BAR + """; }
QPushButton#slateFilter:checked { background: """ + SLATE_BAR + """; border-color: """ + SLATE_BAR + """;
  color: """ + SLATE_BAR_INK + """; font-weight: 700; }
/* 新建项目按钮:拍板黑底,白字,mono letter-spacing,不用 orange */
QPushButton#slateNew { background: """ + SLATE_BAR + """; border: 1px solid """ + SLATE_BAR + """;
  border-radius: 3px; color: """ + SLATE_BAR_INK + """; padding: 7px 16px; font-size: 12px;
  font-weight: 700; font-family: """ + MONO_STACK + """; letter-spacing: 1.5px; }
QPushButton#slateNew:hover { background: #1F2128; border-color: #1F2128; }
QLineEdit#slateSearch { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; padding: 5px 10px; color: """ + SLATE_META + """; selection-background-color: """ + SLATE_BAR + """;
  selection-color: """ + SLATE_BAR_INK + """; }
QLineEdit#slateSearch:focus { border-color: """ + SLATE_BAR + """; }
QComboBox#slateSort { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; padding: 5px 10px; color: """ + SLATE_META + """;
  font-family: """ + MONO_STACK + """; font-size: 11px; }
QComboBox#slateSort:focus { border-color: """ + SLATE_BAR + """; }
"""


# ── EpisodePage 侧栏 slate 版本 ──
#  与启动台一样的色板,但语义同 StepNav 原组件 —— pipeItem / pipeSection /
#  pipeSeg / pipeState / pipeToggle / pipeProgLabel / pipeTag 全复刻,只换视觉。
SLATE_PIPE_QSS = """
QWidget#sidebar { background: """ + SLATE_PAPER + """; border: none;
  border-right: 1px solid """ + SLATE_HAIR + """; }
QLabel#pipeSection { color: """ + SLATE_BAR + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; font-weight: 700; letter-spacing: 2px; padding: 0; }
QLabel#pipeState { color: """ + SLATE_MUTED + """; font-size: 11px; padding: 0; }
QLabel#pipeState[done="1"] { color: """ + SLATE_ST_DONE + """; font-weight: 700; }
QLabel#pipeTag { color: """ + SLATE_BAR_INK + """; background: """ + SLATE_BAR + """;
  border-radius: 2px; padding: 1px 5px; font-family: """ + MONO_STACK + """;
  font-size: 9px; font-weight: 700; letter-spacing: 1px; }
QPushButton#pipeItem { background: transparent; border: none; border-radius: 3px;
  color: """ + SLATE_META + """; font-family: """ + MONO_STACK + """;
  font-size: 11px; letter-spacing: 0.4px; padding: 7px 8px; text-align: left; }
QPushButton#pipeItem:hover { background: """ + SLATE_BG + """; }
QPushButton#pipeItem:checked { background: """ + SLATE_BAR + """; color: """ + SLATE_BAR_INK + """;
  font-weight: 700; }
QPushButton#pipeItem:disabled { color: #c8c7c2; background: transparent; }
QWidget#pipeProgress { background: transparent; border: none; border-top: 1px solid """ + SLATE_HAIR + """;
  border-bottom: 1px solid """ + SLATE_HAIR + """; padding: 8px 0; }
QLabel#pipeProgLabel { color: """ + SLATE_MUTED + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; letter-spacing: 1px; }
QLabel#pipeProgLabel[on="1"] { color: """ + SLATE_BAR + """; font-weight: 700; }
QLabel#pipeProgLabel[done="1"] { color: """ + SLATE_ST_DONE + """; }
QPushButton#pipeSeg { background: """ + SLATE_TRACK + """; border: none;
  border-radius: 1px; min-height: 4px; padding: 0; }
QPushButton#pipeSeg[state="done"] { background: """ + SLATE_BAR + """; }
QPushButton#pipeSeg[state="current"] { background: """ + SLATE_ST_PROG + """; }
QPushButton#pipeToggle { background: transparent; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; color: """ + SLATE_MUTED + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; padding: 6px; letter-spacing: 1px; }
QPushButton#pipeToggle:hover { border-color: """ + SLATE_BAR + """; color: """ + SLATE_BAR + """; }
"""

# ── ASSET_QSS 的 slate 版本 ──
#  复用 ASSET_QSS_LIGHT 同样的 selector 命名(#assetCard / #coverBadge / #coverTag /
#  #sectionTitle / #addBtn / #segTab / #segWrap / #monoTag / #statusDot / #finalPrompt /
#  #roleTag / #taskList / #taskRow / #taskIndex / #taskName / #taskMeta / #taskError /
#  #inspector / #inspectorLabel / #playerStage / #heroLabel / #paramCard / #effective /
#  #refTab / #refCard / #videoHistoryCard / #historyTime / #historyBadge / #chip /
#  #refState / #refThumb / #comicCard / #comicIndex / #comicThumb / #comicDialogue /
#  #narrationBox / #narrationHead / #narrationHint / #stitchBox / #mergePending /
#  #mergingWait / #videoThumb / #videoThumbIcon / #comicThumbBox 等),把 #f97316/
#  #fdf0e6 体系全替换成 #0E0F12 / #F5F4EF slate 体系。
SLATE_ASSET_QSS = """
QWidget#prodBar { background: transparent; }
QWidget#prodContent { background: transparent; }
QLabel#sectionTitle { color: """ + SLATE_BAR + """; font-family: """ + MONO_STACK + """;
  font-size: 11px; font-weight: 700; letter-spacing: 2px; padding-top: 4px; }
QPushButton#addBtn { border: 1px dashed """ + SLATE_HAIR + """; color: """ + SLATE_MUTED + """;
  background: transparent; border-radius: 3px; padding: 2px 10px; font-size: 11px;
  font-weight: 600; letter-spacing: 0.5px; }
QPushButton#addBtn:hover { border-color: """ + SLATE_BAR + """; color: """ + SLATE_BAR + """;
  background: """ + SLATE_BG + """; }
QPushButton#segTab { background: transparent; border: 1px solid transparent;
  border-radius: 3px; padding: 4px 12px; font-size: 11px; font-weight: 600;
  color: """ + SLATE_MUTED + """; font-family: """ + MONO_STACK + """;
  letter-spacing: 0.3px; }
QPushButton#segTab:hover { color: """ + SLATE_BAR + """; }
QPushButton#segTab:checked { background: """ + SLATE_BAR + """; color: """ + SLATE_BAR_INK + """;
  border-color: """ + SLATE_BAR + """; font-weight: 700; }
QFrame#segWrap { background: transparent; border: 1px solid """ + SLATE_HAIR + """; border-radius: 3px; }
QLabel#monoTag { background: transparent; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; padding: 1px 7px; color: """ + SLATE_MUTED + """;
  font-family: """ + MONO_STACK + """; font-size: 11px; letter-spacing: 0.3px; }
QFrame#assetCard { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 4px; }
QFrame#assetCard:hover { border-color: """ + SLATE_BAR + """; }
QPlainTextEdit#chapterEdit { background: """ + SLATE_PAPER + """;
  border: 1px solid """ + SLATE_HAIR + """; border-radius: 4px; }
QPlainTextEdit#chapterEdit:focus { border-color: """ + SLATE_BAR + """; }
QLabel#coverBadge { background: rgba(14,15,18,0.85); color: """ + SLATE_BAR_INK + """;
  border-radius: 2px; padding: 1px 6px; font-family: """ + MONO_STACK + """;
  font-size: 9px; font-weight: 700; letter-spacing: 1px; }
QLabel#coverBadge[state="ready"] { background: """ + SLATE_ST_DONE + """; }
QLabel#coverBadge[state="pending"] { background: rgba(194,143,76,0.85); }
QLabel#coverTag { background: rgba(14,15,18,0.78); color: """ + SLATE_BAR_INK + """;
  border-radius: 2px; padding: 0 5px; font-family: """ + MONO_STACK + """;
  font-size: 9px; letter-spacing: 0.4px; }
QLabel#placeholderIcon { color: """ + SLATE_HAIR + """; font-size: 22px; }
QLabel#roleTag { border: 1px solid """ + SLATE_HAIR + """; border-radius: 2px;
  padding: 1px 7px; font-family: """ + MONO_STACK + """; font-size: 10px;
  background: transparent; color: """ + SLATE_MUTED + """; letter-spacing: 0.3px; }
QLabel#roleTag[role="lead"] { border-color: """ + SLATE_BAR + """; color: """ + SLATE_BAR + """; }
QLabel#roleTag[role="supporting"] { border-color: #5a6e85; color: #5a6e85; }
QLabel#roleTag[role="extra"] { border-color: """ + SLATE_HAIR + """; color: """ + SLATE_MUTED + """; }
QFrame#finalPrompt { border-top: 1px solid """ + SLATE_HAIR + """; }
QLabel#finalLabel { color: """ + SLATE_BAR + """; font-family: """ + MONO_STACK + """;
  font-size: 9px; font-weight: 700; letter-spacing: 2px; }
QLabel#finalText { color: """ + SLATE_MUTED + """; font-size: 11px; }
QLabel#statusDot { border-radius: 2px; padding: 0 6px; font-family: """ + MONO_STACK + """;
  font-size: 10px; font-weight: 600; letter-spacing: 0.3px;
  background: transparent; border: 1px solid """ + SLATE_HAIR + """;
  color: """ + SLATE_MUTED + """; }
QLabel#statusDot[state="ready"] { border-color: """ + SLATE_ST_DONE + """;
  color: """ + SLATE_ST_DONE + """; }
QLabel#statusDot[state="pending"] { border-color: """ + SLATE_ST_PROG + """;
  color: """ + SLATE_ST_PROG + """; }
QLabel#statusDot[state="failed"] { border-color: """ + SLATE_ST_FAIL + """;
  color: """ + SLATE_ST_FAIL + """; }
QFrame#propsEmpty { border: 1px dashed """ + SLATE_HAIR + """; border-radius: 4px; }
QFrame#svcCard { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 4px; }
QFrame#svcCard:hover { border-color: """ + SLATE_BAR + """; }
QFrame#emptyState { background: transparent; border: 1px dashed """ + SLATE_HAIR + """; border-radius: 4px; }
QFrame#taskList { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 4px; }
QFrame#taskHead { background: transparent; border: none;
  border-bottom: 1px solid """ + SLATE_HAIR + """; }
QLabel#taskTitle { color: """ + SLATE_BAR + """; font-family: """ + MONO_STACK + """;
  font-size: 12px; font-weight: 700; letter-spacing: 1.5px; }
QPushButton#metricPill { background: transparent; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 2px; padding: 2px 9px; font-family: """ + MONO_STACK + """;
  font-size: 10px; font-weight: 600; letter-spacing: 0.5px;
  color: """ + SLATE_MUTED + """; }
QPushButton#metricPill:hover { border-color: """ + SLATE_BAR + """; color: """ + SLATE_BAR + """; }
QPushButton#metricPill[state="pending"] { border-color: """ + SLATE_ST_PROG + """;
  color: """ + SLATE_ST_PROG + """; }
QPushButton#metricPill[state="done"] { border-color: """ + SLATE_ST_DONE + """;
  color: """ + SLATE_ST_DONE + """; }
QPushButton#metricPill[state="failed"] { border-color: """ + SLATE_ST_FAIL + """;
  color: """ + SLATE_ST_FAIL + """; }
QPushButton#metricPill[state="all"] { border-color: """ + SLATE_BAR + """; color: """ + SLATE_BAR + """; }
QPushButton#metricPill:checked { border-width: 2px; }
QFrame#taskRow { background: transparent; border: none;
  border-top: 1px solid """ + SLATE_TRACK + """; }
QFrame#taskRow:hover { background: """ + SLATE_BG + """; }
QFrame#taskRow[state="selected"] { background: """ + SLATE_BG + """;
  border-left: 3px solid """ + SLATE_BAR + """; }
QFrame#taskRow[state="done"] { background: rgba(110,140,94,0.06); }
QFrame#taskRow[state="failed"] { background: rgba(161,72,68,0.06); }
QLabel#taskIndex { background: """ + SLATE_BAR + """; color: """ + SLATE_BAR_INK + """;
  border-radius: 2px; padding: 0 5px; font-family: """ + MONO_STACK + """;
  font-size: 9px; font-weight: 700; letter-spacing: 0.5px; }
QLabel#taskName { color: """ + SLATE_META + """; font-size: 12px; font-weight: 600; }
QLabel#taskMeta { color: """ + SLATE_MUTED + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; letter-spacing: 0.3px; }
QLabel#taskError { color: """ + SLATE_ST_FAIL + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; }
QFrame#inspector { background: """ + SLATE_BG + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 4px; }
QFrame#playerPanel { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 4px; }
QLabel#playerStage { background: """ + SLATE_BAR + """; color: #b8bcc4;
  border-radius: 3px; font-family: """ + MONO_STACK + """; font-size: 11px; }
QLabel#inspectorLabel { color: """ + SLATE_BAR + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; font-weight: 700; letter-spacing: 1.5px; }
QLabel#heroLabel { color: """ + SLATE_BAR + """; border-left: 3px solid """ + SLATE_BAR + """;
  padding-left: 6px; font-family: """ + MONO_STACK + """; font-size: 11px;
  font-weight: 700; letter-spacing: 1.5px; }
QFrame#paramCard { background: """ + SLATE_BG + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 4px; }
QLabel#effective { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_BAR + """;
  border-radius: 3px; padding: 3px 8px; font-family: """ + MONO_STACK + """;
  font-size: 11px; color: """ + SLATE_BAR + """; font-weight: 700;
  letter-spacing: 0.5px; }
QPushButton#refTab { background: transparent; border: none;
  border-bottom: 2px solid transparent; padding: 5px 10px 7px;
  font-family: """ + MONO_STACK + """; font-size: 11px; font-weight: 600;
  color: """ + SLATE_MUTED + """; letter-spacing: 0.5px; }
QPushButton#refTab:checked { color: """ + SLATE_BAR + """;
  border-bottom-color: """ + SLATE_BAR + """; font-weight: 700; }
QPushButton#ffAction { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; padding: 3px 10px;
  font-family: """ + MONO_STACK + """; font-size: 11px; font-weight: 600;
  color: """ + SLATE_BAR + """; letter-spacing: 0.5px; min-height: 22px; }
QPushButton#ffAction:hover { background: #fff; border-color: """ + SLATE_BAR + """;
  color: #14161a; }
QPushButton#ffAction:disabled { color: """ + SLATE_HAIR + """; background: """ + SLATE_PAPER + """; }
QPushButton#ffAction[primary="1"] { background: """ + SLATE_BAR + """; border-color: """ + SLATE_BAR + """;
  color: #fff; }
QPushButton#ffAction[primary="1"]:hover { background: #14161a; border-color: #14161a; }
QPushButton#ffAction[primary="1"]:disabled { background: """ + SLATE_HAIR + """;
  border-color: """ + SLATE_HAIR + """; color: #fff; }
QFrame#refCard { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 4px; }
QFrame#refCard[bound="1"] { border-color: """ + """#f97316""" + """; border-width: 2px;
  background: rgba(249,115,22,0.05); }
QFrame#videoHistoryCard { background: """ + SLATE_PAPER + """;
  border: 1px solid """ + SLATE_HAIR + """; border-radius: 3px; }
QFrame#videoHistoryCard:hover { border-color: """ + SLATE_BAR + """; }
QFrame#videoHistoryCard[current="1"] { border-color: """ + SLATE_ST_DONE + """; }
QFrame#videoHistoryCard[previewing="1"] { border-color: """ + SLATE_ST_PROG + """; }
QLabel#historyTime { color: """ + SLATE_MUTED + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; letter-spacing: 0.3px; }
QLabel#historyBadge { color: """ + SLATE_ST_DONE + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; font-weight: 700; letter-spacing: 0.5px; }
QLabel#refState { color: """ + SLATE_MUTED + """; font-family: """ + MONO_STACK + """;
  font-size: 11px; letter-spacing: 0.3px; }
QLabel#refState[ok="1"] { color: """ + SLATE_ST_DONE + """; }
QLabel#chip { background: transparent; color: """ + SLATE_MUTED + """;
  border: 1px solid """ + SLATE_HAIR + """; border-radius: 2px; padding: 1px 8px;
  font-family: """ + MONO_STACK + """; font-size: 10px; letter-spacing: 0.5px; }
QFrame#historyStrip { background: transparent; border: none;
  border-bottom: 1px solid """ + SLATE_HAIR + """; }
QFrame#comicCard { background: """ + SLATE_PAPER + """;
  border: 1px solid """ + SLATE_HAIR + """; border-radius: 4px; }
QFrame#comicCard[state="failed"] { border-color: """ + SLATE_ST_FAIL + """; }
QLabel#comicIndex { background: """ + SLATE_BAR + """; color: """ + SLATE_BAR_INK + """;
  border-radius: 2px; padding: 0 5px; font-family: """ + MONO_STACK + """;
  font-size: 9px; font-weight: 700; letter-spacing: 0.5px; }
QLabel#comicThumb { background: """ + SLATE_BG + """; color: """ + SLATE_MUTED + """;
  border-radius: 4px; font-size: 18px; }
QLabel#comicDialogue { background: """ + SLATE_BG + """;
  border-left: 2px solid """ + SLATE_BAR + """; border-radius: 3px;
  padding: 3px 7px; font-size: 11px; color: """ + SLATE_META + """; }
QFrame#narrationBox { background: """ + SLATE_BG + """; border: 1px dashed """ + SLATE_HAIR + """;
  border-radius: 3px; }
QLabel#narrationHead { color: """ + SLATE_BAR + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel#narrationHint { color: """ + SLATE_MUTED + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; letter-spacing: 0.3px; }
QLabel#comicError { color: """ + SLATE_ST_FAIL + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; }
QFrame#stitchBox { background: """ + SLATE_BG + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 4px; }
QWidget#mergePending { background: transparent; border: none; }
QLabel#mergingWait { color: """ + SLATE_MUTED + """; background: transparent;
  border: none; opacity: 1; font-family: """ + MONO_STACK + """; font-size: 10px;
  letter-spacing: 0.5px; }
QLabel#mergingWait[pulse="1"] { opacity: 0.35; }
QLabel#monoTag[mergeElapsed] { color: """ + SLATE_ST_PROG + """; }
QLabel#refThumb { color: """ + SLATE_MUTED + """; background: """ + SLATE_BG + """;
  border-radius: 4px; font-size: 22px; }
QFrame#comicThumbBox { background: """ + SLATE_BG + """; border: none;
  border-top-left-radius: 4px; border-top-right-radius: 4px; }
QFrame#videoThumb { background: """ + SLATE_BG + """; border-radius: 3px; }
QLabel#videoThumbIcon { color: """ + SLATE_MUTED + """; background: transparent; }
"""

# ── NewProjectDialog / SettingsDialog 表单 slate 版本 ──
#  全局控件级,挂在对话框根 setStyleSheet,跟 SLATE_ASSET_QSS / SLATE_CARD_QSS 互不干扰
#  (后者只用于特定 objectName 的卡片)。
SLATE_FORM_QSS = """
QLineEdit { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; padding: 6px 10px; color: """ + SLATE_META + """; selection-background-color: """ + SLATE_BAR + """;
  selection-color: """ + SLATE_BAR_INK + """; font-size: 13px; }
QLineEdit:focus { border-color: """ + SLATE_BAR + """; }
QLineEdit:disabled { background: """ + SLATE_BG + """; color: """ + SLATE_MUTED + """; }
QComboBox { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; padding: 5px 10px; color: """ + SLATE_META + """;
  font-size: 12px; min-height: 20px; }
QComboBox:focus { border-color: """ + SLATE_BAR + """; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView { background: """ + SLATE_PAPER + """;
  border: 1px solid """ + SLATE_HAIR + """; selection-background-color: """ + SLATE_BG + """;
  selection-color: """ + SLATE_BAR + """; outline: 0; padding: 4px; }
QComboBox QAbstractItemView::item { padding: 4px 8px; border-radius: 2px; }
QSpinBox, QDoubleSpinBox { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; padding: 4px 8px; color: """ + SLATE_META + """; }
QSpinBox:focus, QDoubleSpinBox:focus { border-color: """ + SLATE_BAR + """; }
QPlainTextEdit, QTextEdit { background: """ + SLATE_PAPER + """;
  border: 1px solid """ + SLATE_HAIR + """; border-radius: 3px; padding: 6px 10px;
  color: """ + SLATE_META + """; selection-background-color: """ + SLATE_BAR + """;
  selection-color: """ + SLATE_BAR_INK + """; font-size: 12px; }
QPlainTextEdit:focus, QTextEdit:focus { border-color: """ + SLATE_BAR + """; }
QRadioButton { color: """ + SLATE_META + """; spacing: 8px; padding: 4px 0;
  font-size: 12px; }
QRadioButton::indicator { width: 14px; height: 14px;
  border: 1.5px solid """ + SLATE_HAIR + """; border-radius: 7px;
  background: """ + SLATE_PAPER + """; }
QRadioButton::indicator:hover { border-color: """ + SLATE_BAR + """; }
QRadioButton::indicator:checked { border-color: """ + SLATE_BAR + """;
  background: """ + SLATE_BAR + """;
  /* 内部圆点用一种不依赖图像的拙朴做法:在 indicator 内叠一层 */
  image: none; }
QRadioButton::indicator:checked { border: 4px solid """ + SLATE_BAR + """;
  background: """ + SLATE_PAPER + """; }
QCheckBox { color: """ + SLATE_META + """; spacing: 8px; padding: 4px 0;
  font-size: 12px; }
QCheckBox::indicator { width: 14px; height: 14px;
  border: 1.5px solid """ + SLATE_HAIR + """; border-radius: 2px;
  background: """ + SLATE_PAPER + """; }
QCheckBox::indicator:hover { border-color: """ + SLATE_BAR + """; }
QCheckBox::indicator:checked { background: """ + SLATE_BAR + """;
  border-color: """ + SLATE_BAR + """; }
/* 服务卡片的启用开关:勾选态用绿色(「开」的语义) */
QFrame#svcCard QCheckBox::indicator:checked { background: #16a34a;
  border-color: #16a34a; }
QPushButton { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; color: """ + SLATE_META + """; padding: 6px 14px;
  font-size: 12px; font-weight: 600; }
QPushButton:hover { border-color: """ + SLATE_BAR + """; color: """ + SLATE_BAR + """; }
QPushButton#iconBtn { padding: 0; background: transparent; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; }
QPushButton#iconBtn:hover { background: """ + SLATE_PAPER + """; border-color: """ + SLATE_BAR + """; }
QPushButton:pressed { background: """ + SLATE_BG + """; }
QPushButton:disabled { color: #c8c7c2; border-color: """ + SLATE_HAIR + """; background: transparent; }
QPushButton#slatePrimary { background: """ + SLATE_BAR + """; border: 1px solid """ + SLATE_BAR + """;
  border-radius: 3px; color: """ + SLATE_BAR_INK + """; padding: 7px 18px;
  font-size: 12px; font-weight: 700; letter-spacing: 0.5px; }
QPushButton#slatePrimary:hover { background: #1F2128; border-color: #1F2128; }
QPushButton#slateDanger { background: transparent; border: 1px solid """ + SLATE_ST_FAIL + """;
  border-radius: 3px; color: """ + SLATE_ST_FAIL + """; padding: 6px 14px;
  font-size: 12px; font-weight: 600; }
QPushButton#slateDanger:hover { background: """ + SLATE_ST_FAIL + """; color: """ + SLATE_BAR_INK + """; }
QLabel { color: """ + SLATE_META + """; font-size: 12px; background: transparent; }
QLabel[required="1"] { color: """ + SLATE_META + """; font-size: 12px; font-weight: 600; }
QLabel#slateH2 { color: """ + SLATE_BAR + """; font-size: 15px; font-weight: 700;
  letter-spacing: 0.3px; }
QLabel#slateMuted { color: """ + SLATE_MUTED + """; font-size: 11px; }
QLabel#slateGroupHead { color: """ + SLATE_BAR + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; font-weight: 700; letter-spacing: 2px; padding-top: 8px; }
QGroupBox { background: transparent; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 4px; margin-top: 14px; padding: 14px 12px 8px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left;
  padding: 0 8px; color: """ + SLATE_BAR + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QScrollArea { background: transparent; border: none; }
QTabWidget::pane { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 0 0 4px 4px; top: -1px; padding: 12px; }
QTabBar::tab { background: transparent; color: """ + SLATE_MUTED + """;
  border: 1px solid transparent; border-bottom: none;
  padding: 6px 16px; font-size: 12px; font-weight: 600; }
QTabBar::tab:hover { color: """ + SLATE_BAR + """; }
QTabBar::tab:selected { background: """ + SLATE_PAPER + """;
  border-color: """ + SLATE_HAIR + """; color: """ + SLATE_BAR + """;
  border-radius: 4px 4px 0 0; }
QTableWidget { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; gridline-color: """ + SLATE_HAIR + """; }
QHeaderView::section { background: """ + SLATE_BG + """; border: none;
  border-right: 1px solid """ + SLATE_HAIR + """; border-bottom: 1px solid """ + SLATE_HAIR + """;
  padding: 6px 8px; color: """ + SLATE_BAR + """; font-family: """ + MONO_STACK + """;
  font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QTreeWidget { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; }
QTreeWidget::item { padding: 4px 0; }
QTreeWidget::item:hover { background: """ + SLATE_BG + """; }
QTreeWidget::item:selected { background: """ + SLATE_BG + """; color: """ + SLATE_BAR + """; }
QListWidget { background: """ + SLATE_PAPER + """; border: 1px solid """ + SLATE_HAIR + """;
  border-radius: 3px; }
QListWidget::item { padding: 6px 8px; }
QListWidget::item:hover { background: """ + SLATE_BG + """; }
QListWidget::item:selected { background: """ + SLATE_BG + """;
  color: """ + SLATE_BAR + """; }
"""


def apply_theme(app, mode: str = "light", preferred: str = "") -> None:
    """应用配色:先设调色板(让未显式设 background 的 QWidget 跟随主题),再挂 QSS。"""
    from PySide6.QtGui import QColor, QPalette
    dark = mode == "dark"
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#17181c" if dark else "#f5f6f8"))
    pal.setColor(QPalette.WindowText, QColor("#e8eaed" if dark else "#1f2329"))
    pal.setColor(QPalette.Base, QColor("#1d1f24" if dark else "#ffffff"))
    pal.setColor(QPalette.AlternateBase, QColor("#202126" if dark else "#f7f8fa"))
    pal.setColor(QPalette.Text, QColor("#e8eaed" if dark else "#1f2329"))
    pal.setColor(QPalette.Button, QColor("#26282e" if dark else "#ffffff"))
    pal.setColor(QPalette.ButtonText, QColor("#e8eaed" if dark else "#1f2329"))
    pal.setColor(QPalette.ToolTipBase, QColor("#26282e" if dark else "#ffffff"))
    pal.setColor(QPalette.ToolTipText, QColor("#e8eaed" if dark else "#1f2329"))
    pal.setColor(QPalette.Highlight, QColor("#f97316"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.Link, QColor("#fdba74" if dark else "#f97316"))
    app.setPalette(pal)
    qss = DARK_QSS if mode == "dark" else LIGHT_QSS
    family = resolve_ui_family(preferred or db_get_setting("ui_font", ""))
    if family:
        from PySide6.QtGui import QFont
        f = QFont(family)
        f.setPointSize(app.font().pointSize() or 9)
        app.setFont(f)
        # QSS 的 `*` 用具体族名,别再让 Qt 自由回退挑到片头花体
        qss = qss.replace(FONT_STACK, f"'{family}'", 1)
    app.setStyleSheet(qss)
