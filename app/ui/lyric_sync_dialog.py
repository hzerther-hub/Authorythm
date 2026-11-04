# -*- coding: utf-8 -*-
"""歌词打轴器:逐行给歌词定起止时间(卡拉OK级对轴)。

打轴结果落 metadata.mtv.lyrics_timed,三处消费:
- build_lyrics_ass:字幕按打轴时间逐行出现(不再平分歌曲时长);
- mtv_writer 分镜:prompt 带每行时间窗,镜头切点与歌词行对齐;
- generate_singing_shots:按窗口切音频段做对口型镜头。

打点交互:播放歌曲 → 每当唱到下一行歌词,按「打点」(或空格)把当前播放位置
记为该行开始、上一行结束;也可直接在表格里手填秒数。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

from ..core.i18n import tr
from . import widgets as W


class LyricSyncDialog(QDialog):
    """歌词逐行打轴:播放打点 + 逐行手填,保存写回 mtv.lyrics_timed。"""

    def __init__(self, parent, drama_id: int, song_path: str, duration: float,
                 timed: list[dict] | None, fallback_lines: list[str]):
        super().__init__(parent)
        self._drama_id = drama_id
        self._song = str(song_path)
        self._dur = float(duration or 0)
        self._cur = 0                                   # 下一个待打点的行号
        self.setWindowTitle(tr("mtv_sync_title"))
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        tip = W.muted(tr("mtv_sync_tip").format(d=f"{self._dur:.0f}"))
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # 行数据:优先已打轴的;没打过轴用纯歌词行(时间为空待打)
        rows: list[tuple[str, float | None, float | None]] = []
        if timed:
            rows = [(str(x.get("text") or ""),
                     float(x.get("start") or 0), float(x.get("end") or 0))
                    for x in timed]
        else:
            rows = [(ln, None, None) for ln in fallback_lines]
        if not rows:
            rows = [("", None, None)]

        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels([tr("mtv_sync_line"), tr("mtv_sync_start"),
                                              tr("mtv_sync_end")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        for i, (text, st, en) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(text))
            for col, val in ((1, st), (2, en)):
                spin = self._spin(self._dur)
                if val is not None:
                    spin.setValue(float(val))
                self.table.setCellWidget(i, col, spin)
        self.table.setCurrentCell(0, 0)
        lay.addWidget(self.table, 1)

        # 播放控制行
        prow = QHBoxLayout()
        self.play_btn = QPushButton(tr("mtv_sync_play"))
        self.play_btn.clicked.connect(self._toggle_play)
        prow.addWidget(self.play_btn)
        mark = QPushButton(tr("mtv_sync_mark"))
        mark.setToolTip(tr("mtv_sync_mark_tip"))
        mark.clicked.connect(self._mark)
        prow.addWidget(mark)
        even = QPushButton(tr("mtv_sync_even"))
        even.setToolTip(tr("mtv_sync_even_tip"))
        even.clicked.connect(self._fill_even)
        prow.addWidget(even)
        prow.addStretch(1)
        self.pos_lab = QLabel("0.0s")
        self.pos_lab.setObjectName("muted")
        prow.addWidget(self.pos_lab)
        lay.addLayout(prow)

        btns = QHBoxLayout()
        btns.addStretch(1)
        save = QPushButton(tr("mtv_sync_save"))
        save.setObjectName("primaryBtn")
        save.clicked.connect(self._save)
        btns.addWidget(save)
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        lay.addLayout(btns)

        # 歌曲播放器(打点的「当前时刻」来源)
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.setSource(QUrl.fromLocalFile(str(Path(self._song))))
        self._player.positionChanged.connect(self._on_pos)
        # 空格 = 打点(播放中最高频的操作)
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._mark)

    # ── 表格 ─────────────────────────────────────────────────────────────
    @staticmethod
    def _spin(dur: float):
        from PySide6.QtWidgets import QDoubleSpinBox
        sp = QDoubleSpinBox()
        sp.setRange(0.0, max(10.0, dur + 30.0))
        sp.setDecimals(1)
        sp.setSingleStep(0.5)
        return sp

    def _rows(self) -> list[dict]:
        out = []
        for i in range(self.table.rowCount()):
            text = (self.table.item(i, 0).text() if self.table.item(i, 0) else "").strip()
            st = self.table.cellWidget(i, 1).value()
            en = self.table.cellWidget(i, 2).value()
            out.append({"text": text, "start": round(st, 1), "end": round(en, 1)})
        return out

    # ── 播放与打点 ────────────────────────────────────────────────────────
    def _toggle_play(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self.play_btn.setText(tr("mtv_sync_play"))
        else:
            # 从「下一个待打点行」的起点附近继续,打点不用来回拖
            rows = self._rows()
            if self._cur < len(rows):
                self._player.setPosition(int(rows[self._cur]["start"] * 1000))
            self._player.play()
            self.play_btn.setText(tr("mtv_sync_pause"))

    def _on_pos(self, ms: int):
        self.pos_lab.setText(f"{ms / 1000:.1f}s")

    def _mark(self):
        """打点:当前播放位置 = 第 _cur 行的开始、上一行的结束;指针后移。"""
        pos = self._player.position() / 1000
        if self._cur >= self.table.rowCount():
            return
        if self._cur > 0:
            prev = self.table.cellWidget(self._cur - 1, 2)
            prev.setValue(round(pos, 1))
        cur = self.table.cellWidget(self._cur, 1)
        cur.setValue(round(pos, 1))
        self.table.setCurrentCell(self._cur, 0)
        self._cur += 1
        if self._cur < self.table.rowCount():
            self.table.scrollToItem(self.table.item(self._cur, 0))

    def _fill_even(self):
        """自动均匀:没打点前的起步辅助(0 → dur 均分到每行,再手动微调)。"""
        n = self.table.rowCount()
        if n == 0:
            return
        per = self._dur / n if self._dur > 0 else 5.0
        for i in range(n):
            self.table.cellWidget(i, 1).setValue(round(i * per, 1))
            self.table.cellWidget(i, 2).setValue(round((i + 1) * per, 1))
        self._cur = 0

    # ── 保存 ─────────────────────────────────────────────────────────────
    def _save(self):
        from ..pipeline import mtv as mtv_pipe
        rows = [r for r in self._rows() if r["text"]]
        mtv_pipe.save_lyrics_timed(self._drama_id, rows)
        self.accept()
