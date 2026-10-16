# -*- coding: utf-8 -*-
"""Jev 的两个业务用途:生图供应商参考图能力判定 + 视频供应商路由。

**软建议器契约(两条用途都遵守,缺一不可)**:
任何一步失败都返回 None,由调用方按「原来的行为」继续 —— 没配 key / 连不通 /
熔断中 / JEV_ENABLED=0 / 解析异常,结果全都是 None。
调用方**永远有一个不依赖 Jev 的正确答案**,Jev 只在它可用时提供更优的答案。
本模块任何时候都不得抛出异常打断业务。

用途一 `reference_capable`:白名单之外的 provider 到底支不支持参考图?
    背景见 `image_client.REFERENCE_CAPABLE_PROVIDERS` 的注释 —— qwen-image /
    volcengine 请求体里没有图像字段,传了也丢,表现为「按参考图重绘」静默
    退化成纯文生图。白名单是硬编码的,新接一个供应商就得改代码。

用途二 `pick_video_provider`:按画面描述选视频供应商(choice 原语)。
    choice 返回的是**概率分布**而不是单一答案,正好对应"哪个更合适"。
"""
from __future__ import annotations

import os

from .jev_gate import JevBreaker, get_jev_gate

# 判定"是否真支持参考图"的提问。
#
# ⚠ **实测结论:这个判定不可用作真相源,只作诊断信息。**
# 在本项目真实的配置上跑出来的结果是**错的**:
#   qwen-image   base_url=token-plan.cn-beijing.maas.aliyuncs.com → jev 判 0.52~0.57「支持」
#   volcengine   base_url=ark.cn-beijing.volces.com                → jev 判 0.54~0.61「支持」
# 而这两个恰恰是 `image_client.REFERENCE_CAPABLE_PROVIDERS` 注释里记的、
# **实测确认会静默丢参考图**的 provider。
# 原因:看到知名大厂域名就按常识臆断"这种平台肯定支持图生图"。
# 拆成"请求体有没有图像字段"这种可查证事实来问也没用(仍判 0.52/0.54)——
# 是判断能力问题,不是提问方式问题。
#
# 所以:能力判定继续以白名单为唯一真相源(实测过的写进代码),
# 本函数保留为**只读诊断** —— 新接供应商时人工问一句,拿到线索后再实测验证、
# 把结论写进白名单。不要拿它的返回值驱动参考图的发送决策。
REF_QUESTIONS = {
    "binds_reference": {
        "type": "noul",
        "instructions": (
            "给定的图像模型是否真的支持「参考图 / 图生图」:会把参考图真正发给模型"
            "并受其约束,而不是静默忽略。1=支持并受约束,0=静默忽略(传了也没用)"),
    },
    "strictness": {
        "type": "score",
        "instructions": "该模型对参考图的约束强度",
        "criteria": ["忽略", "仅参考风格色调", "严格锁定主体"],
    },
}

REF_THRESHOLD = float(os.environ.get("JEV_REF_MIN_BIND", "0.45"))

_ref_breaker = JevBreaker("ref-capability")


def reference_capable(provider: str, base_url: str = "", model: str = "") -> bool | None:
    """该图像 provider 是否真支持参考图 —— **仅作诊断线索,不要当决策依据**。

    为什么不做成能力表的后备:见 REF_QUESTIONS 上方的实测记录 —— 在本项目真实
    配置上它把 qwen-image / volcengine 判成「支持」,与实测相反。
    新接供应商时用它拿个方向,然后**实测验证**、把结论写进
    `image_client.REFERENCE_CAPABLE_PROVIDERS`。返回值仅供参考。

    Jev 不可用/失败 → None。state 里带 base_url 和 model,信息越全线索越准。
    """
    if os.environ.get("JEV_REF_ASK") == "0":
        return None
    if _ref_breaker.in_cooldown():
        return None
    gate = get_jev_gate()
    if not gate.usable:
        return None
    state = (f"图像服务 provider={provider} base_url={base_url or '(未知)'} "
             f"model={model or '(未知)'}")
    try:
        result = gate.client.decide(state, REF_QUESTIONS)
    except Exception:  # noqa: BLE001 —— 软建议器契约:绝不外泄
        return None
    if not result or not result.get("answers"):
        _ref_breaker.note_fail()
        return None
    _ref_breaker.note_ok()
    answers = result["answers"]
    try:
        val = float((answers.get("binds_reference") or {}).get("noul"))
    except (TypeError, ValueError):
        return None
    strict = (answers.get("strictness") or {}).get("score")
    capable = val >= REF_THRESHOLD
    print(f"[jev] 参考图能力线索 {provider} bind={val} strict={strict} "
          f"-> {'疑似支持' if capable else '疑似不支持'}"
          f"(仅供参考,需实测验证后再写进白名单)", flush=True)
    return capable


