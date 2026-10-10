# -*- coding: utf-8 -*-
"""AI 服务配置注册表:六类服务(text/image/video/tts/faceswap/jev)多供应商 CRUD + 默认项 + 连通测试。"""
from __future__ import annotations

from ..core import db

SERVICE_TYPES = ["text", "image", "video", "tts", "faceswap", "jev"]

# 手动模板预设(对齐原版「添加服务」对话框:模板快选自动填入 Base URL 与默认模型)
PROVIDER_PRESETS: dict[str, list[dict]] = {
    "text": [
        {"name": "Gemini 官方", "provider": "gemini",
         "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
         "models": ["gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3-flash-preview"]},
        {"name": "OpenAI 官方", "provider": "openai", "base_url": "https://api.openai.com/v1",
         "models": ["deepseek-v4-pro", "deepseek-v4-flash", "gpt-5.6-terra"]},
        {"name": "MiniMax 官方", "provider": "minimax", "base_url": "https://api.minimaxi.com/v1",
         "models": ["MiniMax-M3", "MiniMax-M2.5", "MiniMax-M2"]},
        {"name": "Agnes 官方", "provider": "agnes", "base_url": "https://apihub.agnes-ai.com",
         "models": ["agnes-3.0-flash", "agnes-2.5-pro", "agnes-2.5-flash"]},
    ],
    "image": [
        {"name": "Agnes 官方", "provider": "agnes", "base_url": "https://apihub.agnes-ai.com",
         "models": ["agnes-image-2.5-flash", "agnes-image-2.1-flash", "agnes-image-2.0-flash"]},
        {"name": "OpenAI 官方", "provider": "openai", "base_url": "https://api.openai.com/v1",
         "models": ["gpt-image-2"]},
        {"name": "Gemini 官方", "provider": "gemini",
         "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
         "models": ["gemini-3-pro-image", "gemini-3.1-flash-image"]},
        {"name": "火山方舟 Doubao Seedream", "provider": "volcengine",
         "base_url": "https://ark.cn-beijing.volces.com/api/v3",
         "models": ["doubao-seedream-5-0-260128"]},
        {"name": "百炼图像 · Qwen-Image / 万相", "provider": "qwen-image",
         "base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com",
         "models": ["qwen-image-3.0-pro", "wan2.7-image", "wan2.7-image-pro"]},
        # 本地生图(零云额度、数据不出本机;对齐参考 0117459 移植的三个 provider)
        {"name": "本地 ComfyUI", "provider": "comfyui",
         "base_url": "http://127.0.0.1:8188",
         "models": ["sd_xl_base_1.0.safetensors", "default"]},
        {"name": "本地 SD WebUI (AUTOMATIC1111)", "provider": "sdwebui",
         "base_url": "http://127.0.0.1:7860", "models": ["default"]},
        {"name": "本地 Fooocus-API", "provider": "fooocus",
         "base_url": "http://127.0.0.1:8888", "models": ["default"]},
    ],
    "video": [
        {"name": "Agnes 官方", "provider": "agnes", "base_url": "https://apihub.agnes-ai.com",
         "models": ["agnes-video-2.5-flash", "agnes-video-2.5"]},
        {"name": "火山方舟 Doubao Seedance 2.0", "provider": "volcengine",
         "base_url": "https://ark.cn-beijing.volces.com/api/v3",
         "models": ["doubao-seedance-2-0-mini-260615", "doubao-seedance-2-0-fast-260128",
                    "doubao-seedance-2-0-260128"]},
        {"name": "MiniMax 官方", "provider": "minimax", "base_url": "https://api.minimaxi.com/v1",
         "models": ["MiniMax-H3"]},
        {"name": "阿里云百炼 · Wan 3.0 / HappyHorse", "provider": "aliyun",
         "base_url": "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com",
         "models": ["wan3.0-video", "wan3.0-video-prime", "happyhorse-1.1-t2v",
                    "happyhorse-1.1-i2v", "happyhorse-1.1-r2v"]},
        {"name": "RunningHub · Seedance 2.5 / Wan 3.0", "provider": "runninghub",
         "base_url": "https://www.runninghub.cn",
         "models": ["seedance-2.5", "wan3.0-video", "wan3.0-video-prime"]},
        {"name": "小云雀(剪映) Seedance / 多模型", "provider": "xiaoyunque",
         "base_url": "https://xyq.jianying.com",
         "models": ["Seedance_2.5", "seedance2.0_fast_vision", "seedance2.0_vision", "Seedance_2.0_mini"]},
    ],
    "tts": [
        {"name": "豆包语音(火山引擎)", "provider": "volcengine",
         "base_url": "https://openspeech.bytedance.com",
         "models": ["zh_female_shuangkuaisisi_uranus_bigtts",
                    "zh_male_roucheng_uranus_bigtts", "zh_female_cancan_uranus_bigtts"]},
    ],
    "faceswap": [
        {"name": "本地换脸服务 · InsightFace", "provider": "local-faceswap",
         "base_url": "http://127.0.0.1:5678", "models": ["face-swap"]},
        {"name": "远程换脸服务 · FaceMe", "provider": "remote-faceswap",
         "base_url": "https://face.mei.biz", "models": ["face-swap"]},
    ],
    # Jev 不是生成式 provider:它是 TypeSafe AI 的结构化决策/判读端点(/v1/systemone),
    # 所以不进 adapters,只作为第六类服务登记。
    "jev": [
        {"name": "TypeSafe AI · Jev", "provider": "jev",
         "base_url": "https://api.typesafe.ai", "models": ["jev-latest"]},
    ],
}

