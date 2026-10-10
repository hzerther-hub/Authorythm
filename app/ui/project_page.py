# -*- coding: utf-8 -*-
"""项目页:剧集列表(改名/状态/分辨率/增删/进入制作)+ 素材库(筛选/详情编辑/添加)。"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QMessageBox, QPushButton, QScrollArea,
                               QTabWidget, QVBoxLayout, QWidget)

from .confirm import ask
from ..core import db
from ..core.i18n import tr
from . import widgets as W
from .toast import err, ok
from .cover_dialog import CoverPanel, EpisodeCoverButton

EP_STAGES = ["novel", "script", "assets", "storyboard", "video"]
_EP_STAGE_LABEL_KEY = {"novel": "正文", "script": "剧本", "assets": "资产",
                       "storyboard": "分镜", "video": "成片"}


def ep_stage_label(stage: str) -> str:
    """阶段名现取 —— 模块级 dict 里写 tr() 会把语言定死在 import 那一刻。"""
    return tr(_EP_STAGE_LABEL_KEY.get(stage, stage))


def ep_stage_index(ep: dict) -> int:
    """按产物判定制作阶段(不依赖手工状态字段,对齐原版 detail.vue)。"""
    if len((ep.get("content") or "").strip()) < 200:
        return 0
    if len((ep.get("script_content") or "").strip()) < 100:
        return 1
    n = int(ep.get("storyboard_count") or 0)
    if n <= 0:
        return 2
    if not (ep.get("video_url") or ""):
        return 3
    return 4


# 状态色固定;标签走 i18n 词典(不能在导入时求值,否则切语言不生效)
STATUS_META = {"pending": "#86909c", "active": "#16a34a", "completed": "#f97316"}
STATUS_KEY = {"pending": "u_pending", "active": "u_running", "completed": "u_done"}


def status_label(status: str) -> str:
    return tr(STATUS_KEY.get(status, "u_pending"))


def _chapter_name_missing(ep: dict) -> bool:
    """标题为空或只有「第N集」占位 = 缺章节名(对齐原版 chapterNameMissing)。"""
    import re
    t = (ep.get("title") or "").strip()
    return (not t) or bool(re.match(r"^第\d+集\s*$", t))


class EpisodeCard(QFrame):
    """集卡(对齐原版 .ep-card):EP 序号 + 可改名标题 + 五段进度 + 元信息 + 状态 + 底部动作。"""

    def __init__(self, ep: dict, is_novel: bool = False, on_changed=None,
                 enter=None, rel_needed=None):
        super().__init__()
        self.ep = ep
        self.episode_id = ep["id"]
        self._is_novel = is_novel
        self._on_changed = on_changed
        self._enter = enter
        self._reload_needed = rel_needed
        self.episode_number = ep["episode_number"]
        self.setObjectName("card")
        self.setMinimumWidth(360)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 10)
        lay.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        num_box = QLabel()
        num_box.setFixedSize(40, 40)
        num_box.setAlignment(Qt.AlignCenter)
        num_box.setStyleSheet(
            "background:#f7f8fa; border:1px solid #e4e7ec; border-radius:10px;"
            "color:#4e5969; font-family:monospace; font-size:15px; font-weight:600;")
        num_box.setText(f"EP{ep['episode_number']:02d}")
        num_box.setToolTip(f"EP{ep['episode_number']:02d}")
        top.addWidget(num_box)

        main = QVBoxLayout()
        main.setSpacing(3)
        self.title_edit = QLineEdit(ep["title"] or tr("episode_n").format(ep["episode_number"]))
        f = self.title_edit.font()
        from PySide6.QtGui import QFont
        f2 = QFont(f)
        f2.setBold(True)
        f2.setPointSize(11)
        self.title_edit.setFont(f2)
        self.title_edit.setStyleSheet("border:none;background:transparent;padding:0;")
        self.title_edit.setToolTip(tr("click_rename"))
        self.title_edit.editingFinished.connect(self._rename)
        self.title_edit.returnPressed.connect(self._rename)
        main.addWidget(self.title_edit)

        # 缺章节名且已有正文 → AI 生成章节名
        if _chapter_name_missing(dict(ep)) and (ep.get("content") or "").strip():
            name_row = QHBoxLayout()
            self.name_btn = QPushButton("✨ " + tr("ai_gen_title"))
            self.name_btn.setToolTip(tr("gen_title_tip"))
            self.name_btn.setStyleSheet(
                "QPushButton{border:1px dashed #f97316;color:#f97316;border-radius:10px;"
                "padding:2px 10px;font-size:11px;background:transparent;}")
            self.name_btn.clicked.connect(lambda: self._gen_chapter_title(ep["id"]))
            name_row.addWidget(self.name_btn)
            name_row.addStretch(1)
            main.addLayout(name_row)

        # 五段进度(小说正文 / 剧本 / 资产 / 分镜 / 成片)
        idx = ep_stage_index(ep)
        stage_row = QHBoxLayout()
        stage_row.setSpacing(5)
        track = QHBoxLayout()
        track.setSpacing(2)
        for i, st in enumerate(EP_STAGES):
            seg = QLabel()
            seg.setFixedSize(12, 3)
            if i < idx:
                seg.setStyleSheet("background:#16a34a;border-radius:2px;")
            elif i == idx:
                seg.setStyleSheet("background:#f97316;border-radius:2px;")
            else:
                seg.setStyleSheet("background:#dfe3e8;border-radius:2px;")
            seg.setToolTip(ep_stage_label(st))
            track.addWidget(seg)
        stage_row.addLayout(track)
        stage_text = QLabel(ep_stage_label(EP_STAGES[idx]))
        stage_text.setStyleSheet("color:#86909c; font-size:10.5px;")
        stage_row.addWidget(stage_text)
        stage_row.addStretch(1)
        main.addLayout(stage_row)

        # 元信息行:字数 / 时长 / 已录入 / 已合成 / 时间
        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        wc = len((ep.get("content") or "").strip())
        tw = ep.get("target_words") or 0
        if wc:
            warn = bool(tw) and wc < int(tw * 0.8)
            wl = QLabel(f"✎ {wc}" + (f" / {tw}" if tw else "") + tr(" 字"))
            wl.setStyleSheet(("color:#e0794b;" if warn else "color:#86909c;")
                             + " font-size:11px;")
        else:
            wl = QLabel(tr("not_written"))
            wl.setObjectName("muted")
        meta_row.addWidget(wl)
        if ep.get("duration"):
            dl = QLabel(f"🕘 {int(ep['duration'])}s")
            dl.setObjectName("muted")
            meta_row.addWidget(dl)
        if ep.get("script_content"):
            sl = QLabel("📄 " + tr("script_entered"))
            sl.setStyleSheet("color:#16a34a; font-size:11px;")
            meta_row.addWidget(sl)
        if ep.get("video_url"):
            vl = QLabel("🎬 " + tr("merged_tag"))
            vl.setStyleSheet("color:#16a34a; font-size:11px;")
            meta_row.addWidget(vl)
        meta_row.addStretch(1)
        tsl = QLabel(_rel_time(ep.get("updated_at")))
        tsl.setObjectName("muted")
        meta_row.addWidget(tsl)
        main.addLayout(meta_row)
        top.addLayout(main, 1)

        self.status_btn = QPushButton()
        self.status_btn.setFixedWidth(72)
        self.status_btn.setCursor(Qt.PointingHandCursor)
        self._apply_status(ep.get("status") or "pending")
        self.status_btn.clicked.connect(self._status_menu)
        top.addWidget(self.status_btn)
        lay.addLayout(top)

        # 底部动作条
        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.res_btn = QPushButton(ep["resolution"] or "720p")
        self.res_btn.setFixedWidth(70)
        self.res_btn.setCursor(Qt.PointingHandCursor)
        self.res_btn.setStyleSheet(
            "QPushButton{background:#f7f8fa;border:none;border-radius:6px;"
            "font-size:11px;font-weight:600;}")
        self.res_btn.setToolTip(tr("res_tip"))
        self.res_btn.clicked.connect(self._res_menu)
        foot.addWidget(self.res_btn)
        n_done = db.q1("SELECT COUNT(*) c FROM storyboards WHERE episode_id=? "
                       "AND COALESCE(video_url,'')!=''", (ep["id"],))["c"]
        n_all = db.q1("SELECT COUNT(*) c FROM storyboards WHERE episode_id=?", (ep["id"],))["c"]
        st = QLabel(f"{n_done}/{n_all}")
        st.setObjectName("muted")
        foot.addWidget(st)
        foot.addStretch(1)
        del_btn = W.danger_btn("🗑 " + tr("delete"))   # 图标+文字,常显危险色(此前纯图标几乎不可见)
        del_btn.setFixedHeight(28)
        del_btn.setToolTip(tr("delete_episode"))
        del_btn.clicked.connect(self._del)
        foot.addWidget(del_btn)
        enter = W.primary_btn(tr("write_novel") if is_novel else tr("enter_production") + " ›")
        enter.setFixedHeight(28)
        enter.clicked.connect(lambda: self._enter(self.episode_id))
        foot.addWidget(enter)
        lay.addLayout(foot)

    def mousePressEvent(self, ev):
        if getattr(self, "_btn_clicked", False):
            self._btn_clicked = False
        else:
            self._enter(self.episode_id)
        super().mousePressEvent(ev)

    def _gen_chapter_title(self, episode_id: int):
        from ..core.taskmgr import TASKMGR

        def job(tid):
            from ..pipeline import novel as novel_pipe
            return novel_pipe.gen_chapter_title(episode_id)

        def done(tid, result, error):
            if error:
                err(error)
                return
            name, src = result
            ok((tr("已提取章节名:") if src == "content" else tr("章节名已写入:")) + str(name))
            if self._reload_needed:
                self._reload_needed.emit()

        TASKMGR.submit("novel_title", job, done, episode_id=episode_id)

    def _rename(self):
        title = self.title_edit.text().strip()
        if title:
            db.ex("UPDATE episodes SET title=?, updated_at=? WHERE id=?",
                  (title, db.now(), self.episode_id))
        else:
            self.title_edit.setText(tr("episode_n").format(self.episode_number))
        self.title_edit.clearFocus()

    def _apply_status(self, status: str):
        label, color = status_label(status), STATUS_META.get(status, STATUS_META["pending"])
        self.status_btn.setText(f"●  {label}")
        self.status_btn.setStyleSheet(
            f"QPushButton{{color:{color};background:#f7f8fa;border:none;"
            f"border-radius:20px;font-size:11px;padding:3px 10px;}}")

    def _status_menu(self):
        m = QMenu(self)
        cur = db.q1("SELECT status FROM episodes WHERE id=?", (self.episode_id,))
        for key in STATUS_META:
            act = m.addAction(("● " if cur and cur["status"] == key else "○ ") + status_label(key))
            act.triggered.connect(lambda _=False, k=key: self._set_status(k))
        m.exec()

    def _set_status(self, status: str):
        db.ex("UPDATE episodes SET status=?, updated_at=? WHERE id=?",
              (status, db.now(), self.episode_id))
        self._apply_status(status)
        ok(f"{tr('status_marked')}: {status_label(status)}")

    def _res_menu(self):
        m = QMenu(self)
        for res, label in (("720p", tr("720p · 高清")), ("480p", tr("480p · 流畅"))):
            m.addAction(label).triggered.connect(lambda _=False, r=res: self._set_res(r))
        m.exec()

    def _set_res(self, res: str):
        db.ex("UPDATE episodes SET resolution=?, updated_at=? WHERE id=?",
              (res, db.now(), self.episode_id))
        self.res_btn.setText(res)

    def _del(self):
        if not ask(self, tr("delete_episode"),
                   f"{tr('episode_n').format(self.episode_number)} → {tr('delete')}?", danger=True):
            return
        for t in ("storyboard_characters", "storyboard_props"):
            db.ex(f"DELETE FROM {t} WHERE storyboard_id IN "
                  "(SELECT id FROM storyboards WHERE episode_id=?)", (self.episode_id,))
        db.ex("DELETE FROM storyboards WHERE episode_id=?", (self.episode_id,))
        db.ex("DELETE FROM comic_panel_characters WHERE panel_id IN "
              "(SELECT id FROM comic_panels WHERE episode_id=?)", (self.episode_id,))
        db.ex("DELETE FROM comic_panels WHERE episode_id=?", (self.episode_id,))
        for t in ("episode_characters", "episode_scenes", "episode_props"):
            db.ex(f"DELETE FROM {t} WHERE episode_id=?", (self.episode_id,))
        db.ex("DELETE FROM video_merges WHERE episode_id=?", (self.episode_id,))
        db.ex("DELETE FROM episodes WHERE id=?", (self.episode_id,))
        from ..core.taskmgr import TASKMGR
        TASKMGR.updated.emit()
        if self._on_changed:
            self._on_changed()


def _rel_time(ts: str) -> str:
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:  # noqa: BLE001
        return ts[:16]
    if secs < 60:
        return tr("刚刚")
    if secs < 3600:
        return tr('{} 分钟前').format(int(secs // 60))
    if secs < 86400:
        return tr('{} 小时前').format(int(secs // 3600))
    return f"{dt.month}/{dt.day}"


class AddEpisodeCard(QFrame):
    """网格末尾的「添加第 N 集」占位卡(对齐 .card.ep-empty)。"""

    def __init__(self, number: int, on_click):
        super().__init__()
        self.setObjectName("card")
        self.setMinimumWidth(360)
        self.setMinimumHeight(104)
        self.setCursor(Qt.PointingHandCursor)
        self._on_click = on_click
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        lay.addStretch(1)
        icon = QLabel("+")
        icon.setFixedSize(28, 28)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet("background:#f7f8fa; border-radius:14px; color:#86909c;"
                           "font-size:16px; border:1px solid #e4e7ec;")
        lay.addWidget(icon)
        text = QLabel(tr("add_episode_n", number))
        text.setStyleSheet("color:#86909c; font-size:12.5px; border:none;")
        lay.addWidget(text)
        lay.addStretch(1)

    def mousePressEvent(self, ev):
        self._on_click()
        super().mousePressEvent(ev)


class NewEpisodeDialog(QDialog):
    """新建一集:标题 + 分辨率 + 锁定说明。"""

    def __init__(self, parent, number: int):
        super().__init__(parent)
        self.setWindowTitle(tr("add_episode"))
        self.resize(400, 240)
        f = QFormLayout()
        outer = QVBoxLayout(self)
        self.title = QLineEdit(tr("episode_n").format(number))
        self.title.setPlaceholderText("例如:第 2 集 · 归乡")
        f.addRow(tr("标题"), self.title)
        self.res = QComboBox()
        for r in ("480p", "720p", "1080p"):
            self.res.addItem(r)
        self.res.setCurrentText("720p")
        f.addRow(tr("分辨率"), self.res)
        f.addRow("", W.muted(tr("创建后可在剧集卡上随时修改标题、状态与分辨率。")))
        outer.addLayout(f)
        row = QHBoxLayout()
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        save = W.primary_btn(tr("add_episode"))
        save.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        outer.addLayout(row)

    def data(self):
        return {"title": self.title.text().strip() or tr("episode_n").format(0), "resolution": self.res.currentText()}


class AddAssetDialog(QDialog):
    """＋ 添加资产:角色/场景/道具。"""

    def __init__(self, parent, drama_id: int, kind: str):
        super().__init__(parent)
        self.drama_id, self.kind = drama_id, kind
        label = {"character": "角色", "scene": "场景", "prop": "道具"}[kind]
        self.setWindowTitle(tr('＋ 添加{}').format(label))
        self.resize(440, 340)
        f = QFormLayout()
        outer = QVBoxLayout(self)
        outer.addLayout(f)
        self.name = QLineEdit()
        f.addRow(tr("名称"), self.name)
        self.role = QComboBox()
        for v, l in (("lead", tr("lead")), ("supporting", tr("supporting")), ("extra", tr("extra"))):
            self.role.addItem(l, v)
        self.desc = QLineEdit()
        self.time = QLineEdit()
        if kind == "character":
            f.addRow(tr("角色定位"), self.role)
            f.addRow(tr("appearance"), self.desc)
            f.addRow(tr("styling"), self.time)
        elif kind == "scene":
            f.addRow(tr("地点"), self.desc)
            f.addRow(tr("时间"), self.time)
        else:
            f.addRow(tr("外貌"), self.desc)
        row = QHBoxLayout()
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        save = W.primary_btn(tr("add"))
        save.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(save)
        outer.addLayout(row)

    def save(self):
        ts = db.now()
        name = self.name.text().strip()
        if not name:
            return
        if self.kind == "character":
            db.ex("INSERT INTO characters(drama_id,name,role_type,appearance,styling,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                  (self.drama_id, name, self.role.currentData(), self.desc.text().strip(), self.time.text().strip(), ts, ts))
        elif self.kind == "scene":
            db.ex("INSERT INTO scenes(drama_id,name,location,time,prompt,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                  (self.drama_id, name, self.desc.text().strip(), self.time.text().strip(), "", ts, ts))
        else:
            db.ex("INSERT INTO props(drama_id,name,type,description,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                  (self.drama_id, name, "prop", self.desc.text().strip(), ts, ts))


class AssetCard(QFrame):
    """素材卡:点击打开详情编辑。"""
    def __init__(self, kind: str, row: dict, on_open):
        super().__init__()
        self.setObjectName("card")
        self.setFixedSize(210, 210)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        img = QLabel()
        img.setFixedHeight(96)
        img.setAlignment(Qt.AlignCenter)
        img.setPixmap(W.pixmap_from_media(row["image_url"] or row.get("comic_image_url"), 190, 96))
        lay.addWidget(img)
        name = W.h2(row["name"])
        lay.addWidget(name)
        role = {"lead": tr("lead"), "supporting": tr("supporting"), "extra": tr("extra")}.get(row.get("role_type"), row.get("type") or "")
        chips = QHBoxLayout()
        chips.addWidget(W.tag(role))
        if row["image_url"] or row.get("comic_image_url"):
            chips.addWidget(W.tag(tr("generated")))
        chips.addStretch(1)
        lay.addLayout(chips)
        desc = QLabel((row.get("appearance") or row.get("prompt") or row.get("description") or "")[:50] + "…")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        lay.addWidget(desc)

    def mousePressEvent(self, e):
        import functools
        # 由外部连接点击
        if getattr(self, "_on_click", None):
            self._on_click()
        super().mousePressEvent(e)


class PromoDialog(QDialog):
    """宣传文案:平台 + 格式 + 补充说明 → 生成 → 结果可复制。"""

    def __init__(self, parent, drama_id: int):
        super().__init__(parent)
        self.drama_id = drama_id
        from ..pipeline import promo as promo_pipe
        self.setWindowTitle(tr("promo_copy"))
        self.resize(560, 520)
        root = QVBoxLayout(self)
        root.addWidget(W.h2(tr("promo_copy")))
        f = QFormLayout()
        self.platform = QComboBox()
        for v, n in promo_pipe.PLATFORMS:
            self.platform.addItem(n, v)
        f.addRow(tr("target_platform"), self.platform)
        self.fmt = QComboBox()
        for v, n in promo_pipe.FORMATS:
            self.fmt.addItem(n, v)
        f.addRow(tr("output_format"), self.fmt)
        self.extra = QLineEdit()
        self.extra.setPlaceholderText(tr("补充说明(可选),如 突出性价比"))
        f.addRow(tr("补充"), self.extra)
        root.addLayout(f)
        self.gen_btn = W.primary_btn(tr("✨ 生成文案"))
        self.gen_btn.clicked.connect(self._gen)
        root.addWidget(self.gen_btn)
        self.result = QLineEdit()
        self.result.setReadOnly(True)
        root.addWidget(W.muted(tr("标题")))
        root.addWidget(self.result)
        self.body = QLineEdit()
        self.body.setReadOnly(True)
        root.addWidget(W.muted(tr("正文")))
        root.addWidget(self.body)
        copy_btn = QPushButton(tr("▤ 复制全文"))
        copy_btn.clicked.connect(self._copy)
        row = QHBoxLayout()
        row.addWidget(copy_btn)
        row.addStretch(1)
        close = QPushButton(tr("close"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        root.addLayout(row)

    def _gen(self):
        from ..core.taskmgr import TASKMGR
        pv, fv = self.platform.currentData(), self.fmt.currentData()
        extra = self.extra.text().strip()
        from ..pipeline import promo as promo_pipe
        def job(tid):
            return promo_pipe.generate_promo(self.drama_id, pv, fv, extra=extra)
        def done(tid, result, e):
            if e:
                err(e)
                return
            self.result.setText(result.get("title", ""))
            self.body.setText(result.get("body", ""))
        TASKMGR.submit("promo", job, done, drama_id=self.drama_id)

    def _copy(self):
        from PySide6.QtWidgets import QApplication
        text = f"{self.result.text()}\n\n{self.body.text()}"
        QApplication.clipboard().setText(text)
        ok(tr("已复制到剪贴板"))


class ProjectPage(QWidget):
    enter_episode = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.drama_id = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        head_card = QFrame()
        head_card.setObjectName("card")
        head = QHBoxLayout(head_card)
        head.setContentsMargins(16, 10, 16, 10)
        head.setSpacing(12)
        back = QPushButton("← " + tr("back"))
        back.setFixedSize(30, 30)
        back.setStyleSheet("QPushButton{background:#f7f8fa;border:none;border-radius:15px;"
                           "color:#4e5969;}")
        back.clicked.connect(self._go_back)
        self.title = W.h1("")
        self.title.setStyleSheet("font-size:17px; font-weight:700;")
        head_info = QVBoxLayout()
        head_info.setSpacing(3)
        top_line = QHBoxLayout()
        top_line.setSpacing(8)
        top_line.addWidget(self.title)
        self.style_tag = W.tag("")
        self.style_tag.setStyleSheet("background:#fdf0e6; color:#f97316; border-radius:4px;"
                                     "padding:2px 8px; font-size:12px;")
        top_line.addWidget(self.style_tag)
        self.imit_tag = W.tag(tr("imitated"))
        self.imit_tag.setStyleSheet(
            "background:rgba(168,85,247,0.08); color:#a855f7;"
            "border:1px solid rgba(168,85,247,0.45); border-radius:4px;"
            "padding:2px 8px; font-size:12px;")
        top_line.addWidget(self.imit_tag)
        top_line.addStretch(1)
        head_info.addLayout(top_line)
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        head_info.addWidget(self.sub)
        head.addWidget(back)
        head.addLayout(head_info, 1)
        self.settings_btn = QPushButton("⚙ " + tr("project_settings"))
        self.settings_btn.clicked.connect(self._open_settings)
        head.addWidget(self.settings_btn)
        self.promo_btn = QPushButton("◈ " + tr("promo_copy"))
        self.promo_btn.clicked.connect(self._promo)
        head.addWidget(self.promo_btn)
        # 策划与设定入口(从制作台原文页移到这里,策划是项目级的事,不该藏在单集页里)
        self.novel_btn = QPushButton("⚙ " + tr("novel_settings"))
        self.novel_btn.setToolTip(tr("novel_settings_tip"))
        self.novel_btn.clicked.connect(self._open_novel_settings)
        head.addWidget(self.novel_btn)
        self.book_btn = QPushButton("▤ " + tr("import_book"))
        self.book_btn.setToolTip(tr("导入整本 TXT → 结构分析 → 依样仿写(新建项目)"))
        self.book_btn.clicked.connect(self._book_import)
        head.addWidget(self.book_btn)
        root.addWidget(head_card)
        self.head_card = head_card

        # 项目封面区在 load() 中按 drama_id 构建
        self.cover_holder = QWidget()
        self.cover_holder.setLayout(QVBoxLayout())
        root.addWidget(self.cover_holder)

        self.tabs = QTabWidget()
        ep_holder = QWidget()
        self.ep_lay = QVBoxLayout(ep_holder)
        self.ep_lay.setContentsMargins(0, 10, 0, 10)
        self.ep_lay.setSpacing(12)
        # 集卡网格常驻:reload 只清这个 grid 的条目。
        # (若每次 reload 新建嵌套 QGridLayout 再塞进 ep_lay,ep_lay.takeAt() 取不到嵌套布局里的
        #  卡片——它们已被重新挂到父控件上,旧卡片会留在界面上,表现为重复的「添加第 N 集」)
        self.ep_grid = QGridLayout()
        self.ep_grid.setContentsMargins(0, 0, 0, 0)
        self.ep_grid.setSpacing(10)
        self.ep_lay.addLayout(self.ep_grid)
        self.ep_hint = W.muted("")
        self.ep_hint.setVisible(False)
        self.ep_lay.addWidget(self.ep_hint)
        self.ep_lay.addStretch(1)
        self.ep_scroll = QScrollArea()
        self.ep_scroll.setWidgetResizable(True)
        self.ep_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.ep_scroll.setWidget(ep_holder)
        self.tabs.addTab(self.ep_scroll, tr("episodes"))
        lib_holder = QWidget()
        lib_root = QVBoxLayout(lib_holder)
        lib_bar = QHBoxLayout()
        self.lib_filter = QComboBox()
        for key, label in [("all", tr("filter_all")), ("chars", tr("chars")), ("scenes", tr("scenes")), ("props", tr("props"))]:
            self.lib_filter.addItem(label, key)
        self.lib_filter.currentIndexChanged.connect(self.reload)
        lib_bar.addWidget(self.lib_filter)
        self.add_char = QPushButton(tr("＋ 角色"))
        self.add_char.clicked.connect(lambda: self._add_asset("character"))
        self.add_scene = QPushButton(tr("＋ 场景"))
        self.add_scene.clicked.connect(lambda: self._add_asset("scene"))
        self.add_prop = QPushButton(tr("＋ 道具"))
        self.add_prop.clicked.connect(lambda: self._add_asset("prop"))
        for b in (self.add_char, self.add_scene, self.add_prop):
            lib_bar.addWidget(b)
        lib_bar.addStretch(1)
        lib_root.addLayout(lib_bar)
        self.lib_scroll = QScrollArea()
        self.lib_scroll.setWidgetResizable(True)
        self.lib_scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.lib_grid_holder = QWidget()
        self.lib_grid = QGridLayout(self.lib_grid_holder)
        self.lib_grid.setSpacing(12)
        self.lib_scroll.setWidget(self.lib_grid_holder)
        lib_root.addWidget(self.lib_scroll, 1)
        self.tabs.addTab(lib_holder, tr("asset_library"))
        root.addWidget(self.tabs, 1)

        self._back_cb = None
        self._enter_cb = None
        self._promo_cb = None

    def set_callbacks(self, back_cb, enter_cb, promo_cb=None):
        self._back_cb = back_cb
        self._enter_cb = enter_cb
        self._promo_cb = promo_cb

    def _go_back(self):
        if self._back_cb:
            self._back_cb()

    def _promo(self):
        PromoDialog(self, self.drama_id).exec()

    def _open_novel_settings(self):
        """打开小说策划与设定(总纲/世界观/合约/卷战略/章节计划/主要角色)。"""
        from .novel_dialogs import NovelPlanDialog
        NovelPlanDialog(self, self.drama_id).exec()
        self.reload()

    def _book_import(self):
        from .book_import_dialog import BookImportDialog
        BookImportDialog(self, self.drama_id).exec()

    def load(self, drama_id: int):
        self.drama_id = drama_id
        d = db.q1("SELECT * FROM dramas WHERE id=?", (drama_id,))
        if not d:
            return
        self._drama = dict(d)
        self.title.setText(d["title"])
        nc = db.q1("SELECT COUNT(*) c FROM characters WHERE drama_id=?", (drama_id,))["c"]
        ns = db.q1("SELECT COUNT(*) c FROM scenes WHERE drama_id=?", (drama_id,))["c"]
        ne = db.q1("SELECT COUNT(*) c FROM episodes WHERE drama_id=?", (drama_id,))["c"]
        style = db.q1("SELECT name FROM style_presets WHERE value=?", (d["style"],))
        self.style_tag.setText(style["name"] if style else "")
        self.style_tag.setVisible(bool(style))
        nm = db.jload(d["novel_meta"], {}) or {}
        src = nm.get("imitated_from") or {}
        self.imit_tag.setVisible(bool(src.get("drama_id")))
        if src.get("source_title"):
            self.imit_tag.setText(tr("source_book", src["source_title"]))
        self.sub.setText(f"👤 {tr('characters_n', nc)}   🖼 {tr('scenes_n', ns)}   "
                          f"🎞 {tr('episodes_n', ne)}")
        # 项目封面区(3:4 竖版 + 提示词 + 生成 + 放大预览)
        ch = self.cover_holder.layout()
        while ch.count():
            item = ch.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        ch.addWidget(CoverPanel(drama_id, on_changed=self.reload))
        self.reload()

    def _open_settings(self):
        from .asset_dialogs import ProjectSettingsDialog
        if ProjectSettingsDialog(self, self.drama_id).exec() == QDialog.Accepted:
            self.load(self.drama_id)
            ok(tr("项目设置已保存"))

    def can_add_episode(self) -> bool:
        """集数限制(对齐原版 canAddEpisode):未配置→不限制;集数=1→单集完结;已达总数→禁止。"""
        d = db.q1("SELECT total_episodes FROM dramas WHERE id=?", (self.drama_id,))
        target = (d["total_episodes"] if d else None)
        if not target or int(target) <= 0:
            return True
        current = db.q1("SELECT COUNT(*) c FROM episodes WHERE drama_id=?", (self.drama_id,))["c"]
        if int(target) == 1:
            return False
        return current < int(target)

    def _ep_cols(self) -> int:
        """集卡列数:按实际可用宽度算(窗口窄时先建一列,resize 后重排)。"""
        avail = max(self.ep_scroll.viewport().width(), self.width() - 120)
        return max(1, avail // 380)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if getattr(self, "drama_id", 0):
            self.reload()

    def reload(self):
        # setParent(None) 立即摘除;deleteLater 在这里不生效 —— 旧卡片仍挂在父控件上,
        # 表现为多出一张重复的「添加第 N 集」。
        while self.ep_grid.count():
            item = self.ep_grid.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        rows = db.q("SELECT * FROM episodes WHERE drama_id=? ORDER BY episode_number", (self.drama_id,))
        counts = {r["episode_id"]: r["c"] for r in db.q(
            "SELECT episode_id, COUNT(*) c FROM storyboards GROUP BY episode_id")}
        is_novel = self._drama["work_type"] == "novel" if self._drama else False
        cells = list(rows)
        if self.can_add_episode():
            cells = list(rows) + [None]           # 末尾放「添加第 N 集」占位卡
        cols = self._ep_cols()
        grid = self.ep_grid
        for i, ep in enumerate(cells):
            if ep is None:
                grid.addWidget(AddEpisodeCard(rows[-1]["episode_number"] + 1 if rows else 1,
                                              self._add_episode), i // cols, i % cols)
                continue
            d = dict(ep)
            d["storyboard_count"] = counts.get(ep["id"], 0)
            grid.addWidget(EpisodeCard(d, is_novel=is_novel, on_changed=self.reload,
                                       enter=self._on_enter, rel_needed=self),
                           i // cols, i % cols)
        self.ep_hint.setText("" if self.can_add_episode() else tr("ep_limit_hint"))
        self.ep_hint.setVisible(not self.can_add_episode())
        while self.lib_grid.count():
            item = self.lib_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        f = self.lib_filter.currentData() or "all"
        items = []
        if f in ("all", "chars"):
            items += [("character", dict(r)) for r in db.q("SELECT * FROM characters WHERE drama_id=? ORDER BY id", (self.drama_id,))]
        if f in ("all", "scenes"):
            items += [("scene", dict(r)) for r in db.q("SELECT * FROM scenes WHERE drama_id=? ORDER BY id", (self.drama_id,))]
        if f in ("all", "props"):
            items += [("prop", dict(r)) for r in db.q("SELECT * FROM props WHERE drama_id=? ORDER BY id", (self.drama_id,))]
        cols = max(1, self.lib_grid_holder.width() // 230 or 4)
        for i, (kind, row) in enumerate(items):
            card = AssetCard(kind, row, None)
            card._on_click = lambda k=kind, r=row: self._open_asset(k, r)
            self.lib_grid.addWidget(card, i // cols, i % cols)
        if not items:
            empty = QLabel(tr("暂无素材"))
            empty.setObjectName("muted")
            empty.setAlignment(Qt.AlignCenter)
            self.lib_grid.addWidget(empty, 0, 0)

    def _open_asset(self, kind: str, row: dict):
        from .asset_dialogs import AssetDetailDialog
        AssetDetailDialog(self, kind, row, on_changed=self.reload).exec()
        self.reload()

    def _add_asset(self, kind: str):
        dlg = AddAssetDialog(self, self.drama_id, kind)
        if dlg.exec() == QDialog.Accepted:
            dlg.save()
            self.reload()
            ok(tr("已添加"))

    def _add_episode(self):
        n = (db.q1("SELECT MAX(episode_number) m FROM episodes WHERE drama_id=?", (self.drama_id,))["m"] or 0) + 1
        dlg = NewEpisodeDialog(self, n)
        if dlg.exec() != QDialog.Accepted:
            return
        data = dlg.data()
        ts = db.now()
        db.ex("INSERT INTO episodes(drama_id,episode_number,title,status,resolution,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
              (self.drama_id, n, data["title"], "pending", data["resolution"], ts, ts))
        self.reload()

    def _on_enter(self, episode_id: int):
        if self._enter_cb:
            self._enter_cb(self.drama_id, episode_id)
