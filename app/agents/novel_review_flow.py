# -*- coding: utf-8 -*-
"""Novel 审校循环 — LangGraph StateGraph 版本。

为什么引入(Option B):novel 现有的 `write_review_fix_one_chapter` 用一连串 if/else
    串联 write → review → conditional fix → end,流程分叉多了之后不可读。
    LangGraph StateGraph 让 conditional routing 一目了然,顺带拿 checkpointing / interrupt /
    streaming 能力 —— 是未来 novel 流程可视化 + JEV 状态门控 + 中途人工干预的基础。

怎么引入:**并存**而非替换。
  - 老调用:`from app.pipeline.novel import write_review_fix_one_chapter` —— 不动,
    默认行为不变(187 测试继续通过)。
  - 新调用:`from app.agents.novel_review_flow import build_novel_review_flow` ——
    显式 import,谁用谁跑。LangGraph 装了就跑真 StateGraph,没装就 fallback None。

三/四节点路由(writer → critic → repair/compressor)+ 两条循环:
  - **revise**:critic 给"局部可修补" → repair → 回到 critic 重审
  - **rewrite**:critic 给"整章要重写" → writer → 再走 critic
  - **ok**:critic 满意 → compressor(写库 / 卷段压缩),terminal
  - **giveup**:cycle ≥ max_cycles 强退,terminal
"""
from __future__ import annotations

from typing import TypedDict, Literal, Optional

# State schema — TypedDict 让 LangGraph 静态校验节点读写合法
CritiqueDecision = Literal["ok", "revise", "rewrite", "giveup"]


class NovelReviewState(TypedDict, total=False):
    # 上下文(只读输入)
    outline: str                          # 总纲(input)
    chapters_total: int                   # 项目计划章数(input)

    # 循环追踪
    cycle: int                            # 当前循环轮次(初值 0,writer 后 +1)
    max_cycles: int                       # 上限(input 默认 3)

    # 当前成品 + 审校
    draft: Optional[str]                  # writer 产出
    content: Optional[str]                # 流式路径:已有正文跳过 writer
    critique: Optional[dict]              # critic 产出{overall, dimensions}
    decision: Optional[CritiqueDecision]   # 路由决策,由 critic 设置
    jev_decision: Optional[str]           # JEV 门控输出("pass"|"rewrite"|None 未配)

    # 终态
    final: list[str]                      # 累计通过的章节(目前 demo 只塞 1 章)

    # 实际任务参数(透传给 writer/critic/repair 调用)
    episode_id: int
    config_id: Optional[int]
    lang: Optional[str]
    task_id: Optional[int]                # sys_task.id,用于 stage 上报


# ── LangGraph 软导入 ──
def _try_langgraph():
    """软依赖:LangGraph 没装就返回 (None, None)。不抛错,不警告 log,
    调用方 build_novel_review_flow() 看到 None 就自动走 fallback 路径。"""
    try:
        from langgraph.graph import StateGraph, END  # type: ignore
        return StateGraph, END
    except ImportError:
        return None, None


# ── 节点 ──
# 默认实现:stub + 接 app.pipeline.novel 真实函数(用户按需替换)
# 调用方可以在 build 之前 setattr 覆盖某个节点,或给个 factory 注入。

def _stage(s: str) -> None:
    """stage 标记占位 — 接到 taskmgr 上报 sys_task.params.stage。"""
    try:
        from app.core import taskmgr as TM
        # 调用方负责传 task_id;我们在 state 拿到
    except Exception:  # noqa: BLE001
        pass


def writer_node(state: NovelReviewState) -> dict:
    """第 1 轮调用现有 write_chapter(走原 prompt runner)。后续轮由 router 触发。

    return dict → LangGraph 把这一 dict merge 回 state.所以我们只更新关心的字段,
    不要 return 全 state(TypedDict 的 partial update 语义)。
    """
    from .runner import run_agent_json  # 现有的单步调用
    from ..pipeline.novel import write_chapter, _strip_think
    cycle = state.get("cycle", 0) + 1
    episode_id = state["episode_id"]
    config_id = state.get("config_id")
    lang = state.get("lang")
    task_id = state.get("task_id")
    if task_id:
        try:
            from app.core import taskmgr as TM
            TM.set_stage(task_id, "writing", cycle)
        except Exception:  # noqa: BLE001
            pass
    write_chapter(episode_id, config_id=config_id, lang=lang)
    from ..core import db
    row = db.q1("SELECT content FROM episodes WHERE id=?", (episode_id,))
    draft = (row["content"] if row else "") or ""
    return {"cycle": cycle, "draft": draft}


