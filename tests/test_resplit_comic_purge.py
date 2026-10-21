# -*- coding: utf-8 -*-
"""「漫画重拆 = 彻底清空重来 + 二次确认」的回归测试。

用户要求(2026-10-20):漫画的重拆要和视频一样 —— 重拆就删掉以前的,
已生成的格子图也要删掉,并且动手前必须弹二次确认。

分镜那边已经这么做了(`pipeline.storyboard.purge_episode_storyboards`),
漫画这边原先只有一句 `DELETE FROM comic_panels`,于是:
  - 旧格子图留在磁盘上变成孤儿(和 videos/ 里那批历史孤儿同一个病);
  - 整话拼接长图还挂着 —— 那是**旧格**拼出来的,留着就是错的;
  - 绑定子表(comic_panel_characters/scenes/props)的行没人清,变成孤儿;
  - 没有二次确认,点一下就把旧素材清空。

本文件守住:清理真的删文件/删行、只删本集产物、越界不删、
拆格失败不误删旧格、以及 UI 侧确实有确认弹窗且报出真实数字。
测试绝不碰真实库与真实媒体文件。
"""
from __future__ import annotations

import pathlib

import pytest

from app.pipeline import comic as cm


class _FakeDB:
    """漫画 purge/split 用到的 db 接口最小替身。"""

    def __init__(self, panels=(), stitches=(), episode=None):
        self.panels = [dict(r) for r in panels]
        self.stitches = [dict(r) for r in stitches]
        self.episode = episode
        self.sqls: list[tuple[str, tuple]] = []

    def q(self, sql, args=()):
        if "FROM comic_panels" in sql:
            return self.panels
        if "FROM video_merges" in sql:
            return self.stitches
        return []                       # characters / scenes / props 都查不到

    def q1(self, sql, args=()):
        if "FROM episodes" in sql:
            return self.episode
        if "FROM video_merges" in sql:
            return self.stitches[-1] if self.stitches else None
        return None

    def ex(self, sql, args=()):
        self.sqls.append((sql, args))
        return 1

    def touch(self, *a, **k):
        pass

    def now(self):
        return "2026-10-20T00:00:00Z"


def _panel(**kw):
    row = {"id": 1, "episode_id": 79, "panel_number": 1, "image_url": ""}
    row.update(kw)
    return row


@pytest.fixture()
def static_dir(tmp_path, monkeypatch):
    """把 static 目录指向临时目录 —— 测试绝不能删真实媒体文件。"""
    root = tmp_path / "static"
    for sub in ("images", "videos", "comics"):
        (root / sub).mkdir(parents=True)
    monkeypatch.setattr(cm.config, "STATIC_DIR", root)
    return root


# ── 删文件 / 删行 ──────────────────────────────────────────
def test_purge_deletes_panel_images_and_rows(static_dir, monkeypatch):
    """旧漫画格行 + 它们引用的格子图,都要被删掉。"""
    img = static_dir / "images" / "p1.png"
    img.write_bytes(b"x" * 120)
    fake = _FakeDB([_panel(image_url="/static/images/p1.png")])
    monkeypatch.setattr(cm, "db", fake)

    out = cm.purge_episode_comic_panels(79)

    assert not img.exists(), "旧漫画格图片没删掉"
    assert out["panels"] == 1
    assert out["files"] == 1
    assert out["bytes"] == 120
    sqls = " ".join(s for s, _ in fake.sqls)
    assert "DELETE FROM comic_panels WHERE episode_id" in sqls
    assert "DELETE FROM comic_panel_characters" in sqls
    assert "DELETE FROM comic_panel_scenes" in sqls
    assert "DELETE FROM comic_panel_props" in sqls


def test_purge_deletes_stitch_long_image(static_dir, monkeypatch):
    """整话长图是旧格拼出来的,重拆必须一起删(否则界面上还挂着旧长图)。"""
    stitch = static_dir / "comics" / "stitch_ab12.jpg"
    stitch.write_bytes(b"j" * 50)
    fake = _FakeDB([], stitches=[{"id": 9, "merged_url": "/static/comics/stitch_ab12.jpg"}])
    monkeypatch.setattr(cm, "db", fake)

    out = cm.purge_episode_comic_panels(79)

    assert not stitch.exists(), "整话长图没删"
    assert out["stitch"] == 1
    sqls = " ".join(s for s, _ in fake.sqls)
    assert "DELETE FROM video_merges WHERE id" in sqls


def test_purge_skips_files_outside_static_dir(static_dir, monkeypatch):
    """路径越出 static 目录的一律跳过 —— 不能删到项目外的文件。"""
    outside = static_dir.parent / "outside.png"
    outside.write_bytes(b"keep me")
    fake = _FakeDB([_panel(image_url="../../outside.png")])
    monkeypatch.setattr(cm, "db", fake)

    cm.purge_episode_comic_panels(79)

    assert outside.exists(), "越界文件被删了"


