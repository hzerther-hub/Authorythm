# -*- coding: utf-8 -*-
"""TTS 多引擎合成 + 语速自适应。

三档引擎:
  Path A `seed-tts-2.0`(火山豆包,默认 3 元/万字符)—— 异步 submit/query,
         Resource-Id 区分单角色(seed-tts-2.0)与复刻音色(seed-icl-2.0,voice 以 S_ 开头)
  Path B `seed-audio-1.0`(火山豆包,1 元/分钟)—— 同步 create,返回 base64
  Path C `edge-tts`(Microsoft Edge 云端神经 TTS,免费、无需 API key)——
         中/英/日/韩四语男女各一,按文本主脚本自动选 voice

  Path A → B 的降级:错误含 `resource not granted` → 缓存降级,后续直接走 B
  Path A/B → C 的降级:用户未配火山豆包 API key,或 volcengine 调用抛错 → Edge TTS 自动接管

语速自适应(核心):按 target_duration 合成后 ffprobe 实测时长,超了就提速重合成
                 (最多 2 轮,上限 2.0x)。
"""
from __future__ import annotations

import base64
import subprocess
import time
import uuid
from pathlib import Path

import requests

from ..core import config
from . import registry
from .text_client import AIError
# 解析 ai_service_configs.models(JSON 字符串)用;单独 import 避免 tts_client → db 的循环依赖
import json as _json
from ..core import db as _db_mod

DEFAULT_RESOURCE_ID = "seed-tts-2.0"
CLONED_RESOURCE_ID = "seed-icl-2.0"
DEFAULT_VOICE = "BV001_streaming"   # 对齐 E:\xiaoshuo 火山豆包默认女声(原 BV001)
AUDIO_MODEL = "seed-audio-1.0"
TTS_MODEL = "seed-tts-2.0-standard"

POLL_INTERVAL = 3
POLL_MAX = 200          # ≈10 分钟
_ENGINE_PREF = ["seed-tts-2.0"]   # 模块级降级缓存

# ── Path C:Edge TTS 神经语音 ──
# cloud-only,免费(无需 API Key),无需下载本地语言包 —— 只要联网就有声。
# 覆盖系统全部 16 种界面语言(对齐 LANGS),每种男女两声,共 32 个预设。
EDGE_DEFAULT_FEMALE = "zh-CN-XiaoxiaoNeural"   # 中文默认女声(温柔)
EDGE_DEFAULT_MALE   = "zh-CN-YunxiNeural"     # 中文默认男声(青年)
# (性别, 语言) → Edge voice;不在表里的语言回落 zh 女/男。
EDGE_VOICE_LIST: dict[tuple[str, str], str] = {
    ("female", "zh"):      "zh-CN-XiaoxiaoNeural",
    ("female", "zh-Hant"): "zh-TW-HsiaoChenNeural",
    ("female", "en"):      "en-US-JennyNeural",
    ("female", "ja"):      "ja-JP-NanamiNeural",
    ("female", "ko"):      "ko-KR-SunHiNeural",
    ("female", "fr"):      "fr-FR-DeniseNeural",
    ("female", "de"):      "de-DE-KatjaNeural",
    ("female", "it"):      "it-IT-IsabellaNeural",
    ("female", "pt"):      "pt-BR-FranciscaNeural",
    ("female", "es"):      "es-ES-ElviraNeural",
    ("female", "vi"):      "vi-VN-HoaiMyNeural",
    ("female", "tr"):      "tr-TR-EmelNeural",
    ("female", "ar"):      "ar-EG-SalmaNeural",
    ("female", "hi"):      "hi-IN-SwaraNeural",
    ("female", "id"):      "id-ID-GadisNeural",
    ("female", "th"):      "th-TH-PremwadeeNeural",
    ("male",   "zh"):      "zh-CN-YunxiNeural",
    ("male",   "zh-Hant"): "zh-TW-YunJheNeural",
    ("male",   "en"):      "en-US-GuyNeural",
    ("male",   "ja"):      "ja-JP-KeitaNeural",
    ("male",   "ko"):      "ko-KR-InJoonNeural",
    ("male",   "fr"):      "fr-FR-HenriNeural",
    ("male",   "de"):      "de-DE-ConradNeural",
    ("male",   "it"):      "it-IT-DiegoNeural",
    ("male",   "pt"):      "pt-BR-AntonioNeural",
    ("male",   "es"):      "es-ES-AlvaroNeural",
    ("male",   "vi"):      "vi-VN-NamMinhNeural",
    ("male",   "tr"):      "tr-TR-SerefNeural",
    ("male",   "ar"):      "ar-EG-ShakirNeural",
    ("male",   "hi"):      "hi-IN-MadhurNeural",
    ("male",   "id"):      "id-ID-ArdiNeural",
    ("male",   "th"):      "th-TH-NiwatNeural",
}


