# -*- coding: utf-8 -*-
"""资产/参考图区的变体入口与高度回归。

三件事,都是用户实测反馈:
1. **只有一张人物资产时不要变型** —— 变体的意义是从多套形象里挑一套,
   只有一套时:资产卡上的「◑ 造型变体」按钮和分镜侧栏「绑定参考图」下方的
   变体下拉框都是死控件(点进去是空列表 / 下拉里只有「自动解析」一项)。
2. **白色的区域要跟文字一样高** —— 绑定参考图区在构造期写死
   `setFixedHeight(122)`,没素材时也是同样高度的一片空白。
3. **`AssetCard` 的 `BTN_QSS` 引用在使用之后定义** —— 任何带变体按钮的
   场景/道具卡一进 `__init__` 就 UnboundLocalError,资产页直接刷不出来。
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from app.core import db  # noqa: E402
from app.ui import episode_cards as C  # noqa: E402
from app.ui import episode_page as EP  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


LABELS = {
    "variants": "◑ 造型变体",
    "variants_tip": "同一角色的多套服装造型",
    "variants_tip_scene": "同一场景的多套变体",
    "variants_tip_prop": "同一道具的多套变体",
    "comic_multi_view": "📐 漫画多角度",
    "desc_empty": "无描述", "prompt_ph": "提示词占位",
    "gen_text": "AI 改写", "gen_image": "AI 生成", "redraw": "重绘",
    "gen_text_tip": "", "gen_image_tip": "", "draw": "绘制",
    "gen_done": "已生成", "gen_todo": "未生成",
    "upload": "上传", "upload_tip": "", "delete": "删除", "open": "详情",
    "prompt_label": "提示词", "prompt": "提示词",
    "character": "角色", "scene": "场景", "prop": "道具",
    "cover_done": "已出图", "cover_todo": "未出图", "cover_tag": "封面",
    "narration_label": "旁白", "narration_ph": "旁白占位", "narration_hint": "提示",
}


# ------------------------------------------------------------------ 崩溃回归

def test_asset_card_with_variants_does_not_crash(qapp, monkeypatch):
    """带变体按钮的场景/道具卡必须能建出来。

    BTN_QSS 原先定义在页脚那一段(用到之后),这里必然 UnboundLocalError:
    `cannot access local variable 'BTN_QSS' where it is not associated with a value`。
    """
    from PySide6.QtWidgets import QWidget
    monkeypatch.setattr(C, "status_pill", lambda *_a, **_k: QWidget())
    row = {"id": 1, "name": "出租屋", "description": "", "final_prompt": "",
           "lighting": "", "image_url": ""}
    card = C.AssetCard(row, LABELS, "scene",
                       on_gen=lambda: None, on_gen_text=lambda: None,
                       on_gen_vary=lambda: None, on_upload=lambda: None,
                       on_prompt=lambda: None, on_open=lambda: None,
                       on_delete=lambda: None, on_variants=lambda: None)
    labels = [b.text() for b in card.findChildren(QPushButton)]
    assert labels, "变体按钮应该真的建出来了(否则这个用例没测到东西)"


# ------------------------------------------------------------------ 只有一张图不给变体入口

def test_has_variants_is_false_without_rows(monkeypatch):
    monkeypatch.setattr(db, "q1", lambda *a, **k: {"c": 0})
    fake = EP.EpisodePage.__new__(EP.EpisodePage)
    fake.__dict__.pop("_var_has_cache", None)
    assert fake._has_variants(1, "character") is False


def test_has_variants_is_true_with_rows(monkeypatch):
    monkeypatch.setattr(db, "q1", lambda *a, **k: {"c": 3})
    fake = EP.EpisodePage.__new__(EP.EpisodePage)
    fake.__dict__.pop("_var_has_cache", None)
    assert fake._has_variants(1, "character") is True


def test_has_variants_caches_per_ref(monkeypatch):
    """一屏几十张卡,每张查一次库没必要 —— 同 (kind,id) 只查一次。"""
    calls = []

    def fake_q1(*a, **k):
        calls.append(1)
        return {"c": 0}

    monkeypatch.setattr(db, "q1", fake_q1)
    fake = EP.EpisodePage.__new__(EP.EpisodePage)
    fake.__dict__.pop("_var_has_cache", None)
    for _ in range(5):
        fake._has_variants(1, "character")
    assert len(calls) == 1, f"同一 ref 查了 {len(calls)} 次"


# ------------------------------------------------------------------ 下拉框 / 高度

class _Scroll:
    def __init__(self):
        self.h = None

    def setFixedHeight(self, h):
        self.h = h


def test_bound_refs_empty_area_shrinks_to_text():
    """没有绑定素材时,区域高度应与一行文字相当,而不是写死的 122。"""
    fake = EP.EpisodePage.__new__(EP.EpisodePage)
    fake.sb_bound_scroll = _Scroll()
    fake._sync_bound_refs_height(empty_only=True)
    assert fake.sb_bound_scroll.h == 32


def test_bound_refs_height_grows_with_picker():
    """有变体下拉时比没有时高 —— 少一行控件就少一段高度。"""
    fake = EP.EpisodePage.__new__(EP.EpisodePage)
    fake.sb_bound_scroll = _Scroll()
    fake._sync_bound_refs_height(has_picker=False)
    without = fake.sb_bound_scroll.h
    fake._sync_bound_refs_height(has_picker=True)
    assert fake.sb_bound_scroll.h == without + 22
