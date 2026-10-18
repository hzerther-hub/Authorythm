# -*- coding: utf-8 -*-
"""统一后台任务管理:QThreadPool 执行,状态落 sys_task 表。

生命周期(对齐原版 generation.ts):
  processing → (polling) → completed / failed
"""
from __future__ import annotations

import json
import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from . import db


def create_task(task_type: str, **links) -> int:
    ts = db.now()
    cols = {"type": task_type, "status": "processing", "created_at": ts, "updated_at": ts}
    for k in ("drama_id", "episode_id", "storyboard_id", "scene_id", "character_id", "prop_id",
              "provider", "model", "task_id", "result_url", "local_path"):
        if links.get(k) is not None:
            cols[k] = str(links[k]) if not isinstance(links[k], (int, float)) else links[k]
    keys = ",".join(cols)
    marks = ",".join("?" * len(cols))
    return db.ex(f"INSERT INTO sys_task({keys}) VALUES({marks})", tuple(cols.values()))


def set_stage(task_id: int, stage: str) -> None:
    """写任务阶段标记到 sys_task.params.stage(不改表结构,批量面板据此显示"当前在做什么")。

    阶段:writing 正文生成 / reviewing 审校 / repairing 问题修复 / compressing 卷段压缩。
    失败只记日志,不阻断主流程。
    """
    try:
        row = db.q1("SELECT params FROM sys_task WHERE id=?", (task_id,))
        params = jload_safe(row["params"] if row else None)
        params["stage"] = stage
        db.ex("UPDATE sys_task SET params=?, updated_at=? WHERE id=?",
              (json.dumps(params, ensure_ascii=False), db_now(), task_id))
    except Exception:  # noqa: BLE001
        pass


def get_stage(task_id: int) -> str:
    row = db.q1("SELECT params FROM sys_task WHERE id=?", (task_id,))
    return (jload_safe(row["params"] if row else None)).get("stage", "")


def set_task_progress(task_id: int, percent: int) -> None:
    """写 sys_task.progress 并发 progress 信号(0-100)。

    sys_task.progress 这一列建表时就有,此前从未被写过 —— 视频任务最长等 50 分钟,
    界面上只有一个转圈,用户无法区分「在排队」和「卡死了」。Agnes 轮询响应带
    官方 progress 字段(见 agnes_video.parse_poll_response),这里把它落到列上。

    信号只 emit 不连 UI 消费方时是安全的:worker 线程 emit,谁连谁在主线程收到。
    失败只记日志,不阻断生成。
    """
    try:
        pct = max(0, min(100, int(percent)))
    except (TypeError, ValueError):
        return
    try:
        db.ex("UPDATE sys_task SET progress=?, updated_at=? WHERE id=?",
              (pct, db_now(), task_id))
    except Exception:  # noqa: BLE001
        pass
    try:
        _signals().progress.emit(task_id, pct)
    except Exception:  # noqa: BLE001
        pass


def _signals() -> "TaskSignals":
    """取全局 TaskSignals 单例(延迟导入避免与 QApplication 初始化顺序耦合)。"""
    global _SIGNALS
    if _SIGNALS is None:
        _SIGNALS = TaskSignals()
    return _SIGNALS


_SIGNALS: "TaskSignals | None" = None


