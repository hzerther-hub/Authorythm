# -*- coding: utf-8 -*-
"""项目设置里的「项目说明」入口 → 回填「简介 / 创意描述 / 题材」。

用户诉求(2026-10-21):新建项目时那个「项目说明」弹窗,产出的**简介**和
**创意描述**就是项目设置里那两块红框。落库链路本来是通的,但项目设置里
**没有入口** —— 只有「AI 起草简介/题材」(它不产创意描述),导致项目建好之后
想再调简介/创意描述就只能回新建流程重来。

本测试守住:
1. 项目设置里有「项目说明」按钮;
2. 弹窗结果**真的回填到那两个框**(简介 meta["intro"] / 创意描述
   dramas.creative_description),题材也一并;
3. 创意描述被锁(已按旧创意生成过内容)时**不硬塞**;
4. 想法框预填带上现有名称/简介/创意,让 AI 在既有内容上改写;
5. 新增的 4 个 i18n 键 16 语言齐全。

测试绝不碰真实库。
"""
from __future__ import annotations

import json
import os

import pytest


# ── 假库 ───────────────────────────────────────────────────
class _FakeDB:
    """ProjectSettingsDialog 用到的 db 接口最小替身。"""

    def __init__(self, drama=None, presets=(), generated=0):
        self.drama = drama or {}
        self.presets = list(presets)
        self.generated = generated
        self.executed: list[tuple[str, tuple]] = []

    def q(self, sql, args=()):
        if "style_presets" in sql:
            if "style_type='novel'" in sql:
                return [r for r in self.presets if r.get("style_type") == "novel"]
            if "style_type='comic'" in sql:
                return [r for r in self.presets if r.get("style_type") == "comic"]
            if "style_type='visual'" in sql:
                return [{"name": "3D 漫剧", "value": "3d"}]
            return list(self.presets)
        return []

    def q1(self, sql, args=()):
        if "FROM dramas" in sql:
            return self.drama
        if "FROM episodes" in sql:
            return {"c": self.generated}
        if "comic_panels" in sql:
            return {"c": 0}
        return None

    def ex(self, sql, args=()):
        self.executed.append((sql, args))
        return 1

    # ── 预设显示名 / 下拉选项(db.style_display_name / db.style_options)──
    # 设置页的漫画画风、写作风格下拉现在走 db.style_options(内置项的停用态、
    # 改分类都要生效),视觉风格走 db.style_display_name(内置项用本地化名)。
    # 假库必须跟上,否则这里直接 AttributeError。
    def style_display_name(self, value, name):
        return name or ""

    def style_options(self, style_type):
        rows = [r for r in self.presets if r.get("style_type") == style_type]
        return [(r["name"], r.get("prompt", "") or "") for r in rows]

    def touch(self, *a, **k):
        pass

    def now(self):
        return "2026-10-21T00:00:00Z"

    def jload(self, s, default=None):
        try:
            return json.loads(s) if s else (default or {})
        except Exception:  # noqa: BLE001
            return default or {}


def _drama(**kw):
    d = {
        "id": 79, "title": "旧项目名", "style": "3d", "aspect_ratio": "16:9",
        "work_type": "drama", "novel_style": "", "comic_style": "",
        "ethnicity": "auto", "creative_description": "旧创意描述", "skip_creative": 0,
        "total_episodes": 1, "language": "auto", "metadata": "{}",
        "novel_meta": None, "novel_contract": None,
    }
    d.update(kw)
    return d


def _presets():
    return [
        {"name": "爽感快节奏", "value": "v_novel", "prompt": "novel prompt",
         "style_type": "novel", "is_active": 1, "work_type": "all"},
        {"name": "日系漫画", "value": "v_comic", "prompt": "comic prompt",
         "style_type": "comic", "is_active": 1, "work_type": "all"},
    ]


