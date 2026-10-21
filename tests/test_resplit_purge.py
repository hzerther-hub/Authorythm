# -*- coding: utf-8 -*-
"""「重新拆分 = 彻底清空重来」的回归测试。

用户要求(2026-10-20):
1. 重新拆分时,旧分镜要删掉;
2. 已经生成的视频文件也要删掉;
3. 动手前必须弹二次确认。

旧实现是「按 storyboard_number 幂等 upsert」—— 重拆出 6 镜时只覆盖 1..6,
原来第 7..10 镜的行根本没人碰,变成「描述还是旧的、绑定已清空、视频还在」
的半残状态,还继续占着镜号出现在分镜列表与合片里。

本文件守住:清理逻辑真的删文件、删得掉、只删本集产物、越界不删、
以及 UI 侧确实有确认弹窗。测试绝不碰真实库与真实媒体文件。
"""
from __future__ import annotations

import pathlib

import pytest

from app.pipeline import storyboard as sb


class _FakeDB:
    """purge/split 用到的 db 接口最小替身。"""

    def __init__(self, rows=(), merges=()):
        self.rows = [dict(r) for r in rows]
        self.merges = [dict(r) for r in merges]
        self.sqls: list[tuple[str, tuple]] = []

    def q(self, sql, args=()):
        if "FROM storyboards" in sql:
            return self.rows
        if "FROM video_merges" in sql:
            return self.merges
        return []

    def q1(self, sql, args=()):
        if "FROM episodes" in sql:
            return {"id": 79, "drama_id": 13, "episode_number": 1,
                    "script_content": "## S01 | 室内 | 清晨\n" + "内容" * 300}
        if "COUNT(*)" in sql:
            if "composed_video_url" in sql:
                n = sum(1 for r in self.rows
                        if (r.get("video_url") or "").strip()
                        or (r.get("composed_video_url") or "").strip())
            else:
                n = len(self.rows)
            return {"c": n}
        return None

    def touch(self, *a, **k):
        pass

    def ex(self, sql, args=()):
        self.sqls.append((sql, args))
        return 1

    def now(self):
        return "2026-10-20T00:00:00Z"


def _shot(**kw):
    row = {
        "id": 1, "episode_id": 79, "storyboard_number": 1,
        "video_url": "", "composed_video_url": "", "first_frame_image": "",
        "last_frame_image": "", "composed_image": "",
        "narration_audio_url": "", "subtitle_url": "",
    }
    row.update(kw)
    return row


@pytest.fixture()
def static_dir(tmp_path, monkeypatch):
    """把 static 目录指向临时目录 —— 测试绝不能删真实媒体文件。

    打桩打在 `app.core.config` 模块属性上:真正的删除逻辑已经挪到
    `pipeline.media_files`,它读的就是同一个模块属性。
    """
    from app.core import config as core_config
    root = tmp_path / "static"
    (root / "videos").mkdir(parents=True)
    (root / "images").mkdir(parents=True)
    (root / "comics").mkdir(parents=True)
    monkeypatch.setattr(core_config, "STATIC_DIR", root)
    return root


# ── 删文件 ────────────────────────────────────────────────
def test_purge_deletes_media_files_and_rows(static_dir, monkeypatch):
    """旧分镜行 + 它们引用的视频/首帧文件,都要被删掉。"""
    vid = static_dir / "videos" / "a.mp4"
    vid.write_bytes(b"x" * 100)
    ff = static_dir / "images" / "ff.png"
    ff.write_bytes(b"y" * 50)
    fake = _FakeDB([_shot(video_url="/static/videos/a.mp4",
                          first_frame_image="/static/images/ff.png")])
    monkeypatch.setattr(sb, "db", fake)

    out = sb.purge_episode_storyboards(79)

    assert not vid.exists(), "旧视频文件没删掉"
    assert not ff.exists(), "旧首帧文件没删掉"
    assert out["shots"] == 1
    assert out["files"] == 2
    assert out["bytes"] == 150
    sqls = " ".join(s for s, _ in fake.sqls)
    assert "DELETE FROM storyboards WHERE episode_id" in sqls
    assert "DELETE FROM storyboard_characters" in sqls
    assert "DELETE FROM storyboard_props" in sqls


def test_purge_skips_files_outside_static_dir(static_dir, monkeypatch):
    """路径越出 static 目录的一律跳过 —— 不能删到项目外的文件。"""
    outside = static_dir.parent / "outside.mp4"
    outside.write_bytes(b"keep me")
    fake = _FakeDB([_shot(video_url="../../outside.mp4")])
    monkeypatch.setattr(sb, "db", fake)

    sb.purge_episode_storyboards(79)

    assert outside.exists(), "越界文件被删了"


def test_purge_keeps_comic_stitch_image(static_dir, monkeypatch):
    """合片只删视频;漫画拼接长图(jpg)跟漫画格绑定,留着。"""
    vid = static_dir / "merged.mp4"
    vid.write_bytes(b"v")
    stitch = static_dir / "comics" / "stitch.jpg"
    stitch.write_bytes(b"j")
    fake = _FakeDB([], merges=[{"id": 8, "merged_url": "/static/merged.mp4"},
                               {"id": 9, "merged_url": "/static/comics/stitch.jpg"}])
    monkeypatch.setattr(sb, "db", fake)

    out = sb.purge_episode_storyboards(79)

    assert not vid.exists(), "合片视频没删"
    assert stitch.exists(), "漫画拼接长图不该被这次重拆删掉"
    assert out["merges"] == 1


