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


# ── 人物参照图:纯文字生成 + 换脸(绕开参考图继承的重影)───────────────

def test_fullshot_prompt_has_no_reference_image():
    """底图**不能**带参考图。

    实测:拿用户原照(红橙舞台背景)当参考图生全身像 → 必定带两个半透明人影,
    且会被原样带进每张分镜成品。这是从参考图**继承**的构图惯性,负面词压不住
    (补齐短剧侧张嘴/极端表情负面词后重影反增);只传 1 张图也一样,证明不是
    多图融合。所以底图必须纯文字,长相靠换脸补。
    """
    import inspect
    src = inspect.getsource(vc.build_presenter_fullshot)
    assert "reference_images" not in src, "全身像底图不得传参考图(会继承重影)"


def test_fullshot_prompt_asks_for_shoes_and_full_frame():
    """要完整全身 + 有鞋。

    - 画幅必须竖版:16:9 横画幅装不下头顶到脚底(实测三轮都只到腿/大腿)。
    - 提示词必须**正面**描述鞋与全身:否定式("NOT cropped at knees/thighs")
      连写三轮完全无效,改成「穿…凉鞋,露出完整双脚与脚踝」后一次成功。
    """
    import inspect
    src = inspect.getsource(vc.build_presenter_fullshot)
    assert 'size="1080x1920"' in src, "全身像必须用竖版画幅"
    assert "soles" in src.lower() or "feet" in src.lower(), "未要求脚部入镜"
    assert "凉鞋" in src or "鞋" in src, "未指定鞋款"


def test_read_presenter_desc_declares_footwear_field():
    """原照常是半身照看不到鞋,提取提示词要显式要求 footwear 字段,且允许留空。

    不允许臆造 —— 拍不到就报空,生成时再补默认鞋款。
    """
    import inspect
    src = inspect.getsource(vc.read_presenter_desc)
    assert "footwear" in src, "未提取鞋履"
    assert "留空" in src, "未说明看不到时可留空"


def test_sync_assets_writes_fullshot_and_turnaround_to_separate_columns():
    """资产图分列存:全身像 → image_url(分镜用),三视图 → comic_image_url(仅核对)。

    与短剧侧 comic.comic_asset_image 同构。三视图含 4 个人物实例,当分镜参考
    会把多个实例一起画进画面。
    """
    import inspect
    src = inspect.getsource(vc.sync_assets)
    assert "comic_image_url" in src, "三视图应写 comic_image_url"
    assert "presenter_fullshot" in src


def test_pick_ref_kind_uses_single_reference_image():
    """每镜只传一张参考图。

    实测同时传 2 张(主体+场景)时,右侧必出半透明第二人;而提示词里的
    no onlookers 拗不过图像参照 —— 参考图里明确画了第二个人就会被照抄。
    场景改用文字锚锁定。
    """
    import inspect
    src = inspect.getsource(vc.generate_shot_image)
    assert "ref_pool" not in src, "不应再有多图参考池(会引入重影)"


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
