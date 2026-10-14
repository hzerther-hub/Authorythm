# -*- coding: utf-8 -*-
"""PhotoCraft CLI 桥接:把自然语言聊天的修图指令落到本地可执行文件的 `run` 命令。

设计要点:
- `PhotocraftCLI` 负责定位 exe、单步与多步执行。出错绝不冒到 PySide6 线程。
- `WhitelistMatcher` 把中文短句直接命中常用命令(亮度、翻转、去色…),快路径。
- `IntentParser` 调文本 LLM,生成 {steps:[{cmd, params, reason}]} JSON,验证再执行。
- LLM 没配/没命中 → 自动退回白名单,UI 始终能修图。
- 详细 CLI 行为参考 README:"agent-ready" + "500+ 命令"。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core import config, db


# ── 可执行文件定位 ──

def resolve_install_dir() -> Path | None:
    """按下列顺序定位 PhotoCraft 安装目录:
    1. db.get_setting("photocraft_install_dir")
    2. config.DEFAULT_PHOTOCRAFT_DIR (E:\\photocraft\\photocraft-0.7.0-windows-x64-portable)
    3. 既存在 photocraft-cli.exe 又存在 photocraft.exe 即可算
    """
    custom = db.get_setting("photocraft_install_dir", "").strip()
    for raw in (custom, config.DEFAULT_PHOTOCRAFT_DIR):
        if not raw:
            continue
        p = Path(raw)
        if p.is_dir() and (p / "photocraft-cli.exe").exists() and (p / "photocraft.exe").exists():
            return p
    return None


def resolve_cli_path() -> str | None:
    """优先按用户填的 CLI 路径;否则从 install_dir 拼。"""
    custom = db.get_setting("photocraft_cli_path", "").strip()
    if custom and Path(custom).is_file():
        return custom
    d = resolve_install_dir()
    if d:
        cand = d / ("photocraft-cli.exe" if os.name == "nt" else "photocraft-cli")
        if cand.exists():
            return str(cand)
    return None


def resolve_app_path() -> str | None:
    """桌面 GUI(photocraft.exe)路径,跟 install_dir 同根。"""
    d = resolve_install_dir()
    if d:
        cand = d / ("photocraft.exe" if os.name == "nt" else "photocraft")
        if cand.exists():
            return str(cand)
    return None


# ── Step 数据结构与 CLI 包装 ──

@dataclass
class Step:
    cmd: str
    params: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict:
        d = {"cmd": self.cmd}
        if self.params:
            d["params"] = self.params
        if self.reason:
            d["reason"] = self.reason
        return d


class PhotocraftError(RuntimeError):
    """CLI 调用出错(含 stderr 摘要)。"""


class PhotocraftCLI:
    """photocraft-cli.exe 包装。"""

    def __init__(self, cli_path: str | None = None, timeout: int = 120):
        self.cli_path = cli_path or resolve_cli_path()
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.cli_path) and Path(self.cli_path).is_file()

    def version(self) -> str:
        """调一次 `--version`;失败返回空串。"""
        if not self.available:
            return ""
        try:
            r = subprocess.run(
                [self.cli_path, "--version"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace")
            return (r.stdout or "").strip()
        except Exception:  # noqa: BLE001
            return ""

    # ── 命令清单(缓存 5 分钟) ──

    _cmds_cache: dict[str, Any] = {}
    _cmds_cache_ts: float = 0.0

    def list_commands(self, refresh: bool = False) -> list[dict]:
        """返回全部命令 [{id,label,menu,params,shortcut},...];缓存 5 分钟。"""
        if not refresh and self._cmds_cache and (time.time() - self._cmds_cache_ts) < 300:
            return self._cmds_cache  # type: ignore[return-value]
        if not self.available:
            return []
        try:
            r = subprocess.run(
                [self.cli_path, "commands", "--json"],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            raise PhotocraftError(f"无法列举命令:{exc}") from exc
        if r.returncode != 0:
            raise PhotocraftError(f"commands --json 退出码 {r.returncode}: {(r.stderr or '')[:300]}")
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as exc:
            raise PhotocraftError(f"commands --json 返回非 JSON:{exc}") from exc
        if not isinstance(data, list):
            raise PhotocraftError("commands --json 顶层不是列表")
        self.__class__._cmds_cache = data
        self.__class__._cmds_cache_ts = time.time()
        return data

    def _cmd_ids(self) -> set[str]:
        return {c.get("id") for c in self.list_commands() if c.get("id")}

    # ── 执行 ──

    def run_command(self, in_file: str, out_file: str, cmd_id: str,
                    params: dict | None = None) -> dict:
        """跑单条命令;返回最后一条 JSON 行解析出的 dict(命令结果)。"""
        return self.apply(in_file, [Step(cmd=cmd_id, params=params or {})], out_file)

    def apply(self, in_file: str, steps: list[Step], out_file: str) -> dict:
        """顺序跑多条命令(同进程同一文档上下文);返回最后一条命令结果。

        多步天然依赖同一文档 —— `photocraft-cli run` 内部用一个 Session 串行执行,
        所以多步不需要手动中转。
    """
        if not self.available:
            raise PhotocraftError("PhotoCraft CLI 未配置")
        if not steps:
            raise PhotocraftError("没有可执行的 steps")

        # 校验命令都在白名单里(白名单 = 全部已知命令)
        valid_ids = self._cmd_ids()
        bad = [s.cmd for s in steps if s.cmd not in valid_ids]
        if bad:
            raise PhotocraftError(f"未知命令: {', '.join(bad[:5])}")

        cmd = [self.cli_path, "run", str(Path(in_file).resolve())]
        for s in steps:
            cmd.extend(["--cmd", s.cmd])
            if s.params:
                cmd.extend(["--params", json.dumps(s.params, ensure_ascii=False)])
        cmd.extend(["--out", str(Path(out_file).resolve())])

        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=self.timeout,
                encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired as exc:
            raise PhotocraftError(f"CLI 调用超时,失败:{exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise PhotocraftError(f"CLI 调用失败:{exc}") from exc
        if r.returncode != 0:
            stderr = (r.stderr or "").strip()[:600]
            raise PhotocraftError(f"CLI 退出码 {r.returncode}:{stderr or '(无 stderr)'}")
        # stdout 是 N 行 JSON,每行一个命令结果;失败也可能是 stdout 路径里贴错误信息
        last: dict = {}
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                last = obj
        if not Path(out_file).exists():
            stderr = (r.stderr or "").strip()[:300]
            raise PhotocraftError(f"CLI 未生成输出文件:{stderr or '(空 stderr)'}")
        return last


# ── 白名单(快速零延迟匹配) ──

# 写法:pattern(正则,放支持中文标点)→ Step(template,params)。
# 数字解析用 ?:捕获组。匹配顺序敏感:放在前面的会先匹配。
# 不在本表的项返回 None,让 IntentParser(LLM)接手。
# 注意:这里只放「用户大概率直接打的」常见指令;LLM 路径覆盖其它 400+ 命令。
_NUMBER = r"-?\d+(?:\.\d+)?"


@dataclass
class _WhitelistRule:
    pattern: re.Pattern
    build: Any                       # (m: re.Match, lower: bool) -> Step | list[Step] | None


def _build(p: dict) -> Step:
    return Step(**p)


_WL_RULES: list[_WhitelistRule] = [
    # ── 色彩调整 ──
    _WhitelistRule(re.compile(r"去色|去彩|改成黑白|变黑白|黑白化|grayscale|desaturate"),
                     lambda m, v: _build({"cmd": "image.adjustments.desaturate",
                                          "reason": "去色"})),
    _WhitelistRule(re.compile(r"反色|反相|负片|底片|invert"),
                     lambda m, v: _build({"cmd": "image.adjustments.invert",
                                          "reason": "反相"})),
    _WhitelistRule(re.compile(rf"亮度\s*[+加]\s*({_NUMBER})"),
                     lambda m, v: _build({"cmd": "image.adjustments.brightnessContrast",
                                          "params": {"brightness": int(float(m.group(1)))},
                                          "reason": f"亮度 +{m.group(1)}"})),
    _WhitelistRule(re.compile(rf"亮度\s*[-减]\s*({_NUMBER})"),
                     lambda m, v: _build({"cmd": "image.adjustments.brightnessContrast",
                                          "params": {"brightness": -int(float(m.group(1)))},
                                          "reason": f"亮度 -{m.group(1)}"})),
    _WhitelistRule(re.compile(rf"对比\s*[+加]\s*({_NUMBER})"),
                     lambda m, v: _build({"cmd": "image.adjustments.brightnessContrast",
                                          "params": {"contrast": int(float(m.group(1)))},
                                          "reason": f"对比 +{m.group(1)}"})),
    _WhitelistRule(re.compile(rf"对比\s*[-减]\s*({_NUMBER})"),
                     lambda m, v: _build({"cmd": "image.adjustments.brightnessContrast",
                                          "params": {"contrast": -int(float(m.group(1)))},
                                          "reason": f"对比 -{m.group(1)}"})),
    _WhitelistRule(re.compile(rf"饱和度?\s*[+加]\s*({_NUMBER})"),
                     lambda m, v: _build({"cmd": "image.adjustments.hueSaturation",
                                          "params": {"saturation": int(float(m.group(1)))},
                                          "reason": f"饱和度 +{m.group(1)}"})),
    _WhitelistRule(re.compile(rf"饱和度?\s*[-减]\s*({_NUMBER})"),
                     lambda m, v: _build({"cmd": "image.adjustments.hueSaturation",
                                          "params": {"saturation": -int(float(m.group(1)))},
                                          "reason": f"饱和度 -{m.group(1)}"})),
    _WhitelistRule(re.compile(rf"鲜艳度?\s*[+加]\s*({_NUMBER})"),
                     lambda m, v: _build({"cmd": "image.adjustments.vibrance",
                                          "params": {"vibrance": int(float(m.group(1)))},
                                          "reason": f"鲜艳度 +{m.group(1)}"})),
    _WhitelistRule(re.compile(r"鲜艳度?\s*[-减]|降低鲜艳"),
                     lambda m, v: _build({"cmd": "image.adjustments.vibrance",
                                          "params": {"vibrance": -30},
                                          "reason": "鲜艳度 -30"})),
    _WhitelistRule(re.compile(rf"曝光\s*[+加]\s*({_NUMBER})"),
                     lambda m, v: _build({"cmd": "image.adjustments.exposure",
                                          "params": {"exposure": float(m.group(1))},
                                          "reason": f"曝光 +{m.group(1)}"})),
    # ── 旋转/翻转 ──
    _WhitelistRule(re.compile(r"顺时针(旋转)?\s*90|右转\s*90|转90?顺时针|90\s*cw"),
                     lambda m, v: _build({"cmd": "image.imageRotation.90cw",
                                          "reason": "顺时针 90°"})),
    _WhitelistRule(re.compile(r"逆时针(旋转)?\s*90|左转\s*90|转90?逆时针|90\s*ccw"),
                     lambda m, v: _build({"cmd": "image.imageRotation.90ccw",
                                          "reason": "逆时针 90°"})),
    _WhitelistRule(re.compile(r"翻转\s*180|转180|倒过来"),
                     lambda m, v: _build({"cmd": "image.imageRotation.180",
                                          "reason": "180°"})),
    _WhitelistRule(re.compile(r"水平翻转|水平镜像|左右翻转|左右对调|镜像"),
                     lambda m, v: _build({"cmd": "image.imageRotation.flipCanvasHorizontal",
                                          "reason": "水平翻转"})),
    _WhitelistRule(re.compile(r"垂直翻转|上下翻转|上下对调"),
                     lambda m, v: _build({"cmd": "image.imageRotation.flipCanvasVertical",
                                          "reason": "垂直翻转"})),
    # ── 模糊/锐化 ──
    _WhitelistRule(re.compile(rf"高斯模糊\s*(半径)?\s*({_NUMBER})|模糊\s*({_NUMBER})|模糊一下"),
                     lambda m, v: _build({"cmd": "filter.blur.gaussianBlur",
                                          "params": {"radius": float(m.group(2) or m.group(3) or 3)},
                                          "reason": f"高斯模糊 {m.group(2) or m.group(3) or 3}"})),
    _WhitelistRule(re.compile(r"轻微模糊|轻度模糊|柔焦一下"),
                     lambda m, v: _build({"cmd": "filter.blur.gaussianBlur",
                                          "params": {"radius": 2.0},
                                          "reason": "轻微模糊"})),
    _WhitelistRule(re.compile(r"运动模糊"),
                     lambda m, v: _build({"cmd": "filter.blur.motionBlur",
                                          "params": {"angle": 0, "distance": 10},
                                          "reason": "运动模糊 10px"})),
    _WhitelistRule(re.compile(r"锐化|清晰化|清晰一些"),
                     lambda m, v: _build({"cmd": "filter.sharpen.sharpen",
                                          "reason": "锐化"})),
    _WhitelistRule(re.compile(r"强力锐化|更锐利|强锐化"),
                     lambda m, v: _build({"cmd": "filter.sharpen.sharpenMore",
                                          "reason": "强力锐化"})),
]


class WhitelistMatcher:
    """白名单匹配 —— 不命中返回 None。"""

    def match(self, user_text: str) -> list[Step] | None:
        text = (user_text or "").strip()
        if not text:
            return None
        lower = text.lower()
        for rule in _WL_RULES:
            m = rule.pattern.search(lower)
            if not m:
                continue
            try:
                r = rule.build(m, lower)
            except Exception:  # noqa: BLE001
                return None
            if r is None:
                continue
            return r if isinstance(r, list) else [r]
        return None


# ── LLM 意图解析 ──

# 让 LLM 只用这一份精简命令清单 —— 500+ 命令全部塞进 prompt 它也记不住。
# 想要更广的覆盖就把 30 条常用列出来 + 提醒「不在列表的也允许尝试,只要存在于 photocraft-cli」。
_LLM_SYSTEM_TEMPLATE = """你是「PhotoCraft 聊天修图」的中文意图解析器。

