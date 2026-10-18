# -*- coding: utf-8 -*-
"""AI 服务配置注册表:六类服务(text/image/video/tts/faceswap/jev)多供应商 CRUD + 默认项 + 连通测试。"""
from __future__ import annotations

import json

from ..core import db
from ..core.secrets import ensure_decrypted, ensure_encrypted

SERVICE_TYPES = ["text", "image", "video", "tts", "faceswap", "jev", "stockphoto"]


def _decrypt_row(row) -> dict:
    """把 sqlite3.Row 变 dict,并对 api_key 字段做解密。"""
    d = dict(row)
    if "api_key" in d:
        d["api_key"] = ensure_decrypted(d.get("api_key") or "")
    return d

# 手动模板预设(对齐原版「添加服务」对话框:模板快选自动填入 Base URL 与默认模型)
PROVIDER_PRESETS: dict[str, list[dict]] = {
    "text": [
        {"name": "DeepSeek 官方", "provider": "deepseek",
         "base_url": "https://api.deepseek.com/v1",
         "models": ["deepseek-v4-pro", "deepseek-flash"]},
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
    # 免费图库:只用来搜参考图,不参与任何生成。三家的鉴权方式不同,
    # 见 app/ai/stock_photo.py 的说明。
    "stockphoto": [
        {"name": "Unsplash", "provider": "unsplash",
         "base_url": "https://api.unsplash.com",
         "models": ["search/photos"]},
        {"name": "Pexels", "provider": "pexels",
         "base_url": "https://api.pexels.com",
         "models": ["v1/search"]},
        {"name": "Pixabay", "provider": "pixabay",
         "base_url": "https://pixabay.com",
         "models": ["api/"]},
    ],
}

SVC_CN = {"text": "文本", "image": "图片", "video": "视频", "tts": "配音", "faceswap": "换脸",
         "jev": "Jev", "stockphoto": "图库"}

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


# 支持多模态(能看图/看视频)的模型 —— **按模型名匹配**,不是按 provider。
# 同一家下面既有看图的也有纯文本的(deepseek-flash 是纯文本,agnes-3.0-flash 能读图),
# 按 provider 一刀切会标错。
#
# MiniMax-M 系列是**实测确认能读图**的(video_clone 的读产品图/读人物外貌
# 都发它,`text_client._build_body` 的多模态格式注释也写着它)—— 所以
# "minimax 的 M"是确定项,不是靠名字猜的。
VISION_EXACT = (
    # 名称无规律、只能整串列出的
    "minimax-m", "minimax-m2", "minimax-m3",
)
VISION_HINTS = ("vision", "-vl", "vl-", "3.0-flash", "3-pro", "gpt-4o",
                "gemini-2", "gemini-3", "glm-4v", "kimi-vl", "qwen-vl")


def is_vision_model(model: str | None) -> bool:
    """该模型名是否属于多模态(可收图/收视频)。

    这是**启发式标注**,用于界面提示,不阻断请求 —— 标错顶多提示不准,
    不会把用户的活儿挡下来;而漏标会让本该读图的功能静默拿到胡话。
    """
    m = (model or "").strip().lower()
    if not m:
        return False
    if m.startswith(VISION_EXACT):
        return True
    return any(h in m for h in VISION_HINTS)


def model_entries(service_type: str) -> list[dict]:
    """一条配置里的**每个**模型各出一个下拉条目。

    之前 `_reload_models` 用 `addItem(cfg["model"], cfg["id"])`,一条配置只显示
    默认模型 —— 设置页标签里明明列着 deepseek-v4-pro / deepseek-flash、agnes-image
    三个型号、minimax 五个型号,顶栏下拉里却只有 12 个默认值,其余全选不到。
    这里把 models 列表逐个展开。

    返回 [{label, config_id, model, is_default}]。同一配置有多个模型时 label
    加 provider 前缀,避免"MiniMax-M2"这类看不出是哪家的名字。
    """
    out: list[dict] = []
    for cfg in list_configs(service_type):
        raw = cfg.get("models")
        models: list[str] = []
        if raw:
            try:
                models = [str(m).strip() for m in json.loads(raw) if str(m or "").strip()]
            except (TypeError, ValueError):
                models = []
        default = str(cfg.get("model") or "").strip()
        if default and default not in models:
            models.insert(0, default)      # models 与 model 列不一致时以 model 列为准
        if not models:
            models = [default or "(未配置)"]
        for m in models:
            short = m.split("/")[-1]
            vision = is_vision_model(m)
            base = f"{cfg['provider']} · {short}" if len(models) > 1 else short
            out.append({
                # 多模态模型加文字标记:复刻/图片编辑这类要读图的功能,选到纯文本
                # 模型会拿到一句"我看不到图"式的胡话。
                # 用「[多模态]」而不是 👁 —— Windows 应用字体没有该字形,
                # emoji 在这里会渲染成空白(见 AGENTS.md 图标约定)。
                "label": base + ("  [多模态]" if vision and service_type == "text" else ""),
                "config_id": cfg["id"],
                "model": m,
                "is_default": m == default,
                "vision": vision,
            })
    return out


def select_model(config_id: int, model: str) -> bool:
    """把该配置当前使用的模型切到 model。切换成功返回 True。

    调用链(`runner.run_agent` / `text_client.chat` / `video_client.generate_video`)
    只接受 config_id,模型名一律从库里读,所以「选了哪个模型」这件事只能落到
    配置的 model 列上 —— 选完即刻生效,不必新增参数贯穿整条链路。
    只允许在 models 列表**内**切换,防止借此把配置改成列表外的模型。
    """
    if not model:
        return False
    row = db.q1("SELECT models, model FROM ai_service_configs WHERE id=?", (config_id,))
    if not row:
        return False
    try:
        allowed = [str(m).strip() for m in json.loads(row["models"] or "[]")
                   if str(m or "").strip()]
    except (TypeError, ValueError):
        allowed = []
    if row["model"] == model:
        return False
    if allowed and model not in allowed:
        return False
    db.ex("UPDATE ai_service_configs SET model=?, updated_at=? WHERE id=?",
          (model, db.now(), config_id))
    return True


def normalize_base_url(service_type: str, provider: str, base_url: str) -> str:
    """补齐各厂商要求的 API 版本前缀,避免用户手填漏掉导致 404/403。

    为什么需要:每家的版本段位置不一样,填错/漏填的表现完全不同 ——
      - 火山方舟  缺 `/api/v3` → **空 body 的 404**(网关层就挡了,连不到应用)
      - Agnes     缺 `/v1`      → Cloudflare HTML 拦截页 403
    而填了 `/v1` 后再让客户端拼一次,又会变成 `/v1/v1/...`。

    规则按 (service_type, provider) 走,不是所有厂商一刀切:
      - volcengine + 非 tts → 必须 `/api/v3`(火山方舟统一)
      - agnes                → 必须 `/v1`(图片硬编码拼 `/v1/images/generations`)
      - 其它(openai/deepseek/minimax/…):用户填什么就是什么 —— 这些厂商
        有 OpenAI 兼容(`/v1`)也有原生(`/api/coding/paas/v4`、
        `token-plan…maas.aliyuncs.com` 无版本段),猜错反而更糟。

    **tts 单独排除**:豆包语音走 `openspeech.bytedance.com` 的火山语音自有
    协议(websocket + v3 签名),与方舟的 `/api/v3` REST 完全不是一回事,
    补前缀会直接把 base 改坏。
    """
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return url
    if service_type == "tts":
        return url                      # 语音协议各厂商独立,不猜前缀
    suffix = ""
    if provider == "volcengine" and "/api/v3" not in url:
        suffix = "/api/v3"
    elif provider == "agnes" and "/v1" not in url:
        suffix = "/v1"
    return url + suffix if suffix else url


def list_configs(service_type: str | None = None) -> list:
    if service_type:
        rows = db.q("SELECT * FROM ai_service_configs WHERE service_type=? ORDER BY is_default DESC, priority DESC, id",
                    (service_type,))
    else:
        rows = db.q("SELECT * FROM ai_service_configs ORDER BY service_type, is_default DESC, id")
    # 返回前统一补前缀 —— 调用方(各 client)拿到的就是规范化的 URL。
    # 只在内存里改,不写库:存量配置保持用户原样,新建/编辑时才落规范化值。
    out = []
    for r in rows:
        d = _decrypt_row(r)
        d["base_url"] = normalize_base_url(d["service_type"], d.get("provider", ""), d.get("base_url", ""))
        out.append(d)
    return out


def add_config(service_type: str, provider: str, base_url: str, model: str,
               api_key: str = "", is_default: bool = False, remark: str = "",
               priority: int = 0, models: list[str] | None = None,
               temperature: float | None = None,
               max_tokens: int | None = None) -> int:
    ts = db.now()
    if is_default:
        db.ex("UPDATE ai_service_configs SET is_default=0 WHERE service_type=?", (service_type,))
    elif not db.q1("SELECT id FROM ai_service_configs WHERE service_type=?", (service_type,)):
        is_default = True  # 该类型第一条配置自动设为默认
    import json as _json
    # 落库前补 API 版本前缀(火山 /api/v3、Agnes /v1),见 normalize_base_url
    base_url = normalize_base_url(service_type, provider, base_url)
    # 入库前加密 api_key(salt 派生自机器指纹,跨用户/机器不可解)
    api_key_cipher = ensure_encrypted(api_key or "")
    return db.ex(
        "INSERT INTO ai_service_configs(service_type,provider,base_url,api_key,model,is_default,is_active,remark,priority,models,temperature,max_tokens,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,1,?,?,?,?,?,?,?)",
        (service_type, provider, base_url, api_key_cipher, model,
         1 if is_default else 0, remark, priority,
         _json.dumps(models or [model], ensure_ascii=False),
         temperature, max_tokens, ts, ts))


def update_config(cid: int, **fields) -> None:
    import json as _json
    sets, vals = [], []
    for k in ("provider", "base_url", "api_key", "model", "remark"):
        if k in fields and fields[k] is not None:
            v = fields[k]
            # 改 provider 时要按新 provider 重新判定要不要补前缀(换厂商了规则就变)
            if k == "base_url":
                row = db.q1("SELECT service_type, provider FROM ai_service_configs WHERE id=?", (cid,))
                st = (row["service_type"] if row else "") or fields.get("service_type", "")
                pv = fields.get("provider") or (row["provider"] if row else "")
                v = normalize_base_url(st, pv or "", v)
            # api_key 入库前加密(明文 → enc:...)
            if k == "api_key":
                v = ensure_encrypted(v or "")
            sets.append(f"{k}=?"); vals.append(v)
    if "settings" in fields:                     # 本地生图扩展设置(JSON 字符串;空串存 NULL)
        sets.append("settings=?")
        vals.append(fields["settings"] or None)
    if "models" in fields and fields["models"] is not None:
        v = fields["models"]
        # 调用方可能传 list(标准)或已序列化的 JSON 字符串 —— 字符串直接存,
        # 列表才序列化;否则 list 会被二次编码,读回来退化成单模型(实测踩过)
        if not isinstance(v, str):
            v = _json.dumps(v, ensure_ascii=False)
        sets.append("models=?")
        vals.append(v)
    if "max_tokens" in fields:
        sets.append("max_tokens=?")
        vals.append(fields["max_tokens"])
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
            return _decrypt_row(row)
    row = db.q1("SELECT * FROM ai_service_configs WHERE service_type=? AND is_active=1 ORDER BY is_default DESC, priority DESC, id LIMIT 1",
                (service_type,))
    return _decrypt_row(row) if row else None


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
                "faceswap": "换脸", "jev": "Jev", "stockphoto": "图库"}
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
        cfg = dict(cfg)          # sqlite3.Row 没有 .get,后面统一按 dict 处理
    else:
        active = [r for r in rows if r["is_active"]]
        if not active:
            raise NotConfigured(service_type, f"所有{SVC_CN_LABEL.get(service_type, service_type)}配置都已停用,请在「设置 → AI 服务」启用")
        # 与 default_config 同口径:默认项(is_default)优先,其次按 priority。
        # 曾只看 priority,导致用户标了默认的 deepseek 被 priority 更高的 minimax 抢走,
        # 请求打到 minimax 的裸 base(缺 /v1)→ nginx 404。
        active.sort(key=lambda r: (int(r["is_default"] or 0), int(r["priority"] or 0)), reverse=True)
        cfg = dict(active[0])
    if not (cfg.get("model") or "").strip():
        raise NotConfigured(service_type, "配置缺少模型名", cfg.get("id"))
    if not (cfg.get("base_url") or "").strip():
        raise NotConfigured(service_type, "配置缺少 Base URL", cfg.get("id"))
    if cfg["provider"] not in NO_KEY_PROVIDERS and not (cfg.get("api_key") or "").strip():
        raise NotConfigured(service_type, f"配置「{cfg.get('remark') or cfg['provider']}」缺少 API Key", cfg.get("id"))
    return cfg


