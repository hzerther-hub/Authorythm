# -*- coding: utf-8 -*-
"""Jev 两条新用途:参考图能力诊断 + 视频供应商路由。

**核心契约(用户明确要求):Jev 没开也必须正常运行。**
每条路径都要在 Jev 完全不可用时退回原行为,而且**不抛异常**。

**参考图能力判定的设计决策**(与最初设想不同,这里锁住原因):
最初想「白名单优先、Jev 兜底」,实测发现 **jev 在本项目真实配置上判错** ——
qwen-image / volcengine 都被它判成"支持参考图"(0.52/0.54),
而这两个恰恰是实测确认会静默丢参考图的 provider。它看到知名大厂域名就臆断。
所以能力判定退回**白名单为唯一真相源**,Jev 只作只读诊断线索。
若将来有别的模型能判对,这条测试是改动前的第一道闸。
"""
from __future__ import annotations

from app.ai import image_client, jev_ask, video_client


class _NoJev:
    """Jev 未配置 / 被禁用 / 不通的替身:usable=False。"""

    def __init__(self, reason="unconfigured", disabled=False):
        self.usable = False
        self.disabled = disabled
        self.reason = reason


class _StubBreaker:
    """替掉熔断器,测试里不依赖冷却状态。"""

    def in_cooldown(self):
        return False

    def note_ok(self):
        pass

    def note_fail(self):
        pass


# ── 用途一:参考图能力(白名单为唯一真相源) ────────────────────────

def test_whitelist_provider_never_asks_jev(monkeypatch):
    """白名单内的 provider 直接返回 True,一次网络请求都不发。"""
    called = []

    def boom(*a, **k):
        called.append(1)
        raise AssertionError("白名单命中时不该问 Jev")

    monkeypatch.setattr(jev_ask, "reference_capable", boom)
    image_client.clear_reference_capability_cache()
    for p in image_client.REFERENCE_CAPABLE_PROVIDERS:
        assert image_client.supports_reference_images(p) is True
    assert not called, "白名单命中却去问了 Jev"


def test_known_dropping_providers_are_never_capable(monkeypatch):
    """实测确认会丢参考图的两个 provider,即使 Jev 说支持也必须判不支持。

    这是本文件最重要的一条:防止有人日后把 jev 的判断重新接回决策链路。
    """
    monkeypatch.setattr(jev_ask, "reference_capable", lambda p, b="", m="": True)
    image_client.clear_reference_capability_cache()
    for p in ("qwen-image", "volcengine"):
        assert image_client.supports_reference_images(p) is False, \
            f"{p} 实测会丢参考图,不能因为 Jev 说支持就改成支持"


def test_jev_disabled_falls_back_to_false(monkeypatch):
    """Jev 未配置 → 不支持参考图(保守),且不抛异常。"""
    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _NoJev())
    image_client.clear_reference_capability_cache()
    assert image_client.supports_reference_images("qwen-image") is False


def test_jev_explicitly_disabled_by_env(monkeypatch):
    """JEV_ENABLED=0 / JEV_REF_ASK=0 → 完全不碰 Jev。"""
    monkeypatch.setenv("JEV_ENABLED", "0")
    monkeypatch.setenv("JEV_REF_ASK", "0")
    image_client.clear_reference_capability_cache()
    assert image_client.supports_reference_images("volcengine") is False
    assert jev_ask.reference_capable("volcengine") is None


def test_jev_raising_never_propagates(monkeypatch):
    """Jev 侧抛任何异常都不能让业务崩。"""

    def raiser(p, b="", m=""):
        raise RuntimeError("jev 炸了")

    monkeypatch.setattr(jev_ask, "reference_capable", raiser)
    image_client.clear_reference_capability_cache()
    assert image_client.supports_reference_images("boomvendor") is False


def test_empty_provider_is_conservative(monkeypatch):
    """provider 为空时不能被当成支持,否则会白花参考图的钱。"""
    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _NoJev())
    image_client.clear_reference_capability_cache()
    assert image_client.supports_reference_images(None) is False
    assert image_client.supports_reference_images("") is False


def test_signature_is_provider_only():
    """判定只吃 provider 名 —— 多余参数会让调用点以为它更精确,反而误用。"""
    import inspect
    sig = inspect.signature(image_client.supports_reference_images)
    assert list(sig.parameters) == ["provider"]


def test_hint_cache_is_not_a_decision_cache(monkeypatch):
    """诊断线索会缓存,但换了 provider 名不会串味。"""
    n = {"c": 0}

    def fake(p, b="", m=""):
        n["c"] += 1
        return True

    monkeypatch.setattr(jev_ask, "reference_capable", fake)
    image_client.clear_reference_capability_cache()
    for _ in range(3):
        assert image_client.supports_reference_images("brandnewvendor") is False
    assert n["c"] == 1, "诊断线索没有被缓存,每次都打网络"


# ── jev_ask.reference_capable 本身 ────────────────────────────────

def test_reference_capable_returns_none_when_jev_unavailable(monkeypatch):
    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _NoJev())
    assert jev_ask.reference_capable("whatever") is None


