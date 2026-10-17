# -*- coding: utf-8 -*-
"""网络兼容:优先 IPv4。

本机实测(2026-10-17):
- `apihub.agnes-ai.com` 同时有 A(104.18.x) 与 AAAA(2606:4700::...);
- 本机 IPv6 出口不可用,`Get-NetTCPConnection` 长期停在 `SynSent`;
- urllib3 的 `create_connection` 会先试 IPv6,在不可达地址上等满 connect
  timeout(Agnes 提交 timeout=120s),整次请求最终失败。
- `_batch_images` 串行跑 10 个角色时,每个角色白等约 2 分钟才轮到下一个,
  用户看到的就是「生成角色很慢、而且一直不出图」。

强制 urllib3 的 getaddrinfo 只返回 AF_INET。IPv4 出口正常(实测 1.5s 连通)。
需要恢复 IPv6 时可设 `YIHAO_FORCE_IPV4=0`。
"""
from __future__ import annotations

import os
import socket


def prefer_ipv4() -> None:
    """让 requests/urllib3 只解析 IPv4 地址(进程级,幂等)。"""
    if os.environ.get("YIHAO_FORCE_IPV4", "1") == "0":
        return
    try:
        import urllib3.util.connection as _conn
        _conn.allowed_gai_family = lambda: socket.AF_INET
    except Exception:  # noqa: BLE001 — 没有 urllib3 时不影响主流程
        pass
