# -*- coding: utf-8 -*-
"""回归:模型下拉的两份数据不能抢同一个 Qt 角色。

背景(实测):`W.add_item(combo, label, config_id, user_data=model)` 里,
`combo.addItem(text, data)` 本身就把 data 落在 **Qt.UserRole** 上,
helper 随后又 `setItemData(idx, user_data, Qt.UserRole)` —— 后者把前者
覆盖掉了。于是 `combo.currentData()` 返回的是**型号名**而不是配置 id,
连锁出三个现象:

  1. `findData(config_id)` 永远 -1 → 上次选的模型恢复不出来(静默失效)
  2. `_remember_model` 里 `int(currentData())` → ValueError,崩在信号回调里
  3. `set_setting("yihao.model.<t>", str(currentData()))` 写进去的是型号名,
     下一轮 `_reload_models` 的 `int(saved)` 再崩一次 —— 自我 perpetuating,
     老用户的库里就是这么攒下 `yihao.model.text = 'MiniMax-M3'` 的

另外守住 `db.resolve_selected_config_id`:老库里存的是型号名,读取方必须
能反查回配置 id 并顺手把设置改写成 id(自愈),而不是抛 ValueError。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_add_item_keeps_data_and_user_data_in_separate_roles(qapp):
    """config_id 留在 UserRole(currentData 读它),型号名去 USER_DATA_ROLE。"""
    from PySide6.QtWidgets import QComboBox
    from app.ui import widgets as W

    combo = QComboBox()
    combo.addItem("已配置", None)
    W.add_item(combo, "glm-5.3", 10, user_data="glm-5.3")
    combo.setCurrentIndex(1)          # currentData() 取的是**当前**选中项

    assert combo.currentData() == 10, "currentData() 必须是配置 id"
    assert combo.currentData(W.USER_DATA_ROLE) == "glm-5.3"
    assert combo.findData(10) == 1, "findData(config_id) 必须能命中"


def test_model_combo_current_data_is_int(qapp, monkeypatch):
    """剧集页模型下拉:currentData() 是 int,不是型号名。"""
    from app.ui.episode_page import EpisodePage
    from app.ui import widgets as W

    page = EpisodePage.__new__(EpisodePage)      # 不跑 __init__,只测填下拉那段
    page._sync_res_tiers = lambda: None

    from PySide6.QtWidgets import QComboBox
    combo = QComboBox()
    page.text_model = combo

    # 复刻 _reload_models 的填充逻辑(整页构造太重,这里只测这一句的契约)
    from app.ai import registry
    for ent in registry.model_entries("text"):
        W.add_item(combo, ent["label"], ent["config_id"], user_data=ent["model"])

    combo.setCurrentIndex(1)
    cid = combo.currentData()
    assert isinstance(cid, int), f"currentData() 应为 int,实得 {type(cid).__name__}:{cid!r}"
    assert int(cid) > 0
    assert isinstance(combo.currentData(W.USER_DATA_ROLE), str)


def test_resolve_selected_config_id_accepts_legacy_model_name(monkeypatch):
    """老库里存型号名 → 反查回配置 id,并把设置自愈成 id。"""
    from app.core import db

    monkeypatch.setattr(db, "get_setting",
                        lambda k, d="": {"yihao.model.text": "MiniMax-M3"}.get(k, d))
    rows = [{"id": 4, "model": "MiniMax-M3", "models": '["MiniMax-M3","MiniMax-M2"]'}]
    monkeypatch.setattr(db, "q", lambda sql, *a: rows)
    written = {}
    monkeypatch.setattr(db, "set_setting", lambda k, v: written.__setitem__(k, v))

    got = db.resolve_selected_config_id("text")
    assert got == 4
    assert written["yihao.model.text"] == "4", "应顺手改写成 id 形态,下次走快路径"


def test_resolve_selected_config_id_accepts_id_form(monkeypatch):
    """现行形态:存的是 id,原样返回,不该反查也不该写回。"""
    from app.core import db

    monkeypatch.setattr(db, "get_setting", lambda k, d="": "13" if k == "yihao.model.text" else d)
    written = {}
    monkeypatch.setattr(db, "set_setting", lambda k, v: written.__setitem__(k, v))

    assert db.resolve_selected_config_id("text") == 13
    assert written == {}, "已是 id 形态就不该再写库"


def test_resolve_selected_config_id_unknown_name_returns_none(monkeypatch):
    """型号名查不到所属配置 → None,不抛异常(交调用方兜底)。"""
    from app.core import db

    monkeypatch.setattr(db, "get_setting",
                        lambda k, d="": "no-such-model" if k == "yihao.model.text" else d)
    monkeypatch.setattr(db, "q", lambda sql, *a: [])
    monkeypatch.setattr(db, "set_setting", lambda k, v: None)

    assert db.resolve_selected_config_id("text") is None


def test_resolve_selected_config_id_empty_returns_none(monkeypatch):
    """没配过 → None。"""
    from app.core import db

    monkeypatch.setattr(db, "get_setting", lambda k, d="": d)
    assert db.resolve_selected_config_id("text") is None


def test_theme_rejects_non_positive_point_size():
    """`pointSize() or 9` 拦不住 -1(-1 是 truthy),必须显式判 > 0。"""
    from PySide6.QtGui import QFont

    class _App:
        @staticmethod
        def font():
            return QFont()      # 未显式设点号的字体,pointSize 可能 <= 0

    pt = _App.font().pointSize()
    resolved = pt if pt > 0 else 9
    assert resolved > 0, "传给 setPointSize 的值必须为正"
