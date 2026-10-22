# -*- coding: utf-8 -*-
"""风格预设三分类(visual / comic / novel)回归测试。

对应契约「风格预设三分类 —— TypeScript / pydrama 双端统一契约」:

- 全新库初始化后 style_presets = 20 条 visual + 6 条 comic + 6 条 novel;
- 老库升级:存量行 style_type 全是 'visual'(行为不变),新种子只新增不覆盖;
- 种子幂等:重复 init_db 不动用户改过的 prompt;
- 漫画画风 / 写作风格下拉 = 内置常量 + 库内条目,按 prompt 全文去重,
  且按 work_type 过滤(老画风下拉把 promotion 类也列出来的老毛病不能复现);
- 16 种语言下新增文案与内置条目名都不漏中文。
"""
from __future__ import annotations

import re

import pytest

from app.core import db, i18n

# 契约 2.1 / 2.2 的逐字内容(value → name / sort_order / description / prompt)
CONTRACT_COMIC = {
    "manga_jp": ("日漫", 200, "日式少年漫画，干净墨线 + 网点阴影",
                  "Japanese shōnen manga style, clean ink line art, screentone shading, dynamic action lines"),
    "comic_us": ("美漫", 201, "美式超级英雄漫画，粗墨线 + 高饱和",
                 "American superhero comic book style, bold saturated colors, heavy ink outlines, dynamic poses"),
    "comic_watercolor": ("水彩", 202, "柔和水彩插画，传统画材 + 纸纹质感",
                          "soft watercolor illustration style, gentle washes, traditional painting feel, paper texture"),
    "bw_manga": ("黑白", 203, "黑白漫，高对比墨线 + 网点",
                 "black and white manga style, ink line art, crosshatch shading, screentone, no color"),
    "bold_ink": ("粗描", 204, "粗重墨线，暗调 pulp 插画感",
                 "heavy bold ink line style, dark moody, thick strokes, pulp illustration feel"),
    "guofeng25d": ("国风2.5D", 205, "国风 2.5D 半写实动画质感",
                   "Chinese guofeng 2.5D illustration style, semi-realistic donghua-quality character art, elegant flowing line work"),
}
CONTRACT_NOVEL = {
    "shuanggan_kuaijie": ("爽感快节奏", 300, "短句直给、爽点前置、章末小高潮",
                          "短句为主，情绪外露，段落简短，冲突直给，爽点前置，每章末尾必有小高潮"),
    "xi_ganqing": ("细腻情感流", 301, "重视内心与情绪层次，舒缓共情",
                   "重人物内心与情绪层次，描写细腻，节奏舒缓，重氛围与共情"),
    "xuanyi_jinzhang": ("悬疑紧张", 302, "信息差驱动、多伏笔、章末反转",
                        "信息差驱动，多伏笔，短段制造压迫感，章末反转"),
    "gufeng_yazhi": ("古风雅致", 303, "文白相间、用词考究、意境优先",
                     "文白相间，用词考究，意境优先，节奏沉稳"),
    "youmo_qingsong": ("幽默轻松", 304, "吐槽视角、反差与梗密集",
                       "吐槽视角，反差与梗密集，轻松诙谐但不脱离主线"),
    "yinghe_xieshi": ("硬核写实", 305, "细节考据、冷静克制、强逻辑因果",
                     "细节考据，冷静克制但不冷漠——动作与器物描写精确，同时保留人物内心戏与环境氛围，强逻辑因果"),
}

