# -*- coding: utf-8 -*-
"""图库检索(Unsplash / Pexels /        _only_test_rows(monkeypatch)
_only_test_rows(monk    _only_test_rows(    _only_test_rows(monkeypatch)
monkeypatch)
eypatch)
 Pixabay)。

**软失败是硬要求**:搜图是增强项,任何    _on    _only    _only_test_rows(monkeypatch)
_te    _only_test_rows(monkeypatch)
st_rows(monkeypatch)
ly_test_rows(monkeypatch)
一家挂了都不能影响其余,
更不能阻断    _only_test_rows(monkeypatch)
「图片处理」「聊天改图」的改图主流程。
"""
from __future__ import annotations
from pathlib import Path

import json

import pytest
import requests

from app.ai import stock_photo as sp
from app.core import db


def _add(provider: str, key: str = "dummy-key") -> int:
    return db.exmany.__self__ if False else _insert(provider, key)


# 测试自建的配置一律用这个 id 段(95000+),与用户真实配置(1..9999)不重叠。
# 之前直接按 provider 删,`DELETE ... WHERE provider=?` 会连用户真的 Unsplash
# / Pixabay 配置一起删掉 —— 跑一次测试就把用户的 key 清空了。
TEST_ID_BASE = 95000


def _insert(provider: str, key: str) -> int:
    base = {"unsplash": "https://api.unsplash.com",
            "pexels": "https://api.pexels.com",
            "pixabay": "https://pixabay.com"}[provider]
    row = db.q1("SELECT MAX(id) m FROM ai_service_configs WHERE id>=?", (TEST_ID_BASE,))
    cid = max((row or {}).get("m") or 0, TEST_ID_BASE - 1) + 1
    db.ex("INSERT OR REPLACE INTO ai_service_configs "
          "(id, service_type, provider, model, models, base_url, api_key, "
          " is_active, priority, created_at, updated_at) VALUES (?,?,?,?,?,?,?,1,0,?,?)",
          (cid, "stockphoto", provider, "m", json.dumps(["m"]), base, key,
           db.now(), db.now()))
    return cid


def _drop(provider: str) -> None:
    """只删测试自己建的(id >= TEST_ID_BASE),绝不碰用户真实配置。"""
    db.ex("DELETE FROM ai_service_configs WHERE id>=? AND service_type='stockphoto' "
          "AND provider=?", (TEST_ID_BASE, provider))


def _only_test_rows(monkeypatch, extra: dict | None = None) -> None:
    """让 _cfg_rows 只看到测试自建的配置,忽略用户真实配置。

    不隔离的话,测试既会读到用户真实 key 去发真请求(慢且不确定),
    也可能被断言里的数量假设带偏。
    """
    real = sp._cfg_rows()

    def fake():
        return {k: v for k, v in real.items() if v["id"] >= TEST_ID_BASE}
    monkeypatch.setattr(sp, "_cfg_rows", fake)


@pytest.fixture(autouse=True)
def _isolate_real_configs(monkeypatch):
    """**所有**用例都看不到用户真实配置。

    逐个在用例里插 `_only_test_rows` 漏过一次 —— 有 7 个用例没插上,
    其中几个 `DELETE ... WHERE provider=?` 把用户的 Unsplash/Pixabay
    配置连同 key 一起删了,跑一次测试就丢配置。
    改用 autouse fixture,新增用例自动受保护,不可能漏。
    """
    # 必须**每次调用时**现取,不能在 fixture 建立时快照一次 ——
    # 用例是在 fixture 之后才 _insert() 建配置的,快照里根本没有它。
    def fake():
        return {k: v for k, v in sp._cfg_rows.__wrapped__().items()
                if v["id"] >= TEST_ID_BASE} if hasattr(sp._cfg_rows, "__wrapped__")             else {k: v for k, v in _real_cfg_rows().items() if v["id"] >= TEST_ID_BASE}
    monkeypatch.setattr(sp, "_cfg_rows", fake)
    yield


