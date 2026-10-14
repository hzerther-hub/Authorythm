"""角色 / 场景 / 道具变化检测 → 自动建变体行。

触发逻辑:扫描分镜文字(content / video_prompt / atmosphere / description),
发现「外观 / 场景 / 道具」发生变化的关键词(戴面具/换装/瞎了/家里变富了/加新家具/武器升级...),
自动给对应角色/场景/道具各建一条 variants 行 —— 出图用变体的 final_prompt,
卡片侧自动显示「变身版本」(comic_image_url 也同步),无需用户手动切。

参考思路:对齐原版 character_variants / scene_variants 的同人不同造型场景,
只是触发方式从「用户手动」变成「自动检测」。

⚠️ 这层只**创建变体行**,不会自动跑生图 —— 避免一次性烧太多 token。
生图仍由用户在「造型变体」对话框里点「重生」触发。
"""
from __future__ import annotations

import re

from ..core import db


# ── 角色变化触发词 ───────────────────────────────────────────────────────
# 顺序重要:长的在前(更具体的模式优先匹配);短的会被任何前缀吃掉。
# 每条 = (pattern, kind 中文标签)
#
# 触发词越宽越省事:宁可建重复变体,别漏掉真变化;
# 重复建会在 ensure 里查 variants.label 已有就跳过,不会污染。
CHAR_VARIANT_TRIGGERS: list[tuple[str, str]] = [
    # 面具 / 头饰
    (r"戴[上了]?(?:一副?|一张?|一个)?(?:面具|眼罩|墨镜|兜帽|斗篷|披风|围[巾脖]|头巾|帽子|头盔|风帽)",
     "面具/头饰"),
    # 换装
    (r"换[上了]?(?:新|一身|一套)?(?:衣服|服装|装束|套装|制服|军装|礼服|囚服|便装|和服|汉服)",
     "换装"),
    # 失明 / 眼伤
    (r"(?:瞎了|失明|独眼|盲[人]|眼睛[受负]了?伤|瞎了一只眼|双目失明)",
     "失明/眼伤"),
    # 肢体损伤
    (r"(?:断[了一条]?臂|截肢|少了一条[腿手]?|跛|瘸|拐[着]?|独臂|独腿|缺[了]?臂)",
     "肢体损伤"),
    # 重伤
    (r"(?:受了重伤|重伤|垂死|濒死|昏迷|卧床不起|浑身是血|血迹斑斑)",
     "重伤"),
    # 刀疤 / 烧伤 / 疤痕
    (r"(?:刀疤|烧伤|烫伤|疤痕|独眼龙|脸上有疤)",
     "疤痕"),
    # 病
    (r"(?:病了|病[倒了]|重病|卧病|病入膏肓|缠绵病榻)",
     "生病"),
    # 身体被砍 / 刀伤 / 枪伤
    (r"(?:身体被砍|被砍伤|被刺伤|被击中|中了[一]?枪|中弹)",
     "伤害"),
    # 体型变化
    (r"(?:吃胖了|变胖|胖了[一二三四五六七八九十]?分|瘦了|消瘦|面黄肌瘦|骨瘦如柴)",
     "体型变化"),
    # 怀孕
    (r"(?:怀[上了]?孕|大着[肚子]?|孕妇|挺[着]?大[肚子]?)",
     "怀孕"),
    # 化妆
    (r"(?:化了?妆|浓妆|淡妆|妆容|口红|眼影|腮红)",
     "化妆"),
    # 超自然形态
    (r"(?:鬼[魂灵]|幽灵|僵尸|骷髅|骸骨|灵魂状态)",
     "超自然形态"),
    # 变身
    (r"(?:神化|魔化|妖化|半人半[妖魔兽]|半兽|真身)",
     "变身"),
    # 年龄
    (r"(?:老年|少年|幼年|童年|老态|衰老|返老还童|年迈|白头)",
     "年龄段"),
    # 发色 / 发型
    (r"(?:白发|黑发|染[了]?发|红发|金发|秃[头了]|光头|长发|短发|披发|束发)",
     "发色/发型"),
    # 纹身
    (r"(?:纹[了]?身|刺青|纹身)",
     "纹身"),
    # 机械改造
    (r"(?:假肢|义肢|机械[手臂腿]|改造人|义体|赛博格)",
     "机械改造"),
    # 兽化
    (r"(?:变[成了]?(?:狼|狐|猫|龙|凤|蛇|鬼|魔|仙)|化(?:为|作)?(?:狼|狐|龙|凤|蛇))",
     "兽化"),
    # 异化
    (r"(?:长出(?:翅膀|角|尾巴|鳞片))",
     "异化"),
    # 装备
    (r"(?:戴上(?:头盔|盔甲|护甲)|背着?刀|提着剑|手持长[枪矛]|拔出[刀剑])",
     "装备"),
]


