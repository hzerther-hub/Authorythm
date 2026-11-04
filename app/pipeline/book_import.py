"""导入整本书 → 分析 → 仿写 三段式流水线(对齐原版 2df744b)。

导入:仅 TXT(支持 UTF-8/UTF-16/GBK/GB18030/Big5),三级切章,清空旧章节后批量插入
      (破坏性,已有章节必须显式 confirm —— 见 import_book)。
分析:12 章一组 → 文本模型抽取(summary/beats/characters/settings/hooks),3 worker 并发
      (被限流暂停过则降档 3→2→1),单组重试 3 次(2s→6s 退避);失败率≥30% 且已跑≥50 组
      → 暂停(避免基于残缺数据出错误档案);重跑自动跳过已成功组(断点续跑);
      运行中每 10 秒心跳落盘,进程中途被杀也能从断点续跑。
仿写:四阶段(settings→outline→volumes→creating),三条铁律(专名全换/情节仿而不抄/结构保留)。
      三阶段提示词按上游 novel.ts 的 profileBlock 口径喂「标签化档案」——
      这是「生成的新书与原书骨架像不像」的决定性因素,别改回 json 整坨。
"""
from __future__ import annotations

import contextlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from ..agents import prompts, runner
from ..core import config, db
from ..core.logging_setup import get_logger
from . import character_spec

log = get_logger(__name__)

# ── 系统提示覆盖 ────────────────────────────────────────────────────
#
# workspace/prompts/novel_planner.md 末尾明写「**只输出工具调用,不要输出规划文本**」
# —— 那是 Mastra Agent(带 save_novel_settings / save_main_characters 工具)的口径。
# 本仓 runner 是单次调用、**没有工具**,不覆盖系统提示的话,模型会老实地回
# {"name":"save_novel_settings","arguments":{...}},而 extract_json 把工具调用当
# **合法 JSON** 解析成功 → 设定/总纲/分卷全是空,仿写建出一本空壳书,
# 新书与原书毫无关系。
#
# 这就是 2026-11-02 用户实测「Python 生成的新书改动较大、Vue 版还是同一题材」
# 的**真正根因**:提示词结构只是第二层,第一层是模型压根没交出内容。
# (runner.run_agent 的 docstring 早就记了这个坑,book_import 一直没照做。)
_PLANNER_SYSTEM = (
    "你是资深网文策划,负责起草书级设定/总纲/世界观/故事合约/分卷战略/主要角色。"
    "本次运行环境**没有工具**:不要输出任何工具调用,不要提及 save_novel_settings "
    "之类的函数名;只输出用户消息要求的 JSON 对象,不要 markdown 代码块、不要解释文字。"
)

# 同一个坑的第二处:workspace/prompts/novel_reviewer.md 规定的输出 schema 是
# **审校用**的 {"issues":[…],"facts":[…],"foreshadows":[…],"closes":[…]} —— 那是
# 「章节审校」流程的契约。而分析阶段要的是 {summary,beats,characters,settings,hooks}。
# 模型照章办事返回了**合法的审校 JSON**,解析得出来却没有一个 summary 字段 →
# 「节拍摘要为空」(2026-11-02 实测)。同一个 agent 名、不同任务,必须各自覆盖
# 系统提示,否则模型只会按 md 里的 schema 回。
_ANALYZER_SYSTEM = (
    "你是长篇小说结构分析师,负责按用户消息给定的 JSON 结构抽取章节信息。"
    "本次运行环境**没有工具**:不要输出任何工具调用;"
    "只输出用户消息里写明的那个 JSON 对象,字段名与用户消息完全一致,"
    "不要 markdown 代码块、不要解释文字、不要输出别的 schema。"
)


def _planner_system(lang: str | None) -> str:
    """给整体覆盖过的系统提示补上输出语言约束(与 project_concept 同款)。"""
    return prompts.with_language_suffix(_PLANNER_SYSTEM, lang)


def _analyzer_system(lang: str | None) -> str:
    """分析阶段的系统提示覆盖(见 _ANALYZER_SYSTEM 的坑说明)。"""
    return prompts.with_language_suffix(_ANALYZER_SYSTEM, lang)


def _is_tool_call(data) -> bool:
    """工具调用 JSON({name, arguments})**不是内容**,必须拒。

    workspace 的 novel_planner.md 让模型「只输出工具调用」,而本仓没有工具。
    这种 JSON 解析得出来、却一个设定字段都没有 —— 拿它当设定,建出来的是空壳书。
    """
    return isinstance(data, dict) and set(data.keys()) == {"name", "arguments"}

MIN_CHARS = 1000
MAX_CHARS = 100_000_000
GROUP = 12                 # 每组章数
SAMPLE_HEAD = 6000
SAMPLE_TAIL = 2500
GROUP_CHAR_LIMIT = 9000
FAIL_THRESHOLD = 0.30      # 失败率阈值
FAIL_MIN_SAMPLES = 50      # 触发暂停的最小样本数
HEARTBEAT_S = 10.0         # 分析进度落盘间隔(上游 persistAnalyzeJob 同参数)

CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:第\s*[0-9零一二两三四五六七八九十百千万]+\s*[章回节][^\n]{0,40}|楔子|序章|引子|番外)[^\n]{0,40}\s*$")
SEPARATOR_RE = re.compile(r"^[-_=*~—·]{4,}\s*$")
TITLE_STOPWORDS = {"正文", "目录", "序", "完", "全文完", "未完待续", "公告", "上架感言"}
# 章标题正则的最少命中数:原版是 3 —— 有 3 个「第N章」就按标题切。
# 此前写死 32,短书(3-31 章)全部掉进兜底被 2 万字窗口切碎,章节结构直接丢失。
MIN_HEADING_HITS = 3

# 正在跑分析的项目(上游 analyzeJobs 的进程内版):同一个项目不许并发跑两次。
# 心跳落盘把「running」写进了 novel_meta —— UI 关掉再打开会看到 running 态,
# 于是「恢复分析」按钮是亮的;没有这道闸,用户一点就起第二个分析,两批 worker
# 抢同一份 partial_chunks,续跑出来的档案是花的。
_ANALYZING: set[int] = set()
_ANALYZING_LOCK = threading.Lock()


@contextlib.contextmanager
def _analysis_slot(drama_id: int):
    """占用本项目的分析名额;已在跑就直接拒绝(上游:分析已在进行中)。"""
    with _ANALYZING_LOCK:
        if drama_id in _ANALYZING:
            raise RuntimeError("该项目的分析正在进行中,请等当前分析结束")
        _ANALYZING.add(drama_id)
    try:
        yield
    finally:
        with _ANALYZING_LOCK:
            _ANALYZING.discard(drama_id)


# ═══ 1) 导入 ═══
def bytes_to_utf8(data: bytes, hint: str = "") -> tuple:
    """编码判定:显式优先;自动则 UTF-8 试解,否则 gbk → gb18030 → big5。

    返回 (text, encoding) —— 检出的编码回报给 UI,GBK 老书用户能确认没解错。
    """
    if hint:
        try:
            return data.decode(hint, errors="replace"), hint
        except LookupError:
            pass
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc), "utf-8"
        except UnicodeDecodeError:
            continue
    for enc in ("gbk", "gb18030", "big5"):
        try:
            text = data.decode(enc, errors="replace")
            # 替换符占比 <0.5% 才认(原版同阈值):全替换说明猜错了编码
            if text.count("�") / max(len(text), 1) < 0.005:
                return text, enc
        except Exception:  # noqa: BLE001
            continue
    return data.decode("utf-8", errors="replace"), "utf-8"