SVC_CN = {"text": "文本", "image": "图片", "video": "视频", "tts": "配音", "faceswap": "换脸",
         "jev": "Jev"}

# 各 provider 的可选模型候选(新建时展示;对齐原版设置页展示)
MODEL_CHOICES: dict[str, list[str]] = {
    "minimax": ["MiniMax-M3", "MiniMax-M2.5", "MiniMax-M2.7", "MiniMax-M2.1", "MiniMax-H3"],
    "agnes": ["agnes-3.0-flash", "agnes-2.5-pro", "agnes-2.5-flash",
              "agnes-image-2.5-flash", "agnes-image-2.1-flash", "agnes-image-2.0-flash",
              "agnes-video-2.5-flash", "agnes-video-2.5"],
    "volcengine": ["doubao-seedance-2-0", "doubao-seedance-2-0-fast", "doubao-seedance-2-0-mini", "doubao-seedream-4-0"],
    "aliyun": ["wan3.0-video", "wan3.0-video-prime", "happyhorse-1.1-t2v",
               "happyhorse-1.1-i2v", "happyhorse-1.1-r2v"],
    # 小云雀沉浸式短片 API 的 model 枚举(文档 v1.0.6;非 VIP 账号仅 mini_lite 可用)
    "xiaoyunque": ["Seedance_2.5", "seedance2.0_fast_vision", "seedance2.0_vision", "Seedance_2.0_mini",
                   "MiniMax-H3", "MiniMax-H3-Max", "wan3.0", "happyhorse-1.1", "Seedance_2.0_mini_lite"],
}


def list_configs(service_type: str | None = None) -> list:
    if service_type:
        return db.q("SELECT * FROM ai_service_configs WHERE service_type=? ORDER BY is_default DESC, priority DESC, id",
                    (service_type,))
    return db.q("SELECT * FROM ai_service_configs ORDER BY service_type, is_default DESC, id")


def add_config(service_type: str, provider: str, base_url: str, model: str,
               api_key: str = "", is_default: bool = False, remark: str = "",
               priority: int = 0, models: list[str] | None = None,
               temperature: float | None = None) -> int:
    ts = db.now()
    if is_default:
        db.ex("UPDATE ai_service_configs SET is_default=0 WHERE service_type=?", (service_type,))
    elif not db.q1("SELECT id FROM ai_service_configs WHERE service_type=?", (service_type,)):
        is_default = True  # 该类型第一条配置自动设为默认
    import json as _json
    return db.ex(
        "INSERT INTO ai_service_configs(service_type,provider,base_url,api_key,model,is_default,is_active,remark,priority,models,temperature,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?)",
        (service_type, provider, base_url, api_key, model,
         1 if is_default else 0, remark, priority,
         _json.dumps(models or [model], ensure_ascii=False),
         temperature, ts, ts))


