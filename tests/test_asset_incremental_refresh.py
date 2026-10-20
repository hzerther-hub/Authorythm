# -*- coding: utf-8 -*-
"""批量生图「生成一张显示一张」的回归测试。

用户实测反馈:批量生图时,图要等**整批跑完**才一次性出现,期间界面一动不动,
看起来就是「卡住了」。根因有两层:

1. `episode_page._batch_*` 的 worker job 只写库,UI 刷新全压在最后的 `done()`
   → 整批跑完才 `_reload_assets()`。
2. `taskmgr.on_main()` 用 `QTimer.singleShot` 实现,而 singleShot 创建的定时器
   归属**调用线程** —— worker 线程没有事件循环,定时器永不触发,回调静默不执行。
   所以就算改成「出完一张就刷新」,刷新也发不出去。

第 2 条还顺带拖垮了另外两处功能(分镜首帧「生成一张显示一张」的单镜缩略图、
Agnes 参数体检提示),它们都是同一个写法 —— 本文件一并守住。
"""
from __future__ import annotations

import inspect
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

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
    "lead": "主角", "supporting": "配角", "extra": "龙套",
    "cover_done": "已生成", "cover_todo": "形象待生成", "cover_tag": "视图",
    "narration_label": "旁白", "narration_ph": "旁白占位", "narration_hint": "提示",
    "face_swap": "换脸", "face_swap_tip": "",
}


def _pump(qapp, rounds=60):
    """跑几轮事件循环,让 queued 信号投递的回调真正执行。"""
    for _ in range(rounds):
        qapp.processEvents()
        time.sleep(0.01)


# ─────────────────────────────────────────── on_main 跨线程必须真的执行
def test_on_main_from_worker_thread_runs_in_main_thread(qapp):
    """worker 线程里调 on_main → 回调必须执行,且必须在主线程执行。

    回归:on_main 原先用 QTimer.singleShot。singleShot 的定时器归属**调用线程**,
    worker 没有事件循环 → 定时器永不触发 → 回调静默不执行(哑弹)。
    """
    from app.core.taskmgr import on_main

    main_id = threading.current_thread().ident
    seen: dict = {}

    def _worker():
        on_main(lambda: seen.update(tid=threading.current_thread().ident))

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout=5)
    _pump(qapp)

    assert seen, "worker 线程里 on_main 的回调从未执行 —— 刷新根本发不出去"
    assert seen["tid"] == main_id, "回调不在主线程执行(跨线程碰 Qt 控件会崩)"


# ─────────────────────────────────────────── 封面原地换
def test_cover_box_set_cover_replaces_content_in_place(qapp):
    """CoverBox.set_cover 原地换图:旧控件摘出布局,角标同步换态。"""
    box = C.CoverBox(None, 200, 120, "☺",
                     badge=LABELS["cover_todo"], badge_state="todo",
                     tag_text=LABELS["cover_tag"])
    assert box._content is box._ph, "没图时应该显示占位符"

    box.set_cover("E:/pydrama/data/static/__no_such_file__.png",
                  badge=LABELS["cover_done"], badge_state="ready")

    assert box._content is box._img, "封面控件没换"
    assert box._ph.isHidden(), "占位符没隐藏 —— 会盖在新图上面"
    assert not box._img.isHidden(), "新图没显示"
    assert box._badge.text() == LABELS["cover_done"]
    assert box._badge.property("state") == "ready"


