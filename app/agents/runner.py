"""Agent 执行器:组装 system + user,调用文本模型,解析 JSON 输出。"""
from __future__ import annotations

import json
import re
import time
from typing import cast

from ..ai import registry, text_client
from ..ai.text_client import AI_LLM_TIMEOUT_S, AIError
from ..core import db, zh_convert
from ..core.logging_setup import get_logger
from . import prompts

log = get_logger(__name__)


def _balanced_json_objects(raw: str) -> list[str]:
    """抠出原始输出里所有**顶层平衡**的 JSON 片段(字符串感知的括号配对)。

    为什么不能只取「首个 { 到最后一个 }」:模型输出 `{"a":1}\\n说明\\n{"b":2}` 时,
    首尾一夹把中间说明文字也框进去,JSON.parse 必炸「Unexpected non-whitespace
    character after JSON」。逐个平衡配对才能把真载荷捞出来。

    配对时必须感知字符串状态:JSON 字符串里可能有 } 或 ](如正文里写 "…}…"),
    不感知就会在字符串内部误判深度,提前闭合。
    """
    out: list[str] = []
    stack: list[str] = []
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(raw):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch in "{[":
            if not stack:
                start = i
            stack.append("}" if ch == "{" else "]")
            continue
        if ch in "}]":
            if not stack:
                continue
            stack.pop()
            if not stack and start >= 0:
                out.append(raw[start:i + 1])
                start = -1
    return out


def _close_truncated_json(frag: str) -> str:
    """截断挽救:输出被 max_tokens/连接掐断时,补齐未闭合的字符串引号与括号栈。

    上游 novel.ts 的 tryCloseTruncatedJson 同款。长输出(总纲 1500-3000 字、
    分卷战略)被截断在正文中间是常态 —— 补齐后能捞回大半内容,而不是整段作废。
    """
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in frag:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    fixed = frag
    if esc:
        fixed = fixed[:-1]        # 尾部悬空反斜杠先去掉,否则补引号后仍是非法转义
    if in_str:
        fixed += '"'
    while stack:
        fixed += stack.pop()
    return fixed


