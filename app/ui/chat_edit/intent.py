# -*- coding: utf-8 -*-
"""聊天修图抽屉的意图解析:纯函数集,不 import Qt。

把 `chat_edit_drawer.py` 第 1-410 行的意图/路由/帮助文案全部抽到这里,
`tests/test_chat_intent.py` 直接 import 测试,无需 monkeypatch Qt 上下文。

依赖:
- `re` / `typing` 标准库
- `app.ai.text_client`(LLM 提取图片搜索关键词,可选)
- `app.ai.jev_client`(Jev 路由兜底,可选)
- `app.ai.photocraft_bridge._strip_reasoning`(剥推理块)

不在本文件:
- 任何 Qt 控件
- 任何数据库访问
- 任何 IO
"""
from __future__ import annotations

import re


# 路由结果常量(对外暴露,业务逻辑判断走这些)
INTENT_EDIT = "edit"
INTENT_CHAT = "chat"
INTENT_KNOWLEDGE = "knowledge"        # 问图片处理知识(与当前图无关)→ web 搜索后作答
INTENT_FIND_PHOTO = "find_photo"      # 想找/搜一张新图 → 弹图库搜索,预填关键词
INTENT_WEB_QUERY = "web_search"       # 显式要求联网查资料(查火车/查天气)→ web 搜索后作答
KNOWN_INTENTS = (INTENT_EDIT, INTENT_CHAT, INTENT_KNOWLEDGE, INTENT_FIND_PHOTO,
                 INTENT_WEB_QUERY)


# JEV 路由打分模板:聊天 vs 改图 vs 知识 vs 找图 vs 联网
JEV_INTENT_QUESTIONS = {
    "intent": {
        "type": "choice",
        "instructions": "用户想让 chat-edit 助手做什么?",
        "criteria": {
            "edit": "用户想修改这张图片(改色/裁剪/滤镜/加水印/去字/扩图等)",
            "chat": "用户想问当前这张图片的内容,或要对它点评/要建议",
            "knowledge": "用户问图片处理的知识/概念/参数建议,与当前这张图无关(如:什么是高斯模糊、锐化和磨皮的区别)",
            "find_photo": "用户想找/搜一张新的图片素材(如:我想找一张美女图片、搜一张雪山风景图)",
            "web_search": "用户要求联网查询资料,与图片无关(如:查宁波到淄博的火车、打开web查询天气)",
        },
    },
}


def parse_jev_intent(res: dict | None) -> str:
    """从 decide() 的返回里取意图;取不到/不认识一律 edit(软建议器契约)。

    **answer 是对象不是字符串**:`answers.intent` 的真实形态是
    `{"type": "choice", "choice": "chat", "confidence": 1.0, "probabilities": {...}}`
    (实测本机 Jev 对「这张图片是什么内容?」返回 choice=chat、置信度 1.0)。
    之前直接 `str(answer)` 跟 "chat" 比 —— 一个 dict 的字符串永远不等于
    "chat",于是**每条消息都被判成 edit,聊天分支从上线起就是死代码**,
    问图内容也进改图引擎,产出不了新图就回「未能执行」。这与 AGENTS.md
    记过的视频路由同款坑(choice 的答案在 `choice` 字段,不在外层)。
    """
    answer = (res or {}).get("answers", {}).get("intent")
    if isinstance(answer, dict):
        answer = answer.get("choice") or ""
    val = str(answer or "").strip().lower()
    return val if val in KNOWN_INTENTS else INTENT_EDIT


# 问句/分析类消息的确定性识别 —— 在 Jev 之前跑,命中直接走聊天分支。
# Jev 正常时这是省一次网络往返;Jev 未配/熔断/断网时这是唯一还能把
# 「这是什么图」送进问答的路(那种情况下默认 edit 就是死胡同)。
QUESTION_HINTS = ("什么", "甚么", "啥", "多少", "为什么", "为啥", "怎么样", "如何",
                  "哪个", "哪些", "谁", "介绍一下", "介绍下", "描述", "分析一下",
                  "解释", "看看这", "评价", "内容是", "质量如何")
EDIT_VERBS = ("改成", "改为", "换成", "去掉", "去除", "删除", "抹掉", "加上", "添加",
              "加水印", "裁剪", "裁掉", "旋转", "翻转", "镜像", "提亮", "压暗",
              "模糊", "锐化", "磨皮", "去雾", "反色", "黑白", "饱和", "亮度",
              "对比", "曝光", "色温", "扩图", "重绘", "批量", "补图", "重画",
              "文绘", "执行", "生成")