def detect_lang(text: str) -> str:
    """检测文本语种,覆盖系统 16 种界面语言。

    两段判定:
      1) 快速脚本扫描(避免对每个字符都进 langdetect)—— CJK / 假名 / Hangul /
         Arabic / Thai / Devanagari 之间互斥,出现即锁定。
      2) Latin 字串落到 langdetect(en/fr/de/it/pt/es/vi/tr/id/zh/zh-Hant 等),
         通过概率最高的语言映射到我们的 16 集合。
    """
    if not text or not text.strip():
        return "zh"
    n_kana = n_hangul = n_cjk = n_arabic = n_thai = n_devanagari = n_latin = 0
    for ch in text:
        cp = ord(ch)
        if 0x3040 <= cp <= 0x30FF:
            n_kana += 1
        elif 0xAC00 <= cp <= 0xD7A3:
            n_hangul += 1
        elif 0x0600 <= cp <= 0x06FF:
            n_arabic += 1
        elif 0x0E00 <= cp <= 0x0E7F:
            n_thai += 1
        elif 0x0900 <= cp <= 0x097F:
            n_devanagari += 1
        elif (0x4E00 <= cp <= 0x9FFF
              or 0x3400 <= cp <= 0x4DBF):
            n_cjk += 1
        elif ch.isalpha() and ch.isascii():
            n_latin += 1
    if n_kana > 0:
        return "ja"
    if n_hangul > 0:
        return "ko"
    if n_arabic > 0:
        return "ar"
    if n_thai > 0:
        return "th"
    if n_devanagari > 0:
        return "hi"
    if n_cjk > 0 and n_latin == 0:
        # 纯 CJK(无拉丁) -> 繁简区分用「繁中独有字」反向证据 + langdetect 兜底。
        # 简中极少使用、繁体仍保留的常用字(CJK 统一汉字表内字形相异者),
        # 命中任一即视为 zh-Hant;无命中再交给 langdetect 判断短文本。
        TRAD_CHARS = set("國學會爲說這個們嗎來時後電號飛機業對師寫記處樣點條線體變觀聲聰蘭萬與頭臉醫長舊書畫龍鳳龜龐響漢語試驗麥麗黃齊齒齡")
        if any(ch in TRAD_CHARS for ch in text):
            return "zh-Hant"
        try:
            from langdetect import detect
            guess = detect(text)
            if guess == "zh-tw":
                return "zh-Hant"
        except Exception:                          # noqa: BLE001
            pass
        return "zh"
    # Latin 主导(也可能是 CJK + Latin 混合)→ 朗接 langdetect
    try:
        from langdetect import detect
        guess = detect(text)
        return _LANGDETECT_MAP.get(guess, "en")
    except Exception:                              # noqa: BLE001
        return "en" if n_latin > 0 else "zh"


# langdetect → 我们 16 语言 short code 的映射(只保留 system LANGS 里的语种)
_LANGDETECT_MAP: dict[str, str] = {
    "zh-cn": "zh", "zh-tw": "zh-Hant",
    "en": "en", "ja": "ja", "ko": "ko",
    "fr": "fr", "de": "de", "it": "it",
    "pt": "pt", "es": "es", "vi": "vi",
    "tr": "tr", "ar": "ar", "hi": "hi",
    "id": "id", "th": "th",
}


