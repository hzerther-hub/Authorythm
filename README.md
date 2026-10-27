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
- **繁体界面也走同一套 OpenCC**:繁中表不再从英文表派生,而是「简体中文基准 → `s2twp` 转台湾正字 → 人工校订覆盖」。此前 `T["zh-Hant"] = _t(T["en"], ...)` 导致未翻译的键继承英文,实测 1554 个基准键里只有 107 键是真繁体、1251 键显示简体、1446 键显示英文 —— 「繁體中文」这个选项等于没做。现已修正为 1870 键全覆盖(基准 1554 + 补充词典独有条目 316),英文泄漏 0、缺值 0。
  - 转换在**首次切到繁中时惰性执行**(opencc import 约 45ms + 1554 键转换约 70ms),没选繁中的用户不付这个成本;
  - 与 AI 产出同源:界面看到的繁体和 AI 写的繁体是同一套转换规则,不会出现「界面『頭髮』、正文『头发』」;
  - 人工校订表 `ZH_HANT_MANUAL`(`app/core/i18n.py`)优先于自动转换,留给 OpenCC 转不地道的地方(台湾惯用词、全角标点、专有名词);
- 本地化文件:`app/core/i18n.py`(主表 + `_t()` fallback + `ZH_HANT_MANUAL`)+ `app/core/ui_strings.py`(15 语言全量翻译表,新增语言只需在 `LANGS` 加一行 + 补一列 15 元素 list)。
- **完整度已清零**(2026-10-26 全量体检):`python scripts/i18n_audit.py` 当前输出 **露键名 0 / 露中文 0 / 漏译 0 键 0 处 / 繁中缺值·显英文·值不符 0/0/0 / 日语同中文 0 / 占位符丢失 0 / 有基准零译文 0**;`tests/_i18n_gaps.json` 回归基线**已清空**(此前 146 个露键名 + 145 键/2015 处漏译)。
  - 同轮还修掉三类「不是漏译、但更难看」的问题:**「镜(镜头)」被机翻成「镜子/mirror」**(26 槽)、**串语种**(印尼语串进阿拉伯语槽、法语串进日语槽、中文串进越南语槽等 20 槽)、**U+FFFD 乱码残留**(界面直接显示「���」,23 处)。
  - `scripts/i18n_runtime_check.py` 做**运行时**逐语种体检(查原始表没用:各语种主表是从英文表继承的,全是假警报);英文基准要取「有效英文值」而不是 `T["en"]` —— 补充词典里 324 个 S-only 键不在 `T["en"]` 里,直接取会漏判。
  - `tests/test_i18n_coverage.py` + `tests/_i18n_gaps.json` 守住基线不反弹,另有 **5 条硬守卫**(2 条繁中 + 3 条「值错」类,缺值/错值即红,不走基线)。
  - **第 2 轮**(同日晚些时候)又挖出 4 类「有值、但值是错的」问题 —— 这类**不会触发任何漏译判据**,审计全零也照样存在,共 56 个槽位:**量词/正文被吞**(`items_n` 有 7 个语种只剩 `{0}`)、**葡语原文串进西语槽**(5 键;葡西都是拉丁字母,汉字判据与英文判据**同时失效**)、**整句留英文**(`,{} 章失败` 有 6 个语种全是英文)、**词义错**(`应用` 只当 Apply 按钮用,却按「应用程序/app」译了 15 个语种)。全部已修,并补了 2 条对应硬守卫。
  - **第 3 轮**继续挖出:**非汉字语种(ar/hi/th)漏出中文** 5 处(ar 槽整段中文、ar 里塞汉字「切换」、hi 留个「第」、th 结尾留「生效」)、**语言列表 ja/id/th 三行共用中文列表**(泰语/印尼语用户看到的是中文语言列表)、4 处标签重复词(`Diller / Diller:`)。同时把漏译判据本身的两个盲点补上:中文基准不能只取 `i18n.Z`(324 个 S-only 键从来没被漏译判据看过)、拉丁字母语种渲染出**汉字**就算漏译(逐字相同会漏掉「差一个字」的中文)。全部已修,并补了 1 条对应硬守卫。
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
| 同款复刻 | 参考视频抽帧 → AI 出分镜表 → 产品/模特素材 → 逐镜首帧图+图生视频 → 按原片节奏无损拼接。**三要素锚定**(立绘/空景/产品三图同喂首帧与视频模型)+ 服装锁定 + 特写只禁第二个人的手 + 口播随产品同步改写 + 场景锚空景双锚 + 视觉风格贯穿;步骤按钮按执行顺序排列,批量出视频(全部/补全),成片区最多 8 个可播放/下载/删除,合并可加片头 |
| 小说线 | 开书策划(总纲/世界观/合约/卷/章节)→ 逐章生成 → 六维审校 → 按指令改稿 → 导出整本 |
| 审校降噪 | 审校 issue 真假混杂 → Jev 一次性评分(0 忽略/1 应修/2 必修),修复循环只修值得修的,不为误报烧重写轮(`jev_triage`) |
| 漫画一键出整话 | 「📚 梗概生漫画」:100-1000 字梗概 → 扩成 4-8 场景剧本 → 拆格 → 逐格出图(链式馈送)→ 拼长图,两阶段后台任务任一失败都报 toast;单格失败不中断 |
| 小说模型分设 | **规划模型**(开书策划/分卷/章节计划/角色)与**正文模型**(写章/审校/改稿/章节名)两个下拉分开选。实测依据:minimax-M3 写正文三章 6538 字无衰减,deepseek-v4-pro 5332 字逐章掉 53%;而分卷/合约的结构化 JSON 反过来是 deepseek 更规整 → 详见 `docs/小说-规划与正文模型分设.md` |
| 项目级"温画画风" | `dramas.comic_style` 字段统一漫画资产/漫画格画风,项目设定一键切;其它漫化页不重复下拉 |
| 项目级"朗读音色" | `dramas.metadata.tts_gender` 字段统一男女声(女声/男声) → Edge TTS 16 语种 × 男女 32 个神经 voice 自动选 |
| Edge TTS 免费神经朗读 | 微软云端 Microsoft Edge TTS,**无需 API Key**,**不需下载语言包**,只要联网就有声;脚本旁白 + 整章朗读 同一链路;播放窗口带 voice 名字 |
| 漫画跨格一致性 | 链式 keyframe 馈送(上一张 panel 出图后 url 喂给下一张)+ character_variants 多角度参考图(优先取变体图,没有时退回主图),跨格角色/场景/光影保持一致 |
| 整书导入 → 仿写 | TXT 整书导入 → 三级切章入库 → 12 章一组 Map-Reduce 出仿写档案(失败率过高自动暂停)→ 按设定/总纲/分卷建新项目。**专名全换、情节仿而不抄、结构保留**;依赖链未满足时按钮置灰并给原因 |
| 换脸工具页 | 独立三段式向导:①源人脸(上传/剪贴板/URL/从其他角色形象选)→ ②角色模板图(载入基础形象 + 全部造型变体)→ ③结果区(逐张 ok/失败角标 + 进度条)。角色卡内另有「资产·角色换脸」弹窗,可写回 `characters.image_url` |
| 封面加字 | 文字/字体/字号/颜色/透明度/位置(3×3 九宫格 + **预览图上直接拖拽定位**)/竖排;字体下拉来自 `app/assets/fonts` 10 款(含之芒行楷) |
| 局部修补 | 涂抹要改的区域 → 洋葱填充式 inpaint,**蒙版外像素与原图逐字节一致** —— 比例必然相同、绝不凭空加人物、还不花生图额度 |
| 图库搜图 | 「图片处理」「聊天改图」共用弹窗,选中图**先下载到本地**再交给下游(下游按本地路径写,直接塞远程 URL 会在一半地方炸);没配 key 只提示不阻断 |
| 片头模拟器 | 对齐原版 IntroEditorDialog.vue:预览项目画幅 → 拖拽定位文字中心点 → 真字体 WYSIWYG → 播放预览模拟淡入淡出 → 改动即存 |
| 盲文等待指示器 | 全项目统一的忙碌指示(点字方块 ⠿ 循环变化),替代各页各写一套的「生成中…」标签 |
| 数据 | SQLite 单文件(**29 张表**)+ 本体媒体存储,`data/` 目录即全部数据 |

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
| UI 语言 | 15 种 | 16 种(zh-Hant 的**界面**与**AI 产出**同走 OpenCC `s2twp` 词组级转换,界面不再漏英文/简体) |
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
| 单实例闸门 | 启动时 `db.claim_single_instance()` 抢锁,抢不到直接退出并提示已在运行 —— 两个进程同时写同一个 SQLite 会互相覆盖用户数据(实测踩过)。需要多开时设 `PYDRAMA_ALLOW_MULTI=1` |
| i18n 回归守卫 | `tests/test_i18n_coverage.py` + `tests/_i18n_gaps.json` 基线快照:露键名/漏译/日语同中文/占位符丢失四类缺口**只减不增**;`scripts/i18n_audit.py` 出全 16 语言的当前缺口报告 |
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