def test_unbusy_restores_original_button_text(qapp):
    """解除等待态后按钮文字要还原成原标签 —— 不能留着盲文帧。

    回归:apply_asset_busy 原先在 busy=False 时直接读 button.text() 当"原文字",
    而转圈时文字已被改成盲文帧 → 还原后按钮上永久留着盲文。
    """
    from app.ui.braille import BRAILLE_FRAMES

    row = {"id": 1, "name": "甲", "role_type": "lead",
           "appearance": "", "styling": "", "final_prompt": ""}
    card = C.CharacterAssetCard(row, LABELS, busy=True)
    btns = card.findChildren(QPushButton)
    assert btns
    assert btns[0].text() == BRAILLE_FRAMES[0], "busy 时按钮应变盲文帧"

    card.set_cover_url("/static/whatever.png")

    texts = [b.text() for b in card.findChildren(QPushButton)]
    assert BRAILLE_FRAMES[0] not in texts, "解除等待态后按钮上仍留着盲文"
    assert LABELS["upload"] in texts, "「上传」按钮文字没还原"
    assert all(b.isEnabled() for b in card.findChildren(QPushButton)), \
        "解除等待态后按钮仍处于禁用"
    assert card._cover._badge.text() == LABELS["cover_done"], "角标没切成「已生成」"


# ─────────────────────────────────────────── 页面级:逐项刷新
def test_refresh_asset_cover_updates_only_that_card(qapp):
    """_refresh_asset_cover:只动那一张卡,并把它从等待态集合里摘掉。"""
    row = {"id": 7, "name": "乙", "role_type": "supporting",
           "appearance": "", "styling": "", "final_prompt": ""}
    card = C.CharacterAssetCard(row, LABELS, busy=True)

    page = EP.EpisodePage.__new__(EP.EpisodePage)   # 不走 __init__,只喂必需属性
    page._asset_cards = {("characters", 7): card}
    page._asset_busy = {"characters:7"}
    page.asset_stat = None       # _refresh_asset_stat 直接返回
    page._asset_mode = "regular"

    page._refresh_asset_cover("characters", 7, "/static/whatever.png")

    assert card._cover._badge.text() == LABELS["cover_done"]
    assert "characters:7" not in page._asset_busy, \
        "出完图还留在等待态集合里 —— 中途任何一次 reload 会把它标回「生成中」"


# ─────────────────────────────────────────── 端到端:worker → 主线程 → 卡片
def test_worker_thread_refresh_reaches_card_in_main_thread(qapp):
    """整条链路:worker 线程 → on_main → 主线程 → 卡片原地换图。

    这正是批量生图 job 里发生的事(出完一张就调 _batch_refresh_one)。
    """
    from app.ui.braille import BRAILLE_FRAMES

    row = {"id": 11, "name": "丙", "role_type": "lead",
           "appearance": "", "styling": "", "final_prompt": ""}
    card = C.CharacterAssetCard(row, LABELS, busy=True)

    page = EP.EpisodePage.__new__(EP.EpisodePage)
    page._asset_cards = {("characters", 11): card}
    page._asset_busy = {"characters:11"}
    page.asset_stat = None
    page._asset_mode = "regular"

    # worker 线程里发刷新(和批量 job 里一模一样)
    def _worker():
        page._batch_refresh_one("characters", 11, "/static/whatever.png")

    th = threading.Thread(target=_worker, daemon=True)
    th.start()
    th.join(timeout=5)
    _pump(qapp)

    assert card._cover._content is card._cover._img, "封面没换成图"
    assert card._cover._badge.text() == LABELS["cover_done"]
    assert not card._cover._overlay.isVisible(), "「生成中」遮罩没撤掉"
    assert "characters:11" not in page._asset_busy
    texts = [b.text() for b in card.findChildren(QPushButton)]
    assert BRAILLE_FRAMES[0] not in texts, "按钮上仍留着盲文"


# ─────────────────────────────────────────── 所有批量入口都要逐项刷新
@pytest.mark.parametrize("fn_name", [
    "_batch_images",        # 批量文绘
    "_batch_redo_images",   # 批量重画(单类)
    "_batch_redo_all",      # 批量重画(角色+场景+道具)
    "_batch_fill_missing",  # 补图(单类)
    "_batch_fill_missing_all",  # 补图(全类)
])
def test_batch_job_refreshes_each_asset(fn_name):
    """每个批量 job 都必须逐项刷新,不能只等整批结束。"""
    src = inspect.getsource(getattr(EP.EpisodePage, fn_name))
    assert "_batch_refresh_one" in src, \
        f"{fn_name} 整批跑完才刷新 —— 用户看到的是「按了没反应」"
