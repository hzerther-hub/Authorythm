# -*- coding: utf-8 -*-
"""复刻(video-clone)链路的提示词契约测试。

背景:用户反馈「换了产品图,画面里还是原片的产品」。根因不是参数没调对,而是
`generate_shot_image` 把「原片动作描述」和「新产品描述」硬拼进同一个提示词 ——
动作里的实物跟场景是自洽的(展会/展位/水箱),新产品那句是孤立无援的,
模型必然选自洽的那个。

对齐参考项目 liaodabiao/video-clone-lite 的做法:**拆解后立刻改写分镜表**,
让后续生成时从头到尾看不到旧产品词。本文件锁住这条链路的关键不变量。
"""
from __future__ import annotations

import pytest

from app.ai.prompt_guards import VIDEO_MARKER, apply_video_guards
from app.pipeline import video_clone as vc
from app.pipeline import novel as vc_novel


# ── 时间锚点 ───────────────────────────────────────────────────────────

def test_video_prompt_injects_time_anchor():
    """start/end 此前拆了却不进提示词,视频模型拿不到本镜时间轴。"""
    b = {"start": 2.0, "end": 6.5, "shot": "中景", "camera": "移",
         "action_steps": ["手柄缓缓抬起"], "prompt": "女性展示产品"}
    out = vc._shot_video_prompt(b)
    assert out.startswith("2-6.5秒:")


def test_video_prompt_does_not_duplicate_anchor():
    """改写过的 prompt 自带锚点,外面再加会变成 '0-4秒:0-4秒:'。"""
    b = {"start": 0, "end": 4, "prompt": "0-4秒:中景,女性举起产品"}
    out = vc._shot_video_prompt(b)
    assert out.count("0-4秒") == 1


def test_video_prompt_no_anchor_without_valid_span():
    """起止相同或缺失时不硬造 '0-0秒:'。"""
    assert vc._shot_video_prompt({"start": 4, "end": 4, "prompt": "x"}).startswith("x")
    assert vc._shot_video_prompt({"prompt": "x"}).startswith("x")


def test_video_prompt_falls_back_to_steps_without_prompt_field():
    b = {"start": 0, "end": 3, "shot": "全景", "camera": "摇",
         "action_steps": ["镜头下摇", "露出主体"]}
    out = vc._shot_video_prompt(b)
    assert "全景" in out and "摇" in out and "露出主体" in out


def test_video_prompt_appends_dialogue_marker():
    b = {"start": 0, "end": 4, "prompt": "展示产品", "line": "姐妹们快看"}
    assert "口型同步" in vc._shot_video_prompt(b)


# ── 字数上限 ───────────────────────────────────────────────────────────

def test_shot_prompt_max_chars_fits_english_rewrite():
    """上限按**英文**重绘句的实际长度定,不套用参考项目的中文 200 字口径。

    参考项目那句「单镜头 ≤200 字」是中文口径;rewrite 产出的是英文,实测本项目
    6 镜内容 366-509 字符。按 200 砍,砍掉的正是「白色纸盒」「口红」这类产品名 ——
    模型看不到就只能自由发挥,6 镜全画成同一张「沙发上女性」插画(实测踩过)。
    """
    # 上限必须容得下 rewrite 产出的英文句(实测 435–522 字符)。
    # 曾设 400 → 每镜都被截断,而截掉的句尾正是运镜与氛围
    # (fixed camera / cinematic shallow depth of field),那是复刻的核心信息。
    assert vc.SHOT_PROMPT_MAX_CHARS >= 600
    boards = (vc._meta(15).get("clone") or {}).get("storyboards") or []
    for b in boards[:1]:
        core = str(b.get("prompt") or "")
        # 本镜内容应能整体装进预算,不再被拦腰砍断
        if core:
            assert len(core) <= vc.SHOT_PROMPT_MAX_CHARS or "内容超预算属预期外"


# ── 分镜表改写:核心不变量 ──────────────────────────────────────────────

_BOARDS = [
    {"number": 1, "start": 0, "end": 4, "shot": "全景", "camera": "摇",
     "action": "展会全景", "action_steps": ["露出主机底座"], "product_use": "立式挂烫机"},
    {"number": 2, "start": 4, "end": 9, "shot": "中景", "camera": "移",
     "action": "手柄特写", "action_steps": ["蒸汽喷头手柄挂起"], "product_use": "喷头手柄"},
]


def _fake_chat(payload):
    def _chat(prompt, **kw):
        _chat.last = prompt
        return payload
    return _chat


def test_rewrite_replaces_original_product_terms(monkeypatch):
    """改写后 action_steps / product_use 里不能再有原片实物。"""
    import json
    rewritten = {"storyboards": [
        {"number": 1, "action": "展位全景", "action_steps": ["露出新产品主体"],
         "product_use": "新产品完整呈现", "prompt": "0-4秒:全景,展示玉镯"},
        {"number": 2, "action": "产品特写", "action_steps": ["玉镯举起至胸前"],
         "product_use": "玉镯以佩戴状态呈现", "prompt": "4-9秒:中景,玉镯特写"},
    ]}
    monkeypatch.setattr(vc.text_client, "chat",
                        _fake_chat(json.dumps(rewritten, ensure_ascii=False)))
    out = vc.rewrite_boards_for_product(_BOARDS, "翠绿色玉镯")
    blob = " ".join(str(x.get(k) or "") for x in out for k in
                    ("action", "action_steps", "product_use", "prompt"))
    for stale in ("挂烫机", "主机底座", "蒸汽喷头", "喷头手柄"):
        assert stale not in blob, f"原片实物仍残留:{stale}"


def test_rewrite_preserves_shot_structure(monkeypatch):
    """复刻的本质是保留结构与节奏:景别/运镜/时间轴不能被改。"""
    import json
    same = {"storyboards": [{"prompt": "改写后的提示词"} for _ in _BOARDS]}
    monkeypatch.setattr(vc.text_client, "chat",
                        _fake_chat(json.dumps(same, ensure_ascii=False)))
    out = vc.rewrite_boards_for_product(_BOARDS, "玉镯")
    assert len(out) == len(_BOARDS)
    for orig, new in zip(_BOARDS, out):
        assert new["start"] == orig["start"]
        assert new["end"] == orig["end"]
        assert new["shot"] == orig["shot"]
        assert new["camera"] == orig["camera"]
        assert new["number"] == orig["number"]


def test_rewrite_returns_original_on_model_failure(monkeypatch):
    """改写失败绝不能毁掉已拆好的分镜 —— 它是增强手段,不是前置依赖。"""
    def _boom(*a, **k):
        raise RuntimeError("模拟模型故障")
    monkeypatch.setattr(vc.text_client, "chat", _boom)
    assert vc.rewrite_boards_for_product(_BOARDS, "玉镯") == _BOARDS


def test_rewrite_returns_original_on_empty_output(monkeypatch):
    monkeypatch.setattr(vc.text_client, "chat", _fake_chat('{"storyboards":[]}'))
    assert vc.rewrite_boards_for_product(_BOARDS, "玉镯") == _BOARDS


def test_rewrite_survives_short_model_output(monkeypatch):
    """模型只返回部分镜次时按原顺序补齐,不丢镜。"""
    import json
    monkeypatch.setattr(vc.text_client, "chat",
                        _fake_chat(json.dumps({"storyboards": [{"prompt": "只有一镜"}]})))
    out = vc.rewrite_boards_for_product(_BOARDS, "玉镯")
    assert len(out) == 2
    assert out[0]["prompt"] == "只有一镜"
    assert out[1]["shot"] == "中景"      # 第二镜退回原表,不凭空消失


def test_rewrite_empty_input_is_noop():
    assert vc.rewrite_boards_for_product([], "玉镯") == []


# ── 负面词:带货场景的产品侧约束 ───────────────────────────────────────

def test_video_guard_covers_product_deformation():
    """带货/复刻是本项目视频主场景,产品变形是最高频翻车点。"""
    g = apply_video_guards("产品特写")
    assert "穿模" in g and "变形" in g
    assert "偏色" in g


def test_video_guard_covers_frame_instability():
    g = apply_video_guards("产品特写")
    assert "抖动" in g and "闪烁" in g and "重影" in g


def test_video_guard_has_english_negative_tokens():
    """英文负面 token 对多数平台权重高于中文同义词(见 AGENTS.md)。"""
    g = apply_video_guards("产品特写")
    for token in ("low quality", "deformed", "mutated hands",
                  "jittery motion", "physics error", "product deformation"):
        assert token in g, f"缺英文负面词:{token}"


def test_video_guard_still_idempotent_after_extension():
    """守卫追加了三层以上,幂等必须仍然成立(重试会复用已存 prompt)。"""
    once = apply_video_guards("产品特写")
    assert apply_video_guards(once) == once
    assert once.count(VIDEO_MARKER) == 1


# ── 复刻项目的 UI 适配:不该出现小说/漫画那一套 ─────────────────────────

def test_clone_project_locks_novel_and_comic_steps():
    """复刻内容来自参考视频拆解,没有正文也没有漫画 —— 那三步对它无意义。

    原实现只锁了 comic,跳进工作台先看到 0 字的空剧本编辑器(用户截图反馈)。
    """
    import app.ui.episode_page as ep

    class Fake(ep.EpisodePage):
        def __init__(self, work):
            self._drama = {"work_type": work}
            self._pipeline_expanded = False

        def _progress_done_keys(self):
            return []

    clone = Fake("video_clone")._step_states()
    assert clone["raw"] == "locked"
    assert clone["rewrite"] == "locked"
    assert clone["comic"] == "locked"
    # 分镜与资产是复刻项目真正要用的,不能锁
    assert clone["storyboard"] != "locked"
    assert clone["assets"] != "locked"


def test_other_work_types_unchanged_by_clone_locking():
    """复刻项目的锁不能外溢到小说/短剧 —— 它们要正常写正文。"""
    import app.ui.episode_page as ep

    class Fake(ep.EpisodePage):
        def __init__(self, work):
            self._drama = {"work_type": work}
            self._pipeline_expanded = True

        def _progress_done_keys(self):
            return []

    assert Fake("drama")._step_states()["raw"] != "locked"
    assert Fake("novel")._step_states()["raw"] != "locked"
    assert Fake("drama")._step_states()["comic"] != "locked"