@pytest.fixture()
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ── 假的项目说明弹窗 ───────────────────────────────────────
class _FakeConceptDialog:
    """替换 ProjectConceptDialog:exec 直接返回 Accepted。"""
    Accepted = 1          # == QDialog.Accepted
    REJECTED = 0
    last: dict = {}

    def __init__(self, parent=None, **kw):
        self._kw = kw
        _FakeConceptDialog.last = kw

    def exec(self):
        return _FakeConceptDialog.Accepted

    def result_data(self):
        return {
            "title": "新项目名",
            "description": "新简介内容",
            "creative_description": "新创意描述内容",
            "genre": "玄幻",
        }


def _make_settings(monkeypatch, drama=None, generated=0):
    from app.ui import asset_dialogs as AD
    fake_db = _FakeDB(drama or _drama(), _presets(), generated=generated)
    monkeypatch.setattr(AD, "db", fake_db)
    # novel 模块自己也持有 db 句柄(读 novel_meta 拿叙事人称),一并打桩,
    # 否则初始化会真读用户库;set_novel_pov 会**写**库,必须挡掉。
    from app.pipeline import novel as NV
    monkeypatch.setattr(NV, "db", fake_db)
    monkeypatch.setattr(NV, "set_novel_pov", lambda *a, **k: None)
    dlg = AD.ProjectSettingsDialog(None, 79)
    return dlg, fake_db


# ── 1. 入口存在 ────────────────────────────────────────────
def test_settings_has_concept_button(qt_app, monkeypatch):
    """项目设置里必须有「项目说明」按钮 —— 否则项目建好后无从再调。"""
    dlg, _ = _make_settings(monkeypatch)
    try:
        assert dlg.concept_btn is not None
        assert dlg.concept_btn.text().strip()
        assert dlg.concept_btn.toolTip()
    finally:
        dlg.deleteLater()


# ── 2. 回填两个红框 ────────────────────────────────────────
def test_open_concept_fills_intro_creative_and_genre(qt_app, monkeypatch):
    """「项目说明」的结果要回填到简介 / 创意描述 / 题材三个框。"""
    from app.ui import project_concept_dialog as PCD
    monkeypatch.setattr(PCD, "ProjectConceptDialog", _FakeConceptDialog)
    dlg, _ = _make_settings(monkeypatch)
    try:
        dlg._open_concept()
        assert dlg.intro.text() == "新简介内容"          # 红框 1:简介
        assert dlg.creative.toPlainText() == "新创意描述内容"  # 红框 2:创意描述
        assert dlg._genre_value() == "玄幻"
        assert dlg.title.text() == "新项目名"
    finally:
        dlg.deleteLater()


# ── 3. 保存后真的落库 ──────────────────────────────────────
def test_save_persists_intro_and_creative(qt_app, monkeypatch):
    """回填后点保存:简介进 metadata,创意描述进 dramas 表的独立列。"""
    from app.ui import project_concept_dialog as PCD
    monkeypatch.setattr(PCD, "ProjectConceptDialog", _FakeConceptDialog)
    dlg, fake_db = _make_settings(monkeypatch)
    try:
        dlg._open_concept()
        dlg._save()
        assert fake_db.executed, "保存时一条 UPDATE 都没有"
        sql, args = fake_db.executed[-1]
        assert "creative_description=?" in sql
        assert "新创意描述内容" in args
        # UPDATE 参数顺序:title, aspect, style, ethnicity, metadata, creative...
        meta = json.loads(args[4])
        assert meta["intro"] == "新简介内容"
        assert meta["genre"] == "玄幻"
    finally:
        dlg.deleteLater()


# ── 4. 创意描述被锁时不硬塞 ────────────────────────────────
def test_creative_locked_is_not_overwritten(qt_app, monkeypatch):
    """勾了「不需要创意描述」→ 创意描述是锁的,别偷偷改用户的设定。"""
    from app.ui import project_concept_dialog as PCD
    monkeypatch.setattr(PCD, "ProjectConceptDialog", _FakeConceptDialog)
    dlg, _ = _make_settings(monkeypatch, drama=_drama(skip_creative=1))
    try:
        assert dlg.creative.isEnabled() is False
        dlg._open_concept()
        assert dlg.creative.toPlainText() == "旧创意描述"
    finally:
        dlg.deleteLater()