def critic_node(state: NovelReviewState) -> dict:
    """六维审校 —— 复用 novel.review_chapter,然后归一化成 decision 路由信号。"""
    from ..pipeline.novel import review_chapter
    episode_id = state["episode_id"]
    config_id = state.get("config_id")
    lang = state.get("lang")
    task_id = state.get("task_id")
    if task_id:
        try:
            from app.core import taskmgr as TM
            TM.set_stage(task_id, "reviewing", state.get("cycle", 0))
        except Exception:  # noqa: BLE001
            pass
    try:
        review = review_chapter(episode_id, config_id=config_id, lang=lang)
    except Exception:  # noqa: BLE001
        # 审校炸了不要崩循环 —— 退到 revise 走 repair 让 LLM 自行看一遍
        return {"critique": None, "decision": "revise"}

    # 把"overall=fix"的 review 归一化成 decision:
    #   - dimensions 全过 → "ok"
    #   - overall="fix" 但 issues < 5 → "revise"(局部修)
    #   - overall="fix" 且 issues ≥ 5 → "rewrite"(整章重写更划算)
    #   - cycle ≥ max_cycles → "giveup"
    overall = (review or {}).get("overall")
    dims = (review or {}).get("dimensions") or {}
    issue_count = sum(
        1 for v in dims.values() if isinstance(v, dict) and not v.get("pass", True)
    )
    if overall == "pass":
        decision: CritiqueDecision = "ok"
    elif issue_count >= 5:
        decision = "rewrite"
    elif issue_count >= 1:
        decision = "revise"
    else:
        decision = "ok"

    cycle = state.get("cycle", 0)
    max_cycles = state.get("max_cycles", 3)
    if cycle >= max_cycles and decision != "ok":
        decision = "giveup"
    return {"critique": review, "decision": decision}


def repair_node(state: NovelReviewState) -> dict:
    """局部修复:基于 critic 给的 issues,调 novel_editor 改稿,落库。"""
    from .runner import run_agent
    from ..pipeline.novel import _strip_think, _gate_content, get_novel_pov, pov_rule
    from ..core import db

    review = state.get("critique") or {}
    content = state.get("draft") or ""
    episode_id = state["episode_id"]
    config_id = state.get("config_id")
    lang = state.get("lang")
    task_id = state.get("task_id")

    if task_id:
        try:
            from app.core import taskmgr as TM
            TM.set_stage(task_id, "repairing", state.get("cycle", 0))
        except Exception:  # noqa: BLE001
            pass

    issues = []
    for dim, v in (review.get("dimensions") or {}).items():
        if isinstance(v, dict) and not v.get("pass", True):
            issues.append(f"[{dim}] " + "; ".join(v.get("issues", [])[:3]))
    if not issues:
        # critic 没具体列 issues(可能是 fail/异常) → 极保守:全章 rewrite。
        # 让 routing 自己挑 rewrite 路径就行,这里不动 draft。
        return {"decision": "rewrite"}

    ep = db.q1("SELECT drama_id FROM episodes WHERE id=?", (episode_id,)) or {}
    fix_prompt = (
        "审校发现以下问题,请修复后输出完整修订正文:\n"
        + "\n".join(issues[:8])
        + f"\n\n本项目叙事人称: {pov_rule(get_novel_pov(ep['drama_id']))}(修复时必须保持不变)"
        + f"\n\n原正文:\n{content[:14000]}"
    )
    fixed = _strip_think(run_agent("novel_editor", fix_prompt, lang=lang, config_id=config_id))
    fixed = _gate_content(fixed, "审校修复正文")
    db.ex("UPDATE episodes SET content=?, updated_at=? WHERE id=?", (fixed, db.now(), episode_id))
    return {"draft": fixed}


def compressor_node(state: NovelReviewState) -> dict:
    """终态:把通过的 draft 推进 final 列表,调用方自行入库。"""
    return {"final": [state["draft"]]}


