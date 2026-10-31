"""微软系 TTS 通道(Edge 免费 / 本机离线)的对齐回归测试。

对齐基准:原版 E:\\xiaoshuo fffd6bf(Edge 通道 + 主通道自动降级)与
d98e59d(本机微软语音 + 性别切换)。锁住:
- provider 别名识别(edge/local 及常见写法);
- 本机选音优先级:显式指定 > 配置置顶(性别不冲突)> 按性别挑中文 > 兜底;
  置顶与性别**冲突**时必须跳过 —— 这是「切换性别」能生效的关键;
- atempo 链边界(0.5 下限 / 2.0 上限 / 慢于 0.5 串联);
- 显式选了 edge/local 的合成**不降级**(调主通道抛错必须原样上抛);
- 默认主通道失败 → Edge → 本机的降级链与原因合并;
- registry:微软两条预置存在、edge/local 免 Key 免 Base URL;
- list_local_voices 的 PowerShell 输出解析(打桩,不真跑 PowerShell)。

不碰真实库、不真调 PowerShell/网络。
"""
from __future__ import annotations

import json

import pytest

from app.ai import registry
from app.ai import tts_client as tc

VOICES = [
    {"id": "winrt:Microsoft Huihui", "name": "Microsoft Huihui",
     "lang": "zh-CN", "gender": "female", "engine": "winrt"},
    {"id": "winrt:Microsoft Kangkang", "name": "Microsoft Kangkang",
     "lang": "zh-CN", "gender": "male", "engine": "winrt"},
    {"id": "sapi:Microsoft Zira Desktop", "name": "Microsoft Zira Desktop",
     "lang": "en-US", "gender": "female", "engine": "sapi"},
]


# ── provider 别名 ─────────────────────────────────────────────────

def test_edge_and_local_provider_aliases():
    assert tc._is_edge_provider("edge")
    assert tc._is_edge_provider("Edge-TTS ")
    assert tc._is_edge_provider("microsoft-edge")
    assert not tc._is_edge_provider("volcengine")
    assert not tc._is_edge_provider(None)
    assert tc._is_local_provider("local")
    assert tc._is_local_provider("Local-TTS")
    assert tc._is_local_provider("win-local")
    assert not tc._is_local_provider("edge")


# ── 本机选音优先级 ─────────────────────────────────────────────────

def test_resolve_local_voice_explicit_name_wins():
    v = tc._resolve_local_voice(VOICES, "Microsoft Kangkang", "Microsoft Huihui",
                                "female")
    assert v["name"] == "Microsoft Kangkang"      # 显式指定压过一切


def test_resolve_local_voice_pinned_skipped_on_gender_conflict():
    """置顶女声 + 切男声 → 置顶被跳过改用男声(原版注释:这是性别切换能生效的关键)。"""
    v = tc._resolve_local_voice(VOICES, None, "Microsoft Huihui", "male")
    assert v["gender"] == "male" and v["name"] == "Microsoft Kangkang"


def test_resolve_local_voice_pinned_used_when_gender_matches():
    v = tc._resolve_local_voice(VOICES, None, "Microsoft Zira Desktop", "female")
    assert v["name"] == "Microsoft Zira Desktop"  # 不冲突 → 置顶生效


def test_resolve_local_voice_gender_then_any_zh_then_first():
    only_en = [VOICES[2]]
    v = tc._resolve_local_voice(VOICES, None, "", "male")
    assert v["name"] == "Microsoft Kangkang"      # 按性别挑中文
    v2 = tc._resolve_local_voice(only_en, None, "", "male")
    assert v2["name"] == "Microsoft Zira Desktop"  # 没中文 → 第一个
    assert tc._resolve_local_voice([], None, "", "female") is None


def test_resolve_local_voice_auto_means_unspecified():
    assert tc._find_local_voice(VOICES, "auto") is None   # auto = 按性别自动


# ── atempo 链 ──────────────────────────────────────────────────────

def test_atempo_chain_bounds():
    assert tc._atempo_chain(1.5) == "atempo=1.5000"
    assert tc._atempo_chain(2.5) == "atempo=2.0000"       # 上限 2.0
    assert tc._atempo_chain(0.3) == "atempo=0.5000"       # 下限 0.5(钳住)
    assert tc._atempo_chain(1) == "atempo=1.0000"


# ── 分派:显式通道不降级 / 默认链降级 ───────────────────────────────

class _FakeCfg(dict):
    pass


def _with_cfg(monkeypatch, cfg):
    monkeypatch.setattr(tc.registry, "check_ready",
                        lambda st, cid=None: _FakeCfg(cfg))


