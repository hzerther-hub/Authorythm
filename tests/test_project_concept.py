# -*- coding: utf-8 -*-
"""「项目说明」+ 项目设定预设下拉的回归测试。

用户要求(2026-10-21):
1. 新建项目里加「项目说明」按钮 —— 写一句想法,AI 生成 项目名称/简介/创意描述/题材;
2. 项目设定里加「题材」(对齐 Web 版 xiaoshuo);
3. **漫画风格 / 题材 / 写作风格 三个下拉都不要出现「自定义」** ——
   下拉里摆一个没有地方填的条目只会误导(Web 版的漫画画风就是这个坑:
   选中「自定义」后值被清空、computed 又把空值映射回第一项,输入框永远不出现)。

测试绝不碰真实库。
"""
from __future__ import annotations

import pathlib

import pytest

from app.pipeline import project_concept as pc


# ── 假库 ───────────────────────────────────────────────────
class _FakeDB:
    """dialog 初始化用到的 db 接口最小替身。"""

    def __init__(self, drama=None, presets=()):
        self.drama = drama or {}
        self.presets = list(presets)
        self.executed: list[tuple[str, tuple]] = []

    def q(self, sql, args=()):
        if "style_presets" in sql:
            # 真库返回的是 sqlite3.Row(可 r["name"] 取值),这里给 dict 等价物
            return list(self.presets)
        return []

    def q1(self, sql, args=()):
        if "FROM dramas" in sql:
            return self.drama
        return None

    def ex(self, sql, args=()):
        self.executed.append((sql, args))
        return 1

    def touch(self, *a, **k):
        pass

    def now(self):
        return "2026-10-21T00:00:00Z"

    def jload(self, s, default=None):
        import json
        try:
            return json.loads(s) if s else (default or {})
        except Exception:  # noqa: BLE001
            return default or {}


def _drama(**kw):
    d = {
        "id": 79, "title": "测试项目", "style": "3d", "aspect_ratio": "16:9",
        "work_type": "drama", "novel_style": "", "comic_style": "",
        "ethnicity": "auto", "creative_description": "", "skip_creative": 0,
        "total_episodes": 1, "language": "auto", "metadata": "{}",
    }
    d.update(kw)
    return d


@pytest.fixture()
def qt_app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ── pipeline:生成契约 ──────────────────────────────────────
def test_playbook_covers_four_work_types():
    """四种创作目标各有一套体裁说明;同款复刻刻意不在表里。"""
    assert set(pc.CONCEPT_PLAYBOOK) == {"drama", "novel", "comic", "promotion"}
    assert "video_clone" not in pc.CONCEPT_PLAYBOOK
    for wt, pb in pc.CONCEPT_PLAYBOOK.items():
        assert pb["kind"] and pb["title_hint"] and pb["desc_hint"], f"{wt} 的体裁说明不全"


def test_genre_presets_not_empty():
    """题材预设要够用(12 大类)。"""
    assert len(pc.GENRE_PRESETS) >= 10
    assert len(set(pc.GENRE_PRESETS)) == len(pc.GENRE_PRESETS)


def test_generate_rejects_video_clone():
    """同款复刻不给 AI 项目说明 —— 题材来自参考视频,凭空生成会打架。"""
    with pytest.raises(RuntimeError):
        pc.generate_project_concept(work_type="video_clone", idea="随便写点什么")


def test_generate_rejects_empty_idea():
    """没写想法就直接拒绝,别白烧一次 token。"""
    with pytest.raises(RuntimeError):
        pc.generate_project_concept(work_type="drama", idea="   ")


def test_generate_returns_four_fields(monkeypatch):
    """正常路径返回 名称/简介/创意描述/题材 四件套。"""
    seen = {}

    def fake_ask(prompt, *, config_id, lang):
        seen["prompt"] = prompt
        return {
            "title": "时光邮局", "description": "都市情感短剧",
            "creative_description": "女主在旧邮局收到十年前的信", "genre": "都市言情",
        }

    monkeypatch.setattr(pc, "_ask_concept_json", fake_ask)
    out = pc.generate_project_concept(work_type="drama", idea="一个旧邮局的故事")

    assert out["title"] == "时光邮局"
    assert out["description"] == "都市情感短剧"
    assert out["creative_description"].startswith("女主")
    assert out["genre"] == "都市言情"
    assert "一个旧邮局的故事" in seen["prompt"]
    assert "短剧" in seen["prompt"]           # 体裁说明进了提示词


