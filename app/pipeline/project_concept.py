# -*- coding: utf-8 -*-
"""新建项目时的「项目说明」:从一句想法生成 项目名称 / 简介 / 创意描述 / 题材。

对齐 Web 版(xiaoshuo)的 `POST /novel/generate-project-concept`:
  - 四种创作目标各有一套「一句话体裁」描述与标题风格提示,同一套 JSON 契约只换口味;
  - 可选参考图:先用视觉模型把图里有什么读出来当事实依据,再与用户对每张图的
    补充说明拼成「硬素材」喂给写稿模型 —— 没配多模态时降级为纯文本起意,不阻断;
  - 输出必须含 title/description/creative_description/genre 四个字段,缺字段就
    带更严格的格式要求重试一次(Web 版实测单次成功率约 7-8 成);
  - JSON 彻底解析不出来时逐字段正则兜底 —— 宁可给残缺结果,别让用户白等。

**不落库**:生成结果先回填新建对话框,用户点「创建项目」才随表单一起提交。
同款复刻(video_clone)不走这里 —— 它的题材来自参考视频拆解,凭空生成会和视频打架。
"""
from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path

from ..agents import prompts, runner
from ..core import db
from ..core.i18n import LANG_OUTPUT_NAME
from ..core.logging_setup import get_logger

log = get_logger(__name__)

# 题材预设(对齐 Web 版 GENRE_PRESETS:常见网文 12 大类)
GENRE_PRESETS: list[str] = [
    "都市言情", "古风言情", "玄幻", "仙侠修真", "武侠", "科幻",
    "末世废土", "悬疑推理", "历史", "同人二次元", "轻小说", "灵异神怪",
]
GENRE_CUSTOM = "__genre_custom__"

# 各创作目标的「一句话体裁」描述与标题风格提示 —— 同一套 JSON 契约,只换口味
CONCEPT_PLAYBOOK: dict[str, dict[str, str]] = {
    "drama": {
        "kind": "短剧(竖屏/横屏剧集,面向投放平台,强钩子、快节奏、每集留悬念)",
        "title_hint": "短剧风格:8-16 字,有强冲突或身份反差,最好带情绪冲击"
                       "(不要写「某某传」这种平铺直叙的写法)",
        "desc_hint": "面向平台投放:突出题材、主角处境、开篇钩子",
    },
    "novel": {
        "kind": "长篇网文(有完整世界观与长线主线,分卷连载)",
        "title_hint": "网文风格:6-14 字,题材词 + 主角定位或核心设定,让人一眼看出爽点类型",
        "desc_hint": "面向长线连载:突出世界观、主角金手指、长期主线与爽点",
    },
    "comic": {
        "kind": "漫画(分镜格叙事,画面驱动,旁白式说明)",
        "title_hint": "漫画风格:6-12 字,视觉化、有画面感",
        "desc_hint": "面向漫画分镜:突出画面基调、格数节奏、旁白风格",
    },
    "promotion": {
        "kind": "宣传·营销文案(抖音小红书视频号/公众号等投放物料)",
        "title_hint": "投放物料风格:像真实爆款标题,有钩子和情绪,可适度夸张",
        "desc_hint": "面向投放:突出目标人群、投放平台、转化钩子",
    },
}
# 同款复刻(video_clone)刻意不在表里:题材来自参考视频拆解,凭空生成会和视频打架。

CONCEPT_FIELDS: tuple[str, ...] = ("title", "description", "creative_description", "genre")

SYSTEM_PROMPT = (
    "你是一位短剧/网文/漫画/投放文案的项目策划。"
    "现在要为用户虚构一个「还不存在的」新项目设定,只输出 JSON。"
)

# 参考图识图用的提问 —— 只描述看得见的东西,别臆测品牌/价格/功效
_VISION_PROMPT = "\n".join([
    "请客观描述这张参考图里有什么,用于后续撰写项目设定与剧本。",
    "按「产品/主体是什么、外观与卖点、场景与氛围、图中出现的文字、画面风格与配色」分条列出。",
    "只描述你确实看见的内容,不要臆测品牌名、价格、功效等画面上读不到的信息。",
    "用中文输出,不要输出 JSON。",
])