def _real_cfg_rows() -> dict:
    """未打补丁时的原始实现 —— fixture 用它做实时过滤。"""
    out = {}
    for row in db.q("SELECT * FROM ai_service_configs "
                    "WHERE service_type='stockphoto' AND is_active=1 ORDER BY id"):
        p = (row["provider"] or "").strip().lower()
        if p in sp.SOURCE_ORDER:
            out[p] = dict(row)
    return out


# ── 三家鉴权方式各不相同,这是最容易踩的地方 ────────────────────────

def test_unsplash_uses_client_id_header(monkeypatch):
    """Unsplash 是 Client-ID,写成 Bearer 会 401。"""
    seen = {}

    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"results": []}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers or {}
        return _R()

    monkeypatch.setattr(sp.requests, "get", fake_get)
    _insert("unsplash", "UNS-KEY")
    try:
        sp._search_unsplash("UNS-KEY", "cat", 1, 3)
    finally:
        _drop("unsplash")
    assert seen["headers"].get("Authorization") == "Client-ID UNS-KEY", \
        f"Unsplash 鉴权头不对:{seen['headers']}"


def test_pexels_uses_bare_authorization(monkeypatch):
    """Pexels 是裸 key,不加前缀。"""
    seen = {}

    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"photos": []}

    monkeypatch.setattr(sp.requests, "get",
                        lambda url, params=None, headers=None, timeout=None:
                        (seen.update(headers or {}), _R())[1])
    _insert("pexels", "PX-KEY")
    try:
        sp._search_pexels("PX-KEY", "cat", 1, 3)
    finally:
        _drop("pexels")
    assert seen.get("Authorization") == "PX-KEY", f"Pexels 鉴权头不对:{seen}"


def test_pixabay_passes_key_in_query(monkeypatch):
    """Pixabay 把 key 放 URL 参数,不用鉴权头。"""
    seen = {}

    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"hits": []}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["params"] = params or {}
        seen["headers"] = headers or {}
        return _R()

    monkeypatch.setattr(sp.requests, "get", fake_get)
    _insert("pixabay", "PB-KEY")
    try:
        sp._search_pixabay("PB-KEY", "cat", 1, 3)
    finally:
        _drop("pixabay")
    assert seen["params"].get("key") == "PB-KEY", "Pixabay 的 key 没放进查询参数"
    assert "Authorization" not in seen["headers"], "Pixabay 不该带鉴权头"


def test_pixabay_per_page_floor_is_three(monkeypatch):
    """Pixabay 的 per_page 最小值是 3,传 1 会被服务端拒。"""
    seen = {}

    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"hits": []}

    monkeypatch.setattr(sp.requests, "get",
                        lambda url, params=None, headers=None, timeout=None:
                        (seen.update(params or {}), _R())[1])
    _insert("pixabay", "PB-KEY")
    try:
        sp._search_pixabay("PB-KEY", "cat", 1, 1)
    finally:
        _drop("pixabay")
    assert seen["per_page"] >= 3, f"Pixabay per_page 被传成 {seen['per_page']}"


# ── 软失败 ────────────────────────────────────────────────────────

def test_one_source_failing_does_not_break_others(monkeypatch):
    """一家 401 不能拖垮另两家的结果。"""
    # 只看测试自建的那几条,别把用户真实配置也搜进来
    monkeypatch.setattr(sp, "_cfg_rows", lambda: {
        "pexels": {"api_key": "bad"}, "unsplash": {"api_key": "ok"}})

    def fake_pexels(*a, **k):
        raise requests.HTTPError("401")

    monkeypatch.setattr(sp, "_search_pexels", fake_pexels)
    monkeypatch.setattr(sp, "_search_unsplash",
                        lambda *a, **k: [sp._photo("unsplash", "1", "p", "d")])
    _insert("pexels", "bad")
    _insert("unsplash", "ok")
    try:
        photos, errs = sp.search("cat")
    finally:
        _drop("pexels")
        _drop("unsplash")
    assert len(photos) == 1, "一家失败导致全部无结果"
    assert any("Pexels" in e for e in errs), "失败原因没有上报"


