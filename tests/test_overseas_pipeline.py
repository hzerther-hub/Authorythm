# -*- coding: utf-8 -*-
"""海外题材改写 · 流水线与落库。

**测试不许碰真实库**:`data/yihao.sqlite3` 是用户数据,落库路径全部走临时库。
LLM 一律 monkeypatch 打桩,不真调模型。
"""
from __future__ import annotations

import json

import pytest

from app.core import db
from app.pipeline import overseas


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db.config, "DB_PATH", tmp_path / "oversea.sqlite3")
    old = getattr(db._local, "conn", None)
    if old is not None:
        old.close()
    db._local.conn = None
    db.init_db()
    yield
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        db._local.conn = None


DIAG_JSON = {
    "level": "B",
    "level_reason": "主线可留,文化专名要换",
    "diagnosis": {"setting": {"score": 2, "notes": "货币单位要改"},
                   "structure": {"score": 1, "notes": "开篇没钩子"},
                   "pacing": {"score": 2, "notes": "章末弱"},
                   "language": {"score": 2, "notes": "自指观察"},
                   "compliance": {"score": 2, "notes": "全角标点"}},
    "issues": [{"type": "自指观察", "quote": "我的脸红了", "fix": "改成手指发白"}],
    "opening": {"hook": "电话", "payoff_chapter": 2, "notes": "以电话开场"},
    "glossary": [{"source": "林晚", "target": "Lin Wan", "type": "人名", "note": "女主"}],
    "culture_mappings": [{"source": "总裁", "target": "the CEO", "note": "职位"}],
}


def _fake_run_agent(payload):
    def _run(agent_type, user_prompt, **kwargs):
        _run.calls.append((agent_type, user_prompt, kwargs))
        return payload
    _run.calls = []
    return _run


# ---------------------------------------------------------------- 诊断

def test_diagnose_returns_level_and_glossary(monkeypatch):
    fake = _fake_run_agent(json.dumps(DIAG_JSON, ensure_ascii=False))
    monkeypatch.setattr(overseas.runner, "run_agent", fake)
    monkeypatch.setattr(overseas.runner, "extract_json",
                        lambda t: json.loads(t))
    res = overseas.diagnose(source="我的脸红了。", platform="goodnovel",
                            category="billionaire")
    assert res["level"] == "B"
    assert res["glossary"]["林晚"] == "Lin Wan"
    # 品类术语种子要兜底补上(模型漏抽的专名)
    assert res["glossary"].get("霸总") == "the CEO"
    assert res["culture_mappings"][0]["target"] == "the CEO"
    # 规则片段要进 prompt
    assert "GoodNovel" in fake.calls[0][1]


def test_diagnose_raises_on_empty_source():
    with pytest.raises(ValueError):
        overseas.diagnose(source="   ", platform="goodnovel", category="billionaire")


def test_diagnose_uses_config_fallback(monkeypatch):
    """config_id 传 None 时要回落到全局默认文本模型,不能静默传 None 出去。"""
    from app.ai import registry
    fake = _fake_run_agent(json.dumps(DIAG_JSON, ensure_ascii=False))
    monkeypatch.setattr(overseas.runner, "run_agent", fake)
    monkeypatch.setattr(overseas.runner, "extract_json", lambda t: json.loads(t))
    monkeypatch.setattr(registry, "default_config",
                        lambda st, cid=None: {"id": 4242})
    overseas.diagnose(source="一段中文。", platform="goodnovel",
                      category="billionaire")
    assert fake.calls[0][2]["config_id"] == 4242


def test_default_text_config_survives_none(monkeypatch):
    """default_config 返回 None 时不能 AttributeError(设置页崩的老坑)。"""
    from app.ai import registry
    monkeypatch.setattr(registry, "default_config", lambda st, cid=None: None)
    assert overseas._default_text_config() is None


# ---------------------------------------------------------------- 改写

def test_rewrite_strips_think_and_fence(monkeypatch):
    payload = ("<think>先想一下</think>\n\n```\nAt midnight she waited.\n```")
    fake = _fake_run_agent(payload)
    monkeypatch.setattr(overseas.runner, "run_agent", fake)
    res = overseas.rewrite(source="午夜,她在等。", platform="goodnovel",
                           category="billionaire", level="B",
                           glossary={"林晚": "Lin Wan"})
    assert "<think>" not in res["content"]
    assert "```" not in res["content"]
    assert res["content"].startswith("At midnight")
    # 术语表要进 prompt
    assert "Lin Wan" in fake.calls[0][1]


def test_rewrite_raises_on_empty_source():
    with pytest.raises(ValueError):
        overseas.rewrite(source="", platform="goodnovel", category="billionaire")


