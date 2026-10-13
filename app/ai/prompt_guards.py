# -*- coding: utf-8 -*-
"""平台级提示词质量守卫(对齐参考项目 backend/src/services/prompt-guards.ts)。

在生成服务层(image_client / video_client)统一追加,不依赖 Agent 是否记得写,
覆盖全部入口(分镜帧 / 资产图 / 漫画格 / 小说插画、单集与批量视频),
**对已存库的旧提示词同样生效**。

- 图片:手部 / 肢体 / 人物完整性 / 表情克制 / 画面纯净
- 视频:肢体完整性 + 表演克制 + 节奏约束;视频模型对肢体畸形与强情绪词都天生放大,需平台层压住

分镜/漫画提示词无需自己写这些要求;极端剧情需要爆发时,在分镜 video_prompt 里显式写
「情绪爆发」即可覆盖表演守卫。

设计要点(与原版一致):
- **marker 幂等**:已含同类 marker 时跳过 → 重试复用存储提示词不会重复追加;
- **空提示词不追加**:纯参考素材驱动的生成不凭空引入文本;
- **中英双语**:中文约束 + 英文 negative token(DALL-E / Seedream / Agnes 对英文负面词权重更高);
- **按人数自适应**:people=1 强调「恰好一人」,people>1 改为「恰好 N 人、不得增删」——
  否则双人格子会收到「只许一个人」的自相矛盾指令,模型可能随机删掉第二个角色。
"""
from __future__ import annotations

IMAGE_MARKER = "画面质量要求"
VIDEO_MARKER = "视频质量要求"
PERFORMANCE_MARKER = "表演要求"
PACING_MARKER = "节奏要求"

# 肢体完整性守卫(图与视频共用):视频模型在动态帧里更容易出现手部畸变、肢体分裂重组、人物数量漂移
BODY_INTEGRITY_GUARD = (
    "肢体完整性：手部五指、脚部五趾，没有六指、并指、缺指或融合畸形；两臂两腿，没有三只手三条腿、"
    "多余肢体、复制或扭曲；每人身体只有一颗头、一张脸，没有双头、两头连体身，躺卧人物的床头床尾也没有"
    "多出的第二颗头；人物数量稳定，没有重影、分身或多人复制；连续帧中同一人物身体不分裂、不重组、不融化，"
    "五官与肢体保持一致"
)

# 单人物负面词:positive 强调人物数量约束,negative 显式列出禁止出现的「额外人类」。
# 绝大多数出图模型原生支持 negative_prompt,命中后权重远高于在 positive 末尾追加同类描述。
IMAGE_NEGATIVE_GUARD = (
    "multiple people, second person, extra person, bystander, onlooker, crowd, audience, "
    "duplicate character, copy of subject, second copy, doppelganger, ghostly double, "
    "transparent figure in background, blurred person watching, mannequin, silhouette in mist, "
    "extra heads, crowd in background, friends standing behind, coworkers watching"
)

# 视频质量守卫:肢体之外覆盖视频侧高发伪结构 —— 背景围观路人、被褥家具下多出的肢体、
# 服装发型跨帧漂移、角色间换脸融合、字幕水印、把角色三视图当构图模板照抄成「多视角站桩设定图」
# (绑三视图参考图时的高发病)。躺卧构图是「双头」伪结构高发场景,单独点名。
VIDEO_QUALITY_GUARD = (
    f"视频质量要求：{BODY_INTEGRITY_GUARD}"
    "；这是真实电影拍摄场景：同一人物在画面中只出现一次，不是角色三视图、多视角设定图或拼版，"
    "没有同一人物并排站立的多个副本"
    "；画面里只出现提示词提到的人物，背景与门窗外没有路人围观或走动"
    "；被褥、床铺、桌椅下方没有多出的手臂、腿或身体；同一人物的发型、服装、配饰与随身道具在整段视频中"
    "保持一致，不与参考图里的其他角色换脸或融合五官"
    "；画面纯净，没有字幕、标题、水印、台标与 logo"
    "；cinematic live scene, single appearance of each character, no character turnaround sheet, "
    "no multi-view lineup, no side-by-side duplicates of the same person, one head per body, "
    "no extra limbs under blankets, no onlookers in background, consistent outfit across frames"
)

# 表演守卫:压住模型对强情绪词(尖叫/嘶吼/痛哭)的放大,受惊降级为微反应
VIDEO_PERFORMANCE_GUARD = (
    "表演要求：人物表演自然克制，对话用日常语气与日常音量，没有尖叫嘶吼、大呼小叫、放声痛哭；"
    "受惊用微反应表现（僵住、瞳孔一缩、倒吸气），表情与动作幅度贴近真实生活，没有一惊一乍"
)

# 节奏守卫:禁慢动作与长时间静止凝视;整段在同一场景内连续拍摄,不乱切场景
VIDEO_PACING_GUARD = (
    "节奏要求：正常速度叙事，不使用慢动作，没有长时间的静止凝视或定格，动作连贯有推进；"
    "整段视频在提示词描述的同一场景内连续拍摄，不插入无关的场景切换或转场"
)