def looks_like_analysis(text: str) -> bool:
    """像「问问题/要分析」而不是「要改图」:有疑问特征且不带任何编辑动词。

    批分析命令(「先分析这张图,再给 2 个方案」)是改图流程,调用方须在
    更早处用 wants_batch_analysis 截走,别落到这里。
    """
    t = (text or "").strip()
    if not t:
        return False
    if any(v in t for v in EDIT_VERBS):
        return False
    return ("?" in t or "？" in t or any(h in t for h in QUESTION_HINTS))


# ── 知识问句 vs 找图意图(用户实测提出的两类高频诉求)──
# 知识:「什么是高斯模糊?」「锐化和磨皮有什么区别?」—— 问的是概念/参数,
#       与当前这张图无关 → web 搜索后作答。
# 找图:「我想找一张美女图片」—— 想要的是新素材 → 直接弹图库搜索预填关键词。
# 两者都必须在「关于当前图」的视觉问答之前判断:消息里带「这张/画面」等
# 指代词的是在问当前图,走 chat(多模态看图);不带的是知识/找图。
KNOWLEDGE_HINTS = ("什么是", "什么叫", "是什么意思", "原理", "有什么区别", "的区别",
                   "哪种好", "怎么选", "有什么用", "作用是什么", "推荐", "建议用",
                   "多大", "多少合适", "什么格式", "详解", "教程", "怎么拍",
                   "多少分辨率", "多少dpi", "多少DPI")
IMAGE_REFERS = ("这张", "这图", "此图", "画面", "图里", "图中", "照片里",
                "它", "当前图", "这张照片")
FIND_PHOTO_RE = re.compile(
    r"(想找|帮我找|帮我搜|帮忙找|找一?[张个点些]|找到|搜一?下|搜个?|搜图|来一?[张点]"
    r"|查一?下|查询|查到|查个?|查|寻一?[张个点些]?|哪里?有|有没有"
    r"|换个?|换一?[张批])"
    r".{0,16}(照片|图片|壁纸|素材|画|图)")


def looks_like_knowledge(text: str) -> bool:
    """问图片处理知识(概念/参数/区别),与当前这张图无关 → 走 web 搜索作答。

    知识提示词**优先于编辑动词否决**:「模糊/锐化/磨皮」既是修图术语也是
    编辑动词,「什么是高斯模糊?」按动词否决会被误杀 —— 提示词在就当知识问,
    动词在术语里只是被解释的对象。
    """
    t = (text or "").strip()
    if not t or any(r in t for r in IMAGE_REFERS):
        return False          # 指着当前图问的 → 视觉问答,不是知识检索
    return any(h in t for h in KNOWLEDGE_HINTS)


def looks_like_find_photo(text: str) -> bool:
    """想找/搜一张新图(如「我想找一张美女图片」)→ 弹图库搜索。

    **不做**编辑动词否决:正则(找/搜/换 + 16 字内的照片名词)已足够特异,
    而「换一张黑白的图片」里的「黑白」是编辑动词 —— 否决会误杀找图诉求。
    真正的混合意图(「找张图然后加上水印」)落进图库也无妨,选完图还能改。
    """
    t = (text or "").strip()
    return bool(t) and bool(FIND_PHOTO_RE.search(t))


def extract_photo_query(text: str) -> str:
    """正则兜底:从找图消息里剥出搜索关键词(「查美女图」→「美女」)。

    口语变体无穷多(查/寻/哪有/画/照片…),靠正则追不完 —— 主路径是
    `llm_extract_photo_query` 用文本模型提取,这里只在模型不可用时兜底。
    交替分支**长词必须放前面**:「查」排在「查询」前会剥成「询雪山」。
    """
    t = (text or "").strip()
    t = re.sub(r"(我想|我想要|我想找|帮我|帮忙|给我|麻烦|请|想|要|来一?[张点些]?|来"
               r"|换个?|换一?[张批]"
               r"|查一?下|查询|查到|查[张个点些]?"
               r"|找到|搜到|搜一?下|搜个?|搜"
               r"|寻一?[张个点些]?|寻|哪里?有|有没有"
               r"|找一?[张个点些]|找)", "", t)
    # 量词:查到几张/找一张…(数字词开头才剥,免得吃掉关键词本身)
    t = re.sub(r"[一两二三四五六七八九十几\d]+[张个幅组套点些]", "", t)
    t = re.sub(r"[看看一下呗吧啊呀呢。,,,?!?!?]", "", t)
    # 复合后缀(图片/照片/壁纸…)剥完就到此为止 —— 「山水画图片」是「山水画」
    # +「图片」,不能再把「画」剥掉;原话没带复合后缀才处理光杆「图/画」
    # (「美女图」→「美女」;「国画」len≤2 整词保留)
    t = re.sub(r"(的)?(图片|照片|图像|壁纸|素材)$", "", t)
    if not re.search(r"(图片|照片|图像|壁纸|素材)$", (text or "").strip()):
        if len(t) > 2 and t.endswith(("图", "画")):
            t = t[:-1]
    return t.strip() or "风景"


