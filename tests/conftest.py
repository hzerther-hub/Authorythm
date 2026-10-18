# -*- coding: utf-8 -*-
"""全局测试夹具。"""
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
