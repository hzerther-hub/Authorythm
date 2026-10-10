# -*- coding: utf-8 -*-
"""AI 操作前置检查:任何需要模型的按钮,点击瞬间先校验服务是否就绪。

不通过时立即以 toast 明确告知缺什么、去哪补,而不是让任务静默跑完再报错。
"""
from __future__ import annotations

from ..ai import registry
from ..ai.registry import NotConfigured

SVC_HINT = {
    "text": "AI 改写 / 资产提取 / 分镜 / 小说 / 审校 / 宣传文案",
    "image": "角色形象 / 场景 / 道具 / 漫画格 / 封面",
    "video": "镜头视频 / 图生视频",
    "tts": "旁白配音",
    "faceswap": "角色换脸",
}


def ensure_ready(service_type: str, config_id: int | None = None) -> bool:
    """就绪则返回 True;否则弹明确 toast 并返回 False(调用方应立即中止)。"""
    from PySide6.QtWidgets import QMessageBox
    try:
        registry.check_ready(service_type, config_id)
        return True
    except NotConfigured as e:
        # core 不该依赖 ui,而 ui 又依赖 core —— 局部导入,避免循环
        from ..ui.confirm import warn
        label = registry.SVC_CN_LABEL.get(service_type, service_type)
        msg = (f"{label}服务未就绪 — {e.reason}\n\n"
               f"影响:{SVC_HINT.get(service_type, service_type)}\n\n"
               "请到「设置 → AI 服务」补全配置后重试。")
        warn(None, "无法执行", msg)
        return False


def missing_summary() -> str:
    miss = registry.missing_services()
    if not miss:
        return ""
    names = "、".join(registry.SVC_CN_LABEL.get(m, m) for m in miss)
    return names