def test_purge_without_file_deletion_keeps_media(static_dir, monkeypatch):
    """delete_files=False 时只清库,不动磁盘。"""
    img = static_dir / "images" / "p1.png"
    img.write_bytes(b"x")
    fake = _FakeDB([_panel(image_url="/static/images/p1.png")])
    monkeypatch.setattr(cm, "db", fake)

    cm.purge_episode_comic_panels(79, delete_files=False)

    assert img.exists(), "delete_files=False 却把文件删了"


def test_purge_only_touches_this_episode(static_dir, monkeypatch):
    """别的集的漫画格不能被牵连 —— 清理范围只限本集。"""
    mine = static_dir / "images" / "mine.png"
    other = static_dir / "images" / "other.png"
    mine.write_bytes(b"m")
    other.write_bytes(b"o")
    fake = _FakeDB([_panel(id=1, image_url="/static/images/mine.png")])
    monkeypatch.setattr(cm, "db", fake)

    cm.purge_episode_comic_panels(79)

    assert not mine.exists()
    assert other.exists(), "别人的漫画格文件被删了"
    for sql, args in fake.sqls:
        if "DELETE FROM comic_panels" in sql:
            assert args == (79,), "删除语句没带 episode_id 参数"


# ── 拆分流程 ──────────────────────────────────────────────
def _episode():
    return {"id": 79, "drama_id": 13, "episode_number": 1,
            "script_content": "## S01 | 室内 | 清晨\n" + "内容" * 200}


def test_split_panels_purges_old_panels(static_dir, monkeypatch):
    """重拆必须把旧漫画格清掉再写新的 —— 否则旧图会跟新描述错配。"""
    old_img = static_dir / "images" / "old.png"
    old_img.write_bytes(b"o")
    fake = _FakeDB([_panel(id=1, image_url="/static/images/old.png")],
                   episode=_episode())
    monkeypatch.setattr(cm, "db", fake)
    monkeypatch.setattr(cm.runner, "run_agent_json",
                        lambda *a, **k: {"panels": [{"number": 1, "description": "新格"}]})

    cm.split_panels(79)

    assert not old_img.exists(), "重拆后旧漫画格图片还在"
    sqls = [s for s, _ in fake.sqls]
    del_idx = next(i for i, s in enumerate(sqls) if "DELETE FROM comic_panels" in s)
    ins_idx = next(i for i, s in enumerate(sqls) if "INSERT INTO comic_panels" in s)
    assert del_idx < ins_idx, "必须先清旧格再写新格"


def test_split_panels_keeps_old_panels_when_llm_fails(static_dir, monkeypatch):
    """拆格失败时旧格子要原样留着 —— 不能两头空。"""
    img = static_dir / "images" / "old.png"
    img.write_bytes(b"o")
    fake = _FakeDB([_panel(id=1, image_url="/static/images/old.png")],
                   episode=_episode())
    monkeypatch.setattr(cm, "db", fake)

    def boom(*a, **k):
        raise RuntimeError("模型超时")

    monkeypatch.setattr(cm.runner, "run_agent_json", boom)

    with pytest.raises(RuntimeError):
        cm.split_panels(79)

    assert img.exists(), "拆格失败却把旧素材删了"
    sqls = " ".join(s for s, _ in fake.sqls)
    assert "DELETE FROM comic_panels" not in sqls


def test_split_panels_reports_purge_stats(static_dir, monkeypatch):
    """on_purged 回调要把清理统计交给调用方(UI 要如实报给用户)。"""
    img = static_dir / "images" / "old.png"
    img.write_bytes(b"o")
    fake = _FakeDB([_panel(id=1, image_url="/static/images/old.png")],
                   episode=_episode())
    monkeypatch.setattr(cm, "db", fake)
    monkeypatch.setattr(cm.runner, "run_agent_json",
                        lambda *a, **k: {"panels": [{"number": 1}]})
    seen: dict = {}

    cm.split_panels(79, on_purged=lambda st: seen.update(st))

    assert seen.get("panels") == 1
    assert seen.get("files") == 1


# ── UI:二次确认 ───────────────────────────────────────────
def test_comic_resplit_has_confirmation_dialog():
    """「生成分镜(漫画)」必须弹二次确认 —— 它会删旧格与已生成的图。"""
    src = (pathlib.Path(cm.__file__).parents[1] / "ui" / "episode_page.py").read_text(encoding="utf-8")
    body = src.split("def _split_panels(self):", 1)[1].split("\n    def ", 1)[0]
    assert "ask(" in body, "漫画重拆没有二次确认 —— 点一下就把旧格和图删了"
    assert "_comic_resplit_purge_stats" in body, "确认弹窗必须先统计要删多少东西"


