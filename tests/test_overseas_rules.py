# -*- coding: utf-8 -*-
"""海外题材改写 · 领域规则库。

规则库外置在 `data/overseas/`(用户可编辑),测试一律用临时目录,
绝不碰真实数据目录 —— 用户可能已经改过自己的规则文件。
"""
from __future__ import annotations

import json

import pytest

from app.pipeline import overseas_rules


@pytest.fixture
def rule_dir(tmp_path, monkeypatch):
    d = tmp_path / "overseas"
    monkeypatch.setattr(overseas_rules, "OVERSEAS_DIR", d)
    overseas_rules.seed_templates()
    return d


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- 播种

def test_seed_creates_all_template_files(rule_dir):
    assert (rule_dir / "platforms" / "goodnovel.json").exists()
    assert (rule_dir / "platforms" / "dreame.json").exists()
    assert (rule_dir / "platforms" / "webnovel.json").exists()
    assert (rule_dir / "categories" / "werewolf.json").exists()
    assert (rule_dir / "categories" / "mafia-romance.json").exists()
    assert (rule_dir / "categories" / "billionaire.json").exists()
    assert (rule_dir / "categories" / "systemfic.json").exists()
    assert (rule_dir / "language" / "en-US.json").exists()
    assert (rule_dir / "narrative.json").exists()


def test_seed_never_overwrites_user_edits(rule_dir):
    """用户改过的规则文件必须原样保留 —— 播种只补缺失。"""
    p = rule_dir / "platforms" / "goodnovel.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    data["name"] = "My Own GoodNovel"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    seeded = overseas_rules.seed_templates()
    assert seeded == []
    assert json.loads(p.read_text(encoding="utf-8"))["name"] == "My Own GoodNovel"


def test_seed_reports_newly_seeded_paths(tmp_path, monkeypatch):
    d = tmp_path / "overseas"
    monkeypatch.setattr(overseas_rules, "OVERSEAS_DIR", d)
    seeded = overseas_rules.seed_templates()
    assert "platforms/goodnovel.json" in seeded
    assert "narrative.json" in seeded


def test_seed_force_overwrites_user_edits(rule_dir):
    """force=True 用于「恢复默认规则库」:应覆盖用户改动。"""
    p = rule_dir / "language" / "en-US.json"
    p.write_text('{"id": "en-US", "name": "broken"}', encoding="utf-8")
    seeded = overseas_rules.seed_templates(force=True)
    assert "language/en-US.json" in seeded
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["name"] != "broken"
    assert overseas_rules.validate() == []


# ---------------------------------------------------------------- 查询

def test_list_platforms_and_categories(rule_dir):
    pids = {p["id"] for p in overseas_rules.list_platforms()}
    cids = {c["id"] for c in overseas_rules.list_categories()}
    assert pids == {"dreame", "goodnovel", "webnovel"}
    assert cids == {"werewolf", "mafia-romance", "billionaire", "systemfic"}
    # 平台规格是二手数据 → 必须带「未核实」标记
    good = next(p for p in overseas_rules.list_platforms() if p["id"] == "goodnovel")
    assert good["source_verified"] is False


def test_unknown_platform_raises_with_available_list(rule_dir):
    with pytest.raises(overseas_rules.RuleError) as exc:
        overseas_rules.get_platform("nope")
    msg = str(exc.value)
    assert "nope" in msg
    assert "goodnovel" in msg


def test_unknown_category_and_language_raise(rule_dir):
    with pytest.raises(overseas_rules.RuleError):
        overseas_rules.get_category("nope")
    with pytest.raises(overseas_rules.RuleError):
        overseas_rules.get_language("zz-ZZ")


def test_language_id_rejects_path_traversal(rule_dir):
    """get_language 把 id 直接拼进文件路径,接上 UI 下拉后用户输入即可达。"""
    for bad in ("../narrative", "../../secrets", "/etc/passwd", "",
                "en-US/../../../x", "en US"):
        with pytest.raises(overseas_rules.RuleError):
            overseas_rules.get_language(bad)


