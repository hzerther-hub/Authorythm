# -*- coding: utf-8 -*-
"""2026-10-22 代码审查批次的回归护栏。

这批测试锁住 6 个「功能整个不可用 / 静默丢数据」级别的缺陷:

1. comic_pipeline 把**生图** config_id 传给了**文本**模型调用 → 「AI 出整话」
   与「梗概生漫画」两条入口 100% 出 0 图(每格都报「所选配置不存在」)。
2. video_client 的 minimax 分支从不取 task_id → 提交已计费,轮询必崩。
3. novel.plan_config_id / prose_config_id 在没有文本配置时 AttributeError。
4. comic.panel_reference_images 的 8 张上限把「上一格关键帧」挤掉 → 链式一致性断链。
5. text_stream 按响应头 charset 解码 → 网关不带 charset 时整段中文乱码直落库。
6. storyboard.split_storyboards 先删后拆 → LLM 全失败时旧分镜与已生成视频不可恢复。
"""
from __future__ import annotations

import json
from unittest import mock

import pytest

from app.core import db


# ── 1. 整话编排:文本 config 与生图 config 必须分开 ──────────────────────
def test_full_comic_uses_text_config_for_llm_and_image_config_for_image(tmp_path, monkeypatch):
    """拆格/改写提示词拿文本 id,生图拿生图 id —— 两个 id 不能串线。"""
    from app.pipeline import comic_pipeline

    static = tmp_path / "static" / "comics"
    static.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "t.sqlite3")
    monkeypatch.setattr(db.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db.config, "STATIC_DIR", tmp_path / "static")
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    try:
        did = db.ex("INSERT INTO dramas(title,created_at,updated_at) VALUES(?,?,?)",
                    ("剧", db.now(), db.now()))
        eid = db.ex("INSERT INTO episodes(drama_id,episode_number,script_content,content,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?)", (did, 1, "## S01|内景|白天\n有人。", "## S01|内景|白天\n有人。",
                                           db.now(), db.now()))
        seen = {}

        def fake_split(ep_id, text_config_id=None, lang=None, **kw):
            seen["split_text_cfg"] = text_config_id
            db.ex("INSERT INTO comic_panels(episode_id,panel_number,description,created_at,updated_at)"
                  " VALUES(?,?,?,?,?)", (ep_id, 1, "格", db.now(), db.now()))

        def fake_prompt(pid, drama_id, text_config_id=None, style_value=""):
            seen["prompt_text_cfg"] = text_config_id
            return "提示词"

        def fake_img(prompt, config_id=None, **kw):
            seen["img_cfg"] = config_id
            out = static / "p1.png"
            out.write_bytes(b"\x89PNG\r\n\x1a\n")
            return str(out), "fake"

        with mock.patch("app.pipeline.comic.split_panels", side_effect=fake_split), \
             mock.patch("app.pipeline.comic.panel_image_prompt", side_effect=fake_prompt), \
             mock.patch("app.pipeline.comic_pipeline.image_client.generate_image", side_effect=fake_img), \
             mock.patch("app.pipeline.comic_pipeline.stitch.stitch_panels", return_value="x"):
            comic_pipeline.generate_full_comic(eid, config_id=777, text_config_id=888)

        assert seen.get("split_text_cfg") == 888, "拆格必须用文本模型配置"
        assert seen.get("prompt_text_cfg") == 888, "出图提示词改写必须用文本模型配置"
        assert seen.get("img_cfg") == 777, "生图必须用生图模型配置"
    finally:
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
            db._local.conn = None


def test_panel_image_prompt_and_split_take_text_config_id():
    """两个 LLM 入口的参数名必须带 text_ 前缀(防呆:别再和生图配置同名)。"""
    import inspect

    from app.pipeline import comic

    assert "text_config_id" in inspect.signature(comic.panel_image_prompt).parameters
    assert "text_config_id" in inspect.signature(comic.split_panels).parameters
    assert "config_id" not in inspect.signature(comic.panel_image_prompt).parameters


# ── 2. minimax 视频分支 ────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = json.dumps(payload).encode("utf-8")
        self.text = self.content.decode("utf-8")

    def json(self):
        return self._payload