【PhotoCraft 简介】
开源 Rust 写的 Photoshop 替代品,500+ 命令通过 `photocraft-cli run` 调用。
本次任务:把一句中文修图指令翻译成 JSON 步骤数组。

【当前素材】
用户已上传一张图(随消息附带)。**请仔细看图,理解内容(人物长相、场景、
物件、构图等)再翻译指令**。例:用户说「把人脸变笑」,你得先从图里识别
出哪张脸;「把椅子换成沙发」,要先看清图中椅子的位置和样式。

【支持的常用命令(参数以 JSON 表示;未知字段不传)】
{commands}

【输出格式(严格 JSON,不要 Markdown 包裹)】
{{
  "steps": [
    {{"cmd": "<命令 id>", "params": {{ ... }}, "reason": "给用户看的简短说明(中文)"}}
  ],
  "note": "可选:对用户的额外说明"
}}

【重要规则】
- 仅输出一句合法的 JSON。
- `cmd` 必须是上面命令清单里的 id,或 photocraft-cli 命令注册表里的合法 id。
- 不要解释、不要 Markdown 代码块、不要多余文本。
- 用户要的是单步就一个 step,多步就多个(从前向后顺序执行,后续命令作用在前一步结果上)。
- 数字参数要符合命令 schema 的范围。
- 看不懂的指令 → steps 为空数组,note 写「未能解析」。
- 若指令提到图中具体区域,识别后再写坐标;说不清的就在 note 提示用户。
"""


def _llm_command_catalog(cli: PhotocraftCLI) -> str:
    """精选 30 条常用命令 + 参数,凑成 LLM 系统提示词片段。"""
    # 内置精选清单:在 LLM 不联网 / 命令注册表还没加载完时兜底
    curated = [
        {"id": "image.adjustments.brightnessContrast", "label": "亮度/对比",
         "params": '{"brightness":-150..150,"contrast":-50..100}'},
        {"id": "image.adjustments.exposure", "label": "曝光",
         "params": '{"exposure":-20..20,"offset":-0.5..0.5,"gamma":0.01..9.99}'},
        {"id": "image.adjustments.vibrance", "label": "鲜艳度",
         "params": '{"vibrance":-100..100,"saturation":-100..100}'},
        {"id": "image.adjustments.hueSaturation", "label": "色相/饱和度/明度",
         "params": '{"hue":-180..180,"saturation":-100..100,"lightness":-100..100}'},
        {"id": "image.adjustments.levels", "label": "色阶",
         "params": '{"inBlack":0..253,"gamma":0.01..9.99,"inWhite":2..255}'},
        {"id": "image.adjustments.curves", "label": "曲线",
         "params": '{"points":[[in,out]...2..19个点]}'},
        {"id": "image.adjustments.invert", "label": "反相",
         "params": '{}'},
        {"id": "image.adjustments.desaturate", "label": "去色",
         "params": '{}'},
        {"id": "image.adjustments.threshold", "label": "阈值",
         "params": '{"level":0..255}'},
        {"id": "image.adjustments.posterize", "label": "色调分离",
         "params": '{"levels":2..255}'},
        {"id": "image.adjustments.colorBalance", "label": "色彩平衡",
         "params": '{"cyanRed":-100..100,"magentaGreen":-100..100,"yellowBlue":-100..100}'},
        {"id": "image.adjustments.photoFilter", "label": "照片滤镜",
         "params": '{"density":20,"color":122}'},
        {"id": "image.adjustments.blackWhite", "label": "黑白(精细)",
         "params": '{"reds":0..400,"yellows":0..400,"greens":0..400,"cyans":0..400,"blues":0..400,"magentas":0..400}'},
        {"id": "image.imageRotation.90cw", "label": "顺时针 90°",
         "params": '{}'},
        {"id": "image.imageRotation.90ccw", "label": "逆时针 90°",
         "params": '{}'},
        {"id": "image.imageRotation.180", "label": "180°",
         "params": '{}'},
        {"id": "image.imageRotation.flipCanvasHorizontal", "label": "水平翻转",
         "params": '{}'},
        {"id": "image.imageRotation.flipCanvasVertical", "label": "垂直翻转",
         "params": '{}'},
        {"id": "image.trim", "label": "修剪透明边",
         "params": '{"basedOn":"transparent|topLeft|bottomRight"}'},
        {"id": "image.canvasSize", "label": "画布大小",
         "params": '{"width":px,"height":px,"anchor":"center"}'},
        {"id": "image.imageSize", "label": "图像大小",
         "params": '{"width":px,"height":px,"resample":"bicubic"}'},
        {"id": "filter.blur.gaussianBlur", "label": "高斯模糊",
         "params": '{"radius":0.1..1000}'},
        {"id": "filter.blur.motionBlur", "label": "运动模糊",
         "params": '{"angle":-360..360,"distance":1..2000}'},
        {"id": "filter.blur.boxBlur", "label": "方框模糊",
         "params": '{"radius":1..100}'},
        {"id": "filter.sharpen.sharpen", "label": "锐化",
         "params": '{}'},
        {"id": "filter.sharpen.sharpenMore", "label": "强力锐化",
         "params": '{}'},
        {"id": "filter.sharpen.unsharpMask", "label": "USM 锐化",
         "params": '{"amount":1..500,"radius":0.1..1000,"threshold":0..255}'},
        {"id": "filter.noise.addNoise", "label": "添加噪点",
         "params": '{"amount":0.1..400,"distribution":"uniform|gaussian","monochromatic":bool}'},
        {"id": "filter.noise.median", "label": "中间值(去噪)",
         "params": '{"radius":1..100}'},
        {"id": "filter.distort.twirl", "label": "旋转扭曲",
         "params": '{"angle":-360..360,"radius":1..9999}'},
        {"id": "filter.render.clouds", "label": "云彩滤镜(替换图层)",
         "params": '{}'},
    ]
    # 如果 CLI 已经成功列举过命令,合并:把 CLI 实际清单里没收录的命令注册名也透露给 LLM
    extra_ids: set[str] = set()
    try:
        for c in cli.list_commands():
            cid = c.get("id")
            if cid and not any(x["id"] == cid for x in curated):
                extra_ids.add(cid)
    except Exception:  # noqa: BLE001
        pass

    lines: list[str] = []
    for c in curated:
        lines.append(f"- `{c['id']}` ({c['label']}): {c['params']}")
    if extra_ids:
        # 折叠成一行,只许 LLM 当参考;主清单用上面的精选
        sample = sorted(extra_ids)
        if len(sample) > 80:
            sample = sample[:80]
        lines.append("")
        lines.append("【其它 photocraft 已知命令(必要时可用,参数请严格按 schema)】")
        lines.append("、".join(f"`{x}`" for x in sample))
    return "\n".join(lines)


class IntentParser:
    """文本 LLM 翻译中文 → 命令步骤。"""

    def __init__(self, cli: PhotocraftCLI | None = None):
        self.cli = cli or PhotocraftCLI()
        # 缓存:同一份系统提示词不必每次重生成
        self._system_prompt: str | None = None

    def _get_system(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = _LLM_SYSTEM_TEMPLATE.format(
                commands=_llm_command_catalog(self.cli))
        return self._system_prompt

    def parse(self, user_text: str, image_url: str | None = None,
              config_id: int | None = None) -> tuple[list[Step], str, str]:
        """返回 (steps, note, error)。
        - steps: 解析成功的 Step 列表(可能为空)
        - note: 给用户看的附加说明
        - error: 错误文案(""表示没错误)
        """
        from . import text_client
        system = self._get_system()
        # 提示里强调要 JSON,顺便加点引导避免空 steps 时 LLM 把它擅自改成整段解释
        user_prompt = (
            f"用户指令:{user_text}\n\n"
            "严格输出 JSON。步骤为空时,steps 为 [] 并在 note 写清原因。"
        )
        # 本地路径 → 压缩 data URL,LLM 才看得到图(否则 api 只看到路径字符串)
        # 已经传 http(s) / data: 的不动
        if image_url and not image_url.startswith(("http://", "https://", "data:")):
            from .image_client import _ref_data_url
            converted = _ref_data_url(image_url)
            if converted:
                image_url = converted
        try:
            image_urls = [image_url] if image_url else None
            raw = text_client.chat(
                user_prompt, system=system, config_id=config_id,
                temperature=0.2, max_tokens=2048, json_mode=True,
                timeout=60, image_urls=image_urls)
        except text_client.AIError as exc:
            return [], "", f"LLM 调用失败:{exc}"
        except Exception as exc:  # noqa: BLE001
            return [], "", f"LLM 异常:{exc}"

        raw = (raw or "").strip()
        # LLM 偶尔会裹一层 Markdown ```json```,扒掉再启
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, count=1)
            raw = re.sub(r"\s*```$", "", raw, count=1)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return [], "", f"LLM 输出不是 JSON({exc}):{raw[:160]}"
        if not isinstance(data, dict):
            return [], "", f"LLM JSON 顶层不是 dict:{raw[:160]}"

        steps_raw = data.get("steps") or []
        note = (data.get("note") or "").strip()
        if not isinstance(steps_raw, list):
            return [], note or "", "LLM steps 不是数组"

        # 校验:cmd 必须存在于 CLI 注册表;params 字段必须为 dict
        try:
            valid_ids = self.cli._cmd_ids()
        except PhotocraftError:
            valid_ids = set()
        steps: list[Step] = []
        invalid: list[str] = []
        for s in steps_raw:
            if not isinstance(s, dict):
                continue
            cmd = (s.get("cmd") or "").strip()
            if not cmd:
                continue
            params = s.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            reason = (s.get("reason") or "").strip()
            if valid_ids and cmd not in valid_ids:
                invalid.append(cmd)
                continue
            steps.append(Step(cmd=cmd, params=params, reason=reason))
        if invalid and not steps:
            return [], note, f"未知命令: {', '.join(invalid[:5])}"
        return steps, note, ""


# ── 顶层入口 ──

class ChatEditEngine:
    """白名单 + LLM 双引擎。"""

    def __init__(self):
        self.cli = PhotocraftCLI()
        self.whitelist = WhitelistMatcher()
        self.parser = IntentParser(self.cli)

    @property
    def ready(self) -> bool:
        return self.cli.available

    def status_text(self) -> tuple[bool, str]:
        """返回 (可用, 文案)。"""
        if not self.cli.available:
            return False, "PhotoCraft CLI 未配置"
        v = self.cli.version()
        return True, f"PhotoCraft CLI 已就绪 · {v or 'v?'}"

    def interpret(self, user_text: str, image_url: str | None = None,
                 mode: str = "smart", llm_config_id: int | None = None
                 ) -> tuple[list[Step], str, str]:
        """返回 (steps, engine_label, note)。
        mode: smart / whitelist / llm
        engine_label: "whitelist" 或 "llm"
        """
        # 1. 始终先尝试白名单(快、零成本)
        wl = self.whitelist.match(user_text)
        if wl:
            return wl, "whitelist", ""

        # 2. 白名单未命中,按模式决定是否走 LLM
        if mode == "whitelist":
            return [], "whitelist", ""

        # 3. 走 LLM
        steps, note, lerr = self.parser.parse(
            user_text, image_url=image_url, config_id=llm_config_id)
        if lerr:
            return [], "llm", lerr
        return steps, "llm", note

    def apply(self, in_file: str, steps: list[Step], out_file: str) -> dict:
        return self.cli.apply(in_file, steps, out_file)