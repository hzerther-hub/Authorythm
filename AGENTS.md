# AGENTS.md — 易好短剧 · PySide6 版

AI 短剧/小说/漫画一站式桌面制作工具,对齐开源 Web 版 `ooooinfo/yihao_drama`。
Python 3.13 + PySide6 6.11 + SQLite(23 张表)。只依赖 PySide6 / requests / Pillow,
ffmpeg 走外部二进制(`config.find_ffmpeg()` 探测)。

## 运行与校验

```bash
pip install -r requirements.txt           # 最小依赖(PySide6 / requests / Pillow / edge-tts / cryptography)
pip install -r requirements-dev.txt       # 开发期(rust + mypy + pytest + pyinstaller)
python -m app.main          # 启动(GUI,需显示环境)
python -m pytest tests/ -q  # 283 个回归测试,约 1 分钟
ruff check . && mypy        # lint + 类型检查(pyproject.toml 已配)
```

Git Bash 里**不要**用 `cmd //c start.bat` 启动(路径编码会炸,用 `start.ps1`)。

## 目录与分层

```
app/main.py        入口
app/core/          db(SQLite)/ config(路径·ffmpeg)/ i18n / theme(QSS)/ taskmgr(线程池)/
                   logging_setup(结构化日志)/ metrics(进程内计数)/ secrets(Fernet API Key 加密)
app/agents/        runner(调 LLM + 抽 JSON)/ prompts(System Prompt 种子与注册表)
app/ai/            各供应商客户端: image_client / video_client / text_client / inpaint /
                   registry(API Key 自动加密存取)
app/pipeline/      业务编排: storyboard / comic / novel / shot_tools / erase / extract
app/ui/            36 个 widget/page,最大的 episode_page.py ≈ 5.8k 行
workspace/prompts/ 150 个 Agent System Prompt(.md,15 语言 × 10 Agent),用户可改
workspace/skills/  技能文件
```

**依赖方向单向**:`ui → pipeline → ai → core`。`core` 不 import 上层;
`app/pipeline/comic.py:_style_for` 被 storyboard/prompts_gen 反向复用是有意的例外。

## 数据库

`app/core/db.py` 提供 `q / q1 / ex / exmany`,**参数一律用 `?` 占位**,不要拼字符串。
路径统一走 `config.media_url_to_path()` / `path_to_media_url()`,不要自己拼 `data/static/...`。
环境变量可覆盖:`YIHAO_DATA_DIR` / `SQLITE_PATH` / `STORAGE_PATH`。

**密钥一律不进版本库。** 本仓库是 **public**,任何提交过的 key 都等同公开泄露。
用户的 API Key 加密后存 `ai_service_configs.api_key`(SQLite,`data/` 已被 gitignore),
**由 `app/core/secrets.py` 自动加密**(Fernet + 机器指纹派生密钥,见上文「日志 / 指标 / 密钥」节)。
代码里只读不写 —— 业务侧统一从 `registry.get_config()` / `default_config()` 取明文。
需要某把 key 的地方一律「本机读」,别内置常量:

- 环境变量(如 `YIHAO_BAIDU_FORWARD_KEY`),或
- 设置表 `app_settings`(`db.get_setting(key)`,与 `photocraft_install_dir` 同机制)。

实测踩过:`app/core/translate.py` 硬编码过一把百度转发 key,随仓库推到 GitHub。
删掉代码里的常量**不等于**安全 —— 它还在 git 历史里,必须去服务端作废重发。
新接外部服务前先自查:`git grep -nIE "[\"'](sk-[A-Za-z0-9]{16,}|[0-9a-f]{40,})[\"']" -- '*.py'`。

## 线程模型(最容易踩)

`TASKMGR.submit(type, job, done)` 把 `job` 丢进 QThreadPool(上限 6)。

- **worker 线程里绝不能碰 Qt 控件**。QComboBox 这类要在**主线程**先 `.currentData()`
  快照成局部变量再传进 worker,否则报 `Internal C++ object already deleted`
  (本项目历史上最常见的崩溃源)。
