# -*- coding: utf-8 -*-
"""项目设置 + 素材详情编辑弹窗(对齐原版 detail.vue 的项目设置 / 素材详情对话框)。"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget)

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
        self.resize(480, 460)
        root = QVBoxLayout(self)
        root.addWidget(W.h2(tr("project_settings")))
        f = QFormLayout()
        self.title = QLineEdit(d["title"])
        f.addRow(tr("project_name"), self.title)
        meta = db.jload(d["metadata"], {})
        self.intro = QLineEdit(meta.get("intro", ""))
        self.intro.setPlaceholderText(tr("u_whole_placeholder"))
        f.addRow(tr("u_intro"), self.intro)
        self.genre = QLineEdit(meta.get("genre", ""))
        self.genre.setPlaceholderText(tr("u_genre"))
        f.addRow(tr("u_genre"), self.genre)
        # AI 起草简介/题材:素材优先级 = 首章正文 > 创意描述 > 项目名
        meta_row = QWidget()
        mr = QHBoxLayout(meta_row)
        mr.setContentsMargins(0, 0, 0, 0)
        self.meta_btn = WaitingButton(tr("✨ AI 起草简介 / 题材"))
        self.meta_btn.setToolTip(tr("按「首章正文 → 创意描述 → 项目名称」的优先级取材,自动填简介与题材"))
        self.meta_btn.clicked.connect(self._draft_meta)
        mr.addWidget(self.meta_btn)
        mr.addWidget(_muted(tr("简介与题材会作为小说策划 / 分镜 / 画面生成的上下文")))
        mr.addStretch(1)
        f.addRow("", meta_row)
        # 写法文风:6 个预设 + 自定义(对齐原版 episode.vue 的 NOVEL_STYLES)
        from ..pipeline.novel import NOVEL_STYLES, NOVEL_STYLE_CUSTOM
        style_row = QWidget()
        sr = QVBoxLayout(style_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(4)
        sr1 = QHBoxLayout()
        self.novel_style = QComboBox()
        self.novel_style.addItem(tr("未选(跟随默认)"), "")
        for name, prompt in NOVEL_STYLES:
            # 名字走 tr(),提示词保持中文 —— 后者是发给模型的指令,不是界面文案
            self.novel_style.addItem(tr(name), prompt)
        self.novel_style.addItem(tr("自定义…"), NOVEL_STYLE_CUSTOM)
        _cur = (d["novel_style"] or "").strip()
        _si = self.novel_style.findData(_cur) if _cur else 0
        if _si < 0:
            _si = self.novel_style.findData(NOVEL_STYLE_CUSTOM)
        self.novel_style.setCurrentIndex(_si)
        self.novel_style.currentIndexChanged.connect(self._on_style_pick)
        sr1.addWidget(self.novel_style, 1)
        sr.addLayout(sr1)
        self.novel_style_edit = QPlainTextEdit(_cur)
        self.novel_style_edit.setPlaceholderText(tr("自定义文风:写清句式、节奏、视角与爽点节奏"))
        self.novel_style_edit.setMaximumHeight(64)
        self.novel_style_edit.setVisible(
            self.novel_style.currentData() == NOVEL_STYLE_CUSTOM)
        self.novel_style_edit.textChanged.connect(self._on_style_text)
        sr.addWidget(self.novel_style_edit)
        f.addRow(tr("写法文风"), style_row)
        f.addRow("", _muted(tr("预设全文会作为 AI 写正文的「文风」指令;选自定义可自由描述")))
        self.aspect = QComboBox()
        for v, label in ASPECTS:
            self.aspect.addItem(label if label == "auto" else tr(label), v)
        i = self.aspect.findData(d["aspect_ratio"])
        self.aspect.setCurrentIndex(i if i >= 0 else 0)
        f.addRow(tr("aspect_ratio"), self.aspect)
        self.style = QComboBox()
        for r in db.q("SELECT value,name FROM style_presets WHERE is_active=1 ORDER BY sort_order"):
            self.style.addItem(r["name"], r["value"])
        i = self.style.findData(d["style"])
        self.style.setCurrentIndex(i if i >= 0 else 0)
        f.addRow(tr("visual_style"), self.style)
        # 项目级内容语言(对齐原版 a6a47dc:每个项目可固定语言,互不干扰)
        self.language = QComboBox()
        self.language.addItem(tr("跟随全局设置"), "auto")
        for code, name in LANGS:
            self.language.addItem(f"{name} ({code})", code)
        _li = self.language.findData(d["language"] or "auto")
        self.language.setCurrentIndex(_li if _li >= 0 else 0)
        f.addRow(tr("内容语言"), self.language)
        f.addRow("", W.muted(tr("本项目的剧本/资产/分镜等 AI 产出固定使用该语言,不影响其他项目")))
        self.ethnicity = QComboBox()
        for v, label in ETHNICITIES:
            self.ethnicity.addItem(label if label == "auto" else tr(label), v)
        i = self.ethnicity.findData(d["ethnicity"])
        self.ethnicity.setCurrentIndex(i if i >= 0 else 0)
        f.addRow(tr("ethnicity"), self.ethnicity)

        # ── 创意描述 / 跳过创意 / 集数(对齐原版 72736af)──
        # 锁定条件是「**已经按这份创意生成出真实文字**」,不是「项目里存在第 1 集」——
        # 新建项目必定会建一个空的第 1 集,按前者判会导致创意描述从创建那一刻就永远改不了。
        self._generated = _has_generated_content(drama_id)
        self.skip_creative = QCheckBox(tr("不需要创意描述 — 我会自己粘贴文章"))
        self.skip_creative.setChecked(bool(d["skip_creative"]))
        self.skip_creative.setDisabled(self._generated)
        f.addRow("", self.skip_creative)
        self.creative = QPlainTextEdit(d["creative_description"] or "")
        self.creative.setPlaceholderText(tr("例:女主车祸重生回到高中时代,这一世她要阻止闺蜜嫁给渣男、拿回母亲遗产……"))
        self.creative.setMaximumHeight(96)
        self.creative.setDisabled(self._generated or bool(d["skip_creative"]))
        f.addRow(tr("u_creative_desc"), self.creative)
        f.addRow("", W.muted(
            tr("creative_locked_hint") if self._generated
            else tr("creative_free_hint")))
        self.total_eps = QSpinBox()
        self.total_eps.setRange(1, 999)
        self.total_eps.setValue(int(d["total_episodes"] or 1))
        f.addRow(tr("集数"), self.total_eps)
        f.addRow("", W.muted(tr("项目计划产出多少集。设为 1 表示单集完结,「添加一集」将禁用。")))
        self.skip_creative.toggled.connect(
            lambda on: self.creative.setDisabled(on or self._generated))
        root.addLayout(f)
        root.addStretch(1)
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
        self.accept()


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
        self.img.setPixmap(W.pixmap_from_media(row.get("image_url"), 276, 276))
        self.img.mousePressEvent = lambda _e: ImageViewerDialog(self, row.get("image_url"), row["name"]).exec()
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
                err(e_)
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
            ok(f"已下载:{p.name}")
        except Exception as e:  # noqa: BLE001
            err(str(e))

    def _delete(self):
        if not ask(self, tr("delete"), f"确定删除「{self.row['name']}」?", danger=True):
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
