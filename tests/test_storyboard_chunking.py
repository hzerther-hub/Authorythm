# -*- coding: utf-8 -*-
"""分镜按场景分批的回归测试。

背景见 docs/分镜拆分失败-根因与修复交接.md 第十节:
整集一次调用要吐 50,787+ completion tokens,且波动极大 —— 同一条 prompt
换一次跑就顶满 65536 被 finish_reason=length 截断(128,980 字符全是半截 JSON)。
所以改成按场景分批,每批单次调用。
"""
import pathlib

from app.pipeline import storyboard as sb


SCRIPT = "".join(
    f"## S{i:02d} | 场景{i} | 清晨\n" + ("这是一段剧本内容。" * 30) + "\n"
    for i in range(1, 9)
)


def test_splits_into_multiple_batches_by_scene_header():
    batches = sb._script_batches(SCRIPT, limit=800)
    assert len(batches) > 1, "整集不能塞进一次调用"
    for _, part in batches:
        assert "## S" in part, "每批都必须带场景头,否则模型不知道是哪一场"


def test_no_text_is_lost_across_batches():
    batches = sb._script_batches(SCRIPT, limit=800)
    joined = "".join(part for _, part in batches)
    assert joined.strip() == SCRIPT.strip(), "切批只能切边界,不能丢/改剧本内容"


def test_a_single_long_scene_is_not_split_mid_scene():
    """单场超过上限时宁可整场给一次,也不要在场景中间切断(会拆出半个氛围)。"""
    script = "## S01 | 长场 | 夜\n" + ("字" * 5000)
    assert len(sb._script_batches(script, limit=1000)) == 1


def test_batch_label_reports_scene_range():
    assert sb._batch_label(["## S01 | a\n"]) == "第 01 场"
    assert sb._batch_label(["## S01 | a\n", "## S04 | b\n"]) == "第 01-04 场"


def test_tiny_trailing_scene_is_merged_into_neighbour():
    """一集末尾常有一场只有一两百字,单独一次调用不划算。"""
    script = ("## S01 | a | 清晨\n" + "字" * 1000 + "\n"
              + "## S02 | b | 清晨\n" + "短" * 50 + "\n")
    batches = sb._script_batches(script, limit=1400)
    assert len(batches) == 1, "短场应并进相邻批,而不是单独发一次调用"


def test_prompt_marks_batches_so_model_does_not_repeat_other_scenes():
    ep = {"episode_number": 1}
    p1 = sb._storyboard_prompt(ep, "9:16", "资产", "## S01 | a\n内容", "第 01 场", total=1)
    p2 = sb._storyboard_prompt(ep, "9:16", "资产", "## S01 | a\n内容", "第 01 场", total=3)
    assert "分批说明" not in p1, "单批不该出现分批指令"
    assert "第 01 场" in p2 and "镜号从 1 开始" in p2
    assert "number/title/content" in p2, "字段清单不能因为分批丢掉"


def test_storyboard_module_uses_chunked_batches():
    """守住实现:split_storyboards 必须走 _script_batches,不能再整集一次调用。"""
    src = pathlib.Path(sb.__file__).read_text(encoding="utf-8")
    body = src.split("def split_storyboards(", 1)[1]
    assert "_script_batches(script)" in body
    assert "on_progress" in body
