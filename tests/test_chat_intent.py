# -*- coding: utf-8 -*-
"""回归:聊天改图的意图路由 —— 问图内容必须进问答,不是进改图引擎。

实测 bug(用户报告「为什么系统认为我们要处理图片」):

  用户问「这张图片是什么内容?」,界面回「未能执行 —— 没有产出新图」。
  查证:JEV **判得完全正确**(本机实测 decide() 返回 choice=chat、置信度 1.0),
  但解析代码写的是 `str(answer) == "chat"`,而 `answers.intent` 是个**对象**
  `{"type": "choice", "choice": "chat", "confidence": 1.0, "probabilities": {...}}`
  —— dict 转字符串永远不等于 "chat",于是**每条消息都被判成 edit**,
  聊天分支从上线起就是死代码。与 AGENTS.md 记过的视频路由同款坑
  (choice 的答案在 `choice` 字段,不在外层)。
"""
from __future__ import annotations

# 本机 Jev 对「这张图片是什么内容?\n当前图: xxx.png」的真实响应(2026-10 实测)
_REAL_DECIDE_RES = {
    "model": "jev-1.13.0",
    "answers": {
        "intent": {
            "type": "choice",
            "choice": "chat",
            "confidence": 1.0,
            "probabilities": {"edit": 0.0, "chat": 1.0},
        }
    },
    "elapsed_ms": 953,
}


def test_parse_jev_intent_reads_choice_field_from_real_shape():
    from app.ui.chat_edit_drawer import _INTENT_CHAT, _parse_jev_intent

    assert _parse_jev_intent(_REAL_DECIDE_RES) == _INTENT_CHAT, (
        "真实 JEV 响应(answers.intent 是对象)必须解析出 chat —— "
        "str(dict) 永远不等于 'chat',这就是聊天分支成死代码的根因")


def test_parse_jev_intent_edit_and_fallbacks():
    from app.ui.chat_edit_drawer import _INTENT_EDIT, _INTENT_CHAT, _parse_jev_intent

    edit_res = {"answers": {"intent": {"type": "choice", "choice": "edit",
                                       "confidence": 0.9}}}
    assert _parse_jev_intent(edit_res) == _INTENT_EDIT
    # 兼容裸字符串形态(万一上游改成直接给值)
    assert _parse_jev_intent({"answers": {"intent": "chat"}}) == _INTENT_CHAT
    # 软建议器契约:None / 空对象 / 缺字段 一律 edit,不抛异常
    assert _parse_jev_intent(None) == _INTENT_EDIT
    assert _parse_jev_intent({}) == _INTENT_EDIT
    assert _parse_jev_intent({"answers": {}}) == _INTENT_EDIT


def test_question_messages_route_to_analysis():
    from app.ui.chat_edit_drawer import _looks_like_analysis

    assert _looks_like_analysis("这张图片是什么内容?")
    assert _looks_like_analysis("这是什么图")
    assert _looks_like_analysis("这个构图怎么样")
    assert _looks_like_analysis("描述一下画面里的人物")
    assert not _looks_like_analysis("改成黑白")
    assert not _looks_like_analysis("亮度+30")
    assert not _looks_like_analysis("去掉图片上的文字")
    assert not _looks_like_analysis("")
    # 编辑动词优先于疑问特征:「怎么改成黑白」是要改图,不是问问题
    assert not _looks_like_analysis("怎么把背景改成纯黑?")


def test_batch_analysis_command_not_captured_by_question_rule():
    """「分析…方案」是改图流程,问句规则不得抢走 —— job 里在规则前用
    _wants_batch_analysis 截走;这里守住两者的分工边界。"""
    from app.ai.photocraft_bridge import _wants_batch_analysis
    from app.ui.chat_edit_drawer import _looks_like_analysis

    for cmd in ("先分析这张图,再给 2 个方案", "分析构图,然后给 2 个方案"):
        assert _wants_batch_analysis(cmd), f"批分析命令没被识别:{cmd}"
        # 正因为问句规则对它们也可能为 True,job 里必须先截走
        if _looks_like_analysis(cmd):
            assert _wants_batch_analysis(cmd), (
                f"「{cmd}」会被问句规则抢进聊天,批分析保护失效")


