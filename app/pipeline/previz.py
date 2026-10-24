# -*- coding: utf-8 -*-
"""导演台(DirectorDesk)白模预演工程:数据模型 + 校验 + 文件读写。

对齐上游 mangfufu/director-desk 的 `src/model.ts`(JSON 工程格式 `format='director-desk'`)。

**本模块刻意不实现任何渲染/编码。** 3D 视口、骨骼动画、物理、视频导出全部复用
原版 web 构建(QtWebEngine 内嵌,见 `scripts/fetch_directordesk.py` 与
`app/ui/previz_page.py`)——这是「效果不低于原版」的硬保证:同一段渲染代码,
Python 只负责喂工程 JSON、收导出视频。这里的校验是**提前报警的子集**,
工程被原版加载时原版自己的 assertProject 仍是最终真相源。
"""
from __future__ import annotations

import json
import math
import re
import uuid
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import NoReturn

from ..core.logging_setup import get_logger

log = get_logger(__name__)


class PrevizError(RuntimeError):
    """工程数据非法或文件读写失败。"""


# ── 枚举常量(与 model.ts 对齐)─────────────────────────────────────────

FORMAT = "director-desk"
SUPPORTED_VERSIONS = (1, 2)
ASPECTS = ("9:16", "16:9", "21:9", "3:4", "4:3", "1:1")
FRAME_RATES = (24, 30, 50, 59, 60, 90, 120)
KINDS = ("actor", "prop", "camera", "crowd")
BUILDS = ("slim", "normal", "broad")
GENDERS = ("male", "female")
FACES = ("path", "fixed", "target")
CAMERA_MODES = ("free", "follow", "pov")
CAMERA_AIMS = ("target", "manual")
WALLS = ("north", "south", "east", "west", "ceiling")
COLORS = ["#a7bdd7", "#b8c7b3", "#d1bfa0", "#c5b3c9", "#d0d2d0", "#bdaca4"]
DEFAULT_COLOR = "#d5d5d0"

# 23 种内置动作 → 中文标签(model.ts ACTIONS 全量搬运,别自创动作名)
ACTIONS: dict[str, str] = {
    "idle": "站立 / 待机", "walk": "走路", "run": "跑步", "sit": "坐姿",
    "standup": "起身", "crouch": "蹲下", "crawl": "爬行", "jump": "跳跃",
    "lie": "躺下", "fall": "倒地", "wave": "挥手", "point": "指向",
    "turn": "转身", "guard": "防御", "punch": "出拳", "kick": "踢腿",
    "roundhouse": "回旋踢", "flying-kick": "飞身踢", "dodge": "闪避",
    "throw": "抛掷", "push": "推物", "stumble": "踉跄", "roll": "翻滚",
}

_ID_RE = re.compile(r"^[\w\-.:]{1,200}$", re.UNICODE)
_COLOR_RE = re.compile(r"^#[0-9a-f]{6}$", re.IGNORECASE)


def new_id() -> str:
    return str(uuid.uuid4())


# ── 数据模型 ───────────────────────────────────────────────────────────

