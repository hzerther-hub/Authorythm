# -*- coding: utf-8 -*-
"""建项目自动生成首集内容(对齐参考项目 backend/src/services/auto-generate.ts)。

建项目时按 work_type 后台跑一次对应 Agent,把输出落到对应表:
    novel     → episodes.content                (novel_writer / novel_content)
    drama     → episodes.script_content         (script_rewriter / script)
    comic     → comic_panels(JSON 数组)         (comic_board / comic_panels)
    promotion → episodes.content                (promo_writer / promo)
    clone     → 不生成(分镜来自参考视频拆解)

全程走 sys_task 记录进度;失败只记任务不阻断建项目。
"""
from __future__ import annotations

from ..agents import runner
from ..core import db
from ..core.taskmgr import TASKMGR

from . import script_quality

AGENT_FOR = {
    "novel": ("novel_writer", "novel_content"),
    "drama": ("script_rewriter", "script"),
    "comic": ("comic_board", "comic_panels"),
    "promotion": ("promo_writer", "promo"),
    "video_clone": ("novel_writer", "clone_understand"),
}

PROMPT_TAIL = {
    "novel": ("目标字数：3000 字\n"
              "输出纯文本叙事正文(环境/动作/神态/对白),对白用「角色名:台词」单独成行;"
              "不要输出章节标题或任何说明"),
    "drama": "输出格式化短剧剧本(场景头 ## S1 | … / 动作 / 角色:对白;每个场景 30-60 秒内容)",
    "comic": "输出漫画分镜格数组 JSON:[{description, dialogue, composition, image_prompt}],建议 4-6 格",
    "promotion": ("请输出至少 3 个版本的推广文案(悬念版/情绪版/利益版),"
                  "每版结构:钩子 → 卖点展开 → CTA,用分隔线区分"),
}


def ensure_first_episode(drama_id: int, work_type: str,
                         image_config_id: int | None = None,
                         video_config_id: int | None = None) -> int:
    """建首集(已有则返回第一集);返回 episode id,无须创建时返回 0。"""
    row = db.q1("SELECT id FROM episodes WHERE drama_id=? ORDER BY episode_number LIMIT 1",
                (drama_id,))
    if row:
        return row["id"]
    ts = db.now()
    return db.ex("""INSERT INTO episodes(drama_id,episode_number,title,status,
                   image_config_id,video_config_id,resolution,created_at,updated_at)
                   VALUES(?,1,'第 1 集','draft',?,?,'720p',?,?)""",
                (drama_id, image_config_id, video_config_id, ts, ts))


def build_message(drama: dict, work_type: str) -> str:
    """从 drama 元数据构造足够信息让 Agent 自由发挥。"""
    meta = db.jload(drama.get("metadata"), {}) or {}
    lines = [f"请为新项目《{drama.get('title') or ''}》生成首集内容。"]
    if meta.get("intro"):
        lines.append(f"简介:{meta['intro']}")
    if meta.get("genre"):
        lines.append(f"题材:{meta['genre']}")
    if drama.get("style"):
        lines.append(f"视觉风格:{drama['style']}")
    if (drama.get("novel_style") or "").strip():
        lines.append(f"文风:{drama['novel_style'].strip()}")
    if work_type == "promotion":
        if meta.get("platform"):
            lines.append(f"目标平台:{meta['platform']}")
        if meta.get("format"):
            lines.append(f"输出格式:{meta['format']}")
    if (drama.get("creative_description") or "").strip():
        lines.append(f"创意描述:{drama['creative_description'].strip()[:600]}")
    tail = PROMPT_TAIL.get(work_type)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def _persist(episode_id: int, work_type: str, text: str) -> int:
    """把 Agent 输出落到对应表;返回写入条数(正文类记 1)。"""
    ts = db.now()
    if work_type == "drama":
        db.ex("UPDATE episodes SET script_content=?, updated_at=? WHERE id=?",
              (text, ts, episode_id))
        return 1
    if work_type == "comic":
        panels = runner.extract_json(text)
        if isinstance(panels, list) and panels:
            db.ex("DELETE FROM comic_panels WHERE episode_id=?", (episode_id,))
            n = 0
            for i, p in enumerate(panels):
                if not isinstance(p, dict):
                    continue
                db.ex("""INSERT INTO comic_panels(episode_id,panel_number,description,dialogue,
                       composition,image_prompt,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)""",
                      (episode_id, i + 1, str(p.get("description") or p.get("desc") or ""),
                       str(p.get("dialogue") or ""), str(p.get("composition") or ""),
                       str(p.get("image_prompt") or p.get("prompt") or ""), ts, ts))
                n += 1
            if n:
                return n
        db.ex("UPDATE episodes SET content=?, updated_at=? WHERE id=?", (text, ts, episode_id))
        return 1
    db.ex("UPDATE episodes SET content=?, updated_at=? WHERE id=?", (text, ts, episode_id))
    return 1


def auto_generate_first_episode(drama_id: int, episode_id: int, config_id: int | None = None,
                                lang: str | None = None) -> dict | None:
    """同步跑一次首集生成(供后台任务调用)。返回 {task_type, written} 或 None。"""
    d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
    if not d:
        return None
    work_type = d["work_type"] or "drama"
    if work_type == "video_clone":
        return None                       # 同款复制不自动生成:分镜来自参考视频拆解
    agent_type, task_type = AGENT_FOR.get(work_type, AGENT_FOR["drama"])

    def job(tid):
        text = ""
        last = ""
        for attempt in range(2):          # 重试一次,防网络抖动导致空响应
            text = runner.run_agent(agent_type, build_message(dict(d), work_type),
                                    lang=lang, config_id=config_id)
            if text and text.strip():
                break
            last = text
        if not (text or "").strip():
            raise RuntimeError(f"首集生成返回空内容({last[:80]})")
        if work_type == "drama":
            # 可拍性质量门:满篇画外音/单人独角戏的首集剧本判失败(不落库)。
            # 剧本要拿去分镜和生成视频,一个人在一间屋里自说自话的稿子拍不出来。
            text = script_quality.enforce(
                text,
                lambda p: runner.run_agent(agent_type, p, lang=lang, config_id=config_id),
            )
        return _persist(episode_id, work_type, text)

    def done(tid, result, error):
        if error:
            err(f"首集自动生成失败:{error}")
        elif result:
            ok(f"首集内容已生成({result} 条)")

    TASKMGR.submit(task_type, job, done, drama_id=drama_id, episode_id=episode_id)
    return {"task_type": task_type, "episode_id": episode_id}


def latest_auto_gen_task(drama_id: int) -> dict | None:
    """最近一次首集自动生成任务(供任务面板/项目页展示状态)。"""
    types = [t for t, _ in AGENT_FOR.values()]
    marks = ",".join("?" * len(types))
    return db.q1(f"""SELECT * FROM sys_task WHERE drama_id=? AND type IN ({marks})
                    ORDER BY id DESC LIMIT 1""", (drama_id, *types))