def test_minimax_branch_extracts_task_id_and_polls(monkeypatch):
    """提交响应里的 task_id 必须被取出来并用于轮询。"""
    from app.ai import video_client

    posted = {}
    polled = {}

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        posted["url"] = url
        return _FakeResp({"task_id": "mm-task-123"})

    def fake_get(url, headers=None, timeout=None, **kw):
        polled["url"] = url
        return _FakeResp({"status": "Success", "file": {"download_url": "http://x/v.mp4"}})

    monkeypatch.setattr(video_client.requests, "post", fake_post)
    monkeypatch.setattr(video_client.requests, "get", fake_get)
    monkeypatch.setattr(video_client, "_download", lambda url: "/tmp/v.mp4")
    monkeypatch.setattr(video_client, "_poll", lambda check, *a, **k: check()[1] or "http://x/v.mp4")

    cfg = {"provider": "minimax", "model": "m", "api_key": "k",
           "base_url": "https://mm.example.com"}
    out, provider = video_client._dispatch_once(
        cfg, cfg["base_url"], {"Content-Type": "application/json"}, "提示", "720P", None,
        None, [], None, [], max_side=768, quality=68)

    assert provider == "minimax"
    assert out == "/tmp/v.mp4"
    assert "mm-task-123" in polled.get("url", ""), "轮询 URL 必须带上 task_id"


def test_minimax_missing_task_id_raises_instead_of_polling(monkeypatch):
    """取不到 task_id 就立刻报错 —— 不能拿着空 id 去轮询(提交已计费)。"""
    from app.ai import video_client

    def fake_post(url, json=None, headers=None, timeout=None, **kw):
        return _FakeResp({"oops": 1})

    def fake_get(*a, **kw):
        raise AssertionError("取不到 task_id 时不该发起轮询请求")

    monkeypatch.setattr(video_client.requests, "post", fake_post)
    monkeypatch.setattr(video_client.requests, "get", fake_get)

    cfg = {"provider": "minimax", "model": "m", "api_key": "k",
           "base_url": "https://mm.example.com"}
    with pytest.raises(video_client.AIError):
        video_client._dispatch_once(
            cfg, cfg["base_url"], {"Content-Type": "application/json"}, "提示", "720P", None,
            None, [], None, [], max_side=768, quality=68)


# ── 3. 小说规划/正文模型兜底 ────────────────────────────────────────────
def test_plan_and_prose_config_id_survive_missing_config(monkeypatch):
    """没有文本配置时返回 None,不能 AttributeError(设置页初始化会崩)。"""
    from app.pipeline import novel

    monkeypatch.setattr(novel.db, "get_setting", lambda *a, **k: "")
    monkeypatch.setattr(novel.registry, "default_config", lambda *a, **k: None)

    assert novel.plan_config_id() is None
    assert novel.prose_config_id() is None


def test_plan_and_prose_config_id_read_setting(monkeypatch):
    """设置了专用配置就优先用它。"""
    from app.pipeline import novel

    monkeypatch.setattr(novel.db, "get_setting", lambda key, *a: "4242" if "plan" in key else "5252")
    assert novel.plan_config_id() == 4242
    assert novel.prose_config_id() == 5252


# ── 4. 参考图上限不能挤掉上一格关键帧 ────────────────────────────────────
def test_panel_reference_images_keeps_prev_keyframe(tmp_path, monkeypatch):
    """资产参考图超过 7 张时,prev 关键帧必须仍在(链式一致性的锚)。"""
    from app.pipeline import comic

    refs = []
    for i in range(10):
        p = tmp_path / f"ref{i}.png"
        p.write_bytes(b"x")
        refs.append(str(p))
    prev = tmp_path / "prev.png"
    prev.write_bytes(b"x")

    monkeypatch.setattr(comic, "_panel_bound_assets",
                        lambda pid: ([{"id": 1}], [], []))
    monkeypatch.setattr(comic, "character_all_refs", lambda cid: refs)

    out = comic.panel_reference_images(1, prev_image_url=str(prev))
    assert str(prev) in out, "上一格关键帧被参考图上限挤掉了"
    assert len(out) <= 8, "参考图总数必须受上限约束"