def test_clone_page_title_has_no_episode_number():
    """复刻只有一条片子,标题不该出现「第 N 集」(那行是自动占位)。"""
    import app.ui.episode_page as ep
    drama = {"title": "生成复克", "work_type": "video_clone"}
    ep_row = {"episode_number": 1, "title": "第 1 集"}
    assert ep._page_title(drama, ep_row) == "生成复克"
    drama2 = {"title": "短剧", "work_type": "drama"}
    assert "第 1 集" in ep._page_title(drama2, ep_row)


# ── 项目级联删除 ───────────────────────────────────────────────────────

def test_delete_drama_cascades_all_related_tables(tmp_path, monkeypatch):
    """删项目要连级联表一起清,否则留下定位不到的孤儿行。

    原实现漏了 comic_panel_scenes / comic_panel_props(只删了 *_characters)
    与 storyboard_scenes、sys_task。character_variants 挂在 character 上,
    父行先删就再也定位不到 —— 顺序错了同样会漏。
    """
    from app.core import db as _db
    from app.ui.projects_page import _delete_drama_cascade

    monkeypatch.setattr(_db.config, "DB_PATH", tmp_path / "del.sqlite3")
    old = getattr(_db._local, "conn", None)
    if old is not None:
        old.close()
    _db._local.conn = None
    _db.init_db()
    ts = _db.now()
    D, E, S, C, P = 901, 901, 901, 901, 901
    _db.ex("INSERT INTO dramas(id,title,work_type,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
           (D, "T", "video_clone", "pending", ts, ts))
    _db.ex("INSERT INTO episodes(id,drama_id,episode_number,title,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
           (E, D, 1, "e", "pending", ts, ts))
    _db.ex("INSERT INTO characters(id,drama_id,name,created_at,updated_at) VALUES(?,?,?,?,?)",
           (C, D, "c1", ts, ts))
    _db.ex("INSERT INTO character_variants(id,character_id,label,image_url,created_at) VALUES(901,?,?,?,?)",
           (C, "v1", "/x.png", ts))
    _db.ex("INSERT INTO storyboards(id,episode_id,storyboard_number,created_at,updated_at) VALUES(?,?,?,?,?)",
           (S, E, 1, ts, ts))
    _db.ex("INSERT INTO storyboard_characters(storyboard_id,character_id) VALUES(?,?)", (S, C))
    _db.ex("INSERT INTO storyboard_scenes(storyboard_id,scene_id) VALUES(?,?)", (S, 1))
    _db.ex("INSERT INTO comic_panels(id,episode_id,panel_number,created_at,updated_at) VALUES(?,?,?,?,?)",
           (P, E, 1, ts, ts))
    _db.ex("INSERT INTO comic_panel_scenes(panel_id,scene_id) VALUES(?,?)", (P, 1))
    _db.ex("INSERT INTO comic_panel_props(panel_id,prop_id) VALUES(?,?)", (P, 1))
    _db.ex("INSERT INTO sys_task(id,type,drama_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
           (901, "video", D, "processing", ts, ts))

    _delete_drama_cascade(D)

    for table, key, val in (
            ("dramas", "id", D), ("episodes", "drama_id", D),
            ("characters", "drama_id", D), ("storyboards", "id", S),
            ("comic_panels", "id", P), ("character_variants", "id", 901),
            ("storyboard_characters", "storyboard_id", S),
            ("storyboard_scenes", "storyboard_id", S),
            ("comic_panel_scenes", "panel_id", P), ("comic_panel_props", "panel_id", P),
            ("sys_task", "drama_id", D)):
        n = _db.q1(f"SELECT COUNT(*) c FROM {table} WHERE {key}=?", (val,))["c"]
        assert n == 0, f"{table} 残留 {n} 行"
    conn = getattr(_db._local, "conn", None)
    if conn is not None:
        conn.close()
        _db._local.conn = None


# ── 抽帧 / 直传合并为一条能力 ───────────────────────────────────────────

def test_normalize_shot_maps_direct_fields_to_frame_schema():
    """直传用 shots/duration/dialogue,抽帧用 storyboards/action_steps/line。

    两条路合并成一条后产物必须同构,否则下游要分两套写法 —— 那正是当初
    两套分镜并存、各自缺功能的根源。
    """
    shot = {"shot_type": "特写", "camera": "推", "duration": 6,
            "action_steps": ["手抬起", "凑近产品"],
            "dialogue": ["姐妹们", "看这个"]}
    n = vc._normalize_shot(shot, 2)
    assert n["number"] == 2
    assert n["shot"] == "特写"            # shot_type → shot
    assert n["line"] == "姐妹们 / 看这个"  # dialogue 数组 → line 串
    assert n["start"] == 0.0
    assert n["end"] == 6.0                # duration 推出 end
    assert n["action_steps"] == ["手抬起", "凑近产品"]


def test_normalize_shot_respects_explicit_start():
    n = vc._normalize_shot({"start": 4, "duration": 3}, 1)
    assert (n["start"], n["end"]) == (4.0, 7.0)


def test_normalize_shot_survives_bad_duration():
    """模型偶尔给 duration="三秒" 这种值,不能整批分镜因此崩掉。"""
    n = vc._normalize_shot({"duration": "abc"}, 1)
    assert n["duration"] == 5.0
    assert n["end"] == 5.0


def test_normalize_shot_missing_fields_yields_usable_row():
    n = vc._normalize_shot({}, 1)
    for k in ("number", "start", "end", "shot", "camera", "action_steps"):
        assert k in n, f"缺字段 {k}"
    assert n["shot"] == "中景"             # 兜底景别


# ── 复刻任务要出现在「生成任务列表」里 ─────────────────────────────────

def test_clone_tasks_carry_episode_id():
    """list_tasks 按 episode_id 过滤;clone 任务此前只传 drama_id,
    episode_id 为 None → 复刻项目的生成任务在任务列表里一条都看不到。
    """
    import inspect
    from app.ui import main_window
    src = inspect.getsource(main_window.ClonePage)
    submits = [l for l in src.splitlines() if "TASKMGR.submit(\"clone" in l]
    assert submits, "未找到 clone 任务提交点"
    # 逐个检查后续若干行里是否带 episode_id
    lines = src.splitlines()
    for i, l in enumerate(lines):
        if "TASKMGR.submit(\"clone" in l:
            window = "\n".join(lines[i:i + 3])
            assert "episode_id=" in window, f"缺 episode_id: {l.strip()}"


def test_clone_task_types_have_chinese_labels():
    """sys_task.type 原样入库 clone_*,tr() 会回退成英文键名,需中文映射。"""
    from app.ui.task_panel import TASK_TYPE_LABEL
    for t in ("clone_analyze", "clone_image", "clone_video", "clone_merge"):
        assert t in TASK_TYPE_LABEL, f"{t} 缺中文标签"
        assert TASK_TYPE_LABEL[t].startswith("克隆")


# ── 参考视频播放:AV1 编码兜底 ──────────────────────────────────────────

def test_playable_video_converts_av1(tmp_path):
    """Qt Multimedia 在 Windows 上放不了 AV1(B 站参考视频就是 av01),
    必须转 H.264 再播 —— 否则用户点「看原视频」只有黑屏。
    """
    import subprocess
    from pathlib import Path

    from app.core import config
    from app.ui.main_window import _playable_video

    ff = config.find_ffmpeg()
    if not ff:
        return                                   # 环境没 ffmpeg,跳过
    src = tmp_path / "av1.mp4"
    r = subprocess.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10",
                        "-c:v", "libaom-av1", "-crf", "50", "-b:v", "0", str(src)],
                       capture_output=True, timeout=180)
    if not src.exists():
        return                                   # ffmpeg 无 AV1 编码器,跳过
    out = Path(_playable_video(str(src)))
    assert out.exists() and out.stat().st_size > 0
    probe = subprocess.run([ff, "-i", str(out)], capture_output=True).stderr.decode("utf-8", "replace")
    assert "h264" in probe, "AV1 源应被转成 H.264"


