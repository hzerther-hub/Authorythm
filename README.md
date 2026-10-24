<!-- 此注释表明此 README 的语言。其它语言的 README 见同目录下的兄弟文件。 -->
> **语言 / Language / 言語 / 언어**: **简体中文** | [繁體中文](README.zh-Hant.md) | [English](README.en.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Français](README.fr.md) | [Deutsch](README.de.md) | [Italiano](README.it.md) | [Português](README.pt.md) | [Español](README.es.md) | [Tiếng Việt](README.vi.md) | [Türkçe](README.tr.md) | [العربية](README.ar.md) | [हिन्दी](README.hi.md) | [Bahasa Indonesia](README.id.md) | [ภาษาไทย](README.th.md)

# 易好短剧 · PySide6 版 / Yihao Shorts (PySide6 Edition)

AI 短剧/小说/漫画一站式制作工具。功能 100% 对齐开源项目 [ooooinfo/yihao_drama](https://gitee.com/ooooinfo/yihao_drama.git) (Web 版),并集成了三个社区工具的核心能力:
- **[golanse/easymerger](https://github.com/golanse/easymerger)** — 无损视频合并(参数检测/智能直通/一键对齐异类)
- **[liangdabiao/video-clone-lite](https://github.com/liangdabiao/video-clone-lite)** — 同款复刻(爆款视频结构迁移到你的产品)
- **[mangfufu/director-desk](https://github.com/mangfufu/director-desk)** — 导演台 3D 白模预演(MIT;内嵌其原版 web 构建,详见下文「导演台预演」)

> 黑盒分析报告: [docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md) · 实施计划: [PLAN.md](PLAN.md) · 过程记录: [PROGRESS.md](PROGRESS.md)

---

## 🌐 语言支持(16 种)

**界面语言与 AI 内容语言是同一个开关,内置 16 种**(简繁中文 + 14 种其他语言):

简体中文 / 繁體中文 / English / 日本語 / 한국어 / Français / Deutsch / Italiano / Português / Español / Tiếng Việt / Türkçe / العربية / हिन्दी / Bahasa Indonesia / ภาษาไทย

- 切换入口:顶栏「界面与 AI 内容语言」或「设置 → 通用」;
- 切换后界面文案与 AI 产出(剧本/资产提取/分镜/提示词/小说/文案)**同时**使用所选语言;
- 非 zh/en/ja/ko 的语言通过在 Agent System Prompt 末尾注入显式输出语言指令实现(防止模型漂回英文);
- **繁体中文不走 AI**:`zh-Hant` 的产出在 AI 出口统一经 OpenCC(`s2twp`,词组级消歧 + 台湾用词,如「软件→軟體」)转换,不额外调模型;OpenCC 缺装时优雅退化为简体,不影响启动;
- 本地化文件:`app/core/i18n.py`(主表 + `_t()` fallback)+ `app/core/ui_strings.py`(15 语言全量翻译表,新增语言只需在 `LANGS` 加一行 + 补一列 15 元素 list)。
- **Edge TTS 朗读同步 16 语种**: 切换到「朗读音色」(女声/男声)后,Edge TTS 读出章节文本时,按主脚本自动从 16 语种 × 男女 = 32 个微软神经 voice 中选一个,语种变了 voice 自动切。

## 🔊 Edge TTS 朗读(免费神经语音)

`dramas.metadata.tts_gender`(`female` / `male`)驱动,链路 4 段:

1. **Path A/B 火山豆包**(用户配了 API Key 时) → 付费高质量
2. **Path C Microsoft Edge TTS**(默认) → **免费云端神经语音,无 API Key、无需下载语言包**,只要联网就有声
3. **detect_lang(text)** 用「脚本扫描 + langdetect + 繁中独有字」三重判定,16 种系统界面语言全覆盖
4. **EDGE_VOICE_LIST** 32 个 voice 预设(微软 Azure Neural voices),按 `text 主语言 + gender` 自动选

朗读入口:集工作台「原始内容」面板 → 「🔊 朗读本章」→ 走 `novel.read_aloud` 全集串行合成,完成后弹 `AudioPreviewDialog` 内嵌播放窗口(标题带 `voice 名 + 女声/男声`),用户再次点会弹「重放/重新生成」二选一。分镜旁白走同一入口,`storyboards.narration_voice` 字段记录真实 voice。

## 🎦 导演台预演(内嵌 DirectorDesk)

3D 白模预演与摄影机调度——分镜拆完先在三维场景里「预演」一遍:人物站位/走位、机位/运镜/切镜,导出**参考视频**再交给视频生成模型,把纯提示词生视频的不确定性压下来。

- **渲染内核 = 上游原版**:`scripts/fetch_directordesk.py` 从上游 [mangfufu/director-desk](https://github.com/mangfufu/director-desk)(MIT)Release 下载免安装包、解包其 web 构建(`app.asar`)到 `data/vendor/directordesk/`,由 QtWebEngine 内嵌运行——**渲染/动画/物理/视频导出跑的就是原版那份代码**,效果与原版逐位同源;`--latest` 可追新,默认固定版本保证可复现。
- **应用内入口**:顶栏「◫ 导演台」→ 选集 → 「生成预演工程」。内核未就绪时页面给「获取渲染内核」一键下载(约 170MB,一次性)。
- **分镜 → 预演工程**(`app/pipeline/previz_gen.py`):每镜一台摄影机(景别定焦距/距离、俯仰定高度、推/拉/摇生成运镜路径、黄金角错开机位方向),出场角色 → 男女白模(弧形站位朝向表演区,角色预览图内嵌为工程参考图),道具按关键词映射白模(床→bed、餐桌→table),每镜一条剧情备注(对白/情绪/动作)。
- **数据层**(`app/pipeline/previz.py`):对齐上游 `model.ts` 的 JSON 工程格式(dataclass + 校验,字段逐字一致),生成的 `.directordesk.json` 在内嵌画面里「工程 → 打开」即可精修。
- **导出回流**:导演台导出的参考视频经下载拦截自动落 `data/previz/exports/`,再走本系统视频流水线生成正式成片。

## 🌍 海外题材改写

把中文短剧改写为海外平台(ShortMax/ReelShort/DramaBox 等)目标市场题材的完整流水线:**诊断 → 术语表 → 改写 → 质检**。

- **规则库**(`data/overseas/`,用户可编辑):平台规格 × 品类套路 × 语言层 × 叙事层,按用户选择动态拼装(3 平台 × 4 品类全挂会撑爆 prompt,所以不进 Agent skill);
- **静态校验器**(`overseas_check.py`):按目标语言的书写系统(latin/cjk/other)检测中文残留、术语不一致等,error/warn 两级;
- **不覆盖中文原稿**:改写稿独立落 `overseas_chapter` 表,`episodes.content` 一个字节不动;
- **题材模板 14 语**:北印/日/韩/德/西/法/葡/意/泰/越/土/阿拉伯/印尼 + 美英,模板落 `workspace/prompts/` 同款机制;
- 入口:项目页「海外改写」对话框,选平台/品类/目标语言后先诊断再改写。

## ✨ 功能全景

| 模块 | 能力 |
|------|------|
| 项目启动台 | 统计/筛选(待开始·进行中·已完成)/搜索/删除(二次确认) |
| 新建项目(5 种创作目标) | 📖 写小说 · 🎬 生成短剧 · 📚 生成漫画 · 📣 宣传营销(平台×6/格式×6) · 🎞 同款复刻(新) |
| 导演台预演 | 内嵌原版 DirectorDesk:分镜 → 3D 白模预演工程(机位/走位/切镜)→ 参考视频回流视频流水线(见上节) |
| 海外题材改写 | 诊断→术语表→改写→质检;规则库可编辑;不覆盖中文原稿(见上节) |
| 项目说明 | 新建项目时**一句想法**生成项目名称/简介/创意描述/题材(`project_concept`) |
| 视觉风格 | 风格预设**三分类**(视觉风格/漫画画风/写作风格)20+ 条,完整复刻原版英文提示词,统一电影质感锚点 |
| 集工作台(六阶段) | 原始内容 → AI 改写 → 视漫制作 → 分镜 → 漫画 → 拼接导出 |
| AI Agent ×13 | 剧本改写/角色场景提取/分镜拆解/提示词/小说生成/策划/六维审校/改稿/漫画分镜/**梗概扩剧本**/宣传文案/**海外诊断/海外改写**,System Prompt 全开放可编辑(`workspace/prompts/*.md`) |
| AI 服务 | 文本/图片/视频/配音 四类多供应商(OpenAI 兼容、Gemini、火山 Seedance/Seedream、MiniMax、阿里 Wan、Agnes、qwen-image、本地 InsightFace 换脸),易好 Key 一键配置,连通测试 |
| 任务系统 | 统一任务队列(sys_task),processing → completed/failed,任务面板 |
| 无损合并工具页 | ffprobe 参数一致性检测(分辨率/编码/帧率/Profile/采样率)→ 三通道:全一致 `-c copy` 秒合 / 视频一致音频不同→智能直通 / 少数异类→一键对齐多数派;失败回退链(换中间容器→重编码) |
| 同款复刻 | 参考视频抽帧 → AI 出分镜表 → 产品/模特素材 → 逐镜首帧图+图生视频 → 按原片节奏无损拼接 |
| 小说线 | 开书策划(总纲/世界观/合约/卷/章节)→ 逐章生成 → 六维审校 → 按指令改稿 → 导出整本 |
| 审校降噪 | 审校 issue 真假混杂 → Jev 一次性评分(0 忽略/1 应修/2 必修),修复循环只修值得修的,不为误报烧重写轮(`jev_triage`) |
| 漫画一键出整话 | 「📚 梗概生漫画」:100-1000 字梗概 → 扩成 4-8 场景剧本 → 拆格 → 逐格出图(链式馈送)→ 拼长图,两阶段后台任务任一失败都报 toast;单格失败不中断 |
| 小说模型分设 | **规划模型**(开书策划/分卷/章节计划/角色)与**正文模型**(写章/审校/改稿/章节名)两个下拉分开选。实测依据:minimax-M3 写正文三章 6538 字无衰减,deepseek-v4-pro 5332 字逐章掉 53%;而分卷/合约的结构化 JSON 反过来是 deepseek 更规整 → 详见 `docs/小说-规划与正文模型分设.md` |
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
| UI 语言 | 15 种 | 16 种(含 zh-Hant,繁体产出走 OpenCC 词组级转换) |
| AI 内容语言 | 15 种(跟随项目) | 16 种(全局 + **项目级独立**) |
| Agent 提示词变体 | 4 语言硬编码 | **多语言**(168 文件,13 Agent;含漫画梗概扩剧本与海外诊断/改写) |
| Skill 变体 | 4 语言 | **多语言**(165 文件,含打斗运镜技能) |

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
| 结构化日志 | JSON 落 `data/logs/`(10MB×5 轮转),`sk-xxx`/`Bearer`/长 base64 自动脱敏;WARNING+ 可挂 toast |
| 进程内指标 | `metrics.incr/observe` 埋点(命名 `subsystem.event.unit`),周期刷盘 |
| API Key 加密 | Fernet + 机器指纹派生密钥(`app/core/secrets.py`),落库自动加密、读出透明解密;老库自动迁移 |

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
| **导演台预演** | 内嵌上游 DirectorDesk 原版 web 构建(QtWebEngine);分镜一键生成 3D 预演工程(机位/走位/切镜/剧情备注),参考视频导出自动落 `data/previz/exports/` |
| **海外题材改写** | ShortMax/ReelShort/DramaBox 等平台的题材规则库 + 静态校验器 + 改写流水线;改写稿独立落库,中文原稿零改动 |
| **繁体产出 zh-Hant** | AI 出口统一 OpenCC `s2twp` 词组级转换(头发→頭髮、软件→軟體),不走 AI;缺装优雅退化 |
| **漫画一键出整话** | 梗概(100-1000 字)→ 扩剧本 → 拆格 → 逐格出图 → 拼长图全链路;链式馈送保跨格一致 |
| **审校降噪** | Jev 对审校 issues 一次性评分,只修 ≥1 的;全部可忽略则跳过修复轮 |
| **项目说明** | 新建项目一句想法 → AI 生成名称/简介/创意描述/题材 |
| **风格预设三分类** | 视觉风格 / 漫画画风 / 写作风格 三类独立管理,语义修复(停用≠删除),16 语名对齐 |

## 🚀 快速开始

```bash
# 要求 Python 3.10+(开发验证于 3.13)
pip install -r requirements.txt

# 运行
python -m app.main          # 推荐(包内模块方式)
# 或双击 start.bat
```

<details>
<summary>导演台预演内核下载(可选,也可在应用内一键获取)</summary>

```bash
python scripts/fetch_directordesk.py             # 下载上游 Release → 解包 web 构建
python scripts/fetch_directordesk.py --latest    # 追最新版(默认固定 v0.5.1,可复现)
python scripts/fetch_directordesk.py --zip x.zip # 离线包(先手动下载 Portable win-x64)
python scripts/previz_smoke.py                   # QtWebEngine 渲染冒烟验证
```

不下载也不影响其它功能:「导演台」页会显示引导,点「获取渲染内核」按钮即自动完成。
</details>

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
  core/    config.py(路径/ffmpeg) db.py(23表+种子) i18n.py(16语言) ui_strings.py(15语翻译表)
           zh_convert.py(OpenCC 繁体) secrets.py(Key加密) logging_setup.py metrics.py taskmgr.py theme.py(QSS)
  ai/      registry.py(服务注册表) text_client.py image_client.py video_client.py tts_client.py face_swap.py
  agents/  prompts.py(10 Agent 提示词+多语言机制) runner.py(执行器,出口收口繁体转换)
  pipeline/ rewriter.py extractor.py storyboard.py prompts_gen.py comic.py comic_pipeline.py(一键整话)
           novel.py(规划/正文模型分设) promo.py overseas.py(海外改写) previz.py+previz_gen.py(导演台工程)
           merge.py(easymerger 逻辑) stitch.py(长图) video_clone.py(同款复刻) jev_triage.py(审校降噪)
  ui/      main_window.py projects_page.py new_project_dialog.py project_page.py
           episode_page.py(六阶段工作台) previz_page.py(导演台内嵌) overseas_dialog.py
           settings_dialog.py task_panel.py merger_tool_page.py chat_edit_drawer.py widgets.py
assets/fonts/  打包字体(微软雅黑,对齐原版 drama 字体栈回落策略)
workspace/prompts/  150 个 Agent System Prompt(多语言,用户可改)
data/vendor/directordesk/  导演台 web 构建(fetch_directordesk.py 解包,gitignore)
docs/          分析报告/计划/过程/截图
```

## 📄 许可

延续原版 CC BY-NC-SA 4.0。FFmpeg 以子进程调用,其 GPL/LGPL 许可不影响本项目。

**导演台预演**所用 [mangfufu/director-desk](https://github.com/mangfufu/director-desk) web 构建为 **MIT** 许可(构建产物运行时由 `scripts/fetch_directordesk.py` 从上游 Release 获取,不入版本库;其第三方动作素材许可见上游 `src/animation/library/NOTICE.txt`)。Edge TTS / OpenCC 分别遵循各自服务条款与上游许可。

---
## 📖 小说生成逻辑与「小说策划与设定」的作用

### 概览

pydrama 小说(`work_type=novel`)项目的生成走 `app/pipeline/novel.py`,核心是**两次 AI 调用链**:
1. **策划与设定**:`NovelPlanDialog`(`app/ui/novel_dialogs.py`)让用户写 4 块设定 → `AI 起草 → 保存到 dramas 表`
2. **章节生成**:`generate_chapters_batched` → `write_chapter_with_review` → **LangGraph 审校循环**

### 标题 / 描述 / 创意 三件套

| 字段 | 来源 | 用途 |
|---|---|---|
| **title** | dramas 表 / 用户手动 | 文件名 / 启动台展示 / 全部 prompt 锚点 |
| **intro** | `novel_meta.intro`,用户输入,`AI 自动续写` | 章节 prompt 上下文 → 模特接到"项目是什么" |
| **genre** | `novel_meta.genre`,用户选 | 章节 prompt `style:` 前缀注入,影响写作风格 |

### 「小说策划与设定」在生成小说中的作用

`NovelPlanDialog` 让用户填 **4 块设定**,每块都是**独立的 AI 起草任务**,但有 PREREQ 依赖:

```
PREREQ 依赖:
  outline  (总纲)   ─── 地基,没总纲后面都写不出来
       ↓
  world    (世界观)  ─── 在总纲划定的边界内展开
       ↓
  contract (故事合约) ─── 人称 / 视角 / 风格 / 硬约束
       ↓
  volume   (分卷战略) ─── 把总纲切成卷
```

#### 4 块设定的内容与作用

| 块 | 存储位置 | 章节生成时怎么用 |
|---|---|---|
| **outline 总纲** | dramas.novel_outline | 注入章节 prompt → "项目走向" + 主要角色 + 冲突 |
| **world 世界观** | dramas.novel_world | 注入 → 时间 / 地理 / 法规 / 习俗,character 落点不能破 |
| **contract 合约** | dramas.novel_contract | 注入 → POV / 文学性 / 文风 / 硬约束 |
| **volume 分卷战略** | dramas.novel_volume | 注入 → 当前章节在卷中的位置 + 卷的整体走向 |

加上用户`plan_novel(drama_id, idea, ...)`输入的 idea (`novel_meta.intro` 当 prompt 种子),
→ 这 5 个上下文共同组成每次章节生成时的 prompt 上下文,缺一个章节就会"风格漂"。

### 章节生成 + 审校流程(C.1 + C.2)

`write_chapter_with_review` (在 `app/pipeline/novel.py:918`)现在内部走 `run_novel_review_loop`,
`run_novel_review_loop` (在 `app/agents/novel_review_flow.py`)有 5 个节点:

```
   ┌──────────┐    ┌─────────┐
   │  WRITER  │───▶│ CRITIC  │
   └──────────┘    └────┬────┘
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
  ┌─ REPAIR ─┐   ┌─ COMPRESSOR  ┐  ┌─ END ┐
  │   ▲      │   │   (terminal) │  │      │
  └─JEV──────┘   └───────────────┘  └──────┘
```

- **WRITER**:调 `write_chapter(episode_id, ...)` → 落库 sys_task.stage=`writing`
- **CRITIC**:调 `review_chapter(episode_id, ...)` → 六维审校(连贯 / 节奏 / 文笔 / 角色 / 设定 / 调性)
  - `overall=pass` → **OK** 进 compressor
  - `overall=fix` + 1-4 issues → **revise** 进 repair
  - `overall=fix` + ≥5 issues → **rewrite** 回 writer(整章重写更划算)
  - cycle ≥ `max_cycles`(默认 3)→ **giveup** 强退
- **REPAIR**:`run_agent("novel_editor", ...)` 生成修复版正文 → 落库
- **JEV GATE**:调 `jev_gate().client.decide(...)` 检查**连续性**
  - `<0.5` 不连续 → **rewrite** 回 writer
  - `≥0.5` 通过 → **pass** 再 critic 一轮
  - 未配 / 异常 → 透传(走 critic)
- **COMPRESSOR**:终态,把通过的 draft 推 `final`,调用方入库

### LangGraph vs Fallback 双轨

| 模式 | 触发 | 价值 |
|---|---|---|
| **Fallback**(默认) | `LangGraph` 没装 | 同样的节点函数直接 cycle loop 跑,行为等价 |
| **LangGraph 真图** | `pip install langgraph` | 自动切到 StateGraph 调度 + 可挂 LangSmith trace + `interrupt_before=["jev_gate"]` 中途暂停 |

切换零代码:`pip install langgraph` 即可。其他 13 个 README 看本节开头 → 文档链向完整章节。

