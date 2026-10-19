# -*- coding: utf-8 -*-
"""角色 appearance / styling 的软件层统一规格:规则注入 + 确定性校验 + 定向补写。

问题不是"模型不会写",而是软件层没有兜住(实测:drama 13 的 13 个角色
appearance 全在 45~68 字,而 extractor.md 要求 >=150 字且五官逐项):
  1. workspace/prompts/extractor.*.md 的 15 个语言变体里,只有 zh / en 两份
     写了「appearance >=150 字、每项可画」;其余 13 种语言完全没有这条;
  2. 提示词只是软约束  extractor / novel / book_import / 手工新增 四条写库
     链路在 INSERT 前都没有任何校验,68 字的逗号串照样落库;
  3. 下游 prompts_gen.character_prompt() 把该字段原样拼进出图提示词,
     写不细 = 出图没细节,且跨镜不稳定。
所以规格必须放在代码里,由本模块统一注入 / 统一校验 / 统一补写,不再靠 15 份
markdown 各自维护(人维护 15 份必然漂移,这次就是活证据)。

设计约束:
   audit() 必须**确定性、零网络**,方便测试与批量预检;
   expand_many() 只对不达标的角色发**一次**批量调用,全部达标时零成本;
   任何失败(未配模型 / 超时 / 解析失败 / 模型越改越短)一律**原样返回**,
    绝不阻断资产提取、小说策划、导入、出图这些主流程。
"""
from __future__ import annotations

import json

from ..agents import runner
from ..core import db

# 硬下限。appearance 取 extractor.md 的 150 字口径;styling 原文没给数字,
# 但要求「逐件列出服装 + 颜色 + 材质 + 穿着方式 + 配饰 + 使用痕迹」,80 字是
# 能容纳这些要素的最低值(低于它的样本实测都只写了「白衬衫黑西裤」一句)。
MIN_APPEARANCE = 150
MIN_STYLING = 80

# 同一份规格的中英两版:zh 系语言给中文,其余给英文。**不按 15 种语言各写一份** 
# 规格是给模型看的约束,不是 UI 文案,中英已足够,避免再造 15 份会漂移的副本。
RULES_ZH = """
【角色外观规格(硬性,写库前会校验)】
appearance 与 styling 会**原样**进入出图提示词,写不细就出不来细图。
- appearance 不少于 150 字,必须是连贯散文,**禁止**写成逗号/顿号关键词串
  ("瘦高微驼、黑眼圈明显、方框眼镜"这种短串不合格)。
- 体型:身高 + 体型 + 姿态成因(如"中等身高,偏瘦但不单薄,长年伏案让肩线略松")。
- 面部:脸型轮廓 -> 眉形 / 眼窝 / 眼皮 / 瞳仁 / 鼻梁 / 唇形 / 嘴角 / 下颌线,
  每项都要有**能画出来的具体形态**;允许"普通"这类写实说法,但不能只给评价词。
- 肤质肤色:肤色基调 + 局部特征(暗沉、痘印、胡茬、油光、疲态)。
- 发型:长度 + 发型 + 发质 + 走向与额前碎发。
- 表情神态:写明惯常神情,默认中性克制。
- 文学比喻可以保留,但**必须紧跟可画的具体形态**(例:"微笑像折叠刀"要写成
  "仅单侧嘴角上提,眼轮匝肌不收缩,笑意不达眼底"),否则图像模型会把比喻当真物体。
- styling 不少于 80 字:自上而下逐件写服装、颜色、材质、穿着方式(袖口/腰线/下摆)、
  鞋袜配饰、随身物,以及使用痕迹(褶皱、磨损、旧化)。
- 信息不足时,按角色的年龄 / 身份 / 职业 / 处境**合理补全**到上述颗粒度,
  不要因为原文只写"中年程序员"就输出五个词的压缩串。
""".strip()

RULES_EN = """
[Character appearance spec  enforced before DB write]
appearance and styling are copied verbatim into the image prompt; vague text = vague image.
- appearance must be at least 150 characters of continuous prose. NEVER output a
  comma/顿号-separated keyword list ("tall, thin, glasses, tired" is invalid).
- Body: height + build + why the posture looks that way.
- Face: face shape -> brows / eye sockets / eyelids / pupils / nose bridge / lips /
  mouth corners / jawline, each with a drawable concrete shape. "Ordinary" is allowed
  only if you also describe the actual features.
- Skin: base tone + local features (dullness, marks, stubble, shine, fatigue).
- Hair: length + style + texture + direction and stray strands at the forehead.
- Expression: habitual look, neutral and restrained by default.
- Literary metaphors may stay, but MUST be followed by drawable micro-features
  (e.g. "smiles like a folding knife" must become "only one mouth corner lifts,
  orbicularis oculi does not contract, smile never reaches the eyes"); otherwise an
  image model will render the knife as a real object.
- styling must be at least 80 characters: every garment top-to-bottom, colour,
  material, how it is worn (cuffs/waist/hem), shoes, accessories, carried items,
  plus wear marks (creases, scuffs, fading).
- If the source is thin, infer from age / identity / occupation / situation up to
  this granularity. Never compress into five words.
""".strip()


def rules_for(lang: str | None = None) -> str:
    """返回该语言应追加的规格块(zh 系给中文,其余给英文)。"""
    code = (lang or "zh").lower()
    return RULES_ZH if code.startswith("zh") else RULES_EN


# 分隔符:顿号 / ASCII 逗号 / 分号是"关键词串"的强信号;中文逗号「，」在正常
# 散文里也大量出现,不能单凭它判定。
_LIST_SEPS = "、,;；"
_SENT_END = "。.!?！？"