def _v3(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> list[float]:
    return [float(x), float(y), float(z)]


@dataclass
class Waypoint:
    time: float
    position: list[float] = field(default_factory=lambda: _v3())
    heading: float | None = None  # 人物朝向偏移(弧度),仅 actor/crowd;要么全有要么全无
    stop: bool | None = None
    easing: str | None = None


@dataclass
class MotionPath:
    smooth: bool = False
    points: list[Waypoint] = field(default_factory=list)


@dataclass
class Clip:
    action: str
    start: float
    end: float
    speed: float = 1.0
    id: str = field(default_factory=new_id)
    name: str | None = None


@dataclass
class PoseKey:
    time: float
    pose: dict[str, float | list[float]] = field(default_factory=dict)


@dataclass
class CameraConfig:
    aim: str = "target"
    focal: float = 28.0
    target: list[float] = field(default_factory=lambda: _v3(0, 1, 0))
    targetId: str = ""
    targetHeight: float = 1.2
    mode: str = "free"
    offset: list[float] = field(default_factory=lambda: _v3(0, 1.6, -1.8))
    inheritRotation: bool = True
    hideWalls: list[str] = field(default_factory=list)


@dataclass
class Entity:
    kind: str
    asset: str
    name: str
    position: list[float] = field(default_factory=lambda: _v3())
    id: str = field(default_factory=new_id)
    color: str = DEFAULT_COLOR
    rotation: list[float] = field(default_factory=lambda: _v3())
    scale: list[float] = field(default_factory=lambda: _v3(1, 1, 1))
    visible: bool = True
    locked: bool = False
    height: float = 1.75
    build: str = "normal"
    gender: str = "male"
    path: MotionPath | None = None
    face: str = "path"
    faceTarget: str = ""
    clips: list[Clip] = field(default_factory=list)
    pose: dict[str, float | list[float]] = field(default_factory=dict)
    poseKeys: list[PoseKey] = field(default_factory=list)
    camera: CameraConfig | None = None
    count: int = 12
    spacing: float = 0.75
    seed: int = 42
    reference: str = ""


@dataclass
class Cut:
    time: float
    cameraId: str


@dataclass
class ReferenceImage:
    name: str
    data: str  # data:image/png;base64,... 内嵌,与 characters 表的三视图直接互通
    id: str = field(default_factory=new_id)


@dataclass
class ProductionNote:
    """戏段备注:对白/情绪/动作,供导演台编辑器与配套提示词查看(非自动提示词)。"""
    start: float
    end: float
    story: str = ""
    emotion: str = ""
    dialogue: str = ""
    action: str = ""
    actorId: str = ""
    id: str = field(default_factory=new_id)


@dataclass
class ProductionData:
    fixedPrompt: str = ""
    sceneReferenceIds: list[str] = field(default_factory=list)
    notes: list[ProductionNote] = field(default_factory=list)
    promptText: str = ""        # 「参考视频」模式配套提示词(作者文本,原样导出)
    textOnlyPrompt: str = ""    # 「纯文本」模式配套提示词
    promptMode: str = "reference-video"


@dataclass
class Room:
    width: float = 4.8
    depth: float = 4.2
    height: float = 2.8
    enabled: bool = True


@dataclass
class Project:
    name: str
    duration: float
    entities: list[Entity] = field(default_factory=list)
    cuts: list[Cut] = field(default_factory=list)
    references: list[ReferenceImage] = field(default_factory=list)
    production: ProductionData | None = None
    room: Room = field(default_factory=Room)
    fps: int = 24
    aspect: str = "9:16"
    version: int = 1
    format: str = FORMAT


# ── 构建辅助(对应 model.ts 的 entity()/clip() 工厂)───────────────────

def new_entity(kind: str, asset: str, name: str,
               position: list[float] | None = None) -> Entity:
    """按原版 entity() 工厂的默认值建实体;actor 默认色取 COLORS[0]。"""
    if kind not in KINDS:
        raise PrevizError(f"未知实体类型:{kind}")
    return Entity(
        kind=kind, asset=asset, name=name,
        position=list(position) if position else _v3(),
        color=COLORS[0] if kind == "actor" else DEFAULT_COLOR,
        camera=CameraConfig() if kind == "camera" else None,
    )


def new_clip(action: str, start: float, end: float) -> Clip:
    if action not in ACTIONS:
        raise PrevizError(f"未知动作:{action}(可选:{'/'.join(ACTIONS)})")
    return Clip(action=action, start=float(start), end=float(end))


def add_path(entity: Entity, points: list[tuple[float, tuple[float, float, float]]],
             smooth: bool = True) -> MotionPath:
    """给实体挂走位路径;点按时间升序(原版要求时间严格递增)。"""
    path = MotionPath(smooth=smooth)
    for t, pos in points:
        path.points.append(Waypoint(time=float(t), position=list(pos)))
    entity.path = path
    return path


# ── 数值辅助 ───────────────────────────────────────────────────────────

def aspect_number(aspect: str) -> float:
    w, h = aspect.split(":")
    return float(w) / float(h)


def get_frame_count(start: float, end: float, fps: int) -> int:
    return max(0, math.ceil((end - start) * fps - 1e-8))


# ── 校验(子集;原版 assertProject 仍是加载期最终真相源)────────────────

def _fail(msg: str) -> NoReturn:
    raise PrevizError(f"预演工程无效:{msg}")


def _check_v3(v: object, what: str) -> None:
    if not (isinstance(v, (list, tuple)) and len(v) == 3
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)):
        _fail(f"{what} 坐标错误")