def update_config(cid: int, **fields) -> None:
    import json as _json
    sets, vals = [], []
    for k in ("provider", "base_url", "api_key", "model", "remark"):
        if k in fields and fields[k] is not None:
            sets.append(f"{k}=?"); vals.append(fields[k])
    if "settings" in fields:                     # 本地生图扩展设置(JSON 字符串;空串存 NULL)
        sets.append("settings=?")
        vals.append(fields["settings"] or None)
    if "models" in fields and fields["models"] is not None:
        sets.append("models=?")
        vals.append(_json.dumps(fields["models"], ensure_ascii=False))
    if "temperature" in fields:
        sets.append("temperature=?")
        vals.append(fields["temperature"])
    if "priority" in fields and fields["priority"] is not None:
        sets.append("priority=?"); vals.append(int(fields["priority"]))
    if fields.get("is_default"):
        row = db.q1("SELECT service_type FROM ai_service_configs WHERE id=?", (cid,))
        if row:
            db.ex("UPDATE ai_service_configs SET is_default=0 WHERE service_type=?", (row["service_type"],))
        sets.append("is_default=1")
    if "is_active" in fields:
        sets.append("is_active=?"); vals.append(1 if fields["is_active"] else 0)
    if sets:
        vals += [db.now(), cid]
        db.ex(f"UPDATE ai_service_configs SET {','.join(sets)}, updated_at=? WHERE id=?", tuple(vals))


def delete_config(cid: int) -> None:
    db.ex("DELETE FROM ai_service_configs WHERE id=?", (cid,))


def default_config(service_type: str, config_id: int | None = None) -> dict | None:
    if config_id:
        row = db.q1("SELECT * FROM ai_service_configs WHERE id=? AND service_type=? AND is_active=1", (config_id, service_type))
        if row:
            return dict(row)
    row = db.q1("SELECT * FROM ai_service_configs WHERE service_type=? AND is_active=1 ORDER BY is_default DESC, priority DESC, id LIMIT 1",
                (service_type,))
    return dict(row) if row else None


def apply_yihao_key(api_key: str) -> list[str]:
    """易好快捷配置:一个 Key 写入文本/图片/视频推荐配置。

    视频优先级对齐原版(e653b75 + b78f9bf):MiniMax 98 > Wan 3.0 97 > Seedance 96 > RunningHub 95,
    Seedance 垫底(工作台按 priority 降序取第一个启用配置)。
    """
    created: list[str] = []
    FX = "https://api.firemux.com"
    presets = [
        ("text", "gemini", FX, "gemini-3.8-flash", 101),
        ("text", "openai", FX, "deepseek-v4-pro", 100),
        ("image", "openai", FX, "gpt-image-2", 99),
        ("image", "gemini", FX, "gemini-3-pro-image", 97),
        ("video", "aliyun", FX + "/qwen", "wan3.0-video", 98),
        ("video", "volcengine", FX + "/volcengine", "doubao-seedance-2-0-mini-260615", 97),
        ("video", "minimax", FX + "/minimax", "MiniMax-H3", 96),
        ("video", "runninghub", "https://www.runninghub.cn", "seedance-2.5", 95),
    ]
    for st, provider, url, model, prio in presets:
        row = db.q1("SELECT id FROM ai_service_configs WHERE service_type=? AND provider=?", (st, provider))
        if row:
            update_config(row["id"], api_key=api_key, model=model, base_url=url, priority=prio)
        else:
            add_config(st, provider, url, model, api_key=api_key, priority=prio,
                       is_default=(st != "video"))
        created.append(f"{st}:{provider}/{model}(P{prio})")
    return created


def seed_tts_default() -> None:
    if not (q_tts := db.q1("SELECT id FROM ai_service_configs WHERE service_type='tts'")):
        add_config("tts", "volcengine", "https://openspeech.bytedance.com",
                   "zh_female_shuangkuaisisi_uranus_bigtts", remark="豆包语音")


def seed_faceswap_default() -> None:
    """首次启动种子:本地 InsightFace 换脸服务(可再自行添加远程配置)。"""
    if not (row := db.q1("SELECT id FROM ai_service_configs WHERE service_type='faceswap'")):
        add_config("faceswap", "local-faceswap", "http://127.0.0.1:5678",
                   "face-swap", remark="本地换脸服务", priority=0)