def _looks_like_title(line: str) -> bool:
    t = line.strip()
    if not t or len(t) > 40:
        return False
    if t in TITLE_STOPWORDS:
        return False
    return not re.search(r"[。!！?？…,.，]$", t)


def _chapters_from_marks(lines: list, marks: list, min_body: int = 20) -> list:
    """按标题行号列表切章:正文不足 min_body 的丢掉(书首「正文」标记与首章名之间的空档)。"""
    chapters = []
    for k, start in enumerate(marks):
        end = marks[k + 1] if k + 1 < len(marks) else len(lines)
        body = "\n".join(lines[start + 1:end]).strip()
        if len(body) >= min_body:
            chapters.append((lines[start].strip()[:120], body))
    return chapters


def split_book_into_chapters(text: str) -> list:
    """三级切章:章标题正则 → 分隔线+启发式 → 2 万字窗口兜底。"""
    lines = text.split("\n")
    # 1) 章标题正则(行长≤48 且命中≥3,原版同阈值)
    hits = [i for i, _ln in enumerate(lines)
            if len(_ln.strip()) <= 48 and CHAPTER_HEADING_RE.match(_ln)]
    if len(hits) >= MIN_HEADING_HITS:
        chapters = _chapters_from_marks(lines, hits, min_body=1)
        if chapters:
            return chapters
    # 2) 分隔线 + 短标题行。两种站点格式都认,原版方向优先:
    #    2a) 分隔线在标题**上方**(原版唯一口径:「----」后跟无编号章名)
    #    2b) 分隔线在标题**下方**(标题后加横线,本仓此前唯一口径)
    #    连续分隔线只认一次(向下跳过),避免重复定位到同一标题行。
    for below in (True, False):
        marks = []
        for i, _ln in enumerate(lines):
            if not SEPARATOR_RE.match(_ln.strip()):
                continue
            if below:
                # 向下跳过空行与连续分隔线,找第一个非空行
                j = i + 1
                while j < len(lines) and (SEPARATOR_RE.match(lines[j].strip()) or not lines[j].strip()):
                    j += 1
                if j < len(lines) and _looks_like_title(lines[j]):  # noqa: SIM102  (嵌套 if 各带注释说明,合并成 and 会丢掉可读性)
                    if not marks or marks[-1] != j:
                        marks.append(j)
            else:
                if i > 0 and _looks_like_title(lines[i - 1]):
                    marks.append(i - 1)
        if len(marks) >= MIN_HEADING_HITS:
            chapters = _chapters_from_marks(lines, marks)
            if len(chapters) >= MIN_HEADING_HITS:
                return chapters
    # 3) 兜底:2 万字窗口
    chapters = []
    step = 20000
    for k, start in enumerate(range(0, len(text), step)):
        seg = text[start:start + step].strip()
        if len(seg) >= 200:
            chapters.append((f"片段 {k + 1}", seg))
    return chapters


def import_book(drama_id: int, data: bytes | None = None, text: str = "",
                encoding: str = "", confirm: bool = False) -> dict:
    """导入整本书并切章入库(清空旧章节 + 每批 100 行插入,避开 SQLite 变量上限)。

    **破坏性操作护栏(上游同款)**:导入语义是「本项目改当源书」,会清掉既有全部
    章节(含建项时自动建的空第 1 集)及其分镜。上游是软删(deletedAt)可经数据库恢复,
    本仓是硬删 + 级联清分镜(见下方 DELETE 链)—— 不可逆,所以护栏必须更硬:
    已有章节时**必须显式 confirm=True**,否则直接拒绝。UI 侧先弹二次确认对话框,
    用户点了才带 confirm 重发(上游前后端双保险同款)。

    有意不对齐之处:上游软删、本仓硬删。上游软删是为了「能恢复」,本仓把分镜/
    角色/场景/道具的级联清理做全了(软删留一堆孤儿行反而更难收拾),代价是不可逆
    —— 用 confirm 护栏 + UI 二次确认补上这一层保险。
    """
    if data is not None:
        content, detected_enc = bytes_to_utf8(data, encoding)
    elif text:
        content, detected_enc = text, "utf-8"
    else:
        raise RuntimeError("未提供书籍内容")
    content = content.lstrip("﻿")
    n = len(content)
    if n < MIN_CHARS:
        raise RuntimeError(f"书籍内容太短({n} 字),无法导入")
    if n > MAX_CHARS:
        raise RuntimeError(f"书籍内容过长({n} 字),超出上限")
    chapters = split_book_into_chapters(content)
    if not chapters:
        raise RuntimeError("未能从文本中切分出章节")

    ts = db.now()
    existing = db.q("SELECT id FROM episodes WHERE drama_id=?", (drama_id,))
    if existing and not confirm:
        raise RuntimeError(
            f"该项目已有 {len(existing)} 个章节,导入会清空全部既有章节与分镜并按新书重建。"
            "确认无误请重新导入(带确认标记)。")
    # 清空全部既有章节(含建项时自动建的空第 1 集)及其分镜
    for ep in existing:
        for panel in db.q("SELECT id FROM comic_panels WHERE episode_id=?", (ep["id"],)):
            db.ex("DELETE FROM comic_panel_characters WHERE panel_id=?", (panel["id"],))
            db.ex("DELETE FROM comic_panel_scenes WHERE panel_id=?", (panel["id"],))
            db.ex("DELETE FROM comic_panel_props WHERE panel_id=?", (panel["id"],))
        db.ex("DELETE FROM comic_panels WHERE episode_id=?", (ep["id"],))
        db.ex("DELETE FROM video_merges WHERE episode_id=?", (ep["id"],))
        db.ex("DELETE FROM storyboard_characters WHERE storyboard_id IN "
               "(SELECT id FROM storyboards WHERE episode_id=?)", (ep["id"],))
        db.ex("DELETE FROM storyboard_props WHERE storyboard_id IN "
               "(SELECT id FROM storyboards WHERE episode_id=?)", (ep["id"],))
        db.ex("DELETE FROM storyboards WHERE episode_id=?", (ep["id"],))
        db.ex("DELETE FROM episode_characters WHERE episode_id=?", (ep["id"],))
        db.ex("DELETE FROM episode_scenes WHERE episode_id=?", (ep["id"],))
        db.ex("DELETE FROM episode_props WHERE episode_id=?", (ep["id"],))
        db.ex("DELETE FROM episodes WHERE id=?", (ep["id"],))
    for i in range(0, len(chapters), 100):
        batch = chapters[i:i + 100]
        rows = [(drama_id, i + k + 1, t[:120], c, "draft", None, "720p", ts, ts)
                for k, (t, c) in enumerate(batch)]
        db.exmany("""INSERT INTO episodes(drama_id,episode_number,title,content,status,
                     target_words,resolution,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)""", rows)
    d = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
    meta = db.jload(d["novel_meta"], {}) if d else {}
    meta["imported"] = {"at": ts, "chapters": len(chapters), "chars": n}
    meta.pop("analysis", None)                       # 作废旧档案(章节已变)
    db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), ts, drama_id))
    return {"chapters": len(chapters), "total_chars": n, "encoding": detected_enc}