def llm_extract_photo_query(text: str, llm_id) -> str | None:
    """文本模型提取找图关键词(主路径,口语变体不用挨个写正则)。

    Jev 干不了这活 —— 它只有打分原语、**不吐字**(AGENTS.md),提取关键词
    必须用文本模型。失败/没配/剥完为空一律返回 None,调用方落回正则兜底。
    """
    try:
        from app.ai import text_client as _tc
        from app.ai.photocraft_bridge import _strip_reasoning
        raw = _tc.chat(
            f"用户消息:{text}",
            system=("从用户消息里提取要搜索的图片关键词,只输出关键词本身。"
                    "不要动词(查/搜/找/寻/看/来/换)、不要量词(一张/几张/点/些)、"
                    "不要「图/图片/照片/壁纸/素材/画」这类后缀。"
                    "例:「查美女图」→美女;「哪有赛博朋克壁纸」→赛博朋克;"
                    "「寻几张国画照片」→国画。提取不出就输出:风景"),
            config_id=llm_id, temperature=0.2, timeout=30)
        raw = raw or ""
        if "<think>" in raw and "</think>" not in raw:
            return None          # think 没闭合 = 只输出了思考就被截断,没有关键词
        q = _strip_reasoning(raw).strip().strip('"「」『\'')
        # 推理模型的 think 可能吃掉大半输出,剥完取最后一行非空文本 —— 关键词
        # 就一个词,最后一行就是它
        lines = [x.strip().strip('"「」『\'') for x in q.splitlines() if x.strip()]
        return (lines[-1] if lines else None) or None
    except Exception:  # noqa: BLE001
        return None


def knowledge_query(text: str) -> str:
    """把知识问句剥成搜索引擎友好的关键词:「什么是高斯模糊?」→「高斯模糊」。"""
    t = (text or "").strip()
    t = re.sub(r"(请问|你知道|告诉我|我想知道|什么是|什么叫|是什么意思|是什么"
               r"|有什么区别|的区别|怎么选|哪种好|为什么)", "", t)
    # 标点/语气词单独走字符类 —— 裸 ? 写进交替分支是 "nothing to repeat"
    t = re.sub(r"[吗呢啊?？。，,!!? ]+", "", t)
    return t.strip() or (text or "").strip()


# ── 显式联网查询(「查宁波到淄博的火车」「打开web查询XX」)──
# 用户实测:问火车车次,路由进了纯聊天,模型只好答「我无法查询实时车次」。
# 「查/搜索 + 任意话题」是明确的联网意图,与图片处理知识问句(什么是/区别)
# 是两回事 —— 但找图优先(「查美女图」带图片名词,已在更早处截走)。
WEBQ_NET_WORDS = ("web", "Web", "WEB", "网页", "网上", "互联网", "联网", "上网", "网络")


def looks_like_web_query(text: str) -> bool:
    """显式要求联网查资料:带 web/联网字样,或以 查/搜索/检索 开头的祈使句。"""
    t = (text or "").strip()
    if not t or looks_like_find_photo(t):
        return False            # 「查美女图」是找图,已在路由更早处截走,双保险
    if any(w in t for w in WEBQ_NET_WORDS) and re.search(r"(查|搜|询|找)", t):
        return True
    # 查/搜索 开头(可带 帮我/打开web 等前缀)。只认查/搜根系 —— 「看看这张图」
    # 这类是视觉问答,不能抢
    return bool(re.match(
        r"^(帮我|麻烦|请|给我)?(打开?|用|通过?|走)?"
        r"(web|网页|网上|互联网|联网|上网)?"
        r"(查一?下|查|查询|搜索|搜一?下|搜|检索)", t))


def web_query_text(text: str) -> str:
    """剥掉联网查询的指令外壳,留下搜索词:「打开web查询宁波到淄博的火车表」
    →「宁波到淄博的火车表」。"""
    t = (text or "").strip()
    t = re.sub(r"^(帮我|麻烦|请|给我)+", "", t)
    t = re.sub(r"^(打开?|用|通过?|走)", "", t)
    t = re.sub(r"^(web|Web|WEB|网页|网上|互联网|联网|上网)", "", t)
    t = re.sub(r"^(查一?下|查询|搜索|搜一?下|搜|检索|查)", "", t)
    t = re.sub(r"[?？。，,!! ]+$", "", t)
    return t.strip() or (text or "").strip()


