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


def test_failed_chunk_is_split_into_scenes_and_retried(monkeypatch):
    """整批拿不到 JSON 时按场景对半拆开重试,不能让整集失败。"""
    calls = []

    def fake(agent_type, prompt, **kw):
        calls.append(prompt)
        if "## S01" in prompt and "## S02" in prompt:   # 两场一起给就失败
            raise RuntimeError("storyboard_breaker 输出无法解析为 JSON:<think>...")
        return {"storyboards": [{"number": 1, "title": "镜"}]}

    monkeypatch.setattr(sb.runner, "run_agent_json", fake)
    part = "## S01 | a | 清晨\n内容A\n## S02 | b | 夜\n内容B\n"
    got = sb._boards_for_part({"episode_number": 1}, "9:16", "资产", part, "第 01-02 场",
                              lang="zh", config_id=None)
    assert len(got) == 2, "拆开后两场都应拿到分镜"
    assert len(calls) == 3, "先整批一次 + 拆开各一次"
    assert "## S01" in calls[1] and "## S02" not in calls[1]


def test_split_prompt_defers_video_prompt_to_second_stage():
    """拆分阶段不许再要 video_prompt —— 它是单镜输出翻倍、把预算吐满的主因。"""
    p = sb._storyboard_prompt({"episode_number": 1}, "9:16", "资产", "## S01 | a\n内容")
    assert "本步不生成" in p
    assert "/video_prompt" not in p, "字段清单里不能再出现 video_prompt"
    assert "number/title/content" in p and "/duration" in p


class _FakeDB:
    """split_storyboards 用到的 db 接口最小替身(测试绝不碰真实库)。"""

    def __init__(self, ep):
        self.ep = ep
        self.updates = []

    def q1(self, sql, args=()):
        if "FROM episodes WHERE id" in sql:
            return self.ep
        return None

    def q(self, sql, args=()):
        return []

    def ex(self, sql, args=()):
        self.updates.append((sql, args))
        return 1

    def touch(self, *a, **k):
        pass

    def now(self):
        return "2026-10-18T00:00:00Z"


def test_failed_batch_keeps_other_batches(monkeypatch):
    """一批失败不能把已成功的批次一起丢掉 —— 已生成的必须留在库里。"""
    script = "## S01 | a | 清晨\n" + "字" * 500 + "\n## S02 | b | 夜\n" + "字" * 500
    fake = _FakeDB({"id": 2, "drama_id": 1, "episode_number": 1, "script_content": script})
    monkeypatch.setattr(sb, "db", fake)
    monkeypatch.setattr(sb, "_clear_episode_bindings", lambda *_: None)

    saved = []

    def fake_save(b, num, *a, **k):
        saved.append(num)
        return 10.0

    monkeypatch.setattr(sb, "_save_board", fake_save)

    def fake_part(ep, aspect, assets, part, label, **kw):
        if "## S02" in part:
            raise RuntimeError("模拟第 2 批失败")
        return [{"number": 1, "title": "镜"}]

    monkeypatch.setattr(sb, "_boards_for_part", fake_part)
    failures = []
    n = sb.split_storyboards(2, on_chunk_failed=lambda lbl, reason: failures.append(lbl))
    assert n == 1, "第 1 批的镜头必须落库"
    assert saved == [1]
    assert failures == ["第 02 场"], "失败批次要能点名,方便只补那几场"


def test_split_job_runs_video_prompt_stage():
    """拆分任务必须串上第二阶段的逐镜补写,否则 video_prompt 会一直是空。"""
    src = pathlib.Path(sb.__file__).read_text(encoding="utf-8")
    body = src.split("def split_storyboards_bg(", 1)[1]
    assert "gen_video_prompts(" in body
    assert "video_prompts" in body, "应把阶段名写进任务面板"


def test_storyboard_module_uses_chunked_batches():
    """守住实现:split_storyboards 必须走 _script_batches,不能再整集一次调用。"""
    src = pathlib.Path(sb.__file__).read_text(encoding="utf-8")
    body = src.split("def split_storyboards(", 1)[1]
    assert "_script_batches(script)" in body
    assert "on_progress" in body