def test_chat_reply_strips_reasoning_block(monkeypatch):
    """聊天回复必须剥掉 <think> 推理块(AGENTS.md 解析纪律)。

    实测:问「这张图片是什么内容?」,minimax-M3 先吐一段英文 <think> 再给
    中文正文,气泡里两者都显示了。复用 photocraft_bridge._strip_reasoning。
    """
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import app.ai.text_client as tc
    from app.ui.chat_edit_drawer import ChatEditPanel

    def fake_chat(*a, **k):
        return ("<think>The user is asking what this image is. "
                "I should describe the visual elements.</think>\n"
                "这是一张女性人物的肖像照片,优雅而正式。")

    monkeypatch.setattr(tc, "chat", fake_chat)
    panel = ChatEditPanel()
    res = panel._chat_reply("这张图片是什么内容?", "", None, "smart")
    assert res["kind"] == "chat"
    assert "<think>" not in res["content"], f"推理块没剥干净:{res['content'][:80]}"
    assert "肖像照片" in res["content"]

    # 没闭合的 <think>(模型截断)也不能把 think 内容当正文漏出来
    monkeypatch.setattr(tc, "chat", lambda *a, **k: "<think>思考到一半")
    res2 = panel._chat_reply("问", "", None, "smart")
    assert "思考到一半" not in res2["content"]


def _fake_jev_shortcut(choice, prob):
    """构造 answers.shortcut 的真实响应形态(对象,答案在 choice 字段)。"""
    return {"answers": {"shortcut": {
        "type": "choice", "choice": choice, "confidence": prob,
        "probabilities": {choice: prob, "none": round(1 - prob, 2)}}}}


def test_jev_shortcut_match_accepts_confident_variant(monkeypatch):
    """「改黑白」→「改成黑白」:白名单漏掉的口语变体由 Jev 对上正典命令。"""
    import app.ai.jev_client as jm
    from app.ui.chat_edit_drawer import _jev_shortcut_match

    monkeypatch.setattr(jm.JevClient, "is_configured", lambda self: True)
    monkeypatch.setattr(jm.JevClient, "decide",
                        lambda self, s, q: _fake_jev_shortcut("改成黑白", 0.9))
    assert _jev_shortcut_match("改黑白") == "改成黑白"


def test_jev_shortcut_match_rejects_low_confidence_and_none(monkeypatch):
    """低置信 / 选了 none / 未配 / 异常 一律 None(软建议器契约)。"""
    import app.ai.jev_client as jm
    from app.ui.chat_edit_drawer import _jev_shortcut_match

    monkeypatch.setattr(jm.JevClient, "is_configured", lambda self: True)
    monkeypatch.setattr(jm.JevClient, "decide",
                        lambda self, s, q: _fake_jev_shortcut("改成黑白", 0.4))
    assert _jev_shortcut_match("改黑白") is None, "低于 0.6 不该猜"

    monkeypatch.setattr(jm.JevClient, "decide",
                        lambda self, s, q: _fake_jev_shortcut("none", 0.95))
    assert _jev_shortcut_match("给我讲个笑话") is None

    monkeypatch.setattr(jm.JevClient, "is_configured", lambda self: False)
    assert _jev_shortcut_match("改黑白") is None

    monkeypatch.setattr(jm.JevClient, "is_configured", lambda self: True)
    monkeypatch.setattr(jm.JevClient, "decide", lambda self, s, q: None)
    assert _jev_shortcut_match("改黑白") is None

    def boom(self, s, q):
        raise RuntimeError("network down")
    monkeypatch.setattr(jm.JevClient, "decide", boom)
    assert _jev_shortcut_match("改黑白") is None


def test_shortcut_replay_hits_whitelist():
    """正典命令必须能被白名单确定性命中 —— Jev 挑完重放才算数。"""
    from app.ai.photocraft_bridge import ChatEditEngine, Step
    from app.ui.chat_edit_drawer import _JEV_SHORTCUTS

    eng = ChatEditEngine()
    for canon in list(_JEV_SHORTCUTS)[:6]:
        steps, label, note = eng.interpret(canon, image_url="", mode="whitelist",
                                           llm_config_id=None)
        assert steps, f"正典命令「{canon}」白名单没命中,Jev 挑了也白挑(note={note})"


def test_knowledge_and_find_photo_routing():
    """知识问句 → web 搜索;找图 → 弹图库。两者都不得误伤原有路由。"""
    from app.ui.chat_edit_drawer import (_extract_photo_query, _knowledge_query,
                                         _looks_like_find_photo,
                                         _looks_like_knowledge)

    # 知识:问概念/参数,与当前图无关;指着当前图问的不算
    for t in ("什么是高斯模糊?", "锐化和磨皮有什么区别", "推荐一个磨皮参数",
              "9:16 是多少分辨率"):
        assert _looks_like_knowledge(t), f"该判成知识问句:{t}"
    for t in ("这张图是什么内容?", "画面里的人物是谁", "改成黑白",
              "怎么把图变成黑白的"):
        assert not _looks_like_knowledge(t), f"不该判成知识问句:{t}"

    # 找图:找/搜/换 + 图片名词;术语撞编辑动词的不得误杀
    for t in ("我想找一张美女图片", "搜一下雪山风景图", "给我找点赛博朋克壁纸",
              "换一张黑白的图片"):
        assert _looks_like_find_photo(t), f"该判成找图:{t}"
    for t in ("改成黑白", "什么是高斯模糊?", "把图片换成黑白的"):
        assert not _looks_like_find_photo(t), f"不该判成找图:{t}"

    # 关键词剥离:喂给图库搜索的就是干净名词
    assert _extract_photo_query("我想找一张美女图片") == "美女"
    assert _extract_photo_query("搜一下雪山风景图") == "雪山风景"
    assert _knowledge_query("什么是高斯模糊?") == "高斯模糊"
    assert _knowledge_query("锐化和磨皮有什么区别") == "锐化和磨皮"


