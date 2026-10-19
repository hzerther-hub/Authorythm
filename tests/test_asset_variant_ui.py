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


# ------------------------------------------------------------------ 出整话动态提示

def test_reconcile_busy_marks_pending(monkeypatch):
    """出整话运行中:busy 应恰好等于「还没图的格」集合。"""
    fake = EP.EpisodePage.__new__(EP.EpisodePage)
    fake._comic_busy = {1, 2, 3}
    assert fake._reconcile_full_comic_busy(True, {2, 3, 4, 5}) is True
    assert fake._comic_busy == {2, 3, 4, 5}, "完成的摘掉,新拆出来的(重拆换 id)补上"


def test_reconcile_busy_clears_when_finished():
    """任务结束:全部转圈清掉(收尾亮图由 done 回调的 reload 负责)。"""
    fake = EP.EpisodePage.__new__(EP.EpisodePage)
    fake._comic_busy = {1, 2}
    assert fake._reconcile_full_comic_busy(False, {1, 2}) is True
    assert fake._comic_busy == set()


def test_reconcile_busy_noop_when_already_consistent():
    """没变化就不返回 True —— 轮询靠它避免每 3 秒重建一次网格。"""
    fake = EP.EpisodePage.__new__(EP.EpisodePage)
    fake._comic_busy = {2, 3}
    assert fake._reconcile_full_comic_busy(True, {2, 3}) is False


def test_reconcile_busy_survives_missing_attr():
    fake = EP.EpisodePage.__new__(EP.EpisodePage)
    assert fake._reconcile_full_comic_busy(True, {1}) is False


def test_full_comic_wires_busy_and_poll():
    """守住「出整话要有动态提示」的接线:提交即 busy + 轮询 + done 恢复。"""
    import inspect
    src = inspect.getsource(EP.EpisodePage._ai_full_comic)
    assert "comic_full_btn" in src and ".busy()" in src, \
        "提交后按钮必须进等待态(防重复提交)"
    assert "self._poll_full_comic(tid)" in src, "必须启动逐格亮图轮询"
    assert "self._comic_busy.update(" in src, "待出格必须立即标 busy(转圈)"
    done_src = src.split("def done", 1)[1].split("def job", 1)[0]
    assert ".idle()" in done_src, "done 回调必须恢复按钮"
    assert "self._comic_busy.clear()" in done_src, "done 必须清干净转圈集合"


def test_split_panels_wires_busy_and_auto_draw():
    """「生成分镜」必须有等待态,且拆完自动接出图。

    实测:拆格是一次 88 秒的 LLM 调用(sys_task#1430),按钮全程无变化,
    用户以为没点上;拆完停在 0/10 静态格子,出图要再点一次「▦ 批量出图」,
    用户等在那里以为出图坏了。
    """
    import inspect
    src = inspect.getsource(EP.EpisodePage._split_panels)
    assert "setEnabled(False)" in src and "setEnabled(True)" in src, \
        "拆格期间按钮必须禁用(88 秒级 LLM 调用,不能让用户干等无提示)"
    assert "self._batch_comic()" in src, "拆格完成后必须自动接批量出图"


# ------------------------------------------------------------------ 鬼影守卫

def test_panel_negative_guard_exists_and_covers_observed_failures():
    """守卫常量必须覆盖实测出现过的失败形态(ep79:床上+站着+镜中+窗外 4 个复制人)。"""
    from app.pipeline import comic as comic_pipe
    g = comic_pipe.PANEL_NEGATIVE_GUARD
    for phrase in ("ghost", "duplicate person", "mirror", "window",
                   "same person appearing twice"):
        assert phrase in g, f"守卫词缺 {phrase!r}"


def test_all_panel_draw_paths_use_the_guard():
    """三条出漫画格的链路(单格/批量/整话)都必须带守卫,不许再裸奔。

    此前只有单格重绘带 ghost 守卫,批量与整话没传 —— 实测整话 10 格前 3 格
    全部「同一角色出现 3-4 次」。这里用源码检查锁死三处。
    """
    import inspect
    from app.pipeline import comic_pipeline
    full_src = inspect.getsource(comic_pipeline.generate_full_comic)
    assert "PANEL_NEGATIVE_GUARD" in full_src, "整话 pipeline 必须带鬼影守卫"
    assert "panel_people_count" in full_src, "整话 pipeline 必须传 people 数"
    page_src = inspect.getsource(EP.EpisodePage)
    # 单格(_one_panel_image)与批量(_batch_comic)各至少一处 extra_negative= 守卫
    assert page_src.count("PANEL_NEGATIVE_GUARD") >= 2, \
        "单格与批量链路必须共用 comic.PANEL_NEGATIVE_GUARD"