def jload_safe(raw):
    try:
        v = json.loads(raw or "{}")
        return v if isinstance(v, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def db_now() -> str:
    from . import db as _db
    return _db.now()


def finish_task(task_id: int, status: str, error: str | None = None,
                result_url: str | None = None, local_path: str | None = None) -> None:
    db.ex("UPDATE sys_task SET status=?, error_msg=?, result_url=COALESCE(?,result_url), local_path=COALESCE(?,local_path), updated_at=? WHERE id=?",
          (status, error, result_url, local_path, db.now(), task_id))


def delete_video_task(task_id: int) -> str | None:
    """删除一条视频任务记录与其成片文件(对齐参考项目 DELETE /tasks/:id)。

    若删的是该分镜**当前主视频**,把剩余最新一条已完成记录晋级为 video_url
    (没有则置空、状态归位 failed 让用户能重试);返回晋级后的视频地址(可为 '')。
    文件被占用删不动时不阻断记录清理(Windows 播放器句柄由 UI 侧先释放)。
    """
    from pathlib import Path
    t = db.q1("SELECT * FROM sys_task WHERE id=? AND type='video'", (task_id,))
    if not t:
        return None
    if t["local_path"]:
        try:
            Path(t["local_path"]).unlink(missing_ok=True)
        except OSError:
            pass
    db.ex("DELETE FROM sys_task WHERE id=?", (task_id,))
    sb_id = t["storyboard_id"]
    if not sb_id:
        return None
    from . import config as _cfg
    sb = db.q1("SELECT video_url FROM storyboards WHERE id=?", (sb_id,))
    deleted_media = _cfg.path_to_media_url(Path(t["local_path"])) if t["local_path"] else None
    promoted = ""
    if sb and deleted_media and sb["video_url"] == deleted_media:
        nxt = db.q1("""SELECT local_path FROM sys_task WHERE type='video' AND storyboard_id=?
                       AND status='completed' AND local_path IS NOT NULL AND local_path<>''
                       ORDER BY created_at DESC LIMIT 1""", (sb_id,))
        if nxt and nxt["local_path"]:
            promoted = _cfg.path_to_media_url(Path(nxt["local_path"]))
        db.ex("""UPDATE storyboards SET video_url=?,
                status=CASE WHEN ?<>'' THEN 'completed' ELSE 'failed' END, updated_at=?
                WHERE id=?""", (promoted or None, promoted, db.now(), sb_id))
    return promoted


def active_count() -> int:
    row = db.q1("SELECT COUNT(*) c FROM sys_task WHERE status='processing'")
    return row["c"] if row else 0


class TaskSignals(QObject):
    finished = Signal(int, str)       # task_id, status
    progress = Signal(int, int)       # task_id, percent
    message = Signal(str)
    busy_changed = Signal(bool, str)  # 是否忙, 任务类型(D 类全局 running 态)
    type_finished = Signal(str)       # 某服务类型的任务跑完一个(image/video/tts/…)
    # 任务完成回调走 Qt 跨线程队列(比 QTimer 可靠,不会因事件循环状态丢失)
    done_cb = Signal(object, object, object)   # task_id, result, error


def on_main(fn):
    """把 UI 更新调度回主线程(后台线程直接调 Qt 会跨线程报错)。

    异常必须显式暴露,否则 QTimer.singleShot 会把它静默吞掉,表现为"点了没反应"。
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return

    def _wrapped():
        try:
            fn()
        except Exception:  # noqa: BLE001
            import traceback
            traceback.print_exc()
    QTimer.singleShot(0, _wrapped)


class _FnTask(QRunnable):
    def __init__(self, task_id: int, fn: Callable[..., object], signals: TaskSignals,
                 done_cb: Callable | None, svc: str = "", task_type: str = ""):
        super().__init__()
        self.task_id, self.fn, self.signals, self.done_cb = task_id, fn, signals, done_cb
        self.svc = svc                   # 服务类型:收尾时按类型递减忙计数
        self.task_type = task_type       # 任务类型(用于 metrics 埋点)
        self.setAutoDelete(True)

    def run(self):  # noqa: D102
        import time as _t
        t0 = _t.perf_counter()
        try:
            result = self.fn(self.task_id)
            finish_task(self.task_id, "completed")
            self._emit_done(self.done_cb, result, None)
            self._record_metric("completed", _t.perf_counter() - t0)
        except Exception:  # noqa: BLE001
            err = traceback.format_exc(limit=6)
            finish_task(self.task_id, "failed", err)
            self._emit_done(self.done_cb, None, err)
            self._record_metric("failed", _t.perf_counter() - t0)
        finally:
            self._emit(self.signals.finished, self.task_id, "done")
            self._emit(self.signals.busy_changed, active_count() > 0, "")
            if self.svc:
                self._emit(self.signals.type_finished, self.svc)
            # 周期性刷盘(避免每次都 IO)
            try:
                from . import metrics
                metrics.maybe_flush()
            except Exception:  # noqa: BLE001
                pass

    def _record_metric(self, status: str, duration_sec: float) -> None:
        """埋点:失败也只静默(埋点本身不能抛)。"""
        try:
            from . import metrics
            if self.task_type:
                metrics.incr(f"task.{self.task_type}.{status}")
                metrics.observe(f"task.{self.task_type}.duration_ms",
                                int(duration_sec * 1000))
            if self.svc:
                metrics.incr(f"task.svc.{self.svc}.{status}")
        except Exception:  # noqa: BLE001
            pass

    def _emit_done(self, cb, result, error):
        try:
            self.signals.done_cb.emit(cb, result, error)
        except RuntimeError:  # noqa: BLE001 —— 进程退出中,C++ 端已删;任务状态已落库,无需回调
            pass

    def _emit(self, sig, *args):
        try:
            sig.emit(*args)
        except RuntimeError:  # noqa: BLE001
            pass


class TaskManager(QObject):
    """全局任务管理器:submit() 返回 sys_task id;UI 轮询或订阅信号。"""
    updated = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(6)
        self.signals = TaskSignals()
        # 别名:外部(UI)直接连管理器实例上的 type_finished,不必摸内部 signals
        self.type_finished = self.signals.type_finished
        self.signals.finished.connect(lambda *_: self.updated.emit())
        self.signals.done_cb.connect(self._run_done_cb)
        self.signals.finished.connect(lambda *_: self._leave_busy())
        self.signals.type_finished.connect(self._leave_busy_type)
        self.signals.type_finished.connect(lambda *_: self.updated.emit())

    @staticmethod
    def active_count() -> int:
        return active_count()

    # ── 全局盲文等待(D 类)──
    # 任何任务提交/完成都会把当前活动窗口切成盲文等待态,
    # 避免"点了按钮没反应,不知道在不在跑"。
    _host: object | None = None
    _pending: int = 0

    @classmethod
    def attach_host(cls, window) -> None:
        """主窗口启动时调用,登记为等待态宿主。"""
        cls._host = window

    @classmethod
    def _host_window(cls):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        return app.activeWindow() or app.focusWidget() or cls._host

    _on_main = staticmethod(on_main)

    # 按服务类型的活动任务数:按钮状态同步用(video 忙 → 单镜生成/批量按钮全禁)。
    # 计数在主线程的 submit 与 type_finished(queued 回主线程)两处增减,天然串行。
    TYPE_BUSY: dict[str, int] = {}

    @staticmethod
    def is_busy(service_type: str) -> bool:
        """该服务类型(image/video/tts/text/faceswap)是否还有任务在跑。"""
        return TaskManager.TYPE_BUSY.get(service_type, 0) > 0

    def _enter_busy(self, task_type: str):
        TaskManager._pending += 1
        TaskManager.TYPE_BUSY[task_type] = TaskManager.TYPE_BUSY.get(task_type, 0) + 1
        msg = f"正在{self.LABEL.get(task_type, '处理')}…"
        on_main(lambda: self._apply_busy(True, msg))

    def _leave_busy(self):
        TaskManager._pending = max(0, TaskManager._pending - 1)
        if TaskManager._pending:
            return
        on_main(lambda: self._apply_busy(False, ""))

    def _leave_busy_type(self, svc: str) -> None:
        TaskManager.TYPE_BUSY[svc] = max(0, TaskManager.TYPE_BUSY.get(svc, 0) - 1)

    def _apply_busy(self, on: bool, msg: str):
        # 必须发给登记的主窗口(转轮的宿主)。曾用 activeWindow():任务完成时激活的
        # 窗口往往是"本章已生成"那类弹窗,没有 set_busy,调用被 except 吞掉,
        # 关灯指令丢失 → 顶栏转轮永远转下去。
        w = TaskManager._host or TaskManager._host_window()
        if w is None:
            return
        try:
            w.set_busy(on, msg)
        except Exception:  # noqa: BLE001
            pass

    # 任务类型 → 中文动作名(等待态文案)
    LABEL = {
        "image": "生成图片", "video": "生成视频", "tts": "合成配音", "cover": "生成封面",
        "script": "改写剧本", "novel": "写小说", "novel_batch": "批量写章节",
        "novel_edit": "改稿", "novel_title": "起章节名", "review": "审校",
        "extract": "提取资产", "storyboard": "拆分镜", "sb_repair": "补全分镜",
        "storyboard_split": "拆分镜", "comic": "生成漫画", "prompt": "生成提示词",
        "promo": "写宣传文案", "face_swap": "换脸", "face_swap_batch": "批量换脸",
        "merge": "拼接成片", "stitch": "拼接长图", "episode_cover": "生成章封面",
        "chat_edit": "PhotoCraft 修图",
    }

    # 任务类型 → 所需 AI 服务(未就绪时在提交前拦下,不留"跑了没结果"的空任务)
    TYPE_SERVICE = {
        "script": "text", "novel": "text", "novel_batch": "text", "novel_edit": "text",
        "novel_title": "text", "review": "text", "extract": "text", "storyboard": "text",
        "prompt": "text", "comic": "text", "promo": "text", "sb_repair": "text",
        "cover": "image", "image": "image", "face_swap": "faceswap", "face_swap_batch": "faceswap",
        "video": "video",
        # tts 不做就绪校验:tts_client.synthesize 自带三级引擎链,豆包配置停用/
        # 缺 key 时自动落回**免费的微软 Edge TTS**(无需任何配置)。此前挂了
        # "tts": "tts",用户停用豆包想切免费,就绪校验直接拦下任务弹「配音
        # 服务未就绪」,免费通道永远走不到(实测)。
        # 同款复刻整段直传:走多模态文本模型读 base64 视频。对齐参考项目
        # auto-generate.ts 里 clone_understand 的 taskType;不注册的话 submit 会跳过
        # 就绪校验,缺配置也得等模型把请求打回来才失败。
        "clone_understand": "text",
    }

    def _run_done_cb(self, cb, result, error):
        """在主线程执行完成回调(信号 queued 连接保证线程安全)。"""
        tid = None
        try:
            tid = db.get_db().execute("SELECT MAX(id) id FROM sys_task").fetchone()["id"]
        except Exception:  # noqa: BLE001
            pass
        if cb:
            cb(tid, result, error)

    def submit(self, task_type: str, fn: Callable[..., object],
               done_cb: Callable | None = None, **links) -> int:
        """提交后台任务。AI 类任务先做就绪校验:缺配置/Key 直接弹明确提示并返回 0(不建任务)。"""
        svc = self.TYPE_SERVICE.get(task_type)
        if svc:
            from .preflight import ensure_ready
            if not ensure_ready(svc):
                if done_cb:
                    done_cb(0, None, RuntimeError(f"{task_type} 已取消:{svc} 服务未就绪"))
                return 0
        tid = create_task(task_type, **links)
        self._enter_busy(task_type)
        self.pool.start(_FnTask(tid, fn, self.signals, done_cb, svc, task_type))
        self.signals.busy_changed.emit(True, task_type)
        self.updated.emit()
        return tid

    # 轮询任务列表(任务面板 / 工作台用)
    @staticmethod
    def list_tasks(episode_id: int | None = None, limit: int = 100) -> list:
        if episode_id:
            return db.q("SELECT * FROM sys_task WHERE episode_id=? ORDER BY id DESC LIMIT ?",
                        (episode_id, limit))
        return db.q("SELECT * FROM sys_task ORDER BY id DESC LIMIT ?", (limit,))

    @staticmethod
    def ep_video_stats(episode_id: int) -> dict:
        """本集视频任务的实时统计。

        关键:processing 行只算「5 分钟内动过的」,否则把孤儿(进程被杀但
        没走完 finish_task 路径)的也算成「生成中」,胶囊点进去空操作
        (没有 worker 在跑,「停止」按钮也没法触发)。

        孤儿行顺手在这里归位为 failed —— 下一轮 STARTED 信号来了就一致。
        """
        from datetime import datetime, timedelta
        rows = db.q(
            "SELECT status, COUNT(*) c FROM sys_task WHERE episode_id=? AND type='video' GROUP BY status",
            (episode_id,))
        stats = {r["status"]: r["c"] for r in rows}
        processing = stats.get("processing", 0)
        if processing:
            # 5 分钟没动过的 processing 行 → 视为孤儿
            cutoff = (datetime.utcnow() - timedelta(minutes=5)).isoformat() + "Z"
            orphans = db.q(
                "SELECT id FROM sys_task WHERE episode_id=? AND type='video' "
                "AND status='processing' AND updated_at<?",
                (episode_id, cutoff))
            if orphans:
                ids = ",".join(str(o[0]) for o in orphans)
                db.ex(
                    f"UPDATE sys_task SET status='failed', "
                    f"error_msg='孤儿任务(进程异常退出),自动归位', updated_at=? "
                    f"WHERE id IN ({ids}) AND status='processing'",
                    (datetime.utcnow().isoformat() + "Z",))
                processing -= len(orphans)
                stats["failed"] = stats.get("failed", 0) + len(orphans)
        return {"processing": processing,
                "completed": stats.get("completed", 0),
                "failed": stats.get("failed", 0)}


TASKMGR = TaskManager()


def short_error(err: str) -> str:
    """从 taskmgr 回调的 traceback 全文里取**最后一行** —— 真正的异常类型+消息。

    done 回调拿到的是 format_exc 全文;直接 ``str(error)[:160]`` 只会显示
    「File ... line N, in run」的头部,真正的异常(如 AIError: Agnes 503)
    被截掉,toast 上用户永远看不到失败原因(实测:章节计划生成失败只弹
    三行文件路径)。要完整堆栈去任务面板/任务表 error_msg 列看。
    """
    if not err:
        return ""
    lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
    return lines[-1] if lines else ""