def test_generate_truncates_long_fields(monkeypatch):
    """字段超长要截断 —— 标题/简介/创意描述都有上限。"""
    def fake_ask(prompt, *, config_id, lang):
        return {"title": "标" * 200, "description": "简" * 900,
                "creative_description": "创" * 5000, "genre": "题" * 90}

    monkeypatch.setattr(pc, "_ask_concept_json", fake_ask)
    out = pc.generate_project_concept(work_type="drama", idea="x")
    assert len(out["title"]) <= 60
    assert len(out["description"]) <= 400
    assert len(out["creative_description"]) <= 2000
    assert len(out["genre"]) <= 30


def test_extract_fields_loose_salvages_broken_json():
    """JSON 彻底解析不出来时,逐字段正则兜底能救回残缺结果。"""
    raw = 'title: "时光邮局"\ndescription: "一个关于旧邮局的故事"\n'
    out = pc._extract_fields_loose(raw, pc.CONCEPT_FIELDS)
    assert out["title"] == "时光邮局"
    assert out["description"] == "一个关于旧邮局的故事"


def test_ask_concept_json_retries_on_missing_field(monkeypatch):
    """字段不齐要重试一次(带更严格的格式要求),不是直接放弃。"""
    calls = []

    def fake_run_json(agent_type, prompt, **kw):
        calls.append(prompt)
        if len(calls) == 1:
            return {"title": "只有标题"}
        return {"title": "T", "description": "D", "creative_description": "C", "genre": "G"}

    monkeypatch.setattr(pc.runner, "run_agent_json", fake_run_json)
    out = pc._ask_concept_json("原始提示", config_id=None, lang=None)
    assert out["title"] == "T"
    assert len(calls) == 2
    assert "格式要求" in calls[1]           # 第二次带上了严格格式要求


def test_ask_concept_json_raises_when_always_missing(monkeypatch):
    """两次都缺字段 → 抛错,别把残缺结果当成功返回。"""
    monkeypatch.setattr(pc.runner, "run_agent_json",
                        lambda *a, **k: {"title": "只有标题"})
    # 最后一道防线会再打一次原始输出,这里也打成缺字段,别真去调模型
    monkeypatch.setattr(pc.runner, "run_agent", lambda *a, **k: '{"title": "只有标题"}')
    with pytest.raises(RuntimeError):
        pc._ask_concept_json("提示", config_id=None, lang=None)


# ── UI:新建项目里的「项目说明」按钮 ─────────────────────────
def test_new_project_dialog_has_concept_button(qt_app, monkeypatch):
    """新建项目对话框里必须有「项目说明」按钮(挂在项目名称右侧)。"""
    from app.ui import new_project_dialog as NPD
    monkeypatch.setattr(NPD, "db", _FakeDB(presets=[
        {"name": "3D 漫剧", "value": "3d", "work_type": "drama,novel,comic"}]))
    dlg = NPD.NewProjectDialog()
    try:
        assert dlg.concept_btn is not None
        assert dlg.concept_btn.text()
        # 名称为空 → 按钮置灰(名称是想法框的种子)
        assert dlg.concept_btn.isEnabled() is False
        dlg.name_edit.setText("我的短剧")
        assert dlg.concept_btn.isEnabled() is True
    finally:
        dlg.deleteLater()


def test_concept_button_disabled_for_video_clone(qt_app, monkeypatch):
    """同款复刻不给「项目说明」入口。"""
    from app.ui import new_project_dialog as NPD
    monkeypatch.setattr(NPD, "db", _FakeDB(presets=[
        {"name": "3D 漫剧", "value": "3d", "work_type": "drama,novel,comic"}]))
    dlg = NPD.NewProjectDialog()
    try:
        dlg.name_edit.setText("复刻项目")
        dlg._radios["video_clone"].setChecked(True)
        assert dlg.concept_btn.isEnabled() is False
    finally:
        dlg.deleteLater()


