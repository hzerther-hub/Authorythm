# -*- coding: utf-8 -*-
"""项目设置 + 素材详情编辑弹窗(对齐原版 detail.vue 的项目设置 / 素材详情对话框)。"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
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


class ImageViewerDialog(QDialog):
    """大图查看器(点击图片放大)。"""
    def __init__(self, parent, url: str | None, title: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title or tr("预览"))
        self.resize(760, 620)
        root = QVBoxLayout(self)
        img = QLabel()
        img.setAlignment(Qt.AlignCenter)
        img.setPixmap(W.pixmap_from_media(url, 700, 540))
        root.addWidget(img, 1)
        close = W.primary_btn(tr("close"))
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)


class AssetDetailDialog(QDialog):
    """素材详情编辑(对齐原版):
    左预览(点击放大)+ 右编辑(角色名/角色定位/样貌/妆造 · 场景地点/时间/描述/光影/标签 · 道具名/类型/外貌)
    + 造型变体面板(角色)+ 最终提示词面板(生成/编辑/复制)+ footer(删除/关闭/上传/生成/保存)
    """

    KINDS = {"character": ("characters", tr("chars")), "scene": ("scenes", tr("scenes")), "prop": ("props", tr("props"))}

    def __init__(self, parent, kind: str, row: dict, on_changed=None):
        super().__init__(parent)
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
        # 优先 comic_image_url,没有再回退 image_url —— 与列表卡 CoverBox 同一优先级,
        # 否则同名角色「列表显示 comic 单张」「详情显示 3D 三视图」两张图打架
        _cover = ((row.get("comic_image_url") or "").strip()
                  or (row.get("image_url") or "").strip())
        self.img.setPixmap(W.pixmap_from_media(_cover, 276, 276))
        self.img.mousePressEvent = lambda _e: ImageViewerDialog(self, _cover, row["name"]).exec()
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
        save = W.primary_btn(tr("save"))
        save.clicked.connect(self._save)
        close = QPushButton(tr("close"))
        close.clicked.connect(self.accept)
        for b in (upload, gen_img, save, close):
            footer.addWidget(b)
        root.addLayout(footer)

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
        d = db.q1(f"SELECT * FROM {self.table} WHERE id=?", (self.row["id"],))
        merged = {**dict(d), **self._collect()}
        from ..pipeline import prompts_gen
        fn = {"character": prompts_gen.character_prompt, "scene": prompts_gen.scene_prompt,
              "prop": prompts_gen.prop_prompt}[self.kind]
        def job(tid):
            return fn(self.row["id"])
        def done(tid, result, error):
            if error:
                err(error)
            else:
                ok(tr("提示词已生成"))
                d2 = db.q1(f"SELECT final_prompt FROM {self.table} WHERE id=?", (self.row["id"],))
                self.fp.setPlainText(d2["final_prompt"] or "")
        TASKMGR.submit("prompt", job, done)

    def _gen_image(self):
        from ..core.taskmgr import TASKMGR
        from .toast import err
        from ..ai import image_client
        def job(tid):
            fp = self.fp.toPlainText() or self.row.get("final_prompt") or ""
            if not fp:
                raise RuntimeError(tr("请先生成最终提示词"))
            out, _p = image_client.generate_image(fp)
            url = config.path_to_media_url(out)
            db.ex(f"UPDATE {self.table} SET image_url=?, updated_at=? WHERE id=?", (url, db.now(), self.row["id"]))
            return url
        def done(tid, result, error):
            if error:
                err(e_)
            else:
                self.img.setPixmap(W.pixmap_from_media(result, 276, 276))
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
    """

    def __init__(self, parent, drama_id: int, panel_id: int, on_saved=None):
        super().__init__(parent)
        self.drama_id = drama_id
        self.panel_id = panel_id
        self._on_saved = on_saved
        self.setWindowTitle(tr("bind_panel_assets"))
        self.resize(820, 540)
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
        self._bound_chars = bound_chars
        self._bound_scenes = bound_scenes
        self._bound_props = bound_props

        root = QVBoxLayout(self)
        tip = QLabel(tr("bind_panel_tip"))
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        root.addWidget(tip)

        # 场景段(单选语义:每格至多一个主场景;不勾=无主场景)
        self._scene_chosen = bound_scenes.copy()
        if len(self._scene_chosen) > 1:
            # 模型一次给了多个 scene_id 时只保留第一个,其它视为错误残留
            only = next(iter(self._scene_chosen))
            self._scene_chosen = {only}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QVBoxLayout(body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        grid.addWidget(self._section_label(tr("chars"), f"{len(self._chars)}"))
        grid.addWidget(self._build_char_grid())
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
