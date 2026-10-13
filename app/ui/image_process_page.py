# -*- coding: utf-8 -*-
"""图片处理(AI 改图)页:选素材 → 输入指令 → 批量出图到输出目录。

与 ImageEditDialog 的分工:那个是**手动编辑器**(裁剪/调色/滤镜/水印/去背景,
全是 PIL 确定性操作);这里是**指令驱动**的 AI 改图 —— 「去掉图片上的人物」
「把图里的中文换成英文」这类语义修改,走图生图(原图作参考图 + 指令作提示词)。

素材来源支持三种:本地多选图片、本地目录(递归扫描)、远程图片 URL。
处理结果全部落到输出目录,不覆盖原图。
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ..ai import image_client
from ..ai import registry
from ..core import config, db
from ..core.i18n import tr
from ..core import taskmgr as _TM
from ..core.taskmgr import TASKMGR
from . import widgets as W
from .braille import WaitingButton
from .toast import err, ok, warn

IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

# 单批处理上限。串行逐张调用图像模型,一张几十秒;不设限的话误选一个大目录
# 就会跑几十分钟,用户只能干等。超出的直接拒绝并提示,而不是闷头跑。
MAX_BATCH = 20


def build_edit_prompt(instr: str, people: int = 1) -> str:
    """把用户的一条指令扩写成「受约束的编辑」提示词。

    只把原指令原样发过去,图生图模型会把它当成「照着参考图重新创作一张」——
    实测「去掉图片上的文字」出来的是另一个人物(女人变男人),因为提示词里
    没有任何东西告诉它其余部分必须保持不变。所以必须显式写死不变量。
    """
    who = {0: "画面中不要出现任何人物",
           1: "画面中恰好 1 个人物",
           2: "画面中恰好 2 个人物",
           3: "画面中恰好 3 个人物"}.get(people, f"画面中约 {people} 个人物")
    solo = {0: "no people, empty scene",
            1: "solo, 1girl, alone, single subject, clean background",
            2: "2 people only, no extras, clean background",
            3: "3 people only, no extras, clean background"}.get(
        people, f"{people} people only, no extras, clean background")
    return (
        f"【编辑任务】{instr}\n\n"
        "【必须保持不变】以原图作为唯一事实来源,严格保持:画面构图与视角、人物的"
        "身份与性别年龄、五官与发型、体态姿态、服装与配饰、背景与陈设、光线方向、"
        "色调与整体风格。\n"
        f"【人物】{who};{solo}。\n"
        "【背景规则】大面积纯色或平坦区域保持原本的纯色,不要在空白处脑补人群、"
        "观众、路人或任何人脸;不要新增任何原图中不存在的元素。\n"
        "【禁止】不要重新创作画面,不要替换人物,不要改变性别,不要重新配色或换背景。\n"
        "只输出与原图一致、仅完成上述修改的画面。"
    )


# 改图场景专用负面词:压制"凭空多出来的人"。不进全局守卫 —— 全局加 "men" 会在
# 生成男性角色时误伤,所以只在这个页面 opt-in 追加。
EDIT_NEGATIVE = ("extra people, additional people, background characters, bystanders, "
                 "onlookers, crowd, audience, ghost, transparent figure, blurry face in "
                 "background, extra heads, duplicated person")


class ImageProcessPage(QWidget):
    """AI 改图工作台。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sources: list[str] = []          # 本地路径 / 远程 URL 混合
        self._busy = False
        self._src_widgets: list = []           # 处理中要禁用的来源控件(_build 里登记)
        self._build()
        self._reload_models()
        self._reset_output_dir()

    # ── 界面 ──
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(10)

        # 顶部:标题 + 文本模型 / 图像模型(对齐剧集页顶栏的写法)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = W.h2(tr("image_process"))
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(QLabel(tr("text_svc") + ":"))
        self.text_model = self._mk_combo()
        top.addWidget(self.text_model)
        top.addWidget(QLabel(tr("image_svc") + ":"))
        self.image_model = self._mk_combo()
        self.image_model.setToolTip(tr("image_model_ref_tip"))
        self.image_model.currentIndexChanged.connect(self._on_image_model_changed)
        top.addWidget(self.image_model)
        root.addLayout(top)

        # 来源
        src_card = W.make_card()
        sl = QVBoxLayout(src_card)
        sl.setContentsMargins(12, 10, 12, 10)
        sl.setSpacing(8)
        sl.addWidget(self._section(tr("source_images")))
        row = QHBoxLayout()
        row.setSpacing(6)
        b1 = QPushButton(tr("pick_local_images"))
        b1.clicked.connect(self._pick_files)
        b2 = QPushButton(tr("pick_local_dir"))
        b2.clicked.connect(self._pick_dir)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch(1)
        self._src_widgets.extend([b1, b2])
        self.clear_btn = QPushButton(tr("clear_all"))
        self.clear_btn.clicked.connect(self._clear)
        row.addWidget(self.clear_btn)
        sl.addLayout(row)

        url_row = QHBoxLayout()
        url_row.setSpacing(6)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(tr("remote_url_hint"))
        self.url_edit.returnPressed.connect(self._add_url)
        url_add = QPushButton(tr("add"))
        url_add.clicked.connect(self._add_url)
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(url_add)
        sl.addLayout(url_row)

        self.src_host = QWidget()
        self.src_lay = QVBoxLayout(self.src_host)
        self.src_lay.setContentsMargins(0, 0, 0, 0)
        self.src_lay.setSpacing(4)
        src_scroll = QScrollArea()
        src_scroll.setWidgetResizable(True)
        src_scroll.setFrameShape(QFrame.NoFrame)
        src_scroll.setFixedHeight(320)
        src_scroll.setWidget(self.src_host)
        sl.addWidget(src_scroll)
        self.src_empty = W.muted(tr("no_source"))
        self.src_lay.addWidget(self.src_empty)
        root.addWidget(src_card)

        # 结果区:处理完成后在这里直接看效果,而不是只弹一句「成功」。
        # 每张显示原图 vs 成品对照,点击放大 —— 改图效果必须看得见才算数。
        self.res_card = W.make_card()
        rl2 = QVBoxLayout(self.res_card)
        rl2.setContentsMargins(12, 10, 12, 10)
        rl2.setSpacing(8)
        res_head = QHBoxLayout()
        res_head.addWidget(self._section(tr("result_images")))
        res_head.addStretch(1)
        self.res_count = W.muted("")
        res_head.addWidget(self.res_count)
        btn_open = QPushButton(tr("open_dir"))
        btn_open.setToolTip(tr("open_dir"))
        btn_open.clicked.connect(self._open_out_dir)
        res_head.addWidget(btn_open)
        rl2.addLayout(res_head)
        self.res_host = QWidget()
        self.res_lay = QHBoxLayout(self.res_host)
        self.res_lay.setContentsMargins(0, 0, 0, 0)
        self.res_lay.setSpacing(8)
        self.res_lay.addStretch(1)
        self.res_empty = W.muted(tr("no_result"))
        self.res_lay.addWidget(self.res_empty)
        res_scroll = QScrollArea()
        res_scroll.setWidgetResizable(True)
        res_scroll.setFrameShape(QFrame.NoFrame)
        res_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        res_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        res_scroll.setFixedHeight(168)
        res_scroll.setWidget(self.res_host)
        rl2.addWidget(res_scroll)
        self.res_card.setVisible(False)
        root.addWidget(self.res_card)

        # 指令 + 输出目录(底部)
        foot_card = W.make_card()
        fl = QVBoxLayout(foot_card)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(8)

        out_row = QHBoxLayout()
        out_row.setSpacing(6)
        out_row.addWidget(QLabel(tr("output_dir")))
        self.out_edit = QLineEdit()
        self.out_edit.setReadOnly(True)
        out_row.addWidget(self.out_edit, 1)
        b_out = QPushButton(tr("choose"))
        b_out.clicked.connect(self._pick_out_dir)
        b_open = QPushButton(tr("open_dir"))
        b_open.clicked.connect(self._open_out_dir)
        out_row.addWidget(b_out)
        out_row.addWidget(b_open)
        fl.addLayout(out_row)

        self.instr = QPlainTextEdit()
        self.instr.setPlaceholderText(tr("image_instr_hint"))
        self.instr.setFixedHeight(88)
        fl.addWidget(self.instr)

        # 画面人数:写进提示词当硬约束。原来固定 people=1,遇到"去掉人物"这类
        # 指令会和提示词自相矛盾(要删人却告诉模型保留 1 个人)。
        prow = QHBoxLayout()
        prow.setSpacing(6)
        prow.addWidget(QLabel(tr("people_count")))
        self.people_combo = QComboBox()
        for n in (1, 2, 3):
            self.people_combo.addItem(f"{n} {tr('people_unit')}", n)
        self.people_combo.setToolTip(tr("people_count_tip"))
        prow.addWidget(self.people_combo)
        prow.addStretch(1)
        fl.addLayout(prow)

        act = QHBoxLayout()
        self.status_lab = W.muted("")
        act.addWidget(self.status_lab, 1)
        # 必须用 WaitingButton:W.primary_btn 返回的是普通 QPushButton,**没有
        # .busy() 方法** —— 在 TASKMGR.submit 之前就 AttributeError,任务永远提交
        # 不出去;而且 _busy 已置 True,之后再点全被 return 挡掉(表现为按钮都不能按)。
        self.run_btn = WaitingButton(tr("start_process"), primary=True)
        self.run_btn.clicked.connect(self._run)
        act.addWidget(self.run_btn)
        fl.addLayout(act)
        root.addWidget(foot_card)

    @staticmethod
    def _section(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("inspectorLabel")
        return lab

    @staticmethod
    def _mk_combo() -> QComboBox:
        c = QComboBox()
        c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        c.setMinimumWidth(90)
        c.setMaximumWidth(260)
        return c

    # ── 数据 ──
    def _reload_models(self):
        for combo, stype in ((self.text_model, "text"), (self.image_model, "image")):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem(tr("configured"), None)
            for r in registry.list_configs(stype):
                combo.addItem((r["model"] or "").split("/")[-1] or r["model"], r["id"])
            combo.blockSignals(False)

    def _reset_output_dir(self):
        d = config.STATIC_DIR / "processed"
        d.mkdir(parents=True, exist_ok=True)
        self.out_edit.setText(str(d))

    # ── 来源操作 ──
    def _pick_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, tr("pick_local_images"), "",
            f"Images ({' '.join('*' + e for e in IMG_EXTS)})")
        self._add_paths(paths)
        if len(self._sources) > MAX_BATCH:
            warn(tr("batch_capped").format(MAX_BATCH))

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("pick_local_dir"))
        if not d:
            return
        found = [str(p) for p in sorted(Path(d).rglob("*"))
                 if p.suffix.lower() in IMG_EXTS]
        if not found:
            self.status_lab.setText(tr("dir_no_images"))
            return
        if len(found) > MAX_BATCH:
            warn(tr("batch_capped").format(MAX_BATCH))
            found = found[:MAX_BATCH]
        self._add_paths(found)

    def _add_url(self):
        u = self.url_edit.text().strip()
        if not u:
            return
        if not u.startswith(("http://", "https://")):
            err(tr("url_invalid"))
            return
        if u not in self._sources:
            self._sources.append(u)
        self.url_edit.clear()
        self._render_sources()

    def _add_paths(self, paths):
        for p in paths:
            if p and p not in self._sources:
                self._sources.append(p)
        self._render_sources()

    def _clear(self):
        self._sources.clear()
        self._render_sources()

    def _render_sources(self):
        while self.src_lay.count():
            it = self.src_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        if not self._sources:
            self.src_lay.addWidget(W.muted(tr("no_source")))
            return
        for i, s in enumerate(self._sources[:200]):
            row = QFrame()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            # 功能键浮在图片上(参考项目的交互):不再排到缩略图右边 ——
            # 行宽上千像素时右边的按钮会被甩到屏幕边缘,根本看不见
            holder = QFrame()
            holder.setFixedSize(150, 112)
            holder.setStyleSheet("border:1px solid rgba(128,128,128,60); border-radius:6px;"
                                 "background:#f7f8fa;")
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            holder_img = QLabel(holder)
            holder_img.setGeometry(1, 1, 148, 110)
            holder_img.setAlignment(Qt.AlignCenter)
            if str(s).startswith("http"):
                _ic = W.svg_icon("globe", size=22)
                holder_img.setPixmap(_ic.pixmap(22, 22)) if not _ic.isNull() else holder_img.setText("")
            else:
                holder_img.setPixmap(W.pixmap_from_media(s, 148, 110))
            holder_img.setToolTip(tr("u_view_large"))
            holder_img.setCursor(Qt.PointingHandCursor)
            holder_img.mousePressEvent = lambda _e, x=str(s): self._view_large(x)
            hl.addWidget(holder_img)
            bar = QHBoxLayout()
            bar.setContentsMargins(3, 0, 3, 3)
            bar.setSpacing(3)
            bar.addStretch(1)
            for key, tip, cb in (
                    ("patch_local", "patch_local_tip", self._open_patch),
                    ("edit_image", "edit_image_tip", self._open_edit),
            ):
                b = QPushButton(tr(key))
                b.setFixedSize(30, 22)
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip(tr(tip))
                b.setStyleSheet(
                    "QPushButton{background:rgba(255,255,255,225);border:1px solid rgba(128,128,128,90);"
                    "border-radius:4px;color:#1f2329;font-size:11px;padding:0;}"
                    "QPushButton:hover{background:#f97316;color:#ffffff;}")
                b.clicked.connect(lambda _=False, x=str(s), f=cb: f(x))
                bar.addWidget(b)
            rm = W.svg_icon_btn("close", "", size=22)
            rm.setCursor(Qt.PointingHandCursor)
            rm.setToolTip(tr("u_delete"))
            rm.setStyleSheet(
                "QPushButton{background:rgba(255,255,255,225);border:1px solid rgba(128,128,128,90);"
                "border-radius:4px;color:#4e5969;font-size:12px;padding:0;}"
                "QPushButton:hover{background:#dc2626;color:#ffffff;}")
            rm.clicked.connect(lambda _=False, x=str(s): self._remove_one(x))
            bar.addWidget(rm)
            hl.addLayout(bar)
            rl.addWidget(holder)
            row.setToolTip(str(s))
            self.src_lay.addWidget(row)
        if len(self._sources) > 200:
            self.src_lay.addWidget(W.muted(tr("sources_truncated", 200, len(self._sources))))

    def _view_large(self, path: str):
        """点击缩略图放大预览(复用素材详情的大图查看器)。"""
        from .asset_dialogs import ImageViewerDialog
        ImageViewerDialog(self, path, Path(path).name).exec()

    def _remove_one(self, path: str):
        if path in self._sources:
            self._sources.remove(path)
        self._render_sources()

    def _pick_out_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("output_dir"), self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    def _render_results(self, items):
        """items: [(原图, 成品路径 或 None, 错误文案 或 None)]。

        目录批量时几十张也要能一眼看出哪些成功、哪些失败 —— 所以每张一张卡:
        成功显示成品缩略图,失败显示红框 + 具体报错(悬停可见),都能点开看前后对比。
        """
        while self.res_lay.count():
            it = self.res_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        ok_n = sum(1 for _, out, _e in items if out)
        self.res_count.setText(tr("result_count").format(ok_n, len(items)))
        self.res_card.setVisible(bool(items))
        if not items:
            self.res_lay.addStretch(1)
            self.res_lay.addWidget(W.muted(tr("no_result")))
            return
        for src, out, e in items:
            cell = QFrame()
            cl = QVBoxLayout(cell)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(3)
            box = QFrame()
            box.setFixedSize(150, 112)
            box.setCursor(Qt.PointingHandCursor)
            box.setToolTip(tr("result_compare") if out else (e or ""))
            if out:
                box.setStyleSheet("border:1px solid rgba(22,163,74,90); border-radius:6px;")
                im = QLabel(box)
                im.setGeometry(1, 1, 148, 110)
                im.setAlignment(Qt.AlignCenter)
                im.setPixmap(W.pixmap_from_media(out, 148, 110))
                box.mousePressEvent = lambda _ev, a=src, b=out: self._compare(a, b)
            else:
                box.setStyleSheet("border:1px solid rgba(220,38,38,110); border-radius:6px;"
                                  "background:#fdecec;")
                lb = QLabel(tr("result_failed"), box)
                lb.setGeometry(0, 0, 150, 112)
                lb.setAlignment(Qt.AlignCenter)
                lb.setWordWrap(True)
                lb.setStyleSheet("color:#dc2626; font-size:11px; border:none; background:transparent;")
            cl.addWidget(box)
            cap = QLabel(Path(str(src)).stem[:18])
            cap.setObjectName("muted")
            cap.setAlignment(Qt.AlignCenter)
            cap.setToolTip(str(e) if e else str(src))
            cl.addWidget(cap)
            self.res_lay.insertWidget(self.res_lay.count() - 1, cell)
        self.res_lay.addStretch(1)

    def _open_edit(self, path: str):
        """打开改图对话框(裁剪/旋转/翻转/调色/滤镜/水印/尺寸/去背景)。

        复用已有的 ImageEditDialog —— 它就是参考项目那张「改图·某某」弹窗的等价实现,
        不必重写一套。保存后把成品并入结果区。
        """
        from .image_edit_dialog import ImageEditDialog
        dlg = ImageEditDialog(self, path, None, tr("edit_image"))
        if dlg.exec() == QDialog.Accepted and getattr(dlg, "saved_url", None):
            self._render_results([(path, dlg.saved_url, None)])
            self._replace_source(path, dlg.saved_url)  # 左侧素材指向最新版

    def _replace_source(self, old: str, new: str):
        """用处理后的文件替换来源列表里的原条目。

        这是「链式编辑」的关键:修补/改图完成后左侧素材指向最新版本,
        再修补、再改图、批量处理都以它为基础,而不是又从原图开始。
        原文件不删除,成品也保留在「处理结果」区,可随时对照/找回。
        """
        if old in self._sources:
            self._sources[self._sources.index(old)] = new
            self._render_sources()

    def _open_patch(self, path: str):
        """打开局部修补对话框;完成后把成品并入结果区。"""
        from .patch_dialog import PatchDialog
        dlg = PatchDialog(self, path, Path(self.out_edit.text().strip()))
        if dlg.exec() == QDialog.Accepted and getattr(dlg, "done_url", None):
            self._render_results([(path, dlg.done_url, None)])
            self._replace_source(path, dlg.done_url)   # 左侧素材指向最新版,链式编辑

    def _compare(self, before: str, after: str):
        """原图 vs 成品并排对照 —— 改图效果必须看得见才算数。"""
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("result_compare"))
        dlg.resize(1100, 640)
        lay = QVBoxLayout(dlg)
        row = QHBoxLayout()
        row.setSpacing(10)
        for cap, url in ((tr("before"), before), (tr("after"), after)):
            col = QVBoxLayout()
            lab = QLabel(cap)
            lab.setObjectName("inspectorLabel")
            lab.setAlignment(Qt.AlignCenter)
            col.addWidget(lab)
            im = QLabel()
            im.setAlignment(Qt.AlignCenter)
            im.setPixmap(W.pixmap_from_media(url, 520, 520))
            col.addWidget(im, 1)
            holder = QWidget(); holder.setLayout(col)
            row.addWidget(holder, 1)
        lay.addLayout(row, 1)
        close = W.primary_btn(tr("close"))
        close.clicked.connect(dlg.accept)
        brow = QHBoxLayout()
        brow.addStretch(1)
        brow.addWidget(close)
        lay.addLayout(brow)
        dlg.exec()

    def _open_out_dir(self):
        import os
        d = self.out_edit.text().strip()
        if d and Path(d).is_dir():
            os.startfile(d)  # noqa: Windows 默认资源管理器

    # ── 执行 ──
    def _on_image_model_changed(self):
        """切图像模型时立刻校验:不支持参考图的模型改图必然跑偏,当场提示。"""
        if not self._sources:
            return
        if not self._provider_supports_reference():
            self.status_lab.setText(
                tr("model_no_reference").format(self._image_provider_name()))

    def _image_provider_name(self) -> str:
        cid = self.image_model.currentData()
        if cid is None:
            from ..ai import registry
            lst = registry.list_configs("image")
            cid = lst[0]["id"] if lst else None
        if cid is None:
            return ""
        row = db.q1("SELECT provider FROM ai_service_configs WHERE id=?", (cid,))
        return (row["provider"] if row else "") or ""

    def _provider_supports_reference(self) -> bool:
        from ..ai.image_client import supports_reference_images
        return supports_reference_images(self._image_provider_name())

    def _run(self):
        if self._busy:
            return
        if not self._sources:
            err(tr("no_source"))
            return
        instr = self.instr.toPlainText().strip()
        if not instr:
            err(tr("instr_required"))
            return
        if len(self._sources) > MAX_BATCH:
            err(tr("batch_capped").format(MAX_BATCH))
            return
        # 改图必须有参考图。qwen-image / volcengine 根本不把参考图发给模型,
        # 选它们等于花钱做纯文生图 —— 出来的是另一张不相干的画面。必须拦下。
        if not self._provider_supports_reference():
            err(tr("model_no_reference").format(self._image_provider_name()))
            return
        out_dir = Path(self.out_edit.text().strip())
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            err(str(e)[:160])
            return

        self._busy = True
        self.run_btn.busy(tr("in_progress"))
        self._set_source_enabled(False)
        srcs = list(self._sources)
        cfg = self.image_model.currentData()
        total = len(srcs)
        people = self.people_combo.currentData() or 1
        self.status_lab.setText(tr("process_preparing"))

        def job(tid):
            done_n = 0
            items: list[tuple] = []      # (原图, 成品或 None, 报错或 None) —— 逐张留痕
            fails: list[str] = []
            for i, s in enumerate(srcs):
                if i:
                    time.sleep(1)      # 串行 + 间隔,避免撞上游限流
                _TM.set_stage(tid, f"{i + 1}/{total}")
                self._set_progress(i, total, Path(str(s)).name)
                try:
                    out = self._process_one(s, instr, out_dir, cfg, people)
                    items.append((s, out, None))
                    done_n += 1
                except Exception as exc:  # noqa: BLE001
                    msg = str(exc)[:120]
                    items.append((s, None, msg))
                    fails.append(f"{Path(str(s)).name}: {msg[:60]}")
            return {"done": done_n, "total": total, "out_dir": str(out_dir),
                    "fails": fails, "items": items}

        def done(tid, result, error):
            self._busy = False
            self.run_btn.idle()
            self._set_source_enabled(True)
            if error:
                self.status_lab.setText("")
                err(str(error)[:220])
                return
            r = result or {}
            ok(tr("process_done").format(r.get("done", 0), r.get("total", 0)))
            self._render_results(r.get("items") or [])
            fails = r.get("fails") or []
            self.status_lab.setText(tr("process_failed_n", len(fails)) if fails else "")
            for f in fails[:3]:
                err(str(f)[:180])

        TASKMGR.submit("image", job, done, detail=tr("image_process"))

    def _set_progress(self, done: int, total: int, name: str):
        self.status_lab.setText(tr("process_progress").format(done + 1, total, name))

    def _set_source_enabled(self, on: bool):
        """处理中锁住来源控件:边跑边改来源会让结果对不上。"""
        for w in self._src_widgets:
            try:
                w.setEnabled(on)
            except RuntimeError:
                pass

    @staticmethod
    def _process_one(src: str, instr: str, out_dir: Path, cfg_id, people: int = 1) -> str:
        """按指令改一张图,落到 out_dir;返回输出路径。"""
        # 远程图先下载到临时文件,图生图只吃本地路径
        local = src
        tmp = None
        if str(src).startswith(("http://", "https://")):
            import tempfile
            import requests
            resp = requests.get(src, timeout=60)
            resp.raise_for_status()
            fd, tmp = tempfile.mkstemp(suffix=".img")
            with open(fd, "wb") as f:
                f.write(resp.content)
            local = tmp
        try:
            refs = [local] if local else []
            stem = Path(str(src)).stem or "image"
            out_name = f"{stem}_ai.png"
            out, _p = image_client.generate_image(
                build_edit_prompt(instr, people), out_name=out_name, config_id=cfg_id,
                reference_images=refs, people=people, extra_negative=EDIT_NEGATIVE)
            dest = out_dir / Path(out).name
            Path(out).replace(dest) if Path(out).exists() and dest != Path(out) else None
            if not dest.exists():
                dest = out_dir / out_name
                Path(out).replace(dest)
            return str(dest)
        finally:
            if tmp and Path(tmp).exists():
                Path(tmp).unlink(missing_ok=True)