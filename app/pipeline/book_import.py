# -*- coding: utf-8 -*-
"""导入整本书 → 分析 → 仿写 三段式流水线(对齐原版 2df744b)。

导入:仅 TXT(支持 UTF-8/UTF-16/GBK/GB18030/Big5),三级切章,软删旧章节后批量插入。
分析:12 章一组 → 文本模型抽取(summary/beats/characters/settings/hooks),
      失败率≥30% 且已跑≥50 组 → 暂停(避免基于残缺数据出错误档案);最后 Reduce 出仿写档案。
仿写:四阶段(settings→outline→volumes→creating),三条铁律(专名全换/情节仿而不抄/结构保留)。
"""
from __future__ import annotations

import json
import re

from ..agents import runner
from ..core import db

from . import character_spec

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


# ═══ 1) 导入 ═══
def bytes_to_utf8(data: bytes, hint: str = "") -> str:
    """编码判定:显式优先;自动则 UTF-8 试解,否则 gbk → gb18030 → big5。"""
    if hint:
        try:
            return data.decode(hint, errors="replace")
        except LookupError:
            pass
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    for enc in ("gbk", "gb18030", "big5"):
        try:
            return data.decode(enc, errors="replace")
        except Exception:  # noqa: BLE001
            continue
    return data.decode("utf-8", errors="replace")


def _looks_like_title(line: str) -> bool:
    t = line.strip()
    if not t or len(t) > 40:
        return False
    if t in TITLE_STOPWORDS:
        return False
    return not re.search(r"[。!！?？…,.，]$", t)


def split_book_into_chapters(text: str) -> list:
    """三级切章:章标题正则 → 分隔线+启发式 → 2 万字窗口兜底。"""
    lines = text.split("\n")
    # 1) 章标题正则(行长≤48 且命中≥32)
    hits = [i for i, l in enumerate(lines)
            if len(l.strip()) <= 48 and CHAPTER_HEADING_RE.match(l)]
    if len(hits) >= 32:
        chapters = []
        for k, start in enumerate(hits):
            end = hits[k + 1] if k + 1 < len(hits) else len(lines)
            body = "\n".join(lines[start + 1:end]).strip()
            if len(body) >= 20:
                chapters.append((lines[start].strip()[:120], body))
        if chapters:
            return chapters
    # 2) 分隔线 + 启发式标题
    marks = []
    for i, l in enumerate(lines):
        if SEPARATOR_RE.match(l.strip()) and i > 0 and _looks_like_title(lines[i - 1]):
            marks.append(i - 1)
    if marks:
        chapters = []
        for k, start in enumerate(marks):
            end = marks[k + 1] if k + 1 < len(marks) else len(lines)
            body = "\n".join(lines[start + 1:end]).strip()
            if len(body) >= 20:
                chapters.append((lines[start].strip()[:120], body))
        if chapters:
            return chapters
    # 3) 兜底:2 万字窗口
    chapters = []
    step = 20000
    for k, start in enumerate(range(0, len(text), step)):
        seg = text[start:start + step].strip()
        if len(seg) >= 200:
            chapters.append((f"片段 {k + 1}", seg))
    return chapters


def import_book(drama_id: int, data: bytes = None, text: str = "",
                encoding: str = "") -> dict:
    """导入整本书并切章入库(软删旧章节 + 每批 100 行插入,避开 SQLite 变量上限)。"""
    if data is not None:
        content = bytes_to_utf8(data, encoding)
    elif text:
        content = text
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
    return {"chapters": len(chapters), "total_chars": n}


# ═══ 2) 分析 ═══
MAP_PROMPT = """你是长篇小说结构分析师。下面给出连续若干章的正文节选,请输出 JSON:
{"summary":"≤200字 章节梗概","beats":["关键情节3-6条,每条≤40字,写清谁在什么冲突下做了什么、结果如何"],
"characters":[{"name":"","identity":"","personality":""}],"settings":"世界观要素≤100字","hooks":"节奏与钩子手法≤100字"}
只输出 JSON。beats 是后续仿写情节链的原料,请务必具体。"""

REDUCE_PROMPT = """你是小说结构总编。下面是全书各段的节拍摘要,请输出**仿写档案** JSON:
{"genre":"题材","book_structure":"全书结构≤300字","main_characters":[{"name","identity","personality","arc"}],
"worldview":"世界观≤300字","conflict_lines":["冲突线3-5条"],"rhythm_patterns":"节奏模式≤200字","style_features":"文风特征≤150字"}
只输出 JSON。"""


