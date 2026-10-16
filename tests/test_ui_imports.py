# -*- coding: utf-8 -*-
"""回归:app/ui 每个模块必须可导入,改图弹窗必须能构造出来。

实测踩过:整包合入的「十一参精调」代码里,`_AdjustApplyWorker` 用了没导入的
`Signal`,`__init__` 里引用了没创建的 `apply_adj` 按钮 —— `image_edit_dialog`
**import 就炸**。而所有改图入口(角色卡「改图」、聊天改图缩略图、批量区改图)
都是**点击时才懒导入**这个模块,测试套件从不点它,于是 224 个测试全绿、
用户那边「改图弹窗全部弹不出来」。`adjust_worker.BusyOverlay(QWidget)` 同款。

教训:懒导入让「import 就炸」的 bug 对测试完全隐身。这里把整个 app/ui 包
全部导入一遍,再把改图弹窗真实构造一次。
"""
from __future__ import annotations

import importlib
import pkgutil

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_every_ui_module_imports(qapp):
    import app.ui as pkg

    bad = []
    for m in pkgutil.iter_modules(pkg.__path__):
        try:
            importlib.import_module(f"app.ui.{m.name}")
        except Exception as exc:  # noqa: BLE001
            bad.append(f"app.ui.{m.name}: {type(exc).__name__}: {exc}")
    assert not bad, "以下 UI 模块 import 就炸(懒它们的入口一点就崩):\n" + "\n".join(bad)


def test_image_edit_dialog_constructs(qapp, tmp_path):
    """改图弹窗必须能构造 —— 它是角色卡「改图」/聊天缩略图/批量区共用的
    唯一编辑器,炸了 = 所有编辑入口静默失效。"""
    from PIL import Image
    from app.ui.image_edit_dialog import ImageEditDialog

    img = tmp_path / "t.png"
    Image.new("RGB", (64, 48), (90, 140, 200)).save(img)
    dlg = ImageEditDialog(None, str(img), target={"type": "session"}, title="冒烟")
    from PySide6.QtWidgets import QPushButton
    texts = [x.text() for x in dlg.findChildren(QPushButton)]
    assert any("应用调整" in t for t in texts), (
        "「应用调整」按钮缺失 —— 精调滑杆算完没有落盘入口")
    dlg.deleteLater()