def test_invalid_key_message_is_actionable(monkeypatch):
    """401/403 要说清楚是 key 失效,而不是只丢一个状态码。"""

    def boom(*a, **k):
        resp = requests.Response()
        resp.status_code = 401
        raise requests.HTTPError("401 Client Error", response=resp)

    monkeypatch.setattr(sp, "_search_unsplash", boom)
    _insert("unsplash", "expired")
    try:
        photos, errs = sp.search("cat", source="unsplash")
    finally:
        _drop("unsplash")
    assert not photos
    assert any("失效" in e or "Key" in e for e in errs), f"提示不够明确:{errs}"


def test_network_exception_is_caught(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("dns fail")

    monkeypatch.setattr(sp, "_search_pixabay", boom)
    _insert("pixabay", "k")
    try:
        photos, errs = sp.search("cat", source="pixabay")
    finally:
        _drop("pixabay")
    assert photos == [] and errs, "网络异常没被吞成软失败"


def test_no_keys_configured_returns_friendly_error(monkeypatch):
    monkeypatch.setattr(sp, "_cfg_rows", lambda: {})
    photos, errs = sp.search("cat")
    assert photos == []
    assert any("未配置" in e for e in errs), f"没配 key 的提示不对:{errs}"


def test_empty_query_rejected():
    photos, errs = sp.search("   ")
    assert photos == [] and errs


def test_requesting_unconfigured_source_says_which_available(monkeypatch):
    _insert("pixabay", "k")   # 只配了 Pixabay,请求 Pexels 应明确报"未配置"
    try:
        photos, errs = sp.search("cat", source="pexels")
    finally:
        _drop("pixabay")
    assert photos == []
    assert any("Pixabay" in e for e in errs), "没告诉用户哪些是可用的"


# ── 返回形状 ──────────────────────────────────────────────────────

def test_results_are_normalised_to_one_shape(monkeypatch):
    """三家返回结构完全不同,归一后上层才不用写三套解析。"""
    monkeypatch.setattr(sp, "_search_unsplash", lambda *a, **k: [
        sp._photo("unsplash", "u1", "prev", "dl", 10, 20, "Someone", "alt")])
    monkeypatch.setattr(sp, "_search_pixabay", lambda *a, **k: [
        sp._photo("pixabay", "p1", "prev", "dl", 30, 40, "P", "tags")])
    _insert("unsplash", "k")
    _insert("pixabay", "k")
    try:
        photos, _ = sp.search("cat")
    finally:
        _drop("unsplash")
        _drop("pixabay")
    for p in photos:
        assert set(p) >= {"id", "source", "preview_url", "download_url",
                          "width", "height", "photographer", "alt"}
        assert p["id"].startswith(p["source"] + "-"), "id 必须带来源前缀以防撞号"


def test_test_source_reports_invalid_key(monkeypatch):
    _insert("unsplash", "expired")   # test_source 要能从 _cfg_rows 里读到这条
    def boom(*a, **k):
        resp = requests.Response()
        resp.status_code = 403
        raise requests.HTTPError("403", response=resp)

    monkeypatch.setattr(sp, "_search_unsplash", boom)
    _insert("unsplash", "expired")
    try:
        ok, msg = sp.test_source("unsplash")
    finally:
        _drop("unsplash")
    assert ok is False and "失效" in msg, f"连接测试没识别 key 失效:{msg}"


def test_configured_sources_respects_active_flag():
    cid = _insert("pixabay", "k")
    try:
        db.ex("UPDATE ai_service_configs SET is_active=0 WHERE id=?", (cid,))
        assert "pixabay" not in sp.configured_sources(), "停用的配置仍出现在可用列表"
    finally:
        _drop("pixabay")


def test_thumb_card_shows_dimensions():
    """搜图结果卡片必须直接显示「来源 · 宽×高」。

    用户反馈:搜图是在找特定画幅(9:16 竖版 / 16:9 横版),尺寸只藏在
    点开后的预览标题里,等于要一张张点开才知道合不合适。三家 API 都返回
    width/height,_photo() 也解析了,必须印在卡片上。
    """
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QLabel
    QApplication.instance() or QApplication([])
    from app.ui.stock_photo_dialog import _ImgLabel

    ph = {"id": "pexels-1", "source": "pexels", "preview_url": "",
          "download_url": "", "width": 1920, "height": 1080,
          "photographer": "x", "alt": "x"}
    card = _ImgLabel(ph)
    texts = [c.text() for c in card.findChildren(QLabel)]
    assert any("1920×1080" in t for t in texts), f"卡片上没有尺寸:{texts}"
    assert any("Pexels" in t for t in texts), f"卡片上没有来源:{texts}"

    # API 没给尺寸时退化为只显示来源,不能显示 "0×0" 或崩
    ph2 = dict(ph, source="pixabay", width=0, height=0)
    card2 = _ImgLabel(ph2)
    texts2 = [c.text() for c in card2.findChildren(QLabel)]
    assert any("Pixabay" in t for t in texts2)
    assert not any("0×0" in t for t in texts2)


def test_use_this_closes_dialog_and_feeds_signal(monkeypatch, tmp_path):
    """「使用这张」链路:两层窗先关、下载完成经 downloaded 信号回填。

    复刻 2026-10 实测 bug:`_download` 首用时 _dl 为 None,isRunning() 抛
    AttributeError 被 Qt 吞掉 → 图库页不关、图不进聊天。无线程直测:
    关窗分支(_download)与回填分支(_on_downloaded)分别验证。
    """
    import app.ai.stock_photo as sp
    from app.ui.stock_photo_dialog import StockPhotoDialog

    def fake_download(url, out_path, timeout=30):
        Path(out_path).write_bytes(b"data")
        return True

    monkeypatch.setattr(sp, "download", fake_download)

    got: list[str] = []
    dlg = StockPhotoDialog(None, query="x", auto_search=False)
    dlg.downloaded.connect(got.append)
    # 关窗分支:首次 _dl 为 None,不得崩,且立即 accept(两层窗关闭)
    dlg._download("https://example.com/original.jpg", close_immediately=True)
    assert dlg.result() == StockPhotoDialog.Accepted, "弹窗应立即接受(两层窗关闭)"
    # 回填分支:模拟下载线程完成 → downloaded 信号带路径
    out = tmp_path / "done.jpg"
    out.write_bytes(b"data")
    dlg._on_downloaded(True, str(out))
    assert got, "downloaded 信号没有回填路径"
    assert dlg.local_path == got[0] and Path(got[0]).exists()


def test_use_this_local_copy_feeds_signal(monkeypatch, tmp_path):
    """换画风产物(本地路径)走复制分支:同样关闭并回填。"""
    from app.ui.stock_photo_dialog import StockPhotoDialog

    src = tmp_path / "converted.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n converted")
    got: list[str] = []
    dlg = StockPhotoDialog(None, query="x", auto_search=False)
    dlg.downloaded.connect(got.append)
    dlg._download(str(src), close_immediately=True)
    assert got and Path(got[0]).exists()
    assert dlg.local_path == got[0]


def test_adopt_stock_image_sets_chat_current(tmp_path):
    """聊天侧:下载完成 → 设为当前图 + 对话流气泡。"""
    import app.ai.stock_photo as sp
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.ui.chat_edit_drawer import ChatEditPanel

    panel = ChatEditPanel()
    p = tmp_path / "adopt.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n adopt")
    panel._adopt_stock_image(str(p))
    assert panel._current_image == str(p)
    assert panel.status_lab.text() == ""
