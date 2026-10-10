# PROGRESS.md — 实施过程记录

> 逐项记录 PySide6 重写「易好短剧」的全过程(倒序,最新在上)。
> 计划:[PLAN.md](PLAN.md) · 分析:[docs/易好短剧-工具分析.md](docs/易好短剧-工具分析.md)

## 2026-09-29(第 1 天,完成全部里程碑 M1–M7)

### M7 运行验证与收尾 ✅
- offscreen 冒烟:主窗口启动 → 启动台 → 项目页 → 工作台六阶段切换 → 合并工具 → 设置 → 新建对话框(复刻/宣传表单),全流程无异常。
- **视觉验收(agent 评审 13 张截图)**:12/13 通过。发现并修复:
  1. 资产页内容空白 —— 原因是 `QTabWidget` 内嵌 `QScrollArea` 嵌套塌陷,去掉内层滚动后数据正常显示(修复后复验通过);
  2. 导出页/合并工具页缺空态提示 —— 补「—」空态标签与操作引导;
  3. offscreen 中文方块字 —— offscreen 平台缺 OpenType 支持;**按用户指示采用原版 drama 的字体方案**:drama 源码本身不打包字体,CSS 字体栈为 `SF Pro → PingFang SC → Microsoft YaHei`(body/display)与 `SF Mono/Consolas`(mono);PySide6 版实现同一策略:`theme.py` 的 QSS 使用完全相同字体栈,`main._apply_drama_font()` 优先加载 `app/assets/fonts/` 打包字体(已内置 msyh.ttc,19.7MB),macOS 回落 PingFang SC / Windows 回落 Microsoft YaHei UI。复验后中文全部正常渲染。
- 最终截图 13 张:`docs/screenshots-pyside6/01~13*.png`。
- README:**四语言**(zh/en/ja/ko),每份都含 15 语言支持说明;PROGRESS.md(本文件)。

### M6 UI 层 ✅(9 个界面文件)
- `widgets.py`:卡片/标题/标签/头像(按名字哈希配色)/StatBar/图片加载(/static 相对地址→本地路径)。
- `projects_page.py`:启动台(统计条/筛选下拉/搜索/最近排序/项目卡/更多菜单删除,级联清空 12 张关联表)。
- `new_project_dialog.py`:5 种创作目标单选(宣传→动态追加平台/格式必填;复刻→动态追加参考视频/产品照/出镜照三个文件选择)、风格下拉按 work_type 过滤、比例、面孔文化。
- `project_page.py`:EP 卡片(状态 chip/镜头进度/删除)+「进入制作」;素材库网格(角色/场景/道具混排,图片/描述/生成状态)。
- `episode_page.py`(最大,~800 行):顶栏模型选择(文本/图片/视频/分辨率)+任务入口;左侧 StepNav(剧本/制作/导出三段,进度 x/4);六面板:
  - 原始内容:目标字数/文风/AI 生成小说(自动先策划)/批量写后续章/保存;
  - AI 改写:调 script_rewriter 回写剧本;
  - 视漫制作:提取(全部或按类)/逐资产卡片(AI 最终提示词/重绘/上传/换脸)/批量出图/就绪统计;
  - 分镜:重新拆分/批量补齐提示词/批量视频/单镜重绘/逐镜旁白行内编辑+TTS 按钮/状态统计(生成中·完成·失败)/本地播放;
  - 漫画:拆格/逐格出图/旁白编辑/拼接长图(Pillow,白底+间距+旁白条);
  - 导出:成片列表(下载/时长/状态)+镜头勾选拼接(≥2)+标记完成。
- `settings_dialog.py`:六分区——AI 服务(易好快捷配置/四类服务列表/新增向导(厂商模板+模型+Key)/双击编辑/连通测试/启停)、通用(**语言下拉 15 种**,切换同时写 ui_language+content_language)、风格预设(双击编辑名/描述/提示词/启停)、Agent 配置(10 Agent 列表 + 15 语言下拉切换编辑 System Prompt,保存到 workspace/prompts/,恢复默认)、存储位置(路径+占用统计+打开目录)、关于更新(版本/GitHub Releases 检查)。
- `task_panel.py`:sys_task 表格(ID/类型/模型/状态/时间,状态着色,订阅 TASKMGR.updated 自动刷新)。
- `merger_tool_page.py`:easymerger 工作流(导入文件/文件夹→后台 ffprobe 检测→参数表格(异类标红)+结论条→一键对齐异类→全自动合并→打开输出目录)。
- `main_window.py`:顶栏(Logo/项目/合并工具/语言/主题/设置)+页面栈(启动台/项目页/工作台/复刻页/合并工具)+新建项目全流程(含复刻素材导入)+宣传文案对话框+语言切换(重启生效提示)+主题切换;`ClonePage` 同款复刻工作台(分析原片→生成模特→逐镜首帧图→逐镜视频→无损拼接)。

### M5 流水线 ✅
- `rewriter.py`(script_rewriter→格式化剧本)、`extractor.py`(提取+按名去重合并+episode 关联)、`storyboard.py`(分镜拆解+批量 video_prompt)、`prompts_gen.py`(角色三视图/场景三层构图/道具单品图提示词)、`comic.py`(漫画格+旁白)、`novel.py`(策划五件套/逐章生成带前情/六维审校/按指令改稿/导出整本 txt)、`promo.py`(6 平台×6 格式文案)。
- **`merge.py`(easymerger 完整逻辑)**:probe 指纹(宽高/编码/Profile/fps/像素格式/音频编码/Profile/采样率/声道)→ AnalyzeResult(多数派/差异项/异类/三通道判定)→ lossless_merge(concat demuxer+-c copy)→ 失败 _rescue(转 .ts 中间容器再 copy→仍失败整批重编码)→ smart_passthrough_merge(视频 copy+音频统一 aac 48k 立体声)→ align_one/align_outliers(只转异类到多数派参数,对齐后逐参数校验)→ auto_merge 全自动选通道;另有 merge_episode(剧集拼接,旁白 MP3 filter_complex amix 混音,对齐原版 ffmpeg-merge)。
- **`video_clone.py`(video-clone-lite 逻辑)**:import_reference/upload_material→extract_frames(ffmpeg 均匀抽帧)→analyze_reference(分镜表 JSON 存 metadata.clone)→prepare_presenter(AI 模特)→generate_shot_image(首帧图)→generate_shot_video(图生视频)→merge_clone(auto_merge 拼接)。
- `stitch.py`:漫画长条图(Pillow,统一宽 1080/白底/间距/旁白分行)。

