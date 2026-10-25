# -*- coding: utf-8 -*-
"""TTS 多引擎合成 + 语速自适应。

四档引擎(对齐原版 E:\\xiaoshuo adapters/tts.ts 的四通道):
  Path A `seed-tts-2.0`(火山豆包,默认 3 元/万字符)—— 异步 submit/query,
         Resource-Id 区分单角色(seed-tts-2.0)与复刻音色(seed-icl-2.0,voice 以 S_ 开头)
  Path B `seed-audio-1.0`(火山豆包,1 元/分钟)—— 同步 create,返回 base64
  Path C `edge-tts`(Microsoft Edge 云端神经 TTS,免费、无需 API key)——
         16 语种男女各一,按文本主脚本自动选 voice
  Path D `local`(Windows 本机微软语音,离线、免 Key 免网络)—— PowerShell 驱动
         WinRT/SAPI 双引擎,音色按机器枚举,断网也能出声

  Path A → B 的降级:错误含 `resource not granted` → 缓存降级,后续直接走 B
  Path A/B → C → D 的降级:未配火山 key 或 volcengine 抛错 → Edge 接管 → 仍失败
              再落本机语音;**显式选了 edge/local 的不降级**(用户明确要免费/离线,
              必须让他看到真实错误而不是悄悄换通道)

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


# ══ Path D:本机微软语音(Windows 离线,免 Key 免网络)══════════════════
# 对齐原版 E:\xiaoshuo services/adapters/local-tts.ts(d98e59d)。
# 两套引擎都是微软官方、随 Windows 安装:
#   - WinRT Windows.Media.SpeechSynthesis(Huihui/Yaoyao/Kangkang,16kHz)
#   - SAPI  System.Speech(Huihui Desktop / Zira Desktop,22.05kHz)
# 已知两个坑照搬原版的规避:
#   1) .ps1 必须带 UTF-8 BOM(PS 5.1 无 BOM 按 ANSI 解,中文脚本直接乱码);
#   2) 合成文本不能走命令行参数(同样被 ANSI 化),改走 UTF-8 临时文件。

LOCAL_TTS_MISSING_HINT = (
    "本机没有可用的微软语音引擎音色。请在「设置 → 时间和语言 → 语言和区域」"
    "安装中文(简体)的语音包(系统设置 → 隐私和安全性 → 语音 → 添加语音包),"
    "安装后重启本应用即可。")


def _is_edge_provider(p) -> bool:
    return str(p or "").strip().lower() in ("edge", "edge-tts", "microsoft-edge")


def _is_local_provider(p) -> bool:
    return str(p or "").strip().lower() in ("local", "local-tts", "win-local",
                                            "microsoft-local")


def _powershell_exe() -> str:
    # PS 5.1(PS7 移除了 WinRT 投影,不能驱动 WinRT 引擎)
    import os
    root = os.environ.get("SystemRoot", r"C:\Windows")
    return str(Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")


def _run_powershell(script: Path, args: list, timeout_s: int = 60) -> str:
    r = subprocess.run([_powershell_exe(), "-NoProfile", "-ExecutionPolicy",
                        "Bypass", "-File", str(script), *args],
                       capture_output=True, timeout=timeout_s)
    if r.returncode != 0:
        raise RuntimeError("本地语音引擎调用失败:"
                           + r.stderr.decode("utf-8", "replace")[:400])
    return r.stdout.decode("utf-8", "replace")


_LIST_VOICES_PS = """
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$result = @()
try {
  Add-Type -AssemblyName System.Speech
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  foreach ($v in $s.GetInstalledVoices()) {
    if ($v.Enabled) {
      $result += @{ name = $v.VoiceInfo.Name; lang = $v.VoiceInfo.Culture.Name; gender = [string]$v.VoiceInfo.Gender; engine = 'sapi' }
    }
  }
  $s.Dispose()
} catch {}
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  [void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime]
  foreach ($v in [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices) {
    $g = ''
    try { $g = [string]$v.Gender } catch { $g = '' }
    $result += @{ name = $v.DisplayName; lang = $v.Language; gender = $g; engine = 'winrt' }
  }
} catch {}
$result | ConvertTo-Json -Compress -Depth 4
"""


def _write_ps1(path: Path, body: str) -> None:
    """带 UTF-8 BOM 写 .ps1 —— PS 5.1 正确解析中文的唯一可靠办法。"""
    path.write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))


def list_local_voices() -> list:
    """枚举本机微软音色(SAPI + WinRT 双引擎)。失败/非 Windows 返回空表。

    每项 {id, name, lang, gender, engine};id 形如 `winrt:Microsoft Huihui`。
    """
    import sys
    if sys.platform != "win32":
        return []
    import tempfile
    import shutil
    work = Path(tempfile.mkdtemp(prefix="tts-voices-"))
    try:
        script = work / "list.ps1"
        _write_ps1(script, _LIST_VOICES_PS)
        raw = _run_powershell(script, [], timeout_s=30).strip()
        if not raw:
            return []
        data = _json.loads(raw)
        arr = data if isinstance(data, list) else [data]
        out = []
        for v in arr:
            name = str(v.get("name") or "").strip()
            if not name:
                continue
            out.append({
                "id": "{}:{}".format(v.get("engine"), name),
                "name": name,
                "lang": str(v.get("lang") or ""),
                # SAPI 给 Male/Female,WinRT 同;认不出按女声(原版同口径)
                "gender": "male" if str(v.get("gender") or "").strip().lower() == "male" else "female",
                "engine": "winrt" if v.get("engine") == "winrt" else "sapi",
            })
        return out
    except Exception:  # noqa: BLE001 —— 枚举失败 = 本机没有,不抛
        return []
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _find_local_voice(voices: list, requested) -> dict | None:
    """精确查找(显示名 / 内部 ID / 语言 tag);找不到返回 None,不做兜底。"""
    want = str(requested or "").strip().lower()
    if not want or want == "auto":
        return None
    for v in voices:
        if v["name"].lower() == want or v["id"].lower() == want:
            return v
    for v in voices:
        if v["lang"].lower() == want:
            return v
    return None


def _resolve_local_voice(voices: list, requested, model_voice, gender) -> dict | None:
    """本机通道最终选音(原版 resolveLocalVoice 同口径)。

    显式指定 > 配置置顶音色(**性别不冲突时**才用 —— 置顶女声又切男声,
    置顶会被跳过,这是「切换性别」能生效的关键)> 按性别挑中文 > 任意中文 > 第一个。
    """
    if not voices:
        return None
    exact = _find_local_voice(voices, requested)
    if exact:
        return exact
    g = "male" if gender == "male" else "female"
    pinned = _find_local_voice(voices, model_voice)
    if pinned and pinned["gender"] == g:
        return pinned
    for v in voices:
        if v["lang"].lower().startswith("zh") and v["gender"] == g:
            return v
    for v in voices:
        if v["lang"].lower().startswith("zh"):
            return v
    return voices[0]


def _atempo_chain(rate: float) -> str:
    """ffmpeg atempo 链:单个只支持 0.5~2.0,慢于 0.5 时串联兜底。"""
    r = max(0.5, min(2.0, float(rate or 1)))
    if r >= 1:
        return f"atempo={r:.4f}"
    factors, rest = [], r
    while rest < 0.5:
        factors.append(0.5)
        rest /= 0.5
    factors.append(rest)
    return ",".join(f"atempo={f:.4f}" for f in factors)


def _synth_ps(engine: str) -> str:
    """合成脚本(参数:输入文本文件 / 输出 wav / 音色名)。文本走临时文件防 ANSI 化。"""
    if engine == "sapi":
        return """
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$inFile = $args[0]; $outFile = $args[1]; $voiceName = $args[2]
$txt = [System.IO.File]::ReadAllText($inFile, [System.Text.Encoding]::UTF8)
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($voiceName) { $s.SelectVoice($voiceName) }
$s.SetOutputToWaveFile($outFile)
$s.Speak($txt)
$s.SetOutputToNull()
$s.Dispose()
"""
    return """
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime]
$inFile = $args[0]; $outFile = $args[1]; $voiceName = $args[2]
$txt = [System.IO.File]::ReadAllText($inFile, [System.Text.Encoding]::UTF8)
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.IsGenericMethod -and
  $_.GetParameters()[0].ParameterType.Name -like 'IAsyncOperation*' } | Select-Object -First 1
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$pick = $null
if ($voiceName) { $pick = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | Where-Object { $_.DisplayName -eq $voiceName } | Select-Object -First 1 }
if ($pick) { $synth.Voice = $pick }
$op = $synth.SynthesizeTextToStreamAsync($txt)
$task = $asTask.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke($null, @($op))
$task.Wait(60000) | Out-Null
$stream = $task.Result
$net = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream)
$fs = [System.IO.File]::Create($outFile)
$net.CopyTo($fs)
$fs.Close()
"""


def _synthesize_local(text: str, voice: str | None = None, model_voice: str = "",
                      gender: str = "female", speed: float = 1.0,
                      subdir: str = "narration") -> Path:
    """本机微软语音合成(离线)。无音色时抛带「怎么装语音包」的错误。"""
    import sys
    if sys.platform != "win32":
        raise RuntimeError(f"本地微软语音只支持 Windows(当前 {sys.platform})。"
                           + LOCAL_TTS_MISSING_HINT)
    voices = list_local_voices()
    if not voices:
        raise RuntimeError("没有检测到本机微软语音音色。" + LOCAL_TTS_MISSING_HINT)
    picked = _resolve_local_voice(voices, voice, model_voice, gender)
    if not picked:
        raise RuntimeError("没有检测到本机微软语音音色。" + LOCAL_TTS_MISSING_HINT)
    global _LAST_VOICE
    _LAST_VOICE = picked["name"]

    import tempfile
    import shutil
    work = Path(tempfile.mkdtemp(prefix="tts-local-"))
    try:
        script = work / "synth.ps1"
        txt_file = work / "input.txt"
        wav = work / "out.wav"
        _write_ps1(script, _synth_ps(picked["engine"]))
        txt_file.write_text(text or "", encoding="utf-8")
        _run_powershell(script, [str(txt_file), str(wav), picked["name"]])
        if not wav.exists() or wav.stat().st_size == 0:
            raise RuntimeError("本地语音引擎没有产出音频")
        # WAV → MP3(顺带 atempo 变速)
        ff = config.find_ffmpeg()
        if not ff:
            raise RuntimeError("未找到 ffmpeg(本机语音需要它转 MP3)")
        out = _out_path(subdir=subdir)
        r = subprocess.run([ff, "-y", "-i", str(wav), "-filter:a",
                            _atempo_chain(speed or 1.0), "-codec:a", "libmp3lame",
                            "-b:a", "64k", "-ac", "1", str(out)],
                           capture_output=True, timeout=120)
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("本机语音转 MP3 失败:"
                               + r.stderr.decode("utf-8", "replace")[:300])
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
      1) 配置的 provider 显式是 edge / local → 直接走对应通道,**不降级**
         (用户明确选了免费/离线,必须看到真实错误而不是悄悄换通道)
      2) 配了豆包语音 + api_key → 走 volcengine 双引擎(Path A/B,收费)
      3) volcengine 抛错或未配 key → Edge TTS(Path C,免费微软云)
      4) Edge 也失败 → 本机微软语音(Path D,离线);仍失败把各通道原因合并抛出

    voice 优先:调用方传参 >> 配置项默认 voice >> Edge 按「文本主语言 + 性别」自动选
                (覆盖系统全部 16 种界面语言 · 男女各一,共 32 个预设)。

    target_duration 在 Edge/local 路径会被忽略(提速语义不同;ffprobe 校验留给下一版本)。
    """
    global _LAST_VOICE
    cfg = None
    try:
        cfg = registry.check_ready("tts", config_id)
    except Exception:                          # noqa: BLE001 —— 无任何 TTS 配置时
        cfg = None
    key = (cfg.get("api_key") or "").strip() if cfg else ""
    provider = (cfg.get("provider") or "").strip().lower() if cfg else ""
    model_voice = (cfg.get("model") or "").strip() if cfg else ""
    rate_pct = int(round((max(0.5, min(2.0, float(speed or 1.0))) - 1) * 100))
    reasons: list[str] = []

    # ── 显式选了 Edge(免费):直接走,不降级 ──
    if _is_edge_provider(provider):
        chosen = voice if (voice and "Neural" in voice) else pick_edge_voice(text, gender)
        return _synthesize_edge(text, voice=chosen, speech_rate=rate_pct)

    # ── 显式选了本机语音(离线):直接走,不降级(没语音包时用户要看到「怎么装」)──
    if _is_local_provider(provider):
        return _synthesize_local(text, voice=voice, model_voice=model_voice,
                                 gender=gender, speed=speed, subdir=subdir)

    # ── Path C 提前:voice 已是 Edge voice 名称时,直接走 Edge,绕开 volcengine ──
    if voice and ("Neural" in voice):
        try:
            return _synthesize_edge(text, voice=voice, speech_rate=rate_pct)
        except Exception as e:          # noqa: BLE001
            reasons.append(f"Edge TTS 失败 —— {str(e)[:200]}")   # Edge 不通再回头走火山

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
                volc_voice = model_voice or DEFAULT_VOICE
        _LAST_VOICE = volc_voice
        try:
            return _synthesize_volc(text, volc_voice, cfg, target_duration, speed)
        except Exception as e:          # noqa: BLE001 —— 豆包挂了就降级
            reasons.append(f"主通道({provider or 'volcengine'})失败 —— {str(e)[:300]}")

    # ── Path C:Edge TTS 兜底 ──
    chosen = voice if (voice and "Neural" in voice) else pick_edge_voice(text, gender)
    try:
        return _synthesize_edge(text, voice=chosen, speech_rate=rate_pct)
    except Exception as e:              # noqa: BLE001 —— Edge 也挂,最后落本机
        reasons.append(f"降级到微软 Edge 语音也失败 —— {str(e)[:300]}")

    # ── Path D:本机微软语音(离线)最后兜底 ──
    try:
        return _synthesize_local(text, voice=voice, model_voice=model_voice,
                                 gender=gender, speed=speed, subdir=subdir)
    except Exception as e:              # noqa: BLE001
        reasons.append(f"降级到本机微软语音也失败 —— {str(e)[:300]}")
    # 通道全灭:把每条通道的原因合并抛出,不留裸技术错误(原版同口径)
    raise RuntimeError("；".join(reasons) or "所有 TTS 通道都不可用")


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

    微软系通道探针报通道名与实际音色:edge=免费云端神经、local=本机离线
    (顺带报本机音色数,没装语音包时用户能立刻看出该装什么)。
    """
    provider = (cfg.get("provider") or "").strip().lower()
    if _is_local_provider(provider):
        try:
            voices = list_local_voices()
            if not voices:
                return False, LOCAL_TTS_MISSING_HINT
        except Exception as e:  # noqa: BLE001
            return False, str(e)[:300]
    voice = cfg.get("model") or ""
    if (_is_edge_provider(provider) or _is_local_provider(provider)):
        voice = voice or "auto"          # 微软系:按性别自动选,不硬塞火山 BV 号
    elif not voice or voice.upper().startswith("BV"):
        voice = DEFAULT_VOICE
    try:
        p = synthesize("你好", voice=None if voice == "auto" else voice,
                       config_id=cfg.get("id"))
        p.unlink(missing_ok=True)
        used = _LAST_VOICE or voice
        if _is_local_provider(provider):
            return True, f"OK(本机微软语音 · 音色 {used})"
        if _is_edge_provider(provider):
            return True, f"OK(Edge 神经语音 · 音色 {used})"
        return True, "OK(真实合成验证通过)"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]
