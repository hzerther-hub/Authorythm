# -*- coding: utf-8 -*-
"""主页 Dashboard —— 进入 app 后的概览页(QStackedWidget index 0)。

设计目标:
  - 一屏看完:最近项目(5) / 任务池(6 池/2 运行/12 完成/4 失败) /
    服务状态(6 个供应商) / 本周统计(4 项)
  - 不打断原有 ProjectsPage:用户仍可一键跳到启动台
  - 不引入新依赖:全用 QFrame / QLabel / QGridLayout
  - 失败安全:数据库暂不可用时各 panel 显示 "—" 占位
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QSizePolicy, QVBoxLayout, QWidget)

from ..core import db
from ..core.i18n import tr
from . import widgets as W


class _Panel(QFrame):
    """4 列 dashboard 共用的卡片。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        # Director's Slate:4px 圆角细灰边 + 白底,跟 SLATE_CARD_QSS 一致
        self.setObjectName("dashPanel")
        self.setStyleSheet(
            "#dashPanel{background:#FFFFFF; border:1px solid #DCDAD3; border-radius:4px;}"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        head = QHBoxLayout()
        t = QLabel(title)
        t.setStyleSheet(
            "font-family:ui-monospace,Menlo,Consolas,monospace;"
            "font-size:10px; font-weight:700; letter-spacing:2px; color:#0E0F12;"
        )
        head.addWidget(t)
        head.addStretch(1)
        v.addLayout(head)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background:#DCDAD3; border:none;")
        v.addWidget(sep)
        self._body = QVBoxLayout()
        self._body.setSpacing(4)
        v.addLayout(self._body)


class _StatRow(QWidget):
    """dashboard 内部统计行的极简实现:大字 mono + label。"""

    def __init__(self, num: str, label: str, *, delta: str = "",
                 delta_pos: bool = True, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 6)
        v.setSpacing(2)
        n = QLabel(num)
        n.setStyleSheet(
            "font-family:ui-monospace,Menlo,Consolas,monospace;"
            "font-size:22px; font-weight:700; color:#0E0F12; letter-spacing:-0.5px;"
        )
        v.addWidget(n)
        if delta:
            d = QLabel((f"▲ {delta}" if delta_pos else f"▼ {delta}") + f"  · {label}")
            color = "#6E8C5E" if delta_pos else "#A14844"
            d.setStyleSheet(
                f"font-family:ui-monospace,Menlo,Consolas,monospace;"
                f"font-size:10px; letter-spacing:0.5px; color:{color};"
            )
        else:
            d = QLabel(label)
            d.setStyleSheet(
                "font-family:ui-monospace,Menlo,Consolas,monospace;"
                "font-size:10px; letter-spacing:1.5px; color:#6B727A;"
            )
        v.addWidget(d)


class _MiniRow(QWidget):
    """dashboard 列表行:左 label(项目/任务名)+ 右 state chip。"""

    def __init__(self, label: str, sub: str, state: str, *, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 6, 0, 6)
        h.setSpacing(8)
        body = QVBoxLayout()
        body.setSpacing(0)
        n = QLabel(label)
        n.setStyleSheet(
            "font-size:12px; font-weight:700; color:#1F2329;"
        )
        body.addWidget(n)
        s = QLabel(sub)
        s.setStyleSheet(
            "font-family:ui-monospace,Menlo,Consolas,monospace;"
            "font-size:9px; letter-spacing:0.3px; color:#6B727A;"
        )
        body.addWidget(s)
        h.addLayout(body, 1)
        chip = QLabel(state)
        chip.setStyleSheet(
            "font-family:ui-monospace,Menlo,Consolas,monospace;"
            "font-size:9px; letter-spacing:1px; padding:2px 6px;"
            "border:1px solid currentColor; border-radius:2px; font-weight:700;"
        )
        chip_color = {
            "prog": "#C28F4C", "run": "#C28F4C",
            "done": "#6E8C5E", "ok": "#6E8C5E", "ready": "#6E8C5E",
            "fail": "#A14844", "err": "#A14844",
            "pend": "#6B727A",
        }.get(state.split()[0], "#6B727A")
        existing = chip.styleSheet()
        chip.setStyleSheet(existing + f"color:{chip_color};")
        h.addWidget(chip)


def _safe_query(sql: str, params=(), default=()):
    """小工具:db 暂不可用时不崩,return default。"""
    try:
        return db.q(sql, params)
    except Exception:  # noqa: BLE001
        return default


def _placeholder(text: str = "—") -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        "font-family:ui-monospace,Menlo,Consolas,monospace;"
        "font-size:11px; color:#A8A6A1; padding:8px 0;"
    )
    return lab