def pick_edge_voice(text: str, gender: str = "female") -> str:
    """按文本主语言 + 用户偏好性别挑 Edge voice;不在表里回落中文同性别。"""
    lang = detect_lang(text)
    fallback = EDGE_DEFAULT_FEMALE if gender == "female" else EDGE_DEFAULT_MALE
    return EDGE_VOICE_LIST.get((gender, lang), fallback)


def reset_engine_cache() -> None:
    _ENGINE_PREF[0] = "seed-tts-2.0"


def _out_path(subdir: str = "narration", ext: str = "mp3") -> Path:
    d = config.STATIC_DIR / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{uuid.uuid4().hex[:12]}.{ext}"


def _resource_id(voice: str) -> str:
    return CLONED_RESOURCE_ID if str(voice or "").startswith("S_") else DEFAULT_RESOURCE_ID


def _is_resource_not_granted(msg: str) -> bool:
    m = (msg or "").lower()
    return "resource not granted" in m or ("resource_id=" in m and "not granted" in m)


def _probe_duration(path: Path) -> float:
    """ffprobe 实测音频时长;失败返回 0。"""
    ff = config.find_ffprobe()
    if not ff or not path.exists():
        return 0.0
    try:
        r = subprocess.run([ff, "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30)
        return float((r.stdout or "0").strip() or 0)
    except Exception:  # noqa: BLE001
        return 0.0


# ── Path A: seed-tts-2.0 ──
def _synth_tts20(base: str, key: str, text: str, voice: str, fmt: str = "mp3",
                  speech_rate: int = 0) -> Path:
    task_id = str(uuid.uuid4())
    headers = {
        "Content-Type": "application/json",
        "X-Api-Key": key,
        "X-Api-Resource-Id": _resource_id(voice),
        "X-Api-Request-Id": task_id,
    }
    sample_rate = 48000 if fmt == "ogg_opus" else 24000
    body = {
        "user": {"uid": "yihao-drama"},
        "unique_id": task_id,
        "req_params": {
            "text": text,
            "speaker": voice,
            "audio_params": {"format": fmt, "sample_rate": sample_rate,
                             "speech_rate": speech_rate, "loudness_rate": 0},
            "model": TTS_MODEL,
        },
    }
    r = requests.post(f"{base}/api/v3/tts/submit", json=body, headers=headers, timeout=60)
    try:
        data = r.json()
    except Exception:  # noqa: BLE001
        raise AIError(f"豆包语音提交返回非 JSON(HTTP {r.status_code}): {r.text[:200]}")
    code = str(data.get("code", ""))
    if code not in ("20000000", "0"):
        raise AIError(f"豆包语音提交失败({code}): {data.get('message') or data.get('msg') or r.text[:200]}")
    tid = (data.get("data") or {}).get("task_id")
    if not tid:
        raise AIError(f"豆包语音响应缺少 task_id: {r.text[:200]}")
    for _ in range(POLL_MAX):
        time.sleep(POLL_INTERVAL)
        q = requests.post(f"{base}/api/v3/tts/query", json={"task_id": tid},
                          headers=headers, timeout=30).json()
        d = q.get("data") or {}
        st = d.get("task_status")
        if st == 2:
            url = d.get("audio_url")
            if not url:
                raise AIError("豆包语音任务完成但无 audio_url")
            resp = requests.get(url, timeout=180)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "")
            ext = "wav" if ctype.startswith("audio/wav") else ("pcm" if ctype.startswith("audio/pcm") else fmt)
            out = _out_path(ext=ext)
            out.write_bytes(resp.content)
            return out
        if st == 3:
            raise AIError(f"豆包语音合成失败: {q.get('message') or q.get('msg') or str(q)[:200]}")
    raise AIError("豆包语音合成超时(10 分钟)")


# ── Path B: seed-audio-1.0(同步兜底) ──
def _synth_audio10(base: str, key: str, text: str, fmt: str = "mp3",
                   speech_rate: int = 0) -> Path:
    task_id = str(uuid.uuid4())
    headers = {"Content-Type": "application/json", "X-Api-Key": key, "X-Api-Request-Id": task_id}
    body = {
        "model": AUDIO_MODEL,
        "text_prompt": text,
        "audio_config": {"format": fmt, "sample_rate": 48000 if fmt == "ogg_opus" else 44100,
                         "pitch_rate": 0, "speech_rate": speech_rate, "loudness_rate": 0},
        "watermark": {},
    }
    r = requests.post(f"{base}/api/v3/tts/create", json=body, headers=headers, timeout=120)
    data = r.json()
    if str(data.get("code", "0")) not in ("0", "20000000"):
        raise AIError(f"豆包语音(1.0)失败: {data.get('message') or r.text[:200]}")
    b64 = data.get("audio")
    if not b64:
        raise AIError("豆包语音(1.0)响应缺少 audio")
    out = _out_path(ext=fmt)
    out.write_bytes(base64.b64decode(b64))
    return out


# 模块级最近一次合成使用的 voice,UI(朗读预览窗口标题等)读这个值显示给用户。
_LAST_VOICE: str = ""


def last_voice() -> str:
    """返回最近一次 synthesize() 实际选用的 voice(含 volcengine BV001 / Edge Neural 名称)。"""
    return _LAST_VOICE


# ── Path C:Edge TTS 同步封装 ──
def _synthesize_edge(text: str, voice: str = EDGE_DEFAULT_FEMALE,
                     speech_rate: int = 0, fmt: str = "mp3") -> Path:
    """Edge TTS 云端神经合成;首次发起前会建 asyncio loop(PySide6 进程内主 loop
    通常已在运行,这里用 thread 隔离跑)。Edge 不支持 ffprobe 提速循环,与
    target_duration 联动时只影响 volcengine 路径。
    """
    global _LAST_VOICE
    _LAST_VOICE = voice
    import asyncio
    import concurrent.futures
    import edge_tts
    rate = f"{'+' if int(speech_rate) >= 0 else ''}{int(speech_rate)}%"
    out = _out_path(ext=fmt)

    async def _run() -> None:
        comm = edge_tts.Communicate(text, voice=voice, rate=rate)
        await comm.save(str(out))

    try:
        asyncio.run(_run())
    except RuntimeError:
        # 主线程已有 running loop → 用独立线程跑 asyncio.run
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            ex.submit(lambda: asyncio.run(_run())).result()
    return out


def synthesize(text: str, voice: str | None = None, config_id: int | None = None,
               target_duration: float | None = None, speed: float = 1.0,
               gender: str = "female", subdir: str = "narration") -> Path:
    """合成旁白 MP3。

    引擎链 (按优先级尝试):
      1) 用户在「AI 服务」里配了豆包语音 + api_key → 走 volcengine 双引擎(Path A/B)
      2) 否则,或 volcengine 抛错 → 走 Edge TTS(Path C,免费微软神经)

    voice 优先:调用方传参 >> 配置项默认 voice >> Edge 按「文本主语言 + 性别」自动选
                (覆盖系统全部 16 种界面语言 · 男女各一,共 32 个预设)。

    target_duration 在 Edge 路径会被忽略(Edge 的提速语义与 volcengine 不同,
    强制 speed 走 rate percent 参数;ffprobe 校验留给下一版本)。
    """
    global _LAST_VOICE
    cfg = None
    try:
        cfg = registry.check_ready("tts", config_id)
    except Exception:                          # noqa: BLE001 —— 无任何 TTS 配置时
        cfg = None
    key = (cfg.get("api_key") or "").strip() if cfg else ""

    # ── Path C 提前:voice 已是 Edge voice 名称时,直接走 Edge,绕开 volcengine ──
    if voice and ("Neural" in voice):
        try:
            return _synthesize_edge(text, voice=voice,
                                    speech_rate=int(round((max(0.5, min(2.0, float(speed or 1.0))) - 1) * 100)))
        except Exception:
            pass                       # Edge 不通时再回头走 volcengine

    # ── Path A/B:豆包 ──
    if key:
        # 选 voice 优先级:调用方传入 > cfg.models 列表按 gender 匹配 > cfg.model 默认
        volc_voice = voice
        if not volc_voice:
            try:
                models_raw = (cfg.get("models") if cfg else "") or ""
                models_list = _json.loads(models_raw) if isinstance(models_raw, str) and models_raw else []
            except Exception:                          # noqa: BLE001
                models_list = []
            if models_list:
                # 用下划线包围的子串做边界匹配:zh_female_xxx 不会被 'male' 误中。
                target = "_male_" if gender == "male" else "_female_"
                volc_voice = next((m for m in models_list
                                   if target in (m or "").lower()), models_list[0])
            else:
                volc_voice = (cfg.get("model") if cfg else None) or DEFAULT_VOICE
        _LAST_VOICE = volc_voice
        try:
            return _synthesize_volc(text, volc_voice, cfg, target_duration, speed)
        except Exception as e:          # noqa: BLE001 —— 豆包挂了就降级
            pass

    # ── Path C:Edge TTS 兜底 ──
    chosen = voice if (voice and "Neural" in voice) else pick_edge_voice(text, gender)
    _LAST_VOICE = chosen
    return _synthesize_edge(text, voice=chosen,
                            speech_rate=int(round((max(0.5, min(2.0, float(speed or 1.0))) - 1) * 100)))


def _synthesize_volc(text: str, voice: str, cfg: dict,
                     target_duration: float | None, speed: float) -> Path:
    """原 volcengine A/B 合成逻辑(抽出来便于降级链调用)。"""
    key = (cfg.get("api_key") or "").strip()
    base = cfg["base_url"].rstrip("/")

    def _once(rate: int) -> Path:
        engine = _ENGINE_PREF[0]
        try:
            if engine == AUDIO_MODEL:
                return _synth_audio10(base, key, text, speech_rate=rate)
            return _synth_tts20(base, key, text, voice, speech_rate=rate)
        except Exception as e:  # noqa: BLE001
            if engine != AUDIO_MODEL and _is_resource_not_granted(str(e)):
                _ENGINE_PREF[0] = AUDIO_MODEL
                return _synth_audio10(base, key, text, speech_rate=rate)
            raise

    ratio = max(0.5, min(2.0, float(speed or 1.0)))
    out = _once(int(round((ratio - 1) * 100)))
    if not (target_duration and target_duration > 0):
        return out
    for _ in range(2):                        # 最多 2 轮提速重合成
        dur = _probe_duration(out)
        if dur <= 0 or dur <= target_duration + 0.05:
            break
        prev_rate = int(round((ratio - 1) * 100))
        ratio = min(2.0, ratio * (dur / float(target_duration)))
        new_rate = int(round((ratio - 1) * 100))
        if abs(new_rate - prev_rate) < 1:
            break
        try:
            new_out = _once(new_rate)
        except Exception:  # noqa: BLE001
            break
        out.unlink(missing_ok=True)
        out = new_out
    return out


def test_config(cfg: dict) -> tuple[bool, str]:
    """连通性探针:发真实最小合成(2 字),因为 submit 空体会回 500 导致永远测试不通过。

    config_id 用 `cfg.get("id")` 而不是 `cfg["id"]`:设置页 **弹窗**里的「测试配置」
    传的是 `ServiceDialog._collect()` 的结果,那个 dict **不带 id**(新增配置时更是
    根本没有),下标取值直接 KeyError → 弹窗里点测试永远失败(列表页传整行才有 id)。
    None 是安全的:synthesize 内部会按优先级挑默认 TTS 配置。
    """
    voice = cfg.get("model") or ""
    if not voice or voice.upper().startswith("BV"):
        voice = DEFAULT_VOICE
    try:
        p = synthesize("你好", voice=voice, config_id=cfg.get("id"))
        p.unlink(missing_ok=True)
        return True, "OK(真实合成验证通过)"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]
