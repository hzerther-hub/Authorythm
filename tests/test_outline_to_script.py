# -*- coding: utf-8 -*-
"""Layer 2.3:梗概扩写为剧本(outline_to_script)的回归护栏。

覆盖:
- 空梗概 / 短梗概(<30字) → RuntimeError,不落库
- 模型返回正常 JSON → 落库 + 校验剧本格式(`## S\d+\|...` 头)
- 模型返回空 script → RuntimeError
- 模型返回非 dict(裸字符串) → RuntimeError,友好提示
- 剧本无 `## S` 头 → RuntimeError
- 落库后 comic_pipeline 可直接消费
"""
from __future__ import annotations

from unittest import mock

import pytest

from app.core import db
from app.pipeline import novel


SAMPLE_OUTLINE = (
    "李明是个程序员,周末加班后疲惫不堪,在公司楼下的咖啡馆喝咖啡。"
    "这时他十年未见的初中同学王芳突然出现,告诉他一个秘密——他母亲其实还在世。"
    "李明震惊,决定立刻回老家寻找真相。")
VALID_SCRIPT_JSON = {
    "script": (
        "## S01|内景·咖啡馆|白天\n"
        "李明端着咖啡望向窗外。\n\n"
        "## S02|内景·咖啡馆|白天\n"
        "门铃响了,王芳推门进来。\n\n"
        "## S03|外景·街道|白天\n"
        "李明冲出咖啡馆,打车去车站。\n"
    ),
}


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    static = tmp_path / "static"
    for sub in ("images", "videos", "narration", "merged", "comics", "uploads", "covers"):
        (static / sub).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "t.sqlite3")
    monkeypatch.setattr(db.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db.config, "STATIC_DIR", static)
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    yield tmp_path
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


def _setup_episode(tmp_path, title="测试剧", script="", content=""):
    # 注入一个默认文本配置,避免 prose_config_id() 走 default_config 撞 None
    db.ex(
        "INSERT INTO ai_service_configs(service_type,provider,base_url,api_key,model,is_active,created_at,updated_at)"
        " VALUES('text','openai','https://api.openai.com/v1','sk-test','gpt-test',1,?,?)",
        (db.now(), db.now()),
    )
    did = db.ex(
        "INSERT INTO dramas(title,language,created_at,updated_at) VALUES(?,?,?,?)",
        (title, "zh", db.now(), db.now()),
    )
    eid = db.ex(
        "INSERT INTO episodes(drama_id,episode_number,script_content,content,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?)",
        (did, 1, script, content, db.now(), db.now()),
    )
    return did, eid


def test_empty_outline_raises(tmp_db):
    """空梗概 → RuntimeError,无落库。"""
    did, eid = _setup_episode(tmp_db)
    with pytest.raises(RuntimeError, match="请先输入故事梗概"):
        novel.outline_to_script("", episode_id=eid)
    row = db.q1("SELECT script_content FROM episodes WHERE id=?", (eid,))
    assert row["script_content"] == ""


def test_short_outline_raises(tmp_db):
    """<30 字的梗概 → RuntimeError。"""
    did, eid = _setup_episode(tmp_db)
    with pytest.raises(RuntimeError, match="梗概太短"):
        novel.outline_to_script("太短了", episode_id=eid)


def test_valid_outline_writes_script_to_db(tmp_db):
    """正常 LLM 返回 → 落库 + 剧本含 ## S 头。"""
    did, eid = _setup_episode(tmp_db)
    with mock.patch("app.pipeline.novel.runner.run_agent_json",
                    return_value=VALID_SCRIPT_JSON):
        script = novel.outline_to_script(SAMPLE_OUTLINE, episode_id=eid)

    # 校验返回
    assert "## S01|内景·咖啡馆|白天" in script
    assert "## S03" in script
    # 校验落库
    row = db.q1("SELECT script_content, content FROM episodes WHERE id=?", (eid,))
    assert row["script_content"] == script
    assert row["content"] == script  # 双写 content,方便 comic_pipeline 走 fallback


def test_empty_script_field_raises(tmp_db):
    """模型返回 dict 但 script 字段空 → RuntimeError。"""
    did, eid = _setup_episode(tmp_db)
    with mock.patch("app.pipeline.novel.runner.run_agent_json",
                    return_value={"script": ""}):
        with pytest.raises(RuntimeError, match="模型未返回 script"):
            novel.outline_to_script(SAMPLE_OUTLINE, episode_id=eid)


def test_non_json_response_raises(tmp_db):
    """模型返回非 dict(裸字符串) → RuntimeError,友好提示。"""
    did, eid = _setup_episode(tmp_db)
    with mock.patch("app.pipeline.novel.runner.run_agent_json",
                    return_value="not a json object"):
        with pytest.raises(RuntimeError, match="非 JSON"):
            novel.outline_to_script(SAMPLE_OUTLINE, episode_id=eid)


def test_script_without_scene_header_raises(tmp_db):
    """剧本不含 ## S\\d+\\| 头 → RuntimeError,防止下游 split_panels 爆。"""
    did, eid = _setup_episode(tmp_db)
    bad_script = "这是一些没有格式头的文字\n继续第二段"
    with mock.patch("app.pipeline.novel.runner.run_agent_json",
                    return_value={"script": bad_script}):
        with pytest.raises(RuntimeError, match="格式头"):
            novel.outline_to_script(SAMPLE_OUTLINE, episode_id=eid)
    # 失败时不应落库
    row = db.q1("SELECT script_content FROM episodes WHERE id=?", (eid,))
    assert row["script_content"] == ""


def test_unknown_episode_raises(tmp_db):
    """episode_id 不存在 → RuntimeError。"""
    # 也注入默认文本配置,prose_config_id 链路上游就需要
    db.ex(
        "INSERT INTO ai_service_configs(service_type,provider,base_url,api_key,model,is_active,created_at,updated_at)"
        " VALUES('text','openai','https://api.openai.com/v1','sk-test','gpt-test',1,?,?)",
        (db.now(), db.now()),
    )
    with pytest.raises(RuntimeError, match="剧集不存在"):
        novel.outline_to_script(SAMPLE_OUTLINE, episode_id=99999)