def test_playable_video_passes_through_non_av1(tmp_path):
    """非 AV1 不该白转一次码(转码要花几秒)。"""
    import subprocess
    from pathlib import Path

    from app.core import config
    from app.ui.main_window import _playable_video

    ff = config.find_ffmpeg()
    if not ff:
        return
    src = tmp_path / "h264.mp4"
    subprocess.run([ff, "-y", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
                   capture_output=True, timeout=180)
    if not src.exists():
        return
    assert _playable_video(str(src)) == str(src)


def test_playable_video_missing_file_returns_input():
    from app.ui.main_window import _playable_video
    assert _playable_video("") == ""
    assert _playable_video("nope.mp4") == "nope.mp4"


# ── 每镜只传一张参考图(对齐参考项目 build.py 的 --image-url 单数)────────

def test_pick_ref_kind_routes_shots_to_single_reference():
    """人物照 + 产品照同时传 → Agnes 把两张构图对称融合成**双头图**(实测)。

    所以每镜只能给一张:静物/特写镜用产品图,出镜/佩戴镜用人物图。
    """
    cases = [
        ("深绿色玉手镯静置于原木底座上,圆润饱满的形态初展示", "product"),
        ("深绿色玉手镯被托起展示,展现圆润形态与通透质地", "product"),
        ("玉手镯佩戴于手腕,女子举起手腕展示温润光泽", "presenter"),
        ("女子手举玉手镯微笑注视镜头", "presenter"),
        ("产品完整呈现,细腻质感", "product"),
        ("", "presenter"),
    ]
    for text, want in cases:
        assert vc._pick_ref_kind(text) == want, f"{text[:20]} 选错参考图"


def test_pick_ref_kind_prefers_static_over_person_words():
    """「被托起展示,展现圆润形态与通透质地」是产品特写,不能因含「光泽/质感」
    被判成人物镜 —— 静物词优先级必须高于人物词。"""
    assert vc._pick_ref_kind("被托起展示,展现圆润形态与通透质地") == "product"


def test_rewrite_does_not_hardcode_max_tokens(monkeypatch):
    """max_tokens 属厂商差异,必须由模型配置决定(设置页两个输入框)。

    写死 4096 时推理模型(minimax-M3 吐上万字符 <think>)把预算吃光,正文 JSON
    被截断 → extract_json 失败 → 分镜改写整份回退(实测连续失败两次)。
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(vc.rewrite_boards_for_product).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                assert kw.arg != "max_tokens", "改写仍显式传 max_tokens,未走模型配置"


@pytest.fixture
def qapp_stub():
    """保证 QApplication 只创建一次(Qt 不允许多实例)。"""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ── 人物参照图:三视图 + 自动换脸(用户定版,全身像路线已移除)─────────────

def test_turnaround_prompt_follows_project_style():
    """三视图必须**跟随项目视觉风格**(用户定版「复刻时要将视觉风格带入生成」)。

    此前写死写实电商底,理由(插画笔触让五官失真)只对插画类风格成立,不该
    替用户做决定;写实负面词(NOT illustration)只在写实兜底里,与插画类
    风格不再自相矛盾。
    """
    import inspect
    src = inspect.getsource(vc.build_presenter_turnaround)
    assert "style_value" in src, "三视图生成不接收项目风格"
    assert "db.style_prompt" in src, "三视图生成没有解析项目风格预设"
    assert "标准参考图" in src


def test_read_presenter_desc_extracts_look_only():
    """出镜照提取**只取长相**,不提取服装/配饰/鞋履(用户要求:
    「出镜照不要有服装形象的描述」「环境描写也不要出现,用参考图就行」)。

    复刻的着装跟原片分镜文案走;把出镜照的衣服写成文字锁,成片服装反而
    与原片对不上。旧版提取 footwear/styling 字段,已随该决策移除。
    """
    import inspect
    src = inspect.getsource(vc.read_presenter_desc)
    assert "appearance" in src, "长相提取缺失"
    # 返回值只有长相;styling/footwear 字段已随决策删除(pop 清理旧键不算)
    assert 'return {"appearance": app_} if app_ else None' in src
    assert "不要描述服装" in src, "提示词应显式禁止描述服装"


def _tmp_db(tmp_path, monkeypatch, work_type: str = "video_clone", style: str = ""):
    """测试专用的临时库 fixture(与 test_delete_drama_cascades 同一套路):
    落库路径指到 tmp_path + 重置 thread-local 连接。"""
    from app.core import db as _db
    monkeypatch.setattr(_db.config, "DB_PATH", tmp_path / "clone.sqlite3")
    old = getattr(_db._local, "conn", None)
    if old is not None:
        old.close()
    _db._local.conn = None
    _db.init_db()
    ts = _db.now()
    _db.ex("INSERT INTO dramas(id,title,work_type,style,status,created_at,updated_at)"
           " VALUES(?,?,?,?,?,?,?)", (801, "T", work_type, style, "pending", ts, ts))
    return _db


def test_sync_assets_builds_turnaround_and_swaps_face(tmp_path, monkeypatch):
    """角色资产 = 三视图 + 生成后**立刻换脸**(用户定版,替代全身像路线)。

    全身像路线的两个实测致命伤:服装按文字自由发挥与上传照对不上;脸经
    「换到全身像→再当参考」两次转手与三视图不是同一人。三视图从上传照生成
    (服装/体型同源)+ 换脸钉死五官,分镜参考用切格立绘(standing_ref_of)。
    """
    import json
    from PIL import Image
    _db = _tmp_db(tmp_path, monkeypatch, style="realistic")
    static = tmp_path / "static"
    static.mkdir()
    monkeypatch.setattr(_db.config, "STATIC_DIR", static)
    presenter = tmp_path / "presenter.png"
    Image.new("RGB", (64, 64), "white").save(presenter)
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"presenter": str(presenter)}}), 801))
    calls = {}

    def _fake_gen(prompt, out_name=None, config_id=None, reference_images=None,
                  skip_guard=False, **kw):
        calls["prompt"] = prompt
        calls["refs"] = reference_images
        out = tmp_path / "turnaround.png"
        Image.new("RGB", (256, 256), "white").save(out)   # 单姿势图 → 切格返回原图
        return out, "agnes"

    async_swap = {}

    def _fake_swap(source, template, swap_cfg_id=None):
        async_swap["args"] = (str(source), str(template))
        return template

    monkeypatch.setattr(vc.image_client, "generate_image", _fake_gen)
    monkeypatch.setattr(vc, "swap_clone_face", _fake_swap)
    monkeypatch.setattr(vc, "read_presenter_desc",
                        lambda p, config_id=None: {"appearance": "测试外观",
                                                   "styling": "测试服装",
                                                   "footwear": ""})

    cid, pid, sid = vc.sync_assets(801)

    assert cid, "出镜人物资产未创建"
    clone = _db.jload(_db.q1("SELECT metadata FROM dramas WHERE id=?", (801,))["metadata"], {})["clone"]
    assert clone.get("turnaround_image"), "三视图未生成"
    assert clone.get("turnaround_swapped") is True, "三视图生成后未自动换脸"
    assert clone.get("presenter_desc") == "测试外观", "人物描述未落库(此前恒为空)"
    assert async_swap["args"][0] == str(presenter), "换脸的 source 应是上传出镜照"
    row = _db.q1("SELECT image_url, comic_image_url FROM characters WHERE id=?", (cid,))
    assert row["comic_image_url"], "三视图应写 comic_image_url"
    assert row["image_url"], "分镜参考立绘应写 image_url"


def test_sync_assets_marks_swap_failure_visibly(tmp_path, monkeypatch):
    """换脸失败**不得静默**:保留生成底图但必须标记 turnaround_swapped=False,
    让界面提示「未换脸」—— 此前静默降级,用户拿路人脸当参考图而不自知。"""
    import json
    from PIL import Image
    _db = _tmp_db(tmp_path, monkeypatch)
    monkeypatch.setattr(_db.config, "STATIC_DIR", tmp_path / "static")
    presenter = tmp_path / "presenter.png"
    Image.new("RGB", (64, 64), "white").save(presenter)
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"presenter": str(presenter)}}), 801))

    def _fake_gen(prompt, out_name=None, config_id=None, reference_images=None,
                  skip_guard=False, **kw):
        out = tmp_path / "turnaround.png"
        Image.new("RGB", (256, 256), "white").save(out)
        return out, "agnes"

    def _fail_swap(source, template, swap_cfg_id=None):
        raise RuntimeError("换脸服务不可达")

    monkeypatch.setattr(vc.image_client, "generate_image", _fake_gen)
    monkeypatch.setattr(vc, "swap_clone_face", _fail_swap)
    monkeypatch.setattr(vc, "read_presenter_desc", lambda p, config_id=None: None)

    vc.sync_assets(801)
    clone = _db.jload(_db.q1("SELECT metadata FROM dramas WHERE id=?", (801,))["metadata"], {})["clone"]
    assert clone.get("turnaround_image"), "换脸失败也应保留生成底图"
    assert clone.get("turnaround_swapped") is False, "换脸失败必须可见地标记"


def test_pick_ref_kind_uses_single_reference_image():
    """主体参考的角色分工(2026-10-26 用户定版「每一镜都带齐三主图」后更新):

    · **每一镜**(含特写)都带齐三要素:三视图立绘 + 场景空景 + 产品图,
      顺序按镜类排主体优先;
    · 特写镜的立绘只为锚手部肤质,提示词必须点名「只参照手,严禁画出
      面部或身体」(否则照设定图把整个人画进腕部特写,实测 #03);
    · 多图参考池(ref_pool)仍然禁止;多锚时逐一点名参考图1/2/3 各锁什么。
    """
    import inspect
    src = inspect.getsource(vc.generate_shot_image)
    assert "ref_pool" not in src, "不应再有多图参考池(会引入重影)"
    assert "scene_img" in src and "standing_img" in src, "三要素未带齐"
    assert "参考图2(场景图)" in src, "多锚时必须逐一点名两张图各锁什么"
    assert "严禁画出她的面部或身体" in src, "特写镜带立绘必须限只参照手"


def test_shot_uses_cropped_standing_ref_not_full_turnaround():
    """分镜人物参考 = 三视图**切格后的单人立绘**,不是整张三视图。

    整张三视图有 4 个人物实例,当参考会把多实例一起画进画面(实测中近景镜
    出三个并排人物)。旧项目的 presenter_fullshot 保留作兼容兜底。
    """
    import inspect
    src = inspect.getsource(vc.generate_shot_image)
    assert "standing_ref_of" in src, "人物参考没有走三视图切格"
    assert "presenter_fullshot" in src, "旧项目的全身像兜底丢失"


def test_toolbar_orders_steps_by_execution_order():
    """工具条按钮顺序 = 执行顺序(用户实测反馈「step 按顺序排列」):
    1️⃣ 拆解 → 2️⃣ 备料(模特/产品图/出镜照)→ 3️⃣ 一键重绘 → 4️⃣ 合并。
    直传开关是**模式切换**不是步骤,固定最左,不参与编号。
    """
    import inspect
    from app.ui import main_window
    src = inspect.getsource(main_window.ClonePage)
    order = ["bar.addWidget(direct_btn)", "bar.addWidget(analyze_btn)",
             "bar.addWidget(presenter_btn)", "bar.addWidget(product_btn)",
             "bar.addWidget(presenter_img_btn)", "bar.addWidget(redraw_all_btn)",
             "bar.addWidget(merge_btn)"]
    pos = [src.index(s) for s in order]
    assert pos == sorted(pos), f"工具条按钮顺序乱了:{list(zip(order, pos))}"
    # 全身像路线已移除(用户定版);换脸入口(三视图手动换脸 + 首帧换脸)必须在
    assert "clone_fs_btn" not in src, "「重建人物全身像」按钮应已移除"
    assert "clone_swap_btn" in src and "_swap_turnaround_face" in src, "缺三视图手动换脸入口"
    assert "_shot_face_swap" in src, "缺首帧换脸入口"


def test_fullshot_generation_removed():
    """「不需要全身,只要三视图」—— 纯文字底图+换脸的全身像生成已删除。

    它的两个实测致命伤:服装按文字自由发挥与上传照对不上;脸经两次转手与
    三视图不是同一人。防哪天被加回分镜参考。旧项目已生成的 presenter_fullshot
    图仍作兜底可读(见 generate_shot_image._asset_img)。
    """
    assert not hasattr(vc, "build_presenter_fullshot"), "全身像生成应已删除"


def test_scene_anchor_picks_frame_and_builds_empty_scene(tmp_path, monkeypatch):
    """场景锚从**原视频**提取:挑代表帧 → 去人空景图 + 真实环境描述落库。

    旧实现 scene_prompt 硬编码「室内夜间:书桌+台灯+城市夜景」,与用户原片
    无关;scene_image=首镜生成图(带人),当参考会抄出第二人。
    """
    import json
    _db = _tmp_db(tmp_path, monkeypatch)
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    picks = {}
    for i in (1, 2):
        f = frames_dir / f"f{i:02d}.jpg"
        f.write_bytes(b"fake-jpeg")
        picks[i] = f
    ref = tmp_path / "ref.mp4"
    ref.write_bytes(b"fake-video")     # 必须真实存在,_resolve_local 检查存在性
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"reference": str(ref),
                                  "frames_dir": str(frames_dir)}}), 801))
    gen_calls = {}

    def _fake_chat(prompt, system=None, temperature=None, json_mode=None,
                   config_id=None, image_urls=None):
        if "是否出现以下任何一项" in prompt:
            # 内容门审查:返回干净判定
            return '{"person": false, "product": false}'
        assert len(image_urls) == 2, "应把抽出的帧都给多模态模型挑"
        return '{"frame": 2, "location": "夜晚书房", "lighting": "暖光台灯", "prompt": "木质书桌与窗外夜景"}'

    def _fake_gen(prompt, out_name=None, config_id=None, reference_images=None,
                  skip_guard=False, **kw):
        gen_calls["prompt"] = prompt
        gen_calls["refs"] = reference_images
        out = tmp_path / "scene.png"
        out.write_bytes(b"png")
        return out, "agnes"

    monkeypatch.setattr(vc.text_client, "chat", _fake_chat)
    monkeypatch.setattr(vc.image_client, "generate_image", _fake_gen)
    monkeypatch.setattr(vc, "_duration", lambda p: 16.0)

    assert vc.extract_scene_anchor(801) is True
    clone = _db.jload(_db.q1("SELECT metadata FROM dramas WHERE id=?", (801,))["metadata"], {})["clone"]
    assert clone.get("scene_image"), "空景图未落库"
    assert "夜晚书房" in clone.get("scene_prompt", ""), "环境描述未落库"
    assert clone.get("scene_location") == "夜晚书房"
    assert gen_calls["refs"] == [str(picks[2])], "应以模型挑中的第 2 帧为参考"
    assert "场景:" in gen_calls["prompt"]
    assert "no people" in gen_calls["prompt"], "空景图提示词必须明确去人"


def test_scene_anchor_failure_returns_false_without_blocking(tmp_path, monkeypatch):
    """场景锚任一步失败 → 返回 False 退回纯文字锚,不阻塞分镜分析。"""
    import json
    _db = _tmp_db(tmp_path, monkeypatch)
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"reference": str(tmp_path / "nope.mp4")}}), 801))
    assert vc.extract_scene_anchor(801) is False


def test_upload_material_marks_presenter_uploaded(tmp_path, monkeypatch):
    """补传过出镜照必须标记 presenter_uploaded:prepare_presenter 的防覆盖守卫
    读这个键,此前全仓库没人写入 —— 建项目没传照、事后补传的用户再点
    「AI 生成出镜模特」会把照片顶掉(守卫形同虚设)。"""
    from PIL import Image
    _db = _tmp_db(tmp_path, monkeypatch)
    static = tmp_path / "static"
    monkeypatch.setattr(_db.config, "STATIC_DIR", static)
    img = tmp_path / "me.png"
    Image.new("RGB", (32, 32), "white").save(img)

    vc.upload_material(801, "presenter", img)

    clone = _db.jload(_db.q1("SELECT metadata FROM dramas WHERE id=?", (801,))["metadata"], {})["clone"]
    assert clone.get("presenter_uploaded") is True


def test_replace_material_invalidates_old_turnaround(tmp_path, monkeypatch):
    """换出镜照 = 换人:旧三视图还是上一张脸,必须作废让 sync_assets 重生成。

    否则分镜参考锁的仍是旧人(实测:换照后首帧出的是前一张脸)。
    """
    import inspect
    src = inspect.getsource(vc.replace_material)
    assert 'clone.pop("turnaround_image", None)' in src, "换照未作废旧三视图"
    assert 'clone.pop("presenter_desc", None)' in src, "换照未作废旧人物描述"


# ── 用户素材不得被 AI 生成覆盖 ──────────────────────────────────────────

def test_prepare_presenter_never_overwrites_user_upload():
    """用户传了出镜照,再点「AI 生成出镜模特」不得把素材顶掉。

    实测踩过:原来无条件写 clone["presenter"],上传图被 AI 生成的男模特顶掉 →
      · 外观/服装从男模特提取 → 分镜人物性别乱跳、有的变男人;
      · 换脸把女性脸换上 → 女的体配男的服装。
    """
    import inspect
    src = inspect.getsource(vc.prepare_presenter)
    assert "presenter_uploaded" in src or "presenter_src" in src, \
        "prepare_presenter 未检查用户是否已上传素材"
    # 生成结果必须另存字段,不能直接落在 presenter 上当作主角素材
    assert "clone[\"presenter\"] = str(out)" in src, "应有条件地写入 presenter"
    assert "ai_presenter" in src, "AI 生成结果应另存以便区分"


def test_closeup_shot_prompt_excludes_person():
    """特写/微距镜不得拼人物描述。

    实测:产品特写镜提示词里带「出镜人物…」→ 模型在纯产品画面里凭空造出一张
    脸(张嘴嘶吼的半透明人影)。守卫里的 no onlookers 压不住,因为是提示词
    自己要求出现人物的。
    """
    import inspect
    src = inspect.getsource(vc.generate_shot_image)
    assert "_no_person" in src, "未对特写镜做人物剔除"


def test_single_person_guard_and_closeup_ref_trim(tmp_path, monkeypatch):
    """三张全带 + 单人守卫 + 绑定名失锚兜底(2026-10-27 三次实测事故,**必须真实调用**):

    · 事故一:改单人守卫时 `tail = consist + ...` 初始化行被挪丢 → 所有镜
      首帧 UnboundLocalError 全灭(任务表 1668/1669)。源码断言抓不到这种
      「代码顺序」错误 —— 本测试走真实调用路径;
    · 事故二:模型把立绘人物照画进画面、又配了第二个人 + 窗外巨大人脸
      (用户:「复刻要只有一个人」)→ 提示词必含单人守卫;
    · 事故三:绑定名全对不上(模型写「女生」,资产叫「出镜人物」)→ 三张锚
      被裁得只剩主图,一致性崩。绑定名全部失锚时必须**忽略绑定**回到三张全带
      (用户定版:「只要将三张图喂给模型,不就能保持一致性了」)。
    """
    import json
    from PIL import Image
    _db = _tmp_db(tmp_path, monkeypatch)
    static = tmp_path / "static"
    static.mkdir()
    monkeypatch.setattr(_db.config, "STATIC_DIR", static)
    presenter = tmp_path / "presenter.png"
    product = tmp_path / "product.png"
    scene = tmp_path / "scene.png"
    for p in (presenter, product, scene):
        Image.new("RGB", (64, 64), "white").save(p)
    # 旧分镜形态:绑定名**对不上**资产名(「女生」≠「出镜人物」),与用户
    # 新拆解的数据一致 —— 应触发「全部失锚 → 忽略绑定 → 三张全带」兜底
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?", (json.dumps({"clone": {
        "presenter": str(presenter),
        "presenter_desc": "女,25岁,测试外观",
        "product": str(product),
        "scene_image": str(scene),
        "storyboards": [
            {"number": 1, "shot": "中", "camera": "固定", "start": 0.0, "end": 2.5,
             "action": "出镜人物手托玉镯展示", "action_steps": [], "line": "",
             "product_use": "展示玉镯", "prompt": "",
             "characters": ["女生"], "props": ["玉镯"], "scene": "窗边木桌前"},
            {"number": 2, "shot": "特", "camera": "固定", "start": 2.5, "end": 4.0,
             "action": "手指托住玉镯特写", "action_steps": [], "line": "",
             "product_use": "特写展示", "prompt": "",
             "characters": [], "props": ["玉镯"], "scene": "窗边木桌前"},
        ],
    }}), 801))

    calls = []

    def _fake_gen(prompt, out_name=None, config_id=None, reference_images=None,
                  skip_guard=False, **kw):
        calls.append({"prompt": prompt, "refs": reference_images})
        out = tmp_path / f"ff{len(calls)}.png"
        Image.new("RGB", (32, 32), "white").save(out)
        return out, "agnes"

    monkeypatch.setattr(vc.image_client, "generate_image", _fake_gen)

    vc.generate_shot_image(801, 1, "真人写实")
    vc.generate_shot_image(801, 2, "真人写实")

    mid, close = calls[0], calls[1]
    # 单人守卫:文案无多人词 → 两镜提示词都必须带(含窗外/倒影条款)
    assert "只有出镜人物一个人" in mid["prompt"], "中景镜缺单人守卫"
    assert "不得出现任何人影或倒影" in close["prompt"], "特写镜缺窗外/倒影条款"
    # 绑定名全部失锚 → 忽略绑定,中景三张全带(人物立绘/空景/产品一个不少)
    assert presenter in (mid["refs"] or []), "中景镜应带人物立绘锚脸"
    # 2026-10-28 定版(用户反馈「服装在变」后):特写镜**照带**立绘 ——
    # 裁掉立绘服装就逐镜自由发挥;第二个人的问题由景别归一 + 守卫生效根治,
    # 不靠裁参考图。头像绑定关系(图 N = 角色名)与短剧首帧同款。
    assert presenter in (close["refs"] or []), "特写镜必须带立绘锚服装/肤色"
    assert scene in (close["refs"] or []), "特写镜场景锚必须保留"
    assert product in (close["refs"] or []), "特写镜产品锚必须保留"


# ── 分卷分批生成(章数大时必然截断)──────────────────────────────────

def test_volume_batch_threshold_and_plan_size():
    """计划章数超过阈值要能算出卷数与批数。

    实测:999 章 → 34 卷,一次性输出约 8800 字,而默认 8192 tokens 只够约 6300 字,
    必然中途截断(JSON 括号都不闭合),表现为"卡住"。
    """
    from app.pipeline import novel as nv
    assert nv.VOLUME_BATCH_THRESHOLD > 0
    # 分卷调用**不得显式传 max_tokens**:GUI 路径 config_id=None 时任何兜底值
    #(4096)都会覆盖配置里的大预算(32768)→ MiniMax-M3 思考完预算耗尽,
    # 返回 0 字符(实测连续两次)。不传,text_client 自己读配置。
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(nv.draft_volume_in_batches).lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                assert kw.arg != "max_tokens", "分卷仍显式传 max_tokens,会覆盖配置"
    # 向上取整,不能漏章
    assert -(-999 // nv.VOLUME_CHAPTERS_PER_VOL) == 34
    assert nv.VOLUME_BATCH_SIZE >= 1


def test_volume_in_batches_rejects_small_books():
    """章数未过阈值不该走分批(白白多几次模型调用)。"""
    from app.pipeline import novel as nv
    import pytest
    from app.core import db
    small = db.q1("SELECT id FROM dramas WHERE total_episodes < 60 LIMIT 1")
    if not small:
        pytest.skip("库里没有小体量项目可验证")
    with pytest.raises(RuntimeError):
        nv.draft_volume_in_batches(small["id"])


# ── 资产表软删除列(缺列会让整条链路 OperationalError)──────────────────

def test_asset_tables_have_deleted_at_column(tmp_path, monkeypatch):
    """characters/scenes/props 必须有 deleted_at 列。

    storyboard.py 在这三张表上查 `deleted_at IS NULL`(软删除资产不算数),
    但三张表原本都没这一列 → SQLITE OperationalError: no such column: deleted_at,
    资产提取与分镜拆解整条链路直接报错(实测「重新拆分」一点就弹红框)。
    """
    from app.core import db as _db

    # 隔离必须改 config.DB_PATH。只设 YIHAO_DATA_DIR 时 config 早已导入,
    # DB_PATH 不会重算;reload(db) 只是把 db 模块再执行一遍,连的仍是真实库
    # —— init_db() 的启动回收会把另一个实例正在跑的任务当孤儿收走
    # (实测:跑一次 pytest 就杀掉了用户 20:27 创建的章节计划任务)。
    monkeypatch.setattr(_db.config, "DB_PATH", tmp_path / "asset_schema.sqlite3")
    old = getattr(_db._local, "conn", None)
    if old is not None:
        old.close()
    _db._local.conn = None
    _db.init_db()
    for t in ("characters", "scenes", "props", "storyboards"):
        cols = [r[1] for r in _db.get_db().execute(f"PRAGMA table_info({t})").fetchall()]
        assert "deleted_at" in cols, f"{t} 缺 deleted_at 列"


# ── GUI 构造冒烟:后端能跑 ≠ 界面能跑 ────────────────────────────────

def test_novel_plan_dialog_constructs(qapp_stub):
    """策划对话框必须能**真正构造**出来。

    教训(实测):接自动保存信号时写成 `lambda _t, k=key: ...`,
    PySide6 在对话框初始化时按 0 参调用 textChanged → TypeError,
    对话框构造即失败,后面所有分卷代码一行都没跑到。
    而我当时的验证方式是**单独 import/调用 novel.py 的后端函数**,
    全部成功 → 误报"好了"。后端能跑 ≠ 界面能跑,必须构造真实控件。

    这里只保证"构造不抛异常";不真正跑生成(要调模型,太慢太贵)。
    """
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:                                  # pragma: no cover
        import pytest
        pytest.skip("无 PySide6")
    app = QApplication.instance() or QApplication([])
    from app.ui.novel_dialogs import NovelPlanDialog
    from app.core import db

    did = db.q1("SELECT id FROM dramas WHERE work_type='novel' LIMIT 1")
    if not did:
        import pytest
        pytest.skip("库里没有小说项目可构造")
    dlg = NovelPlanDialog(None, did["id"])      # 构造阶段就会触发 textChanged 连接
    assert dlg is not None


# ── 全书章数不得被生成结果覆盖 ─────────────────────────────────────────

def test_chapter_count_not_overwritten_by_generated_count(tmp_path, monkeypatch):
    """用户设的 999 章不能被自己跑出来的 60 章覆盖。

    现场:`total_episodes` 同时表示「集数」和「全书章数」,而
    generate_chapters_batched 跑完会把它写成**实际生成的章数**。
    于是用户设 999 → 生成 60 章 → 下次打开对话框只剩 60,设定永久丢失。
    章数必须存在 novel_meta.chapter_count,与集数字段分开。
    """
    from app.core import db as _db
    import json as _json

    # 隔离必须改 `config.DB_PATH`,不能只设 YIHAO_DATA_DIR 环境变量 ——
    # config 在**导入时**就把 DATA_DIR 算成 DB_PATH 了,之后再改环境变量完全无效;
    # 而 db.get_db() 连的正是 config.DB_PATH。原写法只 reload 了 db 没 reload
    # config,于是每次跑测试都往 data/yihao.sqlite3(用户真实库)塞一条名为
    # 「T」的 novel 项目,用户删掉还会再出现 —— id 落在 88 万~97 万区间。
    # 同文件的 test_delete_drama_cascades_all_related_tables 用的就是这个写法。
    monkeypatch.setattr(_db.config, "DB_PATH", tmp_path / "planchain.sqlite3")
    old = getattr(_db._local, "conn", None)
    if old is not None:
        old.close()
    _db._local.conn = None
    _db.init_db()

    # init_db 会灌一份种子数据并占用 id=1,所以自建这条要用别的 id
    _new_id = 990001
    _db.ex("INSERT INTO dramas(id,title,work_type,status,total_episodes,novel_meta,"
           "created_at,updated_at) VALUES(?,'plan-scale-test','novel','pending',60,?,?,?)",
           (_new_id, _json.dumps({"chapter_count": 999}), _db.now(), _db.now()))
    from app.pipeline import novel as nv
    n, _w = nv._plan_scale(_new_id, None, None)
    assert n == 999, f"章数被回落成 {n},用户设的 999 丢失"


def test_chapter_count_written_to_meta_not_total_episodes():
    """保存规模时只写 novel_meta,不得再覆盖 total_episodes(那是集数)。"""
    import inspect
    from app.ui import novel_dialogs as nd
    src = inspect.getsource(nd.NovelPlanDialog._on_size_changed)
    assert "chapter_count" in src, "规模保存未写 chapter_count"
    assert "total_episodes=?" not in src, "仍在覆盖 total_episodes(会破坏集数与章数的耦合)"


# ── 服务编辑弹窗不得崩溃 ──────────────────────────────────────────────

def test_service_dialog_opens_for_existing_config(qapp_stub):
    """编辑已有服务配置时,弹窗必须能构造出来。

    实测崩过一次:`self._custom_idx = self.provider_combo.addItem(...)` ——
    QComboBox.addItem() 返回 **None**(不是索引),于是 _custom_idx 是 None,
    _prefill 里 setCurrentIndex(None) 抛 TypeError,异常被吞,
    表现为「点编辑弹不出来」。
    """
    from app.core import db
    from app.ui.settings_dialog import ServiceDialog
    row = db.q1("SELECT * FROM ai_service_configs WHERE service_type='text' LIMIT 1")
    if not row:
        import pytest
        pytest.skip("库里没有文本服务配置")
    dlg = ServiceDialog("text", None, existing=dict(row))
    assert dlg is not None


def test_custom_provider_index_is_valid(qapp_stub):
    """_custom_idx 必须是有效整数 —— addItem 的返回值是 None,不能直接赋值。"""
    from app.ui.settings_dialog import ServiceDialog
    from app.core import db
    row = db.q1("SELECT * FROM ai_service_configs WHERE service_type='text' LIMIT 1")
    if not row:
        import pytest
        pytest.skip("库里没有文本服务配置")
    dlg = ServiceDialog("text", None, existing=dict(row))
    idx = dlg._custom_idx
    assert isinstance(idx, int), f"_custom_idx 应为 int,实际 {type(idx).__name__}"
    assert 0 <= idx < dlg.provider_combo.count()


# ── 2026-10-26 第二批:三要素参考图 / 服装锁定 / 重绘要求 / 口播改写 ──

def test_rewrite_prompt_rewrites_voiceover_line():
    """口播(line)必须随产品同步改写 —— 实测:动作都换成玉手镯了,口播还在
    说「打开看着口红正红」,合成出来嘴上夸的是旧产品(用户截图)。"""
    assert "line(台词)—— 完全沿用" not in vc.REWRITE_PROMPT, "口播不得再列入照抄字段"
    assert "line(推测口播/字幕)也必须同步改写" in vc.REWRITE_PROMPT


def test_shot_person_refs_carry_three_elements():
    """用户定版「每镜三要素:人物/场景/商品」:人物镜三张全带并逐一点名
    (参考图3=产品图);特写镜不喂人物要素(会把完整人物带进单肢特写)。"""
    import inspect
    src = inspect.getsource(vc.generate_shot_image)
    assert "product_img" in src, "产品图未进入参考图组装"
    assert "参考图3(产品图)" in src, "三要素未逐一点名"
    assert 'main_kind == "presenter"' in src


def test_shot_does_not_lock_clothing_to_presenter_desc():
    """服装**不做文字锁**(用户要求,反转旧决策):着装跟原片分镜文案走,
    跨镜一致靠参考图1(人物设定图)锚定。出镜照的服装描述已按用户要求
    移除 —— 锁到上传照的衣服会让成片服装跟原片对不上。"""
    import inspect
    src = inspect.getsource(vc.generate_shot_image)
    assert "服装固定为" not in src, "出镜照服装文字锁应已删除"
    assert "一律以此句为准" not in src
    # 人物身份锁仍在(五官/发型/体型以人物设定图为准),只是不锁服装文字
    assert "发型" in src and "人物设定图" in src


def test_closeup_rule_permits_both_hands_of_presenter():
    """特写单肢规则必须措辞为「只许本人的手、不许第二个人的手」,不能限
    「一只手」—— 分镜里大量正常动作是双手调整/佩戴(实测镜04/05)。"""
    import inspect
    src = inspect.getsource(vc.generate_shot_image)
    assert "只允许出现一只" not in src, "限一只手会把双手动作改坏"
    assert "第二个人的手" in src and "一手或" in src


def test_redraw_hints_global_and_per_shot():
    """重绘要求两层注入:全局(设置表,跨项目)+ 单镜(分镜条目)。"""
    import inspect
    src = inspect.getsource(vc.generate_shot_image)
    assert "yihao.clone_redraw_hint" in src, "全局重绘要求未注入"
    assert "user_hint" in src, "单镜重绘备注未注入"


def test_video_generation_feeds_three_elements():
    """视频生成同样带三要素参考图(用户定版),特写镜剔除人物要素。"""
    import inspect
    src = inspect.getsource(vc.generate_shot_video)
    assert "reference_images=video_refs" in src, "视频生成未带参考图"
    assert "standing_ref_of" in src, "视频参考未用三视图立绘"


# ── 2026-10-26 第三批:think 垃圾不进标题(novel 侧闸门,归档在本文件便于回归)──

def test_strip_think_drops_leading_unclosed_think_line():
    """M3 偶发把指令行「<think>We need answer...」吐在正文首行且无闭合标签:
    旧规则只删标签不删内容,思考体残留成首行 → 标题提取整句当章节名(实测)。"""
    dirty = "<think>We need answer only chapter title only Simplified Chinese <=12 cha\n\n黑货运门外的铁皮应顶着额额。\n\n阿虎把烟头弹进里屋。"
    out = vc_novel._strip_think(dirty)
    assert "<think>" not in out and "We need answer" not in out
    assert out.startswith("黑")


def test_clean_chapter_name_rejects_think_markers():
    assert vc_novel._clean_chapter_name("<think>We need answer only chapter title") == ""
    assert vc_novel._clean_chapter_name("正常的章节名") == "正常的章节名"


def test_extract_title_rejects_think_first_line():
    assert vc_novel.extract_title_from_content("# <think>We need answer only chapter\n\n正文") == ""
    assert vc_novel.extract_title_from_content("# 归乡的井\n\n正文") == "归乡的井"


# ── 2026-10-28:景别简称归一(「手复」项目实测回归)──────────────────────
# 分镜模型会回单字简称(特/中/近),原样落库后特写守卫按全称(「特写/微距」)
# 匹配全部静默失效 → 特写镜出第二个人 + 完整人脸。归一化必须覆盖读写两端。

def test_canon_shot_kind_maps_single_char_abbreviations():
    assert vc._canon_shot_kind("特") == "特写"
    assert vc._canon_shot_kind("中") == "中景"
    assert vc._canon_shot_kind("近") == "近景"
    assert vc._canon_shot_kind("大特") == "大特写"
    assert vc._canon_shot_kind("中近") == "中近景"
    assert vc._canon_shot_kind("远") == "远景"
    assert vc._canon_shot_kind("全") == "全景"


def test_canon_shot_kind_keeps_full_and_unknown_values():
    """全称原样保留;未知景别(航拍/俯拍)不猜 —— 猜错比不归一更糟。"""
    assert vc._canon_shot_kind("特写") == "特写"
    assert vc._canon_shot_kind("特写镜头") == "特写"
    assert vc._canon_shot_kind("微距") == "微距"
    assert vc._canon_shot_kind("中近景") == "中近景"   # 不能被「中景」前缀误吞
    assert vc._canon_shot_kind("航拍") == "航拍"
    assert vc._canon_shot_kind("") == ""
    assert vc._canon_shot_kind(None) == ""


def test_normalize_shot_canonicalizes_abbreviation():
    assert vc._normalize_shot({"shot_type": "特", "duration": 4}, 1)["shot"] == "特写"
    assert vc._normalize_shot({"shot": "中"}, 1)["shot"] == "中景"


def test_pick_ref_kind_closeup_by_abbreviation():
    """存量项目分镜存的是「特」:必须按景别判产品锚,不能掉进文案兜底。"""
    assert vc._pick_ref_kind("", "特") == "product"
    # 文案里明明是人物动作,景别是特 → 仍以景别为准(判定看画面主体)
    assert vc._pick_ref_kind("女子坐在桌前低头看向桌面的手镯", "特") == "product"
    assert vc._pick_ref_kind("", "中") == "presenter"
    assert vc._pick_ref_kind("", "近") == "presenter"


def test_closeup_guards_read_canonized_kind():
    """两处特写守卫(生图单肢规则 / 生视频守卫)必须作用在归一化后的景别上,
    防止以后再引入新的简称漏配(源码契约,照 test_clone_tasks_carry_episode_id 式)。"""
    import inspect
    assert "_canon_shot_kind" in inspect.getsource(vc.generate_shot_image)
    assert "_canon_shot_kind" in inspect.getsource(vc.generate_shot_video)


def test_generate_shot_video_closeup_guard_fires_for_abbreviated_shot(monkeypatch):
    """端到端回归:分镜存简称「特」时,视频提示词必须带上特写单肢守卫
    (修复前:守卫匹配「特写」不中「特」,成片出第二个人 —— 手复 #02/#03 实测)。"""
    from pathlib import Path

    captured = {}

    def _fake_generate(prompt, **kw):
        captured["prompt"] = prompt
        return Path("x.mp4"), "agnes"

    boards = [{"number": 1, "start": 0.0, "end": 4.0, "shot": "特",
               "camera": "固定", "action": "双手捏住玉镯两侧",
               "prompt": "特写:双手取下玉镯", "first_frame": "ff.png"}]
    monkeypatch.setattr(vc, "_clone_storyboards", lambda drama_id: boards)
    monkeypatch.setattr(vc, "_meta", lambda drama_id: {"clone": {}})
    monkeypatch.setattr(vc, "_save_meta", lambda drama_id, meta: None)
    monkeypatch.setattr(vc.db, "style_prompt", lambda style: "真人写实风格")
    monkeypatch.setattr(vc.db, "drama_style", lambda drama_id: "live")
    monkeypatch.setattr(vc.video_client, "generate_video", _fake_generate)
    vc.generate_shot_video(1, 1)
    assert "不得出现第二个人的手或手臂" in captured["prompt"], (
        "景别简称「特」未触发特写守卫")


# ── 2026-10-28:全书分批逐批落库(用户实测 520/999、库里 0 章)──────────────
# generate_chapters_batched 此前只在全部批次跑完后一次性 UPDATE:中途断网/
# 关应用/单批重试耗尽 = 已生成批次全丢。按卷路径一直有 _merge_chapters,
# 全书分批补齐同款,并验证「中途失败已落批次不丢」。

class _NovelDB:
    """够 generate_chapters_batched 用的假 db:记录全部写入。"""

    def __init__(self):
        self.writes: list[tuple] = []

    def q1(self, sql, args=()):
        if "novel_chapters" in sql:
            return {"novel_chapters": None}
        if "novel_contract" in sql:
            return {"novel_meta": None, "novel_contract": ""}
        if "novel_meta" in sql:
            return {"novel_meta": None}
        return None

    def q(self, sql, args=()):
        return []

    def jload(self, raw, default=None):
        import json as _json
        try:
            return _json.loads(raw) if raw else (default if default is not None else {})
        except Exception:
            return default if default is not None else {}

    def ex(self, sql, args=()):
        self.writes.append((sql, args))
        return 1

    def now(self):
        return "2026-10-28T00:00:00Z"


def _plan_db(monkeypatch) -> _NovelDB:
    from app.pipeline import novel as nv
    from app.core import config as _config
    fake = _NovelDB()
    monkeypatch.setattr(nv, "db", fake)
    monkeypatch.setattr(nv, "_plan_scale", lambda drama_id, chapter_count, word_count: (4, 2500))
    monkeypatch.setattr(nv, "plan_config_id", lambda: None)
    monkeypatch.setattr(nv, "_plan_budgets", lambda config_id: (4096,))
    monkeypatch.setattr(nv.config, "resolve_content_language", lambda drama_id: "zh")
    return fake


def _batch_json(start: int, cnt: int) -> str:
    import json as _json
    return _json.dumps({"chapters": [
        {"number": start + i, "title": f"第{start + i}章",
         "goal": f"目标{start + i}", "events": f"事件{start + i}",
         "cliffhanger": f"钩子{start + i}"} for i in range(cnt)]}, ensure_ascii=False)


def test_chapters_batched_persists_every_batch(tmp_path, monkeypatch):
    """全书分批必须**每批落库**:999 章 25 批跑二三十分钟,逐批合并写库,
    任何时刻中断,已生成批次都在库里(用户反馈「不要一次性生成」)。"""
    from app.pipeline import novel as nv
    monkeypatch.setattr(nv, "CHAPTER_BATCH", 2)
    fake = _plan_db(monkeypatch)

    def _fake_agent(name, prompt, **kw):
        import re as _re
        m = _re.search(r"第\s*(\d+)\s*章到第\s*(\d+)\s*章", prompt)
        a, b = int(m.group(1)), int(m.group(2))
        return _batch_json(a, b - a + 1)

    monkeypatch.setattr(nv.runner, "run_agent", _fake_agent)
    out = nv.generate_chapters_batched(801, chapter_count=4, word_count=2500)
    assert out["count"] == 4
    plan_writes = [a for sql, a in fake.writes if "novel_chapters=?" in sql]
    # 2 批逐批落库 + 收尾 1 次 = 至少 3 次写 novel_chapters
    assert len(plan_writes) >= 3, f"逐批落库缺失,只写了 {len(plan_writes)} 次"
    import json as _json
    first_batch = _json.loads(plan_writes[0][0])
    assert len(first_batch) == 2, "第一批完成时就该落 2 章,而不是等全部跑完"


def test_chapters_batched_failure_keeps_finished_batches(tmp_path, monkeypatch):
    """中途失败(某批重试耗尽)时,前面批次必须已经在库里 —— 修复前
    all_ch 只在内存,520 章跟着异常一起蒸发(实测)。"""
    import pytest as _pytest
    from app.pipeline import novel as nv
    monkeypatch.setattr(nv, "CHAPTER_BATCH", 2)
    fake = _plan_db(monkeypatch)

    calls = {"n": 0}

    def _fake_agent(name, prompt, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _batch_json(1, 2)
        raise RuntimeError("模拟第二批重试耗尽")

    monkeypatch.setattr(nv.runner, "run_agent", _fake_agent)
    with _pytest.raises(RuntimeError):
        nv.generate_chapters_batched(802, chapter_count=4, word_count=2500)
    plan_writes = [a for sql, a in fake.writes if "novel_chapters=?" in sql]
    assert plan_writes, "失败时连第一批都没落库"
    import json as _json
    assert len(_json.loads(plan_writes[0][0])) == 2, "已成功批次必须保留"


# ── 镜头脚本三段式(对齐小说线/短剧线的分镜格式)─────────────────────────
#
# 复刻此前每镜只有一行 action_steps 摘要(「中景·固定 · 1.xxx; 2.xxx」),
# 场景与道具只能靠自然语言暗示,模型每镜自由发挥 → 背景/陈设/道具逐镜漂。
# 小说线(与短剧线同一套 storyboard_breaker)的分镜是三段式:
#   description / atmosphere / video_prompt,三段都带 @资产名。
# 下面这组测试锁住「复刻也产出同样三段」这条不变量。

def test_analysis_prompt_requires_three_script_fields(tmp_path, monkeypatch):
    """抽帧拆解的提示词必须要求三段式脚本 —— 少了它们,界面就只有一行摘要,
    场景与道具没有名字可指(@资产名是资产对齐的锚)。"""
    import json
    _db = _tmp_db(tmp_path, monkeypatch)
    ref = tmp_path / "ref.mp4"
    ref.write_bytes(b"fake")
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"reference": str(ref)}}), 801))
    frames = tmp_path / "frames"
    frames.mkdir()
    f1 = frames / "f1.jpg"
    f1.write_bytes(b"jpg")
    monkeypatch.setattr(vc, "extract_frames", lambda *a, **k: [f1])
    monkeypatch.setattr(vc, "_duration", lambda p: 8.0)
    monkeypatch.setattr(vc, "extract_scene_anchor", lambda *a, **k: False)
    monkeypatch.setattr(vc, "sync_assets", lambda *a, **k: (None, None, None))
    seen = {}

    def _chat(prompt, **kw):
        seen["prompt"] = prompt
        return json.dumps({"storyboards": [{
            "number": 1, "start": 0, "end": 8, "shot": "中景", "camera": "固定",
            "action": "举起产品", "action_steps": ["双手托住玉镯", "缓缓抬至镜头前"],
            "description": "【镜头1】中景固定,双手托住玉镯;【镜头2】缓推至手部特写",
            "atmosphere": "侧窗自然光,冷调,室内安静",
            "video_prompt": "出场人物:@出镜人物 道具:@主推产品 场景:@主场景\n[0-3秒] 固定",
            "characters": ["出镜人物"], "props": ["主推产品"], "scene": "主场景"}]},
            ensure_ascii=False)

    monkeypatch.setattr(vc.text_client, "chat", _chat)
    boards = vc.analyze_reference(801)
    for key in ("description", "atmosphere", "video_prompt"):
        assert key in seen["prompt"], f"拆解提示词没要求 {key}"
    assert "【镜头1】" in boards[0]["description"]
    assert boards[0]["atmosphere"]
    assert "@主推产品" in boards[0]["video_prompt"]


