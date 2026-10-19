# -*- coding: utf-8 -*-
"""角色外观规格的软件层护栏。

对应实测问题:drama 13 的 13 个角色 appearance 全在 45~68 字,而规格要求 >=150。
根因不是模型不会写,而是(a)15 份语言提示词里只有 2 份写了规格,(b)落库前
没有任何代码校验,(c)小说/导入/手工三条链路根本不走 extractor 的提示词。
本测试锁住:规格可被确定性校验、补写失败不阻断主流程、四条链路都接上了。
"""
from __future__ import annotations

import inspect

import pytest

from app.pipeline import character_spec as cs

# 用户实际报的那条(68 字,逗号串,无句号)
REAL_SHORT = ("33岁前呈现25岁面容，鹅蛋脸，眉眼锐利带倦意，黑直发常束低马尾，"
              "皮肤因熬夜偏黄，肩颈单薄却坐姿笔直，眼底常藏审视感，微笑时像一把折叠刀")

LONG_OK_APPEARANCE = (
    "她视觉年龄约二十五岁，实际三十三岁。鹅蛋脸轮廓清瘦而利落，下颌线收得干净。"
    "眉骨细长上扬，眉尾略淡；眼窝微深，上眼睑略压，内眼角偏锐，瞳仁定视时眼白露出少。"
    "鼻梁直而窄，鼻头小巧；唇形偏薄，唇峰清晰，嘴角自然平直，惯常只单侧微微上提，"
    "眼轮匝肌不收缩，笑意不达眼底。肤色偏黄，眼下有轻度青色疲态，颧骨处有一粒浅痣。"
    "黑直发浓密垂顺，长度过肩，常束低马尾，发质偏硬，额前有几缕碎发自然垂落。"
    "身高中等偏高，体型偏瘦但不单薄，肩颈单薄，长年伏案后仍保持笔直的坐姿，"
    "说话时下颌微收，目光停留时间比常人略长。")
LONG_OK_STYLING = (
    "上身穿一件洗得发软的白色棉质衬衫，领口第一颗扣子解开，袖口挽到小臂中段，"
    "肘弯处有细密褶痕；下身黑色西装直筒裤，腰线偏高，裤脚刚好盖住鞋面。"
    "脚穿黑色低跟皮质单鞋，鞋头有轻微磨损。右手腕常年戴一只旧式银镯，"
    "表面被磨出柔润的哑光，是母亲留下的旧物。")


def test_real_short_sample_is_flagged():
    issues = cs.audit(REAL_SHORT, "前期城中村阶段穿廉价白衬衫配黑色西装裤")
    assert issues, "68 字的逗号串必须被判定为不达标"
    assert any("appearance" in x for x in issues)
    assert any("关键词串" in x for x in issues)


def test_compliant_sample_passes():
    assert cs.audit(LONG_OK_APPEARANCE, LONG_OK_STYLING) == []


def test_keyword_chain_heuristic_does_not_flag_prose():
    # 有句末标点、分句够长的正常散文不能被误判
    prose = ("她的眉眼很淡。眼睛细长，眼尾微微下垂，看人时先抬下巴再抬眼。"
             "嘴唇偏薄，笑起来几乎看不见牙齿。")
    assert not cs._looks_like_keyword_chain(prose)


def test_rules_available_for_every_ui_language():
    from app.core.i18n import LANGS
    for code, _label in LANGS:
        rules = cs.rules_for(code)
        assert "150" in rules, f"{code} 的规格块缺 150 字硬要求"
        assert "styling" in rules.lower()


def _fake_chars():
    return [
        {"name": "短角色", "appearance": "瘦高，戴眼镜", "styling": "白衬衫"},
        {"name": "已达标", "appearance": LONG_OK_APPEARANCE, "styling": LONG_OK_STYLING},
    ]


def test_expand_many_is_zero_cost_when_all_compliant(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("全部达标时不应调用模型")
    monkeypatch.setattr(cs.runner, "run_agent_json", boom)
    out = cs.expand_many([{"name": "x", "appearance": LONG_OK_APPEARANCE,
                           "styling": LONG_OK_STYLING}])
    assert out[0]["appearance"] == LONG_OK_APPEARANCE


def test_expand_many_only_repairs_deficient_and_merges(monkeypatch):
    seen = {}

    def fake(agent, user, **k):
        seen["user"] = user
        return {"characters": [{"name": "短角色",
                                "appearance": LONG_OK_APPEARANCE,
                                "styling": LONG_OK_STYLING}]}

    monkeypatch.setattr(cs.runner, "run_agent_json", fake)
    out = cs.expand_many(_fake_chars(), lang="zh")

    assert "短角色" in seen["user"]
    assert "已达标" not in seen["user"], "只应把不达标的角色送进补写,别浪费 token"
    by_name = {c["name"]: c for c in out}
    assert by_name["短角色"]["appearance"] == LONG_OK_APPEARANCE
    assert by_name["短角色"]["styling"] == LONG_OK_STYLING
    assert by_name["已达标"]["appearance"] == LONG_OK_APPEARANCE


def test_expand_many_never_raises_on_llm_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("服务超时")

    monkeypatch.setattr(cs.runner, "run_agent_json", boom)
    out = cs.expand_many(_fake_chars(), lang="zh")
    assert out[0]["appearance"] == "瘦高，戴眼镜", "失败必须原样返回,不能阻断提取"


def test_expand_many_rejects_shorter_model_output(monkeypatch):
    def fake(*a, **k):
        return {"characters": [{"name": "短角色", "appearance": "矮", "styling": ""}]}

    monkeypatch.setattr(cs.runner, "run_agent_json", fake)
    out = cs.expand_many(_fake_chars(), lang="zh")
    assert out[0]["appearance"] == "瘦高，戴眼镜", "模型越改越短时要保留原值"


def test_ensure_for_prompt_degrades_to_original_on_failure(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("未配置文本模型")

    monkeypatch.setattr(cs.runner, "run_agent_json", boom)
    ap, st = cs.ensure_for_prompt(
        {"id": 1, "drama_id": 1, "name": "x",
         "appearance": REAL_SHORT, "styling": "白衬衫"})
    assert ap == REAL_SHORT and st == "白衬衫"


#  四条写库链路必须都接上软件层规格(漏一条就是又一处 45 字入口)

@pytest.mark.parametrize("module_name,func_name", [
    ("app.pipeline.extractor", "extract_assets"),
    ("app.pipeline.novel", "plan_characters"),
    ("app.pipeline.prompts_gen", "character_prompt"),
    ("app.pipeline.book_import", "run_imitation"),
])
def test_all_character_write_paths_are_wired(module_name, func_name):
    import importlib
    mod = importlib.import_module(module_name)
    fn = getattr(mod, func_name, None)
    if fn is None:
        pytest.skip(f"{module_name}.{func_name} 尚不存在")
    src = inspect.getsource(fn)
    assert "character_spec" in src, (
        f"{module_name}.{func_name} 没有接 character_spec  这条链路的角色外观会绕过校验")