# 空提示词不追加;已含同类守卫时幂等跳过
def _append_guard(prompt: str, guard: str, marker: str) -> str:
    trimmed = (prompt or "").strip()
    if not trimmed:
        return trimmed
    if marker in trimmed:
        return trimmed
    return f"{trimmed}，\n{guard}"


def _n_people(people: int | None) -> int:
    """人物数归一。**0 必须原样保留** —— 场景空镜/道具单品传的就是 0。

    早期写的是 max(1, int(people or 1)),把 0 抬成 1,于是空镜提示词里追加的
    变成「画面中只有 1 个人」,等于命令模型往会议室里塞一个人。
    """
    try:
        return max(0, int(people))
    except (TypeError, ValueError):
        return 1


def build_image_quality_guard(people: int = 1) -> str:
    """图片质量守卫:肢体完整性 + 表情克制 + 画面纯净 + 按人数自适应的构图约束。"""
    people = _n_people(people)
    if people == 0:
        figure_cn = ("画面中不出现任何人物,也没有人物的手、身体、影子或倒影,"
                     "画面里只有场景或道具本身")
        figure_en = ("Empty scene: no people at all in frame, no human figures, no silhouettes, "
                     "no reflections of people, no crowd in background, no hands, no body parts, "
                     "just the location or the object itself, atmospheric and undisturbed")
    elif people > 1:
        figure_cn = (f"画面人物恰好 {people} 人,不得多于或少于 {people} 人,"
                     "没有围观群众或复制人,没有重影、分身")
        figure_en = (f"Exactly {people} people in frame, no onlookers, no extras, no bystanders, "
                     "no background silhouettes of people, no crowd, "
                     f"no additional figures beyond the {people} characters, "
                     "no duplicate character, no blurred figures watching")
    else:
        figure_cn = "画面中自始至终只有 1 个人(主角本人),背景、远景、雾气和倒影里都没有任何其他人"
        figure_en = ("Single-figure composition: exactly one person in frame, no onlookers, "
                     "no extras, no bystanders, no background silhouettes of people, no crowd, "
                     "no ghostly doppelganger in mist, no duplicate character, "
                     "no blurred figures watching, no second copy of the subject in the background "
                     "or periphery")
    return (
        "画面质量要求：手部五指、脚部五趾，没有六指、并指、缺指或融合畸形；两臂两腿，"
        f"没有三只手三条腿、多余肢体、复制或扭曲；{figure_cn},五官稳定不畸变、不融化；"
        "表情自然克制，没有大张嘴嘶吼、面部扭曲的夸张表情；"
        "画面纯净，没有字幕、文字、标题、水印、字母，没有真实品牌标志与真人明星脸。"
        f"{figure_en}, no wide-open screaming mouth, no exaggerated distorted facial expression"
    )


def build_image_negative_guard(people: int = 1) -> str:
    """图片负面词。多人物时必须去掉 second person / multiple people,否则会把剧情需要的第二个角色禁掉。

    people=0 是空镜/道具:必须换成「禁一切人」的词表,不能沿用单人物那一档 ——
    单人物那档只禁「多余的人」,把人放进来反而是合规的。
    """
    people = _n_people(people)
    if people == 0:
        return (
            "people, person, men, women, man, woman, human, human figure, face, portrait, head, "
            "child, worker, employee, staff, passerby, crowd, audience, bystander, onlooker, "
            "silhouette of a person, shadow of a person, reflections of people, people in background, "
            "hands, arms, body parts, mannequin, human statue, group photo"
        )
    if people > 1:
        return (
            f"person beyond the {people} characters, extra figure, onlooker, bystander, crowd, audience, "
            "duplicate character, copy of subject, doppelganger, ghostly double, "
            "transparent figure in background, blurred person watching, mannequin, silhouette in mist, "
            "extra heads, crowd in background, friends standing behind, coworkers watching"
        )
    return IMAGE_NEGATIVE_GUARD


def apply_image_quality_guard(prompt: str, people: int = 1) -> str:
    """图片提示词统一追加质量守卫(幂等)。"""
    return _append_guard(prompt, build_image_quality_guard(people), IMAGE_MARKER)


def apply_video_guards(prompt: str) -> str:
    """视频提示词统一追加质量 + 表演 + 节奏三层守卫(各自 marker 独立幂等)。"""
    out = _append_guard(prompt, VIDEO_QUALITY_GUARD, VIDEO_MARKER)
    out = _append_guard(out, VIDEO_PERFORMANCE_GUARD, PERFORMANCE_MARKER)
    return _append_guard(out, VIDEO_PACING_GUARD, PACING_MARKER)


def comic_people_prefix(people: int) -> str:
    """漫画格人物数硬前缀(对齐参考项目 routes/comic.ts:211-212)。"""
    people = max(1, int(people or 1))
    if people > 1:
        return (f"画面中恰好 {people} 个人物,背景空无一人,没有围观者。"
                f"Exactly {people} characters, no bystanders, no onlookers, no crowd.")
    return ("画面中恰好 1 个人物,背景空无一人,没有围观者。"
            "Exactly one character, no bystanders, no onlookers, no crowd.")