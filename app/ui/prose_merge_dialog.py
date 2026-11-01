# -*- coding: utf-8 -*-
"""小说体改造 · 逐段对比合并视图(学 Pagekin MergeView)。

原稿/改稿按段落对齐切成 same|hunk 段;每处改动可单选「用原稿 / 用改稿」,
顶部一键全切;底部合并结果可手动编辑。确认后回调返回合并文本。
纯 PySide6 实现,diff 用标准库 difflib,零三方依赖。
"""
from __future__ import annotations

import difflib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QRadioButton, QVBoxLayout, QWidget)

from . import widgets as W
from .toast import err


def _paragraphs(text: str) -> list[str]:
    """按空行切段(与 Pagekin extractParagraphs 同款)。"""
    paras: list[str] = []
    buf: list[str] = []
    for line in (text or "").split("\n"):
        if line.strip() == "":
            if buf:
                paras.append("\n".join(buf))
                buf = []
        else:
            buf.append(line)
    if buf:
        paras.append("\n".join(buf))
    return paras


def align_segments(original: str, revised: str) -> list[dict]:
    """段落级对齐:返回 [{type:'same'|'hunk', original, revised}]。

    SequenceMatcher 按段落列表比对;replace 块即改动区(hunk)。
    """
    a, b = _paragraphs(original), _paragraphs(revised)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    segs: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for p in a[i1:i2]:
                segs.append({"type": "same", "original": p, "revised": p})
        elif tag in ("replace", "delete", "insert"):
            orig_block = "\n\n".join(a[i1:i2])
            rev_block = "\n\n".join(b[j1:j2])
            if orig_block or rev_block:
                segs.append({"type": "hunk", "original": orig_block, "revised": rev_block})
    return segs


class ProseMergeDialog(QDialog):
    """逐段对比合并:每处改动选 原稿/改稿,合并结果可手动编辑后确认。"""

    def __init__(self, parent, original: str, revised: str, on_complete):
        super().__init__(parent)
        self.setWindowTitle("小说体改造 · 逐段对比")
        self.resize(960, 760)
        self._on_complete = on_complete
        self._segs = align_segments(original, revised)
        self._picks: list[str] = ["revised" if s["type"] == "hunk" else "same"
                                  for s in self._segs]
        self._manual_edit = False        # 用户动过合并框后就不再自动刷新

        root = QVBoxLayout(self)
        head = QLabel("每处改动选择【用原稿】或【用改稿】;底部合并结果可直接手动编辑。")
        head.setObjectName("muted")
        root.addWidget(head)

        actions = QHBoxLayout()
        all_orig = QPushButton("全部用原稿")
        all_rev = QPushButton("全部用改稿")
        all_orig.clicked.connect(lambda: self._choose_all("original"))
        all_rev.clicked.connect(lambda: self._choose_all("revised"))
        actions.addWidget(all_orig)
        actions.addWidget(all_rev)
        actions.addStretch(1)
        root.addLayout(actions)

        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner_lay = QVBoxLayout(inner)
        inner_lay.setSpacing(8)
        self._radios: list[tuple[QRadioButton, QRadioButton]] = []
        for idx, seg in enumerate(self._segs):
            if seg["type"] == "same":
                box = QPlainTextEdit(seg["original"])
                box.setReadOnly(True)
                box.setMaximumHeight(64)
                box.setStyleSheet("color:#6b7280; border:none; background:transparent;")
                inner_lay.addWidget(box)
                continue
            card = W.make_card()
            lay = QVBoxLayout(card)
            lay.setContentsMargins(10, 8, 10, 8)
            lab = QLabel("改动区")
            lab.setStyleSheet("font-weight:bold; color:#f97316;")
            lay.addWidget(lab)
            pair = QHBoxLayout()
            ro = QRadioButton("用原稿")
            rr = QRadioButton("用改稿")
            (rr if self._picks[idx] == "revised" else ro).setChecked(True)
            ro.toggled.connect(lambda on, i=idx: self._pick(i, "original" if on else None))
            rr.toggled.connect(lambda on, i=idx: self._pick(i, "revised" if on else None))
            pair.addWidget(ro)
            pair.addWidget(rr)
            pair.addStretch(1)
            lay.addLayout(pair)
            orig_view = QPlainTextEdit(seg["original"])
            rev_view = QPlainTextEdit(seg["revised"])
            for v, tag in ((orig_view, "原稿"), (rev_view, "改稿")):
                v.setReadOnly(True)
                v.setMaximumHeight(110)
                v.setPlaceholderText(tag)
            pair2 = QHBoxLayout()
            pair2.addWidget(orig_view)
            pair2.addWidget(rev_view)
            lay.addLayout(pair2)
            inner_lay.addWidget(card)
            self._radios.append((ro, rr))
        scroll.setWidget(inner)
        root.addWidget(scroll, 1)

        root.addWidget(W.muted("合并结果(可直接手动编辑后再确认):"))
        self.merged_view = QPlainTextEdit()
        self.merged_view.setPlainText(self.merged_text())
        self.merged_view.textChanged.connect(
            lambda: setattr(self, "_manual_edit", True))
        root.addWidget(self.merged_view, 1)

        btns = QHBoxLayout()
        save = W.primary_btn("确认合并并保存")
        save.clicked.connect(self._complete)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(save)
        root.addLayout(btns)
        self._refresh_views()

    def _pick(self, idx: int, choice: str | None):
        if choice:
            self._picks[idx] = choice
        self._refresh_views()

    def _choose_all(self, choice: str):
        i = 0
        for seg in self._segs:
            if seg["type"] != "hunk":
                continue
            self._picks[i] = choice
            ro, rr = self._radios[i]
            (rr if choice == "revised" else ro).setChecked(True)
            i += 1
        self._manual_edit = False
        self._refresh_views()

    def merged_text(self) -> str:
        paras = []
        for i, seg in enumerate(self._segs):
            if seg["type"] == "same" or self._picks[i] == "same":
                paras.append(seg["original"])
            elif self._picks[i] == "revised":
                paras.append(seg["revised"])
            else:
                paras.append(seg["original"])
        return "\n\n".join(paras)

    def _refresh_views(self):
        # 用户手动编辑过合并框就不再覆盖(保留手改内容)
        if getattr(self, "_manual_edit", False):
            return
        if hasattr(self, "merged_view"):
            self.merged_view.setPlainText(self.merged_text())

    def _complete(self):
        merged = self.merged_view.toPlainText().strip()
        if len(merged) < 50:
            err("合并结果为空或过短")
            return
        self._on_complete(merged)
        self.accept()