- `done` 回调经 Qt queued 信号自动回到主线程,可以安全更新 UI;或用 `taskmgr.on_main(fn)`。
- 生图/生视频批量任务要**链式串行**(上一张完成再提下一张),并发会互相踩接口。

## 供应商能力差异

**Jev 只能读文本,不能读图。** `app/ai/jev_client.py` 只有一个端点
`POST /v1/systemone`,入参 `{state, questions}`,questions 三种原语:
`noul`(布尔+置信度)、`choice`(分类+概率分布)、`score`(序数评分)。它**不吐字**。
所以「让 Jev 判图有没有三头六手」这条路走不通 —— 实测把描述对调,
判定跟着描述走,与图像无关。识图判断要走多模态(`ai/text_replace_skill.py` 是现成例子)。

**Jev 判参考图能力不可信,别接进决策。** 实测在本项目真实配置上:
`qwen-image`(token-plan.cn-beijing.maas.aliyuncs.com)判 0.52~0.57「支持」、
`volcengine`(ark.cn-beijing.volces.com)判 0.54~0.61「支持」,
而这两个恰恰是**实测确认会静默丢参考图**的 provider —— 它看到知名大厂域名就臆断。
拆成「请求体有没有图像字段」这种可查证事实来问也没用(仍判 0.52/0.54)。
所以 `image_client.REFERENCE_CAPABLE_PROVIDERS` 白名单是**唯一真相源**;
`jev_ask.reference_capable()` 只作只读诊断线索(打印,不改变返回值)。
新接供应商:问一句拿方向 → **实测发张参考图看画面是否被约束** → 确认后写进白名单。
`tests/test_jev_ask.py::test_known_dropping_providers_are_never_capable` 守着这条。

**视频供应商路由只建议不自动切。** `video_client.suggest_video_config()` 走
choice 原语返回概率分布,但实测 jev 对两种完全不同的画面需求
(3D 卡通 vs 写实电影)给出几乎一样的分布(0.62 / 0.59),判别力有限。
所以:① 不自动改写 `config_id`,只弹提示让用户自己改下拉(换供应商=换钱);
② 前二名差距 <0.15 时标记 `low`,UI 如实说"Jev 也不确定"。
注意 choice 的分布字段名是 **`probabilities`** 不是 `choices`(实测踩过)。

**Jev 的任何新增用法都必须满足**:未配置 / 连不通 / 熔断 / `JEV_ENABLED=0`
/ 解析失败 → 一律返回 None 或原行为,**绝不抛异常打断业务**。
`JevBreaker` 按作用域熔断(连败 2 次冷却 10 分钟),所有调用包 `try/except`。

- **参考图**只有 `agnes / local / comfyui / sdwebui / fooocus` 真的发给模型
  (`image_client.supports_reference_images()`);qwen-image / volcengine 传了也丢,
  表现为「按参考图重绘」悄悄退化成纯文生图。
- **`video_prompt` / 分镜描述里不带画风**,视频模型会默认成通用动画/二次元风。
  出图与出视频都必须显式拼 `db.style_prompt(...)` 前缀。
- **PhotoCraft CLI**(`photocraft_bridge.py`)的 `run` 模式下**选区状态不在命令间传递**
  —— `select.rect` 返回 null,后续 `contentAwareFill` 的 window 与选区无关。
  去文字/选区类需求走 `TextReplaceSkill`(多模态 LLM 定位 + cv2/inpaint)。

## LLM 输出的解析纪律