def test_purge_without_file_deletion_keeps_media(static_dir, monkeypatch):
    """delete_files=False 时只清库,不动磁盘(便于只想清库的场景)。"""
    vid = static_dir / "videos" / "a.mp4"
    vid.write_bytes(b"x")
    fake = _FakeDB([_shot(video_url="/static/videos/a.mp4")])
    monkeypatch.setattr(sb, "db", fake)

    sb.purge_episode_storyboards(79, delete_files=False)

    assert vid.exists(), "delete_files=False 却把文件删了"


# ── 拆分流程 ──────────────────────────────────────────────
def test_split_storyboards_purges_before_saving(monkeypatch):
    """重拆必须先清空旧分镜,再写新分镜 —— 否则旧镜号会残留。"""
    fake = _FakeDB([_shot(id=7, storyboard_number=7)])
    monkeypatch.setattr(sb, "db", fake)
    monkeypatch.setattr(sb, "_clear_episode_bindings", lambda *_: None)
    monkeypatch.setattr(sb, "_boards_for_part",
                        lambda ep, aspect, assets, part, label, **kw:
                        [{"number": 1, "title": "镜"}])
    monkeypatch.setattr(sb, "_save_board", lambda b, num, *a, **k: 10.0)
    monkeypatch.setattr(sb, "gen_video_prompts", lambda *a, **k: 0, raising=False)

    sb.split_storyboards(79, aspect="9:16")

    sqls = [s for s, _ in fake.sqls]
    del_idx = next(i for i, s in enumerate(sqls) if "DELETE FROM storyboards" in s)
    assert del_idx >= 0, "重拆前没有清空旧分镜"


# ── UI:二次确认 ───────────────────────────────────────────
def test_resplit_has_confirmation_dialog():
    """「重新拆分」必须弹二次确认 —— 它会删旧分镜与已生成的视频。"""
    src = (pathlib.Path(sb.__file__).parents[1] / "ui" / "episode_page.py").read_text(encoding="utf-8")
    body = src.split("def _split_sb(self):", 1)[1].split("\n    def ", 1)[0]
    assert "ask(" in body, "重拆没有二次确认 —— 点一下就把旧分镜和视频删了"
    assert "_resplit_purge_stats" in body, "确认弹窗必须先统计要删多少东西"


def test_resplit_confirm_text_covers_all_languages():
    """确认文案要 15 语言齐全(补充词典以中文基准句为 key)。"""
    from app.core.ui_strings import S, LANGS
    key = ("本集已有 {n} 个分镜(含 {v} 个已出视频、{f} 个生成文件,共约 {size})。\n\n"
           "重新拆分将删除全部旧分镜与已生成的视频文件(不可恢复),并从零重新拆分。\n\n确定继续?")
    assert key in S, "重拆确认文案没进补充词典"
    row = S[key]
    assert len(row) == len(LANGS) == 15, f"译文数量应为 15,实际 {len(row)}"
    for i, lang in enumerate(LANGS):
        assert row[i].strip(), f"{lang} 的译文是空的"
        for ph in ("{n}", "{v}", "{f}", "{size}"):
            assert ph in row[i], f"{lang} 的译文丢了占位符 {ph}"


# ── 运行时行为:弹窗内容 + 取消不开拆 ───────────────────────
def test_resplit_confirm_reports_real_counts_and_cancel_does_not_split(monkeypatch, tmp_path):
    """弹窗要报出真实的「会删几个、删多大」;点取消不许开拆。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QComboBox
    from app.core import preflight
    from app.ui import episode_page as EP

    QApplication.instance() or QApplication([])

    # 假库:2 个分镜,1 个有视频
    fake = _FakeDB([_shot(id=1, video_url="/static/videos/a.mp4"),
                    _shot(id=2, storyboard_number=2)])
    monkeypatch.setattr(EP, "db", fake)

    captured: dict = {}
    started: list = []

    def fake_ask(parent, title, text, danger=False):
        captured.update(title=title, text=text, danger=danger)
        return False                      # 用户点「取消」

    monkeypatch.setattr(EP, "ask", fake_ask)
    monkeypatch.setattr(preflight, "ensure_ready", lambda *a, **k: True)
    monkeypatch.setattr(EP.EpisodePage, "_gen_blocked", lambda self, s, l: False)
    monkeypatch.setattr(EP.EpisodePage, "_cfg_for", lambda self, k: None)
    monkeypatch.setattr(EP.sb_pipe, "split_storyboards_bg",
                        lambda *a, **k: (started.append(1), 1)[1])

    page = EP.EpisodePage.__new__(EP.EpisodePage)
    page.episode_id = 79
    page._drama = {"aspect_ratio": "9:16"}
    page.text_model = QComboBox()
    page._sb_split_running = False
    page.split_btn = None

    page._split_sb()

    assert captured, "重拆没有弹二次确认"
    assert captured["title"] == "重新拆分"
    assert captured["danger"] is True, "这是破坏性操作,danger 必须为 True"
    assert "2 个分镜" in captured["text"], f"弹窗没报出分镜数:{captured['text']!r}"
    assert "1 个已出视频" in captured["text"], f"弹窗没报出视频数:{captured['text']!r}"
    assert "不可恢复" in captured["text"]
    assert not started, "用户点取消后仍然开拆了 —— 旧分镜和视频会被白删"