# ═══ 2) 分析 ═══
MAP_PROMPT = """你是长篇小说结构分析师。下面给出连续若干章的正文节选,请输出 JSON:
{"summary":"≤200字 章节梗概","beats":["关键情节3-6条,每条≤40字,写清谁在什么冲突下做了什么、结果如何"],
"characters":[{"name":"","identity":"","personality":""}],"settings":"世界观要素≤100字","hooks":"节奏与钩子手法≤100字"}
只输出 JSON。beats 是后续仿写情节链的原料,请务必具体。"""

REDUCE_PROMPT = """你是小说结构总编。下面是全书各段的节拍摘要,请输出**仿写档案** JSON:
{"genre":"题材","book_structure":"全书结构≤300字","main_characters":[{"name","identity","personality","arc"}],
"worldview":"世界观≤300字","conflict_lines":["冲突线3-5条"],"rhythm_patterns":"节奏模式≤200字","style_features":"文风特征≤150字"}
只输出 JSON。"""

# 被限流暂停后的恢复冷却:上游配额恢复需要时间,30 秒内恢复会被拒绝(原版同参数)
RESUME_COOLDOWN_S = 30


def _with_retry(fn, attempts: int = 3, delays=(2, 6)):
    """失败重试 + 指数退避(2s→6s),专为防文本模型限流(429/5xx/超时)。"""
    last = None
    for i in range(attempts):
        if i > 0 and delays[i - 1]:
            time.sleep(delays[i - 1])
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise last


def _profile_has_content(profile) -> bool:
    """档案里有没有**真内容**。

    Reduce 的模型在输入全空时会「礼貌拒绝」:返回 {"issues":[…],"facts":[]}
    这样的 JSON —— 解析得出 dict,却没有任何可用的档案字段。这种假档案一旦
    按 done 落库,仿写/设定就会基于空档案瞎编(2026-11-01 实测)。
    """
    if not isinstance(profile, dict):
        return False
    for k in ("genre", "book_structure", "worldview", "rhythm_patterns",
              "style_features"):
        if str(profile.get(k) or "").strip():
            return True
    for k in ("main_characters", "conflict_lines"):
        if isinstance(profile.get(k), list) and profile[k]:
            return True
    return False


def _segment_digest(chapters: list) -> str:
    """整组拼接后取头 6000 + 尾 2500(原版口径)。

    尾段必须来自**组的最后一章** —— 此前累计到 6000 字就 break,组内后面的章
    被整章丢弃,尾 2500 取到的是组中段,组尾的关键剧情(钩子/转折)全都没进模型。
    """
    joined = "\n".join(f"【第{num}章 {title}】\n{body}"
                       for num, title, body in chapters)
    if len(joined) > GROUP_CHAR_LIMIT:
        return joined[:SAMPLE_HEAD] + "\n……（中段略）……\n" + joined[-SAMPLE_TAIL:]
    return joined


def _reduce_digest(digests: list) -> str:
    """Reduce 输入:格式化文本(原版格式),而不是 json.dumps —— 模型读结构化叙述
    比读裸 JSON 数组更稳,也不用截断(此前截 24000 字符会把长书后段整段砍掉)。"""

    def _chars_line(d: dict) -> str:
        """人物行:名字(身份,性格) —— 上游 Reduce 输入同款口径。

        此前只写「名字,身份」,**丢掉了性格**:性格正是人物弧线的原料,档案里
        没有它,Reduce 出来的 main_characters[].arc 与 personality 就是空的,
        仿写新书的人物弧线自然对不上原书。
        """
        names = []
        for c in d.get("characters") or []:
            if not isinstance(c, dict):
                continue
            names.append("{} ({},{})".format(
                c.get("name") or "", c.get("identity") or "", c.get("personality") or ""))
        return "、".join(n for n in names if n.strip("(),"))

    parts = []
    for i, d in enumerate(digests, 1):
        parts.append("【段{}】{}\n人物:{}\n设定:{}\n节奏:{}".format(
            i, d.get("summary") or "", _chars_line(d),
            d.get("settings") or "", d.get("hooks") or ""))
    return "\n\n".join(parts)


def run_analysis(drama_id: int, on_progress=None, stop_check=None, resume: bool = False) -> dict:
    """跑章节分析(外层只管「同一项目不许并发」,实际逻辑在 _run_analysis)。

    上游 analyze-book 有同一道闸:分析已在进行中 → 直接拒绝。心跳落盘把
    「running」写进 novel_meta 之后,UI 的「恢复分析」在分析跑着时也是亮的,
    没这道闸就会起第二个分析,两批 worker 抢同一份 partial_chunks。
    """
    with _analysis_slot(drama_id):
        return _run_analysis(drama_id, on_progress=on_progress,
                             stop_check=stop_check, resume=resume)


