# -*- coding: utf-8 -*-
"""i18n 主表 Z 的中文基准值必须是**中文**,不能是键名本身。

实测踩过:新增文案时把键名当成了中文基准,结果

    'stockphoto_general_desc': 'stockphoto_general_desc'

`tr()` 查得到这个键,于是原样把键名显示在界面上 ——
表现为"设置页出现一行英文下划线 slug",而不是"缺翻译回退英文"
(后者至少是句能读懂的话,前者完全看不出是漏了什么)。
"""
from __future__ import annotations

import re

from app.core.i18n import Z, tr
from app.core.ui_strings import S

# 允许纯 ASCII/符号的键:品牌名、API 名、格式串这类确实没有中文的说法
_ALLOWED_ASCII = {
    "base_url", "api_key", "system_prompt", "total_dur",
    "jev_svc", "chat_edit_msg_assistant",
}

# 键名本身是 slug 形态(带下划线且全 ASCII)时,如果它的值 == 键名,就是漏填
_SLUG = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")
_HAS_CJK = re.compile(r"[一-鿿　-〿＀-￯]")


def test_no_key_used_as_its_own_chinese_baseline():
    bad = []
    for k, v in Z.items():
        if k in _ALLOWED_ASCII:
            continue
        if not _SLUG.match(str(k)):
            continue
        if str(v).strip() == str(k).strip():
            bad.append(k)
    assert not bad, f"这些键把键名当成了中文基准,界面会直接显示键名:{bad}"


def test_cjk_bases_actually_contain_cjk():
    """值为中文的键必须真的含汉字,防止误把英文/占位写进基准。"""
    bad = []
    for k, v in S.items():
        if len(v) != 15:
            bad.append((k, f"翻译条数 {len(v)} ≠ 15"))
            continue
        if k in _ALLOWED_ASCII:
            continue
        # 第 0 项是中文基准:不含任何 CJK 且长得像 slug 的,一定是键名没填
        if not _HAS_CJK.search(v[0]) and _SLUG.match(v[0]):
            bad.append((k, f"中文基准是 slug:{v[0]!r}"))
    assert not bad, f"以下键的翻译有问题:{bad}"


def test_new_stockphoto_keys_render_chinese():
    """本轮新增的图库/换画风文案必须真的显示中文。"""
    for k in ("stockphoto_general_desc", "stockphoto_svc"):
        assert _HAS_CJK.search(tr(k)), f"{k} 界面上不是中文:{tr(k)!r}"
        assert Z[k] == S[k][0], f"{k} 的 Z 基准与 S 第 0 项不一致"