def test_direct_mode_prompt_requires_three_script_fields():
    """整段直传模式(UNDERSTAND_PROMPT)也要产出三段式。"""
    for key in ("description", "atmosphere", "video_prompt"):
        assert key in vc.UNDERSTAND_PROMPT, f"直传提示词没要求 {key}"


def test_normalize_shot_keeps_script_fields():
    """直传归一化不能把三段式字段丢掉。"""
    s = vc._normalize_shot({"shot_type": "特", "duration": 4,
                            "description": "【镜头1】特写手部",
                            "atmosphere": "冷调侧光",
                            "video_prompt": "出场人物:@出镜人物"}, 1)
    assert s["shot"] == "特写"
    assert s["description"] == "【镜头1】特写手部"
    assert s["atmosphere"] == "冷调侧光"
    assert s["video_prompt"] == "出场人物:@出镜人物"


def test_rewrite_also_rewrites_script_fields(monkeypatch):
    """按新产品改写时必须**同步改**三段式 —— 不改的话,动作换成玉镯,
    脚本里还在说口红(界面显示的正是这三段)。"""
    import json
    payload = {"storyboards": [{
        "number": 1, "action": "举起玉镯", "action_steps": ["托住玉镯"],
        "product_use": "玉镯呈现", "prompt": "0-4秒:展示玉镯",
        "description": "【镜头1】举起玉镯至胸前",
        "atmosphere": "冷调侧光,安静",
        "video_prompt": "出场人物:@出镜人物 道具:@主推产品 场景:@主场景"}]}
    monkeypatch.setattr(vc.text_client, "chat",
                        _fake_chat(json.dumps(payload, ensure_ascii=False)))
    out = vc.rewrite_boards_for_product(_BOARDS, "玉镯", assets="已知资产")
    assert out[0]["description"] == "【镜头1】举起玉镯至胸前"
    assert out[0]["atmosphere"] == "冷调侧光,安静"
    assert "@主推产品" in out[0]["video_prompt"]