# 拉丁字母语言:界面里出现汉字就是漏译
_LATIN_LANGS = ("en", "fr", "de", "es", "pt", "it", "tr", "vi", "id")
_HAS_CJK = re.compile(r"[一-鿿]")
# 这些内置名在繁体里字形与简体相同(没有对应异体字),出现同样字形是正确的
_ZH_HANT_SAME = {"皮克斯 3D", "日漫", "美漫", "水彩", "黑白", "粗描", "教育卡通"}
# 本轮新增的界面文案(16 语言必须齐全)
_NEW_KEYS = (
    "style_category", "style_type_visual", "style_type_comic", "style_type_novel",
    "style_type_label", "style_toggle", "style_value_label", "style_value_hint",
    "style_value_required", "style_value_dup", "style_builtin_no_delete",
    "style_delete_confirm", "style_new_title", "style_presets_hint",
)


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """按本仓约定隔离:改 config.DB_PATH + 清 thread-local 连接(别用环境变量)。"""
    path = tmp_path / "style_types.sqlite3"
    # 先把文件建出来并落好 WAL:init_db() → get_db() 会执行
    # "PRAGMA journal_mode=WAL",切 WAL 需要对文件取一次独占锁 ——
    # Windows 上刚创建的新文件偶发被占用(杀软扫描等)→ "database is locked"。
    # 这里预先落好 WAL,init_db() 时该 PRAGMA 变成 no-op,不再抢锁。
    import sqlite3
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()
    monkeypatch.setattr(db.config, "DB_PATH", path)
    monkeypatch.setattr(db.config, "DATA_DIR", tmp_path)
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    yield path
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


def _counts() -> dict[str, int]:
    return {r["style_type"]: r["c"] for r in
            db.q("SELECT style_type, COUNT(*) c FROM style_presets GROUP BY style_type")}


def test_fresh_db_seeds_every_builtin_style(tmp_db):
    """每个内置预设都要种进库 —— 数量跟着内置常量走。

    原来写死 20/6/6,新增一个内置画风就得改测试,迟早有人忘(实测:加了
    「黑白漫画」后 6 个用例集体变红)。这里改成跟常量比对,并保留下限,
    既防"被删光",又不因"新增"变红。
    """
    counts = _counts()
    assert counts.get("visual") == len(db.STYLE_PRESETS)
    assert counts.get("comic") == len(db.COMIC_STYLE_PRESETS)
    assert counts.get("novel") == len(db.NOVEL_STYLE_PRESETS)
    assert counts.get("visual", 0) >= 20, "内置视觉风格被删少了"


def test_seed_content_matches_contract_verbatim(tmp_db):
    for value, (name, order, desc, prompt) in CONTRACT_COMIC.items():
        r = db.q1("SELECT * FROM style_presets WHERE value=?", (value,))
        assert r is not None, f"缺漫画画风种子 {value}"
        assert r["name"] == name and r["description"] == desc and r["prompt"] == prompt
        assert r["style_type"] == "comic" and r["work_type"] == "comic"
        assert r["sort_order"] == order
    for value, (name, order, desc, prompt) in CONTRACT_NOVEL.items():
        r = db.q1("SELECT * FROM style_presets WHERE value=?", (value,))
        assert r is not None, f"缺写作风格种子 {value}"
        assert r["name"] == name and r["description"] == desc and r["prompt"] == prompt
        assert r["style_type"] == "novel" and r["work_type"] == "novel"
        assert r["sort_order"] == order


def test_visual_seeds_untouched(tmp_db):
    """视觉风格一条一行不动(名称/prompt/排序都不许被本轮改动)。"""
    assert len(db.STYLE_PRESETS) >= 20, "内置视觉风格被删少了"
    for name, value, order, wt, prompt, _desc in db.STYLE_PRESETS:
        r = db.q1("SELECT * FROM style_presets WHERE value=?", (value,))
        assert r is not None and r["style_type"] == "visual"
        assert r["name"] == name and r["prompt"] == prompt
        assert r["sort_order"] == order and r["work_type"] == wt


