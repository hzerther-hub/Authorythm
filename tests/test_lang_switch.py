# -*- coding: utf-8 -*-
"""回归:语言切换必须重建**所有**页面,不是只有 projects/project/episode。

实测踩过两个坑叠在一起,表现为「切语言大部分无效」:

  1. `_rebuild_ui` 只重建当前页,其余页面靠 `_stale_pages` 标记 + 进入时
     `_ensure_fresh` 懒重建 —— 但 stale 集合里只放了 projects/project/episode,
     dashboard / 聊天改图 / 复刻 / 换脸 / 合并**永远停在旧语言**(不报错)。
  2. `_make_page` 也只有那三种的分支,其它 kind 返回 None;就算标了 stale,
     `_ensure_fresh` 拿到 None 也只是放弃。

修复后 `_make_page` 必须覆盖 `_PAGE_KINDS` 的每一种(数据页 project/episode
除外 —— 它们需要打开过的项目才有意义,返回 None 是合法的)。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _pump(qapp, n=4):
    """跑几轮事件循环,让 QTimer.singleShot(0, ...) 里的重建真正执行。"""
    for _ in range(n):
        qapp.processEvents()


@pytest.fixture()
def win(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    yield w
    w.deleteLater()
    _pump(qapp, 1)


def teardown_module():
    """语言是进程级全局,测完切回中文,别污染后面的用例。"""
    from app.core.i18n import set_language
    set_language("zh")


def test_make_page_supports_every_data_free_kind(win):
    """不依赖项目数据的页面,._make_page 必须都能造出来。

    project/episode 要打开过的项目才有意义(drama_id=0 时返回 None 合法),
    其余 kind 返回 None 就意味着该页语言切换后永远停在旧语言。
    """
    for kind in ("dashboard", "projects", "clone", "face_swap", "merger", "chatedit"):
        p = win._make_page(kind)
        assert p is not None, (
            f"_make_page({kind!r}) 返回 None —— 语言切换后「{kind}」页会停在旧语言")
        p.deleteLater()


def test_language_switch_replaces_tool_pages(win, qapp):
    """切语言后:当前页立即重建;其余页进入时懒重建(_ensure_fresh)。"""
    from app.core.i18n import set_language

    # 起点在仪表盘(栈第 0 页)→ 它必须立即被换掉
    win._goto("dashboard")
    _pump(qapp, 1)
    old_dash = win.dashboard
    set_language("en")
    _pump(qapp); _pump(qapp)
    assert win.dashboard is not old_dash, "当前页(仪表盘)没随语言切换立即重建"

    # 聊天改图不是当前页 → 进入时懒重建
    old_chat = win.chat_edit_page
    win._goto("chatedit")
    _pump(qapp, 1)
    assert win.chat_edit_page is not old_chat, "进入聊天改图页时没有按新语言重建"


def test_chat_session_survives_language_switch(win, qapp):
    """切语言重建聊天改图页,当前会话视图必须还在(会话本体在 SQLite)。"""
    from app.core import db
    from app.core.i18n import set_language
    import tempfile, os
    from PIL import Image

    img = os.path.join(tempfile.mkdtemp(), "s.png")
    Image.new("RGB", (16, 16)).save(img)
    win.chat_edit_page.set_image(img)          # 建会话并设为当前图
    sid = win.chat_edit_page.panel._session_id
    assert sid, "前置失败:没建出会话"

    set_language("en")
    _pump(qapp); _pump(qapp)
    win._goto("chatedit")     # 懒重建在这里发生
    _pump(qapp, 1)

    assert win.chat_edit_page.panel._session_id == sid, "重建后当前会话丢了"
    db.delete_chat_session(sid)


def test_i18n_dashboard_keys_render_per_language():
    """仪表盘新键在主词典缺失时必须能从补充词典拿到各语言译文。"""
    from app.core.i18n import tr, set_language
    try:
        set_language("ja")
        assert "タスク" in tr("dash_tasks_panel")
        set_language("en")
        assert tr("dash_total_n").format(3) == "Total tasks 3"
    finally:
        set_language("zh")