def jev_gate_node(state: NovelReviewState) -> dict:
    """JEV 连续性门控 —— 修完后调 jev_client,看状态是否依然连续。

    返回:
      - "pass": 通过,回到 critic 再审
      - "rewrite": 不连续,回 writer 重新打稿
      - None: JEV 未配 / 调用异常 → 视同 pass(走原 critic)

    项目决策门控(TypeSafe AI):长篇连续性自动判读。未配置时台账照常维护,
    跳过矛盾判定 —— 与已有 .env 兼容逻辑一致。
    """
    # 上报阶段:修完后的连续性检查也是审校过程的一环,界面上要有「正在做什么」,
    # 否则修复(可能十几秒)和 JEV 检查之间红框状态栏是静止的
    if state.get("task_id"):
        try:
            from app.core import taskmgr as TM
            TM.set_stage(state["task_id"], "jev_gate", state.get("cycle", 0))
        except Exception:  # noqa: BLE001
            pass
    try:
        from app.ai.jev_gate import get_jev_gate
        gate = get_jev_gate()
        if not gate.usable:
            return {"jev_decision": None}    # 未配,不拦

        # 提取 state 摘要提给 JEV
        # questions: {连续性? 1=通过,0=不连续}
        questions = {
            "continuity": {
                "type": "noul",
                "instructions": "本章与上文叙事是否仍连续(人物身份/事件/时间线无矛盾)？1=是,0=否",
            }
        }
        draft = state.get("draft") or ""
        ctx = f"【项目总纲】\n{state.get('outline', '')[:1000]}\n【本章正文】\n{draft[:2000]}"
        result = gate.client.decide(ctx, questions)
        if not result or not result.get("answers"):
            return {"jev_decision": None}
        v = (result["answers"].get("continuity") or {}).get("noul")
        try:
            v_float = float(v)
        except (TypeError, ValueError):
            return {"jev_decision": None}
        return {"jev_decision": "pass" if v_float >= 0.5 else "rewrite"}
    except Exception:  # noqa: BLE001 —— JEV 不能拖累审校循环
        return {"jev_decision": None}


# ── 路由 ──
def route_after_criticique(state: NovelReviewState) -> str:
    """conditional edge 的路由函数——纯函数,无副作用,LangGraph 内部会反复调用。

    返回值是节点 name(我已经在 build 里 register 的)。"""
    d = state.get("decision")
    if d == "ok":
        return "compressor"
    if d == "giveup":
        return "__end__"     # LangGraph 的 END sentinel
    # "revise" / "rewrite" / None —— 用 decision 默认到 revise(修补)
    return "repair" if d == "revise" else "writer"


def route_after_jev(state: NovelReviewState) -> str:
    """JEV 门控后的路由 —— 通过 → 再 critic;不连续 → 回 writer;未配置 → 透传。"""
    j = state.get("jev_decision")
    if j == "rewrite":
        return "writer"
    # j == "pass" 或 None 都回到 critic 再过一遍(实际写剧情分支路径)
    return "critic"


# ── 组装 ──
def build_novel_review_flow():
    """返回 LangGraph CompiledStateGraph;LangGraph 没装就返回 None。

    调用方:
        graph = build_novel_review_flow()
        if graph is None:
            # 走老的 write_review_fix_one_chapter
            ...
        else:
            out = graph.invoke({"outline": ..., "chapters_total": 1, "episode_id": 42})
    """
    StateGraph, END = _try_langgraph()
    if StateGraph is None:
        return None

    g = StateGraph(NovelReviewState)
    g.add_node("writer", writer_node)
    g.add_node("critic", critic_node)
    g.add_node("repair", repair_node)
    g.add_node("jev_gate", jev_gate_node)
    g.add_node("compressor", compressor_node)
    g.add_edge("writer", "critic")
    g.add_conditional_edges("critic", route_after_criticique, {
        "compressor": "compressor",
        "__end__": END,
        "repair": "repair",
        "writer": "writer",
    })
    g.add_edge("repair", "jev_gate")          # 修完 → JEV 门控 → 再 critic
    g.add_conditional_edges("jev_gate", route_after_jev, {
        "critic": "critic",
        "writer": "writer",
    })
    g.add_edge("compressor", END)
    g.set_entry_point("writer")
    # C.3 interrupt demo:在 jev_gate 前可暂停,等用户中途决策 prompt 配方。
    # 大部分 caller 用 run_novel_review_loop 不传 interrupt_config,默认无 interrupt。
    return g.compile(checkpointer=None)


