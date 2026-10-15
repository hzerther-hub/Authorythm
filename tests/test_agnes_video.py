# -*- coding: utf-8 -*-
"""Agnes 视频生成的参数契约回归测试。

对着官方文档(https://agnes-ai.com/zh-Hans/docs/agnes-video-25 与
agnes-video-25-flash)锁住几条最容易悄悄坏掉的规则:

1. **端点前缀不对称**:创建走 {base}/v1/videos,轮询走域名根的 /agnesapi
   —— base_url 带不带 /v1 都要拼对,这是最典型的字符串 bug。
2. **档位钳制**:flash 只吃 720P,项目里的 480p/720p/1080p/1K/2K 要映射到
   官方档位,非法值不能直接发出去。
3. **画幅**:adaptive 不是官方值(传 auto 会 400),必须落到具体比例;
   1K 档固定方形,非方形画幅在该档位一定不生效,必须如实回报。
4. **时长**:UI 给 2–30s,Agnes 只吃 4–12s,越界要能说清原值。
5. **轮询**:以 status+url 为准(官方明说 internal_status 不可信),
   completed 无 URL 按失败处理。
6. **进度**:parse_poll_response 返回 5 元组,progress 缺失/越界都不能炸。

这些函数此前**零覆盖**,改一个字符都不会有测试变红。
"""
from __future__ import annotations

import pytest

from app.ai.agnes_video import (VALID_RATIOS, adapt_seconds, build_generate_body,
                                create_endpoint, effective_size, is_flash,
                                normalize_aspect_ratio, normalize_seconds,
                                parse_create_response, parse_poll_response,
                                poll_endpoint, ratio_from_image_bytes)
from app.ai.prompt_guards import (CAMERA_MARKER, CONSISTENCY_MARKER,
                                  VIDEO_CAMERA_GUARD, VIDEO_CONSISTENCY_GUARD,
                                  apply_video_guards)
from app.ai.text_client import AIError

FULL = "agnes-video-2.5"
FLASH = "agnes-video-2.5-flash"


def _cfg(model=FULL):
    return {"provider": "agnes", "model": model, "api_key": "k"}


# ── 端点:创建带 /v1,轮询不带 ──────────────────────────────────────────

def test_create_endpoint_appends_v1_when_missing():
    assert create_endpoint("https://apihub.agnes-ai.com") \
        == "https://apihub.agnes-ai.com/v1/videos"


def test_create_endpoint_does_not_double_v1():
    """base_url 已经带 /v1 时不能拼成 /v1/v1/videos(registry.normalize_base_url 会补)。"""
    assert create_endpoint("https://apihub.agnes-ai.com/v1") \
        == "https://apihub.agnes-ai.com/v1/videos"
    assert create_endpoint("https://apihub.agnes-ai.com/v1/") \
        == "https://apihub.agnes-ai.com/v1/videos"


def test_poll_endpoint_strips_v1_prefix():
    """轮询端点在域名根 /agnesapi,不在 /v1 下 —— 与创建端点前缀不对称。"""
    url = poll_endpoint("https://apihub.agnes-ai.com/v1", "key", "video_1", FULL)
    assert url.startswith("https://apihub.agnes-ai.com/agnesapi?")
    assert "video_id=video_1" in url
    assert "model_name=agnes-video-2.5" in url


def test_poll_endpoint_omits_model_when_unknown():
    """model 缺失时只带 video_id(官方:纯 video_id 查询仅适用于 text 模式)。"""
    url = poll_endpoint("https://apihub.agnes-ai.com", "key", "video_1", None)
    assert "model_name" not in url


# ── 档位钳制 ───────────────────────────────────────────────────────────

def test_is_flash_only_matches_flash():
    assert is_flash(FLASH)
    assert not is_flash(FULL)


def test_flash_is_clamped_to_720p():
    """Flash 传其它档位直接 400(size must be 720P),必须钳死。"""
    assert effective_size(FLASH, "1080P") == "720P"
    assert effective_size(FLASH, "2K") == "720P"
    assert effective_size(FLASH, "720p") == "720P"


def test_full_keeps_valid_tiers():
    assert effective_size(FULL, "720p") == "720P"
    assert effective_size(FULL, "1080p") == "1080P"
    assert effective_size(FULL, "1K") == "1K"
    assert effective_size(FULL, "2k") == "2K"


def test_480p_promotes_to_720p():
    """480p 无对应档位,就近升 720P(降档白花钱且没有更便宜的档位)。"""
    assert effective_size(FULL, "480p") == "720P"


def test_unknown_resolution_falls_back_without_crashing():
    assert effective_size(FULL, "") == "720P"
    assert effective_size(FULL, None) == "720P"
    assert effective_size(FULL, "banana") == "720P"


# ── 时长 ───────────────────────────────────────────────────────────────

def test_normalize_seconds_clamps_to_4_12():
    assert normalize_seconds(2) == "4"
    assert normalize_seconds(25) == "12"
    assert normalize_seconds(8) == "8"