def test_seed_is_idempotent_and_does_not_overwrite_user_edit(tmp_db):
    db.ex("UPDATE style_presets SET prompt='用户改过的 prompt' WHERE value='manga_jp'")
    db.ex("UPDATE style_presets SET name='我的日漫' WHERE value='shuanggan_kuaijie'")
    db.init_db()
    db.init_db()
    assert _counts() == {"visual": len(db.STYLE_PRESETS),
                      "comic": len(db.COMIC_STYLE_PRESETS),
                      "novel": len(db.NOVEL_STYLE_PRESETS)}
    assert db.q1("SELECT prompt FROM style_presets WHERE value='manga_jp'")["prompt"] \
        == "用户改过的 prompt"
    assert db.q1("SELECT name FROM style_presets WHERE value='shuanggan_kuaijie'")["name"] \
        == "我的日漫"


def test_legacy_db_upgrade_keeps_old_rows_visual(tmp_db):
    """老库(没有 style_type 列、只有视觉风格)升级:存量行全是 visual,新增 12 条种子。"""
    conn = db.get_db()
    db.ex("DELETE FROM style_presets WHERE style_type IN ('comic','novel')")
    conn.execute("ALTER TABLE style_presets DROP COLUMN style_type")
    conn.commit()
    assert "style_type" not in [r["name"] for r in db.q("PRAGMA table_info(style_presets)")]
    before = {r["value"] for r in db.q("SELECT value FROM style_presets")}
    assert len(before) == len(db.STYLE_PRESETS)

    db.init_db()

    seeded = set(CONTRACT_COMIC) | set(CONTRACT_NOVEL)
    old_rows = [r for r in db.q("SELECT value, style_type FROM style_presets")
                if r["value"] not in seeded]
    assert not [r for r in old_rows if r["style_type"] != "visual"], \
        "存量行不该被改成非 visual"
    new_values = {r["value"] for r in db.q("SELECT value FROM style_presets")} - before
    assert new_values == seeded
    assert _counts() == {"visual": len(db.STYLE_PRESETS),
                      "comic": len(db.COMIC_STYLE_PRESETS),
                      "novel": len(db.NOVEL_STYLE_PRESETS)}


def test_comic_options_merge_builtin_and_db_rows(tmp_db):
    from app.pipeline.comic import comic_style_options
    opts = comic_style_options()
    prompts = [p for _, p in opts]
    assert len(prompts) == len(set(prompts)), "下拉里出现重复项"
    for value, (_n, _o, _d, prompt) in CONTRACT_COMIC.items():
        assert prompt in prompts, f"内置漫画画风 {value} 不在下拉里"

    # 用户自建条目要能选到
    db.ex("INSERT INTO style_presets(name,value,prompt,description,work_type,style_type,"
          "sort_order,is_active,created_at) VALUES(?,?,?,?,?,?,?,1,?)",
          ("我的画风", "my_comic", "my own comic prompt", "d", "all", "comic", 900, db.now()))
    opts = comic_style_options()
    assert ("我的画风", "my own comic prompt") in opts

    # prompt 全文相同 → 只出现一次
    db.ex("INSERT INTO style_presets(name,value,prompt,description,work_type,style_type,"
          "sort_order,is_active,created_at) VALUES(?,?,?,?,?,?,?,1,?)",
          ("重复项", "dup_comic", CONTRACT_COMIC["manga_jp"][3], "d", "all", "comic", 901, db.now()))
    opts = comic_style_options()
    assert len([p for _, p in opts if p == CONTRACT_COMIC["manga_jp"][3]]) == 1

    # work_type 不匹配的行不进漫画画风下拉(老下拉把 promotion 类也列出来)
    db.ex("INSERT INTO style_presets(name,value,prompt,description,work_type,style_type,"
          "sort_order,is_active,created_at) VALUES(?,?,?,?,?,?,?,1,?)",
          ("宣传类", "promo_comic", "promo prompt", "d", "promotion", "comic", 902, db.now()))
    opts = comic_style_options()
    assert not [p for _, p in opts if p == "promo prompt"]


