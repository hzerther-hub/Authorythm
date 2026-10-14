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
        # 推理型模型(minimax-M3 / glm 等)会先吐一整段 <think>...</think> 推理,
        # 再给 JSON。这里不剥就 json.loads 必然失败(实测 MiniMax-M3 全程在推理)。
        # 与 agents/runner.extract_json 同款处理:成对先剥,未闭合的尾巴取最后一个
        # <think> 之后的全部内容(正文在思考之后)。
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
        if "<think>" in raw:
            raw = raw.rsplit("<think>", 1)[-1]
        raw = raw.strip()
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


def _wants_text_removal(text: str) -> bool:
    """判断用户这句是不是「把图上的文字去掉/替换掉」。

    触发范围刻意保守 —— 误判的代价是多一次识图 LLM 调用(几秒 + token)。
    「字」单字太泛,只在同时提到图/画面类词时才认;「水印/字幕/标题/文案」
    本身就是专用词,直接认。

    容错:
      - 常见打字容错「去请」「去调」也算去掉
      - 「erase / clean / remove」等英文指令也接受
    """
    t = (text or "").strip()
    if not t:
        return False
    # 去掉类关键词 —— 包括常见打字容错("去请"是用户实测的打字错误)
    remove_words = ("去掉", "去除", "删除", "抹掉", "清除", "消除", "擦掉", "擦除",
                    "遮掉", "不要", "去请", "除掉", "移除", "消掉",
                    "remove", "erase", "clean", "delete")
    dedicated = ("文字", "文本", "文案", "字幕", "水印", "签名", "logo")
    broad_char = "字"
    broad_ctx = ("图", "图片", "画面", "照片", "海报", "封面", "背景", "上", "里", "中")
    low = t.lower()
    for rw in remove_words:
        if rw not in t and rw not in low:
            continue
        # 专用词直接命中
        for dw in dedicated:
            if dw in t:
                return True
        # 单字「字」要求同时有上下文词
        if broad_char in t and any(c in t for c in broad_ctx):
            return True
    return False


# ── 批量意图(分析 + N 个方案分别执行) ──

_BATCH_RE_NUM = re.compile(r"[三四五六七八九个十]?\s*个\s*(?:方案|改法|版本|想法|修改|变体|处理|做法)")
_BATCH_RE_DO = re.compile(r"(分别|逐个|依次|挨个|每个)(执行|做|出图|跑|处理|试|尝试)")
_BATCH_RE_FLOW = re.compile(r"先\s*.+?\s*(?:然后|再|接着|之后)\s*.+?(?:执行|做|出图|跑|处理)")
_BATCH_RE_N = re.compile(r"(\d+)\s*个\s*(?:方案|改法|版本|想法|修改|变体)")


def _wants_batch_analysis(text: str) -> bool:
    """检测「先分析,再 N 个方案分别执行」类批量请求。

    触发关键词:
      - 「N 个方案/改法/版本」(三/四/五.../数字 N)
      - 「分别/逐个/依次/每个 执行/做/出图」
      - 「先 X,然后/再 Y,执行」(带分析意图)
    """
    t = (text or "").strip()
    if not t:
        return False
    if _BATCH_RE_NUM.search(t):
        return True
    if _BATCH_RE_DO.search(t):
        return True
    # 「先分析...再执行」也要认(用户没明说数量就给默认 3)
    if _BATCH_RE_FLOW.search(t) and ("分析" in t or "看" in t):
        return True
    return False