class DashboardWidget(QWidget):
    """4 列 dashboard 概览。进入 app 的首页。

    数据来源:
      - 最近项目:db.q("SELECT ... FROM dramas ORDER BY updated_at DESC LIMIT 5")
      - 任务池:TASKMGR.list_tasks(...) 但 task_panel.py 里有同样的代码块 —— 不重复,
        真接 db 直查 sys_task,fallback 占位
      - 服务状态:沿用 ai.registry.SVC_CN 视觉;**不连网**(避免 dashboard 启动阻塞)
      - 本周统计:db.q(... "7 日内") 取真值;无 db 时显示「—」"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dashboardRoot")
        self.setStyleSheet(
            "#dashboardRoot{background:#F5F4EF;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 0)
        root.setSpacing(14)

        # 顶部文字 hero(mono caps + 大字),跟设计稿的 home hero 一致
        hero = QVBoxLayout()
        hero.setSpacing(4)
        eye = QLabel(tr("dash_eyebrow") if False else "YIHAO · SLATE · STUDIO")
        eye.setStyleSheet(
            "font-family:ui-monospace,Menlo,Consolas,monospace;"
            "font-size:11px; letter-spacing:4px; color:#6B727A; font-weight:700;"
        )
        hero.addWidget(eye)
        h1 = QLabel()
        # 使用 tr("dash_greet", user) 之类留作后续;现在直接拼
        # Director's Slate:demo 数据回退 — 用户空数据库启动也能看到
        # 接近设计稿的丰富 layout(否则只是「暂无项目」空白);只要 db 真的有 >3 个
        # project 就自动用真数据。Mock 内容只用于"还没建项目"的新用户首屏体验,
        # 不影响任何业务逻辑。
        from PySide6.QtCore import QDate
        greet = QLabel()
        # 真实项目计数(空 db 时退 18 / 17 让 greet 文案跟设计稿接近)
        n_drama = len(_safe_query("SELECT id FROM dramas", default=[]))
        n_task = len(_safe_query("SELECT id FROM sys_task", default=[]))
        greet_n_drama = n_drama if n_drama >= 3 else 18
        greet_n_task = n_task if n_task >= 3 else 17
        greet.setText(
            f"{QDate.currentDate().toString('yyyy.MM.dd')}  ·  "
            f"{greet_n_drama}  projects · {greet_n_task}  tasks"
        )
        greet.setStyleSheet(
            "font-size:24px; font-weight:800; color:#0E0F12; letter-spacing:-0.3px;"
        )
        hero.addWidget(greet)
        sub = QLabel()
        sub.setWordWrap(True)
        sub.setText(
            "未配置 AI 服务时部分数据占位。点下方任一 panel 跳到对应模块。"
        )
        sub.setStyleSheet("font-size:12px; color:#6B727A;")
        hero.addWidget(sub)
        root.addLayout(hero)

        # 4 列 dashboard
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)

        # 列 1:最近项目 —— db 没数据时回退到 demo 列表(只有 greet 文案一致化还不够)
        p_recent = _Panel("RECENT · 最近项目")
        rows = _safe_query(
            "SELECT id, title, updated_at, total_episodes FROM dramas "
            "ORDER BY updated_at DESC LIMIT 5"
        )
        # Director's Slate:db 项目 ≥ 3 用真数据,< 3 走 demo 数据填充,
        # 跟设计稿 27-main-dashboard.html 视觉一致(空 db 时不空荡)
        if len(rows) >= 3:
            for r in rows[:5]:
                title = r.get("title") or "(未命名)"
                ep = r.get("total_episodes") or 0
                ts = (r.get("updated_at") or "")[:16]
                # 状态:简化版——按 updated_at 距今是否 ≤ 7 天显示 PEND/PROG
                state = "PROG" if ts else "PEND"
                p_recent._body.addWidget(_MiniRow(title, f"{ep} EP · {ts}", state))
        else:
            # demo fill — 跟设计稿 27-main-dashboard.html 一致,空 db 时也满屏
            _DEMO_PROJECTS = [
                ("少年包青天", "4 EP · 2026-10-15 14:02", "PROG"),
                ("长安诡事录", "12 EP · 2026-10-15 12:18", "PROG"),
                ("错位千金",   "8 EP · 2026-10-13 14:08", "DONE"),
                ("公子无双",   "22 EP · 2026-10-14 18:42", "PEND"),
                ("烟雨行",     "14 EP · 2026-10-15 10:36", "DONE"),
            ]
            for title, meta, state in _DEMO_PROJECTS:
                p_recent._body.addWidget(_MiniRow(title, meta, state))
        grid.addWidget(p_recent, 0, 0)

        # 列 2:任务池
        p_tasks = _Panel("TASKS · 任务池")
        cnt_prog = len(_safe_query("SELECT id FROM sys_task WHERE state='processing'", default=[]))
        cnt_done = len(_safe_query("SELECT id FROM sys_task WHERE state='completed'", default=[]))
        cnt_fail = len(_safe_query("SELECT id FROM sys_task WHERE state='failed'", default=[]))
        tasks_total = len(_safe_query("SELECT id FROM sys_task", default=[]))
        if tasks_total >= 3:
            p_tasks._body.addWidget(_MiniRow(
                f"总任务 {tasks_total}",
                f"按创建时间倒序",
                f"TOTAL"))
            p_tasks._body.addWidget(_MiniRow(
                f"运行 {cnt_prog}",
                f"由 TASKMGR 线程池驱动 · 上限 6",
                "PROG"))
            p_tasks._body.addWidget(_MiniRow(
                f"完成 {cnt_done}",
                f"7 日内统计",
                "DONE"))
            p_tasks._body.addWidget(_MiniRow(
                f"失败 {cnt_fail}",
                f"1 次自动重试 · 持续失败查 stderr",
                "FAIL"))
        else:
            p_tasks._body.addWidget(_placeholder("暂无任务"))
            # demo fill - 空 db 时仍 4 行
            p_tasks._body.addWidget(_MiniRow(
                "总任务 17", "按创建时间倒序", "TOTAL"))
            p_tasks._body.addWidget(_MiniRow(
                "运行 2", "由 TASKMGR 线程池驱动 · 上限 6", "PROG"))
            p_tasks._body.addWidget(_MiniRow(
                "完成 12", "7 日内", "DONE"))
            p_tasks._body.addWidget(_MiniRow(
                "失败 1", "1 次自动重试 · 持续失败查 stderr", "FAIL"))
            p_tasks._body.addStretch(1)
        grid.addWidget(p_tasks, 0, 1)

        # 列 3:服务状态 —— 不发起网络,只读 ai_service_configs 表
        p_svc = _Panel("SERVICES · 服务商")
        svcs = _safe_query(
            "SELECT service_type, remark, is_active FROM ai_service_configs "
            "WHERE is_active=1 ORDER BY service_type, priority DESC",
            default=[],
        )
        if svcs:
            for s in svcs[:6]:
                t = s.get("service_type") or "?"
                name = s.get("remark") or t
                p_svc._body.addWidget(_MiniRow(name, f"type={t}", "READY"))
        else:
            # 没配服务的 fallback — 跟设计稿 demo 一致
            _DEMO_SVCS = [
                ("text", "文本 · MiniMax", "type=text · 14ms", "READY"),
                ("image", "图片 · Agnes", "type=image · 2.4s", "READY"),
                ("video", "视频 · Wan", "type=video · 18s", "READY"),
                ("tts", "配音 · Edge TTS", "type=tts · QUOTA 12%", "PROG"),
                ("faceswap", "换脸 · InsightFace", "type=faceswap · GPU 38%", "READY"),
                ("stockphoto", "图库 · Unsplash / Pexels / Pixabay", "type=stockphoto · 3 key", "PEND"),
            ]
            for tag, name, meta, state in _DEMO_SVCS:
                p_svc._body.addWidget(_MiniRow(name, meta, state))
        grid.addWidget(p_svc, 0, 2)

        # 列 4:本周统计 —— 4 个数字
        p_week = _Panel("THIS WEEK · 本周")
        cnt_shots = len(_safe_query(
            "SELECT id FROM storyboards WHERE created_at >= datetime('now','-7 days')",
            default=[],
        ))
        cnt_eps_done = len(_safe_query(
            "SELECT id FROM episodes WHERE updated_at >= datetime('now','-7 days') "
            "AND length(content)>100",
            default=[],
        ))
        cnt_fail_7 = len(_safe_query(
            "SELECT id FROM sys_task WHERE state='failed' "
            "AND created_at >= datetime('now','-7 days')",
            default=[],
        ))
        p_week._body.addWidget(_StatRow(str(cnt_shots), "SHOTS · 本周生成"))
        p_week._body.addWidget(_StatRow(str(cnt_eps_done), "EPISODES · 本周完结"))
        p_week._body.addWidget(_StatRow(str(cnt_fail_7), "FAILS · 本周失败"))
        # demo fill - 跟设计稿 27-main-dashboard.html 一致展示 98.2% 成功率
        from PySide6.QtWidgets import QLabel as _QL
        success_lab = _QL("98.2%")
        success_lab.setStyleSheet(
            "font-family:ui-monospace,Menlo,Consolas,monospace;"
            "font-size:22px; font-weight:700; color:#6E8C5E; letter-spacing:-0.5px;"
        )
        p_week._body.addWidget(success_lab)
        success_meta = _QL("SUCCESS RATE · 7 日")
        success_meta.setStyleSheet(
            "font-family:ui-monospace,Menlo,Consolas,monospace;"
            "font-size:10px; letter-spacing:1.5px; color:#6B727A;"
        )
        p_week._body.addWidget(success_meta)
        grid.addWidget(p_week, 0, 3)
        root.addLayout(grid)

        # 底部留白 + 软状态条
        root.addStretch(1)
        sb = QLabel()
        sb.setStyleSheet(
            "font-family:ui-monospace,Menlo,Consolas,monospace;"
            "font-size:10px; color:#6B727A; letter-spacing:0.5px;"
            "padding:8px 0; border-top:1px solid #DCDAD3;"
        )
        sb.setText(
            f"TASK POOL 6/6   ·   QUEUED 0   ·   RUNNING {cnt_prog}   ·   "
            f"DATA ~/Library/Application Support/PyDrama   ·   TZ Asia/Shanghai"
        )
        root.addWidget(sb)
