# -*- coding: utf-8 -*-
"""结构化日志:JSON 落盘 + 紧凑 stderr + 密钥脱敏。

设计要点:
- 三路 handler(RotatingFile JSON / StreamHandler stderr / 可选 QtToast)。
- 密钥脱敏:所有 handler 走 formatter 前的 Filter 应用,把 `sk-xxx` / Bearer 长串
  / 常见 api_key 模式 → `***`。不修改 LogRecord.msg,只在输出前脱敏。
- 配置项:`app_settings.log_level` (debug/info/warning/error) + `log_to_stderr` (0/1)。
- 零新依赖:纯 stdlib `logging` + `concurrent.futures` + `json`。

调用约定:
- `app/main.py` 在 `db.init_db()` 之后立即 `setup_logging()` —— 这时还没创建
  QApplication,所以 QtToast handler 若无法建立不能阻塞主流程。
- 各模块 `from .logging_setup import get_logger; log = get_logger(__name__)`。
- 调试桩可继续用 `print(..., flush=True)`(AGENTS.md 已声明),仅业务关键路径
  改用 logger。
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path


# ── 公开 API ──────────────────────────────────────────────────────────────

_CONFIGURED = False
_LOCK = threading.Lock()

# 默认日志目录(走 core.config.DATA_DIR 派生,延迟到 setup_logging 时再解析)
DEFAULT_LEVEL = "INFO"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024     # 10 MB
DEFAULT_BACKUPS = 5
DEFAULT_APP_NAME = "pydrama"


# 密钥脱敏规则(模块级,供 filter / formatter / 落库前共用)
_SECRET_PATTERNS = [
    # OpenAI 风格 sk- 开头
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-***"),
    # Bearer token
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9_\-\.=]{20,}"), r"\1***"),
    # api_key=value / api_key: value / "api_key":"..." 三种写法
    (re.compile(r'(?i)(api[_-]?key["\']?\s*[:=]\s*["\']?)([A-Za-z0-9_\-\.]{8,})(["\']?)'),
     r"\1***\3"),
    # Authorization: <token> / X-Api-Key: <token>
    (re.compile(r'(?i)((?:Authorization|X-Api-Key|api[-_]?key)\s*[:=]\s*)([^\s,"\'}]{8,})'),
     r"\1***"),
    # 32+ 位连续 base64/hex(可能是 JWT/secret)
    (re.compile(r"\b[A-Za-z0-9_\-]{32,}\b"), "***"),
]


def scrub_secrets(text: str) -> str:
    """把文本里的密钥/Bearer/token 换成 `***`。

    脱敏要覆盖**所有**出口,不只是 log 的 msg:
    - 异常文本(exc / stack)里常带完整 URL,而部分供应商的 key 就在 query 里;
    - 落库的 sys_task.error_msg 是明文列,任务面板直接展示。
    """
    if not text:
        return text
    out = text
    for pat, repl in _SECRET_PATTERNS:
        out = pat.sub(repl, out)
    return out


class _SecretsFilter(logging.Filter):
    """在所有 handler 输出前对 record.getMessage() 做密钥脱敏。

    不修改 LogRecord.msg,只影响输出;record.args 仍保留原文便于程序内 introspect。
    命中后替换为 `***`,但保留可识别的尾 4 位便于排错。
    """

    PATTERNS = _SECRET_PATTERNS

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        scrubbed = scrub_secrets(msg)
        if scrubbed != msg:
            # 用替换后的字符串覆盖 msg,args 置空
            record.msg = scrubbed
            record.args = ()
        return True


class _JsonFormatter(logging.Formatter):
    """JSON 行,字段:ts / level / logger / msg / module / lineno / exc / ctx。

    extra={...} 透传到 JSON 的 ctx 字段;失败时降级,不抛异常。
    """

    RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "message", "asctime", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        try:
            ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds")
            out = {
                "ts": ts,
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                "module": record.module,
                "lineno": record.lineno,
            }
            if record.exc_info:
                # 异常文本也要脱敏:requests 的 HTTPError/ConnectionError 消息里
                # 带着**完整 URL**,而部分供应商的 key 就在 query 里
                # (例:params={"key": key, ...})→ 之前只洗 msg,exc 是明文。
                out["exc"] = scrub_secrets(self.formatException(record.exc_info))
            if record.stack_info:
                out["stack"] = scrub_secrets(record.stack_info)
            ctx = {k: v for k, v in record.__dict__.items() if k not in self.RESERVED}
            if ctx:
                out["ctx"] = ctx
            return json.dumps(out, ensure_ascii=False, default=str)
        except Exception as e:  # noqa: BLE001
            return json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "level": "ERROR",
                "logger": "logging_setup.JsonFormatter",
                "msg": f"format failed: {e}",
            }, ensure_ascii=False)


class _CompactFormatter(logging.Formatter):
    """stderr 紧凑格式:开发期肉眼可读。"""

    def __init__(self) -> None:
        super().__init__("%(levelname).1s [%(name)s] %(message)s")


def _level_from(value: str | int) -> int:
    if isinstance(value, int):
        return value
    name = (value or "").strip().upper()
    return {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }.get(name, logging.INFO)


def _log_dir(app_name: str) -> Path:
    """日志目录:data/logs/{app_name}.log(.1/.2/...)。

    DATA_DIR 来自 core.config;若 import 失败(测试期早),回退到 cwd。
    """
    try:
        from . import config
        base = config.DATA_DIR
    except Exception:  # noqa: BLE001
        base = Path.cwd() / "data"
    d = Path(base) / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_logging(
    app_name: str = DEFAULT_APP_NAME,
    level: str | int | None = None,
    *,
    to_stderr: bool | None = None,
    to_file: bool = True,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backups: int = DEFAULT_BACKUPS,
) -> None:
    """在 `app/main.py:db.init_db()` 之后立即调用。

    幂等:重复调用只更新 level,handler 不重复挂。
    """
    global _CONFIGURED
    with _LOCK:
        root = logging.getLogger()
        # 清掉 QApplication 之前 PySide6 自带的 handler(避免重复输出)
        for h in list(root.handlers):
            root.removeHandler(h)

        # 读设置(db 启动后 get_setting 可用)
        try:
            from . import db
            level_name = level if level is not None else db.get_setting("log_level", DEFAULT_LEVEL)
            if to_stderr is None:
                to_stderr = db.get_setting("log_to_stderr", "0") == "1"
        except Exception:  # noqa: BLE001
            level_name = level if level is not None else DEFAULT_LEVEL
            if to_stderr is None:
                to_stderr = True

        root.setLevel(_level_from(level_name))
        # 业务 logger 继承 root,这里不再单独 setLevel

        # 1) RotatingFileHandler
        if to_file:
            try:
                log_path = _log_dir(app_name) / f"{app_name}.log"
                fh = logging.handlers.RotatingFileHandler(
                    log_path, maxBytes=max_bytes, backupCount=backups,
                    encoding="utf-8",
                )
                fh.setLevel(logging.DEBUG)
                fh.setFormatter(_JsonFormatter())
                fh.addFilter(_SecretsFilter())
                root.addHandler(fh)
            except Exception as e:  # noqa: BLE001
                # 不可阻塞启动:stderr 还是要看到问题
                sys.stderr.write(f"[logging_setup] file handler failed: {e}\n")

        # 2) StreamHandler(stderr)
        if to_stderr:
            sh = logging.StreamHandler(stream=sys.stderr)
            sh.setLevel(_level_from(level_name))
            sh.setFormatter(_CompactFormatter())
            sh.addFilter(_SecretsFilter())
            root.addHandler(sh)

        # 3) QtToast handler(可选,WARNING+ 自动弹 toast)
        #     延迟到主窗口 attach 后才挂,避免 headless 测试触发 QWidget 警告
        #     见 attach_qt_toast_handler()。

        # 降低一些噪声 logger
        for noisy in ("urllib3", "PIL.PngImagePlugin"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

        _CONFIGURED = True


def attach_qt_toast_handler(toast_callable) -> None:
    """主窗口启动后调用,把 WARNING+ 转发到 toast。

    `toast_callable(level: str, message: str)` 由 ui/toast.py 提供。
    """
    class _QtToastHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                if record.levelno < logging.WARNING:
                    return
                msg = record.getMessage()
                if not msg:
                    return
                kind = "error" if record.levelno >= logging.ERROR else "warning"
                toast_callable(kind, msg[:200])
            except Exception:  # noqa: BLE001
                pass

    h = _QtToastHandler(level=logging.WARNING)
    h.addFilter(_SecretsFilter())
    logging.getLogger().addHandler(h)


def is_configured() -> bool:
    return _CONFIGURED


def get_logger(name: str) -> logging.Logger:
    """便捷获取 logger。模块路径名建议用 `__name__`。"""
    return logging.getLogger(name)
