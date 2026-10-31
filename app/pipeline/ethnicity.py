"""人物面孔文化 → 提示词片段(对齐参考项目 backend/src/services/ethnicity.ts)。

三级解析:**角色覆盖 > 项目设置 > 按内容语言推断**;语言未知时回落 east_asian(UI 默认中文)。
片段以英文追加在风格串之后 —— 生图模型对英文的面孔/服饰提示词权重更高。
"""
from __future__ import annotations

from ..core import db

ETHNICITY_OPTIONS = [
    ("auto", "智能匹配"),
    ("east_asian", "东亚"),
    ("middle_eastern", "中东"),
    ("western", "西方"),
    ("south_asian", "南亚"),
    ("latin", "拉美"),
    ("african", "非洲"),
    ("mixed", "混合"),
]

# 语言 → 面孔文化推断表
LANG_TO_ETHNICITY = {
    "zh": "east_asian", "ja": "east_asian", "ko": "east_asian",
    "th": "east_asian", "vi": "east_asian", "id": "east_asian",
    "ar": "middle_eastern", "he": "middle_eastern", "fa": "middle_eastern", "tr": "middle_eastern",
    "en": "western", "de": "western", "fr": "western", "it": "western", "nl": "western",
    "es": "latin", "pt": "latin",
    "hi": "south_asian", "bn": "south_asian", "ur": "south_asian",
}
DEFAULT_ETHNICITY = "east_asian"

# 英文片段:直接进生图提示词
ETHNICITY_FRAGMENT_EN = {
    "east_asian": ("East Asian facial features, East Asian complexion and bone structure, "
                   "natural black hair texture, East Asian wardrobe styling"),
    "middle_eastern": ("Middle Eastern facial features, olive-to-sand complexion, dark brown hair, "
                       "Middle Eastern attire and headwear details where appropriate"),
    "western": ("Western European facial features, fair complexion, natural light brown or blonde "
                "hair, contemporary Western fashion styling"),
    "south_asian": ("South Asian facial features, warm brown complexion, dark hair, "
                    "South Asian wardrobe and fabric styling"),
    "latin": ("Latin American facial features, warm olive-to-tan complexion, dark hair, "
              "Latin American fashion styling"),
    "african": ("Sub-Saharan African facial features, deep brown complexion, natural coiled hair "
                "texture, African textile and wardrobe styling"),
    "mixed": ("Mixed-ethnicity facial features, blended complexion and bone structure, "
              "varied hair texture, contemporary styling"),
}


def resolve_ethnicity(character_id: int | None = None, drama_id: int | None = None,
                      content_lang: str | None = None) -> str:
    """角色覆盖 > 项目设置 > 按内容语言推断。auto/unknown → 推断结果。"""
    if character_id:
        row = db.q1("SELECT ethnicity_override FROM characters WHERE id=?", (character_id,))
        v = (row["ethnicity_override"] if row else "") or ""
        if v and v != "auto":
            return v
    v = ""
    if drama_id:
        row = db.q1("SELECT ethnicity FROM dramas WHERE id=?", (drama_id,))
        v = (row["ethnicity"] if row else "") or ""
    if v and v != "auto":
        return v
    return LANG_TO_ETHNICITY.get((content_lang or "").lower(), DEFAULT_ETHNICITY)


def ethnicity_fragment(ethnicity: str) -> str:
    """返回该面孔文化的英文提示词片段;未识别返回空串。"""
    return ETHNICITY_FRAGMENT_EN.get(ethnicity or "", "")


def append_ethnicity_fragment(prompt: str, ethnicity: str) -> str:
    """幂等追加:已含该片段则跳过。"""
    frag = ethnicity_fragment(ethnicity)
    text = (prompt or "").strip()
    if not frag or not text or frag in text:
        return text
    return f"{text}, {frag}"