def _run_analysis(drama_id: int, on_progress=None, stop_check=None, resume: bool = False) -> dict:
    """Map → Reduce:产出仿写档案落 novel_meta.analysis。

    - 3 worker 并发(被限流暂停过则按 pause_count 降档 3→2→1)+ 错峰启动
    - 单组重试 3 次(2s→6s 退避),单组失败不阻塞其他组
    - resume=True:跳过 partial_chunks 里已成功的组(断点续跑,配 30s 冷却)
    - 失败率≥30% 且样本≥50 → 暂停并落盘已成功组,不跑 Reduce
    """
    eps = db.q("SELECT episode_number, title, content FROM episodes WHERE drama_id=? "
               "ORDER BY episode_number", (drama_id,))
    chapters = [(r["episode_number"], r["title"] or "", r["content"] or "")
                for r in eps if (r["content"] or "").strip()]
    if not chapters:
        raise RuntimeError("没有可分析的章节正文")
    lang = config.resolve_content_language(drama_id)
    groups = [chapters[i:i + GROUP] for i in range(0, len(chapters), GROUP)]

    d = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
    prev = db.jload(d["novel_meta"], {}) if d else {}
    prev_analysis = prev.get("analysis") or {}
    prev_status = str(prev_analysis.get("status") or "")
    pause_count = int(prev_analysis.get("pause_count") or 0)
    # 断点续跑:预填已成功组;冷却期检查(原版同参数,给上游配额喘息时间)
    chunk_summaries = [None] * len(groups)
    if resume:
        # 「paused」= 失败率安全阀主动暂停;「running」= 上次跑着跑着进程没了
        # (崩溃/被强杀/机器休眠)。上游 analyze-resume 认这两种状态:落盘还是
        # running 而内存无任务 ⇒ 之前跑分析的进程已死,按暂停收进来允许续跑
        # (上游 novel.ts:2386-2417)。此前桌面版只认 paused,进程一崩断点就死在库里。
        if prev_status not in ("paused", "running"):
            raise RuntimeError("当前没有可恢复的分析任务")
        interrupted = prev_status == "running"
        if interrupted:
            # 中断过一次 = 按「被限流过」同等保守处理,并发降一档(上游同款)
            pause_count = max(pause_count, 1)
        last_paused = str(prev_analysis.get("paused_at") or prev_analysis.get("updated_at") or "")
        if last_paused:
            try:
                from datetime import datetime, timezone
                ts = datetime.fromisoformat(last_paused.replace("Z", "+00:00"))
                elapsed = (datetime.now(timezone.utc) - ts).total_seconds()
                if elapsed < RESUME_COOLDOWN_S:
                    wait = int(RESUME_COOLDOWN_S - elapsed) + 1
                    raise RuntimeError(f"冷却中:上游配额恢复需要时间,{wait} 秒后可重试")
            except ValueError:
                pass
        skipped = 0
        for item in prev_analysis.get("partial_chunks") or []:
            i = int(item.get("_seg") or 0) - 1
            if 0 <= i < len(groups) and item.get("_ok"):
                chunk_summaries[i] = item
                skipped += 1
        if skipped:
            log.info("[analyze] 断点续跑:跳过已成功 %d/%d 组(status=%s)",
                     skipped, len(groups), prev_status)

    # 并发档位按 pause_count 动态降档(原版:0→3,1→2,≥2→1),错峰同步加大
    concurrency = 3 if pause_count == 0 else 2 if pause_count == 1 else 1
    stagger_s = 1.0 if pause_count == 0 else 2.0 if pause_count == 1 else 3.0

    lock = threading.Lock()
    cursor = {"i": 0}
    state = {"done": 0, "failed": 0, "aborted": False}
    failed_indexes = []

    def _report():
        if on_progress:
            on_progress(state["done"], state["done"] + state["failed"],
                        f"第{min(state['done'] + state['failed'], len(groups))} 组")

    beat_lock = threading.Lock()
    last_beat = {"t": time.monotonic()}

    def _maybe_heartbeat() -> None:
        """每 10 秒把已成功组落盘一次(上游 persistAnalyzeJob 同款)。

        为什么必须有:分析一本 80 章的书要跑十几分钟,中途进程被杀/机器休眠就全丢
        —— 上游每 10 秒落一次盘,崩了最多丢 10 秒;本仓此前只在暂停/完成时落盘,
        中途崩溃 = 从头再来,上游配额白烧一遍(这正是本轮补的「中断可续跑」的前半段)。
        """
        now = time.monotonic()
        with beat_lock:
            if now - last_beat["t"] < HEARTBEAT_S:
                return
            last_beat["t"] = now
        with lock:
            partial = [{"_seg": i + 1, "_ok": True, **c}
                       for i, c in enumerate(chunk_summaries) if c is not None]
            done_n, failed_n = state["done"], state["failed"]
        try:
            d2 = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
            meta = db.jload(d2["novel_meta"], {}) if d2 else {}
            # 整体替换 analysis(不留上一轮的 profile):重跑期间旧档案是上一轮的结果,
            # 留着会让 UI 以为还能仿写。判定一律以 status 为准(上游同款口径)。
            meta["analysis"] = {"status": "running", "chapters": len(chapters),
                                "partial_chunks": partial, "done": done_n,
                                "failed": failed_n, "total": done_n + failed_n,
                                "pause_count": pause_count, "updated_at": db.now()}
            db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
                  (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
        except Exception as exc:  # noqa: BLE001 —— 心跳失败不阻断分析主流程
            log.warning("[analyze] 心跳落盘失败:%s", exc)

    def _worker(worker_id: int):
        if worker_id:                      # 错峰启动:避免同毫秒并发触发上游限流
            time.sleep(worker_id * stagger_s)
        while True:
            with lock:
                if state["aborted"] or (stop_check and stop_check()):
                    return
                idx = cursor["i"]
                cursor["i"] += 1
            if idx >= len(groups):
                return
            if chunk_summaries[idx] is not None:   # 断点续跑:已成功组直接跳过
                with lock:
                    state["done"] += 1
                    _report()
                continue
            seg = groups[idx]
            try:
                def _map_one(seg=seg):
                    # run_agent_json:注入「只输出 JSON」提示 + response_format=json_object
                    # + **预算阶梯**(被截断自动升 max_tokens 重试)——
                    # 裸 run_agent 三样都没有,推理型模型(MiniMax-M3)一思考就把
                    # 输出预算吃光,回 4 万字符散文,节拍摘要抽不出来(2026-11-02 实测)。
                    data = runner.run_agent_json(
                        "novel_reviewer", f"{_segment_digest(seg)}\n\n{MAP_PROMPT}",
                        temperature=0.2, lang=lang, system=_analyzer_system(lang))
                    if not isinstance(data, dict):
                        raise RuntimeError("节拍抽取输出不是 JSON 对象")
                    # **空转当失败**:推理块吃光输出预算/网关截断时,模型回空或
                    # 不可解析 —— 此前照存空摘要当「成功」,Reduce 拿到全空输入
                    # 产出 {issues:…} 的假档案,状态还是 done,仿写/设定全被
                    # 带进沟里(2026-11-01 实测:重生之我是股神 第二次分析)。
                    # 抛错让 _with_retry 重试;重试耗尽按组失败计数。
                    if not (str(data.get("summary") or "").strip() or data.get("beats")):
                        raise RuntimeError("节拍摘要为空(模型没给出 summary/beats)")
                    return data

                data = _with_retry(_map_one)
                with lock:
                    chunk_summaries[idx] = {
                        "chapters": [seg[0][0], seg[-1][0]],
                        "summary": str(data.get("summary") or ""),
                        "beats": [str(x) for x in (data.get("beats") or [])][:6],
                        "characters": data.get("characters") or [],
                        "settings": str(data.get("settings") or ""),
                        "hooks": str(data.get("hooks") or "")}
                    state["done"] += 1
                    log.info("[analyze] 第 %d 组完成 summary=%d字 beats=%d",
                             idx + 1, len(chunk_summaries[idx]["summary"]),
                             len(chunk_summaries[idx]["beats"]))
                    _report()
            except Exception as exc:  # noqa: BLE001
                with lock:
                    state["failed"] += 1
                    failed_indexes.append(idx)
                    done_now = state["done"] + state["failed"]
                    log.error(f"[analyze] 第 {idx + 1} 组失败({exc})")
                    # 安全阀:失败率≥30% 且样本≥50 → 暂停,不烧光上游配额
                    if (done_now >= FAIL_MIN_SAMPLES
                            and state["failed"] / done_now >= FAIL_THRESHOLD):
                        state["aborted"] = True
                _report()
            # 心跳落盘(锁外调用):进程中途被杀时,已成功组不丢,可续跑
            _maybe_heartbeat()

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(_worker, range(concurrency)))

    def _persist(analysis: dict) -> None:
        d2 = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
        meta = db.jload(d2["novel_meta"], {}) if d2 else {}
        meta["analysis"] = analysis
        db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
              (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))

    if state["aborted"]:
        # 暂停:落盘已成功组(带段号与 _ok 标记,下次 resume 按此跳过)+ pause_count +1
        pause_count += 1
        partial = [{"_seg": i + 1, "_ok": True, **c}
                   for i, c in enumerate(chunk_summaries) if c is not None]
        _persist({"status": "paused", "chapters": len(chapters),
                  "partial_chunks": partial,
                  "done": state["done"], "failed": state["failed"],
                  "total": state["done"] + state["failed"],
                  "pause_count": pause_count, "paused_at": db.now()})
        return {"status": "paused", "done": state["done"],
                "total": state["done"] + state["failed"], "failed": state["failed"]}
    if failed_indexes:
        log.error(f"[analyze] 部分组失败 {len(failed_indexes)}/{len(groups)}:"
              f"{failed_indexes[:10]}")
    # Reduce:只用成功组(失败组混入会把空摘要当真,污染档案);格式化文本不截断
    ok = [c for c in chunk_summaries if c is not None]
    if not ok:
        raise RuntimeError(
            f"全部 {len(groups)} 组节拍抽取失败(模型空转/超时)。"
            "常见原因:推理型模型把输出预算吃光 —— 调大该模型配置的「最大输出 token」"
            "或换个文本模型后重试。")
    profile = runner.run_agent_json(
        "novel_reviewer", f"{_reduce_digest(ok)}\n\n{REDUCE_PROMPT}",
        temperature=0.2, lang=lang, system=_analyzer_system(lang))
    if not isinstance(profile, dict):
        raise RuntimeError("档案输出不是 JSON 对象,请重试分析")
    if not _profile_has_content(profile):
        # 输入全空时模型会「礼貌拒绝」:回 {"issues":[…],"facts":[]} 这种
        # 解析得出的 dict,却没有档案字段 —— 这种假档案绝不能按 done 落库。
        issues = "；".join(str(x) for x in (profile.get("issues") or []))[:200]
        raise RuntimeError("分析没有产出可用档案"
                           + (f":{issues}" if issues else "(档案为空)")
                           + "。请重试分析;反复出现就换一个文本模型。")
    # plot_timeline 落库前剥掉 _seg/_ok 内部标记(resume 用的,不属于档案数据)
    timeline_clean = [{k: v for k, v in c.items() if not k.startswith("_")}
                      for c in ok]
    _persist({"status": "done", "chapters": len(chapters), "profile": profile,
              "plot_timeline": timeline_clean, "chunk_count": len(groups),
              "analyzed_at": db.now()})
    return {"status": "done", "chapters": len(chapters), "profile": profile}


