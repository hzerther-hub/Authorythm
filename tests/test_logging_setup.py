# -*- coding: utf-8 -*-
"""logging_setup 的回归护栏:JSON 序列化 / 密钥脱敏 / 轮转。

注:`setup_logging` 会读 app_settings,但 db.get_setting 会触 db.init_db()。
测试期不连真实库,所以直接 monkeypatch 那个调用路径或传 level 入参。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from app.core import logging_setup


@pytest.fixture
def reset_logging():
    """每个测试前清掉 root logger 的 handlers,避免互相干扰。"""
    root = logging.getLogger()
    saved = list(root.handlers)
    for h in saved:
        root.removeHandler(h)
    yield
    for h in saved:
        root.removeHandler(h)


def test_setup_logging_creates_rotating_file(tmp_path, reset_logging, monkeypatch):
    """调用 setup_logging 后应在 DATA_DIR/logs/pydrama.log 落一行。"""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    # monkeypatch 必须把目录建好 —— RotatingFileHandler 不会自动建父目录
    monkeypatch.setattr(logging_setup, "_log_dir", lambda app_name="pydrama": log_dir)
    # 屏蔽 get_setting 调用
    monkeypatch.setattr("app.core.db.get_setting",
                        lambda k, d=None: {"log_level": "INFO", "log_to_stderr": "0"}.get(k, d))

    logging_setup.setup_logging(to_stderr=False)
    logging.getLogger("test.x").info("hello world")
    # handler 异步 flush,显式调用
    for h in logging.getLogger().handlers:
        h.flush()

    log_path = log_dir / "pydrama.log"
    assert log_path.exists()
    lines = [ln for ln in log_path.read_text("utf-8").splitlines() if ln.strip()]
    assert lines, "log file 为空"
    last = json.loads(lines[-1])
    assert last["level"] == "INFO"
    assert "hello world" in last["msg"]


def test_secrets_filter_strips_api_keys(tmp_path, reset_logging, monkeypatch):
    """敏感字段(sk-/Bearer/api_key)应在输出前被替换为 ***。"""
    # 直接对 _SecretsFilter 做单测,无需启动整套 logging
    f = logging_setup._SecretsFilter()
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "key=sk-abcdef1234567890abcdef token", None, None)
    f.filter(rec)
    assert "sk-***" in rec.msg
    assert "abcdef1234567890" not in rec.msg


def test_secrets_filter_handles_bearer_and_dict(monkeypatch):
    f = logging_setup._SecretsFilter()
    rec = logging.LogRecord("x", logging.INFO, __file__, 1,
                            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456", None, None)
    f.filter(rec)
    assert "Bearer ***" in rec.msg
    assert "abcdefghijklmnopqrstuvwxyz" not in rec.msg


def test_json_formatter_handles_extra_ctx(tmp_path, reset_logging, monkeypatch):
    """extra={...} 应落到 ctx 字段,普通 record 也能格式化。"""
    formatter = logging_setup._JsonFormatter()
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "msg", None, None)
    rec.__dict__["drama_id"] = 42
    out = formatter.format(rec)
    parsed = json.loads(out)
    assert parsed["msg"] == "msg"
    assert parsed["ctx"]["drama_id"] == 42


def test_setup_logging_is_idempotent(reset_logging, monkeypatch):
    """重复调用不会重复挂 handler(否则一行会输出多份)。"""
    monkeypatch.setattr("app.core.db.get_setting", lambda k, d=None: d)
    monkeypatch.setattr(logging_setup, "_log_dir",
                        lambda app_name="pydrama": Path("/tmp") / "logs")
    logging_setup.setup_logging()
    first = len(logging.getLogger().handlers)
    logging_setup.setup_logging()
    second = len(logging.getLogger().handlers)
    assert first == second