def _looks_like_keyword_chain(text: str) -> bool:
    """判断是否"逗号关键词串":分段多且每段短,且整段没有句末标点。

    实测样本「33岁前呈现25岁面容，鹅蛋脸，眉眼锐利带倦意，，微笑时像一把
    折叠刀」= 8 段 / 平均 7.6 字 / 无句号 -> 判为关键词串。正常散文有句号,
    且分句明显更长,不会误伤。
    """
    t = (text or "").strip()
    if not t or any(ch in t for ch in _SENT_END):
        return False
    parts = [p.strip() for p in t.replace("，", "、").split("、") if p.strip()]
    if len(parts) < 5:
        return False
    return (sum(len(p) for p in parts) / len(parts)) < 10


def audit(appearance: str | None, styling: str | None,
          name: str = "") -> list[str]:
    """确定性校验,返回问题列表(空列表 = 达标)。零网络、零副作用。"""
    ap = (appearance or "").strip()
    st = (styling or "").strip()
    issues: list[str] = []
    if len(ap) < MIN_APPEARANCE:
        issues.append(f"appearance 仅 {len(ap)} 字(要求 >={MIN_APPEARANCE})")
    if _looks_like_keyword_chain(ap):
        issues.append("appearance 是逗号关键词串,不是连贯散文")
    if len(st) < MIN_STYLING:
        issues.append(f"styling 仅 {len(st)} 字(要求 >={MIN_STYLING})")
    return issues


def needs_work(char: dict) -> bool:
    return bool(audit((char or {}).get("appearance"), (char or {}).get("styling")))


_REPAIR_SYSTEM = (
    "{rules}\n\n"
    "【输出】只输出一个 JSON 对象,不要解释、不要 Markdown 代码块、不要任何工具调用:\n"
    '{{"characters":[{{"name":"","appearance":"","styling":""}}]}}'
)


def _repair(characters: list[dict], *, config_id: int | None,
            lang: str | None) -> list[dict]:
    """一次批量补写。只传不达标的角色,已有内容作为素材一起给模型。"""
    payload = [{
        "name": str(c.get("name") or "").strip(),
        "role": str(c.get("role") or c.get("role_type") or "").strip(),
        "appearance": str(c.get("appearance") or "").strip(),
        "styling": str(c.get("styling") or "").strip(),
    } for c in characters]
    user = (
        "按规格重写下列角色的 appearance 与 styling。已有文字只作素材:保留其中"
        "可用信息,补全缺失的五官/体型/肤质/发型/服装细节;不要新增剧情,不要写"
        "镜头语言,不要改变角色身份。\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    data = runner.run_agent_json(
        "extractor", user, lang=lang, config_id=config_id,
        system=_REPAIR_SYSTEM.format(rules=rules_for(lang)),
    )
    got = data.get("characters") if isinstance(data, dict) else None
    return [c for c in (got or []) if isinstance(c, dict)]


def expand_many(characters, *, config_id: int | None = None,
                lang: str | None = None, persist: bool = False,
                drama_id: int | None = None) -> list[dict]:
    """把不达标的角色补写到规格;失败时原样返回(绝不阻断主流程)。

    persist=True 且有 drama_id 时回写数据库(仅回写确实变长的字段)。
    """
    chars = [dict(c) for c in (characters or []) if isinstance(c, dict)]
    todo = [c for c in chars if needs_work(c)]
    if not todo:
        return chars
    try:
        fixed = _repair(todo, config_id=config_id, lang=lang)
    except Exception as exc:  # noqa: BLE001  补写是增强,失败不能拖垮提取/策划
        print(f"[character_spec] 补写失败,保留原值: {str(exc)[:160]}", flush=True)
        return chars
    by_name = {str(c.get("name") or "").strip(): c for c in fixed}
    changed: list[dict] = []
    for c in chars:
        got = by_name.get(str(c.get("name") or "").strip())
        if not got:
            continue
        for key in ("appearance", "styling"):
            new = str(got.get(key) or "").strip()
            old = str(c.get(key) or "").strip()
            # 只接受"更完整"的结果:模型偶尔会把详细描述改短,不能让它越改越差
            if new and len(new) >= len(old):
                c[key] = new
        if needs_work(c):
            print(f"[character_spec] 仍不达标: {c.get('name')} "
                  f"{audit(c.get('appearance'), c.get('styling'))}", flush=True)
        else:
            changed.append(c)
    if persist and drama_id and changed:
        ts = db.now()
        for c in changed:
            cid = c.get("id")
            if cid:
                db.ex("UPDATE characters SET appearance=?,styling=?,updated_at=? WHERE id=?",
                      (c.get("appearance") or "", c.get("styling") or "", ts, cid))
    return chars


def ensure_for_prompt(row, *, config_id: int | None = None,
                      lang: str | None = None) -> tuple[str, str]:
    """出图前兜底:老数据不达标就补写并回写,返回 (appearance, styling)。

    这是给**库里已经存成 45~70 字**的历史角色用的  不必人工逐个重写,
    下次生成 final_prompt 时自动补全。任何失败都返回原值。
    """
    if not isinstance(row, dict):
        row = dict(row or {})
    ap = str(row.get("appearance") or "").strip()
    st = str(row.get("styling") or "").strip()
    if not audit(ap, st):
        return ap, st
    cid = row.get("id")
    try:
        one = {"id": cid, "name": row.get("name") or "",
               "appearance": ap, "styling": st}
        fixed = expand_many([one], config_id=config_id, lang=lang,
                            persist=True,
                            drama_id=row.get("drama_id"))
        got = fixed[0] if fixed else one
        return (str(got.get("appearance") or ap).strip(),
                str(got.get("styling") or st).strip())
    except Exception as exc:  # noqa: BLE001
        print(f"[character_spec] 出图前补写失败,用原值: {str(exc)[:160]}", flush=True)
        return ap, st
