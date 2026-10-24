# -*- coding: utf-8 -*-
"""分镜 → 导演台(DirectorDesk)预演工程生成器。

翻译规则(确定性,不调 LLM —— 预演骨架要的是可复现,精修交给导演台编辑器):
- 每个出场角色 → 一个 actor 白模(女性角色用 woman 资产),围成弧形,朝向场地中心;
  角色三视图/预览图内嵌为工程参考图(reference),导演台里直接可见。
- 每个分镜 → 一台摄影机 + 一个切镜点:景别定距离/焦距(特写近、全景远),
  俯仰角定高度,推/拉/摇生成摄影机路径,画面主体绑定分镜的首位角色。
- 道具名按关键词映射到白模资产(床→bed、桌→desk …),映射不上的不硬造。
- 每镜一条 production.note:description→剧情、content→对白、atmosphere→情绪。

生成的是**初始骨架**:走位与运镜细节本来就该在导演台里手调,这里给足结构。
"""
from __future__ import annotations

import base64
import math

from ..core import config, db
from ..core.logging_setup import get_logger
from . import previz
from .previz import (
    CameraConfig,
    Clip,
    Cut,
    Entity,
    MotionPath,
    ProductionNote,
    Project,
    ReferenceImage,
    Room,
    Waypoint,
    new_entity,
)

log = get_logger(__name__)

DEFAULT_SHOT_SECONDS = 3.0

# 道具名关键词 → 白模资产 id(顺序敏感:specific 在前,别让「餐桌」掉进「桌」的桶)
_PROP_KEYWORDS: list[tuple[str, str]] = [
    ("床头柜", "nightstand"), ("餐桌", "table"), ("书桌", "desk"), ("桌子", "table"),
    ("床", "bed"), ("衣柜", "wardrobe"), ("柜", "wardrobe"), ("沙发", "sofa"),
    ("椅子", "chair"), ("座椅", "chair"), ("凳", "chair"), ("椅", "chair"),
    ("路灯", "streetlight"), ("台灯", "lamp"), ("灯", "lamp"),
    ("电脑", "laptop"), ("笔记本", "laptop"), ("杯子", "cup"), ("杯", "cup"),
    ("长剑", "sword"), ("剑", "sword"), ("汽车", "car"), ("车", "car"),
    ("楼梯", "stairs"), ("门", "door"), ("长椅", "bench"), ("树", "tree"),
    ("石头", "rock"), ("围墙", "fence"), ("楼", "building"),
]

# 白模资产全集见上游 asset-catalog.ts;这里只用 legacy 稳定 id


def _guess_female(name: str, appearance: str) -> bool:
    text = f"{name}{appearance}"
    return any(k in text for k in ("女", "她", "小姐", "夫人", "太太", "少女", " girl", "female"))


def _prop_asset(name: str) -> str | None:
    for kw, asset in _PROP_KEYWORDS:
        if kw in name:
            return asset
    return None


def _b64_reference(name: str, image_url: str | None) -> ReferenceImage | None:
    """角色图 → 内嵌参考图。图片走 media_url_to_path,不存在/过大就跳过,不抛。"""
    if not image_url:
        return None
    try:
        path = config.media_url_to_path(image_url)
        if not path.exists() or path.stat().st_size > 4 * 1024 * 1024:
            return None
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return ReferenceImage(name=name[:60], data=f"data:{mime};base64,{data}")
    except Exception as exc:  # 参考图是锦上添花,绝不因它失败打断生成
        log.warning("参考图内嵌跳过 %s:%s", image_url, exc)
        return None


def _shot_camera(idx: int, start: float, dur: float, shot: db.Row,
                 subject_id: str) -> tuple[Entity, Cut]:
    """一个分镜 → 一台摄影机 + 一个切镜点。"""
    shot_type = (shot.get("shot_type") or "") + (shot.get("angle") or "")
    if any(k in shot_type for k in ("特写", "近景", "close")):
        dist, focal = 1.4, 50.0
    elif any(k in shot_type for k in ("全景", "远景", "大全景", "wide")):
        dist, focal = 5.0, 20.0
    else:
        dist, focal = 3.0, 35.0

    height = 1.5
    if "俯" in shot_type:
        height = 2.8
    elif "仰" in shot_type:
        height = 0.7

    # 机位环绕分布,相邻镜头角度错开(黄金角),避免每镜都从同一方向拍
    azimuth = idx * 2.399963
    tx, tz = 0.0, 0.0
    pos = [tx + dist * math.sin(azimuth), height, tz + dist * math.cos(azimuth)]

    cam = new_entity("camera", "camera", f"镜{shot.get('storyboard_number', idx + 1)}", pos)
    movement = shot.get("movement") or ""
    has_path = False
    if any(k in movement for k in ("推", "push")):
        start_pos = [pos[0] * (dist + 1.6) / dist, height, pos[2] * (dist + 1.6) / dist]
        cam.path = MotionPath(smooth=True, points=[
            Waypoint(time=start, position=start_pos), Waypoint(time=start + dur, position=pos)])
        has_path = True
    elif any(k in movement for k in ("拉", "pull")):
        end_pos = [pos[0] * (dist + 1.6) / dist, height, pos[2] * (dist + 1.6) / dist]
        cam.path = MotionPath(smooth=True, points=[
            Waypoint(time=start, position=pos), Waypoint(time=start + dur, position=end_pos)])
        has_path = True
    elif any(k in movement for k in ("摇", "移", "pan", "track")):
        side = 1.2 if idx % 2 == 0 else -1.2
        cam.path = MotionPath(smooth=True, points=[
            Waypoint(time=start, position=[pos[0], height, pos[2]]),
            Waypoint(time=start + dur, position=[pos[0] + side, height, pos[2] + side])])
        has_path = True
    if not has_path:
        cam.path = None

    cam.camera = CameraConfig(
        focal=focal,
        target=[tx, 1.2, tz],
        targetId=subject_id,
        mode="follow" if subject_id else "free",
    )
    return cam, Cut(time=round(start, 3), cameraId=cam.id)