def validate_project(data: dict) -> None:
    """校验工程 dict(已 json.loads);不合法抛 PrevizError。"""
    if not isinstance(data, dict):
        _fail("根必须是对象")
    if data.get("format") != FORMAT or data.get("version") not in SUPPORTED_VERSIONS:
        _fail("不支持的文件格式或版本")
    name = data.get("name")
    if not isinstance(name, str) or not name or len(name) > 200:
        _fail("名称错误")
    duration = data.get("duration")
    if not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        _fail("时长错误")
    if data.get("fps") not in FRAME_RATES:
        _fail("帧率错误")
    if data.get("aspect") not in ASPECTS:
        _fail("画幅错误")
    room = data.get("room") or {}
    for k in ("width", "depth", "height"):
        v = room.get(k)
        if not (isinstance(v, (int, float)) and math.isfinite(v) and 2.3 <= v <= 10000):
            _fail(f"房间尺寸 {k} 需在 2.3~10000 米之间")
    entities = data.get("entities")
    cuts = data.get("cuts")
    if not isinstance(entities, list) or not isinstance(cuts, list):
        _fail("缺少场景数据")

    ids: set[str] = set()
    camera_ids: set[str] = set()
    for e in entities:
        if not isinstance(e, dict):
            _fail("实体必须是对象")
        eid = e.get("id")
        if not isinstance(eid, str) or not _ID_RE.match(eid) or eid in ids:
            _fail(f"实体标识错误或重复:{eid!r}")
        ids.add(eid)
        if e.get("kind") not in KINDS:
            _fail(f"实体 {eid} 类型错误")
        if e.get("kind") == "camera":
            camera_ids.add(eid)
        if not isinstance(e.get("name"), str) or len(e["name"]) > 200:
            _fail(f"实体 {eid} 名称错误")
        if not _COLOR_RE.match(str(e.get("color") or "")):
            _fail(f"实体 {eid} 颜色错误")
        for k in ("position", "rotation", "scale"):
            _check_v3(e.get(k), f"实体 {eid} {k}")
        if any(x <= 0 for x in e["scale"]):
            _fail(f"实体 {eid} 缩放必须为正")
        cam = e.get("camera")
        if e["kind"] == "camera":
            if not isinstance(cam, dict):
                _fail("摄影机缺少配置")
            if cam.get("aim") not in CAMERA_AIMS or cam.get("mode") not in CAMERA_MODES:
                _fail("摄影机参数错误")
            focal = cam.get("focal")
            if not (isinstance(focal, (int, float)) and 8 <= focal <= 300):
                _fail("摄影机焦距需在 8~300")
            for w in cam.get("hideWalls") or []:
                if w not in WALLS:
                    _fail("摄影机隐藏墙面错误")
        elif cam is not None:
            _fail(f"实体 {eid} 非摄影机却带摄影机配置")
        path = e.get("path")
        if path is not None:
            if not isinstance(path, dict) or not isinstance(path.get("points"), list) \
                    or not path["points"]:
                _fail(f"实体 {eid} 路径至少需要一个途经点")
            last_path_t = -1.0
            for w in path["points"]:
                t = w.get("time")
                _check_v3(w.get("position"), f"实体 {eid} 路径点")
                if not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
                    _fail(f"实体 {eid} 路径时间必须严格递增")
                if t <= last_path_t:
                    _fail(f"实体 {eid} 路径时间必须严格递增")
                last_path_t = float(t)
        clips = e.get("clips") or []
        if not isinstance(clips, list):
            _fail(f"实体 {eid} 动作数据错误")
        clip_ids = set()
        for c in clips:
            if not isinstance(c, dict):
                _fail(f"实体 {eid} 动作片段不能为空")
            cid = c.get("id")
            if not isinstance(cid, str) or cid in clip_ids:
                _fail(f"实体 {eid} 动作片段标识重复")
            clip_ids.add(cid)
            if c.get("action") not in ACTIONS:
                _fail(f"实体 {eid} 含未知动作:{c.get('action')!r}")
            s, en, sp = c.get("start"), c.get("end"), c.get("speed")
            if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (s, en, sp)):
                _fail(f"实体 {eid} 动作时间重叠或范围错误")
            assert isinstance(s, (int, float)) and isinstance(en, (int, float)) \
                and isinstance(sp, (int, float))
            if s < 0 or en <= s or sp <= 0:
                _fail(f"实体 {eid} 动作时间重叠或范围错误")
        ordered = sorted(clips, key=lambda c: c["start"])
        for a, b in pairwise(ordered):
            if b["start"] < a["end"]:
                _fail(f"实体 {eid} 动作时间重叠")

    if not camera_ids:
        _fail("至少需要一台摄影机")
    if not cuts:
        _fail("切镜不能为空")
    if cuts[0].get("time") != 0:
        _fail("切镜必须从零秒开始")
    last_t: float = -1.0
    for c in cuts:
        t = c.get("time")
        if not (isinstance(t, (int, float)) and math.isfinite(t) and 0 <= t < duration):
            _fail("切镜时间必须严格递增且落在时长内")
        assert isinstance(t, (int, float))
        if t <= last_t:
            _fail("切镜时间必须严格递增且落在时长内")
        last_t = float(t)
        if c.get("cameraId") not in camera_ids:
            _fail("切镜机位不存在")
    refs = data.get("references") or []
    ref_ids = set()
    for r in refs:
        if not isinstance(r, dict) or not _ID_RE.match(str(r.get("id") or "")) or r["id"] in ref_ids:
            _fail("参考图标识重复或错误")
        ref_ids.add(r["id"])
        if not isinstance(r.get("data"), str) \
                or not r["data"].startswith(("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")):
            _fail("参考图必须内嵌 PNG/JPEG/WebP")
    for note in (data.get("production") or {}).get("notes") or []:
        if note.get("actorId") and note["actorId"] not in ids:
            _fail("剧情备注关联的角色不存在")
        if not isinstance(note.get("actorId"), str):
            _fail("剧情备注 actorId 错误")


