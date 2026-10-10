# -*- coding: utf-8 -*-
"""角色造型变体管理(对齐原版 character_variants):

列表(标签/形象图/默认)→ 新增变体(标签+服装描述 → AI 提示词)→ 变体出图
→ 「用作角色形象」把变体图设为角色主形象。
"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QVBoxLayout)

from ..agents import runner
from ..ai import image_client
from ..core import config, db
from ..core.i18n import tr
from ..core.taskmgr import TASKMGR
from . import widgets as W
from .toast import err, ok


class VariantsDialog(QDialog):
    def __init__(self, parent, character: dict):
        super().__init__(parent)
        self.character = character
        self.setWindowTitle(tr('◑ 造型变体 · {}').format(character['name']))
        self.resize(680, 560)
        root = QVBoxLayout(self)
        root.addWidget(W.h2(tr('◑ {} · 造型变体').format(character['name'])))
        root.addWidget(W.muted(tr("为角色添加多套造型(如 便装/战斗/回忆青年);生成形象后可「用作角色形象」。")))

        add_box = W.make_card()
        a_lay = QHBoxLayout(add_box)
        a_lay.setContentsMargins(10, 8, 10, 8)
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText(tr("变体标签(如 战斗服)"))
        self.costume_edit = QLineEdit()
        self.costume_edit.setPlaceholderText(tr("服装/造型描述(如 黑色劲装,束发,佩剑)"))
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText(tr("场景标签(逗号分隔,如 战斗,雨夜)"))
        self.tags_edit.setToolTip(tr("分镜带这些标签时优先命中本变体(参考图里出现「战斗服」就选战斗变体)"))
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
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        rows = db.q("""SELECT * FROM character_variants WHERE character_id=?
                       ORDER BY is_default DESC, sort_order ASC, id""", (self.character["id"],))
        for r in rows:
            self.list_lay.addWidget(self._row(dict(r)))
        if not rows:
            empty = QLabel(tr("— 暂无变体,上方新增 —"))
            empty.setObjectName("muted")
            empty.setAlignment(Qt.AlignCenter)
            self.list_lay.addWidget(empty)

    def _row(self, r: dict) -> QWidget:
        box = W.make_card()
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
        desc = QLabel((r["costume_desc"] or "")[:80])
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        info.addWidget(desc)
        lay.addLayout(info, 1)
        btns = QVBoxLayout()
        use = W.primary_btn(tr("用作角色形象"))
        use.setEnabled(bool(r["image_url"]))
        use.clicked.connect(lambda _=False, rr=r: self._set_default(rr))
        gen = QPushButton(tr("redraw") + tr("(生成形象)"))
        gen.clicked.connect(lambda _=False, rr=r: self._gen_image(rr))
        btns.addWidget(use)
        btns.addWidget(gen)
        lay.addLayout(btns)
        return box

    def _add_variant(self):
        label = self.label_edit.text().strip()
        costume = self.costume_edit.text().strip()
        if not label:
            self.label_edit.setFocus()
            return
        ts = db.now()
        tags = [t.strip() for t in self.tags_edit.text().replace("、", ",").split(",") if t.strip()]
        nxt = (db.q1("SELECT COALESCE(MAX(sort_order),0)+1 n FROM character_variants WHERE character_id=?",
                      (self.character["id"],))["n"])
        vid = db.ex("""INSERT INTO character_variants(character_id,label,costume_desc,tags,
                       is_default,sort_order,created_at) VALUES(?,?,?,?,0,?,?)""",
                    (self.character["id"], label, costume,
                     json.dumps(tags, ensure_ascii=False), nxt, ts))
        self.label_edit.clear()
        self.costume_edit.clear()
        self.tags_edit.clear()
        # AI 生成变体提示词
        c = db.q1("SELECT * FROM characters WHERE id=?", (self.character["id"],))
        style = db.style_prompt(db.drama_style(c["drama_id"]))
        prompt = f"""目标类型:character(角色造型变体参考图,与主形象同人)
视觉风格前缀: {style}

角色: {c['name']}
主形象样貌: {c['appearance'] or ''}
本变体造型: {label} — {costume}
要求:脸部与发型与主形象保持一致,仅更换服装造型。"""
        def job(tid):
            data = runner.run_agent_json("prompt_generator", prompt, config_id=None)
            fp = (data or {}).get("final_prompt", "")
            if fp:
                db.ex("UPDATE character_variants SET final_prompt=? WHERE id=?", (fp, vid))
            return fp
        def done(tid, result, error):
            if error:
                err("AI")
            self.reload()
        TASKMGR.submit("prompt", job, done, character_id=self.character["id"])

    def _gen_image(self, r: dict):
        def job(tid):
            fp = r["final_prompt"]
            if not fp:
                raise RuntimeError(tr("该变体还没有提示词,请稍后重试或补充造型描述后重新打开"))
            out, _p = image_client.generate_image(fp)
            db.ex("UPDATE character_variants SET image_url=? WHERE id=?",
                  (config.path_to_media_url(out), r["id"]))
            return str(out)
        def done(tid, result, error):
            if error:
                err("AI")
            self.reload()
        TASKMGR.submit("image", job, done, character_id=self.character["id"])

    def _set_default(self, r: dict):
        db.ex("UPDATE character_variants SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END WHERE character_id=?",
              (r["id"], self.character["id"]))
        db.ex("UPDATE characters SET image_url=?, updated_at=? WHERE id=?",
              (r["image_url"], db.now(), self.character["id"]))
        QMessageBox.information(self, tr("visual_style"), tr('已将「{}」设为 {} 的当前形象').format(r['label'], self.character['name']))
        self.reload()