def test_adapt_seconds_reports_original_intent_when_clamped():
    """被钳制时必须回报用户原值,否则「设了 25s 只拿到 12s」无人知晓。"""
    assert adapt_seconds(25) == ("12", 25)
    assert adapt_seconds(2) == ("4", 2)
    assert adapt_seconds(8) == ("8", None)


def test_adapt_seconds_defaults_on_garbage():
    assert adapt_seconds(None) == ("5", None)
    assert adapt_seconds(0) == ("5", None)
    assert adapt_seconds("abc") == ("5", None)


# ── 画幅 ───────────────────────────────────────────────────────────────

def test_valid_ratio_passes_through():
    for r in VALID_RATIOS:
        assert normalize_aspect_ratio(r, "1080P")[0] == r


def test_adaptive_never_reaches_upstream_as_auto():
    """官方明说 aspect_ratio="auto" 会 400 —— adaptive 必须落成具体比例。"""
    got, note = normalize_aspect_ratio("adaptive", "720P")
    assert got in VALID_RATIOS
    assert note, "自适应画幅被改写时应给出说明"


def test_adaptive_uses_first_frame_ratio_when_available():
    """首帧图就是这一镜的构图,它的比例比回落 16:9 准确(竖屏项目出横屏片的根因)。"""
    got, _ = normalize_aspect_ratio("adaptive", "1080P",
                                    first_frame="data:image/jpeg;base64,xx",
                                    data_url_reader=lambda _u: "9:16")
    assert got == "9:16"


def test_1k_tier_is_square_and_says_so():
    """官方:1K 固定输出 1024x1024,与 aspect_ratio 无关 —— 必须如实告知。"""
    got, note = normalize_aspect_ratio("9:16", "1K")
    assert got == "9:16"
    assert note and "1K" in note


def test_1k_square_ratio_has_no_warning():
    assert normalize_aspect_ratio("1:1", "1K")[1] is None


def test_unknown_ratio_falls_back_and_reports():
    got, note = normalize_aspect_ratio("banana", "720P")
    assert got == "16:9"
    assert note and "banana" in note


def test_empty_ratio_uses_official_default():
    assert normalize_aspect_ratio(None, "720P")[0] == "16:9"
    assert normalize_aspect_ratio("", "720P")[0] == "16:9"


def test_ratio_from_image_bytes_maps_to_whitelist():
    """只认 6 个官方值:宁可 None 走兜底,也不能下发上游会 400 的比例。"""
    import io

    from PIL import Image

    def _png(w, h):
        buf = io.BytesIO()
        Image.new("RGB", (w, h)).save(buf, "PNG")
        return buf.getvalue()

    assert ratio_from_image_bytes(_png(1080, 1920)) == "9:16"
    assert ratio_from_image_bytes(_png(1920, 1080)) == "16:9"
    assert ratio_from_image_bytes(_png(1000, 1000)) == "1:1"


def test_ratio_from_image_bytes_handles_garbage():
    assert ratio_from_image_bytes(None) is None
    assert ratio_from_image_bytes(b"not an image") is None


# ── 请求体 ─────────────────────────────────────────────────────────────

def test_body_requires_agnes_video_model():
    with pytest.raises(AIError):
        build_generate_body(_cfg("agnes-image-2.5-flash"), prompt="x",
                            resolution="720p", duration=5, first_frame=None,
                            last_frame=None, ref_images=[])


def test_body_requires_prompt():
    with pytest.raises(AIError):
        build_generate_body(_cfg(), prompt="   ", resolution="720p", duration=5,
                            first_frame=None, last_frame=None, ref_images=[])


def test_body_sets_official_fields_only():
    """官方参数限制:不接受 width/height/fps/quality,也不接受像素值 size。"""
    body = build_generate_body(_cfg(), prompt="推门", resolution="1080p", duration=8,
                               first_frame=None, last_frame=None, ref_images=[],
                               aspect_ratio="9:16")
    assert body["model"] == FULL
    assert body["prompt"] == "推门"
    assert body["seconds"] == "8"
    assert body["size"] == "1080P"
    assert body["aspect_ratio"] == "9:16"
    assert body["mode"] == "text"
    assert body["n"] == 1
    for banned in ("width", "height", "fps", "quality", "num_frames"):
        assert banned not in body


def test_keyframe_mode_drops_reference_media():
    """官方规则:keyframe 禁止同时带 images/audios/videos。

    关键 —— 带首帧的镜头**本来就不该**报「参考图超限」:那些图压根没进请求体,
    计数会让整镜凭空失败。
    """
    body = build_generate_body(
        _cfg(), prompt="x", resolution="720p", duration=5,
        first_frame="https://e.com/a.png", last_frame=None,
        ref_images=[f"https://e.com/{i}.png" for i in range(20)],
        ref_audios=["https://e.com/a.mp3"] * 9)
    assert body["mode"] == "keyframe"
    assert body["first_frame"] == "https://e.com/a.png"
    assert "images" not in body
    assert "audios" not in body