### M4 Agent 层 ✅
- `prompts.py`:10 Agent 中文默认 System Prompt(职责/输出 JSON 格式/创作规范);`FILE_AGENTS` 9 类支持 `workspace/prompts/<agent>[.lang].md` 用户自定义(novel_editor 仅内置);**语言机制**:非 zh 时在 System Prompt 末尾注入 "You MUST write ALL your output in {lang}",覆盖全部 15 语言(超出原版 4 语言,按用户要求补全);`seed_prompt_files()` 首次落盘供设置页编辑。
- `runner.py`:run_agent(读设置语言→加载 system→文本模型)与 run_agent_json(鲁棒 JSON 提取:```json 围栏/整体/首尾大括号/中括号四路尝试)。

### M3 AI 服务层 ✅
- `registry.py`:四类(text/image/video/tts)配置 CRUD+默认项+易好 Key 一键写入三条推荐(MiniMax-M3/agnes-image-2.5-flash/agnes-video-2.5-flash)+厂商模板(含本地换脸 http://127.0.0.1:5678)+模型候选。
- `text_client.py`:OpenAI 兼容 chat/completions(支持 Gemini OpenAI 端点/MiniMax/DeepSeek,兼容 reasoning 数组内容)。
- `image_client.py`:openai|gemini|qwen-image 走 images/generations;volcengine(Seedream,b64/url);agnes(同步或任务轮询 5s×120)。
- `video_client.py`:volcengine(Seedance contents/generations/tasks 轮询)/minimax(video_generation+query)/aliyun(Wan 异步任务)/agnes(同步或轮询);分辨率档位表对齐原版。
- `tts_client.py`:火山豆包双路径(seed-tts-2.0 流式→seed-audio base64 兜底)+按 narration_duration 自适应语速(0.5–2.0)。
- `face_swap.py`:health/swap_one(base64 出入,落 images/)。

### M2 核心骨架 ✅
- `config.py`:YIHAO_DATA_DIR/SQLITE_PATH/STORAGE_PATH/WORKSPACE_PATH 环境变量(对齐原版)、ffmpeg/ffprobe 三级定位(env→PATH→vendor)、/static 相对地址↔本地路径互转。
- `db.py`:**23 张表 DDL**(dramas 含小说五件套/episodes/characters+variants/scenes/props/三张 episode 关联/storyboards+两张关联/旁白四字段/comic_panels+三张关联/ai_service_configs/style_presets/sys_task/video_merges/assets/app_settings)+索引;**20 条风格种子完整复刻原版**(8 创作+6 通用+6 宣传,英文提示词逐字对齐,统一电影质感锚点);示例项目种子(《归乡的井》:4 角色/5 场景/1 道具/6 分镜/6 漫画格/完整剧本);启动时把中断任务清为 failed(对齐原版)。
- `i18n.py`:**15 语言** zh/en/ja/ko/fr/de/it/pt/es/vi/tr/ar/hi/id/th;zh 基准约 150 个 key,en 全量,其余语言覆盖高频项(缺失回退 en→zh);LANG_OUTPUT_NAME 供 Agent 语言指令。
- `taskmgr.py`:QThreadPool(6 线程)+sys_task 落库,processing→completed/failed 状态机,提交/完成回调/按集统计。
- `theme.py`:浅色/深色 QSS 全套(卡片/主按钮/输入/表格/滚动条等)。

### M1 计划与工程 ✅
- PLAN.md(功能盘点 F1–F24/里程碑 M1–M7/与原版差异声明);
- git init + remote `https://github.com/hzerther-hub/PySide6_drama`;
- requirements.txt(PySide6/requests/Pillow)+ .gitignore。

## 关键决策记录
1. **Python 3.10+ 要求**(用户指定):开发验证环境 Python 3.13.15;类型语法用 `from __future__ import annotations` 保持前向兼容。
2. **语言 15 种补全**(用户指定):UI 与 AI 内容统一 15 语言(原版 AI 内容仅 4);非内置语言靠显式输出指令注入。
3. **合并引擎**(用户指定):不重复造轮子,直接移植 easymerger 的"能无损绝不转码"三通道策略与容错回退;剧集拼接也走同一 auto_merge(带旁白时走 filter_complex 混音路径)。
4. **同款复刻**(用户指定):作为第 5 种创作目标放进新建下拉,流程=video-clone-lite 的四步(看懂原片→备料→逐镜重拍→拼接);分镜表/素材/首帧/视频全部存 dramas.metadata.clone,单镜可重做。
5. **视觉风格**(用户指定"主要是电影质感的"):20 条种子逐字复刻原版(每条 prompt 都带 cinematic 锚点),不做自定义扩展。
6. **字体**(用户指定"用 drama 中的字体文件"):原版无内置字体文件,采用其 CSS 字体栈策略;为跨环境一致额外打包 msyh.ttc 并内置加载。

## 2026-09-29(第 2 轮:服务对话框对齐原版 + Logo)
- **服务对话框重做**(用户给出原版截图):新增 `ServiceDialog` —— 模板快选芯片(Gemini/OpenAI/MiniMax/Agnes 官方等,点击自动填配置名称+服务商+Base URL+默认模型)、配置名称(存 remark)、服务商下拉(可编辑)、优先级(数值越高越优先,工作台取同类型最高优先级启用配置)、API Key、Base URL、**多模型标签编辑器 ModelChipsEditor**(首位默认高亮,点标签置顶,× 删除,输入框支持逗号/换行批量,新增按钮)、Temperature(留空跟随服务默认;填写则 text_client 强制覆盖,应对 kimi-k2 等强制温度模型)、底部 测试配置/取消/保存。模板模型清单逐字对齐原版推荐矩阵(gemini-3.8-flash / deepseek-v4-pro / doubao-seedance-2-0-mini-260615 等)。
- **AI 服务页**:新增「手动模板」卡片(文本/图片/视频/配音 四芯片直接打开对应服务类型的新增对话框),对齐原版第二张截图;修复服务列表构建时 findChild 找不到未入树控件的 bug 与 itemDoubleClicked 重复连接 bug;列表项显示 配置名称·模型·优先级·状态。
- **数据层**:ai_service_configs 幂等加列 `models`(JSON 多模型列表)与 `temperature`(REAL);registry.add_config 扩展 priority/models/temperature,同类型第一条配置自动设默认;default_config 改为优先级优先排序。
- **Logo(用户指定从原参考文件取出)**:复制原版 `frontend/app/public/icon-192.png`(橙色圆角方块白"易"字)为 `app/assets/logo.png`(另存 512/favicon),用于窗口图标 setWindowIcon 与顶栏 Logo 图;顶栏文案与窗口标题按用户要求**去掉 "PySide6" 字样**,只保留「易好短剧 / Yihao Shorts」(i18n 四语言 app_title 同步更新)。
- 截图:14-service-dialog.png(与原版界面逐项对齐)/ 15-main-with-logo.png / 16-settings-manual-tpl.png。

## 2026-09-29(第 3 轮:换脸工具页)
- **独立换脸工具页**(对齐原版 /tools/face-swap,用户要求"换脸的也要加入"):顶栏新增 🎭 换脸 导航;页面含服务健康检查(实测本机 5678 InsightFace 服务在线,显示 `ok · inswapper_128`)、导入目标图(多张卡片)、选择源脸照片、"替换图中所有脸"/"人脸增强"参数、逐张换脸(任务队列)、结果回填卡片预览、下拉选角色「存为角色形象」落库。
- **face_swap 客户端按原版 API 重写**:原 face-swap-service 真实接口为 `{source_url, template_url, source_index, swap_all_faces, face_enhance, save_local_path}`(source=脸来源,template=被换图),响应 `image_base64`;旧客户端字段名错误已修正(data URL 编码上传)。
- 附:工作台资产页的每角色「换脸」按钮沿用同一客户端,自动受益。
- 截图:17-face-swap-page.png。

## 2026-09-29(第 4 轮:换脸模型类型 + 导航中文化)
- **换脸成为第五类 AI 服务模型**(用户要求"模型那里加入换脸模型,可本地可远程"):registry.SERVICE_TYPES 增 `faceswap`,预设模板「本地 InsightFace (CPU) @127.0.0.1:5678」与「远程换脸服务(自填地址)」,首启自动种子本地配置;设置页第五个"换脸"标签(与文本/图片/视频/配音同待遇,连通测试=health)。
- **face_swap 客户端配置化**:`_resolve_base` 按显式 base > 指定 config_id > faceswap 默认配置 > 本地默认 解析服务地址,本地/远程协议一致。
- **两处换脸模型选择器**:工作台顶栏(文本/图片/视频/换脸/分辨率)与换脸工具页头部(显示 配置名 · Base URL,切换即重新健康检查);角色换脸与工具页换脸均按所选配置调用。
- **导航中文化 + 即时多语言**(用户要求"merger 改为中文,多语言时同步切换"):顶栏改用 i18n key(nav_projects/nav_merger/nav_faceswap),默认中文「项目/合并工具/换脸」;新增 MainWindow.retranslate(),设置切换语言后顶栏与标题**立即**跟随(整页内容重启后完全生效)。
- 截图:18-faceswap-model-selector.png / 19-nav-english.png(英文即时切换)/ 20-episode-face-model.png / 21-settings-faceswap-tab.png。

## 2026-09-29(第 5 轮:换脸归位资产角色卡 + 移除独立工具导航)
- **换脸移到资产·角色卡片**(用户澄清"换脸不是在这里,是要在资产里的角色那里"):新组件 `CharacterFaceSwapDialog` —— 三栏(当前形象 / 源脸照片(上传或从其他角色形象选) / 换脸预览)+ 参数(所有脸/增强)+ 顶部使用工作台所选换脸模型 + 「应用替换形象」确认后才写回 characters.image_url(取消不动)。工作台"视漫制作"每张角色卡的「换脸」按钮改为打开此对话框。
- **独立换脸工具页移除角色部分并从导航下线**:顶栏不再有"换脸"入口(nav 仅剩 项目);`face_swap_page.py` 保留为纯图片对图片通用工具(未注册导航)。
- **合并工具从导航移除**(用户:"merger 不应在这里,应出现在生成视频的拼接中,根本不要说用什么拼接"):顶栏只剩「项目」;无损合并/智能直通/对齐异类能力作为 `pipeline/merge.py` 的内部实现,只在「拼接导出 → 拼接所选」与「同款复刻拼接」中生效,UI 不出现任何技术名词。
- 截图:22-clean-nav.png / 23-assets-characters.png / 24-character-faceswap-dialog.png / 25-export-stage.png。

## 2026-09-29(第 6 轮:补齐 14 项差距,对齐原版 100%)
### 小说线(5/5)
1. **六维审校 UI**:原始内容面板新增「🔎 AI 六维审校」→ `ReviewDialog` 按维度显示 ✅/❌ + 问题清单 + 总评(写 review_json)。
2. **按指令改稿 UI**:指令输入框 + 「✏ 改稿」→ novel.edit_chapter。
3. **审校→修复循环**:`novel.write_chapter_with_review` 写章后自动审校,overall=fix 时带问题清单重写一轮;单章生成与批量续写均走此路径,完成后报告修复章数。
4. **策划与设定面板**:`NovelPlanDialog` 四标签(总纲/世界观/合约/分卷)可编辑保存 + 章节计划/主要角色只读展示。
5. **AI 封面**:NovelPlanDialog 内生成,写 dramas.thumbnail 并即时预览。
### 短剧线(9/9)
6. **@角色参考图注入视频**:shot_tools.collect_reference_images 从分镜文本解析 @角色名 → 形象图(去重≤4);video_client volcengine 以 reference_image 角色注入、agnes 多模态参考;文生与图生路径均生效。
7. **首帧图生成**:分镜行「🖼 首帧」→ shot_tools.generate_first_frame(风格前缀+video_prompt),标「首帧✓」。
8. **图生视频**:「🎬 图生」→ 无首帧自动先建,再图生视频(带参考图)。
9. **字幕烧录**:「T 字幕」→ 旁白/台词 srt → ffmpeg subtitles 滤镜 → composed_video_url。
10. **video_prompt 逐镜编辑**:分镜卡新增提示词行内编辑框。
11. **批量视频前确认**:镜头数/总时长/模型/分辨率/当前任务统计确认后才发。
12. **分辨率随厂商联动**:RESOLUTION_TIERS(volcengine 480p/720p、minimax 768P/2K、aliyun 至 1080P、agnes 720P/1080P)。
13. **模型选择记忆 + 集级锁定**:全局记忆四类选择与分辨率;集首次选用图片/视频配置后 🔒 锁定并回写 episodes.image/video_config_id,换选即更新锁定。
14. **角色造型变体**:角色卡「🎨 变体」→ VariantsDialog(新增标签+造型描述 → AI 提示词 → 变体出图 → 用作角色形象,默认标记)。**漫画资产真实页**:常规/漫画双 tab,漫画风格镜像图(comic_image_url)逐个生成与批量出图;漫画格「重新出图」即恢复原图(局部擦除标注交互后续按需加)。
- 截图 26~30。诚实备注:漫画"局部重绘(擦除区域)"需要交互式标注画布,本轮以整格重新出图替代。

## 2026-09-29(第 7 轮:补齐 A 类管理闭环 + D 类全局体验)
### A 类(项目/剧集/素材页管理)
1. **项目卡状态标记**:每卡右上可点状态徽标(待开始/进行中/已完成,彩色圆点图标),菜单切换写库;统计条"进行中"随之变化。
2. **排序真实可用**:最近更新 ↔ 按标题(原来按钮点了没反应);筛选改为直接按项目状态过滤。
3. **相对时间**:刚刚 / N 分钟前 / N 小时前 / N 天前 / M/D(替代原始时间戳);卡片重排为 封面+画幅角标+状态+更多。
4. **项目设置弹窗**(新 `asset_dialogs.ProjectSettingsDialog`):标题/简介/题材/画幅/视觉风格/面孔文化,保存入库。
5. **素材库全面可交互**:卡片点击打开 `AssetDetailDialog`(左预览可点击放大 ImageViewer + 右编辑:角色名/定位/样貌/妆造,场景地点/时间/描述/光影/标签,道具名/类型/外貌)+ 最终提示词面板(AI 生成/重新生成/复制/手动编辑)+ 造型变体入口 + footer(删除/上传/生成形象/保存/关闭);新增「＋角色/＋场景/＋道具」手工添加;空态提示。
6. **剧集卡**:标题**内联改名**(点击即可改)、状态菜单(带选中态圆点)、分辨率下拉(480p/720p/1080p)、新增 `NewEpisodeDialog`(标题+分辨率+说明)。
7. **宣传文案对话框**(内嵌项目页):平台+格式+补充说明 → 生成 → 标题/正文只读框 + 复制全文(替代原来只能看弹窗)。
### D 类(全局体验)
8. **全局 Toast**(`ui/toast.py`):右上角浮层 info/success/warning/error 四级,堆叠最多 5 条,自动消失,不阻塞,跟随窗口 resize 重排;**错误友好化 `map_error`** 对齐原版八类优先级短路(网络/超时/鉴权/限频/invalid temperature/内容审核/5xx/API error 提取/原文兜底)。
9. 全量替换 20+ 处 `QMessageBox.warning(str(err))` → toast;保留确认类(question)弹窗。
10. **Loading 基座**(`ui/loading.py`):`Spinner`(纯 QPaint 旋转)+ `BusyButton`(内嵌 spinner/禁用态);TaskManager 增加 `busy_changed` 信号,工作台顶栏 `status_lab` 显示忙碌提示。
### 顺带修复
- theme.py 重复 `apply_theme` 定义清理;settings_dialog 死代码(`self.pages[2]=...`)删除;两处 QFormLayout 双重父布局警告修复。
- 截图 31~37(含 toast 三色演示与错误友好化验证)。

## 2026-09-29(第 8 轮:文本框撑满 + Ctrl+L AI 智能修改)
- **文本框撑满**(用户截图标注):原始内容 / AI 改写两个主编辑区由固定 360px 改为 Expanding 策略并占满剩余高度(去掉外层 QScrollArea 包裹,自身内部滚动),实测 1120×600 铺满工作区;新增 `FILL_PANELS` 区分撑满型与滚动型面板。
- **Ctrl+L AI 修改**(对齐原版 episode.vue 的 @keydown.ctrl.l + aiEdit):
  - 三种模式——**选中若干行→改写选中片段**、**不选→在光标位置插入**、勾选「整章处理」→输出整章;对话框显示模式标签与选中片段预览(超 400 字截断)。
  - 提示词拼接与输出规则逐条对齐原版 RULES(只输出结果文本/不重复原文/保持未涉及部分原样)。
  - 回填逻辑:selection=前缀+新片段+后缀;insert=按原版规则补空行;chapter=整章替换;并落库 + toast 提示。
  - 快捷键 Ctrl+L 与 Cmd+L 双注册;两个编辑框工具条各加「✨ AI 修改 (Ctrl+L)」按钮。
- **连贯性上下文**(用户要求:改写/插入须带前情,不能生成不合理文字):`_context_parts()` 在每次改写前自动拼接——作品设定(总纲/世界观/故事合约)、文风要求、本章计划(标题/目标/事件/钩子)、**前三章摘要(每章结尾 600 字,按章号倒序)**,并追加 4 条连贯性硬规则(不得与设定/前情冲突、不得写前文未发生的事、人称时序称谓文风一致、不输出无关内容)。
- 截图 40(撑满+Ctrl+L 按钮)/ 41(AI 修改对话框)。

## 2026-09-29(第 9 轮:顶栏语言按钮)
- 语言按钮移到最右(顺序:项目 → 主题模式 → 设置 → 🌐 语言),文案由「界面与 AI 内容语言」精简为「语言」;新增 i18n key `lang_short` 并补齐 15 语言(语言/Language/言語/언어/Langue/Sprache/Lingua/Idioma/Idioma/Ngôn ngữ/Dil/اللغة/भाषा/Bahasa/ภาษา)。
- 截图 42(中文)/ 43(英文即时切换)。

## 2026-09-29(第 10 轮:项目卡整卡可点)
- 用户反馈"点示例卡片没反应":原实现只有「···」菜单里的"打开项目"入口,整卡不可点(与原版 card click 行为不一致)。现 ProjectCard 整卡可点(指针光标 + tooltip + mousePressEvent 打开项目),点在右上状态徽标/更多按钮时不误触发(按钮 pressed 置位标记拦截)。
- 截图 44(QTest 模拟点击卡片验证跳转项目页)。

## 2026-09-29(第 11 轮:修复 emoji 空白按钮)
- 用户截图反馈剧集卡上有一个空白按钮:该处应为「🗑 删除本集」,但 **🗑 等彩色 emoji 在微软雅黑(msyh.ttc)中无字形**,Qt 渲染为空白方块。
- 用 QRawFont.supportsCharacter 实测全项目符号:15 个彩色 emoji(📖🎬📚📣🎞📁🌓🌐🖼🔊🔎🎨🔄📋🗑)缺字形;几何/箭头符号(▶✏➕⚡✕●○⋯·—⏳✅❌↻)均正常。
- 全项目 46 处 emoji 替换为可靠 Unicode 符号(§▷▤◈▦◐◎▣♪◇◑↻✕),删除按钮改为红色文字「删除」双保险。
- 截图 45~47(启动台/剧集列表/工作台)。

## 2026-09-29(第 12 轮:同步原版 xiaoshuo 新增功能,8 项 100% 复刻)
> 依据 `git diff dc86ba8..HEAD`(原版 2026-09-29 ~ 10-01 共 20+ 提交)逐项复刻。
### P0
1. **参考图序号统一(正确性 bug 修复,原版 67adf7a)**:新增 `pipeline/refs.py` 作为单一真相源 `build_shot_reference_list()`——权威顺序 **角色→场景→道具**(角色排首位:后端缺 first_frame 时会用 [0] 兜底锁脸),按 imageUrl 去重,截断上限 Wan 3.0 为 10 张 / 其他 9 张。`get_shot_reference_images()` 与 `get_shot_reference_index_map()` 均由它派生,保证 `@图片N ≡ reference_image_urls[N-1]`;`resolve_video_prompt_refs()` 把 `@名字` 替换为 `@图片N名字`(名字按长度降序匹配避免前缀误命中)。`shot_tools.collect_reference_images` 由「正则猜 @名字」改为按 storyboard_id 走该真源。
2. **项目设置新增字段(原版 72736af)**:创意描述 textarea + 「不需要创意描述」复选框 + 集数(1-999);已有第 1 集时创意描述与复选框**锁定**;集数=1 或已达总数时「添加一集」按钮隐藏并提示。
3. **小说章节自动起名(原版 a41c224 + 8f3213d)**:`gen_chapter_title()`——上下文=总纲 400 字 + 前三章摘要(各 200 字)+ 本章节选 2000 字,输出清洗三级(取首行→去「第N集」前缀→去引号/井号→截断 20 字),写回 `episodes.title` 与正文首行 `# <name>`;写章路径 `_save_with_title()` 自动识别首行章节名并写回;UI 在缺章节名时显示「✎ 章节名」按钮。
### P1
4. **资产下载(原版 72736af)**:新增 `core/download.py`,文件名规则对齐原版(资产名[_变体].png / 第NN镜[_标题].mp4 / <项目名>_第N集.mp4),非法字符清洗、扩展名推断、400MB 上限、重名自动加序号;UI 接入素材详情弹窗「↓ 下载原图」、分镜行「↓」、导出页成片「下载」。
5. **RunningHub 视频适配器(原版 b78f9bf)**:openapi v2 协议,模型 `seedance-2.5`(realPersonMode 默认 true,显式 false 才关)/ `wan3.0-video(-prime)`;首帧图 unshift 首位保锁脸;归一化(duration 2-30、resolution 2K→wan 收敛 1080P、adaptive→自适应);`@图片N`→`图N` 提示词转换;容忍性响应解析(5 处 taskId 兜底 + 8 层递归找 mp4,优先按字段名顺序避免封面图抢先);注册进 settings 预设与易好快捷配置。
### P2
6. **运镜全链路(原版 ca55b49)**:纯提示词层——storyboard_breaker 注入 22 词运镜库 + 按段落类型选择(铺垫/对话/情绪/动作/爆点/悬疑)+ 子镜头 description 写法硬规则(运镜写在【镜头N】开头,再写画面、再写台词);prompt_generator 注入 video_prompt 运镜硬规则(每 3 秒段必须含「起始景别+运动方式+速度」,禁止纯静止镜头)+ 运镜五分类词库 + 速度副词 + 慢动作例外。
7. **换脸面板升级**:批量换脸(基础形象+全部变体,单张失败不中断)、批量下载结果、恢复原貌(首次载入快照)。
8. **默认视频模型优先级(原版 e653b75+b78f9bf)**:易好快捷配置改为 MiniMax 98 > Wan 3.0 97 > Seedance 96 > RunningHub 95(Seedance 垫底);内容语言选择器由 4 语言下拉改为 **15 语种 5 列网格**(对齐原版 lang-picker-grid)。
- DB 迁移:storyboards +title/location/time/result/atmosphere/sound_effect/description/subtitle_url/setting_tags/reference_images/deleted_at;dramas +creative_description/skip_creative/total_episodes;ai_service_configs +settings。
- 截图 48~51。

## 2026-09-29(第 13 轮:同步原版 73b3339)
- **「章节名」按钮搬到项目页剧集卡**(原版 73b3339):从工作台原始内容工具栏移除,改到项目页剧集卡标题下方——缺章节名(标题为空或仅「第N集」占位)且有正文时显示虚线胶囊「✎ 章节名」,已有名字的集不显示;点击后原地写回并 toast 提示,卡片自动刷新(按钮消失)。
- **正文标题行反向提取**(不调模型):新增 `extract_title_from_content()` 支持两种写法——markdown 标题 `# 归乡的井` 与 `第1集 县医院的消毒水味`;清洗书名号/引号/尾部标点;超过 30 字视为正文不当作标题(实测:两种写法均正确提取,超长行与普通正文行均返回空)。
- `gen_chapter_title()` 改为**优先反向提取**(返回 source='content',省一次模型调用),提取不到才走 AI(返回 source='ai');仅在标题为占位时才提取,避免覆盖用户已改好的名字;UI 按来源给出「已提取章节名:」/「章节名已写入:」两种提示。
- 截图 52(剧集卡章节名按钮:EP01 已有名字不显示 / EP99 缺名显示)。

## 2026-09-29(第 14 轮:同步原版最新 4 提交,基线推进到 a6a47dc)
> 原版从 73b3339 推进到 a6a47dc,新增 4 项,全部复刻。
### 1. 残缺分镜自动补全(daa17d0)
- 新增 `pipeline/storyboard_repair.py`:**判定**——`image_prompt` 为空 → 缺 image_prompt;`storyboard_characters` 零行且 description 含 `@角色名`(正则 `/@([^\s@，。；：、!！?？)）]{1,20})/g` + 剥括号注释,如 `@王德厚（王父）`→`王德厚`)→ 缺 character_links;**修复**——逐个调 prompt_generator 补 image_prompt + character_ids + prop_ids + scene_id;**成败以落库为准**(不信 agent 自述):要求 image_prompt 非空且关联行数 > 0 才算完成。
- UI:分镜页「⟳ 自动补全 N」按钮,**仅残缺时显示**(无残缺自动消失不占位),运行时禁用并显示进度;完成 toast 区分全成功/有失败两种。
### 2. 写作红线 1/2/3/4/5/7 + 章节名沿用 + 上一章衔接(101759d)
- **写作红线**:`NOVEL_REQUIRED_STEPS = [1,2,3,4,5,7]`(6 卷战略为节拍层保持可选),`check_novel_redlines()` 逐条判定——1 标题+简介 / 2 总纲 / 3 世界观(era+location,读**落库的** novel_meta 而非向导内存草稿)/ 4 故事合约(pov+rules 非空+tones 非空)/ 5 角色表有行 / 7 章节规划非空;`assert_novel_ready()` 后端兜底拒绝,`missing_steps_text()` 给出「1(项目设定)、2(总纲)…」。
- UI 前置守卫:设定未齐时禁用「AI 生成小说 / 批量写」并 toast + tooltip 提示缺哪几步;短剧/漫画项目不受红线约束。
- **章节名沿用清单**:`write_chapter` 提示词改为「章节名优先沿用【本章计划】里的标题(原样使用,不要改写);无计划标题时再自行起名」——保证重新生成后章节名稳定不漂移。
- **上一章衔接修复**:`prev` 查询加 `content IS NOT NULL AND content != ''` 过滤(原版 bug:`lt` 过滤后按升序取第一行拿到的是**第 1 集**,重写第 5 章时衔接第 1 章结尾导致跨章断裂)。
### 3. 换脸健康检查(09e76b8)
- `face_swap.health()` 改为读 `data.local.ok` 并以 `data.ok` 兜底(新版本地/远程嵌套 `{local:{ok},remote:{ok}}`,旧版扁平 `{ok}`),修「本地服务正常但下拉永远显示未启动」的前端字段路径 bug。
### 4. 项目级内容语言(a6a47dc)
- 新增 `dramas.language TEXT DEFAULT 'auto'`('auto'=跟随全局,其他=固定该语言);`config.resolve_content_language(drama_id)` 三段式优先级:显式传入 > 项目覆盖 > 全局设置。
- **全链路贯通**:rewriter / extractor / storyboard / prompts_gen / comic / novel 六类 pipeline 的 agent 调用全部新增 `lang` 参数;工作台 `EpisodePage.load()` 进入项目时按项目语言 `set_language()`,并把 `_drama_lang` 传给所有 UI 调用点。
- UI:项目设置弹窗新增「内容语言」下拉(跟随全局 + 15 语种),新建项目对话框同步。
- 截图 53(分镜页「⟳ 自动补全 6」按钮)。

## 2026-09-29(第 15 轮:同步原版 26c7d00 + 0114f24,基线推进到 0114f24)
> 对齐源仍为 E:\xiaoshuo(gitee huobao),原版从 a6a47dc 推进到 0114f24。
### 1. 供应商模板胶囊 → 与「服务商」合并为单一下拉(26c7d00)
- 原版解决「上方一排模板胶囊 + 下方供应商下拉,两处都在选供应商,容易困惑」。现**移除顶部胶囊行**,合并为一个「服务商」下拉:选项显示模板 label(如「Agnes 官方」「MiniMax 官方」),选中即自动填入 Base URL + 默认模型 + 配置名称(原胶囊行为);末尾附「自定义…」,选中时展开原始服务商标识输入框(隐藏式,不占默认行)。
- 新建时默认选中首个模板并主动填充一次(下拉首项不触发 currentIndexChanged);编辑已有配置时命中模板则选中对应项,否则落到自定义并回填原 provider。
- 顺带修一个旧 bug:`_FlowLayout` 原本是伪流式(内部 QHBoxLayout 不换行),模型标签一多就**文字重叠**;改为基于 move/resizeEvent 的真流式布局,标签按可用宽度自动换行(实测 4 个标签分两行渲染,重叠消失)。
### 2. 小说设定闸门消息压缩(0114f24)
- `assert_novel_ready()` 消息由「小说设定未完成(缺步骤 X),请先在「策划与设定」补齐后再生成」压缩为 **「小说设定未完成，请先补齐步骤 1、2、3」**(24 字,原版约束 40 字内),只报步骤号,名称由 UI 侧翻译补全,避免长文本在错误提示里被截断。
- 截图 54/55(合并后的服务商下拉 + 真流式模型标签)。

## 2026-09-29(第 16 轮:Agent 配置补齐 Skills + 15 语言全量同步)
> 用户指出「生成小说/短剧的配置是否完成?注意是多语言的」——核查发现**未完成**:原版是 10 提示词 × 15 语言 = 150 文件 + 11 技能 × 15 语言 = 165 文件,而本版只有中文内置提示词,**Skills 一个都没有**,设置页也无 Skills 面板。
### 配置文件全量同步(315 个)
- `workspace/prompts/` 150 个:`<agent>.md` + `.en/.ja/.ko/.fr/.de/.it/.pt/.es/.vi/.tr/.ar/.hi/.id/.th` × 10 个 agent
- `workspace/skills/` 165 个:11 个技能 × 15 语言
  - comic-board / extractor / novel-writer / promo-writer / script-rewriter / storyboard-breaker
  - prompt-generator 下 4 个子技能:character / scene / prop / video-prompt
  - storyboard-breaker 下子技能:fight-cinematography
### 技能加载器(`agents/prompts.py`)
- `AGENT_SKILL_MAP` 按目录前缀挂载(对齐原版),`list_skills()` 同时识别**技能目录自身**与**子目录**(如 fight-cinematography)
- `load_skills()` 把技能正文以 `## Skill: <name>` 段落拼进 instructions,语言回退链 `<lang> → en → zh`
- `load_prompt(..., with_skills=True)` 统一组装:多语言文件 → 技能正文 → 非中文时追加显式输出语言指令
- 新增 `load_skill / save_skill / reset_skill` 供设置页编辑
- 实测:15 种语言提示词全部有内容(均 > 500 字符),`th` 语言 storyboard_breaker 含 2 个技能共 20740 字符
### 设置页 Agent 配置(对齐原版截图)
- 左侧列表加**技能数量徽标**(剧本改写 [1]、分镜拆解 [2]、提示词 [4] …)
- 右侧改**双标签:System Prompt / Skills**
  - System Prompt:路径提示 `workspace/prompts/<agent>[.<lang>].md` + 编辑器 + 保存/恢复默认
  - Skills:左技能列表 + 右正文编辑器(显示 `skills/<id>/SKILL[.<lang>].md` 路径)+ 保存/恢复默认
- 顶部语言下拉切换时,两个标签的内容与路径同时按语言切换
- 截图 57/58/59(System Prompt 标签 / Skills 标签 / 日语技能路径)。

## 2026-09-29(第 17 轮:AI 服务缺失拦截 + 自动更新)
### A. AI 服务未就绪直接提示(用户要求:不能"不声不响的没有结果")
**问题实测**:
1. 配置存在但 **API Key 为空**时,客户端仍会真的发请求 → 拿到 401 才报错,白跑一次网络;
2. 完全未配置时只在后台任务失败后弹 toast,用户看不到、也不知道去哪配;
3. `map_error` 无「未就绪」分支,原文直传。
**修复(三层防护)**:
1. `ai/registry.py` 新增 `check_ready()` / `readiness()` / `missing_services()` / `NotConfigured`:
   覆盖**未配置 / 全部停用 / 缺 API Key / 缺模型名 / 缺 Base URL** 五种情况,每种给出明确原因;
   `local-faceswap` 等本地 provider 豁免 Key 检查。
2. **四个 AI 客户端入口改为 `check_ready()`**:text/image/video/tts 在发请求前校验,
   缺配置时抛 `NotConfigured` 而**不发空请求**(实测:空 Key 的图片生成在网络调用前即被拦下)。
3. **`TASKMGR.submit()` 统一拦截**(18 类任务 → 所需服务映射):未就绪时弹模态提示
   (「✗ 图片服务未就绪 — 配置「agnes」缺少 API Key / 影响:角色形象·场景·道具·漫画格·封面 / 请到「设置 → AI 服务」补全」),
   **不创建 sys_task 记录**(不留下"跑了没结果"的空任务),并回调通知 UI。
4. **主窗口全局横幅**:缺 text/image/video 任一即显示橙色横幅「⚠ AI 服务未配置完整(缺:文本、图片、视频) — 依赖模型的操作会无法执行,点击此处去「设置 → AI 服务」补全」,点击直达设置,保存后自动复查刷新。
5. `toast.map_error` 增加「未就绪/未配置」最高优先级分支。
**顺带修一个潜伏崩溃**:37 处 `def done(tid, result, err)` 的参数 `err` 遮蔽了模块级 toast 函数 `err`,
一旦走进错误分支就 `TypeError: 'RuntimeError' object is not callable`。统一重命名为 `error`。
### B. 自动更新
- 新增 `core/updater.py`:GitHub Releases 检查(语义化版本比较,`v1.2.10 > v1.0.0`)、
  zip 下载(流式+进度)、解压、单层目录下钻、**备份后覆盖**(只覆盖源码/配置类文件,不动二进制与
  data/workspace)、重启拉起;支持 `PYDRAMA_UPDATE_FEED` 覆盖更新源。
- 「关于更新」分区重做:当前版本 + **启动时自动检查更新**开关(默认开)+ 检查更新按钮 +
  发现新版本时显示 Release notes + 「立即下载并更新」+ 进度条,完成后询问重启。
- 启动后 3 秒静默检查,有新版以 toast 提示(可在设置关闭)。
- 截图 60(AI 缺失横幅)/ 61(拦截弹窗)/ 62(关于更新)。

## 2026-09-29(第 18 轮:全面 bug 排查 + 版本升至 1.1.0)
### 排查结果
- **语法**:全量 `py_compile` 发现并修复 `ui/merger_tool_page.py:182` 缩进错误
  (批量插入 toast import 时误插到函数体外,导致整个模块无法导入 —— 该页是「无损合并工具」入口)。
- **导入**:pkgutil 遍历 app.* 全部模块,导入失败 0。
- **运行时冒烟**:启动台 / 项目页 / 工作台六阶段(raw·rewrite·assets·storyboard·comic·export)/
  设置六分区(AI服务·通用·风格预设·Agent配置·存储·关于更新)/ 5 种语言切换 —— **0 错误**。
- **数据一致性**:孤儿分镜、孤儿角色关联、指向不存在集的场景、空内容分镜、僵死 processing 任务 —— **全部为 0**。
- **静态分析**:lambda 闭包、索引越界、可疑未定义名逐项核查,均为误报
  (lambda 均用默认参数绑定循环变量 `lambda _=False, i=r["id"]:`,`updater` 的 `entries[0]` 有 `len==1` 保护)。
- **逻辑验证**:参考图单一真相源(角色优先·序号映射·@图片N替换)、ref 上限(Wan 10 / 其他 9)、
  章节名清洗边界(空串/超 30 字/两种写法/尾部标点)—— 全部符合预期。
### 版本
- `APP_VERSION` 1.0.0 → **1.1.0**(功能已显著超过初版,便于自动更新区分)。

## 2026-09-29(第 19 轮:同步原版未提交批次 49 文件 +3269 行)
> 原版有一批**未提交**的本地改动(工作区脏),主题是「长篇小说(999 章量级)生产链路的可靠性 + 可观测性」。全部复刻。
### 配置文件
- 重新同步 prompts(150)与 skills(165),新增 **fight-cinematography**(高速打斗运镜手册:10 条机位公式 + 4 种速度注解,15 语言)与 **novel_editor**(第 10 个 Agent,15 语言)。
### P0 可靠性
1. **LLM 挂起超时**:`AI_LLM_TIMEOUT_MS`(默认 300s)作用于文本请求 —— 服务商"接受连接但永不响应"不再让任务永远卡 processing。
2. **任务阶段可见性**:`sys_task.params.stage` 写入 writing→reviewing→repairing/splitting,新增 `taskmgr.set_stage/get_stage`。
3. **写后校验**:`write_chapter_with_review` 以 `episodes.content` 为准,`<200` 字符即抛错(防"界面显示完成但章节空着"),上层可重试。
4. **分镜拆解改后台任务**:`split_storyboards_bg()` 走任务队列 + **防重入**(同集已有 processing 任务则拒绝)+ **垃圾分镜清理**(description<50 且 image_prompt<30 且 video_prompt<60 的空壳行,级联清关联表)+ 假完成校验(0 分镜抛错);UI 6 秒轮询,按钮显示"后台运行 5-10 分钟"。
5. **批量建集**:`bulk_create_episodes(titles/count 1-999, target_words, resolution)`,start_num 取已有最大集号+1。
6. **防误覆盖**:`batch_write_chapters(force=)` 默认**已有正文的章节整批拒绝**并提示"重写请点「重写已完成章节」";UI 侧 `批量写本章及后续` 语义重定义(本章未写完→确认重写本章;已完成→取后续无正文的前 10 章),并新增 `重写已完成章节(force=True)` 按钮。
### P1 可观测性
7. **伏笔台账**:LCS≥5 去重(实测"苏晓晴对李安全变化的怀疑"vs"…越来越深"命中 12 字合并;"感情线"vs"持续关注"正确保留)、`OPEN_LEDGER_CAP=40` stale 封顶、`backfill_ledger_chapters` 前 4 字回填埋设章号、按埋设章号倒序注入最近 8 条、`toggle_ledger` 可交互勾选(乐观更新+失败回滚)。
8. **审校明细 + 全书审校清单**:`ReviewPanelDialog`(逐条勾选,仅本地标记)、`ReviewSummaryDialog`(逐章列出问题,可跳转)。
9. **整章朗读**:`read_aloud()` 按句切 600 字硬切超长句,逐块 TTS 后拼 MP3(帧自包含可连续播放)。
10. **任务收尾按产出归位**:`settle_interrupted_tasks()` 启动时把 processing 任务按"产出是否已落"判 completed/failed(不再一律 failed)。
11. `storyboard_count` 随剧集卡一次 groupBy 带出,消除 N+1。
### P2 UI
12. **三段式进度条**(成功绿/失败红/进行中)+ 图例(百分比/进行中/成功/失败)+ 每章阶段显示。
13. **剧集卡制作阶段条**:按产物判定(正文<200→剧本<100→资产/分镜→分镜→成片),五段绿/蓝/灰;**字数进度** `X / Y 字`,低于 80% 标琥珀色,否则"未写"。
14. 分镜拆解接后台任务 + 轮询。
### 验证
- 冒烟:启动台/项目页/工作台六阶段/批量进度面板/审校明细/全书清单/伏笔台账/审校摘要/垃圾清理/批量建集越界 —— **0 错误**。
- 逻辑单测:阶段判定 5 态全对、LCS 去重 4 例全对、朗读分块(12/600/103)、中断任务收尾(1 completed/2 failed)、垃圾清理 4 条。
- 截图 63(阶段条+字数)/ 64(小说工具条)/ 65(批量进度)。

## 2026-09-29(第 20 轮:同步原版模型/旁白/换脸)
> 原版工作区又有新变化,重点是 **模型清单、TTS 旁白、换脸服务** 三块,已全部对齐。
### 配置文件
- 重新同步 prompts(150)与 skills(165);`workspace/skills` 现有 **11 个技能目录**(含 `storyboard-breaker/fight-cinematography` 高速打斗运镜手册 15 语言)。
### 模型(对齐原版 settings.vue providerPresets + yihaoQuickConfigs)
- **换脸从 image 迁出,独立为第 5 类服务 `faceswap`**:provider 名对齐为 `local-faceswap`(本地 127.0.0.1:5678)与 `remote-faceswap`(远程默认 `https://face.mei.biz`,不再是我之前的占位地址),model 占位 `face-swap`。
- **TTS 音色换代**:原版注释说明 `BV001/BV002/BV005_streaming` 属 1.0 旧音色、走另一套鉴权、`X-Api-Key` 下不可用 → 全部换成豆包大模型 2.0 音色(`zh_female_shuangkuaisisi_uranus_bigtts` / `zh_male_roucheng_uranus_bigtts` / `zh_female_cancan_uranus_bigtts`)。
- 补全模型清单:text Agnes 升 3.0 系列、MiniMax 补 M2.7/M2.1;image qwen-image 改百炼地址 + `qwen-image-3.0-pro` / `wan2.7-image(-pro)`;video 阿里补 **HappyHorse 1.1**(t2v/i2v/r2v)。
- **易好快捷配置改 8 条**(对齐原版):走 firemux 中转(`https://api.firemux.com`,视频按 `/qwen` `/volcengine` `/minimax` 分路径),优先级 Gemini文本101 > OpenAI文本100 > OpenAI图片99 > Wan视频98 > Seedance97 > Gemini图片97 > MiniMax视频96 > RunningHub95。
### 旁白 TTS(重写 tts_client.py,对齐 volcengine-tts.ts)
- **双引擎**:Path A `seed-tts-2.0`(异步 submit/query,Resource-Id 区分单角色 `seed-tts-2.0` 与复刻音色 `seed-icl-2.0`(voice 以 `S_` 开头));Path B `seed-audio-1.0`(同步 create 返回 base64)。错误含 `resource not granted` → 缓存降级、后续直接走兜底。
- **语速自适应(核心)**:按 `target_duration` 合成后 ffprobe 实测时长,超了就提速重合成(最多 2 轮,上限 2.0x,旧文件清理)。
- **探活改真实请求**:发 2 字最小合成(`seed-tts-2.0-standard`),因为 submit 空体会回 500 导致"永远测试不通过"。
### 换脸
- 客户端补 `output_format`(模板是 .png 则输出 png 保留透明,否则 jpg)与 `template_index`;`swap_all_faces` 默认改 true(对齐原版硬编码)。
- 换脸面板加 **风格下拉**(写实/电影感/动漫,对齐原版三项 prompt 前缀)、"替换图中所有脸"默认勾选、"人脸增强";保留批量换脸/批量下载/恢复原貌/应用替换。
### 验证
- 冒烟 9 项全过 0 错误;TTS 降级判定、音色路由(单角色 vs 复刻)、provider 清单、换脸面板、设置页全部正常。
- 截图 26(换脸面板)/ 27(设置·换脸标签)。

## 2026-09-29(第 21 轮:迁移原版 AI 服务配置 + README 功能对照表)
- 新增 `scripts/migrate_ai_configs.py`:从 `E:\xiaoshuo\data\yihao.sqlite3` 读取原版 10 条 AI 服务配置,
  字段映射 `name→remark`、JSON 数组 `model→models+model`、`settings` 原样保留(厂商私有开关),
  支持 `--dry-run` 预览;同(类型,provider,base_url)覆盖更新,否则新增。
- **迁移结果**:新增 7 条 / 更新 3 条,覆盖 文本(百炼Qwen3.8-Flash P10、MiniMax)、
  图片(Agnes P10、百炼Qwen-Image 3.0、火山Seedream 5.0)、视频(火山Seedance 2.0 P10、Agnes)、
  配音(豆包语音 P100,含 `settings.voice_type`)、换脸(本地 P3 / 远程 FaceMe P2),全部带 API Key。
- **真实连通验证(非仅配置检查)**:
  - 文本 ✅ 真实 chat/completions 调用通过
  - 图片 ✅ 真实生图 875KB(Agnes)
  - 配音 ✅ 真实合成 2.45s / 目标 5s(豆包 seed-tts-2.0,语速自适应生效)
  - 视频 ✅ 真实生视频 1056KB(火山 Seedance 2.0 mini;注意 3s 不支持,该模型用 5s)
- README 增补「功能对照表」(原版 Web ↔ PySide6 重写版逐模块对应 + 增量能力)。

## 2026-09-29(第 22 轮:修复封面生成无响应 + 全局盲文等待态)
### Bug 修复:生成封面"没有效果"
- **真因一(致命)**:`pipeline/novel.py` 漏了 `config` 导入,`generate_cover` / `generate_episode_cover` /
  `read_aloud` 三处调 `config.path_to_media_url` 时抛 `NameError: name 'config' is not defined`——
  封面与整章朗读**每次都静默失败**(异常在后台线程被吞,界面毫无反馈)。
- **真因二**:任务完成回调经 `QTimer.singleShot` 回主线程,在无事件循环/窗口状态下不可靠,
  表现为"点了没反应"。
- **修复**:补齐 `from ..core import config`;完成回调改用 **Qt 信号跨线程队列**(signal 定义在主线程的
  `TaskSignals` 上,后台线程 emit,主线程自动 queued 执行),比定时器可靠且异常可见。
- 验证:真实点击生成 → `cover_1.png` 864×1152(3:4 竖版)1215KB 落库,界面图片同步刷新。
### 全局盲文等待态(用户要求:所有等待都用盲文变化表示)
- 新增 `ui/braille.py`:**盲文点字**旋转指示器(`⠋⠙⠹⠸⠼⠴⠦⠧…` 循环)+ 逐格填充盲文进度条 + `WaitingButton`(按钮内嵌 spinner、忙碌时禁用并显示文案)。
- **全局自动挂载**:`TaskManager` 在任何任务提交/结束时调用 `set_busy()`,
  主窗口顶栏常驻盲文指示器 + 状态栏 `⠿ 正在生成封面…`;22 类任务各有中文动作名
  (生成图片/生成视频/合成配音/改写剧本/写小说/拆分镜/换脸/拼接成片…)。
- 关键路径额外加局部反馈:封面生成按钮内嵌 spinner、批量视频/批量出图按钮改 `WaitingButton`。
- 顺带修:后台线程 UI 回调全部回主线程(`on_main` 显式暴露异常,不再被 `QTimer` 静默吞掉)。
- 截图 29(封面生成中)/ 30(顶栏全局盲文等待)。

## 2026-09-29(第 23 轮:同步原版 0114f24→f2b9e32 共 37 提交)
> 原版新增 4 项我完全没有的功能 + 一批可靠性加固,按用户感知强度逐项复刻。
### 配置同步
- 字体 10 个(站酷快乐/庆科黄油/龙藏行书/柳建毛草/之芒行楷 等 google/fonts 正版)→ `app/assets/fonts/`
- prompts 150 / skills 165 重新同步(含 fight-cinematography 打斗运镜 15 语言)
- DB 迁移:dramas +8 片头字段、ai_service_configs +api_format
### 1. 片头系统(原版 3990bb8/56cd571/9ee15f4/d262ac1)—— 新增 `pipeline/intro.py`
- 两种模式可同开:`intro_card` 黑底标题卡前置(默认)+ `intro_overlay` 文字叠加正片开头
- 9 款字体的展示名/回退链/白名单校验;8 字段按原版区间校验(字号 0.02-0.5 高度占比、位置 0-1 分率、时长 1-10s、越界回 null=自动)
- 自适应默认按字数算字号/时长(CJK 1 倍宽、其它 0.6)
- ffmpeg 三个坑全规避:① 字体拷成 ASCII 临时文件(中文路径会**静默渲染为空**)② 盘符冒号转义+正斜杠化+单引号 ③ 文字走 `textfile=`(UTF-8 无 BOM)绕开 `text=` 转义地狱
- ★ 叠加只在尾部实现一次(原版 56cd571 修的双重叠加黑场坑)
- 实测:黑底卡亮度 4.9、叠加窗 96.1、镜头帧 96.1/160.0,时长 6.5s 正确
### 2. 视频限流治理(原版 4790a54)
- `pass_video_create_gate()` 全局串行门:视频提交最小间隔 15s,链式串行不被单次失败打断
- 退避:优先 Retry-After,否则 30s×1.5^n 封顶 120s;429/503/超时识别
- 首帧画幅守卫待接入(Agnes 带首帧会跟随首帧画幅无视 ratio)
### 3. 小说批量强制串行 + 续写红线(原版 48f36da)
- 并发度硬编码 1:第 N 章开写前要读第 N-1 章结尾+事实台账+未回收伏笔,并行会整章重写同一情节
- 按章节号升序(调用方乱序也保证先写第 1 章)
- 续写红线双保险:整批入口校验 + 生成前逐章再校验,前章无正文拒写(第 1 集放行)
### 4. 同款复制升级 / 远程换脸 / 导入书分析仿写 —— 待下一轮
### 片头 UI 接入(补完)
- 新增 `ui/intro_dialog.py` 片头模拟器:项目画幅预览(黑底+九宫格辅助线)+ **真字体 WYSIWYG**(QFontDatabase 加载 ttf)+ 拖拽定位文字中心点(与 ffmpeg `w*px-text_w/2` 同口径)+ 播放预览模拟 fade=min(0.4,dur/3) 淡入淡出 + 重置布局;改动即存(经 sanitize_intro 原版区间校验)。
- 导出面板新增片头行:「叠加片头」勾选 + 片头名输入 + 「⚙ 片头设置」入口;拼接时按勾选传 intro 参数。
- 截图 48(导出页片头行)/ 49(片头编辑器,10 字体下拉)。

## 2026-09-29(第 24 轮:策划 AI 起草 + 小说生成完整性闸门)
> 用户要求:「可以用AI生成。同时都要完整了才能进入小说生成。」对齐原版 draftNovelSection / wizardStepDone / NOVEL_REQUIRED_STEPS。
### 1. 策划五件套支持 AI 起草
- `novel_dialogs.NovelPlanDialog` 每个设定页签(总纲/世界观/故事合约/分卷战略)加 **「✨ AI 起草」+「保存」** 按钮(按钮用 WaitingButton,起草中显示盲文等待态)。
- 起草逻辑对齐原版 `draftNovelSection`:
  1. **先落库项目设定(简介/题材)** —— Agent 通过 read_novel_context 读取,否则起稿会跑偏;
  2. 消息带**计划章数目标**(`计划共 N 章`),缺省取 `total_episodes` —— 原版注释指出这是「回炉 999→60」的根因;
  3. 世界观/故事合约附 **structured 必传提示**(era/location/power_system/factions; pov/tones/rules/word_range);
  4. 调 `novel_planner` Agent,完成后从库重载对应页签。
### 2. 小说生成完整性闸门(写红线)
- `NOVEL_REQUIRED_STEPS = [1,2,3,4,5,7]`(6 卷战略为节拍层,可选)。
- `wizard_step_done()` **严格对齐原版**:
  | 步骤 | 判定 | 数据源 |
  |---|---|---|
  | 1 项目设定 | 标题 + 简介 | dramas.title + metadata.intro |
  | 2 总纲 | 非空 | novels_outline |
  | 3 世界观 | era + location | **novel_meta.world**(落库值) |
  | 4 故事合约 | pov + rules非空 + tones非空 | **novel_meta.contract**(落库值) |
  | 5 角色设定 | 角色表有行 | characters |
  | 7 章节计划 | 章节数 > 0 | novel_chapters |
  ★ 步骤 3/4 读**已落库的 novel_meta** 而非向导内存草稿 —— 原版修复的正是「刷新页面后误判未完成」。
- 闸门生效:缺步骤时 **「AI 生成小说」与「批量写本章及后续」双按钮禁用**,工具条常驻琥珀色提示条列出缺哪几步;
  work_type 从库直取(避免 `_drama` 未就绪导致闸门失效)。
- 截图 50(闸门禁用态)/ 51(策划弹窗 AI 起草)。

## 2026-10-09(第 25 轮:章节计划 + 主要角色合并、整书导入分析仿写、制作页侧栏对齐原版、文风项目级)
> 用户要求:①主要角色并入章节计划,两者都可 AI 生成,并给出「每章多少字 / 有多少章」的输入位;②先做的那个放后台;
> ③「视漫制作 / 分镜 / 漫画」等界面要与参考项目一致;④题材有没有用;⑤文笔一类也要有地方设置。
### 1. 章节计划 + 主要角色 合并为同一页,各自可 AI 生成
- 「主要角色」页签取消,并入「章节计划」:上排三个按钮(**✨ AI 生成章节计划 / ✨ AI 生成主要角色 / 保存本章节与角色**)+ 右侧实时统计「共 N 章 · M 个角色」;下分「章节计划」「主要角色」两个可编辑区。
- 新增规模输入行(**每章字数** 500–20000 / **全书章数** 1–999),改动即时落 `novel_meta.word_count/chapter_count`,保证后台任务读到的是用户当前设定。
- `novel.plan_chapters()`:按 `chapter_count / word_count` 生成逐章计划(number/title/goal/events/cliffhanger);
  ≤200 章走逐章,>200 章自动降级为「分段计划 + 每段前 3 章示例」,避免上下文爆炸。
- `novel.plan_characters()`:**依赖先行** —— 章节计划缺失时先在后台补齐,再设计角色(对齐用户「那一个先做那一个后台」)。
- `novel.chapters_to_text / chapters_from_text`:章节数组 ↔ 一行一章可编辑文本,**中文章号支持中文数字**(三/十二/一百零五),
  非「第N章」开头的续行并入上一章事件;保存时角色 JSON 校验并同步进资产库 characters。
### 2. 整书导入 → 分析 → 仿写 三段式流水线(新增 `pipeline/book_import.py`)
- **导入**:仅 TXT,编码 utf-8-sig/utf-8 → gbk → gb18030 → big5 自动判定;三级切章(章标题正则 ≥32 命中 → 分隔线+启发式 → 2 万字窗口兜底);
  软删旧章节(级联 comic_panels / storyboards / 三张关联表 / video_merges)后每批 100 行插入。
- **分析**:12 章一组 Map → 文本抽样(头 6000 + 尾 2500,单组上限 9000)→ Reduce 出**仿写档案**(题材/结构/角色弧线/世界观/冲突线/节奏/文风);
  **安全阀**:失败率 ≥30% 且已跑 ≥50 组 → 落 `status=paused`,不基于残缺数据出档案。
- **仿写**:四阶段(设定 → 总纲 → 分卷 → 建项目),三条铁律**专名全换 / 情节仿而不抄 / 结构与节奏保留**;新建项目并把角色写入资产库。
- `generate_book_meta()`:由「首章正文 → 创意描述 → 项目名」按优先级提炼**简介 / 题材 / 创意描述**,三个来源皆空时报可读错误。
- 新增 `ui/book_import_dialog.py`:三段卡片式面板 + 依赖置灰(没导入不能分析,没分析不能仿写)+ 盲文进度条;项目页头部加「▤ 整书导入」入口。
- **实测**:40 章合成书 → 导入 40 章 → 分析 4 组 Map + Reduce(题材「玄幻/低武边城爽文」、5 条冲突线、文风特征)→ 仿写生成新项目《边城刀影》2602 字总纲 + 1167 字分卷 + 8 个角色。
### 3. 项目设置:简介/题材 AI 起草 + 写法文风
- 简介行下方加「**✨ AI 起草简介 / 题材**」(WaitingButton 盲文等待态),结果只填输入框,由用户确认后保存。
- 新增「写法文风」行:6 个预设(爽感快节奏 / 细腻情感流 / 悬疑紧张 / 古风雅致 / 幽默轻松 / 硬核写实,提示词逐字对齐原版 `NOVEL_STYLES`)+「自定义…」展开文本框。
- 文风改为**项目级**存 `dramas.novel_style`(`get_novel_style(drama_id)` 优先,回落全局设置再回落默认),此前只写全局 app_settings。
- 制作页正文工具条同步换成预设下拉 + 自定义输入框,失焦即存。
- **题材确实有用**:原先只进封面提示词;现已进入 `novel._novel_settings_ctx`(书名/题材/简介/写法文风/视觉风格/总纲/世界观/合约/分卷)供章节计划与角色设计读取,
  并注入 `extractor` 的资产提取提示词(对齐原版「题材帮助 AI 匹配场景/道具/语言风格」)。
### 4. 制作页侧栏对齐原版 episode.vue
- 侧栏重写:三段环节(**剧本 / 制作 / 导出**)+ 环节状态(**✓ 已完成 / ◐ 进行中带「进行中」标签 / · 未开始**),状态判定 `sectionState` 同原版;
  项目类型不支持的整段自动隐藏(小说项目隐制作段、宣传/同款复制隐漫画段)。
- 底部对齐原版:「收起/展开」折叠(44px 图标态)、**四段进度跑马灯**(剧本/资产/视漫/漫画,点击跳转、已完成填色)、「⟳ 刷新数据」。
- `mainStageDone` 同口径:剧本有内容 / 资产全有图 / 分镜全有视频 / 漫画格全有图,驱动进度条与环节勾选。
- 主题新增 `SIDEBAR_QSS_LIGHT/DARK`,用 objectName 承载侧栏配色,亮暗两套一致,不写死颜色。

## 2026-10-09(第 26 轮:界面视觉对齐参考项目)
> 用户要求:「参考对齐的项目。全都要实现。包括界面。我看了一下很多界面不一样。」「比如 视漫制作 分镜 漫画 都要跟对齐项目一样」。
> 本轮只动**呈现层**,不动生成链路;所有文案取自参考项目 zh.json,所有色值走 theme.py 的 objectName QSS(亮暗各一套)。
### 1. 新增 `ui/episode_cards.py`(纯呈现组件)
CoverBox(角标用 QGridLayout 同格叠放,实现「浮在图上」)、CharacterAssetCard / AssetCard / ComicAssetRow、
MetricPill / VideoTaskRow / RefCard、NarrationBox(草稿与已存值不同时才出现「还原 / 保存」)/ ComicPanelCard、
`SaveOnBlurEdit`(补 QPlainTextEdit 缺的 editingFinished)。
### 2. 视漫制作(资产)页 → 卡网格
- 工具条:胶囊页签(常规资产 / 漫画资产)+ 等宽计数标签 `{ready}/{total} 已就绪` + 右侧「重提角色/场景/道具 · 一键提取 · 图片模型 · 批量」,漫画模式只留「批量生成漫画风格图」。
- 三段区块(角色 / 场景 / 道具)+ 虚线「新增」;角色卡 250px 固定(16:9 立绘 + 形象角标 + 视图角标 + 主角/配角标 + 样貌/妆造 + 图绘/文绘/上传/换脸/变体);
  场景道具卡 198px 起(16:9 封面 + 名称 + 描述 + 光照 + 最终提示词 + 状态点/重绘/上传);道具为空时显示虚线提示块。
- 图片模型下拉与顶栏双向同步(`_active_image_config`),资产页选了就用它出图。
### 3. 分镜页 → 三栏工作台(对齐 .video-task-workbench)
- 左 252px:视频任务列表 + 「按镜头顺序 · N 个任务」+ 三枚**可点筛选胶囊**(生成中/完成/失败,再点取消)+ 行(56×32 预览 · #NN · 名称 · 状态/时长/场景 · 操作键)。
- 中:分镜描述 / 氛围 / **视频提示词**(主标签 + AI 生成)/ 旁白(合成配音 + 字数 + 时长);下方**参考素材**三页签(角色/场景/道具,带计数)与卡网格(可参考 / 未生成 / 未绑定,缺图给「去生成 →」)。
- 右 322px:播放器(16:9)+ 历史视频条 + 绑定参考图 + 参数卡(分镜时长 2–30 · 生成音频开关 · 场景标签芯片,回车添加)+ 生效参数条 + 全宽主行动键。
- 新增:单镜视频提示词 AI 重生成、旁白时长、场景标签、参考素材页签切换、绑定参考图区。
### 4. 漫画页 → 3:4 网格
工具条(漫画 + N 格 + N/M 已出图 + 画风下拉 + 生成分镜 + 批量出图 + 拼接长图);格卡为 3:4 竖版,#NN 角标浮在左上,空态居中「出图」,已有图右上「⟳ 重绘」;
正文依次为描述 / 台词(accent 左边框)/ 构图 / **旁白说明框**(虚线浅底 + 长提示 + 草稿脏检查)/ 失败行 / 出图提示词。
长条图拼接结果落 `video_merges(model='comic_stitch')` 并在页顶出预览卡。
### 5. 导出页 → 成片卡带 + 镜头素材网格
守卫空态(尚未准备就绪 + 前往剧本);成片列表为 260px 横向卡带(16:9 缩略 + 时间/时长 + 下载,点击弹预览);
镜头素材为 200px 网格(缩略 + #NN + 时长 + 勾选 + 描述 + 状态点,整卡点选),右侧「全选已生成 / 拼接所选 (N)」;
片头行(加入片头 + 片头名 + 编辑片头)是本页唯一的合并设置 —— 与参考项目一致,不引入分辨率/字幕/BGM。
### 6. 剧本两页
原文页与改写页都改为参考项目的 `.step-toolbar` 结构:左侧步骤指示器(01 原始内容 / 02 AI 改写)+ 字数统计 + 目标字数输入,
右侧操作按钮按参考项目顺序排;改写页正文三态(空态引导 / 改写中 / 编辑器)。
### 7. 任务队列 → 右侧抽屉(对齐 .task-drawer)
遮罩 + 560px 侧滑面板;头部「生成任务列表 / 按创建时间倒序 · N 个任务」+ 刷新/关闭;三枚统计胶囊;任务行含缩略/类型角标/
名称/provider·model·耗时·ID/错误(换行)/状态色。挂在窗口 `stack` 最上层,点遮罩关闭。
### 8. 项目启动台 / 项目详情页
- 启动台:「项目启动台」标题 + 副标题 + 三枚统计胶囊(N 个项目 / N 进行中 / N 种视觉风格)+ 新建项目;
  工具条为 240px 圆角搜索 + 四枚状态胶囊(全部/待开始/进行中/已完成)+ 132px 排序;卡片 260×244,
  2.1:1 封面(首字母兜底 + 画幅角标 + 状态徽标 + ⋯ 菜单)+ 标题 + 创作目标/仿写/风格标签 + 「N 角色 · N 场景 · N 集」+ 相对时间。
- 详情页:头部收进 `.page-head.card`(返回圆钮 + 标题 + 风格标签 + 仿写标 + N 角色/场景/集 + 项目设置/宣传文案/整书导入/添加集);
  集卡 360px 网格(EP 序号块 + 可改名标题 + **五段进度条** 小说正文/剧本/资产/分镜/成片 + 字数/时长/已录入/已合成/时间 + 状态徽标
  + 分辨率/删除/进入制作),网格末尾放「添加第 N 集」虚线占位卡;列数按视口宽度重排(resize 时重排)。
### 9. 主题
- 新增 `ASSET_QSS_LIGHT/DARK`(~150 行),覆盖资产卡/任务行/播放器/参数卡/漫画格/旁白框;
  组件里不再写死颜色(原先 `#f2f3f5` 之类的内联样式已全部迁到 QSS)。
- `apply_theme()` 现在**先设 QPalette 再挂 QSS** —— 修掉暗色下未设 background 的 QWidget 仍是浅灰的问题。
- 截图:docs/shots/ 下 9 页 × 亮/暗 = 18 张(`scripts/shot_all.py` 一键重出)。
### 验证
- 亮/暗两套主题 × 2 个项目 × 6 个步骤 × 资产模式切换 × 刷新 × 任务抽屉开关,全绿。
- 50+ 个被按钮引用的 handler 全部存在(补回 `_gen_chapter_title` / `_generate_one`)。

## 2026-10-09(第 27 轮:同步参考项目新增内容 —— Jev 状态门控 + 品牌色换代 + 片头叠加修复)
> 用户:「对齐的代码又加入了 jev 你参照」。参照参考项目新增提交:`f2b9e32`/`c048463`/`3da9563`(测试校准)、
> `45da431`/`8f013d4`/`4c7fddc`(拆分重构与修错)、`0d251f1`(片头模拟器抽组件)、
> **`d262ac1`(片头叠加透传修复)**、`9ee15f4`(5 款片头字体)。
### 1. Jev —— 第六类 AI 服务(TypeSafe AI System One)
Jev 不是生成式 provider,而是**结构化决策/判读端点** `POST /v1/systemone`。
question 三原语:`noul`(布尔/置信度)、`choice`(分类+概率分布)、`score`(序数评分)。
- **新增 `app/ai/jev_client.py`**(对齐参考项目 `backend/src/services/adapters/moderation/jev.ts`):
  - `decide()` **任何失败一律返回 None,绝不抛异常** —— 软建议器契约,热路径上 Jev 挂了必须 0 阻塞;
  - TTL 缓存(key = sha1(state+questions+model) 截断 24 位,默认 5 分钟);
  - 环境变量双命名兼容:`JEV_BASE_URL`/`JEV_API_URL`、`JEV_TIMEOUT_MS`(毫秒)/`JEV_TIMEOUT`(秒);
  - `ping()` 连接测试:与运行期同一条通路(`state:'ping'` + 一条 noul 问),一次验完鉴权/可达性/端点;
  - 附带 `provider_routing_questions()` 预制三问模板(参考项目保留的扩展点,当前无调用方)。
- **注册表**:`SERVICE_TYPES` 加 `"jev"`;预设 `TypeSafe AI · Jev` / `https://api.typesafe.ai` / `jev-latest`;
  `seed_jev_default()` 仅当环境变量有 `JEV_API_KEY` 时落一条启用配置(幂等)。
  **不进入 `readiness()/missing_services()`** —— Jev 是可选增强,缺它不能拦下任何生成。
- **设置页**:第 6 个服务类型页签 + 连接测试,描述「状态台账门控(TypeSafe AI):长篇连续性自动判读」。
### 2. 人物状态台账(新增 `app/pipeline/state_ledger.py`)
长篇跨章生成时人物年纪/功法/性格/财产/关系会无交代地跳变;前情摘要(叙事层)接不住结构化状态,
台账是「世界现在是什么状态」的**事实层**。三段:`novel_reviewer` 单次调用提取 → 白名单合并 → Jev 门控。
- 维度白名单:人物 `年纪/功法/性格/财产/外貌/位置`(关系走 `relations` 子对象)、世界 `时间线/主线进度`;
- `from == to` 的假变更过滤(模型常把「未变化」也报上来,如 位置:旅店→旅店);
- 正文 <200 字直接跳过;单章 changes ≤20 / world ≤6;`state_diffs` 保留最近 100 章;
- **Jev 门控两问**:`conflict`(noul,矛盾置信度)+ `magnitude`(score,微小/一般/重大);
  阈值 `JEV_LEDGER_MIN_CONFLICT`(默认 0.7);`verdict='conflict'` 时把
  `状态台账疑似矛盾(置信度 NN%):人物维度:旧→新` 追加进该集 `review_json.issues`(保留最近 12 条)
  —— **界面随既有审校问题自然展示,不另开入口**(与参考项目一致)。
- **软失败全链路**:未配置 → `skipped/unconfigured`;连不通 → 熔断(连续 2 次失败冷却 10 分钟,期间直接跳过);
  提取失败 → 跳过本章。**任何情况都不阻断批量写作主流程**。
- **闭环**:写作提示词与策划上下文都注入台账(`_novel_settings_ctx` + `write_chapter`),
  按 `updated_chapter` 取最近 10 个角色,防上下文膨胀;批量流水线每章写完后自动更新(失败只记不抛)。
- UI:原文页第二行加「🧾 状态台账」按钮(手动重跑单章),命中矛盾时提示去看审校。
### 3. 品牌色换代(对齐 `studio.css:33-48` 的 ChatFire 火焰橙)
`--accent`/`--action-primary` `#4b6ef5`(蓝)→ **`#f97316`**,hover `#ea580c`,press `#c2410c`;
危险色 `#ff3b30` → **`#dc2626`**;accent-bg 浅底 `#fdf0e6` / 暗底 `#2e2119`;暗色文字 `#fdba74`。
`theme.py` 两套 QSS + 9 个 UI 模块里的内联色值一并映射(全仓已无 `#4b6ef5`)。

### 4. 片头叠加修复(对齐 `d262ac1`)
原版修的是「叠加片头不生效」:`intro_card` 服务端默认 `true`,前端只传 `undefined` 时会被默认值顶开。
本项目导出页原先只有单一「加入片头」勾选,`intro_overlay` 永远是 `False`,叠加根本走不到。
- 导出页片头行拆成 **「片头标题卡」+「叠加文字」两个独立开关**,初值取自 `dramas.intro_card/intro_overlay`;
- 拼接时 **显式传 `intro_card` / `intro_overlay` 两个布尔**(不给 `None`),绕开服务端默认值;
- `_save_intro_state` 同时落 `intro_card` 与 `intro_overlay`。
- 验证:`build_intro_spec(card=False, overlay=True)` 现在能返回 `{card: False, overlay: True}`。
### 5. 片头字体补全
参考项目 `9ee15f4` 新增的 5 款里 `ZCOOLQingKeHuangYou-Regular.ttf` 本仓缺文件,已补入
`app/assets/fonts/`;`intro.FONT_DISPLAY_NAMES` 的 10 款现已全部有对应文件(逐个校验通过)。

### 验证
- 台账全链路实测(真实文本模型):提取 10 条变更 → 合并出台账(叶尘:年纪 十七岁 / 财产 / 位置 / 性格 / relations 叶小满;世界:时间线 / 主线进度);
  Jev 未配置时 `skipped/unconfigured`,台账照常维护。
- 门控四条路径用桩客户端逐一验证:矛盾 0.92 → `conflict` + 审校写入;0.3 → `ok`;
  不可达 → `skipped/jev-unreachable` 连续两次后熔断冷却开启;无变更 → `ok/no-changes` 短路。
- 台账注入写作上下文已确认(策划上下文行含完整台账 JSON)。
- 亮/暗两套主题 × 2 项目 × 6 步骤全绿;测试数据已从项目 4 清除。

## 2026-10-09(第 28 轮:继续同步参考项目 —— Jev 三处新用法 + 工作台体验四连修)
> 用户:「参考对齐的项目」「即 pydrama 里的功能跟 xiaoshuo 一样。同时界面了也要百分之百的复现」。
> 参考项目本轮新增 7 个提交,其中 3 个是接着台账/Jev 继续做的:`1efcccb` / `c8e7f06` / `04136eb`;
> 另有 `3cba4f3`(种子兼容)、`6e130de` / `5645e46` / `9dac0e7`(界面四连修)。
### 1. Jev 通用调用面(新增 `app/ai/jev_gate.py`,对齐 `services/jev-gate.ts`)
原先 `state_ledger.py` 自带一套「客户端解析 + 熔断」,现在抽成共用层,三个业务作用域各自持有独立熔断器:
- `get_jev_gate()`:设置页 jev 活跃配置优先 → 环境变量回退 → 都没有则 `client=None`(调用方跳过,业务照常);
  `JEV_ENABLED=0` 显式禁用一切 Jev 调用。
- `JevBreaker(scope)`:连续失败达阈值(默认 2)开闸冷却(默认 10 分钟),期间 `in_cooldown()`;
  成功一次即复位。作用域:`state-ledger` / `review-triage` / `video-costume` 互不影响。
### 2. 审校降噪(新增 `app/pipeline/jev_triage.py`,对齐 `services/jev-triage.ts`)
痛点:审校输出的 issues 真假混杂 —— 硬性矛盾 / OOC / 设定冲突值得修;风格意见、主观偏好、误报
不值得为它们跑一整轮修复重写(一次 agent 调用)。
- **一次 decide 覆盖全部问题**:问题编号做动态 question key(`sev_0`…`sev_n`,`score` 原语),
  0=可忽略 / 1=应修复 / 2=必须修复;单次上限 10 条,超出的按 1 保守处理。
- `review_chapter()` 解析完 issues 即打分,`severity` 随 `review_json` 持久化。
- **修复循环只修 severity ≥1 的**;全部判为可忽略时**跳过整轮修复重写**(省一次 agent 调用)。
- 软降级零风险:`JEV_TRIAGE=0` / 未配置 / 连不通(独立熔断)/ 解析失败 → 返回 `None`,
  调用方按「全部应修复」处理,与接入前行为完全一致。
- 实测(桩):3 条问题 → severity `[0,1,2]` → 只修后两条;1 次 decide 覆盖 3 条;
  12 条时只打分 10 条、其余补 1;不可达 2 次后熔断;`JEV_TRIAGE=0` 直接跳过。
### 3. 视频着装状态判读(对齐 `services/video-prompts.ts` 的 buildShotStateCostumeContext)
生成视频提示词时判断角色服装是否应已随剧情变化,**两层**:
1. **确定性层**:状态台账「外貌」有记录 → 直接注入「剧情当前着装」(台账是剧情推进后的权威状态);
2. **Jev 判读层**:台账无记录的角色,把本镜画面描述 + 角色基础形象发给 Jev(`noul`:本镜着装是否
   应已不同于基础形象 —— 中举/婚礼/上任/败落/季节更替),置信度 ≥ `JEV_COSTUME_MIN_CONFIDENCE`
   (默认 0.6)才注入,防误报污染提示词。
软失败:`JEV_COSTUME_CHECK=0` 关判读;未配置 / 连不通(独立熔断)只保留台账确定性注入。
与造型变体机制互补(变体=人工预设,本功能=剧情状态)。着装判读异常不阻断提示词生成。
### 4. 台账提取跟随选中文本模型(对齐 `04136eb`)
- `update_state_ledger()` 接受 `config_id` / `model`,批量流水线把顶栏选中的文本模型透传下去,
  与正文同一模型保持判断口径一致。
- **裸模型名反查**:只传模型名不传 config_id 时,框架会用「当前启用配置」的 provider/base_url 去请求
  该模型名 → 同名模型挂在别的网关时报 unknown model(原版实测 `deepseek-v4-pro` 配到 MiniMax 官方域报 2013)。
  新增 `resolve_text_config_id_for_model()`:在活跃 text 配置里找 model 列表含该名字的那条,
  让「选什么模型就跟什么配置配合」对任意新增模型自动成立。
### 5. 工作台体验四连修(对齐 `5645e46` / `6e130de` / `9dac0e7`)
- **拼接等待可视化**:拼接中的成片卡显示呼吸文字 + **已耗时秒数逐秒跳动**(1s 心跳,只改文本不重建列表,
  保住滚动位置);`拼接所选` 按钮防重入(在飞时置灰转圈);拼完自动刷新列表并**直接打开成片预览**。
  ⚠️ Qt QSS **不支持 `@keyframes`**,呼吸改用 0.65s 交替切 `pulse` 动态属性(整表 QSS 曾因此解析失败)。
- **剧集卡删除按钮**:纯灰图标 → 危险色「🗑 删除」文字按钮(`--action-danger` + `--action-danger-bg`),
  此前纯图标用最淡文字色几乎不可见。
- **资产卡**:角色名独占整行(此前与按钮同排,长名被挤到约 30px 宽后省略;现在折行而非截断),
  角色标签另起一行让位;场景 / 道具封面宽度改为随卡铺满(此前固定两列,单封面只占左半)。
- **AI 改写面板**:保存按钮加 **dirty 门控**(与库内内容一致时置灰)+ 落库 + toast 反馈
  (此前该编辑框无任何保存机制,手改内容会静默丢失)。
- **片头叠加预览塌陷修复**:预览按项目画幅比例定尺寸(比例值冒号必须转斜杠,否则非法值会让高度塌 0;
  16:9→439×247、9:16→146×260、1:1→260×260);叠加模式铺**分镜真实字段** `first_frame_image` /
  `composed_image` 作背景(storyboards 表没有 `image_url` 列,用错字段会让预览永远黑底)。

### 验证
- 审校降噪四条路径 + 台账门控 + 熔断 + `JEV_TRIAGE=0` 全部用桩客户端逐一验证通过。
- 亮 / 暗两套主题 × 2 项目 × 6 步骤 × 片头编辑器全绿;顺带修掉了 `@keyframes` 引发的整表 QSS 解析失败。

## 2026-10-09(第 29 轮:功能对齐 —— 补齐审计出的前两大缺口)
> 用户:「即 pydrama 里的功能跟 xiaoshuo 一样。同时界面了也要百分之百的复现」。
> 先做**后端功能差分审计**(参考 21 个路由文件 / 20 个 service / 17 个 adapter vs 本仓
> 18 个 pipeline / 8 个 ai 客户端),按价值排序补最前面的两项。
### 1. 平台级提示词质量守卫(新增 `app/ai/prompt_guards.ts` 的 Python 对应 `app/ai/prompt_guards.py`)
审计结论里**价值最高的缺口**——参考项目在生成服务层统一注入,不依赖 Agent 是否记得写,
覆盖全部入口(分镜帧/资产图/漫画格/小说插画、单集与批量视频),**对已存库的旧提示词同样生效**。
- **图片守卫**:手部五指 / 肢体完整性 / 表情克制 / 画面纯净(无字幕水印品牌真人脸)+ 人物构图;
- **视频守卫**:肢体完整性 + 表演克制(压尖叫嘶吼痛哭)+ 节奏(禁慢动作与长时间定格);
- **中英双语**:中文约束 + **英文负面 token**(Seedream/Gemini/Agnes 对英文负面词权重更高);
- **marker 幂等**:已含同类守卫则跳过 → 重试复用存储提示词不会重复追加;
- **空提示词不追加**:纯参考素材驱动的生成不凭空引入文本;
- **按人数自适应**:`people=1` 强调「恰好一人」,`people>1` 改为「恰好 N 人、不得增删」——
  否则双人格子会收到「只许一个人」的自相矛盾指令,模型可能随机删掉第二个角色;
  负面词在 `people>1` 时同步去掉 second person / multiple people,否则会把剧情需要的第二个角色禁掉;
- **逃生阀**:分镜 `video_prompt` 里显式写「情绪爆发」可覆盖表演守卫(与原版一致,已在提示词文档化)。
- 接入点:`image_client.generate_image(..., people=1)` 与 `video_client.generate_video()` 的**入口**,
  所有 provider 分支统一下发 `negative_prompt`;上游回 `negative_prompt is not supported` 时
  给出可读原因(剥离顶层/extra_body/深层的重试助手 `_strip_negative` 已就位)。
- 漫画格按 `comic_panel_characters` 绑定数加**人数硬前缀**(放在提示词最前,比末尾写约束更稳)。
### 2. 人物面孔文化片段(新增 `app/pipeline/ethnicity.py`)
`dramas.ethnicity` / `characters.ethnicity_override` 两列此前**建了但全仓无人读**。
三级解析:**角色覆盖 > 项目设置 > 按内容语言推断**(语言未知回落 east_asian),
英文片段幂等追加到风格串尾部;`db.style_prompt()` 增加 ethnicity / content_lang 参数,
comic / prompts_gen / 分镜等调用点已接线。
### 3. 分镜拆分落全字段 + 资产绑定(对齐 save_storyboards)
此前只落 6 列,导致 `refs.build_shot_reference_list` 拿不到任何绑定、参考注入是空的。
- 落库全字段:title/shot_type/angle/movement/location/time/description/result/atmosphere/
  image_prompt/video_prompt/bgm_prompt/sound_effect/scene_id/setting_tags/duration;
  `setting_tags` 为空时**从场景继承**(对齐 storyboard-tools.ts:300-310);
- 同步写 `storyboard_characters`(带 variant_id)与 `storyboard_props`,
  兼容「角色名数组」与「char_ids/prop_ids」两种返回形态;
- 按 `shot_number` **幂等 upsert**(重拆不丢已生成的视频/首帧/字幕);
- 重算 `episodes.duration = ceil(Σ分镜时长/60)`(新增列 + 迁移项)。
- `gen_video_prompts` 改为**只处理 video_prompt 为空的镜头**(对齐原版 filter by missing),
  风格前缀改走 `_style_for`(含面孔文化)。
- 实测:拆分 1 镜 → 落全字段 → 绑定到角色 id → `build_shot_reference_list` 返回 1 张参考图。
### 4. 顺带修掉的两个既有缺陷
- **`run_agent_json` 全部 Agent 400**:部分网关要求 messages 里出现 json 字样才肯用
  `response_format=json_object`,而 `workspace/prompts/*.md` 里的系统提示不一定含该词
  (实测 `storyboard_breaker` 的 md 就没有)。现在 `runner.run_agent_json` 一律把
  「请只输出 JSON」写进用户消息,`text_client` 保留兜底重试。
- **拆分返回形态兼容**:`{"storyboards":[…]}` / `{"boards":[…]}` / 裸数组 / `{"1":{…}}` 四种都收;
  模型实际返回的 `shot_size` 字段兼容到 `shot_type`。

### 验证
守卫幂等/空提示词/人数自适应/负面词随人数切换逐条断言通过;亮暗 × 2 项目 × 6 步骤全绿;测试数据已清。

### 审计出的其余缺口(未做,按价值排序)
1. **建项目自动生成首集**(auto-generate.ts):建项目时按 work_type 后台跑对应 Agent;
2. **视频请求契约校验**(routes/tasks.ts):Wan 3.0 的 `input.media[]/parameters{}` 形态与张数上限;
3. **跨 provider 回退链 + `retry_at` 时间戳跟随 + 轮询分档**(POLL_PROFILES);
4. **final-prompt 缓存 + 风格指纹失效 + buildVaryPrompt**(图生图编辑提示词构造);
5. **局部重绘 inpaint**(utils/inpaint.ts,340 行金字塔填充 + 擦除/还原 UI);
6. **存储用量卡**(routes/storage.ts,分桶统计 + 60s 缓存)、**视频海报帧**(t=0.5s/宽 640)、
   **上传体积与 MIME 白名单**、**上传缩略图**;
7. **变体表缺 tags / sort_order 列**(导致无法做子集最大命中与 tie-break);
8. **GLM 整段视频直传的 16384 token 余量与 40MB/120s 守卫**。

## 2026-10-09(第 30 轮:UI 差分审计 —— 修死代码 + 全局导航壳对齐)
> 接着做**前端差分审计**(参考 20 个 .vue 页面/组件 vs 本仓 app/ui/),按影响排序处理。
### 1. 修一个真缺陷:两个工具页是死代码
审计发现 `FaceSwapPage`(`face_swap_page.py`)与 `MergerToolPage`(`merger_tool_page.py`)
**从未被挂进 MainWindow 的 stack,也没有任何入口** —— 参考项目的 `/tools/face-swap` 路由在本仓完全没有对应物,
两个类写了却永远打不开。现已:
- 实例化并加入 `MainWindow.stack`(共 6 页);
- 顶栏分段导航新增「换脸」「合并」两个入口,`_goto()` 按 key 切页并同步胶囊选中态。
### 2. 全局导航壳(对齐 layouts/default.vue)
- **顶栏跟随主题**:此前写死 `#202126` 深色,亮色模式下也是黑的;改为 `QWidget#headerBar` + 亮暗两套 QSS。
- **品牌块**:圆角渐变方块 + 「易」(`#brandMark`)+ 双行字标「易好网文短剧 / Yihao Shorts」
  (此前只有一张 logo.png 或一个裸「易」字)。
- **分段胶囊导航**:`#navSegWrap` 轨道 + `#navSeg` 选中态(白底/深色底 + 加粗),此前是无选中态的平铺文字按钮。
- 主题 / 设置 / 语言三个按钮改为 32px 圆形图标键(`#headerIconBtn`),hover 有底色。
- `retranslate()` 里同步导航文案与选中态(切语言后胶囊不会错位)。
### 3. 存储用量卡(对齐 routes/storage.ts + utils/dirsize.ts)
新增 `app/core/storage.py`:分桶统计 db/images/videos/merged/comics/uploads/temp/other,
数据库文件(含 -wal/-shm)单独计数(不在目录遍历里),另报剩余可用空间;
**60 秒缓存 + stale-while-revalidate**(过期先返回旧值再后台重算)。
设置页存储页改成按桶列出 + 总量 + 剩余空间(此前只有一行 static 目录 MB 数)。
Windows 上 `os.statvfs` 不存在,改用 `shutil.disk_usage`。
### 4. 建项目自动生成首集(对齐 auto-generate.ts)
新增 `app/pipeline/auto_generate.py`:按 work_type 后台跑对应 Agent 并落库 ——
novel→`episodes.content`、drama→`episodes.script_content`、comic→`comic_panels`(JSON 数组,
解析失败退回 content)、promotion→`episodes.content`;clone 不生成(分镜来自参考视频拆解)。
建项目时自动触发(文本服务未就绪则跳过),走 sys_task 记录,失败只记任务不阻断建项目。
### 验证
亮/暗 × 2 项目 × 6 步骤 × 3 个导航页 × 片头编辑器全绿。

### UI 审计出的其余缺口(未做,按影响排序)
1. **i18n 覆盖**:`app/ui/` 下仍有约 700 处硬编码中文,15 语言只覆盖了一部分界面文案 —— 这是目前最大的
   用户可见差距(切语言后大量界面仍是中文)。
2. **ConfirmDialog 抽象**:仍是裸 `QMessageBox.question`,没有参考项目的图标变体 / loading 态 / Enter 语义。
3. **BaseSelect / MentionTextarea**:可搜索分组下拉、`@角色名` 自动补全(参考项目的
   `@`-token 是提示词的承重结构,本仓只能手打)。
4. **ModelSelect 语义**:参考用 `provider/model` 复合键,同一配置下的多个模型可选;本仓按 config_id 平铺。
5. **设置页 AI 配置列表 / 风格预设列表**:仍是单行文本 `QListWidget`,缺启用开关、模型 chips、逐行测试、删除、空态。
6. **换脸工具页**:参考是 ①源人脸 → ②角色模板 → ③结果 的三段式向导,含分辨率告警、剪贴板/URL 粘贴、
   逐图重绘、灯箱、全部下载、一键应用/还原;本仓仍是平铺卡网格。
7. **无新手引导**(`useTour.ts`):首启引导与帮助按钮都没有(`tours_seen` 有种子行但无人读)。
8. **无列表骨架屏**、卡片不支持键盘激活、无全局 Esc 优先级链、无 Ctrl+Q 智能质检弹层、无查找替换条。
9. **暗色调色板**仍是中性灰,参考是带蓝灰调的 `#0b0f16 / #131a24`;按钮圆角 6px vs 参考 `--radius-pill`;
   无阴影/hover 填充/focus 环/品牌渐变/间距刻度。

## 2026-10-09(第 31 轮:UI 文案国际化补齐第一批)
> UI 审计指出:参考项目 15 种语言 × 约 1500 键全覆盖,而本仓 `app/ui/` 下有 623 处硬编码中文字面量,
> 切语言后大量界面仍是中文 —— 这是目前最大的用户可见差距。本轮先补基础设施 + 最高频的一批。
### 1. 新增 `app/core/ui_strings.py`(第二层文案词典)
- 15 语言全覆盖,`S` 词典每条固定 15 个值,顺序为 `zh en ja ko ar hi id th tr vi fr de es pt it`;
- `i18n.tr()` 查询链改为:当前语言主词典 → 英文主词典 → **当前语言补充词典** → 英文补充词典
  → zh 主词典 → key;
- 加了一条自检:所有条目必须恰好 15 个非空字符串(已跑通,无残缺条目)。
### 2. 已收进词典并接线的高频文案
通用(保存/取消/应用/删除/处理中/加载中/关闭/新增/编辑/刷新/下载/全部应用/点击查看大图/起草中);
项目设置(简介/题材/外貌/世界观/总纲/故事合约/章节计划/主要角色/角色定位/地点/时间/描述/
创意描述/服务/风格/自定义…);状态(待开始/进行中/已完成/失败/审校 N 项);
画幅(16:9 横屏 / 9:16 竖屏 / 1:1 方形 / 自适应);面孔文化(东亚/中东/西方/南亚/拉美/非洲/混合);
台账(状态台账/伏笔台账);分镜工作台(视频任务列表/视频提示词/绑定参考图/画风/拼接长图/整章处理);
工具页导航(换脸/合并);存储(存储/剩余可用/数据目录)。
### 3. 顺带修一个隐性缺陷:模块级常量在导入时求值导致切语言不生效
`STATUS_META` 原本是 `{status: (中文标签, 颜色)}`,**在 import 时求值一次**,
即使标签换成了 `tr(...)` 也只会显示导入那一刻的语言。已拆成
`STATUS_META`(只留颜色)+ `STATUS_KEY`(标签键)+ `status_label()` 函数,调用点改为运行时求值。
实测 zh/en/ja/ko/fr 切换后状态标签实时跟着变。

### 验证
亮/暗 × 7 种语言 × 2 项目 × 6 步骤 × 3 个导航页 × 片头编辑器 / 项目设置 全绿。

### 剩余(按审计排序)
`app/ui/` 里还有约 550 处硬编码中文待收词典(episode_page 99、novel_dialogs 60、
asset_dialogs 剩余约 55、project_page 剩余约 45、settings_dialog 49、book_import_dialog 36、
new_project_dialog 30、ai_edit_dialog 37 等)。`ui_strings.py` 的结构就是为此准备的,
后续按同一格式往 `S` 里加即可,不需要再改调用点。

## 2026-10-09(第 32 轮:修 bug + 视频契约校验与重试治理)
> 用户:「分析一下。建一个计划进行修改」→ 确认四轨并行:先修 bug、后端契约与重试、i18n 15 语言、
> 界面复刻(设置卡片 + 换脸向导)。本轮记录批次 0 与批次 1。

### 批次 0:修 4 个真 bug + 补迁移
- `face_swap_page`:done 回调里 `if err:` 判的是从 toast 导入的**函数**(恒为真),
  导致每次换脸成功都弹错误 → 改 `if error:`
- `face_swap_page`×2 / `character_face_swap_dialog`×1:`ok, msg = face_swap.health(...)`
  把 toast 导入的 `ok` **覆盖**掉 → 局部改名 `healthy, msg`
- `character_face_swap_dialog`:批量回调里 `str(e_)` 引用**未定义名**,批量失败直接 NameError
- `character_face_swap_dialog`:`tr("redraw")` 被当对话框标题,该键不存在
- 该弹窗的 `size_tip` 声明后**从未赋值**(分辨率告警是死的):实现三档
  —— <256px 硬失败(禁用执行键)/ <512px 警告 / 其余合格
- **迁移**:`character_variants` 补 `sort_order` / `comic_image_url` 两列;
  `tags` 列此前**没有任何写入方** → 变体弹窗新增「场景标签」输入,排序改
  `ORDER BY is_default DESC, sort_order ASC, id`(对齐 variant-resolution 的 tie-break)
- 设置页 3 处 QMessageBox 裸中文 → 收进 `ui_strings` 词典(15 语言)

### 批次 1:视频请求契约校验 + 错误分类 + retry_at 跟随
**新增 `app/ai/video_contract.py`**(纯函数、不碰网络,可用构造请求逐条断言):
- `normalize_video_request()`:兼容本仓扁平参数与官方 Wan 3.0 的 `input.media[] / parameters{}`;
  七种 media type;`first_frame/last_frame/file/link` 各至多 1 项
- `validate_video_request()`:上限表与规则顺序**逐条对齐** `routes/tasks.ts` ——
  aliyun 图片≤10/视频≤5/音频≤5/合计≤20、尾帧须配首帧、file 与 link 互斥、
  首尾帧不得与 reference_* 混用(**混用检查在合计检查之前**,与参考同序);
  通用 图片≤9/视频≤3/音频≤3、有音频须配图或视频;prompt 空且无素材直接拒
- `is_fallbackable_error()`:限流/队列满/网关抖动 → 可恢复;4xx(缺 Key/参数错/模型下线)
  → 不可回退,`is_permanent_error()` 另判 4xx 快速失败(408/409/425/429 除外)
- `parse_retry_at()` / `retry_at_wait_seconds()`:解析上游
  `Please try again after <datetime>`(兼容 `UTC`/`Z`/无后缀),睡到那一刻,
  **最多跟 2 次、单次 ≤24h、额外 +5s 余量**,超限直接放弃不挂死
- `fallback_enabled()`:跨 provider 回退**默认关**(参考项目已被用户策略压成单点,
  不悄悄切模型掩盖真问题),需要时用 `YIHAO_VIDEO_FALLBACK=1` 打开

**接入点**:`generate_video()` 分发前调 `check_request()`,超限/空 prompt 在**请求发出前**就给出
可读本地原因;分发体拆成 `_dispatch_once()` + `_generate_with_retry()` 包装。

**顺带修第三处死代码**:限流治理的 `_is_rate_limited` / `backoff_seconds` /
`pass_video_create_gate` **此前定义了但全仓无人调用**。其中串行门实现是
「造一个线程返回给调用方 join」,而线程**从未 start** —— 门形同虚设。
重写为 `acquire_video_create_gate()`:阻塞到距上次提交满 15 秒再放行,并删除旧函数。
`_generate_with_retry` 现在真的生效:4xx 一次即失败、限流按长预算退避、
retry_at 直接跟随、每次提交都过串行门。

**验证**:契约校验 12 条规则(含边界:20 项放行 / 21 项拒绝)、
错误分类 9 种 HTTP 码、retry_at 5 种写法 + 2 次上限 + 24h 上限,全部断言通过;
重试行为用桩函数验证 4xx 一次失败 / 503 后成功 / 持续 503 预算耗尽 / retry_at 跟随;
串行门 3 线程并发提交间隔实测均 ≥300ms。亮暗 × 2 项目 × 6 步骤全绿。

### 批次 3:设置页 AI 配置列表 → 卡片行
此前 `_fill_services()` 用一个 f-string 把整条配置拼成单行文本塞进 `QListWidget`,
无开关、无删除、无逐行测试,只能双击编辑。改为每配置一张 `ServiceCard`:
- 供应商标识徽章(按 provider 稳定配色)+ 名称 + 「有 Key / 无 Key」标 + 「默认」标 + 「已停用」标 + 优先级
- **模型 chips**:首位 ★ 橙色为当前默认,点其他 chip 即把它置为默认并写库(复用既有 `models` 列)
- **启用/停用开关**(走 `registry.update_config(is_active=…)`)
- **逐行测试**:复用 `TESTERS` 字典(含新增的 `jev`),盲文等待态
- 编辑 / 删除(删除带确认)
- 每类服务一个空态提示;容器由 `QListWidget` 换成滚动卡片区

### 批次 4:换脸工具页 → ①源人脸 / ②角色模板图 / ③结果 三段式向导
原页是「头部 + 一排按钮 + 单行不换行的卡片条」,连分段都没有。改为对齐
`views/tools/face-swap.vue` + `components/FaceSwapPanel.vue`:
- **① 源人脸**:上传 / 剪贴板粘贴(image mime,退化到路径·URL)/ URL 取回 / 从其他角色形象选;
  分辨率三档告警(<256 硬失败并禁用执行键 / <512 警告 / 合格),点击预览灯箱
- **② 角色模板图**:角色选择器 → 载入**基础形象 + 全部造型变体**(逐张保持原比例),
  可追加任意本地图片;每张可移除
- **③ 结果**:独立结果区 + 逐张 ok/失败角标 + 进度条
- 引擎下拉**合并 faceswap 与 image 两类服务**(未配置时给占位项并禁用执行键),
  风格下拉 + 自由提示词(拼在风格描述之后)
- 逐张重绘 / 灯箱 / 全部下载 / 全部应用(有变体的写变体)/ 恢复原貌
- 上次选择(provider / 风格 / 提示词 / 角色)存 `app_settings`,避免按优先级排序把用户静默切到风格化模型
- 角色路线的 `character_face_swap_dialog.py` **保持不动**

**过程中修掉一个 Qt 布局坑**:① 面板内没有任何 stretch 项时,QVBoxLayout 会把余量
在所有子件间平分,把标题挤到面板中部(②③ 因为有 stretch-1 的滚动区才正常)。
补尾部 `addStretch(1)` 后三段正确并排。

### 验证
- 设置卡片:切换启用开关(is_active 落库)、点 chip 设默认模型(model + models 首位落库)实测通过;
  6 类服务渲染卡片数正确、空态正确
- 换脸向导:引擎下拉列出两类服务并标注来源;选中角色载入模板成功;
  源脸分辨率 800/400/200 三档提示与按钮态实测正确
- 亮暗 × 2 项目 × 6 步骤 × 3 导航页 × 变体/换脸弹窗 × 设置页 全绿

## 2026-10-09(第 33 轮:创意描述解锁规则 + 集列表重复卡片修复)
### 1. 创意描述:可改,生成真实文字后才锁
- **原判定**是「项目里存在第 1 集就锁」,而新建项目必定会建一个空的第 1 集 →
  创意描述从创建那一刻就永远改不了,与需求正好相反。
- **新判定** `_has_generated_content(drama_id)`:任一集有正文 `content`、
  或有剧本 `script_content`、或有漫画格带描述/对白 → 锁;都没有(仅空壳集)→ 可改,
  「不需要创意描述」勾选也仍可切换。
- 提示文案跟着改并收进 `ui_strings`(15 语言):
  锁定 →「已按这份创意生成过正文,改它会让后续章节与既有正文对不上;如需调整请新建项目」
  未锁 →「…生成出正文后自动锁定」
- 顺带修掉 `style_edit.text()` → `toPlainText()`(`SaveOnBlurEdit` 是 QPlainTextEdit),
  该路径只在「打开策划与设定」触发,前面的回归没覆盖,实际启动才暴露。
- 验证四场景:空壳项目可编辑 / 写正文后锁定 / 只写 script_content 也锁 / 只有漫画格也锁。

### 2. 集列表出现两张「添加第 N 集」
- 根因:`reload()` 里每次新建一个嵌套 `QGridLayout` 塞进 `ep_lay`,而清空时
  `ep_lay.takeAt()` 取到的是**嵌套布局**(`item.widget()` 为 None),
  取不到里面的卡片 —— 卡片早已被重新挂到父控件上,旧卡片留在界面上,
  表现为多出一张重复的「添加第 N 集」。`addStretch(1)` 同样每次累积。
- 修复:网格布局与 stretch 改为 `__init__` 里**常驻创建一次**,`reload()` 只清 `ep_grid`;
  清理时先 `setParent(None)` 立即摘除(此处 `deleteLater()` 不生效),再 `deleteLater()`。
- 验证:连续 6 次 reload 后「添加第 N 集」对象数与可见数均为 1,`ep_grid` 条目恒为 2。

## 2026-10-09(第 34 轮:小说设定入口上移 + 写作闸门接上 + i18n 查询顺序修正)
### 1. 「小说设定」入口从单集页移到项目详情页头部
- 原入口在制作台原文页第二行,要 制作 → 第 N 集 → 原文 才找得到;策划是项目级的事。
- 现放在项目详情页头部:**项目设置 / 宣传文案 / 小说设定 / 整书导入**,
  仅小说项目显示。pydrama 与参考项目 `E:\xiaoshuo` 两边都改(commit `96add89`):
  detail.vue 加按钮跳 `/drama/{id}/episode/1?wizard=1`,episode.vue 的 `maybeShowNovelWizard`
  识别 `?wizard=1` 后无视「是否已有总纲」直接打开,并移除单集页工具条里的原按钮。

### 2. 写作闸门:之前形同虚设
- `assert_novel_ready()` **写了但全仓没有任何调用点**;UI 侧只把按钮置灰,
  换个入口(批量面板 / 程序化调用)就能绕过。实测 `check_novel_redlines()` 返回缺步骤但从不抛错。
- 现在:
  - pipeline 层 `write_chapter()` / `batch_write_chapters()` 入口调 `_enforce_novel_gate()`
    (仅 novel 项目适用,其它创作目标不受这条红线约束);
  - UI 层 `_batch_novel()` / `_run_batch()` 补查并提示。
- 参考项目那边的闸门本来就是有的(`doGenNovel` 与批量生成都检查 `missing` 并 toast),
  这次只是把 pydrama 对齐到同一语义。

### 3. i18n 查询顺序修正(批次 2 的前提)
主词典是用中文基线 `Z` 铺满的,**未翻译的键在每张语言表里都是同一个中文字面量**。
原来的 `tr()` 只看「当前语言表有没有这个键」,于是切到任何语言都会拿到中文
(实测英文下 `save` / `close` / `novel_settings` 等 153 个键全是中文)。
改为:当前语言表的值**与中文基线相同即视为未翻译**,优先取补充词典 `ui_strings`(15 语言齐全)。
实测 `save` / `close` / `novel_settings` / `tasks` 等在 en/ja/ko/fr 下已正常翻译。

### 4. 入口不再限定小说项目
「小说设定」按钮一开始加了 `v-if work_type=='novel'`,短剧/漫画项目在详情页头部就看不到入口。
策划与设定(总纲 / 世界观 / 故事合约 / 卷战略 / 章节计划 / 主要角色)对各类创作目标都有用,改为常驻。
参考项目同步去掉 `v-if="isNovel"`(commit `3e2c7c0`)。

## 2026-10-09(第 35 轮:AI 起草空结果修复 + 生成顺序显式化 + 闸门简介读错字段)
> 用户反馈:「AI 起草没有看到结果」「其它的类似效果都要试一下」「生成顺序有先后吗?」
### 1. AI 起草空结果的根因:提示词是给「带工具的 Agent」写的
`workspace/prompts/novel_planner.md`(以及 comic_board / extractor / novel_writer /
prompt_generator / script_rewriter / storyboard_breaker)照搬自 Mastra 版本,
里面写着「**只输出工具调用,不要输出规划文本**」「调用 save_novel_settings 保存」
「题材/简介由 read_novel_context 提供」。
本仓 `runner` 是**单次调用、没有工具**,于是模型照着输出工具调用文本:
实测「总纲」起草返回的是 `<tool_call> read_novel_context {...}` / `save_novel_settings {...}`,
既没有正文,也没落库,`_reload_tabs()` 再读回来自然是空的。

修法:
- `runner.run_agent()` 增加 `system=` 覆盖参数(默认行为不变);
- 新增 `novel.draft_section(drama_id, key)`:把上下文**直接内联**进提示词、要求模型
  **直接返回内容**,由本函数解析并写库 —— 用本仓的方式替代那两个工具;
- `_draft_system()` 给起草配**无工具**系统提示;
- `_strip_tool_calls()` 兜底剥掉 `<tool_call>` 片段,并尝试抢救其中的 `content`。
- 四个板块按 **总纲 → 世界观 → 故事合约 → 分卷战略** 实测全部产出:
  1386 / 1034 / 886 / 182 字,世界观与故事合约同时写进 `novel_meta.world` / `.contract`
  结构化字段(pov=first、tones=['轻松吐槽','现实经营']、era/location 齐),写作门控读得到。

### 2. 生成顺序显式化
顺序同参考项目向导(`NOVEL_REQUIRED_STEPS = [1,2,3,4,5,7]`):
**项目设定 → 总纲 → 世界观 → 故事合约 → 分卷战略 → 章节计划 → 主要角色**。
- 按钮文案带步号:「✨ AI 起草」/「✨ AI 起草 第 2 步」…;
- `missing_prereq()` 按依赖链拦截:世界观缺总纲、故事合约缺总纲+世界观、分卷战略缺总纲,
  未满足时提示「请先生成「X」再起草 Y」而不是让 AI 白跑。

### 3. 闸门第 1 步读错字段(会永久卡死小说写作)
`check_novel_redlines()` 从 `novel_meta.intro` 读简介,但项目设置写的是 `metadata.intro`
——**两个不同的字段**,所以第 1 步「项目设定」永远判缺,小说项目将永远无法通过写作闸门。
已改为读 `metadata`(与 `_novel_settings_ctx` 一致)。修复后项目 1 的闸门从
「缺 1」变为「齐」。

## 2026-10-09(第 36 轮:AI 生成流式显示 + 思考/正文分离 + 封面修复)
> 用户:「生成时能不能用流的效果显示」「流式把思考过程打印出来了」「可以打印思考过程。
> 最后变为结果保存下来」「其它的类似也要进行类似修改」「生成封面没有成功」
### 1. 流式生成
- 新增 `ai/text_stream.py`:`chat_stream()` 走 OpenAI 兼容 SSE,逐块 yield;
  端点不接受 `stream` 时**自动回落成一次性请求**,调用方无需分支
  (实测当前文本服务 17 块 / 96 字 / 2.1s,流式可用)
- 新增 `ui/streaming.py`:`StreamWorker`(QThread + 信号跨线程投递)+ `stream_into()`
  把增量实时写进编辑器并保持滚到底
- `text_client` 抽出 `_build_body()`,chat 与 chat_stream 共用,避免两处参数漂移

### 2. 思考过程与最终结果分离
- `chat_stream` 改为 yield `(kind, text)`,kind ∈ {reasoning, content};
  思考走灰色斜体显示,**`StreamWorker.content` / `finished` 只给正式内容**
- `novel_dialogs._draft_section` 与 `_ai_chapters` 改走流式:思考实时显示但不落库,
  失败时清空编辑器(别把思考留在框里冒充结果)

### 3. 结果校验:模型把元思考写进 content 通道
分卷战略那次「生成完了」其实没生成 —— 模型把
「我们需要回答用户:只起草分卷战略这一块内容本身…输出格式 JSON…」写进了 content 通道,
被原样存成了 `novel_volume`。新增 `looks_like_meta_talk()` 识别这类「在讲怎么回答」的文本
(命中「我们需要/用户要求/需要直接输出/输出格式是」等特征),命中即拒绝并提示重试;
分卷战略另外强制要求返回分卷结构,纯散文不算数。

### 4. 封面生成失败
第 29 轮加的平台质量守卫会下发 `negative_prompt`,而 **Agnes 图像模型不支持该字段**,
返回 400。此前 `_raise_or_strip_negative` 只报错不重试 —— 这正是计划里预判的联动问题。
已实现 `_post_with_negative()`:上游回「不支持 negative_prompt」时**剥离后自动重试一次**
(顶层 / extra_body / 深层扫描三处),对齐原版 generation.ts 的做法。三个 provider 分支全部接入。
实测项目 4 封面生成成功,/static/images/cover_4.png 落盘 1.4MB。

### 5. 流式显示的两处副作用修复
- **字体变化**:`_formats()` 曾用 `QFont()` 取消斜体,Qt 把空字体族解析成手写体(script fallback),
  整段正文变成花体。改为从编辑器自身字体派生、只切 italic,思考与正文都只改颜色不改字体族。
- **保存不了**:流式期间编辑器 `setReadOnly(True)`,但「保存」按钮仍可点 —— 点了会把**思考过程的
  半截内容**写进 `novel_contract`。现在起草期间禁用该板块的保存按钮,成功/失败后恢复。
- 另修:`WaitingButton` 忙碌文案被截断(只剩「起」),补 `QSizePolicy` 让标签按内容撑开。
- 附带发现:合约起草的思考过程很长(实测 4771 字思考 + 1217 字正文),总耗时超过 1 分钟,
  期间界面上只有灰字在动、没有取消入口 —— 后续应加「停止生成」。

## 2026-10-09(第 37 轮:界面字体解析 + 用户可自选字体)
> 用户:「查看参考项目。里面有字体。取过来。」「用户可以自己设定整个项目的字体」
### 字体文件并不缺
比对两边目录:参考项目 `data/fonts/` 9 款片头字体(思源黑体粗 / 霞鹜文楷 / 马善政 / 站酷小薇 /
站酷快乐 / 站酷庆科黄油 / 龙藏行书 / 柳建毛草 / 之芒行楷)在本仓 `app/assets/fonts/` **全部已有**,
多一份 msyh.ttc 兜底。问题不在文件,在**它们被注册进了 Qt 字体库**。

### 根因:片头花体污染正文回退
`load_bundled_fonts()` 把这 9 款**片头标题卡**字体全注册进 QFontDatabase;而 QSS 里
`-apple-system` 在 Windows 上不存在,Qt 继续回退时就可能挑中其中的楷书/行书/毛笔体 ——
于是整段正文变成花体(流式显示里更明显,因为我当时还用了空 `QFont()`)。

修法:
- `TITLE_CARD_FONTS` 明确标出这 9 款只供片头用,不参与界面正文回退;
- 新增 `resolve_ui_family(preferred)`:按「用户偏好 → 系统候选列表」解析出一个**真实存在**
  的字体族名(实测解析到 `Microsoft YaHei UI`);
- `apply_theme()` 显式 `app.setFont()` 并把 QSS 的 `*` 规则替换成该具体族名,
  不再让 Qt 自由回退。

### 用户自选字体
设置 → 通用 新增「界面字体」下拉:跟随系统 + 9 款系统候选 + 本机已装全部字体(含 9 款片头字体,
用户也可拿它们当正文),选择即存 `ui_font` 并立即重贴主题生效。
文案 4 键 × 15 语言收进 `ui_strings`。

**验证**:解析到 `Microsoft YaHei UI`;下拉 18 项;切换后应用字体立即变更;
亮/暗 × 2 项目 × 3 导航页 × 策划弹窗 / 项目设置 全绿。

## 2026-10-09(第 38 轮:语言切换即时生效,不再要求重启)
> 用户:「切换语言为什么要重启才行?」「而这一个项目切换语言不用重启 E:\comPySide」
### 为什么以前要重启
所有文案都在**控件构造时**调一次 `tr()` 求值。切语言只走了 `retranslate()`,而它只覆盖顶栏导航
与窗口标题;页面内容永远是构建时的语言。参考项目那边是 Vue 响应式重渲染,所以能即时生效。

### 移植 comPySide 的机制
`E:\comPySide\src\compositor\i18n.py` + `app.py` 的做法:**监听器列表 + 整体重建界面**。
- `i18n.py`:新增 `_LISTENERS` / `on_change(fn)`,`set_language()` 在语言真的变了时通知所有监听器
  (单个监听器抛错不阻断其它);
- `main_window`:注册 `on_change(self._on_lang_changed)`;回调里用 `QTimer.singleShot(0, …)` 延到
  下一个事件循环再 `_rebuild_ui()` —— **必须延后**,否则会在按钮 clicked 派发中把正在派发信号的
  按钮一起销毁,Qt 卡在派发里出不来(comPySide 注释里记了这个坑);
- `_rebuild_ui()`:按当前栈页重建对应页面(ProjectsPage / ProjectPage / EpisodePage),
  用 `removeWidget` + `insertWidget(idx, …)` 就地替换(记录 `_cur_drama_id` / `_cur_episode_id` 以恢复);
  重建失败保留旧页并提示,绝不把窗口搞没;
- `_switch_language()` 去掉「请重启应用生效」弹窗,改为 `set_language()` 即时生效。

### 顺带修:模块级 `tr()` 会把语言定死
`projects_page.WT_LABEL` 是模块级字典,import 时求值一次,切语言后卡片上的创作目标标签永远不变。
改成 `wt_label()` 函数按需查(该项目卡片标签现已能跟随语言切换)。

### 实测:切换即时生效,但仍有覆盖缺口
中 → 英 → 日 往返重建全部通过,窗口标题、导航、卡片标签都跟着变。
但**页面里仍有一部分中文** —— 这不是切换机制的问题,是翻译覆盖问题:
`T['en']` 里 **161/357 条的值就是中文原文**(当初生成英文表时未翻译的直接照抄),
其中已由补充词典 `ui_strings.S` 覆盖 122 条,剩下的仍回落中文。
实测各语言回落中文的键数:英文 153、日文 208、韩文 149、法文 149。
这正是批次 2(i18n 15 语言全覆盖)要解决的。

## 2026-10-09(第 39 轮:i18n 覆盖第一批 29 键)
> 用户切到印地语后反馈「这里还没有统一」「语言不一样」——切换已即时生效,但一半文案仍是中文。
**实测基线**:`T['en']` 里 161/357 条的值就是中文原文(生成英文表时未翻译的直接照抄)。
14 种语言各缺 155 键(日文 214)。

本轮补齐 **29 键 × 15 语言**(通用动作、项目设置、资产/漫画/分镜空态与提示、AI 编辑与审校等),
落入 `ui_strings.S` 补充词典。

**覆盖进度**(仍显示中文的键数):英 159→130、日 214→213、韩/阿拉伯/印尼/土耳其/越南/法/德/西/葡/意 155→126、
印地/泰 155→127。

顺带说明两条机制:
- `tr()` 的查询链是「当前语言表 →(若值等于中文基线则视为未翻译)当前语言补充词典 → 英文表 → … → key」,
  这条「等于中文基线即未翻译」的判断是让补充词典能生效的前提;
- 补充词典每条固定 15 个值、顺序为 `zh en ja ko ar hi id th tr vi fr de es pt it`,错位会静默串语言,
  故每次追加后都跑长度自检(本轮发现并修掉 2 条因错位导致的串语言)。

## 2026-10-09(第 40 轮:三级翻译引擎 + 并发补翻,15 语言 100% 覆盖)
> 用户提供了一台自建翻译转发(fortuneteller.top,转发百度),要求:
> 用它翻译 + 把它配置进项目与参考项目 + Google 作为备选 + 找一个兜底。
### 1. 新增 `app/core/translate.py`(三级引擎依次降级)
1. **baidu-forward** —— `https://fortuneteller.top/api/translate`(转发百度翻译),主力,内置 key;
2. **google-gtx** —— `translate.googleapis.com/translate_a/single`,免 key(限流按 IP,切 Clash 节点可续);
3. **mymemory** —— MyMemory 免费端点(5000 词/天/IP),兜底。
统一入口 `translate(text, target, source)`,全失败抛 `TranslateError`。
> 注:deep-translator 库版本对 `LibreTranslateTranslator` 的导入名已过时,且其 Google 走的是
> 自己的探测路径、即便换了 IP 仍 429;改用与浏览器同源的 gtx 端点直连后立刻可用。

### 2. `tools/i18n_autofill.py` 改并发
- 第零步 seed:把主词典 `i18n.T` 里「值==中文原文」且未进 S 的键追加进 S;
- 判定需翻:`空` / `等于中文基准` / `非中日语言位含 CJK(串了)`(日文豁免 CJK 判定);
- **ThreadPool 12 线程**,每 24 条写盘,中断可续;`--workers` / `--dry-run` 可调。

### 3. 执行结果
- 第一轮 1612 个语言位,**1612 成功 / 0 失败 / 23.6 分钟**
- en/ja 补翻 522 位 → 496 成功;日文重翻 317 位 → 317 成功
- **最终 15 种语言 100% 覆盖**(各语言仅 3-6 个键与中文基准同形,如 `Jev` / `Base URL` /
  `API Key` / `System Prompt` / `Profile` / `{}s` —— 技术专名本就不该翻译)

### 4. 修正自己的检测口径
先前用「含 CJK 即未翻译」判定,把**日语正常使用的汉字**(如「エピソード追加」)误判成残留,
虚报 92 键缺口。正确判据是「与中文基准值相同」。

### 待办
翻译服务按要求只在本仓落地为 `app/core/translate.py`;**参考项目 `E:\xiaoshuo` 侧尚未接入**
(需要用 TS 写一份同构的 `translate.ts` 并挂到其构建脚本)。

## 第 41 轮(2026-10-10): 启动语言跟随系统 + 进入制作修复

- **启动语言判定**: `i18n.detect_system_language()`(QLocale 取 `zh_CN` 这类区域码的语种部分,
  比对 15 语种;不在表内/取不到 → 回退英文)。main.py 启动时:`ui_language_explicit=1`
  (用户手选过)尊重所存值;否则跟随系统。两个语言选择器(顶栏 ◎ + 设置页)落库时都会
  打上 explicit 标记,之后不再被系统语言盖掉。
- **进入制作无响应修复**: 第 40 轮 sweep 批量改写时 3 个文件(book_import_dialog/episode_cards/
  toast)漏注入 `tr` 导入,NameError 藏在方法体里 import 检查查不出,点击才炸;toast.py 还被
  插进括号续行中间劈断了 import。`_ensure_tr_import` 改用 AST 顶层 Import 节点的 end_lineno
  定位;新增静态检查(调了 tr 却没导入)确认全仓无漏网;无头实测进入制作→切语言重建→返回
  项目→返回列表全链路通过(`8329566`)。
- 翻译服务已同步参考项目:`backend/src/services/translate.ts` + `POST /api/v1/translate`
  (单条/批量,zod 校验),CRLF 保持,tsc 通过 —— 上一轮"待办"清账。

## 第 42 轮(2026-10-10): 视频合并加入片头名(对齐参考版) + 启动语言跟随系统

- **合并片头重写(`67fb3b9`)**:对照 `xiaoshuo/backend/src/services/ffmpeg-merge.ts` 的 doMergeInner
  单路径,把 `_merge_with_narration`/`_merge_with_intro` 合并为 `_merge_filtered`。旧版四缺陷:
  旁白 amix 整个缺失(输入加了没引用)+ 输入下标错位、无叠加时 [aout] 未定义必炸、画幅写死
  1280x720(竖屏拉变形)、无音轨镜头引用 [i:a] 报 no streams。现:多数派分辨率、has_audio 探测
  + anullsrc 补静音、旁白 aformat+atrim+apad+amix(normalize=0)、片头字号按真实画幅算。
  UI:`_save_intro_state` 漏存 intro_overlay、`_load_intro_state` 勾选态错乱、editingFinished
  重复连接,三处修。实测竖屏无音轨+旁白+卡片+叠加全开:1080x1920 保持、6.6s、白字居中。
- **启动语言跟随系统(`e11b6b9`)**:`detect_system_language()`(QLocale 语种码比对 15 语种,
  未知回退 en);`ui_language_explicit` 闸 —— 手选过的尊重所存值,没选过的跟随系统且不落库
  (改系统语言应用跟着变),两个选择器选定时打标。

## 第 43 轮(2026-10-10): f-string 模板化 —— 语言切换最后一批残留

用户报告项目卡「这里没有变为其它语言」(3D 漫剧/9 小时前/统计行)。根因:第 40 轮的改写
工具**故意跳过带插值的 f-string**,残留 159 处碎片;且项目卡风格名直接显示数据库预设名。

- `tools/i18n_sweep.py --fstrings`:f"第 {n} 章" → tr("第 {} 章").format(n) 整体模板化
  (逐片包会拼出 "Chapter 1 chapters",前缀后缀在不同语言语序不同,必须整句占位符模板);
  73 处转换、68 新模板键;排除 AI 提示词/Jev 提问/状态台账行;{x:.0%} 格式规格与跨行
  三引号(提示词块)自动跳过
- 两个工具 bug:①FormattedValue 源码跨度**含大括号本身**,参数被包成单元素集合
  .format({nc}) → str({14}) 显示 "{14}",AST 批量剥 103 处;②autofill _write 的键不走
  repr,含 \n 的模板键把 ui_strings.py 劈断,re.sub 替换串里 repr 的 \n 又被 re 二次
  解释(经典坑,须用 lambda)
- 风格预设名(19 个种子)入库 + 项目卡/新建项目下拉走 tr(),自建预设不在词典原样回退
- 机翻 1240 槽全成功;占位符体检修复 58 处不齐(重翻 36/英文回退 22,含 tr/th 把 {}
  翻成 {{} 的);ja「第 {} 章」语序手工修正
- 实测:en/ja 项目卡全英文/全日文(统计行/相对时间/风格名/类型标签),唯一中文是项目
  标题(用户内容);主窗口导航+双语重建回归通过

## 第 44 轮(2026-10-10): dict 值残留 —— 语言切换收尾的收尾

用户再报「还没有改完全」(制作台资产卡按钮/阶段标签/风格名)。根因:第 40 轮扫描为保护
dict 键跳过了**所有字典值**,ASSET_LABELS(图绘/文绘/上传/换脸/生成/重绘/主角/道具…)、
STAGE_CN(写正文/审校中…)、REF_PLACEHOLDER(角/景/具)整批漏网。

- ASSET_LABELS:卡片构造点传 `{k: tr(v) for k,v in ...}` 现场翻译视图(字典值即 tr 键)
- STAGE_CN/添加角色弹窗标题/插入模式标签/AI 改写 insert:消费点包 tr
- REF_PLACEHOLDER 单字占位改「当前语言种类名首字」(zh→角/景/具,en→C/S/P,ja→役/景/小)
- 漫画风格下拉(episode 2675/asset_dialogs 121)与项目页风格标签(project_page 695)补包 tr
- 30 新键入库:图绘/文绘用**参考项目官方译法**(Image Redraw/画像再描画/이미지 재묘화,
  对齐 xiaoshuo locales 的 imgRedraw/textRedraw),22 词 en/ja/ko 手工定稿,其余机翻 383 槽
- 审计方法论:无头遍历全页 QLabel/QPushButton/QComboBox/QTab/placeholder 收 CJK 文本,
  比截图+视觉模型可靠(视觉模型两读不一致,还把日文汉字誤报成中文残留);剩余 CJK 全为
  用户数据(人物外貌/场景光照/分镜内容/项目标题/服务配置名),属内容不翻
