# -*- coding: utf-8 -*-
"""设置对话框:AI 服务 / 通用(15 语言+主题)/ 风格预设 / Agent 配置 / 存储 / 关于更新。"""
from __future__ import annotations

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QStackedWidget, QTabWidget, QVBoxLayout, QWidget)

from .confirm import ask, warn
from ..agents import prompts
from ..ai import face_swap as fs_mod
from ..ai import registry
from ..ai.registry import SVC_CN
from ..ai.image_client import test_config as img_test
from ..ai.text_client import test_config as text_test
from ..ai.tts_client import test_config as tts_test
from ..ai.video_client import test_config as video_test
from ..core import config, db
from ..core.i18n import LANGS, tr
from . import widgets as W
from .braille import WaitingButton
from .toast import err, ok as ok_toast

from ..ai.jev_client import test_config as jev_test  # noqa: E402

TESTERS = {"text": text_test, "image": img_test, "video": video_test,
           "tts": tts_test, "faceswap": fs_mod.test_config, "jev": jev_test}
SVC_LABEL = {"text": "text_svc", "image": "image_svc", "video": "video_svc",
             "tts": "tts_svc", "faceswap": "faceswap_svc", "jev": "jev_svc"}
SVC_DESC = {"text": "svc_text_desc", "image": "svc_image_desc",
            "video": "svc_video_desc", "tts": "svc_tts_desc",
            "faceswap": "本地或远程 InsightFace 换脸服务(角色形象换脸/换脸工具页)",
            "jev": "状态台账门控(TypeSafe AI):长篇连续性自动判读。未配置时台账照常维护,只是不做矛盾判定"}