# ── 便利包装(无 LangGraph 时也可用)──
def run_novel_review_loop(*, episode_id: int, outline: str = "",
                          chapters_total: int = 1, max_cycles: int = 3,
                          config_id: int | None = None,
                          lang: str | None = None,
                          task_id: int | None = None,
                          content: str | None = None,
                          on_cycle=None) -> dict:
    """统一的入口:有 LangGraph 走 StateGraph,没装就 fall back 到
    直接 while-loop 调现有 pipeline(与老 write_review_fix_one_chapter 等价但
    多了 cycle 上限)。

    返回:{"decision": str, "final": [str], "cycles": int}
    """
    graph = build_novel_review_flow()
    final: list[str] = []
    cycles = 0
    decision = "revise"

    if graph is not None:
        # LangGraph 路径
        from ..core.taskmgr import TASKMGR
        out = graph.invoke({
            "outline": outline,
            "chapters_total": chapters_total,
            "cycle": 0,
            "max_cycles": max_cycles,
            "draft": content,             # 流式路径:已生成的正文跳过 writer
            "content": content,
            "critique": None,
            "decision": None,
            "jev_decision": None,
            "final": [],
            "episode_id": episode_id,
            "config_id": config_id,
            "lang": lang,
            "task_id": task_id,
        })
        return {
            "decision": out.get("decision") or "giveup",
            "final": out.get("final") or [],
            "cycles": out.get("cycle", 0),
        }

    # Fallback:直接 cycle loop,逐节点调,跟 StateGraph 同语义
    draft = content                       # 流式路径:已生成的正文直接当首轮 draft
    critique = None
    while decision in ("revise", "rewrite") and cycles < max_cycles:
        if on_cycle:
            on_cycle(cycles + 1, "running")
        if draft is None or decision == "rewrite":
            draft = writer_node({
                "cycle": cycles, "episode_id": episode_id,
                "config_id": config_id, "lang": lang, "task_id": task_id,
            })["draft"]
        out_c = critic_node({
            "cycle": cycles, "draft": draft, "critique": critique,
            "episode_id": episode_id, "config_id": config_id,
            "lang": lang, "task_id": task_id, "max_cycles": max_cycles,
        })
        decision = out_c["decision"]
        critique = out_c["critique"]
        cycles += 1
        if decision == "revise":
            out_r = repair_node({
                "cycle": cycles, "draft": draft, "critique": critique,
                "episode_id": episode_id, "config_id": config_id,
                "lang": lang, "task_id": task_id,
            })
            draft = out_r.get("draft", draft)
            decision = out_r.get("decision", decision)
            # C.2 fallback JEV gate:repair 后跑一次 jev_gate,
            # "rewrite" 则强制回 writer,即使 cycles 没满
            try:
                jev_out = jev_gate_node({
                    "episode_id": episode_id, "draft": draft,
                    "outline": outline, "task_id": task_id,
                    "cycle": cycles,       # 阶段上报用:界面上显示「第 N 轮」
                })
            except Exception:  # noqa: BLE001
                jev_out = {"jev_decision": None}
            if jev_out.get("jev_decision") == "rewrite":
                decision = "rewrite"
        if on_cycle:
            on_cycle(cycles, decision)
    if decision == "ok":
        final = compressor_node({"draft": draft})["final"]
    elif cycles >= max_cycles and decision in ("revise", "rewrite"):
        # cycle 用尽还有 issues → 强退 giveup(对齐 LangGraph 行为)
        decision = "giveup"
    return {"decision": decision, "final": final, "cycles": cycles}


def interrupt_demo_one_step(episode_id: int, max_cycles: int = 3, **kw):
    """C.3 interrupt demo —— 用 LangGraph native interrupt 在 jev_gate 前暂停。

    用法(需要装 langgraph):
        graph = build_novel_review_flow()
        if graph is None:
            return None
        from langgraph.checkpoint.memory import MemorySaver
        graph.checkpointer = MemorySaver()
        config = {"configurable": {"thread_id": f"novel-{episode_id}"}}
        # 第 1 段 invoke:跑到 jev_gate 前自动停
        out = graph.invoke({"episode_id": episode_id, "max_cycles": max_cycles, **kw}, config)
        # 用户这时可改 state["outline"],然后 None 续跑
        out2 = graph.invoke(None, config)
        return out2

    这个函数本身不主动 invoke —— 它返回 LangGraph 配置示例 + 注释,
    实际 invoke 由 caller 在装了 LangGraph 后决定。
    """
    StateGraph, END = _try_langgraph()
    if StateGraph is None:
        return None
    # 真 interrupt 要 build 时加 interrupt_before=["jev_gate"]:
    g = StateGraph(NovelReviewState)
    g.add_node("writer", writer_node)
    g.add_node("critic", critic_node)
    g.add_node("repair", repair_node)
    g.add_node("jev_gate", jev_gate_node)
    g.add_node("compressor", compressor_node)
    g.add_edge("writer", "critic")
    g.add_conditional_edges("critic", route_after_criticique, {
        "compressor": "compressor", "__end__": END,
        "repair": "repair", "writer": "writer",
    })
    g.add_edge("repair", "jev_gate")
    g.add_conditional_edges("jev_gate", route_after_jev, {
        "critic": "critic", "writer": "writer",
    })
    g.add_edge("compressor", END)
    g.set_entry_point("writer")
    return g.compile(
        checkpointer=None,
        interrupt_before=["jev_gate"],   # ← 真正在 jev_gate 之前暂停
    )
