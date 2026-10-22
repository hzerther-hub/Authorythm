# -*- coding: utf-8 -*-
"""API Key 加密 (secrets.py) 的回归护栏。

覆盖:
- encrypt/decrypt roundtrip
- `enc:` 前缀检测
- ensure_* 幂等性
- 迁移(migrate_unencrypted_keys)对历史明文值的升级
- 错误密文抛 SecretError(不静默返回空串)
- 空串不加密

注意隔离:monkeypatch DATA_DIR 到 tmp_path,防止覆盖用户的真实 data/.secret_salt。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core import secrets
from app.core import db


@pytest.fixture
def tmp_secrets_dir(tmp_path, monkeypatch):
    """重定向 DATA_DIR 到 tmp_path,清掉 secrets 缓存。

    secrets._get_fernet 会惰性生成 salt 并缓存 Fernet 实例 —— 不清缓存的话
    同一个 pytest 进程里第二次测试会复用旧 salt 与旧 Fernet,数据看上去"对"实则错。
    """
    monkeypatch.setattr(secrets.config, "DATA_DIR", tmp_path)
    # 防止测试间互相污染(切换 DATA_DIR 必须 reset)
    secrets._reset_for_testing()
    yield tmp_path
    secrets._reset_for_testing()


def test_encrypt_decrypt_roundtrip(tmp_secrets_dir):
    plain = "sk-abcdef1234567890abcdef"
    cipher = secrets.encrypt(plain)
    assert secrets.is_encrypted(cipher)
    assert secrets.decrypt(cipher) == plain


def test_encrypt_empty_string_returns_empty(tmp_secrets_dir):
    assert secrets.encrypt("") == ""
    assert secrets.encrypt(None) == ""  # type: ignore[arg-type]


def test_ensure_encrypted_idempotent(tmp_secrets_dir):
    plain = "sk-test-1234567890"
    once = secrets.ensure_encrypted(plain)
    twice = secrets.ensure_encrypted(once)
    assert once == twice, "ensure_encrypted 必须是幂等"
    assert secrets.decrypt(once) == plain


def test_ensure_decrypted_on_plain_returns_plain(tmp_secrets_dir):
    """明文值走 ensure_decrypted 应该原样返回(向后兼容旧值)。"""
    plain = "sk-test-not-yet-encrypted"
    assert secrets.ensure_decrypted(plain) == plain


def test_decrypt_garbage_raises(tmp_secrets_dir):
    """错误密文必须抛 SecretError(不能静默返回空串,那样业务侧就丢了 key 不知情)。"""
    with pytest.raises(secrets.SecretError):
        secrets.decrypt("enc:this-is-not-a-valid-fernet-token")


def test_decrypt_unencrypted_passthrough(tmp_secrets_dir):
    """不带 enc: 前缀的旧值直接返回(给迁移期接口兜底)。"""
    assert secrets.decrypt("legacy-plain-key") == "legacy-plain-key"


def test_salt_file_created_with_0600_on_unix(tmp_secrets_dir):
    """首次运行应在 DATA_DIR/.secret_salt 落 16 字节。"""
    # 调用一次触发 salt 生成
    secrets.encrypt("sk-trigger-salt-generation")
    salt_path = tmp_secrets_dir / ".secret_salt"
    assert salt_path.exists()
    assert len(salt_path.read_bytes()) == 16
    if os.name != "nt":
        mode = salt_path.stat().st_mode & 0o777
        assert mode == 0o600, f"salt 文件权限 {oct(mode)} 应为 0o600"


def test_salt_file_is_binary_even_with_newline_bytes(tmp_secrets_dir, monkeypatch):
    """salt 必须**按二进制**写:Windows 的 os.open 默认文本模式,随机 salt 里
    只要出现 0x0A 就会被翻成 0x0D0A → 文件变 17 字节 → 下次启动读到的 salt
    与当次派生的密钥对不上,密文永久解不开(实测 1/16 概率触发)。
    """
    tricky = b"\x0a" + b"\x1a" + b"\x0d" + b"x" * 13     # 含换行符与 Ctrl-Z
    assert len(tricky) == 16
    monkeypatch.setattr(secrets.os, "urandom", lambda n: tricky)

    salt = secrets._load_or_create_salt()
    salt_path = tmp_secrets_dir / ".secret_salt"
    assert salt_path.exists()
    assert salt_path.read_bytes() == tricky, "salt 文件被文本模式改写了(换行符被翻译)"
    assert len(salt_path.read_bytes()) == 16
    assert salt == tricky


# ── 迁移(migrate_unencrypted_keys)──

@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """与 test_stuck_task_watchdog 同款,清 thread-local 连接。"""
    path = tmp_path / "t.sqlite3"
    monkeypatch.setattr(db.config, "DB_PATH", path)
    monkeypatch.setattr(db.config, "DATA_DIR", tmp_path)
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    yield path
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


def test_migrate_unencrypted_keys_upgrades_legacy(tmp_db, tmp_path):
    """直接往库里塞旧明文值,调 migrate_unencrypted_keys 应当升级为 enc:...。"""
    # 插一条明文
    db.ex(
        "INSERT INTO ai_service_configs(service_type,provider,base_url,api_key,model,is_active,created_at,updated_at)"
        " VALUES('text','openai','https://api.openai.com/v1','sk-old-plain-key','gpt-5.6-terra',1,?,?)",
        (db.now(), db.now()),
    )

    # secrets 缓存清掉
    secrets._reset_for_testing()
    out = secrets.migrate_unencrypted_keys()

    assert out["scanned"] == 1
    assert out["migrated"] == 1
    assert out["failed"] == 0

    # 再读,应当是 enc:... 前缀
    row = db.q1("SELECT api_key FROM ai_service_configs WHERE service_type='text'")
    assert row["api_key"].startswith("enc:")

    # 业务侧 list_configs() 应当自动解密回来
    from app.ai import registry
    cfgs = registry.list_configs("text")
    assert cfgs[0]["api_key"] == "sk-old-plain-key"


def test_migrate_skips_already_encrypted(tmp_db):
    """已是 enc:... 的值不应被二次加密。"""
    # 先 add_config(走加密路径)
    from app.ai import registry
    cid = registry.add_config("text", "openai", "https://api.openai.com/v1", "gpt-5.6-terra",
                              api_key="sk-test-already-encrypted-12345678")
    secrets._reset_for_testing()
    out = secrets.migrate_unencrypted_keys()
    assert out["migrated"] == 0
    # 再加一条(应该仍能正常加密)
    registry.update_config(cid, api_key="sk-second-key-1234567890")
    secrets._reset_for_testing()
    row = db.q1("SELECT api_key FROM ai_service_configs WHERE id=?", (cid,))
    assert row["api_key"].startswith("enc:")
    assert secrets.decrypt(row["api_key"]) == "sk-second-key-1234567890"
