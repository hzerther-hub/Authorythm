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
from ..core.theme import SLATE_FORM_QSS
from . import widgets as W
from .braille import WaitingButton
from .toast import err, ok as ok_toast

from ..ai.jev_client import test_config as jev_test  # noqa: E402


def _stockphoto_test(cfg: dict) -> tuple[bool, str]:
    """图库连接测试。test_source 只认库里已启用的一行,而设置页测的是**表单里
    还没保存**的值 —— 所以先按 provider 认出来直接测,别指望库里已经有。"""
    from ..ai import stock_photo as sp
    prov = (cfg.get("provider") or "").strip().lower()
    if prov not in sp.SOURCE_ORDER:
        return False, "未知的图库类型"
    key = (cfg.get("api_key") or "").strip()
    if not key:
        return False, "未填 API Key"
    try:
        fn = sp._searcher_for(prov)
        if fn is None:
            return False, "未实现的适配器"
        got = fn(key, "test", 1, 3)
    except Exception as exc:  # noqa: BLE001
        resp = getattr(exc, "response", None)
        code = resp.status_code if resp is not None else None
        if code in (401, 403):
            return False, "API Key 无效或已失效 — 到 key 官网重新申请"
        if code:
            return False, f"HTTP {code}"
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"
    return True, f"可用 · 命中 {len(got)} 张"


TESTERS = {"text": text_test, "image": img_test, "video": video_test,
           "tts": tts_test, "faceswap": fs_mod.test_config, "jev": jev_test,
           "stockphoto": _stockphoto_test}
SVC_LABEL = {"text": "text_svc", "image": "image_svc", "video": "video_svc",
             "tts": "tts_svc", "faceswap": "faceswap_svc", "jev": "jev_svc",
             "stockphoto": "stockphoto_svc"}
