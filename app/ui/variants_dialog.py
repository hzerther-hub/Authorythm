# -*- coding: utf-8 -*-
"""造型变体管理(对齐原版 character_variants / scene_variants / prop_variants):

列表(标签/形象图/默认)→ 新增变体(标签+描述 → AI 提示词)→ 变体出图
→ 「设为主形象」把变体图设回对应资产(image_url)。

三种 kind 复用同一份 UI/逻辑,只换表名与字段名:
  character → character_variants / characters
  scene     → scene_variants     / scenes
  prop      → prop_variants      / props
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..agents import runner
from ..ai import image_client
from ..core import config, db
from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from . import widgets as W
from .toast import err, ok


# 三个 kind 的表名 / 资产字段名 / 资产名 / 描述字段集中映射。
# 加新 kind(建筑 / 服饰 …)只需在此处加一行 + 加 i18n 文案。
_KIND_CFG: dict[str, dict] = {
    "character": dict(var_tbl="character_variants", asset_tbl="characters",
                      ref_col="character_id", name_col="name",
                      desc_col="costume_desc", desc_ph="服装/造型描述(如 黑色劲装,束发,佩剑)",
                      use_btn="用作角色形象", use_done="已将「{}」设为 {} 的当前形象"),
    "scene":     dict(var_tbl="scene_variants",     asset_tbl="scenes",
                      ref_col="scene_id",     name_col="name",
                      desc_col="change_desc", desc_ph="场景状态描述(如 装修后 / 雨夜 / 冬季)",
                      use_btn="用作场景形象", use_done="已将「{}」设为 {} 的当前形象"),
    "prop":      dict(var_tbl="prop_variants",      asset_tbl="props",
                      ref_col="prop_id",      name_col="name",
                      desc_col="change_desc", desc_ph="道具状态描述(如 升级后 / 染血 / 破损)",
                      use_btn="用作道具形象", use_done="已将「{}」设为 {} 的当前形象"),
}


class VariantsDialog(QDialog):
    def __init__(self, parent, asset: dict, kind: str = "character"):
        super().__init__(parent)
        if kind not in _KIND_CFG:
            raise ValueError(f"unknown variant kind: {kind}")
        self.asset = asset
        self.kind = kind
        self._cfg = _KIND_CFG[kind]
        asset_name = asset.get("name") or asset.get("location") or ""
        self.setWindowTitle(tr('◑ 造型变体 · {}').format(asset_name))
        self.resize(680, 560)
        root = QVBoxLayout(self)
        root.addWidget(W.h2(tr('◑ {} · 造型变体').format(asset_name)))
        root.addWidget(W.muted(tr("为该资产添加多套变体(造型 / 场景状态 / 道具状态);"
                                 "生成后可选「用作主形象」覆盖回资产图。")))

        add_box = W.make_card()
        a_lay = QHBoxLayout(add_box)
        a_lay.setContentsMargins(10, 8, 10, 8)
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText(tr("变体标签(如 战斗服)"))
        self.costume_edit = QLineEdit()
        self.costume_edit.setPlaceholderText(tr(self._cfg["desc_ph"]))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText(tr("场景标签(逗号分隔,如 战斗,雨夜)"))
        self.tags_edit.setToolTip(tr("分镜带这些标签时优先命中本变体"))
        add_btn = W.primary_btn("＋ " + tr("add"))
        add_btn.clicked.connect(self._add_variant)
        a_lay.addWidget(self.label_edit, 1)
        a_lay.addWidget(self.costume_edit, 2)
        a_lay.addWidget(self.tags_edit, 1)
        a_lay.addWidget(add_btn)
        root.addWidget(add_box)

        self.list_lay = QVBoxLayout()
        root.addLayout(self.list_lay)
        root.addStretch(1)
        self.reload()

    def reload(self):
        cfg = self._cfg
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        rows = db.q(f"SELECT * FROM {cfg['var_tbl']} WHERE {cfg['ref_col']}=? "
                    f"ORDER BY is_default DESC, sort_order ASC, id", (self.asset["id"],))
        for r in rows:
            self.list_lay.addWidget(self._row(dict(r)))
        if not rows:
            empty = QLabel(tr("— 暂无变体,上方新增 —"))
            empty.setObjectName("muted")
            empty.setAlignment(Qt.AlignCenter)
            self.list_lay.addWidget(empty)

    def _row(self, r: dict) -> QWidget:
        box = W.make_card()
        # Director's Slate:variant 行 4px 圆角 + 细灰边 + hover 时边变黑,
        # 与启动台 SlateStrip 同一卡片语言保持一致
        box.setObjectName("variantRow")
        box.setStyleSheet(
            "QFrame#variantRow{background:#FFFFFF; border:1px solid #DCDAD3;"
            "border-radius:4px;}"
            "QFrame#variantRow:hover{border-color:#0E0F12;}"
            "QFrame#variantRow QLabel{background:transparent;}"
        )
        lay = QHBoxLayout(box)
        lay.setContentsMargins(10, 8, 10, 8)
        img = QLabel()
        img.setPixmap(W.pixmap_from_media(r["image_url"], 84))
        img.setFixedWidth(90)
        lay.addWidget(img)
        info = QVBoxLayout()
        head = QHBoxLayout()
        head.addWidget(W.h2(r["label"]))
        if r["is_default"]:
            head.addWidget(W.tag(tr("默认")))
        if r["image_url"]:
            head.addWidget(W.tag(tr("generated")))
        head.addStretch(1)
        info.addLayout(head)
        desc = QLabel((r.get(self._cfg["desc_col"]) or "")[:80])
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        info.addWidget(desc)
        lay.addLayout(info, 1)
        btns = QVBoxLayout()
        use_btn = W.primary_btn(tr(self._cfg["use_btn"]))
        use_btn.setEnabled(bool(r["image_url"]))
        use_btn.clicked.connect(lambda _=False, rr=r: self._set_default(rr))
        gen = QPushButton(tr("redraw") + tr("(生成形象)"))
        gen.clicked.connect(lambda _=False, rr=r: self._gen_image(rr))
        btns.addWidget(use_btn)
        btns.addWidget(gen)
        lay.addLayout(btns)
        return box

    def _add_variant(self):
        label = self.label_edit.text().strip()
        costume = self.costume_edit.text().strip()
        if not label:
            self.label_edit.setFocus()
            return
        cfg = self._cfg
        ts = db.now()
        tags = [t.strip() for t in self.tags_edit.text().replace("、", ",").split(",") if t.strip()]
        nxt = (db.q1(f"SELECT COALESCE(MAX(sort_order),0)+1 n FROM {cfg['var_tbl']} "
                     f"WHERE {cfg['ref_col']}=?", (self.asset["id"],))["n"])
        vid = db.ex(
            f"INSERT INTO {cfg['var_tbl']}({cfg['ref_col']},label,{cfg['desc_col']},"
            f"tags,is_default,sort_order,created_at) VALUES(?,?,?,?,0,?,?)",
            (self.asset["id"], label, costume,
             json.dumps(tags, ensure_ascii=False), nxt, ts))
        self.label_edit.clear()
        self.costume_edit.clear()
        self.tags_edit.clear()
        # AI 生成变体提示词
        a = db.q1(f"SELECT * FROM {cfg['asset_tbl']} WHERE id=?", (self.asset["id"],))
        if not a:
            return
        # 不同 kind 的提示词前缀不同:角色强调「同人不同造型」,
        # 场景/道具强调「状态/细节变化,主体外观保持一致」。
        kind_prompt = {
            "character": "目标类型:character(角色造型变体参考图,与主形象同人)",
            "scene":     "目标类型:scene(场景状态变体参考图,与主场景同景)",
            "prop":      "目标类型:prop(道具状态变体参考图,与主道具同物)",
        }[self.kind]
        keep_term = (
            "脸部与发型与主形象保持一致,仅更换服装造型" if self.kind == "character"
            else "主体外观/构图与主形象保持一致,仅按下方描述更换状态细节")
        style = db.style_prompt(db.drama_style(a["drama_id"]))
        # 资产名字段:场景用 location,角色/道具用 name
        an = a.get("name") or a.get("location") or ""
        # 主形象描述:角色 appearance;场景 lighting+setting_tags;道具 description
        if self.kind == "character":
            main_desc = a.get("appearance") or ""
        elif self.kind == "scene":
            setting_tags = a.get("setting_tags") or ""
            main_desc = (a.get("lighting") or "") + ((" · " + setting_tags) if setting_tags else "")
        else:
            main_desc = a.get("description") or ""
        prompt = (
            f"{kind_prompt}\n视觉风格前缀: {style}\n\n"
            f"资产: {an}\n"
            f"主形象样貌: {main_desc}\n本变体描述: {label} — {costume}\n"
            f"要求:{keep_term}。"
        )
        def job(tid):
            data = runner.run_agent_json("prompt_generator", prompt, config_id=None)
            fp = (data or {}).get("final_prompt", "")
            if fp:
                db.ex(f"UPDATE {cfg['var_tbl']} SET final_prompt=? WHERE id=?", (fp, vid))
            return fp
        def done(tid, result, error):
            if error:
                err("AI")
            self.reload()
        TASKMGR.submit("prompt", job, done)

    def _gen_image(self, r: dict):
        if TASKMGR.is_busy("image"):
            from .toast import err as _err
            _err("已有图片生成任务在跑,请等它完成后再试")
            return
        cfg = self._cfg
        def job(tid):
            fp = r["final_prompt"]
            if not fp:
                raise RuntimeError(tr("该变体还没有提示词,请稍后重试或补充描述后重新打开"))
            # 角色变体复用三视图白底守卫;场景/道具不需要该守卫。
            from ..ai.prompt_guards import (CHARACTER_SHEET_NEGATIVE,
                                            CHARACTER_SHEET_PROMPT_SUFFIX)
            is_sheet = any(k in fp for k in ("三视图", "turnaround", "character sheet"))
            if self.kind == "character":
                if "white background" not in fp.lower():
                    fp = fp + ", clean pure white background, isolated subject"
                fp = fp + CHARACTER_SHEET_PROMPT_SUFFIX
            out, _p = image_client.generate_image(
                fp,
                skip_guard=is_sheet,
                extra_negative=CHARACTER_SHEET_NEGATIVE if self.kind == "character" else None)
            db.ex(f"UPDATE {cfg['var_tbl']} SET image_url=? WHERE id=?",
                  (config.path_to_media_url(out), r["id"]))
            return str(out)
        def done(tid, result, error):
            if error:
                err("AI")
            self.reload()
        TASKMGR.submit("image", job, done)

    def _set_default(self, r: dict):
        cfg = self._cfg
        db.ex(
            f"UPDATE {cfg['var_tbl']} SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END "
            f"WHERE {cfg['ref_col']}=?",
            (r["id"], self.asset["id"]))
        db.ex(
            f"UPDATE {cfg['asset_tbl']} SET image_url=?, updated_at=? WHERE id=?",
            (r["image_url"], db.now(), self.asset["id"]))
        an = self.asset.get("name") or self.asset.get("location") or ""
        QMessageBox.information(
            self, tr("visual_style"),
            tr(self._cfg["use_done"]).format(r["label"], an))
        self.reload()