class SettingsDialog(QDialog):
    # 更新下载进度:updater 在工作线程里回调,靠这个信号回主线程驱动进度条
    download_progress = Signal(int, int)
    def __init__(self, parent=None, on_language_changed=None, on_theme_changed=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings"))
        self.resize(880, 620)
        self._on_lang = on_language_changed
        self._on_theme = on_theme_changed
        root = QHBoxLayout(self)
        self.tabs_nav = QListWidget()
        self.tabs_nav.setFixedWidth(150)
        for key, icon in [("ai_services", "🔌"), ("general", "⚙️"), ("style_presets", "◑"),
                          ("agent_config", "🤖"), ("storage", "💾"), ("about_update", "ℹ️")]:
            item = QListWidgetItem(f"{icon}  {tr(key)}")
            self.tabs_nav.addItem(item)
        root.addWidget(self.tabs_nav)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.pages = [self._page_ai(), self._page_general(), self._page_styles(),
                      self._page_agents(), self._page_storage(), self._page_about()]
        for p in self.pages:
            self.stack.addWidget(p)
        self.tabs_nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.tabs_nav.setCurrentRow(0)

    # ── AI 服务 ──
    def _page_ai(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        quick = W.make_card()
        q_lay = QVBoxLayout(quick)
        q_lay.setContentsMargins(14, 12, 14, 12)
        q_lay.addWidget(W.h2(tr("quick_config") + tr(" · 推荐")))
        q_lay.addWidget(W.muted(tr("quick_hint")))
        row = QHBoxLayout()
        self.yihao_key = QLineEdit()
        self.yihao_key.setPlaceholderText("Yihao API Key")
        apply_btn = W.primary_btn(tr("write_config"))
        apply_btn.clicked.connect(self._apply_yihao)
        row.addWidget(self.yihao_key, 1)
        row.addWidget(apply_btn)
        q_lay.addLayout(row)
        lay.addWidget(quick)

        # 手动模板(对齐原版:选服务类型直接填推荐 provider/base URL/model)
        manual = W.make_card()
        m_lay = QVBoxLayout(manual)
        m_lay.setContentsMargins(14, 12, 14, 12)
        m_lay.addWidget(W.h2(tr("manual_templates")))
        m_lay.addWidget(W.muted(tr("选择服务类型后,直接用模板填充推荐的 `provider / base URL / model`。")))
        chips = QHBoxLayout()
        for st in registry.SERVICE_TYPES:
            b = QPushButton(tr(SVC_LABEL[st]))
            b.setStyleSheet("QPushButton{border-radius:14px;padding:5px 18px;background:rgba(128,128,128,30);font-weight:600;}")
            b.clicked.connect(lambda _=False, s=st: self._add_service(s))
            chips.addWidget(b)
        chips.addStretch(1)
        m_lay.addLayout(chips)
        lay.addWidget(manual)

        self.svc_tabs = QTabWidget()
        self._svc_hosts: dict[str, QWidget] = {}
        self._svc_empties: dict[str, QLabel] = {}
        for st in registry.SERVICE_TYPES:
            tab = QWidget()
            t_lay = QVBoxLayout(tab)
            t_lay.setContentsMargins(12, 10, 12, 10)
            t_lay.setSpacing(8)
            desc = SVC_DESC[st]
            bar = QHBoxLayout()
            bar.addWidget(W.muted(tr(desc)))
            bar.addStretch(1)
            add = QPushButton("＋ " + tr("add"))
            add.clicked.connect(lambda _=False, s=st: self._add_service(s))
            bar.addWidget(add)
            t_lay.addLayout(bar)
            host = QWidget()
            host_lay = QVBoxLayout(host)
            host_lay.setContentsMargins(0, 0, 0, 0)
            host_lay.setSpacing(8)
            self._svc_hosts[st] = host
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
            scroll.setWidget(host)
            t_lay.addWidget(scroll, 1)
            empty = QLabel(tr("svc_empty"))
            empty.setObjectName("muted")
            empty.setAlignment(Qt.AlignCenter)
            self._svc_empties[st] = empty
            t_lay.addWidget(empty)
            self.svc_tabs.addTab(tab, tr(SVC_LABEL[st]))
            self._fill_services(st)
        lay.addWidget(self.svc_tabs, 1)
        return w

    def _fill_services(self, st: str):
        """把该类型的配置渲染成卡片行(启用开关 / 模型 chips / 测试 / 编辑 / 删除)。"""
        host = self._svc_hosts.get(st)
        if not host:
            return
        host_lay = host.layout()
        while host_lay.count():
            it = host_lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        rows = registry.list_configs(st)
        for cfg in rows:
            host_lay.addWidget(ServiceCard(
                dict(cfg), self,
                on_toggle=self._toggle_service,
                on_test=self._test_service,
                on_edit=self._edit_service_by_id,
                on_delete=self._delete_service,
                on_set_default_model=self._set_default_model))
        host_lay.addStretch(1)
        empty = self._svc_empties.get(st)
        if empty:
            empty.setVisible(not rows)

    def _apply_yihao(self):
        key = self.yihao_key.text().strip()
        if not key:
            return
        created = registry.apply_yihao_key(key)
        for st in registry.SERVICE_TYPES:
            self._fill_services(st)
        QMessageBox.information(self, tr("write_config"), "\n".join(created))

    def _add_service(self, st: str):
        dlg = ServiceDialog(st, self)
        if dlg.exec() == QDialog.Accepted:
            d = dlg.data()
            registry.add_config(st, d["provider"], d["base_url"], d["model"],
                                api_key=d["api_key"], remark=d["name"],
                                priority=d["priority"], models=d["models"],
                                temperature=d["temperature"])
            self._fill_services(st)

    def _edit_service_by_id(self, cfg: dict):
        cfg = dict(cfg)
        st = cfg["service_type"]
        dlg = ServiceDialog(st, self, existing=cfg)
        if dlg.exec() == QDialog.Accepted:
            d = dlg.data()
            registry.update_config(cfg["id"], provider=d["provider"], base_url=d["base_url"],
                                    model=d["model"], api_key=d["api_key"],
                                    remark=d["name"], priority=d["priority"],
                                    models=d["models"], temperature=d["temperature"])
            self._fill_services(st)

    def _toggle_service(self, cfg: dict, on: bool):
        """启用/停用一条配置(对齐原版逐行开关)。"""
        registry.update_config(cfg["id"], is_active=1 if on else 0)
        self._fill_services(cfg["service_type"])

    def _set_default_model(self, cfg: dict, model: str):
        """点模型 chip 把它设为该配置的默认模型(models 首位)。"""
        models = _cfg_models(cfg)
        if model in models:
            models.remove(model)
        models.insert(0, model)
        registry.update_config(cfg["id"], model=model, models=json.dumps(models, ensure_ascii=False))
        self._fill_services(cfg["service_type"])

    def _test_service(self, cfg: dict):
        """逐行连通测试(对齐原版 Test 按钮)。"""
        tester = TESTERS.get(cfg["service_type"])
        if not tester:
            return
        card = self.sender()
        btn = getattr(card, "test_btn", None) or self.sender()
        try:
            ok, msg = tester(cfg)
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, str(exc)[:300]
        if btn is not None and hasattr(btn, "idle"):
            btn.idle()
        if ok:
            ok_toast(tr("test_ok") + ": " + msg)
        else:
            err(tr("test_fail") + ": " + msg)

    def _delete_service(self, cfg: dict):
        name = cfg.get("remark") or cfg.get("provider")
        if not ask(self, tr("delete"), tr("confirm_delete_service", name), danger=True):
            return
        registry.delete_config(cfg["id"])
        self._fill_services(cfg["service_type"])

    # ── 通用(语言 15 种 + 主题) ──
    def _page_general(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(14)
        box = W.make_card()
        f = QFormLayout(box)
        f.setContentsMargins(14, 14, 14, 14)
        # 15 语种网格选择器(对齐原版 lang-picker-grid:5 列网格,点即用)
        self.lang_btns: dict[str, QPushButton] = {}
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        cur = db.get_setting("content_language", "zh")
        for i, (code, name) in enumerate(LANGS):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(code == cur)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=code: self._pick_lang(c))
            self.lang_btns[code] = b
            grid.addWidget(b, i // 5, i % 5)
        f.addRow(tr("ui_language"), grid_holder)
        f.addRow("", W.muted(tr("language_note") + "  ·  UI × 15 / AI × 15"))
        theme_box = QWidget()
        trow = QHBoxLayout(theme_box)
        trow.setContentsMargins(0, 0, 0, 0)
        self.theme_combo = QComboBox()
        for key, label in [("light", tr("light")), ("dark", tr("dark")), ("system", tr("follow_system"))]:
            self.theme_combo.addItem(label, key)
        cur_t = db.get_setting("theme", "light")
        j = self.theme_combo.findData(cur_t)
        self.theme_combo.setCurrentIndex(j if j >= 0 else 0)
        self.theme_combo.currentIndexChanged.connect(self._change_theme)
        trow.addWidget(self.theme_combo)
        trow.addStretch(1)
        f.addRow(tr("theme"), theme_box)

        # 界面字体:系统字体 + 项目打包字体(片头那批也可选作正文)
        from PySide6.QtGui import QFontDatabase
        font_box = QWidget()
        frow = QHBoxLayout(font_box)
        frow.setContentsMargins(0, 0, 0, 0)
        self.font_combo = QComboBox()
        self.font_combo.setMinimumWidth(240)
        self.font_combo.addItem(tr("font_follow_system"), "")
        from ..core.theme import UI_FONT_CANDIDATES
        for fam in UI_FONT_CANDIDATES:
            self.font_combo.addItem(fam, fam)
        have = set(QFontDatabase.families())
        for fam in sorted(f for f in have if f not in UI_FONT_CANDIDATES):
            self.font_combo.addItem(fam, fam)
        j = self.font_combo.findData(db.get_setting("ui_font", ""))
        self.font_combo.setCurrentIndex(max(0, j))
        self.font_combo.currentIndexChanged.connect(self._change_font)
        frow.addWidget(self.font_combo)
        apply_btn = QPushButton(tr("font_preview"))
        apply_btn.clicked.connect(self._change_font)
        frow.addWidget(apply_btn)
        frow.addStretch(1)
        f.addRow(tr("ui_font"), font_box)
        f.addRow("", W.muted(tr("ui_font_note")))
        lay.addWidget(box)
        lay.addStretch(1)
        return w

    def _change_font(self):
        """切换界面字体,立即生效(重贴 QSS + 重设应用默认字体)。"""
        fam = self.font_combo.currentData() or ""
        db.set_setting("ui_font", fam)
        from PySide6.QtWidgets import QApplication
        from ..core.theme import apply_theme, db_get_setting
        mode = db.get_setting("theme", "light")
        if mode == "system":
            mode = "light"
        apply_theme(QApplication.instance(), mode, preferred=fam)

    def _pick_lang(self, lang: str):
        for code, b in self.lang_btns.items():
            b.setChecked(code == lang)
        db.set_setting("content_language", lang)
        db.set_setting("ui_language", lang)
        from ..core.i18n import set_language
        set_language(lang)
        if self._on_lang:
            self._on_lang(lang)

    def _change_theme(self):
        mode = self.theme_combo.currentData()
        db.set_setting("theme", mode)
        if self._on_theme:
            self._on_theme(mode)

    # ── 风格预设 ──
    def _page_styles(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        self.style_list = QListWidget()
        for r in db.q("SELECT * FROM style_presets ORDER BY sort_order"):
            active = "✅" if r["is_active"] else "⛔"
            item = QListWidgetItem(f"{active}  {r['name']}  ·  {r['description'] or ''}")
            item.setData(Qt.UserRole, dict(r))
            self.style_list.addItem(item)
        self.style_list.itemDoubleClicked.connect(self._edit_style)
        lay.addWidget(W.muted(tr("双击编辑风格 · 电影质感提示词前缀")))
        lay.addWidget(self.style_list)
        return w

    def _edit_style(self, item: QListWidgetItem):
        row = item.data(Qt.UserRole)
        dlg = _StyleDialog(dict(row), self)
        if dlg.exec() == QDialog.Accepted:
            d = dlg.data()
            db.ex("UPDATE style_presets SET name=?, prompt=?, description=?, is_active=? WHERE id=?",
                  (d["name"], d["prompt"], d["description"], d["is_active"], row["id"]))
            self._refresh_styles()

    def _refresh_styles(self):
        self.style_list.clear()
        for r in db.q("SELECT * FROM style_presets ORDER BY sort_order"):
            active = "✅" if r["is_active"] else "⛔"
            item = QListWidgetItem(f"{active}  {r['name']}  ·  {r['description'] or ''}")
            item.setData(Qt.UserRole, dict(r))
            self.style_list.addItem(item)

    # ── Agent 配置 ──
    def _page_agents(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        # 左侧 Agent 列表(带技能数量徽标,对齐原版)
        self.agent_list = QListWidget()
        self.agent_list.setFixedWidth(230)
        for a in prompts.AGENT_META:
            n = len(prompts.list_skills(a["type"]))
            badge = f"  [{n}]" if n else ""
            QListWidgetItem(f"{a['icon']}  {a['name']}{badge}", self.agent_list)
        lay.addWidget(self.agent_list)

        right = QVBoxLayout()
        head = QHBoxLayout()
        head.addWidget(W.h2(""))
        self.agent_title = W.h2("")
        head.addWidget(self.agent_title)
        head.addStretch(1)
        self.agent_lang = QComboBox()
        for code, name in LANGS:
            self.agent_lang.addItem(name, code)
        self.agent_lang.setCurrentIndex(0)
        self.agent_lang.currentIndexChanged.connect(self._load_agent_content)
        head.addWidget(self.agent_lang)
        right.addLayout(head)

        # 双标签:System Prompt / Skills(对齐原版)
        self.agent_tabs = QTabWidget()
        prompt_page = QWidget()
        p_lay = QVBoxLayout(prompt_page)
        p_lay.setContentsMargins(0, 10, 0, 0)
        self.prompt_path_lab = W.muted("")
        p_lay.addWidget(self.prompt_path_lab)
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setMinimumHeight(320)
        p_lay.addWidget(self.prompt_edit, 1)
        p_btns = QHBoxLayout()
        p_save = W.primary_btn(tr("save"))
        p_save.clicked.connect(self._save_agent_prompt)
        p_reset = QPushButton(tr("restore_default"))
        p_reset.clicked.connect(self._reset_agent_prompt)
        p_btns.addWidget(p_save)
        p_btns.addWidget(p_reset)
        p_btns.addStretch(1)
        p_lay.addLayout(p_btns)
        self.agent_tabs.addTab(prompt_page, tr("system_prompt"))

        skill_page = QWidget()
        s_lay = QVBoxLayout(skill_page)
        s_lay.setContentsMargins(0, 10, 0, 0)
        s_split = QHBoxLayout()
        self.skill_list = QListWidget()
        self.skill_list.setFixedWidth(200)
        self.skill_list.currentRowChanged.connect(self._load_skill)
        self.skill_path_lab = W.muted("")
        self.skill_edit = QPlainTextEdit()
        s_split.addWidget(self.skill_list)
        right_col = QVBoxLayout()
        right_col.addWidget(self.skill_path_lab)
        right_col.addWidget(self.skill_edit, 1)
        s_btns = QHBoxLayout()
        s_save = W.primary_btn(tr("save"))
        s_save.clicked.connect(self._save_skill)
        s_reset = QPushButton(tr("restore_default"))
        s_reset.clicked.connect(self._reset_skill)
        s_btns.addWidget(s_save)
        s_btns.addWidget(s_reset)
        s_btns.addStretch(1)
        right_col.addLayout(s_btns)
        s_split.addLayout(right_col, 1)
        s_lay.addLayout(s_split)
        self.agent_tabs.addTab(skill_page, "Skills")
        right.addWidget(self.agent_tabs, 1)
        lay.addLayout(right, 1)

        self.agent_list.currentRowChanged.connect(lambda _i: self._load_agent_content())
        self.agent_list.setCurrentRow(0)
        self._load_agent_content()
        return w

    def _current_agent(self) -> str:
        row = self.agent_list.currentRow()
        if 0 <= row < len(prompts.AGENT_META):
            return prompts.AGENT_META[row]["type"]
        return ""

    def _load_agent_content(self):
        agent = self._current_agent()
        if not agent:
            return
        meta = next((a for a in prompts.AGENT_META if a["type"] == agent), {})
        self.agent_title.setText(f"{meta.get('icon','')} {meta.get('name', agent)}")
        lang = self.agent_lang.currentData()
        # System Prompt
        path = prompts.prompt_file(agent, lang)
        text = path.read_text(encoding="utf-8") if path.exists() else prompts.DEFAULT_PROMPTS.get(agent, "")
        self.prompt_edit.setPlainText(text)
        self.prompt_path_lab.setText(tr("prompt_saved").format(agent)
                                      + (f".{lang}" if lang != "zh" else ""))
        # Skills
        self.skill_list.blockSignals(True)
        self.skill_list.clear()
        self._skills = prompts.list_skills(agent)
        for sk in self._skills:
            self.skill_list.addItem(sk["name"])
        self.skill_list.blockSignals(False)
        if self._skills:
            self.skill_list.setCurrentRow(0)
        self._load_skill()

    def _current_skill_id(self) -> str:
        row = self.skill_list.currentRow()
        if 0 <= row < len(getattr(self, "_skills", [])):
            return self._skills[row]["id"]
        return ""

    def _load_skill(self):
        sid = self._current_skill_id()
        if not sid:
            self.skill_edit.setPlainText("")
            self.skill_path_lab.setText("")
            return
        lang = self.agent_lang.currentData()
        self.skill_edit.setPlainText(prompts.load_skill(sid, lang))
        self.skill_path_lab.setText(f"skills/{sid}/SKILL.md"
                                    + (f".{lang}" if lang != "zh" else ""))

    def _save_agent_prompt(self):
        agent = self._current_agent()
        if agent:
            prompts.save_prompt(agent, self.agent_lang.currentData(), self.prompt_edit.toPlainText())

    def _reset_agent_prompt(self):
        agent = self._current_agent()
        if agent:
            prompts.reset_prompt(agent, self.agent_lang.currentData())
            self._load_agent_content()

    def _save_skill(self):
        sid = self._current_skill_id()
        if sid:
            prompts.save_skill(sid, self.skill_edit.toPlainText())

    def _reset_skill(self):
        sid = self._current_skill_id()
        if sid:
            prompts.reset_skill(sid)
            self._load_skill()

    # ── 存储 ──
    def _page_storage(self) -> QWidget:
        """存储用量卡(对齐参考项目 routes/storage.ts):分桶统计 + 剩余空间 + 打开目录。"""
        from ..core import storage
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)
        box = W.make_card()
        f = QFormLayout(box)
        f.setContentsMargins(14, 14, 14, 14)
        self._storage_labels: dict[str, QLabel] = {}
        self._refresh_storage(f)
        open_btn = QPushButton(tr("打开数据目录"))
        open_btn.clicked.connect(lambda: __import__("os").startfile(str(config.DATA_DIR)))  # noqa
        f.addRow("", open_btn)
        lay.addWidget(box)
        hint = W.muted(tr("用量每 60 秒刷新一次;数据库文件(含 WAL)单独计数,不在目录遍历里"))
        lay.addWidget(hint)
        lay.addStretch(1)
        return w

    def _refresh_storage(self, form: QFormLayout | None = None) -> None:
        """重算并刷新各分桶用量行。"""
        from ..core import storage
        data = storage.get_usage()
        buckets = data.get("buckets") or {}
        for key, label in storage.BUCKET_CN.items():
            size = storage.human_size(buckets.get(key, 0))
            if form is not None:
                row = QLabel(size)
                self._storage_labels[key] = row
                form.addRow(label, row)
            elif key in self._storage_labels:
                self._storage_labels[key].setText(size)
        total = QLabel(storage.human_size(data.get("used", 0)))
        free = QLabel(storage.human_size(data.get("free", 0)))
        if form is not None:
            form.addRow("◆", total)
            self._storage_labels["used"] = total
            form.addRow(tr("剩余可用"), free)
            self._storage_labels["free"] = free
        else:
            self._storage_labels.get("used", total).setText(storage.human_size(data.get("used", 0)))
            self._storage_labels.get("free", free).setText(storage.human_size(data.get("free", 0)))

    # ── 关于 ──
    def _page_about(self) -> QWidget:
        from ..core import updater
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(W.h2(f"易好短剧 · {tr('version')} {config.APP_VERSION}"))
        lay.addWidget(W.muted(tr("「易好短剧」(Yihao Drama) 的 PySide6 桌面实现,功能对齐原版。")))
        lay.addWidget(W.muted(f"语言 / Languages: {len(LANGS)}(中文/EN/日本語/한국어/Français/Deutsch/Italiano/Português/Español/Tiếng Việt/Türkçe/العربية/हिन्दी/Bahasa Indonesia/ภาษาไทย)"))
        lay.addWidget(W.muted("核心:10 Agents · 11 Skills · 20 风格预设 · 无损合并(easymerger) · 同款复刻(video-clone-lite) · 封面体系"))

        box = W.make_card()
        b_lay = QVBoxLayout(box)
        b_lay.setContentsMargins(14, 12, 14, 12)
        row = QHBoxLayout()
        self.ver_lab = W.muted(f"{tr('version')} {updater.current_version()}")
        row.addWidget(self.ver_lab)
        row.addStretch(1)
        self.auto_update_cb = QCheckBox(tr("启动时自动检查更新"))
        self.auto_update_cb.setChecked(updater.read_state().get("auto_check", True))
        self.auto_update_cb.toggled.connect(
            lambda on: updater.write_state(auto_check=on))
        row.addWidget(self.auto_update_cb)
        check = QPushButton(tr("check_update"))
        check.clicked.connect(self._check_update)
        row.addWidget(check)
        b_lay.addLayout(row)
        self.update_lab = W.muted("")
        self.update_lab.setWordWrap(True)
        b_lay.addWidget(self.update_lab)
        self.notes_lab = QPlainTextEdit()
        self.notes_lab.setReadOnly(True)
        self.notes_lab.setMaximumHeight(110)
        self.notes_lab.setVisible(False)
        b_lay.addWidget(self.notes_lab)
        self.upd_btn = W.primary_btn(tr("⬇ 立即下载并更新"))
        self.upd_btn.setVisible(False)
        self.upd_btn.clicked.connect(self._do_update)
        b_lay.addWidget(self.upd_btn)
        self.prog = QProgressBar()
        self.prog.setVisible(False)
        b_lay.addWidget(self.prog)
        lay.addWidget(box)
        lay.addWidget(W.muted(f"更新源:{updater.FEED_URL}"))
        lay.addStretch(1)
        self._upd_result = {}
        return w

    def _check_update(self):
        """检查更新(后台线程,避免阻塞界面)。"""
        from PySide6.QtCore import QThread
        self.download_progress.connect(self._on_download_progress)
        from ..core import updater
        self.update_lab.setText(tr("正在检查更新…"))
        res_holder = {}

        class _T(QThread):
            def run(self):
                res_holder["r"] = updater.check()
        th = _T()
        th.finished.connect(lambda: self._show_update_result(res_holder.get("r", {})))
        th.start()
        self._upd_thread = th

    def _show_update_result(self, r: dict):
        if r.get("error"):
            self.update_lab.setText("❌ " + r["error"])
            self.upd_btn.setVisible(False)
            self.notes_lab.setVisible(False)
            return
        if r.get("has_update"):
            self.update_lab.setText(f"发现新版本 v{r['latest']}(当前 v{r['current']})")
            if r.get("notes"):
                self.notes_lab.setPlainText(r["notes"])
                self.notes_lab.setVisible(True)
            self.upd_btn.setVisible(bool(r.get("url")))
            self._upd_result = r
        else:
            self.update_lab.setText(f"✅ 已是最新版本(v{r['latest']})")
            self.upd_btn.setVisible(False)
            self.notes_lab.setVisible(False)

    def _on_download_progress(self, done: int, total: int) -> None:
        """下载进度回主线程:总长未知就保持转圈,已知就显示百分比。"""
        if total > 0:
            self.prog.setRange(0, total)
            self.prog.setValue(done)
        else:
            self.prog.setRange(0, 0)

    def _do_update(self):
        """下载并应用更新,完成后询问重启。"""
        from PySide6.QtCore import QThread
        from ..core import updater
        url = self._upd_result.get("url", "")
        if not url:
            warn(self, tr("update"), tr("update_failed_no_url"))
            return
        self.prog.setVisible(True)
        self.prog.setRange(0, 0)          # 拿不到总长时先转圈,拿到就转确定进度
        self.upd_btn.setEnabled(False)
        out = {}

        class _T(QThread):
            def run(self):
                try:
                    # 信号是线程安全的:工作线程发,主线程收到再动进度条
                    out["files"] = updater.do_update(
                        url, lambda d, t: self.download_progress.emit(d, t))
                except Exception as e:  # noqa: BLE001
                    out["err"] = str(e)
        th = _T()

        def finished():
            self.prog.setVisible(False)
            self.upd_btn.setEnabled(True)
            if out.get("err"):
                warn(self, tr("update"), tr("update_failed") + str(out["err"])[:300])
                return
            n = len(out.get("files", []))
            if ask(self, tr("update"), tr("update_restart_q", n)):
                updater.restart_app()
        th.finished.connect(finished)
        th.start()
        self._upd_thread2 = th

class _FlowLayout(QWidget):
    """真流式布局:子控件按可用宽度自动换行(模型标签/芯片用)。

    用 move/resizeEvent 手动摆放;QHBoxLayout 不会换行,标签一多就会挤在一起文字重叠。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[QWidget] = []
        self._h = 30
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

    def add(self, w: QWidget):
        self._items.append(w)
        w.setParent(self)
        w.show()
        self._relayout()

    def clear(self):
        for w in self._items:
            w.setParent(None)
            w.deleteLater()
        self._items = []
        self._h = 30

    def _relayout(self):
        if not self._items:
            return
        x = y = line_h = 0
        maxw = max(1, self.width() - 2)
        for w in self._items:
            w.adjustSize()
            ww, hh = w.width(), w.height()
            if x > 0 and x + ww > maxw:
                x = 0
                y += line_h + 8
                line_h = 0
            w.move(x, y)
            x += ww + 8
            line_h = max(line_h, hh)
        self._h = max(30, y + line_h)
        self.setMinimumHeight(self._h)
        self.updateGeometry()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._relayout()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self.width(), self._h)

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(120, self._h)


def _muted(text: str) -> QLabel:
    return W.muted(text)


class ModelChipsEditor(QWidget):
    """多模型标签编辑器(对齐原版):首位为默认模型;点标签置顶;× 删除;输入框支持逗号/换行批量。"""
    changed = Signal()

    def __init__(self, models=None):
        super().__init__()
        self.models = [m for m in (models or []) if m]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.flow = _FlowLayout()
        lay.addWidget(self.flow)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(tr("输入模型名,回车添加(支持逗号/换行批量粘贴)"))
        self.input.returnPressed.connect(self._add_from_input)
        add_btn = QPushButton(tr("新增"))
        add_btn.clicked.connect(self._add_from_input)
        row.addWidget(self.input, 1)
        row.addWidget(add_btn)
        lay.addLayout(row)
        lay.addWidget(_muted(tr("首位为默认模型;点击标签可置顶,输入框支持逗号/换行批量粘贴")))
        self._render()

    def _render(self):
        self.flow.clear()
        for i, m in enumerate(list(self.models)):
            chip = QPushButton(m + (tr("  默认") if i == 0 else ""))
            chip.setToolTip(tr("点击置顶设为默认"))
            chip.setStyleSheet(
                "QPushButton{border-radius:12px; padding:3px 10px; font-size:12px;}"
                + ("QPushButton{background:#f97316;color:white;font-weight:700;border:none;}"
                   if i == 0 else "QPushButton{background:rgba(128,128,128,35);}"))
            chip.clicked.connect(lambda _=False, idx=i: self._promote(idx))
            self.flow.add(chip)
            x = QPushButton("×")
            x.setFixedSize(22, 22)
            x.setStyleSheet("QPushButton{border:none;background:transparent;color:#888;font-weight:700;}")
            x.clicked.connect(lambda _=False, idx=i: self._remove(idx))
            self.flow.add(x)

    def _promote(self, idx: int):
        if idx <= 0:
            return
        self.models.insert(0, self.models.pop(idx))
        self._render()
        self.changed.emit()

    def _remove(self, idx: int):
        self.models.pop(idx)
        self._render()
        self.changed.emit()

    def _add_from_input(self):
        import re as _re
        for part in _re.split(r"[,\n;，；]", self.input.text()):
            p = part.strip()
            if p and p not in self.models:
                self.models.append(p)
        self.input.clear()
        self._render()
        self.changed.emit()

    def set_models(self, models):
        self.models = [m for m in (models or []) if m]
        self._render()
        self.changed.emit()


class ServiceCard(QFrame):
    """一条 AI 服务配置卡片:徽章 + 名称/Key 标 + 模型 chips + 开关 + 测试/编辑/删除。

    对齐原版 settings.vue 的 config card(provider logo badge、名称、「有 Key/无 Key」标、
    「已停用」标、点击 model chip 设默认、逐行 Test、启用开关、编辑、删除)。
    """

    def __init__(self, cfg: dict, parent, on_toggle=None, on_test=None,
                 on_edit=None, on_delete=None, on_set_default_model=None):
        super().__init__()
        self.cfg = cfg
        self.setObjectName("svcCard")
        self.setEnabled(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        # 供应商标识徽章(取首字母,原版是 provider logo)
        badge = QLabel((cfg.get("remark") or cfg.get("provider") or "?")[:1].upper())
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignCenter)
        badge.setObjectName("svcBadge")
        badge.setStyleSheet(
            f"background:{_provider_tint(cfg.get('provider'))}; color:#fff;"
            "border-radius:7px; font-weight:800;")
        head.addWidget(badge)
        name = QLabel(cfg.get("remark") or cfg.get("provider") or "")
        f = name.font()
        f.setBold(True)
        name.setFont(f)
        name.setToolTip(f"{cfg.get('provider')}  ·  {cfg.get('base_url')}")
        head.addWidget(name)
        head.addWidget(W.tag(tr("configured") if cfg.get("api_key") else tr("no_key")))
        if cfg.get("is_default"):
            head.addWidget(self._tag_orange(tr("default")))
        if not cfg.get("is_active"):
            off = W.tag(tr("stopped"))
            off.setStyleSheet("background:#fdecec;color:#dc2626;border-radius:4px;padding:2px 8px;")
            head.addWidget(off)
        head.addStretch(1)
        head.addWidget(W.tag(f"P{cfg.get('priority') or 0}"))
        # 启用开关
        self.toggle = QCheckBox("")
        self.toggle.setChecked(bool(cfg.get("is_active")))
        self.toggle.setToolTip(tr("toggle_enabled"))
        self.toggle.toggled.connect(lambda on: on_toggle(cfg, on) if on_toggle else None)
        head.addWidget(self.toggle)
        lay.addLayout(head)

        # 模型 chips:点一下即设为该配置的默认模型
        models = _cfg_models(cfg)
        if models:
            chips = _FlowLayout()
            for i, m in enumerate(models):
                is_default = (i == 0)
                chip = QPushButton(("★ " if is_default else "") + m)
                chip.setToolTip(tr("click_set_default_model") if not is_default
                                else tr("is_default_model"))
                # 单个选择器(拼接两个 QPushButton{} 规则会让 Qt 报解析失败)
                chip.setStyleSheet(
                    "QPushButton{border-radius:12px;padding:3px 10px;font-size:12px;"
                    + "background:#f97316;color:#ffffff;font-weight:700;border:none;}"
                    if is_default else
                    "QPushButton{border-radius:12px;padding:3px 10px;font-size:12px;"
                    "background:rgba(128,128,128,35);}")
                if not is_default and on_set_default_model:
                    chip.setCursor(Qt.PointingHandCursor)
                    chip.clicked.connect(
                        lambda _=False, mm=m: on_set_default_model(cfg, mm))
                chips.add(chip)
            lay.addWidget(chips)
        else:
            lay.addWidget(W.muted(tr("no_models_yet")))

        base = QLabel(cfg.get("base_url") or "")
        base.setObjectName("muted")
        base.setToolTip(base.text())
        lay.addWidget(base)

        # 动作行
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.test_btn = WaitingButton(tr("test"))
        self.test_btn.setFixedHeight(26)
        self.test_btn.clicked.connect(lambda: on_test(cfg) if on_test else None)
        actions.addWidget(self.test_btn)
        actions.addStretch(1)
        edit = QPushButton("✎ " + tr("edit"))
        edit.setFixedHeight(26)
        edit.clicked.connect(lambda: on_edit(cfg) if on_edit else None)
        actions.addWidget(edit)
        delete = QPushButton("🗑 " + tr("delete"))
        delete.setObjectName("danger")
        delete.setFixedHeight(26)
        delete.clicked.connect(lambda: on_delete(cfg) if on_delete else None)
        actions.addWidget(delete)
        lay.addLayout(actions)

    @staticmethod
    def _tag_orange(text: str) -> QLabel:
        t = W.tag(text)
        t.setStyleSheet("background:#fdf0e6;color:#ea580c;border-radius:4px;padding:2px 8px;")
        return t


def _provider_tint(provider: str | None) -> str:
    """按 provider 给徽章一个稳定颜色(同 provider 同色)。"""
    palette = {"openai": "#10a37f", "gemini": "#4285f4", "volcengine": "#f97316",
               "agnes": "#8b5cf6", "minimax": "#ef4444", "aliyun": "#0ea5e9",
               "qwen-image": "#6366f1", "xiaoyunque": "#ec4899",
               "local-faceswap": "#64748b", "remote-faceswap": "#64748b", "jev": "#14b8a6"}
    return palette.get(provider or "", "#64748b")


def _cfg_models(cfg: dict) -> list[str]:
    """配置上的模型列表:优先 models 数组,否则回落到单个 model。"""
    raw = cfg.get("models")
    if raw:
        try:
            models = json.loads(raw) if isinstance(raw, str) else list(raw)
        except (TypeError, ValueError):
            models = []
        if isinstance(models, list):
            models = [str(m) for m in models if m]
            if models:
                return models
    m = (cfg.get("model") or "").strip()
    return [m] if m else []

class ServiceDialog(QDialog):
    """添加/编辑 AI 服务(对齐原版「添加文本服务」界面):

    模板快选 → 配置名称/服务商/优先级/API Key/Base URL/多模型标签/Temperature → 测试配置/保存。
    """

    def __init__(self, st: str, parent=None, existing=None):
        super().__init__(parent)
        import json as _json
        self._st = st
        self._existing = existing
        cn = SVC_CN[st]
        self.setWindowTitle((tr("编辑") if existing else tr("添加")) + cn + tr("服务"))
        self.resize(560, 760)
        root = QVBoxLayout(self)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(W.h2((tr("编辑") if existing else tr("添加")) + cn + tr("服务")))
        head.addStretch(1)
        head.addWidget(W.tag(cn))
        root.addLayout(head)
        root.addWidget(_muted(tr("选择「服务商」后会自动填入更合理的 `Base URL` 与默认模型;需要其他厂商时选「自定义」直接填写。")))

        form = QFormLayout()
        form.setSpacing(8)
        self.name_edit = QLineEdit()
        form.addRow(tr("配置名称"), self.name_edit)
        # 服务商:模板 label 与自定义合并为一个下拉(对齐原版 26c7d00,消除两处选供应商的困惑)
        self.provider_combo = QComboBox()
        self._tpl_by_index: dict[int, dict] = {}
        CUSTOM = "__custom__"
        for p in registry.PROVIDER_PRESETS.get(st, []):
            idx = self.provider_combo.count()
            self.provider_combo.addItem(p["name"])       # 显示模板 label,如「MiniMax 官方」
            self._tpl_by_index[idx] = p
        self._custom_idx = self.provider_combo.addItem(tr("自定义…"))
        self.provider_combo.currentIndexChanged.connect(self._on_provider_pick)
        form.addRow(tr("服务商"), self.provider_combo)
        self.provider_edit = QLineEdit()
        self.provider_edit.setPlaceholderText(tr("服务商标识,如 openai / 自定义厂商名"))
        self.provider_edit.setVisible(False)
        form.addRow("", self.provider_edit)
        self.priority_spin = QSpinBox()
        self.priority_spin.setRange(-99, 99)
        self.priority_spin.setValue(0)
        form.addRow(tr("优先级"), self.priority_spin)
        form.addRow("", _muted(tr("数值越高越优先。工作台默认使用同类型里优先级最高的启用配置。")))
        self.api_key = QLineEdit()
        self.api_key.setPlaceholderText("sk-...")
        self.api_key.setEchoMode(QLineEdit.Password)
        form.addRow("API Key", self.api_key)
        self.base_url = QLineEdit()
        form.addRow("Base URL", self.base_url)
        self.models_editor = ModelChipsEditor()
        form.addRow(tr("模型"), self.models_editor)
        self.temperature = QLineEdit()
        self.temperature.setPlaceholderText(tr("如 0.6"))
        form.addRow(tr("Temperature (留空跟随服务默认)"), self.temperature)
        form.addRow("", _muted("部分模型强制固定温度(如 kimi-k2 只允许 0.6),遇 invalid temperature 错误时在此填入对应值"))
        root.addLayout(form)
        root.addStretch(1)

        bottom = QHBoxLayout()
        test_btn = QPushButton(tr("测试配置"))
        test_btn.setStyleSheet("QPushButton{color:#e0794b;border:none;font-weight:700;}")
        test_btn.clicked.connect(self._test)
        cancel = QPushButton(tr("取消"))
        cancel.clicked.connect(self.reject)
        save = W.primary_btn(tr("保存"))
        save.clicked.connect(self._save)
        bottom.addWidget(test_btn)
        bottom.addStretch(1)
        bottom.addWidget(cancel)
        bottom.addWidget(save)
        root.addLayout(bottom)
        self.test_lab = QLabel("")
        self.test_lab.setWordWrap(True)
        root.addWidget(self.test_lab)

        if existing:
            self._prefill(_json)
        elif self._tpl_by_index:
            # 新建时默认选中首个模板并填充(下拉首项不会触发 currentIndexChanged)
            self._on_provider_pick(self.provider_combo.currentIndex())

    def _on_provider_pick(self, idx: int):
        """选中模板 → 自动填配置名 / Base URL / 默认模型(原胶囊行为);选自定义 → 显示原始输入框。"""
        tpl = self._tpl_by_index.get(idx)
        if tpl:
            self.name_edit.setText(f"{tpl['name']}-{SVC_CN[self._st]}")
            self.base_url.setText(tpl["base_url"])
            self.models_editor.set_models(list(tpl["models"]))
            self.provider_edit.setVisible(False)
        else:
            self.provider_edit.setVisible(True)
            self.provider_edit.setFocus()

    def _apply_template(self, p: dict):
        """按模板填充(供测试/外部调用)。"""
        for i, t in self._tpl_by_index.items():
            if t is p:
                self.provider_combo.setCurrentIndex(i)
                return
        self.provider_combo.setCurrentIndex(self._custom_idx)
        self.provider_edit.setText(p["provider"])

    def _prefill(self, _json):
        e = self._existing
        self.name_edit.setText(e.get("remark") or "")
        # 回填:命中模板则选中该项,否则落到自定义
        hit = -1
        for i, t in self._tpl_by_index.items():
            if t["provider"] == e["provider"]:
                hit = i
                break
        if hit >= 0:
            self.provider_combo.setCurrentIndex(hit)
        else:
            self.provider_combo.setCurrentIndex(self._custom_idx)
            self.provider_edit.setText(e["provider"])
        self.priority_spin.setValue(int(e.get("priority") or 0))
        self.api_key.setText(e.get("api_key") or "")
        self.base_url.setText(e.get("base_url") or "")
        models = _json.loads(e["models"]) if e.get("models") else [e["model"]]
        self.models_editor.set_models(models)
        if e.get("temperature") is not None:
            self.temperature.setText(str(e["temperature"]))

    def _current_provider(self) -> str:
        """当前服务商标识:选中模板取其 provider,选自定义取输入框文本。"""
        tpl = self._tpl_by_index.get(self.provider_combo.currentIndex())
        if tpl:
            return tpl["provider"]
        return self.provider_edit.text().strip()

    def _collect(self) -> dict:
        temp_raw = self.temperature.text().strip()
        temperature = None
        if temp_raw:
            try:
                temperature = float(temp_raw)
            except ValueError:
                pass
        models = self.models_editor.models or [""]
        return {"service_type": self._st,
                "name": self.name_edit.text().strip(),
                "provider": self._current_provider(),
                "base_url": self.base_url.text().strip(),
                "api_key": self.api_key.text().strip(),
                "priority": self.priority_spin.value(),
                "models": models,
                "model": models[0],
                "temperature": temperature}

    def _test(self):
        cfg = self._collect()
        ok, msg = TESTERS[cfg["service_type"]](
            {"service_type": cfg["service_type"], "provider": cfg["provider"],
             "base_url": cfg["base_url"], "api_key": cfg["api_key"], "model": cfg["model"]})
        self.test_lab.setText(("✅ " if ok else "❌ ") + msg[:200])

    def _save(self):
        data = self._collect()
        if not data["model"] or not data["base_url"]:
            self.test_lab.setText(tr("❌ Base URL 与至少一个模型必填"))
            return
        self.accept()

    def data(self) -> dict:
        return self._collect()


class _StyleDialog(QDialog):
    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(row["name"])
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit(row["name"])
        self.desc = QLineEdit(row.get("description") or "")
        self.active = QCheckBox(tr("enabled"))
        self.active.setChecked(bool(row["is_active"]))
        f.addRow(tr("visual_style"), self.name)
        f.addRow(tr("描述"), self.desc)
        f.addRow("", self.active)
        lay.addLayout(f)
        self.prompt = QPlainTextEdit(row["prompt"])
        lay.addWidget(self.prompt, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def data(self) -> dict:
        return {"name": self.name.text().strip(), "prompt": self.prompt.toPlainText(),
                "description": self.desc.text().strip(), "is_active": 1 if self.active.isChecked() else 0}
