# -*- coding: utf-8 -*-
"""海外题材改写 · 静态校验器(R1-R11)。

只做纯函数测试,不碰数据库、不碰真实数据目录。
"""
from __future__ import annotations

from app.pipeline.overseas_check import (
    _HOOK_MARKERS_DEFAULT,
    check_chapter_words,
    check_chinese_residue,
    check_cliffhanger,
    check_glossary_consistency,
    check_opening_payoff,
    check_passivity,
    check_paywall_position,
    check_redundancy,
    check_self_observation,
    check_task_reward,
    check_translationese,
    format_issues,
    run_checks,
)

PASSIVE_EN = ("I saw the door. I felt the cold air. I heard the wind outside.")
ACTIVE_EN = "I saw the door. I decided to run. I pushed it open and ran."


# ---------------------------------------------------------------- R1

def test_r1_flags_chinese_self_observation():
    issues = check_self_observation("我的脸红了,那句话像刀一样扎进来。")
    assert any(i.rule == "R1" for i in issues)
    assert issues[0].severity == "error"


def test_r1_flags_english_self_observation():
    issues = check_self_observation("My face flushed the moment she read it.")
    assert any(i.rule == "R1" for i in issues)


def test_r1_allows_hand_sensation():
    """「我的手指发白」不算违背(有感觉依据),不该误报。"""
    assert check_self_observation("我的手指发白,攥紧了衣角。") == []


def test_r1_does_not_flag_normal_sentences():
    """夹字符的宽松写法会误伤:「我的眼睛盯着红酒杯」必须放过。"""
    assert check_self_observation("我的眼睛盯着那杯红酒,一动不动。") == []
    assert check_self_observation("我的脸被他的手挡住了。") == []
    assert check_self_observation("My skin burned where the rope bit in.") == []


def test_r1_bare_expression_is_warning_not_error():
    issues = check_self_observation("我的表情很平静,像早就知道答案。")
    assert issues and issues[0].severity == "warn"


# ---------------------------------------------------------------- R2

def test_r2_flags_passive_chain():
    issues = check_passivity(PASSIVE_EN)
    assert any(i.rule == "R2" for i in issues)


def test_r2_allows_active_chain():
    assert check_passivity(ACTIVE_EN) == []


def test_r2_flags_chinese_passive_chain():
    text = "我看到门口有人。我感觉心里发冷。我听见身后传来脚步声。"
    assert any(i.rule == "R2" for i in check_passivity(text))


# ---------------------------------------------------------------- R3

def test_r3_flags_adjacent_duplicate_sentences():
    text = "The rain hammered the glass. The rain hammered the glass. He waited by the door."
    assert any(i.rule == "R3" for i in check_redundancy(text))


def test_r3_flags_repeated_fragment():
    text = ("She opened the gate and walked toward the old stone bridge in the rain. "
            "She opened the gate and walked toward the old stone bridge in the rain. "
            "She opened the gate and walked toward the old stone bridge in the rain.")
    assert any(i.rule == "R3" for i in check_redundancy(text))


def test_r3_quiet_on_normal_text():
    text = ("He opened the door. The room smelled of rain and old wood. "
            "She set her bag down and looked at the window.")
    assert check_redundancy(text) == []


# ---------------------------------------------------------------- R4

def test_r4_flags_chinese_residue_in_english_draft():
    issues = check_chinese_residue("He opened the door and said 你好 to her, then left.")
    assert any(i.rule == "R4" for i in issues)
    assert issues[0].severity == "error"


def test_r4_flags_fullwidth_punctuation():
    issues = check_chinese_residue("She turned, and the room went very quiet，then he smiled.")
    assert any("全角" in i.message for i in issues)


def test_r4_quiet_on_pure_chinese_draft():
    """中文原稿不该被自己的汉字判成残留。"""
    assert check_chinese_residue("她推开门,屋里很安静。") == []


def test_r4_quiet_on_clean_english():
    assert check_chinese_residue("She opened the door and the room went quiet.") == []


