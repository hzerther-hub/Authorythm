# -*- coding: utf-8 -*-
"""集页顶部标题 _page_title 的回归测试。

曾经的真实缺陷:标题渲染成「项目 · 第 1 集 · 第 1 集」。去重逻辑拿集标题去
startswith 一个不带空格的 f"第{n}集",而新建剧集时 title 是 tr('episode_n')
生成的**带空格**的「第 1 集」,永远匹配不上,于是集号被拼了两遍。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.ui.episode_page import _page_title  # noqa: E402


@pytest.mark.parametrize("title", ["第 1 集", "第1集", "第  1  集", "第1集　夜谈"])
def test_duplicate_episode_number_removed(title):
    """集标题只是集号本身时,不能重复渲染。"""
    ep = {"episode_number": 1, "title": title}
    out = _page_title({"title": "固炉夜话"}, ep)
    assert out.count("第") == 1, f"标题重复了集号: {out}"


def test_prefix_stripped_but_chapter_name_kept():
    """带集号前缀的真实章节名要保留章节名部分。"""
    ep = {"episode_number": 1, "title": "第 1 集 夜谈"}
    assert _page_title({"title": "固炉夜话"}, ep) == "固炉夜话 · 第 1 集 · 夜谈"


def test_title_without_prefix_untouched():
    """不带集号前缀的历史章节名(「第1章 …」)原样保留 —— 旧项目的显示不能被改坏。"""
    ep = {"episode_number": 1, "title": "第1章 裁员后我打开了青岚界"}
    assert _page_title({"title": "两界穿梭"}, ep) == \
        "两界穿梭 · 第 1 集 · 第1章 裁员后我打开了青岚界"


@pytest.mark.parametrize("title,num,expect", [
    ("", 1, "固炉夜话 · 第 1 集"),
    (None, 3, "固炉夜话 · 第 3 集"),
    ("夜谈", 2, "固炉夜话 · 第 2 集 · 夜谈"),
])
def test_edge_cases(title, num, expect):
    assert _page_title({"title": "固炉夜话"},
                       {"episode_number": num, "title": title}) == expect


def test_mismatched_number_prefix_not_stripped():
    """标题里的集号和本集集号对不上时不能乱剥(否则第 5 集会吃掉「第 2 集」前缀)。"""
    ep = {"episode_number": 5, "title": "第 2 集 倒叙"}
    assert _page_title({"title": "固炉夜话"}, ep) == "固炉夜话 · 第 5 集 · 第 2 集 倒叙"