def test_new_project_result_data_carries_concept(qt_app, monkeypatch):
    """项目说明生成的内容要随表单一起提交(简介/题材进 metadata,创意描述单独列)。"""
    import json
    from app.ui import new_project_dialog as NPD
    monkeypatch.setattr(NPD, "db", _FakeDB(presets=[
        {"name": "3D 漫剧", "value": "3d", "work_type": "drama,novel,comic"}]))
    dlg = NPD.NewProjectDialog()
    try:
        dlg.name_edit.setText("时光邮局")
        dlg._concept = {"description": "都市情感短剧",
                        "creative_description": "女主收到十年前的信",
                        "genre": "都市言情"}
        data = dlg.result_data()
        meta = json.loads(data["metadata"])
        assert meta["intro"] == "都市情感短剧"
        assert meta["genre"] == "都市言情"
        assert data["creative_description"] == "女主收到十年前的信"
        assert data["title"] == "时光邮局"
    finally:
        dlg.deleteLater()


def test_concept_dialog_result_data_shape(qt_app):
    """项目说明弹窗的返回结构固定为 名称/简介/创意描述/题材。"""
    from app.ui.project_concept_dialog import ProjectConceptDialog
    dlg = ProjectConceptDialog(work_type="drama", title="想法")
    try:
        assert dlg.idea_edit.toPlainText() == "想法"     # 想法框预填项目名
        dlg.res_name.setText("时光邮局")
        dlg.res_desc.setPlainText("简介")
        dlg.res_creative.setPlainText("创意")
        dlg.res_genre.setText("都市言情")
        data = dlg.result_data()
        assert set(data) == {"title", "description", "creative_description", "genre"}
        assert data["title"] == "时光邮局"
    finally:
        dlg.deleteLater()


# ── UI:项目设定里的三个预设下拉(不许有「自定义」)──────────
def _settings_dialog(monkeypatch, drama=None):
    from app.ui import asset_dialogs as AD
    fake = _FakeDB(drama=drama or _drama(),
                   presets=[{"name": "3D 漫剧", "value": "3d"},
                            {"name": "日漫赛璐璐", "value": "anime"}])
    monkeypatch.setattr(AD, "db", fake)
    monkeypatch.setattr(AD, "_has_generated_content", lambda *a, **k: False)
    dlg = AD.ProjectSettingsDialog(None, 79)
    return dlg, fake


def test_settings_genre_is_preset_dropdown(qt_app, monkeypatch):
    """题材是预设下拉,没有「自定义」条目。"""
    dlg, _ = _settings_dialog(monkeypatch)
    try:
        items = [dlg.genre_combo.itemText(i) for i in range(dlg.genre_combo.count())]
        assert not any("自定义" in t for t in items), f"题材下拉不该有自定义:{items}"
        assert dlg.genre_combo.count() >= len(pc.GENRE_PRESETS)
    finally:
        dlg.deleteLater()


def test_settings_comic_style_has_no_custom(qt_app, monkeypatch):
    """漫画画风没有「自定义」条目(且不再有自定义编辑框)。"""
    dlg, _ = _settings_dialog(monkeypatch)
    try:
        items = [dlg.comic_style.itemText(i) for i in range(dlg.comic_style.count())]
        assert not any("自定义" in t for t in items), f"漫画画风下拉不该有自定义:{items}"
        assert not hasattr(dlg, "comic_style_edit")
    finally:
        dlg.deleteLater()


def test_settings_novel_style_has_no_custom(qt_app, monkeypatch):
    """写作风格没有「自定义」条目(且不再有自定义编辑框)。"""
    dlg, _ = _settings_dialog(monkeypatch)
    try:
        items = [dlg.novel_style.itemText(i) for i in range(dlg.novel_style.count())]
        assert not any("自定义" in t for t in items), f"写作风格下拉不该有自定义:{items}"
        assert not hasattr(dlg, "novel_style_edit")
    finally:
        dlg.deleteLater()


def test_settings_keeps_legacy_custom_value(qt_app, monkeypatch):
    """存量项目里手写过的值(非预设)不能被悄悄清空 —— 作为额外条目保留。"""
    dlg, _ = _settings_dialog(monkeypatch, _drama(
        metadata='{"genre": "我自编的题材"}', comic_style="my-own-style",
        novel_style="我自编的文风"))
    try:
        assert dlg.genre_combo.currentData() == "我自编的题材"
        assert dlg.comic_style.currentData() == "my-own-style"
        assert dlg.novel_style.currentData() == "我自编的文风"
    finally:
        dlg.deleteLater()


def test_settings_save_writes_genre_from_dropdown(qt_app, monkeypatch):
    """保存时题材取下拉选中项。"""
    dlg, fake = _settings_dialog(monkeypatch)
    try:
        dlg.genre_combo.setCurrentIndex(dlg.genre_combo.findData("悬疑推理"))
        dlg._save()
        import json
        ups = [s for s, _ in fake.executed if "UPDATE dramas SET" in s]
        assert ups, "保存没有执行 UPDATE"
        args = dict(fake.executed)[ups[0]]
        meta = json.loads(args[4])
        assert meta["genre"] == "悬疑推理"
    finally:
        dlg.deleteLater()