def test_novel_options_merge_builtin_and_db_rows(tmp_db):
    from app.pipeline.novel import NOVEL_STYLES, novel_style_options
    opts = novel_style_options()
    prompts = [p for _, p in opts]
    assert len(prompts) == len(set(prompts)), "下拉里出现重复项"
    for _name, prompt in NOVEL_STYLES:
        assert prompt in prompts
    db.ex("INSERT INTO style_presets(name,value,prompt,description,work_type,style_type,"
          "sort_order,is_active,created_at) VALUES(?,?,?,?,?,?,?,1,?)",
          ("我的文风", "my_novel", "my own writing style", "d", "all", "novel", 900, db.now()))
    assert ("我的文风", "my own writing style") in novel_style_options()


def test_disabled_preset_disappears_from_dropdown(tmp_db):
    from app.pipeline.comic import comic_style_options
    db.ex("UPDATE style_presets SET is_active=0 WHERE value='manga_jp'")
    prompts = [p for _, p in comic_style_options()]
    assert CONTRACT_COMIC["manga_jp"][3] not in prompts


# ── 回归:内置项的「停用」与「改分类」必须真的生效 ────────────────
# 内置预设删不掉(种子每次启动都会补回),所以「停用」是官方唯一的替代手段。
# 如果内置常量兜底把停用/改分类的行又加回下拉,这两条路径就形同虚设。

def test_disabled_builtin_is_not_revived_by_constant_fallback(tmp_db):
    """停用的内置项不能被内置常量兜底复活。"""
    from app.core.db import merge_style_options, style_options
    db.ex("UPDATE style_presets SET is_active=0 WHERE value='manga_jp'")
    # 纯函数:行存在且 is_active=0 → 不出现
    rows = db.q("SELECT * FROM style_presets")
    prompts = [p for _l, p in merge_style_options(rows, "comic")]
    assert CONTRACT_COMIC["manga_jp"][3] not in prompts
    # 真实取数路径同样要过滤掉
    assert CONTRACT_COMIC["manga_jp"][3] not in [p for _l, p in style_options("comic")]
    assert prompts, "兜底:仍有其它画风可选"


def test_builtin_moved_to_other_category_leaves_old_dropdown(tmp_db):
    """用户把内置项改到别的分类后,它不能再出现在原分类下拉里。"""
    from app.core.db import style_options
    db.ex("UPDATE style_presets SET style_type='visual' WHERE value='manga_jp'")
    assert CONTRACT_COMIC["manga_jp"][3] not in [p for _l, p in style_options("comic")]


def test_style_options_fetches_builtin_rows_regardless_of_category(tmp_db):
    """style_options 必须把内置项整行取回来(含被改分类/停用的),否则函数分不清
    「库里没有」和「被停用/改了分类」,只能走常量兜底把用户的操作无视掉。"""
    from app.core.db import style_options
    db.ex("UPDATE style_presets SET style_type='visual', is_active=0 WHERE value='manga_jp'")
    # 停用 + 改分类 → 漫画下拉里没有
    assert CONTRACT_COMIC["manga_jp"][3] not in [p for _l, p in style_options("comic")]
    # 恢复启用但仍在 visual 分类 → 依然不在漫画下拉(分类说了算)
    db.ex("UPDATE style_presets SET is_active=1 WHERE value='manga_jp'")
    assert CONTRACT_COMIC["manga_jp"][3] not in [p for _l, p in style_options("comic")]


def test_style_prompt_flex_resolves_disabled_full_prompt(tmp_db):
    """按 prompt 全文也要能查到停用状态:否则「停用」在数据层完全失效。"""
    prompt = CONTRACT_COMIC["manga_jp"][3]
    assert db.style_prompt_flex(prompt)
    db.ex("UPDATE style_presets SET is_active=0 WHERE value='manga_jp'")
    assert db.style_prompt_flex(prompt) == ""