def test_r4_does_not_flag_english_curly_quotes():
    """弯引号 “ ” 与破折号 — 在英文排版里是正规用法,不能当成中文标点。

    真实改写稿全篇用 “ 展开引号,早期版本把它们列进全角禁用集 → 整篇误报。
    """
    text = ("“Your father’s bill is short by half a million dollars,” she said — "
            "and I could not answer.")
    assert check_chinese_residue(text) == []


def test_r4_still_flags_real_fullwidth_punctuation():
    issues = check_chinese_residue("She turned, and the room went very quiet，然后他笑了。")
    assert any(i.rule == "R4" for i in issues)


# ---------------------------------------------------------------- R5

def test_r5_flags_reversed_name():
    issues = check_glossary_consistency("Wan Lin arrived at noon.", {"林晚": "Lin Wan"})
    assert any(i.rule == "R5" for i in issues)


def test_r5_flags_case_variant():
    issues = check_glossary_consistency("chen mo sat down quietly.", {"陈默": "Chen Mo"})
    assert any(i.rule == "R5" for i in issues)
    assert issues[0].severity == "warn"


def test_r5_quiet_when_consistent():
    assert check_glossary_consistency("Lin Wan arrived at noon.", {"林晚": "Lin Wan"}) == []


def test_r5_accepts_sentence_initial_capital_of_lowercase_term():
    """术语表里是小写起头的普通名词短语(总裁→the CEO)时,正文句首写
    「The CEO」是英文正常句首大写,**不算术语不一致**。
    真实改写稿就是这么写的,早期版本把它误报成 R5。"""
    text = 'His answer came without hesitation. “The CEO asked me to call you.”'
    assert check_glossary_consistency(text, {"总裁": "the CEO"}) == []


def test_r5_still_flags_mid_sentence_capital_of_lowercase_term():
    """同样的大小写差异,但出现在句中 —— 那是真不一致,仍要报。"""
    issues = check_glossary_consistency(
        "I told The CEO everything.", {"总裁": "the CEO"})
    assert any(i.rule == "R5" for i in issues)


def test_r5_flags_whitespace_variant():
    """术语要逐字照用:双空格也算写法不一致(之前被空白归一化吃掉了)。"""
    issues = check_glossary_consistency(
        "She works at Shengshi  Group now.", {"盛世集团": "Shengshi Group"})
    assert any(i.rule == "R5" for i in issues)


def test_r5_accepts_list_form_glossary():
    issues = check_glossary_consistency(
        "Wan Lin arrived.", [{"source": "林晚", "target": "Lin Wan"}])
    assert any(i.rule == "R5" for i in issues)


# ---------------------------------------------------------------- R6/R7

def test_r6_flags_short_and_long_chapters():
    assert check_chapter_words("too short", (800, 1500))[0].rule == "R6"
    long_text = "word " * 1600
    assert check_chapter_words(long_text, (800, 1500))[0].rule == "R6"


def test_r6_quiet_inside_bounds():
    text = "word " * 900
    assert check_chapter_words(text, (800, 1500)) == []


def test_r6_quiet_without_bounds():
    assert check_chapter_words("too short", None) == []


def test_r7_flags_paywall_outside_platform_range():
    assert check_paywall_position([6, 7], (6, 8)) == []
    issues = check_paywall_position([12], (6, 8))
    assert issues and issues[0].rule == "R7"


def test_r7_quiet_when_platform_has_no_range():
    assert check_paywall_position([12], None) == []


# ---------------------------------------------------------------- R8/R9/R11

def test_r8_flags_missing_opening_payoff():
    issues = check_opening_payoff("She walked home slowly.", ["Alpha", "mate"], 3, 1)
    assert issues and issues[0].rule == "R8"


def test_r8_quiet_when_keyword_present():
    assert check_opening_payoff("He was the Alpha of the pack.", ["Alpha"], 3, 1) == []


def test_r8_skips_chapters_beyond_opening_window():
    assert check_opening_payoff("She walked home slowly.", ["Alpha"], 3, 9) == []


def test_r9_flags_missing_cliffhanger():
    issues = check_cliffhanger("She turned and walked away quietly.", ["before she could"])
    assert issues and issues[0].rule == "R9"