def test_reference_capable_never_raises_on_client_exception(monkeypatch):
    """客户端抛异常必须被吞成 None(软建议器契约)。"""
    class _Gate:
        usable = True
        disabled = False
        reason = None

        class _Client:
            def decide(self, state, questions):
                raise RuntimeError("network down")

        client = _Client()

    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _Gate())
    monkeypatch.setattr(jev_ask, "_ref_breaker", _StubBreaker())
    assert jev_ask.reference_capable("x") is None


def test_reference_capable_bad_answer_returns_none(monkeypatch):
    """答案结构对不上 → None,不猜。"""
    class _Gate:
        usable = True
        disabled = False
        reason = None

        class _Client:
            def decide(self, state, questions):
                return {"answers": {"binds_reference": {"noul": "不是数字"}}}

        client = _Client()

    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _Gate())
    monkeypatch.setattr(jev_ask, "_ref_breaker", _StubBreaker())
    assert jev_ask.reference_capable("x") is None


def test_reference_capable_respects_threshold(monkeypatch):
    """越过阈值返回 True,不过返回 False(诊断语义)。"""
    class _Gate:
        usable = True
        disabled = False
        reason = None

        def __init__(self, val):
            self.client = self._Client(val)

        class _Client:
            def __init__(self, val):
                self.val = val

            def decide(self, state, questions):
                return {"answers": {"binds_reference": {"noul": self.val},
                                    "strictness": {"score": 1.9}}}

    monkeypatch.setattr(jev_ask, "_ref_breaker", _StubBreaker())
    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _Gate(0.9))
    assert jev_ask.reference_capable("x") is True
    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _Gate(0.1))
    assert jev_ask.reference_capable("x") is False


# ── 用途二:视频供应商路由 ────────────────────────────────────────

def test_video_route_returns_none_without_jev(monkeypatch):
    """Jev 没开 → None,调用方继续用当前选择。"""
    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _NoJev())
    cands = {"agnes:agnes-video-2.5-flash": "Agnes 官方-video",
             "volcengine:seedance": "火山方舟"}
    assert jev_ask.pick_video_provider("国风 3D", cands) is None


def test_video_route_skips_single_candidate(monkeypatch):
    """只有一个候选时路由没有意义,不该为此发请求。"""
    called = []

    class _Gate:
        usable = True
        disabled = False
        reason = None

        class _Client:
            def decide(self, state, questions):
                called.append(1)
                return {"answers": {"best": {"choice": "a"}}}

        client = _Client()

    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _Gate())
    assert jev_ask.pick_video_provider("x", {"a": "只有一个"}) is None
    assert not called, "只有一个候选却发了请求"


def test_video_route_parses_choice_and_distribution(monkeypatch):
    """认 {"choice": k, "choices": {...}} 结构,返回 (key, 分布)。"""
    class _Gate:
        usable = True
        disabled = False
        reason = None

        class _Client:
            def decide(self, state, questions):
                return {"answers": {"best": {"choice": "agnes:x",
                                             "choices": {"agnes:x": 0.7, "volc:y": 0.3}}}}

        client = _Client()

    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _Gate())
    cands = {"agnes:x": "Agnes", "volc:y": "Volcengine"}
    got = jev_ask.pick_video_provider("国风 3D", cands)
    assert got is not None
    assert got[0] == "agnes:x"
    assert got[1]["volc:y"] == 0.3


def test_video_route_parses_dist_only_shape(monkeypatch):
    """只回 choices 分布(无 choice 字段)时取最高分。"""
    class _Gate:
        usable = True
        disabled = False
        reason = None

        class _Client:
            def decide(self, state, questions):
                return {"answers": {"best": {"choices": {"a": 0.2, "b": 0.8}}}}

        client = _Client()

    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _Gate())
    got = jev_ask.pick_video_provider("x", {"a": "A", "b": "B"})
    assert got[0] == "b"


def test_video_route_rejects_hallucinated_candidate(monkeypatch):
    """Jev 报了一个不存在的供应商 → None,绝不采用。"""
    class _Gate:
        usable = True
        disabled = False
        reason = None

        class _Client:
            def decide(self, state, questions):
                return {"answers": {"best": {"choice": "从未配置的供应商"}}}

        client = _Client()

    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _Gate())
    assert jev_ask.pick_video_provider("x", {"a": "A", "b": "B"}) is None


def test_video_route_env_kill_switch(monkeypatch):
    """JEV_VIDEO_ROUTE=0 显式关闭。"""
    monkeypatch.setenv("JEV_VIDEO_ROUTE", "0")
    assert jev_ask.pick_video_provider("x", {"a": "A", "b": "B"}) is None


def test_suggest_video_config_is_none_without_jev(monkeypatch):
    """UI 入口:Jev 不可用时返回 None,UI 只弹一句提示,不改选择。"""
    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _NoJev())
    assert video_client.suggest_video_config("国风 3D") is None


