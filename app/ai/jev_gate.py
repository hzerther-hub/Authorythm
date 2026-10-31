"""Jev 通用调用面 —— 客户端解析 + 按作用域熔断。

对齐参考项目 backend/src/services/jev-gate.ts。所有 Jev 业务调用(状态台账门控、
审校降噪、视频着装判读、未来的提示词预检等)都从这里拿客户端:
    1. 设置页 jev 活跃配置优先(UI 可改 key / 网关 / 模型)
    2. 环境变量回退(JEV_API_KEY + JEV_BASE_URL / JEV_API_URL)
    3. 都没有 → client=None(调用方跳过 Jev 逻辑,业务照常)

熔断:每个作用域独立计数,连续失败达阈值即开闸冷却,期间 in_cooldown()=True,
调用方直接跳过;成功一次即复位。全局开关 `JEV_ENABLED=0` 显式禁用一切 Jev 调用。
"""
from __future__ import annotations

import os
import time


class JevGate:
    """一次 Jev 可用性快照。"""

    def __init__(self, disabled: bool, client, reason: str | None):
        self.disabled = disabled          # JEV_ENABLED=0 → 业务完全跳过 Jev 步骤
        self.client = client              # 未就绪时为 None
        self.reason = reason              # disabled / unconfigured;可用时为 None

    @property
    def usable(self) -> bool:
        return not self.disabled and self.client is not None


def get_jev_gate() -> JevGate:
    """解析当前可用的 Jev 客户端(设置页配置优先,环境变量回退)。"""
    if os.environ.get("JEV_ENABLED") == "0":
        return JevGate(True, None, "disabled")
    try:
        from . import registry
        cfg = registry.default_config("jev")
        if cfg and (cfg.get("api_key") or "").strip() and (cfg.get("base_url") or "").strip():
            from .jev_client import JevClient
            return JevGate(False, JevClient(config_id=cfg["id"]), None)
    except Exception:  # noqa: BLE001 —— 配置读取失败走环境变量回退
        pass
    if not (os.environ.get("JEV_API_KEY") or "").strip():
        return JevGate(False, None, "unconfigured")
    from .jev_client import JevClient
    return JevGate(False, JevClient(), None)


class JevBreaker:
    """按作用域独立的熔断器(连续失败达阈值 → 冷却 → 成功即复位)。"""

    def __init__(self, scope: str, fail_threshold: int = 2, cooldown_ms: int = 10 * 60 * 1000):
        self.scope = scope
        self.fail_threshold = fail_threshold
        self.cooldown_ms = cooldown_ms
        self.fails = 0
        self.cooldown_until = 0.0

    def in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def cooldown_left_min(self) -> int:
        return int((self.cooldown_until - time.time()) // 60) + 1

    def note_fail(self) -> None:
        self.fails += 1
        if self.fails >= self.fail_threshold:
            self.cooldown_until = time.time() + self.cooldown_ms / 1000.0

    def note_ok(self) -> None:
        self.fails = 0
        self.cooldown_until = 0.0

    def skip_reason(self) -> str:
        return f"cooldown({self.cooldown_left_min()}m)"
