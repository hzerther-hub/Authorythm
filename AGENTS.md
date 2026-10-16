# AGENTS.md — 易好短剧 · PySide6 版

AI 短剧/小说/漫画一站式桌面制作工具,对齐开源 Web 版 `ooooinfo/yihao_drama`。
Python 3.13 + PySide6 6.11 + SQLite(23 张表)。只依赖 PySide6 / requests / Pillow,
ffmpeg 走外部二进制(`config.find_ffmpeg()` 探测)。

## 运行与校验

```bash
pip install -r requirements.txt
python -m app.main          # 启动(GUI,需显示环境)
python -m pytest tests/ -q  # 32 个回归测试,约 1.5s
```

Git Bash 里**不要**用 `cmd //c start.bat` 启动(路径编码会炸,用 `start.ps1`)。

## 目录与分层

```
app/main.py        入口
app/core/          db(SQLite)/ config(路径·ffmpeg)/ i18n / theme(QSS)/ taskmgr(线程池)
app/agents/        runner(调 LLM + 抽 JSON)/ prompts(System Prompt 种子与注册表)
app/ai/            各供应商客户端: image_client / video_client / text_client / inpaint
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