def test_rewrite_prompt_keeps_asset_names_verbatim():
    """改写提示词必须把「已知资产」喂进去,并要求 @引用逐字保留 ——
    名字一改,这一镜的参考图就对不上。"""
    assert "{assets}" in vc.REWRITE_PROMPT
    assert "assets=" in __import__("inspect").getsource(
        vc.rewrite_boards_for_product)


def test_shot_video_prompt_prefers_script_field():
    """三段式的 video_prompt 优先 —— 它带 @资产名与 3 秒分段,
    是「跨镜场景与道具一致」的执行点。"""
    b = {"start": 0, "end": 4, "prompt": "旧拼装句",
         "video_prompt": "出场人物:@出镜人物 场景:@主场景\n[0-3秒] 缓推"}
    assert vc._shot_video_prompt(b).startswith("出场人物:")


def test_legacy_board_gets_synthesized_script():
    """存量分镜没有三段式字段 → 读侧兜底合成,界面不至于空一大块。"""
    b = {"shot": "中景", "camera": "固定",
         "action_steps": ["托住玉镯", "抬至镜头前"]}
    vc.ensure_script_fields(b)
    assert "【镜头1】" in b["description"]
    assert "托住玉镯" in b["description"]
    assert b["atmosphere"] == ""     # 合成不出来就留空,交给「重写镜头脚本」
    assert b["video_prompt"]


