# -*- coding: utf-8 -*-
"""项目设置 + 素材详情编辑弹窗(对齐原版 detail.vue 的项目设置 / 素材详情对话框)。"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from .confirm import ask
from ..core import config, db
from ..core.i18n import LANGS, tr
from . import widgets as W
from .braille import WaitingButton
from .toast import err, ok

ASPECTS = [("16:9", "u_ratio_16_9"), ("9:16", "u_ratio_9_16"),
            ("1:1", "u_ratio_1_1"), ("adaptive", "u_ratio_adaptive")]
ETHNICITIES = [("auto", "auto"), ("east_asian", "u_eth_east_asian"),
               ("middle_eastern", "u_eth_middle_eastern"), ("western", "u_eth_western"),
               ("south_asian", "u_eth_south_asian"), ("latin", "u_eth_latin"),
               ("african", "u_eth_african"), ("mixed", "u_eth_mixed")]


def _has_generated_content(drama_id: int) -> bool:
    """项目是否已经产出**真实文字**(正文 / 剧本 / 漫画格)。

    锁定创意描述的本意是保护「已按这份创意生成的章节」之间的一致性,
    所以只有真生成过内容才锁;新建项目自带的空壳集数不算
    (否则创意描述从创建那一刻就永远改不了)。
    """
    row = db.q1("""SELECT COUNT(*) c FROM episodes
                   WHERE drama_id=? AND (
                       LENGTH(TRIM(COALESCE(content,''))) > 0
                    OR LENGTH(TRIM(COALESCE(script_content,''))) > 0)""", (drama_id,))
    if row and row["c"]:
        return True
    panel = db.q1("""SELECT COUNT(*) c FROM comic_panels p JOIN episodes e ON e.id=p.episode_id
                     WHERE e.drama_id=?
                       AND (LENGTH(TRIM(COALESCE(p.description,''))) > 0
                         OR LENGTH(TRIM(COALESCE(p.dialogue,''))) > 0)""", (drama_id,))
    return bool(panel and panel["c"])


def _muted(t: str) -> QLabel:
    return W.muted(t)


class ProjectSettingsDialog(QDialog):
    """项目设置:标题 / 简介 / 题材 / 画幅 / 视觉风格 / 面孔文化。"""

    def __init__(self, parent, drama_id: int):
        super().__init__(parent)
        self.drama_id = drama_id
        d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
        self.setWindowTitle(tr("project_settings"))
        self.resize(640, 540)
        root = QVBoxLayout(self)
        root.addWidget(W.h2(tr("project_settings")))
        # 双列布局:把字段配对到两列,缩短对话框高度
        # 列结构:[label, control, label, control] 四列两两配对
        # 全宽行:占 col 0+1 (左) + col 2+3 (右,空占)
        from PySide6.QtWidgets import QGridLayout
        f = QGridLayout()
        f.setHorizontalSpacing(14)
        f.setVerticalSpacing(6)
        f.setColumnStretch(1, 3)
        f.setColumnStretch(3, 3)
        row_idx = 0

        def _lab(text: str) -> QLabel:
            return QLabel(text)

        def _row_pair(label_l, ctrl_l, label_r, ctrl_r):
            """左 (col 0,1) 右 (col 2,3) 一行两项配对。"""
            nonlocal row_idx
            f.addWidget(_lab(label_l), row_idx, 0, Qt.AlignRight | Qt.AlignVCenter)
            f.addWidget(ctrl_l, row_idx, 1)
            f.addWidget(_lab(label_r), row_idx, 2, Qt.AlignRight | Qt.AlignVCenter)
            f.addWidget(ctrl_r, row_idx, 3)
            row_idx += 1

        def _row_full(label_text, ctrl, hint_text=None):
            """全宽一行(标签 col 0,控件 col 1-3 合并)。"""
            nonlocal row_idx
            if label_text:
                f.addWidget(_lab(label_text), row_idx, 0, Qt.AlignRight | Qt.AlignTop)
                f.addWidget(ctrl, row_idx, 1, 1, 3)
            else:
                f.addWidget(ctrl, row_idx, 0, 1, 4)
            row_idx += 1
            if hint_text:
                f.addWidget(_muted(hint_text), row_idx, 0, 1, 4)
                row_idx += 1

        def _row_hint_full(hint_text):
            nonlocal row_idx
            f.addWidget(_muted(hint_text), row_idx, 0, 1, 4)
            row_idx += 1

        # 项目名称 — 全宽
        self.title = QLineEdit(d["title"])
        _row_full(tr("project_name"), self.title)

        meta = db.jload(d["metadata"], {})
        # 简介 — 全宽
        self.intro = QLineEdit(meta.get("intro", ""))
        self.intro.setPlaceholderText(tr("u_whole_placeholder"))
        _row_full(tr("u_intro"), self.intro)

        # 题材 — 全宽(短文本输入)
        self.genre = QLineEdit(meta.get("genre", ""))
        self.genre.setPlaceholderText(tr("u_genre"))
        _row_full(tr("u_genre"), self.genre)

        # AI 起草简介/题材 + 提示 — 全宽放一行
        meta_row = QWidget()
        mr = QHBoxLayout(meta_row)
        mr.setContentsMargins(0, 0, 0, 0)
        self.meta_btn = WaitingButton(tr("✨ AI 起草简介 / 题材"))
        W.set_icon(self.meta_btn, "magic")
        self.meta_btn.setToolTip(tr("按「首章正文 → 创意描述 → 项目名称」的优先级取材,自动填简介与题材"))
        self.meta_btn.clicked.connect(self._draft_meta)
        mr.addWidget(self.meta_btn)
        mr.addWidget(_muted(tr("简介与题材会作为小说策划 / 分镜 / 画面生成的上下文")))
        mr.addStretch(1)
        _row_full("", meta_row)

        # 写法文风:6 预设 + 自定义(全宽)
        from ..pipeline.novel import NOVEL_STYLES, NOVEL_STYLE_CUSTOM
        self.novel_style = QComboBox()
        self.novel_style.addItem(tr("未选(跟随默认)"), "")
        for name, prompt in NOVEL_STYLES:
            self.novel_style.addItem(tr(name), prompt)
        self.novel_style.addItem(tr("自定义…"), NOVEL_STYLE_CUSTOM)
        _cur = (d["novel_style"] or "").strip()
        _si = self.novel_style.findData(_cur) if _cur else 0
        if _si < 0:
            _si = self.novel_style.findData(NOVEL_STYLE_CUSTOM)
        self.novel_style.setCurrentIndex(_si)
        self.novel_style.currentIndexChanged.connect(self._on_style_pick)
        _row_full(tr("写法文风"), self.novel_style)

        self.novel_style_edit = QPlainTextEdit(_cur)
        self.novel_style_edit.setPlaceholderText(tr("自定义文风:写清句式、节奏、视角与爽点节奏"))
        self.novel_style_edit.setMaximumHeight(56)
        self.novel_style_edit.setVisible(self.novel_style.currentData() == NOVEL_STYLE_CUSTOM)
        self.novel_style_edit.textChanged.connect(self._on_style_text)
        _row_full("", self.novel_style_edit)
        _row_hint_full(tr("预设全文会作为 AI 写正文的「文风」指令;选自定义可自由描述"))

        # 画面比例 | 视觉风格  (两列配对)
        self.aspect = QComboBox()
        for v, label in ASPECTS:
            self.aspect.addItem(label if label == "auto" else tr(label), v)
        i = self.aspect.findData(d["aspect_ratio"])
        self.aspect.setCurrentIndex(i if i >= 0 else 0)
        self.style = QComboBox()
        for r in db.q("SELECT value,name FROM style_presets WHERE is_active=1 ORDER BY sort_order"):
            self.style.addItem(tr(r["name"]), r["value"])
        i = self.style.findData(d["style"])
        self.style.setCurrentIndex(i if i >= 0 else 0)
        _row_pair(tr("aspect_ratio"), self.aspect,
                 tr("visual_style"), self.style)

        # 画风(温画画风) | 内容语言  (两列配对)
        self.comic_style = QComboBox()
        self.comic_style.addItem(tr("未选(跟随默认)"), "")
        for r in db.q("SELECT value,name FROM style_presets WHERE is_active=1 ORDER BY sort_order"):
            self.comic_style.addItem(tr(r["name"]), r["value"])
        self.comic_style.addItem(tr("comic_style_custom"), "__custom__")
        self.language = QComboBox()
        self.language.addItem(tr("跟随全局设置"), "auto")
        for code, name in LANGS:
            self.language.addItem(f"{name} ({code})", code)
        _li = self.language.findData(d["language"] or "auto")
        self.language.setCurrentIndex(_li if _li >= 0 else 0)
        _row_pair(tr("u_comic_style"), self.comic_style,
                 tr("内容语言"), self.language)
        _row_hint_full(tr("本项目的所有漫画资产图与漫画格共用此画风;选自定义可自由描述"))

        # 漫画画风自定义编辑框 — 全宽(展开条件)
        # 顺序很关键:必须**先建 edit、再连信号、最后 setCurrentIndex**。
        # 旧版 connect 写在 edit 之前,setCurrentIndex 同步触发 _on_comic_style_pick
        # → 访问还没建的 self.comic_style_edit → AttributeError;Python 没真崩,
        # 但 Qt 内部态已被搞坏,后续 dialog.show() 段错误,应用退出。
        self.comic_style_edit = QPlainTextEdit(d["comic_style"] or "")
        self.comic_style_edit.setPlaceholderText(tr("自定义画风:写清笔触、线条、色调、氛围"))
        self.comic_style_edit.setMaximumHeight(56)
        self.comic_style.currentIndexChanged.connect(self._on_comic_style_pick)
        self.comic_style_edit.textChanged.connect(self._on_comic_style_text)
        _cur_cs = (d["comic_style"] or "").strip()
        _cs_idx = self.comic_style.findData(_cur_cs) if _cur_cs else 0
        if _cs_idx < 0:
            _cs_idx = self.comic_style.findData("__custom__")
        self.comic_style.setCurrentIndex(_cs_idx if _cs_idx >= 0 else 0)
        self.comic_style_edit.setVisible(self.comic_style.currentData() == "__custom__")
        _row_full("", self.comic_style_edit)

        # 人物面孔文化 | 朗读音色  (两列配对)
        self.ethnicity = QComboBox()
        for v, label in ETHNICITIES:
            self.ethnicity.addItem(label if label == "auto" else tr(label), v)
        i = self.ethnicity.findData(d["ethnicity"])
        self.ethnicity.setCurrentIndex(i if i >= 0 else 0)
        self.tts_gender = QComboBox()
        self.tts_gender.addItem("👩 " + tr("tts_gender_female"), "female")
        self.tts_gender.addItem("👨 " + tr("tts_gender_male"), "male")
        i = self.tts_gender.findData(meta.get("tts_gender", "female"))
        self.tts_gender.setCurrentIndex(i if i >= 0 else 0)
        _row_pair(tr("ethnicity"), self.ethnicity,
                 tr("tts_gender"), self.tts_gender)
        _row_hint_full(tr("tts_gender_hint"))

        # ── 创意描述 / 跳过创意 / 集数(对齐原版 72736af)──
        # 锁定条件是「**已经按这份创意生成出真实文字**」,不是「项目里存在第 1 集」——
        # 新建项目必定会建一个空的第 1 集,按前者判会导致创意描述从创建那一刻就永远改不了。
        self._generated = _has_generated_content(drama_id)
        self.skip_creative = QCheckBox(tr("不需要创意描述 — 我会自己粘贴文章"))
        self.skip_creative.setChecked(bool(d["skip_creative"]))
        self.skip_creative.setDisabled(self._generated)
        f.addWidget(self.skip_creative, row_idx, 0, 1, 4)
        row_idx += 1
        self.creative = QPlainTextEdit(d["creative_description"] or "")
        self.creative.setPlaceholderText(tr("例:女主车祸重生回到高中时代,这一世她要阻止闺蜜嫁给渣男、拿回母亲遗产……"))
        self.creative.setMaximumHeight(72)
        self.creative.setDisabled(self._generated or bool(d["skip_creative"]))
        _row_full(tr("u_creative_desc"), self.creative)
        _row_hint_full(
            tr("creative_locked_hint") if self._generated
            else tr("creative_free_hint"))

        from ..pipeline.novel import POV_LABELS, get_novel_pov
        self.pov_combo = QComboBox()
        for code, desc in POV_LABELS.items():
            self.pov_combo.addItem(tr(desc), code)
        self.pov_combo.setCurrentIndex(self.pov_combo.findData(get_novel_pov(d["id"])))
        self.pov_combo.setToolTip(tr("写章与审校都会按此人称强制校验"))
        self.total_eps = QSpinBox()
        self.total_eps.setRange(1, 999)
        self.total_eps.setValue(int(d["total_episodes"] or 1))
        _row_pair(tr("叙事人称"), self.pov_combo,
                 tr("集数"), self.total_eps)
        _row_hint_full(tr("项目计划产出多少集。设为 1 表示单集完结,「添加一集」将禁用。"))

        self.skip_creative.toggled.connect(
            lambda on: self.creative.setDisabled(on or self._generated))
        root.addLayout(f)
        row = QHBoxLayout()
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        save = W.primary_btn(tr("save"))
        save.clicked.connect(self._save)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        root.addLayout(row)

    def _on_style_pick(self):
        """选预设 → 填进自定义框(留作展示)并隐藏;选「自定义…」→ 展开编辑框。"""
        from ..pipeline.novel import NOVEL_STYLE_CUSTOM
        data = self.novel_style.currentData()
        custom = data == NOVEL_STYLE_CUSTOM
        self.novel_style_edit.setVisible(custom)
        if not custom:
            self.novel_style_edit.blockSignals(True)
            self.novel_style_edit.setPlainText(data or "")
            self.novel_style_edit.blockSignals(False)
        elif not self.novel_style_edit.toPlainText().strip():
            self.novel_style_edit.setFocus()

    def _on_style_text(self):
        """自定义文风编辑:只要内容与某个预设不同,下拉就停在「自定义…」。"""
        from ..pipeline.novel import NOVEL_STYLE_CUSTOM
        text = self.novel_style_edit.toPlainText().strip()
        if text and self.novel_style.findData(text) < 0:
            i = self.novel_style.findData(NOVEL_STYLE_CUSTOM)
            if i >= 0 and self.novel_style.currentIndex() != i:
                self.novel_style.blockSignals(True)
                self.novel_style.setCurrentIndex(i)
                self.novel_style.blockSignals(False)
        self.novel_style_edit.setVisible(True)

    def _on_comic_style_pick(self, _idx=0):
        """温画画风下拉切换:预设 → 实时回填、即时落库;自定义 → 展开编辑框。"""
        data = self.comic_style.currentData()
        custom = data == "__custom__"
        self.comic_style_edit.setVisible(custom)
        if data and not custom:
            # 预设选中 → 把 value 同步到编辑框,立刻写入 DB
            self.comic_style_edit.blockSignals(True)
            self.comic_style_edit.setPlainText(data)
            self.comic_style_edit.blockSignals(False)
            db.ex("UPDATE dramas SET comic_style=?, updated_at=? WHERE id=?",
                  (data, db.now(), self.drama_id))
        elif custom and not self.comic_style_edit.toPlainText().strip():
            self.comic_style_edit.setFocus()

    def _on_comic_style_text(self):
        """温画画风自由编辑:文本脱离当前预设时把下拉拨回「自定义…」,内容实时落库。"""
        text = self.comic_style_edit.toPlainText().strip()
        # 只有 text 不与任何预设吻合时才把下拉拨回「自定义」
        if self.comic_style.findData(text) < 0:
            i = self.comic_style.findData("__custom__")
            if i >= 0 and self.comic_style.currentIndex() != i:
                self.comic_style.blockSignals(True)
                self.comic_style.setCurrentIndex(i)
                self.comic_style.blockSignals(False)
                self.comic_style_edit.setVisible(True)
        db.ex("UPDATE dramas SET comic_style=?, updated_at=? WHERE id=?",
              (text, db.now(), self.drama_id))

    def _draft_meta(self):
        """AI 起草简介与题材(不直接落库,填进输入框由用户确认后保存)。"""
        from ..core.preflight import ensure_ready
        if not ensure_ready("text", None):
            return
        btn = self.meta_btn
        btn.busy(tr("起草中"))

        def job(tid):
            from ..pipeline import book_import
            return book_import.generate_book_meta(
                self.drama_id,
                title=self.title.text().strip(),
                creative=self.creative.toPlainText().strip())

        def done(tid, result, error):
            btn.idle()
            if error:
                err(error)
                return
            if not result:
                err(tr("AI 未返回内容,请重试"))
                return
            if result.get("description"):
                self.intro.setText(str(result["description"]).strip())
            if result.get("genre"):
                self.genre.setText(str(result["genre"]).strip())
            ok(tr("已填入简介与题材,确认无误后点保存"))

        from ..core.taskmgr import TASKMGR
        TASKMGR.submit("prompt", job, done, drama_id=self.drama_id)

    def _save(self):
        from ..pipeline.novel import NOVEL_STYLE_CUSTOM
        d = db.q1("SELECT metadata FROM dramas WHERE id=?", (self.drama_id,))
        meta = db.jload(d["metadata"], {}) if d else {}
        meta["intro"] = self.intro.text().strip()
        meta["genre"] = self.genre.text().strip()
        meta["tts_gender"] = self.tts_gender.currentData() or "female"
        style_data = self.novel_style.currentData()
        novel_style = (self.novel_style_edit.toPlainText().strip()
                       if style_data == NOVEL_STYLE_CUSTOM else (style_data or ""))
        db.ex("""UPDATE dramas SET title=?, aspect_ratio=?, style=?, ethnicity=?, metadata=?,
               creative_description=?, skip_creative=?, total_episodes=?, language=?,
               novel_style=?, updated_at=? WHERE id=?""",
              (self.title.text().strip() or tr("未命名"), self.aspect.currentData(),
               self.style.currentData(), self.ethnicity.currentData(),
               json.dumps(meta, ensure_ascii=False),
               None if self.skip_creative.isChecked() else self.creative.toPlainText().strip(),
               1 if self.skip_creative.isChecked() else 0,
               self.total_eps.value(), self.language.currentData(),
               novel_style, db.now(), self.drama_id))
        # 叙事人称独立字段(存 novel_meta.contract.pov,与小说设定页共用同一数据源)
        from ..pipeline.novel import set_novel_pov
        set_novel_pov(self.drama_id, self.pov_combo.currentData())
        self.accept()


class VideoPreviewDialog(QDialog):
    """视频预览弹窗:QVideoWidget + 播放/暂停 + 进度条(成片/单镜共用)。

    之前成片预览复用 ImageViewerDialog,QPixmap 读不了 mp4,弹出来是灰块。
    """

    def __init__(self, parent, url: str | None, title: str = ""):
        super().__init__(parent)
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget
        from PySide6.QtWidgets import QSlider
        self.setWindowTitle(title or tr("预览"))
        self.resize(560, 500)
        root = QVBoxLayout(self)
        self.vw = QVideoWidget()
        root.addWidget(self.vw, 1)
        ctrl = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(46)
        self.play_btn.clicked.connect(self._toggle)
        ctrl.addWidget(self.play_btn)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(lambda v: self.player.setPosition(v))
        ctrl.addWidget(self.slider, 1)
        self.time_lab = QLabel("0:00 / 0:00")
        self.time_lab.setObjectName("muted")
        ctrl.addWidget(self.time_lab)
        root.addLayout(ctrl)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)      # Qt6 必须显式挂音频输出
        self.player.setVideoOutput(self.vw)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(
            lambda ms: self.slider.setRange(0, max(1, int(ms))))
        from pathlib import Path
        p = config.media_url_to_path(url) if str(url or "").startswith(("/static/", "static/")) else (Path(url) if url else None)
        if p and str(p):
            self.player.setSource(QUrl.fromLocalFile(str(p)))
            self.player.play()

    @staticmethod
    def _fmt(ms: int) -> str:
        s = int(ms // 1000)
        return f"{s // 60}:{s % 60:02d}"

    def _toggle(self):
        from PySide6.QtMultimedia import QMediaPlayer
        st = QMediaPlayer.PlaybackState
        if self.player.playbackState() == st.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_pos(self, ms: int):
        from PySide6.QtMultimedia import QMediaPlayer
        st = QMediaPlayer.PlaybackState
        self.play_btn.setText("⏸" if self.player.playbackState() == st.PlayingState else "▶")
        self.slider.blockSignals(True)
        self.slider.setValue(int(ms))
        self.slider.blockSignals(False)
        self.time_lab.setText(f"{self._fmt(ms)} / {self._fmt(self.player.duration())}")

    def closeEvent(self, ev):
        self.player.stop()
        super().closeEvent(ev)


class AudioPreviewDialog(QDialog):
    """朗读 MP3 内嵌播放(沿用 QMediaPlayer + 播放/暂停 + 进度条)。

    跟 VideoPreviewDialog 一样结构,但没有视频 widget —— 只剩音频控制行。
    用于「朗读本章」完成后直接弹出来播,不让用户跳到系统播放器。
    """

    def __init__(self, parent, url: str | None, title: str = ""):
        super().__init__(parent)
        from PySide6.QtCore import QUrl
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtWidgets import QSlider
        self.setWindowTitle(title or tr("audio_preview"))
        self.resize(560, 130)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        ctrl = QHBoxLayout()
        ctrl.setSpacing(8)
        self.play_btn = QPushButton("⏸")
        self.play_btn.setFixedWidth(40)
        self.play_btn.clicked.connect(self._toggle)
        ctrl.addWidget(self.play_btn)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1)
        self.slider.sliderMoved.connect(lambda v: self.player.setPosition(v))
        ctrl.addWidget(self.slider, 1)
        self.time_lab = QLabel("0:00 / 0:00")
        self.time_lab.setObjectName("muted")
        self.time_lab.setFixedWidth(96)
        ctrl.addWidget(self.time_lab)
        close_btn = QPushButton(tr("close"))
        close_btn.clicked.connect(self.accept)
        ctrl.addWidget(close_btn)
        root.addLayout(ctrl)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(self._on_dur)
        self.player.playbackStateChanged.connect(self._on_state)
        from pathlib import Path
        p = config.media_url_to_path(url) if str(url or "").startswith(("/static/", "static/")) else (Path(url) if url else None)
        if p and str(p):
            self.player.setSource(QUrl.fromLocalFile(str(p)))
            self.player.play()

    def _toggle(self):
        from PySide6.QtMultimedia import QMediaPlayer
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _on_pos(self, ms: int):
        from PySide6.QtMultimedia import QMediaPlayer
        st = QMediaPlayer.PlaybackState
        self.play_btn.setText("⏸" if self.player.playbackState() == st.PlayingState else "▶")
        self.slider.blockSignals(True)
        self.slider.setValue(int(ms))
        self.slider.blockSignals(False)
        self.time_lab.setText(f"{self._fmt(ms)} / {self._fmt(self.player.duration())}")

    def _on_dur(self, ms):
        self.slider.setRange(0, max(1, int(ms)))

    def _on_state(self, state):
        from PySide6.QtMultimedia import QMediaPlayer
        self.play_btn.setText("⏸" if state == QMediaPlayer.PlaybackState.PlayingState else "▶")

    @staticmethod
    def _fmt(ms: int) -> str:
        s = int(ms // 1000)
        return f"{s // 60}:{s % 60:02d}"

    def closeEvent(self, ev):
        self.player.stop()
        super().closeEvent(ev)


class _RemoteImg(QThread):
    """后台取远程图。取完 emit QPixmap 回主线程。"""
    got = Signal(object)

    def __init__(self, url: str, w: int, h: int, parent=None):
        super().__init__(parent)
        self._url, self._w, self._h = url, w, h

    def run(self):
        from PySide6.QtGui import QPixmap as _QP
        try:
            import requests
            r = requests.get(self._url, timeout=20)
            if r.status_code != 200 or not r.content:
                return
            pm = _QP()
            if not pm.loadFromData(r.content):
                return
            dpr = W._ui_dpr() if hasattr(W, "_ui_dpr") else 1.0
            pm = pm.scaled(int(self._w * dpr), int(self._h * dpr),
                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self.got.emit(pm)
        except Exception:  # noqa: BLE001 —— 取图失败不该让预览窗口打不开
            return


class ImageViewerDialog(QDialog):
    """大图查看器(点击图片放大)。

    confirm_text 为 None 时只有「关闭」(原有行为,现有 8 处调用不变);
    传了字符串则额外显示一个确认按钮,点它走 accept() 并置 used=True ——
    搜图弹窗用它实现"先放大看清楚,再决定用不用"。
    """
    def __init__(self, parent, url: str | None, title: str = "",
                 confirm_text: str | None = None,
                 extra_text: str | None = None, on_extra=None,
                 style_choices=None, style_default: str | None = None):
        super().__init__(parent)
        self.used = False
        self._on_extra = on_extra
        self._img_label = None
        self._style_combo = None
        self.setWindowTitle(title or tr("预览"))
        self.resize(760, 620)
        root = QVBoxLayout(self)
        img = QLabel()
        img.setAlignment(Qt.AlignCenter)
        self._img_label = img
        remote = bool(url) and str(url).startswith(("http://", "https://"))
        if remote:
            # 搜图预览传的是远程 URL。**不能**靠 pm.isNull() 判断要不要远程加载 ——
            # pixmap_from_media 对认不出的路径会返回一块**非 null 的灰色占位**,
            # 拿 isNull() 当条件会让这个分支永远进不去,窗口里就只剩灰块(实测踩过)。
            img.setPixmap(W.pixmap_from_media(None, 700, 540))
        else:
            img.setPixmap(W.pixmap_from_media(url, 700, 540))
        # 起线程补一次网络取图;不阻塞主线程 —— 图库响应可能好几秒,
        # 同步下会让窗口"点了没反应"。
        if remote:
            self._th = _RemoteImg(url, 700, 540, self)
            # 注意:这里**不能**在 lambda 里 deleteLater 掉线程对象 ——
            # got 信号正是从它身上 emit 的,一删就把仍在投递的信号链断了,
            # 结果是"线程跑完了但图没贴上",窗口里留一块灰占位(实测踩过)。
            self._th.got.connect(img.setPixmap)
            self._th.finished.connect(self._on_remote_done)
            self._th.start()
        root.addWidget(img, 1)
        close = W.primary_btn(tr("close"))
        close.clicked.connect(self.reject)
        row = QHBoxLayout()
        if extra_text and on_extra:
            ex = QPushButton(extra_text)
            W.set_icon(ex, "magic")
            ex.setToolTip(tr("把这张图转成选定的画风,转完可以直接使用"))
            ex.clicked.connect(self._on_extra_clicked)
            row.addWidget(ex)
            self._btn_extra = ex
            if style_choices:
                # 画风下拉:换画风的目标风格可选。不再死绑「项目默认」——
                # 聊天改图里经常根本没开项目,「项目画风」是空话(用户实测提出)。
                # 预选 style_default(项目画风;没项目时调用方给 3d)。
                self._style_combo = QComboBox()
                for val, lab in style_choices:
                    self._style_combo.addItem(lab, val)
                i = self._style_combo.findData(style_default)
                self._style_combo.setCurrentIndex(i if i >= 0 else 0)
                self._style_combo.setToolTip(tr("换画风的目标风格"))
                row.addWidget(self._style_combo)
        if confirm_text:
            use = W.primary_btn(confirm_text)
            use.clicked.connect(self._on_use)
            row.addWidget(use)
            self._btn_use = use
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)

    def _on_extra_clicked(self):
        if self._on_extra:
            self._on_extra(self)

    def selected_style(self) -> str | None:
        """画风下拉当前选中的 value;没建下拉(非换画风场景)返回 None。"""
        return self._style_combo.currentData() if self._style_combo else None

    def set_busy(self, on: bool, text: str = ""):
        """换画风等长任务的等待效果:图片上盖转圈遮罩 + 文案,只禁用动作按钮。

        **不要** setEnabled(False) 整窗 —— 禁用会让整窗子控件走 disabled 调色板,
        彩色图整体变灰,用户以为生成了黑白(实测反馈)。转换期间照片保持原色。
        """
        for b in (getattr(self, "_btn_extra", None), getattr(self, "_btn_use", None)):
            if b is not None:
                b.setEnabled(not on)
        if on:
            if getattr(self, "_busy_overlay", None) is None:
                from .adjust_worker import BusyOverlay
                self._busy_overlay = BusyOverlay(self._img_label)
                self._busy_overlay.setGeometry(self._img_label.rect())
            self._busy_overlay.start(text or tr("处理中…"))
        elif getattr(self, "_busy_overlay", None) is not None:
            self._busy_overlay.stop()

    def show_local_image(self, path: str):
        """换画风完成后原地刷新显示 —— 避免用户还要自己关窗重开。"""
        if self._img_label is not None:
            self._img_label.setPixmap(W.pixmap_from_media(path, 700, 540))
        th = getattr(self, "_th", None)
        if th is not None and th.isRunning():
            th.quit()
            th.wait(2000)
        self._th = None

    def _on_use(self):
        self.used = True
        self.accept()

    def _on_remote_done(self):
        self._th = None      # 线程自然结束,断开引用让 Qt 回收

    def _stop_thread(self):
        """停掉取图线程。

        `quit()` 对阻塞在 `requests.get` 里的 `run()` **无效**(事件循环根本没
        机会转),必须 `terminate()` 兜底,否则关窗时 QThread 会被带着跑着析构,
        报 "QThread: Destroyed while thread is still running"。
        """
        th = getattr(self, "_th", None)
        if th is not None and th.isRunning():
            th.quit()
            if not th.wait(2000):
                th.terminate()
                th.wait(500)
        self._th = None

    def done(self, r):
        # 「使用这张」/「关闭」走 done() 而不是 closeEvent(),两条路径都要停线程,
        # 否则点完按钮弹窗一关就报线程还在跑。
        self._stop_thread()
        super().done(r)

    def closeEvent(self, e):
        self._stop_thread()
        super().closeEvent(e)


class AssetDetailDialog(QDialog):
    """素材详情编辑(对齐原版):
    左预览(点击放大)+ 右编辑(角色名/角色定位/样貌/妆造 · 场景地点/时间/描述/光影/标签 · 道具名/类型/外貌)
    + 造型变体面板(角色)+ 最终提示词面板(生成/编辑/复制)+ footer(删除/关闭/上传/生成/保存)
    """

    KINDS = {"character": ("characters", tr("chars")), "scene": ("scenes", tr("scenes")), "prop": ("props", tr("props"))}

    def __init__(self, parent, kind: str, row: dict, on_changed=None,
                 drama_id: int | None = None):
        super().__init__(parent)
        # props/characters 两张表不带 drama_id,换画风要靠它取项目当前画风
        self.drama_id = drama_id if drama_id is not None else row.get("drama_id")
        self.kind = kind
        self.table = self.KINDS[kind][0]
        self.row = row
        self._on_changed = on_changed
        self.setWindowTitle(f"{self.KINDS[kind][1]} · {row['name']}")
        self.resize(860, 660)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.addWidget(W.h2(f"{self.KINDS[kind][1]} · {row['name']}"))

        body = QHBoxLayout()
        # 左预览
        left = QVBoxLayout()
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignCenter)
        self.img.setFixedSize(280, 280)
        self.img.setStyleSheet("border:1px solid rgba(128,128,128,60);border-radius:8px;")
        # 优先 image_url(常规 / 3D),没有再回退 comic_image_url —— 与列表卡 CoverBox 同一优先级,
        # 详情页预览就是用户主要使用的常规版(给视频生成当 first_frame)。
        _cover = ((row.get("image_url") or "").strip()
                  or (row.get("comic_image_url") or "").strip())
        self.img.setPixmap(W.pixmap_from_media(_cover, 276, 276))
        # 点击看大图:URL **点击时从库现读**,不能用构造期闭包 —— 生成形象/
        # 改图/换画风/上传都会更新 image_url,闭包里存的地址是旧图(用户实测:
        # 缩略图已是新四格,弹窗还停在旧三格)
        self.img.mousePressEvent = lambda _e: self._view_large_image()
        self.img.setToolTip(tr("点击查看大图"))
        left.addWidget(self.img)
        dl = QPushButton(tr("↓ 下载原图"))
        dl.setToolTip(tr("下载原图到本地,文件名自动使用资产名"))
        dl.clicked.connect(self._download)
        left.addWidget(dl)
        body.addLayout(left)
        # 右编辑
        right = QVBoxLayout()
        f = QFormLayout()
        if kind == "character":
            self.name = QLineEdit(row["name"])
            f.addRow(tr("名称"), self.name)
            self.role = QComboBox()
            for v, label in (("lead", tr("lead")), ("supporting", tr("supporting")), ("extra", tr("extra"))):
                self.role.addItem(label, v)
            i = self.role.findData(row.get("role_type") or "supporting")
            self.role.setCurrentIndex(i if i >= 0 else 1)
            f.addRow(tr("角色定位"), self.role)
            self.appearance = QPlainTextEdit(row.get("appearance") or "")
            f.addRow(tr("appearance"), self.appearance)
            self.styling = QPlainTextEdit(row.get("styling") or "")
            f.addRow(tr("styling"), self.styling)
        elif kind == "scene":
            self.name = QLineEdit(row["name"])
            f.addRow(tr("名称"), self.name)
            self.location = QLineEdit(row.get("location") or "")
            f.addRow(tr("地点"), self.location)
            self.time = QLineEdit(row.get("time") or "")
            f.addRow(tr("时间"), self.time)
            self.desc = QPlainTextEdit(row.get("prompt") or "")
            f.addRow(tr("描述"), self.desc)
            self.lighting = QPlainTextEdit(row.get("lighting") or "")
            f.addRow(tr("lighting"), self.lighting)
            tags = db.jload(row.get("setting_tags"), []) or []
            self.tags = QLineEdit(", ".join(tags))
            self.tags.setPlaceholderText(tr("标签,逗号分隔(如 室内,夜)"))
            f.addRow(tr("标签"), self.tags)
        else:
            self.name = QLineEdit(row["name"])
            f.addRow(tr("名称"), self.name)
            self.ptype = QComboBox()
            for v in ("prop", tr("信物"), tr("文件"), tr("关键道具")):
                self.ptype.addItem(v, v)
            i = self.ptype.findData(row.get("type") or "prop")
            self.ptype.setCurrentIndex(i if i >= 0 else 0)
            f.addRow(tr("类型"), self.ptype)
            self.desc = QPlainTextEdit(row.get("description") or "")
            f.addRow(tr("外貌"), self.desc)
        right.addLayout(f)
        right.addStretch(1)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        # 最终提示词
        fp_box = W.make_card()
        fp_lay = QVBoxLayout(fp_box)
        fp_lay.setContentsMargins(10, 8, 10, 8)
        fp_lay.addWidget(W.h2(tr("final_prompt")))
        self.fp = QPlainTextEdit(row.get("final_prompt") or "")
        self.fp.setMaximumHeight(90)
        self.fp.setPlaceholderText(tr("可手动编辑;或点「AI 生成」自动产出"))
        fp_lay.addWidget(self.fp)
        fp_btns = QHBoxLayout()
        gen_fp = QPushButton(tr("✨ AI 生成"))
        W.set_icon(gen_fp, "magic")
        gen_fp.clicked.connect(self._gen_prompt)
        regen_fp = QPushButton(tr("↻ 重新生成"))
        regen_fp.clicked.connect(self._gen_prompt)
        copy_fp = QPushButton(tr("▤ 复制"))
        copy_fp.clicked.connect(self._copy_prompt)
        for b in (gen_fp, regen_fp, copy_fp):
            fp_btns.addWidget(b)
        fp_btns.addStretch(1)
        fp_lay.addLayout(fp_btns)
        # 生成期间的忙碌反馈留存引用:点了要有"在动了"的观感(用户实测:
        # 点 AI 生成/生成形象界面毫无反应,其实是任务在后台跑或错误被吞)
        self._fp_gen_btns = (gen_fp, regen_fp)
        root.addWidget(fp_box)

        # 角色变体
        if kind == "character":
            var_btn = QPushButton(tr("◑ 造型变体"))
            var_btn.clicked.connect(self._open_variants)
            root.addWidget(var_btn)

        # footer
        footer = QHBoxLayout()
        delete = W.danger_btn(tr("delete"))
        delete.clicked.connect(self._delete)
        footer.addWidget(delete)
        if self.row.get("image_url"):
            edit_btn = QPushButton("🎨 " + tr("改图"))
            W.set_icon(edit_btn, "palette")
            edit_btn.setToolTip(tr("裁剪/旋转/精调/滤镜/水印/尺寸/AI 去背景,保存后写回资产"))
            edit_btn.clicked.connect(self._open_image_edit)
            footer.addWidget(edit_btn)
            erase_btn = QPushButton("🩹 " + tr("擦除"))
            W.set_icon(erase_btn, "edit")
            erase_btn.setToolTip(tr("涂抹要擦掉的区域,程序化填充(线条/地面等结构会自然延续)"))
            erase_btn.clicked.connect(self._erase_region)
            footer.addWidget(erase_btn)
            restore_btn = QPushButton(tr("还原原图"))
            restore_btn.setToolTip(tr("还原到最早擦除前的原图"))
            restore_btn.clicked.connect(self._restore_original)
            footer.addWidget(restore_btn)
            # 换画风:刻意做成手动两步(生成预览 → 看图 → 才替换),不自动落库。
            # 实测图生图会往画面里加原图没有的人物/元素,一键替换会毁掉用户资产。
            conv_btn = QPushButton(tr("换画风"))
            W.set_icon(conv_btn, "magic")
            conv_btn.setToolTip(tr(
                "把现有形象图转成项目画风或指定画风。先生成预览,满意才替换原图。"))
            conv_btn.clicked.connect(self._open_style_convert)
            footer.addWidget(conv_btn)
            # 去背景(换脸边车 rembg /remove;可用性探针决定置灰)
            if self._bg_available():
                bg_btn = QPushButton(tr("去背景"))
                bg_btn.setToolTip(tr("rembg 抠出主体,输出带透明通道的 PNG(不覆盖原图)"))
                bg_btn.clicked.connect(self._bg_remove)
                footer.addWidget(bg_btn)
        footer.addStretch(1)
        upload = QPushButton(tr("upload"))
        upload.clicked.connect(self._upload)
        gen_img = W.primary_btn(tr("◑ 生成形象"))
        gen_img.clicked.connect(self._gen_image)
        self.gen_img_btn = gen_img          # 忙碌反馈用(_gen_image 里切换文案/置灰)
        save = W.primary_btn(tr("save"))
        save.clicked.connect(self._save)
        close = QPushButton(tr("close"))
        close.clicked.connect(self.accept)
        for b in (upload, gen_img, save, close):
            footer.addWidget(b)
        root.addLayout(footer)

    def _open_style_convert(self):
        """打开换画风弹窗。accepted 才写回 image_url —— 用户点「取消」原图不动。"""
        from .style_convert_dialog import StyleConvertDialog
        from .toast import err as _err
        from ..ai import image_client
        from ..pipeline import style_convert as SC

        # 提前拦一道:不支持参考图的 provider 会凭空生成一张无关的图,
        # 与其跑完才发现,不如现在就说清楚(省一次 API 和一次误导)。
        try:
            cfg = image_client.registry.check_ready("image", None)
        except Exception as exc:  # noqa: BLE001
            _err(str(exc)[:160])
            return
        if not image_client.supports_reference_images(cfg["provider"]):
            _err(tr("换画风需要支持参考图的图像模型(agnes/local/comfyui/sdwebui/fooocus),"
                    "当前是「{p}」——请到顶栏切换图像模型").format(p=cfg["provider"]))
            return

        dlg = StyleConvertDialog(self.row["id"], self.table, self.drama_id, parent=self)
        if dlg.exec() == QDialog.Accepted and dlg.result_path:
            SC.apply_result(self.row["id"], self.table, dlg.result_path)
            if self._on_changed:
                self._on_changed()
            self._reload_after_edit()
            self.accept()

    def _open_image_edit(self):
        from .image_edit_dialog import open_image_edit
        open_image_edit(self, self.row["image_url"],
                        target={"type": self.kind, "id": self.row["id"], "kind": "main"},
                        title=f"{tr('改图')} · {self.row['name']}",
                        on_saved=self._reload_after_edit)

    def _bg_available(self) -> bool:
        from ..pipeline import erase as ER
        from ..ai import registry
        try:
            cfg = registry.check_ready("faceswap", None)
        except Exception:  # noqa: BLE001 —— 换脸服务未配置,去背景不可用
            return False
        ok, _ = ER.bg_remove_health(cfg)
        return ok

    def _erase_region(self):
        from .mask_erase_dialog import open_erase_dialog
        open_erase_dialog(self, self.row["image_url"], self.kind, self.row["id"],
                          on_done=self._reload_after_edit, title=self.windowTitle())

    def _restore_original(self):
        from ..pipeline import erase as ER
        from .toast import err, ok
        try:
            ER.restore_original(self.kind, self.row["id"])
            ok(tr("已还原原图"))
            self._reload_after_edit()
        except Exception as e:  # noqa: BLE001
            err(e)

    def _reload_after_edit(self):
        """擦除/还原后刷新详情弹窗里的预览图。"""
        from ..core import db
        row = db.q1(f"SELECT * FROM {self.table} WHERE id=?", (self.row["id"],))
        if row:
            self.row = dict(row)
        self.img.setPixmap(W.pixmap_from_media(self.row.get("image_url"), 280, 280))

    def _bg_remove(self):
        from ..ai import registry
        from ..pipeline import erase as ER
        from .toast import err, ok
        cfg = registry.check_ready("faceswap", None)
        try:
            p = config.media_url_to_path(self.row["image_url"])
            new_path = ER.bg_remove(cfg, p)
            # 结果写回资产(带透明通道的新 PNG),对齐参考 apply_to 语义
            db.ex(f"UPDATE {self.table} SET image_url=?, updated_at=? WHERE id=?",
                  (config.path_to_media_url(new_path), db.now(), self.row["id"]))
            ok(tr("去背景完成"))
            self._reload_after_edit()
        except Exception as e:  # noqa: BLE001
            err(e)

    def _collect(self) -> dict:
        d = {"name": self.name.text().strip() or self.row["name"]}
        if self.kind == "character":
            d.update(role_type=self.role.currentData(),
                     appearance=self.appearance.toPlainText(), styling=self.styling.toPlainText())
        elif self.kind == "scene":
            tags = [t.strip() for t in self.tags.text().split(",") if t.strip()]
            d.update(location=self.location.text().strip(), time=self.time.text().strip(),
                     prompt=self.desc.toPlainText(), lighting=self.lighting.toPlainText(),
                     setting_tags=json.dumps(tags, ensure_ascii=False))
        else:
            d.update(type=self.ptype.currentData(), description=self.desc.toPlainText())
        return d

    def _save(self):
        d = self._collect()
        sets = ",".join(f"{k}=?" for k in d)
        db.ex(f"UPDATE {self.table} SET {sets}, updated_at=? WHERE id=?", (*d.values(), db.now(), self.row["id"]))
        if self._on_changed:
            self._on_changed()
        self.accept()

    def _copy_prompt(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.fp.toPlainText())

    def _gen_prompt(self):
        from ..core.taskmgr import TASKMGR
        from .toast import err, ok
        # 忙碌反馈:置灰两个生成按钮 —— 之前点了毫无动静,用户不知道在跑
        for b in getattr(self, "_fp_gen_btns", ()):
            b.setEnabled(False)
            b.setText(b.text() if "…" in b.text() else b.text() + "…")
        d = db.q1(f"SELECT * FROM {self.table} WHERE id=?", (self.row["id"],))
        merged = {**dict(d), **self._collect()}
        from ..pipeline import prompts_gen
        fn = {"character": prompts_gen.character_prompt, "scene": prompts_gen.scene_prompt,
              "prop": prompts_gen.prop_prompt}[self.kind]
        def job(tid):
            return fn(self.row["id"])
        def done(tid, result, error):
            for b in getattr(self, "_fp_gen_btns", ()):
                b.setEnabled(True)
                b.setText(b.text().replace("…", ""))
            if error:
                err(str(error)[:200])
            else:
                ok(tr("提示词已生成"))
                d2 = db.q1(f"SELECT final_prompt FROM {self.table} WHERE id=?", (self.row["id"],))
                self.fp.setPlainText(d2["final_prompt"] or "")
        TASKMGR.submit("prompt", job, done)

    def _gen_image(self):
        from ..core.taskmgr import TASKMGR
        from .toast import err, ok
        from ..ai import image_client
        # 忙碌反馈:生成要几十秒,按钮不变化用户会连点/以为死了(用户实测)
        btn = getattr(self, "gen_img_btn", None)
        if btn is not None:
            btn.setEnabled(False)
            btn.setText(tr("◑ 生成中…"))
        if TASKMGR.is_busy("image"):
            from .toast import err as _err
            _err("已有图片生成任务在跑,请等它完成后再试")
            return
        def job(tid):
            fp = self.fp.toPlainText() or self.row.get("final_prompt") or ""
            if not fp:
                raise RuntimeError(tr("请先生成最终提示词"))
            # 角色形象图统一白底(共享守卫,见 prompt_guards 白底注释):
            # 风格前缀的 creamy bokeh 会把纯白背景画成彩色虚化、挤掉脸部特写
            from ..ai.prompt_guards import (CHARACTER_SHEET_NEGATIVE,
                                            CHARACTER_SHEET_PROMPT_SUFFIX)
            extra_neg = None
            # 存量脏提示词就地清洗(不用重新 AI 生成):①风格前缀被 LLM 复读
            # 多份(实测 4 份);②旧版兜底块的矛盾短语(no close-up / only
            # three full-body)与中文四格规格打架,实测特写格被丢
            from ..pipeline.prompts_gen import _dedupe_style_prefix, _style_prefix
            did = self.row.get("drama_id")
            if did:
                fp = _dedupe_style_prefix(fp, _style_prefix(did))
            import re as _re
            fp = _re.sub(r"no close-up portraits\s*[,，]\s*no facial zoom-ins\s*[,，]?", "", fp)
            fp = _re.sub(r"only three full-body views( in a horizontal row)?",
                         "exactly four panels in a horizontal row: one front-face "
                         "close-up plus three full-body views", fp)
            fp = _re.sub(r"[,，]{2,}", ", ", fp)
            fp = _re.sub(r"。{2,}", "。", fp)
            # 三视图/turnaround 提示词自含完整构图说明(左特写 + 三全身),必须
            # 跳过人数守卫 —— people=1 公共负面词禁「multiple people/duplicate」,
            # 而三视图本质是同一人的多次出现,模型为守规会砍掉特写那格
            # (用户实测:应四格只出三格,少的正是正面特写)。
            is_sheet = any(k in fp for k in ("三视图", "turnaround", "character sheet"))
            if self.kind == "character":
                if "white background" not in fp.lower():
                    fp = fp + ", clean pure white background, isolated subject"
                fp = fp + CHARACTER_SHEET_PROMPT_SUFFIX
                extra_neg = CHARACTER_SHEET_NEGATIVE
            out, _p = image_client.generate_image(fp, skip_guard=is_sheet,
                                                  extra_negative=extra_neg)
            url = config.path_to_media_url(out)
            db.ex(f"UPDATE {self.table} SET image_url=?, updated_at=? WHERE id=?", (url, db.now(), self.row["id"]))
            return url
        def done(tid, result, error):
            if btn is not None:
                btn.setEnabled(True)
                btn.setText(tr("◑ 生成形象"))
            if error:
                # 之前这里写的是 err(e_) —— e_ 根本不存在,回调自己 NameError,
                # 失败被吞得干干净净,表现为「点生成没反应」
                err(str(error)[:200])
                return
            self.img.setPixmap(W.pixmap_from_media(result, 276, 276))
            ok(tr("形象已生成"))
            if self._on_changed:
                self._on_changed()
        TASKMGR.submit("image", job, done)

    def _upload(self):
        import shutil
        from PySide6.QtWidgets import QFileDialog
        p, _ = QFileDialog.getOpenFileName(self, tr("upload"), "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not p:
            return
        dst = config.STATIC_DIR / "uploads" / f"up_{self.row['id']}_{config.uuid.uuid4().hex[:6]}{p[p.rfind('.'):][:8]}"
        shutil.copy(p, dst)
        url = config.path_to_media_url(dst)
        db.ex(f"UPDATE {self.table} SET image_url=?, updated_at=? WHERE id=?", (url, db.now(), self.row["id"]))
        self.img.setPixmap(W.pixmap_from_media(url, 276, 276))
        if self._on_changed:
            self._on_changed()

    def _view_large_image(self):
        """点击预览图看大图:image_url/comic_image_url **现读库**,保证弹窗
        与缩略图是同一张(生成形象/上传/擦除/换画风之后都不会再拿旧图)。

        本方法属于 AssetDetailDialog —— 第一次修时误插进了 ImageViewerDialog,
        点击时 AttributeError 被事件循环吞掉,弹窗直接弹不出(实测)。
        """
        d = db.q1(f"SELECT image_url, comic_image_url FROM {self.table} WHERE id=?",
                  (self.row["id"],))
        url = ""
        if d:
            url = ((d.get("image_url") or "").strip()
                   or (d.get("comic_image_url") or "").strip())
        if not url:
            return
        ImageViewerDialog(self, url, self.row.get("name") or "").exec()

    def _download(self):
        from ..core import download as dl_mod
        from .toast import err, ok
        try:
            p = dl_mod.download_asset_image(self.row, self.kind)
            ok(tr('已下载:{}').format(p.name))
        except Exception as e:  # noqa: BLE001
            err(str(e))

    def _delete(self):
        if not ask(self, tr("delete"), tr('确定删除「{}」?').format(self.row['name']), danger=True):
            return
        for t in ("episode_characters", "episode_scenes", "episode_props"):
            db.ex(f"DELETE FROM {t} WHERE {self.table[:-1]}_id=?", (self.row["id"],))
        db.ex(f"DELETE FROM {self.table} WHERE id=?", (self.row["id"],))
        if self._on_changed:
            self._on_changed()
        self.accept()

    def _open_variants(self):
        from .variants_dialog import VariantsDialog
        c = db.q1("SELECT * FROM characters WHERE id=?", (self.row["id"],))
        if c:
            VariantsDialog(self, dict(c)).exec()
            if self._on_changed:
                self._on_changed()


class _BindCard(QFrame):
    """单条可选资产卡:缩略/占位 + 名称 + 复选框。

    整卡可点切换勾选(对齐 RefCard 的 star-prop 风格),复选框只是显式标记。
    """

    def __init__(self, row: dict, kind: str, checked: bool, on_toggle=None):
        super().__init__()
        self.setObjectName("bindCard")
        self._checked = checked
        self._on_toggle = on_toggle
        self._row = row                       # _refresh_grids 用:重设勾选时找对应 id
        self._kind = kind
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(3)
        url = (row.get("comic_image_url") or row.get("image_url") or "").strip()
        if url:
            im = QLabel()
            im.setAlignment(Qt.AlignCenter)
            im.setMinimumHeight(70)
            im.setPixmap(W.pixmap_from_media(url, 240, 70))
            im.setScaledContents(True)
            from PySide6.QtWidgets import QSizePolicy
            sp = QSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            sp.setHeightForWidth(True)
            im.setSizePolicy(sp)
            lay.addWidget(im)
        else:
            ph = QLabel({"character": "👤", "scene": "🏞", "prop": "📦"}.get(kind, "▣"))
            ph.setAlignment(Qt.AlignCenter)
            ph.setFixedHeight(80)
            ph.setObjectName("bindThumb")
            lay.addWidget(ph)
        nm = QLabel(str(row.get("name") or ""))
        f = nm.font()
        f.setBold(True)
        nm.setFont(f)
        nm.setWordWrap(True)
        lay.addWidget(nm)
        self.box = QCheckBox()
        self.box.setChecked(bool(checked))
        self.box.setText(tr("bind_to_panel"))
        self.box.toggled.connect(self._emit)
        lay.addWidget(self.box)
        self.setProperty("bound", "1" if checked else "0")
        self.setCursor(Qt.PointingHandCursor)
        self.mousePressEvent = lambda _e: self._toggle()
        # 复选框自己点也会冒泡到卡片,这里拦一下
        self.box.mousePressEvent = lambda e: QCheckBox.mousePressEvent(self.box, e)

    def _toggle(self):
        self.box.setChecked(not self.box.isChecked())

    def _emit(self, v: bool):
        self.setProperty("bound", "1" if v else "0")
        self.style().unpolish(self)
        self.style().polish(self)
        if self._on_toggle:
            self._on_toggle(v)


class ComicPanelBindDialog(QDialog):
    """漫画格手动绑资产:角色(多选)/场景(单选)/道具(多选)。

    来自 split_panels 的自动绑定写入 comic_panel_characters/scenes/props;
    本对话框是手动覆写通道 —— 用户能再勾选/取消,确认后整集替换语义写入
    (「整格重绑」),与 _toggle_ref_bind 风格一致。

    **默认全部自动绑定**(已绑的不动,未绑的全选上),用户不满意再手调;
    顶部「全选 / 全不选」一键切换,不再一个个点。
    """

    def __init__(self, parent, drama_id: int, panel_id: int, on_saved=None):
        super().__init__(parent)
        self.drama_id = drama_id
        self.panel_id = panel_id
        self._on_saved = on_saved
        self.setWindowTitle(tr("bind_panel_assets"))
        self.resize(960, 600)
        # 三段资产先一次性读出
        self._chars = [dict(r) for r in db.q(
            "SELECT id, name, appearance, styling, image_url, comic_image_url "
            "FROM characters WHERE drama_id=? ORDER BY id", (drama_id,))]
        self._scenes = [dict(r) for r in db.q(
            "SELECT id, name, prompt, lighting, image_url, comic_image_url "
            "FROM scenes WHERE drama_id=? ORDER BY id", (drama_id,))]
        self._props = [dict(r) for r in db.q(
            "SELECT id, name, description, image_url, comic_image_url "
            "FROM props WHERE drama_id=? ORDER BY id", (drama_id,))]
        # 当前已绑
        bound_chars = {r["character_id"] for r in db.q(
            "SELECT character_id FROM comic_panel_characters WHERE panel_id=?",
            (panel_id,))}
        bound_scenes = {r["scene_id"] for r in db.q(
            "SELECT scene_id FROM comic_panel_scenes WHERE panel_id=?",
            (panel_id,))}
        bound_props = {r["prop_id"] for r in db.q(
            "SELECT prop_id FROM comic_panel_props WHERE panel_id=?",
            (panel_id,))}
        # **默认全部自动勾选**(已绑的不动 + 未绑的全选上),用户想减再手调。
        # 单独把场景限制在 1 个(单选语义)。
        self._bound_chars = set(c["id"] for c in self._chars)  # ← 全选
        self._bound_props = set(p["id"] for p in self._props)  # ← 全选
        # 场景段(单选语义:每格至多一个主场景;不勾=无主场景)
        self._scene_chosen = bound_scenes.copy()
        if len(self._scene_chosen) > 1:
            # 模型一次给了多个 scene_id 时只保留第一个,其它视为错误残留
            only = next(iter(self._scene_chosen))
            self._scene_chosen = {only}
        # 若无已绑场景且只有 1 个场景 → 自动选这个(最常见的「整集就 1 个场景」)
        if not self._scene_chosen and len(self._scenes) == 1:
            self._scene_chosen = {self._scenes[0]["id"]}

        root = QVBoxLayout(self)
        tip = QLabel(tr("bind_panel_tip"))
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        root.addWidget(tip)

        # 顶部工具条:全选/全不选/分别各段切换 + 变体说明
        tools = QHBoxLayout()
        tools.setSpacing(6)
        all_on = QPushButton("✓ " + tr("bind_all_on"))
        all_on.setObjectName("slateSort")
        all_off = QPushButton("✗ " + tr("bind_all_off"))
        all_off.setObjectName("slateSort")
        all_on.clicked.connect(self._all_on)
        all_off.clicked.connect(self._all_off)
        tools.addWidget(all_on)
        tools.addWidget(all_off)
        tools.addStretch(1)
        hint = QLabel(tr("bind_default_hint"))
        hint.setObjectName("muted")
        tools.addWidget(hint)
        root.addLayout(tools)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QVBoxLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        # 角色段:同时显示主图(常规 / 漫画) + 变体(同角色不同造型)
        grid.addWidget(self._section_label(tr("chars"), f"{len(self._chars)}"))
        grid.addWidget(self._build_char_grid_with_variants())
        grid.addWidget(self._section_label(tr("scenes"), f"{len(self._scenes)}"))
        grid.addWidget(self._build_scene_grid())
        grid.addWidget(self._section_label(tr("props"), f"{len(self._props)}"))
        grid.addWidget(self._build_prop_grid())
        grid.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        row = QHBoxLayout()
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        save = W.primary_btn(tr("save"))
        save.clicked.connect(self._save)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        root.addLayout(row)

    def _all_on(self):
        """一键全选:角色 + 场景(留 1 个)+ 道具全勾上。"""
        self._bound_chars = set(c["id"] for c in self._chars)
        self._bound_props = set(p["id"] for p in self._props)
        if self._scenes and not self._scene_chosen:
            self._scene_chosen = {self._scenes[0]["id"]}
        # 重建 UI 刷新勾选
        self._refresh_grids()

    def _all_off(self):
        """一键全不选。"""
        self._bound_chars.clear()
        self._bound_props.clear()
        self._scene_chosen.clear()
        self._refresh_grids()

    def _refresh_grids(self):
        """重画三个 grid 让勾选状态同步(简单粗暴直接重画,
        后面 _build_* 也得在 __init__ 里走一遍)。"""
        # 拿父 widget 重画就行 —— grid 在 scroll 里的 body 上。
        # 简化处理:就关掉重开对话框也行,这里直接 setVisible + reset。
        # 先实现最小可用版:遍历 _BindCard 实例 setChecked。
        for w in self.findChildren(_BindCard):
            row = getattr(w, "_row", None)
            kind = getattr(w, "_kind", None)
            if not row:
                continue
            if kind == "character":
                w.box.setChecked(row["id"] in self._bound_chars)
            elif kind == "scene":
                w.box.setChecked(row["id"] in self._scene_chosen)
            elif kind == "prop":
                w.box.setChecked(row["id"] in self._bound_props)
            elif kind == "variant":
                # 变体选项独立管理,这里不重画
                pass

    def _section_label(self, name: str, count: str) -> QLabel:
        lb = QLabel(f"{name} · {count}")
        lb.setObjectName("bindSection")
        return lb

    def _build_char_grid(self) -> QWidget:
        wrap = QWidget()
        g = QGridLayout(wrap)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        if not self._chars:
            g.addWidget(QLabel(tr("no_assets_yet")), 0, 0)
            return wrap
        cols = 3
        for i, r in enumerate(self._chars):
            checked = r["id"] in self._bound_chars
            card = _BindCard(r, "character", checked,
                             on_toggle=lambda v, rid=r["id"]: self._toggle_char(rid, v))
            g.addWidget(card, i // cols, i % cols)
        return wrap

    def _build_char_grid_with_variants(self) -> QWidget:
        """角色段:每行一个角色(主图 + 该角色所有变体,横向并排)。"""
        wrap = QWidget()
        g = QVBoxLayout(wrap)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(10)
        if not self._chars:
            g.addWidget(QLabel(tr("no_assets_yet")))
            return wrap
        for r in self._chars:
            # 主图卡
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(0, 0, 0, 0)
            checked = r["id"] in self._bound_chars
            card = _BindCard(r, "character", checked,
                             on_toggle=lambda v, rid=r["id"]: self._toggle_char(rid, v))
            card.setFixedWidth(240)
            row.addWidget(card)
            # 变体卡(若有):同角色不同造型(面具版/老年版/病号版等)→ 供「此刻画风不同」的镜
            vs = db.q("SELECT id, label, image_url, comic_image_url "
                      "FROM character_variants WHERE character_id=? "
                      "AND COALESCE(image_url, comic_image_url)!='' "
                      "ORDER BY sort_order, id", (r["id"],))
            if vs:
                tag = QLabel(f"+ {len(vs)} {tr('variant_label')}")
                tag.setObjectName("muted")
                tag.setStyleSheet("padding-top:18px;")
                row.addWidget(tag, 0, Qt.AlignTop)
                for v in vs:
                    checked_v = False  # 变体默认不勾(避免过多参考图让模型花)
                    vcard = _BindCard(v, "variant", checked_v,
                                      on_toggle=lambda v_, vid=v["id"]: None)
                    vcard.setFixedWidth(140)
                    row.addWidget(vcard)
            g.addLayout(row)
        return wrap

    def _build_scene_grid(self) -> QWidget:
        wrap = QWidget()
        g = QGridLayout(wrap)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        if not self._scenes:
            g.addWidget(QLabel(tr("no_assets_yet")), 0, 0)
            return wrap
        cols = 3
        for i, r in enumerate(self._scenes):
            checked = r["id"] in self._scene_chosen
            card = _BindCard(r, "scene", checked,
                             on_toggle=lambda v, rid=r["id"]: self._toggle_scene(rid, v))
            g.addWidget(card, i // cols, i % cols)
        return wrap

    def _build_prop_grid(self) -> QWidget:
        wrap = QWidget()
        g = QGridLayout(wrap)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(8)
        if not self._props:
            g.addWidget(QLabel(tr("no_assets_yet")), 0, 0)
            return wrap
        cols = 3
        for i, r in enumerate(self._props):
            checked = r["id"] in self._bound_props
            card = _BindCard(r, "prop", checked,
                             on_toggle=lambda v, rid=r["id"]: self._toggle_prop(rid, v))
            g.addWidget(card, i // cols, i % cols)
        return wrap

    def _toggle_char(self, rid: int, on: bool):
        if on:
            self._bound_chars.add(rid)
        else:
            self._bound_chars.discard(rid)

    def _toggle_scene(self, rid: int, on: bool):
        # 单选语义:勾了新场景就清掉旧的
        self._scene_chosen = {rid} if on else set()

    def _toggle_prop(self, rid: int, on: bool):
        if on:
            self._bound_props.add(rid)
        else:
            self._bound_props.discard(rid)

    def _save(self):
        # 写库前再加一道「场景单选」收口:防御 _toggle_scene 状态被外部绕过
        if len(self._scene_chosen) > 1:
            only = next(iter(self._scene_chosen))
            self._scene_chosen = {only}
        db.ex("DELETE FROM comic_panel_characters WHERE panel_id=?", (self.panel_id,))
        db.ex("DELETE FROM comic_panel_scenes WHERE panel_id=?", (self.panel_id,))
        db.ex("DELETE FROM comic_panel_props WHERE panel_id=?", (self.panel_id,))
        for cid in self._bound_chars:
            db.ex("INSERT OR IGNORE INTO comic_panel_characters(panel_id,character_id) VALUES(?,?)",
                  (self.panel_id, int(cid)))
        for sid in self._scene_chosen:
            db.ex("INSERT OR IGNORE INTO comic_panel_scenes(panel_id,scene_id) VALUES(?,?)",
                  (self.panel_id, int(sid)))
        for pid in self._bound_props:
            db.ex("INSERT OR IGNORE INTO comic_panel_props(panel_id,prop_id) VALUES(?,?)",
                  (self.panel_id, int(pid)))
        if self._on_saved:
            self._on_saved()
        self.accept()
