# -*- coding: utf-8 -*-
"""MTV 项目线:歌曲管理 + 无对白剧本 + 全静音合并铺歌。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import db
from app.pipeline import mtv


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "mtv.sqlite3")
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    yield
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


@pytest.fixture
def qapp():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _mk_drama(work_type: str = "mtv", metadata: dict | None = None) -> int:
    db.ex("""INSERT INTO dramas(title,style,aspect_ratio,work_type,metadata,status,created_at,updated_at)
             VALUES('测试MV','3d','9:16',?,?,'pending',?,?)""",
          (work_type, json.dumps(metadata or {}, ensure_ascii=False), db.now(), db.now()))
    return db.get_db().execute("SELECT id FROM dramas ORDER BY id DESC LIMIT 1").fetchone()["id"]


def _mk_episode(drama_id: int) -> int:
    ts = db.now()
    return db.ex("""INSERT INTO episodes(drama_id,episode_number,title,status,resolution,created_at,updated_at)
                 VALUES(?,1,'第 1 集','draft','720p',?,?)""", (drama_id, ts, ts))


class _FakeRet:
    returncode = 0
    stderr = b""


# ── 元数据 ───────────────────────────────────────────────────────────

def test_save_song_copies_mp3_and_probes_duration(tmp_db, tmp_path, monkeypatch):
    """存歌:MP3 拷入 uploads、时长以实测为准(用户手填只是没传歌时的估计)。"""
    monkeypatch.setattr(db.config, "STATIC_DIR", tmp_path / "static")
    mp3 = tmp_path / "song.mp3"
    mp3.write_bytes(b"id3-fake")
    monkeypatch.setattr(mtv, "probe_audio_duration", lambda p: 141.0)
    did = _mk_drama(metadata={"mtv": {"lyrics": "旧词", "song_duration": 60}})
    out = mtv.save_song(did, lyrics="新词全部", song_path=mp3)
    assert out["song_duration"] == 141, "时长应以 MP3 实测为准,不是用户手填"
    assert out["lyrics"] == "新词全部"
    meta = mtv.mtv_meta(did)
    assert meta["song_url"].startswith("/static/")
    p = db.config.media_url_to_path(meta["song_url"])
    assert p.exists() and p.read_bytes() == b"id3-fake"


def test_mtv_meta_ignores_non_mtv_projects(tmp_db):
    did = _mk_drama(work_type="drama")
    assert mtv.mtv_meta(did) == {}


# ── 剧本契约 ─────────────────────────────────────────────────────────

def test_mtv_writer_prompt_contract():
    """mtv_writer 的系统提示词:无对白、场景头与时长标记、总和=歌曲时长。"""
    from app.agents.prompts import DEFAULT_PROMPTS
    p = DEFAULT_PROMPTS["mtv_writer"]
    assert "无对白" in p and "无旁白" in p
    assert "## S01 | 内景 · 地点 | 时间" in p
    assert "【时长:10秒】" in p
    assert "歌曲总时长" in p or "时长之和" in p


def test_auto_generate_builds_mtv_context_and_persists_script(tmp_db, monkeypatch):
    """歌词/时长必须进提示词;剧本落 script_content(下游分镜链路读这一列)。

    不走 TASKMGR.submit(其就绪校验在无 GUI 的测试环境会弹框卡死),
    直接测 build_message(上下文构造)与 _persist(落库)两个纯函数。
    """
    from app.pipeline import auto_generate as ag
    did = _mk_drama(metadata={"mtv": {"lyrics": "杀向南天门\n俺还是要上班", "song_duration": 141}})
    ep = _mk_episode(did)
    d = dict(db.q1("SELECT * FROM dramas WHERE id=?", (did,)))
    msg = ag.build_message(d, "mtv")
    assert "杀向南天门" in msg and "141" in msg, "歌词与歌曲时长必须进提示词"
    script = "## S01 | 外景 · 五行山 | 黎明\n【时长:10秒】\n画面描述"
    assert ag._persist(ep, "mtv", script) == 1
    row = db.q1("SELECT script_content FROM episodes WHERE id=?", (ep,))
    assert "五行山" in (row["script_content"] or "")
    assert ag.AGENT_FOR["mtv"] == ("mtv_writer", "mtv_script")


def test_new_project_dialog_mtv_fields_and_defaults(qapp):
    """MTV 选型:歌词/时长/选歌字段出现,画幅默认 9:16,结果带 mtv 元数据与歌路径。"""
    from app.ui.new_project_dialog import NewProjectDialog
    dlg = NewProjectDialog()
    dlg._radios["mtv"].setChecked(True)
    assert not dlg.lyrics_edit.isHidden()
    dlg.name_edit.setText("杀向南天门")
    dlg.lyrics_edit.setPlainText("歌词第一行")
    dlg._song_path = "C:/songs/xxx.mp3"
    assert dlg.aspect_combo.currentData() == "9:16", "MTV 应默认 9:16 竖屏"
    data = dlg.result_data()
    m = db.jload(data["metadata"], {})["mtv"]
    assert m["lyrics"] == "歌词第一行" and m["song_duration"] > 0
    assert data["song_src"] == "C:/songs/xxx.mp3"


def test_new_project_dialog_other_types_hide_mtv_fields(qapp):
    from app.ui.new_project_dialog import NewProjectDialog
    dlg = NewProjectDialog()
    dlg._radios["drama"].setChecked(True)
    assert not hasattr(dlg, "lyrics_edit") or dlg.lyrics_edit.isHidden()
    dlg.name_edit.setText("普通短剧")
    assert dlg.result_data()["song_src"] == ""


# ── 合并:全静音 + 铺歌 ──────────────────────────────────────────────

def test_merge_mtv_silent_concat_and_song_mux(tmp_db, tmp_path, monkeypatch):
    """合并两步:① 统一画幅拼接且**无任何音频流**(-an);② 画面 copy + 铺歌(-shortest)。"""
    monkeypatch.setattr(db.config, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "static" / "merged").mkdir(parents=True)
    song = tmp_path / "song.mp3"
    song.write_bytes(b"mp3")
    did = _mk_drama(metadata={"mtv": {"lyrics": "x", "song_duration": 141}})
    monkeypatch.setattr(mtv, "probe_audio_duration", lambda p: 141.0)
    mtv.save_song(did, song_path=song)
    ep = _mk_episode(did)
    v1, v2 = tmp_path / "v1.mp4", tmp_path / "v2.mp4"
    v1.write_bytes(b"v")
    v2.write_bytes(b"v")

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"out")
        return _FakeRet()

    monkeypatch.setattr(mtv.subprocess, "run", fake_run)
    monkeypatch.setattr(mtv.config, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(mtv.merge_mod, "episode_shot_files",
                        lambda eid, ids=None: [v1, v2])
    monkeypatch.setattr(mtv.merge_mod, "_majority_size", lambda shots: (720, 1280))
    monkeypatch.setattr(mtv.merge_mod, "probe", lambda p: {"duration": 20.0})

    out = mtv.merge_mtv(ep, [1, 2])
    assert len(calls) == 2, "应恰好两步:静音拼接 + 铺歌"
    concat_cmd, mux_cmd = " ".join(calls[0]), " ".join(calls[1])
    assert "concat=" in concat_cmd and "-an" in concat_cmd, "拼接必须无音频流"
    assert "720:1280" in concat_cmd, "统一到多数派画幅"
    assert "-map 0:v" in mux_cmd and "-map 1:a" in mux_cmd and "-shortest" in mux_cmd
    assert "-c:v copy" in mux_cmd, "铺歌不得重压画面"
    row = db.q1("SELECT status, model FROM video_merges WHERE episode_id=?", (ep,))
    assert row["status"] == "completed" and row["model"] == "mtv-song"
    assert out.exists()


def test_merge_mtv_without_song_is_silent_only(tmp_db, tmp_path, monkeypatch):
    """没传歌:只出无声画面(model=mtv-silent),不炸。"""
    monkeypatch.setattr(db.config, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "static" / "merged").mkdir(parents=True)
    did = _mk_drama(metadata={"mtv": {"lyrics": "x", "song_duration": 100}})
    ep = _mk_episode(did)
    v1 = tmp_path / "v1.mp4"
    v1.write_bytes(b"v")

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"out")
        return _FakeRet()

    monkeypatch.setattr(mtv.subprocess, "run", fake_run)
    monkeypatch.setattr(mtv.config, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(mtv.merge_mod, "episode_shot_files", lambda eid, ids=None: [v1])
    monkeypatch.setattr(mtv.merge_mod, "_majority_size", lambda shots: (720, 1280))
    monkeypatch.setattr(mtv.merge_mod, "probe", lambda p: {"duration": 10.0})
    mtv.merge_mtv(ep)
    assert len(calls) == 1, "无歌时只有静音拼接一步"
    row = db.q1("SELECT model FROM video_merges WHERE episode_id=?", (ep,))
    assert row["model"] == "mtv-silent"


def test_auto_generate_strips_think_block():
    """首集剧本落库前必须剥思维链 —— 2026-11-02 实测:MTV 首集 60449 字里
    57946 字是 <think>,界面/分镜/资产提取全读到脏数据。"""
    from app.agents import runner
    raw = ("<think>我们需要规划 15 个场景,每场 8-12 秒……</think>\n"
           "## S01 | 内景 · 出租屋 | 深夜\n【时长:9秒】\n画面描述")
    assert runner.strip_think(raw).startswith("## S01")
    # 未闭合尾巴:正文在思考之后,行级启发式剥思考行,不丢正文
    raw2 = "<think>Let me plan the scenes.\n- wait, 15 scenes\n\n## S02 | 外景 · 街道 | 夜\n【时长:10秒】\n正文"
    assert "## S02" in runner.strip_think(raw2)
    # auto_generate 的 job 里真的调用了 strip_think(源码级守卫,防回归)
    import inspect
    from app.pipeline import auto_generate as ag
    src = inspect.getsource(ag)
    assert "runner.strip_think" in src


# ── 歌词字幕 + 歌曲条(对齐交接文档平台的歌曲条)────────────────────────

def test_build_lyrics_ass_even_timing(tmp_db, tmp_path):
    """歌词 → ASS:空行跳过,每行平分歌曲时长,时间戳 H:MM:SS.CS。"""
    ass = mtv.build_lyrics_ass("第一句\n\n第二句\n第三句", 90,
                               tmp_path / "lyrics.ass", w=720, h=1280)
    s = ass.read_text(encoding="utf-8")
    assert s.count("Dialogue: 0,") == 3, "空行不得生成字幕行"
    assert "0:00:00.00,0:00:30.00" in s, "每行 90/3=30 秒"
    assert "PlayResX: 720" in s and "PlayResY: 1280" in s, "PlayRes 跟画幅走"
    assert "Microsoft YaHei" in s
    # 非空歌词必须存在
    assert "第三句" in s


def test_build_lyrics_ass_empty_raises(tmp_db, tmp_path):
    with pytest.raises(RuntimeError, match="歌词为空"):
        mtv.build_lyrics_ass("\n\n  \n", 90, tmp_path / "x.ass")


def test_merge_mtv_burns_lyrics_subtitles_when_enabled(tmp_db, tmp_path, monkeypatch):
    """歌词字幕开着:铺歌命令带 subtitles 滤镜且画面重压(不能 -c:v copy)。"""
    monkeypatch.setattr(db.config, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "static" / "merged").mkdir(parents=True)
    song = tmp_path / "song.mp3"
    song.write_bytes(b"mp3")
    did = _mk_drama(metadata={"mtv": {"lyrics": "第一句\n第二句",
                                      "song_duration": 100, "subtitle": True}})
    monkeypatch.setattr(mtv, "probe_audio_duration", lambda p: 100.0)
    mtv.save_song(did, song_path=song)
    ep = _mk_episode(did)
    v1 = tmp_path / "v1.mp4"
    v1.write_bytes(b"v")

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"out")
        return _FakeRet()

    monkeypatch.setattr(mtv.subprocess, "run", fake_run)
    monkeypatch.setattr(mtv.config, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(mtv.merge_mod, "episode_shot_files", lambda eid, ids=None: [v1])
    monkeypatch.setattr(mtv.merge_mod, "_majority_size", lambda shots: (720, 1280))
    monkeypatch.setattr(mtv.merge_mod, "probe", lambda p: {"duration": 10.0})
    mtv.merge_mtv(ep)
    assert len(calls) == 2
    mux_cmd = " ".join(calls[1])
    assert "subtitles=" in mux_cmd, "字幕开着必须烧进画面"
    assert "-c:v copy" not in mux_cmd, "带滤镜时画面必须重压"
    # ass 文件真的生成在 silent 同目录,且命令用相对名喂滤镜(避 Windows 冒号坑)
    assert any(a == "subtitles=lyrics.ass" for a in calls[1]), \
        f"subtitles 滤镜应用相对文件名: {calls[1]}"
    assert (tmp_path / "static" / "merged" / "lyrics.ass").exists()


def test_episode_page_song_bar_mtv_only(tmp_db, tmp_path, monkeypatch, qapp):
    """歌曲条仅 MTV 项目显示:歌曲名+时长/播放/换歌/歌词/字幕开关;
    非 MTV 项目整行隐藏。"""
    from app.ui.episode_page import EpisodePage
    monkeypatch.setattr(db.config, "STATIC_DIR", tmp_path / "static")
    (tmp_path / "static" / "uploads").mkdir(parents=True)
    song = tmp_path / "song.mp3"
    song.write_bytes(b"mp3")
    did = _mk_drama(metadata={"mtv": {"lyrics": "词", "song_duration": 127}})
    monkeypatch.setattr(mtv, "probe_audio_duration", lambda p: 127.0)
    mtv.save_song(did, song_path=song)
    ep = _mk_episode(did)
    page = EpisodePage()
    page.load(drama_id=did, episode_id=ep)
    assert not page._song_row_host.isHidden(), "MTV 项目应显示歌曲条"
    assert "2:07" in page.song_lab.text(), "时长 127s 应显示为 2:07"
    # 非 MTV
    did2 = _mk_drama(work_type="drama")
    ep2 = _mk_episode(did2)
    page.load(drama_id=did2, episode_id=ep2)
    assert page._song_row_host.isHidden(), "非 MTV 项目应隐藏歌曲条"


def test_set_song_subtitle_persists(tmp_db):
    did = _mk_drama(metadata={"mtv": {"lyrics": "x", "song_duration": 10}})
    mtv.set_song_subtitle(did, True)
    assert mtv.mtv_meta(did)["subtitle"] is True
    mtv.set_song_subtitle(did, False)
    assert mtv.mtv_meta(did)["subtitle"] is False
