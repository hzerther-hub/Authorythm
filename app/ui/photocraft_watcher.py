# -*- coding: utf-8 -*-
"""PhotoCraft 手动改图监听:打开图片到桌面端,文件改了自动回调。

# 背景
- chat-edit 页 + image-process 页都用了「✋ 我手动改」姿势,代码 100% 重复。
- QFileSystemWatcher 在 Windows 下对 PhotoCraft「先删后写」的保存姿势不稳,
  必须配合 mtime+size 双检 + QTimer 兜底 + 父目录监听。

# 设计
- 一个组件 = 启动 PhotoCraft + 三路监听(mtime/size) + emit changed。
- 调用方只接 changed 信号,语义跟 QFileSystemWatcher 一致(回调拿到新路径)。
- 不主动杀进程:用户可能自己启动了一个 PhotoCraft,杀了他就没法继续编辑。

# 用法
```python
from app.ui.photocraft_watcher import PhotoCraftWatcher

w = PhotoCraftWatcher(parent)
w.changed.connect(lambda new_path: print("saved:", new_path))
ok = w.watch("/path/to/image.png")
if not ok:
    print("未启动")
# 退出/切页时:
w.stop()
```
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal


class PhotoCraftWatcher(QObject):
    """打开图到 PhotoCraft,监听保存并 emit changed。"""

    # 文件被改(PhotoCraft 保存了一次)→ 新路径
    changed = Signal(str)
    # 启动/失败事件
    started = Signal()
    failed = Signal(str)

    # Polling 兜底周期
    POLL_MS = 1500

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._watcher: QFileSystemWatcher | None = None
        self._timer: QTimer | None = None
        self._current_path: str | None = None
        self._last_mtime: float | None = None
        self._last_size: int | None = None

    # ── 对外 ──

    @property
    def current_path(self) -> str | None:
        return self._current_path

    @property
    def watching(self) -> bool:
        return self._current_path is not None

    def watch(self, image_path: str) -> tuple[bool, str]:
        """打开 image_path 到 PhotoCraft 桌面端,开始三路监听。

        返回 (success, error)。
        """
        p = Path(image_path)
        if not p.exists():
            return False, f"图片不存在:{image_path}"

        from ..ai.photocraft_bridge import resolve_app_path
        app_path = resolve_app_path()
        if not app_path:
            return False, "PhotoCraft 未配置(设置 → PhotoCraft 聊天修图)"

        # 终止之前监听(若用户连点几次)
        self.stop()

        try:
            self._proc = subprocess.Popen(
                [app_path, str(p.resolve())], close_fds=True)
        except Exception as exc:  # noqa: BLE001
            return False, f"启动 PhotoCraft 失败:{exc}"

        # 初始化 mtime + size(用 .resolve() 保证和 watcher 一致)
        cur = str(p.resolve())
        self._current_path = cur
        try:
            self._last_mtime = os.path.getmtime(cur)
            self._last_size = os.path.getsize(cur)
        except OSError:
            self._last_mtime = None
            self._last_size = None

        # 1) QFileSystemWatcher.fileChanged(快路径)
        # 2) QFileSystemWatcher.directoryChanged(PhotoCraft 偶尔保存为新文件)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.addPath(cur)
        self._watcher.addPath(str(p.parent))
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._watcher.directoryChanged.connect(self._on_dir_changed)

        # 3) QTimer polling(Windows 下 watcher 漏事件时兜底)
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

        self.started.emit()
        return True, ""

    def stop(self) -> None:
        """停监听(不主动杀 PhotoCraft 进程)。"""
        if self._watcher:
            try:
                self._watcher.fileChanged.disconnect(self._on_file_changed)
            except Exception:  # noqa: BLE001
                pass
            try:
                self._watcher.directoryChanged.disconnect(self._on_dir_changed)
            except Exception:  # noqa: BLE001
                pass
            self._watcher.deleteLater()
            self._watcher = None
        if self._timer:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        self._current_path = None
        self._last_mtime = None
        self._last_size = None
        self._proc = None

    # ── 内部 ──

    def _on_file_changed(self, path: str):
        # 编辑器保存时常常先删后写,watcher 触发后 path 会被摘掉 —— 二次保险。
        if self._watcher and path and path not in self._watcher.files():
            self._watcher.addPath(path)
        self._check_and_apply(path)

    def _on_dir_changed(self, _dir: str):
        if self._current_path:
            self._check_and_apply(self._current_path)

    def _poll(self):
        if self._current_path:
            self._check_and_apply(self._current_path)

    def _check_and_apply(self, path: str):
        """mtime + size 双检,任一变化才视为改动,emit changed。"""
        if not path or not Path(path).exists():
            return
        try:
            new_mtime = os.path.getmtime(path)
            new_size = os.path.getsize(path)
        except OSError:
            return
        if self._last_mtime is not None:
            mtime_changed = new_mtime > self._last_mtime + 0.05  # 浮点容差
            size_changed = (self._last_size is not None
                            and new_size != self._last_size)
            if not (mtime_changed or size_changed):
                return
        self._last_mtime = new_mtime
        self._last_size = new_size
        self.changed.emit(path)
