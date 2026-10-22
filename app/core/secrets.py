# -*- coding: utf-8 -*-
"""API Key 加密:基于 Fernet,机器指纹派生密钥,salt 存 data/.secret_salt。

设计要点:
- 算法:`cryptography.fernet.Fernet`(AES-128-CBC + HMAC-SHA256,标准做法)。
- 密钥派生:`PBKDF2HMAC(SHA256, 200_000 轮, salt, 32 bytes)`。
  - 输入 = `getpass.getuser() + platform.node() + str(uuid.getnode())`。
  - **不要把派生输入本身写盘**:只存 salt。
- 存储格式:`enc:<base64-fernet-token>`,加 `enc:` 前缀便于检测旧明文值。
- 迁移:`migrate_unencrypted_keys()` 启动时一次性扫表,旧值批量升级为
  `enc:...` 后写回。失败只警告不删旧值(可选:加 `api_key_legacy TEXT` 字段,
  本轮不引入,出问题靠 git 找回)。
- 跨平台:Windows / macOS / Linux 均一致;`data/.secret_salt` 用 os.urandom(16),
  Unix 强设 0600 权限,Windows 跳过(chmod 无效)。
- 冻结构建兼容:`cryptography` 自带 PyInstaller hook,无需特殊处理。

API:
    encrypt(plain) -> str           # 加 enc: 前缀
    decrypt(cipher) -> str          # 去掉 enc: 前缀并解密
    is_encrypted(s) -> bool         # 以 enc: 前缀判定
    ensure_encrypted(s) -> str      # 幂等
    ensure_decrypted(s) -> str      # 幂等
    migrate_unencrypted_keys()      # 启动期调用,扫表迁移
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import os
import platform
import threading
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from . import config  # 用于 DATA_DIR 派生;测试 monkeypatch 改 config.DATA_DIR


PREFIX = "enc:"
_PBKDF2_ITERS = 200_000
_SALT_BYTES = 16
_LOCK = threading.Lock()
_FERNET: Fernet | None = None


class SecretError(RuntimeError):
    """密文无法解密(改了机器/用户/盐;或密文被破坏)。"""


# ── 路径与盐 ──────────────────────────────────────────────────────────────

def _data_dir() -> Path:
    try:
        base = config.DATA_DIR
    except Exception:  # noqa: BLE001
        base = Path.cwd() / "data"
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _salt_path() -> Path:
    return _data_dir() / ".secret_salt"


def _load_or_create_salt() -> bytes:
    """salt 路径:data/.secret_salt。首次运行用 os.urandom(16) 生成。

    Unix 0600,Windows 跳过 chmod。

    **必须原子创建**:原来的写法是「exists() 就读,否则 write_bytes()」——
    两个进程同时启动(应用 + pytest + 诊断脚本,本项目记录过这个场景)会
    各自生成一份 salt,后写者覆盖前者 → 先启动那进程用 salt A 加密、
    文件里却是 salt B → 落库的密文**永久解不开**。
    更糟的是 write_bytes 是「截断 + 写」,此刻另一个进程可能读到**空 salt**
    并据此派生密钥,写进去的密文同样不可解。
    现在用 O_CREAT|O_EXCL 原子创建:O_EXCL 失败说明别人先建了 → 读它的。
    """
    p = _salt_path()
    salt = os.urandom(_SALT_BYTES)
    try:
        # O_EXCL:文件已存在就抛 FileExistsError —— 不会截断、不会覆盖
        #
        # ⚠️ Windows 必须加 O_BINARY:os.open 默认是**文本模式**,随机 salt 里
        # 只要有一个 0x0A 就会被翻成 0x0D0A → 文件变成 17 字节,下次启动读到的
        # salt 与当次派生的密钥对不上 → 密文永久解不开(实测 1/16 概率触发)。
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(str(p), flags, 0o600)
        try:
            written = os.write(fd, salt)
            if written != _SALT_BYTES:
                raise OSError(f"salt 写入不完整:{written}/{_SALT_BYTES}")
        finally:
            os.close(fd)
        return salt
    except FileExistsError:
        pass                     # 别人先建好了 → 用它那份
    except OSError:
        pass
    try:
        data = p.read_bytes()
        if data:
            return data
    except OSError:
        pass
    # 读不到(权限/空文件)→ 退回到写自己的,并明确记录
    try:
        p.write_bytes(salt)
    except OSError:
        pass
    return salt


# ── 密钥派生 ──────────────────────────────────────────────────────────────

def _machine_fingerprint() -> str:
    """机器指纹:用户名 + 主机名 + MAC 地址。"""
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "unknown"
    try:
        node = platform.node() or "unknown"
    except Exception:  # noqa: BLE001
        node = "unknown"
    try:
        mac = str(uuid.getnode())
    except Exception:  # noqa: BLE001
        mac = "unknown"
    return f"{user}|{node}|{mac}"


def _derive_key(salt: bytes) -> bytes:
    """从机器指纹 + salt 派生出 32 字节(URL-safe base64),Fernet 直接吃这个。"""
    raw = _machine_fingerprint().encode("utf-8", errors="replace")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERS,
    )
    return base64.urlsafe_b64encode(kdf.derive(raw))


def _get_fernet() -> Fernet:
    global _FERNET
    with _LOCK:
        if _FERNET is None:
            salt = _load_or_create_salt()
            _FERNET = Fernet(_derive_key(salt))
        return _FERNET


# 允许测试时强制重置缓存(切 salt / 切指纹后必须调)
def _reset_for_testing() -> None:
    global _FERNET
    with _LOCK:
        _FERNET = None


# ── 公开 API ──────────────────────────────────────────────────────────────

def is_encrypted(s: str) -> bool:
    """是否已加密(以 `enc:` 前缀判定)。空串返回 False。"""
    if not s:
        return False
    return s.startswith(PREFIX)


def encrypt(plain: str) -> str:
    """加密。空串直接返回空串(避免空 key 产生密文后判为已加密)。"""
    if plain is None or plain == "":
        return ""
    if is_encrypted(plain):
        return plain
    f = _get_fernet()
    token = f.encrypt(plain.encode("utf-8")).decode("ascii")
    return PREFIX + token


def decrypt(cipher: str) -> str:
    """解密。空串 / 未加密值原样返回;InvalidToken 抛 SecretError。"""
    if not cipher:
        return ""
    if not is_encrypted(cipher):
        return cipher
    f = _get_fernet()
    try:
        return f.decrypt(cipher[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError, base64.binascii.Error) as e:
        raise SecretError(f"API Key 解密失败(可能换了机器或 salt 损坏): {e}") from e


def ensure_encrypted(s: str) -> str:
    """幂等:已是密文就原样返回,明文就加密。"""
    if not s:
        return ""
    return s if is_encrypted(s) else encrypt(s)


def ensure_decrypted(s: str) -> str:
    """幂等:已加密就解密,明文就原样返回。"""
    if not s:
        return ""
    return decrypt(s) if is_encrypted(s) else s


# ── 启动期迁移 ────────────────────────────────────────────────────────────

def migrate_unencrypted_keys() -> dict[str, int]:
    """扫描 ai_service_configs.api_key,把明文值升级为 enc:...。

    返回 {"scanned": N, "migrated": M, "failed": F}。
    失败只记录,不让启动阻塞。调用方负责打日志。
    """
    from . import db
    out = {"scanned": 0, "migrated": 0, "failed": 0}
    try:
        rows = db.q("SELECT id, api_key FROM ai_service_configs WHERE api_key IS NOT NULL AND api_key<>''")
    except Exception:
        return out
    for r in rows:
        out["scanned"] += 1
        v = r["api_key"] or ""
        if not v or is_encrypted(v):
            continue
        try:
            new = encrypt(v)
            db.ex("UPDATE ai_service_configs SET api_key=?, updated_at=? WHERE id=?",
                  (new, db.now(), int(r["id"])))
            out["migrated"] += 1
        except Exception:
            out["failed"] += 1
    return out