体检脚本(改完 i18n 或文档后跑一遍):

```bash
python scripts/i18n_audit.py        # 全 16 语言 i18n 缺口报告(露键名/漏译/繁中缺值/占位符)
python scripts/i18n_runtime_check.py # 运行时逐语种体检(串语种/回落英文 —— 查原始表会全是假警报)
python scripts/i18n_gap_baseline.py # 回归基线快照(只减不增,配合 tests/_i18n_gaps.json)
python scripts/readme_factcheck.py  # README 里的数字与仓库实际状态对账(表数/提示词数/UI 文件数)
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
  core/    config.py(路径/ffmpeg) db.py(29表+种子) i18n.py(16语言+ZH_HANT_MANUAL) ui_strings.py(15语翻译表)
           zh_convert.py(OpenCC 繁体,AI 产出 + 繁中界面共用) secrets.py(Key加密) logging_setup.py metrics.py
           taskmgr.py theme.py(QSS)
  ai/      registry.py(服务注册表) text_client.py image_client.py video_client.py tts_client.py face_swap.py
  agents/  prompts.py(13 Agent 提示词+多语言机制) runner.py(执行器,出口收口繁体转换)
  pipeline/ rewriter.py extractor.py storyboard.py prompts_gen.py comic.py comic_pipeline.py(一键整话)
           novel.py(规划/正文模型分设) book_import.py(整书导入→分析→仿写) promo.py overseas.py(海外改写)
           previz.py+previz_gen.py(导演台工程) merge.py(easymerger 逻辑) stitch.py(长图) video_clone.py(同款复刻)
           jev_triage.py(审校降噪) video_poster.py(视频海报帧)
  ui/      main_window.py projects_page.py new_project_dialog.py project_page.py
           episode_page.py(六阶段工作台,≈8k 行) previz_page.py(导演台内嵌) overseas_dialog.py
           settings_dialog.py task_panel.py merger_tool_page.py chat_edit_drawer.py widgets.py
           book_import_dialog.py(整书导入) face_swap_page.py(换脸向导) cover_text_dialog.py(封面加字)
           patch_dialog.py(局部修补) stock_photo_dialog.py(图库搜图) intro_dialog.py(片头) braille.py(盲文等待)
assets/fonts/  打包字体(微软雅黑,对齐原版 drama 字体栈回落策略)
workspace/prompts/  168 个 Agent System Prompt(13 类 Agent,多语言,用户可改)
workspace/skills/   165 个技能文件
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