# ── 序列化 ─────────────────────────────────────────────────────────────

def project_to_dict(project: Project) -> dict:
    return asdict(project)


def project_to_json(project: Project, *, pretty: bool = True) -> str:
    return json.dumps(project_to_dict(project), ensure_ascii=False, indent=2 if pretty else None)


def save_project(project: Project, path: Path) -> Path:
    """工程落盘(.directordesk.json)。目录不存在自动创建。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = project_to_dict(project)
    validate_project(data)
    path.write_text(project_to_json(project), encoding="utf-8")
    log.info("previz 工程已保存:%s(%d 实体 / %d 切镜)", path, len(project.entities), len(project.cuts))
    return path


def load_project(path: Path) -> dict:
    """读取并校验工程文件,返回 dict(原样传给 web 端,不做 dataclass 还原)。"""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PrevizError(f"无法读取工程文件:{exc}") from exc
    except json.JSONDecodeError as exc:
        raise PrevizError(f"工程文件不是合法 JSON:{exc}") from exc
    validate_project(data)
    return data


# ── 示例工程(model.ts demoProject 的忠实移植,冒烟测试 / UI「打开示例」用)──

def demo_project() -> Project:
    a = new_entity("actor", "person", "人物 A · 床边", [-0.5, 0, -0.75])
    a.color = COLORS[1]
    a.rotation = [0, math.pi / 2, 0]
    a.clips = [new_clip("sit", 0, 7), new_clip("standup", 7, 9), new_clip("idle", 9, 15)]

    b = new_entity("actor", "person", "人物 B · 走向衣柜", [0.55, 0, 1.4])
    b.clips = [new_clip("idle", 0, 2), new_clip("walk", 2, 6), new_clip("turn", 6, 8), new_clip("idle", 8, 15)]
    add_path(b, [(2, (0.55, 0, 1.4)), (4, (0.9, 0, 0.05)), (6, (1.15, 0, -0.95))])

    c = new_entity("actor", "person", "人物 C · 书桌", [-1.65, 0, 1.05])
    c.color = COLORS[2]
    c.gender = "female"
    c.height = 1.65
    c.rotation = [0, -math.pi / 2, 0]
    c.clips = [new_clip("sit", 0, 15)]
    c.poseKeys = [PoseKey(time=0, pose={"head": 8}),
                  PoseKey(time=9, pose={"head": -12, "headYaw": 30}),
                  PoseKey(time=12, pose={"head": 0, "headYaw": 0})]

    d = new_entity("actor", "person", "人物 D · 进门", [1.55, 0, 1.75])
    d.color = COLORS[3]
    d.height = 1.8
    d.clips = [new_clip("idle", 0, 3), new_clip("walk", 3, 6), new_clip("idle", 6, 9),
               new_clip("walk", 9, 13), new_clip("idle", 13, 15)]
    add_path(d, [(3, (1.55, 0, 1.75)), (6, (1.3, 0, 0.65)), (9, (1.3, 0, 0.65)), (13, (0.1, 0, 0.6))],
             smooth=False)

    props = []
    for asset, name, pos, rot in (("bed", "双人床", (-1.25, 0, -0.9), 0),
                                  ("nightstand", "床头柜", (-2.08, 0, -1.66), 0),
                                  ("wardrobe", "衣柜", (1.35, 0, -1.78), 0),
                                  ("desk", "书桌", (-2.02, 0, 1.05), math.pi / 2),
                                  ("chair", "座椅", (-1.65, 0, 1.05), -math.pi / 2),
                                  ("lamp", "台灯", (-2.08, 0.58, -1.66), 0),
                                  ("laptop", "电脑", (-2.02, 0.75, 1.05), math.pi / 2)):
        p = new_entity("prop", asset, name, list(pos))
        p.rotation = [0, rot, 0]
        props.append(p)

    ca = new_entity("camera", "camera", "A · 室内全景", [2.15, 1.65, 1])
    ca.camera = CameraConfig(focal=20, target=[-0.8, 1, -0.6])
    add_path(ca, [(0, (2.15, 1.65, 1)), (15, (2.05, 1.6, 0.8))], smooth=False)

    cb = new_entity("camera", "camera", "B · 人物跟拍", [2.2, 1.5, 0.6])
    cb.camera = CameraConfig(focal=28, targetHeight=1.3, targetId=b.id)
    add_path(cb, [(3, (2.2, 1.5, 0.6)), (10, (2.2, 1.5, 0.15))])

    cc = new_entity("camera", "camera", "C · 主观视角", [0, 1.65, 0])
    cc.camera = CameraConfig(mode="pov", targetId=d.id, offset=[0, 1.67, 0.13], focal=24)

    return Project(
        name="卧室 · 四人调度", duration=15, aspect="16:9",
        room=Room(width=4.8, depth=4.2, height=2.8),
        entities=[a, b, c, d, ca, cb, cc, *props],
        cuts=[Cut(time=0, cameraId=ca.id), Cut(time=5, cameraId=cb.id), Cut(time=10, cameraId=ca.id)],
    )
