<!-- 此注释表明此 README 的语言。其它语言的 README 见同目录下的兄弟文件。 -->
> **语言 / Language / 言語 / 언어**: **简体中文** | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# 易好短剧 · PySide6 版 / Yihao Shorts (PySide6 Edition)

AI 短剧/小说/漫画一站式制作工具。功能 100% 对齐开源项目 [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版),并集成了两个社区工具的核心能力:
- **[golanse/easymerger](https://github.com/golanse/easymerger)** — 无损视频合并(参数检测/智能直通/一键对齐异类)
- **[liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)** — 同款复刻(爆款视频结构迁移到你的产品)

> 黑盒分析报告: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)

---

## 🌐 语言支持(16 种)

**界面语言与 AI 内容语言是同一个开关,内置 16 种**(简繁中文 + 14 种其他语言):

简体中文 / 繁體中文 / English / 日本語 / 한국어 / Français / Deutsch / Italiano / Português / Español / Tiếng Việt / Türkçe / العربية / हिन्दी / Bahasa Indonesia / ภาษาไทย

- 切换入口:顶栏「界面与 AI 内容语言」或「设置 → 通用」;
- 切换后界面文案与 AI 产出(剧本/资产提取/分镜/提示词/小说/文案)**同时**使用所选语言;
- 非 zh/en/ja/ko 的语言通过在 Agent System Prompt 末尾注入显式输出语言指令实现(防止模型漂回英文);
- 本地化文件:`app/core/i18n.py`(主表 + `_t()` fallback)+ `app/core/ui_strings.py`(15 语言全量翻译表,新增语言只需在 `LANGS` 加一行 + 补一列 15 元素 list)。
- **Edge TTS 朗读同步 16 语种**: 切换到「朗读音色」(女声/男声)后,Edge TTS 读出章节文本时,按主脚本自动从 16 语种 × 男女 = 32 个微软神经 voice 中选一个,语种变了 voice 自动切。

## 🔊 Edge TTS 朗读(免费神经语音)

`dramas.metadata.tts_gender`(`female` / `male`)驱动,链路 4 段:

1. **Path A/B 火山豆包**(用户配了 API Key 时) → 付费高质量
2. **Path C Microsoft Edge TTS**(默认) → **免费云端神经语音,无 API Key、无需下载语言包**,只要联网就有声
3. **detect_lang(text)** 用「脚本扫描 + langdetect + 繁中独有字」三重判定,16 种系统界面语言全覆盖
4. **EDGE_VOICE_LIST** 32 个 voice 预设(微软 Azure Neural voices),按 `text 主语言 + gender` 自动选

朗读入口:集工作台「原始内容」面板 → 「🔊 朗读本章」→ 走 `novel.read_aloud` 全集串行合成,完成后弹 `AudioPreviewDialog` 内嵌播放窗口(标题带 `voice 名 + 女声/男声`),用户再次点会弹「重放/重新生成」二选一。分镜旁白走同一入口,`storyboards.narration_voice` 字段记录真实 voice。

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
| 项目级"温画画风" | `dramas.comic_style` 字段统一漫画资产/漫画格画风,项目设定一键切;其它漫化页不重复下拉 |
| 项目级"朗读音色" | `dramas.metadata.tts_gender` 字段统一男女声(女声/男声) → Edge TTS 16 语种 × 男女 32 个神经 voice 自动选 |
| Edge TTS 免费神经朗读 | 微软云端 Microsoft Edge TTS,**无需 API Key**,**不需下载语言包**,只要联网就有声;脚本旁白 + 整章朗读 同一链路;播放窗口带 voice 名字 |
| 漫画跨格一致性 | 链式 keyframe 馈送(上一张 panel 出图后 url 喂给下一张)+ character_variants 多角度参考图(优先取变体图,没有时退回主图),跨格角色/场景/光影保持一致 |
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
| **聊天改图独立 tab** | 顶栏「💬 聊天改图」独立成页,不与「图片处理」挤在一个 splitter;点气泡里的图直接进「改图」弹窗,点「应用」回写会话当前图 |
| **文字编辑技能** | 「把『影星传媒』改成『歌星』」/「去掉图片上的文字」—— 多模态 LLM 定位文字 → cv2 笔画级掩膜 inpaint 抹除 → PIL 渲新字,字色/字号随原图自适应 |
| **水印:文字 / 图片** | 改图弹窗内可切换两种水印;8 套文字预设,或自定义文字 + 颜色 + 字号 + 竖排;图片水印支持选图 + 缩放 + 透明度;九宫格一键定位(也可在预览上拖) |
| **面板资产手动绑定** | 漫画格可手动绑角色(多选)/场景(单选)/道具(多选),出图时取其镜像作参考图,跨格一致性有锚点 |
| **漫画格雷同检测** | 描述相似度 ≥70% 自动挂警告,可跳转对比或单格重抽,避免整集出同一张图 |
| **视频风格前缀** | 三处视频生成统一补画风前缀,不再默认退化成动画 / 二次元风 |
| **画风预设** | 20 条,新增「皮克斯 3D」;项目设置一处切换,漫画资产与漫画格共用 |
| **`/help` 速查** | 聊天改图输入框打 `/help`,列出全部可用写法(白名单确定性命中 / 需识图 / LLM 兜底,三类分开标注) |
| **就绪总览** | 顶栏「?」列出 7 类服务(文本 / 图片 / 视频 / 配音 / 换脸 / JEV / PhotoCraft)是否就绪,未就绪行可点直达设置 |
| **可点击链接** | 设置页每条配置的 Base URL 是真链接,点一下浏览器直达;PhotoCraft / JEV 未就绪时直接给官方下载 / 申请入口 |
| **连接测试有等待态** | 后台线程跑,按钮变「测试中…」,慢服务不再冻结界面 |

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