# ═══ 3) 仿写 ═══
#
# 下面三段提示词是对齐上游 novel.ts 的 runImitation(阶段1设定→2总纲→3分卷)。
# **保真度全靠提示词结构,不是靠模型自觉** —— 与上游逐段比对后修了三处关键偏差,
# 每一处都直接对应「生成的新书与原书差太多」:
#
#   ① 铁律第 3 条上游写的是「叙事结构、**人物配置与弧线、冲突线、爽点周期与文风**
#      全部沿用原书骨架」;本仓原实现只写了「分卷节奏、章节密度、爽点间隔沿用节拍
#      时间线」—— 人物弧线/冲突线/文风没被点名,模型就当自由发挥 → 骨架漂移。
#   ② 原书档案此前是 json.dumps 整坨喂进去的。模型读整坨 JSON 读的是「待转换的
#      数据」,读标签化逐行才是「要照着写的骨架」。上游是 profileBlock 逐行标签,
#      本仓改成同样的标签化 —— 这一条是题材/结构保真度最高杠杆的一处。
#   ③ 分卷阶段上游把**新书总纲**也喂了进去,本仓原实现没有 —— 分卷与总纲各写各的,
#      卷与卷之间的承接关系就散了。
#
# 另:铁律第 2 条上游带「(如:压制→机遇→爆发→打脸→升级→更大压制……)」的功能序列
# 举例 —— 这个锚点让模型知道要复刻的是**节奏骨架**而非题材细节,一并补上。

IMITATE_RULES = """三条铁律:
1. **专名全换**:书名、全部人名、地名、势力名、功法/物品等专有名词必须全部自创,
   不得沿用原书任何专名;
2. **情节仿而不抄**:事件序列的「功能」必须与原书节拍一一对应
   (如:压制→机遇→爆发→打脸→升级→更大压制……),但每个具体事件的场景、冲突缘由、
   解决方式、爽点形式必须重新设计,不得复述原书任何具体桥段 —— 读者应感到
   「同一套拳法,打出了新招式」;
3. **结构与节奏保留**:叙事结构、人物配置与弧线、冲突线、爽点周期与文风
   **全部沿用原书骨架**。"""


def _profile_block(profile: dict) -> str:
    """原书档案的**标签化可读版块**(上游 profileBlock 同款)。

    刻意不 json.dumps 整坨:整坨 JSON 在模型眼里是「待转换的数据」,标签化逐行
    才是「要照着写的骨架」。这是上游保真度更高、桌面版此前差距最大的一处。
    """
    return "\n".join([
        f"原书题材:{profile.get('genre') or ''}",
        f"结构:{profile.get('book_structure') or ''}",
        f"世界观:{profile.get('worldview') or ''}",
        "核心人物:" + json.dumps(profile.get("main_characters") or [], ensure_ascii=False),
        "冲突线:" + json.dumps(profile.get("conflict_lines") or [], ensure_ascii=False),
        f"节奏模式:{profile.get('rhythm_patterns') or ''}",
        f"文风:{profile.get('style_features') or ''}",
    ])


SETTINGS_PROMPT = """你是一位网文主编。下面是一本书的「仿写档案」——请据此设计一本**全新**小说的书级设定。

{rules}

{profile_block}
原书共 {chapters} 章,新书 planned_chapters 应与之同量级。
{title_hint}

只输出 JSON:{{"title":"新书名","genre":"题材","description":"一句话简介,≤120字",
 "world":{{...}},"contract":{{...}},"characters":[...全用新名...],"planned_chapters":总章数整数}}
world/contract 完整 schema:world={{era,location,power_system,factions:[{{name,desc}}],note}};
contract={{pov:"third_limited|first|third_omniscient 之一",tones:[...],
 rules:["硬约束3-6条,含「所有角色沿用新名,不得出现原书专名」",
       "情节重设计纪律:按卷战略节拍推进,禁止复述原书具体桥段"],
 word_range:[1800,2600],note}}。
角色最多 12 个。"""

OUTLINE_PROMPT = """你是网文主编。基于下面的「新书设定」与「原书情节节拍时间线」,写新书的总纲。
要求:开篇/发展/高潮/结局的书级走向 + 情节主链概述,1500-3000 字;情节主链按节拍
时间线顺序映射,但每个具体事件全部重新设计,不得复述原书桥段 ——「同一套拳法,
打出新招式」。

{timeline}

【新书设定】
{settings}

只输出 JSON:{{"outline":"总纲正文,1500-3000字"}}"""

VOLUMES_PROMPT = """你是网文主编。基于「新书设定」「新书总纲」与「原书情节节拍时间线」,写新书的分卷战略。

输出 markdown:按节拍时间线分卷(每卷 30-80 章),每卷一小节:
### 第N卷 卷名(第X-Y章)
- 对应原书功能:<该卷承接原书哪段桥段的功能序列>
- 新书情节:<重新设计的具体事件链,100-200字,含本卷钩子与爽点>

{timeline}

【新书设定】
{settings}

【新书总纲】
{outline}

只输出 JSON:{{"volumes":"卷战略 markdown 全文"}}"""


def _timeline_digest(analysis: dict) -> str:
    """节拍时间线的仿写口径文本(原版格式):段号 + 章区间 + 梗概 + 节拍链。

    时间线必须进 outline 与 volumes 两个阶段(此前只进 volumes,总纲丢情节链映射,
    写出来的是「同题材新书」而不是「同骨架新书」)。"""
    tl = analysis.get("plot_timeline") or []
    if not tl:
        return "(无逐段节拍:仅按新书设定与结构做书级映射)"
    rows = []
    for i, t in enumerate(tl, 1):
        ch = t.get("chapters") or ["?", "?"]
        beats = " → ".join(str(b) for b in (t.get("beats") or []))
        rows.append(f"【原书第{ch[0]}-{ch[1]}章·段{i}】{t.get('summary') or ''}\n节拍:{beats}")
    return "【情节节拍时间线】\n" + "\n\n".join(rows)