SVC_DESC = {"text": "svc_text_desc", "image": "svc_image_desc",
            "video": "svc_video_desc", "tts": "svc_tts_desc",
            "faceswap": "本地或远程 InsightFace 换脸服务(角色形象换脸/换脸工具页)",
            "jev": "状态台账门控(TypeSafe AI):长篇连续性自动判读。未配置时台账照常维护,只是不做矛盾判定",
            "stockphoto": "免费图库检索(Unsplash/Pexels/Pixabay):仅用于「图片处理」「聊天改图」搜参考图,不参与任何生成"}


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
        # Director's Slate: 全局控件表单 slate 化(已在 theme.SLATE_FORM_QSS)。
        # 这里额外覆盖:left nav 的当前行选中态用 slate 边 + 文字,徽章/数字色保留.
        # 搜索/过滤/排序等复合控件因 settings 极少用,依赖级联即可。
        self.setStyleSheet(
            SLATE_FORM_QSS
            + "QListWidget#tabsNav { background: " + "transparent; border: none; } "
            + "QListWidget#tabsNav::item { padding: 9px 14px; color: " + "#4e5969; font-size: 12px; "
              "border-radius: 3px; margin: 0 6px 1px; } "
            + "QListWidget#tabsNav::item:hover { background: #f5f4ef; color: #0e0f12; } "
            + "QListWidget#tabsNav::item:selected { background: #0e0f12; color: #f5f4ef; "
              "font-weight: 700; }"
        )
        self.tabs_nav.setObjectName("tabsNav")

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

        # 申请/安装指南:各服务 key 申请入口 + 软件下载说明(docs/API申请与软件安装指南.md)
        guide_row = QHBoxLayout()
        guide_btn = QPushButton("📖 " + tr("查看 API 申请与软件安装指南"))
        guide_btn.setCursor(Qt.PointingHandCursor)
        guide_btn.setStyleSheet(
            "QPushButton{border:1px solid #DCDAD3;border-radius:3px;padding:5px 14px;"
            "background:transparent;color:#1F2329;font-weight:600;}"
            "QPushButton:hover{border-color:#f97316;color:#f97316;}")
        def _open_guide():
            import os as _os
            p = config.ROOT_DIR / "docs" / "API申请与软件安装指南.md"
            if p.exists():
                _os.startfile(str(p))
            else:
                from .toast import err as _err
                _err(f"指南文件不存在:{p}")
        guide_btn.clicked.connect(_open_guide)
        guide_row.addWidget(guide_btn)
        guide_row.addStretch(1)
        lay.addLayout(guide_row)

        # 手动模板(对齐原版:选服务类型直接填推荐 provider/base URL/model)
        manual = W.make_card()
        m_lay = QVBoxLayout(manual)
        m_lay.setContentsMargins(14, 12, 14, 12)
        m_lay.addWidget(W.h2(tr("manual_templates")))
        m_lay.addWidget(W.muted(tr("选择服务类型后,直接用模板填充推荐的 `provider / base URL / model`。")))
        chips = QHBoxLayout()
        for st in registry.SERVICE_TYPES:
            b = QPushButton(tr(SVC_LABEL[st]))
            b.setStyleSheet(
                "QPushButton{border:1px solid #DCDAD3;border-radius:3px;padding:5px 14px;"
                "background:transparent;color:#1F2329;font-weight:600;letter-spacing:0.5px;"
                "font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace;font-size:11px;}"
                "QPushButton:hover{border-color:#0E0F12;color:#0E0F12;background:#F5F4EF;}"
            )
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=st: self._add_service(s))
            chips.addWidget(b)
        chips.addStretch(1)
        m_lay.addLayout(chips)
        lay.addWidget(manual)

        # 浏览器实时查询(jev-ultrafast)总开关:默认关 —— 实测复杂站点(12306)
        # 一次查询要烧 200+ 次 Jev 决策调用;开了才会用本机 Chrome 上官网真查
        # (查火车/天气等实时数据),失败自动落回普通网页搜索
        bq_card = W.make_card()
        bq_lay = QVBoxLayout(bq_card)
        bq_lay.setContentsMargins(14, 12, 14, 12)
        self.bq_cb = QCheckBox(tr("浏览器实时查询(实验)—— 查火车/天气等实时信息时用浏览器上官网真查"))
        self.bq_cb.setChecked(db.get_setting("browser_query_enabled", "0") == "1")
        self.bq_cb.toggled.connect(
            lambda on: db.set_setting("browser_query_enabled", "1" if on else "0"))
        bq_lay.addWidget(self.bq_cb)
        bq_hint = W.muted(tr("需要本机 Chrome;复杂站点一次查询会消耗较多 Jev 决策调用,默认关闭。失败自动落回普通网页搜索。"))
        bq_hint.setWordWrap(True)
        bq_lay.addWidget(bq_hint)
        lay.addWidget(bq_card)

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
                on_set_default_model=self._set_default_model,
                on_manage_models=self._manage_models))
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
                                temperature=d["temperature"],
                                max_tokens=d.get("max_tokens"))
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
                                    models=d["models"], temperature=d["temperature"],
                                    settings=d.get("settings"),
                                    max_tokens=d.get("max_tokens"))
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

    def _manage_models(self, cfg: dict):
        """打开该配置的模型管理清单(删除/添加/设默认,改完刷新卡片 chips)。"""
        dlg = ModelManageDialog(cfg, self,
                                on_changed=lambda: self._fill_services(cfg.get("service_type") or ""))
        dlg.exec()

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

        # 绕过系统代理:requests 在 Windows 上会读注册表的系统代理(Clash 等),
        # 代理间歇性拒连时视频/图片请求会成片失败。开这个开关可强制直连。
        from PySide6.QtWidgets import QCheckBox
        self.bypass_proxy_chk = QCheckBox(tr("bypass_proxy"))
        self.bypass_proxy_chk.setChecked(db.get_setting("network_bypass_proxy", "0") == "1")
        self.bypass_proxy_chk.setToolTip(tr("bypass_proxy_tip"))
        self.bypass_proxy_chk.toggled.connect(
            lambda on: db.set_setting("network_bypass_proxy", "1" if on else "0"))
        f.addRow(tr("network"), self.bypass_proxy_chk)
        f.addRow("", W.muted(tr("bypass_proxy_tip")))

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

        # ── PhotoCraft 聊天修图集成(独立卡片,与上方「界面」并列) ──
        pc = W.make_card()
        pl = QVBoxLayout(pc)
        pl.setContentsMargins(14, 14, 14, 14)
        pl.setSpacing(8)
        pl.addWidget(W.h2(tr("chat_edit_section")))

        # 安装目录
        pc_dir_row = QHBoxLayout()
        pc_dir_row.setSpacing(6)
        self.pc_dir_edit = QLineEdit()
        self.pc_dir_edit.setText(db.get_setting("photocraft_install_dir", "") or config.DEFAULT_PHOTOCRAFT_DIR)
        self.pc_dir_edit.setToolTip(tr("chat_edit_install_dir_tip"))
        pc_dir_row.addWidget(self.pc_dir_edit, 1)
        b_dir = QPushButton("…")
        b_dir.setFixedWidth(28)
        b_dir.setCursor(Qt.PointingHandCursor)
        b_dir.setToolTip(tr("chat_edit_install_dir"))
        b_dir.clicked.connect(self._pick_photocraft_dir)
        pc_dir_row.addWidget(b_dir)
        b_open = QPushButton(tr("chat_edit_open_install_dir"))
        b_open.setCursor(Qt.PointingHandCursor)
        b_open.clicked.connect(self._open_photocraft_dir)
        pc_dir_row.addWidget(b_open)
        b_test = W.primary_btn(tr("chat_edit_test_cli"))
        b_test.clicked.connect(self._test_photocraft_cli)
        pc_dir_row.addWidget(b_test)
        pl.addLayout(pc_dir_row)
        pl.addWidget(W.muted(tr("chat_edit_install_dir_tip")))

        # CLI 路径(可选覆盖)
        cli_h_row = QHBoxLayout()
        cli_h_row.setSpacing(6)
        self.pc_cli_edit = QLineEdit()
        self.pc_cli_edit.setText(db.get_setting("photocraft_cli_path", ""))
        self.pc_cli_edit.setToolTip(tr("chat_edit_cli_path_tip"))
        cli_h_row.addWidget(self.pc_cli_edit, 1)
        b_cli = QPushButton("…")
        b_cli.setFixedWidth(28)
        b_cli.setCursor(Qt.PointingHandCursor)
        b_cli.clicked.connect(self._pick_photocraft_cli)
        cli_h_row.addWidget(b_cli)
        pl.addLayout(cli_h_row)

        # 引擎模式
        eng_row = QHBoxLayout()
        eng_row.setSpacing(6)
        eng_row.addWidget(W.muted(tr("chat_edit_engine") + ":"))
        self.pc_engine_combo = QComboBox()
        for k, label in [
            ("smart", tr("chat_edit_engine_smart")),
            ("whitelist", tr("chat_edit_engine_whitelist")),
            ("llm", tr("chat_edit_engine_llm")),
            ("off", tr("chat_edit_engine_off")),
        ]:
            self.pc_engine_combo.addItem(label, k)
        cur_mode = db.get_setting("chat_edit_engine_mode", "smart") or "smart"
        j = self.pc_engine_combo.findData(cur_mode)
        self.pc_engine_combo.setCurrentIndex(max(0, j))
        self.pc_engine_combo.currentIndexChanged.connect(self._save_pc_engine_mode)
        eng_row.addWidget(self.pc_engine_combo)
        eng_row.addStretch(1)
        pl.addLayout(eng_row)

        # LLM 文本模型选择(仅在智能/LLM 模式下生效)
        llm_row = QHBoxLayout()
        llm_row.setSpacing(6)
        llm_row.addWidget(W.muted(tr("text_svc") + ":"))
        self.pc_llm_combo = QComboBox()
        self.pc_llm_combo.setMinimumWidth(180)
        self.pc_llm_combo.addItem(tr("configured"), "")
        for r in registry.list_configs("text"):
            self.pc_llm_combo.addItem((r["model"] or "").split("/")[-1] or r["model"], str(r["id"]))
        cur_llm = db.get_setting("chat_edit_llm_config_id", "")
        j = self.pc_llm_combo.findData(cur_llm)
        self.pc_llm_combo.setCurrentIndex(max(0, j))
        self.pc_llm_combo.currentIndexChanged.connect(self._save_pc_llm)
        llm_row.addWidget(self.pc_llm_combo)
        llm_row.addStretch(1)
        pl.addLayout(llm_row)

        # 状态(测试后在这里显示)
        self.pc_status = W.muted("")
        pl.addWidget(self.pc_status)

        # 保存时统一落盘
        self.pc_dir_edit.editingFinished.connect(self._save_pc_dir)
        self.pc_cli_edit.editingFinished.connect(self._save_pc_cli)

        lay.addWidget(pc)
        lay.addWidget(self._build_stockphoto_card())
        lay.addStretch(1)
        return w

    # 三个免费图库的 key 与「AI 服务 → 图库」是**同一份**配置
    # (ai_service_configs, service_type='stockphoto'),两处任改其一即可,
    # 这里只是给「图片处理 / 聊天改图」这类入口一个就近的修改位置。
    STOCK_SOURCES = [
        ("unsplash", "Unsplash", "https://api.unsplash.com", "search/photos"),
        ("pexels", "Pexels", "https://api.pexels.com", "v1/search"),
        ("pixabay", "Pixabay", "https://pixabay.com", "api/"),
    ]

    def _build_stockphoto_card(self) -> QWidget:
        card = W.make_card()
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 14, 14, 14)
        cl.setSpacing(8)
        cl.addWidget(W.h2(tr("图库")))
        cl.addWidget(W.muted(tr("stockphoto_general_desc")))

        self._stock_edits: dict[str, QLineEdit] = {}
        self._stock_status: dict[str, QLabel] = {}
        for prov, name, base, model in self.STOCK_SOURCES:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(W.muted(f"{name}:"))
            edit = QLineEdit()
            cfg = db.q1("SELECT id, api_key FROM ai_service_configs "
                        "WHERE service_type='stockphoto' AND provider=?", (prov,))
            from ..core.secrets import ensure_decrypted
            edit.setText(ensure_decrypted((cfg["api_key"] if cfg else "") or ""))
            edit.setPlaceholderText(tr("API Key"))
            edit.editingFinished.connect(lambda p=prov: self._save_stock_key(p))
            row.addWidget(edit, 1)
            btn = QPushButton(tr("测试"))
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, p=prov: self._test_stock_key(p))
            row.addWidget(btn)
            cl.addLayout(row)
            st = W.muted("")
            cl.addWidget(st)
            self._stock_edits[prov] = edit
            self._stock_status[prov] = st
        return card

    def _save_stock_key(self, provider: str):
        key = (self._stock_edits[provider].text() or "").strip()
        cfg = db.q1("SELECT id FROM ai_service_configs "
                    "WHERE service_type='stockphoto' AND provider=?", (provider,))
        if cfg:
            from ..core.secrets import ensure_encrypted
            db.ex("UPDATE ai_service_configs SET api_key=?, updated_at=? WHERE id=?",
                  (ensure_encrypted(key), db.now(), cfg["id"]))
        else:
            base = dict((p, (b, m)) for p, _n, b, m in self.STOCK_SOURCES)[provider]
            registry.add_config("stockphoto", provider, base[0], base[1],
                                api_key=key, remark=f"{provider} 免费图库")
        self._stock_status[provider].setText(tr("已保存"))

    def _test_stock_key(self, provider: str):
        """真发一次搜索请求验鉴权 —— 图库 key 最常见的问题就是过期。"""
        from ..ai import stock_photo as sp
        self._save_stock_key(provider)          # 先落盘,再测库里的值
        self._stock_status[provider].setText(tr("测试中…"))

        def job(tid):
            row = db.q1("SELECT provider, api_key FROM ai_service_configs "
                        "WHERE service_type='stockphoto' AND provider=? "
                        "AND is_active=1", (provider,))
            from ..core.secrets import ensure_decrypted
            key = ensure_decrypted((row["api_key"] or "").strip()) if row else ""
            if not key:
                return False, tr("未填 API Key")
            try:
                fn = sp._searcher_for(provider)
                if fn is None:
                    return False, tr("未实现的适配器")
                got = fn(key, "test", 1, 3)
            except Exception as exc:  # noqa: BLE001
                resp = getattr(exc, "response", None)
                code = resp.status_code if resp is not None else None
                if code in (401, 403):
                    return False, tr("API Key 无效或已失效,请重新申请")
                if code:
                    return False, f"HTTP {code}"
                return False, f"{type(exc).__name__}: {str(exc)[:100]}"
            return True, tr("可用 · 命中 {n} 张").format(n=len(got))

        def done(tid, result, error):
            ok_, msg = result if isinstance(result, tuple) else (False, str(error or ""))
            lab = self._stock_status.get(provider)
            if lab:
                lab.setText(msg)
            (ok_toast if ok_ else err)(msg)

        from ..core.taskmgr import TASKMGR
        TASKMGR.submit("image", job, done)

    def _pick_photocraft_dir(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, tr("chat_edit_install_dir"),
                                              self.pc_dir_edit.text())
        if d:
            self.pc_dir_edit.setText(d)
            db.set_setting("photocraft_install_dir", d)
            self.pc_status.setText("")

    def _open_photocraft_dir(self):
        import os
        from pathlib import Path
        d = self.pc_dir_edit.text().strip()
        if d and Path(d).is_dir():
            try:
                os.startfile(d)  # noqa
            except Exception as exc:  # noqa: BLE001
                self.pc_status.setText(str(exc)[:160])

    def _pick_photocraft_cli(self):
        from PySide6.QtWidgets import QFileDialog
        from pathlib import Path
        start = self.pc_dir_edit.text() or ""
        f, _ = QFileDialog.getOpenFileName(
            self, tr("chat_edit_cli_path"),
            start, "Exe (photocraft-cli.exe *.exe);;All files (*)")
        if f:
            self.pc_cli_edit.setText(f)
            db.set_setting("photocraft_cli_path", f)

    def _test_photocraft_cli(self):
        self._save_pc_dir()
        self._save_pc_cli()
        from ..ai.photocraft_bridge import ChatEditEngine
        eng = ChatEditEngine()
        ok, txt = eng.status_text()
        if ok:
            self.pc_status.setText(tr("chat_edit_cli_ok").format(txt))
        else:
            self.pc_status.setText(tr("chat_edit_cli_bad").format(txt))

    def _save_pc_dir(self):
        d = self.pc_dir_edit.text().strip()
        cur = db.get_setting("photocraft_install_dir", "") or config.DEFAULT_PHOTOCRAFT_DIR
        if d and d != cur:
            db.set_setting("photocraft_install_dir", d)
            from ..ai.photocraft_bridge import PhotocraftCLI as _PC
            _PC._cmds_cache = {}
            _PC._cmds_cache_ts = 0.0

    def _save_pc_cli(self):
        p = self.pc_cli_edit.text().strip()
        cur = db.get_setting("photocraft_cli_path", "")
        if p != cur:
            db.set_setting("photocraft_cli_path", p)
            from ..ai.photocraft_bridge import PhotocraftCLI as _PC
            _PC._cmds_cache = {}
            _PC._cmds_cache_ts = 0.0

    def _save_pc_engine_mode(self):
        mode = self.pc_engine_combo.currentData() or "smart"
        db.set_setting("chat_edit_engine_mode", mode)

    def _save_pc_llm(self):
        cid = self.pc_llm_combo.currentData() or ""
        db.set_setting("chat_edit_llm_config_id", cid)

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
        db.set_setting("ui_language_explicit", "1")   # 用户手选,此后不再跟随系统
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
        # 三个分类切换:视觉风格 / 漫画风格 / 写作风格
        top = QHBoxLayout()
        top.addWidget(W.muted(tr("style_category")))
        self.style_type_combo = QComboBox()
        for st in db.STYLE_TYPES:
            self.style_type_combo.addItem(tr(db.STYLE_TYPE_LABEL_KEYS[st]), st)
        self.style_type_combo.currentIndexChanged.connect(self._refresh_styles)
        top.addWidget(self.style_type_combo)
        top.addStretch(1)
        lay.addLayout(top)
        lay.addWidget(W.muted(tr("style_presets_hint")))
        self.style_list = QListWidget()
        self.style_list.itemDoubleClicked.connect(self._edit_style)
        lay.addWidget(self.style_list, 1)
        btns = QHBoxLayout()
        b_add = W.primary_btn(tr("add"))
        b_add.clicked.connect(self._add_style)
        b_toggle = QPushButton(tr("style_toggle"))
        b_toggle.clicked.connect(self._toggle_style)
        b_del = QPushButton(tr("delete"))
        b_del.clicked.connect(self._delete_style)
        btns.addWidget(b_add)
        btns.addWidget(b_toggle)
        btns.addWidget(b_del)
        btns.addStretch(1)
        lay.addLayout(btns)
        self._refresh_styles()
        return w

    def _refresh_styles(self, *_args):
        """按当前分类(style_type)刷新风格预设列表(保持选中项)。"""
        lst = getattr(self, "style_list", None)
        if lst is None:
            return
        # 刷新前记住选中行 —— 启停后列表会重建,不记住的话第二次操作就没选中项了
        sel_id = None
        cur_item = lst.currentItem()
        if cur_item is not None:
            cur_data = cur_item.data(Qt.UserRole)
            sel_id = cur_data.get("id") if cur_data else None
        st = self.style_type_combo.currentData() or db.STYLE_TYPE_VISUAL
        lst.clear()
        for r in db.q("SELECT * FROM style_presets WHERE style_type=? ORDER BY sort_order, id",
                      (st,)):
            active = "✅" if r["is_active"] else "⛔"
            # 内置条目显示本地化名,用户自建显示 name 原样
            label = db.style_display_name(r["value"], r["name"])
            item = QListWidgetItem(f"{active}  {label}  ·  {r['description'] or ''}")
            item.setData(Qt.UserRole, dict(r))
            lst.addItem(item)
        if sel_id is not None:
            for i in range(lst.count()):
                data = lst.item(i).data(Qt.UserRole)
                if data and data.get("id") == sel_id:
                    lst.setCurrentRow(i)
                    break

    def _edit_style(self, item: QListWidgetItem):
        row = item.data(Qt.UserRole)
        if not row:
            return
        dlg = _StyleDialog(dict(row), self)
        if dlg.exec() == QDialog.Accepted:
            d = dlg.data()
            db.ex("UPDATE style_presets SET name=?, prompt=?, description=?, is_active=?, style_type=? WHERE id=?",
                  (d["name"], d["prompt"], d["description"], d["is_active"],
                   d["style_type"], row["id"]))
            self._refresh_styles()

    def _add_style(self):
        """新增一条预设:分类取当前分类,value 由用户填(全局唯一,创建后不可改)。"""
        st = self.style_type_combo.currentData() or db.STYLE_TYPE_VISUAL
        row = {"id": None, "name": "", "value": "", "prompt": "", "description": "",
               "work_type": "all", "style_type": st, "is_active": 1, "sort_order": 0}
        dlg = _StyleDialog(row, self, is_new=True)
        if dlg.exec() != QDialog.Accepted:
            return
        d = dlg.data()
        value = (d.get("value") or "").strip()
        if not value:
            warn(self, tr("style_new_title"), tr("style_value_required"))
            return
        if db.q1("SELECT id FROM style_presets WHERE value=?", (value,)):
            warn(self, tr("style_new_title"), tr("style_value_dup"))
            return
        row_max = db.q1("SELECT MAX(sort_order) m FROM style_presets WHERE style_type=?",
                        (d["style_type"],))
        order = int((row_max["m"] if row_max and row_max["m"] is not None else 0)) + 1
        db.ex("""INSERT INTO style_presets(name,value,prompt,description,work_type,style_type,
                      sort_order,is_active,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
              (d["name"] or value, value, d["prompt"] or "", d["description"],
               "all", d["style_type"], order, d["is_active"], db.now()))
        self._refresh_styles()

    def _toggle_style(self):
        item = self.style_list.currentItem()
        if not item:
            return
        row = item.data(Qt.UserRole)
        db.ex("UPDATE style_presets SET is_active=? WHERE id=?",
              (0 if row["is_active"] else 1, row["id"]))
        self._refresh_styles()

    def _delete_style(self):
        item = self.style_list.currentItem()
        if not item:
            return
        row = item.data(Qt.UserRole)
        # 内置预设有种子兜底(启动时 INSERT OR IGNORE 会补回来),删了也白删
        if row["value"] in db.BUILTIN_STYLE_NAMES:
            warn(self, tr("style_presets"), tr("style_builtin_no_delete"))
            return
        label = db.style_display_name(row["value"], row["name"])
        if not ask(self, tr("delete"), tr("style_delete_confirm", label), danger=True):
            return
        db.ex("DELETE FROM style_presets WHERE id=?", (row["id"],))
        self._refresh_styles()

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
        lay.addWidget(W.h2(tr('易好短剧 · {} {}').format(tr('version'), config.APP_VERSION)))
        lay.addWidget(W.muted(tr("「易好短剧」(Yihao Drama) 的 PySide6 桌面实现,功能对齐原版。")))
        lay.addWidget(W.muted(tr('语言 / Languages: {}(中文/EN/日本語/한국어/Français/Deutsch/Italiano/Português/Español/Tiếng Việt/Türkçe/العربية/हिन्दी/Bahasa Indonesia/ภาษาไทย)').format(len(LANGS))))
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
        W.set_icon(self.upd_btn, "download")
        self.upd_btn.setVisible(False)
        self.upd_btn.clicked.connect(self._do_update)
        b_lay.addWidget(self.upd_btn)
        self.prog = QProgressBar()
        self.prog.setVisible(False)
        b_lay.addWidget(self.prog)
        lay.addWidget(box)
        lay.addWidget(W.muted(tr('更新源:{}').format(updater.FEED_URL)))
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
            self.update_lab.setText(tr('发现新版本 v{}(当前 v{})').format(r['latest'], r['current']))
            if r.get("notes"):
                self.notes_lab.setPlainText(r["notes"])
                self.notes_lab.setVisible(True)
            self.upd_btn.setVisible(bool(r.get("url")))
            self._upd_result = r
        else:
            self.update_lab.setText(tr('✅ 已是最新版本(v{})').format(r['latest']))
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
            # 标签宽度已用字体度量 setFixedWidth 算准;此处再 adjustSize() 会被
            # 重置回 sizeHint 导致文字竖排,故只对未固定宽度的控件调整
            if not w.testAttribute(Qt.WidgetAttribute.WA_Resized) or w.minimumWidth() <= 0:
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
        self.models = [c for c in (self._clean_name(m) for m in (models or [])) if c]
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
        from ..ai.registry import is_vision_model
        for i, m in enumerate(list(self.models)):
            # 多模态模型标注一下:复刻/图片编辑要读图,选纯文本模型只会拿到胡话。
            vis = is_vision_model(m)
            chip = QPushButton(m + (tr("  默认") if i == 0 else "")
                               + (tr("  多模态") if vis else ""))
            chip.setToolTip(tr("多模态模型,可读图/读视频") if vis
                            else tr("纯文本模型,不能读图"))
            chip.setStyleSheet(
                "QPushButton{border-radius:12px; padding:3px 10px; font-size:12px;}"
                + ("QPushButton{background:#f97316;color:white;font-weight:700;border:none;}"
                   if i == 0 else "QPushButton{background:rgba(128,128,128,35);}"))
            chip.clicked.connect(lambda _=False, idx=i: self._promote(idx))
            # 用字体度量硬算宽度并 setFixedWidth:_FlowLayout._relayout 会对每个标签
            # 调 adjustSize() 把宽度重置回 sizeHint,setMinimumWidth 挡不住,
            # 结果「deepseek-v4-pro  默认」被逐字竖排(每行一个字)
            from PySide6.QtGui import QFontMetrics
            from PySide6.QtWidgets import QSizePolicy
            fm = QFontMetrics(chip.font())
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            chip.setFixedWidth(fm.horizontalAdvance(chip.text()) + 26)   # 26 = 左右内边距
            chip.setFixedHeight(26)
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
        """批量粘贴解析:兼容 JSON 数组、引号、方括号/书名号、中英文逗号分号与换行。

        直接从剪贴板粘来的 ["a","b"] / "a", "b" / 【a】、'a' 这类都能正确拆成
        纯模型名 —— 曾把这些符号原样当成模型名存进配置,请求直接失败。
        """
        import re as _re
        raw = self.input.text().strip()
        if not raw:
            return
        body = raw
        if body[:1] in "[【（「" and body[-1:] in "]】）」":
            body = body[1:-1]                      # 整体数组括号:["a","b"] → "a","b"
        parts = _re.split(r"[,\n;，；、]+", body)
        added = 0
        for part in parts:
            p = part.strip()
            p = _re.sub(r"""^["'“‘\[（【「]+""", "", p)   # 剥开头的引号/括号
            p = _re.sub(r"""["'”’\]）】」]+$""", "", p)    # 剥结尾的引号/括号
            p = p.strip().strip(",").strip()
            if p and p not in self.models:
                self.models.append(p)
                added += 1
        self.input.clear()
        self._render()
        self.changed.emit()
        if added:
            ok_toast(tr("已添加 {} 个模型").format(added))

    @staticmethod
    def _clean_name(name: str) -> str:
        """去掉模型名里混入的引号/方括号(历史脏数据,如 ["gpt-4"] 存成 ['gpt-4'])。"""
        import re as _re
        p = str(name or "").strip()
        p = _re.sub(r"""^["'“‘\[（【「]+""", "", p)
        p = _re.sub(r"""["'”’\]）】」]+$""", "", p)
        return p.strip().strip(",").strip()

    def set_models(self, models):
        out: list[str] = []
        for m in (models or []):
            c = self._clean_name(m)
            if c and c not in out:
                out.append(c)
        self.models = out
        self._render()
        self.changed.emit()


class ModelManageDialog(QDialog):
    """管理一条 AI 服务配置的模型清单:删除 / 添加 / 设默认。

    清单内的模型会出现在各页面的模型下拉里(「多模型生效」= 都可选,★ 为默认)。
    删除/添加/设默认立即写库,**无需重启**(生成时现读配置)。删除当前默认模型
    时,默认自动落到剩余的第一个;最后一个模型不允许删(删空会让相关功能全部
    失去可选模型,真要清空请直接删掉整条配置)。
    """

    def __init__(self, cfg: dict, parent=None, on_changed=None):
        super().__init__(parent)
        self.cfg_id = cfg["id"]
        self._svc = cfg.get("service_type") or ""
        self._on_changed = on_changed
        self.setWindowTitle(tr("管理模型") + " · " + (cfg.get("remark") or cfg.get("provider") or ""))
        self.resize(480, 440)
        root = QVBoxLayout(self)

        hint = W.muted(tr("清单内的模型都会出现在各页面的模型下拉里(多选即多模型生效);★ 为默认。更改立即生效,无需重启。"))
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.listw = QListWidget()
        root.addWidget(self.listw, 1)

        add_row = QHBoxLayout()
        self.new_edit = QLineEdit()
        self.new_edit.setPlaceholderText(tr("输入模型名,如 doubao-seedance-2-0-mini-260615"))
        self.new_edit.returnPressed.connect(self._add)
        add_row.addWidget(self.new_edit, 1)
        add_btn = W.primary_btn(tr("添加"))
        add_btn.clicked.connect(self._add)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        btns = QHBoxLayout()
        del_btn = QPushButton("🗑 " + tr("delete"))
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._delete_selected)
        btns.addWidget(del_btn)
        set_def = QPushButton("★ " + tr("设为默认"))
        set_def.clicked.connect(self._set_default)
        btns.addWidget(set_def)
        btns.addStretch(1)
        close = QPushButton(tr("close"))
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        root.addLayout(btns)
        self._reload()

    # ── 数据 ──
    def _row(self) -> dict:
        return dict(db.q1("SELECT * FROM ai_service_configs WHERE id=?", (self.cfg_id,)) or {})

    def _models(self) -> list[str]:
        return _cfg_models(self._row())

    def _save(self, models: list[str], default: str):
        # models 传**列表**(update_config 自己序列化;传字符串会被二次编码)
        registry.update_config(self.cfg_id, model=default, models=models)
        self._reload()
        if self._on_changed:
            self._on_changed()

    def _reload(self):
        row = self._row()
        default = (row.get("model") or "").strip()
        self.listw.clear()
        for m in _cfg_models(row):
            item = QListWidgetItem(("★  " if m == default else "      ") + m)
            item.setData(Qt.UserRole, m)
            self.listw.addItem(item)
        # 默认行置顶显示
        for i in range(self.listw.count()):
            if self.listw.item(i).text().startswith("★"):
                it = self.listw.takeItem(i)
                self.listw.insertItem(0, it)
                break
        self.listw.setCurrentRow(0)

    # ── 操作 ──
    def _add(self):
        name = self.new_edit.text().strip()
        if not name:
            return
        models = self._models()
        if name in models:
            self.new_edit.clear()
            return                       # 已存在,静默收场
        models.append(name)
        default = (self._row().get("model") or "").strip() or name
        self.new_edit.clear()
        self._save(models, default)

    def _delete_selected(self):
        item = self.listw.currentItem()
        if not item:
            return
        name = item.data(Qt.UserRole)
        models = self._models()
        if len(models) <= 1:
            from .toast import err
            err(tr("最后一个模型不允许删除 —— 真要清空请直接删除整条配置"))
            return
        models = [m for m in models if m != name]
        default = (self._row().get("model") or "").strip()
        if default == name:
            default = models[0]          # 删的是默认 → 落到剩余第一个
        self._save(models, default)

    def _set_default(self):
        item = self.listw.currentItem()
        if not item:
            return
        models = self._models()
        name = item.data(Qt.UserRole)
        if name in models:
            models.remove(name)
        models.insert(0, name)
        self._save(models, name)