def test_regenerate_script_writes_fields_and_keeps_pacing(tmp_path, monkeypatch):
    """「重写镜头脚本」只补三段,镜号/起止/景别/运镜/动作一个都不许动。"""
    import json
    _db = _tmp_db(tmp_path, monkeypatch)
    boards = [{"number": 1, "start": 0, "end": 4, "shot": "中景", "camera": "固定",
               "action": "举起产品", "action_steps": ["托住产品"]},
              {"number": 2, "start": 4, "end": 9, "shot": "特写", "camera": "推",
               "action": "产品特写", "action_steps": ["推到镜头前"]}]
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"storyboards": boards}}, ensure_ascii=False), 801))
    payload = {"storyboards": [
        {"number": 1, "description": "【镜头1】固定中景,双手托住产品",
         "atmosphere": "侧窗自然光,冷调",
         "video_prompt": "出场人物:@出镜人物 场景:@主场景"},
        {"number": 2, "description": "【镜头1】缓推至产品特写",
         "atmosphere": "同一场景,冷调延续",
         "video_prompt": "出场人物:@出镜人物 场景:@主场景"}]}
    monkeypatch.setattr(vc.text_client, "chat",
                        _fake_chat(json.dumps(payload, ensure_ascii=False)))
    assert vc.regenerate_script(801) == 2
    meta = _db.jload(_db.q1("SELECT metadata FROM dramas WHERE id=?", (801,))["metadata"],
                     {})["clone"]
    bs = meta["storyboards"]
    assert bs[0]["description"].startswith("【镜头1】")
    assert bs[1]["atmosphere"] == "同一场景,冷调延续"
    assert (bs[0]["start"], bs[0]["end"], bs[0]["shot"], bs[0]["camera"]) == \
        (0, 4, "中景", "固定")
    assert (bs[1]["start"], bs[1]["end"], bs[1]["shot"], bs[1]["camera"]) == \
        (4, 9, "特写", "推")
    assert bs[0]["action_steps"] == ["托住产品"]