def generate_from_episode(episode_id: int, *, aspect: str = "9:16",
                          out_path=None) -> dict:
    """把一集的分镜翻译成导演台工程并落盘。返回 {path, shots, actors, props}。

    纯确定性转换:同库同参必出同工程;不调 LLM、不并发。
    """
    ep = db.q1("SELECT * FROM episodes WHERE id=?", (episode_id,))
    if not ep:
        raise RuntimeError(f"剧集不存在:id={episode_id}")
    shots = db.q("SELECT * FROM storyboards WHERE episode_id=? AND deleted_at IS NULL "
                 "ORDER BY storyboard_number", (episode_id,))
    if not shots:
        raise RuntimeError("本集还没有分镜,请先拆分分镜再生成预演工程")

    # ── 出场角色 → actor ────────────────────────────────────────────
    char_rows = db.q("SELECT DISTINCT c.id, c.name, c.appearance, c.image_url "
                     "FROM characters c JOIN storyboard_characters sc ON sc.character_id=c.id "
                     "JOIN storyboards s ON s.id=sc.storyboard_id "
                     "WHERE s.episode_id=? AND s.deleted_at IS NULL ORDER BY c.id",
                     (episode_id,))
    actors: list[Entity] = []
    references: list[ReferenceImage] = []
    for i, ch in enumerate(char_rows or []):
        female = _guess_female(ch["name"] or "", ch["appearance"] or "")
        a = new_entity("actor", "woman" if female else "person", ch["name"] or f"角色{i + 1}")
        a.gender = "female" if female else "male"
        a.height = 1.65 if female else 1.75
        # 弧形排布,朝向中心;第一个角色放台前
        ang = -math.pi / 2 + i * 0.9
        a.position = [round(1.6 * math.sin(ang), 3), 0.0, round(1.6 * math.cos(ang), 3)]
        a.rotation = [0.0, round(math.pi + ang, 3), 0.0]
        ref = _b64_reference(f"{a.name} · 参考图", ch["image_url"])
        if ref:
            references.append(ref)
            a.reference = ref.id
        actors.append(a)
    if actors:
        total = sum(float(s.get("duration") or DEFAULT_SHOT_SECONDS) for s in shots)
        for a in actors:
            a.clips = [Clip(action="idle", start=0.0, end=total)]

    # ── 道具 → 白模(关键词映射,映射不上就不放,宁缺毋滥)────────────
    prop_rows = db.q("SELECT DISTINCT p.name FROM props p JOIN episode_props ep ON ep.prop_id=p.id "
                     "WHERE ep.episode_id=? ORDER BY p.id", (episode_id,)) or []
    props: list[Entity] = []
    placed: set[str] = set()
    slot = 0
    for p in prop_rows:
        asset = _prop_asset(p["name"] or "")
        if not asset or asset in placed:
            continue
        placed.add(asset)
        e = new_entity("prop", asset, p["name"][:60])
        # 沿场地后缘一字排开,避开中央表演区
        e.position = [round(-2.0 + (slot % 5) * 1.0, 3), 0.0, round(-1.8 - (slot // 5) * 0.8, 3)]
        props.append(e)
        slot += 1

    # ── 每镜:主体绑定 + 摄影机/切镜 + 剧情备注 ─────────────────────
    char_by_storyboard: dict[int, int | None] = {}
    for s in shots:
        row = db.q1("SELECT character_id FROM storyboard_characters WHERE storyboard_id=? "
                    "ORDER BY rowid LIMIT 1", (s["id"],))
        char_by_storyboard[s["id"]] = row["character_id"] if row else None
    actor_id_by_char = {ch["id"]: actors[i].id for i, ch in enumerate(char_rows or [])}

    entities: list[Entity] = [*actors, *props]
    cuts: list[Cut] = []
    notes: list[ProductionNote] = []
    t = 0.0
    for idx, s in enumerate(shots):
        dur = float(s.get("duration") or DEFAULT_SHOT_SECONDS)
        subject_id = actor_id_by_char.get(char_by_storyboard.get(s["id"]) or -1, "")
        cam, cut = _shot_camera(idx, t, dur, s, subject_id)
        entities.append(cam)
        cuts.append(cut)
        notes.append(ProductionNote(
            start=t, end=t + dur, actorId=subject_id,
            story=(s.get("description") or s.get("title") or "")[:400],
            dialogue=(s.get("content") or "")[:400],
            emotion=(s.get("atmosphere") or "")[:120],
            action=f"{s.get('shot_type') or ''} {s.get('movement') or ''}".strip()[:120],
        ))
        t += dur

    project = Project(
        name=f"{ep['title'] or '第' + str(ep['episode_number']) + '集'} · 预演",
        duration=round(t, 3), aspect=aspect,
        room=Room(width=5.2, depth=4.6, height=2.8),
        entities=entities, cuts=cuts, references=references,
        production=previz.ProductionData(notes=notes),
    )
    data = previz.project_to_dict(project)
    previz.validate_project(data)

    path = out_path or (config.DATA_DIR / "previz" / f"ep{episode_id}.directordesk.json")
    previz.save_project(project, path)
    log.info("预演工程已生成:%s(%d 镜 / %d 角色 / %d 道具白模)",
             path, len(shots), len(actors), len(props))
    return {"path": str(path), "shots": len(shots), "actors": len(actors),
            "props": len(props), "duration": round(t, 3)}