# ── 场景变化触发词 ───────────────────────────────────────────────────────
# 场景状态(装修/季节/光线/物件增减/时间段)的关键词
SCENE_VARIANT_TRIGGERS: list[tuple[str, str]] = [
    # 富 / 穷 / 装修变化
    (r"(?:变富|变穷|发财|破产|装修|翻新|改装|改建|重建|新建|拆迁)",
     "场景状态"),
    # 季节 / 天气
    (r"(?:季节[变化]|换季|春[天季]|夏[天季]|秋[天季]|冬[天季]|梅雨[季]|雪[季天])",
     "季节"),
    # 光线 / 色调 / 氛围巨变
    (r"(?:光线[大变]|灯光[大换]|色调[变改]|夜景|日景|黎明|黄昏|正午|深夜)",
     "光线"),
    # 时间段
    (r"(?:白天|夜晚|夜[里深]|凌晨|傍晚|正午|清晨|日暮)",
     "时间段"),
    # 物件增减(家具/陈设)
    (r"(?:加[了新添了][一]?(?:件|套|台|把|张|个|盏)[一]?(?:家具|陈设|摆设|桌椅|沙发|柜子|书架|床|灯|画|花瓶|地毯|摆件|挂件))",
     "物件增减"),
    # 战乱 / 灾难 / 节日 / 和平
    (r"(?:战乱|战火|灾难|废墟|残垣|战后|灾后|节日|庆典|婚礼|葬礼|祭奠|和平|繁荣|萧条)",
     "状态事件"),
    # 损坏 / 破败
    (r"(?:破败|破损|残破|烧毁|炸毁|倒塌|塌[了]?|毁[了]?坏)",
     "损坏"),
    # 搬迁 / 新居
    (r"(?:搬[进家到了]|新居|新房|新[址店铺]|搬迁)",
     "搬迁"),
]


# ── 道具变化触发词 ───────────────────────────────────────────────────────
# 道具状态(损坏/替换/升级/新增)的关键词
PROP_VARIANT_TRIGGERS: list[tuple[str, str]] = [
    # 损坏 / 旧化
    (r"(?:道具[损坏]|破旧|残缺|碎裂|折断|断了|毁坏|烧焦|锈蚀)",
     "损坏"),
    # 替换 / 升级 / 翻新
    (r"(?:替换[了]?|换[成了]?|升级[了]?|翻新[了]?|改造[了]?|强化[了]?)",
     "替换/升级"),
    # 新增 / 拿到 / 出现
    (r"(?:新[增添得来了到]?(?:把|件|条|本|枚|只|张|个)[一]?刀|剑|枪|符|书|信|牌|石|珠|玉|宝|钥匙|地图|药)",
     "新增"),
    # 消失 / 遗失 / 销毁
    (r"(?:消失|遗失|丢失|不见了|被毁[了]?|销毁)",
     "消失"),
    # 变形 / 激活
    (r"(?:变形|激活|觉醒|进化|升级|解封|解[锁封])",
     "变形"),
    # 武器进化(刀剑升级 / 法器觉醒)
    (r"(?:武器[升级进化]|法器[觉醒]|神器[现世]|魔剑|神剑)",
     "武器进化"),
]


def detect_appearance_changes(text: str, shot_number: int | None = None,
                              storyboard_id: int | None = None) -> list[dict]:
    """扫描文本里所有外观变化触发词,返回去重后的 [{kind, snippet, shot, storyboard_id, match}]。

    同一种 kind 多次出现只算一次(同一集里同一个角色反复「戴面具」,建一次变体足够);
    snippet 取首次匹配的 30 字上下文,便于变体 label 写人话。
    """
    if not text:
        return []
    found: dict[str, dict] = {}
    for pat, kind, _label_kind in VARIANT_TRIGGERS:
        for m in re.finditer(pat, text):
            if kind in found:
                break                       # 同 kind 不重复
            start = max(0, m.start() - 8)
            end = min(len(text), m.end() + 12)
            snippet = text[start:end].replace("\n", " ").strip()
            found[kind] = {
                "kind": kind,
                "match": m.group(0),
                "snippet": ("…" if start > 0 else "") + snippet
                          + ("…" if end < len(text) else ""),
                "shot": shot_number,
                "storyboard_id": storyboard_id,
            }
            break                          # 同 kind 只记首次匹配
    return list(found.values())


