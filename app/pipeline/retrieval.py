# -*- coding: utf-8 -*-
"""FTS5 前文检索(零新依赖):建索引/搜索/注入写作提示词。

BGE 向量升级路径:本模块预留 Embedder 接口;若检测到 onnxruntime + 本地
BGE 模型文件,可加向量通道(本期只实现 FTS5 trigram,零新依赖)。
"""
from __future__ import annotations

import json
import re

from ..core import db

_MIN_QUERY = 3          # trigram 至少 3 字才能 MATCH
_SNIPPET_LEN = 24       # snippet 前后 token 数
_TOKENS = "tokenize='trigram'"


def _table(drama_id: int) -> str:
    return f"novel_fts_{drama_id}"


def _version_key(drama_id: int) -> str:
    return f"yihao.fts_version.{drama_id}"


def _content_stamp(drama_id: int) -> str:
    """章节内容版本戳:任一章正文/标题变化都会变(重建索引用)。"""
    row = db.q1("SELECT COUNT(*) c, SUM(length(coalesce(content,''))+length(coalesce(title,''))) s, "
                "MAX(updated_at) m FROM episodes WHERE drama_id=?", (drama_id,))
    row = row or {}
    return f"{row.get('c') or 0}:{row.get('s') or 0}:{row.get('m') or ''}"


def ensure_index(drama_id: int, force: bool = False) -> bool:
    """建/重建该书的 FTS 索引。内容版本戳没变则跳过(懒重建)。失败返回 False。"""
    try:
        stamp = _content_stamp(drama_id)
        if not force and db.get_setting(_version_key(drama_id), "") == stamp:
            return True
        name = _table(drama_id)
        db.ex(f"DROP TABLE IF EXISTS {name}")
        db.ex(f"CREATE VIRTUAL TABLE {name} USING fts5(episode_id UNINDEXED, title, body, {_TOKENS})")
        eps = db.q("SELECT id, episode_number, title, content FROM episodes "
                   "WHERE drama_id=? ORDER BY episode_number", (drama_id,))
        for r in eps:
            body = " ".join((r["content"] or "").split())
            db.ex(f"INSERT INTO {name}(episode_id, title, body) VALUES(?,?,?)",
                  (r["id"], r["title"] or f"第{r['episode_number']}集", body[:20000]))
        db.set_setting(_version_key(drama_id), stamp)
        return True
    except Exception as exc:  # noqa: BLE001 —— 检索是增强项,绝不阻断写作
        print(f"[retrieval] 索引失败({exc})", flush=True)
        return False


def _terms(query: str) -> list[str]:
    """把查询拆成 ≥3 字的词项(trigram 下限),中文按标点/空白切。"""
    raw = re.split(r"[，。、；：？！\s,.:;?!()（）\[\]{}\"'「」]+", query or "")
    terms = []
    for seg in raw:
        seg = seg.strip()
        if len(seg) >= _MIN_QUERY:
            terms.append('"' + seg.replace('"', "") + '"')
        elif 2 <= len(seg) < _MIN_QUERY and re.search(r"[\u4e00-\u9fff]", seg):
            terms.append('"' + seg + '"')
    return terms[:6]


def search_passages(drama_id: int, query: str, limit: int = 3) -> list[dict]:
    """按关键词检索前文段落,返回 [{episode_number, title, snippet}]。失败返回 []。"""
    terms = _terms(query)
    if not terms:
        return []
    try:
        ensure_index(drama_id)
        name = _table(drama_id)
        cond = " OR ".join("body MATCH ?" for _ in terms)
        sql = (f"SELECT episode_id, title, snippet({name}, 2, '【', '】', '…', {_SNIPPET_LEN}) sn "
               f"FROM {name} WHERE {cond} ORDER BY rank LIMIT {int(limit)}")
        rows = db.q(sql, tuple(terms))
        out = []
        for r in rows:
            ep = db.q1("SELECT episode_number FROM episodes WHERE id=?", (r["episode_id"],))
            out.append({"episode_number": (ep or {}).get("episode_number"),
                        "title": r["title"], "snippet": r["sn"]})
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[retrieval] 检索失败({exc})", flush=True)
        return []


def passages_for_chapter_plan(drama_id: int, plan: dict, limit: int = 3) -> list[dict]:
    """按本章计划的标题/目标/事件检索前文(排除本章自身),供写作注入。"""
    query = "；".join(str(plan.get(k) or "") for k in ("title", "goal", "events"))
    if not query.strip():
        return []
    hits = search_passages(drama_id, query, limit=limit + 2)
    # 截断到 limit;命中段太短的丢弃
    return [h for h in hits if len(h.get("snippet") or "") > 20][:limit]