def readiness() -> list[tuple[str, str, str]]:
    """全局就绪概览:[(服务类型, 状态文案, 原因)],供 UI 横幅/安装帮助弹窗展示。

    覆盖**全部 6 类**:text / image / video / tts / faceswap / jev。
    原先只遍历前三类,而主窗口「?」安装帮助弹窗按 6 行渲染,对取不到的
    service_type 用 `ready.get(st, False)` 兜底 → tts / faceswap / jev
    **永远显示「✗ 未配置」**,哪怕配好且测试通过(用户实测:豆包配音和 JEV
    都正常,却都标红)。PhotoCraft 不在此列 —— 它是本地工具不查配置表,
    由 main_window 单独探测。
    """
    out = []
    for st in ("text", "image", "video", "tts", "faceswap", "jev"):
        try:
            cfg = check_ready(st)
            out.append((st, "ok", f"{cfg.get('remark') or cfg['provider']}/{cfg['model']}"))
        except NotConfigured as e:
            out.append((st, "missing", e.reason))
        except Exception as e:  # noqa: BLE001 —— 探测本身出错也归 missing,别炸横幅
            out.append((st, "missing", str(e)[:120]))
    return out


def missing_services() -> list[str]:
    """缺失的服务类型,空=齐备。

    **只算 text/image/video 三类核心** —— 顶部横幅是「AI 未就绪」提示,不该把
    换脸/配音/JEV 这些可选能力也报成「AI 服务未配置完整」(用户看到会很莫名:
    明明能出图,却提示 AI 没配好)。它们的状态在「?」安装帮助弹窗里单独展示。
    """
    core = {"text", "image", "video"}
    return [st for st, status, _ in readiness()
            if st in core and status != "ok"]