# 快捷命令的「正典清单」:白名单没命中时,让 Jev 判断用户消息跟哪条最接近。
# 只收**无参数歧义**的命令(带具体数值的按常见默认值给),criteria 文案写给
# Jev 看语义,执行时重放正典命令本身 —— 白名单会对正典命令确定性命中。
# 实测动机:「改黑白」白名单没命中(规则只认 改成黑白/改为黑白/黑白化/去色),
# 而 Jev 能判出它跟「改成黑白」是同一件事(本机实测 choice=改成黑白)。
JEV_SHORTCUTS = {
    "改成黑白": "把图片转成黑白/去色/变灰度",
    "反色": "反相/负片/底片效果",
    "亮度+30": "把图片调亮/提亮",
    "亮度-30": "把图片调暗/压暗",
    "对比+20": "增强对比/更通透",
    "对比-20": "减弱对比/变平",
    "饱和度+30": "颜色更浓/更鲜艳",
    "饱和度-40": "颜色变淡/降低鲜艳度",
    "曝光+10": "增加曝光/高光提亮",
    "顺时针旋转90": "图片顺时针转 90 度/向右转",
    "逆时针旋转90": "图片逆时针转 90 度/向左转",
    "旋转180": "图片倒过来/转 180 度",
    "水平翻转": "左右镜像/水平镜像",
    "垂直翻转": "上下翻转/垂直镜像",
    "高斯模糊 5": "把图片模糊/虚化背景",
    "锐化": "让图片更清晰/细节更锐",
    "磨皮": "皮肤柔化/美肤/去瑕疵感",
    "去雾": "去雾感/更通透清晰",
    "胶片感": "胶片色调滤镜/复古色彩",
    "暖色调": "暖色滤镜/偏黄偏暖",
    "冷色调": "冷色滤镜/偏蓝偏冷",
    "裁掉透明边": "裁剪掉四周的透明/空白边缘",
}

# 概率低于这条就当 Jev 没说话 —— 对齐视频路由的低置信纪律,宁可落到
# 带图问答兜底,也不猜错命令白花一次用户的图
JEV_SHORTCUT_MIN_PROB = 0.6


def jev_shortcut_match(text: str) -> str | None:
    """白名单没命中时,问 Jev「这条消息跟哪条快捷命令最接近」。

    choice 原语天然适合 N 选一。任何失败(未配/挂了/低置信/选了 none)
    一律返回 None,调用方落到带图问答兜底 —— 软建议器契约,绝不打断业务。
    注意 answers.shortcut 是对象,答案在 `choice` 字段(intents 同款坑)。
    """
    from app.ai.jev_client import JevClient
    try:
        client = JevClient()
        if not client.is_configured() or not (text or "").strip():
            return None
        criteria = dict(JEV_SHORTCUTS)
        criteria["none"] = "都不是,用户想要别的"
        questions = {"shortcut": {
            "type": "choice",
            "instructions": "用户消息跟哪条改图快捷命令最接近?",
            "criteria": criteria,
        }}
        res = client.decide(f"用户消息: {text}", questions) or {}
        ans = (res.get("answers") or {}).get("shortcut")
        if not isinstance(ans, dict):
            return None
        choice = str(ans.get("choice") or "").strip()
        probs = ans.get("probabilities") or {}
        try:
            p = float(probs.get(choice, 0) or 0)
        except (TypeError, ValueError):
            p = 0.0
        if choice not in JEV_SHORTCUTS or p < JEV_SHORTCUT_MIN_PROB:
            return None
        return choice
    except Exception:  # noqa: BLE001
        return None