def _wants_batch_n(text: str) -> int:
    """从用户句子里提取 N(默认 3)。"""
    m = _BATCH_RE_N.search(text or "")
    if m:
        try:
            return max(1, min(8, int(m.group(1))))
        except (TypeError, ValueError):
            pass
    m = _BATCH_RE_NUM.search(text or "")
    if m:
        cn = m.group(0)
        digits = {"三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        for k, v in digits.items():
            if k in cn:
                return min(8, v)
    return 3


# 批量规划的 LLM 系统提示 —— 让 LLM 看图后给 N 个**单条可执行**方案
_ANALYZE_PLAN_SYSTEM = """你是图像修改顾问。用户给一张图 + 一句修改意图。

任务:
1. 用 2-3 句中文简短分析图的构图/色调/主题(共 < 100 字)
2. 提出 N 个不同的修改方案。每个方案必须有一个**单条可执行**的 prompt。

输出严格 JSON(不要 Markdown 围栏、不要解释、不要思考过程):
{
  "analysis": "构图分析文本",
  "plans": [
    {
      "id": "A",
      "title": "方案标题(5-10 字)",
      "description": "这个方案要做什么(1-2 句中文)",
      "prompt": "具体的修改指令,必须是「聊天改图」能直接执行的单条指令"
    },
    ...
  ]
}

prompt 必须是「聊天改图」已支持的指令,例如:
- "改成黑白" / "反色" / "去色"
- "亮度+30" / "对比+10" / "饱和度+20"
- "高斯模糊 5" / "锐化"
- "顺时针旋转 90" / "水平翻转"
- "裁剪成 1:1 居中"
- "把'X'改成'Y'"
- "去掉图片上的文字"

要求:
- plans 数量 = 用户要求的 N
- 每个 plan 的 prompt 必须是单条可执行指令(不要复杂句)
- 3 个方案必须有**视觉差异**,不要同质化
- 不要泛泛而谈("增强" / "优化" 这种不可执行的不收)"""


def analyze_and_plan(image_path: str, user_intent: str, n: int = 3,
                     config_id: int | None = None,
                     timeout: int = 90) -> tuple[str, list[dict], str]:
    """LLM 看图 + 返回 N 个修改方案。

    返回 (analysis, plans, error)。
    plans = [{"id", "title", "description", "prompt"}, ...]

    实现:
      - data URL 直接传给多模态 LLM(同 locate_text_regions 路径)
      - 推理块 / Markdown 围栏 用 _strip_reasoning 统一剥掉
      - 兜底:LLM 没给方案时返回空列表(由 caller 走温和回复)
    """
    from . import text_client
    from .image_client import _ref_data_url

    p = Path(image_path)
    if not p.exists():
        return "", [], f"图片不存在:{image_path}"
    data_url = _ref_data_url(str(p))
    if not data_url:
        return "", [], "图片读取失败(无法转 data URL)"

    ask = (f"用户意图:{user_intent}\n\n"
           f"请按系统提示给出 {n} 个方案的 JSON。")

    try:
        raw = text_client.chat(
            ask, system=_ANALYZE_PLAN_SYSTEM,
            config_id=config_id, temperature=0.5, max_tokens=8000,
            json_mode=True, timeout=timeout, image_urls=[data_url])
    except text_client.AIError as exc:
        return "", [], f"LLM 调用失败:{exc}"
    except Exception as exc:  # noqa: BLE001
        return "", [], f"LLM 异常:{exc}"

    body = _strip_reasoning(raw)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return "", [], f"LLM 输出不是 JSON({exc}):{body[:160]}"
    if not isinstance(data, dict):
        return "", [], "LLM JSON 顶层不是 dict"

    analysis = (data.get("analysis") or "").strip()
    plans_raw = data.get("plans") or []
    if not isinstance(plans_raw, list):
        return analysis, [], "LLM plans 不是数组"

    letters = "ABCDEFGH"
    out: list[dict] = []
    for i, p in enumerate(plans_raw):
        if not isinstance(p, dict):
            continue
        prompt = str(p.get("prompt") or "").strip()
        if not prompt:
            continue
        out.append({
            "id": str(p.get("id") or letters[i] if i < len(letters) else str(i + 1)),
            "title": str(p.get("title") or f"方案 {letters[i]}").strip(),
            "description": str(p.get("description") or "").strip(),
            "prompt": prompt,
        })
    return analysis, out[:n], ""


# ── 文字定位(用多模态 LLM 替代 OCR)──

# 用户说「去掉图片上的文字」时,PhotoCraft CLI 只能做 edit.contentAwareFill,
# 必须先有 select.rect 选区,而 CLI 的 858 条命令里**没有 OCR / 文字检测**,
# 不知道文字在哪 → LLM 直接回 0 steps。
#
# 这里补一层:多模态 LLM(项目里本来就配了识图模型)看图,返回文字包围盒,
# 再翻译成 select.rect + edit.contentAwareFill。坐标用 0-1000 归一化,
# 避免不同分辨率下换算出错。

_LOCATE_SYSTEM = """你是图片文字检测器。找出图中所有**文字区域**并返回包围盒坐标。

**最重要**:用户消息里会告诉你这张图的实际像素尺寸(如「这张图是 800x600 像素」)。
你必须返回**该像素尺寸下的坐标**,不要返回百分比、不要自己换算、不要用 0-1000 归一化。

严格输出 JSON,不要任何解释、Markdown 围栏或思考过程:
{"regions": [{"text": "识别到的文字", "x1": 120, "y1": 80, "x2": 400, "y2": 140}]}

坐标规则:
- x1/y1 = 文字左上角像素坐标;x2/y2 = 右下角像素坐标;全部是整数
- x1 < x2,y1 < y2,且必须落在图片尺寸范围内(0 ≤ 坐标 < 宽/高)
- 框要**完整包住文字笔画**,宁可略大一点也别切到字;四周留 3-6 像素余量
- 一个文字行/词组算一个 region;同一块连续文字合并成一个
- 图中没有文字时返回 {"regions": []}

只检测文字,不要把图案、logo 图形、人物面部当成文字。"""


def _strip_reasoning(raw: str) -> str:
    """剥 <think> 推理块 + Markdown 围栏,留下纯 JSON 正文。

    推理型模型(minimax-M3 / glm 等)会先吐一整段 <think> 再给 JSON,
    不剥就 json.loads 必然失败。
    """
    raw = (raw or "").strip()
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S)
    if "<think>" in raw:
        raw = raw.rsplit("<think>", 1)[-1]
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, count=1)
        raw = re.sub(r"\s*```$", "", raw, count=1)
    return raw.strip()


