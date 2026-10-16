# -*- coding: utf-8 -*-
"""回归:每个导航按钮都必须在 _goto 的页面表里登记。

实测踩过:dashboard 加进顶栏导航胶囊(`_nav_defs`)和 `_PAGE_KINDS`,唯独漏了
`_goto` 里那张 key → 页面实例的映射表。结果 `_goto("dashboard")` 取到 None,
函数第二行就 `return` —— **按钮能点、点了什么都不发生,而且不报任何错**。
比崩溃难查得多,因为它看起来完全像"点了没反应",没有任何堆栈可循。

这类 bug 的形态是「加了一个新页面,改了 4 个地方忘了第 5 个」,所以测试直接
把所有登记处横向比一遍,新增导航项时哪张表没跟上会立刻失败。
"""
from __future__ import annotations

import re

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _nav_keys(source: str) -> list[str]:
    """从 _build 的 _nav_defs 字面量里解析出所有导航键。"""
    m = re.search(r"_nav_defs\s*=\s*\[(.*?)\]", source, re.S)
    assert m, "找不到 _nav_defs"
    return re.findall(r'\(\s*"(\w+)"\s*,', m.group(1))


def test_every_nav_key_registered_in_goto(qapp):
    from app.ui import main_window as mw

    src = mw.__file__
    with open(src, encoding="utf-8") as f:
        source = f.read()
    goto_src = source[source.index("    def _goto(self, key: str):"):]
    goto_src = goto_src[:goto_src.index("\n    def ", 10)]
    # 值可能是 self.xxx 也可能是 getattr(self, "xxx", None),两种都算登记
    registered = set(re.findall(r'"(\w+)":\s*(?:self\.|getattr\(\s*self)', goto_src))

    missing = [k for k in _nav_keys(source) if k not in registered]
    assert not missing, (
        f"导航键 {missing} 没在 _goto 的页面表里登记 —— 点按钮会静默无反应"
        f"(page is None 直接 return)。请补进 _goto 的映射表。")


def test_every_nav_key_registered_in_retranslate(qapp):
    """retranslate 也要登记,否则切语言后按钮的高亮态对不上当前页。"""
    from app.ui import main_window as mw

    with open(mw.__file__, encoding="utf-8") as f:
        source = f.read()
    body = source[source.index("    def retranslate(self):"):]
    body = body[:body.index("\n    def ", 10)]
    registered = set(re.findall(r'"(\w+)":\s*(?:self\.|getattr)', body))

    missing = [k for k in _nav_keys(source) if k not in registered]
    assert not missing, f"导航键 {missing} 没在 retranslate 的页面表里登记(切语言后高亮会丢)"


def test_nav_keys_have_a_page_in_the_stack(qapp):
    """_PAGE_KINDS 的下标必须与页面栈的 addWidget 顺序一一对应。"""
    from app.ui.main_window import MainWindow

    w = MainWindow()
    assert w.stack.count() == len(MainWindow._PAGE_KINDS), (
        f"页面栈有 {w.stack.count()} 页,_PAGE_KINDS 只有 "
        f"{len(MainWindow._PAGE_KINDS)} 项 —— 下标对不上,切语言会重建错页面")
    assert type(w.stack.widget(0)).__name__ == "DashboardWidget", (
        "第 0 页必须是仪表盘(_PAGE_KINDS 首位也要是 dashboard,漏了全表右移一位)")


def test_clicking_every_nav_button_actually_navigates(qapp):
    """端到端:从别的页点每个导航按钮,必须真的切过去。"""
    from app.ui.main_window import MainWindow

    w = MainWindow()
    expect = {
        "dashboard": "DashboardWidget",
        "projects": "ProjectsPage",
        "chatedit": "ChatEditDrawer",
    }
    for key, want in expect.items():
        for start in ("projects", "chatedit", "dashboard"):
            w._goto(start)
            w.nav_btns[key].click()
            got = type(w.stack.currentWidget()).__name__
            assert got == want, f"从 {start} 点「{key}」没跳过去(仍是 {got},期望 {want})"
            checked = [k for k, b in w.nav_btns.items() if b.isChecked()]
            assert checked == [key], f"点完「{key}」高亮的却是 {checked}"