def test_comic_resplit_confirm_text_covers_all_languages():
    """确认文案要 15 语言齐全(补充词典以中文基准句为 key)。"""
    from app.core.ui_strings import S, LANGS
    key = ("本集已有 {n} 个漫画格(含 {v} 个已出图、{f} 个生成文件,共约 {size})。\n\n"
           "重新拆分会删除全部旧漫画格、已生成的格子图片与整话长图(不可恢复),"
           "并从零重新拆分。\n\n确定继续?")
    assert key in S, "漫画重拆确认文案没进补充词典"
    row = S[key]
    assert len(row) == len(LANGS) == 15, f"译文数量应为 15,实际 {len(row)}"
    for i, lang in enumerate(LANGS):
        assert row[i].strip(), f"{lang} 的译文是空的"
        for ph in ("{n}", "{v}", "{f}", "{size}"):
            assert ph in row[i], f"{lang} 的译文丢了占位符 {ph}"
    # 标题也要有 15 语言
    title = "重新拆分漫画格"
    assert title in S, "漫画重拆确认标题没进补充词典"
    assert len(S[title]) == len(LANGS) == 15
    for i, lang in enumerate(LANGS):
        assert S[title][i].strip(), f"{lang} 的标题译文是空的"


# ── 运行时行为:弹窗内容 + 取消不开拆 ───────────────────────
def test_comic_resplit_confirm_reports_real_counts_and_cancel_does_not_split(
        monkeypatch, tmp_path):
    """弹窗要报出真实的「会删几个、删多大」;点取消不许开拆。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.ui import episode_page as EP

    QApplication.instance() or QApplication([])

    root = tmp_path / "static"
    (root / "images").mkdir(parents=True)
    (root / "comics").mkdir(parents=True)
    (root / "images" / "a.png").write_bytes(b"a" * 1024)
    (root / "comics" / "stitch.jpg").write_bytes(b"s" * 1024)
    monkeypatch.setattr(EP.config, "STATIC_DIR", root)

    # 假库:2 个漫画格,1 个已出图,另有整话长图
    fake = _FakeDB([_panel(id=1, image_url="/static/images/a.png"),
                    _panel(id=2, panel_number=2)],
                   stitches=[{"id": 9, "merged_url": "/static/comics/stitch.jpg"}])
    monkeypatch.setattr(EP, "db", fake)

    captured: dict = {}
    started: list = []

    def fake_ask(parent, title, text, danger=False):
        captured.update(title=title, text=text, danger=danger)
        return False                      # 用户点「取消」

    monkeypatch.setattr(EP, "ask", fake_ask)
    monkeypatch.setattr(EP.comic_pipe, "split_panels",
                        lambda *a, **k: (started.append(1), 1)[1])

    page = EP.EpisodePage.__new__(EP.EpisodePage)
    page.episode_id = 79

    page._split_panels()

    assert captured, "漫画重拆没有弹二次确认"
    assert captured["danger"] is True, "这是破坏性操作,danger 必须为 True"
    assert "2 个漫画格" in captured["text"], f"弹窗没报出格数:{captured['text']!r}"
    assert "1 个已出图" in captured["text"], f"弹窗没报出已出图数:{captured['text']!r}"
    assert "不可恢复" in captured["text"]
    assert not started, "用户点取消后仍然开拆了 —— 旧格和图会被白删"


def test_comic_resplit_stats_counts_stitch_in_files(monkeypatch, tmp_path):
    """整话长图也要算进「会删几个文件」—— 它同样是旧格拼出来的。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from app.ui import episode_page as EP

    QApplication.instance() or QApplication([])

    root = tmp_path / "static"
    (root / "images").mkdir(parents=True)
    (root / "comics").mkdir(parents=True)
    (root / "images" / "a.png").write_bytes(b"a" * 2048)
    (root / "comics" / "stitch.jpg").write_bytes(b"s" * 2048)
    monkeypatch.setattr(EP.config, "STATIC_DIR", root)

    fake = _FakeDB([_panel(id=1, image_url="/static/images/a.png")],
                   stitches=[{"id": 9, "merged_url": "/static/comics/stitch.jpg"}])
    monkeypatch.setattr(EP, "db", fake)

    page = EP.EpisodePage.__new__(EP.EpisodePage)
    page.episode_id = 79
    st = page._comic_resplit_purge_stats()

    assert st["n"] == 1
    assert st["v"] == 1
    assert st["f"] == 2, "整话长图没算进文件数"
    assert st["size"] == "0.0 MB"