def test_jev_intent_parses_four_ways(monkeypatch):
    """Jev 四选一:knowledge / find_photo 也要能从 choice 字段解析出来。"""
    from app.ui.chat_edit_drawer import (_INTENT_FIND_PHOTO, _INTENT_KNOWLEDGE,
                                         _parse_jev_intent)

    def res(choice):
        return {"answers": {"intent": {"type": "choice", "choice": choice,
                                       "confidence": 0.9}}}

    assert _parse_jev_intent(res("knowledge")) == _INTENT_KNOWLEDGE
    assert _parse_jev_intent(res("find_photo")) == _INTENT_FIND_PHOTO
    assert _parse_jev_intent(res("garbage")) == "edit", "不认识的值退 edit"


def test_knowledge_reply_uses_search_and_strips_think(monkeypatch):
    """知识回答 = 搜索结果喂 LLM;带来源;think 块剥掉;搜索挂了注明未核实。"""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import app.ai.text_client as tc
    import app.ai.web_search as WS
    from app.ui.chat_edit_drawer import ChatEditPanel

    panel = ChatEditPanel()
    monkeypatch.setattr(WS, "search", lambda q, **k: (
        [("高斯模糊 - 维基", "https://wiki.example/g", "高斯模糊是…")], ""))
    monkeypatch.setattr(tc, "chat",
                        lambda *a, **k: "<think>reasoning</think>高斯模糊是线性平滑滤波 [1]")
    r = panel._knowledge_reply("什么是高斯模糊?", None)
    assert r["kind"] == "knowledge"
    assert "高斯模糊是线性平滑滤波" in r["content"] and "<think>" not in r["content"]
    assert r["sources"] == ["https://wiki.example/g"]

    # 搜索挂 → 纯 LLM 兜底,注明未经联网核实
    monkeypatch.setattr(WS, "search", lambda q, **k: ([], "三引擎全挂"))
    monkeypatch.setattr(tc, "chat", lambda *a, **k: "答案")
    r2 = panel._knowledge_reply("什么是直方图?", None)
    assert "未经联网核实" in r2["content"] and "答案" in r2["content"]

    # LLM 也挂 → error,done 会走统一错误气泡
    def boom(*a, **k):
        raise tc.AIError("timeout")
    monkeypatch.setattr(tc, "chat", boom)
    r3 = panel._knowledge_reply("什么是直方图?", None)
    assert r3.get("error")


def test_web_search_parses_bing_html(monkeypatch):
    """移植的 web_search:用罐头 Bing 页面验证解析与缓存。"""
    import app.ai.web_search as WS

    page = ('<li class="b_algo"><h2><a href="https://example.com/a">'
            '高斯<b>模糊</b> - 百度百科</a></h2><p>高斯模糊是<em>线性</em>平滑滤波</p></li>')
    # DDG lite 现在排第一,也得打桩 —— 不然这个用例会真发网络请求
    monkeypatch.setattr(WS, "_fetch_ddg_lite", lambda q: "")
    monkeypatch.setattr(WS, "_fetch_page", lambda url: page)
    hits, err = WS.search("高斯模糊", use_cache=False)
    assert err == "" and hits, f"解析失败:{err}"
    title, url, snip = hits[0]
    assert url == "https://example.com/a"
    assert "<b>" not in title and "高斯模糊" in title
    assert "高斯模糊是线性平滑滤波" in snip

    # 全引擎空页 → 软失败(空列表 + 错误文案),不抛异常
    monkeypatch.setattr(WS, "_fetch_ddg_lite", lambda q: "")
    monkeypatch.setattr(WS, "_fetch_page", lambda url: "")
    hits2, err2 = WS.search("高斯模糊", use_cache=False)
    assert hits2 == [] and "无结果" in err2