def test_glossary_seed_and_bounds(rule_dir):
    seed = overseas_rules.glossary_seed("werewolf")
    assert seed["Alpha"] == "Alpha"
    assert seed["标记"] == "mate mark"
    assert overseas_rules.chapter_bounds("goodnovel") == (800, 1500)
    assert overseas_rules.paywall_range("goodnovel") == (6, 8)
    # Webnovel 的卡点区间二手来源没给 → 不做该检查
    assert overseas_rules.paywall_range("webnovel") is None


# ---------------------------------------------------------------- 体检

def test_validate_passes_on_seeded_templates(rule_dir):
    assert overseas_rules.validate() == []


def test_validate_flags_broken_paywall_range(rule_dir):
    _write(rule_dir / "platforms" / "badplat.json",
           {"id": "badplat", "name": "Bad",
            "paywall": {"paywall_chapter_range": [9, 3]}})
    problems = overseas_rules.validate()
    assert any("badplat" in p for p in problems)


def test_validate_flags_category_without_glossary(rule_dir):
    _write(rule_dir / "categories" / "nocat.json",
           {"id": "nocat", "name": "No Glossary"})
    problems = overseas_rules.validate()
    assert any("nocat" in p and "glossary_seed" in p for p in problems)


def test_validate_flags_missing_platform_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(overseas_rules, "OVERSEAS_DIR", tmp_path / "empty")
    problems = overseas_rules.validate()
    assert any("平台" in p for p in problems)


# ---------------------------------------------------------------- 拼装

def _section(text: str, title: str) -> str:
    """取某个 '## 标题' 段落的内容(到下一个 '## ' 为止)。"""
    start = text.find(f"## {title}")
    if start < 0:
        return ""
    rest = text[start:]
    nxt = rest.find("\n## ", 1)
    return rest[:nxt] if nxt > 0 else rest


def test_assemble_only_includes_selected_platform_and_category(rule_dir):
    """按需加载:没选中的平台/品类绝不能出现在 prompt 里(否则 prompt 爆炸)。

    注意:平台读者画像里会提到该平台收的其它品类(那是给模型做背景的),
    所以这里只查**品类规则段** —— 未选中的品类的桥段与术语不能漏进来。
    """
    text = overseas_rules.assemble("goodnovel", "werewolf")
    assert "GoodNovel" in text
    assert "Dreame" not in text
    cat = _section(text, "品类套路")
    assert "fated_mate" in cat
    assert "hidden_identity" not in cat
    assert "black_card_drama" not in cat
    # 显式钉死单一品类,避免模型把平台收的其它品类桥段混进来
    assert "只采用" in cat


def test_assemble_contains_paywall_reverse_steps(rule_dir):
    text = overseas_rules.assemble("goodnovel", "werewolf")
    assert "付费卡点设计" in text
    assert "倒推步骤" in text
    assert "免费段只堆惨" in text


def test_assemble_marks_current_level(rule_dir):
    text = overseas_rules.assemble("goodnovel", "werewolf", level="B")
    assert "西化改造" in text
    assert "←当前级别" in text


def test_assemble_includes_target_language_points(rule_dir):
    text = overseas_rules.assemble("goodnovel", "werewolf", target_lang="en-US")
    assert "目标语言要点" in text
    assert "块钱" in text  # 常见误译对照


def test_assemble_includes_platform_style_notes(rule_dir):
    """平台文风与读者口味必须进 prompt —— 换平台真正变的是这一段。"""
    text = overseas_rules.assemble("goodnovel", "werewolf")
    assert "平台文风与读者口味" in text
    assert "读者画像" in text
    assert "审核尺度" in text


def test_different_platforms_produce_different_rules(rule_dir):
    """同一篇稿子换平台,规则片段必须真的不一样。"""
    good = overseas_rules.assemble("goodnovel", "billionaire")
    web = overseas_rules.assemble("webnovel", "billionaire")
    assert good != web
    assert "第 6-8 章" in good          # GoodNovel 卡点区间
    assert "日更 1500 字" in web        # Webnovel 日更
    assert "男频" in web
    assert "女频" in good