def test_probabilities_field_name(monkeypatch):
    """分布字段是 `probabilities`(实测网关如此),不是 `choices`。"""
    class _Gate:
        usable = True
        disabled = False
        reason = None

        class _Client:
            def decide(self, state, questions):
                return {"answers": {"best": {
                    "choice": "b", "confidence": 0.9,
                    "probabilities": {"a": 0.1, "b": 0.9}}}}

        client = _Client()

    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _Gate())
    got = jev_ask.pick_video_provider("x", {"a": "A", "b": "B"})
    assert got[1] == {"a": 0.1, "b": 0.9}, "没读到 probabilities 分布"


def test_low_confidence_flagged_when_distribution_is_flat(monkeypatch):
    """分布接近 → 标记低置信,如实告诉用户 jev 自己也不确定。

    实测依据:两个候选上,「3D 卡通」给 0.62、「写实电影」给 0.59,
    两种完全不同的需求压倒性偏向同一个 —— 它的判别力不足以包装成明确建议。
    """
    class _Gate:
        usable = True
        disabled = False
        reason = None

        class _Client:
            def decide(self, state, questions):
                return {"answers": {"best": {
                    "choice": "a",
                    "probabilities": {"a": 0.52, "b": 0.48}}}}

        client = _Client()

    monkeypatch.setattr(jev_ask, "get_jev_gate", lambda: _Gate())
    monkeypatch.setattr(jev_ask, "pick_video_provider",
                        lambda need, c=None: ("agnes:m", {"agnes:m": 0.52, "volc:n": 0.48}))
    rows = [{"id": 7, "is_active": 1, "provider": "agnes", "model": "m"}]
    monkeypatch.setattr("app.ai.registry.list_configs", lambda t: rows)
    got = jev_ask.pick_video_config_advisory("x")
    assert got is not None
    assert got[2] is True, "分布只差 0.04 却没标低置信"


def test_low_confidence_not_flagged_when_clear(monkeypatch):
    """分布明显分层 → 不标低置信。"""
    monkeypatch.setattr(jev_ask, "pick_video_provider",
                        lambda need, c=None: ("agnes:m", {"agnes:m": 0.85, "volc:n": 0.15}))
    rows = [{"id": 7, "is_active": 1, "provider": "agnes", "model": "m"}]
    monkeypatch.setattr("app.ai.registry.list_configs", lambda t: rows)
    got = jev_ask.pick_video_config_advisory("x")
    assert got[2] is False


def test_advisory_returns_none_for_unknown_pick(monkeypatch):
    """Jev 报的配置对不上活跃配置 → None,绝不给出建议。"""
    monkeypatch.setattr(jev_ask, "pick_video_provider",
                        lambda need, c=None: ("已删除的配置", {}))
    rows = [{"id": 7, "is_active": 1, "provider": "agnes", "model": "m"}]
    monkeypatch.setattr("app.ai.registry.list_configs", lambda t: rows)
    assert jev_ask.pick_video_config_advisory("x") is None


def test_advisory_ignores_inactive_config(monkeypatch):
    """指向已停用的配置 → None,不建议用不能用的配置。"""
    monkeypatch.setattr(jev_ask, "pick_video_provider",
                        lambda need, c=None: ("agnes:m", {}))
    rows = [{"id": 7, "is_active": 0, "provider": "agnes", "model": "m"}]
    monkeypatch.setattr("app.ai.registry.list_configs", lambda t: rows)
    assert jev_ask.pick_video_config_advisory("x") is None


def test_candidates_read_from_live_configs(monkeypatch):
    """候选必须现取:用户改了配置,候选表要跟着变。"""
    monkeypatch.setattr("app.ai.registry.list_configs", lambda t: [
        {"id": 1, "is_active": 1, "provider": "agnes", "model": "m1", "remark": "备注A"},
        {"id": 2, "is_active": 0, "provider": "volc", "model": "m2", "remark": "已停用"},
        {"id": 3, "is_active": 1, "provider": "volc", "model": "m3", "remark": ""},
    ])
    c = jev_ask.video_provider_candidates()
    assert "agnes:m1" in c and c["agnes:m1"] == "备注A"
    assert "volc:m3" in c and c["volc:m3"] == "volc", "remark 空时应回退到 provider 名"
    assert "volc:m2" not in c, "已停用的配置不该进候选"


def test_candidates_never_raise_on_db_error(monkeypatch):
    """读配置炸了 → 空候选,路由静默跳过。"""

    def boom(t):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.ai.registry.list_configs", boom)
    assert jev_ask.video_provider_candidates() == {}


def test_suggest_video_config_never_raises(monkeypatch):
    """Jev 侧炸了,UI 入口也不能抛 —— 点了按钮不能崩。"""

    def raiser(*a, **k):
        raise RuntimeError("jev 炸了")

    monkeypatch.setattr(jev_ask, "pick_video_provider", raiser)
    assert video_client.suggest_video_config("x") is None


def test_generate_video_signature_unchanged():
    """路由是旁路能力,generate_video 的签名与默认行为不得改变。"""
    import inspect
    sig = inspect.signature(video_client.generate_video)
    assert sig.parameters["config_id"].default is None
    # 没有偷偷新增会改写供应商的参数
    assert "auto_route" not in sig.parameters