推理型模型(minimax-M3 / glm)会先吐 `<think>...</think>` 再给 JSON。
**解析前必须先剥推理块**,否则 `json.loads` 必然失败。
参考实现:`agents/runner.extract_json()`、`photocraft_bridge._strip_reasoning()`。
同一个函数里往往还要剥 ```` ```json ```` 围栏。

## 小说线:规划模型 / 正文模型分设

小说生产分两档模型,配置键 `yihao.novel.plan_cfg` / `yihao.novel.prose_cfg`,
取值的 `plan_config_id()` / `prose_config_id()` 各自回退全局默认文本模型。
实测依据(同批章节计划,两模型各写第 1-3 章):
minimax-M3 6538 字(1988/2638/1912,无衰减);deepseek-v4-pro 5332 字
(2513/1640/1179,逐章掉 53%)。规划侧相反 —— deepseek 的结构化 JSON
(分卷/合约)明显更规整。详细说明见 `docs/小说-规划与正文模型分设.md`。

**新增小说入口时,必须在函数体内自己兜底**:

```python
def some_new_entry(..., config_id: int | None = None):
    config_id = config_id or plan_config_id()   # 规划侧
    config_id = config_id or prose_config_id()  # 正文侧
```

只写在 UI 层是不够的:调用点有十几处(UI/批量/程序化),任一处漏掉兜底就会
**静默退回全局默认模型**,界面上选了也没用且看不出异常。
`tests/test_split_models.py` 逐个入口断言源码里含对应兜底调用,新增入口会被逼着补。

坑:`novel_dialogs._draft_section` 曾经读 `self.text_combo`,该控件被 plan/prose
两个下拉取代后 `hasattr` 恒为 False → 永远传 `None`。改这类「控件被换掉」的
读取点前先确认属性还在,别信 `hasattr` 兜底会给出正确行为。

**测试不许碰真实库**。`data/yihao.sqlite3` 是用户数据,测试里凡是会落库的路径
(门控 / 提示词拼装 / 落库)全部 monkeypatch 打桩。真跑过一次 `write_chapter`
就把用户一章正文覆盖成了测试夹具内容。

**测试段的 id 会连带吃掉用户配置,两个坑叠在一起**(实测踩过):
1. 清理时 `DELETE ... WHERE provider=?` 不带 id 条件 → 连用户真的配置一起删;
   改成只删 `id>=TEST_ID_BASE`(95000)的自建行,并用 **autouse fixture** 统一
   屏蔽真实配置 —— 逐个用例手动插隔离必然漏,实测漏了 7 个。
2. 更隐蔽的:`registry.add_config` 用 `MAX(id)+1` 分配 id,而库里残留着大量
   上百万的测试垃圾行,于是**新配置被分到 96002,正好落进测试清理段**,
   跑一次测试就没了。用户真实配置要手动指定一个安全 id(本项目用 1001/1002)。
   排查手法:配置凭空消失时先查 `SELECT MAX(id) FROM ai_service_configs`。

## 角色形象图(三视图)提示词管线

四格规格 = 左起正面脸部特写 + 正面/90°侧面/背面三个等高全身,纯白背景。
三个历史坑,任何一个复发都是「应四格只出三格」或「背景彩色虚化」:

1. **风格前缀复读**:`prompts_gen.character_prompt` 把视觉风格前缀喂给 LLM,
   它会整段复读多份(实测 4 份)进 final_prompt,稀释角色描述与布局指令。
   `_dedupe_style_prefix` 在生成时去重;`asset_dialogs._gen_image` 对**存量**
   脏提示词再洗一遍。
2. **中英规格矛盾**:旧版英文布局块写 "no close-up portraits / only three
   full-body views",与中文规格「恰 4 个实例(1 特写 + 3 全身)」直接冲突,
   模型随机二选一 → 特写格被丢。系统提示词(agents/prompts.py 的
   prompt_generator)与兜底块都必须写**四格**规格;生成/生图两处正则剥除
   残留矛盾短语。
3. **人数守卫打架**:people=1 公共负面词禁「multiple people / duplicate
   character」,而三视图本质是同一人的多次出现 → 三视图类提示词
   (含 三视图/turnaround/character sheet)**必须 skip_guard**;白底压制走
   prompt_guards 的 CHARACTER_SHEET_PROMPT_SUFFIX/_NEGATIVE(共享常量,
   经 extra_negative 追加,不覆盖公用负面词)。漫画格/场景**不要**带这两样
   —— 那里需要环境。

## 漫画端到端生成(Layer 1+2,2026-10-18)

- **一键出整话**:`app.pipeline.comic_pipeline.generate_full_comic(episode_id, ...)` 是
  串行编排(拆格 → 出图 → 拼长图);**单格失败不中断**;走 `TASKMGR.submit("comic", ...)` 不阻塞主线程。
  - 不要并发 — 关键帧链式馈送(prev panel → next panel ref)依赖**按序**;
  - force=False 跳过已出图格;force=True 全部重出。
- **多角度 ref**:`comic.character_all_refs(character_id)` 返回该角色所有可用
  参考图(去重 + 限 3 张 + 存在性检查);`comic.panel_reference_images` 用它替换
  原单 ref,跨格一致性显著提升(StoryDiffusion / MangaNinja 风格「参考库」)。
  - **3 张上限**是「锁定外观」与「payload 不撑爆」的最佳折中(实测
    qwen-image / volcengine 传满 6 张就开始静默丢图)。
  - 新增变体走 `app/ui/variants_dialog.VariantsDialog`;角色卡「📐 漫画多角度」
    按钮是同一对话框的便捷入口(tooltip 强调「跨格一致性」)。
- **故事线入口**:`app.pipeline.novel.outline_to_script(outline, episode_id)` 把
  100-1000 字梗概扩成 4-8 场景的格式化剧本;失败不落库。
  - UI 在原始内容工具条「📚 梗概生漫画」按钮,弹多行输入框,两阶段 taskmgr
    任务(先扩剧本,再出整话),任一阶段失败都报 toast。
  - 校验:剧本必须含至少 1 个 `## S\d+\|...` 头,否则 RuntimeError。