def seed_jev_default() -> None:
    """Jev 种子:仅当环境变量给了 Key 时落一条启用配置(幂等,已有任何 jev 行就跳过)。

    对齐参考项目 seedDefaultJevConfigIfMissing:与 TTS 种子的区别是这条 is_active=True。
    """
    import os
    key = (os.environ.get("JEV_API_KEY") or "").strip()
    if not key:
        return
    if db.q1("SELECT id FROM ai_service_configs WHERE service_type='jev'"):
        return
    add_config("jev", "jev",
               (os.environ.get("JEV_BASE_URL") or os.environ.get("JEV_API_URL")
                or "https://api.typesafe.ai").rstrip("/"),
               os.environ.get("JEV_MODEL") or "jev-latest",
               api_key=key, remark="Jev 状态门控(TypeSafe AI)", priority=100)


# ── 就绪检查(缺失配置/Key 时直接拦下,不让请求白跑) ──
SVC_CN_LABEL = {"text": "文本", "image": "图片", "video": "视频", "tts": "配音",
                "faceswap": "换脸", "jev": "Jev"}
# 不需要 API Key 的 provider(本地服务)
NO_KEY_PROVIDERS = {"local-faceswap", 'comfyui', 'sdwebui', 'fooocus'}


class NotConfigured(RuntimeError):
    """AI 服务未就绪:未配置 / 未启用 / 缺 API Key / 缺模型名。"""

    def __init__(self, service_type: str, reason: str, config_id: int | None = None):
        self.service_type = service_type
        self.reason = reason
        self.config_id = config_id
        label = SVC_CN_LABEL.get(service_type, service_type)
        super().__init__(f"{label}服务未就绪:{reason}")


def check_ready(service_type: str, config_id: int | None = None) -> dict:
    """检查该类服务是否可用;不可用抛 NotConfigured(带明确原因)。

    覆盖四种情况:未配置 / 全部停用 / 缺 API Key / 缺模型名或 Base URL。
    """
    rows = registry_list = list_configs(service_type)
    if not rows:
        raise NotConfigured(service_type, f"尚未配置{SVC_CN_LABEL.get(service_type, service_type)}服务,请到「设置 → AI 服务」添加")
    if config_id:
        cfg = next((r for r in rows if r["id"] == config_id), None)
        if not cfg:
            raise NotConfigured(service_type, "所选配置不存在", config_id)
        if not cfg["is_active"]:
            raise NotConfigured(service_type, "所选配置已停用,请在「设置 → AI 服务」启用", config_id)
    else:
        active = [r for r in rows if r["is_active"]]
        if not active:
            raise NotConfigured(service_type, f"所有{SVC_CN_LABEL.get(service_type, service_type)}配置都已停用,请在「设置 → AI 服务」启用")
        cfg = dict(active[0])
        for r in active:  # 优先级最高者
            if int(r["priority"] or 0) > int(cfg.get("priority") or 0):
                cfg = dict(r)
    if not (cfg.get("model") or "").strip():
        raise NotConfigured(service_type, "配置缺少模型名", cfg.get("id"))
    if not (cfg.get("base_url") or "").strip():
        raise NotConfigured(service_type, "配置缺少 Base URL", cfg.get("id"))
    if cfg["provider"] not in NO_KEY_PROVIDERS and not (cfg.get("api_key") or "").strip():
        raise NotConfigured(service_type, f"配置「{cfg.get('remark') or cfg['provider']}」缺少 API Key", cfg.get("id"))
    return cfg


def readiness() -> list[tuple[str, str, str]]:
    """全局就绪概览:[(服务类型, 状态文案, 原因)],供 UI 横幅展示。"""
    out = []
    for st in ("text", "image", "video"):
        try:
            cfg = check_ready(st)
            out.append((st, "ok", f"{cfg.get('remark') or cfg['provider']}/{cfg['model']}"))
        except NotConfigured as e:
            out.append((st, "missing", e.reason))
    return out


def missing_services() -> list[str]:
    """缺失的核心服务类型(文本/图片/视频),空=齐备。"""
    return [st for st, status, _ in readiness() if status != "ok"]