def test_different_categories_produce_different_rules(rule_dir):
    a = overseas_rules.assemble("goodnovel", "billionaire")
    b = overseas_rules.assemble("goodnovel", "werewolf")
    assert a != b
    cat_a = _section(a, "品类套路")
    cat_b = _section(b, "品类套路")
    assert "fated_mate" in cat_b
    assert "hidden_identity" in cat_a
    assert "fated_mate" not in cat_a
    assert "Mafia Romance" not in cat_a
    # 平台读者画像会提到别的品类,但品类规则段不能混
    assert "只采用" in cat_a


def test_assemble_unknown_platform_raises(rule_dir):
    with pytest.raises(overseas_rules.RuleError):
        overseas_rules.assemble("nope", "werewolf")


# ---------------------------------------------------------------- 多语言包

def test_all_language_packs_load_and_validate(rule_dir):
    """每个语言包都要能被加载并通过 schema —— 否则用户选到它才在 UI 层炸。"""
    assert overseas_rules.validate() == []
    langs = overseas_rules.list_languages()
    assert len(langs) >= 14, f"语言包太少: {[l['id'] for l in langs]}"
    ids = {l["id"] for l in langs}
    assert "en-US" in ids and "fr-FR" in ids and "zh-Hant" not in ids, \
        "zh-Hant 走简繁转换,不该作为海外目标语言包出现"
    for l in langs:
        data = overseas_rules.get_language(l["id"])
        assert data.get("name"), f"{l['id']} 缺 name"
        assert data.get("punctuation", {}).get("forbid_fullwidth"), \
            f"{l['id']} 缺 forbid_fullwidth"


def test_skeleton_packs_are_labelled_not_silent(rule_dir):
    """骨架包必须标 depth=skeleton —— 静默降级比明确告知危险得多。

    否则用户看到「质检全过」,其实只跑了语言无关的几条规则。
    """
    langs = {l["id"]: l for l in overseas_rules.list_languages()}
    full = [k for k, v in langs.items() if v["depth"] == "full"]
    skel = [k for k, v in langs.items() if v["depth"] == "skeleton"]
    assert set(full) == {"en-US", "fr-FR", "es-ES", "pt-BR", "id-ID"}, full
    assert len(skel) == 9, skel
    for k in skel:
        assert langs[k]["name_zh"], f"{k} 缺中文名"
        data = overseas_rules.get_language(k)
        assert data.get("depth_note"), f"{k} 缺 depth_note,UI 无法解释降级"


def test_full_packs_have_usable_localisation_rules(rule_dir):
    """完整包必须有真规则 —— 这三块以前是数据文件里的死字段。"""
    for lid in ("en-US", "fr-FR", "es-ES", "pt-BR", "id-ID"):
        d = overseas_rules.get_language(lid)
        assert d["address"]["map"], f"{lid} 称呼表为空"
        assert d["common_mistranslations"], f"{lid} 误译表为空"
        assert d["hook_markers"]["patterns"], f"{lid} 钩子标记为空"
        assert d["self_observation_forbidden"]["patterns"], f"{lid} 自指观察正则为空"
        assert d["euphemism"]["levels"], f"{lid} 委婉层级为空"
        assert d["money_time"]["examples"], f"{lid} 金钱/时间示例为空"


def test_dead_fields_now_reach_the_prompt(rule_dir):
    """以前 filler / euphemism / money_time / address.map 没人读,写的人以为生效了。"""
    text = overseas_rules.assemble("goodnovel", "billionaire", target_lang="fr-FR")
    assert "称呼固定译名" in text and "beau-père" in text
    assert "委婉层级" in text and "n\'a pas survécu".replace("\'", "'") in text
    assert "时间与金钱表达" in text and "au cœur de la nuit" in text
    assert "语气词" in text


def test_prompt_names_the_actual_target_language(rule_dir):
    """规则段的标题必须写实际语种名,不能永远叫「English」。"""
    fr = overseas_rules.assemble("goodnovel", "billionaire", target_lang="fr-FR")
    assert "目标语言要点(French)" in fr
    es = overseas_rules.assemble("goodnovel", "billionaire", target_lang="es-ES")
    assert "目标语言要点(Spanish)" in es