def test_project_settings_dropdown_hides_disabled_builtin(tmp_db, qt_app):
    """项目设置里的「画风」下拉不能出现被停用的内置项(UI 真实路径)。"""
    from app.ui import asset_dialogs

    db.ex("INSERT INTO dramas(title,created_at,updated_at) VALUES(?,?,?)",
          ("测试剧", db.now(), db.now()))
    did = db.q1("SELECT id FROM dramas ORDER BY id DESC LIMIT 1")["id"]
    db.ex("UPDATE style_presets SET is_active=0 WHERE value='manga_jp'")
    dlg = asset_dialogs.ProjectSettingsDialog(None, did)
    try:
        prompts = [dlg.comic_style.itemData(i) for i in range(dlg.comic_style.count())]
        assert CONTRACT_COMIC["manga_jp"][3] not in prompts
    finally:
        dlg.deleteLater()


def test_visual_style_prompt_resolution_unchanged(tmp_db):
    """视觉风格的老消费路径不变:db.style_prompt() 仍按 value 取 prompt。"""
    assert db.style_prompt("3d").startswith("high-quality 3D CG animation still")
    assert db.style_prompt("no-such-value") == ""


def test_style_prompt_flex_accepts_value_and_full_prompt(tmp_db):
    """漫画画风链路:存量项目存的是 value,新下拉存的是 prompt 全文,两种都要认。"""
    by_value = db.style_prompt_flex("3d")
    by_prompt = db.style_prompt_flex(db.style_prompt("3d"))
    assert by_value and by_prompt
    assert db.style_prompt_flex("") == ""
    # 库里没有的 value:不查表,当 prompt 全文原样用(新下拉写的就是全文)
    assert db.style_prompt_flex("no-such-value").startswith("no-such-value")
    # 停用的预设不生效(与老 style_prompt() 一致)
    db.ex("UPDATE style_presets SET is_active=0 WHERE value='3d'")
    assert db.style_prompt_flex("3d") != by_value


def test_display_name_rule_builtin_localized_user_raw(tmp_db):
    """内置条目显示本地化名,用户自建条目显示 name 原样。"""
    assert db.style_display_name("manga_jp", "随便改的名字") == "日漫"
    assert db.style_display_name("my_comic", "我的画风") == "我的画风"


def test_new_ui_strings_present_in_all_16_languages():
    from app.core.i18n import LANGS
    langs = [code for code, _ in LANGS]
    assert len(langs) == 16, f"界面语言数不是 16:{len(langs)}"
    assert set(langs) == {"zh", "zh-Hant", "en", "ja", "ko", "fr", "de", "it", "pt",
                          "es", "vi", "tr", "ar", "hi", "id", "th"}
    for lang in langs:
        i18n.set_language(lang)
        for key in _NEW_KEYS:
            val = i18n.tr(key)
            assert val and val != key, f"{lang} 下 {key} 没翻译出来:{val!r}"
            if lang in _LATIN_LANGS:
                assert not _HAS_CJK.search(val), f"{lang} 下 {key} 漏出中文:{val!r}"
        assert "{0}" in i18n.tr("style_delete_confirm"), "删除确认文案缺占位符"
    i18n.set_language("zh")


def test_builtin_style_names_present_in_all_16_languages():
    """内置风格名(含漫画画风)16 语言齐全,不漏中文。"""
    from app.core.i18n import LANGS
    names = sorted(db.BUILTIN_STYLE_NAMES.values())
    assert len(names) >= 32, "内置风格名被删少了"
    for lang in [code for code, _ in LANGS]:
        i18n.set_language(lang)
        for name in names:
            val = i18n.tr(name)
            assert val, f"{lang} 下内置风格名 {name} 没翻译"
            if lang in _LATIN_LANGS:
                assert not _HAS_CJK.search(val), f"{lang} 下内置风格名 {name} 漏出中文:{val!r}"
        if lang == "zh-Hant":
            for name in names:
                if name in _ZH_HANT_SAME:
                    continue
                assert i18n.tr(name) != name, f"繁体下 {name} 还是简体"
    i18n.set_language("zh")


