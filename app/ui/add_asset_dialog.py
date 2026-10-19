# -*- coding: utf-8 -*-
"""手动新增资产对话框(对齐参考项目 episode.vue openAssetCreate/saveAssetCreate)。

角色: 名称/定位/样貌/妆造;场景: 地点/时间/描述/光照;道具: 名称/类型/描述。
"""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout,
                               QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout)

from ..core import db
from ..core.i18n import tr
from ..pipeline import character_spec
from . import widgets as W
from .toast import err, ok, warn

ROLE_ITEMS = [("lead", "主角"), ("supporting", "配角")]
KIND_TABLE = {"character": "characters", "scene": "scenes", "prop": "props"}
KIND_LINK = {"character": "episode_characters", "scene": "episode_scenes",
             "prop": "episode_props"}
KIND_COL = {"character": "character_id", "scene": "scene_id", "prop": "prop_id"}


class AddAssetDialog(QDialog):
    def __init__(self, parent, kind: str, drama_id: int, episode_id: int,
                 on_done=None):
        super().__init__(parent)
        self.kind = kind
        self.drama_id = drama_id
        self.episode_id = episode_id
        self.on_done = on_done
        self.setWindowTitle(tr("新增资产"))
        self.resize(460, 360)
        root = QVBoxLayout(self)
        f = QFormLayout()
        f.setSpacing(8)

        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("必填"))
        self.role = QComboBox()
        for code, label in ROLE_ITEMS:
            self.role.addItem(label, code)
        self.type = QComboBox()
        self.type.addItem(tr("道具"), "prop")
        self.desc = QPlainTextEdit()
        self.desc.setMaximumHeight(110)
        # 样貌/妆造是出图提示词的原料,单行输入框连 150 字都看不全 -> 改多行,
        # 并把规格提示写在占位符里(真正的兜底在 character_spec,不靠用户自觉)。
        self.appearance = QPlainTextEdit()
        self.appearance.setMaximumHeight(80)
        self.appearance.setPlaceholderText(tr(
            "150 字以上连贯描述:身高体型、五官逐项、肤质、发型、惯常神情"))
        self.styling = QPlainTextEdit()
        self.styling.setMaximumHeight(70)
        self.styling.setPlaceholderText(tr(
            "80 字以上:逐件服装/颜色/材质/穿着方式/鞋袜配饰/使用痕迹"))
        self.location = QLineEdit()
        self.time = QLineEdit()
        self.lighting = QLineEdit()

        if kind == "character":
            f.addRow(tr("角色名"), self.name)
            f.addRow(tr("定位"), self.role)
            f.addRow(tr("样貌"), self.appearance)
            f.addRow(tr("妆造"), self.styling)
        elif kind == "scene":
            f.addRow(tr("地点"), self.location)
            f.addRow(tr("时间"), self.time)
            f.addRow(tr("光照"), self.lighting)
            f.addRow(tr("描述"), self.desc)
        else:
            f.addRow(tr("名称"), self.name)
            f.addRow(tr("类型"), self.type)
            f.addRow(tr("描述"), self.desc)
        root.addLayout(f)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton(tr("cancel"))
        cancel.clicked.connect(self.reject)
        save = W.primary_btn(tr("save"))
        save.clicked.connect(self._save)
        row.addWidget(cancel)
        row.addWidget(save)
        root.addLayout(row)

    def _save(self):
        try:
            ts = db.now()
            if self.kind == "character":
                name = self.name.text().strip()
                if not name:
                    raise ValueError(tr("请填写角色名"))
                if db.q1("SELECT id FROM characters WHERE drama_id=? AND name=?",
                         (self.drama_id, name)):
                    raise ValueError(tr("同名角色已存在"))
                cid = db.ex(
                    "INSERT INTO characters(drama_id,name,role_type,appearance,styling,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (self.drama_id, name, self.role.currentData(),
                     self.appearance.toPlainText().strip(),
                     self.styling.toPlainText().strip(), ts, ts))
                # 不阻断手工录入(用户可能就是要先占位),但明确告知不达标,
                # 否则又是"存进去看着正常、出图才发现没细节"。
                issues = character_spec.audit(self.appearance.toPlainText(),
                                              self.styling.toPlainText())
                if issues:
                    warn(tr("外观描述偏简,出图细节会不足:") + issues[0])
            elif self.kind == "scene":
                loc = self.location.text().strip()
                if not loc:
                    raise ValueError(tr("请填写地点"))
                if db.q1("SELECT id FROM scenes WHERE drama_id=? AND location=?",
                         (self.drama_id, loc)):
                    raise ValueError(tr("同名场景已存在"))
                cid = db.ex(
                    "INSERT INTO scenes(drama_id,location,time,prompt,lighting,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (self.drama_id, loc, self.time.text().strip(),
                     self.desc.toPlainText().strip(), self.lighting.text().strip(), ts, ts))
            else:
                name = self.name.text().strip()
                if not name:
                    raise ValueError(tr("请填写名称"))
                if db.q1("SELECT id FROM props WHERE drama_id=? AND name=?",
                         (self.drama_id, name)):
                    raise ValueError(tr("同名道具已存在"))
                cid = db.ex(
                    "INSERT INTO props(drama_id,name,type,description,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (self.drama_id, name, self.type.currentData(),
                     self.desc.toPlainText().strip(), ts, ts))
            db.ex(f"INSERT OR IGNORE INTO {KIND_LINK[self.kind]}(episode_id,{KIND_COL[self.kind]})"
                  " VALUES(?,?)", (self.episode_id, cid))
            self.accept()
            ok(tr("已新增资产"))
            if self.on_done:
                self.on_done()
        except Exception as exc:  # noqa: BLE001
            err(str(exc)[:160])