def test_r9_quiet_with_marker_or_question():
    assert check_cliffhanger(
        "She turned. Before she could answer, the door burst open.",
        ["before she could"]) == []
    assert check_cliffhanger("Who was on the other side?", []) == []


def test_r9_recognises_began_to_as_hook():
    """真实改写稿的收尾:「...began to blink red.」是标准断点,不能误报。"""
    issues = check_cliffhanger(
        "The access panel beside them began to blink red.",
        ["began to", "started to"])
    assert issues == []


def test_r9_recognises_interrupted_action_as_hook():
    """「...before my hand touched the handle.」= 动作被打断,属于未完成动作钩子。

    真实改写稿的收尾句,早期版本没收录这个句式,把它误报成「章末无钩子」。
    """
    issues = check_cliffhanger(
        "It opened from the inside before my hand touched the handle.",
        _HOOK_MARKERS_DEFAULT)
    assert issues == []


def test_r11_flags_missing_task_reward():
    tr = {"required": True, "markers": ["level up", "reward"]}
    issues = check_task_reward("She looked at the panel and closed it.", tr)
    assert issues and issues[0].rule == "R11"


def test_r11_quiet_with_reward_marker():
    tr = {"required": True, "markers": ["level up", "reward"]}
    text = "She looked at the panel.\n\nLevel up! The System chimed."
    assert check_task_reward(text, tr) == []


def test_r11_skipped_when_category_does_not_require():
    assert check_task_reward("She looked at the panel.", {"required": False}) == []


# ---------------------------------------------------------------- R10

def test_r10_flags_overlong_sentence():
    cfg = {"max_sentence_words": 20, "max_passive_ratio": 0.3, "max_filler_total": 3,
           "filler_words": ["very"],
           "passive_pattern": r"\b(?:was|were|is|are|been|being|be)\s+\w+(?:ed|en)\b"}
    text = ("This is a sentence that goes on and on and on and on and on and on "
            "and on and on and on and on and on and on and on and on.")
    assert any(i.rule == "R10" for i in check_translationese(text, cfg))


def test_r10_flags_filler_overuse():
    cfg = {"max_sentence_words": 35, "max_passive_ratio": 0.9, "max_filler_total": 2,
           "filler_words": ["very"]}
    text = "It was a very good day, a very long day, a very strange day indeed."
    assert any("填充词" in i.message for i in check_translationese(text, cfg))


def test_r10_quiet_on_clean_english():
    cfg = {"max_sentence_words": 35, "max_passive_ratio": 0.3, "max_filler_total": 5,
           "filler_words": ["very"], "passive_pattern": r"\b(?:was|were|is|are)\s+\w+(?:ed|en)\b"}
    text = ("She opened the door and found the room empty. "
            "Someone had left the lamp on.")
    assert check_translationese(text, cfg) == []


# ---------------------------------------------------------------- 汇总

def test_run_checks_aggregates_rule_ids():
    platform = {"chapter": {"min_words": 10, "max_words": 1000},
                "paywall": {"paywall_chapter_range": [6, 8]},
                "opening": {"payoff_within_chapters": 3}}
    category = {"payoff_keywords": ["Alpha"], "task_reward": {"required": False}}
    language = {"hook_markers": {"en": ["before she could"]}, "translationese": {}}
    text = "My face flushed when she saw him. He said 你好 to her."
    rules = {i.rule for i in run_checks(text, chapter_no=1, platform=platform,
                                         category=category, language=language)}
    assert "R1" in rules
    assert "R4" in rules


def test_run_checks_quiet_on_healthy_chapter():
    platform = {"chapter": {"min_words": 10, "max_words": 1000},
                "paywall": {"paywall_chapter_range": [6, 8]},
                "opening": {"payoff_within_chapters": 3}}
    category = {"payoff_keywords": ["Alpha"], "task_reward": {"required": False}}
    language = {"hook_markers": {"en": ["before she could"]},
                "translationese": {"max_sentence_words": 35, "max_passive_ratio": 0.9,
                                   "max_filler_total": 9, "filler_words": []}}
    text = ("She decided to tell him everything. He was the Alpha of the northern pack "
            "and he had waited three winters for this answer. Before she could speak, "
            "the war horn sounded beyond the ridge and every wolf in the camp turned.")
    assert run_checks(text, chapter_no=1, platform=platform, category=category,
                       language=language) == []


