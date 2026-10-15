# -*- coding: utf-8 -*-
"""TypeSafe AI / Jev 客户端 —— 状态台账门控与预审软建议。

对齐参考项目 backend/src/services/adapters/moderation/jev.ts。
端点 POST {base_url}/v1/systemone,question 原语三种:
    noul   —— 布尔/置信度          {type, instructions}
    choice —— 分类 + 概率分布      {type, instructions, criteria: {k: 描述}}
    score  —— 序数评分(下标即等级) {type, instructions, criteria: [...]}

**软建议器契约:任何失败都返回 None,绝不抛异常。**
生成热路径上调用时若 Jev 挂了,必须 0 阻塞地走默认流程。
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import requests

DEFAULT_BASE = "https://api.typesafe.ai"
# 未配置时提示用:官网(申请 Access Key 的入口)
JEV_URL = "https://typesafe.ai/"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT_S = 8.0
DEFAULT_CACHE_TTL_S = 5 * 60

# 连通性探针用(对齐参考项目 aiConfigs.ts 的 p === 'jev' 分支)
PING_QUESTIONS = {"ok": {"type": "noul", "instructions": "reply ok"}}


def provider_routing_questions() -> dict:
    """provider 路由软建议三问(参考项目保留的预制模板,供扩展点使用)。"""
    return {
        "will_trigger_realperson_policer": {
            "type": "noul",
            "instructions": "生成内容是否会触发真人形象审核拦截",
        },
        "best_provider": {
            "type": "choice",
            "instructions": "哪个 provider 出片最合适",
            "criteria": {
                "volcengine_doubao_seedance": "国产 3D 动画与国风画面",
                "agnes_3dcg": "3D CG 卡通渲染",
                "aliyun_wan": "写实与通用视频",
            },
        },
        "violence_level": {
            "type": "score",
            "instructions": "暴力/敏感等级",
            "criteria": ["无", "轻度", "中度", "重度"],
        },
    }


class JevClient:
    """Jev 决策客户端(带 TTL 缓存,失败一律 None)。"""

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "",
                 timeout_s: float | None = None, cache_ttl_s: float | None = None,
                 config_id: int | None = None):
        from . import registry
        cfg = registry.default_config("jev", config_id) if config_id is not None else None
        if cfg is None and config_id is None:
            cfg = registry.default_config("jev")
        self.config_id = (cfg or {}).get("id") if cfg else config_id
        self.api_key = (cfg or {}).get("api_key") or api_key or os.environ.get("JEV_API_KEY", "").strip()
        # 环境变量双命名:JEV_BASE_URL(本仓库惯例)/ JEV_API_URL(兼容配置名)
        self.base_url = ((cfg or {}).get("base_url")
                         or api_key and base_url
                         or os.environ.get("JEV_BASE_URL")
                         or os.environ.get("JEV_API_URL")
                         or base_url
                         or DEFAULT_BASE).rstrip("/")
        self.model = (cfg or {}).get("model") or model or os.environ.get("JEV_MODEL") or DEFAULT_MODEL
        if timeout_s is not None:
            self.timeout_s = float(timeout_s)
        else:
            # JEV_TIMEOUT_MS 毫秒 / JEV_TIMEOUT 秒(兼容名,×1000)
            sec = os.environ.get("JEV_TIMEOUT")
            if sec and sec.isdigit() and int(sec) > 0:
                self.timeout_s = int(sec)
            else:
                ms = os.environ.get("JEV_TIMEOUT_MS")
                self.timeout_s = (int(ms) / 1000.0) if (ms or "").isdigit() and int(ms) > 0 else DEFAULT_TIMEOUT_S
        self.cache_ttl_s = cache_ttl_s if cache_ttl_s is not None else float(
            os.environ.get("JEV_CACHE_TTL_MS") or DEFAULT_CACHE_TTL_S) / 1000.0
        self._cache: dict[str, tuple[float, dict]] = {}

    def is_configured(self) -> bool:
        return bool(self.api_key) and bool(self.base_url)

    def decide(self, state: str, questions: dict) -> dict | None:
        """POST /v1/systemone。任何错误都吞掉返回 None —— 这是软建议器。"""
        if not self.is_configured() or not state or not questions:
            return None
        key = self._hash_request(state, questions)
        hit = self._cache.get(key)
        if hit and hit[0] > time.time():
            return {**hit[1], "cached": True}
        started = time.time()
        try:
            resp = requests.post(
                f"{self.base_url}/v1/systemone",
                headers={"Authorization": f"Bearer {self.api_key}",
                         "Content-Type": "application/json"},
                json={"model": self.model, "state": state, "questions": questions},
                timeout=self.timeout_s,
            )
            if resp.status_code >= 400:
                return None                      # 不在热路径刷错误日志,交给上层观测
            data = resp.json() or {}
            result = {
                "model": data.get("model") or self.model,
                "answers": data.get("answers") or {},
                "usage": {
                    "input_tokens": (data.get("usage") or {}).get("input_tokens", 0),
                    "output_tokens": (data.get("usage") or {}).get("output_tokens", 0),
                },
                "elapsed_ms": int((time.time() - started) * 1000),
                "cached": False,
            }
            self._cache[key] = (time.time() + self.cache_ttl_s, result)
            return result
        except Exception:  # noqa: BLE001  —— 软建议器契约:一律 None
            return None

    def ping(self) -> dict | None:
        """连接测试:与运行期同一条通路,一次验完鉴权/可达性/端点。"""
        return self.decide("ping", PING_QUESTIONS)

    def _hash_request(self, state: str, questions: dict) -> str:
        payload = json.dumps({"s": state, "q": questions, "m": self.model},
                             ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:24]   # 截断即可,只要稳定


def test_config(config_id: int | dict | None = None) -> tuple[bool, str]:
    """设置页「连接测试」。返回 (是否通过, 说明)。

    config_id 既接受**配置 id(int)**,也接受**整行配置 dict** —— 设置页
    ServiceDialog._test 把 `self._collect()` 的结果(一个 dict)当第一个位置参数
    传进来,原先这里签名写的是 int,dict 一路传到 registry.default_config() 就被
    当 SQL 参数绑 → "type 'dict' is not supported"。两种都兼容掉。
    """
    if isinstance(config_id, dict):
        api_key = (config_id.get("api_key") or "").strip()
        base_url = (config_id.get("base_url") or "").strip() or DEFAULT_BASE
        model = (config_id.get("model") or "").strip() or DEFAULT_MODEL
        if not api_key:
            return False, f"未配置 API Key —— 申请入口:{JEV_URL}"
        client = JevClient(api_key=api_key, base_url=base_url, model=model)
    else:
        client = JevClient(config_id=config_id)
    if not client.is_configured():
        return False, "未配置 API Key"
    res = client.ping()
    if res is None:
        return False, f"无法连接 {client.base_url}/v1/systemone(鉴权失败或网络不通)"
    if "ok" not in (res.get("answers") or {}):
        return False, "端点可达但未返回预期答案"
    usage = res.get("usage") or {}
    return True, (f"{res['model']} · {res['elapsed_ms']}ms · "
                  f"in {usage.get('input_tokens', 0)} / out {usage.get('output_tokens', 0)}")