def test_explicit_local_provider_never_falls_back(monkeypatch):
    """显式选本机语音:local 合成抛错必须原样上抛,不许悄悄换通道。"""
    _with_cfg(monkeypatch, {"provider": "local", "api_key": "", "model": "auto",
                            "models": "[]", "base_url": ""})
    calls = []

    def _boom(*a, **k):
        calls.append("local")
        raise RuntimeError("没有检测到本机微软语音音色。请安装语音包")

    monkeypatch.setattr(tc, "_synthesize_local", _boom)
    monkeypatch.setattr(tc, "_synthesize_edge",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该降级到 Edge")))
    with pytest.raises(RuntimeError, match="语音包"):
        tc.synthesize("你好", gender="female")
    assert calls == ["local"]


def test_explicit_edge_provider_never_calls_volc(monkeypatch):
    _with_cfg(monkeypatch, {"provider": "edge", "api_key": "", "model": "auto",
                            "models": "[]", "base_url": ""})
    out = tc._out_path()
    monkeypatch.setattr(tc, "_synthesize_edge",
                        lambda text, voice="v", speech_rate=0: out)
    monkeypatch.setattr(tc, "_synthesize_volc",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该走火山")))
    assert tc.synthesize("你好", gender="female") == out


def test_default_chain_degrades_and_merges_reasons(monkeypatch):
    """默认(火山)配置:主通道 → Edge → 本机 全灭时,三段原因合并抛出。"""
    _with_cfg(monkeypatch, {"provider": "volcengine", "api_key": "sk-x",
                            "model": "BV001_streaming", "models": "[]",
                            "base_url": "https://openspeech.bytedance.com"})
    monkeypatch.setattr(tc, "_synthesize_volc",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429 quota")))
    monkeypatch.setattr(tc, "_synthesize_edge",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("edge down")))
    monkeypatch.setattr(tc, "_synthesize_local",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no voice")))
    with pytest.raises(RuntimeError) as ei:
        tc.synthesize("你好", gender="female")
    msg = str(ei.value)
    assert "429 quota" in msg and "edge down" in msg and "no voice" in msg


def test_default_chain_local_is_final_net(monkeypatch):
    """Edge 挂了但本机有音色 → 本机兜底成功,不抛错。"""
    _with_cfg(monkeypatch, {"provider": "volcengine", "api_key": "", "model": "",
                            "models": "[]", "base_url": ""})
    out = tc._out_path()

    def _fake_local(*a, **k):
        tc._LAST_VOICE = "Microsoft Huihui"     # 与真实实现同口径:选音后记录
        return out

    monkeypatch.setattr(tc, "_synthesize_edge",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("edge down")))
    monkeypatch.setattr(tc, "_synthesize_local", _fake_local)
    assert tc.synthesize("你好", gender="female") == out
    assert tc.last_voice() == "Microsoft Huihui"  # 本机通道也要记录音色


# ── list_local_voices:PowerShell 输出解析(打桩)──────────────────

def test_list_local_voices_parses_powershell_json(monkeypatch):
    payload = [
        {"name": "Microsoft Huihui Desktop", "lang": "zh-CN",
         "gender": "Female", "engine": "sapi"},
        {"name": "Microsoft Kangkang", "lang": "zh-CN",
         "gender": "Male", "engine": "winrt"},
        {"name": "", "lang": "fr-FR", "gender": "Female", "engine": "winrt"},
    ]

    def fake_ps(script, args, timeout_s=60):
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(tc, "_run_powershell", fake_ps)
    voices = tc.list_local_voices()
    assert len(voices) == 2                       # 空名条目被滤掉
    assert voices[0]["id"] == "sapi:Microsoft Huihui Desktop"
    assert voices[0]["gender"] == "female"
    assert voices[1]["gender"] == "male"


def test_list_local_voices_swallows_errors(monkeypatch):
    def fake_ps(script, args, timeout_s=60):
        raise RuntimeError("powershell gone")
    monkeypatch.setattr(tc, "_run_powershell", fake_ps)
    assert tc.list_local_voices() == []           # 枚举失败 = 没有,不抛


# ── registry:预置与校验豁免 ────────────────────────────────────────

def test_tts_presets_include_microsoft_channels():
    providers = {p["provider"] for p in registry.PROVIDER_PRESETS["tts"]}
    assert {"volcengine", "edge", "local"} <= providers


def test_check_ready_exempts_key_and_url_for_microsoft(tmp_path, monkeypatch):
    """edge/local 配置:免 API Key、免 Base URL,不再被 check_ready 拦下。"""
    monkeypatch.setattr(registry.db.config, "DB_PATH", tmp_path / "tts.sqlite3")
    old = getattr(registry.db._local, "conn", None)
    if old is not None:
        old.close()
    registry.db._local.conn = None
    registry.db.init_db()
    try:
        registry.add_config("tts", "edge", "", "auto", api_key="",
                            remark="Edge 免费")
        cfg = registry.check_ready("tts")
        assert cfg["provider"] == "edge"
        registry.add_config("tts", "local", "", "auto", api_key="",
                            remark="本机离线")
        cfg2 = registry.check_ready("tts", cfg["id"])   # 指定 id 取回 edge 那条
        assert cfg2["provider"] == "edge"
    finally:
        conn = getattr(registry.db._local, "conn", None)
        if conn is not None:
            conn.close()
            registry.db._local.conn = None


def test_ps1_script_written_with_bom(tmp_path):
    """PS 5.1 无 BOM 按 ANSI 解析中文 → 脚本必须带 UTF-8 BOM(原版踩过的坑)。"""
    f = tmp_path / "s.ps1"
    tc._write_ps1(f, "$x = '中文'")
    assert f.read_bytes()[:3] == b"\xef\xbb\xbf"