def test_regenerate_script_failure_keeps_table(tmp_path, monkeypatch):
    """补写失败绝不能毁掉已有分镜表(它是增强手段,不是前置依赖)。"""
    import json
    _db = _tmp_db(tmp_path, monkeypatch)
    boards = [{"number": 1, "start": 0, "end": 4, "shot": "中景"}]
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"storyboards": boards}}, ensure_ascii=False), 801))

    def _boom(*a, **k):
        raise RuntimeError("模拟模型故障")

    monkeypatch.setattr(vc.text_client, "chat", _boom)
    assert vc.regenerate_script(801) == 0
    meta = _db.jload(_db.q1("SELECT metadata FROM dramas WHERE id=?", (801,))["metadata"],
                     {})["clone"]
    assert "description" not in meta["storyboards"][0]


def test_clone_task_label_for_script_rewrite():
    """新任务类型要有中文标签,否则任务面板显示英文键名。"""
    from app.ui.task_panel import TASK_TYPE_LABEL
    assert TASK_TYPE_LABEL["clone_script"].startswith("克隆")


def test_clone_card_shows_three_script_sections(tmp_path, monkeypatch, qapp_stub):
    """分镜卡片要按小说线的格式展示「分镜描述/氛围/视频提示词」三段 ——
    界面与脚本格式对齐,用户才能看出「这一镜锁的是哪个场景、哪个道具」。"""
    import json
    from PySide6.QtWidgets import QTextEdit
    from app.ui.main_window import ClonePage
    _db = _tmp_db(tmp_path, monkeypatch)
    boards = [{
        "number": 1, "start": 0, "end": 4, "shot": "中景", "camera": "固定",
        "action": "举起产品", "action_steps": ["托住产品"],
        "description": "【镜头1】固定中景,双手托住产品",
        "atmosphere": "侧窗自然光,冷调",
        "video_prompt": "出场人物:@出镜人物 场景:@主场景",
        "narration": "这枚玉镯温润又油光"}]
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"storyboards": boards}}, ensure_ascii=False), 801))
    page = ClonePage()
    page.load(801)
    html = " ".join(b.toHtml() for b in page.findChildren(QTextEdit))
    for label in ("分镜描述", "氛围", "视频提示词", "旁白"):
        assert label in html, f"卡片缺少「{label}」段"
    assert "【镜头1】" in html