def test_format_issues_renders_text():
    issues = run_checks("My face flushed.", chapter_no=1)
    lines = format_issues(issues)
    assert lines and lines[0].startswith("[R1]")


# ---------------------------------------------------------------- 多语言语种

def test_japanese_chapter_length_is_not_zero():
    """日文稿既不是中文、也几乎不含拉丁字母。

    旧实现里 `_count_words` 只认拉丁字母,日文稿字数恒为 0 → R6 每章误报
    「章节字数 0 低于平台下限 800」,用户改对了却满屏报错。
    """
    from app.pipeline.overseas_check import _count_words
    ja = "彼は彼女を見た。その瞬間、心臓が止まった。窓の外では雨が降っていた。" * 12
    n = _count_words(ja, "ja-JP")
    # 30 个汉字/假名 × 12 轮 = 360 字,按「1 字 ≈ 1.8 英文词」折算 ≈ 200 词
    assert 180 <= n <= 220, f"日文字数折算异常: {n}"


def test_thai_and_arabic_are_not_zero_words():
    """泰语/阿拉伯语无空格分词,也不能算成 0 词。"""
    from app.pipeline.overseas_check import _count_words
    th = "เขาเดินเข้ามาในห้องและมองไปที่เธออย่างเงียบงัน" * 20
    ar = "دخل الغرفة ونظر إليها بصمت لا توصفه الكلمات" * 20
    assert _count_words(th, "th-TH") > 100
    assert _count_words(ar, "ar-SA") > 100


def test_latin_word_count_unchanged():
    """拉丁系仍按词数 1:1 —— 平台规格是按英文词数标的。"""
    from app.pipeline.overseas_check import _count_words
    en = "He walked into the room and looked at her without a word."
    assert _count_words(en, "en-US") == 12


def test_japanese_not_treated_as_chinese_source():
    """日文稿不能被当成「中文原稿」而跳过中文残留/翻译腔检查。"""
    from app.pipeline.overseas_check import _is_chinese
    ja = "彼は彼女を見た。その瞬間、心臓が止まった。"
    assert _is_chinese(ja) is True, "无 lang 时沿用旧启发式"
    assert _is_chinese(ja, "ja-JP") is False, "传了 lang 就必须按语种判"


def test_skeleton_pack_does_not_silently_pass_qc():
    """骨架包的 passive_pattern 显式为空 → R10 必须**跳过**,不能回落英语正则。

    回落的后果:英语正则跑在泰文上永远匹配不到 → R10 全过 → 用户以为质检通过,
    实际什么都没检(假绿)。
    """
    issues = check_translationese("some text here", {"passive_pattern": ""})
    assert issues == [], "未校准的语言不该跑英语翻译腔正则"


def test_run_checks_uses_patterns_list_for_any_language():
    """R1/R9 认语言无关的 `patterns` 列表,不再依赖 .en/.zh 硬编码 key。"""
    from app.pipeline.overseas_check import run_checks
    fr = "Son visage devint rouge, et il le regarda fixement."
    issues = run_checks(fr, platform={}, category={},
                        language={"id": "fr-FR",
                                  "self_observation_forbidden": {
                                      "patterns": [r"visage devint rouge"]},
                                  "hook_markers": {"patterns": ["le regarda"]}},
                        lang_id="fr-FR")
    assert any(i.rule == "R1" for i in issues), "法语 R1 正则没生效"


def test_run_checks_skips_r1_when_no_patterns_for_language():
    """语言包没给正则时宁可不报,也不拿英语正则去套非英语正文。"""
    from app.pipeline.overseas_check import run_checks
    issues = run_checks("Son visage devint rouge.", platform={}, category={},
                        language={"id": "fr-FR",
                                  "self_observation_forbidden": {"patterns": []}},
                        lang_id="fr-FR")
    assert not [i for i in issues if i.rule == "R1"], "无语言正则时不该报 R1"