# ---------------------------------------------------------------- 质检

def test_check_returns_issues_for_bad_draft():
    issues = overseas.check("我的脸红了。", platform="goodnovel",
                            category="billionaire")
    assert any(i.rule == "R1" for i in issues)


def test_check_quiet_for_clean_draft():
    issues = overseas.check(
        "She opened the door. Her phone lit up. Before she could answer, "
        "a car door slammed outside.", platform="goodnovel", category="billionaire")
    assert not any(i.rule in ("R1", "R4") for i in issues)


def test_check_survives_unknown_platform():
    """规则 id 不存在时不能抛异常,应安静返回空。"""
    assert overseas.check("hi", platform="nope", category="nope") == []


# ---------------------------------------------------------------- 落库

def test_save_project_and_chapter_roundtrip(tmp_db):
    pid = overseas.save_project(drama_id=900001, episode_id=900002,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="中文原稿",
                                glossary={"林晚": "Lin Wan"},
                                diag=DIAG_JSON)
    assert pid > 0
    row = db.q1("SELECT * FROM overseas_project WHERE id=?", (pid,))
    assert row["platform"] == "goodnovel"
    assert row["status"] == "diagnosed"
    assert json.loads(row["glossary_json"])["林晚"] == "Lin Wan"

    cid = overseas.save_chapter(project_id=pid, episode_id=900002,
                                chapter_no=1, content="At midnight she waited.",
                                title="Ch1", notes="n", qc=[])
    assert cid > 0
    rows = overseas.list_chapters(pid)
    assert len(rows) == 1
    assert rows[0]["status"] == "done"
    assert rows[0]["words"] > 0


def test_update_project_only_touches_allowed_fields(tmp_db):
    pid = overseas.save_project(drama_id=900003, episode_id=None,
                                platform="dreame", category="werewolf",
                                level="A", source_text="x")
    overseas.update_project(pid, level="C", status="done", bogus_field="x")
    row = db.q1("SELECT * FROM overseas_project WHERE id=?", (pid,))
    assert row["level"] == "C"
    assert row["status"] == "done"


# ---------------------------------------------------------------- 跨章一致性
# 用户问题:「一章一章的改,怎么保证情节一致?」—— 三件套:滚动衔接 / 术语累积 /
# project 复用。以下用例锁住这三件事。

def test_rewrite_injects_prev_tail_block(monkeypatch):
    """有上一章改写稿结尾时,prompt 必须含「上一章衔接」硬约束节。"""
    got = {}

    def fake_run(agent, prompt, **kw):
        got["prompt"] = prompt
        return "She stared at the contract."

    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)
    overseas.rewrite(source="第三章原文", platform="goodnovel",
                     category="billionaire", glossary={"林晚": "Lin Wan"},
                     prev_tail="…the door closed behind Lin Wan.",
                     target_lang="en-US")
    p = got["prompt"]
    assert "上一章衔接" in p and "the door closed behind Lin Wan." in p
    assert "不得凭空恢复" in p                    # 人物状态硬约束在场


def test_rewrite_without_prev_tail_has_no_block(monkeypatch):
    """第一章/孤立改写:不注入衔接节(空占位只会误导模型)。"""
    got = {}

    def fake_run(agent, prompt, **kw):
        got["prompt"] = prompt
        return "Chapter one."

    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)
    overseas.rewrite(source="第一章原文", platform="goodnovel",
                     category="billionaire", glossary={"林晚": "Lin Wan"})
    assert "上一章衔接" not in got["prompt"]


def test_find_project_reuses_same_params(tmp_db):
    """同书同参数只认一个 project;换平台/语言另起(链不能串)。"""
    p1 = overseas.save_project(drama_id=900010, episode_id=None,
                               platform="goodnovel", category="billionaire",
                               level="B", source_text="x",
                               target_lang="en-US")
    assert overseas.find_project(900010, "goodnovel", "billionaire", "en-US") == p1
    assert overseas.find_project(900010, "dreame", "billionaire", "en-US") == 0
    assert overseas.find_project(900010, "goodnovel", "billionaire", "es-ES") == 0
    assert overseas.find_project(999999, "goodnovel", "billionaire", "en-US") == 0


def test_extract_new_terms_merges_only_new(monkeypatch):
    """增量抽取:只留术语表还没有的新词(表里已有的剔除,模型复读也不并回去)。"""
    def fake_run(agent, prompt, **kw):
        assert "林晚" in prompt                    # 现有表要喂给模型对齐风格
        return json.dumps({"new_terms": {"林晚": "Lin Wan",       # 已有 → 剔除
                                         "沈砚": "Shen Yan",      # 新 → 保留
                                         "": "x"}}, ensure_ascii=False)

    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)
    out = overseas.extract_new_terms("沈砚走进来。", {"林晚": "Lin Wan"})
    assert out == {"沈砚": "Shen Yan"}