# ── 设置页:三分类切换 + 增删改停 ────────────────────────────────
@pytest.fixture
def qt_app():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _style_page(dlg):
    """切到「风格预设」页并返回该对话框(控件都挂在对话框上)。"""
    from app.core.i18n import tr
    for i in range(dlg.tabs_nav.count()):
        if tr("style_presets") in dlg.tabs_nav.item(i).text():
            dlg.tabs_nav.setCurrentRow(i)
            break
    return dlg


def test_settings_page_switches_three_categories(tmp_db, qt_app):
    from app.ui import settings_dialog as sdlg
    dlg = sdlg.SettingsDialog(None)
    try:
        page = _style_page(dlg)
        combo = page.style_type_combo
        assert [combo.itemData(i) for i in range(combo.count())] == ["visual", "comic", "novel"]
        counts = {}
        for i in range(combo.count()):
            combo.setCurrentIndex(i)
            counts[combo.currentData()] = page.style_list.count()
        assert counts == {"visual": len(db.STYLE_PRESETS),
                          "comic": len(db.COMIC_STYLE_PRESETS),
                          "novel": len(db.NOVEL_STYLE_PRESETS)}
    finally:
        dlg.deleteLater()


def test_settings_page_add_toggle_delete(tmp_db, qt_app, monkeypatch):
    """新增 → 启停 → 删除,走设置页真实按钮。"""
    from PySide6.QtCore import Qt

    from app.ui import settings_dialog as sdlg
    # 确认框是模态的,offscreen 下会一直等 —— 这里直接放行
    monkeypatch.setattr(sdlg, "ask", lambda *a, **k: True)
    monkeypatch.setattr(sdlg, "warn", lambda *a, **k: None)
    dlg = sdlg.SettingsDialog(None)
    try:
        page = _style_page(dlg)
        page.style_type_combo.setCurrentIndex(1)   # 漫画风格
        assert page.style_list.count() == 6

        # 新增(直接落库,等价于弹窗确认后的路径)
        db.ex("INSERT INTO style_presets(name,value,prompt,description,work_type,style_type,"
              "sort_order,is_active,created_at) VALUES(?,?,?,?,?,?,?,1,?)",
              ("我的画风", "my_comic2", "my prompt", "d", "all", "comic", 999, db.now()))
        page._refresh_styles()
        assert page.style_list.count() == 7

        # 启停
        page.style_list.setCurrentRow(page.style_list.count() - 1)
        row = page.style_list.currentItem().data(Qt.UserRole)
        page._toggle_style()
        assert db.q1("SELECT is_active FROM style_presets WHERE id=?", (row["id"],))["is_active"] == 0
        page._toggle_style()
        assert db.q1("SELECT is_active FROM style_presets WHERE id=?", (row["id"],))["is_active"] == 1

        # 删除(自建条目可删)
        page.style_list.setCurrentRow(page.style_list.count() - 1)
        page._delete_style()
        assert db.q1("SELECT id FROM style_presets WHERE value='my_comic2'") is None
    finally:
        dlg.deleteLater()


def test_settings_page_shows_localized_name_for_builtin(tmp_db, qt_app):
    """内置条目显示本地化名,用户自建显示 name 原样。"""
    from app.ui import settings_dialog as sdlg
    dlg = sdlg.SettingsDialog(None)
    try:
        page = _style_page(dlg)
        page.style_type_combo.setCurrentIndex(1)   # 漫画风格
        labels = [page.style_list.item(i).text() for i in range(page.style_list.count())]
        assert any("日漫" in t for t in labels)
        db.ex("INSERT INTO style_presets(name,value,prompt,description,work_type,style_type,"
              "sort_order,is_active,created_at) VALUES(?,?,?,?,?,?,?,1,?)",
              ("我的画风", "my_comic3", "my prompt", "d", "all", "comic", 998, db.now()))
        page._refresh_styles()
        labels = [page.style_list.item(i).text() for i in range(page.style_list.count())]
        assert any("我的画风" in t for t in labels)
    finally:
        dlg.deleteLater()