# ── i18n ───────────────────────────────────────────────────
def test_new_i18n_keys_have_15_languages():
    """新增文案要 15 语言齐全(补充词典以英文键为 key)。"""
    from app.core.ui_strings import S, LANGS
    from app.core import i18n
    keys = [
        "concept_btn", "concept_btn_tip", "concept_dialog_title", "concept_dialog_desc",
        "concept_idea", "concept_idea_ph", "concept_idea_hint", "concept_add_image",
        "concept_ref_limit", "concept_ref_images", "concept_ref_note_ph", "concept_ref_note_hint",
        "concept_generate", "concept_regenerate", "concept_apply", "concept_generating",
        "concept_need_idea", "concept_need_title", "concept_done", "concept_not_supported",
        "concept_result_title", "concept_result_name_ph", "concept_result_desc",
        "concept_result_creative", "concept_result_genre", "concept_result_genre_ph",
        "genre_custom", "genre_custom_ph", "genre_hint", "comic_style_hint", "novel_style_hint",
    ]
    for k in keys:
        assert k in i18n.Z, f"{k} 没进主词典 Z"
        assert k in S, f"{k} 没进补充词典"
        row = S[k]
        assert len(row) == len(LANGS) == 15, f"{k} 的译文数应为 15,实际 {len(row)}"
        for i, lang in enumerate(LANGS):
            assert row[i].strip(), f"{k} 的 {lang} 译文是空的"
    assert "{n}" in S["concept_ref_limit"][0]
    assert "{n}" in S["concept_ref_note_ph"][0]


def test_new_i18n_keys_resolve_in_every_language():
    """每个语言下 tr() 都要能解析出译文(不能回落成 key 本身)。

    注意:会把界面语言切来切去,**必须在结束时还原** —— 否则后续用例
    全被带偏(实测 4 个无关用例因此挂掉:标题文案变成了意大利语)。
    """
    from app.core import i18n
    keys = ["concept_btn", "concept_dialog_desc", "genre_hint",
            "comic_style_hint", "novel_style_hint", "concept_result_genre"]
    setter = getattr(i18n, "set_language", None)
    if setter is None:
        pytest.skip("i18n 没有 set_language")
    old = i18n._current
    try:
        for lang in ("zh", "zh-Hant", "en", "ja", "ko", "ar", "hi", "id", "th", "tr", "vi",
                     "fr", "de", "es", "pt", "it"):
            setter(lang)
            for k in keys:
                v = i18n.tr(k)
                assert v and v != k, f"{lang} 下 {k} 没解析出来"
    finally:
        setter(old)


def test_new_i18n_keys_have_traditional_chinese():
    """繁体是第 16 种语言,新键在繁体下必须是真繁体(不是英文、也不是简体)。"""
    from app.core import i18n
    keys = ["concept_btn", "concept_dialog_desc", "genre_hint",
            "comic_style_hint", "novel_style_hint", "concept_result_creative"]
    setter = getattr(i18n, "set_language", None)
    if setter is None:
        pytest.skip("i18n 没有 set_language")
    old = i18n._current
    try:
        setter("zh-Hant")
        trad = {k: i18n.tr(k) for k in keys}
        setter("zh")
        simp = {k: i18n.tr(k) for k in keys}
        setter("en")
        eng = {k: i18n.tr(k) for k in keys}
    finally:
        setter(old)
    for k in keys:
        assert trad[k] != eng[k], f"{k} 的繁体回落成了英文"
        assert trad[k] != simp[k], f"{k} 的繁体回落成了简体"


# ── 源码级守门:别把「自定义」加回来 ───────────────────────
def test_no_custom_option_in_settings_dropdowns():
    """源码级守门:项目设定的三个下拉不许再加「自定义」条目。"""
    src = (pathlib.Path(pc.__file__).parents[1] / "ui" / "asset_dialogs.py").read_text(
        encoding="utf-8")
    for bad in ('addItem(tr("自定义…")', 'addItem(tr("comic_style_custom")',
                'addItem(tr("genre_custom")'):
        assert bad not in src, f"项目设定里又出现了自定义条目:{bad}"