def detect_in_storyboard(storyboard: dict) -> list[dict]:
    """对单条 storyboard 全字段扫描,聚合去重(只走角色类触发词)。

    场景/道具类触发词由 detect_scene_changes / detect_prop_changes 单独跑,
    避免一条分镜既被分类成「角色变化」又被分类成「场景变化」造成变体行重复。
    """
    fields = ["content", "description", "video_prompt",
              "atmosphere", "result", "title"]
    text = "\n".join(str(storyboard.get(f, "") or "") for f in fields)
    return detect_changes(text, CHAR_VARIANT_TRIGGERS,
                          shot_number=storyboard.get("storyboard_number"),
                          storyboard_id=storyboard.get("id"))


def detect_scene_changes(storyboard: dict) -> list[dict]:
    """检测场景类变化(同 kind 去重)。"""
    fields = ["content", "description", "video_prompt", "atmosphere", "result"]
    text = "\n".join(str(storyboard.get(f, "") or "") for f in fields)
    return detect_changes(text, SCENE_VARIANT_TRIGGERS,
                          shot_number=storyboard.get("storyboard_number"),
                          storyboard_id=storyboard.get("id"))


def detect_prop_changes(storyboard: dict) -> list[dict]:
    """检测道具类变化(同 kind 去重)。"""
    fields = ["content", "description", "video_prompt", "atmosphere", "result"]
    text = "\n".join(str(storyboard.get(f, "") or "") for f in fields)
    return detect_changes(text, PROP_VARIANT_TRIGGERS,
                          shot_number=storyboard.get("storyboard_number"),
                          storyboard_id=storyboard.get("id"))


def detect_changes(text: str, triggers: list[tuple[str, str]],
                   shot_number: int | None = None,
                   storyboard_id: int | None = None) -> list[dict]:
    """通用检测:用给定的 triggers 表扫文本,返回 [{kind, snippet, shot, storyboard_id, match}]。"""
    if not text:
        return []
    found: dict[str, dict] = {}
    for pat, kind in triggers:
        for m in re.finditer(pat, text):
            if kind in found:
                break                       # 同 kind 不重复
            start = max(0, m.start() - 8)
            end = min(len(text), m.end() + 12)
            snippet = text[start:end].replace("\n", " ").strip()
            found[kind] = {
                "kind": kind,
                "match": m.group(0),
                "snippet": ("…" if start > 0 else "") + snippet
                          + ("…" if end < len(text) else ""),
                "shot": shot_number,
                "storyboard_id": storyboard_id,
            }
            break                          # 同 kind 只记首次匹配
    return list(found.values())


def find_character_ids_in_text(text: str) -> list[int]:
    """从分镜文字里提取 @名字 → characters.id 列表(简化版:直接匹配 @开头的名字)。

    不做角色级覆盖解析(那是 @resolve 的事),只把 @xxx 当锚点扫一遍,
    没匹配上就交给上层用 episode 关联的所有角色兜底。
    """
    from . import refs as refs_mod
    sb = {"content": text, "description": "", "video_prompt": text}
    return refs_mod.resolve_video_prompt_refs(text, sb)