def _repair_json_text(src: str) -> str:
    """修 JSON 字符串字面量内部的**裸换行/回车/制表符**,顺带去掉结构尾部多余逗号。

    模型写中文长句时经常在 JSON 字符串里直接换行,JSON.parse 直接报
    "Unterminated string in JSON" —— 补 \\n 就好,补引号救不了。

    **刻意不做的事**:把中文弯引号 “ ” 批量换成 ASCII 双引号。正文里 “……” 是
    正常内容(她说“我不同意”),一换就会把字符串提前闭合,反而制造新的解析错误。
    """
    out: list[str] = []
    in_str = False
    esc = False
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if in_str:
            if esc:
                out.append(ch)
                esc = False
                i += 1
                continue
            if ch == "\\":
                out.append(ch)
                esc = True
                i += 1
                continue
            if ch == '"':
                in_str = False
                out.append(ch)
                i += 1
                continue
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            # 字符串外的尾逗号:看向后第一个非空白字符,是 } 或 ] 就把这个逗号丢掉
            j = i + 1
            while j < n and src[j].isspace():
                j += 1
            if j < n and src[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_fields_loose(raw: str, fields: list[str]) -> dict | None:
    """逐字段正则兜底:JSON 彻底解析不出来时,按 "key": "value" 逐个抠字段。

    只给「宁可给残缺结果也别让用户白等」的场景用(字段清单由调用方给)。
    四种写法依次尝试(越往后越宽松):
      "key": "value" / "key": value / key: "value" / key: value
    """
    out: dict[str, str] = {}
    found = 0
    for f in fields:
        patterns = [
            (re.compile(r'"' + re.escape(f) + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', re.S), True),
            (re.compile(r'"' + re.escape(f) + r'"\s*:\s*([^\n\r,}]{1,600})'), False),
            (re.compile(r'(?:^|[\n\r{,])[ \t]*' + re.escape(f)
                        + r'[ \t]*:[ \t]*"([^"\n\r]*)"', re.I), True),
            (re.compile(r'(?:^|[\n\r{,])[ \t]*' + re.escape(f)
                        + r'[ \t]*:[ \t]*([^\n\r,}]{1,600})', re.I), False),
        ]
        val: str | None = None
        quoted = False
        for rx, is_quoted in patterns:
            m = rx.search(raw)
            if not m:
                continue
            val = m.group(1)
            quoted = is_quoted
            break
        if val is None:
            continue
        val = val.strip()
        if not quoted:
            val = val.strip("\"'").strip()
        else:
            val = val.replace("\\n", "\n").replace("\\t", "\t")
            val = val.replace('\\"', '"').replace("\\\\", "\\")
        if not val:
            continue
        out[f] = val
        found += 1
    return out if found else None


# 思考行启发式:剥掉 <think> 后正文前粘着的推理行(中英)
_THINK_LINE = re.compile(
    r"^\s*(?:[-*•]\s*|\d+[.)]\s*)?"
    r"(wait|actually|let me|let'?s|hmm|okay|so i|i need|i should|i will|i'?ll|"
    r"the user|user wants|looking at|storyboard description|duration:|atmosphere:|"
    r"character:|scene:|shot \d|\d+s?, so|but the user|let me draft|"
    r"[一-鿿]{0,4}(让我|我想|首先|我需要|我应该|推理))",
    re.I)


def strip_think(content: str) -> str:
    """剥掉模型混进正文通道的思维链(<think>…</think>),只留可用正文。

    推理型模型(glm / minimax-M3)先吐一整段推理再给正文;extract_json 内部
    会剥,但**拿纯文本**的调用方(auto_generate 首集剧本、流式草稿)此前
    直接落库 —— 2026-11-02 实测:MTV 首集剧本 60449 字里 57946 字是
    <think>,界面"看不到剧本"。
    处理顺序:成对块 → 未闭合尾巴(正文在思考后,行级启发式剥思考行)→
    工具调用残留 → 英文元思考前缀。与 ui.episode_page._strip_model_think
    同源(pipeline 层不能反向 import UI,故下沉到 runner 供两边共用)。
    """
    text = content or ""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "<think>" in text:
        tail = text.rsplit("<think>", 1)[-1]
        if "</think>" not in tail:
            lines = tail.splitlines()
            while lines and (not lines[0].strip() or _THINK_LINE.match(lines[0])):
                lines.pop(0)
            text = "\n".join(lines)
    text = re.sub(r"<tool_call>.*?(?:</tool_call>|$)", "", text, flags=re.S)
    text = re.sub(
        r"(?s)^\s*(Wait|Actually|Let me|Hmm|Okay|So I)[^.]*\."
        r"(\s+|(Wait|Actually|Let me|Hmm|Okay|So I)[^.]*\.)+",
        "", text)
    return text.strip()


def extract_json(text: str, fields: list[str] | None = None, *,                salvage: bool = False) -> dict | list | None:
    """从模型输出中稳健提取 JSON(容忍 ```json 围栏、<think> 推理块与前后杂文)。

    **必须先剥 <think> 再找 JSON**:推理型模型(glm-5.3 / MiniMax-M3 等)会先吐一整段
    带花括号的思维链,「首个 { 到最后一个 }」会把推理连同正文一起框进来,必然解析失败。
    实测 comic_board 正是栽在这里。

    分层降级(上游 novel.ts 的 parseJsonLoose 同款移植):
      L0 现有候选(围栏 / 整体 / 首尾截取 / 去尾逗号)
      L1 平衡对象逐个解析,取**最大的**可解析载荷
      L2 L1 的每个候选先修「字符串内裸换行」再解析
      L3 截断挽救:补齐未闭合的引号与括号栈 —— **仅 salvage=True 时启用**
      L4 逐字段正则兜底(需传 fields)

    **L0 全败才走 L1-L4**:现有候选的顺序与优先级原样保留,凡是今天能解析出来的
    输出,解析结果与改前逐字节一致 —— 加固只影响「今天返回 None」的那批。

    ## 为什么 L3(截断挽救)要 opt-in
    预算阶梯(_call_budgeted)靠「解析失败 + 判定被截断」来**升预算重试**:
    截断的输出必须解析失败,阶梯才会往上爬。L3 若默认开启,被掐断的 JSON 会被
    抢救成「半个对象」并被当成成功,阶梯就不爬了 —— max_tokens 永远停在起始档
    (实测 test_agent_budget 的阶梯断言就是这么红的)。
    所以 L3 默认关;只有「没有阶梯、只能靠这一次输出」的调用点(整书导入仿写的
    长总纲/分卷)才显式 salvage=True,拿回被截断的大半正文。
    """
    if not text:
        return None
    # 1) 先剥成对 <think>...</think>
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    # 2) 未闭合的尾巴:正文在思考之后,取最后一个 <think> 之后的全部内容
    if "<think>" in text:
        text = text.rsplit("<think>", 1)[-1]
    text = text.strip()
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidates = []
    if fence:
        candidates.append(fence.group(1).strip())
    # 直接整体
    candidates.append(text.strip())
    # 首个 { 到最后一个 }
    s, e = text.find("{"), text.rfind("}")
    if s >= 0 and e > s:
        candidates.append(text[s:e + 1])
    s2, e2 = text.find("["), text.rfind("]")
    if s2 >= 0 and e2 > s2:
        candidates.append(text[s2:e2 + 1])
    # 尾逗号修复候选:LLM 常写 {"a": 1,} / [1,2,] —— json.loads 必炸,去尾逗号就能救
    for cand in list(candidates):
        fixed = re.sub(r",\s*([}\]])", r"\1", cand)
        if fixed != cand:
            candidates.append(fixed)
    for cand in candidates:
        try:
            return json.loads(cand)
        except Exception:  # noqa: BLE001
            continue

    # ── L1/L2:平衡对象提取(原文多段 JSON / 夹带说明文字时,L0 会整体失败) ──
    objs = _balanced_json_objects(text)
    for repair in (False, True):
        best = None
        best_len = -1
        for cand in objs:
            try:
                parsed = json.loads(_repair_json_text(cand) if repair else cand)
            except Exception:  # noqa: BLE001
                continue
            # 真载荷通常是最大的那个:前面的小对象常是模型的自我说明
            if len(cand) > best_len:
                best = parsed
                best_len = len(cand)
        if best is not None:
            return best

    # ── L3:截断挽救(输出被 max_tokens 掐断 —— 长总纲/分卷的常态) ──
    if salvage:
        starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
        if starts:
            frag = text[min(starts):]
            try:
                return json.loads(_close_truncated_json(_repair_json_text(frag)))
            except Exception:  # noqa: BLE001
                pass

    # ── L4:逐字段正则兜底 ──
    if fields:
        loose = _extract_fields_loose(text, fields)
        if loose:
            log.warning("extract_json.field_fallback fields=%s raw=%d字符",
                        ",".join(fields), len(text))
            return loose
    return None


def run_agent(agent_type: str, user_prompt: str, *, lang: str | None = None,
              json_output: bool = False, temperature: float = 0.7,
              config_id: int | None = None,
              image_urls: list[str] | None = None,
              system: str | None = None,
              max_tokens: int | None = None,
              timeout: int | None = None,
              with_meta: bool = False) -> str | tuple[str, dict]:
    """system=None 时用 workspace/prompts/<type>.<lang>.md。

    传入 system 可整体覆盖:workspace 里的提示词是给**带工具的 Mastra Agent** 写的
    (例如 novel_planner.md 里写着「只输出工具调用,不要输出规划文本」),
    本仓 runner 是单次调用、没有工具,不覆盖就会拿到一串 <tool_call> 文本。

    with_meta=True 时返回 (content, meta),meta 含 finish_reason / usage ——
    预算自适应要靠 finish_reason=="length" 判断截断,不能只靠括号配平去猜。
    """
    if lang is None:
        lang = db.get_setting("content_language", "zh")
    system = system if system is not None else prompts.load_prompt(agent_type, lang or "")
    kwargs: dict = {}
    if timeout is not None:
        kwargs["timeout"] = timeout
    out = text_client.chat(
        user_prompt, system=system, temperature=temperature,
        json_mode=json_output, config_id=config_id, image_urls=image_urls,
        max_tokens=max_tokens, with_meta=with_meta, **kwargs)
    # 内容语言 = 繁体中文时,在出口统一做简→繁转换。
    # 选这里而不是各调用点:34 个调用点逐个改,漏一个就是「有的稿繁、有的稿简」。
    # 提示词里没有可靠的繁体指令(workspace/prompts 只有 comic_outline_writer
    # 有 zh-Hant 文件),让模型自己写繁体既慢又不稳 —— 转换是确定性的、零成本的。
    # with_meta 时 out 是 (content, meta),只转 content。
    if isinstance(out, tuple):
        return zh_convert.apply_output_language(out[0], lang), out[1]
    return zh_convert.apply_output_language(out, lang)


JSON_HINT = "请只输出 JSON,不要任何解释文字、不要 Markdown 代码块标记。"

# workspace/prompts/*.md 是给带工具的 Mastra Agent 写的(「调用 read_xxx / save_xxx」),
# 本仓 runner 没有工具。不加这句时,模型会老老实实回一个
# {"name": "read_script_for_extraction", "arguments": {...}} —— 它是合法 JSON,
# extract_json 会解析成功,但调用方拿到的是工具调用而不是结果,资产提取 0 条。
_NO_TOOL_HINT = (
    "\n\n【本次运行环境没有工具】不要调用任何工具,也不要输出 "
    '{"name": "...", "arguments": {...}} 形式的工具调用;直接输出最终 JSON。'
)


def _looks_like_tool_call(data) -> bool:
    """识别 {"name": "...", "arguments": {...}} 这种工具调用 JSON。"""
    return (isinstance(data, dict) and set(data) == {"name", "arguments"}
            and isinstance(data.get("name"), str))


# ---------------------------------------------------------------- 输出预算自适应
#
# 为什么要有这一层:推理型模型(minimax-M3 / deepseek-v4-pro / glm 等)会先吐一整段
# <think>,默认 8192 的输出预算会被这段思维链吃光 —— finish_reason=length、
# 正文 0 字符,extract_json 必然返回 None。实测后果是分镜拆分从上线起一次都没成功过
# (storyboards 表 0 行、storyboard_split 任务恒 failed)。
#
# **刻意不针对任何具体模型**:过去 extractor 硬写 32768、novel 硬写 32768、
# 分镜干脆没写,换一家供应商就得重新试一遍。这里改成「看输出是否被截断」来决定
# 升不升预算 —— 非推理模型不会触发(输出本来就不是截断的),推理模型无论需要多少
# 都能自己爬到够用为止,不需要为它单独调参。
#
# 三个信号合起来判定「这次是被预算截断了」:
#   1. finish_reason == "length" —— 供应商自己说的,唯一可靠信号
#   2. 空响应                  —— 预算全烧在 <think> 上,正文一个字没写
#   3. <think> 未闭合 / 括号不配平 —— 供应商不给 finish_reason 时的退化判断
# **只看括号配平会漏**(实测 minimax-M3 分镜 8192 档):切在 JSON 字符串中间时
# `{` 与 `}` 数量仍然相等,于是被判成「不是截断」,预算永远不升。
# 只有命中这些信号才升预算;否则(JSON 写坏 / 模型回了工具调用 / 输出散文)升预算
# 纯属浪费 token,那种情况走既有的禁工具重试。
BUDGET_START = 8192        # 阶梯起点(爬升机制:截断才升档,避免小任务烧大预算)
BUDGET_CEILING = 128000    # 自适应天花板(用户定版「最大的 max_token 128000」):
                           # 到顶还截断就是提示词本身太长,交给人看
BUDGET_FACTOR = 2


def _configured_budget(config_id: int | None, explicit: int | None) -> int:
    """起始预算 = 调用方显式值 > 服务配置里手填的值 > BUDGET_START。

    与 `novel._configured_max_tokens`、`ai/text_client._build_body` 同一优先级,
    三处口径必须一致,否则会出现「配置里填的大预算被程序兜底盖掉」。

    **走 `registry.default_config` 而不是按 id 直查**:调用点绝大多数传
    `config_id=None`(让 text_client 自己挑默认配置),此时按 id 直查是
    `WHERE id=NULL`,永远查不到行 → 一律退到 8192。而 text_client._build_body
    在同一种情况下会用默认配置里手填的值(本机是 32768)。两处口径一分裂,
    第一次请求就白发一个短预算,多烧一次往返还得靠阶梯爬回来。
    """
    if explicit:
        return int(explicit)
    try:
        cfg = registry.default_config("text", config_id) or {}
        v = int(cfg.get("max_tokens") or 0)
        if v:
            return v
    except Exception:  # noqa: BLE001 —— 读不到就按兜底走,不能因此中断业务
        pass
    # 无配置时的兜底 = 32768,与 text_client._default_max_tokens 同一口径
    # (用户要求「没有配置则 32768」;曾退 8192,两处口径分裂)。
    return int(registry.TEXT_DEFAULT_MAX_TOKENS)


def _looks_truncated(raw: str | None, finish_reason: str | None = None) -> bool:
    """输出是否像是被输出预算截断(见上方注释的信号)。"""
    # 信号 0:供应商明确说 length —— 优先信它,不要再靠文本猜
    if finish_reason == "length":
        return True
    if not raw or not raw.strip():
        return True  # 信号 1:空响应
    t = raw.strip()
    if "<think>" in t and "</think>" not in t:
        return True  # 信号 2:思考块没闭合
    # 信号 3:括号不配平(正文写到一半被切断)
    return t.count("{") > t.count("}") or t.count("[") > t.count("]")


def _timeout_for(budget: int) -> int:
    """预算越大,供应商吐字时间越长:按 60 tokens/s 估,再加 120s 余量。

    实测 minimax-M3 出 50,787 completion tokens 用了 401s(≈127 tok/s),
    固定 300s 超时会让 65536 档必然 Timeout —— 而 Timeout 不是 AIError,
    会直接冒到任务里,看起来和「模型不会写 JSON」完全无关。
    """
    return max(AI_LLM_TIMEOUT_S, budget // 60 + 120)


def _budget_rejected(err: AIError) -> bool:
    """供应商是不是「单纯不认这个 max_tokens」,而不是配置/鉴权坏了。

    只有前者才值得退回低档重试;401/404 之类退回低档也没意义,白白拖时间。
    """
    msg = str(err).lower()
    if any(k in msg for k in ("401", "403", "404", "unauthorized", "invalid api key")):
        return False
    return any(k in msg for k in ("max_tokens", "max tokens", "too large", "exceeds",
                                  "invalid_parameter", "context length"))


def _budget_ladder(start: int, ceiling: int) -> list[int]:
    """start, start*2, start*4 ... 直到 ceiling。已到顶就只给一档。"""
    out, b = [start], start
    while b < ceiling:
        b = min(b * BUDGET_FACTOR, ceiling)
        out.append(b)
    return out


def _call_budgeted(agent_type: str, prompt: str, *, lang, config_id, image_urls,
                   system, start_budget: int, parse, accept, temperature: float = 0.4):
    """按预算阶梯调用模型,直到 parse() 拿到 accept() 认可的结果。

    阶梯中途遇到 AIError(供应商拒绝该预算,通常 400)就把天花板压到这一档 ——
    **天花板由供应商自己告诉我们**,而不是代码里写死某个模型的上限。
    若调用方传的起始预算就被拒,退回到 BUDGET_START 重新爬(而不是直接失败:
    调用方按「这个 Agent 输出大」填的高预算,供应商不认不代表配置坏了)。
    返回 (data, last_raw):data 为 None 表示全阶梯都没拿到可用结果。
    """
    ladder = _budget_ladder(start_budget, BUDGET_CEILING)
    last_raw = ""
    i = 0
    while i < len(ladder):
        budget = ladder[i]
        t0 = time.perf_counter()
        # 先记一条「已发出」:分解一集分镜要 6-8 分钟,只有事后日志的话,
        # 用户看到任务卡在 processing 时完全无法判断是在正常等还是已经挂死
        log.info("agent.budget.call agent=%s budget=%d attempt=%d/%d timeout=%ds",
                 agent_type, budget, i + 1, len(ladder), _timeout_for(budget))
        try:
            raw, meta = cast(tuple, run_agent(agent_type, prompt, lang=lang, json_output=True,
                                  temperature=temperature, config_id=config_id,
                                  image_urls=image_urls, system=system,
                                  max_tokens=budget, timeout=_timeout_for(budget),
                                  with_meta=True))
        except AIError as e:
            log.warning("agent.budget.rejected agent=%s budget=%d err=%s",
                        agent_type, budget, str(e)[:200])
            if i == 0 and _budget_rejected(e) and start_budget > BUDGET_START:
                ladder = _budget_ladder(BUDGET_START, BUDGET_CEILING)
                i = 0
                continue
            # 起始档就炸 = 供应商侧硬错误(配置错/鉴权失败),照常抛出。
            if i == 0:
                raise
            # 更高档被拒 = 到顶了,用上一档再试一次就收手。
            ladder = ladder[:i]
            break
        last_raw = raw or ""
        truncated = _looks_truncated(raw, meta.get("finish_reason"))
        usage = meta.get("usage") or {}
        log.info("agent.budget.attempt agent=%s budget=%d finish=%s out_tokens=%s "
                 "chars=%d truncated=%s elapsed=%.1fs",
                 agent_type, budget, meta.get("finish_reason"),
                 usage.get("completion_tokens"), len(last_raw), truncated,
                 time.perf_counter() - t0)
        data = parse(raw)
        if data is not None and accept(data):
            return data, last_raw
        # 不是被截断 → 升预算也救不回来,别再烧 token。
        if not truncated:
            break
        i += 1
    return None, last_raw


def run_agent_json(agent_type: str, user_prompt: str, *, lang: str | None = None,
                   config_id: int | None = None,
                   image_urls: list[str] | None = None,
                   system: str | None = None,
                   max_tokens: int | None = None,
                   temperature: float = 0.4,
                   fields: list[str] | None = None) -> dict | list:
    """跑 Agent 并解析 JSON;解析失败时抛 RuntimeError(带原始输出片段)。

    **总是把「只输出 JSON」写进用户消息**:部分网关要求 messages 里出现 json 字样才肯用
    response_format=json_object,而 workspace/prompts/*.md 里的系统提示不一定含该词
    (实测 storyboard_breaker 的 md 就没有),否则整个 Agent 调用 400。

    system:整体覆盖系统提示(同 run_agent)。extractor 这类提示词写死了
    「调用工具保存」的 Agent 必须用 JSON 专用 system,否则拿到的是工具调用。
    max_tokens:起始输出预算(**不是上限**,被截断时仍会往上自适应升)。
    不传则读该服务配置里手填的值,留空用 8192。
    temperature:采样温度(默认 0.4)。结构化抽取宜低(0.2),创作类可高些。
    fields:逐字段兜底清单 —— 连 JSON 都解析不出来时按 "key": "value" 抠,
    宁可给残缺结果也别让用户白等(上游 askConceptJson 同款)。

    失败时按「输出是否被截断」自适应升预算重试(见 _looks_truncated / _budget_ladder),
    对推理型与非推理型模型一视同仁,不需要为单个供应商调参。
    """
    prompt = user_prompt if JSON_HINT in user_prompt else user_prompt + "\n\n" + JSON_HINT
    start = _configured_budget(config_id, max_tokens)
    data, raw = _call_budgeted(
        agent_type, prompt, lang=lang, config_id=config_id, image_urls=image_urls,
        system=system, start_budget=start,
        parse=extract_json,
        accept=lambda d: not _looks_like_tool_call(d),
        temperature=temperature,
    )
    if data is None:
        # 不是预算问题(模型照着带工具的 prompt 回了工具调用 / JSON 写坏):
        # 明确禁工具再试一次,沿用既有模式。
        # load_prompt 本身也可能抛(Agent 名拼错/提示词文件缺失)——那种情况下
        # 必须让下面那句「输出无法解析为 JSON」照常抛出去,否则真正的失败原因
        # 会被一个无关的 ValueError 顶掉,排查时看到的是错的东西。
        try:
            base_system = system if system is not None else prompts.load_prompt(agent_type, lang or "")
            raw2 = run_agent(agent_type, prompt, lang=lang, json_output=True,
                             temperature=temperature, config_id=config_id, image_urls=image_urls,
                             system=base_system + _NO_TOOL_HINT, max_tokens=start,
                             # 重试必须用同一套放大后的超时:start 是 65536 时默认
                             # 300s 根本不够,实测重试就是死在 300s 的 ReadTimeout
                             # (requests 的 Timeout 继承 IOError,会被下面 except 吞掉,
                             #  最终报成「输出无法解析为 JSON」,把真因藏了)
                             timeout=_timeout_for(start))
        except (AIError, ValueError, OSError) as e:
            log.warning("agent.retry.failed agent=%s err=%s", agent_type, str(e)[:200])
            raw2 = None
        # fields 兜底:连 JSON 都解析不出来时,逐字段抠出能抠的(宁可残缺也别空手)
        d2 = extract_json(cast(str, raw2), fields=fields) if raw2 else None
        if d2 is not None and not _looks_like_tool_call(d2):
            return d2
        log.warning("agent.parse.failed agent=%s finish_unparsed raw_head=%r raw_tail=%r",
                    agent_type, (raw2 or raw or "")[:160], (raw2 or raw or "")[-160:])
    if data is None:
        raise RuntimeError(f"{agent_type} 输出无法解析为 JSON:{raw[:300]}")
    return data
