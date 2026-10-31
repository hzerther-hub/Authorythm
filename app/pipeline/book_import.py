"""导入整本书 → 分析 → 仿写 三段式流水线(对齐原版 2df744b)。

导入:仅 TXT(支持 UTF-8/UTF-16/GBK/GB18030/Big5),三级切章,软删旧章节后批量插入。
分析:12 章一组 → 文本模型抽取(summary/beats/characters/settings/hooks),3 worker 并发
      (被限流暂停过则降档 3→2→1),单组重试 3 次(2s→6s 退避);失败率≥30% 且已跑≥50 组
      → 暂停(避免基于残缺数据出错误档案);重跑自动跳过已成功组(断点续跑)。
仿写:四阶段(settings→outline→volumes→creating),三条铁律(专名全换/情节仿而不抄/结构保留)。
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from ..agents import runner
from ..core import config, db
from ..core.logging_setup import get_logger
from . import character_spec

log = get_logger(__name__)

MIN_CHARS = 1000
MAX_CHARS = 100_000_000
GROUP = 12                 # 每组章数
SAMPLE_HEAD = 6000
SAMPLE_TAIL = 2500
GROUP_CHAR_LIMIT = 9000
FAIL_THRESHOLD = 0.30      # 失败率阈值
FAIL_MIN_SAMPLES = 50      # 触发暂停的最小样本数

CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:第\s*[0-9零一二两三四五六七八九十百千万]+\s*[章回节][^\n]{0,40}|楔子|序章|引子|番外)[^\n]{0,40}\s*$")
SEPARATOR_RE = re.compile(r"^[-_=*~—·]{4,}\s*$")
TITLE_STOPWORDS = {"正文", "目录", "序", "完", "全文完", "未完待续", "公告", "上架感言"}
# 章标题正则的最少命中数:原版是 3 —— 有 3 个「第N章」就按标题切。
# 此前写死 32,短书(3-31 章)全部掉进兜底被 2 万字窗口切碎,章节结构直接丢失。
MIN_HEADING_HITS = 3


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
                encoding: str = "") -> dict:
    """导入整本书并切章入库(软删旧章节 + 每批 100 行插入,避开 SQLite 变量上限)。"""
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
    # 软删全部既有章节(含建项时自动建的空第 1 集)及其分镜
    for ep in db.q("SELECT id FROM episodes WHERE drama_id=?", (drama_id,)):
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
        names = []
        for c in d.get("characters") or []:
            if not isinstance(c, dict):
                continue
            names.append("{},{}".format(c.get("name") or "", c.get("identity") or ""))
        return "、".join(n for n in names if n.strip(","))

    parts = []
    for i, d in enumerate(digests, 1):
        parts.append("【段{}】{}\n人物:{}\n设定:{}\n节奏:{}".format(
            i, d.get("summary") or "", _chars_line(d),
            d.get("settings") or "", d.get("hooks") or ""))
    return "\n\n".join(parts)


def run_analysis(drama_id: int, on_progress=None, stop_check=None, resume: bool = False) -> dict:
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
    pause_count = int(prev_analysis.get("pause_count") or 0)
    # 断点续跑:预填已成功组;冷却期检查(原版同参数,给上游配额喘息时间)
    chunk_summaries = [None] * len(groups)
    if resume:
        if prev_analysis.get("status") != "paused":
            raise RuntimeError("当前没有可恢复的暂停分析")
        last_paused = str(prev_analysis.get("paused_at") or "")
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
            log.info(f"[analyze] 断点续跑:跳过已成功 {skipped}/{len(groups)} 组")

    # 并发档位按 pause_count 动态降档(原版:0→3,1→2,≥2→1),错峰同步加大
    concurrency = 3 if pause_count == 0 else 2 if pause_count == 1 else 1
    stagger_s = 1.0 if pause_count == 0 else 2.0 if pause_count == 1 else 3.0

    import threading
    lock = threading.Lock()
    cursor = {"i": 0}
    state = {"done": 0, "failed": 0, "aborted": False}
    failed_indexes = []

    def _report():
        if on_progress:
            on_progress(state["done"], state["done"] + state["failed"],
                        f"第{min(state['done'] + state['failed'], len(groups))} 组")

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
                data = _with_retry(lambda seg=seg: runner.extract_json(
                    runner.run_agent("novel_reviewer",
                                     f"{_segment_digest(seg)}\n\n{MAP_PROMPT}",
                                     temperature=0.2, lang=lang)) or {})
                with lock:
                    chunk_summaries[idx] = {
                        "chapters": [seg[0][0], seg[-1][0]],
                        "summary": str(data.get("summary") or ""),
                        "beats": [str(x) for x in (data.get("beats") or [])][:6],
                        "characters": data.get("characters") or [],
                        "settings": str(data.get("settings") or ""),
                        "hooks": str(data.get("hooks") or "")}
                    state["done"] += 1
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
    raw = runner.run_agent("novel_reviewer",
                           f"{_reduce_digest(ok)}\n\n{REDUCE_PROMPT}", temperature=0.2,
                           lang=lang)
    profile = runner.extract_json(raw) or {}
    # plot_timeline 落库前剥掉 _seg/_ok 内部标记(resume 用的,不属于档案数据)
    timeline_clean = [{k: v for k, v in c.items() if not k.startswith("_")}
                      for c in ok]
    _persist({"status": "done", "chapters": len(chapters), "profile": profile,
              "plot_timeline": timeline_clean, "chunk_count": len(groups),
              "analyzed_at": db.now()})
    return {"status": "done", "chapters": len(chapters), "profile": profile}


# ═══ 3) 仿写 ═══
IMITATE_RULES = """严格遵守三条铁律:
1. **专名全换**:书名、人名、地名、势力名、功法物品名必须全部重新起名;
2. **情节仿而不抄**:事件的"功能"一一对应(原书这里是什么作用),但具体事件、场景、冲突、解决方式、爽点全部重新设计 —— 同一套拳法,打出新招式;
3. **结构与节奏保留**:分卷节奏、章节密度、爽点间隔沿用原书节拍时间线。"""

SETTINGS_PROMPT = """你是资深网文策划。基于下面的原书仿写档案,创作一部**全新**小说的设定。
{rules}
原书档案: {profile}
原书共 {chapters} 章,新书 planned_chapters 应与之同量级。