def imitations_of(drama_id: int) -> list:
    """反查一本原著的全部仿写本(「一篇原著可仿成 N 本」的列表数据源)。

    不在原著 novel_meta 里维护正向列表 —— 那要在每次仿写成功后同步写回,
    半路失败/手工删库都会失真;直接扫 dramas.novel_meta 的 imitated_from 反查,
    永远以仿写本自己登记的出处为准(单一事实来源)。项目量级几十个,全扫无压力。
    返回 [{drama_id, title, at}] 按创建时间升序(第 1 本、第 2 本…)。
    """
    out = []
    for r in db.q("SELECT id, title, novel_meta, created_at FROM dramas "
                  "WHERE novel_meta LIKE '%imitated_from%'"):
        src = ((db.jload(r["novel_meta"], {}) or {}).get("imitated_from") or {})
        if src.get("drama_id") == drama_id:
            out.append({"drama_id": r["id"], "title": r["title"],
                        "at": r["created_at"] or ""})
    out.sort(key=lambda x: x["at"])
    return out


def run_imitation(drama_id: int, title: str = "", on_progress=None) -> dict:
    """四阶段仿写(settings→outline→volumes→creating),创建新项目。每阶段带重试。"""
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    analysis = (db.jload(d["novel_meta"], {}) or {}).get("analysis") or {}
    if analysis.get("status") != "done" or not _profile_has_content(analysis.get("profile")):
        raise RuntimeError("仿写档案为空或不可用,请先完成章节分析"
                           "(旧档案可能是空转产出的假档案,重跑一次「开始分析」即可)")
    profile_block = _profile_block(analysis["profile"])[:12000]
    timeline = _timeline_digest(analysis)
    # 仿写产出的是**新书**,但新书在建库时没有 language 字段可继承(见下方 INSERT),
    # 所以这里按被仿的源项目语言产出 —— 用户「拿一本 X 语的书仿一本」时期待的就是同语种。
    lang = config.resolve_content_language(drama_id)

    def stage(msg):
        if on_progress:
            on_progress(msg)

    def _ask(prompt: str):
        # 每阶段独立重试(原版 withRetry 同款):大 JSON 输出偶发截断,重试通常可解。
        # system 覆盖掉 workspace 的 novel_planner.md —— 那份提示写的是
        # 「只输出工具调用」,本仓没有工具,不覆盖模型就回工具调用 JSON(见 _PLANNER_SYSTEM)。
        return _with_retry(lambda: runner.run_agent_json(
            "novel_planner", prompt, temperature=0.4, lang=lang,
            system=_planner_system(lang)))

    # 1) settings
    stage("生成设定")
    # 用户指定书名时告诉模型「书名用这个,其余专名仍需自创」—— 上游同款。
    # 不说的话模型会连书名一起换掉,用户填的名字就白填了。
    title_hint = (f"用户指定新书名:{title}(书名用这个,其余专名仍需自创)"
                  if title else "新书名自拟(风格与原书一致但不重名)")
    try:
        raw = _ask(SETTINGS_PROMPT.format(rules=IMITATE_RULES, profile_block=profile_block,
                                          chapters=analysis.get("chapters") or "未知",
                                          title_hint=title_hint))
    except Exception as exc:
        raise RuntimeError(f"仿写设定阶段失败:{str(exc)[:200]}") from exc
    st = raw
    # 模型若直接回 JSON 数组,st.get 会抛 AttributeError('list' object has no
    # attribute 'get'),仿写任务以一句天书失败。明确报错让用户知道是输出格式问题、可重试。
    if not isinstance(st, dict):
        raise RuntimeError("设定阶段模型输出不是 JSON 对象,请重试仿写")
    # **工具调用不算数**:{"name":"save_novel_settings","arguments":{...}} 是合法 JSON,
    # 但里面没有书名/人物/世界观 —— 拿它当设定,建出来的是一本空壳书。
    if _is_tool_call(st):
        raise RuntimeError("模型返回的是工具调用而非设定内容,请重试仿写")
    try:
        planned_n = int(st.get("planned_chapters") or 0)
    except (TypeError, ValueError):
        planned_n = 0
    settings = {
        "title": title or st.get("title") or "未命名新书",
        "genre": st.get("genre", ""),
        "description": st.get("description", ""),
        "outline": "", "world": st.get("world", {}), "contract": st.get("contract", {}),
        "characters": (st.get("characters") or [])[:12],
        # 兜底链:模型输出 → 原书章数 → 100(原版同口径;此前兜底 1,漏字段就建出 1 章的书)
        "planned": max(1, min(999, planned_n or int(analysis.get("chapters") or 0) or 100)),
    }
    # 总纲/分卷阶段喂**完整**设定(含人物)。此前只喂 title/genre/description/world/
    # contract,人物名单缺席 —— 总纲里写不出与设定一致的角色,新书自己人与自己
    # 设定对不上。上游是整个 settings JSON 一起喂。
    settings_ctx = json.dumps({
        "title": settings["title"], "genre": settings["genre"],
        "description": settings["description"], "world": settings["world"],
        "contract": settings["contract"], "characters": settings["characters"],
        "planned_chapters": settings["planned"],
    }, ensure_ascii=False)

    # 2) outline
    stage("生成总纲")
    try:
        raw = _ask(OUTLINE_PROMPT.format(settings=settings_ctx, timeline=timeline))
    except Exception as exc:
        raise RuntimeError(f"仿写总纲阶段失败:{str(exc)[:200]}") from exc
    outline = ((raw.get("outline") or "") if isinstance(raw, dict) else "")[:8000]
    # 总纲空 → 明确失败,不建空壳书。上游同款(仿写总纲输出缺少 outline 即抛错):
    # 静默建出一本没总纲的新书,用户在向导里看不出哪里出了问题。
    if not outline.strip():
        raise RuntimeError("仿写总纲输出为空(模型输出被截断或格式不符),请重试仿写")

    # 3) volumes
    stage("生成分卷")
    # 分卷阶段必须带上**新书总纲**:上游是「设定 + 总纲 + 节拍时间线」三份一起喂。
    # 缺总纲时分卷与总纲各写各的,卷与卷之间的承接关系就散了(上游同款结构)。
    try:
        raw = _ask(VOLUMES_PROMPT.format(settings=settings_ctx, timeline=timeline,
                                         outline=outline))
    except Exception as exc:
        raise RuntimeError(f"仿写分卷阶段失败:{str(exc)[:200]}") from exc
    volumes = ((raw.get("volumes") or "") if isinstance(raw, dict) else "")[:12000]
    if not volumes.strip():
        raise RuntimeError("仿写分卷输出为空(模型输出被截断或格式不符),请重试仿写")

    # 4) creating
    stage("创建项目")
    ts = db.now()
    meta = {"world": settings["world"], "contract": settings["contract"],
            "chapter_count": settings["planned"],
            "imitated_from": {"drama_id": drama_id, "source_title": d["title"],
                              "analyzed_at": analysis.get("analyzed_at")}}
    new_id = db.ex("""INSERT INTO dramas(title,style,aspect_ratio,work_type,novel_outline,
                   novel_world,novel_contract,novel_volume,novel_chapters,total_episodes,
                   novel_meta,metadata,language,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (settings["title"], d["style"], d["aspect_ratio"], "novel", outline,
                   json.dumps(settings["world"], ensure_ascii=False),
                   json.dumps(settings["contract"], ensure_ascii=False),
                   volumes, "[]", settings["planned"],
                   json.dumps(meta, ensure_ascii=False),
                   json.dumps({"intro": settings["description"], "genre": settings["genre"]},
                              ensure_ascii=False),
                   lang, ts, ts))
    # 旧实现把 personality 当 appearance、identity 当 styling  语义就不对
    # (性格不是长相),长度也远低于出图规格。这里把 identity/personality/arc
    # 合并成"素材",交给软件层统一补写成可出图的 appearance + styling;
    # 一次批量调用,失败原样返回,不阻断建项目。
    seed = []
    for idx, c in enumerate(settings["characters"]):
        name = (c.get("name") or "").strip()
        if not name:
            continue
        material = "；".join(
            x for x in (c.get("identity"), c.get("personality"), c.get("arc")) if x)
        seed.append({"name": name,
                     "role": "lead" if idx == 0 else "supporting",
                     "appearance": material, "styling": ""})
    seed = character_spec.expand_many(seed, lang=lang)
    for idx, c in enumerate(seed):
        db.ex("""INSERT INTO characters(drama_id,name,role_type,appearance,styling,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
              (new_id, c["name"], "lead" if idx == 0 else "supporting",
               c.get("appearance") or "", c.get("styling") or "", ts, ts))
    db.ex("""INSERT INTO episodes(drama_id,episode_number,title,status,resolution,created_at,updated_at)
           VALUES(?,1,?,'pending','720p',?,?)""",
          (new_id, "第1集", ts, ts))
    return {"status": "done", "drama_id": new_id, "title": settings["title"],
            "planned_chapters": settings["planned"], "characters": len(settings["characters"])}


# ── 导入书的设定补齐(与仿写是两条路)──────────────────────────────────
#
# 仿写 = 拿这本书的骨架写一本**新书**(专名全换、情节重新设计,产出另一个项目);
# 设定补齐 = 项目里躺着的就是这本书的章节,把「项目设置/小说设定」**照原书总结**
# 出来 —— 简介/题材/总纲/世界观/合约/分卷描述的都是这本书本身。此前只有仿写
# 这条路,导入完设定栏全空,后续 AI 起草/写章对不上导入的内容(用户实测反馈
# 「导入后项目设置小说设定的功能不对,没有意义」)。
#
# 产物与「AI 起草」persist_draft 同构:novel_outline/novel_volume 存纯文本,
# novel_world/novel_contract 列存可读全文、结构化部分镜像进 novel_meta
# (写作门控读 meta["world"]/meta["contract"],叙事人称读 meta["contract"]["pov"])。
BOOK_SETTINGS_PROMPT = """你是资深网文策划。下面是一本小说的**结构分析档案**,请提炼这本书本身的设定。
这是「总结」不是「创作」:人名、地名、术语、情节一律照原书,不要改名,不要新造原书没有的设定。
档案:
{profile_block}
原书共 {chapters} 章。

输出 JSON:
{{"genre":"题材","description":"一句话简介≤120字",
 "world":{{"text":"完整世界观全文(照原书总结,不设字数上限)","structured":{{"era":"时代背景","location":"主要地点","power_system":"力量/能力体系","factions":[{{"name":"","desc":""}}],"note":""}}}},
 "contract":{{"text":"完整故事合约全文(照原书总结)","structured":{{"pov":"first|second|third_limited|third_omni","tones":["基调"],"rules":["该书叙事硬约束3-6条"],"word_range":[1800,2600],"note":""}}}},
 "characters":[{{"name":"","identity":"","personality":"","arc":"成长线"}}]}}
只输出 JSON。角色最多 12 个,只收原书里真实出现的主要角色。"""

BOOK_OUTLINE_PROMPT = """基于这本书的情节节拍时间线,写**这本书的全书总纲**(1500-3000 字):
按原书实际情节写 —— 起承转合、主线暗线、结局,全部照原书,不得另编结局或新增情节。
{settings}
{timeline}
只输出 JSON:{{"outline":"总纲正文"}}"""

BOOK_VOLUMES_PROMPT = """按情节节拍时间线给这本书划分卷册(每卷 30-80 章,按原书实际结构),markdown 格式:
### 第N卷 卷名(第X-Y章)
- 情节:本卷讲了什么(照原书)
- 关键事件:
{settings}
{timeline}
【全书总纲】
{outline}
只输出 JSON:{{"volumes":"markdown 正文"}}"""


def generate_book_settings(drama_id: int, on_progress=None) -> dict:
    """导入的书 → 本项目自己的小说设定(总纲/世界观/合约/分卷 + 简介/题材 + 主要角色)。

    前置:章节分析已完成(novel_meta.analysis.status == done)。三阶段
    settings→outline→volumes,每阶段独立重试(与 run_imitation 同款)。
    """
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    analysis = (db.jload(d["novel_meta"], {}) or {}).get("analysis") or {}
    if analysis.get("status") != "done" or not _profile_has_content(analysis.get("profile")):
        raise RuntimeError("仿写档案为空或不可用,请先完成章节分析"
                           "(旧档案可能是空转产出的假档案,重跑一次「开始分析」即可)")
    profile_block = _profile_block(analysis["profile"])[:12000]
    timeline = _timeline_digest(analysis)
    lang = config.resolve_content_language(drama_id)

    def stage(msg):
        if on_progress:
            on_progress(msg)

    def _ask(prompt: str):
        return _with_retry(lambda: runner.run_agent_json(
            "novel_planner", prompt, temperature=0.3, lang=lang,
            system=_planner_system(lang)))

    stage("提炼设定")
    raw = _ask(BOOK_SETTINGS_PROMPT.format(
        profile_block=profile_block, chapters=analysis.get("chapters") or "未知"))
    st = raw
    if not isinstance(st, dict):
        raise RuntimeError("设定阶段模型输出不是 JSON 对象,请重试")
    if _is_tool_call(st):
        raise RuntimeError("模型返回的是工具调用而非设定内容,请重试")
    world = st.get("world") or {}
    contract = st.get("contract") or {}
    # text 缺失时退回结构化的 JSON 文本 —— 列里空着比塞一段 JSON 更难看,
    # 但「有内容」优先:结构化字段至少给写作门控与用户一个可改的起点。
    world_text = (str(world.get("text") or "").strip()
                  or json.dumps(world.get("structured") or {}, ensure_ascii=False))
    contract_text = (str(contract.get("text") or "").strip()
                     or json.dumps(contract.get("structured") or {}, ensure_ascii=False))
    genre = str(st.get("genre") or "").strip()
    desc = str(st.get("description") or "").strip()
    settings_ctx = json.dumps({"genre": genre, "description": desc,
                               "world": world.get("structured") or {},
                               "contract": contract.get("structured") or {}},
                              ensure_ascii=False)

    def _ask_field(prompt: str, field: str) -> str:
        """取某个长文本字段,最多 3 次,全空返回 ""。

        **只跑一层重试**:外层 3 次 × _with_retry 内层 3 次 = 9 次调用,
        一次总纲就是 1500-3000 字,9 次太贵。这里自己管重试,单层 3 次封顶。
        """
        for attempt in range(3):
            try:
                data = runner.run_agent_json(
                    "novel_planner", prompt, temperature=0.3, lang=lang,
                    system=_planner_system(lang))
            except Exception as exc:  # noqa: BLE001 —— 解析失败也算「这一轮空」
                log.warning("book_settings.%s.empty drama=%s attempt=%s err=%s",
                            field, drama_id, attempt + 1, str(exc)[:160])
                continue
            val = str(data.get(field) or "").strip() if isinstance(data, dict) else ""
            if val:
                return val
            log.warning("book_settings.%s.empty drama=%s attempt=%s 无 %s 字段",
                        field, drama_id, attempt + 1, field)
        return ""

    stage("生成总纲")
    # 总纲是**最容易空转**的一段:模型多半直接回大段散文,把 JSON 结构吃掉,
    # 解析不出 "outline" 就静默拿到空串 —— 此前照写空串,任务报完成、总纲栏空白,
    # 用户以为整个设定都没生成(2026-11-01 实测)。
    # 修:重试 3 次;仍空则记入 missing 明确上报,绝不静默。
    outline = _ask_field(
        BOOK_OUTLINE_PROMPT.format(settings=settings_ctx, timeline=timeline),
        "outline")[:8000]

    stage("生成分卷")
    # 分卷带上刚生成的总纲:卷与卷的承接关系要跟总纲对得上(上游仿写侧同款结构)
    volumes = _ask_field(
        BOOK_VOLUMES_PROMPT.format(settings=settings_ctx, timeline=timeline,
                                   outline=outline),
        "volumes")[:12000]

    stage("写入项目")
    ts = db.now()
    db.ex("""UPDATE dramas SET novel_outline=?, novel_world=?, novel_contract=?,
             novel_volume=?, updated_at=? WHERE id=?""",
          (outline, world_text, contract_text, volumes, ts, drama_id))
    # 结构化镜像(persist_draft 同款):写作门控读 meta["world"]/meta["contract"]
    meta = db.jload(d["novel_meta"], {}) or {}
    if isinstance(world.get("structured"), dict) and world["structured"]:
        meta["world"] = world["structured"]
    if isinstance(contract.get("structured"), dict) and contract["structured"]:
        meta["contract"] = contract["structured"]
    meta["book_settings_at"] = ts
    db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), ts, drama_id))
    # 简介/题材合并进 metadata —— 与「项目说明」共用 meta["intro"]/meta["genre"]
    # 槽位(extractor / AI 起草 / 写章上下文都按这两个键读),不另开新列。
    md = db.jload(d["metadata"], {}) or {}
    if genre:
        md["genre"] = genre
    if desc:
        md["intro"] = desc
    db.ex("UPDATE dramas SET metadata=? WHERE id=?",
          (json.dumps(md, ensure_ascii=False), drama_id))
    # 主要角色入资产(只补缺:重复导入/重跑不插重复行 —— 角色行是用户可编辑
    # 的资产,覆盖会毁掉用户改过的样貌/妆造)
    have = db.q1("SELECT COUNT(*) AS n FROM characters WHERE drama_id=? AND deleted_at IS NULL",
                 (drama_id,))
    inserted = 0
    if have and int(have["n"] or 0) == 0:
        seed = []
        for idx, c in enumerate(st.get("characters") or []):
            name = str(c.get("name") or "").strip()
            if not name:
                continue
            material = "；".join(
                x for x in (c.get("identity"), c.get("personality"), c.get("arc")) if x)
            seed.append({"name": name, "role": "lead" if idx == 0 else "supporting",
                         "appearance": material, "styling": ""})
        seed = character_spec.expand_many(seed, lang=lang)
        for idx, c in enumerate(seed):
            db.ex("""INSERT INTO characters(drama_id,name,role_type,appearance,styling,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)""",
                  (drama_id, c["name"], "lead" if idx == 0 else "supporting",
                   c.get("appearance") or "", c.get("styling") or "", ts, ts))
            inserted += 1
    missing = [name for name, v in (("总纲", outline), ("分卷", volumes)) if not v]
    log.info("book_settings.done drama=%s outline=%d volumes=%d chars=%d missing=%s",
             drama_id, len(outline), len(volumes), inserted, missing or "无")
    return {"outline": len(outline), "volumes": len(volumes), "characters": inserted,
            "missing": missing}


