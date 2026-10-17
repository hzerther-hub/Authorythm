# -*- coding: utf-8 -*-
"""IPv4 优先:防止生图在不可达的 IPv6 上等满 connect timeout。

现场:apihub.agnes-ai.com 同时有 A/AAAA,本机 IPv6 无出口,
urllib3 先连 IPv6 会卡在 SynSent;Agnes 提交 timeout=120s,
批量 10 个角色每个白等约 2 分钟且全部失败。
"""
from __future__ import annotations

import socket


def test_ai_package_forces_ipv4():
    import app.ai  # noqa: F401  导入即触发 prefer_ipv4()
    import urllib3.util.connection as uc

    assert uc.allowed_gai_family() == socket.AF_INET