# ── /help 帮助文案 ──
# 按**实际实现**分类,不是拍脑袋写的:
#   ① 白名单:正则确定性命中,零延迟、结果稳定(photocraft_bridge._WL_RULES)
#   ② 文字编辑:走 TextReplaceSkill,需要多模态模型定位文字
#   ③ 加水印: PIL ImageDraw 画字 + alpha 叠加 PNG,不走 PhotoCraft
#   ④ 批分析: LLM 看图给 N 个单条 prompt,逐条执行
#   ⑤ 外部打开: 用 PhotoCraft 桌面端编辑,改完自动同步回来
#   ⑥ 兜底: 白名单没命中时交给 LLM 自由理解,措辞/命令不保证完全一致
HELP_TEXT = """可以用下面这些说法改图(直接发文字即可,回车执行)。

【色彩 · 白名单,最稳】
改成黑白 / 改为黑白 / 黑白化 / 去色
亮度+30   亮度-20
对比+15   饱和度-40
曝光+10   鲜艳度-30
反色 / 反相 / 负片
去雾 / 除雾
加饱和 / 降饱和 / 鲜艳度+30
暖色调 / 冷色调 / 色温+30
胶片感 / 电影感 / 暗部提亮 / 亮部压暗

【几何 · 白名单】
顺时针旋转90 / 右转90
逆时针旋转90 / 左转90
水平翻转 / 水平镜像 / 左右翻转
垂直翻转 / 上下翻转
旋转180 / 转180 / 倒过来
裁掉透明边

【滤镜 · 白名单】
高斯模糊 5 / 模糊5 / 模糊一下
轻微模糊 / 轻度模糊 / 柔焦一下
运动模糊
锐化 / 清晰一些
强力锐化 / 更锐利
磨皮 / 皮肤柔化
中值去噪 / 加噪点 10
旋转扭曲 / 锐化30

【文字编辑 · 需要识图,稍慢】
把「影星传媒」改成「歌星」      ← 推荐加引号
把"CHAMPION"换成"TITLE"
将标题改为副标题
去掉图片上的文字 / 去除水印 / 删除字幕
加上文字 公司名 到左下              ← 字体/颜色/位置在「改图」面板里调

【加水印 · 当前图烙字 / 贴 PNG】
加水印 版权所有 到右下 / 宽 15% / 透 60%
加水印 草图 v1 到中下 黄字黑边
加 PNG 水印 → 选 PNG 文件 → 选位置 → 点「加水印」

【批分析 · 先分析再 N 个方案】
先分析这张图,再给 3 个改进方案分别执行
分析构图,然后给 2 个方案

【批改图 · 一键批量(资产页也能用)】
批量文绘 角色         ← 全角色全生图,3s 间隔,串行
批量重画 场景         ← 强制覆盖已有图,跑新风格
补图全部               ← 只生空白图(image_url IS NULL),不浪费 token
批量视频               ← 任务列表所有「无视频」分镜全跑

【聊天 · 直接问图(不动图)】
这张图片是什么内容?    ← 问句自动进问答,多模态模型看图回答
这个构图怎么样 / 给点配色建议
对比这张图和电影感调色的区别

【知识 · 联网搜索后作答(带来源)】
什么是高斯模糊?        ← 图片处理知识自动先搜再答
锐化和磨皮有什么区别 / 9:16 是多少分辨率

【联网查询 · 任意话题】
查宁波到淄博的火车      ← 显式查询自动联网,答案带来源链接
打开web查询今天天气 / 帮我查一下12306

【找图 · 自动弹图库搜索】
我想找一张美女图片      ← 关键词自动预填,选中即成当前图
搜一下雪山风景图 / 来点赛博朋克壁纸

【外部打开 · PhotoCraft 桌面端】
✋ 我手动改             ← 启动 PhotoCraft,改完自动同步回来
🖥 PhotoCraft           ← 桌面端当前版本号 + 打开外部应用按钮

提示:数字是强度参数,可正可负(亮度+30 比 亮度30 更明确);加水印/批分析/
      批改图/外部打开用面板里的按钮,不是打字;
      「重抽」/「撤销」直接点气泡里的图片,弹「改图」面板裁剪/精调/水印/AI 修补;
      需要先选图 —— 没图时面板会明确报错。"""


__all__ = [
    "INTENT_EDIT", "INTENT_CHAT", "INTENT_KNOWLEDGE", "INTENT_FIND_PHOTO",
    "INTENT_WEB_QUERY", "KNOWN_INTENTS",
    "JEV_INTENT_QUESTIONS", "JEV_SHORTCUTS", "JEV_SHORTCUT_MIN_PROB",
    "QUESTION_HINTS", "EDIT_VERBS",
    "KNOWLEDGE_HINTS", "IMAGE_REFERS", "FIND_PHOTO_RE",
    "WEBQ_NET_WORDS",
    "parse_jev_intent",
    "looks_like_analysis", "looks_like_knowledge", "looks_like_find_photo",
    "looks_like_web_query",
    "extract_photo_query", "llm_extract_photo_query",
    "knowledge_query", "web_query_text", "jev_shortcut_match",
    "HELP_TEXT",
]