def locate_text_regions(image_path: str, config_id: int | None = None,
                        timeout: int = 60) -> tuple[list[dict], str]:
    """用多模态 LLM 找出图里的文字区域。

    返回 (regions, error);regions = [{"text", "x1","y1","x2","y2"}],**像素坐标**。

    为什么把图片尺寸写进提示:让模型自己按百分比/千分比换算时算不准
    (实测 800×600 的图,文字在 y≈400 处,模型报 y=300‰ → 换算回像素只有 240,
    框完全错位)。直接告知尺寸并要求返回像素坐标后,坐标基本吻合。
    """
    from . import text_client
    from .image_client import _ref_data_url
    p = Path(image_path)
    if not p.exists():
        return [], f"图片不存在:{image_path}"
    iw = ih = 0
    try:
        from PIL import Image
        with Image.open(p) as _im:
            iw, ih = _im.size
    except Exception:  # noqa: BLE001
        pass
    data_url = _ref_data_url(str(p))
    if not data_url:
        return [], "图片读取失败(无法转成 data URL)"
    ask = (f"这张图是 {iw}×{ih} 像素。"
           f"请找出图里所有文字,返回该尺寸下的像素坐标包围盒。") if iw else \
          "请找出图里所有文字,返回像素坐标包围盒。"
    try:
        raw = text_client.chat(
            ask, system=_LOCATE_SYSTEM,
            config_id=config_id, temperature=0.1, max_tokens=8000,
            json_mode=True, timeout=timeout, image_urls=[data_url])
    except text_client.AIError as exc:
        return [], f"识图模型调用失败:{exc}"
    except Exception as exc:  # noqa: BLE001
        return [], f"识图异常:{exc}"

    body = _strip_reasoning(raw)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return [], f"识图模型输出不是 JSON:{body[:160]}"
    regions_raw = data.get("regions") if isinstance(data, dict) else None
    if not isinstance(regions_raw, list):
        return [], f"识图模型未返回 regions:{body[:160]}"

    # 万一模型又给了 0-1000 归一化值(坐标看着像千分比),按图尺寸还原
    looks_normalized = bool(regions_raw) and max(
        (int(float(r.get(k) or 0)) for r in regions_raw if isinstance(r, dict)
         for k in ("x2", "y2")), default=0) <= 1000 and iw > 1000

    out: list[dict] = []
    for r in regions_raw:
        if not isinstance(r, dict):
            continue
        try:
            x1 = int(float(r.get("x1")))
            y1 = int(float(r.get("y1")))
            x2 = int(float(r.get("x2")))
            y2 = int(float(r.get("y2")))
        except (TypeError, ValueError):
            continue
        if looks_normalized and iw:
            x1, x2 = int(x1 / 1000 * iw), int(x2 / 1000 * iw)
            y1, y2 = int(y1 / 1000 * ih), int(y2 / 1000 * ih)
        limit_w = iw or 10000
        limit_h = ih or 10000
        x1, x2 = sorted((max(0, min(limit_w, x1)), max(0, min(limit_w, x2))))
        y1, y2 = sorted((max(0, min(limit_h, y1)), max(0, min(limit_h, y2))))
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        out.append({"text": str(r.get("text") or "").strip()[:40],
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return out, ""


def regions_to_steps(regions: list[dict], image_path: str | None = None,
                     fill_cmd: str = "edit.contentAwareFill") -> list[Step]:
    """把文字包围盒翻译成 select.rect + 填充命令的步骤序列。

    两个必须对齐 CLI 的细节(查 photocraft-cli 命令表确认):
      1. `select.rect` 的参数是 **x / y / width / height**(左上角 + 宽高),
         **不是** x1/y1/x2/y2;
      2. 单位是**像素** —— locate_text_regions 已把图片尺寸写进提示让模型直接给
         像素坐标,这里不再做归一化换算。

    image_path 只用于兜底:拿到真实画布尺寸好把选区夹回图内。
    """
    iw = ih = 0
    if image_path:
        try:
            from PIL import Image
            with Image.open(image_path) as _im:
                iw, ih = _im.size
        except Exception:  # noqa: BLE001
            pass
    # 外扩系数:模型给的框仍可能略紧,contentAwareFill 只处理选区内像素,
    # 框小了字就抹不干净。宁可多盖背景(fill 本来就是拿周围像素推),不能漏字。
    GROW = 0.20   # 每边外扩 20%
    steps: list[Step] = []
    for r in regions:
        px1, py1 = int(r["x1"]), int(r["y1"])
        px2, py2 = int(r["x2"]), int(r["y2"])
        w = max(1, px2 - px1)
        h = max(1, py2 - py1)
        x = int(px1 - w * GROW)
        y = int(py1 - h * GROW)
        ex2 = int(px2 + w * GROW)
        ey2 = int(py2 + h * GROW)
        # 夹回画布
        if iw:
            x = max(0, min(iw - 2, x))
            ex2 = max(x + 2, min(iw, ex2))
        if ih:
            y = max(0, min(ih - 2, y))
            ey2 = max(y + 2, min(ih, ey2))
        steps.append(Step(
            cmd="select.rect",
            params={"x": x, "y": y, "width": max(1, ex2 - x),
                    "height": max(1, ey2 - y), "mode": "replace"},
            reason=f"框选「{r.get('text') or '文字'}」({x},{y} {ex2 - x}×{ey2 - y})"))
    if regions:
        steps.append(Step(cmd=fill_cmd, params={"sampling": "auto"},
                          reason=f"内容识别填充,抹掉 {len(regions)} 处文字"))
        steps.append(Step(cmd="select.deselect", params={}, reason="清除选区"))
    return steps


def remove_text_by_inpaint(image_path: str, regions: list[dict],
                           out_file: str | None = None) -> tuple[str, str]:
    """用项目自带的 inpaint 能力抹掉文字区域(绕开 PhotoCraft 选区限制)。

    为什么不用 PhotoCraft 的 select.rect + contentAwareFill:
    实测 photocraft-cli 的 `run` 模式下**选区状态不在命令间传递** ——
    select.rect 返回 null,后续 contentAwareFill 的 window 与选区坐标完全无关
    (选 y=430,填充 window 是 y=289),文字纹丝不动。这是 CLI 侧限制,换调用姿势无效。

    这里走 app.ai.image_client.inpaint_masked:LLM 定位 → 合成矩形 mask →
    inpaint 重建被盖住的像素。定位框由 locate_text_regions 给(像素坐标)。
    """
    import io as _io
    import uuid as _uuid
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover
        return "", "Pillow 未安装"
    from ..core import config
    from ..pipeline.inpaint import inpaint_masked

    p = Path(image_path)
    if not p.exists():
        return "", f"图片不存在:{image_path}"
    try:
        base = Image.open(p)
        base.load()
    except Exception as exc:  # noqa: BLE001
        return "", f"图片读取失败:{exc}"
    W, H = base.size

    # 透明蒙版:alpha=255 处被重绘(见 inpaint_masked 约定「alpha=擦除强度」)
    mask = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    d = ImageDraw.Draw(mask)
    for r in regions:
        x1, y1 = int(r["x1"]), int(r["y1"])
        x2, y2 = int(r["x2"]), int(r["y2"])
        w, h = max(1, x2 - x1), max(1, y2 - y1)
        # 外扩 20% + 至少 6px,盖住字形抗锯齿边缘
        gx, gy = max(0, int(w * 0.2)) + 6, max(0, int(h * 0.2)) + 6
        d.rectangle([max(0, x1 - gx), max(0, y1 - gy),
                     min(W - 1, x2 + gx), min(H - 1, y2 + gy)],
                    fill=(0, 0, 0, 255))
    buf = _io.BytesIO()
    mask.save(buf, "PNG")

    try:
        result = inpaint_masked(p.read_bytes(), buf.getvalue())
    except Exception as exc:  # noqa: BLE001
        return "", f"局部重绘失败:{exc}"
    if not result:
        return "", "局部重绘没有返回结果"
    out = Path(out_file) if out_file else (
        config.STATIC_DIR / "processed" / f"notext_{_uuid.uuid4().hex[:10]}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(result)
    return str(out), ""


# ── OpenCV 抹字(本地、零网络) ──

def _opencv_available() -> bool:
    """OpenCV(cv2) + numpy 是否可用。TextReplaceSkill 用这个判定走 cv2.inpaint
    还是退到 inpaint_masked。
    """
    try:
        import cv2  # noqa: F401
        import numpy as np  # noqa: F401
        return True
    except ImportError:
        return False


def inpaint_regions_opencv(in_path: str, regions: list[dict], out_path: str,
                           radius: int = 3) -> tuple[bool, str]:
    """用 OpenCV cv2.inpaint(TELEA 算法)抹掉指定文字区域。

    CLI 兜底:PhotoCraft 的 select.rect 选区状态不传递(实测),
    后续 contentAwareFill 完全对不上字。cv2.inpaint 直接吃 mask,
    算法速度够、抹中文小字、字幕、水印都干净。

    返回 (success, error)。
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False, "未安装 opencv-python,无法用 cv2.inpaint"

    p = Path(in_path)
    if not p.exists():
        return False, f"图片不存在:{in_path}"
    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None:
        return False, f"图片读取失败:{in_path}"
    h, w = img.shape[:2]

    mask = np.zeros((h, w), dtype=np.uint8)
    for r in regions:
        x1, y1 = int(r["x1"]), int(r["y1"])
        x2, y2 = int(r["x2"]), int(r["y2"])
        rw, rh = max(1, x2 - x1), max(1, y2 - y1)
        # 外扩 20% + 6px,盖住字形抗锯齿边缘(跟 remove_text_by_inpaint 比例一致)
        gx = max(0, int(rw * 0.2)) + 6
        gy = max(0, int(rh * 0.2)) + 6
        cv2.rectangle(mask,
                      (max(0, x1 - gx), max(0, y1 - gy)),
                      (min(w - 1, x2 + gx), min(h - 1, y2 + gy)),
                      255, thickness=-1)
    # TELEA = Fast Marching Method:速度够、对小区域干净
    result = cv2.inpaint(img, mask, inpaintRadius=radius, flags=cv2.INPAINT_TELEA)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(out), result):
        return False, f"写出失败:{out_path}"
    return True, ""


def remove_text(image_path: str, out_file: str | None = None,
                config_id: int | None = None) -> tuple[str, str]:
    """一键抹掉图中所有文字:LLM 定位 + OpenCV/inpaint 抹除。

    这是 _wants_text_removal 那条路径的真正实现 —— interpret() 里那条
    select.rect + contentAwareFill 实际上没生效(CLI 选区不传递)。
    """
    regions, lerr = locate_text_regions(image_path, config_id=config_id)
    if lerr:
        return "", f"文字定位失败:{lerr}"
    if not regions:
        return "", "这张图里没检测到文字,无法执行「去文字」。"
    out = Path(out_file) if out_file else (
        config.STATIC_DIR / "processed" / f"notext_{int(time.time())}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    if _opencv_available():
        ok, err = inpaint_regions_opencv(image_path, regions, str(out))
        if ok:
            return str(out), ""
    return remove_text_by_inpaint(image_path, regions, out_file=str(out))


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

        # 3. 「去掉图上的文字」这类需要选区的指令:CLI 没 OCR,先用多模态 LLM
        #    定位文字,再翻译成 select.rect + contentAwareFill。
        #    不做这步的话 LLM 会因为「没给坐标」直接回 0 steps(实测)。
        if _wants_text_removal(user_text) and image_url:
            regions, lerr = locate_text_regions(image_url, config_id=llm_config_id)
            if lerr:
                return [], "llm", f"文字定位失败:{lerr}"
            if not regions:
                return [], "llm", "这张图里没检测到文字,无法执行「去文字」。"
            steps = regions_to_steps(regions, image_path=image_url)
            found = "、".join(f"「{r['text']}」" for r in regions[:5]) or f"{len(regions)} 处"
            note = (f"已定位到 {len(regions)} 处文字:{found}。"
                    f"逐个框选后用内容识别填充抹除。")
            return steps, "llm", note

        # 4. 走 LLM
        steps, note, lerr = self.parser.parse(
            user_text, image_url=image_url, config_id=llm_config_id)
        if lerr:
            return [], "llm", lerr
        return steps, "llm", note

    def apply(self, in_file: str, steps: list[Step], out_file: str) -> dict:
        return self.cli.apply(in_file, steps, out_file)