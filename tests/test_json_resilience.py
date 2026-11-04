"""JSON 解析韧性回归:模型输出畸形时的四层降级(对齐上游 novel.ts 的 parseJsonLoose)。

上游在 novel.ts 里给 `askBookJson` 配了一套容错解析,动机写得很直白:
推理型模型(MiniMax-M3 / DeepSeek-V4 等)即使被要求「只输出 JSON」,也可能在 JSON
前后夹带 <think> 块或说明文字,或者把 JSON 字符串里的换行写成裸换行,或者干脆
被 max_tokens 掐断 —— 旧的「首 { 到尾 }」粗截会把垃圾一起切进来,
JSON.parse 报 "Unexpected non-whitespace character after JSON"。

桌面版此前只有一个 extract_json(围栏 / 整体 / 首尾截取 / 去尾逗号),
遇到上面几种畸形一律返回 None —— 表现就是「模型明明回了东西,界面却说没有」。
本文件锁住移植进来的四层降级,并锁住**零回归**:今天能解析的输出,
解析结果与改前逐字节一致(新层只在老候选全败后才启用)。
"""
from __future__ import annotations

from app.agents import runner


def test_plain_json_still_parses():
    """基线:普通 JSON 与围栏 JSON 照旧解析(改前就能过的,改后必须还过)。"""
    assert runner.extract_json('{"a": 1}') == {"a": 1}
    assert runner.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert runner.extract_json('```\n{"a": 1}\n```') == {"a": 1}
    assert runner.extract_json('[1, 2]') == [1, 2]


def test_think_block_stripped_before_parsing():
    """<think> 推理块必须先剥 —— 推理型模型(glm-5.3 / MiniMax-M3)必坑。"""
    raw = "<think>让我想想 {这里不是 JSON}</think>\n{\"ok\": true}"
    assert runner.extract_json(raw) == {"ok": True}


def test_trailing_comma_fixed():
    """尾逗号 {"a": 1,} —— 改前就支持,必须保持。"""
    assert runner.extract_json('{"a": 1,}') == {"a": 1}


def test_bare_newline_inside_string_repaired():
    """L1/L2:JSON 字符串里的**裸换行**修成 \\n。

    模型写中文长句时经常在 JSON 字符串里直接换行,JSON.parse 直接报
    "Unterminated string in JSON" —— 补 \\n 就好,补引号救不了。
    """
    raw = '{"outline": "第一行\n第二行\n第三行"}'
    out = runner.extract_json(raw)
    assert out == {"outline": "第一行\n第二行\n第三行"}


def test_truncated_json_salvaged_when_opted_in():
    """L3:输出被 max_tokens 掐断时补齐未闭合的引号与括号栈,捞回大半内容。

    长输出(总纲 1500-3000 字、分卷战略)被截断是常态 —— 补齐后能救回正文,
    而不是整段作废。**必须显式 salvage=True**:见下面那条默认关闭的测试。
    """
    raw = '{"outline": "很长的总纲正文被掐断了'
    out = runner.extract_json(raw, salvage=True)
    assert isinstance(out, dict)
    assert str(out["outline"]).startswith("很长的总纲正文被掐断了")


def test_truncated_json_not_salvaged_by_default():
    """截断挽救默认**关闭** —— 预算阶梯靠「解析失败」判断输出被截断。

    截断的输出必须解析失败,阶梯才会往上爬 max_tokens;若默认抢救成「半个对象」
    并当成成功,阶梯就永远停在起始档(实测 test_agent_budget 的阶梯断言就是这么红的)。
    """
    raw = '{"outline": "很长的总纲正文被掐断了'
    assert runner.extract_json(raw) is None


def test_multiple_objects_with_prose_picks_largest():
    """L1:输出夹带说明文字且有多个 JSON 对象时,取**最大的**可解析载荷。

    真载荷通常最大;前面的小对象常是模型的自我说明。
    """
    raw = '{"note": "思考"} garbage {"title": "新书名", "genre": "玄幻"}'
    out = runner.extract_json(raw)
    assert out == {"title": "新书名", "genre": "玄幻"}


def test_field_fallback_when_json_unparseable():
    """L4:JSON 彻底解析不出来时按 "key": "value" 逐字段抠 —— 宁可给残缺结果。"""
    raw = '模型说了一堆话\ndescription: "一本书的简介"\ngenre: 仙侠'
    out = runner.extract_json(raw, fields=["description", "genre"])
    assert isinstance(out, dict)
    assert out["description"] == "一本书的简介"
    assert out["genre"] == "仙侠"


def test_field_fallback_without_fields_returns_none():
    """没给 fields 就不做兜底 —— 保持「解析不出就是解析不出」的诚实语义。"""
    raw = '模型说了一堆话\ndescription: "一本书的简介"'
    assert runner.extract_json(raw) is None


def test_curly_quotes_inside_string_not_mangled():
    """修复**刻意不碰**中文弯引号 “ ”。

    正文里 “……” 是正常内容(她说“我不同意”),批量换成 ASCII 双引号会把
    字符串提前闭合,反而制造新的解析错误。
    """
    raw = '{"line": "她说“我不同意”,然后走了"}'
    out = runner.extract_json(raw)
    assert out == {"line": "她说“我不同意”,然后走了"}


def test_zero_regression_on_previously_working_inputs():
    """零回归:老实现能解析出来的,新实现结果必须完全一致。

    老候选顺序(围栏 → 整体 → 首{到尾} → 首[到尾] → 去尾逗号)原样保留,
    新层只在这些全败之后才启用。
    """
    cases = [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '前言说明\n{"a": 1}\n后记说明',
        '{"a": {"b": [1, 2]}}',
        '[{"a": 1}, {"b": 2}]',
        '{"a": 1,}',
        '{"text": "含 } 的字符串"}',
    ]
    for raw in cases:
        assert runner.extract_json(raw) is not None, raw


def test_empty_and_none_inputs():
    assert runner.extract_json("") is None
    assert runner.extract_json("   ") is None