def _data_url(path: str | Path) -> str:
    """本地图片 → data URL(多模态端点直读)。"""
    p = Path(path)
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def _extract_fields_loose(raw: str, fields: tuple[str, ...]) -> dict:
    """逐字段正则兜底:JSON 彻底解析不出来时,直接按 "key": "value" 逐个抠字段。

    四种写法依次尝试(越往后越宽松):
        "key": "value"   —— 标准 JSON
        "key": value     —— 键带引号、值是裸文本
        key: "value"     —— 键是裸文本、值带引号
        key: value       —— 全裸文本(模型输出退化时的最后一道防线)
    """
    out: dict = {}
    for f in fields:
        patterns = [
            (re.compile(r'"' + f + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', re.S), True),
            (re.compile(r'"' + f + r'"\s*:\s*([^\n\r,}]{1,600})'), False),
            (re.compile(r'(?:^|[\n\r{,])[ \t]*' + f + r'[ \t]*:[ \t]*"([^"\n\r]*)"', re.I), True),
            (re.compile(r'(?:^|[\n\r{,])[ \t]*' + f + r'[ \t]*:([^\n\r,}]{1,600})', re.I), False),
        ]
        val: str | None = None
        quoted = False
        for rx, is_quoted in patterns:
            m = rx.search(raw or "")
            if not m:
                continue
            val = m.group(1)
            quoted = is_quoted
            break
        if val is None:
            continue
        val = val.strip()
        if not quoted:
            val = val.lstrip("\"'").rstrip("\"'").strip()
        else:
            val = (val.replace("\\n", "\n").replace("\\t", "\t")
                      .replace('\\"', '"').replace("\\\\", "\\"))
        if val:
            out[f] = val
    return out


def _ask_concept_json(prompt: str, *, config_id: int | None, lang: str | None) -> dict:
    """跑一次「项目说明」并保证四个字段齐全。

    为什么不直接 run_agent_json 就完事:它只保证「能解析成 JSON」,不保证
    「字段是我要的那几个」—— 模型偶尔会回一个字段完全不对的合法 JSON。
    所以额外做字段齐全性校验,不齐就带更严格的格式要求重试一次。
    """
    strict = "\n".join([
        "",
        "【格式要求(本次必须严格遵守)】",
        "- 只输出一个 JSON 对象,不要任何解释、前后缀文字或 markdown 代码块。",
        "- 每个字段的值必须写在同一行内,值里面不要出现换行符。",
        "- 必须且只能包含这几个键:" + "、".join(CONCEPT_FIELDS) + "。",
        "",
    ])
    last_err: Exception | None = None
    for attempt in range(2):
        p = prompt if attempt == 0 else prompt + strict
        try:
            data = runner.run_agent_json("project_concept", p, lang=lang,
                                         config_id=config_id,
                                         system=prompts.with_language_suffix(SYSTEM_PROMPT, lang))
        except Exception as e:  # noqa: BLE001 —— 解析失败也是一种「不齐」
            last_err = e
            continue
        if not isinstance(data, dict):
            last_err = RuntimeError("模型输出无法解析为 JSON")
            continue
        missing = [f for f in CONCEPT_FIELDS if not str(data.get(f) or "").strip()]
        if missing:
            last_err = RuntimeError("模型输出缺少字段:" + "、".join(missing))
            continue
        return data
    # 最后一道防线:拿原始输出逐字段抠 —— 宁可给残缺结果,别让用户白等
    try:
        raw = runner.run_agent("project_concept", prompt + strict, lang=lang,
                               json_output=True, temperature=0.4,
                               config_id=config_id,
                               system=prompts.with_language_suffix(SYSTEM_PROMPT, lang))
        # run_agent 带 with_meta 时会返回 (content, meta) 元组,这里不用 meta
        loose = _extract_fields_loose(raw, CONCEPT_FIELDS) if isinstance(raw, str) else {}
        if all(str(loose.get(f) or "").strip() for f in CONCEPT_FIELDS):
            return loose
    except Exception as e:  # noqa: BLE001
        last_err = e
    raise last_err or RuntimeError("生成项目说明失败")


def _read_ref_images(ref_images: list[str], ref_notes: list[str],
                     config_id: int | None) -> list[str]:
    """逐张识图 → 拼成「图 i 的画面事实 + 用户对图 i 的要求」。

    每张图单独识别(而不是一次全传),这样每张图的用户补充说明能精确对上
    它自己的画面。没配多模态 / 读不出来时不阻断 —— 降级为纯文本起意。
    """
    from ..ai import text_client

    blocks: list[str] = []
    for i, path in enumerate(ref_images):
        note = ""
        try:
            raw = text_client.chat(_VISION_PROMPT, temperature=0.2, max_tokens=1024,
                                   config_id=config_id, image_urls=[_data_url(path)])
            note = (raw.strip()[:2000] if isinstance(raw, str) else "")
        except Exception as e:  # noqa: BLE001 —— 识图失败不阻断整体
            log.warning("project_concept.vision_failed index=%s err=%s", i, str(e)[:200])
            note = ""
        user_note = (ref_notes[i] if i < len(ref_notes) else "").strip()
        lines: list[str] = []
        if note:
            lines += [f"【参考图 {i + 1}·画面事实】", note]
        if user_note:
            # 没配视觉模型时这张图识别不出来,如实告诉模型「按用户描述理解」,
            # 别让它假装看见了图(编造画面比不满足要求更糟)
            lines.append(f"【参考图 {i + 1}·用户要求】{user_note}"
                         + ("" if note else "(这张图没能自动识别画面内容,按用户描述理解)"))
        if lines:
            blocks += lines
    return blocks


def generate_project_concept(*, work_type: str, idea: str,
                             ref_images: list[str] | None = None,
                             ref_notes: list[str] | None = None,
                             config_id: int | None = None,
                             lang: str | None = None) -> dict:
    """从一句想法生成 项目名称/简介/创意描述/题材。

    Args:
        work_type:创作目标(drama/novel/comic/promotion);video_clone 不支持。
        idea:用户写的想法(项目名称或一句构想),最多取前 300 字。
        ref_images:可选参考图的本地路径(最多 12 张)。
        ref_notes:与 ref_images 一一对应的「这张图要怎么用」说明。
        config_id:文本模型 config_id;None 走全局默认。
        lang:AI 内容语言;None 走全局内容语言设置。

    Returns:
        {"title","description","creative_description","genre","vision_used"}
    """
    wt = (work_type or "drama").strip()
    if wt not in CONCEPT_PLAYBOOK:
        raise RuntimeError("同款复刻不支持 AI 项目说明:题材来自参考视频拆解,凭空生成会和视频打架")
    seed = (idea or "").strip()[:300]
    if not seed:
        raise RuntimeError("请先写下你的想法")
    playbook = CONCEPT_PLAYBOOK[wt]

    # 内容语言:项目里所有 AI 产出都按这个语言走,别让模型漂回英文
    #
    # "auto" 必须在这里就解析掉:dramas.language 的默认值就是 'auto'(跟随全局),
    # 调用方(asset_dialogs 项目设置)直接传原始列值的话,lang_hint 会变成字符串
    # "auto",提示词变成「所有字段的值用auto输出。」—— 实测过的活 bug。
    # 拿不到 drama_id(新建项目尚未落库)时退回全局设置。
    out_lang = lang or ""
    if out_lang == "auto" or out_lang not in LANG_OUTPUT_NAME:
        out_lang = db.get_setting("content_language", "zh") or "zh"
        if out_lang not in LANG_OUTPUT_NAME:
            out_lang = "zh"
    lang_hint = LANG_OUTPUT_NAME.get(out_lang, out_lang)

    images = [str(p) for p in (ref_images or []) if str(p).strip()][:12]
    notes = [str(n or "") for n in (ref_notes or [])][:12]

    vision_blocks = _read_ref_images(images, notes, config_id) if images else []
    has_user_ref = any(n.strip() for n in notes)

    ask = (f"用户的初步想法(项目名称或一句构想):{seed}" if seed
           else "用户没有给任何限定,请完全自由发挥。")
    lines = [
        "你是一位短剧/网文/漫画项目策划。现在要为用户虚构一个「还不存在的」新项目设定,只输出 JSON。",
        "",
        f"体裁:{playbook['kind']}",
        f"本轮体裁要求:{playbook['title_hint']} / {playbook['desc_hint']}",
        f"用户输入:{ask}",
    ]
    if vision_blocks:
        lines += [
            "",
            "【用户上传的参考图】",
            *vision_blocks,
            "这些图是用户给的硬素材:文案/设定必须贴合画面事实来写,不要描述图里没有的东西。",
        ]
        if has_user_ref:
            lines.append("用户对每张图写的补充要求是硬性要求,必须在项目名/简介/创意描述里体现出来"
                         "(例如要求某场景出现在剧本中,就要在创意描述里写明这个场景会被拍出来)。")
    lines += [
        "",
        "需要你产出四个字段:",
        "- title:项目名称。" + playbook["title_hint"] + "。只给名称本身,不要加书名号、序号或标点装饰。",
        "- description:项目简介,60-120 字,概括题材、主角身份、核心冲突与基调(给下游 AI 提供项目语境)。",
        "- creative_description:创意描述,120-300 字,具体到「谁在什么境遇下遇到/获得了什么、"
        "由此开启什么主线、核心爽点或看点方向」,写陈述句,不要空话套话。",
        "- genre:题材标签,2-6 字(如 都市重生 / 玄幻修仙 / 都市脑洞)。",
        "",
        "硬性要求:四个字段都要与本轮体裁吻合;不要输出与已存在项目雷同的套路;"
        "不要出现「故事简介」「本作」这类元叙述。",
        f"所有字段的值用{lang_hint}输出。",
        "格式要求:只输出一个 JSON 对象,不要解释文字、不要 markdown 代码块;"
        "每个字段的值写在同一行内,值里不要出现换行符。",
        '只输出 JSON:{"title":"...","description":"...","creative_description":"...","genre":"..."}',
    ]
    prompt = "\n".join(lines)

    data = _ask_concept_json(prompt, config_id=config_id, lang=lang)
    return {
        "title": str(data.get("title") or "").strip()[:60],
        "description": str(data.get("description") or "").strip()[:400],
        "creative_description": str(data.get("creative_description") or "").strip()[:2000],
        "genre": str(data.get("genre") or "").strip()[:30],
        "vision_used": any("·画面事实】" in b for b in vision_blocks),
    }