class ServiceCard(QFrame):
    """一条 AI 服务配置卡片:徽章 + 名称/Key 标 + 模型 chips + 开关 + 测试/编辑/删除。

    对齐原版 settings.vue 的 config card(provider logo badge、名称、「有 Key/无 Key」标、
    「已停用」标、点击 model chip 设默认、逐行 Test、启用开关、编辑、删除)。
    """

    def __init__(self, cfg: dict, parent, on_toggle=None, on_test=None,
                 on_edit=None, on_delete=None, on_set_default_model=None,
                 on_manage_models=None):
        super().__init__()
        self.cfg = cfg
        self._on_manage_models = on_manage_models
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
                W.set_icon(chip, "star") if is_default else None
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

        # base_url 做成可点击链接:用户看到服务地址后常要直接开浏览器看控制台/文档
        _url = (cfg.get("base_url") or "").strip()
        if _url.startswith(("http://", "https://")):
            base = QLabel(f'<a href="{_url}">{_url}</a>')
            base.setOpenExternalLinks(True)
            base.setTextInteractionFlags(Qt.TextBrowserInteraction)
            base.setCursor(Qt.PointingHandCursor)
        else:
            base = QLabel(_url)
        base.setObjectName("muted")
        base.setToolTip(_url or tr("未配置 Base URL"))
        lay.addWidget(base)

        # 动作行
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.test_btn = WaitingButton(tr("test"))
        self.test_btn.setFixedHeight(26)
        self.test_btn.clicked.connect(lambda: on_test(cfg) if on_test else None)
        actions.addWidget(self.test_btn)
        # 模型管理:删除/添加/设默认 —— 清单里的模型就是各页面下拉的选项
        mgmt = QPushButton("⚙ " + tr("管理模型"))
        mgmt.setFixedHeight(26)
        mgmt.setToolTip(tr("删除不存在的模型、添加新模型、设默认;清单内都可选"))
        mgmt.clicked.connect(
            lambda: self._on_manage_models(self.cfg) if self._on_manage_models else None)
        actions.addWidget(mgmt)
        actions.addStretch(1)
        edit = QPushButton("✎ " + tr("edit"))
        W.set_icon(edit, "edit")
        edit.setFixedHeight(26)
        edit.clicked.connect(lambda: on_edit(cfg) if on_edit else None)
        actions.addWidget(edit)
        delete = QPushButton("🗑 " + tr("delete"))
        W.set_icon(delete, "delete")
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
        # addItem() 返回 **None**(不是索引)—— 必须用 addItem + count() 自己算。
        # 原写法 `self._custom_idx = addItem(...)` 让 _custom_idx 变成 None,
        # 编辑已有配置时 _prefill 调 setCurrentIndex(None) 直接 TypeError,
        # 异常被吞 → 表现为「点编辑弹不出来」(实测)。
        self.provider_combo.addItem(tr("自定义…"))
        self._custom_idx = self.provider_combo.count() - 1
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
        # token 预算:上下文长度(仅作提示/校验)与最大输出(实际发给模型的 max_tokens)
        self.ctx_tokens = QLineEdit()
        self.ctx_tokens.setPlaceholderText(tr("如 128000,留空跟随服务默认"))
        form.addRow(tr("上下文长度"), self.ctx_tokens)
        self.max_tokens = QLineEdit()
        self.max_tokens.setPlaceholderText(tr("如 32768,留空则用默认 8192"))
        form.addRow(tr("最大输出 token"), self.max_tokens)
        # 本地生图扩展设置(JSON):comfyui_workflow / comfyui_negative_prompt / image_base_size /
        # image_steps / image_cfg_scale / image_sampler / image_negative_prompt /
        # fooocus_performance / fooocus_styles —— 留空走内置默认
        self.settings_edit = QPlainTextEdit()
        self.settings_edit.setPlaceholderText(tr("本地服务扩展设置 JSON,如") + ' {"image_base_size": 1024, "comfyui_workflow": "..."}')
        self.settings_edit.setMaximumHeight(64)
        form.addRow(tr("扩展设置 (JSON)"), self.settings_edit)
        form.addRow("", _muted("思考型模型(deepseek-v4-pro / MiniMax-M3 等)思考与正文共用输出预算,"
                              "最大输出填太小会把正文截断,建议 32768 以上"))
        root.addLayout(form)
        root.addStretch(1)

        bottom = QHBoxLayout()
        test_btn = QPushButton(tr("测试配置"))
        test_btn.setStyleSheet("QPushButton{color:#e0794b;border:none;font-weight:700;}")
        test_btn.clicked.connect(self._test)
        self._test_btn = test_btn          # _test 里要用它做等待态(禁用+改文案)
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
        if e.get("ctx_tokens"):
            self.ctx_tokens.setText(str(e["ctx_tokens"]))
        if e.get("max_tokens"):
            self.max_tokens.setText(str(e["max_tokens"]))
        import json as _sj
        raw_settings = e.get("settings")
        if raw_settings:
            try:
                self.settings_edit.setPlainText(_sj.dumps(_sj.loads(raw_settings), ensure_ascii=False, indent=1))
            except (ValueError, TypeError):
                self.settings_edit.setPlainText(raw_settings)

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

        def _int_or_none(raw: str):
            raw = (raw or "").strip()
            try:
                v = int(raw)
                return v if v > 0 else None
            except ValueError:
                return None

        return {"service_type": self._st,
                "ctx_tokens": _int_or_none(self.ctx_tokens.text()),
                "max_tokens": _int_or_none(self.max_tokens.text()),
                "name": self.name_edit.text().strip(),
                "provider": self._current_provider(),
                "base_url": self.base_url.text().strip(),
                "api_key": self.api_key.text().strip(),
                "priority": self.priority_spin.value(),
                "models": models,
                "model": models[0],
                "temperature": temperature,
                "settings": self.settings_edit.toPlainText().strip()}

    def _test(self):
        """连接测试。

        必须**丢到后台线程**跑:网络请求要 5~30s,原先在主线程同步发,界面直接
        冻结 —— 用户点「测试配置」后按钮毫无变化、标签空白,看起来就是"点了
        没反应"(实测 DeepSeek 最明显)。现在:按钮进等待态 → 后台跑 →
        回调回主线程刷新标签。
        """
        if getattr(self, "_testing", False):
            return
        cfg = self._collect()
        tester = TESTERS.get(cfg["service_type"])
        if not tester:
            self.test_lab.setText(tr("❌ 该服务类型不支持测试"))
            return
        payload = {"service_type": cfg["service_type"], "provider": cfg["provider"],
                   "base_url": cfg["base_url"], "api_key": cfg["api_key"],
                   "model": cfg["model"]}
        self._testing = True
        btn = getattr(self, "_test_btn", None)
        if btn is not None:
            btn.setEnabled(False)
            btn.setText(tr("测试中…"))
        self.test_lab.setText(tr("⏳ 正在测试,请稍候…"))

        def job(_tid):
            try:
                return tester(payload)
            except Exception as exc:  # noqa: BLE001
                return False, f"{type(exc).__name__}: {str(exc)[:200]}"

        def done(_tid, result, error):
            self._testing = False
            if btn is not None:
                btn.setEnabled(True)
                btn.setText(tr("测试配置"))
            if error:
                self.test_lab.setText("❌ " + str(error)[:200])
                return
            ok, msg = result if isinstance(result, tuple) else (False, str(result))
            self.test_lab.setText(("✅ " if ok else "❌ ") + msg[:200])

        from ..core.taskmgr import TASKMGR
        TASKMGR.submit("prompt", job, done, detail=tr("test"))

    def _save(self):
        data = self._collect()
        if not data["model"] or not data["base_url"]:
            self.test_lab.setText(tr("❌ Base URL 与至少一个模型必填"))
            return
        self.accept()

    def data(self) -> dict:
        return self._collect()


