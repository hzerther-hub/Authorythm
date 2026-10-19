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
CAMERA_MARKER = "镜头要求"
CONSISTENCY_MARKER = "一致性要求"
# 参考图锁的 marker:幂等关键字,二次调用不重复追加
REFERENCE_LOCK_MARKER = "参考图外貌锁定"

# 肢体完整性守卫(图与视频共用):视频模型在动态帧里更容易出现手部畸变、肢体分裂重组、人物数量漂移
BODY_INTEGRITY_GUARD = (
    "肢体完整性：手部五指、脚部五趾，没有六指、并指、缺指或融合畸形；两臂两腿，没有三只手三条腿、"
    "多余肢体、复制或扭曲；每人身体只有一颗头、一张脸，没有双头、两头连体身，躺卧人物的床头床尾也没有"
    "多出的第二颗头；人物数量稳定，没有重影、分身或多人复制；连续帧中同一人物身体不分裂、不重组、不融化，"
    "五官与肢体保持一致"
)

# 单人物负面词:positive 强调人物数量约束,negative 显式列出禁止出现的「额外人类」。
# 绝大多数出图模型原生支持 negative_prompt,命中后权重远高于在 positive 末尾追加同类描述。
# 实际场景:模型最爱往「窗户/门/远景/画面边缘/模糊背景」塞人 —— 「bystander」拦不下,
# 必须把具体藏人位置一一列名,实测有效把 5+ 个路人砍回到 1。
IMAGE_NEGATIVE_GUARD = (
    "multiple people, second person, extra person, bystander, onlooker, crowd, audience, "
    "duplicate character, copy of subject, second copy, doppelganger, ghostly double, "
    "transparent figure in background, blurred person watching, mannequin, silhouette in mist, "
    "extra heads, crowd in background, friends standing behind, coworkers watching, "
    "people in background, people in distance, people in doorway, people in window, "
    "people at edges of frame, people in periphery, blurry figures in background, "
    "out-of-focus person behind, face visible through window, person standing behind glass"
)

# 角色「形象图/三视图」白底守卫 —— 公共词表里没有背景条目,形象图生成点共用
# 这一份(经 extra_negative 追加,不覆盖公用负面词)。
# 为什么要压制:最终提示词开头的风格前缀带 creamy bokeh / soft warm lighting,
# 实测会把纯白背景画成彩色虚化、还会把「正面脸部特写」挤出构图 —— 参考图与
# 换脸链路对纯色背景最稳,必须双向压制(正向后缀 + 负面词)。
# 只给形象图用:漫画格/场景里的角色需要环境,**不要**带到剧情画面生成。
CHARACTER_SHEET_PROMPT_SUFFIX = (
    ", pure white seamless studio background (#FFFFFF), flat even front lighting, "
    "no bokeh, no depth of field, no colored or gradient background"
)
CHARACTER_SHEET_NEGATIVE = (
    "colored background, gradient background, bokeh, pastel background, "
    "environment, scenery, interior"
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
    # 产品侧:带货/复刻是本项目的视频主场景,产品变形是最高频的翻车点。
    # 参照 video-clone-lite/references/seedance-knowledge.md 第六节负面词模板补入
    # 「产品无穿模无变形 / 颜色校准无偏色」与画面稳定项(该文件列的 jittery motion、
    # physics error 在跨帧视频里的权重高于纯画质词)
    "；产品外形 1:1 还原参考图,没有穿模、变形、融化或忽大忽小,颜色与实物一致无偏色"
    "；画面稳定,没有抖动、闪烁、重影或忽明忽暗"
    "；画面纯净，没有字幕、标题、水印、台标与 logo"
    "；cinematic live scene, single appearance of each character, no character turnaround sheet, "
    "no multi-view lineup, no side-by-side duplicates of the same person, one head per body, "
    "no extra limbs under blankets, no onlookers in background, consistent outfit across frames, "
    # 英文负面 token 对多数平台权重高于中文同义词(见 AGENTS.md 供应商能力差异一节)
    "low quality, blurry, deformed, mutated hands, extra limbs, bad anatomy, jittery motion, "
    "physics error, face distortion, clothing glitch, watermark, text, logo, "
    "no extra fingers, no asymmetrical features, product deformation, color shift"
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
        figure_cn = ("画面中自始至终只有 1 个人(主角本人),背景、远景、雾气和倒影里都没有任何其他人,"
                     "窗户、门口、画面边缘和模糊背景里也不出现任何人脸或人形")
        figure_en = ("Single-figure composition: exactly one person in frame, no onlookers, "
                     "no extras, no bystanders, no background silhouettes of people, no crowd, "
                     "no ghostly doppelganger in mist, no duplicate character, "
                     "no blurred figures watching, no second copy of the subject in the background "
                     "or periphery, no face visible through window, no person in doorway, "
                     "no one standing at the edges or behind the main character")
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
            "ghost figure, ghost copy, ghost in background, transparent figure, transparent body, "
            "translucent figure, semi-transparent person, faded silhouette, "
            "second copy of same character, mirror image of character, "
            "blurred person watching, mannequin, silhouette in mist, "
            "extra heads, crowd in background, friends standing behind, coworkers watching, "
            # 用户实测:模型最喜欢在「窗户 / 门 / 远景 / 画面边缘 / 模糊背景」里塞
            # 路人 —— 单写 bystander 拦不下,得把「具体藏人位置」点名禁掉。
            # 这条加在多人分支,挡住 2 人 → 5 人 这种扩散。
            "people in background, people in distance, people in doorway, "
            "people in window, people at edges of frame, people in periphery, "
            "blurry figures in background, out-of-focus person behind, "
            "no character turnaround sheet in background, no reference photo in scene"
        )
    return IMAGE_NEGATIVE_GUARD