# ── 4b. 锁定条件:空创意描述不锁 ───────────────────────────
def test_empty_creative_stays_editable_after_content(qt_app, monkeypatch):
    """创意描述本来是空的 + 已产出内容 → **不锁**。

    锁一个空值没有任何东西可保护(「保持已生成章节与创意一致」对空值不成立),
    却会让老项目永远补不上一份创意描述(实测 3 个项目卡在这)。
    """
    dlg, _ = _make_settings(monkeypatch,
                            drama=_drama(creative_description=""), generated=1)
    try:
        assert dlg._generated is True            # 内容确实已产出
        assert dlg._creative_locked is False      # 但空值不锁
        assert dlg.creative.isEnabled() is True
    finally:
        dlg.deleteLater()


def test_existing_creative_stays_locked_after_content(qt_app, monkeypatch):
    """已有创意描述 + 已产出内容 → 锁(保护已生成章节与这份创意一致)。"""
    dlg, _ = _make_settings(monkeypatch,
                            drama=_drama(creative_description="旧创意描述"), generated=1)
    try:
        assert dlg._creative_locked is True
        assert dlg.creative.isEnabled() is False
    finally:
        dlg.deleteLater()


def test_empty_creative_can_be_filled_by_concept(qt_app, monkeypatch):
    """老项目(有内容、创意描述为空)用「项目说明」补写 → 真能填进去。"""
    from app.ui import project_concept_dialog as PCD
    monkeypatch.setattr(PCD, "ProjectConceptDialog", _FakeConceptDialog)
    dlg, _ = _make_settings(monkeypatch,
                            drama=_drama(creative_description=""), generated=1)
    try:
        dlg._open_concept()
        assert dlg.creative.toPlainText() == "新创意描述内容"
    finally:
        dlg.deleteLater()


# ── 5. 想法预填带上现有上下文 ─────────────────────────────
def test_open_concept_prefills_current_context(qt_app, monkeypatch):
    """想法框要带上现有名称/简介/创意,让 AI 在既有内容上改写。"""
    from app.ui import project_concept_dialog as PCD
    monkeypatch.setattr(PCD, "ProjectConceptDialog", _FakeConceptDialog)
    dlg, _ = _make_settings(monkeypatch)
    try:
        dlg.intro.setText("现有简介文本")
        dlg._open_concept()
        idea = _FakeConceptDialog.last.get("idea", "")
        assert "现有简介文本" in idea
        assert "旧项目名" in idea
        assert "旧创意描述" in idea
    finally:
        dlg.deleteLater()


# ── 6. 弹窗支持 idea 预填 ─────────────────────────────────
def test_concept_dialog_accepts_idea(qt_app):
    """弹窗的 idea 参数优先于 title —— 项目设置传的是拼好的上下文。"""
    from app.ui.project_concept_dialog import ProjectConceptDialog
    dlg = ProjectConceptDialog(work_type="drama", title="名字", idea="完整上下文")
    try:
        assert dlg.idea_edit.toPlainText() == "完整上下文"
    finally:
        dlg.deleteLater()


# ── 7. i18n:新增 4 键 16 语言齐全 ─────────────────────────
def test_new_settings_i18n_keys_in_16_langs():
    """新增的 4 个键,16 种语言都要能取到值(取不到就显示英文裸键)。"""
    from app.core import i18n, ui_strings
    keys = ["concept_btn_tip_settings", "concept_filled_settings",
            "concept_creative_locked", "concept_idea_current"]
    langs = ["zh", "zh-Hant", "en", "ja", "ko", "ar", "hi", "id", "th", "tr",
             "vi", "fr", "de", "es", "pt", "it"]
    for k in keys:
        assert len(ui_strings.S.get(k, [])) == 15, f"{k} 补充词典不是 15 语言"
    try:
        for lang in langs:
            i18n.set_language(lang)
            for k in keys:
                v = i18n.tr(k)
                assert v and str(v).strip(), f"{lang}/{k} 取不到值"
                assert v != k, f"{lang}/{k} 回退成了 key 本身"
    finally:
        i18n.set_language("zh")   # 必须还原,否则污染后续用例