def test_panel_reference_images_without_prev_respects_limit(tmp_path, monkeypatch):
    """没有 prev 时也守 8 张上限。"""
    from app.pipeline import comic

    refs = []
    for i in range(12):
        p = tmp_path / f"r{i}.png"
        p.write_bytes(b"x")
        refs.append(str(p))
    monkeypatch.setattr(comic, "_panel_bound_assets", lambda pid: ([{"id": 1}], [], []))
    monkeypatch.setattr(comic, "character_all_refs", lambda cid: refs)

    out = comic.panel_reference_images(1)
    assert len(out) == 8


# ── 5. 流式(SSE)解码不能被响应头 charset 带偏 ──────────────────────────
class _FakeSSE:
    """模拟 requests 的流式响应:按 self.encoding 解码字节流。"""

    def __init__(self, raw: bytes):
        self.raw = raw
        self.status_code = 200
        self.encoding = "ISO-8859-1"      # requests 对无 charset 的 text/* 就是给这个
        self.closed = False

    def iter_lines(self, decode_unicode=False):
        for line in self.raw.split(b"\n"):
            if decode_unicode:
                yield line.decode(self.encoding or "utf-8", errors="replace")
            else:
                yield line

    def close(self):
        self.closed = True


def test_stream_decodes_utf8_even_without_charset(monkeypatch):
    """网关返回 text/event-stream(不带 charset)时中文不能变乱码。"""
    from app.ai import text_stream

    payload = json.dumps({"choices": [{"delta": {"content": "你好世界"}}]},
                         ensure_ascii=False).encode("utf-8")
    raw = b"data: " + payload + b"\n\ndata: [DONE]\n"

    class _R:
        def __init__(self):
            self.status_code = 200
            self.encoding = "ISO-8859-1"
            self.raw = raw

        def iter_lines(self, decode_unicode=False):
            for line in self.raw.split(b"\n"):
                if decode_unicode:
                    yield line.decode(self.encoding or "utf-8", errors="replace")
                else:
                    yield line

        def close(self):
            pass

    resp = _R()
    monkeypatch.setattr(text_stream.registry, "check_ready",
                        lambda *a, **k: {"base_url": "http://x", "api_key": "k", "model": "m"})
    monkeypatch.setattr(text_stream.requests, "post", lambda *a, **k: resp)

    chunks = list(text_stream.chat_stream("提示"))
    text = "".join(t for kind, t in chunks if kind == "content")
    assert text == "你好世界", f"流式内容乱码了:{text!r}"


# ── 6. 分镜重拆:LLM 全失败时不能先删旧分镜 ──────────────────────────────
def test_resplit_keeps_old_storyboards_when_llm_fails(tmp_path, monkeypatch):
    """全部批次失败 → 旧分镜与已生成视频原样保留,不许两头空。"""
    from app.pipeline import storyboard as sb

    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "t.sqlite3")
    monkeypatch.setattr(db.config, "DATA_DIR", tmp_path)
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    try:
        did = db.ex("INSERT INTO dramas(title,created_at,updated_at) VALUES(?,?,?)",
                    ("剧", db.now(), db.now()))
        eid = db.ex("INSERT INTO episodes(drama_id,episode_number,script_content,content,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?)", (did, 1, "## S01|内景|白天\n有人。", "x", db.now(), db.now()))
        db.ex("INSERT INTO storyboards(episode_id,storyboard_number,description,created_at,updated_at)"
              " VALUES(?,?,?,?,?)", (eid, 1, "旧分镜", db.now(), db.now()))

        def boom(*a, **k):
            raise RuntimeError("模型不可用")

        monkeypatch.setattr(sb, "_boards_for_part", boom)
        purged = []
        monkeypatch.setattr(sb, "purge_episode_storyboards",
                            lambda *a, **k: purged.append(1) or {"shots": 1})

        with pytest.raises(RuntimeError):
            sb.split_storyboards(eid, aspect="9:16", on_chunk_failed=lambda label, reason: None)

        assert not purged, "LLM 全失败时不该清空旧分镜"
        n = db.q1("SELECT COUNT(*) c FROM storyboards WHERE episode_id=?", (eid,))["c"]
        assert n == 1, "旧分镜被误删了"
    finally:
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
            db._local.conn = None
