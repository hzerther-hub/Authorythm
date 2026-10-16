# -*- coding: utf-8 -*-
"""手动换画风弹窗:选画风 → 生成 → **先看结果,满意才替换原图**。

刻意分两步而不是「一键换」:实测图生图会持续往画面里加元素(真人转漫画
连着四次加了 8/12/2 个人,场景转漫画加了店小二),提示词压不住。
所以生成结果先落在临时文件,由用户点「用这张」才写回库 —— 原图随时还在。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout)

from ..core.i18n import tr
from ..pipeline import style_convert
from . import widgets as W
from .toast import err, info, warn


class StyleConvertDialog(QDialog):
    """row_id / table 决定转哪张图;accepted 时 result_path 是新图本地路径。"""

    def __init__(self, row_id: int, table: str, drama_id: int,
                 parent=None, config_id: int | None = None):
        super().__init__(parent)
        self.row_id, self.table, self.drama_id = row_id, table, drama_id
        self.config_id = config_id
        self.result_path = ""
        self.setWindowTitle(tr("换画风"))
        self.resize(720, 720)

        root = QVBoxLayout(self)
        root.addWidget(W.h2(f"{style_convert._TABLES.get(table, '')} · 换画风"))

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("目标画风")))
        self.style_combo = QComboBox()
        cur = _current_style(drama_id)
        for v, n in style_convert.available_styles():
            self.style_combo.addItem(n, v)
            if v == cur:
                self.style_combo.setCurrentIndex(self.style_combo.count() - 1)
        row.addWidget(self.style_combo, 1)
        self.go_btn = W.primary_btn(tr("生成预览"))
        self.go_btn.clicked.connect(self._run)
        row.addWidget(self.go_btn)
        root.addLayout(row)

        self.before = _label_img(300, 220)
        self.after = _label_img(300, 220)
        cmp_row = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(W.muted(tr("原图")))
        left.addWidget(self.before)
        cmp_row.addLayout(left)
        right = QVBoxLayout()
        right.addWidget(W.muted(tr("转换结果")))
        right.addWidget(self.after)
        cmp_row.addLayout(right)
        root.addLayout(cmp_row)

        self.status = W.muted("")
        root.addWidget(self.status)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.use_btn = QPushButton(tr("用这张替换原图"))
        self.use_btn.setObjectName("primary")
        self.use_btn.setEnabled(False)      # 没生成出结果之前不能点
        self.use_btn.clicked.connect(self._accept)
        bottom.addWidget(self.use_btn)
        cancel = QPushButton(tr("取消"))
        cancel.clicked.connect(self.reject)
        bottom.addWidget(cancel)
        root.addLayout(bottom)

        _fill_img(self.before, _current_image(row_id, table))

    def _run(self):
        if not self.go_btn.isEnabled():
            return
        style = self.style_combo.currentData()
        self.go_btn.setEnabled(False)
        self.use_btn.setEnabled(False)
        self.status.setText(tr("正在转换…通常 30-60 秒"))
        self._shot = None
        _submit_convert(self, self.row_id, self.table, style, self.config_id, self._done)

    def _done(self, path: str | None, error: str | None):
        self.go_btn.setEnabled(True)
        if error or not path:
            self.status.setText(tr("转换失败:{}").format(str(error or "")[:160]))
            return
        self._shot = path
        _fill_img(self.after, path)
        self.use_btn.setEnabled(True)
        self.status.setText(
            tr("转换完成。模型可能加入了原图没有的人物或元素 —— 满意点「用这张」,否则取消保留原图。"))

    def _accept(self):
        if not self._shot:
            return
        self.result_path = self._shot
        self.accept()


def _current_style(drama_id: int) -> str:
    from ..core import db
    try:
        r = db.q1("SELECT comic_style, style FROM dramas WHERE id=?", (drama_id,))
    except Exception:  # noqa: BLE001
        return "3d"
    if not r:
        return "3d"
    return (r["comic_style"] or r["style"] or "3d")


def _current_image(row_id: int, table: str) -> str:
    from ..core import config, db
    try:
        u = (db.q1(f"SELECT image_url FROM {table} WHERE id=?", (row_id,)) or {}).get("image_url") or ""
    except Exception:  # noqa: BLE001
        return ""
    if not u:
        return ""
    return str(config.media_url_to_path(u) if u.startswith(("/static/", "static/")) else u)


def _label_img(w: int, h: int) -> QLabel:
    lab = QLabel()
    lab.setFixedSize(w, h)
    lab.setAlignment(Qt.AlignCenter)
    lab.setStyleSheet("background:#f5f5f5;border:1px solid #ddd;")
    lab.setText(tr("—"))
    return lab


def _fill_img(lab: QLabel, path: str):
    if not path:
        lab.setText(tr("无"))
        return
    try:
        from PySide6.QtGui import QPixmap
        pm = QPixmap(str(path))
        if pm.isNull():
            lab.setText(tr("读取失败"))
            return
        lab.setPixmap(pm.scaled(lab.width() - 4, lab.height() - 4,
                                Qt.KeepAspectRatio, Qt.SmoothTransformation))
    except Exception:  # noqa: BLE001
        lab.setText(tr("读取失败"))


def _submit_convert(dlg: StyleConvertDialog, row_id, table, style, config_id, done):
    """走 TASKMGR(worker 线程只碰纯数据,不碰控件),done 回主线程更新界面。"""
    from ..core.taskmgr import TASKMGR

    def job(tid):
        return style_convert.convert(row_id, table, style, config_id)

    def finish(tid, result, error):
        done(str(result) if result and not error else None,
             str(error) if error else None)

    TASKMGR.submit("image", job, finish)