# ── 视频供应商路由(choice 原语) ──────────────────────────────────

def video_provider_candidates() -> dict:
    """当前活跃的视频供应商 → 中文能力描述,作为 choice 的 criteria。

    criteria 必须**现取**:用户随时会增删改供应商配置,写死会路由到已删的 provider。
    描述取配置的 remark,回退到 provider 名 —— 让 jev 判"哪个更合适画面需求"。
    """
    from . import registry
    out: dict[str, str] = {}
    try:
        for row in registry.list_configs("video"):
            if not row.get("is_active"):
                continue
            key = f"{row['provider']}:{row['model']}"
            out[key] = (row.get("remark") or "").strip() or row["provider"]
    except Exception:  # noqa: BLE001
        return {}
    return out


def pick_video_provider(visual_need: str,
                        candidates: dict | None = None) -> tuple[str, dict] | None:
    """按画面需求选视频供应商,返回 (key, 概率分布)。不可用/无候选 → None。

    **必须显式调用**:本项目所有业务默认由用户在界面上选配置,不让 Jev 自动
    改写用户的选择(擅自换供应商 = 擅自换钱)。这里只提供建议,
    调用方决定要不要采纳,采纳前应向用户展示分布。
    """
    if os.environ.get("JEV_VIDEO_ROUTE") == "0":
        return None
    cands = candidates if candidates is not None else video_provider_candidates()
    if len(cands) < 2:
        return None                       # 只有一个候选,路由没有意义
    gate = get_jev_gate()
    if not gate.usable:
        return None
    question = {
        "best": {
            "type": "choice",
            "instructions": f"哪个视频供应商最适合产出这个画面:{visual_need}",
            "criteria": cands,
        },
    }
    state = f"画面需求:{visual_need}\n候选供应商及各自特点:" + ";".join(
        f"{k}={v}" for k, v in cands.items())
    try:
        result = gate.client.decide(state, question)
    except Exception:  # noqa: BLE001
        return None
    if not result or not result.get("answers"):
        return None
    best = (result["answers"].get("best") or {})
    # choice 的返回结构在不同网关版本上见过 {"choice": k} 与 {"choices": {k: p}} 两种,
    # 两种都认,认不出就返回 None 交调用方退回默认。
    picked = best.get("choice")
    # 分布字段名踩过坑:实测网关返回的是 `probabilities`,不是 `choices`。
    # 两个名字都认(不同网关版本见过两种),认不出分布就返回空 dict 不报错 ——
    # 分布只是给用户看的附加信息,选中的供应商才是结论。
    dist = best.get("probabilities") or best.get("choices") or {}
    if not picked and isinstance(dist, dict) and dist:
        picked = max(dist, key=lambda k: dist[k] if isinstance(dist[k], (int, float)) else -1)
    if picked not in cands:
        return None
    print(f"[jev] 视频供应商建议 {picked} dist={dist}(候选 {len(cands)})", flush=True)
    return picked, dist


def pick_video_config_advisory(visual_need: str) -> tuple[int, dict, bool] | None:
    """路由建议 + 是否值得当真。返回 (config_id, 分布, 低置信)。

    **实测:jev 的供应商判别力有限。** 在本项目两个候选上,
    「国产 3D 卡通渲染」给 0.62,「写实电影感雨夜追逐」给 0.59 —— 两种完全
    不同的需求都压倒性偏向同一个,区分度不足。分布接近(前二名差距 <0.15)
    时一律标记低置信,调用方应如实告诉用户「它也不确定」,别包装成明确建议。
    """
    from . import registry, video_client as vc
    got = pick_video_provider(visual_need)
    if not got:
        return None
    picked, dist = got
    cfg_id = None
    try:
        for row in registry.list_configs("video"):
            if row.get("is_active") and f"{row['provider']}:{row['model']}" == picked:
                cfg_id = row["id"]
                break
    except Exception:  # noqa: BLE001
        return None
    if cfg_id is None:
        return None
    vals = sorted((v for v in dist.values() if isinstance(v, (int, float))),
                  reverse=True)
    low = len(vals) < 2 or (vals[0] - vals[1]) < 0.15
    return cfg_id, dist, low