META_PROMPT = """提炼下面这部作品的项目信息,输出 JSON:

{"genre":"题材,2-6字,例 都市情感 / 仙侠 / 悬疑",
 "description":"项目简介,60-120字,概括题材、主角身份、核心冲突与基调",
 "creative_description":"创意描述,100-300字,具体到「谁在什么境遇下获得/遭遇了什么、由此开启什么主线、核心爽点方向」,陈述句,不写空话"}
只输出 JSON。题材要具体到能指导后续 AI 生成分镜与画面,不要写「都市」这种过宽的词。"""

META_FIELDS = ("genre", "description", "creative_description")


def generate_book_meta(drama_id: int, title: str = "", creative: str = "") -> dict:
    """提炼简介/题材/创意(不落库,由前端确认后保存)。

    素材优先级:前 3 章正文采样(各取头 3500 + 尾 1000,原版口径 —— 只看第 1 章
    开头会漏掉题材信息常常靠后铺垫的书)→ 创意描述 → 项目名称。
    三个来源都为空时抛出可读错误,不静默返回空。

    字数口径对齐上游 generate-book-meta(description 60-120 字 / creative 100-300 字
    / genre 2-6 字):此前桌面版写的是 ≤60 / ≤150 字,简介太短撑不起「给 AI 提供
    全书语境」的作用。

    重试口径对齐上游 withRetry:大段 JSON 输出偶发截断/空转,重试通常可解。
    字段齐全性也照上游 askConceptJson 的路子校验 —— 模型偶尔回一个字段完全不对的
    合法 JSON,缺字段就带更严格的格式要求重来一次,而不是让用户对着空框发呆。
    """
    parts = []
    rows = db.q("""SELECT content FROM episodes WHERE drama_id=? AND content IS NOT NULL
                   AND content!='' ORDER BY episode_number LIMIT 3""", (drama_id,))
    samples = []
    for r in rows:
        t = (r["content"] or "").strip()
        if len(t) <= 100:                      # 不足 100 字的章当噪声跳过(原版同口径)
            continue
        samples.append(t[:3500] + "\n……（中段略）……\n" + t[-1000:] if len(t) > 4500 else t)
    if samples:
        parts.append("【开头节选】\n" + "\n\n".join(samples))
    if (creative or "").strip():
        parts.append(f"【创意描述】\n{creative.strip()[:1500]}")
    if title:
        parts.append(f"【项目名称】{title}")
    if not parts:
        raise RuntimeError("没有可参考的素材:请先填写项目名称或创意描述,或先导入正文")

    strict = "\n".join([
        "",
        "【格式要求(本次必须严格遵守)】",
        "- 只输出一个 JSON 对象,不要任何解释、前后缀文字或 markdown 代码块。",
        "- 每个字段的值必须写在同一行内,值里面不要出现换行符。",
        "- 必须且只能包含这几个键:" + "、".join(META_FIELDS) + "。",
        "",
    ])
    lang = config.resolve_content_language(drama_id)
    last_err: Exception | None = None
    for attempt in range(2):
        prompt = "\n".join(parts) + "\n\n" + META_PROMPT
        if attempt:
            prompt += strict
        try:
            # run_agent_json + fields 兜底:JSON 彻底解析不出来时逐字段抠,
            # 宁可给残缺结果别让用户白等(上游 askConceptJson 同款)。
            data = _with_retry(lambda p=prompt: runner.run_agent_json(
                "novel_planner", p, temperature=0.3, lang=lang,
                system=_planner_system(lang), fields=list(META_FIELDS)))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue
        if not isinstance(data, dict):
            last_err = RuntimeError("模型输出无法解析为 JSON")
            continue
        missing = [f for f in META_FIELDS if not str(data.get(f) or "").strip()]
        if missing:
            last_err = RuntimeError("模型输出缺少字段:" + "、".join(missing))
            continue
        return {k: data.get(k) for k in META_FIELDS}
    raise last_err or RuntimeError("AI 起草简介失败,请重试")