def test_extract_new_terms_failure_returns_empty(monkeypatch):
    """抽取是增强不是依赖:模型挂了返回空 dict,不阻塞改写。"""
    def fake_run(agent, prompt, **kw):
        raise RuntimeError("429")
    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)
    assert overseas.extract_new_terms("正文", {"a": "b"}) == {}


def test_next_chapter_no_reuse_and_increment(tmp_db):
    """章号:重改本集沿用原号(不占新章);新集 = max+1(此前硬编码 1)。"""
    pid = overseas.save_project(drama_id=900011, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x")
    overseas.save_chapter(project_id=pid, episode_id=101, chapter_no=1,
                          content="chapter one")
    overseas.save_chapter(project_id=pid, episode_id=102, chapter_no=2,
                          content="chapter two")
    assert overseas.next_chapter_no(pid, 103) == 3      # 新集 → max+1
    assert overseas.next_chapter_no(pid, 102) == 2      # 重改第 2 集 → 沿用
    assert overseas.next_chapter_no(pid, None) == 3     # 无集上下文 → max+1


def test_chapter_tail_takes_latest_rewritten_not_source(tmp_db):
    """衔接锚 = 章号**严格小于当前章**的最大那章改写稿结尾。

    按章号而不是「跳过自己取最大」:重改第 1 章时若取最大,会把**后面的**
    第 2 章当上一章,倒序污染 —— 必须为空。"""
    pid = overseas.save_project(drama_id=900012, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x")
    overseas.save_chapter(project_id=pid, episode_id=201, chapter_no=1,
                          content="A" * 50 + "THE-FIRST-END")
    overseas.save_chapter(project_id=pid, episode_id=202, chapter_no=2,
                          content="B" * 50 + "THE-LATEST-END")
    # 写第 3 章 → 锚是第 2 章结尾
    assert "THE-LATEST-END" in overseas.chapter_tail(pid, 3)
    # 重改第 2 章 → 锚退到第 1 章结尾
    assert overseas.chapter_tail(pid, 2).endswith("THE-FIRST-END")
    # 重改第 1 章 → 没有上一章,锚为空
    assert overseas.chapter_tail(pid, 1) == ""
    assert overseas.chapter_tail(999999, 5) == ""       # 没有历史 → 空串


# ---------------------------------------------------------------- 顺序红线
# 用户规则(2026-10-24):上一章没改写,本章不能改 —— 跨章一致依赖上一章改写稿。

def _mk_eps(drama_id: int, nums: list) -> dict:
    """建集,返回 {episode_number: episode_id}。"""
    out = {}
    for n in nums:
        db.ex("""INSERT INTO episodes(drama_id,episode_number,title,content,status,
                 resolution,created_at,updated_at) VALUES(?,?,?,?,'draft','720p',?,?)""",
              (drama_id, n, f"第{n}章", f"第{n}章正文" * 30, db.now(), db.now()))
        out[n] = db.get_db().execute(
            "SELECT id FROM episodes ORDER BY id DESC LIMIT 1").fetchone()["id"]
    return out


def test_sequential_gate_blocks_when_previous_not_rewritten(tmp_db):
    """第 2 章:上一集(第 1 章)在同 project 没改写稿 → 拒绝,错误带上一章标题。"""
    eps = _mk_eps(900020, [1, 2])
    pid = overseas.save_project(drama_id=900020, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x", target_lang="es-ES")
    with pytest.raises(RuntimeError, match="第1章.*还没有改写"):
        overseas.assert_previous_rewritten(pid, eps[2])
    with pytest.raises(RuntimeError):        # 连 project 都没有 → 同样拒绝
        overseas.assert_previous_rewritten(0, eps[2])


def test_sequential_gate_passes_when_previous_done(tmp_db):
    """上一集已有同 project 改写稿 → 放行(重改本章也放行)。"""
    eps = _mk_eps(900021, [1, 2])
    pid = overseas.save_project(drama_id=900021, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x", target_lang="es-ES")
    overseas.save_chapter(project_id=pid, episode_id=eps[1], chapter_no=1,
                          content="Capitulo uno.")
    overseas.assert_previous_rewritten(pid, eps[2])     # 不抛即通过


def test_sequential_gate_scoped_per_project_language(tmp_db):
    """各语言各有各的链:英文链改完第 1 章,西语链的第 2 章照样被拒。"""
    eps = _mk_eps(900022, [1, 2])
    en_pid = overseas.save_project(drama_id=900022, episode_id=None,
                                   platform="goodnovel", category="billionaire",
                                   level="B", source_text="x", target_lang="en-US")
    overseas.save_chapter(project_id=en_pid, episode_id=eps[1], chapter_no=1,
                          content="Chapter one.")
    es_pid = overseas.find_project(900022, "goodnovel", "billionaire", "es-ES")
    assert es_pid in (0, None)
    with pytest.raises(RuntimeError):
        overseas.assert_previous_rewritten(es_pid or 0, eps[2])


def test_sequential_gate_first_chapter_and_paste_always_pass(tmp_db):
    """第 1 章无前置恒放行;手动粘贴流(episode_id=None)天然顺序,不设卡。"""
    eps = _mk_eps(900023, [1, 2])
    overseas.assert_previous_rewritten(0, eps[1])       # 第 1 章,没 project 也放行
    overseas.assert_previous_rewritten(12345, None)     # 粘贴流


def test_sequential_gate_tolerates_episode_gaps(tmp_db):
    """集号不连续(第 1、3 集存在,2 被删):改第 3 集只要求第 1 集已改。"""
    eps = _mk_eps(900024, [1, 3])
    pid = overseas.save_project(drama_id=900024, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x")
    with pytest.raises(RuntimeError, match="第1章"):
        overseas.assert_previous_rewritten(pid, eps[3])
    overseas.save_chapter(project_id=pid, episode_id=eps[1], chapter_no=1,
                          content="one.")
    overseas.assert_previous_rewritten(pid, eps[3])


# ---------------------------------------------------------------- 西化书名
# 用户问:「小说的名字怎么西化?」—— 诊断顺带按平台 title_style 出目标语言书名,
# 不直译中文书名(直译在海外平台没有点击欲)。

TITLE_DIAG = {**DIAG_JSON, "title": {
    "main": "Divorced Billionaire Heiress", "alts": ["Her Secret Fortune", ""],
    "reason": "踩中核心冲突+身份反差"}}


def test_diagnose_returns_localized_title(monkeypatch):
    fake = _fake_run_agent(json.dumps(TITLE_DIAG, ensure_ascii=False))
    monkeypatch.setattr(overseas.runner, "run_agent", fake)
    monkeypatch.setattr(overseas.runner, "extract_json", lambda t: json.loads(t))
    res = overseas.diagnose(source="正文", platform="goodnovel",
                            category="billionaire", book_title="离婚后我成了首富")
    assert res["title_target"] == "Divorced Billionaire Heiress"
    assert res["title_alts"] == ["Her Secret Fortune"]     # 空备选被滤掉,至多 2 个
    assert res["title_reason"]
    # 中文书名要进 prompt(不给书名就不该出现书名节)
    assert "离婚后我成了首富" in fake.calls[0][1]


def test_diagnose_without_book_title_skips_title_section(monkeypatch):
    """没给中文书名 → prompt 不含书名节(模型没看过全书,凭空造的书名与内容无关)。"""
    fake = _fake_run_agent(json.dumps(DIAG_JSON, ensure_ascii=False))
    monkeypatch.setattr(overseas.runner, "run_agent", fake)
    monkeypatch.setattr(overseas.runner, "extract_json", lambda t: json.loads(t))
    res = overseas.diagnose(source="正文", platform="goodnovel",
                            category="billionaire")
    assert "中文书名" not in fake.calls[0][1]
    assert res["title_target"] == ""                        # 老响应无 title → 空


def test_title_target_persists_on_project(tmp_db):
    pid = overseas.save_project(drama_id=900030, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x",
                                title_target="Divorced Billionaire Heiress")
    assert db.q1("SELECT title_target FROM overseas_project WHERE id=?",
                 (pid,))["title_target"] == "Divorced Billionaire Heiress"
    overseas.update_project(pid, title_target="Her Secret Fortune")
    assert db.q1("SELECT title_target FROM overseas_project WHERE id=?",
                 (pid,))["title_target"] == "Her Secret Fortune"


# ---------------------------------------------------------------- 全翻译模式
# 用户需求(2026-10-24):模式下拉加「全翻译」—— 只译不改,与改写三档并存。

def test_translate_mode_prompt_has_no_platform_rules(monkeypatch):
    """全翻译(T):prompt 不含平台规则节、不含上一章衔接;含忠实翻译指令。"""
    got = {}

    def fake_run(agent, prompt, **kw):
        got["prompt"] = prompt
        return "Ella abrió la puerta."

    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)
    res = overseas.rewrite(source="她推开了门。", platform="goodnovel",
                           category="billionaire", level="T",
                           glossary={"林晚": "Lin Wan"},
                           prev_tail="…previous tail…", target_lang="es-ES")
    assert res["level"] == "T"
    p = got["prompt"]
    assert "全翻译" in p and "零改动" in p
    assert "目标平台规格" not in p          # 平台规则是改写套路,翻译不带
    assert "previous tail" not in p         # 衔接硬约束授权改开头,与忠实翻译矛盾
    assert "林晚" in p                      # 术语表仍生效(译名链不能断)


def test_check_translate_mode_skips_platform_rules():
    """全翻译:平台结构规则(章末钩子 R9 等)不适用 —— 忠实翻译保留原文结构,
    被它们打回全是误报;语言层(中文残留 R4)照常。"""
    flat = ("Ella abrió la puerta. Él se fue. " * 30) + "。她说。"
    strict = overseas.check(flat, platform="goodnovel",
                            category="billionaire", level="B", target_lang="en-US")
    rules_strict = {i.rule for i in strict}
    loose = overseas.check(flat, platform="goodnovel",
                           category="billionaire", level="T", target_lang="en-US")
    rules_loose = {i.rule for i in loose}
    assert "R4" in rules_loose                     # 中文残留照常抓
    dropped = rules_strict - rules_loose
    assert dropped and dropped <= {"R6", "R7", "R8", "R9", "R11"}  # 平台结构类被放行


def test_diagnose_truncates_overlong_source(monkeypatch):
    """多章/整本粘进原文区时,诊断采样头 9000 + 尾 3000(截图实测:原文区带滚动条,
    不截会把整段塞进一次调用 —— 爆上下文/烧钱)。"""
    long_src = "开" * 20000 + "尾" * 5000
    fake = _fake_run_agent(json.dumps(DIAG_JSON, ensure_ascii=False))
    monkeypatch.setattr(overseas.runner, "run_agent", fake)
    monkeypatch.setattr(overseas.runner, "extract_json", lambda t: json.loads(t))
    overseas.diagnose(source=long_src, platform="goodnovel",
                      category="billionaire")
    sent = fake.calls[0][1]
    assert "中段略" in sent
    assert len(sent) < 20000 + len(long_src)   # 没有整段透传
    # 头尾都在:开头标记与结尾标记同时可寻
    assert sent.find("开" * 50) < sent.find("尾" * 50)


# ---------------------------------------------------------------- 章号与章名
# 用户需求(2026-10-24):要有地方写第几章、章名用目标语言。

def test_generate_chapter_title_from_rewritten_content(monkeypatch):
    """章名按**改写稿**起(B/C 级改写后内容已与原文不同),剥围栏/引号,失败为空。"""
    def fake_run(agent, prompt, **kw):
        assert "The Contract" in prompt or "章节正文" in prompt
        return '```\n\"The Contract She Refused to Sign\"\n```'
    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)
    t = overseas.generate_chapter_title("She stared at The Contract. " * 10,
                                        target_lang="en-US")
    assert t == "The Contract She Refused to Sign"

    def boom(agent, prompt, **kw):
        raise RuntimeError("429")
    monkeypatch.setattr(overseas.runner, "run_agent", boom)
    assert overseas.generate_chapter_title("x", target_lang="en-US") == ""
    assert overseas.generate_chapter_title("", target_lang="en-US") == ""


def test_save_chapter_persists_title(tmp_db):
    pid = overseas.save_project(drama_id=900040, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x")
    overseas.save_chapter(project_id=pid, episode_id=None, chapter_no=1,
                          title="The Contract She Refused to Sign",
                          content="Chapter one body.")
    row = db.q1("SELECT title FROM overseas_chapter WHERE project_id=?", (pid,))
    assert row["title"] == "The Contract She Refused to Sign"


# ---------------------------------------------------------------- 整书生成
# 用户工作流(2026-10-25):书写完 → 一次定好书级设定 → 逐章自动生成,
# 而不是每章手动点一遍。

def _mk_book(drama_id: int, nums=(1, 2, 3)) -> dict:
    eps = {}
    for n in nums:
        db.ex("""INSERT INTO episodes(drama_id,episode_number,title,content,status,
                 resolution,created_at,updated_at) VALUES(?,?,?,?,'draft','720p',?,?)""",
              (drama_id, n, f"第{n}章", f"第{n}章正文:" + "内容" * 30, db.now(), db.now()))
        eps[n] = db.get_db().execute(
            "SELECT id FROM episodes ORDER BY id DESC LIMIT 1").fetchone()["id"]
    return eps


def _stub_llm(monkeypatch, calls=None):
    """打桩:抽词→无新词;改写→按原文编号回显;章名→Chapter N。"""
    import re as _re

    def fake_run(agent, prompt, **kw):
        if calls is not None:
            calls.append((agent, prompt))
        if agent == "overseas_analyzer":
            return json.dumps({"new_terms": {}}, ensure_ascii=False)
        if "章名" in prompt or "章节正文" in prompt and "起一个" in prompt:
            return "Auto Title"
        m = _re.search(r"第(\d+)章", prompt)
        return f"Rewritten chapter {m.group(1)} body." if m else "Body."

    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)


def test_batch_rewrite_generates_all_chapters_in_order(tmp_db, monkeypatch):
    """整书生成:按集号顺序出全部章,章号 1..N,每章关联自己的原集。"""
    eps = _mk_book(900050)
    _stub_llm(monkeypatch)
    out = overseas.batch_rewrite(drama_id=900050, platform="goodnovel",
                                 category="billionaire", level="B",
                                 target_lang="en-US",
                                 title="The Batch Book")
    assert out["failed_at"] == 0 and out["done"] == 3 and out["skipped"] == 0
    pid = overseas.find_project(900050, "goodnovel", "billionaire", "en-US")
    rows = overseas.list_chapters(pid)
    assert [r["chapter_no"] for r in rows] == [1, 2, 3]
    assert {r["episode_id"] for r in rows} == set(eps.values())
    assert db.q1("SELECT title_target FROM overseas_project WHERE id=?",
                 (pid,))["title_target"] == "The Batch Book"


def test_batch_rewrite_resumes_and_skips_done(tmp_db, monkeypatch):
    """断点续跑:已改写的集跳过,再点只补剩余(书名/术语不重置)。"""
    eps = _mk_book(900051, nums=(1, 2))
    _stub_llm(monkeypatch)
    overseas.batch_rewrite(drama_id=900051, platform="goodnovel",
                           category="billionaire", level="B",
                           title="Book Two")
    # 新增第 3 章原文,再跑整书 → 1/2 跳过,只出 3
    db.ex("""INSERT INTO episodes(drama_id,episode_number,title,content,status,
             resolution,created_at,updated_at) VALUES(900051,3,'第3章','第3章正文', 'draft','720p',?,?)""",
          (db.now(), db.now()))
    out = overseas.batch_rewrite(drama_id=900051, platform="goodnovel",
                                 category="billionaire", level="B",
                                 title="")          # 空书名不动已定书名
    assert out["skipped"] == 2 and out["done"] == 1
    pid = overseas.find_project(900051, "goodnovel", "billionaire", "en-US")
    assert db.q1("SELECT title_target FROM overseas_project WHERE id=?",
                 (pid,))["title_target"] == "Book Two"      # 书名没被空值顶掉
    assert len(overseas.list_chapters(pid)) == 3


def test_batch_rewrite_stops_on_failure_and_keeps_done(tmp_db, monkeypatch):
    """单章失败即停:已完成章保留,返回失败章号与原因(修好再点从断点续跑)。"""
    _mk_book(900052, nums=(1, 2, 3))
    state = {"n": 0}

    def fake_run(agent, prompt, **kw):
        state["n"] += 1
        if state["n"] > 4:               # 第 2 章改写调用时炸(1=抽词,2=改写,3=章名,4=第2章抽词→第2章改写=5)
            if "Rewritten" not in prompt and agent == "overseas_rewriter" and "翻译模式" not in prompt and "改写" not in prompt[:4]:
                pass
        import re as _re
        if agent == "overseas_analyzer":
            return json.dumps({"new_terms": {}}, ensure_ascii=False)
        m = _re.search(r"第(\d+)章", prompt)
        if m and m.group(1) == "2" and "章名" not in prompt:
            raise RuntimeError("429 quota")
        return f"Rewritten chapter {m.group(1)} body." if m else "Body."

    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)
    out = overseas.batch_rewrite(drama_id=900052, platform="goodnovel",
                                 category="billionaire", level="B")
    assert out["failed_at"] == 2 and "429" in out["error"]
    assert out["done"] == 1                       # 第 1 章已完成并保留
    pid = overseas.find_project(900052, "goodnovel", "billionaire", "en-US")
    assert len(overseas.list_chapters(pid)) == 1


def test_batch_rewrite_carries_stored_diag_issues(tmp_db, monkeypatch):
    """已存诊断的「发现」是书级资产:整书生成的每章改写都要带着修(与单章同口径)。"""
    _mk_book(900060)
    pid = overseas.save_project(
        drama_id=900060, episode_id=None, platform="goodnovel",
        category="billionaire", level="B", source_text="",
        diag={"level": "B", "issues": [
            {"type": "自指观察", "quote": "她的脸红了", "fix": "改成手指发白"}]})
    prompts = []

    def fake_run(agent, prompt, **kw):
        prompts.append(prompt)
        if agent == "overseas_analyzer":
            return json.dumps({"new_terms": {}}, ensure_ascii=False)
        import re as _re
        m = _re.search(r"第(\d+)章", prompt)
        return f"Rewritten {m.group(1)}." if m else "Body."

    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)
    overseas.batch_rewrite(drama_id=900060, platform="goodnovel",
                           category="billionaire", level="B")
    # 改写类调用(非抽词、非章名)的 prompt 必须含诊断发现
    rewrite_prompts = [p for p in prompts if "待改写" in p or "诊断发现" in p]
    assert rewrite_prompts, "没捕获到改写 prompt"
    assert all("她的脸红了" in p and "手指发白" in p for p in rewrite_prompts)


# ---------------------------------------------------------------- 空正文防线
# 实测(2026-10-25 用户截图):整书生成第 8 章存了 0 词空章,且断点续跑会把它
# 当「已完成」跳过,永远补不上。三道防线:save 拒空 / batch 空即停 / 空章自愈。

def test_save_chapter_refuses_empty_content(tmp_db):
    pid = overseas.save_project(drama_id=900070, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x")
    with pytest.raises(RuntimeError, match="空正文"):
        overseas.save_chapter(project_id=pid, episode_id=None, chapter_no=1,
                              content="   ")
    assert overseas.list_chapters(pid) == []


def test_batch_heals_empty_chapters_and_redoes_them(tmp_db, monkeypatch):
    """历史空章:批量先删(自愈),该章按未完成重出;空正文按失败停在断点。"""
    eps = _mk_book(900071, nums=(1, 2))
    pid = overseas.save_project(drama_id=900071, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x")
    # 第 1 章正常,第 2 章是历史空章
    overseas.save_chapter(project_id=pid, episode_id=eps[1], chapter_no=1,
                          content="Good chapter one.")
    db.ex("INSERT INTO overseas_chapter(project_id,episode_id,chapter_no,title,"
          " content,words,qc_json,status,created_at,updated_at)"
          " VALUES(?,?,?,?,?,0,'[]','done',?,?)",
          (pid, eps[2], 2, "", "  ", db.now(), db.now()))
    calls = {"n": 0}

    def fake_run(agent, prompt, **kw):
        calls["n"] += 1
        if agent == "overseas_analyzer":
            return json.dumps({"new_terms": {}}, ensure_ascii=False)
        import re as _re
        m = _re.search(r"第(\d+)章", prompt)
        return f"Rewritten {m.group(1)}." if m else "Body."

    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)
    out = overseas.batch_rewrite(drama_id=900071, platform="goodnovel",
                                 category="billionaire", level="B")
    assert out["failed_at"] == 0
    assert out["skipped"] == 1 and out["done"] == 1     # 第1跳过,空章重出
    rows = overseas.list_chapters(pid)
    assert [r["chapter_no"] for r in rows] == [1, 2]
    assert all((r["content"] or "").strip() for r in rows)   # 不再有 0 词行


def test_batch_stops_when_rewrite_returns_empty(tmp_db, monkeypatch):
    """改写返回空串:停在断点保住已完成,绝不落空章。"""
    _mk_book(900072, nums=(1, 2))

    def fake_run(agent, prompt, **kw):
        if agent == "overseas_analyzer":
            return json.dumps({"new_terms": {}}, ensure_ascii=False)
        import re as _re
        m = _re.search(r"第(\d+)章", prompt)
        if m and m.group(1) == "2":
            return "   "                          # 第 2 章空正文
        return f"Rewritten {m.group(1)}." if m else "Body."

    monkeypatch.setattr(overseas.runner, "run_agent", fake_run)
    out = overseas.batch_rewrite(drama_id=900072, platform="goodnovel",
                                 category="billionaire", level="B")
    assert out["failed_at"] == 2 and "空正文" in out["error"]
    assert out["done"] == 1
    pid = overseas.find_project(900072, "goodnovel", "billionaire", "en-US")
    assert len(overseas.list_chapters(pid)) == 1


def test_cleanup_heals_empty_and_duplicate_rows(tmp_db):
    """软件自愈(用户要求:再出现要靠软件补,不是人工操作):
    空行删掉;同集「旧空行 + 新好行」只留最新好行;整集全空则清光待重出。"""
    pid = overseas.save_project(drama_id=900080, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x")
    ts = db.now()
    # 集 101:好行;集 102:旧空行 + 新好行(历史 bug 形态);集 103:只有空行
    db.ex("INSERT INTO overseas_chapter(project_id,episode_id,chapter_no,title,"
          " content,words,qc_json,status,created_at,updated_at)"
          " VALUES(?,101,1,'t','Good one.',9,'[]','done',?,?)", (pid, ts, ts))
    db.ex("INSERT INTO overseas_chapter(project_id,episode_id,chapter_no,title,"
          " content,words,qc_json,status,created_at,updated_at)"
          " VALUES(?,102,2,'','',0,'[]','done',?,?)", (pid, ts, ts))
    db.ex("INSERT INTO overseas_chapter(project_id,episode_id,chapter_no,title,"
          " content,words,qc_json,status,created_at,updated_at)"
          " VALUES(?,102,2,'t','Good two.',8,'[]','done',?,?)", (pid, ts, ts))
    db.ex("INSERT INTO overseas_chapter(project_id,episode_id,chapter_no,title,"
          " content,words,qc_json,status,created_at,updated_at)"
          " VALUES(?,103,3,'','  ',0,'[]','done',?,?)", (pid, ts, ts))
    overseas.cleanup_empty_chapters(pid)
    rows = overseas.list_chapters(pid)
    assert len(rows) == 2                       # 101 好行 + 102 最新好行;103 清光
    assert all((r["content"] or "").strip() for r in rows)
    assert {r["episode_id"] for r in rows} == {101, 102}


# ---------------------------------------------------------------- 删除 / 重生成 / 链洞
# 用户规则(2026-10-25):删掉中间章后,后续章不能再生成,除非先补上。

def _mk_chain(drama_id: int, n: int = 3) -> tuple:
    """建 n 集并直接落 n 章改写稿,返回 (pid, {episode_number: chapter_row_id})。"""
    eps = _mk_book(drama_id, nums=list(range(1, n + 1)))
    pid = overseas.save_project(drama_id=drama_id, episode_id=None,
                                platform="goodnovel", category="billionaire",
                                level="B", source_text="x")
    ids = {}
    for k in range(1, n + 1):
        cid = overseas.save_chapter(
            project_id=pid, episode_id=eps[k], chapter_no=k,
            title=f"T{k}", content=f"Chapter {k} body. " * 20)
        ids[k] = cid
    return pid, ids


def test_delete_middle_blocks_later_regen_until_refilled(tmp_db, monkeypatch):
    pid, ids = _mk_chain(900090)                      # 章 1,2,3
    assert overseas.delete_chapter(ids[2])            # 删第 2 章 → 链洞在 2
    assert overseas.missing_chapter_before(pid, 3) == 2
    # 重生成第 3 章 → 拒绝,指向第 2 章这个洞
    with pytest.raises(RuntimeError, match="第 2 章缺失"):
        overseas.regenerate_chapter(
            project_id=pid, episode_id=1, chapter_no=3,
            platform="goodnovel", category="billionaire", level="B")
    # 新生成的章号 = 最小洞(2):生成动作只许先补洞
    assert overseas.next_chapter_no(pid, None) == 2
    # 补上第 2 章(重生成洞位)后,链连续,后续解锁
    _stub_llm(monkeypatch)
    ep2 = db.q1("SELECT id FROM episodes WHERE drama_id=? AND episode_number=2",
                (900090,))["id"]
    overseas.regenerate_chapter(
        project_id=pid, episode_id=ep2, chapter_no=2,
        platform="goodnovel", category="billionaire", level="B")
    assert overseas.missing_chapter_before(pid, 3) == 0
    rows = {r["chapter_no"] for r in overseas.list_chapters(pid)}
    assert rows == {1, 2, 3}


def test_regenerate_keeps_mid_chain_number_and_replaces(tmp_db, monkeypatch):
    """重生成中链章:沿用原章号(不排到队尾),旧行替换不并存。"""
    pid, ids = _mk_chain(900091)
    ep2 = db.q1("SELECT id FROM episodes WHERE drama_id=? AND episode_number=2",
                (900091,))["id"]
    _stub_llm(monkeypatch)
    out = overseas.regenerate_chapter(
        project_id=pid, episode_id=ep2, chapter_no=2,
        platform="goodnovel", category="billionaire", level="B")
    assert out["chapter_no"] == 2
    rows = overseas.list_chapters(pid)
    assert [r["chapter_no"] for r in rows] == [1, 2, 3]      # 没有第 4 章(未排队尾)
    assert len([r for r in rows if r["episode_id"] == ep2]) == 1  # 旧行已替换


def test_regenerate_no_source_episode(tmp_db):
    pid, ids = _mk_chain(900092)
    # 没挂原集的章(手动粘贴形态)→ 报可读错误
    cid = overseas.save_chapter(project_id=pid, episode_id=None, chapter_no=4,
                                title="T4", content="Pasted chapter. " * 20)
    with pytest.raises(RuntimeError, match="正文"):
        overseas.regenerate_chapter(
            project_id=pid, episode_id=0, chapter_no=4,
            platform="goodnovel", category="billionaire", level="B")