def ensure_variants_for_storyboard(storyboard: dict, drama_id: int) -> list[int]:
    """扫描一条 storyboard,把所有命中的变化 → 为关联的角色 / 场景 / 道具各建一条变体。

    返回本次新创建的 variant_id 列表(已存在的不计)。
    """
    ep_id = storyboard.get("episode_id")
    if not ep_id:
        return []
    # 1. 角色变体
    char_changes = detect_in_storyboard(storyboard)
    # 该镜关联的角色
    rels = db.q("SELECT character_id FROM storyboard_characters WHERE storyboard_id=?",
                (storyboard["id"],))
    cids = [r["character_id"] for r in rels]
    if not cids:
        # 兜底:集级关联的角色都算
        cids = [r["id"] for r in db.q(
            "SELECT character_id FROM episode_characters WHERE episode_id=?",
            (ep_id,))]
    # 2. 场景变体
    scene_changes = detect_scene_changes(storyboard)
    # 该镜关联的场景(若空 → 兜底用集级关联)
    scenes = db.q("SELECT scene_id FROM storyboard_scenes WHERE storyboard_id=?",
                  (storyboard["id"],))
    sids = [s["scene_id"] for s in scenes]
    if not sids:
        sids = [s["id"] for s in db.q(
            "SELECT scene_id FROM episode_scenes WHERE episode_id=?", (ep_id,))]
    # 3. 道具变体
    prop_changes = detect_prop_changes(storyboard)
    props = db.q("SELECT prop_id FROM storyboard_props WHERE storyboard_id=?",
                 (storyboard["id"],))
    pids = [p["prop_id"] for p in props]
    if not pids:
        pids = [p["id"] for p in db.q(
            "SELECT prop_id FROM episode_props WHERE episode_id=?", (ep_id,))]

    shot = storyboard.get("storyboard_number", 0)
    created: list[int] = []

    for cid in cids:
        for ch in char_changes:
            vid = _ensure_char_variant(cid, ch, shot, drama_id)
            if vid:
                created.append(vid)
    for sid in sids:
        for ch in scene_changes:
            vid = _ensure_scene_variant(sid, ch, shot, drama_id)
            if vid:
                created.append(vid)
    for pid in pids:
        for ch in prop_changes:
            vid = _ensure_prop_variant(pid, ch, shot, drama_id)
            if vid:
                created.append(vid)
    return created


def _ensure_char_variant(character_id: int, change: dict,
                          shot_number: int, drama_id: int) -> int | None:
    """建一条 character_variants(同 label 已有就跳过)。"""
    c = db.q1("SELECT name FROM characters WHERE id=?", (character_id,))
    if not c:
        return None
    label = f"{c['name']} · 镜#{shot_number:02d} · {change['kind']}"
    if db.q1("SELECT id FROM character_variants WHERE character_id=? AND label=?",
             (character_id, label)):
        return None
    costume_desc = (f"{change['match']} —— {change['snippet']}").strip()
    ts = db.now()
    sort_order = (db.q1(
        "SELECT COALESCE(MAX(sort_order),0)+1 n FROM character_variants WHERE character_id=?",
        (character_id,))["n"])
    return db.ex(
        "INSERT INTO character_variants(character_id,label,costume_desc,tags,"
        "is_default,sort_order,created_at) VALUES(?,?,?,?,0,?,?)",
        (character_id, label, costume_desc, "[]", sort_order, ts))


def _ensure_scene_variant(scene_id: int, change: dict,
                          shot_number: int, drama_id: int) -> int | None:
    """建一条 scene_variants(同 label 已有就跳过)。"""
    s = db.q1("SELECT name FROM scenes WHERE id=?", (scene_id,))
    if not s:
        return None
    label = f"{s['name']} · 镜#{shot_number:02d} · {change['kind']}"
    if db.q1("SELECT id FROM scene_variants WHERE scene_id=? AND label=?",
             (scene_id, label)):
        return None
    change_desc = (f"{change['match']} —— {change['snippet']}").strip()
    ts = db.now()
    sort_order = (db.q1(
        "SELECT COALESCE(MAX(sort_order),0)+1 n FROM scene_variants WHERE scene_id=?",
        (scene_id,))["n"])
    return db.ex(
        "INSERT INTO scene_variants(scene_id,label,change_desc,tags,"
        "is_default,sort_order,created_at) VALUES(?,?,?,?,0,?,?)",
        (scene_id, label, change_desc, "[]", sort_order, ts))


def _ensure_prop_variant(prop_id: int, change: dict,
                         shot_number: int, drama_id: int) -> int | None:
    """建一条 prop_variants(同 label 已有就跳过)。"""
    p = db.q1("SELECT name FROM props WHERE id=?", (prop_id,))
    if not p:
        return None
    label = f"{p['name']} · 镜#{shot_number:02d} · {change['kind']}"
    if db.q1("SELECT id FROM prop_variants WHERE prop_id=? AND label=?",
             (prop_id, label)):
        return None
    change_desc = (f"{change['match']} —— {change['snippet']}").strip()
    ts = db.now()
    sort_order = (db.q1(
        "SELECT COALESCE(MAX(sort_order),0)+1 n FROM prop_variants WHERE prop_id=?",
        (prop_id,))["n"])
    return db.ex(
        "INSERT INTO prop_variants(prop_id,label,change_desc,tags,"
        "is_default,sort_order,created_at) VALUES(?,?,?,?,0,?,?)",
        (prop_id, label, change_desc, "[]", sort_order, ts))