def _segment_digest(chapters: list) -> str:
    parts, total = [], 0
    for num, body in chapters:
        piece = f"【第{num}章】\n{body}"
        parts.append(piece)
        total += len(piece)
        if total > SAMPLE_HEAD:
            break
    joined = "\n".join(parts)
    if len(joined) > GROUP_CHAR_LIMIT:                # 抽样:头 6000 + 尾 2500
        joined = joined[:SAMPLE_HEAD] + "\n……（中段略）……\n" + joined[-SAMPLE_TAIL:]
    return joined


def run_analysis(drama_id: int, on_progress=None, stop_check=None) -> dict:
    """Map → Reduce:产出仿写档案落 novel_meta.analysis。失败率过高自动暂停。"""
    eps = db.q("SELECT episode_number, content FROM episodes WHERE drama_id=? "
               "ORDER BY episode_number", (drama_id,))
    chapters = [(r["episode_number"], r["content"] or "") for r in eps if (r["content"] or "").strip()]
    if not chapters:
        raise RuntimeError("没有可分析的章节正文")
    digests, failed, total = [], 0, 0
    for i in range(0, len(chapters), GROUP):
        if stop_check and stop_check():
            break
        seg = chapters[i:i + GROUP]
        total += 1
        try:
            raw = runner.run_agent("novel_reviewer",
                               f"{_segment_digest(seg)}\n\n{MAP_PROMPT}", temperature=0.2)
            data = runner.extract_json(raw) or {}
            digests.append({"chapters": [seg[0][0], seg[-1][0]],
                            "summary": data.get("summary", ""),
                            "beats": data.get("beats", []),
                            "characters": data.get("characters", []),
                            "settings": data.get("settings", ""),
                            "hooks": data.get("hooks", "")})
        except Exception:  # noqa: BLE001
            failed += 1
        if on_progress:
            on_progress(total - failed, total, f"第{i + 1}-{seg[-1][0]}章")
        # 安全阀:失败率≥30% 且样本≥50 → 暂停,不跑 Reduce(避免残缺数据出错误档案)
        if total >= FAIL_MIN_SAMPLES and failed / total >= FAIL_THRESHOLD:
            d = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
            meta = db.jload(d["novel_meta"], {}) if d else {}
            meta["analysis"] = {"status": "paused", "chapters": len(chapters),
                                "partial_chunks": digests, "failed": failed, "total": total}
            db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
                  (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
            return {"status": "paused", "done": total - failed, "total": total, "failed": failed}
    # Reduce
    timeline = json.dumps(digests, ensure_ascii=False)[:24000]
    raw = runner.run_agent("novel_reviewer",
                           f"全书节拍时间线:\n{timeline}\n\n{REDUCE_PROMPT}", temperature=0.2)
    profile = runner.extract_json(raw) or {}
    d = db.q1("SELECT novel_meta FROM dramas WHERE id=?", (drama_id,))
    meta = db.jload(d["novel_meta"], {}) if d else {}
    meta["analysis"] = {"status": "done", "chapters": len(chapters), "profile": profile,
                        "plot_timeline": digests, "chunk_count": total,
                        "analyzed_at": db.now()}
    db.ex("UPDATE dramas SET novel_meta=?, updated_at=? WHERE id=?",
          (json.dumps(meta, ensure_ascii=False), db.now(), drama_id))
    return {"status": "done", "chapters": len(chapters), "profile": profile}


# ═══ 3) 仿写 ═══
IMITATE_RULES = """严格遵守三条铁律:
1. **专名全换**:书名、人名、地名、势力名、功法物品名必须全部重新起名;
2. **情节仿而不抄**:事件的"功能"一一对应(原书这里是什么作用),但具体事件、场景、冲突、解决方式、爽点全部重新设计 —— 同一套拳法,打出新招式;
3. **结构与节奏保留**:分卷节奏、章节密度、爽点间隔沿用原书节拍时间线。"""

SETTINGS_PROMPT = """你是资深网文策划。基于下面的原书仿写档案,创作一部**全新**小说的设定。
{rules}
原书档案: {profile}

输出 JSON:
{{"title":"新书名","genre":"题材","description":"一句话简介≤120字",
 "world":{{"era":"时代背景","location":"主要舞台","power_system":"力量体系","factions":[{{"name":"","desc":""}}],"note":""}},
 "contract":{{"pov":"third_limited|first|third_omniscient","tones":["基调"],"rules":["规则3-6条"],"word_range":[1800,2600],"note":""}},
 "characters":[{{"name":"","identity":"","personality":"","arc":"成长线"}}],"planned_chapters":60}}
只输出 JSON。角色最多 12 个。"""

OUTLINE_PROMPT = """基于已确定的新书设定,写一份 1500-3000 字的总纲(有起承转合、有主线有暗线、结局明确)。
{settings}
只输出 JSON:{{"outline":"总纲正文"}}"""

VOLUMES_PROMPT = """按节拍时间线把新书分卷(每卷 30-80 章),格式:
### 第N卷 卷名(第X-Y章)
- 对应原书功能:
- 新书情节:
{settings}
只输出 JSON:{{"volumes":"markdown 正文"}}"""


def run_imitation(drama_id: int, title: str = "", on_progress=None) -> dict:
    """四阶段仿写(settings→outline→volumes→creating),创建新项目。"""
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    analysis = (db.jload(d["novel_meta"], {}) or {}).get("analysis") or {}
    if analysis.get("status") != "done" or not analysis.get("profile"):
        raise RuntimeError("请先完成章节分析")
    profile = json.dumps(analysis["profile"], ensure_ascii=False)[:12000]
    timeline = json.dumps(analysis.get("plot_timeline", []), ensure_ascii=False)[:8000]

    def stage(msg):
        if on_progress:
            on_progress(msg)

    # 1) settings
    stage("生成设定")
    raw = runner.run_agent("novel_planner",
                           SETTINGS_PROMPT.format(rules=IMITATE_RULES, profile=profile),
                           temperature=0.4)
    st = runner.extract_json(raw) or {}
    settings = {
        "title": title or st.get("title") or "未命名新书",
        "genre": st.get("genre", ""),
        "description": st.get("description", ""),
        "outline": "", "world": st.get("world", {}), "contract": st.get("contract", {}),
        "characters": (st.get("characters") or [])[:12],
        "planned": max(1, min(999, int(st.get("planned_chapters") or 1))),
    }
    settings_ctx = json.dumps({k: settings[k] for k in
                               ("title", "genre", "description", "world", "contract")},
                              ensure_ascii=False)

    # 2) outline
    stage("生成总纲")
    raw = runner.run_agent("novel_planner",
                           OUTLINE_PROMPT.format(rules=IMITATE_RULES, settings=settings_ctx),
                           temperature=0.4)
    outline = ((runner.extract_json(raw) or {}).get("outline") or "")[:8000]

    # 3) volumes
    stage("生成分卷")
    raw = runner.run_agent("novel_planner",
                           VOLUMES_PROMPT.format(rules=IMITATE_RULES,
                                                settings=settings_ctx + "\n节拍时间线:" + timeline),
                           temperature=0.4)
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
                   novel_meta,metadata,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (settings["title"], d["style"], d["aspect_ratio"], "novel", outline,
                   json.dumps(settings["world"], ensure_ascii=False),
                   json.dumps(settings["contract"], ensure_ascii=False),
                   volumes, "[]", settings["planned"],
                   json.dumps(meta, ensure_ascii=False),
                   json.dumps({"intro": settings["description"], "genre": settings["genre"]},
                              ensure_ascii=False),
                   ts, ts))
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
    seed = character_spec.expand_many(
        seed, lang=db.get_setting("content_language", "zh"))
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

    素材优先级:已导入的首章正文 → 创意描述 → 项目名称。
    三个来源都为空时抛出可读错误,不静默返回空。
    """
    parts = []
    first = db.q1("""SELECT content FROM episodes WHERE drama_id=? AND content IS NOT NULL
                     AND content!='' ORDER BY episode_number LIMIT 1""", (drama_id,))
    body = ((first or {}).get("content") or "")[:3000]
    if body:
        parts.append(f"【作品开头】\n{body}")
    if (creative or "").strip():
        parts.append(f"【创意描述】\n{creative.strip()[:1500]}")
    if title:
        parts.append(f"【项目名称】{title}")
    if not parts:
        raise RuntimeError("没有可参考的素材:请先填写项目名称或创意描述,或先导入正文")
    raw = runner.run_agent("novel_planner", "\n".join(parts) + "\n\n" + META_PROMPT, temperature=0.3)
    return runner.extract_json(raw) or {}
