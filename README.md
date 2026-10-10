# 🎬 易好短剧 · PySide6 版(Yihao Shorts Desktop)

**简体中文** | [English](#english) | [日本語](#日本語) | [한국어](#한국어)

基于 **PySide6(Python 3.10+)** 的 AI 短剧/小说/漫画一站式制作工具。功能 100% 对齐开源项目 [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git)(Web 版),并集成了两个社区工具的核心能力:

- **[golanse/easymerger](https://github.com/golanse/easymerger)** — 无损视频合并(参数检测/智能直通/一键对齐异类)
- **[liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)** — 同款复刻(爆款视频结构迁移到你的产品)

> 黑盒分析报告:[docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划:[PLAN.md](PLAN.md) · 过程记录:[PROGRESS.md](PROGRESS.md)

---

## 🌐 语言支持(15 种)

**界面语言与 AI 内容语言是同一个开关,内置 15 种**(超过原版 Web 的"UI 15 种 + AI 内容 4 种"):

中文 / English / 日本語 / 한국어 / Français / Deutsch / Italiano / Português / Español / Tiếng Việt / Türkçe / العربية / हिन्दी / Bahasa Indonesia / ภาษาไทย

- 切换入口:顶栏「界面与 AI 内容语言」或「设置 → 通用」;
- 切换后界面文案与 AI 产出(剧本/资产提取/分镜/提示词/小说/文案)**同时**使用所选语言;
- 非 zh/en/ja/ko 的语言通过在 Agent System Prompt 末尾注入显式输出语言指令实现(防止模型漂回英文);
- 本地化文件:`app/core/i18n.py`(新增语言只需在 `LANGS` 加一行 + 补 `T[lang]` 字典)。

## ✨ 功能全景

| 模块 | 能力 |
|------|------|
| 项目启动台 | 统计/筛选(待开始·进行中·已完成)/搜索/删除(二次确认) |
| 新建项目(5 种创作目标) | 📖 写小说 · 🎬 生成短剧 · 📚 生成漫画 · 📣 宣传营销(平台×6/格式×6) · 🎞 同款复刻(新) |
| 视觉风格 | 20 条预设(短剧向 8 + 通用 6 + 宣传 6),完整复刻原版英文提示词,统一电影质感锚点 |
| 集工作台(六阶段) | 原始内容 → AI 改写 → 视漫制作 → 分镜 → 漫画 → 拼接导出 |
| AI Agent ×10 | 剧本改写/角色场景提取/分镜拆解/提示词/小说生成/策划/六维审校/改稿/漫画分镜/宣传文案,System Prompt 全开放可编辑(`workspace/prompts/*.md`) |
| AI 服务 | 文本/图片/视频/配音 四类多供应商(OpenAI 兼容、Gemini、火山 Seedance/Seedream、MiniMax、阿里 Wan、Agnes、qwen-image、本地 InsightFace 换脸),易好 Key 一键配置,连通测试 |
| 任务系统 | 统一任务队列(sys_task),processing → completed/failed,任务面板 |
| 无损合并工具页 | ffprobe 参数一致性检测(分辨率/编码/帧率/Profile/采样率)→ 三通道:全一致 `-c copy` 秒合 / 视频一致音频不同→智能直通 / 少数异类→一键对齐多数派;失败回退链(换中间容器→重编码) |
| 同款复刻 | 参考视频抽帧 → AI 出分镜表 → 产品/模特素材 → 逐镜首帧图+图生视频 → 按原片节奏无损拼接 |
| 小说线 | 开书策划(总纲/世界观/合约/卷/章节)→ 逐章生成 → 六维审校 → 按指令改稿 → 导出整本 |
| 数据 | SQLite 单文件(23 张表)+ 本体媒体存储,`data/` 目录即全部数据 |

## 📊 功能对照表(原版 Web ↔ 本桌面版)

### 一、原版功能对应

| 原版模块 | 原版实现 | 本版对应 | 状态 |
|---|---|---|---|
| 项目启动台 | `pages/index.vue` | `ProjectsPage` | ✅ |
| 新建项目(5 目标) | 同上 | `NewProjectDialog` | ✅ |
| 项目详情/剧集列表 | `views/drama/detail.vue` | `ProjectPage` | ✅ |
| 项目设置 | detail.vue 弹窗 | `ProjectSettingsDialog` | ✅ |
| 素材库(角色/场景/道具) | detail.vue | `AssetDetailDialog` | ✅ |
| 集工作台(六阶段) | `views/drama/episode.vue` (11.6k 行) | `EpisodePage` | ✅ |
| 原始内容/AI 改写 | episode.vue scriptStep | `raw` / `rewrite` 面板 | ✅ |
| 视漫制作(资产) | prodTab assets | `assets` 面板(常规/漫画双 tab) | ✅ |
| 分镜/视频 | prodTab videos | `storyboard` 面板 | ✅ |
| 漫画 | prodTab comic | `comic` 面板 | ✅ |
| 拼接导出 | prodTab export | `export` 面板 | ✅ |
| 设置(六分区) | `pages/settings.vue` | `SettingsDialog` | ✅ |
| Agent 配置 | settings.vue | System Prompt / Skills 双标签 | ✅ |
| 风格预设 | settings.vue | 20 条种子 + 编辑 | ✅ |
| AI 服务(五类) | settings.vue | `ServiceDialog` | ✅ |
| 换脸 | `tools/face-swap.vue` | 资产角色卡内换脸对话框 | ✅ |
| 任务面板 | `useTaskDrawer` | `TaskPanel` | ✅ |

### 二、多语言深度(原版所无)

| 能力 | 原版 Web | 本版 |
|---|---|---|
| UI 语言 | 15 种 | 15 种 |
| AI 内容语言 | 15 种(跟随项目) | 15 种(全局 + **项目级独立**) |
| Agent 提示词变体 | 4 语言硬编码 | **15 语言**(150 文件) |
| Skill 变体 | 4 语言 | **15 语言**(165 文件,含打斗运镜技能) |

### 三、可靠性(源自原版后期加固)

| 能力 | 说明 |
|---|---|
| LLM 挂起超时 | `AI_LLM_TIMEOUT_MS` 默认 300s,防服务商"接受连接不响应" |
| 任务阶段可见 | `writing→reviewing→repairing→splitting` 写入 `sys_task.params.stage` |
| 写后校验 | 以数据库为准判定成功,`content<200` 判失败(防"显示完成实则空章") |
| 分镜后台拆解 | 防重入 + 垃圾行清理 + 6s 轮询(原同步 HTTP 会被代理掐断) |
| 防误覆盖 | 已有正文的章节整批拒绝,需显式"重写"才放行 |
| 中断任务归位 | 重启时按"产出是否已落"判 completed/failed,不一律 failed |
| 参考图序号 | 单一真相源,`@图片N ≡ reference_image_urls[N-1]` |

### 四、本版增量(原版没有)

| 能力 | 说明 |
|---|---|
| 批量建集 | 1–999 集一次插入(原版逐个建集) |
| 伏笔台账 | LCS≥5 去重 + 40 条封顶 + 埋设章号回填 + 可交互勾选 |
| 审校明细/全书清单 | 逐条勾选标记 + 跨章跳转 |
| 整章朗读 | 按句切 600 字,逐块 TTS 拼 MP3 |
| 三段式进度条 | 成功/失败/进行中 + 图例 + 每章阶段 |
| 制作阶段条 | 按产物判定 5 态(正文→剧本→资产→分镜→成片) |
| 剧集卡字数进度 | `X/Y 字`,低于 80% 标琥珀色 |
| 封面体系 | 项目封面(资产参考图)+ 单章封面,均 3:4 |
| 语速自适应 TTS | 双引擎 + ffprobe 实测超时自动提速重合成(≤2 轮) |
| AI 未就绪拦截 | 未配置/缺 Key 时点按钮立即提示,不静默失败 |
| 自动更新 | GitHub Releases 检查 → 备份覆盖 → 询问重启 |
| 无损合并工具 | ffprobe 参数检测 + 三通道合并 + 失败回退链 |
| 同款复刻 | 爆款视频结构迁移到你的产品 |

## 🚀 快速开始

```bash
# 要求 Python 3.10+(开发验证于 3.13)
pip install -r requirements.txt

# 运行
python -m app.main          # 推荐(包内模块方式)
# 或双击 start.bat
```

<details>
<summary>从原版迁移 AI 服务配置(可选)</summary>

```bash
py -3.13 -m scripts.migrate_ai_configs --dry-run   # 预览
py -3.13 -m scripts.migrate_ai_configs             # 迁移(读 E:\\xiaoshuo 的 sqlite)
```

也可手动配置:**设置 → AI 服务 → 易好快捷配置**,粘贴 Yihao API Key 一键写入 8 条推荐配置;或用「手动模板」按厂商逐个添加(文本/图片/视频/配音/换脸五类,支持 Base URL、多模型、温度、优先级、连通测试)。

- 数据目录:`data/`(SQLite + 生成的图片/视频/成片)
- Agent 提示词:`workspace/prompts/*.md`(设置页可在线编辑)
- FFmpeg:自动从 PATH 查找;或设置环境变量 `FFMPEG_BIN` / `FFPROBE_BIN`;或放入 `vendor/ffmpeg/bin/`
- AI 服务:首次启动进入「设置 → AI 服务」,粘贴 Yihao API Key 一键写入三条推荐配置,或手动模板逐个添加

## 📁 结构

```
app/
  core/    config.py(路径/ffmpeg) db.py(23表+种子) i18n.py(15语言) taskmgr.py(任务队列) theme.py(QSS)
  ai/      registry.py(服务注册表) text_client.py image_client.py video_client.py tts_client.py face_swap.py
  agents/  prompts.py(10 Agent 提示词+15语言机制) runner.py(执行器)
  pipeline/ rewriter.py extractor.py storyboard.py prompts_gen.py comic.py novel.py promo.py
           merge.py(easymerger 逻辑) stitch.py(长图) video_clone.py(同款复刻)
  ui/      main_window.py projects_page.py new_project_dialog.py project_page.py
           episode_page.py(六阶段工作台) settings_dialog.py task_panel.py merger_tool_page.py widgets.py
assets/fonts/  打包字体(微软雅黑,对齐原版 drama 字体栈回落策略)
docs/          分析报告/计划/过程/截图
```

## 📄 许可

延续原版 CC BY-NC-SA 4.0。FFmpeg 以子进程调用,其 GPL/LGPL 许可不影响本项目。

---

<a name="english"></a>
# 🎬 Yihao Shorts (PySide6 Edition)

**A one-stop AI studio for short dramas, novels and comics**, rebuilt in PySide6 (Python 3.10+). Feature-complete rewrite of [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git), plus core logic from [golanse/easymerger](https://github.com/golanse/easymerger) (lossless merging) and [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite) (viral-video cloning).

## 🌐 Languages — 15 supported

**UI language and AI-content language share one switch**, available in 15 languages:

Chinese / English / 日本語 / 한국어 / Français / Deutsch / Italiano / Português / Español / Tiếng Việt / Türkçe / العربية / हिन्दी / Bahasa Indonesia / ภาษาไทย

Switching updates both the interface and all AI output (scripts, asset extraction, storyboards, prompts, novels, marketing copy). Languages outside zh/en/ja/ko are enforced via an explicit output-language directive appended to each agent's system prompt.

**Beyond the original**: agent prompts and skills ship in **all 15 languages** here (150 prompt + 165 skill files), and each project can fix its own content language independently of the global setting.

## Features

- **5 creative goals**: novel / short drama / comic / promotion (6 platforms × 6 formats) / video clone
- **6-stage studio**: raw text → AI rewrite → assets → storyboard → comic → merge & export
- **10 AI agents** with fully editable system prompts (`workspace/prompts/*.md`)
- **Multi-provider AI services**: text/image/video/TTS (OpenAI-compatible, Gemini, Volcengine Seedance/Seedream, MiniMax, Aliyun Wan, Agnes, qwen-image, local InsightFace face-swap)
- **Lossless merger tool**: ffprobe parameter consistency check (resolution/codec/fps/profile/sample-rate) → lossless concat (`-c copy`), smart passthrough (video copy + audio aligned), or align-outliers-then-merge; with fallback chain
- **Video clone**: analyze reference video → AI storyboard → your product/presenter → shot-by-shot re-generation → lossless merge
- **Novel pipeline**: planning → chapter writing → 6-dimension review → editing → full book export
- **20 style presets** faithful to the original (cinematic quality anchors), SQLite storage (23 tables)

## 📊 Feature mapping (original Web ↔ this desktop build)

### Original modules — all covered

| Original module | Original file | Here | |
|---|---|---|---|
| Project launcher | `pages/index.vue` | `ProjectsPage` | ✅ |
| New project (5 goals) | same | `NewProjectDialog` | ✅ |
| Project detail / episode list | `views/drama/detail.vue` | `ProjectPage` | ✅ |
| Project settings | detail.vue dialog | `ProjectSettingsDialog` | ✅ |
| Asset library (chars/scenes/props) | detail.vue | `AssetDetailDialog` | ✅ |
| Episode studio (6 stages) | `views/drama/episode.vue` (11.6k lines) | `EpisodePage` | ✅ |
| Raw text / AI rewrite | scriptStep | `raw` / `rewrite` panels | ✅ |
| Assets | prodTab assets | `assets` panel (normal + comic tabs) | ✅ |
| Storyboard / video | prodTab videos | `storyboard` panel | ✅ |
| Comic | prodTab comic | `comic` panel | ✅ |
| Merge & export | prodTab export | `export` panel | ✅ |
| Settings (6 sections) | `pages/settings.vue` | `SettingsDialog` | ✅ |
| Agent config | settings.vue | System Prompt / Skills dual tabs | ✅ |
| Style presets | settings.vue | 20 seeds + editor | ✅ |
| AI services (5 types) | settings.vue | `ServiceDialog` | ✅ |
| Face swap | `tools/face-swap.vue` | in-dialog on asset character card | ✅ |
| Task panel | `useTaskDrawer` | `TaskPanel` | ✅ |

### Multilingual depth — beyond the original

| Capability | Original Web | Here |
|---|---|---|
| UI languages | 15 | 15 |
| AI content languages | 15 (per project) | 15 (global **+ independent per project**) |
| Agent prompt variants | 4 hardcoded | **15** (150 files) |
| Skill variants | 4 | **15** (165 files, incl. fight-cinematography) |

### Reliability hardening

| Capability | Why |
|---|---|
| LLM hang timeout | `AI_LLM_TIMEOUT_MS` (300s default) — providers that accept the connection but never answer |
| Task stage visibility | `writing → reviewing → repairing → splitting` stored in `sys_task.params.stage` |
| Write-after verify | success judged from the DB; `content < 200` = failure (no "completed but empty chapter") |
| Background storyboard split | re-entrancy guard + junk-row cleanup + 6s polling (the original synchronous HTTP gets cut off) |
| Overwrite protection | chapters with existing text are rejected unless you explicitly hit "rewrite" |
| Interrupted task settling | on restart, completed/failed decided by whether output actually landed |
| Reference-image indexing | single source of truth; `@图片N ≡ reference_image_urls[N-1]` |

### Additions not in the original

| Capability | Notes |
|---|---|
| Bulk episode creation | 1–999 episodes inserted in one go |
| Foreshadowing ledger | LCS≥5 dedup, 40-item cap, chapter backfill, interactive toggle |
| Review detail / book-wide review list | per-item checkbox, jump to chapter |
| Full-chapter read-aloud | sentence-split at 600 chars, per-chunk TTS concatenated to MP3 |
| Three-segment progress bar | ok / fail / running + legend + per-chapter stage |
| Production stage bar | derived from actual artifacts, 5 states |
| Word-count progress | `X / Y 字`, amber below 80% |
| Cover system | project cover (with asset reference) + per-chapter cover, both 3:4 |
| Speed-adaptive TTS | dual engine + ffprobe-measured re-synthesis when too long |
| AI readiness guard | missing config/Key blocks the button with a clear message |
| Auto update | GitHub Releases check → backup & overwrite → ask to restart |
| Lossless merger | ffprobe param check + three-channel merge + fallback chain |
| Video clone | migrate a viral video's structure onto your product |

## Quick start

```bash
pip install -r requirements.txt   # Python 3.10+
python app/main.py
```

Data lives in `data/`; configure AI providers in Settings → AI Services (or paste a Yihao API Key for one-click setup).

License: CC BY-NC-SA 4.0 (inherited from the original project).

---

<a name="日本語"></a>
# 🎬 易好短劇 PySide6 版(日本語)

**AI によるショートドラマ・小説・漫画のワンストップ制作ツール**(Python 3.10+ / PySide6)。オープンソース [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) の全機能を再実装し、[golanse/easymerger](https://github.com/golanse/easymerger)(ロスレス結合)と [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)(動画複製)の核心ロジックを統合しました。

## 🌐 対応言語 — 15 言語

**UI 言語と AI 出力言語は同じスイッチで**、15 言語に対応:

中国語 / English / 日本語 / 한국어 / Français / Deutsch / Italiano / Português / Español / Tiếng Việt / Türkçe / العربية / हिन्दी / Bahasa Indonesia / ภาษาไทย

切り替えると、画面表示と AI が生成するすべてのコンテンツ(脚本・アセット・絵コンテ・プロンプト・小説・宣伝文)が同じ言語で出力されます。

## 主な機能

- **5 つの創作目標**:小説 / ショートドラマ / 漫画 / プロモーション / 動画複製
- **6 段階ワークベンチ**:原文 → AI リライト → アセット → 絵コンテ → 漫画 → 結合・書き出し
- **10 種類の AI Agent**(System Prompt は全て編集可能)
- **マルチプロバイダ AI**(OpenAI 互換 / Gemini / 火山 Seedance / MiniMax / 阿里 Wan / Agnes / ローカル顔交換)
- **ロスレス結合ツール**:ffprobe によるパラメータ一致判定(解像度/コーデック/FPS/Profile)→ `-c copy` / スマートパススルー / 外れ値整列の 3 チャネル + 失敗時フォールバック
- **小説制作**:企画 → 逐章生成 → 6 観点レビュー → 加筆 → 全編書き出し

## 📊 機能対応表（原版 Web ↔ 本デスクトップ版）

### 原版のモジュール — すべて対応

| 原版モジュール | 原版ファイル | 本版 | |
|---|---|---|---|
| プロジェクト起動台 | `pages/index.vue` | `ProjectsPage` | ✅ |
| 新規プロジェクト（5 目標） | 同上 | `NewProjectDialog` | ✅ |
| プロジェクト詳細 / 話数一覧 | `views/drama/detail.vue` | `ProjectPage` | ✅ |
| プロジェクト設定 | detail.vue ダイアログ | `ProjectSettingsDialog` | ✅ |
| アセットライブラリ | detail.vue | `AssetDetailDialog` | ✅ |
| エピソードスタジオ（6 段階） | `episode.vue`（11.6k 行） | `EpisodePage` | ✅ |
| 原文 / AI リライト | scriptStep | `raw` / `rewrite` パネル | ✅ |
| アセット | prodTab assets | `assets` パネル（通常/コミック） | ✅ |
| 絵コンテ / 動画 | prodTab videos | `storyboard` パネル | ✅ |
| コミック | prodTab comic | `comic` パネル | ✅ |
| 結合・書き出し | prodTab export | `export` パネル | ✅ |
| 設定（6 セクション） | `pages/settings.vue` | `SettingsDialog` | ✅ |
| Agent 設定 | settings.vue | System Prompt / Skills タブ | ✅ |
| スタイルプリセット | settings.vue | 20 シード + 編集 | ✅ |
| AI サービス（5 種） | settings.vue | `ServiceDialog` | ✅ |
| 顔入れ替え | `tools/face-swap.vue` | アセットのキャラカード内 | ✅ |
| タスクパネル | `useTaskDrawer` | `TaskPanel` | ✅ |

### 多言語の深み — 原版を超えた点

| 機能 | 原版 Web | 本版 |
|---|---|---|
| UI 言語 | 15 | 15 |
| AI コンテンツ言語 | 15 | 15（全体 + **プロジェクト個別**） |
| Agent プロンプト変種 | 4 言語固定 | **15 言語**（150 ファイル） |
| Skill 変種 | 4 | **15**（165 ファイル） |

### 信頼性の強化

| 機能 | 目的 |
|---|---|
| LLM ハングタイムアウト | `AI_LLM_TIMEOUT_MS`（既定 300 秒）— 応答しないプロバイダ対策 |
| タスク段階の可視化 | `writing → reviewing → repairing → splitting` を記録 |
| 書き込み後の検証 | 成功は DB 判定、`content < 200` は失敗扱い |
| 絵コンテのバックグラウンド分割 | 再入防止 + ゴミ行掃除 + 6 秒ポーリング |
| 上書き防止 | 本文がある章は batch 拒否、明示操作時のみ許可 |
| 中断タスクの整理 | 再起動時、出力の実着地で completed/failed を判定 |
| 参考画像インデックス | 単一真実源、`@画像N ≡ reference_image_urls[N-1]` |

### 本版のみの追加機能

| 機能 | 備考 |
|---|---|
| 話数の一括作成 | 1〜999 話を一度に挿入 |
| 伏線台帳 | LCS≥5 の重複排除、上限 40、対話的トグル |
| レビュー詳細 / 全書レビュー一覧 | 項目チェック、章へのジャンプ |
| 章全体の読み上げ | 600 字分割、逐次 TTS を MP3 結合 |
| 三区画プログレスバー | 成功 / 失敗 / 実行中 + 章ごとの段階 |
| 制作段階バー | 生成物から 5 状態を判定 |
| 文字数プログレス | `X / Y 字`、80% 未満は琥珀色 |
| カバー体系 | プロジェクト / 章カバー、ともに 3:4 |
| 速度適応 TTS | デュアルエンジン + 実測で長ければ再合成 |
| AI 未設定ガード | 設定不足時はボタン押下で即座に明示 |
| 自動更新 | Releases 確認 → バックアップ → 再起動確認 |
| ロスレス結合 | パラメータ検査 + 3 チャネル + フォールバック |
| 同款复刻 | ヒット動画の構造を製品へ移行 |

## クイックスタート

```bash
pip install -r requirements.txt   # Python 3.10+
python app/main.py
```

ライセンス:CC BY-NC-SA 4.0(原プロジェクトより継承)。

---

<a name="한국어"></a>
# 🎬 이하오 숏드라마 PySide6 판(한국어)

**AI로 만드는 숏드라마·소설·만화 올인원 제작 도구**(Python 3.10+ / PySide6). 오픈소스 [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git)의 전체 기능을 재구현하고, [golanse/easymerger](https://github.com/golanse/easymerger)(무손실 병합)와 [liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)(영상 복제)의 핵심 로직을 통합했습니다.

## 🌐 지원 언어 — 15 개

**UI 언어와 AI 출력 언어가 하나의 스위치로 동작**하며 15 개 언어를 지원합니다:

중국어 / English / 日本語 / 한국어 / Français / Deutsch / Italiano / Português / Español / Tiếng Việt / Türkçe / العربية / हिन्दी / Bahasa Indonesia / ภาษาไทย

전환하면 화면 문구와 AI가 생성하는 모든 콘텐츠(대본·에셋·스토리보드·프롬프트·소설·홍보 문구)가 같은 언어로 출력됩니다.

## 주요 기능

- **5 가지 창작 목표**: 소설 / 숏드라마 / 만화 / 홍보 마케팅 / 영상 복제
- **6 단계 워크벤치**: 원문 → AI 각색 → 에셋 → 스토리보드 → 만화 → 병합·내보내기
- **10 종 AI Agent**(System Prompt 전체 편집 가능)
- **멀티 프로바이더 AI**(OpenAI 호환 / Gemini / 버섹 Seedance / MiniMax / 알리 Wan / Agnes / 로컬 얼굴 교체)
- **무손실 병합 도구**: ffprobe 파라미터 일치 검사(해상도/코덱/FPS/Profile) → `-c copy` / 스마트 패스스루 / 이상치 정렬 3 채널 + 실패 폴백
- **소설 제작**: 기획 → 챕터 생성 → 6 항목 검토 → 수정 → 전체 내보내기

## 📊 기능 대응표(원본 Web ↔ 본 데스크톱 버전)

### 원본 모듈 — 전부 대응

| 원본 모듈 | 원본 파일 | 본 버전 | |
|---|---|---|---|
| 프로젝트 런처 | `pages/index.vue` | `ProjectsPage` | ✅ |
| 새 프로젝트(5 목표) | 동일 | `NewProjectDialog` | ✅ |
| 프로젝트 상세 / 회차 목록 | `views/drama/detail.vue` | `ProjectPage` | ✅ |
| 프로젝트 설정 | detail.vue 대화상자 | `ProjectSettingsDialog` | ✅ |
| 에셋 라이브러리 | detail.vue | `AssetDetailDialog` | ✅ |
| 에피소드 스튜디오(6단계) | `episode.vue`(11.6k줄) | `EpisodePage` | ✅ |
| 원문 / AI 각색 | scriptStep | `raw` / `rewrite` 패널 | ✅ |
| 에셋 | prodTab assets | `assets` 패널(일반/만화) | ✅ |
| 스토리보드 / 영상 | prodTab videos | `storyboard` 패널 | ✅ |
| 만화 | prodTab comic | `comic` 패널 | ✅ |
| 병합·내보내기 | prodTab export | `export` 패널 | ✅ |
| 설정(6개 섹션) | `pages/settings.vue` | `SettingsDialog` | ✅ |
| Agent 설정 | settings.vue | System Prompt / Skills 탭 | ✅ |
| 스타일 프리셋 | settings.vue | 20개 시드 + 편집 | ✅ |
| AI 서비스(5종) | settings.vue | `ServiceDialog` | ✅ |
| 얼굴 교체 | `tools/face-swap.vue` | 에셋 캐릭터 카드 내 | ✅ |
| 태스크 패널 | `useTaskDrawer` | `TaskPanel` | ✅ |

### 다국어 깊이 — 원본을 넘어선 부분

| 기능 | 원본 Web | 본 버전 |
|---|---|---|
| UI 언어 | 15 | 15 |
| AI 콘텐츠 언어 | 15 | 15(전역 + **프로젝트별 독립**) |
| Agent 프롬프트 변형 | 4개 고정 | **15개 언어**(150개 파일) |
| Skill 변형 | 4 | **15**(165개 파일) |

### 신뢰성 강화

| 기능 | 목적 |
|---|---|
| LLM 행 타임아웃 | `AI_LLM_TIMEOUT_MS`(기본 300초) — 응답 없는 제공자 대비 |
| 태스크 단계 가시성 | `writing → reviewing → repairing → splitting` 기록 |
| 기록 후 검증 | 성공 여부를 DB로 판정, `content < 200` 은 실패 처리 |
| 스토리보드 백그라운드 분할 | 재진입 방지 + 쓰레기 행 정리 + 6초 폴링 |
| 덮어쓰기 방지 | 본문 있는 회차는 batch 거부, 명시적 "다시 쓰기" 시에만 허용 |
| 중단 태스크 정리 | 재시작 시 실제 산출물 존재 여부로 completed/failed 판정 |
| 참조 이미지 인덱스 | 단일 진실 원천, `@이미지N ≡ reference_image_urls[N-1]` |

### 원본에 없는 추가 기능

| 기능 | 비고 |
|---|---|
| 회차 일괄 생성 | 1~999회 한 번에 삽입 |
| 복선 장부 | LCS≥5 중복 제거, 상한 40, 대화형 토글 |
| 검토 상세 / 전체 검토 목록 | 항목별 체크, 해당 회차로 이동 |
| 회차 전체 음성 읽기 | 600자 분할, 순차 TTS 를 MP3 로 결합 |
| 3구간 진행률 | 성공 / 실패 / 진행 중 + 범례 + 회차별 단계 |
| 제작 단계 바 | 산출물로부터 5단계 판정 |
| 분자 수 진행 | `X / Y 자`, 80% 미만은 호박색 |
| 커버 체계 | 프로젝트 / 회차 커버, 모두 3:4 |
| 속도 적응 TTS | 듀얼 엔진 + 실측 초과 시 재합성 |
| AI 미설정 가드 | 설정/Key 누락 시 버튼 즉시 안내 |
| 자동 업데이트 | Releases 확인 → 백업 덮어쓰기 → 재시작 확인 |
| 무손실 병합 | 파라미터 검사 + 3채널 병합 + 폴백 |
| 동款式 복제 | 바이럴 영상 구조를 내 제품으로 이전 |

## 빠른 시작

```bash
pip install -r requirements.txt   # Python 3.10+
python app/main.py
```

라이선스: CC BY-NC-SA 4.0(원 프로젝트 승계).