- **新增 Agent** `comic_outline_writer`(16 语言提示词已落盘 `workspace/prompts/`);
  严格遵循梗概的人物与主线,**不**自创新角色/反转/额外事件。

## 文本编码

`app/core/encoding.py` 是乱码防护:`repair()` 只能救回 latin-1/cp1252 误读,
**GBK 误读不可逆**(字节已丢),必须抛 `MojibakeError` 中止,绝不静默落库。
改动涉及文本落库路径时先读该模块 docstring 与 `tests/test_encoding_guard.py`。

## i18n(16 语言)

- `app/core/i18n.py` 主表 `Z`(中文基准)+ 英文表;`app/core/ui_strings.py` 是 15 语言
  补充词典。新增 UI 文案:先在 `Z` 加中文基准键,再按 `zh en ja ko ar hi id th tr vi fr de es pt it`
  顺序在 `ui_strings.py` 补 15 元素 list。
- 界面语言与 AI 内容语言是**同一个开关**(`set_language`)。
- **缺翻译也能跑**:`tr()` 会回退英文再回退 key 本身,所以只加中文键不会崩,
  但界面会显示英文 —— 补全时别只改一处。

## Qt / UI 约定(本项目特有的坑)

- **新增一种页面必须同步三处**:`_PAGE_KINDS`(与 addWidget 顺序一一对应)、
  `_make_page`(语言切换的重建靠它,**没有分支 = 该页切语言后永远停在旧语言**)、
  `_goto` 的页面映射表(没有 = 按钮点了静默没反应)。三个坑各实战踩过一次
  (dashboard 漏 _goto、dashboard 漏 _PAGE_KINDS 首位、全部工具页漏 _make_page),
  `tests/test_nav_wiring.py` 与 `tests/test_lang_switch.py` 守着。

- **图标一律用 iconfont SVG**(`app/ui/icons.py` + `app/ui/icons.py:ALIAS`),
  **不要用 emoji 或几何字符**(▶ ⬇ 🗑 🩹 在 Windows 应用字体里没有字形,
  渲染成纯空白,实测颜色数=1)。用 `W.svg_icon_btn(name, tip, size)` /
  `W.icon_btn(QStyle.StandardPixmap.X, ...)`。
