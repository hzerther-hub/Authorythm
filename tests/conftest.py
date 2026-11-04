"""全局测试夹具。"""
from __future__ import annotations

import shutil

import pytest


@pytest.fixture(autouse=True)
def _reset_secrets_cache():
    """secrets 的 Fernet 实例按 DATA_DIR 派生并缓存。

    某些测试 monkeypatch config.DATA_DIR / 换 salt 后,缓存里的 Fernet 与
    后续测试要解的密文不匹配(InvalidSignature)。每个测试结束后强制重置,
    下次访问按当前 DATA_DIR 重新派生。
    """
    yield
    try:
        from app.core import secrets
        secrets._reset_for_testing()
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture(autouse=True, scope="session")
def _isolate_real_db(tmp_path_factory):
    """**测试绝不碰真实库** data/yihao.sqlite3(CLAUDE.md 第 1 条)。

    起因(2026-11-02 实测):`test_lang_switch` / `test_chat_intent` /
    `test_stock_photo` 这几个 UI 用例会构造 MainWindow / 聊天抽屉,连带触发
    `db.set_setting` 与 `INSERT INTO chat_edit_sessions` —— 写的是**用户的真库**。
    跑一次全量 pytest,真库的 app_settings 就多一条 yihao.editor_font_size、
    chat_edit_sessions 就多几行会话记录。

    修法:整轮测试用**真实库的副本**当库。
      · 用副本而不是空库 —— 有些用例依赖真库里的既有数据(如 video_clone 那些
        「库里没有小体量项目」的 skip 判定),副本能让它们的行为与改前完全一致;
      · 只在 session 级改一次 —— 避免每个用例拷一次 8MB 库(930 个用例太慢);
      · DATA_DIR 不动 —— salt/静态资源仍在原处,密钥解密不受影响。

    用例自带的 tmp_db 夹具照旧生效(monkeypatch 会把它盖成用例自己的临时库)。
    """
    from app.core import config, db

    real = config.DB_PATH
    if not real.exists():
        yield
        return
    copied = tmp_path_factory.mktemp("real_db") / "yihao.sqlite3"
    shutil.copy2(real, copied)
    old_path = config.DB_PATH
    old_conn = getattr(db._local, "conn", None)
    if old_conn is not None:
        old_conn.close()
    db._local.conn = None
    config.DB_PATH = copied
    try:
        yield
    finally:
        config.DB_PATH = old_path
        conn = getattr(db._local, "conn", None)
        if conn is not None:
            conn.close()
        db._local.conn = None