class _StyleDialog(QDialog):
    def __init__(self, row: dict, parent=None, is_new: bool = False):
        super().__init__(parent)
        self.is_new = is_new
        self.setWindowTitle(tr("style_new_title") if is_new else (row.get("name") or ""))
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit(row.get("name") or "")
        # value 是全局唯一键,创建后不可修改(沿用既有约定)
        self.value = QLineEdit(row.get("value") or "")
        if not is_new:
            self.value.setReadOnly(True)
        self.type_combo = QComboBox()
        for st in db.STYLE_TYPES:
            self.type_combo.addItem(tr(db.STYLE_TYPE_LABEL_KEYS[st]), st)
        ti = self.type_combo.findData(row.get("style_type") or db.STYLE_TYPE_VISUAL)
        self.type_combo.setCurrentIndex(ti if ti >= 0 else 0)
        self.desc = QLineEdit(row.get("description") or "")
        self.active = QCheckBox(tr("enabled"))
        self.active.setChecked(bool(row.get("is_active", 1)))
        f.addRow(tr("名称"), self.name)
        f.addRow(tr("style_value_label"), self.value)
        f.addRow(tr("style_type_label"), self.type_combo)
        f.addRow(tr("描述"), self.desc)
        f.addRow("", self.active)
        lay.addLayout(f)
        if is_new:
            lay.addWidget(W.muted(tr("style_value_hint")))
        self.prompt = QPlainTextEdit(row.get("prompt") or "")
        lay.addWidget(self.prompt, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

    def data(self) -> dict:
        return {"name": self.name.text().strip(), "value": self.value.text().strip(),
                "style_type": self.type_combo.currentData() or db.STYLE_TYPE_VISUAL,
                "prompt": self.prompt.toPlainText(),
                "description": self.desc.text().strip(),
                "is_active": 1 if self.active.isChecked() else 0}