输出 JSON:
{{"title":"新书名","genre":"题材","description":"一句话简介≤120字",
 "world":{{"era":"时代背景","location":"主要舞台","power_system":"力量体系","factions":[{{"name":"","desc":""}}],"note":""}},
 "contract":{{"pov":"third_limited|first|third_omniscient","tones":["基调"],"rules":["规则3-6条"],"word_range":[1800,2600],"note":""}},
 "characters":[{{"name":"","identity":"","personality":"","arc":"成长线"}}],"planned_chapters":60}}
只输出 JSON。角色最多 12 个。"""

OUTLINE_PROMPT = """基于已确定的新书设定与原书情节节拍时间线,写一份 1500-3000 字的总纲
(有起承转合、有主线有暗线、结局明确)。情节主链按节拍时间线顺序映射,但每个具体事件
全部重新设计,不得复述原书桥段 —— 同一套拳法,打出新招式。
{settings}
{timeline}
只输出 JSON:{{"outline":"总纲正文"}}"""

VOLUMES_PROMPT = """按节拍时间线把新书分卷(每卷 30-80 章),格式:
### 第N卷 卷名(第X-Y章)
- 对应原书功能:
- 新书情节:
{settings}
{timeline}
只输出 JSON:{{"volumes":"markdown 正文"}}"""


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
    if analysis.get("status") != "done" or not analysis.get("profile"):
        raise RuntimeError("请先完成章节分析")
    profile = json.dumps(analysis["profile"], ensure_ascii=False)[:12000]
    timeline = _timeline_digest(analysis)
    # 仿写产出的是**新书**,但新书在建库时没有 language 字段可继承(见下方 INSERT),
    # 所以这里按被仿的源项目语言产出 —— 用户「拿一本 X 语的书仿一本」时期待的就是同语种。
    lang = config.resolve_content_language(drama_id)

    def stage(msg):
        if on_progress:
            on_progress(msg)

    def _ask(prompt: str):
        # 每阶段独立重试(原版 withRetry 同款):大 JSON 输出偶发截断,重试通常可解
        return _with_retry(lambda: runner.run_agent(
            "novel_planner", prompt, temperature=0.4, lang=lang))

    # 1) settings
    stage("生成设定")
    raw = _ask(SETTINGS_PROMPT.format(rules=IMITATE_RULES, profile=profile,
                                      chapters=analysis.get("chapters") or "未知"))
    st = runner.extract_json(raw) or {}
    # `or {}` 只兜得住 None(解析失败→默认值,既有行为);模型若直接回 JSON
    # 数组,st.get 会抛 AttributeError('list' object has no attribute 'get'),
    # 仿写任务以一句天书失败。明确报错让用户知道是输出格式问题、可重试。
    if not isinstance(st, dict):
        raise RuntimeError("设定阶段模型输出不是 JSON 对象,请重试仿写")
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
    settings_ctx = json.dumps({k: settings[k] for k in
                               ("title", "genre", "description", "world", "contract")},
                              ensure_ascii=False)

    # 2) outline
    stage("生成总纲")
    raw = _ask(OUTLINE_PROMPT.format(rules=IMITATE_RULES, settings=settings_ctx,
                                     timeline=timeline))
    outline = ((runner.extract_json(raw) or {}).get("outline") or "")[:8000]

    # 3) volumes
    stage("生成分卷")
    raw = _ask(VOLUMES_PROMPT.format(rules=IMITATE_RULES, settings=settings_ctx,
                                     timeline=timeline))
    volumes = ((runner.extract_json(raw) or {}).get("volumes") or "")[:12000]

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


META_PROMPT = """提炼下面这部作品的项目信息,输出 JSON:
{"genre":"题材,2-8字,例 都市情感 / 仙侠 / 悬疑",
 "description":"一句话简介,≤60字,点出主角+处境+核心冲突",
 "creative_description":"故事是什么,2-3句,≤150字,写清主线与结局走向"}
只输出 JSON。题材要具体到能指导后续 AI 生成分镜与画面,不要写「都市」这种过宽的词。"""


def generate_book_meta(drama_id: int, title: str = "", creative: str = "") -> dict:
    """提炼简介/题材/创意(不落库,由前端确认后保存)。

    素材优先级:前 3 章正文采样(各取头 3500 + 尾 1000,原版口径 —— 只看第 1 章
    开头会漏掉题材信息常常靠后铺垫的书)→ 创意描述 → 项目名称。
    三个来源都为空时抛出可读错误,不静默返回空。
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
    raw = runner.run_agent("novel_planner", "\n".join(parts) + "\n\n" + META_PROMPT,
                           temperature=0.3,
                           lang=config.resolve_content_language(drama_id))
    return runner.extract_json(raw) or {}
