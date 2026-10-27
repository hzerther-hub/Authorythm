# -*- coding: utf-8 -*-
"""把存量 api_key 密文从「含用户名」的旧指纹迁移到「主机名+MAC」新指纹。

背景(2026-10-27 实测):`secrets._machine_fingerprint` 原来含
`getpass.getuser()`,同一台机器用 Administrator 与 user 两个账户先后启动
应用 → 双方加密的密文互相对不上,全部 key 解不开,设置弹窗构造即崩。
指纹剔除用户名后,旧格式密文需要本脚本一次性解开并用新指纹重加密。

- 幂等:新指纹能解开的行直接跳过,重复跑无副作用。
- 候选旧指纹:user / Administrator / 当前用户(主机名+MAC 不变)。
- 绝不打印任何密钥明文;改库前自动备份 DB 到 data/*.bak-keymigration。
- 新增候选用户名:在 CANDIDATE_USERS 里补一行再跑即可。

用法:python scripts/migrate_secrets_fingerprint.py
"""
from __future__ import annotations

import base64
import getpass
import platform
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "yihao.sqlite3"
SALT_PATH = ROOT / "data" / ".secret_salt"
PREFIX = "enc:"
_PBKDF2_ITERS = 200_000

CANDIDATE_USERS = ["user", "Administrator"]


def _fernet_for(fingerprint: str, salt: bytes) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_PBKDF2_ITERS
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(fingerprint.encode("utf-8", "replace"))))


def main() -> int:
    if not DB_PATH.exists() or not SALT_PATH.exists():
        print(f"缺文件:{DB_PATH if not DB_PATH.exists() else SALT_PATH}", file=sys.stderr)
        return 1
    salt = SALT_PATH.read_bytes()

    node = platform.node() or "unknown"
    mac = str(uuid.getnode())
    new_f = _fernet_for(f"{node}|{mac}", salt)

    users = list(dict.fromkeys([getpass.getuser(), *CANDIDATE_USERS]))
    old_fernets = [(u, _fernet_for(f"{u}|{node}|{mac}", salt)) for u in users]

    backup = DB_PATH.with_suffix(".sqlite3.bak-keymigration-"
                                 + datetime.now().strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(DB_PATH, backup)
    print(f"已备份 → {backup.name}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, service_type, provider, api_key FROM ai_service_configs "
        "WHERE api_key IS NOT NULL AND api_key LIKE 'enc:%'"
    ).fetchall()

    kept = migrated = failed = 0
    for r in rows:
        token = r["api_key"][len(PREFIX):]
        try:
            new_f.decrypt(token.encode("ascii"))
            kept += 1
            continue                       # 已是新格式(或本机指纹本就匹配)
        except InvalidToken:
            pass
        except Exception:
            failed += 1
            continue
        plain = None
        for user, f in old_fernets:
            try:
                plain = f.decrypt(token.encode("ascii")).decode("utf-8")
                used_user = user
                break
            except InvalidToken:
                continue
            except Exception:
                continue
        if plain is None:
            failed += 1
            print(f"  ✗ id={r['id']} ({r['service_type']}/{r['provider']}) "
                  f"所有候选指纹都解不开,保持原样")
            continue
        new_cipher = PREFIX + new_f.encrypt(plain.encode("utf-8")).decode("ascii")
        conn.execute("UPDATE ai_service_configs SET api_key=? WHERE id=?",
                     (new_cipher, r["id"]))
        migrated += 1
        print(f"  ✓ id={r['id']} ({r['service_type']}/{r['provider']}) "
              f"经用户「{used_user}」指纹解开,已重加密")

    conn.commit()
    conn.close()
    print(f"完成:已是新格式 {kept} / 迁移 {migrated} / 解不开 {failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