def test_llm_extract_photo_query(monkeypatch):
    """找图关键词主路径走文本模型;think 块剥掉、取最后一行;失败回退正则。"""
    import app.ai.text_client as tc
    from app.ui.chat_edit_drawer import _extract_photo_query, _llm_extract_photo_query

    monkeypatch.setattr(
        tc, "chat",
        lambda *a, **k: "<think>thinking about the request</think>\n\n美女")
    assert _llm_extract_photo_query("查美女图", None) == "美女"

    # think 把输出吃光(截断)→ None,调用方落回正则兜底
    monkeypatch.setattr(tc, "chat", lambda *a, **k: "<think>只想到一半")
    assert _llm_extract_photo_query("查美女图", None) is None
    assert _extract_photo_query("查美女图") == "美女"

    # 模型抛异常 → None 不外溢
    def boom(*a, **k):
        raise RuntimeError("no model")
    monkeypatch.setattr(tc, "chat", boom)
    assert _llm_extract_photo_query("查美女图", None) is None


def test_find_photo_query_variants():
    """正则兜底:查/寻/哪有/画/照片 各种口语变体都要剥出干净关键词。"""
    from app.ui.chat_edit_drawer import _extract_photo_query, _looks_like_find_photo

    cases = [("查美女图", "美女"), ("查一下美女图片", "美女"),
             ("查询雪山风景图", "雪山风景"), ("查到几张赛博朋克图", "赛博朋克"),
             ("帮我查点赛博朋克壁纸", "赛博朋克"), ("找到美女图片", "美女"),
             ("我想找一张美女图片", "美女"), ("搜一下雪山风景图", "雪山风景"),
             ("来点古风壁纸", "古风"), ("寻几张国画照片", "国画"),
             ("哪有赛博朋克壁纸", "赛博朋克"), ("哪里有山水画图片", "山水画"),
             ("查山水画照片", "山水画"), ("查国画", "国画")]
    for t, want in cases:
        assert _looks_like_find_photo(t), f"没判成找图:{t}"
        assert _extract_photo_query(t) == want, f"关键词剥错:{t}"
    for t in ("改成黑白", "把图片换成黑白的", "什么是高斯模糊?"):
        assert not _looks_like_find_photo(t), f"误判找图:{t}"


def test_web_query_routing_and_extraction():
    """显式联网查询(查火车/打开web查询XX)→ web_search 意图,搜索词剥掉外壳。"""
    from app.ui.chat_edit_drawer import (_looks_like_web_query, _web_query_text,
                                         _looks_like_find_photo)

    for t in ("打开web查询宁波到淄博的火车表", "查宁波到淄博的火车",
              "帮我查一下天气", "联网查一下最新模型", "搜索一下锐化教程"):
        assert _looks_like_web_query(t), f"该判成联网查询:{t}"
    for t in ("查美女图", "搜一下雪山风景图",       # 找图优先
              "什么是高斯模糊?", "这张图是什么内容?", "改成黑白"):
        assert not _looks_like_web_query(t), f"误判联网查询:{t}"
    # 找图判定不受影响
    assert _looks_like_find_photo("查美女图")
    # 取词
    assert _web_query_text("打开web查询宁波到淄博的火车表") == "宁波到淄博的火车表"
    assert _web_query_text("查宁波到淄博的火车") == "宁波到淄博的火车"
    assert _web_query_text("帮我查一下天气") == "天气"


def test_web_search_ddg_lite_first(monkeypatch):
    """引擎顺序:DDG lite 第一(Bing 对无 cookie 客户端会假装答了无关内容)。"""
    import app.ai.web_search as WS

    calls = []

    def fake_lite(q):
        calls.append("ddg")
        return ("<a rel=\"nofollow\" href=\"https://trains.ctrip.com/x\" "
                "class='result-link'>宁波到淄博高铁查询</a>"
                "<td class='result-snippet'>高铁时刻表与余票</td>")

    def fake_bing(*a, **k):
        calls.append("bing")
        return "<li class='b_algo'><h2><a href='https://x.com'>junk</a></h2><p>junk</p></li>"

    monkeypatch.setattr(WS, "_fetch_ddg_lite", fake_lite)
    monkeypatch.setattr(WS, "_fetch_page", fake_bing)
    hits, err = WS.search("宁波到淄博的火车", use_cache=False)
    assert calls[0] == "ddg", f"DDG lite 应该是第一引擎,实际顺序:{calls}"
    assert err == "" and hits
    # href 在 class 前面的新标记也要能解析(实测 lite 版就是这个顺序)
    assert hits[0][0] == "宁波到淄博高铁查询"
    assert hits[0][1] == "https://trains.ctrip.com/x"
    assert "高铁时刻表" in hits[0][2]
