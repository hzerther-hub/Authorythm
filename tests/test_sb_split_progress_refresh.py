# -*- coding: utf-8 -*-
"""分镜拆分进行中的界面增量刷新回归。

bug 背景:分批拆分(`pipeline/storyboard.split_storyboards`)**逐批落库** ——
每批成功即写进 storyboards,失败批次只影响自己。但 UI 的轮询
`episode_page._poll_sb_split` 在 `status == "processing"` 时直接 return,
只在任务 completed 后才 `_reload_storyboard()`。

于是任务跑的那十几分钟里,库里已经躺着二十几条分镜,界面却一直显示
「0 段落」和「开始拆分分镜」的空状态 —— 用户看到的就是「一直进行中、没有结果」。
本仓在批量生图上早就踩过同一个坑并改成逐项刷新(见 AGENTS.md「开发习惯」),
分批拆分这条新链路需要同样的处理。

**测试不许碰真实库**:`db.q1` 被打桩成假的计数查询。
"""
from __future__ import annotations

import inspect

from app.ui import episode_page as ep


class _Fake:
    """只带 _refresh_sb_split_progress 用到的属性的最小替身。"""

    def __init__(self, episode_id: int = 83, seen: int = 0):
        self.episode_id = episode_id
        self._sb_split_seen = seen
        self.reloads = 0

    def _reload_storyboard(self):
        self.reloads += 1


def _stub_count(monkeypatch, counts):
    """让 db.q1 依次返回 counts 里的计数(模拟逐批落库)。"""
    it = iter(counts)

    def fake_q1(sql, args=()):
        class _R(dict):
            def __getitem__(self, k):
                return dict.__getitem__(self, k)

        return _R(c=next(it))

    monkeypatch.setattr(ep.db, "q1", fake_q1)


def test_refresh_reloads_when_batches_land(monkeypatch):
    """分镜数变了就重建列表 —— 第一批落库后用户就该看见东西。"""
    _stub_count(monkeypatch, [7])
    fake = _Fake(seen=0)
    ep.EpisodePage._refresh_sb_split_progress(fake)
    assert fake.reloads == 1
    assert fake._sb_split_seen == 7


def test_refresh_skips_when_nothing_changed(monkeypatch):
    """数没变就不刷 —— 否则每 6 秒重建一次整张列表,纯属浪费。"""
    _stub_count(monkeypatch, [7])
    fake = _Fake(seen=7)
    ep.EpisodePage._refresh_sb_split_progress(fake)
    assert fake.reloads == 0


def test_refresh_survives_db_failure(monkeypatch):
    """轮询里的读库失败不能打断任务监控,也不能把界面刷崩。"""

    def boom(*_a, **_k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(ep.db, "q1", boom)
    fake = _Fake(seen=0)
    ep.EpisodePage._refresh_sb_split_progress(fake)   # 不抛就算过
    assert fake.reloads == 0


def test_polling_branch_calls_progress_refresh():
    """守住「processing 分支必须刷新」这条契约。

    用源码检查而不是实例化整个页面:这个方法体里套着 QTimer.singleShot 的
    lambda 链,真跑起来要 Qt 事件循环,不适合当单测。源码里只要还写着
    「processing 就 return」,这个断言就红。
    """
    src = inspect.getsource(ep.EpisodePage._poll_sb_split)
    processing_branch = src.split('if st == "processing":', 1)[1]
    # 到下一个 `self._sb_split_running = False` 之前就是 processing 分支
    processing_branch = processing_branch.split("self._sb_split_running = False", 1)[0]
    assert "_refresh_sb_split_progress" in processing_branch, \
        "任务 processing 时必须增量刷新列表,否则分批落库期间界面一直是空的"


def test_timeout_error_read_is_none_safe():
    """任务行查不到时不能再 `row[...]` —— row 是 None,会抛 TypeError 盖掉真实提示。"""
    src = inspect.getsource(ep.EpisodePage._poll_sb_split)
    assert 'err((row["error_msg"] if row else None)' in src, \
        "任务行缺失时的错误分支必须先判空 row"
