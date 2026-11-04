"""所有文本模型的最大输出 token 一律从服务配置获取(用户定版,2026-11-01)。

背景:整书导入的分析/仿写连环空转,排查发现多条业务调用链还在显式传
硬编码 max_tokens(32768/128000/2048/1024/512/256)—— 它们会把用户在
设置页「最大输出 token」里填的预算顶掉,推理模型预算不够时没有任何入口可调。

预算的取值链(text_client._build_body / runner._configured_budget 同一口径):
    调用方显式值 > 服务配置里手填的 max_tokens > TEXT_DEFAULT_MAX_TOKENS(128000)
所以「从配置获取」= 业务调用点**不传** max_tokens;确实要传的(如 novel 的
预算阶梯)首档也必须来自配置。

本守卫用 AST 扫全 app:任何调用给 max_tokens 传**数字字面量**即红。
允许:None(=走配置)、变量传值(阶梯/配置派生)、text_client.test_config 的
连通性探针(8 token 的 ping,不是业务调用)。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
# 连通性探针:发 8 token 的 "ping" 验证 base_url/key 可用,与业务预算无关
ALLOWED_FILES = {"text_client.py"}


def _literal_max_tokens_calls():
    out = []
    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in path.parts or path.name in ALLOWED_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "max_tokens":
                    continue
                v = kw.value
                # None 字面量 = 显式走配置,放行;变量/表达式 = 调用方派生(如
                # novel 的预算阶梯,首档来自配置),放行;数字字面量 = 硬编码,红。
                if isinstance(v, ast.Constant) and isinstance(v.value, (int, float)):
                    out.append(f"{path.relative_to(ROOT)}:{node.lineno} "
                               f"max_tokens={v.value!r}")
    return out


def test_no_hardcoded_max_tokens_in_business_calls():
    bad = _literal_max_tokens_calls()
    assert not bad, (
        f"有 {len(bad)} 处调用硬编码了 max_tokens(把配置里的预算顶掉了):\n  "
        + "\n  ".join(bad)
        + "\n修法:删掉该实参,让 text_client/runner 从服务配置的 max_tokens 取值;"
          "推理模型预算不够请到设置页调大该模型配置的「最大输出 token」。")


def test_configured_budget_prefers_service_config(monkeypatch):
    """runner 的预算阶梯首档必须优先取服务配置手填的值。"""
    import tempfile

    from app.agents import runner as _runner
    from app.ai import registry
    from app.core import config as _config
    from app.core import db as _db

    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setattr(_config, "DB_PATH", tmp / "mt.sqlite3")
    old = getattr(_db._local, "conn", None)
    if old is not None:
        old.close()
    _db._local.conn = None
    _db.init_db()
    try:
        cfg_id = registry.add_config(
            "text", provider="custom", base_url="https://example.invalid/v1",
            model="test-model", api_key="sk-test", is_default=True,
            max_tokens=45000)
        assert _runner._configured_budget(cfg_id, None) == 45000, \
            "配置里手填的 max_tokens 必须是阶梯首档"
        # 显式传值仍然最优先(阶梯语义:调用方真有理由覆盖时)
        assert _runner._configured_budget(cfg_id, 60000) == 60000
    finally:
        if getattr(_db._local, "conn", None) is not None:
            _db._local.conn.close()
            _db._local.conn = None
