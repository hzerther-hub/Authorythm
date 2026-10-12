# -*- coding: utf-8 -*-
"""火山引擎豆包语音 TTS(对齐原版 volcengine-tts.ts,双引擎 + 语速自适应)。

引擎:
  Path A `seed-tts-2.0`(默认,3 元/万字符)—— 异步 submit/query,Resource-Id 区分
         单角色(seed-tts-2.0)与复刻音色(seed-icl-2.0,voice 以 S_ 开头)
  Path B `seed-audio-1.0`(兜底,1 元/分钟)—— 同步 create,返回 base64
  fallback 触发:错误含 `resource not granted` → 缓存降级,后续直接走 Path B

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

DEFAULT_RESOURCE_ID = "seed-tts-2.0"
CLONED_RESOURCE_ID = "seed-icl-2.0"
DEFAULT_VOICE = "BV001_streaming"   # 对齐 E:\xiaoshuo 火山豆包默认女声(原 BV001)
AUDIO_MODEL = "seed-audio-1.0"
TTS_MODEL = "seed-tts-2.0-standard"

POLL_INTERVAL = 3
POLL_MAX = 200          # ≈10 分钟
_ENGINE_PREF = ["seed-tts-2.0"]   # 模块级降级缓存


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


def synthesize(text: str, voice: str | None = None, config_id: int | None = None,
               target_duration: float | None = None, speed: float = 1.0,
               subdir: str = "narration") -> Path:
    """合成旁白 MP3。target_duration 给定时按实测时长自动提速(最多 2 轮,≤2.0x)。"""
    cfg = registry.check_ready("tts", config_id)
    key = (cfg.get("api_key") or "").strip()
    if not key:
        raise AIError("配音服务缺少 API Key(火山引擎访问令牌)")
    voice = voice or cfg.get("model") or DEFAULT_VOICE
    base = cfg["base_url"].rstrip("/")

    def _once(rate: int) -> Path:
        engine = _ENGINE_PREF[0]
        try:
            if engine == AUDIO_MODEL:
                return _synth_audio10(base, key, text, speech_rate=rate)
            return _synth_tts20(base, key, text, voice, speech_rate=rate)
        except Exception as e:  # noqa: BLE001
            if engine != AUDIO_MODEL and _is_resource_not_granted(str(e)):
                _ENGINE_PREF[0] = AUDIO_MODEL          # 缓存降级,后续直接走兜底
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
    """连通性探针:发真实最小合成(2 字),因为 submit 空体会回 500 导致永远测试不通过。"""
    voice = cfg.get("model") or ""
    if not voice or voice.upper().startswith("BV"):
        voice = DEFAULT_VOICE
    try:
        p = synthesize("你好", voice=voice, config_id=cfg["id"])
        p.unlink(missing_ok=True)
        return True, "OK(真实合成验证通过)"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]