- **`QLabel.setMinimumWidth(0)` 不等于不撑宽**。`minimumSizeHint` 会向上传导撑大父控件:
  装了 pixmap 的 QLabel、长文本不换行的 QLabel、`QPushButton` 的文字宽,都会把卡片顶宽。
  窄卡片布局里给这些控件加 `setSizePolicy(QSizePolicy.Ignored, ...)`。
- **网格列数只有一处真相源**:`episode_page.ASSET_GRID_COLS`。改动列数时
  `_reload_assets` 的 `cols` 与构造期 `setColumnStretch` 循环范围都要跟着变,
  两处硬编码不同步就会出现「卡片挤左边 + 右侧大片空白」。
- 网格容器要 `addWidget(host, 0, Qt.AlignLeft)` —— 默认 `stretch=1` 会让它吃满父宽。
- 主题有三套(light/dark/slate),改样式要同步 `app/core/theme.py` 的三处 QSS。
- 改 `QSS` 后重启要清 `__pycache__`,否则会加载旧字节码。

## 日志 / 指标 / 密钥(三件套)

- **结构化日志**:`app/core/logging_setup.py` 提供 `setup_logging()` / `get_logger(name)`。
  业务模块用 `log = get_logger(__name__)`;**不要再用 `print(..., flush=True)` 作业务日志**
  (调试桩仍可用)。配置项:`app_settings.log_level` / `app_settings.log_to_stderr`。
  - JSON 落 `data/logs/pydrama.log`(10MB × 5 份轮转)。
  - 密钥脱敏:`_SecretsFilter` 自动替换 `sk-xxx` / `Bearer xxx` / `api_key=xxx` / 长 base64。
  - WARNING+ 可选挂到 toast(`logging_setup.attach_qt_toast_handler(toast_callable)`)。
- **指标**:`app/core/metrics.py` 极简实现 —— `incr(name)` / `observe(name, val)` /
  `snapshot()` / `flush_now()`。**埋点用 try/except 包住**(库内部 `incr/observe` 已自带,
  不要再套)。**关键**:snapshot 内部会取锁,flush_now 持锁调它 → 死锁,要走
  `_snapshot_locked()`。命名约定 `subsystem.event.unit`,见 `metrics.NAMING_HINT`。
- **API Key 加密**:`app/core/secrets.py` 提供 `encrypt` / `decrypt` / `ensure_*` /
  `migrate_unencrypted_keys`。库内对用户完全透明 —— 业务侧 `registry.get_config()` /
  `default_config()` 拿到的就是明文,落库前自动 `ensure_encrypted`。
  - **派生密钥 = 机器指纹 + salt**(PBKDF2 200k 轮)。换机器 / 换用户 / 删
    `data/.secret_salt` 都会让旧 key 解不出来 → 重新输入。
  - **不要在代码里硬编码 key**;AGENTS.md 顶部已说明自查命令。

## 并行会话协作(本项目常见冲突)

工作区可能有**并行会话**同时改同一批文件。改动前先 `git status` + 看文件 mtime,
发现不是你写的文件(如 `app/ai/text_replace_skill.py`)先确认来源再决定是否一起提交。
改完用 `git stash` 存快照,不要用 `git checkout stash@{N} -- <file>` 试探性恢复
(会把快照覆盖回工作区,等于没退)。

## 开发习惯

- 长流程分批后台跑时**参数要先在主线程快照**再进 worker(见「线程模型」)。
- 批量生图要**逐项刷新 UI**(已完成那一张立刻显示),不要等全部结束再 reload ——
  全表重建在 15 张图规模就要 1.5s+,用户看到的是「按了没反应」。
- 注释写「为什么这样」不写「这做了什么」,尤其要记下**踩过的坑**(附实测数据)。
- 调试输出用 `print(..., flush=True)`,不要留 `app.log` / `app.err.log` 进版本库。