# 参考图外貌锁定 —— 任何带 reference_images 的生图都会自动追加。
# 实测不写这句时,模型把参考图当装饰,自己脑补人物外貌(用户截图里:
# sb 60 绑了陈默参考图,出图却是穿 POLO 的少年,跟"带工牌的中年"完全不像)。
# 提到 image_client 底层:任何用 image_client.generate_image 的调用方(分镜首帧、
# 资产形象、聊天改图、漫画格……)都自动受益,不用每个调用方自己拼。
REFERENCE_LOCK_GUARD = (
    "参考图外貌锁定:本图随附的参考图 N 必须严格作为画面里人物 N 的外貌来源 —— "
    "五官、发型、体型、年龄、服装、配饰、工牌/背包/伤痕/痣等所有人物特征,均按参考图 N 的实样。"
    "禁止模型自由创作或脑补人物外貌;不要重新设计或修改形象。"
)


def apply_image_quality_guard(prompt: str, people: int = 1) -> str:
    """图片提示词统一追加质量守卫(幂等)。"""
    return _append_guard(prompt, build_image_quality_guard(people), IMAGE_MARKER)


# 镜头语言守卫(对齐 Agnes 官方「提示词建议」第 3 项:镜头语言)。
# 官方把「推拉摇移跟、固定镜头、景别」列为独立一项 —— 不显式写,视频模型默认
# 固定机位 + 中景,短剧最需要的近景/过肩/跟拍就出不来。
VIDEO_CAMERA_GUARD = (
    "镜头要求：镜头运动与景别按提示词描述执行，没有指定时使用自然的跟随或缓慢推进；"
    "人物说话时保持面部清晰可见的双人过肩或近景，不做无意义的大幅甩镜与快速变焦"
)

# 一致性守卫(对齐官方建议第 6 项:一致性要求)。
# 视频模型跨帧最容易漂的就是人物相貌与场景陈设,而本项目每个镜头都绑了角色
# 参考图(keyframe 模式下首帧已做身份锁定,这里说的是**运动过程中**不许漂)。
VIDEO_CONSISTENCY_GUARD = (
    "一致性要求：人物的五官、发型、体型、服装与随身道具在整段视频中保持不变，"
    "不发生换脸、换装或年龄漂移；场景的陈设、材质与光照方向保持一致；"
    "首帧与末帧属于同一时空的同一次连续拍摄"
)


def apply_video_guards(prompt: str) -> str:
    """视频提示词统一追加质量 + 表演 + 节奏 + 镜头 + 一致性五层守卫
    (各自 marker 独立幂等)。

    后两层对齐 Agnes 官方「提示词建议」的六段结构 —— 原先只有前三层,官方明确
    单列的「镜头语言」与「一致性要求」两段缺失,视频模型拿不到就按默认固定机位
    中景出片,且运动中的人物外貌会漂。
    """
    out = _append_guard(prompt, VIDEO_QUALITY_GUARD, VIDEO_MARKER)
    out = _append_guard(out, VIDEO_PERFORMANCE_GUARD, PERFORMANCE_MARKER)
    out = _append_guard(out, VIDEO_PACING_GUARD, PACING_MARKER)
    out = _append_guard(out, VIDEO_CAMERA_GUARD, CAMERA_MARKER)
    return _append_guard(out, VIDEO_CONSISTENCY_GUARD, CONSISTENCY_MARKER)


def comic_people_prefix(people: int) -> str:
    """漫画格人物数硬前缀(对齐参考项目 routes/comic.ts:211-212)。"""
    people = max(1, int(people or 1))
    if people > 1:
        return (f"画面中恰好 {people} 个人物,背景空无一人,没有围观者。"
                f"Exactly {people} characters, no bystanders, no onlookers, no crowd.")
    return ("画面中恰好 1 个人物,背景空无一人,没有围观者。"
            "Exactly one character, no bystanders, no onlookers, no crowd.")