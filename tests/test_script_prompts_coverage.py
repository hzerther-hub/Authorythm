# -*- coding: utf-8 -*-
"""可拍性硬规则的 15 语言覆盖度护栏。

背景:2026-10-20 某次短剧改写产出「11 场全在同一间出租屋、每场只有画外音」的剧本,
根因是技能文件写着「心理描写可转化为角色表情/动作**或画外音**」。修法分两层:
    1) 提示词层:skill/prompt 里禁画外音、要求心理外化、要求对手戏、要求换场景;
    2) 程序层:`app.pipeline.script_quality` 体检 + 返工 + 不合格不落库(见 test_script_quality.py)。

本文件守着第 1 层:**15 种语言一个都不能漏**。漏一种 = 那种语言下照样会产出拍不出来的剧本。

判定不依赖具体措辞(各语言翻译不同,按词表匹配必误报 —— 踩过"voix off"既可能出现在
"允许"句也可能出现在"禁止"句):
- 文件数量对齐(少一个语言文件 = 漏);
- 每个文件的硬规则块条目数 ≥ 基准(少一条 = 漏);
- ``load_prompt`` 的结果里必须逐条出现该语言 workspace 文件的硬规则条目
  (load_prompt 会在末尾追加"输出语言要求"段,所以不能靠"最后一个 ## 块"定位)。
"""
from __future__ import annotations

import re

import pytest

from app.agents.prompts import load_prompt
from app.core.config import PROMPTS_DIR, WORKSPACE_DIR
from app.core.i18n import LANG_NAMES

# 提示词语言:zh 用无后缀的 <agent>.md;comic_outline_writer 另有 zh-Hant
PROMPT_LANGS = ["en", "ja", "ko", "ar", "hi", "id", "th", "tr", "vi", "fr", "de", "es", "pt", "it"]
BULLET_RE = re.compile(r"^\s*[-*]\s+\S", re.MULTILINE)
HEADING_RE = re.compile(r"(?m)^##\s")


def _read(path) -> str:
    return path.read_text(encoding="utf-8")


def _hard_block(text: str) -> str:
    """取文件里最后一个 '## 标题' 之后的内容 —— 追加在末尾的硬规则块。"""
    heads = list(HEADING_RE.finditer(text))
    return text[heads[-1].start():] if heads else ""


def _bullets(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if BULLET_RE.match(ln)]


def _prompt_files(agent: str) -> list:
    """<agent>.md(中文基准) + <agent>.<lang>.md(其余语言)。"""
    files = [PROMPTS_DIR / (agent + ".md")]
    files += sorted(PROMPTS_DIR.glob(agent + ".*.md"))
    return [f for f in files if f.exists()]


# ---------------------------------------------------------------- 技能文件

def _skill_files() -> list:
    return sorted((WORKSPACE_DIR / "skills" / "script-rewriter").glob("SKILL*.md"))


def _lang_of(path, prefix):
    """从文件名取语言:``<prefix>.md`` → zh,<prefix>.<lang>.md`` → <lang>。"""
    return path.name[len(prefix):-3].lstrip(".") or "zh"


def test_skill_files_cover_all_languages():
    """SKILL 必须覆盖 script_rewriter 提示词覆盖的每一种语言。

    不写死"15 个":项目正在补第 16 种语言(zh-Hant),写死数量会把"合法新增语言"
    误报成故障。改成**跨文件一致性** —— 少了某个语言的文件会报,加了新语言不会误报。
    """
    skill_langs = {_lang_of(f, "SKILL") for f in _skill_files()}
    prompt_langs = {_lang_of(f, "script_rewriter") for f in _prompt_files("script_rewriter")}
    assert skill_langs == prompt_langs, (
        f"SKILL 与 script_rewriter 提示词的语言集合不一致:"
        f"SKILL 缺 {sorted(prompt_langs - skill_langs)} / 多 {sorted(skill_langs - prompt_langs)}")
    assert "zh" in skill_langs, "SKILL 缺少中文基准文件(SKILL.md)"


def test_skill_files_no_longer_allow_voice_over():
    """原来那句「心理描写…或画外音」必须已被替换(中文基准文件里再也不能出现)。"""
    for f in _skill_files():
        assert "或画外音" not in _read(f), f"{f.name} 仍写着「或画外音」"


def test_skill_files_keep_three_filmability_rules():
    """每个语言的技能文件都要有 ≥3 条硬规则条目(心理外化/对手戏/换场景)。"""
    for f in _skill_files():
        bullets = _bullets(_read(f))
        assert len(bullets) >= 3, f"{f.name} 的规则条目过少({len(bullets)})"


# ---------------------------------------------------------------- 提示词文件

def test_prompt_languages_are_consistent_across_agents():
    """两个 agent 的提示词语言集合要一致(zh-Hant 允许只出现在其中一个)。

    少一个语言 = 那个语言下照样会产出拍不出来的剧本,必须报出来。
    """
    script_langs = {_lang_of(f, "script_rewriter") for f in _prompt_files("script_rewriter")}
    comic_langs = {_lang_of(f, "comic_outline_writer") for f in _prompt_files("comic_outline_writer")}
    assert "zh" in script_langs and "zh" in comic_langs, "缺中文基准文件"
    assert script_langs - {"zh-Hant"} == comic_langs - {"zh-Hant"}, (
        f"两个 agent 的语言集合不一致:"
        f"script_rewriter 缺 {sorted(comic_langs - script_langs - {'zh-Hant'})} / "
        f"comic_outline_writer 缺 {sorted(script_langs - comic_langs - {'zh-Hant'})}")


def test_prompt_languages_are_supported():
    """提示词文件的语言必须在项目支持的界面语言集合内(防写错后缀)。"""
    supported = set(LANG_NAMES)
    for agent in ("script_rewriter", "comic_outline_writer"):
        for f in _prompt_files(agent):
            lang = _lang_of(f, agent)
            assert lang in supported, f"{f.name} 的语言 {lang} 不在支持列表内"


@pytest.mark.parametrize("agent,min_bullets", [("script_rewriter", 5), ("comic_outline_writer", 4)])
def test_every_language_prompt_has_full_hard_rule_block(agent, min_bullets):
    """每个语言的提示词末尾都要有完整的硬规则块(条目数不少于基准)。"""
    for f in _prompt_files(agent):
        bullets = _bullets(_hard_block(_read(f)))
        assert len(bullets) >= min_bullets, \
            f"{f.name} 硬规则条目不足({len(bullets)} < {min_bullets})"


@pytest.mark.parametrize("agent", ["script_rewriter", "comic_outline_writer"])
def test_load_prompt_reads_workspace_file_not_builtin_default(agent):
    """load_prompt 必须读 workspace 文件(内置 DEFAULT_PROMPTS 会被它覆盖)。"""
    for f in _prompt_files(agent):
        lang = f.name[len(agent) + 1:-3] or "zh"
        bullets = _bullets(_hard_block(_read(f)))
        assert bullets, f"{f.name} 没有硬规则条目"
        got = load_prompt(agent, lang)
        assert got, f"load_prompt({agent},{lang}) 返回空"
        missing = [b for b in bullets if b not in got]
        assert not missing, f"load_prompt({agent},{lang}) 少了硬规则条目:{missing[:2]}"