def test_clone_video_prompt_maps_asset_names_to_reference_index(tmp_path, monkeypatch):
    """视频提示词里的 @资产名 要换成 @图片N(与小说线同款)——

    复刻此前把 @出镜人物/@主场景/@主推产品 原样发给视频模型,模型无从判断
    哪张参考图是谁:三张图(人物立绘/场景空景/产品图)被平均融合,人物与场景
    在运动过程中漂移(首帧对、后面跑偏)。序号与 reference_images 严格对齐。
    """
    import json
    from PIL import Image
    _db = _tmp_db(tmp_path, monkeypatch, style="realistic")
    static = tmp_path / "static"
    static.mkdir()
    monkeypatch.setattr(_db.config, "STATIC_DIR", static)
    ta = tmp_path / "ta.png"
    Image.new("RGB", (64, 64), "white").save(ta)
    sc = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), "white").save(sc)
    pr = tmp_path / "product.png"
    Image.new("RGB", (64, 64), "white").save(pr)
    boards = [{"number": 1, "start": 0, "end": 4, "shot": "中景",
               "first_frame": str(ta),
               "video_prompt": "出场人物:@出镜人物 道具:@主推产品 场景:@主场景\n"
                               "[0-3秒] 固定中景"}]
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"storyboards": boards,
                                  "turnaround_image": str(ta),
                                  "scene_image": str(sc),
                                  "product": str(pr)}}, ensure_ascii=False), 801))
    seen = {}

    def _gen(prompt, **kw):
        seen["prompt"] = prompt
        seen["refs"] = kw.get("reference_images")
        out = tmp_path / "v.mp4"
        out.write_bytes(b"video")
        return out, "agnes"

    monkeypatch.setattr(vc.video_client, "generate_video", _gen)
    vc.generate_shot_video(801, 1)
    p = seen["prompt"]
    assert "@出镜人物" not in p and "@主场景" not in p and "@主推产品" not in p
    assert "@图片1" in p and "@图片2" in p and "@图片3" in p
    assert "参考图说明" in p
    # 序号必须与参考图顺序对齐(人物立绘 → 场景空景 → 产品图)
    assert len(seen["refs"]) == 3
    assert seen["refs"][0] == str(ta)
    assert seen["refs"][1] == str(sc)
    assert seen["refs"][2] == str(pr)


def test_header_example_follows_custom_asset_names():
    """信息头模板必须用本项目真实资产名 —— 模型照抄示例,写死「@出镜人物」
    就与用户自定义的产品名对不上(@名字对不上 → 换不成 @图片N → 参考图失锚,
    场景与道具逐镜漂)。"""
    assert vc._header_example({}) == "出场人物:@出镜人物 道具:@主推产品 场景:@主场景"
    assert vc._header_example({"presenter_name": "林小姐",
                               "product_name": "翡翠手镯"}) == \
        "出场人物:@林小姐 道具:@翡翠手镯 场景:@主场景"


# ── 视频提示词的严格格式 + 第四段旁白(用户 2026-10-28 定版)─────────────

def test_video_prompt_format_spec_is_shared_by_all_prompts():
    """四处提示词(抽帧拆解/整段直传/按产品改写/补写脚本)必须引用**同一份**
    视频提示词格式规格 —— 规格散开就会漂:改了一处忘了另一处,模型收到的
    要求自相矛盾。"""
    assert "出场人物：" in vc.VIDEO_PROMPT_FORMAT
    assert "。场景：" in vc.VIDEO_PROMPT_FORMAT
    assert "行首**必须重复一次 @场景名**" in vc.VIDEO_PROMPT_FORMAT
    assert "{vp_format}" in vc.REWRITE_PROMPT
    assert "{vp_format}" in vc.SCRIPT_PROMPT
    # 直传提示词是 f-string,规格已经插进去了(查内容而不是查占位符名)
    assert "行首**必须重复一次 @场景名**" in vc.UNDERSTAND_PROMPT
    import inspect
    assert "VIDEO_PROMPT_FORMAT" in inspect.getsource(vc.analyze_reference)


def test_video_prompt_format_marks_only_bound_assets():
    """@ 只标注**本镜绑定**的资产 —— 绑定决定参考图,@名是模型对上参考图的抓手。"""
    assert "characters / props / scene" in vc.VIDEO_PROMPT_FORMAT
    assert "没绑定的资产不要出现在 @ 里" in vc.VIDEO_PROMPT_FORMAT


def test_narration_is_part_of_script_fields():
    """脚本是四段:分镜描述/氛围/视频提示词/旁白(视频解说)。"""
    assert "narration" in vc.SCRIPT_FIELDS
    s = vc._normalize_shot({"shot_type": "中景", "narration": "这一段在讲产品"},
                           1)
    assert s["narration"] == "这一段在讲产品"


def test_rewrite_also_rewrites_narration(monkeypatch):
    """按新产品改写时旁白也要改 —— 原片旁白夸的是旧产品。"""
    import json
    payload = {"storyboards": [{
        "number": 1, "action": "举起玉镯", "action_steps": ["托住玉镯"],
        "product_use": "玉镯呈现", "prompt": "0-4秒:展示玉镯",
        "description": "【镜头1】举起玉镯", "atmosphere": "冷调侧光",
        "video_prompt": "出场人物：@出镜人物。场景：@主场景",
        "narration": "这枚玉镯温润又油光"}]}
    monkeypatch.setattr(vc.text_client, "chat",
                        _fake_chat(json.dumps(payload, ensure_ascii=False)))
    out = vc.rewrite_boards_for_product(_BOARDS, "玉镯", assets="已知资产")
    assert out[0]["narration"] == "这枚玉镯温润又油光"


def test_shots_and_narrations_stay_aligned(tmp_path, monkeypatch):
    """旁白必须与镜头视频**一一对应** —— 只按「有视频的镜」取,
    否则第 2 镜的旁白会混到第 1 镜的画面上(听起来就是串台)。"""
    import json
    _db = _tmp_db(tmp_path, monkeypatch)
    v1 = tmp_path / "v1.mp4"
    v1.write_bytes(b"v")
    v2 = tmp_path / "v2.mp4"
    v2.write_bytes(b"v")
    a2 = tmp_path / "a2.mp3"
    a2.write_bytes(b"a")
    boards = [
        {"number": 1, "video": str(v1)},                       # 有视频,没旁白
        {"number": 2, "video": str(v2), "narration_audio_url": str(a2)},
        {"number": 3, "narration_audio_url": str(a2)},        # 没视频,不参与
    ]
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"storyboards": boards}}, ensure_ascii=False), 801))
    shots, narrs = vc.clone_shots_with_narrations(801)
    assert len(shots) == len(narrs) == 2
    assert shots[0] == v1 and narrs[0] is None
    assert shots[1] == v2 and narrs[1] == a2


def test_synth_shot_narration_stores_audio_on_board(tmp_path, monkeypatch):
    """合成旁白后音频 URL 按镜号存回分镜条目(合片时混音要用)。"""
    import json
    _db = _tmp_db(tmp_path, monkeypatch)
    static = tmp_path / "static"
    static.mkdir()
    monkeypatch.setattr(_db.config, "STATIC_DIR", static)
    boards = [{"number": 1, "start": 0, "end": 4,
               "narration": "这枚玉镯温润又油光"}]
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"storyboards": boards}}, ensure_ascii=False), 801))

    def _fake_synth(text, **kw):
        out = tmp_path / "n.mp3"
        out.write_bytes(b"mp3")
        _fake_synth.text = text
        return out

    monkeypatch.setattr(vc.tts_client, "synthesize", _fake_synth)
    p = vc.synth_shot_narration(801, 1)
    assert p.exists()
    assert _fake_synth.text == "这枚玉镯温润又油光"
    meta = _db.jload(_db.q1("SELECT metadata FROM dramas WHERE id=?", (801,))["metadata"],
                     {})["clone"]
    b = meta["storyboards"][0]
    assert b.get("narration_audio_url"), "旁白音频未落库"
    assert b.get("narration_voice")


def test_synth_shot_narration_falls_back_to_line():
    """脚本没写旁白时,退回 line 里的「推测口播」引号内容。"""
    import json
    import tempfile
    from pathlib import Path as _P
    tmp = _P(tempfile.mkdtemp())
    from app.core import db as _db
    _db.config.DB_PATH = tmp / "n.sqlite3"
    if getattr(_db._local, "conn", None) is not None:
        _db._local.conn.close()
    _db._local.conn = None
    _db.init_db()
    ts = _db.now()
    _db.ex("INSERT INTO dramas(id,title,work_type,style,status,created_at,updated_at)"
           " VALUES(?,?,?,?,?,?,?)", (899, "T", "video_clone", "", "pending", ts, ts))
    boards = [{"number": 1, "start": 0, "end": 4,
               "line": '无清晰可辨口播;推测口播: "看这枚玉镯,圆润又油光。"'}]
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"storyboards": boards}}, ensure_ascii=False), 899))

    def _fake_synth(text, **kw):
        out = tmp / "n.mp3"
        out.write_bytes(b"mp3")
        _fake_synth.text = text
        return out

    vc.tts_client.synthesize = _fake_synth
    try:
        vc.synth_shot_narration(899, 1)
    finally:
        vc.tts_client.synthesize = getattr(vc.tts_client, "synthesize")
    assert "圆润又油光" in _fake_synth.text


def test_clone_script_dialog_has_four_sections_with_actions(tmp_path, monkeypatch,
                                                             qapp_stub):
    """「镜头脚本」弹窗要与小说线检查器同款:四段标题 + 视频提示词头的
    「AI 生成」+ 旁白头的「🔊 合成配音」。"""
    import json
    from PySide6.QtWidgets import QDialog, QPushButton, QTextEdit
    from app.ui.main_window import ClonePage
    _db = _tmp_db(tmp_path, monkeypatch)
    boards = [{"number": 1, "start": 0, "end": 4, "shot": "中景",
               "description": "【镜头1】固定中景",
               "atmosphere": "冷调",
               "video_prompt": "出场人物：@出镜人物。场景：@主场景",
               "narration": "这枚玉镯温润又油光"}]
    _db.ex("UPDATE dramas SET metadata=? WHERE id=?",
           (json.dumps({"clone": {"storyboards": boards}}, ensure_ascii=False), 801))
    page = ClonePage()
    page.load(801)
    grabbed = {}
    orig = QDialog.exec

    def _exec(self_):
        self_.resize(820, 760)
        self_.show()
        qapp_stub.processEvents()
        grabbed["buttons"] = [b.text() for b in self_.findChildren(QPushButton)]
        grabbed["edits"] = len(self_.findChildren(QTextEdit))
        return QDialog.Rejected

    QDialog.exec = _exec
    try:
        page._shot_script(1)
    finally:
        QDialog.exec = orig
    assert grabbed["edits"] == 4, f"弹窗应有 4 段文本框,实得 {grabbed['edits']}"
    assert any("AI" in t for t in grabbed["buttons"]), "视频提示词段缺「AI 生成」"
    assert any("配音" in t for t in grabbed["buttons"]), "旁白段缺「合成配音」"