def test_last_frame_only_is_keyframe():
    body = build_generate_body(_cfg(), prompt="x", resolution="720p", duration=5,
                               first_frame=None, last_frame="https://e.com/z.png",
                               ref_images=[])
    assert body["mode"] == "keyframe"
    assert body["last_frame"] == "https://e.com/z.png"
    assert "first_frame" not in body


def test_reference_mode_truncates_to_official_limits():
    """超限截断而非报错:少带几张不该让整条任务直接失败。"""
    body = build_generate_body(_cfg(), prompt="x", resolution="720p", duration=5,
                               first_frame=None, last_frame=None,
                               ref_images=[f"https://e.com/{i}.png" for i in range(30)])
    assert body["mode"] == "reference"
    assert len(body["images"]) == 8          # 2.5 最多 8 张


def test_flash_reference_limits():
    body = build_generate_body(_cfg(FLASH), prompt="x", resolution="720p", duration=5,
                               first_frame=None, last_frame=None,
                               ref_images=[f"https://e.com/{i}.png" for i in range(30)])
    assert len(body["images"]) == 5          # Flash 最多 5 张


def test_flash_rejects_reference_video():
    with pytest.raises(AIError):
        build_generate_body(_cfg(FLASH), prompt="x", resolution="720p", duration=5,
                            first_frame=None, last_frame=None, ref_images=[],
                            ref_videos=["https://e.com/v.mp4"])


def test_seed_is_integer_or_float_only():
    body = build_generate_body(_cfg(), prompt="x", resolution="720p", duration=5,
                               first_frame=None, last_frame=None, ref_images=[],
                               seed=42)
    assert body["seed"] == 42
    bad = build_generate_body(_cfg(), prompt="x", resolution="720p", duration=5,
                              first_frame=None, last_frame=None, ref_images=[],
                              seed="abc")
    assert "seed" not in bad                 # 非法值静默丢弃,不能把脏值发给上游


# ── 轮询响应 ───────────────────────────────────────────────────────────

def test_completed_returns_top_level_url():
    status, url, err, dur, pct = parse_poll_response(
        {"status": "completed", "url": "https://cdn/v.mp4", "seconds": "8"})
    assert (status, url, err, dur, pct) == ("completed", "https://cdn/v.mp4", None, 8, 100)


def test_completed_without_url_is_failure():
    """任务完成却拿不到地址不能当成功落库。"""
    status, url, err, _, _ = parse_poll_response({"status": "completed"})
    assert status == "failed"
    assert url is None
    assert err


def test_failed_carries_error_message():
    status, _, err, _, _ = parse_poll_response(
        {"status": "failed", "error": {"message": "Invalid reference media"}})
    assert status == "failed"
    assert err == "Invalid reference media"


def test_in_progress_reports_official_progress():
    """官方:以 status/progress 为准,internal_progress 即使是 pending/0 也不能信。"""
    status, url, _, _, pct = parse_poll_response(
        {"status": "in_progress", "progress": 42, "internal_progress": 0,
         "internal_status": "pending"})
    assert status == "running"
    assert url is None
    assert pct == 42


def test_progress_clamped_and_bad_values_survive():
    assert parse_poll_response({"status": "in_progress", "progress": 999})[4] == 100
    assert parse_poll_response({"status": "in_progress", "progress": -5})[4] == 0
    assert parse_poll_response({"status": "in_progress"})[4] is None
    assert parse_poll_response({"status": "in_progress", "progress": "x"})[4] is None


def test_parse_create_response_prefers_video_id():
    task = parse_create_response({"id": "task_1", "task_id": "task_1",
                                  "video_id": "video_1", "model": FULL})
    video_id, sep, model = task.partition("::")
    assert (video_id, model) == ("video_1", FULL)
    assert sep == "::"


def test_parse_create_response_requires_an_id():
    with pytest.raises(AIError):
        parse_create_response({"status": "queued"})


# ── 提示词守卫 ─────────────────────────────────────────────────────────

def test_video_guards_include_camera_and_consistency():
    """官方建议六段结构里的「镜头语言」与「一致性要求」此前完全缺失。"""
    out = apply_video_guards("女孩推门进来")
    assert CAMERA_MARKER in out
    assert CONSISTENCY_MARKER in out


def test_video_guards_are_idempotent():
    """重试复用已存 prompt 时不能把守卫追加两遍(marker 幂等是唯一的防线)。"""
    once = apply_video_guards("女孩推门进来")
    twice = apply_video_guards(once)
    assert once == twice
    assert once.count("镜头要求：") == 1
    assert once.count("一致性要求：") == 1


def test_marker_matches_guard_prefix():
    """marker 与 guard 字面量是双向硬耦合:marker 必须逐字等于 guard 开头。"""
    assert VIDEO_CAMERA_GUARD.startswith(CAMERA_MARKER + "：")
    assert VIDEO_CONSISTENCY_GUARD.startswith(CONSISTENCY_MARKER + "：")


def test_empty_prompt_gets_no_guards():
    assert apply_video_guards("") == ""
