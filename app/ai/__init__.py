# -*- coding: utf-8 -*-
"""AI 客户端包。

导入即启用 IPv4 优先:本机 IPv6 出口不可用,Cloudflare 域名(Agnes)会
在 IPv6 上卡满 connect timeout,生图每个角色白等约 2 分钟。
详见 app/core/net.py 的实测记录。
"""
from __future__ import annotations

from ..core.net import prefer_ipv4

prefer_ipv4()
